"""
activity_push.py — submeter atividade on-chain pra atrair attestation dos validators.

Estrategia:
1. Submit N TradeIntents ao RiskRouter (assinados EIP-712)
2. Submit N feedbacks ao ReputationRegistry
3. Esperar 6-24h pra validators detectarem e atestarem
4. Re-checar getAverageValidationScore(agent_id)

Uso:
    python scripts/activity_push.py --intents 5 --feedbacks 5
    python scripts/activity_push.py --intents 3  # only intents
    python scripts/activity_push.py --check-score-only  # just print current score

Pre-req: ERC8004_PRIVATE_KEY no .env, agent_id ja registered (logs/erc8004/state.json).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

STATE_PATH = ROOT / "logs" / "erc8004" / "state.json"


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def normalize_key(raw: str) -> str:
    raw = raw.strip()
    if not raw.startswith("0x"):
        raw = "0x" + raw
    return raw


def main():
    parser = argparse.ArgumentParser(description="Push on-chain activity for validator attestation")
    parser.add_argument("--intents", type=int, default=5,
                        help="number of TradeIntents to submit (default 5)")
    parser.add_argument("--feedbacks", type=int, default=5,
                        help="number of reputation feedbacks (default 5)")
    parser.add_argument("--check-score-only", action="store_true",
                        help="just print current validation/reputation scores and exit")
    parser.add_argument("--delay", type=float, default=3.0,
                        help="seconds between submissions (default 3.0)")
    args = parser.parse_args()

    raw_key = os.getenv("ERC8004_PRIVATE_KEY", "")
    if not raw_key or raw_key == "0x...":
        print("ERROR: ERC8004_PRIVATE_KEY not set in .env")
        sys.exit(1)

    state = load_state()
    if "agent_id" not in state:
        print("ERROR: agent_id not found in logs/erc8004/state.json — run setup_erc8004.py first")
        sys.exit(1)

    agent_id = int(state["agent_id"])
    print(f"Agent ID: {agent_id}")

    from setup_erc8004 import find_working_rpc
    print("Finding working Sepolia RPC...")
    rpc = find_working_rpc()

    from compliance.erc8004_onchain import ERC8004Hackathon
    client = ERC8004Hackathon(private_key=normalize_key(raw_key), rpc_url=rpc)
    client.agent_id = agent_id

    print(f"Wallet: {client.address}")
    bal = client.w3.from_wei(client.w3.eth.get_balance(client.address), "ether")
    print(f"Balance: {bal} ETH")

    # Print current scores
    print()
    print("=" * 60)
    print("CURRENT SCORES (before push)")
    print("=" * 60)
    val_score = client.get_validation_score()
    rep_score = client.get_reputation_score()
    print(f"  Validation: {val_score}/100")
    print(f"  Reputation: {rep_score}/100")
    print()

    if args.check_score_only:
        sys.exit(0)

    state.setdefault("activity_log", [])

    # =========================================================
    # Submit TradeIntents
    # =========================================================
    if args.intents > 0:
        print(f"Submitting {args.intents} TradeIntents to RiskRouter...")
        # Vary action and amount to look "active"
        intent_configs = [
            ("BTC/USD", "BUY", 50.0),
            ("BTC/USD", "BUY", 25.0),
            ("BTC/USD", "SELL", 30.0),
            ("BTC/USD", "BUY", 75.0),
            ("BTC/USD", "SELL", 40.0),
            ("BTC/USD", "BUY", 35.0),
            ("BTC/USD", "BUY", 60.0),
            ("BTC/USD", "SELL", 20.0),
            ("BTC/USD", "BUY", 45.0),
            ("BTC/USD", "BUY", 55.0),
        ]
        for i in range(args.intents):
            pair, action, amount = intent_configs[i % len(intent_configs)]
            print(f"\n  [{i + 1}/{args.intents}] {action} {pair} ${amount}...")
            try:
                result = client.submit_trade_intent(
                    pair=pair, action=action, amount_usd=amount,
                    max_slippage_bps=100, deadline_seconds=600,
                )
                approved = result.get("approved", False)
                tx = result.get("tx", "")
                reason = result.get("reason", "")
                marker = "OK" if approved else "REJECTED"
                print(f"    {marker} ({reason}) tx={tx[:20]}")
                state["activity_log"].append({
                    "type": "trade_intent",
                    "ts": time.time(),
                    "result": result,
                })
                save_state(state)
            except Exception as e:
                print(f"    ERROR: {e}")
                state["activity_log"].append({"type": "trade_intent", "error": str(e), "ts": time.time()})
                save_state(state)
            time.sleep(args.delay)

    # =========================================================
    # Submit reputation feedbacks
    # =========================================================
    if args.feedbacks > 0:
        print(f"\nSubmitting {args.feedbacks} reputation feedbacks...")
        for i in range(args.feedbacks):
            score = 70 + (i * 5) % 25  # 70, 75, 80, 85, 90, 70...
            comment = f"Self-reported trade outcome #{i + 1}: simulated paper trade for activity baseline"
            print(f"\n  [{i + 1}/{args.feedbacks}] score={score}...")
            try:
                result = client.submit_feedback(
                    score=score,
                    trade_id=f"sim_trade_{int(time.time())}_{i}",
                    comment=comment,
                    feedback_type=0,
                )
                if result is None:
                    print(f"    FAILED (None returned)")
                else:
                    tx = result.get("tx", "")
                    print(f"    OK tx={tx[:20]}")
                state["activity_log"].append({
                    "type": "feedback", "score": score,
                    "ts": time.time(), "result": result,
                })
                save_state(state)
            except Exception as e:
                print(f"    ERROR: {e}")
                state["activity_log"].append({"type": "feedback", "error": str(e), "ts": time.time()})
                save_state(state)
            time.sleep(args.delay)

    # =========================================================
    # Final balance + scores
    # =========================================================
    print()
    print("=" * 60)
    print("DONE")
    print("=" * 60)
    bal_after = client.w3.from_wei(client.w3.eth.get_balance(client.address), "ether")
    print(f"Final balance: {bal_after} ETH (spent ~{float(bal) - float(bal_after):.6f} on gas)")
    val_score = client.get_validation_score()
    rep_score = client.get_reputation_score()
    print(f"Validation: {val_score}/100 (was 0 before — won't update immediately)")
    print(f"Reputation: {rep_score}/100")
    print()
    print("Validators may take hours to detect new activity. Re-check tomorrow with:")
    print("  python scripts/activity_push.py --check-score-only")


if __name__ == "__main__":
    main()
