import logging

from domain.enums import DrawdownBand

logger = logging.getLogger(__name__)


class DrawdownController:
    """
    Maps current drawdown to a band that controls sizing and behavior.
    """

    def get_band(self, drawdown: float) -> DrawdownBand:
        if drawdown > 0.08:
            return DrawdownBand.CIRCUIT_BREAKER
        elif drawdown > 0.05:
            return DrawdownBand.MINIMUM
        elif drawdown > 0.03:
            return DrawdownBand.DEFENSIVE
        else:
            return DrawdownBand.NORMAL

    def get_sizing_multiplier(self, band: DrawdownBand) -> float:
        return {
            DrawdownBand.NORMAL: 1.0,
            DrawdownBand.DEFENSIVE: 0.6,
            DrawdownBand.MINIMUM: 0.3,
            DrawdownBand.CIRCUIT_BREAKER: 0.0,
        }[band]

    def is_circuit_breaker(self, band: DrawdownBand) -> bool:
        return band == DrawdownBand.CIRCUIT_BREAKER
