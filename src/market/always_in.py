"""Always-in bias — core Nogran PA concept, computed deterministically.

"Every moment the market is always-in long, always-in short, or in
transition." The bias is the implicit position a price action trader holds
based on observable evidence — NOT an LLM guess.

We score each direction from observable evidence:
  Long score (each adds +1):
    - last bar is bull
    - 3+ of last 5 bars are bull
    - price > EMA20 (15m)
    - structure is HH_HL
    - 1h is above EMA20
    - 1h direction is "up"

  Short score is mirror.

Decision:
  long_score >= 4 AND short_score <= 1  →  SEMPRE_COMPRADO
  short_score >= 4 AND long_score <= 1  →  SEMPRE_VENDIDO
  otherwise                             →  NEUTRO

Calling layer should use this instead of asking the LLM to classify layer 2.
"""

from __future__ import annotations

from typing import Optional


def compute_always_in(
    last_bar_is_bull: bool,
    last_5_bull_count: int,
    price_above_ema: bool,
    structure: str,
    tf_1h_above_ema: bool,
    tf_1h_direction: Optional[str],
) -> str:
    """Returns 'SEMPRE_COMPRADO', 'SEMPRE_VENDIDO', or 'NEUTRO'.

    Domain enum values are kept in Portuguese to match the rest of the codebase
    (CLAUDE.md notes: enums in PT, prompts/reasoning in EN).
    """
    long_score = 0
    short_score = 0

    if last_bar_is_bull:
        long_score += 1
    else:
        short_score += 1

    if last_5_bull_count >= 3:
        long_score += 1
    elif last_5_bull_count <= 2:
        short_score += 1

    if price_above_ema:
        long_score += 1
    else:
        short_score += 1

    if structure == "HH_HL":
        long_score += 1
    elif structure == "LH_LL":
        short_score += 1

    if tf_1h_above_ema:
        long_score += 1
    else:
        short_score += 1

    if tf_1h_direction == "up":
        long_score += 1
    elif tf_1h_direction == "down":
        short_score += 1

    if long_score >= 4 and short_score <= 1:
        return "SEMPRE_COMPRADO"
    if short_score >= 4 and long_score <= 1:
        return "SEMPRE_VENDIDO"
    return "NEUTRO"
