"""Pure math indicator functions. No classes, no state, no I/O."""


def sma(values: list[float], period: int) -> float:
    """Simple moving average of the last `period` values."""
    if not values or period <= 0:
        return 0.0
    window = values[-period:]
    if not window:
        return 0.0
    return sum(window) / len(window)


def ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average — returns the full EMA series.

    Uses SMA of the first `period` values as the seed, then applies the
    standard EMA formula for the remaining values.
    """
    if not values or period <= 0:
        return []
    if len(values) < period:
        # Not enough data for a proper seed; return SMA per point as fallback.
        running = []
        for i in range(len(values)):
            running.append(sum(values[: i + 1]) / (i + 1))
        return running

    k = 2.0 / (period + 1)
    result: list[float] = []

    # Seed: SMA of first `period` values
    seed = sum(values[:period]) / period
    # Fill the first `period - 1` entries with NaN-like placeholder? No — keep
    # the series the same length as input by back-filling with partial SMAs.
    for i in range(period):
        result.append(sum(values[: i + 1]) / (i + 1))
    result[period - 1] = seed  # exact SMA at the seed point

    # EMA from period onward
    prev = seed
    for i in range(period, len(values)):
        val = values[i] * k + prev * (1 - k)
        result.append(val)
        prev = val

    return result


def ema_current(values: list[float], period: int) -> float:
    """Latest EMA value."""
    series = ema(values, period)
    if not series:
        return 0.0
    return series[-1]


# ---------------------------------------------------------------------------
# ATR helpers
# ---------------------------------------------------------------------------

def _true_ranges(candles: list[tuple]) -> list[float]:
    """Compute true-range series from (high, low, close) candles."""
    if not candles:
        return []
    trs: list[float] = []
    for i, (h, l, _c) in enumerate(candles):
        if i == 0:
            trs.append(h - l)
        else:
            prev_close = candles[i - 1][2]
            trs.append(max(h - l, abs(h - prev_close), abs(l - prev_close)))
    return trs


def atr_series(candles: list[tuple], period: int = 14) -> list[float]:
    """Full ATR series using Wilder smoothing (RMA).

    Returns a list the same length as candles. Entries before enough data
    are filled with 0.0.
    """
    trs = _true_ranges(candles)
    if not trs or period <= 0:
        return []
    if len(trs) < period:
        # Not enough data — return simple average of available TRs as single point
        return [sum(trs) / len(trs)] * len(trs)

    result = [0.0] * len(trs)

    # Seed: SMA of first `period` true ranges
    seed = sum(trs[:period]) / period
    result[period - 1] = seed

    prev = seed
    for i in range(period, len(trs)):
        val = (prev * (period - 1) + trs[i]) / period
        result[i] = val
        prev = val

    return result


def atr(candles: list[tuple], period: int = 14) -> float:
    """Current (latest) ATR value."""
    series = atr_series(candles, period)
    if not series:
        return 0.0
    return series[-1]


# ---------------------------------------------------------------------------
# ADX
# ---------------------------------------------------------------------------

def adx(candles: list[tuple], period: int = 14) -> float:
    """Average Directional Index from (high, low, close) candles.

    Uses Wilder smoothing for +DM, -DM, TR, and DX.
    """
    if not candles or period <= 0 or len(candles) < period + 1:
        return 0.0

    n = len(candles)

    # Step 1: raw +DM, -DM, TR
    plus_dm_raw: list[float] = []
    minus_dm_raw: list[float] = []
    tr_raw: list[float] = []

    for i in range(1, n):
        h, l, c = candles[i]
        ph, pl, pc = candles[i - 1]

        up_move = h - ph
        down_move = pl - l
        plus_dm_raw.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dm_raw.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        tr_raw.append(max(h - l, abs(h - pc), abs(l - pc)))

    if len(plus_dm_raw) < period:
        return 0.0

    # Step 2: Wilder-smooth +DM, -DM, TR over `period`
    def wilder_smooth(raw: list[float], p: int) -> list[float]:
        result = [0.0] * len(raw)
        result[p - 1] = sum(raw[:p])
        for i in range(p, len(raw)):
            result[i] = result[i - 1] - (result[i - 1] / p) + raw[i]
        return result

    sm_plus_dm = wilder_smooth(plus_dm_raw, period)
    sm_minus_dm = wilder_smooth(minus_dm_raw, period)
    sm_tr = wilder_smooth(tr_raw, period)

    # Step 3: +DI, -DI, DX
    dx_values: list[float] = []
    for i in range(period - 1, len(sm_tr)):
        if sm_tr[i] == 0.0:
            continue
        plus_di = 100.0 * sm_plus_dm[i] / sm_tr[i]
        minus_di = 100.0 * sm_minus_dm[i] / sm_tr[i]
        di_sum = plus_di + minus_di
        if di_sum == 0.0:
            dx_values.append(0.0)
        else:
            dx_values.append(100.0 * abs(plus_di - minus_di) / di_sum)

    if len(dx_values) < period:
        return dx_values[-1] if dx_values else 0.0

    # Step 4: Wilder-smooth DX to get ADX
    adx_val = sum(dx_values[:period]) / period
    for i in range(period, len(dx_values)):
        adx_val = (adx_val * (period - 1) + dx_values[i]) / period

    return adx_val


# ---------------------------------------------------------------------------
# Bar-overlap / choppiness helpers
# ---------------------------------------------------------------------------

def calculate_bar_overlap(candles: list[tuple]) -> float:
    """Ratio 0-1 of how much consecutive bars overlap.

    candles are (high, low) tuples. High overlap = choppy/ranging market.
    Returns the average pairwise overlap ratio.
    """
    if not candles or len(candles) < 2:
        return 0.0

    overlaps: list[float] = []
    for i in range(1, len(candles)):
        h1, l1 = candles[i - 1]
        h2, l2 = candles[i]

        overlap_high = min(h1, h2)
        overlap_low = max(l1, l2)
        overlap = max(0.0, overlap_high - overlap_low)

        combined_range = max(h1, h2) - min(l1, l2)
        if combined_range == 0.0:
            overlaps.append(1.0)
        else:
            overlaps.append(overlap / combined_range)

    return sum(overlaps) / len(overlaps)


# ---------------------------------------------------------------------------
# Consecutive / direction helpers
# ---------------------------------------------------------------------------

def count_consecutive(is_bullish: list[bool]) -> tuple[int, int]:
    """Count consecutive bullish / bearish candles from end of list.

    Returns (consecutive_bull, consecutive_bear). One of them will be 0.
    """
    if not is_bullish:
        return (0, 0)

    last = is_bullish[-1]
    count = 0
    for val in reversed(is_bullish):
        if val == last:
            count += 1
        else:
            break

    if last:
        return (count, 0)
    return (0, count)


def count_direction_changes(is_bullish: list[bool]) -> float:
    """Ratio 0-1 of direction changes in the list.

    A value close to 1.0 means the market alternates direction almost every
    candle (very choppy). Close to 0.0 means sustained trend.
    """
    if not is_bullish or len(is_bullish) < 2:
        return 0.0

    changes = 0
    for i in range(1, len(is_bullish)):
        if is_bullish[i] != is_bullish[i - 1]:
            changes += 1

    return changes / (len(is_bullish) - 1)
