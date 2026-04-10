# SETUP — nogran.trader.agent

> Install, configuration and execution guide.
> For architecture and design decisions, see [README.md](./README.md).
> For technical detail, see [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## Quick start with Docker (recommended for judges)

Dashboard demo in one command, with no local dependency other than Docker:

```bash
docker compose up
# open http://localhost:8501 (DEMO_MODE=1, synthetic data)
```

Full stack (dashboard + agent):

```bash
export OPENAI_API_KEY=sk-...
docker compose --profile full up
```

Stop:
```bash
docker compose down                  # dashboard only
docker compose --profile full down   # everything
```

The Kraken CLI is **not** bundled in the container — for live paper trading, install it on the host.

---

## Prerequisites (manual install without Docker)

- Python 3.10+
- Kraken CLI
- OpenAI API key
- (Optional) Ethereum wallet for ERC-8004

---

## 1. Install

```bash
cd nogran.trader.agent

# Virtual environment
python -m venv venv

# Windows
.\venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

# Dependencies
pip install -r requirements.txt
```

---

## 2. Kraken CLI

The hackathon requires the Kraken CLI as the execution layer.

### Install

```bash
# Linux/Mac
curl --proto '=https' --tlsv1.2 -LsSf \
  https://github.com/krakenfx/kraken-cli/releases/latest/download/kraken-cli-installer.sh | sh

# Windows — download the binary from:
# https://github.com/krakenfx/kraken-cli/releases
```

### Verify install

```bash
kraken --version
```

### Test paper trading (no API key needed)

```bash
kraken paper buy BTC/USD 0.001 -o json
kraken paper balance -o json
kraken paper pnl -o json
kraken paper reset -o json
```

### Market data (no API key needed)

```bash
kraken market ticker BTC/USD -o json
kraken market ohlc BTC/USD --interval 1 -o json
```

---

## 3. Environment variables

Copy `.env.example` to `.env` and configure:

```env
# OpenAI — strategy LLM provider (single-call structured output)
OPENAI_API_KEY=sk-...

# Kraken (optional — paper trading does not need an API key)
KRAKEN_API_KEY=
KRAKEN_SECRET_KEY=

# ERC-8004 (Sepolia Testnet — hackathon shared contracts)
ERC8004_PRIVATE_KEY=0x...
ERC8004_AGENT_URI=https://raw.githubusercontent.com/nogran/nogran.trader.agent/main/agent_registration.json
SEPOLIA_RPC=https://rpc.sepolia.org
```

---

## 4. PA KB chunks (optional, improves RAG quality)

The Nogran PA KB has two components:

- `data/probabilities/pa_probabilities.json` — 62 setups + 22 hard rules (already in this repo)
- `data/chunks/layer*.json` — reference passages injected into the LLM prompt (gitignored — copy from the private dataset repo to enable the full RAG)

Without the chunks, `PARetriever` returns empty gracefully and the LLM falls back to its training-data knowledge. The agent stays functional, just with less context.

---

## 5. ERC-8004 (Sepolia Testnet)

### 5.1 Generate a wallet

```bash
python -c "from eth_account import Account; a = Account.create(); print(f'Address: {a.address}\nKey: {a.key.hex()}')"
```

### 5.2 Get test ETH

Use a Sepolia faucet:
- https://sepoliafaucet.com/
- https://www.alchemy.com/faucets/ethereum-sepolia

### 5.3 Configure

Add to `.env`:
```env
ERC8004_PRIVATE_KEY=0x_your_private_key
ERC8004_AGENT_URI=https://raw.githubusercontent.com/YOUR_USER/nogran.trader.agent/main/agent_registration.json
```

### 5.4 Register the agent

Registration happens automatically on the first `main.py` run. To register manually:

```bash
cd src && python -c "
from compliance.erc8004_onchain import ERC8004Hackathon
erc = ERC8004Hackathon(private_key='0x...', rpc_url='https://rpc.sepolia.org')
print(f'Connected: {erc.is_connected}')
agent_id = erc.register_agent(agent_wallet=erc.address, name='nogran.trader.agent', description='...', capabilities=[], agent_uri='')
print(f'Agent registered: id={agent_id}')
"
```

---

## 6. Running the agent

```bash
cd src && python main.py
```

The agent will:
1. Connect to the Kraken WebSocket (15m)
2. Compute features (EMA, ATR, ADX, swings, etc.)
3. Filter choppy markets (Market Quality Score)
4. Call the Strategy Engine (`python_llm` or `mock` heuristic)
5. Apply the AI Overlay (regime + confidence)
6. Compute the Risk Score (drawdown, R/R, Sharpe)
7. Compute the Decision Score (4 sub-scores)
8. Sign the TradeIntent (ERC-8004)
9. Execute via the Kraken CLI (paper trading)
10. Log everything in `logs/decisions/` (JSONL)

---

## 7. Technical notes

**Windows — DNS resolver:**
The project detects Windows and uses `ThreadedResolver` instead of `aiodns`.

**Defensive validation:**
`signal_parser.py` validates the LLM JSON via `LLMSignalSchema` (Pydantic strict bounds + directional coherence). Incoherent signals are coerced to AGUARDAR.

**Decision Score:**
Only executes trades with a score > 65/100. Hard veto if any sub-score < 20.

**Execution:**
All orders go through the Kraken CLI paper mode. Orders without a stop loss are forbidden by the code.

---

## 8. Repository structure

```
nogran.trader.agent/
├── src/
│   ├── main.py                        # Full pipeline
│   ├── domain/                        # Models and enums
│   ├── market/                        # WebSocket, Features, Pre-Filter
│   ├── strategy/                      # LLM Strategy + PA Retriever + Signal Parser + KB
│   ├── ai/                            # Regime Detector, Decision Scorer
│   ├── risk/                          # Position Sizer, Drawdown, Exposure
│   ├── execution/                     # Kraken CLI wrapper, Executor
│   ├── compliance/                    # ERC-8004, Decision Logger
│   ├── telemetry/                     # Trade Journal (planned)
│   └── infra/                         # Config, Indicators
├── data/probabilities/                # PA KB JSON (62 setups + 22 rules)
├── data/chunks/                       # RAG chunks (gitignored, sourced from the private dataset repo)
├── logs/decisions/                    # Audit trail JSONL
├── agent_registration.json            # ERC-8004 agent metadata
├── requirements.txt
├── .env.example
├── LICENSE                            # MIT
├── THIRD_PARTY.md                     # Third-party disclosure
├── README.md
├── SETUP.md
└── ARCHITECTURE.md
```
