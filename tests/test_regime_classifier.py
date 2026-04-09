"""Tests for src/market/regime_classifier.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from market.regime_classifier import classify_regime  # noqa: E402


def _kw(**overrides):
    """Default neutral inputs, override what matters."""
    base = dict(
        structure="INDETERMINATE",
        adx=18.0,
        bar_overlap=0.30,
        consecutive_bull=0,
        consecutive_bear=0,
        atr_ratio=1.0,
        tf_1h_above_ema=False,
        tf_1h_below_ema=False,
        tf_1h_direction=None,
    )
    base.update(overrides)
    return base


class TestRegimeClassifier:
    def test_default_neutral_is_transition(self):
        assert classify_regime(**_kw()) == "transition"

    def test_strong_trending_up(self):
        out = classify_regime(**_kw(
            structure="HH_HL", adx=28.0, tf_1h_above_ema=True, tf_1h_direction="up"
        ))
        assert out == "trending_up"

    def test_strong_trending_down(self):
        out = classify_regime(**_kw(
            structure="LH_LL", adx=28.0, tf_1h_below_ema=True, tf_1h_direction="down"
        ))
        assert out == "trending_down"

    def test_weak_trending_up_without_htf_alignment(self):
        # Structure says HH_HL but 1h not aligned. Still trending_up (weak).
        out = classify_regime(**_kw(structure="HH_HL", adx=20.0))
        assert out == "trending_up"

    def test_range_low_adx_high_overlap(self):
        out = classify_regime(**_kw(adx=14.0, bar_overlap=0.65))
        assert out == "range"

    def test_wedge_lh_hl_is_range(self):
        out = classify_regime(**_kw(structure="LH_HL", adx=22.0))
        assert out == "range"

    def test_spike_bull(self):
        out = classify_regime(**_kw(atr_ratio=1.5, consecutive_bull=5))
        assert out == "spike"

    def test_spike_bear(self):
        out = classify_regime(**_kw(atr_ratio=1.5, consecutive_bear=5))
        assert out == "spike"

    def test_spike_overrides_range(self):
        # High ATR ratio means we are NOT in chop
        out = classify_regime(**_kw(
            atr_ratio=1.6, consecutive_bull=5, adx=14.0, bar_overlap=0.65
        ))
        assert out == "spike"
