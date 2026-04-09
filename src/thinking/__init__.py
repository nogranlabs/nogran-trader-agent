"""
Thinking module — captures the agent's reasoning trace per candle in
Nogran price action style. Used to surface "what the agent is thinking" on the dashboard
and to audit decision quality after the fact.

Public API:
    from thinking import (
        Thought, ThoughtStream, ThoughtStage, ThoughtType,
        narrate_bar, narrate_pre_filter, narrate_signal,
        narrate_overlay, narrate_risk, narrate_decision, narrate_veto,
        detect_mind_changes,
    )
"""

from thinking.detector import detect_mind_changes
from thinking.models import (
    Thought,
    ThoughtStage,
    ThoughtStream,
    ThoughtType,
)
from thinking.narrator import (
    narrate_bar,
    narrate_decision,
    narrate_overlay,
    narrate_pre_filter,
    narrate_risk,
    narrate_signal,
    narrate_veto,
)

__all__ = [
    "Thought",
    "ThoughtStage",
    "ThoughtStream",
    "ThoughtType",
    "narrate_bar",
    "narrate_pre_filter",
    "narrate_signal",
    "narrate_overlay",
    "narrate_risk",
    "narrate_decision",
    "narrate_veto",
    "detect_mind_changes",
]
