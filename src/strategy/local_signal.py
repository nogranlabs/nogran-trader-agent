"""
Local signal generator v2 — rule-based PA setup detection WITHOUT LLM.

Uses deterministic detectors from src/strategy/pa_setups/ to identify
setups from the Nogran PA methodology. Each detector is a pure function
over FeatureSnapshot that returns a DetectedSetup or None.

Two modes:
  STRATEGY_SOURCE=mock  → main.py calls generate_local_signal() directly
  STRATEGY_SOURCE=python_llm → backtest.py uses this as pre-filter; if
    a detector fires, calls LLM to confirm

Replaces the old naive heuristics (consecutive_bull + body_pct) with
actual pattern recognition (pullback structure, swing context, HTF
alignment, climactic exhaustion).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from domain.enums import Action, AlwaysIn, DayType, Regime, SetupType, SignalBarQuality
from domain.models import FeatureSnapshot, TradeSignal
from strategy.pa_setups import DetectedSetup
from strategy.pa_setups.h2_long import detect_h2_long
from strategy.pa_setups.l2_short import detect_l2_short
from strategy.pa_setups.climactic_fade import (
    detect_climactic_long_fade,
    detect_climactic_short_fade,
)


# All detectors, in evaluation order. Each returns DetectedSetup | None.
DETECTORS = [
    detect_h2_long,
    detect_l2_short,
    detect_climactic_long_fade,
    detect_climactic_short_fade,
]


def detect_local_regime(features: FeatureSnapshot) -> Regime:
    """Simple regime detector without ML."""
    if features.adx_14 >= 25 and features.bar_overlap_ratio < 0.45:
        return Regime.TRENDING
    if features.bar_overlap_ratio > 0.55:
        return Regime.RANGING
    return Regime.TRANSITIONING


def generate_local_signal(
    features: FeatureSnapshot,
    regime: Regime | None = None,
    strict_trend_alignment: bool = True,
) -> TradeSignal:
    """Generate a TradeSignal using rule-based PA detectors (no LLM).

    Runs ALL detectors against the current FeatureSnapshot, collects
    matches, picks the best by (priority, confidence), and returns it
    as a TradeSignal. If no detector fires, returns AGUARDAR.
    """
    if regime is None:
        regime = detect_local_regime(features)

    # Run all detectors
    hits: list[DetectedSetup] = []
    for fn in DETECTORS:
        try:
            result = fn(features)
            if result is not None:
                hits.append(result)
        except Exception:
            pass  # detector failure = skip, don't crash the pipeline

    if not hits:
        return _aguardar(features)

    # Pick best by (priority desc, confidence desc)
    best = max(hits, key=lambda s: (s.priority, s.confidence))

    # Map DetectedSetup → TradeSignal
    return TradeSignal(
        action=best.action,
        confidence=best.confidence,
        day_type=_infer_day_type(features),
        always_in=_infer_always_in(features),
        setup=best.setup_type,
        signal_bar_quality=SignalBarQuality.APROVADO,
        entry_price=best.entry,
        stop_loss=best.stop,
        take_profit=best.target,
        decisive_layer=5,
        reasoning=best.reasoning,
        timestamp=datetime.now(timezone.utc),
    )


def _aguardar(features: FeatureSnapshot) -> TradeSignal:
    c = features.candle
    return TradeSignal(
        action=Action.AGUARDAR,
        confidence=20,
        day_type=_infer_day_type(features),
        always_in=_infer_always_in(features),
        setup=SetupType.NONE,
        signal_bar_quality=SignalBarQuality.REPROVADO,
        entry_price=c.close,
        stop_loss=c.close,
        take_profit=c.close,
        decisive_layer=1,
        reasoning="No PA detector fired on this candle.",
        timestamp=datetime.now(timezone.utc),
    )


def _infer_day_type(features: FeatureSnapshot) -> DayType:
    """Best-effort day type from features (no LLM)."""
    if features.regime == "trending_up" or features.regime == "trending_down":
        if features.consecutive_bull >= 4 or features.consecutive_bear >= 4:
            return DayType.TREND_FROM_OPEN
        return DayType.SPIKE_AND_CHANNEL
    if features.regime == "range":
        return DayType.TRENDING_TRADING_RANGE
    return DayType.INDEFINIDO


def _infer_always_in(features: FeatureSnapshot) -> AlwaysIn:
    """Map computed_always_in string → enum."""
    ai = features.computed_always_in
    if ai == "SEMPRE_COMPRADO":
        return AlwaysIn.SEMPRE_COMPRADO
    if ai == "SEMPRE_VENDIDO":
        return AlwaysIn.SEMPRE_VENDIDO
    return AlwaysIn.NEUTRO
