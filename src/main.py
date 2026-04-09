"""
nogran.trader.agent — Main Pipeline

Flow:
  Kraken WS -> Feature Engine -> Pre-Filter (MQ Score)
  -> Strategy Engine (python_llm or local mock) -> Strategy Score
  -> Nogran PA KB enrichment + hallucination detector
  -> AI Overlay (Regime + Confidence -> AO Score)
  -> Risk Engine (Risk Score + Position Sizing)
  -> Decision Scorer (4 sub-scores -> GO/NO-GO)
  -> ERC-8004 (RiskRouter + Checkpoint + Reputation)
  -> Execution (Kraken CLI)
  -> Decision Logger (Audit Trail)
"""

import asyncio
import logging
import os
import sys

import aiohttp

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai.confidence_adjuster import calculate_ao_score
from ai.decision_scorer import DecisionScorer
from ai.regime_detector import detect_regime
from compliance.decision_logger import DecisionLogger
from domain.enums import Action, DrawdownBand
from domain.models import Candle, DecisionScore, RiskApproval, TradeSignal
from execution.executor import Executor
from execution.kraken_cli import KrakenCLIError
from infra.config import Config
from market.candle_buffer import CandleBuffer
from market.feature_engine import FeatureEngine
from market.pre_filter import (
    calculate_mq_score,
    get_session_mode,
    get_session_sizing_mult,
    get_session_threshold,
    is_setup_allowed,
)
from risk.drawdown_controller import DrawdownController
from risk.exposure_manager import ExposureManager
from risk.metrics import RiskMetrics
from risk.position_sizer import PositionSizer
from strategy.fact_builder import build_fact
from strategy.local_signal import detect_local_regime, generate_local_signal
from strategy.probabilities_kb import ProbabilitiesKB
from strategy.signal_parser import calculate_strategy_score_with_kb

# STRATEGY_SOURCE controls where signals come from:
#   "python_llm" → OpenAI GPT-4o single-call structured output (default)
#   "mock"       → local deterministic Nogran price action heuristic (no LLM)
STRATEGY_SOURCE = os.getenv("STRATEGY_SOURCE", "python_llm").lower()

# Lazy: only construct LLMStrategy if STRATEGY_SOURCE == "python_llm"
_llm_strategy = None


def get_llm_strategy():
    """Lazy-init LLMStrategy. Avoids loading openai if not used."""
    global _llm_strategy
    if _llm_strategy is None:
        from strategy.llm_strategy import LLMStrategy
        _llm_strategy = LLMStrategy()
    return _llm_strategy

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-20s] %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# Optional ERC-8004 import
erc8004 = None
try:
    from compliance.erc8004_onchain import ERC8004Hackathon
    HAS_ERC8004 = True
except ImportError:
    HAS_ERC8004 = False
    logger.warning("web3/eth_account not installed — ERC-8004 disabled")


# ============================================================
# Risk Score Calculator
# ============================================================

def calculate_risk_score(
    signal: TradeSignal,
    metrics: RiskMetrics,
    dd_controller: DrawdownController,
) -> int:
    """Risk Score (0-100) based on capital health and trade viability."""
    score = 100.0

    dd = metrics.current_drawdown
    band = dd_controller.get_band(dd)
    if band == DrawdownBand.CIRCUIT_BREAKER:
        return 0
    elif band == DrawdownBand.MINIMUM:
        score -= 50
    elif band == DrawdownBand.DEFENSIVE:
        score -= 25

    if signal.stop_loss == 0 or signal.entry_price == 0:
        return 0
    risk = abs(signal.entry_price - signal.stop_loss)
    reward = abs(signal.take_profit - signal.entry_price)
    rr = reward / risk if risk > 0 else 0
    if rr < Config.MIN_REWARD_RISK:
        return 0
    elif rr < 2.0:
        score -= 10
    elif rr >= 3.0:
        score += 10

    sharpe = metrics.sharpe_rolling
    if sharpe < -1.0:
        score -= 30
    elif sharpe < 0:
        score -= 15
    elif sharpe > 1.0:
        score += 10

    if metrics.consecutive_losses >= 3:
        score -= 25

    return max(0, min(100, int(score)))


# ============================================================
# ERC-8004 Initialization
# ============================================================

def init_erc8004() -> object | None:
    """Initialize ERC-8004 hackathon contracts. Returns ERC8004Hackathon or None.

    Idempotente: le agent_id de logs/erc8004/state.json se ja existir, evitando
    re-registrar o agente em cada start.
    """
    if not HAS_ERC8004:
        logger.info("ERC-8004: web3 not installed — disabled")
        return None

    private_key = Config.ERC8004_PRIVATE_KEY
    if not private_key:
        logger.info("ERC-8004: No private key configured — disabled")
        return None

    # Try multiple Sepolia RPCs (rpc.sepolia.org cai com frequencia)
    rpc_candidates = [
        Config.SEPOLIA_RPC,
        "https://ethereum-sepolia-rpc.publicnode.com",
        "https://sepolia.gateway.tenderly.co",
        "https://eth-sepolia.public.blastapi.io",
    ]

    erc = None
    for rpc in rpc_candidates:
        try:
            candidate = ERC8004Hackathon(private_key=private_key, rpc_url=rpc)
            if candidate.is_connected:
                erc = candidate
                logger.info(f"ERC-8004: Connected to Sepolia via {rpc}. Wallet: {erc.address}")
                break
        except Exception:
            continue

    if erc is None:
        logger.warning("ERC-8004: All RPC endpoints failed")
        return None

    try:
        # Load cached agent_id (avoid re-registration)
        from pathlib import Path
        state_path = Path(__file__).resolve().parent.parent / "logs" / "erc8004" / "state.json"
        if state_path.exists():
            import json as _json
            try:
                state = _json.loads(state_path.read_text(encoding="utf-8"))
                if "agent_id" in state:
                    erc.agent_id = int(state["agent_id"])
                    logger.info(f"ERC-8004: Loaded cached agent_id={erc.agent_id}")
            except Exception as e:
                logger.warning(f"ERC-8004: Failed to read state.json: {e}")

        if erc.agent_id is None:
            agent_uri = Config.ERC8004_AGENT_URI
            agent_id = erc.register_agent(
                agent_wallet=erc.address,
                name="nogran.trader.agent",
                description="BTC/USD trading agent with PA KB hallucination detector",
                capabilities=["trading", "risk_management", "price_action_analysis"],
                agent_uri=agent_uri or "",
            )
            logger.info(f"ERC-8004: Agent registered! agentId={agent_id}")
            # Persist to state.json
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                __import__("json").dumps({"address": erc.address, "agent_id": agent_id}, indent=2),
                encoding="utf-8",
            )

        return erc

    except Exception as e:
        logger.error(f"ERC-8004 initialization failed: {e}")
        return None


# ============================================================
# Main Pipeline
# ============================================================

async def run_pipeline():
    """Main trading pipeline."""
    logger.info("=" * 60)
    logger.info("nogran.trader.agent v3 starting...")
    logger.info("=" * 60)

    # --- Initialize components ---
    buf_1m = CandleBuffer(maxlen=200)
    buf_5m = CandleBuffer(maxlen=100)
    feature_engine = FeatureEngine()
    decision_scorer = DecisionScorer()
    probabilities_kb = ProbabilitiesKB()  # Nogran PA knowledge base for SS enrichment + hallucination detection
    risk_metrics = RiskMetrics(initial_capital=Config.INITIAL_CAPITAL)
    dd_controller = DrawdownController()
    exposure_mgr = ExposureManager()
    position_sizer = PositionSizer(dd_controller)
    executor = Executor(pair=Config.TRADING_PAIR, mode="paper")
    decision_logger = DecisionLogger()

    candle_index = 0

    logger.info(f"Strategy source: {STRATEGY_SOURCE.upper()}")

    # --- ERC-8004 ---
    global erc8004
    erc8004 = init_erc8004()

    # --- WebSocket connection ---
    logger.info(f"Connecting to Kraken WebSocket for {Config.TRADING_PAIR}...")

    try:
        import ccxt.pro as ccxt_pro

        exchange_config = {}
        if sys.platform == "win32":
            connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
            exchange_config["session"] = aiohttp.ClientSession(connector=connector)

        exchange = ccxt_pro.kraken(exchange_config)

        logger.info("Market data: Kraken WebSocket (ccxt.pro)")
        logger.info("Execution: Kraken CLI (paper mode)")
        logger.info("Pipeline ready. Waiting for candles...")

        while True:
            try:
                candles_1m = await exchange.watch_ohlcv(
                    Config.TRADING_PAIR, Config.TIMEFRAME_EXEC
                )
                if not candles_1m:
                    continue

                raw = candles_1m[-1]
                current_candle = Candle(
                    timestamp=raw[0],
                    open=float(raw[1]),
                    high=float(raw[2]),
                    low=float(raw[3]),
                    close=float(raw[4]),
                    volume=float(raw[5]) if len(raw) > 5 else 0.0,
                )

                is_new = buf_1m.add(current_candle)
                if not is_new:
                    continue

                candle_index += 1

                # 5m data (optional)
                try:
                    candles_5m = await asyncio.wait_for(
                        exchange.watch_ohlcv(Config.TRADING_PAIR, Config.TIMEFRAME_CONFIRM),
                        timeout=1.0,
                    )
                    if candles_5m:
                        r5 = candles_5m[-1]
                        buf_5m.add(Candle(
                            timestamp=r5[0], open=float(r5[1]), high=float(r5[2]),
                            low=float(r5[3]), close=float(r5[4]),
                            volume=float(r5[5]) if len(r5) > 5 else 0.0,
                        ))
                except (asyncio.TimeoutError, Exception):
                    pass

                # --- Force close check ---
                if exposure_mgr.should_force_close(candle_index):
                    logger.warning("Force closing position (max time exceeded)")
                    try:
                        balance = executor.get_balance()
                        btc_bal = balance.get("balances", {}).get("BTC", {}).get("total", 0)
                        executor.close_position(Config.TRADING_PAIR, volume=float(btc_bal), side="buy")
                    except Exception as e:
                        logger.error(f"Force close failed: {e}")
                    exposure_mgr.on_position_closed(candle_index)

                # ========================================
                # STAGE 1: FEATURE ENGINE
                # ========================================
                features = feature_engine.compute(buf_1m, buf_5m, candle_index)
                if features is None:
                    continue

                logger.info(
                    f"#{candle_index}: "
                    f"{'BULL' if current_candle.is_bullish else 'BEAR'} "
                    f"C=${current_candle.close:.1f} "
                    f"Body={features.body_pct:.0f}% "
                    f"EMA={features.ema_20:.1f} "
                    f"ATR={features.atr_14:.1f}"
                )

                # ========================================
                # STAGE 1.5: SESSION MODE
                # ========================================
                session_mode = get_session_mode()
                session_threshold = get_session_threshold(session_mode)

                if session_mode == "OBSERVATION":
                    logger.info(f"#{candle_index}: OBSERVATION mode — not trading")
                    decision_logger.log_decision(
                        decision_score=decision_scorer.calculate(0, 0, 0, 0),
                        mq_score=0,
                        regime="",
                        fact="",
                        session_mode=session_mode,
                    )
                    continue

                logger.info(f"Session: {session_mode} (threshold={session_threshold})")

                # ========================================
                # STAGE 2: PRE-FILTER (MQ Score)
                # ========================================
                mq_score = calculate_mq_score(features)
                if mq_score < 30:
                    logger.info(f"PRE-FILTER VETO: MQ={mq_score}/100")
                    veto_score = decision_scorer.calculate(mq_score, 0, 50, 50)
                    decision_logger.log_decision(decision_score=veto_score, mq_score=mq_score, regime="", fact="", session_mode=session_mode)
                    continue

                # ========================================
                # STAGE 3: EXPOSURE CHECK
                # ========================================
                can_trade, exposure_reason = exposure_mgr.can_open_position(candle_index)
                if not can_trade:
                    logger.info(f"EXPOSURE VETO: {exposure_reason}")
                    continue

                # ========================================
                # STAGE 4: STRATEGY ENGINE (python_llm or local mock)
                # ========================================
                fact = build_fact(features, Config.TIMEFRAME_EXEC)

                if STRATEGY_SOURCE == "python_llm":
                    # python_llm mode: OpenAI single-call structured output
                    try:
                        signal = get_llm_strategy().ask(features)
                        if signal is None:
                            logger.warning("python_llm returned None, skipping candle")
                            continue
                        logger.info(
                            f"STRATEGY (python_llm): {signal.action.value} "
                            f"setup={signal.setup.value} conf={signal.confidence} "
                            f"layer={signal.decisive_layer}"
                        )
                    except Exception as e:
                        logger.error(f"python_llm call failed: {e}")
                        continue
                else:
                    # mock mode: deterministic Nogran PA heuristic (no LLM)
                    local_regime = detect_local_regime(features)
                    signal = generate_local_signal(features, local_regime, strict_trend_alignment=True)
                    logger.info(f"STRATEGY (mock): {signal.action.value} setup={signal.setup.value} conf={signal.confidence}")

                if signal is None:
                    logger.warning("Strategy Engine: no signal")
                    continue

                if signal.action == Action.AGUARDAR:
                    logger.info(f"STRATEGY: WAIT — {signal.reasoning[:80]}")
                    veto_score = decision_scorer.calculate(mq_score, 0, 50, 50)
                    decision_logger.log_decision(decision_score=veto_score, signal=signal, mq_score=mq_score, fact=fact, session_mode=session_mode)
                    continue

                # SS enriched with Nogran PA KB (blend LLM 60% + PA 40%, hallucination detector)
                enriched_ss = calculate_strategy_score_with_kb(signal, kb=probabilities_kb)
                ss_score = enriched_ss.blended_score
                if enriched_ss.match:
                    kb_log_label = f"KB={enriched_ss.match.setup_id}({enriched_ss.match.probability_pct}%)"
                else:
                    kb_log_label = "KB=no_match"
                if enriched_ss.alarm:
                    logger.warning(
                        f"HALLUCINATION_ALARM[{enriched_ss.alarm.severity}]: "
                        f"LLM={enriched_ss.alarm.llm_score} vs PA={enriched_ss.alarm.pa_probability} "
                        f"(gap={enriched_ss.alarm.gap:+d}) for {enriched_ss.alarm.setup_id}"
                    )
                logger.info(
                    f"STRATEGY: {signal.action.value} (conf={signal.confidence}, setup={signal.setup.value}, "
                    f"SS_llm={enriched_ss.llm_score} -> SS_blended={ss_score}, {kb_log_label})"
                )

                # Build kb metadata dicts for the audit log (None if no match)
                kb_match_log = None
                if enriched_ss.match:
                    kb_match_log = {
                        "setup_id": enriched_ss.match.setup_id,
                        "name_pt": enriched_ss.match.name_pt,
                        "probability_pct": enriched_ss.match.probability_pct,
                        "probability_confidence": enriched_ss.match.probability_confidence,
                        "min_reward_risk": enriched_ss.match.min_reward_risk,
                        "llm_score": enriched_ss.llm_score,
                        "blended_score": enriched_ss.blended_score,
                    }
                hallucination_alarm_log = None
                if enriched_ss.alarm:
                    hallucination_alarm_log = {
                        "llm_score": enriched_ss.alarm.llm_score,
                        "pa_probability": enriched_ss.alarm.pa_probability,
                        "gap": enriched_ss.alarm.gap,
                        "direction": enriched_ss.alarm.direction,
                        "setup_id": enriched_ss.alarm.setup_id,
                        "severity": enriched_ss.alarm.severity,
                    }

                # ========================================
                # STAGE 5: AI OVERLAY
                # ========================================
                regime = detect_regime(features)
                ao_score = calculate_ao_score(signal, features, regime, risk_metrics.trades)

                # ========================================
                # STAGE 6: RISK ENGINE
                # ========================================
                rs_score = calculate_risk_score(signal, risk_metrics, dd_controller)

                # ========================================
                # STAGE 7: DECISION SCORE
                # ========================================
                decision = decision_scorer.calculate(mq_score, ss_score, ao_score, rs_score)
                # Override threshold based on session
                if decision.total < session_threshold:
                    decision = DecisionScore(
                        total=decision.total,
                        go=False,
                        breakdown=decision.breakdown,
                        threshold=session_threshold,
                        hard_veto=decision.hard_veto,
                        veto_reason=f"Score {decision.total:.1f} < session threshold {session_threshold} ({session_mode})",
                    )

                # Check setup allowed in current session
                if decision.go and not is_setup_allowed(signal.setup.value, session_mode):
                    decision = DecisionScore(
                        total=decision.total,
                        go=False,
                        breakdown=decision.breakdown,
                        threshold=session_threshold,
                        hard_veto=False,
                        veto_reason=f"Setup {signal.setup.value} not allowed in {session_mode} mode",
                    )
                    logger.info(f"SESSION VETO: {decision.veto_reason}")

                # ========================================
                # STAGE 8: ERC-8004 (RiskRouter + Checkpoint)
                # ========================================
                erc8004_tx = ""

                if erc8004 and decision.go:
                    # Simulate first (no gas)
                    sim = erc8004.simulate_trade_intent(
                        pair="BTCUSD",
                        action="BUY" if signal.action == Action.COMPRA else "SELL",
                        amount_usd=signal.entry_price * 0.001,  # Rough USD value
                    )
                    logger.info(f"ERC-8004 simulate: approved={sim['approved']}, reason={sim['reason']}")

                    if sim["approved"]:
                        # Submit real trade intent on-chain
                        try:
                            result = erc8004.submit_trade_intent(
                                pair="BTCUSD",
                                action="BUY" if signal.action == Action.COMPRA else "SELL",
                                amount_usd=signal.entry_price * 0.001,
                            )
                            erc8004_tx = result.get("tx", "")
                            if not result["approved"]:
                                logger.warning(f"ERC-8004 RiskRouter rejected: {result['reason']}")
                        except Exception as e:
                            logger.error(f"ERC-8004 submit failed: {e}")

                    # Post checkpoint (always, even if rejected)
                    try:
                        erc8004.post_checkpoint(
                            decision_score=decision.total,
                            action=signal.action.value,
                            pair="BTCUSD",
                            reasoning_summary=signal.reasoning,
                        )
                    except Exception as e:
                        logger.error(f"ERC-8004 checkpoint failed: {e}")

                # ========================================
                # STAGE 9: EXECUTE OR LOG
                # ========================================
                if decision.go:
                    pos_size = position_sizer.calculate(
                        capital=risk_metrics.current_equity,
                        atr=features.atr_14,
                        decision_score=decision,
                        metrics=risk_metrics,
                    )
                    pos_size *= get_session_sizing_mult(session_mode)

                    dd = risk_metrics.current_drawdown
                    band = dd_controller.get_band(dd)
                    risk_approval = RiskApproval(
                        approved=True,
                        position_size=pos_size,
                        adjusted_stop=signal.stop_loss,
                        adjusted_target=signal.take_profit,
                        risk_pct=Config.RISK_PER_TRADE,
                        reward_risk_ratio=abs(signal.take_profit - signal.entry_price) / abs(signal.entry_price - signal.stop_loss) if abs(signal.entry_price - signal.stop_loss) > 0 else 0,
                        current_drawdown=dd,
                        drawdown_band=band,
                        regime=regime,
                        atr=features.atr_14,
                        sharpe_rolling=risk_metrics.sharpe_rolling,
                        risk_score=rs_score,
                    )

                    logger.info(
                        f"EXECUTING: {signal.action.value} {pos_size:.6f} BTC "
                        f"@ ${signal.entry_price:.1f} (Score: {decision.total:.1f})"
                    )

                    try:
                        exec_result = executor.execute_trade(signal, risk_approval, decision)
                        exposure_mgr.on_position_opened(candle_index)

                        decision_logger.log_decision(
                            decision_score=decision, signal=signal, risk_approval=risk_approval,
                            execution_result={
                                "order_id": exec_result.order_id,
                                "fill_price": exec_result.fill_price,
                                "timestamp": exec_result.timestamp.isoformat() if exec_result.timestamp else None,
                            },
                            mq_score=mq_score, regime=regime.value, fact=fact,
                            erc8004_signature=erc8004_tx,
                            session_mode=session_mode,
                            kb_match=kb_match_log,
                            hallucination_alarm=hallucination_alarm_log,
                            rr_warning=enriched_ss.rr_warning,
                        )

                        # Post reputation feedback after execution
                        if erc8004 and exec_result.success:
                            try:
                                erc8004.submit_feedback(
                                    score=int(decision.total),
                                    trade_id=exec_result.order_id,
                                    comment=f"Score={decision.total:.1f} Setup={signal.setup.value}",
                                    feedback_type=0,  # TRADE_EXECUTION
                                )
                            except Exception as e:
                                logger.error(f"ERC-8004 feedback failed: {e}")

                    except KrakenCLIError as e:
                        logger.error(f"Execution failed: {e}")
                        decision_logger.log_decision(
                            decision_score=decision, signal=signal, risk_approval=risk_approval,
                            execution_result={"error": str(e)},
                            mq_score=mq_score, regime=regime.value, fact=fact,
                            session_mode=session_mode,
                            kb_match=kb_match_log,
                            hallucination_alarm=hallucination_alarm_log,
                            rr_warning=enriched_ss.rr_warning,
                        )
                else:
                    logger.info(f"VETOED: Score {decision.total:.1f}/100 ({decision.veto_reason})")
                    decision_logger.log_decision(
                        decision_score=decision, signal=signal,
                        mq_score=mq_score, regime=regime.value, fact=fact,
                        session_mode=session_mode,
                        kb_match=kb_match_log,
                        hallucination_alarm=hallucination_alarm_log,
                        rr_warning=enriched_ss.rr_warning,
                    )

                    # Post checkpoint for vetoed decisions too (transparency)
                    if erc8004:
                        try:
                            erc8004.post_checkpoint(
                                decision_score=decision.total,
                                action="WAIT",
                                pair="BTCUSD",
                                reasoning_summary=f"VETOED: {decision.veto_reason}",
                            )
                        except Exception:
                            pass

            except KeyboardInterrupt:
                raise
            except Exception as e:
                # Information disclosure mitigation: only log full traceback in debug mode.
                # Prod logs get error type + message only — no paths, no stack frames.
                if Config.DEBUG:
                    logger.error(f"Pipeline error: {type(e).__name__}: {e}", exc_info=True)
                else:
                    logger.error(f"Pipeline error: {type(e).__name__}: {e}")
                await asyncio.sleep(5)

    except ImportError:
        logger.error("ccxt.pro not installed. Install: pip install ccxt")
        return


def main():
    try:
        asyncio.run(run_pipeline())
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        # Final reputation check
        if erc8004:
            try:
                rep = erc8004.get_reputation_score()
                val = erc8004.get_validation_score()
                logger.info(f"Final scores — Reputation: {rep}/100, Validation: {val}/100")
            except Exception:
                pass


if __name__ == "__main__":
    main()
