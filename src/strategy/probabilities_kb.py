"""
Knowledge base of Nogran price action probabilities for Strategy Score enrichment.

Loads data/probabilities/pa_probabilities.json (62 setups + 22 hard rules,
curated in-house for the Nogran PA methodology, cross-checked against public
open-source references).

Pipeline de uso:
    kb = ProbabilitiesKB()
    enriched = kb.enrich_signal(signal, llm_score)
    # enriched.blended_score: SS final (LLM 60% + PA 40%)
    # enriched.alarm: HallucinationAlarm with anti-hallucination warning, or None
    # enriched.match: KBMatch with setup_id + notes, or None

Mantem o Decision Scorer intacto (CLAUDE.md regra: nao alterar logica do scorer).
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from domain.enums import Action
from domain.models import TradeSignal

logger = logging.getLogger(__name__)


# Localizacao do JSON (relativo ao diretorio do projeto, nao ao src/)
DEFAULT_KB_PATH = Path(__file__).resolve().parents[2] / "data" / "probabilities" / "pa_probabilities.json"


# Mapping between the 6 SetupTypes the LLM can return and the setup_ids in the PA KB
# (direction-aware). When the LLM returns a setup we do not map, enrichment is
# skipped (no_match) and the original LLM score flows through unchanged.
SETUP_MAPPING: dict[str, dict[str, str]] = {
    "second_entry_H2": {
        "long":  "high_2_pullback_ma_bull",
        "short": "low_2_pullback_ma_bear",
    },
    "breakout_pullback": {
        "long":  "breakout_pullback_bull_flag",
        "short": "breakout_pullback_bear_flag",
    },
    "H2_ema": {
        "long":  "limit_quiet_bull_flag_at_ma",
        "short": "limit_quiet_bear_flag_at_ma",
    },
    "ii_breakout": {
        "long":  "tr_breakout_setup",
        "short": "tr_breakout_setup",
    },
    # shaved_bar is a bar-quality descriptor, not a named PA setup.
    # No mapping -> graceful degradation (no_match).
}


# Weights for the blended SS: final = LLM * BLEND_LLM + PA * BLEND_PA
BLEND_LLM = 0.6
BLEND_PA = 0.4

# Hallucination alarm threshold: point gap between LLM and PA KB probability
HALLUCINATION_GAP_THRESHOLD = 25


@dataclass
class KBMatch:
    """Setup encontrado na KB."""
    setup_id: str
    name_en: str
    name_pt: str
    probability_pct: int
    probability_confidence: str
    min_reward_risk: Optional[float]
    notes_pt: str = ""


@dataclass
class HallucinationAlarm:
    """Disparado quando o LLM e a KB PA discordam significativamente."""
    llm_score: int
    pa_probability: int
    gap: int
    direction: str  # "llm_too_optimistic" | "llm_too_pessimistic"
    setup_id: str
    severity: str   # "warning" | "critical"


@dataclass
class EnrichedScore:
    """Resultado do enriquecimento de um TradeSignal pela KB."""
    llm_score: int                    # Score original do calculate_strategy_score
    blended_score: int                # Score final apos blend (LLM 60% + PA 40%)
    match: Optional[KBMatch]          # KB match (None se setup nao mapeado)
    alarm: Optional[HallucinationAlarm]  # Anti-hallucination alarm (None se OK)
    rr_warning: Optional[str]         # Soft warning sobre R/R abaixo do recomendado


class ProbabilitiesKB:
    """
    Loader + lookup + enriquecimento de TradeSignal.

    Carrega o JSON uma vez na inicializacao. Lookup O(1) por setup_id.
    """

    def __init__(
        self,
        kb_path: Path | str | None = None,
        clamp_max_pct: int | None = None,
        hallucination_threshold: int | None = None,
    ):
        """
        Args:
            kb_path: path to the KB JSON file
            clamp_max_pct: if set, clamp every setup's probability_pct to
                min(original, clamp_max_pct). Used for diagnostic Test #3
                ("the book values are too optimistic for BTC 15m").
            hallucination_threshold: if set, override the gap threshold
                that triggers a hallucination alarm. Default 25. Used for
                diagnostic Test #2 (tighter alarm).
        """
        self.kb_path = Path(kb_path) if kb_path else DEFAULT_KB_PATH
        self.clamp_max_pct = clamp_max_pct
        self.halu_threshold = hallucination_threshold or HALLUCINATION_GAP_THRESHOLD
        self.setups: dict[str, dict] = {}
        self.hard_rules: list[dict] = []
        self.metadata: dict = {}
        self._load()

    def _load(self) -> None:
        if not self.kb_path.exists():
            logger.warning(f"Probabilities KB not found at {self.kb_path} — enrichment disabled")
            return
        try:
            data = json.loads(self.kb_path.read_text(encoding="utf-8"))
            self.setups = {s["setup_id"]: s for s in data.get("setups", [])}
            # Test #3: clamp KB probabilities — assume the book values are
            # over-optimistic for BTC 15m. Replaces every setup probability
            # with min(original, clamp_max_pct).
            if self.clamp_max_pct is not None:
                for sid, s in self.setups.items():
                    orig = s.get("probability_pct", 0)
                    if orig > self.clamp_max_pct:
                        s["probability_pct"] = self.clamp_max_pct
                logger.info(
                    f"ProbabilitiesKB: clamped all setup probabilities to "
                    f"<= {self.clamp_max_pct} (Test #3)"
                )
            self.hard_rules = data.get("hard_rules", [])
            self.metadata = {
                "version": data.get("version"),
                "total_setups": data.get("total_setups"),
                "total_hard_rules": data.get("total_hard_rules"),
            }
            logger.info(
                f"ProbabilitiesKB loaded: {len(self.setups)} setups, "
                f"{len(self.hard_rules)} hard rules (version {self.metadata.get('version')})"
            )
        except Exception as e:
            logger.error(f"Failed to load probabilities KB: {e}")
            self.setups = {}
            self.hard_rules = []

    def lookup(self, llm_setup: str, action: Action) -> Optional[KBMatch]:
        """
        Map LLM SetupType + Action -> KB setup match.
        Returns None if no mapping or KB empty.
        """
        if not self.setups:
            return None
        direction_map = SETUP_MAPPING.get(llm_setup)
        if not direction_map:
            return None
        if action == Action.COMPRA:
            kb_id = direction_map.get("long")
        elif action == Action.VENDA:
            kb_id = direction_map.get("short")
        else:
            return None
        if not kb_id or kb_id not in self.setups:
            return None
        s = self.setups[kb_id]
        return KBMatch(
            setup_id=s["setup_id"],
            name_en=s["name_en"],
            name_pt=s["name_pt"],
            probability_pct=s["probability_pct"],
            probability_confidence=s["probability_confidence"],
            min_reward_risk=s.get("min_reward_risk"),
            notes_pt=s.get("notes_pt", ""),
        )

    def enrich_signal(
        self,
        signal: TradeSignal,
        llm_score: int,
        trade_rr: Optional[float] = None,
    ) -> EnrichedScore:
        """
        Enriquecimento principal: combina LLM score com probabilidade da PA KB.

        - llm_score: SS calculado por calculate_strategy_score(signal)
        - trade_rr: razao reward/risk efetiva do trade (do Risk Engine), opcional
        """
        match = self.lookup(signal.setup.value, signal.action)

        if match is None:
            # No-match: passa o score original sem alteracao
            return EnrichedScore(
                llm_score=llm_score,
                blended_score=llm_score,
                match=None,
                alarm=None,
                rr_warning=None,
            )

        # Blend: LLM 60% + PA 40%
        blended = int(round(llm_score * BLEND_LLM + match.probability_pct * BLEND_PA))
        blended = max(0, min(100, blended))

        # Detect hallucination
        alarm = self._detect_hallucination(llm_score, match)

        # Soft warning on R/R below the recommended floor for this setup (does not block)
        rr_warning = None
        if trade_rr is not None and match.min_reward_risk is not None:
            if trade_rr < match.min_reward_risk:
                rr_warning = (
                    f"R/R do trade ({trade_rr:.2f}) abaixo do recomendado pela PA KB "
                    f"para {match.setup_id} ({match.min_reward_risk}). "
                    f"MIN_REWARD_RISK global (1.5) ainda atendido."
                )

        return EnrichedScore(
            llm_score=llm_score,
            blended_score=blended,
            match=match,
            alarm=alarm,
            rr_warning=rr_warning,
        )

    def _detect_hallucination(
        self,
        llm_score: int,
        match: KBMatch,
    ) -> Optional[HallucinationAlarm]:
        """
        Dispara alarme se LLM e PA KB discordam por >= HALLUCINATION_GAP_THRESHOLD.
        """
        gap = llm_score - match.probability_pct
        abs_gap = abs(gap)
        # Use the instance-level threshold (allows Test #2 override).
        if abs_gap < self.halu_threshold:
            return None

        direction = "llm_too_optimistic" if gap > 0 else "llm_too_pessimistic"
        # Critical se gap >= 40, warning entre 25-40
        severity = "critical" if abs_gap >= 40 else "warning"

        logger.warning(
            f"HALLUCINATION_ALARM ({severity}): llm={llm_score} vs PA={match.probability_pct} "
            f"(gap={gap:+d}) for setup {match.setup_id}"
        )

        return HallucinationAlarm(
            llm_score=llm_score,
            pa_probability=match.probability_pct,
            gap=gap,
            direction=direction,
            setup_id=match.setup_id,
            severity=severity,
        )
