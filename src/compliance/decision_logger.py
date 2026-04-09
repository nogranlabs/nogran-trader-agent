"""
Audit trail logger — records EVERY decision (executed or not) as JSONL.
Each entry includes the full Decision Score breakdown.
"""

import json
import logging
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from domain.models import DecisionScore, RiskApproval, TradeSignal

logger = logging.getLogger(__name__)

LOGS_DIR = Path("logs/decisions")


class DecisionLogger:
    """Append-only JSONL logger for audit trail."""

    def __init__(self, log_dir: Path | str = LOGS_DIR):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _today_file(self) -> Path:
        return self.log_dir / f"{date.today().isoformat()}.jsonl"

    def _serialize(self, obj) -> dict:
        """Convert dataclass/enum to JSON-safe dict."""
        if hasattr(obj, "__dataclass_fields__"):
            result = {}
            for k, v in asdict(obj).items():
                result[k] = self._serialize(v)
            return result
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif hasattr(obj, "value"):  # Enum
            return obj.value
        elif isinstance(obj, dict):
            return {k: self._serialize(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._serialize(i) for i in obj]
        return obj

    def log_decision(
        self,
        decision_score: DecisionScore,
        signal: TradeSignal | None = None,
        risk_approval: RiskApproval | None = None,
        execution_result: dict | None = None,
        mq_score: int = 0,
        regime: str = "",
        fact: str = "",
        erc8004_signature: str = "",
        session_mode: str = "",
        candle_data: dict | None = None,
        kb_match: dict | None = None,
        hallucination_alarm: dict | None = None,
        rr_warning: str | None = None,
    ):
        """Log a complete decision with all context."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "decision_score": self._serialize(decision_score),
            "executed": decision_score.go,
            "mq_score": mq_score,
            "regime": regime,
            "session_mode": session_mode,
        }

        if candle_data:
            entry["candle"] = candle_data

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

        if risk_approval:
            entry["risk"] = {
                "approved": risk_approval.approved,
                "position_size": risk_approval.position_size,
                "adjusted_stop": risk_approval.adjusted_stop,
                "adjusted_target": risk_approval.adjusted_target,
                "risk_pct": risk_approval.risk_pct,
                "reward_risk_ratio": risk_approval.reward_risk_ratio,
                "current_drawdown": risk_approval.current_drawdown,
                "drawdown_band": risk_approval.drawdown_band.value,
                "sharpe_rolling": risk_approval.sharpe_rolling,
                "risk_score": risk_approval.risk_score,
            }

        if execution_result:
            entry["execution"] = execution_result

        if erc8004_signature:
            entry["erc8004_signature"] = erc8004_signature

        if fact:
            entry["fact_preview"] = fact[:200]

        # Nogran PA KB enrichment (knowledge base citation + hallucination detector)
        if kb_match:
            entry["kb_match"] = kb_match
        if hallucination_alarm:
            entry["hallucination_alarm"] = hallucination_alarm
        if rr_warning:
            entry["rr_warning"] = rr_warning

        # Write
        try:
            filepath = self._today_file()
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.debug(f"Decision logged to {filepath}")
        except Exception as e:
            logger.error(f"Failed to log decision: {e}")

    def log_outcome(self, intent_id: str, pnl: float, exit_reason: str):
        """Log trade outcome (appended as separate entry)."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "type": "outcome",
            "intent_id": intent_id,
            "pnl": pnl,
            "exit_reason": exit_reason,
        }
        try:
            filepath = self._today_file()
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to log outcome: {e}")
