import logging
from datetime import datetime, timezone

from domain.models import FeatureSnapshot
from infra.config import Config

logger = logging.getLogger(__name__)


def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


# ============================================================
# SESSION MODE
# ============================================================

def get_session_mode(now_utc: datetime | None = None) -> str:
    """
    Determine trading session mode based on UTC time and day of week.

    Returns: "AGGRESSIVE", "CONSERVATIVE", or "OBSERVATION"

    Schedule:
      Monday-Friday:
        13:30-21:00 UTC  →  AGGRESSIVE  (NY session — peak volume)
        07:00-13:30 UTC  →  CONSERVATIVE (London — only best setups)
        21:00-07:00 UTC  →  OBSERVATION  (Asia/transition — no trading)

      Saturday-Sunday:
        07:00-21:00 UTC  →  CONSERVATIVE (reduced activity, only best setups)
        21:00-07:00 UTC  →  OBSERVATION  (no trading)
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    hour = now_utc.hour + now_utc.minute / 60.0  # e.g. 13:30 = 13.5
    is_weekend = now_utc.weekday() >= 5  # Saturday=5, Sunday=6

    if is_weekend:
        if Config.CONSERVATIVE_START <= hour < Config.AGGRESSIVE_END:
            return "CONSERVATIVE"
        else:
            return "OBSERVATION"
    else:
        if Config.AGGRESSIVE_START <= hour < Config.AGGRESSIVE_END:
            return "AGGRESSIVE"
        elif Config.CONSERVATIVE_START <= hour < Config.AGGRESSIVE_START:
            return "CONSERVATIVE"
        else:
            return "OBSERVATION"


def get_session_threshold(session_mode: str) -> int:
    """Get Decision Score threshold for current session."""
    if session_mode == "AGGRESSIVE":
        return Config.AGGRESSIVE_THRESHOLD
    elif session_mode == "CONSERVATIVE":
        return Config.CONSERVATIVE_THRESHOLD
    else:
        return 999  # Observation — never trade


def get_session_sizing_mult(session_mode: str) -> float:
    """Get position sizing multiplier for current session."""
    if session_mode == "AGGRESSIVE":
        return Config.AGGRESSIVE_SIZING_MULT
    elif session_mode == "CONSERVATIVE":
        return Config.CONSERVATIVE_SIZING_MULT
    else:
        return 0.0


def is_setup_allowed(setup: str, session_mode: str) -> bool:
    """Check if a setup type is allowed in the current session."""
    if session_mode == "AGGRESSIVE":
        return True  # All setups allowed
    elif session_mode == "CONSERVATIVE":
        return setup in Config.CONSERVATIVE_SETUPS
    else:
        return False


# ============================================================
# MARKET QUALITY SCORE
# ============================================================

def calculate_mq_score(features: FeatureSnapshot) -> int:
    """
    Market Quality Score (0-100).
    High score = good trading conditions. Low score = chop/dead market.
    """
    score = 100.0

    # Chop penalty: bar overlap
    if features.bar_overlap_ratio > 0.7:
        score -= 40
    elif features.bar_overlap_ratio > 0.5:
        score -= 20

    # Volatility: ATR relative to average
    if features.atr_ratio < 0.5:
        score -= 30  # Dead market
    elif features.atr_ratio < 0.8:
        score -= 15  # Low volatility

    # Direction noise: too many direction changes
    if features.direction_change_ratio > 0.6:
        score -= 20

    # Peak session bonus
    if features.is_peak_session:
        score += 10

    # ADX: clear trend strongly preferred (only trade when trend is real)
    # Empirical: in v1.4 backtest 2026-04-09 every losing trade had ADX < 25
    # (chop misread as trend by the LLM). Hard cap below 20.
    if features.adx_14 > 30:
        score += 10
    elif features.adx_14 < 25:
        score -= 15

    result = int(clamp(score, 0, 100))

    # Hard cap: no real trend → cannot pass default pre-filter (50). Rule:
    # teaches "do not trade in random walk" — if ADX < 20 the market is
    # statistically a random walk and no setup is reliable.
    if features.adx_14 < 20:
        result = min(result, 40)
    logger.info(f"MQ Score: {result} (overlap={features.bar_overlap_ratio:.2f}, atr_ratio={features.atr_ratio:.2f}, adx={features.adx_14:.1f})")
    return result
