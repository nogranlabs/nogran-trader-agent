"""Tests for src/market/swing_points.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from domain.models import Candle  # noqa: E402
from market.swing_points import (  # noqa: E402
    classify_structure,
    compute_swing_context,
    detect_swings,
)


def _c(ts: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(timestamp=ts, open=o, high=h, low=l, close=c, volume=1.0)


def _bull_pullback_pattern():
    """Make a clear HH/HL bull structure: up-down-up-down-up with higher swings.

    Highs: 100, 105, 102, 110, 108, 115, 112, 120
    Lows:   95,  99,  98, 105, 103, 110, 109, 115
    Should have swing highs at peaks and swing lows at troughs.
    """
    candles = []
    pattern = [
        (95, 100), (99, 105), (98, 102), (105, 110), (103, 108),
        (110, 115), (109, 112), (115, 120),
    ]
    for i, (low, high) in enumerate(pattern):
        candles.append(_c(i * 60, low + 1, high, low, high - 1))
    return candles


class TestDetectSwings:
    def test_empty_input(self):
        assert detect_swings([], lookback=2) == []

    def test_too_few_candles(self):
        # Need at least 2*lookback+1 = 5 candles for lookback=2
        candles = [_c(i, 100, 101, 99, 100) for i in range(4)]
        assert detect_swings(candles, lookback=2) == []

    def test_finds_obvious_swing_high(self):
        # 100, 102, 110 (peak), 103, 101 — middle bar is the swing high
        candles = [
            _c(0, 99, 100, 98, 99),
            _c(1, 99, 102, 98, 100),
            _c(2, 100, 110, 99, 109),  # swing high
            _c(3, 109, 103, 100, 101),
            _c(4, 101, 101, 99, 100),
        ]
        swings = detect_swings(candles, lookback=2)
        assert len(swings) >= 1
        highs = [s for s in swings if s.type == "high"]
        assert len(highs) == 1
        assert highs[0].index == 2
        assert highs[0].price == 110

    def test_finds_obvious_swing_low(self):
        # 100, 98, 90 (trough), 95, 99 — middle bar is the swing low
        candles = [
            _c(0, 100, 101, 99, 100),
            _c(1, 100, 99, 98, 99),
            _c(2, 99, 91, 90, 91),  # swing low
            _c(3, 91, 96, 91, 95),
            _c(4, 95, 100, 95, 99),
        ]
        swings = detect_swings(candles, lookback=2)
        lows = [s for s in swings if s.type == "low"]
        assert len(lows) == 1
        assert lows[0].index == 2
        assert lows[0].price == 90

    def test_alternating_swings_in_zigzag(self):
        candles = _bull_pullback_pattern()
        swings = detect_swings(candles, lookback=1)
        # Zigzag has multiple alternating swings
        types = [s.type for s in swings]
        assert "high" in types
        assert "low" in types


class TestClassifyStructure:
    def test_indeterminate_when_too_few_swings(self):
        from market.swing_points import Swing
        # Only 1 high, 1 low → not enough
        swings = [
            Swing(index=2, price=100, type="high"),
            Swing(index=5, price=95, type="low"),
        ]
        assert classify_structure(swings) == "INDETERMINATE"

    def test_hh_hl_uptrend(self):
        from market.swing_points import Swing
        swings = [
            Swing(index=0, price=100, type="high"),
            Swing(index=2, price=95, type="low"),
            Swing(index=5, price=105, type="high"),  # higher high
            Swing(index=7, price=98, type="low"),    # higher low
        ]
        assert classify_structure(swings) == "HH_HL"

    def test_lh_ll_downtrend(self):
        from market.swing_points import Swing
        swings = [
            Swing(index=0, price=110, type="high"),
            Swing(index=2, price=100, type="low"),
            Swing(index=5, price=105, type="high"),  # lower high
            Swing(index=7, price=95, type="low"),    # lower low
        ]
        assert classify_structure(swings) == "LH_LL"

    def test_hh_ll_expanding(self):
        from market.swing_points import Swing
        swings = [
            Swing(index=0, price=100, type="high"),
            Swing(index=2, price=95, type="low"),
            Swing(index=5, price=110, type="high"),  # higher high
            Swing(index=7, price=90, type="low"),    # lower low
        ]
        assert classify_structure(swings) == "HH_LL"

    def test_lh_hl_wedge(self):
        from market.swing_points import Swing
        swings = [
            Swing(index=0, price=110, type="high"),
            Swing(index=2, price=90, type="low"),
            Swing(index=5, price=105, type="high"),  # lower high
            Swing(index=7, price=95, type="low"),    # higher low
        ]
        assert classify_structure(swings) == "LH_HL"


class TestComputeSwingContext:
    def test_empty_returns_default(self):
        ctx = compute_swing_context([])
        assert ctx.last_swing_high is None
        assert ctx.last_swing_low is None
        assert ctx.bars_since_swing_high == -1
        assert ctx.structure == "INDETERMINATE"

    def test_populates_last_swing_high_and_distance(self):
        # Build pattern: 100, 102, 110 (peak), 103, 101, 100 — current is bar 5
        candles = [
            _c(0, 99, 100, 98, 99),
            _c(1, 99, 102, 98, 100),
            _c(2, 100, 110, 99, 109),  # swing high at index 2
            _c(3, 109, 103, 100, 101),
            _c(4, 101, 101, 99, 100),
            _c(5, 100, 100, 98, 99),  # current
        ]
        ctx = compute_swing_context(candles, lookback=2)
        assert ctx.last_swing_high == 110
        assert ctx.last_swing_high_index == 2
        assert ctx.bars_since_swing_high == 3  # current (5) - 2

    def test_returns_indeterminate_with_no_clear_swings(self):
        # Monotonic up — no swings yet
        candles = [_c(i, 100 + i, 101 + i, 99 + i, 100 + i) for i in range(10)]
        ctx = compute_swing_context(candles, lookback=2)
        # No internal swing because each bar is higher than the prior
        assert ctx.structure == "INDETERMINATE"
