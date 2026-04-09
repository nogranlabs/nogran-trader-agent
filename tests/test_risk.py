"""
Tests for the Risk Engine: drawdown bands, exposure manager, position sizer, metrics.

Resolves docs/tech-debt.md ALTO: "Faltam testes para risk engine".
"""

import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from domain.enums import Action, DrawdownBand
from domain.models import DecisionScore, ScoreBreakdown, TradeResult
from infra.config import Config
from risk.drawdown_controller import DrawdownController
from risk.exposure_manager import ExposureManager
from risk.metrics import RiskMetrics
from risk.position_sizer import PositionSizer, clamp, map_range

# ============================================================
# Helpers
# ============================================================

def make_decision_score(total: float = 75.0, go: bool = True) -> DecisionScore:
    bd = {
        "market_quality": ScoreBreakdown(score=80, weight=0.20, contribution=16.0),
        "strategy": ScoreBreakdown(score=70, weight=0.35, contribution=24.5),
        "ai_overlay": ScoreBreakdown(score=60, weight=0.20, contribution=12.0),
        "risk": ScoreBreakdown(score=90, weight=0.25, contribution=22.5),
    }
    return DecisionScore(
        total=total, go=go, breakdown=bd, threshold=65,
        hard_veto=False, veto_reason="",
    )


def make_trade(pnl: float, pct: float = 0.01) -> TradeResult:
    now = datetime.utcnow()
    return TradeResult(
        intent_id=f"id-{pnl}",
        action=Action.COMPRA,
        side="buy",
        entry_price=50000.0,
        exit_price=50000.0 + pnl,
        position_size=0.001,
        pnl=pnl,
        pnl_pct=pct,
        decision_score=make_decision_score(),
        entry_time=now,
        exit_time=now + timedelta(minutes=5),
        exit_reason="take_profit" if pnl > 0 else "stop_loss",
    )


# ============================================================
# DrawdownController
# ============================================================

class TestDrawdownController:
    def setup_method(self):
        self.dd = DrawdownController()

    def test_normal_band_below_3pct(self):
        assert self.dd.get_band(0.0) == DrawdownBand.NORMAL
        assert self.dd.get_band(0.029) == DrawdownBand.NORMAL

    def test_defensive_band_3_to_5pct(self):
        assert self.dd.get_band(0.04) == DrawdownBand.DEFENSIVE
        assert self.dd.get_band(0.05) == DrawdownBand.DEFENSIVE

    def test_minimum_band_5_to_8pct(self):
        assert self.dd.get_band(0.06) == DrawdownBand.MINIMUM
        assert self.dd.get_band(0.08) == DrawdownBand.MINIMUM

    def test_circuit_breaker_above_8pct(self):
        assert self.dd.get_band(0.09) == DrawdownBand.CIRCUIT_BREAKER
        assert self.dd.get_band(0.20) == DrawdownBand.CIRCUIT_BREAKER

    def test_sizing_multipliers(self):
        assert self.dd.get_sizing_multiplier(DrawdownBand.NORMAL) == 1.0
        assert self.dd.get_sizing_multiplier(DrawdownBand.DEFENSIVE) == 0.6
        assert self.dd.get_sizing_multiplier(DrawdownBand.MINIMUM) == 0.3
        assert self.dd.get_sizing_multiplier(DrawdownBand.CIRCUIT_BREAKER) == 0.0

    def test_is_circuit_breaker(self):
        assert self.dd.is_circuit_breaker(DrawdownBand.CIRCUIT_BREAKER)
        assert not self.dd.is_circuit_breaker(DrawdownBand.NORMAL)


# ============================================================
# ExposureManager
# ============================================================

class TestExposureManager:
    def setup_method(self):
        self.mgr = ExposureManager()

    def test_initial_state_can_open(self):
        # Move past cooldown by starting at a high candle index
        ok, _ = self.mgr.can_open_position(100)
        assert ok

    def test_blocks_when_position_open(self):
        self.mgr.on_position_opened(100)
        ok, reason = self.mgr.can_open_position(101)
        assert not ok
        assert "open" in reason.lower()

    def test_cooldown_after_close(self):
        # Open at 100, close at 105
        self.mgr.on_position_opened(100)
        self.mgr.on_position_closed(105)
        # Immediately try to reopen (within cooldown)
        ok, reason = self.mgr.can_open_position(105)
        assert not ok
        assert "cooldown" in reason.lower()

    def test_cooldown_clears(self):
        self.mgr.on_position_opened(100)
        self.mgr.on_position_closed(105)
        ok, _ = self.mgr.can_open_position(105 + Config.COOLDOWN_CANDLES + 1)
        assert ok

    def test_force_close_after_max_time(self):
        self.mgr.on_position_opened(100)
        # Just before limit
        assert not self.mgr.should_force_close(100 + Config.MAX_POSITION_TIME_CANDLES - 1)
        # At limit
        assert self.mgr.should_force_close(100 + Config.MAX_POSITION_TIME_CANDLES)

    def test_force_close_no_position_returns_false(self):
        assert not self.mgr.should_force_close(1000)


# ============================================================
# PositionSizer
# ============================================================

class TestPositionSizerHelpers:
    def test_clamp_within_range(self):
        assert clamp(5, 0, 10) == 5

    def test_clamp_below_min(self):
        assert clamp(-1, 0, 10) == 0

    def test_clamp_above_max(self):
        assert clamp(15, 0, 10) == 10

    def test_map_range_basic(self):
        # 50 in [0,100] -> 5 in [0,10]
        assert map_range(50, 0, 100, 0, 10) == 5

    def test_map_range_clamps_high(self):
        # 200 in [0,100] gets clamped, then maps to 10
        assert map_range(200, 0, 100, 0, 10) == 10

    def test_map_range_clamps_low(self):
        assert map_range(-50, 0, 100, 0, 10) == 0


class TestPositionSizer:
    def setup_method(self):
        self.dd = DrawdownController()
        self.sizer = PositionSizer(self.dd)
        self.metrics = RiskMetrics(initial_capital=10000.0)

    def test_zero_atr_returns_zero(self):
        size = self.sizer.calculate(
            capital=10000.0, atr=0.0,
            decision_score=make_decision_score(),
            metrics=self.metrics,
        )
        assert size == 0.0

    def test_basic_sizing_normal_drawdown(self):
        # capital=10000, RISK_PER_TRADE=0.01 -> $100 risk
        # atr=100, ATR_STOP_MULTIPLIER=1.5 -> stop_dist=$150
        # base_size = 100/150 = 0.667
        # score 75 -> mult 0.75 (since 75 in [65,95] linearly to [0.6, 1.0])
        size = self.sizer.calculate(
            capital=10000.0, atr=100.0,
            decision_score=make_decision_score(75.0),
            metrics=self.metrics,
        )
        assert size > 0

    def test_circuit_breaker_returns_min_size(self):
        # Force a high drawdown
        self.metrics.equity_curve = [10000.0, 8000.0]  # 20% drawdown
        size = self.sizer.calculate(
            capital=10000.0, atr=100.0,
            decision_score=make_decision_score(75.0),
            metrics=self.metrics,
        )
        # Circuit breaker mult = 0, but min_size clamp -> 0.0001
        assert size == 0.0001

    def test_higher_score_larger_size(self):
        size_low = self.sizer.calculate(
            capital=10000.0, atr=100.0,
            decision_score=make_decision_score(65.0),
            metrics=self.metrics,
        )
        size_high = self.sizer.calculate(
            capital=10000.0, atr=100.0,
            decision_score=make_decision_score(95.0),
            metrics=self.metrics,
        )
        assert size_high > size_low

    def test_size_never_below_min(self):
        # Tiny capital -> size should still respect min_size
        size = self.sizer.calculate(
            capital=10.0, atr=100.0,
            decision_score=make_decision_score(65.0),
            metrics=self.metrics,
        )
        assert size >= 0.0001


# ============================================================
# RiskMetrics
# ============================================================

class TestRiskMetrics:
    def test_initial_state(self):
        m = RiskMetrics(initial_capital=10000.0)
        assert m.total_pnl == 0.0
        assert m.current_equity == 10000.0
        assert m.win_rate == 0.0
        assert m.consecutive_losses == 0

    def test_total_pnl_after_trades(self):
        m = RiskMetrics()
        m.update(make_trade(100))
        m.update(make_trade(-50))
        m.update(make_trade(200))
        assert m.total_pnl == 250.0

    def test_equity_curve_grows(self):
        m = RiskMetrics()
        m.update(make_trade(100))
        m.update(make_trade(-30))
        assert m.equity_curve == [10000.0, 10100.0, 10070.0]
        assert m.current_equity == 10070.0
        assert m.max_equity == 10100.0

    def test_current_drawdown(self):
        m = RiskMetrics()
        m.update(make_trade(500))    # equity 10500 (peak)
        m.update(make_trade(-300))   # equity 10200
        # drawdown = 1 - 10200/10500 = 0.0286
        assert abs(m.current_drawdown - (300 / 10500)) < 1e-9

    def test_max_drawdown_tracks_worst(self):
        m = RiskMetrics()
        m.update(make_trade(1000))   # 11000 peak
        m.update(make_trade(-500))   # 10500 -> dd ~4.5%
        m.update(make_trade(2000))   # 12500 new peak
        m.update(make_trade(-100))   # 12400 -> dd 0.8%
        # Worst dd was after first loss
        assert m.max_drawdown >= 500 / 11000 - 1e-9

    def test_win_rate(self):
        m = RiskMetrics()
        m.update(make_trade(100))
        m.update(make_trade(100))
        m.update(make_trade(-50))
        m.update(make_trade(-50))
        assert m.win_rate == 0.5

    def test_avg_win_loss(self):
        m = RiskMetrics()
        m.update(make_trade(100))
        m.update(make_trade(200))
        m.update(make_trade(-50))
        m.update(make_trade(-100))
        assert m.avg_win == 150.0
        assert m.avg_loss == -75.0

    def test_expectancy(self):
        m = RiskMetrics()
        m.update(make_trade(100))   # win
        m.update(make_trade(-50))   # loss
        # expectancy = 0.5 * 100 + 0.5 * -50 = 25
        assert m.expectancy == 25.0

    def test_profit_factor(self):
        m = RiskMetrics()
        m.update(make_trade(200))
        m.update(make_trade(100))
        m.update(make_trade(-100))
        # PF = 300 / 100 = 3.0
        assert m.profit_factor == 3.0

    def test_profit_factor_no_losses_inf(self):
        m = RiskMetrics()
        m.update(make_trade(100))
        m.update(make_trade(200))
        assert m.profit_factor == float("inf")

    def test_consecutive_losses(self):
        m = RiskMetrics()
        m.update(make_trade(100))
        m.update(make_trade(-50))
        m.update(make_trade(-50))
        m.update(make_trade(-50))
        assert m.consecutive_losses == 3

    def test_consecutive_losses_resets_on_win(self):
        m = RiskMetrics()
        m.update(make_trade(-50))
        m.update(make_trade(-50))
        m.update(make_trade(100))   # most recent is win
        assert m.consecutive_losses == 0

    def test_sharpe_rolling_needs_min_5_trades(self):
        m = RiskMetrics()
        for _ in range(4):
            m.update(make_trade(100, 0.01))
        assert m.sharpe_rolling == 0.0

    def test_sharpe_rolling_zero_variance(self):
        m = RiskMetrics()
        for _ in range(10):
            m.update(make_trade(100, 0.01))   # all identical
        assert m.sharpe_rolling == 0.0

    def test_equity_at_ath_true_at_start(self):
        m = RiskMetrics()
        assert m.equity_at_ath is True

    def test_equity_at_ath_false_after_loss(self):
        m = RiskMetrics()
        m.update(make_trade(100))
        m.update(make_trade(-50))
        assert m.equity_at_ath is False
