"""
periodic_checkpoint.py — posta validation checkpoint a cada N horas.

Uso:
    # Postar 1x agora (combinacao manual + cron externo)
    python scripts/periodic_checkpoint.py --once

    # Loop interno a cada 6h (ate Ctrl+C)
    python scripts/periodic_checkpoint.py --interval 6

Comportamento:
1. Le o run de backtest mais recente (ou usa decisao agregada do live se disponivel)
2. Calcula score composto via post_validation.compute_validation_score
3. Posta on-chain via ERC8004Hackathon.post_checkpoint
4. Salva tx hash em logs/erc8004/checkpoints.jsonl

Por que isso importa pro hackathon:
- Mostra que o agente esta VIVO e operando ate o freeze
- Move o ranking automatico de "validation quality" continuamente
- Cria audit trail on-chain de quantas vezes o agente reportou status
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

CHECKPOINTS_LOG = ROOT / "logs" / "erc8004" / "checkpoints.jsonl"
STATE_PATH = ROOT / "logs" / "erc8004" / "state.json"


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def append_checkpoint_log(entry: dict):
    CHECKPOINTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINTS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def post_one() -> dict:
    """Post a single checkpoint. Returns the result dict."""
    import os
    from setup_erc8004 import find_working_rpc, normalize_key
    from post_validation import compute_validation_score, find_latest_run

    raw_key = os.getenv("ERC8004_PRIVATE_KEY", "")
    if not raw_key or raw_key == "0x...":
        return {"error": "ERC8004_PRIVATE_KEY not set"}

    state = load_state()
    if "agent_id" not in state:
        return {"error": "no agent_id in state.json — run setup_erc8004.py first"}

    from compliance.erc8004_onchain import ERC8004Hackathon

    try:
        rpc = find_working_rpc()
    except RuntimeError as e:
        return {"error": str(e)}

    client = ERC8004Hackathon(private_key=normalize_key(raw_key), rpc_url=rpc)
    client.agent_id = int(state["agent_id"])

    # Compute score from latest run
    latest = find_latest_run()
    if latest is None:
        return {"error": "no backtest run found"}

    with open(latest / "summary.json", encoding="utf-8") as f:
        summary = json.load(f)
    breakdown = compute_validation_score(summary)

    # Post on-chain
    try:
        result = client.post_checkpoint(
            decision_score=float(breakdown.final_score),
            action="periodic_checkpoint",
            pair="BTC/USD",
            reasoning_summary=breakdown.notes,
        )
    except Exception as e:
        return {"error": f"post_checkpoint failed: {e}"}

    if result is None:
        return {"error": "post_checkpoint returned None"}

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "score": breakdown.final_score,
        "tx": result.get("tx", ""),
        "run": latest.name,
        "breakdown": breakdown.to_dict(),
    }
    append_checkpoint_log(entry)
    return entry


def main():
    parser = argparse.ArgumentParser(description="Periodic ValidationRegistry checkpoint poster")
    parser.add_argument("--once", action="store_true", help="post 1 checkpoint and exit")
    parser.add_argument("--interval", type=float, default=6.0, help="hours between posts (loop mode)")
    parser.add_argument("--max-iters", type=int, default=0, help="0 = infinite loop")
    args = parser.parse_args()

    if args.once:
        print("Posting 1 checkpoint...")
        result = post_one()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if "error" not in result else 1)

    print(f"Periodic checkpoint loop: every {args.interval}h")
    iters = 0
    while args.max_iters == 0 or iters < args.max_iters:
        ts = datetime.now(timezone.utc).isoformat()
        print(f"\n[{ts}] Posting checkpoint #{iters + 1}...")
        result = post_one()
        if "error" in result:
            print(f"  ERROR: {result['error']}")
        else:
            print(f"  OK: score={result['score']} tx={result['tx']}")
        iters += 1
        if args.max_iters and iters >= args.max_iters:
            break
        sleep_secs = args.interval * 3600
        print(f"  Sleeping {args.interval}h until next post...")
        time.sleep(sleep_secs)


if __name__ == "__main__":
    main()
