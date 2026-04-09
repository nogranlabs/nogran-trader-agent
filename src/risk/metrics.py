import math
from dataclasses import dataclass, field

from domain.models import TradeResult


@dataclass
class RiskMetrics:
    """Real-time performance tracking."""
    trades: list[TradeResult] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=lambda: [10000.0])
    initial_capital: float = 10000.0

    def update(self, trade: TradeResult):
        self.trades.append(trade)
        new_equity = self.equity_curve[-1] + trade.pnl
        self.equity_curve.append(new_equity)

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def current_equity(self) -> float:
        return self.equity_curve[-1]

    @property
    def max_equity(self) -> float:
        return max(self.equity_curve)

    @property
    def current_drawdown(self) -> float:
        """Current drawdown as a fraction (0.0 to 1.0)."""
        peak = self.max_equity
        return 1 - (self.current_equity / peak) if peak > 0 else 0.0

    @property
    def max_drawdown(self) -> float:
        peak = self.equity_curve[0]
        max_dd = 0.0
        for eq in self.equity_curve:
            peak = max(peak, eq)
            dd = 1 - (eq / peak) if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
        return max_dd

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades)

    @property
    def avg_win(self) -> float:
        wins = [t.pnl for t in self.trades if t.pnl > 0]
        return sum(wins) / len(wins) if wins else 0.0

    @property
    def avg_loss(self) -> float:
        losses = [t.pnl for t in self.trades if t.pnl < 0]
        return sum(losses) / len(losses) if losses else 0.0

    @property
    def expectancy(self) -> float:
        if not self.trades:
            return 0.0
        return (self.win_rate * self.avg_win) + ((1 - self.win_rate) * self.avg_loss)

    @property
    def profit_factor(self) -> float:
        total_wins = sum(t.pnl for t in self.trades if t.pnl > 0)
        total_losses = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        if total_losses == 0:
            return float('inf') if total_wins > 0 else 0.0
        return total_wins / total_losses

    @property
    def consecutive_losses(self) -> int:
        count = 0
        for t in reversed(self.trades):
            if t.pnl < 0:
                count += 1
            else:
                break
        return count

    @property
    def sharpe_rolling(self) -> float:
        """Rolling Sharpe over last 20 trades (annualized is meaningless for intraday, so just ratio)."""
        recent = self.trades[-20:]
        if len(recent) < 5:
            return 0.0
        returns = [t.pnl_pct for t in recent]
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std_ret = math.sqrt(variance)
        # Floating-point safety: when all returns are equal, FP rounding can
        # leave std_ret as a tiny non-zero (~1e-18) instead of exact 0,
        # producing absurd Sharpe values when divided into mean_ret. Treat
        # anything below the FP noise floor as zero variance.
        if std_ret < 1e-10:
            return 0.0
        return mean_ret / std_ret

    @property
    def equity_at_ath(self) -> bool:
        return self.current_equity >= self.max_equity
