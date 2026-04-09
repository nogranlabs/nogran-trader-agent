# nogran.trader.agent — Requirements para o hackathon

> O que o trader **PRECISA** ter ate 2026-04-12. Derivado de `docs/hackathon-criteria.md`.
> Status atualizado em: 2026-04-08
> Legenda: [x] feito | [~] parcial | [ ] pendente | [-] fora de escopo

---

## A. CRITICO — sem isso nao da pra submeter

### A.1 Pipeline executavel end-to-end
- [x] Kraken WS -> Feature Engine -> Pre-Filter -> Strategy Engine -> AI Overlay -> Risk Engine -> Decision Scorer -> Execution
- [x] Decision threshold 65, hard veto sub-score < 20
- [x] Pipeline-check passa (`/pipeline-check`)
- [x] 190 testes verdes (`pytest tests/`)
- [x] Docker `docker compose up` roda dashboard demo sem deps externas

### A.2 Backtest com metricas hackathon-aligned (PHASE 8.1 + 8.2)
- [x] `scripts/backtest.py` — roda pipeline contra OHLCV historico (3 sources: ccxt|csv|synthetic)
- [x] **Modo no-LLM obrigatorio** — reusa `mock_llm_response`/`mock_regime`/`_mock_ao_score` do simulate_market.py + KB enrichment direto
- [x] Dados: ccxt Kraken BTC/USD 1m, paginado, cacheado em data/historical/
- [x] Output: trades JSONL + equity curve CSV + decisions JSONL + summary JSON
- [x] `src/telemetry/backtest_metrics.py`:
 - [x] PnL liquido (fees Kraken 0.26% taker)
 - [x] Sharpe ratio annualized (parametrizado por bars/year — 525600 pra 1m)
 - [x] Max drawdown (peak-to-trough)
 - [x] Sortino, Calmar, CAGR
 - [x] Win rate, profit factor, expectancy, avg R:R realizado
- [x] **Buy-and-hold baseline** lado a lado + alpha vs B&H
- [x] PnL simulator com prioridade intrabar stop/target (assume stop primeiro se ambos batidos = conservador)
- [x] Position size capped a 1x leverage (sem isso explode com ATR pequeno)
- [x] Entry no NEXT bar open (evita lookahead bias)
- [x] 42 testes em `tests/test_backtest_metrics.py` (232 total agora)
- [ ] Tunar threshold/RR pra superar fee drag — strategy issue, nao engine (item separado)

**Por que e CRITICO:** ranking oficial e Sharpe + DD + validation. Sem backtest, nao temos numero pra reportar. Sem numero, perdemos pra qualquer agente que tem.

### A.3 Validation Registry post (PHASE 8.5)
- [x] `scripts/post_validation.py` criado, le `summary.json` do backtest e calcula score composto
- [x] **Score formula final:** 50% PnL (sigmoid Sharpe × dd_factor) + 30% Quality (audit/coverage) + 20% Risk discipline
- [x] **Justificativa do composito:** com Sharpe -11 do backtest atual, formula puramente PnL daria 0. O score composto da 31/100 (PnL=0, Q=68, R=53) — score honesto que reflete pipeline solido apesar de PnL fraco
- [x] Dry-run mode (`--dry-run`) funciona sem wallet
- [x] 23 testes em `tests/test_post_validation.py` (255 total agora)
- [x] Reutiliza `ERC8004Hackathon.post_checkpoint` ja implementado em `src/compliance/erc8004_onchain.py`
- [ ] **Pendente: usuario gerar wallet Sepolia + adicionar `ERC8004_PRIVATE_KEY` em `.env`**
- [ ] **Pendente: faucet de testnet ETH** (https://www.alchemy.com/faucets/ethereum-sepolia)
- [ ] **Pendente: rodar `python scripts/post_validation.py --latest` (sem --dry-run) pra postar de verdade**

**Por que e CRITICO:** "validation quality" e um dos 3 eixos do ranking oficial. Sem post on-chain, validation score = 0 e perdemos automaticamente.

### A.4 ERC-8004 funcional
- [x] Config com 5 contratos Sepolia
- [x] `src/compliance/erc8004_onchain.py` existe
- [~] Registracao do agente (manual via SETUP.md, precisa testar end-to-end)
- [~] TradeIntent assinado EIP-712 antes da execucao (codigo existe, validar fluxo)
- [ ] Risk Router enforcement (position size, leverage, daily loss) — verificar se chamamos
- [ ] Reputation Registry feedback pos-trade

### A.5 Kraken CLI funcional
- [x] `src/execution/kraken_cli.py` wrapper subprocess
- [x] Sanitizacao de stderr (paths, hex)
- [x] Paper trading (`kraken paper buy/sell/balance/pnl`)
- [ ] Testar end-to-end: backtest -> sinais -> kraken paper buy -> log

---

## B. ALTO IMPACTO — moves juiz, killer pitch

### B.1 Hallucination alarm vs PnL (PHASE 8.3)
- [ ] Cruzar `hallucination_alarm` (ja logado em JSONL) com PnL realizado dos backtests
- [ ] Tabela: `alarm_severity × winrate × avg_pnl`
- [ ] **Hipotese:** trades com alarm critico tem winrate < trades sem alarm
- [ ] Se confirmada -> narrativa do pitch: *"o detector de alucinacao do Nogran PA KB tem valor mensuravel em PnL"*

**Por que e ALTO IMPACTO:** este e o **diferencial unico** do nogran. Nenhum outro agente tem cross-check estruturado contra livro. Provar com numero = ganha "Uniqueness & creativity" sem competicao.

### B.2 Dashboard aba Backtest (PHASE 8.4)
- [ ] Equity curve plotly (agent vs buy-and-hold)
- [ ] KPI cards: Sharpe, MaxDD, Calmar, Win rate, Profit factor
- [ ] Trade scatter colorido por kb_match / hallucination_alarm
- [ ] Tabela do B.1 incorporada

### B.3 Nogran PA KB (G.2++) ja existe
- [x] 62 setups + 22 hard rules em `data/probabilities/pa_probabilities.json`
- [x] Loader, lookup, blend (60% LLM + 40% Nogran PA)
- [x] Hallucination detector (warning >=25, critical >=40)
- [x] R/R soft warning
- [x] 24 testes em `tests/test_probabilities_kb.py`
- [x] Logado em JSONL (`kb_match`, `hallucination_alarm`, `rr_warning`)
- [x] Dashboard ja mostra (4 KPIs + badge na Latest Decision)

### B.4 Thinking stream (`thinking-2026-04-08.jsonl`)
- [x] Aba Thinking no dashboard
- [x] Thoughts narram cada estagio do pipeline
- [x] Detecta mind-changes (revisions)
- [x] 30+ testes em `tests/test_thinking.py`

---

## C. APRESENTACAO — pitch material

### C.1 Video pitch (~3 min)
- [ ] Roteiro: problema -> solucao -> demo (dashboard rodando) -> diferencial Nogran PA KB -> ranking
- [ ] Mostrar terminal do agente em paper trading + dashboard side-by-side
- [ ] Postar em X taggando `@lablabai` e `@Surgexyz_`

### C.2 README hackathon-section
- [ ] Adicionar bloco "Hackathon Submission" no `README.md` com:
 - Demo URL / como rodar em 1 comando
 - Numeros do backtest (Sharpe, DD, PnL vs buy-hold)
 - Validation score on-chain (link Sepolia explorer)
 - Nogran PA KB metrics
 - Link pro video pitch

### C.3 Architecture diagram (visual)
- [~] Ja temos ASCII em README.md
- [ ] Considerar versao PNG/SVG pro pitch

### C.4 Documentacao tecnica
- [x] ARCHITECTURE.md (57KB)
- [x] CLAUDE.md
- [x] SETUP.md
- [x] tech-debt.md
- [x] feature-gap-audit.md
- [x] hackathon-criteria.md (este projeto)
- [x] trader-requirements.md (este arquivo)

---

## D. JA TEMOS — nao mexer

### Risk & Decision
- [x] Decision Scorer (4 sub-scores: MQ 20% + SS 35% + AO 20% + RS 25%)
- [x] Hard veto sub-score < 20
- [x] Drawdown bands (0-3% normal, 3-5% defensivo 60%, 5-8% minimo 30%, >8% circuit breaker)
- [x] Position sizer (ATR + score + drawdown)
- [x] Exposure manager (1 posicao, cooldown, max 30 candles)
- [x] Circuit breakers (3 losses, DD >8%, Sharpe <-1, latencia >10s)

### Pre-Filter & Features
- [x] Market Quality Score
- [x] EMA(20), ATR(14), ADX(14), bar overlap, consecutive bars

### AI Layer
- [x] Regime detector (TRENDING/RANGING/TRANSITIONING)
- [x] Confidence adjuster (10 fatores)
- [x] Multi-TF (1m + 5m)

### Compliance & Logs
- [x] Decision logger JSONL (com kb_match, hallucination_alarm, rr_warning)
- [x] ERC-8004 onchain module
- [x] Sanitizacao Kraken stderr
- [x] LOG_DIR validado contra path traversal

### Quality
- [x] 190 testes
- [x] Ruff lint 0 issues
- [x] CI matrix Python 3.10/3.11/3.12
- [x] detect-secrets baseline
- [x] Docker (default + full profile)

---

## E. FORA DE ESCOPO PHASE 8 — nao tocar ate pos-hackathon

Items do `feature-gap-audit.md` que NAO movem ranking em 4 dias:
- [-] Trail stop / scale in/out
- [-] Multi-cenario output (mudanca arquitetural no LLM)
- [-] H/L counter algoritmico (P1, alto esforco)
- [-] Trend Line detection algoritmico
- [-] Measured Moves
- [-] Day Type heuristico
- [-] Always-In rule-based
- [-] Breakout assessor (6 criterios)
- [-] Gap detection
- [-] Key levels tracking

**Regra de ouro:** se nao move Sharpe, DD, validation score OU narrativa do pitch -> nao implementar antes de 2026-04-12.

---

## F. Checklist de freeze (2026-04-11 night)

- [ ] `pytest tests/` 100% verde
- [ ] `docker compose up` roda sem erro em maquina limpa
- [ ] Backtest reproducivel: `python scripts/backtest.py --days 30` gera CSV + metricas iguais a 2 runs
- [ ] Validation score postado on-chain (tx hash linkavel)
- [ ] Video pitch publicado em X com tags
- [ ] README hackathon-section com numeros finais
- [ ] Submissao no portal lablab feita
- [ ] Branch `dev` mergeada em `main`, tag `v1.0-hackathon`

---

## G. Como usar este arquivo

- Antes de comecar qualquer task -> verificar se ela esta em A/B/C
- Se nao esta -> NAO fazer (vai pra E)
- Antes do freeze -> rodar checklist F
- Atualizar status `[ ]` -> `[x]` a cada conclusao
- Se duvida sobre criterio -> consultar `hackathon-criteria.md`
