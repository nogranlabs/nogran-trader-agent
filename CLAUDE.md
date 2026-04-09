# CLAUDE.md — nogran.trader.agent

## O que e este projeto

Agente autonomo de trading BTC/USD. Pipeline: Kraken WS → Feature Engine → Pre-Filter → Strategy Engine (python_llm com Nogran PA RAG, ou mock heuristic) → **Nogran PA KB enrichment** → AI Overlay → Risk Engine → Decision Scorer → ERC-8004 → Execution (Kraken CLI).

Trade executa SOMENTE se Decision Score > 65 e nenhum sub-score < 20.

## Stack

- Python 3.10+ (asyncio), ccxt.pro (WebSocket), Kraken CLI (paper trading)
- OpenAI GPT-4o (single-call structured output) — provider-agnostic via `LLMStrategy`
- Web3.py + eth-account: contratos Sepolia (ERC-8004 hackathon)
- Agent0 SDK (opcional, `pip install agent0-sdk==1.7.0`): camada de discovery OASF — `src/compliance/agent0_discovery.py`. Trading pipeline NAO depende dela.
- Dashboard: Streamlit + Plotly
- Testes: pytest

## Estrutura

```
src/main.py          # Pipeline principal (entry point)
src/ai/              # Regime detector, confidence adjuster, decision scorer
src/market/          # Candle buffer, feature engine, pre-filter (MQ score)
src/strategy/        # llm_strategy, llm_prompts, pa_retriever, signal_parser, probabilities_kb
src/risk/            # Drawdown controller, exposure manager, position sizer, metrics
src/execution/       # Executor + Kraken CLI wrapper (subprocess)
src/compliance/      # Decision logger (JSONL), ERC-8004 on-chain
src/domain/          # Enums e dataclasses (Candle, TradeSignal, DecisionScore)
src/infra/           # Config (env vars), indicators (SMA, EMA, ATR, ADX)
src/learning/        # Planejado, nao implementado (docstring no __init__.py)
src/telemetry/       # Planejado, nao implementado (docstring no __init__.py)
dashboard/           # Streamlit app (le logs/decisions/*.jsonl)
data/chunks/         # 6 JSONs (layer0..layer5) — gitignored, vem do dataset privado
data/probabilities/  # PA KB (62 setups + 22 hard rules) — usada pelo probabilities_kb
scripts/             # backtest.py, simulate_market.py, setup_erc8004.py
tests/               # pytest suite
```

## Como rodar

**Docker (rapido, recomendado):**
```bash
docker compose up                     # dashboard demo na porta 8501
docker compose --profile full up      # stack completo (dashboard + agent)
```

**Manual:**
```bash
pip install -r requirements.txt
cp .env.example .env  # preencher OPENAI_API_KEY (e ERC8004_PRIVATE_KEY se quiser on-chain)
cd src && python main.py
```

Dashboard: `cd dashboard && streamlit run app.py`

## Regras para o agente

- NAO alterar logica do Decision Scorer sem aprovacao (pesos: MQ 20%, SS 35%, AO 20%, RS 25%)
- NAO alterar thresholds de risco (Config: RISK_PER_TRADE=1%, DECISION_THRESHOLD=65, MIN_REWARD_RISK=1.5)
- NAO alterar a Nogran PA KB (`data/probabilities/pa_probabilities.json`) sem reextrair do dataset privado e fazer cross-check
- NAO hardcodar credenciais — tudo via .env e Config class
- Fatos para o LLM sao escritos em portugues (fact_builder.py)
- Testes devem rodar com: `pytest tests/`
- Sem lint configurado ainda (ver `docs/tech-debt.md`)
- **NUNCA rodar API paga (OpenAI live) sem confirmacao explicita do usuario** — sempre passar primeiro pelo backtest mock

## Nogran PA KB & Hallucination Detector

Camada de enriquecimento entre o Strategy Engine e o Decision Scorer. NAO altera o scorer (regra acima respeitada).

- `data/probabilities/pa_probabilities.json`: 62 setups + 22 hard rules curados in-house. O conteudo verbatim do material original fica no repo privado nogran-trader-dataset.
- `src/strategy/probabilities_kb.py`: loader, lookup direction-aware, blend (LLM 60% + PA 40%), hallucination detector (warning >=25, critical >=40), R/R soft warning.
- `src/strategy/signal_parser.py`: `calculate_strategy_score_with_kb()` ao lado de `calculate_strategy_score()`.
- `src/main.py`: Stage 4 usa a versao enriquecida e propaga `kb_match`/`hallucination_alarm`/`rr_warning` para o decision_logger.
- `src/compliance/decision_logger.py`: 3 campos opcionais novos no JSONL.
- `dashboard/app.py`: 4 KPIs novos (KB Match Rate, KB Hits, Alarms, Critical) + badge na Latest Decision card + sample data com KB.
- 24 testes em `tests/test_probabilities_kb.py` (loader, lookup, blend, alarm, R/R, backward compat).
- Detalhes completos: ARCHITECTURE.md secao 9.

## Documentacao existente

- `README.md` — visao geral e arquitetura resumida
- `ARCHITECTURE.md` — documentacao tecnica detalhada
- `SETUP.md` — guia de instalacao e configuracao
- `docs/tech-debt.md` — debitos tecnicos mapeados

## Dependencias entre modulos

main.py importa todos os modulos. Ordem do pipeline:
market → strategy (LLM via `llm_strategy.py`) → ai → risk → compliance → execution

Execution depende de: Kraken CLI binary no PATH
LLM depende de: OPENAI_API_KEY no .env
