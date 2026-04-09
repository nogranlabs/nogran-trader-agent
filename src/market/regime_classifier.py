"""Regime classifier — explicit market state.

Core rule: BEFORE you look at any setup, classify the day. Are you in a
trend, a trading range, a spike, a transition? The same setup that works in
a trend FAILS in a range. The classifier here gives the LLM a single regime
label so it stops trying to apply trend setups in ranges.

Output regimes:
  - trending_up      : HH_HL structure + 1h up + ADX > 20
  - trending_down    : LH_LL structure + 1h down + ADX > 20
  - range            : low ADX, high overlap, structure indeterminate or LH_HL
  - transition       : structure mixed, mid ADX, no clear bias
  - spike            : extreme ATR ratio + consecutive bars one direction
"""

from __future__ import annotations

from typing import Optional


def classify_regime(
    structure: str,
    adx: float,
    bar_overlap: float,
    consecutive_bull: int,
    consecutive_bear: int,
    atr_ratio: float,
    tf_1h_above_ema: bool,
    tf_1h_below_ema: bool,
    tf_1h_direction: Optional[str],
) -> str:
    """Single function: returns one of trending_up | trending_down | range | transition | spike.

    Args reflect the FeatureSnapshot fields directly so callers can pass them
    by keyword.
    """
    # Spike: very strong directional move with expanded ATR
    if atr_ratio > 1.4 and consecutive_bull >= 4:
        return "spike"
    if atr_ratio > 1.4 and consecutive_bear >= 4:
        return "spike"

    # Range: chop with low ADX and high overlap
    if adx < 18 and bar_overlap > 0.55:
        return "range"
    if structure == "LH_HL":  # contracting wedge counts as range-ish
        return "range"

    # Trending up: structure + HTF agree + ADX confirms
    if structure == "HH_HL" and tf_1h_above_ema and adx >= 20:
        return "trending_up"

    # Trending down: structure + HTF agree + ADX confirms
    if structure == "LH_LL" and tf_1h_below_ema and adx >= 20:
        return "trending_down"

    # Weaker trends (one of the conditions fires but not all)
    if structure == "HH_HL" and adx >= 18:
        return "trending_up"  # weak uptrend
    if structure == "LH_LL" and adx >= 18:
        return "trending_down"

    # Default fallback
    return "transition"
