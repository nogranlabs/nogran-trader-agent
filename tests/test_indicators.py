"""
Tests for src/infra/indicators.py — pure-math indicator functions.

Resolves docs/tech-debt.md ALTO: "Faltam testes para indicators".
"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from infra.indicators import (
    adx,
    atr,
    atr_series,
    calculate_bar_overlap,
    count_consecutive,
    count_direction_changes,
    ema,
    ema_current,
    sma,
)


class TestSMA:
    def test_empty_returns_zero(self):
        assert sma([], 5) == 0.0

    def test_zero_period_returns_zero(self):
        assert sma([1.0, 2.0, 3.0], 0) == 0.0

    def test_single_value(self):
        assert sma([5.0], 5) == 5.0

    def test_basic_average(self):
        # Last 3 of [1,2,3,4,5] = 3,4,5 -> 4.0
        assert sma([1.0, 2.0, 3.0, 4.0, 5.0], 3) == 4.0

    def test_period_larger_than_input(self):
        # Period 10 with 3 values -> uses all 3 -> 2.0
        assert sma([1.0, 2.0, 3.0], 10) == 2.0

    def test_uniform_values(self):
        assert sma([7.0] * 10, 5) == 7.0


class TestEMA:
    def test_empty_returns_empty(self):
        assert ema([], 5) == []

    def test_zero_period_returns_empty(self):
        assert ema([1.0, 2.0], 0) == []

    def test_returns_full_length(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        result = ema(values, 5)
        assert len(result) == len(values)

    def test_first_period_minus_one_is_partial_sma(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = ema(values, 3)
        # First value should be just values[0]
        assert result[0] == 1.0
        # Second is mean of [1, 2]
        assert result[1] == 1.5

    def test_seed_at_period_index(self):
        values = [10.0] * 10
        result = ema(values, 5)
        # When all values are equal, EMA should equal that value at every point
        assert all(abs(v - 10.0) < 1e-9 for v in result)

    def test_ema_current_latest_value(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        assert ema_current(values, 3) == ema(values, 3)[-1]

    def test_ema_current_empty_returns_zero(self):
        assert ema_current([], 5) == 0.0

    def test_short_input_fallback(self):
        # Less than period -> partial SMAs
        result = ema([1.0, 2.0, 3.0], 5)
        assert len(result) == 3
        assert result[0] == 1.0
        assert result[1] == 1.5
        assert result[2] == 2.0


class TestATR:
    def test_empty_returns_zero(self):
        assert atr([], 14) == 0.0

    def test_atr_series_empty(self):
        assert atr_series([], 14) == []

    def test_single_candle(self):
        # Single bar (high, low, close) — TR is just high-low
        candles = [(110.0, 100.0, 105.0)]
        result = atr_series(candles, 14)
        # Less than period -> averages whatever is available
        assert len(result) == 1
        assert abs(result[0] - 10.0) < 1e-9

    def test_uniform_range_candles(self):
        # All bars have same range (10) -> ATR should converge to ~10
        candles = [(110.0 + i, 100.0 + i, 105.0 + i) for i in range(20)]
        result = atr(candles, 14)
        assert result > 0
        assert result < 20  # sanity bound

    def test_atr_grows_with_bigger_ranges(self):
        small = [(101.0, 100.0, 100.5)] * 20
        large = [(120.0, 100.0, 110.0)] * 20
        assert atr(large, 14) > atr(small, 14)


class TestADX:
    def test_empty_returns_zero(self):
        assert adx([], 14) == 0.0

    def test_too_few_candles_returns_zero(self):
        candles = [(110.0, 100.0, 105.0)] * 5
        assert adx(candles, 14) == 0.0

    def test_strong_uptrend_high_adx(self):
        # Strict uptrend: each bar higher than the last
        candles = []
        for i in range(40):
            base = 100.0 + i * 2
            candles.append((base + 1, base, base + 0.5))
        result = adx(candles, 14)
        assert result > 20  # trending markets typically show ADX > 20

    def test_choppy_market_low_adx(self):
        # Alternating up/down small bars
        candles = []
        for i in range(40):
            offset = 0.5 if i % 2 == 0 else -0.5
            base = 100.0 + offset
            candles.append((base + 0.3, base - 0.3, base))
        result = adx(candles, 14)
        # Choppy market should show lower ADX than trending one
        assert result < 50


class TestBarOverlap:
    def test_empty_returns_zero(self):
        assert calculate_bar_overlap([]) == 0.0

    def test_single_bar_returns_zero(self):
        assert calculate_bar_overlap([(110.0, 100.0)]) == 0.0

    def test_zero_overlap_trending(self):
        # Each bar starts above the previous -> no overlap
        bars = [(110.0, 100.0), (120.0, 111.0), (130.0, 121.0)]
        result = calculate_bar_overlap(bars)
        assert result == 0.0

    def test_full_overlap_identical_bars(self):
        bars = [(110.0, 100.0), (110.0, 100.0), (110.0, 100.0)]
        result = calculate_bar_overlap(bars)
        assert result == 1.0

    def test_partial_overlap(self):
        bars = [(110.0, 100.0), (115.0, 105.0)]
        # overlap = 110-105 = 5; combined = 115-100 = 15; ratio = 0.333
        result = calculate_bar_overlap(bars)
        assert abs(result - 5.0 / 15.0) < 1e-9


class TestConsecutive:
    def test_empty_returns_zero_zero(self):
        assert count_consecutive([]) == (0, 0)

    def test_all_bull(self):
        assert count_consecutive([True, True, True]) == (3, 0)

    def test_all_bear(self):
        assert count_consecutive([False, False, False]) == (0, 3)

    def test_trailing_bull_only(self):
        assert count_consecutive([False, False, True, True]) == (2, 0)

    def test_trailing_bear_only(self):
        assert count_consecutive([True, True, False, False, False]) == (0, 3)

    def test_single_bar(self):
        assert count_consecutive([True]) == (1, 0)
        assert count_consecutive([False]) == (0, 1)


class TestDirectionChanges:
    def test_empty_returns_zero(self):
        assert count_direction_changes([]) == 0.0

    def test_single_returns_zero(self):
        assert count_direction_changes([True]) == 0.0

    def test_no_changes(self):
        assert count_direction_changes([True, True, True, True]) == 0.0

    def test_all_changes(self):
        # T,F,T,F -> 3 changes / 3 transitions = 1.0
        assert count_direction_changes([True, False, True, False]) == 1.0

    def test_partial_changes(self):
        # T,T,F,F -> 1 change / 3 transitions = 0.333
        result = count_direction_changes([True, True, False, False])
        assert abs(result - 1.0 / 3.0) < 1e-9
