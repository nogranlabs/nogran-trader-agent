"""
Second Attempt detectors — the highest-probability PA setup.

Core rule: "After a failed breakout, the second attempt in the same
direction succeeds ~60% of the time." This is the most reliable setup
in the entire methodology.

The feature engine already tracks failed breakouts via
`src/market/failed_attempts.py` and exposes:
  - features.second_attempt_long_pending: bool
  - features.second_attempt_short_pending: bool
  - features.bars_since_failed_breakout_up: int (-1 if none)
  - features.bars_since_failed_breakout_down: int (-1 if none)

Our job: when the pending flag is True AND the current bar breaks the
level cleanly, emit the setup.

CONDITIONS (long second attempt):
  1. features.second_attempt_long_pending == True
  2. Current bar is bullish (breaking upward)
  3. bars_since_failed_breakout_up in [1..5] (recent enough)
  4. Body > 30% (not a doji — real conviction)
  5. HTF not against us (tf_1h_direction != "down")

STOP: last_swing_low or entry - 1.5 ATR (whichever is closer)
TARGET: entry + 2× risk (high-probability setup = can aim for 2R)
"""

from __future__ import annotations

from typing import Optional

from domain.enums import Action, SetupType
from domain.models import FeatureSnapshot
from strategy.pa_setups import DetectedSetup


def detect_second_attempt_long(features: FeatureSnapshot) -> Optional[DetectedSetup]:
    """Detect a long second attempt after a failed upward breakout."""

    if not features.second_attempt_long_pending:
        return None

    bars_since = features.bars_since_failed_breakout_up
    if bars_since < 0 or bars_since > 10:
        return None  # too old or not detected (relaxed from 5 to 10 — second
                     # attempts can develop over 6-10 bars in crypto 15m)

    candle = features.candle
    if not candle.is_bullish:
        return None  # need a bull bar to confirm the second push

    if candle.body_pct < 30:
        return None  # doji — weak conviction

    # HTF gate: don't buy second attempt into bearish HTF
    if features.tf_1h_direction is not None and features.tf_1h_direction == "down":
        return None

    # Stop: swing low or ATR-based, whichever is tighter
    if features.last_swing_low and features.last_swing_low > 0:
        structural_stop = features.last_swing_low * 0.999
        atr_stop = candle.close - features.atr_14 * 1.5
        stop = max(structural_stop, atr_stop)  # tighter of the two
    else:
        stop = candle.close - features.atr_14 * 1.5

    risk = candle.close - stop
    if risk <= 0 or risk / candle.close < 0.003:
        return None

    target = candle.close + risk * 1.5

    # Confidence: high base because this is the #1 setup
    conf = 70
    if bars_since <= 2:
        conf += 5  # very recent failed attempt = stronger
    if features.structure_classification == "HH_HL":
        conf += 5  # aligned with uptrend structure
    if candle.body_pct > 60:
        conf += 5  # strong signal bar

    return DetectedSetup(
        setup_id="high_2_pullback_ma_bull",  # maps to the H2 KB entry
        setup_type=SetupType.SECOND_ENTRY_H2,
        action=Action.COMPRA,
        confidence=min(conf, 95),
        entry=candle.close,
        stop=stop,
        target=target,
        reasoning=(
            f"Second attempt long: failed breakout up {bars_since} bars ago, "
            f"now retrying with bull bar (body {candle.body_pct:.0f}%), "
            f"stop ${stop:.0f}, target ${target:.0f} (R:R 2.0)"
        ),
        decisive_factor="second_attempt_after_failed_breakout",
        priority=80,  # highest priority — this is the #1 setup
    )


def detect_second_attempt_short(features: FeatureSnapshot) -> Optional[DetectedSetup]:
    """Detect a short second attempt after a failed downward breakout."""

    if not features.second_attempt_short_pending:
        return None

    bars_since = features.bars_since_failed_breakout_down
    if bars_since < 0 or bars_since > 10:
        return None  # relaxed from 5 to 10

    candle = features.candle
    if candle.is_bullish:
        return None  # need a bear bar

    if candle.body_pct < 30:
        return None

    # HTF gate
    if features.tf_1h_direction is not None and features.tf_1h_direction == "up":
        return None

    # Stop: swing high or ATR-based
    if features.last_swing_high and features.last_swing_high > 0:
        structural_stop = features.last_swing_high * 1.001
        atr_stop = candle.close + features.atr_14 * 1.5
        stop = min(structural_stop, atr_stop)  # tighter
    else:
        stop = candle.close + features.atr_14 * 1.5

    risk = stop - candle.close
    if risk <= 0 or risk / candle.close < 0.003:
        return None

    target = candle.close - risk * 1.5

    conf = 70
    if bars_since <= 2:
        conf += 5
    if features.structure_classification == "LH_LL":
        conf += 5
    if candle.body_pct > 60:
        conf += 5

    return DetectedSetup(
        setup_id="low_2_pullback_ma_bear",
        setup_type=SetupType.SECOND_ENTRY_H2,
        action=Action.VENDA,
        confidence=min(conf, 95),
        entry=candle.close,
        stop=stop,
        target=target,
        reasoning=(
            f"Second attempt short: failed breakout down {bars_since} bars ago, "
            f"now retrying with bear bar (body {candle.body_pct:.0f}%), "
            f"stop ${stop:.0f}, target ${target:.0f} (R:R 2.0)"
        ),
        decisive_factor="second_attempt_after_failed_breakout",
        priority=80,
    )
