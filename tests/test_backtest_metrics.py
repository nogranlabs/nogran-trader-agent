"""Tests for src/telemetry/backtest_metrics.py — hackathon ranking metrics."""

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from telemetry.backtest_metrics import (  # noqa: E402
    ANNUAL_DAYS,
    BacktestMetrics,
    TradeRecord,
    buy_and_hold,
    cagr,
    calmar_ratio,
    compute_metrics,
    equity_to_returns,
    format_metrics,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
)

# ============================================================
# equity_to_returns
# ============================================================


class TestEquityToReturns:
    def test_empty(self):
        assert equity_to_returns([]) == []

    def test_single_point(self):
        assert equity_to_returns([10000.0]) == []

    def test_flat_curve(self):
        assert equity_to_returns([100.0, 100.0, 100.0]) == [0.0, 0.0]

    def test_doubling(self):
        rets = equity_to_returns([100.0, 200.0])
        assert rets == [1.0]

    def test_loss(self):
        rets = equity_to_returns([100.0, 90.0])
        assert rets == pytest.approx([-0.10])

    def test_zero_prev_safe(self):
        rets = equity_to_returns([0.0, 100.0])
        assert rets == [0.0]


# ============================================================
# max_drawdown
# ============================================================


class TestMaxDrawdown:
    def test_empty(self):
        assert max_drawdown([]) == 0.0

    def test_single(self):
        assert max_drawdown([100.0]) == 0.0

    def test_no_drawdown_monotonic(self):
        assert max_drawdown([100.0, 110.0, 120.0]) == 0.0

    def test_simple_drop(self):
        # peak 100 -> trough 80 -> dd 20%
        assert max_drawdown([100.0, 80.0]) == pytest.approx(0.20)

    def test_recovery_then_bigger_drop(self):
        # 100 -> 50 (50%) -> 200 (peak) -> 100 (50% from 200)
        # both DDs are 50%, max is 50%
        assert max_drawdown([100.0, 50.0, 200.0, 100.0]) == pytest.approx(0.50)

    def test_smaller_dd_after_recovery(self):
        # 100 -> 90 (10%) -> 150 (peak) -> 135 (10% from 150)
        # max should be max of both = 10%
        assert max_drawdown([100.0, 90.0, 150.0, 135.0]) == pytest.approx(0.10)

    def test_complex_curve(self):
        # peak at 150, trough at 75 -> 50%
        curve = [100.0, 120.0, 150.0, 100.0, 75.0, 90.0]
        assert max_drawdown(curve) == pytest.approx(0.50)


# ============================================================
# sharpe_ratio
# ============================================================


class TestSharpe:
    def test_empty(self):
        assert sharpe_ratio([]) == 0.0

    def test_single_return(self):
        assert sharpe_ratio([0.01]) == 0.0

    def test_zero_variance(self):
        # Constant returns -> std=0 -> 0 (avoid div-by-zero)
        assert sharpe_ratio([0.01, 0.01, 0.01, 0.01]) == 0.0

    def test_positive_returns(self):
        # Random-ish positive returns
        rets = [0.01, 0.02, -0.01, 0.015, 0.005]
        s = sharpe_ratio(rets, periods_per_year=252)
        assert s > 0

    def test_negative_returns(self):
        rets = [-0.01, -0.02, -0.005]
        s = sharpe_ratio(rets, periods_per_year=252)
        assert s < 0

    def test_periods_per_year_scales(self):
        rets = [0.001, 0.002, -0.001, 0.0015]
        s_daily = sharpe_ratio(rets, periods_per_year=252)
        s_min = sharpe_ratio(rets, periods_per_year=525600)
        # higher periods -> larger annualized
        assert s_min > s_daily


# ============================================================
# sortino_ratio
# ============================================================


class TestSortino:
    def test_empty(self):
        assert sortino_ratio([]) == 0.0

    def test_no_downside(self):
        # all-positive returns -> downside list empty -> 0
        assert sortino_ratio([0.01, 0.02, 0.005]) == 0.0

    def test_with_downside(self):
        rets = [0.01, -0.005, 0.02, -0.01, 0.015]
        sor = sortino_ratio(rets, periods_per_year=252)
        assert sor > 0  # mean positive

    def test_all_negative(self):
        rets = [-0.01, -0.02, -0.005, -0.015]
        sor = sortino_ratio(rets, periods_per_year=252)
        assert sor < 0


# ============================================================
# cagr + calmar
# ============================================================


class TestCAGR:
    def test_zero_initial(self):
        assert cagr(0, 100, 365) == 0.0

    def test_zero_period(self):
        assert cagr(100, 200, 0) == 0.0

    def test_double_in_one_year(self):
        c = cagr(100, 200, 365.25)
        assert c == pytest.approx(1.0, rel=1e-3)

    def test_loss(self):
        c = cagr(100, 50, 365.25)
        assert c == pytest.approx(-0.5, rel=1e-3)


class TestCalmar:
    def test_zero_dd_positive_cagr(self):
        assert calmar_ratio(0.5, 0.0) == float("inf")

    def test_zero_dd_zero_cagr(self):
        assert calmar_ratio(0.0, 0.0) == 0.0

    def test_normal(self):
        assert calmar_ratio(0.20, 0.10) == pytest.approx(2.0)


# ============================================================
# buy_and_hold
# ============================================================


class TestBuyAndHold:
    def test_zero_first_close(self):
        pnl, pct = buy_and_hold(10000, 0, 100)
        assert pnl == 0.0 and pct == 0.0

    def test_no_fees_double(self):
        # 10k @ 100 = 100 BTC; sell at 200 = 20k; pnl = 10k = 100%
        pnl, pct = buy_and_hold(10000, 100, 200, fee_pct=0.0)
        assert pnl == pytest.approx(10000)
        assert pct == pytest.approx(1.0)

    def test_with_fees(self):
        pnl, pct = buy_and_hold(10000, 100, 200, fee_pct=0.0026)
        # rough check: pnl is less than no-fee
        assert pnl < 10000
        assert pct < 1.0

    def test_loss(self):
        pnl, _ = buy_and_hold(10000, 100, 50, fee_pct=0.0)
        assert pnl == pytest.approx(-5000)


# ============================================================
# compute_metrics — integration
# ============================================================


class TestComputeMetrics:
    def test_no_trades(self):
        m = compute_metrics(
            trades=[],
            equity_curve=[10000.0],
            initial_capital=10000.0,
            first_close=100.0,
            last_close=100.0,
            period_days=1.0,
            bars_processed=0,
        )
        assert m.num_trades == 0
        assert m.total_pnl == 0.0
        assert m.win_rate == 0.0
        assert m.profit_factor == 0.0
        assert m.max_drawdown == 0.0

    def test_all_winners(self):
        trades = [
            TradeRecord(pnl=100, pnl_pct=0.01, fees=2, rr_realized=2.0),
            TradeRecord(pnl=200, pnl_pct=0.02, fees=2, rr_realized=2.5),
        ]
        equity = [10000, 10100, 10300]
        m = compute_metrics(
            trades=trades,
            equity_curve=equity,
            initial_capital=10000,
            first_close=100,
            last_close=110,
            period_days=10,
            bars_processed=14400,
        )
        assert m.num_trades == 2
        assert m.num_wins == 2
        assert m.num_losses == 0
        assert m.win_rate == 1.0
        assert m.total_pnl == pytest.approx(300)
        assert m.profit_factor == float("inf")
        assert m.avg_rr_realized == pytest.approx(2.25)

    def test_mixed_trades(self):
        trades = [
            TradeRecord(pnl=100, pnl_pct=0.01, fees=2, rr_realized=2.0),
            TradeRecord(pnl=-50, pnl_pct=-0.005, fees=2, rr_realized=0.5),
            TradeRecord(pnl=150, pnl_pct=0.015, fees=2, rr_realized=3.0),
            TradeRecord(pnl=-75, pnl_pct=-0.0075, fees=2, rr_realized=0.7),
        ]
        equity = [10000, 10100, 10050, 10200, 10125]
        m = compute_metrics(
            trades=trades,
            equity_curve=equity,
            initial_capital=10000,
            first_close=100,
            last_close=105,
            period_days=20,
            bars_processed=28800,
        )
        assert m.num_trades == 4
        assert m.num_wins == 2
        assert m.num_losses == 2
        assert m.win_rate == 0.5
        # PF = 250 / 125 = 2.0
        assert m.profit_factor == pytest.approx(2.0)
        assert m.total_fees == pytest.approx(8)

    def test_max_dd_in_metrics(self):
        # equity 10000 -> 12000 -> 9000 -> 11000 : max DD = (12000 - 9000) / 12000 = 25%
        equity = [10000, 12000, 9000, 11000]
        m = compute_metrics(
            trades=[TradeRecord(pnl=1000, pnl_pct=0.1)],
            equity_curve=equity,
            initial_capital=10000,
            first_close=100,
            last_close=110,
            period_days=30,
            bars_processed=43200,
        )
        assert m.max_drawdown == pytest.approx(0.25)
        assert m.max_drawdown_pct == pytest.approx(25.0)

    def test_alpha_vs_buy_hold(self):
        # Buy and hold from 100 to 200 = +100% (minus fees)
        # Strategy: zero PnL
        m = compute_metrics(
            trades=[],
            equity_curve=[10000, 10000],
            initial_capital=10000,
            first_close=100,
            last_close=200,
            period_days=10,
            bars_processed=14400,
            fee_pct=0.0,
        )
        assert m.buy_hold_pnl_pct == pytest.approx(1.0)
        assert m.alpha_vs_buy_hold == pytest.approx(-1.0)


# ============================================================
# format_metrics
# ============================================================


class TestFormatMetrics:
    def test_renders_without_error(self):
        m = compute_metrics(
            trades=[TradeRecord(pnl=100, pnl_pct=0.01)],
            equity_curve=[10000, 10100],
            initial_capital=10000,
            first_close=100,
            last_close=101,
            period_days=1,
            bars_processed=1440,
        )
        out = format_metrics(m)
        assert "BACKTEST METRICS" in out
        assert "Sharpe" in out
        assert "Buy-and-hold" in out
        assert "Alpha vs B&H" in out

    def test_inf_profit_factor_renders(self):
        m = compute_metrics(
            trades=[TradeRecord(pnl=100, pnl_pct=0.01)],  # all wins
            equity_curve=[10000, 10100],
            initial_capital=10000,
            first_close=100,
            last_close=101,
            period_days=1,
            bars_processed=1440,
        )
        out = format_metrics(m)
        assert "inf" in out  # PF or Calmar should render as 'inf'


# ============================================================
# to_dict serialization
# ============================================================


class TestToDict:
    def test_dict_keys(self):
        m = compute_metrics(
            trades=[TradeRecord(pnl=100, pnl_pct=0.01)],
            equity_curve=[10000, 10100],
            initial_capital=10000,
            first_close=100,
            last_close=101,
            period_days=1,
            bars_processed=1440,
        )
        d = m.to_dict()
        assert set(d.keys()) == {"pnl", "risk", "trades", "baseline", "meta"}
        assert "sharpe_ratio" in d["risk"]
        assert "max_drawdown" in d["risk"]
        assert "win_rate" in d["trades"]
        assert "alpha_vs_buy_hold" in d["baseline"]
