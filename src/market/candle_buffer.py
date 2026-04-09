from collections import deque

from domain.models import Candle


class CandleBuffer:
    """Ring buffer of Candle objects for a single timeframe."""

    def __init__(self, maxlen: int = 100):
        self._candles: deque[Candle] = deque(maxlen=maxlen)
        self._last_timestamp: int | None = None

    def add(self, candle: Candle) -> bool:
        """Add candle. Returns True if it's a NEW candle (new timestamp)."""
        if self._last_timestamp is not None and candle.timestamp <= self._last_timestamp:
            return False
        self._candles.append(candle)
        self._last_timestamp = candle.timestamp
        return True

    @property
    def candles(self) -> list[Candle]:
        return list(self._candles)

    @property
    def latest(self) -> Candle | None:
        return self._candles[-1] if self._candles else None

    @property
    def previous(self) -> Candle | None:
        return self._candles[-2] if len(self._candles) >= 2 else None

    def __len__(self) -> int:
        return len(self._candles)

    def closes(self) -> list[float]:
        return [c.close for c in self._candles]

    def hlc_tuples(self) -> list[tuple[float, float, float]]:
        """Returns list of (high, low, close) for ATR/ADX calculation."""
        return [(c.high, c.low, c.close) for c in self._candles]

    def hl_tuples(self) -> list[tuple[float, float]]:
        """Returns list of (high, low) for overlap calculation."""
        return [(c.high, c.low) for c in self._candles]

    def is_bullish_list(self) -> list[bool]:
        return [c.is_bullish for c in self._candles]

    def volumes(self) -> list[float]:
        return [c.volume for c in self._candles]
