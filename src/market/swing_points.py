"""Swing point detection — structural analysis for Nogran PA.

The methodology relies on swing highs and swing lows to define market
structure. A swing high is a bar whose high is strictly greater than the highs
of N bars before AND N bars after. Swing low is the mirror.

Once enough swings are detected, market structure is classified:
  - HH_HL  : higher highs + higher lows = bull trend
  - LH_LL  : lower highs + lower lows  = bear trend
  - HH_LL  : higher highs + lower lows  = expanding range / volatile
  - LH_HL  : lower highs + higher lows  = contracting range (wedge)
  - INDETERMINATE: not enough swings yet

The current bar can NEVER be confirmed as a swing — we need N bars after to
confirm. So at any moment, the "last confirmed swing" is at least N bars old.

Usage:
    swings = detect_swings(candles, lookback=2)
    ctx = compute_swing_context(candles, lookback=2)
    # ctx.last_swing_high, ctx.last_swing_low, ctx.bars_since_*, ctx.structure
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from domain.models import Candle


@dataclass
class Swing:
    """A confirmed swing point."""
    index: int           # candle index in the input list
    price: float         # high (for swing_high) or low (for swing_low)
    type: str            # "high" | "low"


@dataclass
class SwingContext:
    """Aggregated swing context for the current bar."""
    last_swing_high: Optional[float] = None
    last_swing_low: Optional[float] = None
    last_swing_high_index: int = -1
    last_swing_low_index: int = -1
    bars_since_swing_high: int = -1   # -1 if no swing detected yet
    bars_since_swing_low: int = -1
    structure: str = "INDETERMINATE"  # see module docstring
    swing_high_count: int = 0          # how many highs detected in window
    swing_low_count: int = 0


def detect_swings(candles: list[Candle], lookback: int = 2) -> list[Swing]:
    """Detect all swing highs and lows using fractal-N method.

    A bar at index i is a swing high if:
        high[i] > high[i-k] for k in 1..lookback
        AND high[i] > high[i+k] for k in 1..lookback

    The first `lookback` bars and last `lookback` bars cannot be swings (not
    enough neighbors to confirm).

    Args:
        candles: chronological list of candles (oldest first)
        lookback: how many bars on each side to check (default 2)

    Returns:
        List of Swing objects, in chronological order.
    """
    swings: list[Swing] = []
    n = len(candles)
    if n < 2 * lookback + 1:
        return swings

    for i in range(lookback, n - lookback):
        h = candles[i].high
        l = candles[i].low

        # Swing high: strictly greater than neighbors on both sides
        is_swing_high = True
        for k in range(1, lookback + 1):
            if candles[i - k].high >= h or candles[i + k].high >= h:
                is_swing_high = False
                break

        if is_swing_high:
            swings.append(Swing(index=i, price=h, type="high"))
            continue  # a bar can't be both high and low at the same lookback

        # Swing low: strictly less than neighbors on both sides
        is_swing_low = True
        for k in range(1, lookback + 1):
            if candles[i - k].low <= l or candles[i + k].low <= l:
                is_swing_low = False
                break

        if is_swing_low:
            swings.append(Swing(index=i, price=l, type="low"))

    return swings


def classify_structure(swings: list[Swing]) -> str:
    """Classify market structure from the most recent swings.

    Looks at the last 2 highs and last 2 lows. Returns one of:
      HH_HL  : higher high + higher low (uptrend)
      LH_LL  : lower high + lower low (downtrend)
      HH_LL  : higher high + lower low (expanding volatility)
      LH_HL  : lower high + higher low (contracting / wedge)
      INDETERMINATE: not enough swings of each type
    """
    highs = [s for s in swings if s.type == "high"]
    lows = [s for s in swings if s.type == "low"]

    if len(highs) < 2 or len(lows) < 2:
        return "INDETERMINATE"

    last_high, prev_high = highs[-1], highs[-2]
    last_low, prev_low = lows[-1], lows[-2]

    higher_high = last_high.price > prev_high.price
    higher_low = last_low.price > prev_low.price

    if higher_high and higher_low:
        return "HH_HL"
    if not higher_high and not higher_low:
        return "LH_LL"
    if higher_high and not higher_low:
        return "HH_LL"
    if not higher_high and higher_low:
        return "LH_HL"
    return "INDETERMINATE"


def compute_swing_context(
    candles: list[Candle],
    lookback: int = 2,
    window: int = 50,
) -> SwingContext:
    """Compute the swing context for the current (last) candle.

    Args:
        candles: chronological candles (oldest first); the LAST one is "now"
        lookback: fractal width (default 2)
        window: how many bars back to look for swings (limits cost)

    Returns:
        SwingContext describing where the current bar is relative to recent
        swings, plus the structure classification.
    """
    if not candles:
        return SwingContext()

    # Limit the window for performance — we only need recent swings
    work = candles[-window:] if len(candles) > window else list(candles)
    base_offset = len(candles) - len(work)
    swings = detect_swings(work, lookback=lookback)

    ctx = SwingContext()
    if not swings:
        return ctx

    highs = [s for s in swings if s.type == "high"]
    lows = [s for s in swings if s.type == "low"]

    current_index = len(candles) - 1

    if highs:
        last_h = highs[-1]
        ctx.last_swing_high = last_h.price
        ctx.last_swing_high_index = base_offset + last_h.index
        ctx.bars_since_swing_high = current_index - ctx.last_swing_high_index

    if lows:
        last_l = lows[-1]
        ctx.last_swing_low = last_l.price
        ctx.last_swing_low_index = base_offset + last_l.index
        ctx.bars_since_swing_low = current_index - ctx.last_swing_low_index

    ctx.swing_high_count = len(highs)
    ctx.swing_low_count = len(lows)
    ctx.structure = classify_structure(swings)

    return ctx
