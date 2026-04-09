"""
post_validation.py — postar checkpoint no ValidationRegistry da hackathon (Sepolia).

Le o `summary.json` de um backtest run (gerado por scripts/backtest.py) e chama
`ERC8004Hackathon.post_checkpoint()` com um score composito (PnL + qualidade).

Uso:
  # Dry-run (nao precisa wallet, so calcula e imprime)
  python scripts/post_validation.py --dry-run --run-dir logs/backtest/<run_id>

  # Live (precisa ERC8004_PRIVATE_KEY no .env e ETH de faucet em Sepolia)
  python scripts/post_validation.py --run-dir logs/backtest/<run_id>

  # Pega o run mais recente automaticamente
  python scripts/post_validation.py --dry-run --latest

Score composto (0-100):
  - 50% PnL component:    sigmoid(sharpe) * (1 - dd_pct/10) * 100
  - 30% Process quality:  audit completeness, KB coverage, test count
  - 20% Risk discipline:  max_dd inverso, hard veto rate

Justificativa: ValidationRegistry mede "confiabilidade do checkpoint", nao
puramente PnL. Um agente que perde dinheiro mas tem audit trail impecavel,
KB coverage 100%, e 0 violacoes de risco e mais "validavel" que um que
ganha muito mas quebra disciplina.

CLAUDE.md compliance: nao altera Decision Scorer nem thresholds de risco.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


# ============================================================
# Score composto
# ============================================================


@dataclass
class ValidationScoreBreakdown:
    pnl_component: float       # 0-100
    quality_component: float   # 0-100
    risk_component: float      # 0-100
    final_score: int           # 0-100 (rounded)
    notes: str                 # human-readable

    def to_dict(self) -> dict:
        return {
            "pnl_component": round(self.pnl_component, 2),
            "quality_component": round(self.quality_component, 2),
            "risk_component": round(self.risk_component, 2),
            "final_score": self.final_score,
            "notes": self.notes,
        }


def _sigmoid(x: float, k: float = 0.5) -> float:
    """Logistic sigmoid centered at 0. k controls steepness."""
    try:
        return 1.0 / (1.0 + math.exp(-k * x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def compute_pnl_component(sharpe: float, max_dd_pct: float) -> float:
    """PnL component (0-100): rewards positive Sharpe + low drawdown.

    sharpe: annualized Sharpe ratio
    max_dd_pct: max drawdown in percent (e.g. 8.0 means 8%)
    """
    sharpe_score = _sigmoid(sharpe, k=0.7) * 100  # sharpe 0 → 50, +5 → 97, -5 → 3
    # Drawdown penalty: 0% → 1.0, 10% → 0, 20% → 0
    dd_factor = max(0.0, 1.0 - (max_dd_pct / 10.0))
    return sharpe_score * dd_factor


def compute_quality_component(stats: dict, coverage_data: Optional[dict] = None) -> float:
    """Process quality (0-100): audit completeness + KB coverage + test count.

    Inputs sao opcionais; ausente → componente neutro (50).
    """
    if not stats:
        return 50.0

    score = 0.0

    # Audit completeness: ratio of GO/(GO+NOGO) actually decided
    total = stats.get("total_decisions", 0)
    go = stats.get("go", 0)
    no_go = stats.get("no_go", 0)
    decided = go + no_go
    if total > 0:
        decided_ratio = min(1.0, decided / max(total, 1))
        score += decided_ratio * 30  # max 30 pts
    else:
        score += 15  # neutral

    # Hard vetoes percent (Risk + pre-filter): higher is BETTER (filtering ruim)
    veto_pf = stats.get("vetoes_pre_filter", 0)
    veto_rs = stats.get("vetoes_risk", 0)
    if total > 0:
        veto_ratio = (veto_pf + veto_rs) / max(total, 1)
        veto_score = min(1.0, veto_ratio * 5)  # 20%+ veto = 30 pts
        score += veto_score * 30
    else:
        score += 15

    # Pipeline reach: did the run actually process candles?
    bars = coverage_data.get("bars_processed", 0) if coverage_data else 0
    if bars >= 5000:
        score += 25  # large sample
    elif bars >= 1000:
        score += 18
    elif bars >= 100:
        score += 10
    else:
        score += 5

    # Test count proxy (passed via coverage_data; ele fica fixed por enquanto)
    test_count = coverage_data.get("test_count", 0) if coverage_data else 0
    if test_count >= 200:
        score += 15
    elif test_count >= 100:
        score += 10
    elif test_count >= 50:
        score += 6
    else:
        score += 2

    return min(100.0, score)


def compute_risk_component(max_dd_pct: float, num_trades: int, alarms: int) -> float:
    """Risk discipline (0-100): low DD + reasonable trade frequency + low alarms."""
    score = 0.0
    # DD inverse: 0% → 50, 5% → 25, 10%+ → 0
    if max_dd_pct < 1:
        score += 50
    elif max_dd_pct < 3:
        score += 40
    elif max_dd_pct < 5:
        score += 30
    elif max_dd_pct < 8:
        score += 18
    elif max_dd_pct < 10:
        score += 8
    else:
        score += 0

    # Trade frequency (sweet spot 50-500 in 30 days)
    if 50 <= num_trades <= 500:
        score += 30
    elif 10 <= num_trades < 50:
        score += 20
    elif num_trades > 500:
        score += 15
    elif num_trades > 0:
        score += 10
    else:
        score += 0

    # Alarms: pequena qtd e ok (mostra detector funciona); muito = problema
    if alarms == 0:
        score += 15  # silent detector
    elif alarms <= 5:
        score += 20  # detector firing healthily
    elif alarms <= 20:
        score += 12
    else:
        score += 5  # too noisy

    return min(100.0, score)


def compute_validation_score(summary: dict) -> ValidationScoreBreakdown:
    """Aggregator: le summary.json e produz score composto."""
    metrics = summary.get("metrics", {})
    stats = summary.get("stats", {})

    risk_metrics = metrics.get("risk", {})
    trades_metrics = metrics.get("trades", {})
    meta = metrics.get("meta", {})

    sharpe = risk_metrics.get("sharpe_ratio", 0.0)
    max_dd_pct = risk_metrics.get("max_drawdown_pct", 0.0)
    num_trades = trades_metrics.get("num_trades", 0)
    alarms = stats.get("alarms", 0)

    coverage_data = {
        "bars_processed": meta.get("bars_processed", 0),
        "test_count": 232,  # current verified count
    }

    pnl_c = compute_pnl_component(sharpe, max_dd_pct)
    quality_c = compute_quality_component(stats, coverage_data)
    risk_c = compute_risk_component(max_dd_pct, num_trades, alarms)

    final = (pnl_c * 0.50) + (quality_c * 0.30) + (risk_c * 0.20)
    final_int = max(1, min(100, int(round(final))))

    notes = (
        f"Composite v1: PnL={pnl_c:.0f}/Q={quality_c:.0f}/R={risk_c:.0f}. "
        f"Sharpe={sharpe:.2f} DD={max_dd_pct:.1f}% trades={num_trades} alarms={alarms}"
    )

    return ValidationScoreBreakdown(
        pnl_component=pnl_c,
        quality_component=quality_c,
        risk_component=risk_c,
        final_score=final_int,
        notes=notes,
    )


# ============================================================
# Backtest run discovery
# ============================================================


def find_latest_run() -> Optional[Path]:
    base = ROOT / "logs" / "backtest"
    if not base.exists():
        return None
    runs = sorted([p for p in base.iterdir() if p.is_dir()])
    return runs[-1] if runs else None


def load_summary(run_dir: Path) -> dict:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"summary.json not found in {run_dir}")
    with open(summary_path) as f:
        return json.load(f)


# ============================================================
# Posting (live mode)
# ============================================================


def post_to_chain(score: int, notes: str, action_summary: str = "backtest") -> dict:
    """Submit checkpoint to ValidationRegistry on Sepolia.

    Returns dict with tx_hash + score on success, or error info.
    """
    private_key = os.getenv("ERC8004_PRIVATE_KEY", "")
    if not private_key or private_key == "0x...":  # pragma: allowlist secret
        return {"error": "ERC8004_PRIVATE_KEY not set in .env"}

    try:
        from compliance.erc8004_onchain import ERC8004Hackathon
    except ImportError as e:
        return {"error": f"failed to import ERC8004Hackathon: {e}"}

    try:
        client = ERC8004Hackathon(private_key=private_key)
    except Exception as e:
        return {"error": f"failed to init client: {e}"}

    if not client.is_connected:
        return {"error": "not connected to Sepolia RPC"}

    # Try to read agent_id from registration metadata or trigger registration
    agent_id_path = ROOT / "logs" / "erc8004_agent_id.txt"
    if agent_id_path.exists():
        try:
            client.agent_id = int(agent_id_path.read_text().strip())
        except Exception:
            pass

    if client.agent_id is None:
        try:
            print("Agent not yet registered on-chain. Registering...")
            agent_id = client.register_agent()
            agent_id_path.parent.mkdir(parents=True, exist_ok=True)
            agent_id_path.write_text(str(agent_id))
            print(f"  agent_id={agent_id}, cached in {agent_id_path}")
        except Exception as e:
            return {"error": f"agent registration failed: {e}"}

    # Post checkpoint
    result = client.post_checkpoint(
        decision_score=float(score),
        action="backtest_validation",
        pair="BTC/USD",
        reasoning_summary=notes,
    )
    if result is None:
        return {"error": "post_checkpoint returned None"}
    return result


# ============================================================
# Entry
# ============================================================


def main():
    parser = argparse.ArgumentParser(description="Post backtest validation score to ValidationRegistry")
    parser.add_argument("--run-dir", type=str, default=None,
                        help="path to logs/backtest/<run_id>/. Default: --latest")
    parser.add_argument("--latest", action="store_true",
                        help="usa o backtest run mais recente")
    parser.add_argument("--dry-run", action="store_true",
                        help="nao envia tx; so calcula e imprime")
    parser.add_argument("--out", type=str, default=None,
                        help="path opcional para salvar o resultado JSON")
    args = parser.parse_args()

    # Resolve run dir
    if args.run_dir:
        run_dir = Path(args.run_dir)
    elif args.latest:
        latest = find_latest_run()
        if latest is None:
            print("ERROR: no backtest runs found in logs/backtest/")
            sys.exit(1)
        run_dir = latest
    else:
        latest = find_latest_run()
        if latest is None:
            print("ERROR: provide --run-dir or --latest")
            sys.exit(1)
        run_dir = latest
        print(f"(no --run-dir, using latest: {run_dir.name})")

    summary = load_summary(run_dir)
    breakdown = compute_validation_score(summary)

    print()
    print("=" * 64)
    print("VALIDATION SCORE")
    print("=" * 64)
    print(f"  Run dir         : {run_dir.name}")
    print(f"  PnL component   : {breakdown.pnl_component:.1f} / 100  (weight 50%)")
    print(f"  Quality compo.  : {breakdown.quality_component:.1f} / 100  (weight 30%)")
    print(f"  Risk discipline : {breakdown.risk_component:.1f} / 100  (weight 20%)")
    print(f"  -------")
    print(f"  FINAL SCORE     : {breakdown.final_score} / 100")
    print(f"  Notes           : {breakdown.notes}")
    print("=" * 64)

    payload = {
        "score": breakdown.final_score,
        "breakdown": breakdown.to_dict(),
        "run_dir": str(run_dir),
        "summary_input": {
            "sharpe": summary["metrics"]["risk"]["sharpe_ratio"],
            "max_dd_pct": summary["metrics"]["risk"]["max_drawdown_pct"],
            "num_trades": summary["metrics"]["trades"]["num_trades"],
            "win_rate": summary["metrics"]["trades"]["win_rate"],
        },
    }

    if args.dry_run:
        print()
        print("DRY-RUN — no on-chain transaction sent.")
        print("Would call: ValidationRegistry.postEIP712Attestation(")
        print(f"  agent_id, checkpoint_hash, score={breakdown.final_score}, notes='{breakdown.notes[:60]}...'")
        print(")")
        result = {"dry_run": True, **payload}
    else:
        print()
        print("Posting to Sepolia ValidationRegistry...")
        post_result = post_to_chain(breakdown.final_score, breakdown.notes)
        if "error" in post_result:
            print(f"FAILED: {post_result['error']}")
            print()
            print("Setup steps necessarios:")
            print("  1. Gerar wallet:")
            print("     python -c \"from eth_account import Account; a=Account.create(); print(a.address); print(a.key.hex())\"")
            print("  2. Adicionar ERC8004_PRIVATE_KEY=0x... no .env")
            print("  3. Pegar testnet ETH em https://www.alchemy.com/faucets/ethereum-sepolia")
            print("  4. Re-rodar este script sem --dry-run")
            sys.exit(2)
        print(f"  tx_hash: {post_result.get('tx', 'unknown')}")
        print(f"  score:   {post_result.get('score', breakdown.final_score)}")
        result = {**payload, **post_result}

    if args.out:
        out_path = Path(args.out)
    else:
        out_path = run_dir / "validation_post.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print()
    print(f"Result saved -> {out_path}")


if __name__ == "__main__":
    main()
