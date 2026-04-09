import logging

from domain.enums import Regime
from domain.models import FeatureSnapshot

logger = logging.getLogger(__name__)


def detect_regime(features: FeatureSnapshot) -> Regime:
    """
    Simplified regime detection using ADX + ATR + overlap.
    Full version would use HMM or more sophisticated analysis.
    """
    adx = features.adx_14
    atr_ratio = features.atr_ratio
    overlap = features.bar_overlap_ratio

    if adx > 25 and atr_ratio > 1.1 and overlap < 0.4:
        regime = Regime.TRENDING
    elif adx < 20 and overlap > 0.6:
        regime = Regime.RANGING
    else:
        regime = Regime.TRANSITIONING

    logger.info(f"Regime: {regime.value} (ADX={adx:.1f}, ATR_ratio={atr_ratio:.2f}, overlap={overlap:.2f})")
    return regime
