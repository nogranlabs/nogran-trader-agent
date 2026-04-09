"""
Nogran price action narrator — turns numerical pipeline state into a short
narrative of observations, chained together and naming concrete patterns
("trend bar", "doji", "second entry", "wedge bull flag"), with explicit
context references ("after a trend line break", "in a bull trend") and
decisive language about probability and reward/risk.

Each function takes the raw inputs of one pipeline stage and returns a
list of payload dicts (text_pt, concepts, type, confidence, metadata)
that the caller appends to a ThoughtStream.

The narrator is intentionally pure (no I/O, no globals) so it can be
tested in isolation and reused by both the live agent and the offline
simulation script.
"""

from __future__ import annotations

from typing import Any, Optional

from thinking.models import ThoughtType

# ============================================================
# Bar-level narration (feature snapshot -> PA observation)
# ============================================================

def narrate_bar(features: Any) -> list[dict]:
    """Describe the current candle in Nogran PA vocabulary.

    Returns a list of thought-payloads (dicts ready to be passed to
    ThoughtStream.add). Always emits at least one observation.

    Expected features object: same FeatureSnapshot dataclass as the
    main pipeline (or a duck-typed equivalent for tests).
    """
    candle = features.candle
    body_pct = features.body_pct
    upper_tail = features.upper_tail_pct
    lower_tail = features.lower_tail_pct
    is_bull = candle.is_bullish
    direction = "alta" if is_bull else "baixa"

    # Bar quality classification
    if body_pct >= 70 and upper_tail < 15 and lower_tail < 15:
        quality = "trend bar forte"
        concept = "strong_trend_bar"
    elif body_pct >= 50:
        quality = "trend bar"
        concept = "trend_bar"
    elif body_pct < 25:
        quality = "doji"
        concept = "doji_bar"
    else:
        quality = "barra fraca"
        concept = "weak_bar"

    text = f"Barra {candle.timestamp}: {quality} de {direction}, body {body_pct:.0f}%"

    # Tail observations
    tail_notes = []
    if upper_tail >= 30:
        tail_notes.append(f"tail superior {upper_tail:.0f}% (vendedores presentes no topo)")
    if lower_tail >= 30:
        tail_notes.append(f"tail inferior {lower_tail:.0f}% (compradores presentes no fundo)")
    if tail_notes:
        text += ". " + ". ".join(tail_notes)

    payloads = [{
        "type": ThoughtType.OBSERVATION,
        "text_pt": text,
        "concepts": [concept],
        "confidence": 80,
        "metadata": {
            "body_pct": round(body_pct, 1),
            "upper_tail_pct": round(upper_tail, 1),
            "lower_tail_pct": round(lower_tail, 1),
            "close": candle.close,
        },
    }]

    # Position vs EMA20 + ATR
    price_vs_ema = features.price_vs_ema
    if abs(price_vs_ema) >= 0.5:
        side = "acima" if price_vs_ema > 0 else "abaixo"
        text2 = f"Preco {abs(price_vs_ema):.2f}% {side} da EMA20."
        if features.atr_ratio >= 1.3:
            text2 += f" ATR {features.atr_ratio:.2f}x media (vol expandindo)"
        elif features.atr_ratio <= 0.7:
            text2 += f" ATR {features.atr_ratio:.2f}x media (vol comprimindo, pode estar em range apertado)"
        payloads.append({
            "type": ThoughtType.OBSERVATION,
            "text_pt": text2,
            "concepts": ["ema_20", "atr"],
            "confidence": 80,
            "metadata": {
                "price_vs_ema": round(price_vs_ema, 2),
                "atr_ratio": round(features.atr_ratio, 2),
            },
        })

    # Consecutive bull/bear count
    if features.consecutive_bull >= 4:
        payloads.append({
            "type": ThoughtType.HYPOTHESIS,
            "text_pt": (
                f"{features.consecutive_bull} barras bullish consecutivas — "
                "spike phase em curso, talvez transicione para channel"
            ),
            "concepts": ["bull_spike"],
            "confidence": 70,
        })
    elif features.consecutive_bear >= 4:
        payloads.append({
            "type": ThoughtType.HYPOTHESIS,
            "text_pt": (
                f"{features.consecutive_bear} barras bearish consecutivas — "
                "bear spike, fundo provavelmente nao chegou ainda"
            ),
            "concepts": ["bear_spike"],
            "confidence": 70,
        })

    return payloads


# ============================================================
# Pre-filter narration (MQ score)
# ============================================================

def narrate_pre_filter(mq_score: int, features: Any) -> list[dict]:
    """Describe the market quality verdict."""
    overlap = features.bar_overlap_ratio
    direction_changes = features.direction_change_ratio
    atr_ratio = features.atr_ratio

    if mq_score < 30:
        text = (
            f"MQ={mq_score}/100 — mercado em chop. Overlap {overlap*100:.0f}%, "
            f"flips de direcao {direction_changes*100:.0f}%. "
            "Tight trading range domina — aguardar."
        )
        return [{
            "type": ThoughtType.VETO,
            "text_pt": text,
            "concepts": ["tight_trading_range", "chop", "tight_tr_trumps_all"],
            "confidence": 90,
            "metadata": {
                "mq_score": mq_score,
                "bar_overlap": round(overlap, 2),
                "direction_changes": round(direction_changes, 2),
                "atr_ratio": round(atr_ratio, 2),
            },
        }]

    if mq_score < 50:
        text = (
            f"MQ={mq_score}/100 — operavel mas marginal. "
            "Exigir setup A+ para passar."
        )
        ttype = ThoughtType.OBSERVATION
        confidence = 60
    elif mq_score < 75:
        text = (
            f"MQ={mq_score}/100 — mercado saudavel, overlap moderado. "
            "Setups normais aceitaveis."
        )
        ttype = ThoughtType.OBSERVATION
        confidence = 75
    else:
        text = (
            f"MQ={mq_score}/100 — mercado limpo, alta operabilidade. "
            "Trend bars e expansao de ATR."
        )
        ttype = ThoughtType.OBSERVATION
        confidence = 90

    return [{
        "type": ttype,
        "text_pt": text,
        "concepts": ["market_quality"],
        "confidence": confidence,
        "metadata": {"mq_score": mq_score},
    }]


# ============================================================
# Strategy Engine narration
# ============================================================

def narrate_signal(signal: Any) -> list[dict]:
    """Describe the Strategy Engine TradeSignal."""
    if signal is None:
        return [{
            "type": ThoughtType.OBSERVATION,
            "text_pt": "Strategy Engine nao retornou sinal — sem leitura para esta barra.",
            "concepts": [],
            "confidence": 0,
        }]

    action = signal.action.value if hasattr(signal.action, "value") else str(signal.action)
    setup = signal.setup.value if hasattr(signal.setup, "value") else str(signal.setup)
    day_type = signal.day_type.value if hasattr(signal.day_type, "value") else str(signal.day_type)
    always_in = signal.always_in.value if hasattr(signal.always_in, "value") else str(signal.always_in)

    if action == "AGUARDAR":
        text = (
            f"Strategy: AGUARDAR. Tipo de dia '{day_type}', always-in '{always_in}'. "
            f"Razao: {signal.reasoning[:140]}"
        )
        return [{
            "type": ThoughtType.OBSERVATION,
            "text_pt": text,
            "concepts": [day_type, always_in.lower()],
            "confidence": signal.confidence,
            "metadata": {
                "decisive_layer": signal.decisive_layer,
                "setup": setup,
            },
        }]

    direction_pt = "compra" if action == "COMPRA" else "venda"
    text = (
        f"Strategy: {direction_pt} via {setup}, dia '{day_type}', always-in '{always_in}'. "
        f"Camada decisiva {signal.decisive_layer}/5. Confianca {signal.confidence}%. "
        f"Entry {signal.entry_price:.1f} stop {signal.stop_loss:.1f} target {signal.take_profit:.1f}."
    )
    return [{
        "type": ThoughtType.HYPOTHESIS,
        "text_pt": text,
        "concepts": [setup, day_type, always_in.lower()],
        "confidence": signal.confidence,
        "metadata": {
            "action": action,
            "setup": setup,
            "decisive_layer": signal.decisive_layer,
            "reward_risk": _safe_rr(signal),
        },
    }]


def _safe_rr(signal: Any) -> Optional[float]:
    try:
        risk = abs(signal.entry_price - signal.stop_loss)
        if risk == 0:
            return None
        return round(abs(signal.take_profit - signal.entry_price) / risk, 2)
    except Exception:
        return None


# ============================================================
# Nogran PA KB lookup narration
# ============================================================

def narrate_kb_match(enriched: Any) -> list[dict]:
    """Describe the Nogran PA KB lookup result + hallucination alarm if any."""
    if enriched is None or enriched.match is None:
        return [{
            "type": ThoughtType.OBSERVATION,
            "text_pt": "PA KB: setup nao mapeado nas entradas disponiveis. Sem ancora numerica.",
            "concepts": [],
            "confidence": 50,
        }]

    m = enriched.match
    payloads = [{
        "type": ThoughtType.OBSERVATION,
        "text_pt": (
            f"PA KB: {m.name_pt} — {m.probability_pct}% "
            f"({m.probability_confidence}). Min R/R: {m.min_reward_risk}. "
            f"LLM={enriched.llm_score} -> blended={enriched.blended_score}"
        ),
        "concepts": [m.setup_id],
        "confidence": m.probability_pct,
        "metadata": {
            "kb_setup_id": m.setup_id,
            "kb_probability": m.probability_pct,
            "llm_score": enriched.llm_score,
            "blended_score": enriched.blended_score,
        },
    }]

    if enriched.alarm:
        a = enriched.alarm
        direction_pt = "otimista" if a.direction == "llm_too_optimistic" else "pessimista"
        payloads.append({
            "type": ThoughtType.ALARM,
            "text_pt": (
                f"ALARME ({a.severity}): LLM {direction_pt} demais. "
                f"llm={a.llm_score} vs PA={a.pa_probability} (gap {a.gap:+d}). "
                "Provavel alucinacao — descontar peso do LLM."
            ),
            "concepts": ["hallucination_alarm", a.setup_id],
            "confidence": 95,
            "metadata": {
                "severity": a.severity,
                "gap": a.gap,
                "direction": a.direction,
            },
        })

    if enriched.rr_warning:
        payloads.append({
            "type": ThoughtType.OBSERVATION,
            "text_pt": enriched.rr_warning,
            "concepts": ["reward_risk_check"],
            "confidence": 60,
        })

    return payloads


# ============================================================
# AI overlay narration
# ============================================================

def narrate_overlay(ao_score: int, regime: Any, signal: Any) -> list[dict]:
    """Describe the AI overlay verdict and detect regime/setup contradictions."""
    regime_str = regime.value if hasattr(regime, "value") else str(regime)

    text = f"AI overlay: regime {regime_str}, score {ao_score}/100."

    payload = {
        "type": ThoughtType.OBSERVATION,
        "text_pt": text,
        "concepts": [f"regime_{regime_str.lower()}"],
        "confidence": ao_score,
        "metadata": {"regime": regime_str, "ao_score": ao_score},
    }
    return [payload]


# ============================================================
# Risk engine narration
# ============================================================

def narrate_risk(rs_score: int, risk_metrics: Any, drawdown: float) -> list[dict]:
    """Describe the risk engine verdict."""
    dd_pct = drawdown * 100
    if drawdown > 0.08:
        text = (
            f"Risk={rs_score}/100. Drawdown {dd_pct:.1f}% > 8% — "
            "CIRCUIT BREAKER, sem operacao."
        )
        return [{
            "type": ThoughtType.VETO,
            "text_pt": text,
            "concepts": ["circuit_breaker", "drawdown_band"],
            "confidence": 100,
            "metadata": {"rs_score": rs_score, "drawdown": round(drawdown, 4)},
        }]

    if drawdown > 0.05:
        band = "MINIMUM (sizing 30%)"
        ttype = ThoughtType.OBSERVATION
    elif drawdown > 0.03:
        band = "DEFENSIVE (sizing 60%)"
        ttype = ThoughtType.OBSERVATION
    else:
        band = "NORMAL (sizing 100%)"
        ttype = ThoughtType.OBSERVATION

    text = f"Risk={rs_score}/100. Drawdown {dd_pct:.2f}%, banda {band}."
    return [{
        "type": ttype,
        "text_pt": text,
        "concepts": ["drawdown_band"],
        "confidence": rs_score,
        "metadata": {"rs_score": rs_score, "drawdown": round(drawdown, 4)},
    }]


# ============================================================
# Final decision narration
# ============================================================

def narrate_decision(decision: Any) -> list[dict]:
    """Describe the final Decision Score verdict."""
    total = decision.total
    threshold = decision.threshold

    if decision.go:
        text = (
            f"DECISAO: GO. Score {total:.1f} > threshold {threshold}. "
            "Edge positivo (probabilidade x reward > risco x (1-prob))."
        )
        return [{
            "type": ThoughtType.DECISION,
            "text_pt": text,
            "concepts": ["traders_equation", "decision_go"],
            "confidence": int(total),
            "metadata": {
                "total": total,
                "threshold": threshold,
                "breakdown": {
                    k: {"score": v.score, "weight": v.weight, "contribution": v.contribution}
                    for k, v in decision.breakdown.items()
                },
            },
        }]

    return [{
        "type": ThoughtType.DECISION,
        "text_pt": (
            f"DECISAO: NO-GO. Score {total:.1f} < threshold {threshold}. "
            f"Razao: {decision.veto_reason or 'score insuficiente'}. "
            "Regra: 'if in doubt, stay out'."
        ),
        "concepts": ["if_in_doubt_stay_out", "decision_no_go"],
        "confidence": 100 - int(total),
        "metadata": {
            "total": total,
            "threshold": threshold,
            "veto_reason": decision.veto_reason,
        },
    }]


# ============================================================
# Veto narration (single-stage hard veto)
# ============================================================

def narrate_veto(stage: str, reason: str, pa_rule: str = "") -> list[dict]:
    """Standardized veto thought with optional PA rule citation."""
    text = f"VETO ({stage}): {reason}"
    if pa_rule:
        text += f" — regra PA: '{pa_rule}'"
    return [{
        "type": ThoughtType.VETO,
        "text_pt": text,
        "concepts": ["hard_veto"] + ([pa_rule] if pa_rule else []),
        "confidence": 100,
        "metadata": {"stage": stage},
    }]
