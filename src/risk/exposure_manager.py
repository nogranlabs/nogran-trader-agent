import logging
import time

from infra.config import Config

logger = logging.getLogger(__name__)


class ExposureManager:
    """Controls position limits, cooldowns, and max time in position."""

    def __init__(self):
        self.has_open_position: bool = False
        self.position_entry_candle: int = 0
        self.last_trade_candle: int = 0
        self.trades_this_hour: list[float] = []  # timestamps

    def can_open_position(self, current_candle_index: int) -> tuple[bool, str]:
        """Check if we can open a new position."""
        if self.has_open_position:
            return False, "Position already open"

        # Cooldown check
        candles_since_last = current_candle_index - self.last_trade_candle
        if candles_since_last < Config.COOLDOWN_CANDLES:
            return False, f"Cooldown: {candles_since_last}/{Config.COOLDOWN_CANDLES} candles"

        # Hourly trade limit
        now = time.time()
        self.trades_this_hour = [t for t in self.trades_this_hour if now - t < 3600]
        if len(self.trades_this_hour) >= Config.MAX_TRADES_PER_HOUR:
            return False, f"Max trades/hour reached ({Config.MAX_TRADES_PER_HOUR})"

        return True, "OK"

    def on_position_opened(self, candle_index: int):
        self.has_open_position = True
        self.position_entry_candle = candle_index
        self.trades_this_hour.append(time.time())

    def on_position_closed(self, candle_index: int):
        self.has_open_position = False
        self.last_trade_candle = candle_index

    def should_force_close(self, current_candle_index: int) -> bool:
        """Check if position exceeded max time."""
        if not self.has_open_position:
            return False
        candles_in_position = current_candle_index - self.position_entry_candle
        if candles_in_position >= Config.MAX_POSITION_TIME_CANDLES:
            logger.warning(f"Position exceeded max time: {candles_in_position} candles")
            return True
        return False
