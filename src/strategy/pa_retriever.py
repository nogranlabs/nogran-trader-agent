"""
PA Retriever — rule-based RAG over local Nogran price action knowledge chunks.

Loads chunks from data/chunks/layer*.json (maintained in a separate private
dataset repo) and selects relevant passages for a given FeatureSnapshot using
deterministic feature → topic mappings (no embeddings, no vector DB).

Why deterministic instead of vector search:
- Only ~213 chunks total (small enough for memory)
- Feature → topic mapping is well-defined by the Nogran PA framework
- Reproducible (same features = same chunks → same cache key)
- Zero infra (no Postgres, no FAISS)
- Auditable (caller can read code to know which chunks come back)
- Mirrors the "if you see X, consult topic Y" teaching heuristic

Mapping logic:
  Layer 1 (day_type):    chosen by ADX, consecutive bars, bar overlap
  Layer 2 (always_in):   chosen by EMA distance, body, direction
  Layer 3 (structure):   always-in needs trend lines + breakouts always
  Layer 4 (micro):       chosen by body%, tail%, climax detection
  Layer 5 (setup):       chosen by signal bar quality + setup type

Each layer returns 1 base chunk (always) + 1 conditional chunk (if matches).
Total: ~5-10 chunks per call, ~5000-8000 tokens of inline context.

If the chunks dir is missing (e.g. a clone without the private dataset),
the retriever returns an empty result gracefully and the LLM falls back to
its training-data knowledge.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from domain.models import FeatureSnapshot

logger = logging.getLogger(__name__)


# Default chunks location (populated locally from the private dataset repo)
DEFAULT_CHUNKS_DIR = Path(__file__).resolve().parents[2] / "data" / "chunks"

# Layer files (in load order). Missing files are skipped (graceful).
LAYER_FILES = [
    ("layer0", "layer0_glossary.json"),
    ("layer1", "layer1_day_type.json"),
    ("layer2", "layer2_macro.json"),
    ("layer3", "layer3_structure.json"),
    ("layer4", "layer4_micro.json"),
    ("layer5", "layer5_setup.json"),
]


@dataclass
class PAChunk:
    """One chunk extracted from a PA layer file."""
    layer: str          # "layer1" | "layer2" | ... | "layer5"
    chunk_id: str       # canonical identifier
    topic: str          # e.g. "spike_and_channel", "bar_anatomy"
    description: str    # short description
    content: str        # the actual text passage

    def __repr__(self) -> str:
        return f"<PAChunk {self.layer}/{self.chunk_id} topic={self.topic!r}>"


@dataclass
class RetrievalResult:
    """Result of a retrieval call: chunks grouped by layer."""
    chunks: dict[str, list[PAChunk]] = field(default_factory=dict)
    total_chunks: int = 0
    total_chars: int = 0

    def chunk_ids(self) -> list[str]:
        """Flat list of all chunk IDs returned (for cache keying / audit)."""
        ids = []
        for layer_chunks in self.chunks.values():
            ids.extend(c.chunk_id for c in layer_chunks)
        return sorted(ids)

    def to_prompt_text(self) -> str:
        """Format the retrieved chunks as a structured PA reference for the LLM."""
        if not self.chunks:
            return ""
        sections = ["# NOGRAN PA REFERENCE (selected for current market context)\n"]
        for layer in sorted(self.chunks.keys()):
            layer_chunks = self.chunks[layer]
            if not layer_chunks:
                continue
            sections.append(f"\n## {layer.upper()}\n")
            for c in layer_chunks:
                sections.append(f"### {c.topic} — {c.chunk_id}\n{c.content}\n")
        return "\n".join(sections)


# ============================================================
# PARetriever — main class
# ============================================================


class PARetriever:
    """Rule-based retriever over local PA chunks.

    Lazy-loads chunks on first call. If chunks dir is missing, all retrievals
    return empty results (graceful degradation).
    """

    def __init__(self, chunks_dir: Optional[Path] = None):
        self.chunks_dir = Path(chunks_dir) if chunks_dir else DEFAULT_CHUNKS_DIR
        self._loaded = False
        self._by_layer_topic: dict[str, dict[str, list[PAChunk]]] = {}
        self._by_id: dict[str, PAChunk] = {}
        self._available = False

    def _load(self):
        """Lazy load all chunk files. Idempotent."""
        if self._loaded:
            return
        self._loaded = True

        if not self.chunks_dir.exists():
            logger.warning(
                f"PA chunks dir not found at {self.chunks_dir}. "
                "Retrieval will return empty (LLM falls back to training data)."
            )
            self._available = False
            return

        loaded_count = 0
        for layer_name, filename in LAYER_FILES:
            path = self.chunks_dir / filename
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")
                continue

            self._by_layer_topic.setdefault(layer_name, {})
            for raw in data:
                chunk = PAChunk(
                    layer=layer_name,
                    chunk_id=raw.get("id", "?"),
                    topic=raw.get("topic", "?"),
                    description=raw.get("description", ""),
                    content=raw.get("content", ""),
                )
                self._by_layer_topic[layer_name].setdefault(chunk.topic, []).append(chunk)
                self._by_id[chunk.chunk_id] = chunk
                loaded_count += 1

        self._available = loaded_count > 0
        if self._available:
            logger.info(
                f"PARetriever loaded {loaded_count} chunks from {self.chunks_dir} "
                f"({len(self._by_layer_topic)} layers)"
            )

    @property
    def available(self) -> bool:
        """True if chunks were successfully loaded."""
        if not self._loaded:
            self._load()
        return self._available

    @property
    def total_loaded(self) -> int:
        """Total chunks loaded across all layers."""
        if not self._loaded:
            self._load()
        return len(self._by_id)

    # =========================================================
    # Selection rules per layer
    # =========================================================

    def _pick_layer1_topic(self, f: FeatureSnapshot) -> list[str]:
        """Layer 1 (day_type): which topics to retrieve based on features."""
        topics = []
        # Always include spike_and_channel — most common pattern
        topics.append("spike_and_channel")
        # If strong directional momentum, also include trend_from_open
        if (f.consecutive_bull >= 3 or f.consecutive_bear >= 3) and f.adx_14 >= 25:
            topics.append("trend_from_open")
        # If choppy/range conditions, include trending_trading_range
        if 0.4 < f.bar_overlap_ratio <= 0.55:
            topics.append("trending_trading_range")
        # If strong reversal indication (bull bars after bear, or vice versa), reversal_day
        if (f.consecutive_bull >= 2 and f.consecutive_bear == 0 and f.upper_tail_pct >= 30) or \
           (f.consecutive_bear >= 2 and f.consecutive_bull == 0 and f.lower_tail_pct >= 30):
            topics.append("reversal_day")
        return topics

    def _pick_layer2_topic(self, f: FeatureSnapshot) -> list[str]:
        """Layer 2 (macro/always_in)."""
        topics = ["spectrum_of_price_action"]
        # Strong directional → signs of strength relevant
        if f.adx_14 >= 25 or abs(f.price_vs_ema) > 0.5:
            topics.append("signs_of_strength_in_trends")
        # Always-in transitions need two-legs analysis
        if f.consecutive_bull >= 2 or f.consecutive_bear >= 2:
            topics.append("two_legs")
        return topics

    def _pick_layer3_topic(self, f: FeatureSnapshot) -> list[str]:
        """Layer 3 (structure): trend lines + breakouts always relevant."""
        return ["trend_lines", "breakouts_and_tests"]

    def _pick_layer4_topic(self, f: FeatureSnapshot) -> list[str]:
        """Layer 4 (micro): bar anatomy + reversal/signal bar criteria."""
        topics = ["bar_anatomy"]
        # Possible reversal: large tails
        if f.upper_tail_pct >= 30 or f.lower_tail_pct >= 30:
            topics.append("reversal_bar_criteria")
        # Always include signal bar criteria when there's a candidate setup
        if f.body_pct >= 40:
            topics.append("signal_and_entry_bars")
        return topics

    def _pick_layer5_topic(self, f: FeatureSnapshot) -> list[str]:
        """Layer 5 (setup): signal bar types + second entries."""
        topics = ["signal_bar_types"]
        # Second entries are core to PA reliability
        if f.consecutive_bull >= 2 or f.consecutive_bear >= 2:
            topics.append("second_entries")
        return topics

    # =========================================================
    # Public API
    # =========================================================

    def retrieve(
        self,
        features: FeatureSnapshot,
        max_per_topic: int = 1,
        max_per_layer: int = 2,
    ) -> RetrievalResult:
        """Retrieve relevant PA chunks for the given features.

        Strategy:
        1. Per layer, pick relevant topics via _pick_layerN_topic()
        2. For each topic, take the first `max_per_topic` chunks
        3. Cap at `max_per_layer` chunks per layer
        4. Concat across layers

        Default: ~5-10 chunks total, ~5000-8000 tokens of context.
        """
        if not self.available:
            return RetrievalResult()

        result = RetrievalResult()

        layer_pickers = {
            "layer1": self._pick_layer1_topic,
            "layer2": self._pick_layer2_topic,
            "layer3": self._pick_layer3_topic,
            "layer4": self._pick_layer4_topic,
            "layer5": self._pick_layer5_topic,
        }

        for layer_name, picker in layer_pickers.items():
            if layer_name not in self._by_layer_topic:
                continue
            wanted_topics = picker(features)
            picked: list[PAChunk] = []
            for topic in wanted_topics:
                topic_chunks = self._by_layer_topic[layer_name].get(topic, [])
                if not topic_chunks:
                    continue
                picked.extend(topic_chunks[:max_per_topic])
                if len(picked) >= max_per_layer:
                    picked = picked[:max_per_layer]
                    break
            if picked:
                result.chunks[layer_name] = picked
                result.total_chunks += len(picked)
                result.total_chars += sum(len(c.content) for c in picked)

        return result

    def get_chunk(self, chunk_id: str) -> Optional[PAChunk]:
        """Lookup a single chunk by ID (for tests / debugging)."""
        if not self._loaded:
            self._load()
        return self._by_id.get(chunk_id)
