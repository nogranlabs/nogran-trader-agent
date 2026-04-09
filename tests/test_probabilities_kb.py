"""
Tests for ProbabilitiesKB — Nogran PA knowledge base, blend math, hallucination detector.

Garante:
- KB carrega 62 setups + 22 hard rules sem erro
- Lookup direction-aware funciona (long -> bull setup, short -> bear setup)
- Blend formula esta correta (LLM 60% + Nogran PA 40%)
- Hallucination alarm dispara no gap >= 25 com severity correta
- No-match degrada gracefully
- Backward compat: calculate_strategy_score sem KB nao quebra
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime

from domain.enums import Action, AlwaysIn, DayType, SetupType, SignalBarQuality
from domain.models import TradeSignal
from strategy.probabilities_kb import (
    BLEND_LLM,
    BLEND_PA,
    HALLUCINATION_GAP_THRESHOLD,
    EnrichedScore,
    HallucinationAlarm,
    KBMatch,
    ProbabilitiesKB,
)
from strategy.signal_parser import calculate_strategy_score, calculate_strategy_score_with_kb


def make_signal(
    action=Action.COMPRA,
    setup=SetupType.SECOND_ENTRY_H2,
    confidence=70,
    day_type=DayType.TREND_FROM_OPEN,
    always_in=AlwaysIn.SEMPRE_COMPRADO,
    quality=SignalBarQuality.APROVADO,
):
    return TradeSignal(
        action=action,
        confidence=confidence,
        day_type=day_type,
        always_in=always_in,
        setup=setup,
        signal_bar_quality=quality,
        entry_price=50000.0,
        stop_loss=49500.0,
        take_profit=51000.0,
        decisive_layer=5,
        reasoning="test",
        timestamp=datetime.utcnow(),
    )


@pytest.fixture(scope="module")
def kb():
    return ProbabilitiesKB()


class TestKBLoading:
    def test_kb_loads_setups(self, kb):
        assert len(kb.setups) >= 60, f"Expected 60+ setups, got {len(kb.setups)}"

    def test_kb_loads_hard_rules(self, kb):
        assert len(kb.hard_rules) >= 20, f"Expected 20+ rules, got {len(kb.hard_rules)}"

    def test_kb_metadata_present(self, kb):
        assert kb.metadata.get("version") is not None
        assert kb.metadata.get("total_setups") == len(kb.setups)


class TestLookup:
    def test_h2_long_maps_to_bull_setup(self, kb):
        match = kb.lookup("second_entry_H2", Action.COMPRA)
        assert match is not None
        assert match.setup_id == "high_2_pullback_ma_bull"
        assert match.probability_pct == 60

    def test_h2_short_maps_to_bear_setup(self, kb):
        match = kb.lookup("second_entry_H2", Action.VENDA)
        assert match is not None
        assert match.setup_id == "low_2_pullback_ma_bear"
        assert match.probability_pct == 60

    def test_breakout_pullback_long(self, kb):
        match = kb.lookup("breakout_pullback", Action.COMPRA)
        assert match is not None
        assert match.setup_id == "breakout_pullback_bull_flag"

    def test_shaved_bar_returns_none(self, kb):
        # shaved_bar is not in SETUP_MAPPING
        match = kb.lookup("shaved_bar", Action.COMPRA)
        assert match is None

    def test_unknown_setup_returns_none(self, kb):
        match = kb.lookup("nonexistent_setup", Action.COMPRA)
        assert match is None

    def test_aguardar_returns_none(self, kb):
        match = kb.lookup("second_entry_H2", Action.AGUARDAR)
        assert match is None


class TestBlend:
    def test_blend_formula_basic(self, kb):
        # LLM=80, pa=60 -> 80*0.6 + 60*0.4 = 48 + 24 = 72
        signal = make_signal(action=Action.COMPRA, setup=SetupType.SECOND_ENTRY_H2)
        result = kb.enrich_signal(signal, llm_score=80)
        # Nogran PA H2 bull = 60%
        expected = round(80 * BLEND_LLM + 60 * BLEND_PA)
        assert result.blended_score == expected

    def test_blend_clamped_to_100(self, kb):
        signal = make_signal()
        result = kb.enrich_signal(signal, llm_score=100)
        assert 0 <= result.blended_score <= 100

    def test_blend_clamped_to_0(self, kb):
        signal = make_signal()
        result = kb.enrich_signal(signal, llm_score=0)
        assert 0 <= result.blended_score <= 100

    def test_blend_weights_sum_to_one(self):
        assert BLEND_LLM + BLEND_PA == pytest.approx(1.0)


class TestNoMatchDegradation:
    def test_no_match_keeps_original_score(self, kb):
        signal = make_signal(setup=SetupType.SHAVED_BAR)
        result = kb.enrich_signal(signal, llm_score=75)
        assert result.match is None
        assert result.blended_score == 75
        assert result.alarm is None


class TestHallucinationAlarm:
    def test_no_alarm_when_close(self, kb):
        # LLM=65, pa=60, gap=5 -> no alarm
        signal = make_signal(setup=SetupType.SECOND_ENTRY_H2, action=Action.COMPRA)
        result = kb.enrich_signal(signal, llm_score=65)
        assert result.alarm is None

    def test_alarm_warning_at_gap_25(self, kb):
        # LLM=85, pa=60, gap=+25 -> warning
        signal = make_signal(setup=SetupType.SECOND_ENTRY_H2, action=Action.COMPRA)
        result = kb.enrich_signal(signal, llm_score=85)
        assert result.alarm is not None
        assert result.alarm.gap == 25
        assert result.alarm.direction == "llm_too_optimistic"
        assert result.alarm.severity == "warning"

    def test_alarm_critical_at_gap_40(self, kb):
        # LLM=100, pa=60, gap=+40 -> critical
        signal = make_signal(setup=SetupType.SECOND_ENTRY_H2, action=Action.COMPRA)
        result = kb.enrich_signal(signal, llm_score=100)
        assert result.alarm is not None
        assert result.alarm.gap == 40
        assert result.alarm.severity == "critical"

    def test_alarm_pessimistic_direction(self, kb):
        # LLM=30, pa=60, gap=-30 -> pessimistic warning
        signal = make_signal(setup=SetupType.SECOND_ENTRY_H2, action=Action.COMPRA)
        result = kb.enrich_signal(signal, llm_score=30)
        assert result.alarm is not None
        assert result.alarm.gap == -30
        assert result.alarm.direction == "llm_too_pessimistic"


class TestRRWarning:
    def test_rr_warning_when_below_recommended(self, kb):
        signal = make_signal(setup=SetupType.SECOND_ENTRY_H2, action=Action.COMPRA)
        # H2 bull recommended R/R = 1.5, trade R/R = 1.2
        result = kb.enrich_signal(signal, llm_score=70, trade_rr=1.2)
        assert result.rr_warning is not None
        assert "1.2" in result.rr_warning

    def test_no_rr_warning_when_at_recommended(self, kb):
        signal = make_signal(setup=SetupType.SECOND_ENTRY_H2, action=Action.COMPRA)
        result = kb.enrich_signal(signal, llm_score=70, trade_rr=1.5)
        assert result.rr_warning is None

    def test_no_rr_warning_when_no_match(self, kb):
        signal = make_signal(setup=SetupType.SHAVED_BAR)
        result = kb.enrich_signal(signal, llm_score=70, trade_rr=0.5)
        assert result.rr_warning is None


class TestBackwardCompat:
    def test_calculate_strategy_score_unchanged(self):
        """Funcao original ainda retorna int (nao quebra Decision Scorer tests)."""
        signal = make_signal()
        score = calculate_strategy_score(signal)
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_with_kb_none_returns_llm_score(self):
        """Sem KB, calculate_strategy_score_with_kb deve retornar igual ao original."""
        signal = make_signal()
        result = calculate_strategy_score_with_kb(signal, kb=None)
        assert isinstance(result, EnrichedScore)
        assert result.blended_score == calculate_strategy_score(signal)
        assert result.match is None
        assert result.alarm is None

    def test_with_kb_active_blends(self, kb):
        signal = make_signal(action=Action.COMPRA, setup=SetupType.SECOND_ENTRY_H2)
        result = calculate_strategy_score_with_kb(signal, kb=kb)
        LLM = calculate_strategy_score(signal)
        expected_blend = round(LLM * BLEND_LLM + 60 * BLEND_PA)
        assert result.blended_score == expected_blend
