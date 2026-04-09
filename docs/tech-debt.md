# Tech Debt — nogran.trader.agent

Debitos tecnicos mapeados em 2026-04-05 (diagnostico 01 + auditoria seguranca 03).
Prioridade: CRITICO > ALTO > MEDIO > BAIXO.

---

## CRITICO

### ExposureManager usa wall-clock (`time.time`) em vez de tempo simulado
- `src/risk/exposure_manager.py:29` — `now = time.time` no `can_open_position`
- **Bug em backtest:** todos os 8615 candles processam em <1s, fazendo `trades_this_hour` acumular 4 trades em segundos reais. Apos isso, o limite hourly bloqueia **permanente** e o backtest gera so 4 trades qualquer dataset
- **Bug latente em live:** se o agent ficar pausado/dormindo entre trades, `trades_this_hour` carrega ts antigos. Se varios trades acontecerem em rapida sucessao apos pausa longa, comportamento e indefinido. Edge case raro mas existe.
- Workaround atual: `scripts/backtest.py` define `BacktestExposureManager` que usa `candle_index` no lugar de wall-clock. Mantem mesma API publica.
- **Fix definitivo pendente:** refatorar `ExposureManager` pra aceitar `now_provider: Callable[[], float] = time.time` na construcao. Live passa default, backtest passa lambda que retorna `candle.timestamp/1000`. NAO fazer antes do hackathon (risco de mexer em codigo de risk).
- Descoberto: 2026-04-08 durante sweep do backtest. Detalhes em `docs/strategy-fee-drag-finding.md` secao "Sweep 30d completo"

### ~~Dependencias sem version pinning~~ — RESOLVIDO (2026-04-08)
- ~~`requirements.txt` lista 8 pacotes sem versao~~
- Resolvido: `requirements.lock` adicionado (87 pacotes pinados via `pip freeze`). `requirements.txt` reescrito com pins explicitos para os 7 deps diretos. ERC-8004 deps (web3, eth-account) marcados como opcionais.
- Pendente: `pip audit` automatizado e verificacao de CVEs em CI.
- Pendente: `dashboard/requirements.txt` ainda usa `>=` sem upper bound.

### ~~Sem validacao de schema na resposta do LLM~~ — RESOLVIDO (2026-04-08)
- ~~`src/strategy/signal_parser.py:20-71` — parseia JSON do LLM sem schema validation~~
- Resolvido: `LLMSignalSchema` (Pydantic v2) valida bounds (precos 0-1e7, confianca 0-100, strings <=4000 chars), checa coerencia direcional (BUY/SELL com stop/target do lado certo), e ignora extra fields silenciosamente. 29 testes em `tests/test_signal_parser.py`. Sinais incoerentes sao coerced para AGUARDAR ao inves de quebrar o pipeline.

---

## ALTO

### ~~Testes insuficientes~~ — RESOLVIDO (2026-04-08)
- Estado inicial: 1 teste (test_agent.py com resposta hardcoded)
- Adicionado nesta sessao:
 - `test_decision_scorer.py` (12 testes — Decision Score weights, threshold, hard veto)
 - `test_probabilities_kb.py` (24 testes — Nogran PA KB loader, lookup, blend, hallucination detector)
 - `test_signal_parser.py` (29 testes — Pydantic schema validation)
 - `test_kraken_sanitize.py` (10 testes — info disclosure mitigation)
 - `test_indicators.py` (37 testes — SMA, EMA, ATR, ADX, bar overlap, consecutive)
 - `test_risk.py` (41 testes — DrawdownController, ExposureManager, PositionSizer, RiskMetrics)
- Total atual: **154 testes passando** (1 -> 154, +153)
- Cobertura agora atinge: Decision Scorer, Strategy Score, Nogran PA KB, signal validation, indicators, risk engine, sanitization
- Pendente: tests de integracao end-to-end com LLM real (so demo)

### ~~Sem CI/CD~~ — RESOLVIDO (2026-04-08)
- ~~Nenhum GitHub Actions, nenhum pipeline de build/test~~
- Resolvido: `.github/workflows/ci.yml` adicionado. Roda em push/PR para `dev`/`main` em Python 3.10/3.11/3.12 (matriz). Steps: ruff lint, pytest (75 testes), detect-secrets vs baseline. Deps minimas instaladas (sem ccxt/web3/streamlit).
- Pendente: deploy automatizado (n/a para hackathon).

### ~~Sem lint/formatacao~~ — RESOLVIDO (2026-04-08)
- ~~Nenhum ruff, flake8, black, isort, mypy configurado~~
- Resolvido: `pyproject.toml` com config ruff (selecao conservadora: E4/E7/E9/F/I/B/UP/W605, line-length 120). 323 issues iniciais reduzidas a 0 (42 auto-fix + 7 manuais + ajuste de 5 ignorados intencionalmente para nao reformat-massive a base). Lint roda em CI a cada push/PR.
- Pendente: black/mypy nao foram adicionados (ruff cobre o suficiente para hackathon).

### ~~Sem containerizacao~~ — RESOLVIDO (2026-04-08)
- ~~Nenhum Dockerfile ou docker-compose~~
- Resolvido: `Dockerfile` (python:3.12-slim, non-root user, entrypoint dispatcher) + `docker-compose.yml` com 2 perfis:
 - **default:** so o dashboard em modo demo (1 comando, zero deps externas) — `docker compose up`
 - **full:** dashboard + agent + postgres+pgvector + LLM — `docker compose --profile full up`
- Kraken CLI nao esta no container (out-of-scope para a imagem demo).
- `.dockerignore` exclui venv, tests, .git, trader refs/, etc. para imagem lean.

### ~~Sem pre-commit hooks para deteccao de segredos~~ — RESOLVIDO (2026-04-08)
- ~~Nenhum git-secrets, truffleHog, detect-secrets ou pre-commit hook configurado~~
- Resolvido: `detect-secrets` instalado, `.secrets.baseline` gerado (2 hits, ambos placeholders `usuario:senha` em templates — auditados como falsos positivos). `.pre-commit-config.yaml` adicionado como opt-in. Para ativar: `pip install pre-commit detect-secrets && pre-commit install`.
- Pendente: rotacionar Kraken API keys se repo foi compartilhado em algum momento (boa pratica geral, nao um achado).

### ~~unsafe_allow_html no dashboard com dados dinamicos~~ — RESOLVIDO (2026-04-08)
- ~~`dashboard/app.py` usa `unsafe_allow_html=True` em 13 locais com risco em 2~~
- Auditado: 13 ocorrencias, 11 com conteudo estatico (CSS, layer cards, footer, badges com enums controlados) — sem risco. As 2 com risco real foram corrigidas:
 - **KB citation card** (G.2++): refatorado para nao usar `unsafe_allow_html`. Renderiza via `st.markdown` nativo + `st.caption` — caracteres especiais em `kb_id`/`kb_cite` sao escapados pelo Streamlit.
 - **Signed intent row**: `sig_short` e `row["action"]` (originados do JSONL) agora passam por `markupsafe.escape` antes da interpolacao.

### ~~Stack traces expostos em logs~~ — RESOLVIDO (2026-04-08)
- ~~`src/main.py:512` — `logger.error(..., exc_info=True)`~~
- Resolvido: `exc_info=True` agora condicional em `Config.DEBUG` (env var `AGENT_DEBUG`). Default OFF — prod logs apenas tipo do erro + mensagem, sem paths nem stack frames. Para reativar em troubleshooting: `AGENT_DEBUG=1 python main.py`.
- `src/compliance/erc8004_onchain.py:292` — referencia ja nao existe no codigo atual.

---

## MEDIO

### ~~Modulos vazios~~ — RESOLVIDO (2026-04-08)
- ~~`src/learning/__init__.py` e `src/telemetry/__init__.py` vazios~~
- Resolvido: ambos agora tem docstring explicitando "PLANNED, NOT IMPLEMENTED" + descricao do design e ponteiro para `ARCHITECTURE.md` secao 4. O codigo continua nao existindo, mas qualquer dev abrindo o arquivo entende o status.

### ~~Codigo legado nao removido~~ — RESOLVIDO (2026-04-08)
- ~~`src/_legacy_v1/` contem 4 arquivos (brain.py, execution.py, ingest_data.py, market_data.py)~~
- Resolvido: pasta inteira removida. Nenhum import era feito. v3 e a unica versao agora.

### Mensagens de commit genericas
- Todos os 9 commits tem mensagem "update" ou "create project"
- Sem branches, tags, ou PRs
- **Impacto:** impossivel entender historico de mudancas

### ~~stderr do Kraken CLI exposto sem sanitizacao~~ — RESOLVIDO (2026-04-08)
- ~~`src/execution/kraken_cli.py:45-48` — stderr do subprocess repassado direto para error messages~~
- Resolvido: nova funcao `_sanitize_stderr` trunca para 300 chars, redacta paths Windows (`C:\...`), POSIX home (`/home/...`, `/Users/...`) e hex strings de 40+ chars (potenciais keys/sigs/hashes). 10 testes em `tests/test_kraken_sanitize.py`.

### ~~LOG_DIR do dashboard configuravel sem validacao~~ — RESOLVIDO (2026-04-08)
- ~~`dashboard/app.py:28-29` — `DECISIONS_LOG_DIR` via env var sem checagem de path traversal~~
- Resolvido: path expandido + resolvido + validado para ficar dentro do projeto root ou home do usuario. Caminho suspeito (ex: `..\..\Windows\System32`) cai para o default em vez de honrar o env var.

### Exposicao de arquitetura se repo publico
- `CLAUDE.md` e `ARCHITECTURE.md` (57KB) descrevem pipeline, pesos, thresholds
- Se repo for publico, atacante sabe como o agente decide
- **Decisao pendente:** se publico, adicionar `CLAUDE.md` e `.claude/` ao `.gitignore`

---

## BAIXO

### ~~Dashboard sem requirements isolado no root~~ — RESOLVIDO (2026-04-08)
- ~~`dashboard/requirements.txt` existe mas nao e referenciado no setup~~
- Resolvido: `dashboard/requirements.txt` agora pinado para versoes da `requirements.lock` e instalado pelo Dockerfile no mesmo `pip install`. Setup local manual continua funcionando via `pip install -r dashboard/requirements.txt`.

### Config com OPENAI_API_KEY nao usada diretamente
- `Config.OPENAI_API_KEY` e carregada mas nunca usada no Python — OpenAI e chamada pelo LLM
- **Impacto:** confusao sobre onde a key e usada

### Sem tipagem forte
- Type hints parciais — sem mypy ou pyright configurado
- **Impacto:** bugs de tipo so aparecem em runtime

### File handle nao fechado em prepare_knowledge.py
- `src/prepare_knowledge.py:~330` — `PyPDF2.PdfReader(open(...))` sem context manager
- **Impacto:** resource leak se script rodar multiplas vezes

---

## RESOLVIDOS

### .gitignore incompleto — RESOLVIDO (2026-04-05)
- Corrigido: `__pycache__/` global, `*.pyc`, `.env.local`, `*.egg-info/`, `logs/`

## Dados pessoais / LGPD — N/A
- Nenhum dado pessoal coletado ou armazenado
- Agente autonomo sem interacao com usuarios finais
- Logs contem apenas dados de mercado e scores
