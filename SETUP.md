# SETUP — nogran.trader.agent

> Guia de instalacao, configuracao e execucao.
> Para arquitetura e decisoes, veja [README.md](./README.md).
> Para detalhes tecnicos, veja [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## Quick start com Docker (recomendado para juizes)

Demo do dashboard em 1 comando, sem nenhuma dependencia local alem do Docker:

```bash
docker compose up
# abrir http://localhost:8501 (DEMO_MODE=1, dados sinteticos)
```

Stack completo (dashboard + agent):

```bash
export OPENAI_API_KEY=sk-...
docker compose --profile full up
```

Stop:
```bash
docker compose down                  # so o dashboard
docker compose --profile full down   # tudo
```

O Kraken CLI **nao** esta no container — para live paper trading, instale-o no host.

---

## Pre-requisitos (instalacao manual sem Docker)

- Python 3.10+
- Kraken CLI
- Chave de API da OpenAI
- (Opcional) Wallet Ethereum para ERC-8004

---

## 1. Instalacao

```bash
cd nogran.trader.agent

# Ambiente virtual
python -m venv venv

# Windows
.\venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

# Dependencias
pip install -r requirements.txt
```

---

## 2. Kraken CLI

O hackathon exige o Kraken CLI como execution layer.

### Instalacao

```bash
# Linux/Mac
curl --proto '=https' --tlsv1.2 -LsSf \
  https://github.com/krakenfx/kraken-cli/releases/latest/download/kraken-cli-installer.sh | sh

# Windows — baixar binario de:
# https://github.com/krakenfx/kraken-cli/releases
```

### Verificar instalacao

```bash
kraken --version
```

### Testar paper trading (sem API key)

```bash
kraken paper buy BTC/USD 0.001 -o json
kraken paper balance -o json
kraken paper pnl -o json
kraken paper reset -o json
```

### Market data (sem API key)

```bash
kraken market ticker BTC/USD -o json
kraken market ohlc BTC/USD --interval 1 -o json
```

---

## 3. Variaveis de Ambiente

Copie `.env.example` para `.env` e configure:

```env
# OpenAI — provider do strategy LLM (single-call structured output)
OPENAI_API_KEY=sk-...

# Kraken (opcional — paper trading nao precisa de API key)
KRAKEN_API_KEY=
KRAKEN_SECRET_KEY=

# ERC-8004 (Sepolia Testnet — hackathon shared contracts)
ERC8004_PRIVATE_KEY=0x...
ERC8004_AGENT_URI=https://raw.githubusercontent.com/nogran/nogran.trader.agent/main/agent_registration.json
SEPOLIA_RPC=https://rpc.sepolia.org
```

---

## 4. PA KB chunks (opcional, melhora qualidade do RAG)

A Nogran PA KB tem dois componentes:

- `data/probabilities/pa_probabilities.json` — 62 setups + 22 hard rules (no repo, ja incluido)
- `data/chunks/layer*.json` — passagens de referencia injetadas no prompt do LLM (gitignored — vem do repo dataset privado, copiar manualmente para ativar o RAG completo)

Sem os chunks, o `PARetriever` retorna empty gracefully e o LLM cai pro conhecimento de training data. O agente continua funcional, so com menos contexto.

---

## 5. ERC-8004 (Sepolia Testnet)

### 5.1 Gerar wallet

```bash
python -c "from eth_account import Account; a = Account.create(); print(f'Address: {a.address}\nKey: {a.key.hex()}')"
```

### 5.2 Obter ETH de teste

Use um faucet de Sepolia:
- https://sepoliafaucet.com/
- https://www.alchemy.com/faucets/ethereum-sepolia

### 5.3 Configurar

Adicione ao `.env`:
```env
ERC8004_PRIVATE_KEY=0x_sua_chave_privada
ERC8004_AGENT_URI=https://raw.githubusercontent.com/SEU_USER/nogran.trader.agent/main/agent_registration.json
```

### 5.4 Registrar agente

O registro acontece automaticamente na primeira execucao do `main.py`. Para registrar manualmente:

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

## 6. Executando o Agente

```bash
cd src && python main.py
```

O agente ira:
1. Conectar ao WebSocket da Kraken (15m)
2. Calcular features (EMA, ATR, ADX, swings, etc.)
3. Filtrar mercado choppy (Market Quality Score)
4. Chamar o Strategy Engine (python_llm ou mock heuristic)
5. Aplicar AI Overlay (regime + confidence)
6. Calcular Risk Score (drawdown, R/R, Sharpe)
7. Calcular Decision Score (4 sub-scores)
8. Assinar TradeIntent (ERC-8004)
9. Executar via Kraken CLI (paper trading)
10. Logar tudo em `logs/decisions/` (JSONL)

---

## 7. Notas Tecnicas

**Windows — DNS resolver:**
O projeto detecta Windows e usa `ThreadedResolver` em vez de `aiodns`.

**Validacao defensiva:**
O `signal_parser.py` valida o JSON do LLM via `LLMSignalSchema` (Pydantic strict bounds + coerencia direcional). Sinais incoerentes sao coerced para AGUARDAR.

**Decision Score:**
So executa trades com score > 65/100. Hard veto se qualquer sub-score < 20.

**Execution:**
Todas as ordens passam pelo Kraken CLI paper mode. Ordens sem stop loss sao proibidas pelo codigo.

---

## 8. Estrutura do Repositorio

```
nogran.trader.agent/
├── src/
│   ├── main.py                        # Pipeline completo
│   ├── domain/                        # Modelos e enums
│   ├── market/                        # WebSocket, Features, Pre-Filter
│   ├── strategy/                      # LLM Strategy + PA Retriever + Signal Parser + KB
│   ├── ai/                            # Regime Detector, Decision Scorer
│   ├── risk/                          # Position Sizer, Drawdown, Exposure
│   ├── execution/                     # Kraken CLI Wrapper, Executor
│   ├── compliance/                    # ERC-8004, Decision Logger
│   ├── telemetry/                     # Trade Journal (futuro)
│   └── infra/                         # Config, Indicators
├── data/probabilities/                # PA KB JSON (62 setups + 22 rules)
├── data/chunks/                       # Chunks RAG (gitignored, vem do dataset privado)
├── logs/decisions/                    # Audit trail JSONL
├── agent_registration.json            # ERC-8004 agent metadata
├── requirements.txt
├── .env.example
├── README.md
├── SETUP.md
└── ARCHITECTURE.md
```
