"""Tests for Decision Scorer — validates weights, threshold, and hard veto logic."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai.decision_scorer import DecisionScorer


@pytest.fixture
def scorer():
    return DecisionScorer()


class TestWeights:
    def test_weights_match_documented_values(self, scorer):
        """CLAUDE.md:52 — MQ 20%, SS 35%, AO 20%, RS 25%"""
        assert scorer.WEIGHTS["market_quality"] == 0.20
        assert scorer.WEIGHTS["strategy"] == 0.35
        assert scorer.WEIGHTS["ai_overlay"] == 0.20
        assert scorer.WEIGHTS["risk"] == 0.25

    def test_weights_sum_to_one(self, scorer):
        assert sum(scorer.WEIGHTS.values()) == pytest.approx(1.0)


class TestThreshold:
    def test_default_threshold_is_65(self, scorer):
        assert scorer.threshold == 65


class TestScoreCalculation:
    def test_all_100_returns_100(self, scorer):
        result = scorer.calculate(100, 100, 100, 100)
        assert result.total == 100.0
        assert result.go is True

    def test_all_zero_returns_zero_with_veto(self, scorer):
        result = scorer.calculate(0, 0, 0, 0)
        assert result.total == 0.0
        assert result.go is False
        assert result.hard_veto is True

    def test_weighted_calculation(self, scorer):
        # MQ=80*0.20 + SS=70*0.35 + AO=60*0.20 + RS=90*0.25
        # = 16 + 24.5 + 12 + 22.5 = 75.0
        result = scorer.calculate(80, 70, 60, 90)
        assert result.total == 75.0
        assert result.go is True

    def test_below_threshold_is_no_go(self, scorer):
        # MQ=50*0.20 + SS=50*0.35 + AO=50*0.20 + RS=50*0.25 = 50.0
        result = scorer.calculate(50, 50, 50, 50)
        assert result.total == 50.0
        assert result.go is False
        assert "Score 50.0 < threshold 65" in result.veto_reason


class TestHardVeto:
    def test_single_subscore_below_20_vetoes(self, scorer):
        # High total but MQ=10 < 20
        result = scorer.calculate(10, 100, 100, 100)
        assert result.go is False
        assert result.hard_veto is True
        assert "MQ=10" in result.veto_reason

    def test_exactly_20_does_not_veto(self, scorer):
        result = scorer.calculate(20, 100, 100, 100)
        assert result.hard_veto is False

    def test_multiple_subscores_below_20(self, scorer):
        result = scorer.calculate(10, 15, 100, 100)
        assert result.hard_veto is True
        assert "MQ=10" in result.veto_reason
        assert "SS=15" in result.veto_reason


class TestBreakdown:
    def test_breakdown_has_all_components(self, scorer):
        result = scorer.calculate(80, 70, 60, 90)
        assert set(result.breakdown.keys()) == {
            "market_quality", "strategy", "ai_overlay", "risk"
        }

    def test_breakdown_contributions_sum_to_total(self, scorer):
        result = scorer.calculate(80, 70, 60, 90)
        contrib_sum = sum(b.contribution for b in result.breakdown.values())
        assert contrib_sum == pytest.approx(result.total, abs=0.1)
