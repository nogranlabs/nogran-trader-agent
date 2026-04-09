"""
simulate_market.py — offline market simulation for auditing the agent's
reasoning without needing a live LLM / Kraken / postgres stack.

Generates synthetic BTC/USD 1-minute candles that traverse a series of
PA-style market phases (chop -> bull spike -> channel -> wedge top
-> reversal), runs them through the same feature engine + pre-filter
+ KB lookup + AI overlay + risk engine + decision scorer that the live
pipeline uses, and writes:

    logs/decisions/<date>.jsonl       — same audit format as live
    logs/decisions/thoughts-<date>.jsonl  — thought streams per candle

The simulation also exercises the mind-change detector (revisions),
hallucination alarm (when the mocked LLM response over- or under-
estimates a setup vs the PA KB), and risk veto.

Usage:
    python scripts/simulate_market.py
    python scripts/simulate_market.py --candles 200 --seed 7
    python scripts/simulate_market.py --output-dir logs/sim
"""

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make src importable when running as a script
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ai.decision_scorer import DecisionScorer  # noqa: E402
from domain.enums import Action, AlwaysIn, DayType, Regime, SetupType, SignalBarQuality  # noqa: E402
from domain.models import Candle, FeatureSnapshot, TradeSignal  # noqa: E402
from market.candle_buffer import CandleBuffer  # noqa: E402
from market.feature_engine import FeatureEngine  # noqa: E402
from market.pre_filter import calculate_mq_score  # noqa: E402
from strategy.probabilities_kb import ProbabilitiesKB  # noqa: E402
from strategy.signal_parser import calculate_strategy_score_with_kb  # noqa: E402
from thinking import (  # noqa: E402
    ThoughtStage,
    ThoughtStream,
    detect_mind_changes,
    narrate_bar,
    narrate_decision,
    narrate_overlay,
    narrate_pre_filter,
    narrate_risk,
    narrate_signal,
)
from thinking.narrator import narrate_kb_match  # noqa: E402

# ============================================================
# Synthetic candle generator
# ============================================================

def generate_pa_phases(n: int, seed: int = 42) -> list[Candle]:
    """Generate n candles that walk through PA-style market phases.

    Phases (proportional to n):
      1. tight chop          (~20%)  — tight TR, MQ should veto
      2. bull spike          (~15%)  — strong consecutive bull bars
      3. bull channel        (~25%)  — pullbacks to EMA, H2 setups
      4. wedge top           (~15%)  — three pushes up, weakening
      5. reversal + spike dn (~15%)  — bear reversal entries
      6. bear channel        (~10%)  — L2 setups
    """
    rng = random.Random(seed)
    candles: list[Candle] = []
    price = 67_000.0
    ts0 = int(datetime(2026, 4, 8, 13, 0, tzinfo=timezone.utc).timestamp() * 1000)

    p1 = int(n * 0.20)
    p2 = int(n * 0.15)
    p3 = int(n * 0.25)
    p4 = int(n * 0.15)
    p5 = int(n * 0.15)
    p6 = n - (p1 + p2 + p3 + p4 + p5)

    def make(o, h, l, c) -> Candle:
        nonlocal ts0
        ts0 += 60_000
        return Candle(
            timestamp=ts0,
            open=o, high=max(o, h, c), low=min(o, l, c), close=c,
            volume=rng.uniform(5, 20),
        )

    # Phase 1: tight chop
    for _ in range(p1):
        delta = rng.uniform(-15, 15)
        new_price = price + delta
        h = max(price, new_price) + rng.uniform(2, 8)
        l = min(price, new_price) - rng.uniform(2, 8)
        candles.append(make(price, h, l, new_price))
        price = new_price

    # Phase 2: bull spike (strong directional)
    for _i in range(p2):
        body = rng.uniform(40, 90)
        new_price = price + body
        h = new_price + rng.uniform(0, 5)
        l = price - rng.uniform(0, 3)
        candles.append(make(price, h, l, new_price))
        price = new_price

    # Phase 3: bull channel (with H2 pullbacks)
    for i in range(p3):
        if i % 5 in (3, 4):  # pullback bars
            body = -rng.uniform(15, 30)
        else:
            body = rng.uniform(20, 50)
        new_price = price + body
        h = max(price, new_price) + rng.uniform(3, 10)
        l = min(price, new_price) - rng.uniform(3, 10)
        candles.append(make(price, h, l, new_price))
        price = new_price

    # Phase 4: wedge top — three pushes with smaller bodies + tails
    for _ in range(p4):
        body = rng.uniform(5, 25)
        new_price = price + body
        # Bigger upper tails (rejection at the top)
        h = max(price, new_price) + rng.uniform(15, 35)
        l = min(price, new_price) - rng.uniform(2, 8)
        candles.append(make(price, h, l, new_price))
        price = new_price

    # Phase 5: bear reversal + spike down
    for _i in range(p5):
        body = -rng.uniform(30, 80)
        new_price = price + body
        h = price + rng.uniform(0, 5)
        l = new_price - rng.uniform(0, 5)
        candles.append(make(price, h, l, new_price))
        price = new_price

    # Phase 6: bear channel with L2 setups
    for i in range(p6):
        if i % 5 in (3, 4):
            body = rng.uniform(10, 25)  # pullback up
        else:
            body = -rng.uniform(15, 40)
        new_price = price + body
        h = max(price, new_price) + rng.uniform(3, 10)
        l = min(price, new_price) - rng.uniform(3, 10)
        candles.append(make(price, h, l, new_price))
        price = new_price

    return candles


# ============================================================
# Mock LLM response — PA-aware deterministic responder
# ============================================================

def mock_llm_response(features: FeatureSnapshot, regime: Regime,
                      hallucinate: bool = False,
                      strict_trend_alignment: bool = False) -> TradeSignal:
    """Build a TradeSignal that a real Strategy Engine might produce.

    Heuristics roughly mirror core rule:
    - Strong consecutive bull bars + high body% in trending regime -> H2 BUY
    - Strong consecutive bear bars + bearish bias -> L2 SELL
    - Choppy/transitioning -> AGUARDAR
    - In wedge-top phases (large upper tails, slowing momentum) -> SELL hypothesis

    `hallucinate=True` flips the confidence to make the LLM look overly
    optimistic/pessimistic vs the PA KB — used to exercise the
    hallucination detector in the audit.

    `strict_trend_alignment=True` adds counter-trend guards (PA rule:
    "NUNCA opere contra tendencia sem quebra de LT significativa"). Em
    uptrends fortes (price > EMA por >0.8%), bloqueia wedge-top SHORTs e
    L2 SELLs. Em downtrends fortes (-0.8%), bloqueia bull continuations.
    Use no backtest pra evitar viés counter-trend; deixe False na demo
    sintetica pra exercitar mais codigo.
    """
    candle = features.candle
    ema_diff = features.price_vs_ema
    body = features.body_pct
    consec_bull = features.consecutive_bull
    consec_bear = features.consecutive_bear
    upper_tail = features.upper_tail_pct
    is_bull = candle.is_bullish

    # Trend alignment thresholds (em pct: +/-0.8% da EMA)
    STRONG_UP = 0.8
    STRONG_DOWN = -0.8

    # Choppy / transitioning -> wait
    if regime == Regime.RANGING or features.bar_overlap_ratio > 0.55:
        return _make_signal(Action.AGUARDAR, 30, "trending_trading_range",
                            AlwaysIn.NEUTRO, SetupType.NONE, "Mercado em trading range, aguardar quebra.",
                            entry=candle.close, stop=candle.close, target=candle.close)

    # Wedge top: large upper tails after a run-up -> SELL hypothesis
    # Counter-trend guard: NAO shortar em uptrend forte (>+0.8% da EMA)
    wedge_top_ok = upper_tail >= 30 and features.consecutive_bull >= 2 and ema_diff > 0
    if strict_trend_alignment and ema_diff > STRONG_UP:
        wedge_top_ok = False  # uptrend forte: nao shortar wedge top
    if wedge_top_ok:
        conf = 80 if hallucinate else 55
        return _make_signal(
            Action.VENDA, conf, "reversal_day", AlwaysIn.NEUTRO,
            SetupType.BREAKOUT_PULLBACK,
            "Wedge top — tres empurroes para cima, tail superior crescendo.",
            entry=candle.close, stop=candle.close + features.atr_14,
            target=candle.close - features.atr_14 * 2,
        )

    # Bull continuation H2
    # Counter-trend guard: NAO comprar em downtrend forte (<-0.8% da EMA)
    bull_ok = is_bull and consec_bull >= 2 and ema_diff > -0.5 and body >= 40
    if strict_trend_alignment and ema_diff < STRONG_DOWN:
        bull_ok = False
    if bull_ok:
        conf = 92 if hallucinate else 72
        return _make_signal(
            Action.COMPRA, conf, "trend_from_open", AlwaysIn.SEMPRE_COMPRADO,
            SetupType.SECOND_ENTRY_H2,
            "Pullback completou H2 acima da EMA20 — segunda entrada em bull trend.",
            entry=candle.close, stop=candle.close - features.atr_14,
            target=candle.close + features.atr_14 * 2,
        )

    # Bear continuation L2
    # Counter-trend guard: NAO shortar em uptrend forte (>+0.8% da EMA)
    bear_ok = not is_bull and consec_bear >= 2 and ema_diff < 0.5 and body >= 40
    if strict_trend_alignment and ema_diff > STRONG_UP:
        bear_ok = False
    if bear_ok:
        conf = 92 if hallucinate else 72
        return _make_signal(
            Action.VENDA, conf, "spike_and_channel", AlwaysIn.SEMPRE_VENDIDO,
            SetupType.SECOND_ENTRY_H2,
            "Pullback completou L2 abaixo da EMA20 — segunda entrada em bear trend.",
            entry=candle.close, stop=candle.close + features.atr_14,
            target=candle.close - features.atr_14 * 2,
        )

    # NEW: Bull H2 setup quando ainda tem espaco mas momentum atual e pequeno.
    # Em uptrends fortes (>+0.8% EMA) compramos pullbacks tecnicos mesmo
    # sem ter acabado de fazer 2 bullbars consecutivos — eh o "with-trend"
    # bias do Nogran PA (Cap. 19, Always-In Long).
    if strict_trend_alignment and ema_diff > STRONG_UP and is_bull and consec_bull >= 1:
        conf = 65
        return _make_signal(
            Action.COMPRA, conf, "trend_from_open", AlwaysIn.SEMPRE_COMPRADO,
            SetupType.H2_EMA,
            "Always-in long — uptrend forte, comprar pullback tecnico.",
            entry=candle.close, stop=candle.close - features.atr_14,
            target=candle.close + features.atr_14 * 2,
        )
    # Symmetric: bear pullback in strong downtrend
    if strict_trend_alignment and ema_diff < STRONG_DOWN and not is_bull and consec_bear >= 1:
        conf = 65
        return _make_signal(
            Action.VENDA, conf, "spike_and_channel", AlwaysIn.SEMPRE_VENDIDO,
            SetupType.H2_EMA,
            "Always-in short — downtrend forte, vender pullback tecnico.",
            entry=candle.close, stop=candle.close + features.atr_14,
            target=candle.close - features.atr_14 * 2,
        )

    return _make_signal(Action.AGUARDAR, 25, "indefinido", AlwaysIn.NEUTRO,
                        SetupType.NONE, "Sem sinal claro nesta barra.",
                        entry=candle.close, stop=candle.close, target=candle.close)


def _make_signal(action, conf, day_type, always_in, setup, reason, entry, stop, target):
    return TradeSignal(
        action=action,
        confidence=conf,
        day_type=DayType(day_type),
        always_in=AlwaysIn(always_in),
        setup=setup,
        signal_bar_quality=SignalBarQuality.APROVADO,
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        decisive_layer=5 if action != Action.AGUARDAR else 1,
        reasoning=reason,
        timestamp=datetime.now(timezone.utc),
    )


# ============================================================
# Mock regime detector
# ============================================================

def mock_regime(features: FeatureSnapshot) -> Regime:
    if features.adx_14 >= 25 and features.bar_overlap_ratio < 0.45:
        return Regime.TRENDING
    if features.bar_overlap_ratio > 0.55:
        return Regime.RANGING
    return Regime.TRANSITIONING


# ============================================================
# Decision logger that also writes thought streams
# ============================================================

class SimAuditLogger:
    """Lightweight logger that writes both decisions.jsonl and thoughts.jsonl."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        date = datetime.now(timezone.utc).date().isoformat()
        self.decisions_path = output_dir / f"{date}.jsonl"
        self.thoughts_path = output_dir / f"thoughts-{date}.jsonl"
        # Truncate previous run for a clean audit
        self.decisions_path.write_text("", encoding="utf-8")
        self.thoughts_path.write_text("", encoding="utf-8")

    def log_decision(self, entry: dict):
        with open(self.decisions_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_thoughts(self, stream: ThoughtStream):
        with open(self.thoughts_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(stream.to_dict(), ensure_ascii=False) + "\n")


# ============================================================
# Main simulation loop
# ============================================================

def run_simulation(n_candles: int, seed: int, output_dir: Path):
    candles = generate_pa_phases(n_candles, seed)
    print(f"Generated {len(candles)} candles across 6 Nogran PA phases.")

    feature_engine = FeatureEngine()
    buf_1m = CandleBuffer(maxlen=200)
    decision_scorer = DecisionScorer()
    kb = ProbabilitiesKB()
    logger = SimAuditLogger(output_dir)

    stats = {
        "total": 0,
        "go": 0,
        "no_go": 0,
        "vetoes_pre_filter": 0,
        "vetoes_risk": 0,
        "alarms": 0,
        "revisions": 0,
    }

    for idx, candle in enumerate(candles):
        buf_1m.add(candle)
        if idx < 25:  # warmup
            continue
        features = feature_engine.compute(buf_1m, candle_index=idx)
        if features is None:
            continue

        stream = ThoughtStream(candle_index=idx)
        stats["total"] += 1

        # Stage 1: bar observation
        for p in narrate_bar(features):
            stream.add(stage=ThoughtStage.FEATURE, **p)

        # Stage 2: pre-filter MQ
        mq_score = calculate_mq_score(features)
        for p in narrate_pre_filter(mq_score, features):
            stream.add(stage=ThoughtStage.PRE_FILTER, **p)

        if mq_score < 30:
            stats["vetoes_pre_filter"] += 1
            decision = decision_scorer.calculate(mq_score, 0, 50, 50)
            for p in narrate_decision(decision):
                stream.add(stage=ThoughtStage.DECISION, **p)
            _flush(logger, stream, decision, stats, candle, mq_score)
            continue

        # Stage 3: regime + Strategy Engine (mocked)
        regime = mock_regime(features)
        # Hallucinate every 7th candle to exercise the alarm
        hallucinate = idx % 7 == 0
        signal = mock_llm_response(features, regime, hallucinate=hallucinate)
        for p in narrate_signal(signal):
            stream.add(stage=ThoughtStage.STRATEGY, **p)

        if signal.action == Action.AGUARDAR:
            decision = decision_scorer.calculate(mq_score, 0, 50, 50)
            for p in narrate_decision(decision):
                stream.add(stage=ThoughtStage.DECISION, **p)
            _flush(logger, stream, decision, stats, candle, mq_score, signal=signal, regime=regime)
            continue

        # Stage 4: KB enrichment + hallucination detector
        enriched = calculate_strategy_score_with_kb(signal, kb=kb)
        for p in narrate_kb_match(enriched):
            stream.add(stage=ThoughtStage.KB_LOOKUP, **p)

        ss_score = enriched.blended_score
        if enriched.alarm:
            stats["alarms"] += 1

        # Stage 5: AI overlay (simplified — score from regime + signal alignment)
        ao_score = _mock_ao_score(regime, signal, features)
        for p in narrate_overlay(ao_score, regime, signal):
            stream.add(stage=ThoughtStage.AI_OVERLAY, **p)

        # Stage 6: risk engine
        # Synthetic drawdown that grows mid-simulation to trigger a veto
        synthetic_dd = 0.01 + (idx % 50) * 0.002
        if synthetic_dd > 0.08:
            # Circuit breaker — drop rs_score below 20 to force a hard veto
            rs_score = 10
            stats["vetoes_risk"] += 1
        else:
            rs_score = max(25, int(80 - synthetic_dd * 500))
        for p in narrate_risk(rs_score, None, synthetic_dd):
            stream.add(
                stage=ThoughtStage.RISK,
                **p,
            )

        # Stage 7: decision
        decision = decision_scorer.calculate(mq_score, ss_score, ao_score, rs_score)
        for p in narrate_decision(decision):
            stream.add(stage=ThoughtStage.DECISION, **p)

        # Stage 8: mind-change detection (after all evidence is in)
        revisions = detect_mind_changes(stream)
        for r in revisions:
            stream.revise(
                original_id=r["original_id"],
                stage=r["stage"],
                text_pt=r["text_pt"],
                concepts=r.get("concepts", []),
                confidence=r.get("confidence", 70),
                metadata=r.get("metadata", {}),
            )
        stats["revisions"] += len(revisions)

        _flush(logger, stream, decision, stats, candle, mq_score, signal=signal, regime=regime, ss=ss_score, ao=ao_score, rs=rs_score, enriched=enriched)

    return stats, logger


def _mock_ao_score(regime: Regime, signal: TradeSignal, features: FeatureSnapshot) -> int:
    """Simple AI overlay scoring for the simulation."""
    base = 50
    if regime == Regime.TRENDING:
        base += 20
    elif regime == Regime.RANGING:
        base -= 15
    if signal.always_in == AlwaysIn.SEMPRE_COMPRADO and signal.action == Action.COMPRA:
        base += 15
    elif signal.always_in == AlwaysIn.SEMPRE_VENDIDO and signal.action == Action.VENDA:
        base += 15
    if features.adx_14 >= 30:
        base += 10
    return max(0, min(100, base))


def _flush(logger, stream, decision, stats, candle, mq_score,
           signal=None, regime=None, ss=0, ao=50, rs=50, enriched=None):
    if decision.go:
        stats["go"] += 1
    else:
        stats["no_go"] += 1

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "candle_index": stream.candle_index,
        "candle": {
            "timestamp": candle.timestamp,
            "open": candle.open, "high": candle.high,
            "low": candle.low, "close": candle.close,
        },
        "mq_score": mq_score,
        "regime": regime.value if regime else "",
        "decision_score": {
            "total": decision.total,
            "go": decision.go,
            "hard_veto": decision.hard_veto,
            "veto_reason": decision.veto_reason,
            "threshold": decision.threshold,
            "breakdown": {
                k: {"score": v.score, "weight": v.weight, "contribution": v.contribution}
                for k, v in decision.breakdown.items()
            },
        },
        "executed": decision.go,
    }
    if signal:
        entry["signal"] = {
            "action": signal.action.value,
            "confidence": signal.confidence,
            "day_type": signal.day_type.value,
            "always_in": signal.always_in.value,
            "setup": signal.setup.value,
            "signal_bar_quality": signal.signal_bar_quality.value,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "decisive_layer": signal.decisive_layer,
            "reasoning": signal.reasoning,
        }
    if enriched and enriched.match:
        entry["kb_match"] = {
            "setup_id": enriched.match.setup_id,
            "name_pt": enriched.match.name_pt,
            "probability_pct": enriched.match.probability_pct,
            "llm_score": enriched.llm_score,
            "blended_score": enriched.blended_score,
            "book_refs": enriched.match.book_refs,
        }
    if enriched and enriched.alarm:
        a = enriched.alarm
        entry["hallucination_alarm"] = {
            "llm_score": a.llm_score,
            "pa_probability": a.pa_probability,
            "gap": a.gap,
            "direction": a.direction,
            "setup_id": a.setup_id,
            "severity": a.severity,
        }
    logger.log_decision(entry)
    logger.log_thoughts(stream)


# ============================================================
# Entry point
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Offline market simulation + audit")
    parser.add_argument("--candles", type=int, default=200, help="number of candles to generate")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    parser.add_argument(
        "--output-dir", type=str,
        default=str(ROOT / "logs" / "decisions"),
        help="where to write decisions.jsonl + thoughts-<date>.jsonl",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    print(f"Simulating {args.candles} candles (seed={args.seed}) -> {output_dir}")
    stats, logger = run_simulation(args.candles, args.seed, output_dir)

    print()
    print("=" * 60)
    print("SIMULATION SUMMARY")
    print("=" * 60)
    print(f"  total decisions       : {stats['total']}")
    print(f"  GO                    : {stats['go']}")
    print(f"  NO-GO                 : {stats['no_go']}")
    print(f"  pre-filter vetoes     : {stats['vetoes_pre_filter']}")
    print(f"  risk vetoes           : {stats['vetoes_risk']}")
    print(f"  hallucination alarms  : {stats['alarms']}")
    print(f"  mind-change revisions : {stats['revisions']}")
    print()
    print(f"  decisions: {logger.decisions_path}")
    print(f"  thoughts:  {logger.thoughts_path}")


if __name__ == "__main__":
    main()
