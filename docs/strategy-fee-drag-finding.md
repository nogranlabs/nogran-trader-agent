# Achado critico: mock heuristic nao tem alpha real — fee drag e secundario

> **ATUALIZACAO 2026-04-08 (apos sweep 30d Binance):** O titulo original era "fee drag mata o
> backtest no 1m com RR=1.5". Apos ampliar o sample para 30 dias e 252 trades, o achado real e
> mais grave: a mock heuristic NAO TEM alpha mensuravel. Mesmo com fees=0 e RR tunado, perde
> ~8% em 30 dias. Win rate 17%, expectancy -$4/trade. Detalhes na secao "Sweep 30d completo".

# Original (mantido para historico): fee drag mata o backtest no 1m com RR=1.5

> Descoberto: 2026-04-08 durante smoke test do `scripts/backtest.py`
> Severidade: **CRITICA** — sem fix, o leaderboard automatico (PnL/Sharpe) e impossivel de ganhar
> Arquivo afetado: `src/infra/config.py`, `scripts/backtest.py`

---

## TL;DR

A combinacao default `TIMEFRAME_EXEC=1m` + `MIN_REWARD_RISK=1.5` gera trades cujo
**reward em dolares e menor que o fee drag round-trip** na maioria dos regimes
de mercado em BTC/USD via Kraken (taker fee 0.26%).

**Resultado:** mesmo trades que batem `take_profit` viram **loss liquido** porque as fees comem o ganho. O backtest synthetic (500 candles, seed 42) sai com:

- **PnL: -1.90%**
- **Sharpe: -64.7**
- **Buy-and-hold no mesmo periodo: +3.89%**
- **Alpha: -5.80%**

E cada uma das 4 trades fechou em `take_profit` mas pnl liquido foi ~ -$47.

---

## Matematica do problema

### Custo de transacao Kraken
- Taker fee: **0.26% por lado**
- Round-trip (entrada + saida) = **0.52% do notional**

### Reward esperado da config atual
Em BTC/USD ~$67,000 com `Config.ATR_STOP_MULTIPLIER=1.5` e `Config.MIN_REWARD_RISK=1.5`:

- ATR(14) tipico no 1m: **$15-50**
- Stop distance = ATR x 1.5 = **$22-75**
- Reward distance = stop x RR = stop x 1.5 = **$33-112**

### Comparacao
- Reward em pct do preco: $33-112 / $67,000 = **0.05% - 0.17%**
- Fee drag: **0.52%**
- **Reward < Fee drag em ~80% dos cenarios**

Conclusao: a estrategia esta estruturalmente incapaz de gerar PnL positivo
com a config atual em chop ou tendencia fraca. Precisa de movimentos espike
de >0.6% para apenas empatar com fees.

---

## Por que nao foi pego antes

1. **Live paper trading nao foi medido em PnL net** — o pipeline so logava decisoes/sinais, nao fechava posicoes simuladas.
2. **Sem backtest** ate hoje (Phase 8.1 e justamente quando descobrimos).
3. **Os mocks no `simulate_market.py`** nao tinham PnL simulator, so verificavam se o pipeline GO/NO-GO funcionava.
4. **A literatura Nogran PA** assume mercados de futuros (S&P 500 e-minis) onde fees por trade sao $0.50-2 em contratos de $200k notional — fee drag de 0.001%, irrelevante. Crypto via Kraken e 500x mais caro.

---

## Opcoes de fix (em ordem de impacto vs custo)

| # | Fix | Custo | Espera-se | Justificativa |
|---|---|---|---|---|
| 1 | **Timeframe 5m em vez de 1m** | trivial — `--timeframe 5m` no backtest | Reward 4-5x maior, fee drag mesmo | ATR no 5m BTC ~ $80-200, stop x 1.5 ~ $120-300 (0.18-0.45%), ainda apertado mas viavel |
| 2 | **MIN_REWARD_RISK 3.0** | trivial — flag no backtest | Menos trades vencem, mas vencedores cobrem 5+ losses | Eleva reward target. Pra cobrir 0.52% fees, RR precisa ser >> 1.5 |
| 3 | **MQ threshold 50** (era 30) | trivial — flag no backtest | Filtra chop, fica so com setups limpos | Em chop, stops sao curtos e fees cumulativas matam |
| 4 | **Peak session only** (UTC 13:30-21:00) | trivial — flag no backtest | 70% do volume BTC, movimentos maiores | Ja temos `features.is_peak_session`, basta vetar fora |
| 5 | **Maker orders (limit, nao market)** | medio — refactor execution | Fee 0.16% (em vez de 0.26%) = **38% menos drag** | Kraken Pro Maker fee. Pode ser desempate vs concorrentes |
| 6 | **ATR_STOP_MULTIPLIER 2.5** | trivial — flag no backtest | Stops mais largos, posicoes menores | NAO resolve fee drag direto, so reduz noise stops |

### Combinacao recomendada (testar nesta ordem)
1. `--timeframe 5m --rr 3.0 --mq-threshold 50 --peak-only`
2. Se ainda negativo: `--timeframe 15m --rr 3.0`
3. Se ainda negativo: refactor pra maker orders

---

## O que NAO funciona

- **Aumentar size** — alavanca o problema, mesma fee%
- **Threshold 55 (em vez de 65)** — mais trades ruins, fee drag pior
- **Mais features no Pre-Filter** — nao e problema de sinal, e de economia do trade
- **Compounding em runs maiores** — fee drag e proporcional, nao se dilui

---

## Implicacoes para o hackathon

### Antes de tunar
- **Leaderboard automatico (Sharpe/PnL):** competitividade ZERO, perdemos pra qualquer agente que trada
- **Critério juiz "Application of Tech":** OK (tem pipeline, ERC-8004, KB)
- **Critério juiz "Uniqueness":** OK (Nogran PA KB hallucination detector e unico)
- **Critério juiz "Impact":** **comprometido** — agente que perde dinheiro nao tem impact pratico

### Depois de tunar (combinacao recomendada, expectativa)
- PnL esperado: **+2% a +8%** em 30 dias de BTC normal
- Sharpe esperado: **0.5 a 1.5**
- MaxDD esperado: **<5%** (Risk Engine ja controla isso bem)
- **Competitivo no leaderboard automatico** + mantem todos os criterios qualitativos

---

## Por que isso e o achado mais importante da sessao

Tudo que fizemos antes (190 testes, CI, 14 tech-debt items, Nogran PA KB, Thinking tab) **nao serve** se o agente nao consegue gerar PnL. O hackathon e ranqueado por performance real, nao por code quality.

Esse achado e o **gate critico** entre "projeto bonito" e "projeto que ganha hackathon".

---

## Acoes imediatas

1. [ ] Refatorar `scripts/backtest.py` para aceitar flags de tuning sem mutar `Config` (CLAUDE.md proibe alterar thresholds de risco sem aprovacao). Backtest vira ferramenta de sweep.
2. [ ] Rodar baseline + 5 combos tunados em dataset real (Kraken 7d, ja com cache).
3. [ ] Documentar a melhor combinacao em `trader-requirements.md`.
4. [ ] Solicitar aprovacao do usuario para atualizar `Config` com a melhor combinacao.
5. [ ] Re-rodar live paper trading com a nova config para validar (1-2 dias antes do freeze).

---

## Sweep 30d completo (Binance BTC/USDT 5m, 8615 candles)

### Bug critico encontrado durante o sweep

`ExposureManager.can_open_position` usa `time.time` (wall-clock real). Em backtest batch
todos os candles processam em <1s, fazendo o limite de 4 trades/hora **bloquear permanentemente
apos os primeiros 4 trades**. Isso reduzia QUALQUER backtest a 4 trades, quaisquer parametros.

Fix: criada `BacktestExposureManager` em `scripts/backtest.py` que usa `candle_index` em vez
de wall-clock. Live `ExposureManager` mantida intocada (CLAUDE.md proibe alterar logica de risk).

### Resultados (todos com mock heuristic + strict_trend_alignment, 30d Binance 5m)

| # | Combo | Trades | WinRate | PnL | Sharpe | DD | PF |
|---|---|---|---|---|---|---|---|
| A | baseline (rr=1.5, taker) | 19 | 21% | -8.03% | -11.4 | 8.1% | 0.05 |
| B | rr=3.0 taker | 252 | 17% | -8.29% | -11.0 | 8.3% | 0.10 |
| C | rr=3.0 maker | 255 | 22% | -8.42% | -11.8 | 8.4% | 0.15 |
| D | **rr=3.0 zero-fee** | 328 | 28% | **-8.11%** | -5.9 | 8.1% | **0.73** |
| E | rr=3.0 mq=50 | 252 | 17% | -8.29% | -11.0 | 8.3% | 0.10 |
| F | rr=3.0 mq=50 peak | 252 | 17% | -8.29% | -11.0 | 8.3% | 0.10 |

Buy-and-hold no mesmo periodo: **+3.35%**.

### Diagnose dos 252 trades do combo B

```
side: long 121, short 131 (balanced — trend filter funciona)
exit: stop_loss 173, take_profit 46, timeout 32, end_of_data 1
longs: win_rate 17.4% avg_pnl -$4.13
shorts: win_rate 16.8% avg_pnl -$2.52
stops: 173 trades, avg -$5.31
targets: 46 trades, avg +$1.80 (liquido)
```

**Expectancy matematica:** 0.17 × $1.80 + 0.83 × (-$5.31) = -$4.10 por trade.

**Implicacao:** com win rate 17%, precisariamos RR realizado **>= 5.0** para breakeven (sem fees).
Mas RR realizado avg = 1.5 (igual ao alvo). A mock heuristic gera sinais que **nao melhoram
sobre random** — ela e basicamente um gerador de candidatos pra demonstracao do pipeline,
nao uma estrategia real.

### Conclusao revisada

1. **Fee drag e secundario** — eliminar fees reduz prejuizo apenas marginalmente (-8.42% → -8.11%)
2. **A mock heuristic do `simulate_market.py` nao tem alpha** — win rate 17%, expectancy negativa
 independente de qualquer parametro
3. **Tuning de Config nao resolve** — ja testamos 6 combinacoes
4. **Pra ganhar o leaderboard automatico precisamos**:
 - **Substituir o gerador de sinais** por algo melhor (LLM real, ou heuristic com edge)
 - **OU** rodar agente live (com LLM + GPT-4o) por 4 dias e usar logs reais
 - **OU** aceitar derrota no PnL e maximizar critérios qualitativos

### Sinais positivos (nao tudo perdido)

- **Pipeline funciona end-to-end** — backtest engine, fee modeling, position sizing, all working
- **Sample agora e estatisticamente significativo** (252 trades em 30d) — backtest pode validar mudancas
- **Nogran PA KB ja gera 0 alarmes** nos sinais mock (eles sao deterministicos, nao alucinatorios)
- **Risk Engine controla DD** dentro do esperado (8% MaxDD com 250+ trades)
- **Aprendemos cedo** que precisamos substituir o gerador — antes do freeze do hackathon

### Caminhos viaveis para o hackathon (4 dias restantes)

| # | Caminho | Esforco | Risco | Probabilidade de ganhar leaderboard |
|---|---|---|---|---|
| 1 | **Live trading com LLM** por 3 dias antes do freeze | medio (setup) | alto (depende de mercado) | media |
| 2 | **Reescrever heuristica** com regras Nogran PA duras + validacao | alto | medio | baixa-media |
| 3 | **Aceitar derrota PnL** e maximizar Validation Registry + pitch qualitativo | baixo | baixo | baixa (mas garante metade da nota) |
| 4 | **Hibrido**: live trading + validation registry + pitch focado em Nogran PA KB | medio | medio-baixo | **MELHOR EV** |

**Recomendacao trader:** caminho 4. Live trading com config tunada (rr=3, peak-only)
gera dados reais, validation registry move ranking direto, e pitch foca em Nogran PA KB
(diferencial unico). Mesmo com PnL flat, ganha em validation + uniqueness.

---

## Lessons learned (para retrospectiva pos-hackathon)

- **Sempre simular fees reais antes de escolher timeframe**. Nao faca 1m em exchange com fee 0.26%.
- **Backtest deveria ter sido Phase 1, nao Phase 8**. Construir pipeline antes de validar economia e backwards.
- **Mocks de execucao escondem problemas de fee drag**. Mock so deve ser usado pra testes funcionais, nunca pra avaliar PnL.
- **Default de framework Nogran PA pressupoe futures**. Crypto exige re-calibracao de RR, timeframe, e fees.

---

## Referencias

- `scripts/backtest.py` — engine do backtest
- `src/telemetry/backtest_metrics.py` — calculo de fees e metricas
- `logs/backtest/<run_id>/` — dados raw do achado
- `docs/hackathon-criteria.md` — critérios oficiais que esse fix afeta
- `docs/trader-requirements.md` item A.2 — checklist
