"""Tests for src/market/always_in.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from market.always_in import compute_always_in  # noqa: E402


class TestAlwaysIn:
    def test_strong_bull_returns_sempre_comprado(self):
        out = compute_always_in(
            last_bar_is_bull=True,
            last_5_bull_count=4,
            price_above_ema=True,
            structure="HH_HL",
            tf_1h_above_ema=True,
            tf_1h_direction="up",
        )
        assert out == "SEMPRE_COMPRADO"

    def test_strong_bear_returns_sempre_vendido(self):
        out = compute_always_in(
            last_bar_is_bull=False,
            last_5_bull_count=1,
            price_above_ema=False,
            structure="LH_LL",
            tf_1h_above_ema=False,
            tf_1h_direction="down",
        )
        assert out == "SEMPRE_VENDIDO"

    def test_mixed_returns_neutro(self):
        # Half bull, half bear evidence → no clear bias
        out = compute_always_in(
            last_bar_is_bull=True,
            last_5_bull_count=3,
            price_above_ema=True,
            structure="INDETERMINATE",
            tf_1h_above_ema=False,
            tf_1h_direction="down",
        )
        assert out == "NEUTRO"

    def test_neutro_when_structure_indeterminate_and_split(self):
        out = compute_always_in(
            last_bar_is_bull=False,
            last_5_bull_count=2,
            price_above_ema=True,
            structure="INDETERMINATE",
            tf_1h_above_ema=True,
            tf_1h_direction=None,
        )
        assert out == "NEUTRO"
