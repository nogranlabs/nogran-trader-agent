"""
Nogran PA setup detectors — rule-based entry detection in Python.

Each detector is a pure function that takes a FeatureSnapshot (with swings,
regime, always-in, recent_bars, etc.) and returns a DetectedSetup or None.
No LLM involved — these ARE the "brain" of the price action methodology
codified in deterministic rules.

The orchestrator (local_signal.py or main.py) calls all detectors per candle,
collects the matches, picks the best, and optionally asks the LLM to confirm.

Detector naming: detect_<setup_id>_<direction>
  e.g. detect_h2_long, detect_l2_short, detect_climactic_long_fade

Each detector should:
  - Check HTF context first (don't fight the 1h)
  - Check regime alignment
  - Check swing structure (HH/HL, LH/LL)
  - Check pullback pattern in recent_bars
  - Set stop at structural level (swing low for longs, swing high for shorts)
  - Set target based on ATR or measured move
  - Return None if conditions not met (= this candle is not this setup)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from domain.enums import Action, SetupType


@dataclass
class DetectedSetup:
    """A setup detected by a rule-based detector."""
    setup_id: str           # matches PA KB setup_id (e.g. "high_2_pullback_ma_bull")
    setup_type: SetupType   # maps to the LLM schema enum (e.g. SECOND_ENTRY_H2)
    action: Action          # COMPRA or VENDA
    confidence: int         # 0-100 (detector's self-assessed quality)
    entry: float
    stop: float
    target: float
    reasoning: str          # short English explanation
    decisive_factor: str    # which feature was the trigger
    priority: int = 50      # higher = preferred when multiple setups fire

    @property
    def rr(self) -> float:
        risk = abs(self.entry - self.stop)
        if risk <= 0:
            return 0.0
        return abs(self.target - self.entry) / risk
