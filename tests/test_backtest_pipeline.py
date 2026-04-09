"""Tests for scripts/backtest.py pipeline guards.

Pins regression-prone behavior introduced 2026-04-09:
- BacktestExposureManager uses candle_index (not wall-clock) for rate-limit windows.
  Bug it replaces: live ExposureManager called time.time(), so a batch backtest
  processing 8000 candles in <1s would exhaust the hourly trade limit after the
  4th trade and never reopen — silently capping every backtest at 4 trades.
- TuningParams.require_kb_match defaults to True. PA KB hallucination veto
  must be ON by default in the backtest. Empirical: in v1.4 backtest, 7 of 9
  no-kb-match trades lost.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from backtest import (  # noqa: E402
    BacktestExposureManager,
    BiasTracker,
    OpenPosition,
    TuningParams,
    _maybe_move_to_breakeven,
)

from domain.enums import Action, AlwaysIn, DayType, SetupType, SignalBarQuality  # noqa: E402
from domain.models import Candle as CandleModel  # noqa: E402
from domain.models import TradeSignal  # noqa: E402
from strategy.probabilities_kb import ProbabilitiesKB  # noqa: E402
from strategy.signal_parser import calculate_strategy_score_with_kb  # noqa: E402

# ============================================================
# BacktestExposureManager — uses candle index, not wall clock
# ============================================================


class TestBacktestExposureManager:
    def _mgr(self, bars_per_hour=4, max_per_hour=4, cooldown=2):
        return BacktestExposureManager(
            bars_per_hour=bars_per_hour,
            max_trades_per_hour=max_per_hour,
            cooldown_candles=cooldown,
        )

    def test_initial_state_allows_open(self):
        mgr = self._mgr()
        ok, _ = mgr.can_open_position(current_candle_index=10)
        assert ok is True

    def test_blocks_when_position_already_open(self):
        mgr = self._mgr()
        mgr.on_position_opened(10)
        ok, reason = mgr.can_open_position(11)
        assert ok is False
        assert "open" in reason.lower()

    def test_cooldown_blocks_then_releases(self):
        mgr = self._mgr(cooldown=3)
        mgr.on_position_opened(10)
        mgr.on_position_closed(12)
        # Cooldown is 3 candles after close → blocked at 13, 14
        ok, _ = mgr.can_open_position(13)
        assert ok is False
        ok, _ = mgr.can_open_position(14)
        assert ok is False
        ok, _ = mgr.can_open_position(15)
        assert ok is True

    def test_hourly_window_uses_candle_index_not_wall_clock(self):
        # The bug being pinned: a batch backtest processes thousands of candles
        # within milliseconds. If the rate limit window were wall-clock-based,
        # the 5th trade would be blocked forever. With candle index, the window
        # rolls forward as candles advance.
        import time

        mgr = self._mgr(bars_per_hour=4, max_per_hour=4, cooldown=0)

        # Open + close 4 trades back-to-back. Candle 0,1 / 2,3 / 4,5 / 6,7.
        for entry, exit_ in [(0, 1), (2, 3), (4, 5), (6, 7)]:
            ok, _ = mgr.can_open_position(entry)
            assert ok is True, f"trade at candle {entry} should be allowed"
            mgr.on_position_opened(entry)
            mgr.on_position_closed(exit_)

        # The hourly window now contains all 4 trades. At candle 8 the window
        # is candle 4..8 → trades at 4 and 6 still in window. So 2 trades in
        # window, max is 4 → still allowed.
        ok, _ = mgr.can_open_position(8)
        assert ok is True

        # Even with NO wall-clock delay, advancing the candle index pushes
        # old trades out of the window. After candle 100, all trades are old.
        ok, _ = mgr.can_open_position(100)
        assert ok is True

        # Sanity: this whole flow happens in the same wall-clock second.
        # The bug version of the manager would have failed by now because
        # time.time() barely moved.
        assert time.time() - time.time() < 0.5  # trivially true; documents intent

    def test_max_per_hour_window_enforced_within_window(self):
        # 4 trades inside a 4-candle window → next trade in same window blocked
        mgr = self._mgr(bars_per_hour=4, max_per_hour=4, cooldown=0)
        for i in range(4):
            mgr.on_position_opened(i)
            mgr.on_position_closed(i)
        # candle 4: window is candle 0..4 → 4 trades in window, blocked
        ok, reason = mgr.can_open_position(4)
        assert ok is False
        assert "trades" in reason.lower() or "max" in reason.lower()
        # candle 5: window is 1..5, drop trade at 0 → 3 in window, allowed
        ok, _ = mgr.can_open_position(5)
        assert ok is True

    def test_force_close_on_max_hold(self):
        mgr = self._mgr()
        mgr.on_position_opened(10)
        assert mgr.should_force_close(current_candle_index=15, max_hold=10) is False
        assert mgr.should_force_close(current_candle_index=20, max_hold=10) is True

    def test_force_close_returns_false_when_no_open_position(self):
        mgr = self._mgr()
        assert mgr.should_force_close(current_candle_index=100, max_hold=10) is False


# ============================================================
# TuningParams — kb_match veto is ON by default
# ============================================================


class TestTuningParamsKbVeto:
    def test_require_kb_match_default_true(self):
        t = TuningParams()
        assert t.require_kb_match is True, (
            "PA KB veto must be ON by default. If this fails, hallucinated "
            "setups will pass through to live trading. See backtest 2026-04-09."
        )

    def test_can_be_disabled_explicitly(self):
        t = TuningParams(require_kb_match=False)
        assert t.require_kb_match is False


# ============================================================
# PA KB lookup — fake setups must return no match
# ============================================================
#
# This is the underlying mechanism the veto relies on: if the LLM returns a
# setup that does not exist in pa_probabilities.json (or exists but
# doesn't match the current direction/regime), ProbabilitiesKB.lookup() returns
# None, calculate_strategy_score_with_kb yields enriched.match=None, and the
# backtest hits its `vetoes_no_kb` branch.


def _fake_signal(setup=SetupType.NONE, action=Action.COMPRA) -> TradeSignal:
    return TradeSignal(
        action=action,
        confidence=70,
        day_type=DayType.TREND_FROM_OPEN,
        always_in=AlwaysIn.SEMPRE_COMPRADO if action == Action.COMPRA else AlwaysIn.SEMPRE_VENDIDO,
        setup=setup,
        signal_bar_quality=SignalBarQuality.APROVADO,
        entry_price=67000.0,
        stop_loss=66600.0,
        take_profit=67800.0,
        decisive_layer=5,
        reasoning="test",
        timestamp=datetime.now(timezone.utc),
    )


class TestBiasTracker:
    """Anti-bias direcional. Empirical: v1.5 2880c had 12/12 long trades."""

    def test_warmup_allows_anything(self):
        bt = BiasTracker(window_size=5, max_ratio=0.8)
        # Window not full yet → all allowed regardless of bias
        bt.record("long")
        bt.record("long")
        bt.record("long")
        ok, _ = bt.can_take("long")
        assert ok is True
        ok, _ = bt.can_take("short")
        assert ok is True

    def test_full_window_all_long_blocks_long(self):
        bt = BiasTracker(window_size=5, max_ratio=0.8)
        for _ in range(5):
            bt.record("long")
        ok, reason = bt.can_take("long")
        assert ok is False
        assert "long" in reason
        # But shorts are still allowed (and welcome)
        ok, _ = bt.can_take("short")
        assert ok is True

    def test_max_ratio_threshold(self):
        # 4 longs / 1 short out of 5 = 80% → exactly at the cap, should block
        bt = BiasTracker(window_size=5, max_ratio=0.8)
        for d in ["long", "long", "long", "long", "short"]:
            bt.record(d)
        ok, _ = bt.can_take("long")
        assert ok is False
        ok, _ = bt.can_take("short")
        assert ok is True  # only 1 short → not biased toward short

    def test_just_below_max_ratio_allows(self):
        # 3 longs / 2 shorts = 60% → below 0.8, allowed
        bt = BiasTracker(window_size=5, max_ratio=0.8)
        for d in ["long", "long", "long", "short", "short"]:
            bt.record(d)
        ok, _ = bt.can_take("long")
        assert ok is True

    def test_window_rolls(self):
        # Window only keeps last N
        bt = BiasTracker(window_size=3, max_ratio=0.8)
        for _ in range(10):
            bt.record("long")
        # Window has 3 longs → blocks
        assert bt.can_take("long")[0] is False
        bt.record("short")  # window: long, long, short
        # 2 longs / 1 short = 67% → below 80%
        assert bt.can_take("long")[0] is True

    def test_invalid_direction_is_noop(self):
        bt = BiasTracker(window_size=5, max_ratio=0.8)
        for _ in range(5):
            bt.record("long")
        ok, reason = bt.can_take("hold")
        assert ok is True
        assert "non-directional" in reason
        bt.record("garbage")  # ignored
        assert len(bt.recent) == 5

    def test_disabled_by_default_in_tuning(self):
        # 2026-04-09 — bias_window default is 0 (disabled). Anti-bias is NOT
        # Nogran PA-native; the rule states "trade WITH the trend". The tracker is
        # available via --bias-window N but off by default.
        t = TuningParams()
        assert t.bias_window == 0


class TestBreakevenMove:
    """Stop ratchets to entry when price moves trigger_rr * risk in our favor."""

    def _long(self, entry=70000.0, stop=69300.0):
        # 1.0% stop distance — risk = 700
        return OpenPosition(
            side="long",
            entry_index=0,
            entry_time=0,
            entry_price=entry,
            stop_loss=stop,
            take_profit=entry + 1400.0,
            size=0.1,
            decision_score=80.0,
            mq=90, ss=80, ao=70, rs=80,
            original_stop_loss=stop,  # critical for test
        )

    def _short(self, entry=70000.0, stop=70700.0):
        return OpenPosition(
            side="short",
            entry_index=0,
            entry_time=0,
            entry_price=entry,
            stop_loss=stop,
            take_profit=entry - 1400.0,
            size=0.1,
            decision_score=80.0,
            mq=90, ss=80, ao=70, rs=80,
            original_stop_loss=stop,
        )

    def _candle(self, high, low):
        return CandleModel(timestamp=0, open=(high + low) / 2,
                           high=high, low=low,
                           close=(high + low) / 2, volume=1.0)

    def test_long_below_trigger_does_not_move(self):
        pos = self._long(entry=70000, stop=69300)  # risk 700, trigger at 70700
        # Bar high 70500 — only +500 of profit, below 1R = 700
        moved = _maybe_move_to_breakeven(pos, self._candle(high=70500, low=70200))
        assert moved is False
        assert pos.stop_loss == 69300
        assert pos.breakeven_moved is False

    def test_long_at_trigger_moves_stop_to_entry(self):
        pos = self._long(entry=70000, stop=69300)  # trigger 70700
        moved = _maybe_move_to_breakeven(pos, self._candle(high=70700, low=70400))
        assert moved is True
        # F1 fix (c): stop ratchets to entry + 0.1R buffer (= 70000 + 700*0.1 = 70070)
        assert pos.stop_loss == 70070.0
        assert pos.breakeven_moved is True

    def test_long_well_above_trigger_moves(self):
        pos = self._long(entry=70000, stop=69300)
        moved = _maybe_move_to_breakeven(pos, self._candle(high=71500, low=70900))
        assert moved is True
        # F1 fix (c): stop ratchets to entry + 0.1R buffer (long → above entry)
        assert pos.stop_loss == 70070.0

    def test_short_at_trigger_moves(self):
        pos = self._short(entry=70000, stop=70700)  # trigger 69300
        moved = _maybe_move_to_breakeven(pos, self._candle(high=69900, low=69300))
        assert moved is True
        # F1 fix (c): stop ratchets to entry - 0.1R buffer (short → below entry)
        assert pos.stop_loss == 69930.0

    def test_short_below_trigger_does_not_move(self):
        pos = self._short(entry=70000, stop=70700)
        moved = _maybe_move_to_breakeven(pos, self._candle(high=69900, low=69500))
        assert moved is False
        assert pos.stop_loss == 70700

    def test_idempotent_only_moves_once(self):
        pos = self._long(entry=70000, stop=69300)
        first = _maybe_move_to_breakeven(pos, self._candle(high=70800, low=70500))
        assert first is True
        second = _maybe_move_to_breakeven(pos, self._candle(high=72000, low=70900))
        assert second is False  # already moved
        # F1 fix (c): stop stays at entry + 0.1R buffer set by first move
        assert pos.stop_loss == 70070.0

    def test_no_op_if_original_stop_unset(self):
        # If a caller forgets to set original_stop_loss, do nothing rather than crash
        pos = self._long()
        pos.original_stop_loss = 0.0
        moved = _maybe_move_to_breakeven(pos, self._candle(high=72000, low=70500))
        assert moved is False

    def test_custom_trigger_rr(self):
        pos = self._long(entry=70000, stop=69300)  # risk 700
        # trigger_rr=2.0 → must hit 70000+1400 = 71400
        moved = _maybe_move_to_breakeven(
            pos, self._candle(high=71000, low=70500), trigger_rr=2.0
        )
        assert moved is False  # only +1000 < 1400
        moved = _maybe_move_to_breakeven(
            pos, self._candle(high=71500, low=70800), trigger_rr=2.0
        )
        assert moved is True


class TestKbMatchUnderlying:
    def test_setup_none_returns_no_kb_match(self):
        # SetupType.NONE means LLM didn't pick a setup at all → cannot match KB.
        kb = ProbabilitiesKB()
        sig = _fake_signal(setup=SetupType.NONE)
        enriched = calculate_strategy_score_with_kb(sig, kb=kb)
        assert enriched.match is None, (
            "SetupType.NONE must never produce a PA KB match. "
            "If this fails, the veto would be bypassed for empty setups."
        )

    def test_kb_returns_match_or_none_consistently(self):
        # Smoke: lookup is deterministic for the same input.
        kb = ProbabilitiesKB()
        sig = _fake_signal(setup=SetupType.SECOND_ENTRY_H2)
        e1 = calculate_strategy_score_with_kb(sig, kb=kb)
        e2 = calculate_strategy_score_with_kb(sig, kb=kb)
        # Both calls return the same match state (None or same setup_id)
        if e1.match is None:
            assert e2.match is None
        else:
            assert e2.match is not None
            assert e1.match.setup_id == e2.match.setup_id
