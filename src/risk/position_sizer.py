import logging

from domain.models import DecisionScore
from infra.config import Config
from risk.drawdown_controller import DrawdownController
from risk.metrics import RiskMetrics

logger = logging.getLogger(__name__)


def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


def map_range(value: float, in_min: float, in_max: float, out_min: float, out_max: float) -> float:
    """Map value from one range to another, clamped."""
    value = clamp(value, in_min, in_max)
    return out_min + (value - in_min) * (out_max - out_min) / (in_max - in_min)


class PositionSizer:
    """
    Dynamic position sizing: ATR-based risk + Decision Score + Drawdown.
    """

    def __init__(self, dd_controller: DrawdownController):
        self.dd_controller = dd_controller

    def calculate(
        self,
        capital: float,
        atr: float,
        decision_score: DecisionScore,
        metrics: RiskMetrics,
    ) -> float:
        """
        Calculate position size in base currency units.
        Risk per trade is constant in dollar terms, adjusted by score and drawdown.
        """
        if atr <= 0:
            logger.warning("ATR is zero, cannot calculate position size")
            return 0.0

        # 1. Base risk in dollars
        risk_dollars = capital * Config.RISK_PER_TRADE

        # 2. Stop distance (ATR-based)
        stop_distance = atr * Config.ATR_STOP_MULTIPLIER

        # 3. Score multiplier (65-95 mapped to 0.6-1.0)
        score_mult = map_range(decision_score.total, 65, 95, 0.6, 1.0)

        # 4. Drawdown multiplier
        band = self.dd_controller.get_band(metrics.current_drawdown)
        dd_mult = self.dd_controller.get_sizing_multiplier(band)

        # 5. Final size
        base_size = risk_dollars / stop_distance
        position_size = base_size * score_mult * dd_mult

        # Clamp to reasonable bounds (min 0.0001 BTC, max 10% of capital in BTC equiv)
        min_size = 0.0001
        max_size = capital * 0.1 / (atr * 10) if atr > 0 else 1.0  # rough upper bound

        result = clamp(position_size, min_size, max_size)

        logger.info(
            f"Position size: {result:.6f} "
            f"(risk=${risk_dollars:.2f}, stop_dist=${stop_distance:.2f}, "
            f"score_mult={score_mult:.2f}, dd_mult={dd_mult:.2f}, band={band.value})"
        )
        return result
