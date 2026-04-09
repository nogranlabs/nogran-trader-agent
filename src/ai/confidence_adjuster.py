import logging

from domain.enums import Action, Regime
from domain.models import FeatureSnapshot, TradeResult, TradeSignal

logger = logging.getLogger(__name__)


def adjust_confidence(
    signal: TradeSignal,
    features: FeatureSnapshot,
    regime: Regime,
    recent_trades: list[TradeResult],
) -> int:
    """
    Adjust LLM confidence based on factors the LLM doesn't have access to.
    Returns adjusted confidence (0-100).
    """
    confidence = float(signal.confidence)

    # Regime alignment
    trending_setups = {"second_entry_H2", "breakout_pullback", "shaved_bar"}
    if regime == Regime.TRENDING and signal.setup.value in trending_setups:
        confidence += 10
    elif regime == Regime.TRANSITIONING:
        confidence -= 15
    elif regime == Regime.RANGING and signal.setup.value in trending_setups:
        confidence -= 10

    # Multi-TF confirmation
    if features.tf_5m_direction is not None:
        signal_dir = "ALTA" if signal.action == Action.COMPRA else "BAIXA"
        if features.tf_5m_direction == signal_dir:
            confidence += 10
        else:
            confidence -= 15

    # Volume
    if features.volume_ratio > 1.2:
        confidence += 5
    elif features.volume_ratio < 0.5:
        confidence -= 10

    # ATR dynamics
    if features.atr_expanding:
        confidence += 5
    elif features.atr_contracting:
        confidence -= 10

    # Revenge trade penalty
    if recent_trades:
        last = recent_trades[-1]
        if last.pnl < 0 and last.side == ("buy" if signal.action == Action.COMPRA else "sell"):
            confidence -= 10

    # Session
    if not features.is_peak_session:
        confidence -= 10

    result = max(0, min(100, int(confidence)))
    logger.info(f"Confidence adjusted: {signal.confidence} -> {result} (regime={regime.value})")
    return result


def calculate_ao_score(
    signal: TradeSignal,
    features: FeatureSnapshot,
    regime: Regime,
    recent_trades: list[TradeResult],
) -> int:
    """
    AI Overlay Score (0-100).
    Based on regime alignment, multi-TF, volume, and behavioral filters.
    """
    score = 70.0  # Neutral base

    # Regime alignment
    trending_setups = {"second_entry_H2", "breakout_pullback", "shaved_bar"}
    if regime == Regime.TRENDING and signal.setup.value in trending_setups:
        score += 15
    elif regime == Regime.TRENDING and signal.action == Action.VENDA and signal.setup.value not in trending_setups:
        score -= 15
    elif regime == Regime.TRANSITIONING:
        score -= 20

    # Multi-TF
    if features.tf_5m_direction is not None:
        signal_dir = "ALTA" if signal.action == Action.COMPRA else "BAIXA"
        if features.tf_5m_direction == signal_dir:
            score += 10
        else:
            score -= 15

    # Volume
    if features.volume_ratio > 1.2:
        score += 5
    elif features.volume_ratio < 0.5:
        score -= 10

    # ATR
    if features.atr_expanding:
        score += 5
    elif features.atr_contracting:
        score -= 10

    # Revenge trade
    if recent_trades:
        last = recent_trades[-1]
        if last.pnl < 0 and last.side == ("buy" if signal.action == Action.COMPRA else "sell"):
            score -= 10

    # Overtrading (simple check)
    trades_last_hour = sum(1 for t in recent_trades if t.age_minutes < 60) if recent_trades else 0
    if trades_last_hour >= 3:
        score -= 15
    elif trades_last_hour >= 2:
        score -= 5

    return max(0, min(100, int(score)))
