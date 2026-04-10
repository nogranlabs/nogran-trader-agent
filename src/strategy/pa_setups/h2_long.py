"""
H2 Long detector — Second Entry pullback buy in an uptrend.

The H2 is the single most important setup in price action methodology:
"After a spike up, wait for a 1-2 bar pullback, then buy the resumption."

CONDITIONS (all must be true):
  1. HTF context bullish: tf_1h_direction == "up" OR tf_1h_above_ema
  2. Local structure bullish: structure_classification in {HH_HL} OR
     computed_always_in == SEMPRE_COMPRADO
  3. Recent pullback visible: in last 5 bars, at least 1-2 consecutive
     bear bars (the pullback) followed by a bull bar (the resumption)
  4. Current bar is the RESUMPTION bar (bull, moderate body, not at spike top)
  5. Price near EMA20 (within 1.5 ATR) — pullback came close to the mean
  6. NOT at 5-bar high (we're in the dip, not the spike top)
  7. ATR not contracting (volatility alive for the move to happen)

STOP: last_swing_low (structural anchor) with 0.1% buffer below
TARGET: entry + 2× risk (R:R 2.0)
"""

from __future__ import annotations

from typing import Optional

from domain.enums import Action, SetupType
from domain.models import FeatureSnapshot
from strategy.pa_setups import DetectedSetup


def detect_h2_long(features: FeatureSnapshot) -> Optional[DetectedSetup]:
    """Detect an H2 long setup. Returns DetectedSetup or None."""

    # --- Gate 1: HTF must be bullish ---
    # Strict: require 1h direction == "up". Also block if regime is ranging
    # (0W/7L in Window B bear where regime was range/transition).
    if features.tf_1h_direction is not None:
        if features.tf_1h_direction != "up":
            return None  # 1h is not bullish — don't buy
    if features.regime in ("range", "transition"):
        return None  # don't buy pullbacks in range/transition — H2 is a trend setup

    # --- Gate 2: Local structure bullish ---
    structure_ok = (
        features.structure_classification == "HH_HL"
        or features.computed_always_in == "SEMPRE_COMPRADO"
    )
    if not structure_ok:
        return None

    # --- Gate 3: Pullback visible in recent bars ---
    bars = features.recent_bars
    if len(bars) < 4:
        return None

    # Look for pattern: at least 1 bear bar in the last 3-4 bars,
    # with the current (last) bar being bullish = resumption
    current = bars[-1]
    if not current.is_bullish:
        return None  # current bar must be bull (resumption bar)

    # Require 2+ bear bars as pullback (real pullback, not just 1 bar dip).
    # Tightened after d60-70 v2 mock showing 7 losses on H2 longs.
    prev4 = bars[-5:-1] if len(bars) >= 5 else bars[:-1]
    bear_count = sum(1 for b in prev4 if not b.is_bullish)
    if bear_count < 2:
        return None  # no real pullback (need 2+ bear bars before the bull resumption)

    # --- Gate 4: NOT at spike top + must be near recent low ---
    if features.is_at_5bar_high and features.consecutive_bull >= 3:
        return None  # this is a spike top, NOT a pullback resumption
    # The pullback should have created a recent 5-bar low within 3 bars.
    # If bars_since_5bar_low > 3, we're not in the dip anymore.
    if features.bars_since_5bar_low > 3:
        return None  # too far from the pullback low

    # --- Gate 5: Price near EMA (pullback came close to mean) ---
    if features.atr_14 <= 0:
        return None
    ema_distance_atr = abs(features.price_vs_ema) / 100 * features.candle.close / features.atr_14
    if ema_distance_atr > 2.0:
        return None  # price too far from EMA — not a pullback to mean

    # --- Gate 6: Volatility alive ---
    if features.atr_contracting:
        return None  # dying volatility — setup unlikely to reach target

    # --- Gate 7: Signal bar quality ---
    if current.body_pct < 30:
        return None  # doji — weak signal bar

    # --- Structural stop and target ---
    if features.last_swing_low is None or features.last_swing_low <= 0:
        # No swing low detected — fall back to ATR-based stop
        stop = current.close - features.atr_14 * 1.5
    else:
        stop = features.last_swing_low * 0.999  # 0.1% buffer below swing low

    risk = current.close - stop
    if risk <= 0:
        return None  # impossible geometry (swing low above entry)

    # Minimum stop distance check (0.5% of entry)
    if risk / current.close < 0.005:
        return None  # stop too tight — noise territory

    target = current.close + risk * 1.5  # R:R 2.0

    # --- Confidence scoring ---
    conf = 60  # base
    if features.consecutive_bull >= 2 and bear_count >= 2:
        conf += 10  # clean H2 pattern (2 bear, now 2+ bull)
    if features.is_touching_ema:
        conf += 5  # pulled back exactly to EMA = textbook
    if features.tf_1h_direction == "up":
        conf += 5  # HTF confirmation
    if features.volume_ratio > 1.2:
        conf += 5  # volume on resumption bar

    return DetectedSetup(
        setup_id="high_2_pullback_ma_bull",
        setup_type=SetupType.SECOND_ENTRY_H2,
        action=Action.COMPRA,
        confidence=min(conf, 95),
        entry=current.close,
        stop=stop,
        target=target,
        reasoning=(
            f"H2 long: pullback ({bear_count} bear bars) in HH/HL structure, "
            f"resumption bull bar, price {ema_distance_atr:.1f} ATR from EMA20, "
            f"stop at swing low ${stop:.0f}, target ${target:.0f} (R:R 2.0)"
        ),
        decisive_factor="pullback_resumption_in_uptrend",
        priority=70,
    )
