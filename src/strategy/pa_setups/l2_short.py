"""
L2 Short detector — Second Entry pullback sell in a downtrend.

Mirror of H2 Long. "After a spike down, wait for a 1-2 bar pullback up,
then sell the resumption down."

CONDITIONS (all must be true):
  1. HTF context bearish: tf_1h_direction == "down" OR tf_1h_below_ema
  2. Local structure bearish: structure_classification in {LH_LL} OR
     computed_always_in == SEMPRE_VENDIDO
  3. Recent pullback visible: in last 5 bars, at least 1-2 consecutive
     bull bars (the pullback up) followed by a bear bar (the resumption)
  4. Current bar is the RESUMPTION bar (bear, moderate body, not at spike bottom)
  5. Price near EMA20 (within 1.5 ATR)
  6. NOT at 5-bar low (we're in the rally, not the spike bottom)
  7. ATR not contracting

STOP: last_swing_high (structural anchor) with 0.1% buffer above
TARGET: entry - 2× risk (R:R 2.0)
"""

from __future__ import annotations

from typing import Optional

from domain.enums import Action, SetupType
from domain.models import FeatureSnapshot
from strategy.pa_setups import DetectedSetup


def detect_l2_short(features: FeatureSnapshot) -> Optional[DetectedSetup]:
    """Detect an L2 short setup. Returns DetectedSetup or None."""

    # --- Gate 1: HTF must be bearish ---
    # Strict: require 1h direction == "down". Also block in range/transition.
    if features.tf_1h_direction is not None:
        if features.tf_1h_direction != "down":
            return None
    if features.regime in ("range", "transition"):
        return None  # don't sell pullbacks in range/transition — L2 is a trend setup

    # --- Gate 2: Local structure bearish ---
    structure_ok = (
        features.structure_classification == "LH_LL"
        or features.computed_always_in == "SEMPRE_VENDIDO"
    )
    if not structure_ok:
        return None

    # --- Gate 3: Pullback visible in recent bars ---
    bars = features.recent_bars
    if len(bars) < 4:
        return None

    current = bars[-1]
    if current.is_bullish:
        return None  # current bar must be bear (resumption bar)

    # Require 2+ bull bars as pullback (was 1 — too easy to satisfy,
    # produced 10 losses in 12 trades on d60-70 mock). A real pullback
    # needs at least 2 bars of counter-trend movement.
    prev4 = bars[-5:-1] if len(bars) >= 5 else bars[:-1]
    bull_count = sum(1 for b in prev4 if b.is_bullish)
    if bull_count < 2:
        return None  # no real pullback (need 2+ bull bars before the bear resumption)

    # --- Gate 4: NOT at spike bottom + must be near recent high ---
    if features.is_at_5bar_low and features.consecutive_bear >= 3:
        return None
    if features.bars_since_5bar_high > 3:
        return None  # too far from the pullback high

    # --- Gate 5: Price near EMA ---
    if features.atr_14 <= 0:
        return None
    ema_distance_atr = abs(features.price_vs_ema) / 100 * features.candle.close / features.atr_14
    if ema_distance_atr > 2.0:
        return None

    # --- Gate 6: Volatility alive ---
    if features.atr_contracting:
        return None

    # --- Gate 7: Signal bar quality ---
    if current.body_pct < 30:
        return None

    # --- Structural stop and target ---
    if features.last_swing_high is None or features.last_swing_high <= 0:
        stop = current.close + features.atr_14 * 1.5
    else:
        stop = features.last_swing_high * 1.001  # 0.1% buffer above swing high

    risk = stop - current.close
    if risk <= 0:
        return None

    if risk / current.close < 0.005:
        return None

    target = current.close - risk * 1.5

    # --- Confidence scoring ---
    conf = 60
    if features.consecutive_bear >= 2 and bull_count >= 2:
        conf += 10
    if features.is_touching_ema:
        conf += 5
    if features.tf_1h_direction == "down":
        conf += 5
    if features.volume_ratio > 1.2:
        conf += 5

    return DetectedSetup(
        setup_id="low_2_pullback_ma_bear",
        setup_type=SetupType.SECOND_ENTRY_H2,  # reuses the same enum
        action=Action.VENDA,
        confidence=min(conf, 95),
        entry=current.close,
        stop=stop,
        target=target,
        reasoning=(
            f"L2 short: pullback ({bull_count} bull bars) in LH/LL structure, "
            f"resumption bear bar, price {ema_distance_atr:.1f} ATR from EMA20, "
            f"stop at swing high ${stop:.0f}, target ${target:.0f} (R:R 2.0)"
        ),
        decisive_factor="pullback_resumption_in_downtrend",
        priority=70,
    )
