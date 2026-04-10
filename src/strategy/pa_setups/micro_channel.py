"""
Micro channel detector — tight trend continuation with small pullbacks.

KB setup: micro_channel_with_trend (probability 70% — highest in the KB!)

A micro channel is a tight, orderly trend where:
- Most bars overlap (controlled advance, not a spike)
- No large counter-trend bars (pullbacks are tiny)
- Price stays near EMA20 (within 1 ATR)
- ADX is moderate to high (trend has structure)

This is the "small pullback trend" — the market grinds in one direction
with minimal pullbacks. Each small dip to EMA is a buy (in uptrend) or
each small rally to EMA is a sell (in downtrend).

CONDITIONS (long micro channel):
  1. Uptrend: HH_HL structure OR always-in long
  2. Tight channel: bar_overlap_ratio 0.3–0.55 (orderly, not choppy)
  3. Price near EMA: within 1 ATR
  4. EMA slope positive
  5. Current bar touching or just bounced from EMA
  6. ADX > 20 (trend has structure)
  7. HTF aligned

STOP: EMA20 - 1 ATR (below the mean)
TARGET: entry + 1.5× risk (conservative — channels don't spike)
"""

from __future__ import annotations

from typing import Optional

from domain.enums import Action, SetupType
from domain.models import FeatureSnapshot
from strategy.pa_setups import DetectedSetup


def detect_micro_channel_long(features: FeatureSnapshot) -> Optional[DetectedSetup]:
    """Detect a long entry in a micro channel (tight uptrend)."""

    # --- Gate 1: Uptrend structure ---
    if features.structure_classification not in ("HH_HL",):
        if features.computed_always_in != "SEMPRE_COMPRADO":
            return None

    # --- Gate 2: Tight channel (moderate overlap = orderly, not chop) ---
    overlap = features.bar_overlap_ratio
    if overlap < 0.25 or overlap > 0.55:
        return None  # too spiky (no overlap) or too choppy

    # --- Gate 3: Price near EMA ---
    if features.atr_14 <= 0:
        return None
    ema_dist_atr = abs(features.price_vs_ema) / 100 * features.candle.close / features.atr_14
    if ema_dist_atr > 1.0:
        return None  # too far from EMA

    # --- Gate 4: EMA slope positive ---
    if features.ema_slope_direction != "up":
        return None

    # --- Gate 5: Touching or near EMA (pullback to mean) ---
    if not features.is_touching_ema and features.bars_since_ema_test > 2:
        return None  # not currently testing EMA

    # --- Gate 6: ADX showing trend ---
    if features.adx_14 < 20:
        return None

    # --- Gate 7: HTF aligned ---
    if features.tf_1h_direction is not None and features.tf_1h_direction != "up":
        return None

    # --- Gate 8: Current bar should be bullish (bounce from EMA) ---
    if not features.candle.is_bullish:
        return None

    candle = features.candle

    # Stop below EMA by 1 ATR
    stop = features.ema_20 - features.atr_14
    risk = candle.close - stop
    if risk <= 0 or risk / candle.close < 0.003:
        return None

    target = candle.close + risk * 1.5  # conservative for channel

    conf = 65
    if features.is_touching_ema:
        conf += 10  # textbook EMA bounce
    if features.adx_14 > 30:
        conf += 5  # strong trend
    if features.tf_1h_direction == "up":
        conf += 5

    return DetectedSetup(
        setup_id="micro_channel_with_trend",
        setup_type=SetupType.H2_EMA,
        action=Action.COMPRA,
        confidence=min(conf, 90),
        entry=candle.close,
        stop=stop,
        target=target,
        reasoning=(
            f"Micro channel long: tight uptrend (overlap {overlap:.2f}), "
            f"EMA bounce ({ema_dist_atr:.1f} ATR away), ADX {features.adx_14:.0f}, "
            f"stop below EMA ${stop:.0f}, target ${target:.0f} (R:R 1.5)"
        ),
        decisive_factor="tight_channel_ema_bounce",
        priority=75,  # high priority — 70% KB probability
    )


def detect_micro_channel_short(features: FeatureSnapshot) -> Optional[DetectedSetup]:
    """Detect a short entry in a micro channel (tight downtrend)."""

    if features.structure_classification not in ("LH_LL",):
        if features.computed_always_in != "SEMPRE_VENDIDO":
            return None

    overlap = features.bar_overlap_ratio
    if overlap < 0.25 or overlap > 0.55:
        return None

    if features.atr_14 <= 0:
        return None
    ema_dist_atr = abs(features.price_vs_ema) / 100 * features.candle.close / features.atr_14
    if ema_dist_atr > 1.0:
        return None

    if features.ema_slope_direction != "down":
        return None

    if not features.is_touching_ema and features.bars_since_ema_test > 2:
        return None

    if features.adx_14 < 20:
        return None

    if features.tf_1h_direction is not None and features.tf_1h_direction != "down":
        return None

    if features.candle.is_bullish:
        return None  # need bear bar (rejection from EMA)

    candle = features.candle
    stop = features.ema_20 + features.atr_14
    risk = stop - candle.close
    if risk <= 0 or risk / candle.close < 0.003:
        return None

    target = candle.close - risk * 1.5

    conf = 65
    if features.is_touching_ema:
        conf += 10
    if features.adx_14 > 30:
        conf += 5
    if features.tf_1h_direction == "down":
        conf += 5

    return DetectedSetup(
        setup_id="micro_channel_with_trend",
        setup_type=SetupType.H2_EMA,
        action=Action.VENDA,
        confidence=min(conf, 90),
        entry=candle.close,
        stop=stop,
        target=target,
        reasoning=(
            f"Micro channel short: tight downtrend (overlap {overlap:.2f}), "
            f"EMA rejection ({ema_dist_atr:.1f} ATR away), ADX {features.adx_14:.0f}, "
            f"stop above EMA ${stop:.0f}, target ${target:.0f} (R:R 1.5)"
        ),
        decisive_factor="tight_channel_ema_rejection",
        priority=75,
    )
