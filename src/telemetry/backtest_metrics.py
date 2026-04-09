"""
Backtest performance metrics — hackathon-aligned (lablab.ai AI Trading Agents).

Implementa as metricas que o ranking oficial usa:
    - PnL liquido (net of fees)
    - Sharpe ratio annualized (sqrt(252) para dailyish; sqrt(525600) para 1m bars)
    - Max drawdown (peak-to-trough)
    - Sortino ratio (so usa downside)
    - Calmar ratio (CAGR / MaxDD)
    - Win rate, profit factor, expectancy

Tambem fornece:
    - Buy-and-hold baseline a partir do primeiro/ultimo close
    - Equity curve helpers (peak, dd series)

Tudo puro Python (math + statistics) — sem numpy/pandas pra ser dependency-light.

Premissa: as funcoes recebem listas de floats. O caller (scripts/backtest.py)
e responsavel por construir essas listas a partir dos TradeResult / Candles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import mean, pstdev

# Periods per year for annualization. Default = 252 (trading days), mas
# pra estrategias intra-bar pode-se passar 525600 (minutos no ano) etc.
ANNUAL_DAYS = 252.0


@dataclass
class BacktestMetrics:
    """Conjunto canonico de metricas hackathon-aligned."""

    # PnL
    initial_capital: float
    final_equity: float
    total_pnl: float
    total_pnl_pct: float
    total_fees: float

    # Trade stats
    num_trades: int
    num_wins: int
    num_losses: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float
    avg_rr_realized: float

    # Risk
    max_drawdown: float          # fraction (0-1)
    max_drawdown_pct: float      # same as percentage
    sharpe_ratio: float          # annualized
    sortino_ratio: float         # annualized
    calmar_ratio: float          # CAGR / MaxDD
    cagr: float                  # compounded annual growth rate

    # Baseline
    buy_hold_pnl: float
    buy_hold_pnl_pct: float
    alpha_vs_buy_hold: float     # strategy_pct - buyhold_pct

    # Meta
    period_days: float = 0.0
    bars_processed: int = 0

    def to_dict(self) -> dict:
        return {
            "pnl": {
                "initial_capital": round(self.initial_capital, 2),
                "final_equity": round(self.final_equity, 2),
                "total_pnl": round(self.total_pnl, 2),
                "total_pnl_pct": round(self.total_pnl_pct, 4),
                "total_fees": round(self.total_fees, 2),
                "cagr": round(self.cagr, 4),
            },
            "risk": {
                "max_drawdown": round(self.max_drawdown, 4),
                "max_drawdown_pct": round(self.max_drawdown_pct, 4),
                "sharpe_ratio": round(self.sharpe_ratio, 4),
                "sortino_ratio": round(self.sortino_ratio, 4),
                "calmar_ratio": round(self.calmar_ratio, 4),
            },
            "trades": {
                "num_trades": self.num_trades,
                "num_wins": self.num_wins,
                "num_losses": self.num_losses,
                "win_rate": round(self.win_rate, 4),
                "avg_win": round(self.avg_win, 2),
                "avg_loss": round(self.avg_loss, 2),
                "profit_factor": round(self.profit_factor, 4),
                "expectancy": round(self.expectancy, 4),
                "avg_rr_realized": round(self.avg_rr_realized, 4),
            },
            "baseline": {
                "buy_hold_pnl": round(self.buy_hold_pnl, 2),
                "buy_hold_pnl_pct": round(self.buy_hold_pnl_pct, 4),
                "alpha_vs_buy_hold": round(self.alpha_vs_buy_hold, 4),
            },
            "meta": {
                "period_days": round(self.period_days, 4),
                "bars_processed": self.bars_processed,
            },
        }


# ============================================================
# Core formula helpers
# ============================================================


def equity_to_returns(equity_curve: list[float]) -> list[float]:
    """Convert equity curve to per-step simple returns."""
    if len(equity_curve) < 2:
        return []
    out = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        if prev <= 0:
            out.append(0.0)
        else:
            out.append((equity_curve[i] - prev) / prev)
    return out


def max_drawdown(equity_curve: list[float]) -> float:
    """Peak-to-trough max drawdown as fraction (0-1)."""
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            dd = 1.0 - (eq / peak)
            if dd > max_dd:
                max_dd = dd
    return max_dd


def sharpe_ratio(returns: list[float], periods_per_year: float = ANNUAL_DAYS,
                 risk_free: float = 0.0) -> float:
    """Annualized Sharpe ratio.

    returns: per-period returns (not %)
    periods_per_year: how many of those periods are in a year (252 daily,
                      525600 minutes, etc.)
    risk_free: per-period risk-free rate (default 0)
    """
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free for r in returns]
    mu = mean(excess)
    sd = pstdev(excess)
    if sd < 1e-12:
        return 0.0
    return (mu / sd) * math.sqrt(periods_per_year)


def sortino_ratio(returns: list[float], periods_per_year: float = ANNUAL_DAYS,
                  risk_free: float = 0.0) -> float:
    """Annualized Sortino ratio (downside-deviation only)."""
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free for r in returns]
    mu = mean(excess)
    downside = [r for r in excess if r < 0]
    if len(downside) < 2:
        return 0.0
    dd_var = sum(r * r for r in downside) / len(downside)
    dd_sd = math.sqrt(dd_var)
    if dd_sd < 1e-12:
        return 0.0
    return (mu / dd_sd) * math.sqrt(periods_per_year)


def cagr(initial: float, final: float, period_days: float) -> float:
    """Compounded annual growth rate."""
    if initial <= 0 or final <= 0 or period_days <= 0:
        return 0.0
    years = period_days / 365.25
    if years <= 0:
        return 0.0
    return (final / initial) ** (1.0 / years) - 1.0


def calmar_ratio(cagr_value: float, max_dd: float) -> float:
    """Calmar = CAGR / MaxDD. Inf if MaxDD == 0 and CAGR > 0."""
    if max_dd <= 1e-9:
        return float("inf") if cagr_value > 0 else 0.0
    return cagr_value / max_dd


# ============================================================
# Buy-and-hold baseline
# ============================================================


def buy_and_hold(initial_capital: float, first_close: float, last_close: float,
                 fee_pct: float = 0.0026) -> tuple[float, float]:
    """Simulate naive buy-at-start, hold-to-end. Returns (pnl, pnl_pct).

    fee_pct = round-trip fee fraction (Kraken taker default 0.26%).
    """
    if first_close <= 0:
        return 0.0, 0.0
    units = initial_capital / first_close
    gross_exit = units * last_close
    fee_in = units * first_close * fee_pct
    fee_out = gross_exit * fee_pct
    final = gross_exit - fee_in - fee_out
    pnl = final - initial_capital
    pnl_pct = pnl / initial_capital
    return pnl, pnl_pct


# ============================================================
# Aggregator
# ============================================================


@dataclass
class TradeRecord:
    """Minimal trade record consumed by `compute_metrics`.

    Independent from domain.models.TradeResult to avoid coupling backtest to
    the live execution model.
    """
    pnl: float
    pnl_pct: float
    fees: float = 0.0
    rr_realized: float = 0.0
    is_win: bool = field(init=False)

    def __post_init__(self):
        self.is_win = self.pnl > 0


def compute_metrics(
    trades: list[TradeRecord],
    equity_curve: list[float],
    initial_capital: float,
    first_close: float,
    last_close: float,
    period_days: float,
    bars_processed: int,
    bars_per_year: float = ANNUAL_DAYS,
    fee_pct: float = 0.0026,
) -> BacktestMetrics:
    """Aggregate everything into a `BacktestMetrics` snapshot.

    bars_per_year: usado para anualizar Sharpe/Sortino. Default 252 (diario).
                   Para 1m bars use 525600. Para 5m bars use 105120.
                   O backtest passa a constante apropriada.
    """
    final_equity = equity_curve[-1] if equity_curve else initial_capital
    total_pnl = final_equity - initial_capital
    total_pnl_pct = total_pnl / initial_capital if initial_capital > 0 else 0.0
    total_fees = sum(t.fees for t in trades)

    num_trades = len(trades)
    wins = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]
    num_wins = len(wins)
    num_losses = len(losses)
    win_rate = num_wins / num_trades if num_trades else 0.0

    avg_win = sum(t.pnl for t in wins) / num_wins if num_wins else 0.0
    avg_loss = sum(t.pnl for t in losses) / num_losses if num_losses else 0.0

    total_wins = sum(t.pnl for t in wins)
    total_losses_abs = abs(sum(t.pnl for t in losses))
    if total_losses_abs > 0:
        profit_factor = total_wins / total_losses_abs
    else:
        profit_factor = float("inf") if total_wins > 0 else 0.0

    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
    rr_values = [t.rr_realized for t in trades if t.rr_realized > 0]
    avg_rr_realized = sum(rr_values) / len(rr_values) if rr_values else 0.0

    max_dd = max_drawdown(equity_curve)
    returns = equity_to_returns(equity_curve)
    sharpe = sharpe_ratio(returns, periods_per_year=bars_per_year)
    sortino = sortino_ratio(returns, periods_per_year=bars_per_year)
    cagr_value = cagr(initial_capital, final_equity, period_days)
    calmar = calmar_ratio(cagr_value, max_dd)

    bh_pnl, bh_pct = buy_and_hold(initial_capital, first_close, last_close, fee_pct=fee_pct)
    alpha = total_pnl_pct - bh_pct

    return BacktestMetrics(
        initial_capital=initial_capital,
        final_equity=final_equity,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        total_fees=total_fees,
        num_trades=num_trades,
        num_wins=num_wins,
        num_losses=num_losses,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        expectancy=expectancy,
        avg_rr_realized=avg_rr_realized,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd * 100,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        cagr=cagr_value,
        buy_hold_pnl=bh_pnl,
        buy_hold_pnl_pct=bh_pct,
        alpha_vs_buy_hold=alpha,
        period_days=period_days,
        bars_processed=bars_processed,
    )


# ============================================================
# Pretty-printing helper
# ============================================================


def format_metrics(m: BacktestMetrics) -> str:
    """Compact human-readable summary for stdout."""
    inf = float("inf")
    pf = "inf" if m.profit_factor == inf else f"{m.profit_factor:.2f}"
    cal = "inf" if m.calmar_ratio == inf else f"{m.calmar_ratio:.2f}"
    lines = [
        "=" * 64,
        "BACKTEST METRICS",
        "=" * 64,
        f"Period           : {m.period_days:.1f} days  ({m.bars_processed} bars)",
        f"Initial capital  : ${m.initial_capital:,.2f}",
        f"Final equity     : ${m.final_equity:,.2f}",
        f"Net PnL          : ${m.total_pnl:,.2f}  ({m.total_pnl_pct*100:+.2f}%)",
        f"Total fees       : ${m.total_fees:,.2f}",
        f"CAGR             : {m.cagr*100:+.2f}%",
        "-" * 64,
        f"Sharpe (ann.)    : {m.sharpe_ratio:.3f}",
        f"Sortino (ann.)   : {m.sortino_ratio:.3f}",
        f"Calmar           : {cal}",
        f"Max drawdown     : {m.max_drawdown_pct:.2f}%",
        "-" * 64,
        f"Trades           : {m.num_trades} (wins {m.num_wins} / losses {m.num_losses})",
        f"Win rate         : {m.win_rate*100:.1f}%",
        f"Avg win / loss   : ${m.avg_win:,.2f} / ${m.avg_loss:,.2f}",
        f"Profit factor    : {pf}",
        f"Expectancy       : ${m.expectancy:,.2f}",
        f"Avg R:R realized : {m.avg_rr_realized:.2f}",
        "-" * 64,
        f"Buy-and-hold PnL : ${m.buy_hold_pnl:,.2f}  ({m.buy_hold_pnl_pct*100:+.2f}%)",
        f"Alpha vs B&H     : {m.alpha_vs_buy_hold*100:+.2f}%",
        "=" * 64,
    ]
    return "\n".join(lines)
