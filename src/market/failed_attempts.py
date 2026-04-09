"""Failed breakout / second-attempt detection — "second-entry" rule.

Core rule: after a FAILED attempt to break a key level (swing high or
swing low), the SECOND attempt in the SAME direction succeeds about 60% of the
time. This is one of the highest-probability setups in the entire methodology
("second entry").

A "failed attempt" is detected when:
  - A candle's high pierces a recent swing high (breakout up), then
  - The same or next candle CLOSES back below that swing high (failure)

The "second attempt pending" flag is set if the most recent failed attempt
happened within the last 5 bars and the price has retraced toward (but not
yet broken) the same level. The next bar that breaks the level cleanly is
the "second entry" trigger.

This module is stateless: it inspects the candle list and the swing context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from domain.models import Candle


@dataclass
class FailedAttemptContext:
    bars_since_failed_breakout_up: int = -1
    bars_since_failed_breakout_down: int = -1
    second_attempt_long_pending: bool = False
    second_attempt_short_pending: bool = False


def detect_failed_attempts(
    candles: list[Candle],
    last_swing_high: Optional[float],
    last_swing_low: Optional[float],
    lookback: int = 6,
) -> FailedAttemptContext:
    """Walk back through `lookback` bars looking for failed breakouts.

    A failed UP breakout: bar.high > swing_high but bar.close <= swing_high.
    A failed DOWN breakout: bar.low < swing_low but bar.close >= swing_low.
    """
    ctx = FailedAttemptContext()
    if not candles:
        return ctx

    # Look at the most recent N bars (excluding current if you want, but here
    # we include current — the convention counts the current bar).
    window = candles[-lookback:] if len(candles) > lookback else list(candles)
    n = len(window)
    current_index = len(candles) - 1

    if last_swing_high is not None:
        for i, c in enumerate(window):
            pierced = c.high > last_swing_high
            failed = c.close <= last_swing_high
            if pierced and failed:
                # bars_since: from this bar to the current bar
                local_idx = (current_index - (n - 1)) + i
                ctx.bars_since_failed_breakout_up = current_index - local_idx
                # If the failure is recent (last 5 bars), arm the second-attempt
                if ctx.bars_since_failed_breakout_up <= 5:
                    ctx.second_attempt_long_pending = True
                break  # report the most recent only

    if last_swing_low is not None:
        for i, c in enumerate(window):
            pierced = c.low < last_swing_low
            failed = c.close >= last_swing_low
            if pierced and failed:
                local_idx = (current_index - (n - 1)) + i
                ctx.bars_since_failed_breakout_down = current_index - local_idx
                if ctx.bars_since_failed_breakout_down <= 5:
                    ctx.second_attempt_short_pending = True
                break

    return ctx
