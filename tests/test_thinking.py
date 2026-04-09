"""
Tests for src/thinking/ — ThoughtStream model, narrator, and mind-change detector.
"""

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from domain.enums import (
    Action,
    AlwaysIn,
    DayType,
    Regime,
    SetupType,
    SignalBarQuality,
)
from domain.models import (
    Candle,
    DecisionScore,
    FeatureSnapshot,
    ScoreBreakdown,
    TradeSignal,
)
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
    narrate_kb_match,
    narrate_overlay,
    narrate_pre_filter,
    narrate_risk,
    narrate_signal,
    narrate_veto,
)

# ============================================================
# Helpers
# ============================================================

def make_candle(o=50000.0, h=50100.0, l=49900.0, c=50080.0, v=10.0, ts=1000):
    return Candle(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def make_features(candle=None, **overrides):
    candle = candle or make_candle()
    base = {
        "candle": candle,
        "candle_index": 100,
        "ema_20": 50000.0,
        "atr_14": 100.0,
        "atr_sma_20": 100.0,
        "adx_14": 25.0,
        "price_vs_ema": 0.16,
        "atr_ratio": 1.0,
        "body_pct": candle.body_pct,
        "upper_tail_pct": candle.upper_tail_pct,
        "lower_tail_pct": candle.lower_tail_pct,
        "consecutive_bull": 1,
        "consecutive_bear": 0,
        "bar_overlap_ratio": 0.3,
        "direction_change_ratio": 0.3,
        "volume_ratio": 1.1,
    }
    base.update(overrides)
    return FeatureSnapshot(**base)


def make_signal(action=Action.COMPRA, conf=75, setup=SetupType.SECOND_ENTRY_H2):
    return TradeSignal(
        action=action,
        confidence=conf,
        day_type=DayType.TREND_FROM_OPEN,
        always_in=AlwaysIn.SEMPRE_COMPRADO,
        setup=setup,
        signal_bar_quality=SignalBarQuality.APROVADO,
        entry_price=50000.0,
        stop_loss=49500.0,
        take_profit=51000.0,
        decisive_layer=5,
        reasoning="test reasoning",
        timestamp=datetime.utcnow(),
    )


def make_decision(total=75.0, go=True, veto_reason=""):
    bd = {
        "market_quality": ScoreBreakdown(score=80, weight=0.20, contribution=16.0),
        "strategy": ScoreBreakdown(score=70, weight=0.35, contribution=24.5),
        "ai_overlay": ScoreBreakdown(score=60, weight=0.20, contribution=12.0),
        "risk": ScoreBreakdown(score=90, weight=0.25, contribution=22.5),
    }
    return DecisionScore(
        total=total, go=go, breakdown=bd, threshold=65,
        hard_veto=False, veto_reason=veto_reason,
    )


# ============================================================
# ThoughtStream model
# ============================================================

class TestThoughtStream:
    def test_empty_stream(self):
        s = ThoughtStream(candle_index=42)
        assert s.candle_index == 42
        assert s.thoughts == []
        assert s.revision_count == 0
        assert not s.has_veto
        assert not s.has_alarm

    def test_add_thought_assigns_id(self):
        s = ThoughtStream(candle_index=10)
        t = s.add(ThoughtStage.FEATURE, ThoughtType.OBSERVATION, "test")
        assert t.id == "t10-001"
        assert t.candle_index == 10
        assert s.thoughts == [t]

    def test_add_increments_id(self):
        s = ThoughtStream(candle_index=10)
        t1 = s.add(ThoughtStage.FEATURE, ThoughtType.OBSERVATION, "a")
        t2 = s.add(ThoughtStage.FEATURE, ThoughtType.OBSERVATION, "b")
        assert t1.id == "t10-001"
        assert t2.id == "t10-002"

    def test_revise_links_to_original(self):
        s = ThoughtStream(candle_index=10)
        original = s.add(ThoughtStage.STRATEGY, ThoughtType.HYPOTHESIS, "buy h2")
        revision = s.revise(original.id, ThoughtStage.AI_OVERLAY, "regime says no")
        assert revision.type == ThoughtType.REVISION
        assert revision.revision_of == original.id
        assert s.revision_count == 1

    def test_find_by_stage(self):
        s = ThoughtStream(candle_index=10)
        s.add(ThoughtStage.FEATURE, ThoughtType.OBSERVATION, "f")
        s.add(ThoughtStage.RISK, ThoughtType.OBSERVATION, "r")
        s.add(ThoughtStage.RISK, ThoughtType.VETO, "v")
        risks = s.find_by_stage(ThoughtStage.RISK)
        assert len(risks) == 2
        assert s.has_veto

    def test_find_by_id(self):
        s = ThoughtStream(candle_index=10)
        t = s.add(ThoughtStage.FEATURE, ThoughtType.OBSERVATION, "x")
        assert s.find_by_id(t.id) is t
        assert s.find_by_id("nonexistent") is None

    def test_confidence_clamped(self):
        s = ThoughtStream(candle_index=10)
        t1 = s.add(ThoughtStage.FEATURE, ThoughtType.OBSERVATION, "x", confidence=200)
        t2 = s.add(ThoughtStage.FEATURE, ThoughtType.OBSERVATION, "y", confidence=-10)
        assert t1.confidence == 100
        assert t2.confidence == 0

    def test_to_dict_serializes(self):
        s = ThoughtStream(candle_index=10)
        s.add(ThoughtStage.FEATURE, ThoughtType.OBSERVATION, "x")
        s.add(ThoughtStage.RISK, ThoughtType.VETO, "v")
        d = s.to_dict()
        assert d["candle_index"] == 10
        assert d["thought_count"] == 2
        assert d["has_veto"] is True
        assert len(d["thoughts"]) == 2
        # Stage and type should be serialized as strings
        assert d["thoughts"][0]["stage"] == "feature"
        assert d["thoughts"][0]["type"] == "observation"

    def test_alarm_detection(self):
        s = ThoughtStream(candle_index=10)
        s.add(ThoughtStage.KB_LOOKUP, ThoughtType.ALARM, "hallucination!")
        assert s.has_alarm


# ============================================================
# Narrator: bar narration
# ============================================================

class TestNarrateBar:
    def test_strong_trend_bar_emits_observation(self):
        # Body 80%, no tails -> strong trend bar
        candle = make_candle(o=50000, h=50104, l=50000, c=50100)
        feats = make_features(candle=candle)
        payloads = narrate_bar(feats)
        assert len(payloads) >= 1
        assert payloads[0]["type"] == ThoughtType.OBSERVATION
        assert "trend bar" in payloads[0]["text_pt"].lower()

    def test_doji_emits_doji_concept(self):
        # Tiny body
        candle = make_candle(o=50000, h=50100, l=49900, c=50001)
        feats = make_features(candle=candle, body_pct=0.5)
        payloads = narrate_bar(feats)
        assert any("doji" in p["text_pt"].lower() for p in payloads)
        assert "doji_bar" in payloads[0]["concepts"]

    def test_bull_spike_4_consecutive(self):
        feats = make_features(consecutive_bull=5, consecutive_bear=0)
        payloads = narrate_bar(feats)
        assert any("spike phase" in p["text_pt"].lower() for p in payloads)

    def test_bear_spike_4_consecutive(self):
        feats = make_features(consecutive_bear=4, consecutive_bull=0)
        payloads = narrate_bar(feats)
        assert any("bear spike" in p["text_pt"].lower() for p in payloads)


# ============================================================
# Narrator: pre-filter narration
# ============================================================

class TestNarratePreFilter:
    def test_chop_emits_veto(self):
        feats = make_features(bar_overlap_ratio=0.7, direction_change_ratio=0.6)
        payloads = narrate_pre_filter(20, feats)
        assert payloads[0]["type"] == ThoughtType.VETO
        assert "tight" in payloads[0]["text_pt"].lower()
        assert "tight_tr_trumps_all" in payloads[0]["concepts"]

    def test_clean_market_high_confidence(self):
        feats = make_features(bar_overlap_ratio=0.2)
        payloads = narrate_pre_filter(85, feats)
        assert payloads[0]["type"] == ThoughtType.OBSERVATION
        assert payloads[0]["confidence"] >= 80

    def test_marginal_market(self):
        feats = make_features()
        payloads = narrate_pre_filter(40, feats)
        assert payloads[0]["type"] == ThoughtType.OBSERVATION
        assert payloads[0]["confidence"] == 60


# ============================================================
# Narrator: signal (Strategy Engine) narration
# ============================================================

class TestNarrateSignal:
    def test_buy_emits_hypothesis(self):
        sig = make_signal(action=Action.COMPRA, conf=80)
        payloads = narrate_signal(sig)
        assert payloads[0]["type"] == ThoughtType.HYPOTHESIS
        assert "compra" in payloads[0]["text_pt"].lower()
        assert payloads[0]["confidence"] == 80

    def test_aguardar_emits_observation(self):
        sig = make_signal(action=Action.AGUARDAR)
        payloads = narrate_signal(sig)
        assert payloads[0]["type"] == ThoughtType.OBSERVATION
        assert "aguardar" in payloads[0]["text_pt"].lower()

    def test_none_signal_handled(self):
        payloads = narrate_signal(None)
        assert payloads[0]["confidence"] == 0
        assert "strategy engine" in payloads[0]["text_pt"].lower()

    def test_setup_in_concepts(self):
        sig = make_signal(setup=SetupType.SECOND_ENTRY_H2)
        payloads = narrate_signal(sig)
        assert "second_entry_H2" in payloads[0]["concepts"]


# ============================================================
# Narrator: KB match
# ============================================================

class TestNarrateKBMatch:
    def test_match_emits_observation(self):
        match = SimpleNamespace(
            setup_id="high_2_pullback_ma_bull",
            name_pt="High 2 pullback",
            probability_pct=60,
            probability_confidence="explicit",
            min_reward_risk=1.5,
        )
        enriched = SimpleNamespace(
            match=match, llm_score=70, blended_score=66,
            alarm=None, rr_warning=None,
        )
        payloads = narrate_kb_match(enriched)
        assert len(payloads) == 1
        assert payloads[0]["type"] == ThoughtType.OBSERVATION
        assert "60%" in payloads[0]["text_pt"]
        assert "high_2_pullback_ma_bull" in payloads[0]["concepts"]

    def test_no_match_handled(self):
        enriched = SimpleNamespace(match=None, llm_score=0, blended_score=0, alarm=None, rr_warning=None)
        payloads = narrate_kb_match(enriched)
        assert "nao mapeado" in payloads[0]["text_pt"]

    def test_alarm_emits_alarm_thought(self):
        match = SimpleNamespace(
            setup_id="high_2_pullback_ma_bull",
            name_pt="H2",
            probability_pct=60,
            probability_confidence="explicit",
            min_reward_risk=1.5,
        )
        alarm = SimpleNamespace(
            severity="critical",
            gap=45,
            direction="llm_too_optimistic",
            llm_score=100,
            pa_probability=60,
            setup_id="high_2_pullback_ma_bull",
        )
        enriched = SimpleNamespace(
            match=match, llm_score=100, blended_score=84,
            alarm=alarm, rr_warning=None,
        )
        payloads = narrate_kb_match(enriched)
        assert len(payloads) == 2
        assert payloads[1]["type"] == ThoughtType.ALARM
        assert "critical" in payloads[1]["text_pt"]


# ============================================================
# Narrator: overlay, risk, decision, veto
# ============================================================

class TestNarrateOverlay:
    def test_basic(self):
        sig = make_signal()
        payloads = narrate_overlay(75, Regime.TRENDING, sig)
        assert payloads[0]["type"] == ThoughtType.OBSERVATION
        assert "trending" in payloads[0]["text_pt"].lower()


class TestNarrateRisk:
    def test_circuit_breaker(self):
        payloads = narrate_risk(20, None, drawdown=0.10)
        assert payloads[0]["type"] == ThoughtType.VETO
        assert "circuit breaker" in payloads[0]["text_pt"].lower()

    def test_normal(self):
        payloads = narrate_risk(80, None, drawdown=0.01)
        assert payloads[0]["type"] == ThoughtType.OBSERVATION
        assert "normal" in payloads[0]["text_pt"].lower()


class TestNarrateDecision:
    def test_go_decision(self):
        d = make_decision(total=75, go=True)
        payloads = narrate_decision(d)
        assert payloads[0]["type"] == ThoughtType.DECISION
        assert "go" in payloads[0]["text_pt"].lower()
        assert "traders_equation" in payloads[0]["concepts"]

    def test_no_go_decision(self):
        d = make_decision(total=50, go=False, veto_reason="low score")
        payloads = narrate_decision(d)
        assert payloads[0]["type"] == ThoughtType.DECISION
        assert "no-go" in payloads[0]["text_pt"].lower()


class TestNarrateVeto:
    def test_basic(self):
        payloads = narrate_veto("risk", "drawdown 9%")
        assert payloads[0]["type"] == ThoughtType.VETO
        assert "drawdown" in payloads[0]["text_pt"]

    def test_with_pa_rule(self):
        payloads = narrate_veto("strategy", "no setup", "if_in_doubt_stay_out")
        assert "if_in_doubt_stay_out" in payloads[0]["concepts"]


# ============================================================
# Mind-change detector
# ============================================================

class TestDetectMindChanges:
    def test_no_thoughts_no_revisions(self):
        s = ThoughtStream(candle_index=1)
        assert detect_mind_changes(s) == []

    def test_strategy_vs_overlay_transitioning(self):
        s = ThoughtStream(candle_index=1)
        s.add(
            ThoughtStage.STRATEGY, ThoughtType.HYPOTHESIS, "buy h2",
            metadata={"action": "COMPRA"},
        )
        s.add(
            ThoughtStage.AI_OVERLAY, ThoughtType.OBSERVATION, "transitioning",
            metadata={"regime": "TRANSITIONING"},
        )
        revisions = detect_mind_changes(s)
        assert len(revisions) >= 1
        assert any("regime_contradiction" in r["concepts"] for r in revisions)

    def test_strategy_with_trending_no_revision(self):
        s = ThoughtStream(candle_index=1)
        s.add(
            ThoughtStage.STRATEGY, ThoughtType.HYPOTHESIS, "buy h2",
            metadata={"action": "COMPRA"},
        )
        s.add(
            ThoughtStage.AI_OVERLAY, ThoughtType.OBSERVATION, "trending",
            metadata={"regime": "TRENDING"},
        )
        revisions = detect_mind_changes(s)
        # The TRANSITIONING rule should not fire here
        regime_revs = [r for r in revisions if "regime_contradiction" in r.get("concepts", [])]
        assert regime_revs == []

    def test_hallucination_alarm_creates_revision(self):
        s = ThoughtStream(candle_index=1)
        target = s.add(
            ThoughtStage.STRATEGY, ThoughtType.HYPOTHESIS, "buy",
            metadata={"action": "COMPRA"},
        )
        s.add(
            ThoughtStage.KB_LOOKUP, ThoughtType.ALARM, "alarm",
            metadata={"severity": "critical", "gap": 40},
        )
        revisions = detect_mind_changes(s)
        assert any(r["original_id"] == target.id for r in revisions)
        assert any("hallucination_alarm" in r["concepts"] for r in revisions)

    def test_risk_veto_revises_strategy(self):
        s = ThoughtStream(candle_index=1)
        target = s.add(
            ThoughtStage.STRATEGY, ThoughtType.HYPOTHESIS, "buy",
            metadata={"action": "COMPRA"},
        )
        s.add(ThoughtStage.RISK, ThoughtType.VETO, "drawdown")
        revisions = detect_mind_changes(s)
        assert any(r["original_id"] == target.id for r in revisions)
        assert any("risk_veto" in r["concepts"] for r in revisions)

    def test_pre_filter_dissonance_with_high_conf_signal(self):
        s = ThoughtStream(candle_index=1)
        s.add(ThoughtStage.PRE_FILTER, ThoughtType.VETO, "chop")
        target = s.add(
            ThoughtStage.STRATEGY, ThoughtType.HYPOTHESIS, "buy with high conf",
            confidence=85,
            metadata={"action": "COMPRA"},
        )
        revisions = detect_mind_changes(s)
        assert any("tight_tr_trumps_all" in r["concepts"] for r in revisions)
        assert any(r["original_id"] == target.id for r in revisions)
