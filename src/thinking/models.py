"""
Data models for the thought stream.

A Thought is a single observation/hypothesis/revision/decision made by
the agent at a specific pipeline stage. A ThoughtStream is the ordered
collection of thoughts emitted during one candle's analysis.

Mind changes (revisions) are first-class: a later thought can mark itself
as `revision_of` an earlier thought, capturing the moment the agent
updated its view based on new evidence (e.g. AI overlay disagreeing with
the Strategy Engine, or risk engine vetoing a high score).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ThoughtStage(str, Enum):
    """Pipeline stage that emitted the thought."""
    FEATURE = "feature"
    PRE_FILTER = "pre_filter"
    STRATEGY = "strategy"        # Strategy Engine output (python_llm or mock)
    KB_LOOKUP = "kb_lookup"      # Nogran PA knowledge base match
    AI_OVERLAY = "ai_overlay"
    RISK = "risk"
    DECISION = "decision"
    EXECUTION = "execution"
    META = "meta"                # session, errors, lifecycle


class ThoughtType(str, Enum):
    """What kind of thought it is — drives styling and audit semantics."""
    OBSERVATION = "observation"  # Factual reading of the market state
    HYPOTHESIS = "hypothesis"    # Probable interpretation, not certain
    REVISION = "revision"        # Updates / contradicts a prior thought (mind change)
    VETO = "veto"                # Hard rule blocking action
    DECISION = "decision"        # Final go/no-go
    ALARM = "alarm"              # Hallucination detector or other warnings


@dataclass
class Thought:
    """A single reasoning step in a Nogran PA-style narrative."""
    id: str
    candle_index: int
    stage: ThoughtStage
    type: ThoughtType
    text_pt: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    text_en: str = ""
    concepts: list[str] = field(default_factory=list)  # ["high_2_pullback", ...]
    confidence: int = 50                                      # 0-100
    revision_of: Optional[str] = None                          # id of revised thought
    metadata: dict = field(default_factory=dict)               # raw numbers, debug data

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stage"] = self.stage.value
        d["type"] = self.type.value
        d["timestamp"] = self.timestamp.isoformat()
        return d


@dataclass
class ThoughtStream:
    """Ordered collection of thoughts for a single candle's analysis run."""
    candle_index: int
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    thoughts: list[Thought] = field(default_factory=list)
    _next_id: int = 0  # internal counter for generating thought ids

    # ---- mutation API ----------------------------------------------------

    def add(
        self,
        stage: ThoughtStage,
        type: ThoughtType,
        text_pt: str,
        text_en: str = "",
        concepts: Optional[list[str]] = None,
        confidence: int = 50,
        revision_of: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Thought:
        """Append a new thought to the stream and return it."""
        self._next_id += 1
        thought = Thought(
            id=f"t{self.candle_index}-{self._next_id:03d}",
            candle_index=self.candle_index,
            stage=stage,
            type=type,
            text_pt=text_pt,
            text_en=text_en,
            concepts=list(concepts or []),
            confidence=max(0, min(100, confidence)),
            revision_of=revision_of,
            metadata=dict(metadata or {}),
        )
        self.thoughts.append(thought)
        return thought

    def revise(
        self,
        original_id: str,
        stage: ThoughtStage,
        text_pt: str,
        text_en: str = "",
        concepts: Optional[list[str]] = None,
        confidence: int = 50,
        metadata: Optional[dict] = None,
    ) -> Thought:
        """Add a revision thought that links back to an earlier thought.

        Convenience wrapper over `add()` that sets type=REVISION and the
        `revision_of` link in one call.
        """
        return self.add(
            stage=stage,
            type=ThoughtType.REVISION,
            text_pt=text_pt,
            text_en=text_en,
            concepts=concepts,
            confidence=confidence,
            revision_of=original_id,
            metadata=metadata,
        )

    def find_by_stage(self, stage: ThoughtStage) -> list[Thought]:
        """Return all thoughts emitted by a given stage."""
        return [t for t in self.thoughts if t.stage == stage]

    def find_by_id(self, thought_id: str) -> Optional[Thought]:
        for t in self.thoughts:
            if t.id == thought_id:
                return t
        return None

    @property
    def revision_count(self) -> int:
        return sum(1 for t in self.thoughts if t.type == ThoughtType.REVISION)

    @property
    def has_veto(self) -> bool:
        return any(t.type == ThoughtType.VETO for t in self.thoughts)

    @property
    def has_alarm(self) -> bool:
        return any(t.type == ThoughtType.ALARM for t in self.thoughts)

    def to_dict(self) -> dict:
        return {
            "candle_index": self.candle_index,
            "started_at": self.started_at.isoformat(),
            "thought_count": len(self.thoughts),
            "revision_count": self.revision_count,
            "has_veto": self.has_veto,
            "has_alarm": self.has_alarm,
            "thoughts": [t.to_dict() for t in self.thoughts],
        }
