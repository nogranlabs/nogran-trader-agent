#!/usr/bin/env bash
# run_live_paper.sh — start nogran live paper trading (Linux/Mac/WSL)
#
# Uso:
#   ./scripts/run_live_paper.sh           # auto (LLM se disponivel, mock se nao)
#   ./scripts/run_live_paper.sh mock      # forca mock (sem LLM)
#   ./scripts/run_live_paper.sh LLM       # forca LLM

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:-auto}"
export STRATEGY_SOURCE="$MODE"

echo "================================================================"
echo "  nogran.trader.agent — LIVE PAPER TRADING"
echo "================================================================"
echo "  Strategy source : $STRATEGY_SOURCE"
echo "  Trading pair    : BTC/USD"
echo "  Mode            : Kraken CLI paper (no real money)"
echo "  Logs            : logs/decisions/\$date.jsonl"
echo "  Stop with       : Ctrl+C"
echo "================================================================"
echo

if [ ! -f .env ]; then
    echo "WARNING: .env not found. ERC-8004 will be disabled."
fi

PYTHON="venv/Scripts/python.exe"
if [ ! -f "$PYTHON" ]; then
    PYTHON="venv/bin/python"
fi
if [ ! -f "$PYTHON" ]; then
    echo "ERROR: venv not found. Create with: python -m venv venv"
    exit 1
fi

if ! command -v kraken >/dev/null 2>&1; then
    echo "WARNING: kraken CLI not found. Execution may fail."
    echo "  Install: https://github.com/krakenfx/kraken-cli/releases"
    read -r -p "Proceed anyway? (y/N) " proceed
    [ "$proceed" = "y" ] || exit 1
fi

echo "Starting agent..."
cd src
exec "../$PYTHON" main.py
