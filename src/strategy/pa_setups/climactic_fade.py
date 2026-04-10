"""
Climactic fade detectors — fade exhaustion moves.

A "climax" is a large trend bar at the END of a move. The exhaustion is
signalled by the bar being significantly larger than ATR (range > 1.5x ATR)
with strong momentum (body > 60%). The FADE is the reversal that follows.

Two variants:
  - detect_climactic_long_fade: after a bearish climax → BUY fade
  - detect_climactic_short_fade: after a bullish climax → SELL fade

CONDITIONS (long fade after bear climax):
  1. Recent bear climax: one of the last 3 bars is a BEAR bar with
     range > 1.5 ATR AND body_pct > 60%
  2. Current bar shows reversal intent: is bullish OR has long lower tail
  3. Structure allows reversal: NOT in strong downtrend (LH_LL with high ADX)
  4. HTF not strongly against us
  5. Price at or near 5-bar low (we're buying the dip)

STOP: low of the climax bar - 0.1% buffer
TARGET: entry + 1.5× risk (conservative R:R since we're fading)
"""

from __future__ import annotations

from typing import Optional

from domain.enums import Action, SetupType
from domain.models import FeatureSnapshot
from strategy.pa_setups import DetectedSetup


def detect_climactic_long_fade(features: FeatureSnapshot) -> Optional[DetectedSetup]:
    """Detect a long fade after a bearish climax."""

    bars = features.recent_bars
    if len(bars) < 3:
        return None

    current = bars[-1]

    # --- Gate 1: Find a bear climax in the last 3 bars ---
    climax_bar = None
    for b in bars[-3:]:
        bar_range = b.high - b.low
        if (not b.is_bullish
                and bar_range > features.atr_14 * 1.2
                and b.body_pct > 50):
            climax_bar = b

    if climax_bar is None:
        return None

    # --- Gate 2: Current bar shows reversal intent ---
    reversal_intent = current.is_bullish or current.lower_tail_pct > 40
    if not reversal_intent:
        return None

    # --- Gate 3: NOT in strong confirmed downtrend ---
    if (features.structure_classification == "LH_LL"
            and features.adx_14 > 30
            and features.tf_1h_direction == "down"):
        return None  # trend is too strong to fade

    # --- Gate 4: Price near 5-bar low ---
    if not features.is_at_5bar_low and features.bars_since_5bar_low > 2:
        return None  # climax was a while ago, already bounced

    # --- Stop and target ---
    climax_low = climax_bar.low
    stop = climax_low * 0.999  # just below the climax bar
    risk = current.close - stop
    if risk <= 0:
        return None
    if risk / current.close < 0.003:
        return None  # too tight

    target = current.close + risk * 1.5  # conservative 1.5R

    # --- Confidence ---
    conf = 55  # lower than trend setups (we're counter-trend)
    if current.is_bullish and current.body_pct > 50:
        conf += 10  # strong reversal bar
    if features.consecutive_bear >= 3:
        conf += 5  # deep exhaustion (3+ bear bars before reversal)
    if features.volume_ratio > 1.3:
        conf += 5  # climax volume

    return DetectedSetup(
        setup_id="fade_sell_climax",
        setup_type=SetupType.BREAKOUT_PULLBACK,
        action=Action.COMPRA,
        confidence=min(conf, 85),
        entry=current.close,
        stop=stop,
        target=target,
        reasoning=(
            f"Climactic long fade: bear climax bar range {climax_bar.high - climax_bar.low:.0f} > "
            f"1.5x ATR {features.atr_14:.0f}, reversal bar forming, "
            f"stop below climax ${stop:.0f}, target ${target:.0f} (R:R 1.5)"
        ),
        decisive_factor="bear_climax_exhaustion",
        priority=60,
    )


def detect_climactic_short_fade(features: FeatureSnapshot) -> Optional[DetectedSetup]:
    """Detect a short fade after a bullish climax."""

    bars = features.recent_bars
    if len(bars) < 3:
        return None

    current = bars[-1]

    # --- Gate 1: Find a bull climax in the last 3 bars ---
    climax_bar = None
    for b in bars[-3:]:
        bar_range = b.high - b.low
        if (b.is_bullish
                and bar_range > features.atr_14 * 1.2
                and b.body_pct > 50):
            climax_bar = b

    if climax_bar is None:
        return None

    # --- Gate 2: Current bar shows reversal intent ---
    reversal_intent = not current.is_bullish or current.upper_tail_pct > 40
    if not reversal_intent:
        return None

    # --- Gate 3: NOT in strong confirmed uptrend ---
    if (features.structure_classification == "HH_HL"
            and features.adx_14 > 30
            and features.tf_1h_direction == "up"):
        return None

    # --- Gate 4: Price near 5-bar high ---
    if not features.is_at_5bar_high and features.bars_since_5bar_high > 2:
        return None

    # --- Stop and target ---
    climax_high = climax_bar.high
    stop = climax_high * 1.001
    risk = stop - current.close
    if risk <= 0:
        return None
    if risk / current.close < 0.003:
        return None

    target = current.close - risk * 1.5

    # --- Confidence ---
    conf = 55
    if not current.is_bullish and current.body_pct > 50:
        conf += 10
    if features.consecutive_bull >= 3:
        conf += 5
    if features.volume_ratio > 1.3:
        conf += 5

    return DetectedSetup(
        setup_id="fade_buy_climax",
        setup_type=SetupType.BREAKOUT_PULLBACK,
        action=Action.VENDA,
        confidence=min(conf, 85),
        entry=current.close,
        stop=stop,
        target=target,
        reasoning=(
            f"Climactic short fade: bull climax bar range {climax_bar.high - climax_bar.low:.0f} > "
            f"1.5x ATR {features.atr_14:.0f}, reversal bar forming, "
            f"stop above climax ${stop:.0f}, target ${target:.0f} (R:R 1.5)"
        ),
        decisive_factor="bull_climax_exhaustion",
        priority=60,
    )
