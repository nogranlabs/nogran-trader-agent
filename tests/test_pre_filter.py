"""Tests for src/market/pre_filter.py — calculate_mq_score.

Background: in 2026-04-09 the pre-filter MQ formula was tightened. Before, the
ADX rule was `< 15 → -10`, which left chop with ADX 18-24 essentially unfiltered
(MQ stayed >= 80). The 1000-candle backtest showed every losing trade had ADX
in that "no real trend" zone. The new rule is `< 20 → -35` and `< 25 → -15`, so
chop drops below the default threshold of 50 and gets vetoed before the LLM is
even called.

These tests pin the new formula so a future refactor cannot silently weaken it.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from domain.models import Candle, FeatureSnapshot  # noqa: E402
from market.pre_filter import calculate_mq_score  # noqa: E402


def make_features(**overrides) -> FeatureSnapshot:
    """Defaults to 'good market': trending, low chop, peak session."""
    candle = Candle(
        timestamp=1775653260000,
        open=66950.0,
        high=67100.0,
        low=66900.0,
        close=67000.0,
        volume=5.0,
    )
    defaults = dict(
        candle=candle,
        candle_index=100,
        ema_20=66970.0,
        atr_14=80.0,
        atr_sma_20=70.0,
        adx_14=30.0,
        price_vs_ema=0.045,
        atr_ratio=1.14,
        body_pct=60.0,
        upper_tail_pct=15.0,
        lower_tail_pct=25.0,
        consecutive_bull=3,
        consecutive_bear=0,
        bar_overlap_ratio=0.30,
        direction_change_ratio=0.20,
        volume_ratio=1.2,
        is_peak_session=True,
        atr_expanding=True,
        atr_contracting=False,
    )
    defaults.update(overrides)
    return FeatureSnapshot(**defaults)


class TestMqScoreBaseline:
    def test_perfect_trend_caps_at_100(self):
        # Strong trend, low chop, peak session, expanding ATR → score capped at 100
        f = make_features(adx_14=35.0, bar_overlap_ratio=0.20,
                          direction_change_ratio=0.10, atr_ratio=1.3)
        assert calculate_mq_score(f) == 100

    def test_neutral_market_passes_default_threshold(self):
        # Default fixture is "decent market" — should be >= 50 (default backtest threshold)
        f = make_features()
        assert calculate_mq_score(f) >= 50


class TestAdxRule:
    """ADX < 20 must produce a veto-grade penalty (the 2026-04-09 fix)."""

    def test_adx_below_20_drops_below_default_threshold(self):
        # ADX 18 = no real trend. Even with everything else clean, MQ should fall < 50.
        f = make_features(adx_14=18.0, bar_overlap_ratio=0.30,
                          direction_change_ratio=0.20)
        score = calculate_mq_score(f)
        assert score < 50, f"low-ADX chop should fail default pre-filter (got {score})"

    def test_adx_19_still_vetoes(self):
        f = make_features(adx_14=19.0)
        assert calculate_mq_score(f) < 50

    def test_adx_22_is_weak_trend_partial_penalty(self):
        # ADX 22 = weak trend. Penalized but does not hit the hard cap.
        # With peak session bonus the floor is roughly 95 (100 - 15 + 10).
        f = make_features(adx_14=22.0)
        clean = make_features(adx_14=30.0)
        score = calculate_mq_score(f)
        clean_score = calculate_mq_score(clean)
        assert score < clean_score, "ADX 22 must be weaker than ADX 30"
        assert score > 40, "ADX 22 should not hit the <20 hard cap"

    def test_adx_25_no_penalty(self):
        f = make_features(adx_14=25.0)
        # Just barely "real trend" — no ADX penalty
        assert calculate_mq_score(f) >= 90

    def test_adx_above_30_gets_bonus(self):
        f_low = make_features(adx_14=25.0)
        f_high = make_features(adx_14=35.0)
        assert calculate_mq_score(f_high) >= calculate_mq_score(f_low)


class TestChopPenalties:
    def test_severe_chop_overlap_penalizes(self):
        f = make_features(bar_overlap_ratio=0.75)
        clean = make_features(bar_overlap_ratio=0.30)
        assert calculate_mq_score(f) < calculate_mq_score(clean)

    def test_dead_market_atr_penalizes(self):
        f = make_features(atr_ratio=0.4)
        normal = make_features(atr_ratio=1.1)
        assert calculate_mq_score(f) < calculate_mq_score(normal)

    def test_high_direction_change_penalizes(self):
        f = make_features(direction_change_ratio=0.7)
        clean = make_features(direction_change_ratio=0.2)
        assert calculate_mq_score(f) < calculate_mq_score(clean)


class TestLowAdxIsHardestSingleVeto:
    """Regression: ADX <20 alone must drop a clean candle below 50."""

    def test_clean_chart_with_low_adx_still_vetoes(self):
        # Everything else perfect, only ADX bad. The 2026-04-09 backtest showed
        # this exact pattern was the dominant losing scenario.
        f = make_features(
            adx_14=18.0,
            bar_overlap_ratio=0.20,    # clean
            direction_change_ratio=0.10,  # clean
            atr_ratio=1.2,             # ok volatility
            is_peak_session=True,      # peak bonus
        )
        score = calculate_mq_score(f)
        assert score < 50, (
            f"Low-ADX must dominate other positive signals (got {score}). "
            "If this test fails, the ADX rule was weakened — see 2026-04-09 backtest."
        )
