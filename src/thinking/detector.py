"""
Mind-change detector — inspects a ThoughtStream and returns the list of
revisions that should be appended.

A "mind change" is a moment where one stage's verdict contradicts an
earlier stage's, prompting the agent to update its view in an iterative,
narrative way ("This looks like a wedge bull flag... but actually the
third push has a closing tail, so it's more likely a final flag reversal").

Detection rules (each is a function that returns a Thought payload or None):

1. **Strategy vs AI overlay disagreement** — the LLM proposes BUY but the
   regime detector says RANGING -> revision marking the strategy thought as
   downgraded.
2. **Hallucination alarm fired** — the Nogran PA KB and the LLM disagree by
   >=25 points -> revision of the strategy hypothesis.
3. **Risk veto on a passing setup** — Decision Score would have been GO
   but the risk engine produced a hard veto -> revision of the strategy
   thought.
4. **Pre-filter veto on a high-confidence signal** — strategy later returned
   a high-confidence buy in a market the pre-filter already vetoed.

Each rule is intentionally narrow and explicit. It is meant to surface
moments where the agent visibly changes its conclusion, not to second-
guess every minor disagreement.
"""

from __future__ import annotations

from thinking.models import ThoughtStage, ThoughtStream, ThoughtType


def detect_mind_changes(stream: ThoughtStream) -> list[dict]:
    """Inspect the stream and return revision payloads to append.

    The caller is responsible for actually adding them via stream.revise()
    so the order of insertion stays consistent.
    """
    revisions: list[dict] = []

    revisions.extend(_strategy_vs_overlay(stream))
    revisions.extend(_hallucination_revisions(stream))
    revisions.extend(_risk_veto_revisions(stream))
    revisions.extend(_pre_filter_dissonance(stream))

    return revisions


# ============================================================
# Rule 1: strategy vs overlay disagreement
# ============================================================

def _strategy_vs_overlay(stream: ThoughtStream) -> list[dict]:
    strategy_thoughts = [
        t for t in stream.find_by_stage(ThoughtStage.STRATEGY)
        if t.type == ThoughtType.HYPOTHESIS
    ]
    if not strategy_thoughts:
        return []

    overlay_thoughts = stream.find_by_stage(ThoughtStage.AI_OVERLAY)
    if not overlay_thoughts:
        return []

    # The most recent strategy hypothesis vs latest overlay observation
    s = strategy_thoughts[-1]
    o = overlay_thoughts[-1]
    s_action = (s.metadata or {}).get("action", "")
    o_regime = (o.metadata or {}).get("regime", "")

    if not s_action or not o_regime:
        return []

    # Buying/selling in a TRANSITIONING regime is risky — revise the strategy
    if s_action in ("COMPRA", "VENDA") and o_regime == "TRANSITIONING":
        return [{
            "original_id": s.id,
            "stage": ThoughtStage.AI_OVERLAY,
            "text_pt": (
                f"Revisao: regime TRANSITIONING contradiz a hipotese de {s_action.lower()}. "
                "Nao operar contra-tendencia sem trend line break + signal bar forte."
            ),
            "concepts": ["regime_contradiction", "no_countertrend_without_tl_break"],
            "confidence": 70,
            "metadata": {
                "strategy_action": s_action,
                "overlay_regime": o_regime,
            },
        }]
    return []


# ============================================================
# Rule 2: hallucination alarm -> revision of strategy thought
# ============================================================

def _hallucination_revisions(stream: ThoughtStream) -> list[dict]:
    alarms = [t for t in stream.thoughts if t.type == ThoughtType.ALARM]
    if not alarms:
        return []

    strategy_thoughts = [
        t for t in stream.find_by_stage(ThoughtStage.STRATEGY)
        if t.type == ThoughtType.HYPOTHESIS
    ]
    if not strategy_thoughts:
        return []

    revisions = []
    target = strategy_thoughts[-1]
    for alarm in alarms:
        sev = (alarm.metadata or {}).get("severity", "warning")
        gap = (alarm.metadata or {}).get("gap", 0)
        revisions.append({
            "original_id": target.id,
            "stage": ThoughtStage.KB_LOOKUP,
            "text_pt": (
                f"Revisao da hipotese do LLM: hallucination alarm {sev} "
                f"(gap {gap:+d} pts). PA KB diverge — confianca rebaixada."
            ),
            "concepts": ["hallucination_alarm", "kb_cross_check"],
            "confidence": 80 if sev == "warning" else 95,
            "metadata": {"alarm_severity": sev, "gap": gap},
        })
    return revisions


# ============================================================
# Rule 3: risk veto on a passing setup
# ============================================================

def _risk_veto_revisions(stream: ThoughtStream) -> list[dict]:
    risk_vetoes = [
        t for t in stream.find_by_stage(ThoughtStage.RISK)
        if t.type == ThoughtType.VETO
    ]
    if not risk_vetoes:
        return []

    strategy_thoughts = [
        t for t in stream.find_by_stage(ThoughtStage.STRATEGY)
        if t.type == ThoughtType.HYPOTHESIS
    ]
    if not strategy_thoughts:
        return []

    target = strategy_thoughts[-1]
    risk = risk_vetoes[-1]
    return [{
        "original_id": target.id,
        "stage": ThoughtStage.RISK,
        "text_pt": (
            "Revisao: o setup parecia bom, mas o risk engine vetou "
            "(drawdown / circuit breaker). 'Always have a protective stop' "
            "— preservar capital antes de perseguir edge."
        ),
        "concepts": ["risk_veto", "always_use_stop", "protect_capital"],
        "confidence": 100,
        "metadata": {
            "risk_thought_id": risk.id,
        },
    }]


# ============================================================
# Rule 4: high-confidence signal in pre-filter-vetoed market
# ============================================================

def _pre_filter_dissonance(stream: ThoughtStream) -> list[dict]:
    pre_vetoes = [
        t for t in stream.find_by_stage(ThoughtStage.PRE_FILTER)
        if t.type == ThoughtType.VETO
    ]
    if not pre_vetoes:
        return []

    strategy_thoughts = [
        t for t in stream.find_by_stage(ThoughtStage.STRATEGY)
        if t.type == ThoughtType.HYPOTHESIS and t.confidence >= 70
    ]
    if not strategy_thoughts:
        return []

    target = strategy_thoughts[-1]
    return [{
        "original_id": target.id,
        "stage": ThoughtStage.META,
        "text_pt": (
            "Revisao: strategy esta vendo um setup forte, mas o mercado ja foi vetado "
            "pelo MQ score (chop / tight TR). 'Tight trading range trumps everything' "
            "— ignorar o sinal e esperar quebra real."
        ),
        "concepts": ["tight_tr_trumps_all", "pre_filter_dissonance"],
        "confidence": 90,
    }]
