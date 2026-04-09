import logging
from dataclasses import dataclass, field
from datetime import datetime

from domain.enums import Action
from domain.models import DecisionScore, RiskApproval, TradeSignal
from execution.kraken_cli import KrakenCLI, KrakenCLIError

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    success: bool
    order_id: str = ""
    pair: str = ""
    side: str = ""
    volume: float = 0.0
    fill_price: float = 0.0
    order_type: str = "market"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    error: str = ""
    raw_response: dict = field(default_factory=dict)


class Executor:
    """
    Executes trades via Kraken CLI paper trading.
    Takes signals from the strategy engine, applies risk sizing,
    and places orders through the CLI wrapper.
    """

    def __init__(self, pair: str = "BTC/USD", mode: str = "paper"):
        self.pair = pair
        self.cli = KrakenCLI(mode=mode)
        logger.info(f"Executor initialized: pair={pair}, mode={mode}")

    def execute_trade(
        self,
        signal: TradeSignal,
        risk_approval: RiskApproval,
        decision_score: DecisionScore,
    ) -> ExecutionResult:
        """
        Execute a trade based on the signal, risk approval, and decision score.
        Only executes if decision_score.go is True and risk_approval.approved is True.
        """
        if not decision_score.go:
            logger.warning(f"Decision score vetoed trade: go={decision_score.go}, total={decision_score.total}")
            return ExecutionResult(success=False, error="Decision score vetoed trade")

        if not risk_approval.approved:
            logger.warning(f"Risk approval denied: {risk_approval.reason}")
            return ExecutionResult(success=False, error=f"Risk denied: {risk_approval.reason}")

        if signal.action == Action.AGUARDAR:
            logger.info("Signal is AGUARDAR (wait), no trade executed")
            return ExecutionResult(success=False, error="Signal is AGUARDAR")

        side = "buy" if signal.action == Action.COMPRA else "sell"
        volume = risk_approval.position_size

        logger.info(
            f"Executing {side} {volume} {self.pair} | "
            f"confidence={signal.confidence} | risk_pct={risk_approval.risk_pct:.2f}% | "
            f"score={decision_score.total:.1f}"
        )

        # Place market entry order
        try:
            if side == "buy":
                response = self.cli.paper_buy(self.pair, volume)
            else:
                response = self.cli.paper_sell(self.pair, volume)
        except KrakenCLIError as e:
            logger.error(f"Order failed: {e}")
            return ExecutionResult(
                success=False,
                pair=self.pair,
                side=side,
                volume=volume,
                error=str(e),
            )

        order_id = response.get("order_id", response.get("txid", "unknown"))
        fill_price = float(response.get("price", response.get("avg_price", 0)))

        logger.info(f"Order filled: id={order_id}, price={fill_price}, side={side}, volume={volume}")

        # Place OCO-like stop loss and take profit as limit orders
        self._place_oco_orders(
            side=side,
            volume=volume,
            stop_loss=risk_approval.adjusted_stop,
            take_profit=risk_approval.adjusted_target,
        )

        return ExecutionResult(
            success=True,
            order_id=str(order_id),
            pair=self.pair,
            side=side,
            volume=volume,
            fill_price=fill_price,
            order_type="market",
            raw_response=response,
        )

    def _place_oco_orders(
        self, side: str, volume: float, stop_loss: float, take_profit: float
    ) -> None:
        """
        Place stop loss and take profit limit orders (OCO-like behavior).
        For a buy entry, the stop loss is a sell limit below and take profit is a sell limit above.
        For a sell entry, it's the opposite.
        """
        exit_side = "sell" if side == "buy" else "buy"

        # Stop loss
        try:
            if exit_side == "sell":
                self.cli.paper_sell_limit(self.pair, volume, stop_loss)
            else:
                self.cli.paper_buy_limit(self.pair, volume, stop_loss)
            logger.info(f"Stop loss placed: {exit_side} {volume} @ {stop_loss}")
        except KrakenCLIError as e:
            logger.error(f"Failed to place stop loss: {e}")

        # Take profit
        try:
            if exit_side == "sell":
                self.cli.paper_sell_limit(self.pair, volume, take_profit)
            else:
                self.cli.paper_buy_limit(self.pair, volume, take_profit)
            logger.info(f"Take profit placed: {exit_side} {volume} @ {take_profit}")
        except KrakenCLIError as e:
            logger.error(f"Failed to place take profit: {e}")

    def get_status(self) -> dict:
        """Get account summary (positions + PnL) from Kraken CLI."""
        try:
            status = self.cli.paper_status()
            logger.info(f"Status: {status}")
            return status
        except KrakenCLIError as e:
            logger.error(f"Failed to get status: {e}")
            return {}

    def get_balance(self) -> dict:
        """Get current account balance."""
        try:
            balance = self.cli.paper_balance()
            logger.info(f"Balance: {balance}")
            return balance
        except KrakenCLIError as e:
            logger.error(f"Failed to get balance: {e}")
            return {}

    def get_orders(self) -> dict:
        """Get open orders."""
        try:
            orders = self.cli.paper_orders()
            logger.info(f"Orders: {orders}")
            return orders
        except KrakenCLIError as e:
            logger.error(f"Failed to get orders: {e}")
            return {}

    def get_history(self) -> dict:
        """Get trade history."""
        try:
            history = self.cli.paper_history()
            logger.info(f"History: {history}")
            return history
        except KrakenCLIError as e:
            logger.error(f"Failed to get history: {e}")
            return {}

    def close_position(self, pair: str, volume: float, side: str = "buy") -> ExecutionResult:
        """
        Close a position by placing the opposite market order.
        side: the current position side ('buy' means we are long, so we sell to close).
        volume: the amount to close. Get from balance if unknown.
        """
        close_side = "sell" if side == "buy" else "buy"

        # If volume not provided, try to get from balance
        if volume <= 0:
            balance = self.get_balance()
            balances = balance.get("balances", {})
            # Extract BTC balance for BTC pairs
            base = pair.split("/")[0] if "/" in pair else pair[:3]
            base_bal = balances.get(base, {})
            volume = float(base_bal.get("total", 0))

        if volume <= 0:
            logger.warning(f"No balance found for {pair}")
            return ExecutionResult(success=False, pair=pair, error="No balance to close")

        logger.info(f"Closing position: {close_side} {volume} {pair}")

        try:
            if close_side == "buy":
                response = self.cli.paper_buy(pair, volume)
            else:
                response = self.cli.paper_sell(pair, volume)
        except KrakenCLIError as e:
            logger.error(f"Failed to close position: {e}")
            return ExecutionResult(success=False, pair=pair, side=close_side, error=str(e))

        order_id = response.get("order_id", response.get("txid", "unknown"))
        fill_price = float(response.get("price", response.get("avg_price", 0)))

        logger.info(f"Position closed: id={order_id}, price={fill_price}")

        return ExecutionResult(
            success=True,
            order_id=str(order_id),
            pair=pair,
            side=close_side,
            volume=volume,
            fill_price=fill_price,
            order_type="market",
            raw_response=response,
        )
