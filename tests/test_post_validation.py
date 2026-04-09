"""Tests for scripts/post_validation.py — score composto sem rede."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from post_validation import (  # noqa: E402
    ValidationScoreBreakdown,
    _sigmoid,
    compute_pnl_component,
    compute_quality_component,
    compute_risk_component,
    compute_validation_score,
)

# ============================================================
# sigmoid
# ============================================================


class TestSigmoid:
    def test_zero(self):
        assert _sigmoid(0) == pytest.approx(0.5)

    def test_large_positive(self):
        assert _sigmoid(100) == pytest.approx(1.0, rel=1e-3)

    def test_large_negative(self):
        assert _sigmoid(-100) == pytest.approx(0.0, abs=1e-3)

    def test_overflow_safe(self):
        # Should not raise
        _sigmoid(1e6)
        _sigmoid(-1e6)


# ============================================================
# compute_pnl_component
# ============================================================


class TestPnLComponent:
    def test_neutral_sharpe_no_dd(self):
        # sharpe 0, dd 0 → ~50
        s = compute_pnl_component(sharpe=0, max_dd_pct=0)
        assert 49 <= s <= 51

    def test_high_sharpe_low_dd(self):
        s = compute_pnl_component(sharpe=3, max_dd_pct=2)
        # sigmoid(2.1) ~ 0.89 * 100 = 89, then * 0.8 = 71
        assert s > 60

    def test_negative_sharpe(self):
        s = compute_pnl_component(sharpe=-5, max_dd_pct=2)
        # sigmoid(-3.5) ~ 0.03 * 100 = 3 * 0.8 = 2.4
        assert s < 10

    def test_huge_dd_zeros_score(self):
        s = compute_pnl_component(sharpe=2, max_dd_pct=15)
        # dd_factor < 0 → clamped 0
        assert s == 0.0

    def test_dd_at_10_pct(self):
        s = compute_pnl_component(sharpe=2, max_dd_pct=10)
        # dd_factor = 0
        assert s == 0.0

    def test_dd_at_5_pct_halves(self):
        s_no_dd = compute_pnl_component(sharpe=2, max_dd_pct=0)
        s_5_dd = compute_pnl_component(sharpe=2, max_dd_pct=5)
        # 5% dd → factor 0.5 → halves
        assert s_5_dd == pytest.approx(s_no_dd * 0.5, rel=1e-3)


# ============================================================
# compute_quality_component
# ============================================================


class TestQualityComponent:
    def test_empty_stats(self):
        assert compute_quality_component({}) == 50.0

    def test_full_stats(self):
        stats = {
            "total_decisions": 1000,
            "go": 50, "no_go": 950,
            "vetoes_pre_filter": 200, "vetoes_risk": 100,
        }
        coverage = {"bars_processed": 8000, "test_count": 232}
        s = compute_quality_component(stats, coverage)
        assert s >= 80  # high coverage + decided + vetoes + tests

    def test_low_decided_ratio(self):
        stats = {"total_decisions": 1000, "go": 5, "no_go": 5, "vetoes_pre_filter": 0, "vetoes_risk": 0}
        coverage = {"bars_processed": 100, "test_count": 10}
        s = compute_quality_component(stats, coverage)
        assert s < 30  # most candles never decided

    def test_no_coverage_data(self):
        stats = {"total_decisions": 100, "go": 50, "no_go": 50,
                 "vetoes_pre_filter": 10, "vetoes_risk": 5}
        s = compute_quality_component(stats, None)
        # Should not raise; gives a reasonable mid score
        assert 30 <= s <= 80


# ============================================================
# compute_risk_component
# ============================================================


class TestRiskComponent:
    def test_perfect_discipline(self):
        # 1% DD, 100 trades, 0 alarms
        s = compute_risk_component(max_dd_pct=1, num_trades=100, alarms=0)
        assert s >= 80

    def test_terrible_dd(self):
        s = compute_risk_component(max_dd_pct=15, num_trades=100, alarms=0)
        # DD bracket 0 + freq 30 + alarm 15 = 45
        assert s < 60

    def test_zero_trades(self):
        s = compute_risk_component(max_dd_pct=0, num_trades=0, alarms=0)
        # 50 + 0 + 15 = 65
        assert s == pytest.approx(65, abs=2)

    def test_too_many_alarms(self):
        s = compute_risk_component(max_dd_pct=2, num_trades=100, alarms=100)
        # 40 + 30 + 5 = 75
        assert s < 80


# ============================================================
# compute_validation_score (integration)
# ============================================================


class TestComputeValidationScore:
    def _build_summary(self, sharpe=0.0, dd_pct=2.0, num_trades=100,
                      total=1000, go=20, no_go=200, alarms=0,
                      bars=5000):
        return {
            "metrics": {
                "risk": {"sharpe_ratio": sharpe, "max_drawdown_pct": dd_pct},
                "trades": {"num_trades": num_trades, "win_rate": 0.5},
                "meta": {"bars_processed": bars},
            },
            "stats": {
                "total_decisions": total,
                "go": go,
                "no_go": no_go,
                "vetoes_pre_filter": 50,
                "vetoes_risk": 100,
                "alarms": alarms,
            },
        }

    def test_great_run(self):
        summary = self._build_summary(sharpe=2.5, dd_pct=2, num_trades=200,
                                       total=8000, go=100, no_go=500, alarms=2)
        breakdown = compute_validation_score(summary)
        assert breakdown.final_score >= 60
        assert "Sharpe" in breakdown.notes

    def test_terrible_run(self):
        # Mimics our current backtest: sharpe -11, dd 8%, 252 trades, 0 alarms
        summary = self._build_summary(sharpe=-11, dd_pct=8.3, num_trades=252,
                                       total=8615, go=252, no_go=8400, alarms=0)
        breakdown = compute_validation_score(summary)
        # PnL component ~ 0, but quality + risk should pull the score up
        assert breakdown.pnl_component < 5
        assert breakdown.quality_component > 50
        # Final should still be > 20 (saved by quality+risk)
        assert 20 <= breakdown.final_score <= 60

    def test_score_in_valid_range(self):
        summary = self._build_summary()
        breakdown = compute_validation_score(summary)
        assert 1 <= breakdown.final_score <= 100

    def test_breakdown_to_dict(self):
        summary = self._build_summary()
        breakdown = compute_validation_score(summary)
        d = breakdown.to_dict()
        assert set(d.keys()) == {"pnl_component", "quality_component",
                                  "risk_component", "final_score", "notes"}

    def test_zero_sharpe_neutral(self):
        summary = self._build_summary(sharpe=0, dd_pct=0, num_trades=100,
                                       total=1000, go=100, no_go=900)
        breakdown = compute_validation_score(summary)
        # sigmoid(0)=0.5 * 100 = 50, * dd_factor 1.0 = 50
        assert 45 <= breakdown.pnl_component <= 55
