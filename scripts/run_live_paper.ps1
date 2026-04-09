# run_live_paper.ps1 — start nogran live paper trading no Windows
#
# Modos:
#   .\scripts\run_live_paper.ps1            -> auto (default = python_llm)
#   .\scripts\run_live_paper.ps1 -Mock      -> forca strategy mock (sem LLM, sem custo)
#   .\scripts\run_live_paper.ps1 -PythonLlm -> forca python_llm (OpenAI live, custo!)
#
# Pre-requisitos:
#   - .env com ERC8004_PRIVATE_KEY (ja setado se voce rodou setup_erc8004.py)
#   - Kraken CLI instalado (https://github.com/krakenfx/kraken-cli)
#   - Para -PythonLlm: OPENAI_API_KEY no .env

[CmdletBinding()]
param(
    [switch]$Mock,
    [switch]$PythonLlm,
    [switch]$Auto
)

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# Resolve strategy source
if ($Mock) { $env:STRATEGY_SOURCE = "mock" }
elseif ($PythonLlm) { $env:STRATEGY_SOURCE = "python_llm" }
else { $env:STRATEGY_SOURCE = "python_llm" }  # default

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  nogran.trader.agent — LIVE PAPER TRADING" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Strategy source : $env:STRATEGY_SOURCE"
Write-Host "  Trading pair    : BTC/USD"
Write-Host "  Mode            : Kraken CLI paper (no real money)"
Write-Host "  Logs            : logs/decisions/<date>.jsonl"
Write-Host "  Stop with       : Ctrl+C"
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# Sanity checks
if (-not (Test-Path ".env")) {
    Write-Host "WARNING: .env not found. ERC-8004 will be disabled." -ForegroundColor Yellow
}

if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "ERROR: venv not found. Create with: python -m venv venv" -ForegroundColor Red
    exit 1
}

# Check kraken CLI
$kraken = Get-Command kraken -ErrorAction SilentlyContinue
if (-not $kraken) {
    Write-Host "WARNING: kraken CLI not found in PATH. Execution will fail." -ForegroundColor Yellow
    Write-Host "  Install: https://github.com/krakenfx/kraken-cli/releases" -ForegroundColor Yellow
    Write-Host ""
    $proceed = Read-Host "Proceed anyway? (y/N)"
    if ($proceed -ne "y") { exit 1 }
}

Write-Host "Starting agent..." -ForegroundColor Green
Set-Location src
& ..\venv\Scripts\python.exe main.py
