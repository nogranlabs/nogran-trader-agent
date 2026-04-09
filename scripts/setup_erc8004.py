"""
setup_erc8004.py — registra agente, claim allocation, e posta checkpoint inicial.

Uso (apos colocar ERC8004_PRIVATE_KEY no .env):
    python scripts/setup_erc8004.py

Idempotente: pula passos ja executados (cache em logs/erc8004/state.json).

Steps:
  1. Conecta no Sepolia, valida balance > 0.01 ETH
  2. register_agent() → AgentRegistry → cacheia agent_id
  3. claim_allocation() → HackathonVault → 0.05 ETH sandbox
  4. post_checkpoint() → ValidationRegistry → score do latest backtest
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402
from web3 import Web3  # noqa: E402

load_dotenv(ROOT / ".env")

STATE_PATH = ROOT / "logs" / "erc8004" / "state.json"
STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Public Sepolia RPCs em ordem de preferencia. rpc.sepolia.org cai com frequencia.
SEPOLIA_RPCS = [
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://sepolia.gateway.tenderly.co",
    "https://endpoints.omniatech.io/v1/eth/sepolia/public",
    "https://eth-sepolia.public.blastapi.io",
    "https://1rpc.io/sepolia",
    "https://sepolia.drpc.org",
    "https://rpc.sepolia.org",  # last resort
]


def find_working_rpc() -> str:
    """Itera os RPCs e retorna o primeiro que responde."""
    from web3 import Web3
    for url in SEPOLIA_RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 5}))
            if w3.is_connected():
                # Sanity: confirma chain id
                if w3.eth.chain_id == 11155111:
                    print(f"  Using RPC: {url}")
                    return url
        except Exception:
            continue
    raise RuntimeError("No working Sepolia RPC found")


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
    raw_key = os.getenv("ERC8004_PRIVATE_KEY", "")
    if not raw_key or raw_key == "0x...":
        print("ERROR: ERC8004_PRIVATE_KEY not set in .env")
        sys.exit(1)

    key = normalize_key(raw_key)
    print(f"Key loaded: {len(key)} chars")

    from compliance.erc8004_onchain import ERC8004Hackathon

    print("Searching working Sepolia RPC...")
    rpc_url = find_working_rpc()

    print("Connecting to Sepolia...")
    client = ERC8004Hackathon(private_key=key, rpc_url=rpc_url)
    if not client.is_connected:
        print("ERROR: Sepolia RPC not reachable")
        sys.exit(2)

    print(f"  Address: {client.address}")
    bal_wei = client.w3.eth.get_balance(client.address)
    bal_eth = Web3.from_wei(bal_wei, "ether")
    print(f"  Balance: {bal_eth} ETH")
    if bal_wei < Web3.to_wei(0.01, "ether"):
        print("ERROR: balance < 0.01 ETH, get more from faucet")
        sys.exit(3)

    state = load_state()
    state["address"] = client.address

    # =========================================================
    # Step 1: register_agent (idempotent)
    # =========================================================
    if "agent_id" in state:
        client.agent_id = state["agent_id"]
        print(f"Step 1: SKIP (already registered, agent_id={client.agent_id})")
    else:
        print("Step 1: Registering agent on AgentRegistry...")
        try:
            agent_id = client.register_agent(
                name="nogran.trader.agent",
                description="BTC/USD trading agent with PA KB hallucination detector",
                capabilities=["trading", "risk_management", "price_action_analysis"],
                agent_uri="",
            )
            state["agent_id"] = agent_id
            state["register_tx"] = "registered"
            save_state(state)
            print(f"  agent_id={agent_id}")
        except Exception as e:
            print(f"  FAILED: {e}")
            sys.exit(4)

    # =========================================================
    # Step 2: claim_allocation (idempotent)
    # =========================================================
    if state.get("allocation_claimed"):
        print(f"Step 2: SKIP (already claimed)")
    else:
        print("Step 2: Claiming HackathonVault allocation...")
        try:
            result = client.claim_allocation()
            if result.get("already_claimed"):
                print(f"  Already claimed. Balance: {Web3.from_wei(result['balance_wei'], 'ether')} ETH")
            else:
                print(f"  Claimed! tx={result.get('tx', '?')}")
                state["claim_tx"] = result.get("tx", "")
            state["allocation_claimed"] = True
            save_state(state)
        except Exception as e:
            print(f"  FAILED: {e}")
            # Don't exit — checkpoint can still work
            state["claim_error"] = str(e)
            save_state(state)

    # =========================================================
    # Step 3: post_checkpoint (always reposts — score may evolve)
    # =========================================================
    print("Step 3: Computing validation score from latest backtest...")
    from post_validation import compute_validation_score, find_latest_run

    latest = find_latest_run()
    if latest is None:
        print("  WARNING: no backtest run found, using default score=50")
        score = 50
        notes = "No backtest available — bootstrap checkpoint"
    else:
        with open(latest / "summary.json", encoding="utf-8") as f:
            summary = json.load(f)
        breakdown = compute_validation_score(summary)
        score = breakdown.final_score
        notes = breakdown.notes
        print(f"  Run: {latest.name}")
        print(f"  Score: {score}/100  ({breakdown.notes})")

    print("Step 3: Posting checkpoint to ValidationRegistry...")
    try:
        result = client.post_checkpoint(
            decision_score=float(score),
            action="backtest_validation",
            pair="BTC/USD",
            reasoning_summary=notes,
        )
        if result is None:
            print("  FAILED: post_checkpoint returned None")
            sys.exit(5)
        state["last_checkpoint"] = {
            "score": result.get("score", score),
            "tx": result.get("tx", ""),
            "notes": notes,
        }
        save_state(state)
        print(f"  tx={result.get('tx', '?')}")
        print(f"  score={result.get('score', score)}")
    except Exception as e:
        print(f"  FAILED: {e}")
        sys.exit(5)

    # Final balance
    bal_wei = client.w3.eth.get_balance(client.address)
    bal_eth = Web3.from_wei(bal_wei, "ether")
    print()
    print("=" * 64)
    print("ERC-8004 SETUP COMPLETE")
    print("=" * 64)
    print(f"  Address     : {client.address}")
    print(f"  agent_id    : {state.get('agent_id', '?')}")
    print(f"  Balance     : {bal_eth} ETH (after gas)")
    print(f"  State file  : {STATE_PATH}")
    print()
    print("Sepolia explorer links:")
    print(f"  Address  : https://sepolia.etherscan.io/address/{client.address}")
    if state.get("last_checkpoint", {}).get("tx"):
        tx = state["last_checkpoint"]["tx"]
        print(f"  Last tx  : https://sepolia.etherscan.io/tx/{tx}")


if __name__ == "__main__":
    main()
