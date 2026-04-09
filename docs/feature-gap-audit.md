# Auditoria: Especificacao Nogran PA v2 vs Implementacao Atual

> Realizada em 2026-04-05 | 56 itens mapeados
> Resultado: 1 completo (2%), 14 parciais (25%), 41 ausentes (73%)

---

## Resumo Quantitativo

| Categoria | OK | Parcial | Ausente | Total |
|---|---|---|---|---|
| 12.1 Funcionalidades Core | 1 | 3 | 2 | 6 |
| 12.2 Motor de Probabilidades | 0 | 1 | 3 | 4 |
| 12.3 Cenarios | 0 | 2 | 2 | 4 |
| 12.4 Padroes L1 (Trends) | 0 | 4 | 3 | 7 |
| 12.4 Padroes L2 (Trading Ranges) | 0 | 1 | 9 | 10 |
| 12.4 Padroes L3 (Reversals) | 0 | 0 | 9 | 9 |
| 12.5 Gestao de Ordens | 0 | 1 | 4 | 5 |
| 12.6 Filtros de Nao-Operacao | 0 | 1 | 3 | 4 |
| 12.7 Frontend | 0 | 1 | 6 | 7 |
| **TOTAL** | **1** | **14** | **41** | **56** |

---

## 12.1 Funcionalidades Core

| Item | Status | Onde esta | O que falta |
|---|---|---|---|
| EMA 20 | OK | `src/infra/indicators.py` calcula EMA(20). `src/market/feature_engine.py` expoe `ema_20` e `price_vs_ema` (% distancia) | — |
| Always-In Detection | Parcial | Enum `AlwaysIn` em `src/domain/enums.py` (SEMPRE_COMPRADO/SEMPRE_VENDIDO/NEUTRO). Valor parseado do LLM em `src/strategy/signal_parser.py` | Deteccao 100% delegada ao LLM/Strategy Engine. Sem heuristica rule-based no Python (ex: ADX + momentum + consecutive bars) |
| Day Type Classification | Parcial | Enum `DayType` em `src/domain/enums.py` com 6 tipos. Classificacao via LLM em `signal_parser.py` | Faltam tipos: `small_pullback_trend`, `trading_range_day`, `barbwire_narrow_range`. Sem heuristica local para complementar/validar LLM |
| Bar Classification (trend bar vs doji) | Parcial | `src/domain/models.py` Candle calcula `body_pct`, `upper_tail_pct`, `lower_tail_pct`, `is_bullish` | Nao classifica explicitamente como "trend bar" vs "doji". Falta threshold (ex: body_pct < 33% = doji). Delegado ao LLM |
| H/L Counting (H1-H4, L1-L4) | Ausente | Referenciado nos chunks RAG (`bar_counting_h1_h2_l1_l2` em `data/chunks/`) | Sem codigo Python. LLM infere do texto sem validacao local. Fundamental para setups Nogran PA |
| Trend Line Detection | Ausente | Conceito nos chunks RAG (Cap.13 layer3) | Sem algoritmo de deteccao. Sem tracking de breaks de LT. Necessario para Major Trend Reversal e counter-trend guard |

---

## 12.2 Motor de Probabilidades

| Item | Status | Onde esta | O que falta |
|---|---|---|---|
| Trader's Equation Calculator | Ausente | — | Nao existe `P(win) x Reward vs P(loss) x Risk`. Sistema usa score ponderado 0-100. RR validado (>=1.5) mas sem calculo de expected value |
| Directional Probability | Ausente | — | Sem estimativa de probabilidade direcional (ex: "60% bull para X ticks"). Regime detector eh binario (trending/ranging/transitioning), nao probabilistico |
| Probability Modifiers | Parcial | `src/ai/confidence_adjuster.py` modifica confianca com +/- pontos (regime +10/-15, volume +5/-10, ATR +5/-10, multi-TF +10/-15, revenge -10, session -10) | Sao ajustes aditivos a um score, nao multiplicadores de probabilidade real. Nao mapeiam para P(sucesso) |
| Probabilidade por contexto | Ausente | — | Tabela da Secao 2.3 da spec (60-70% pullback em tendencia, 20% breakout em range, etc.) nao codificada em nenhum lugar |

---

## 12.3 Cenarios

| Item | Status | Onde esta | O que falta |
|---|---|---|---|
| Multi-scenario output | Ausente | — | Sistema gera 1 sinal (COMPRA/VENDA/AGUARDAR) por candle. Spec exige 2-3 cenarios com probabilidades por barra |
| Trap detection | Ausente | — | Sem identificacao de "quem esta sendo preso". LLM pode mencionar no `reasoning` mas sem campo estruturado no TradeSignal |
| Best trade selection | Parcial | `src/ai/decision_scorer.py` faz GO/NO-GO no unico sinal | Nao compara multiplos cenarios. Seleciona se o unico sinal passa o threshold, nao o melhor entre alternativas |
| Entry/Stop/Target precision | Parcial | `src/domain/models.py` TradeSignal tem `entry_price`, `stop_loss`, `take_profit` vindos do LLM | Precos absolutos, nao condicionais Nogran PA ("1 tick acima da high da bar X"). Sem validacao de precisao |

---

## 12.4 Padroes Implementados — Livro 1 (Trends)

| Padrao | Status | Onde esta | O que falta |
|---|---|---|---|
| Spike and Channel | RAG only | Chunks layer1 Cap.21 (241KB). Sem deteccao algoritmica | Detectar spike (N barras trend consecutivas, baixa sobreposicao) e transicao para channel (sobreposicao aumenta) |
| Trend From the Open / Small Pullback | RAG only | `DayType.TREND_FROM_OPEN` enum existe. Classificacao via LLM | Heuristica: abertura = extremo do dia + spike forte sem pullback significativo |
| Trending Trading Range | RAG only | `DayType.TRENDING_TRADING_RANGE` enum existe. LLM classifica | Detectar lateralidades conectadas por breakouts |
| Signs of Strength (lista completa) | RAG only | Cap.19 nos chunks layer1 | Spec lista 20+ sinais. Chunks cobrem ~10. Nenhum codificado como checklist algoritmica |
| Micro Channels | Ausente | — | Nem nos chunks RAG nem no codigo |
| Two Legs | RAG only | Conceito nos chunks layer2 | Sem deteccao automatica de "2 pernas" em pullbacks |
| Stairs / Broad Channel | Ausente | — | Nao implementado em nenhuma camada |

---

## 12.4 Padroes Implementados — Livro 2 (Trading Ranges)

| Padrao | Status | Onde esta | O que falta |
|---|---|---|---|
| Trading Range detection | Parcial | `src/ai/regime_detector.py` detecta RANGING (ADX<20 + overlap>0.6) | Simplificado vs spec. Nao identifica limites do range (high/low), duracao, ou "meio do range" |
| Tight TR / Barbwire detection | Ausente | `bar_overlap_ratio` existe em feature_engine mas sem threshold especifico | Spec: barbwire = tight TR com dojis + caudas grandes + sobreposicao. Nao detectado. "NAO OPERE" nao implementado como veto |
| Breakout assessment (real vs falso) | Ausente | — | Spec define 6 criterios (barras consecutivas, gap com EMA, follow-through, direcao HTF, pullback <50%, sem caudas). Nenhum codificado |
| Breakout Mode | Ausente | — | Conceito de "prestes a romper em qualquer direcao" nao implementado |
| Failed Breakouts | Ausente | — | Sem deteccao algoritmica de breakouts que falham e revertem |
| Measured Moves | Ausente | — | Sem calculo: spike height -> channel target, range height -> breakout target |
| Support/Resistance magnets | Ausente | — | Sem tracking de key levels (yesterday H/L, prior swing H/L, round numbers) |
| Pullback classification (5 tipos) | Ausente | — | Spec: bar pullback, minor TL, EMA, MA gap, major TL. Nenhum classificado |
| Wedge pullbacks | Ausente | — | Sem deteccao de 3 pushes em pullback |
| Double Top/Bottom flags | Ausente | — | Sem deteccao de DT/DB como continuation flags |

---

## 12.4 Padroes Implementados — Livro 3 (Reversals)

| Padrao | Status | Onde esta | O que falta |
|---|---|---|---|
| Major Trend Reversal (3 requisitos) | Ausente | — | Os 3 requisitos (LT break + teste do extremo + falha no teste) nao sao verificados. Requisito mais importante para reversoes |
| Climactic Reversals | Ausente | — | Sem deteccao de climax (barra excessivamente grande seguida de spike oposto) |
| Wedge reversals (3 pushes) | Ausente | — | Sem contagem de pushes. Wedge eh um dos padroes mais confiaveis |
| Expanding Triangles | Ausente | — | 3 pushes com volatilidade crescente — nao detectado |
| Final Flags | Ausente | — | Ultima flag antes da reversao — sutil mas poderosa |
| Double Top/Bottom Pullbacks | Ausente | — | DT seguido de pullback -> lower high = short. Nao implementado |
| Failed breakout reversals | Ausente | — | Failed failure -> breakout pullback. "Um dos melhores trades" segundo Nogran PA |
| Opening Patterns (Caps.17-20) | Ausente | — | Sem analise de primeira hora, relacao com ontem, gap openings |
| Gap Openings | Ausente | — | Sem deteccao de gaps entre dias ou entre barras |

---

## 12.5 Gestao de Ordens

| Item | Status | Onde esta | O que falta |
|---|---|---|---|
| Scalp vs Swing decision | Ausente | — | Todas posicoes tratadas igualmente. Max hold 30 candles. Spec: scalp=1-3pts/70%+ WR, swing=4+pts/40-60% WR |
| Stop placement | Parcial | Stop vem do LLM no TradeSignal. `src/risk/position_sizer.py` usa ATR x 1.5 como fallback | Sem logica "1 tick alem da signal bar ou entry bar (o que for maior protecao)". Sem breakeven stop |
| Trail stop | Ausente | Stop eh estatico. Colocado como limit order na entrada via `src/execution/executor.py` e nunca ajustado | Spec: trail abaixo do higher low mais recente (bull), mover para breakeven apos 1x risk de lucro |
| Scale in/out | Ausente | Posicao atomica em `executor.py`. Entrada e saida completas | Spec: scale out parcial no primeiro alvo (1x risk), resto com trail. Scale in nos pullbacks em trends fortes |
| Profit target (measured move) | Ausente | Target vem do LLM. Sem calculo local | Spec: measured moves baseados em spike height, gap, range height |

---

## 12.6 Filtros de Nao-Operacao

| Item | Status | Onde esta | O que falta |
|---|---|---|---|
| Barbwire/Tight TR bloqueia | Parcial | `src/market/pre_filter.py`: `bar_overlap_ratio > 0.7` penaliza MQ em -40pts | NAO bloqueia explicitamente. Pode passar se outros scores altos. Spec diz "NAO OPERE" = deveria ser hard veto |
| Meio do range + meio do dia | Ausente | — | Sem conceito de "meio do range". Session modes existem mas nao detectam "pior hora para operar" |
| Counter-trend sem LT break | Ausente | — | Sem tracking de trend lines. Always-in alignment da +/-5 pts no SS mas sem veto. Spec: "NUNCA opere contra tendencia sem quebra de LT significativa" |
| Trader's Equation negativa bloqueia | Ausente | — | RR < 1.5 retorna risk_score=0 (efetivamente veta). Mas nao eh P(win)xR vs P(loss)xRisk — eh apenas ratio minimo |

---

## 12.7 Frontend (Dashboard Streamlit)

| Item | Status | Onde esta | O que falta |
|---|---|---|---|
| Painel de cenarios com probabilidades | Ausente | `dashboard/app.py` mostra 1 decisao | Multi-cenario com probabilidades (formato da Secao 11.1 da spec) |
| Probabilidade direcional (visual) | Ausente | — | Barras Bull/Bear/Flat com percentuais (Secao 11.3 da spec) |
| Always-in visivel | Parcial | No TradeSignal, visivel na tab Trade Review | Sem destaque principal no dashboard. Deveria ser prominente |
| Contadores de estado (12 campos) | Ausente | Apenas `consecutive_bull/bear` | Spec: bars_since_signal, legs, pushes, bars_since_ema_touch, daily_range, distance_from_ema, last_tl_break, etc. |
| Key levels no grafico | Ausente | Grafico candlestick existe sem marcacoes | Spec: yesterday H/L, today open, measured moves, trend lines |
| Trap alerts | Ausente | — | Quem esta sendo preso, por que, onde estao stops sendo cacados |
| Qualidade setup A+/B/C/D | Ausente | Score numerico 0-100 | Spec: classificacao qualitativa visivel (A+ = best trade, D = nao opere) |

---

## Divergencias Criticas entre Spec e Implementacao

### 1. Arquitetura Fundamentalmente Diferente
A spec pressupoe um **motor de analise rule-based** que gera cenarios com probabilidades. A implementacao eh **LLM-first**: o Strategy Engine faz a analise Nogran PA e retorna 1 sinal. O Python valida/pontua mas nao analisa price action.

**Impacto:** A maioria dos 41 itens ausentes nao pode ser resolvida com patches — requer uma camada nova de analise algoritmica.

### 2. Single Signal vs Multi-Scenario
Spec exige 2-3 cenarios por barra com probabilidades. Sistema gera 1 sinal binario (COMPRA/VENDA/AGUARDAR). Mudanca arquitetural necessaria no Strategy Engine e no pipeline.

### 3. Probabilidades Ausentes
Nenhuma probabilidade explicita. O score 0-100 eh um proxy de confianca, nao mapeavel para a Trader's Equation `P(win) x Reward vs P(loss) x Risk`.

### 4. Gestao de Posicao Estatica
Stop fixo, sem trailing, sem scale in/out, sem parciais. A spec exige trail stops, breakeven stops, scaling, e decisao scalp vs swing.

### 5. Barbwire Nao Bloqueia (Violacao da Spec)
Spec: "NAO OPERE" em barbwire/tight TR. Implementacao: penaliza MQ mas nao veta. Trade pode executar em barbwire se outros scores forem altos.

### 6. Counter-Trend Sem Guarda (Violacao da Spec)
Spec: "NUNCA opere contra tendencia sem quebra de LT significativa". Implementacao: sem tracking de trend lines, logo impossivel validar. Always-in alignment eh bonus/penalidade leve (+/-5 pts), nao veto.

---

## Tabela de Probabilidades Nogran PA (Referencia para Implementacao)

Fonte: trilogia Nogran PA (30+ anos experiencia). Heuristicas, nao backtesting estatistico.

### Tendencia
| Situacao | P(sucesso) | Notas |
|---|---|---|
| Pullback para EMA em tendencia forte (H2/L2) | ~60-70% | Melhor setup with-trend |
| Segunda entrada (second signal) na tendencia | ~60%+ | Mais confiavel que a primeira |
| Scalp na direcao do spike durante spike | ~60-70% | Probabilidade alta mas breve |
| Entrada no canal (with-trend) | ~55-60% | Canal eh mais fraco que spike |
| Trade contra tendencia sem quebra de LT | ~20-30% | Quase sempre perde |

### Lateralidade
| Situacao | P(sucesso) | Notas |
|---|---|---|
| Fade no extremo do range (comprar baixo/vender alto) | ~60% | Principal estrategia em range |
| Breakout do range ser real | ~20% | 80% falham |
| Fade de breakout falso | ~60-70% | Setup muito confiavel |
| Trade no meio do range | ~50% | Probabilidade direcional equilibrada. Evitar |

### Reversao
| Situacao | P(sucesso) | Notas |
|---|---|---|
| Reversao com LT break + teste do extremo | ~40-60% | Precisa dos 3 requisitos |
| Primeira tentativa de reversao funcionar | ~20% | 80% falham. Espere segunda entrada |
| Segunda entrada de reversao (second signal) | ~55-60% | Mais confiavel |
| Opening reversal atingir swing (4+ pts) | ~40% | Mas reward:risk compensa (2:1+) |
| Wedge reversal (3 pushes) | ~50-60% | Depende do contexto |

### Breakout
| Situacao | P(sucesso) | Notas |
|---|---|---|
| Spike forte de 3+ barras ter measured move | ~60% | Probabilidade direcional durante spike |
| Breakout com gap da EMA ter follow-through | ~60%+ | Moving average gap = forca |
| Breakout pullback (failed failure) | ~60%+ | Um dos melhores trades |
| Five-tick failure gerar scalp oposto | ~60% | Scalpers presos saindo |

### Relacao R:R Minima por Win Rate
| Win Rate | R:R minimo para ser lucrativo |
|---|---|
| 80% | 1:4 (risco 4x reward) — scalps extremos |
| 70% | 1:2 (risco 2x reward) — scalps normais |
| 60% | 1:1 (risco = reward) — swing entries |
| 50% | Reward > Risk obrigatorio |
| 40% | Reward >= 2x Risk — reversoes e swings |

---

## Priorizacao de Implementacao

### P0 — Alto Impacto, Esforco Baixo/Medio (implementar primeiro)

| # | Item | Justificativa | Esforco | Arquivo alvo |
|---|---|---|---|---|
| 1 | Barbwire/Tight TR hard veto | Evita perdas em condicoes que spec diz "NAO OPERE". Ja tem `bar_overlap_ratio` — falta threshold + veto | Baixo | `src/market/pre_filter.py` |
| 2 | Bar classification (trend bar vs doji) | Base para tudo. Threshold em `body_pct` (ex: <33% = doji) | Baixo | `src/domain/models.py` |
| 3 | Trader's Equation basica | RR ja validado (>=1.5). Adicionar P(win) via lookup table + calcular EV | Medio | Novo: `src/ai/traders_equation.py` |
| 4 | Trail stop | Stop estatico eh a maior divergencia operacional. Trailing abaixo de higher lows | Medio | `src/execution/executor.py` |
| 5 | Counter-trend guard | Se always_in=LONG e action=VENDA (ou vice-versa), aplicar veto ou penalidade severa (-30 SS) | Baixo | `src/ai/confidence_adjuster.py` |

### P1 — Alto Impacto, Esforco Alto

| # | Item | Justificativa | Esforco | Arquivo alvo |
|---|---|---|---|---|
| 6 | Multi-scenario output | Mudanca arquitetural no Strategy Engine. Pedir 2-3 cenarios com probabilidades no JSON | Alto | Strategy Engine + `src/strategy/signal_parser.py` |
| 7 | H/L Counting algoritmico | Fundamental para Nogran PA. Detectar H1-H4/L1-L4 no Python | Alto | Novo: `src/market/bar_counter.py` |
| 8 | Trend Line detection | Necessario para Major Trend Reversal e counter-trend guard. Swing highs/lows + regressao | Alto | Novo: `src/market/trend_lines.py` |
| 9 | Measured Moves | Alvos estruturais em vez de LLM-only. Spike height -> channel target | Medio | Novo: `src/market/measured_moves.py` |
| 10 | Scale in/out + parciais | Melhora Trader's Equation real. Refactor do executor | Alto | `src/execution/executor.py` |

### P2 — Medio Impacto, Esforco Variavel

| # | Item | Esforco | Arquivo alvo |
|---|---|---|---|
| 11 | Day Type heuristico (complementar LLM) | Medio | Novo: `src/market/day_type_detector.py` |
| 12 | Always-In rule-based (ADX + momentum) | Medio | `src/ai/regime_detector.py` |
| 13 | Breakout real vs falso (6 criterios da spec) | Alto | Novo: `src/market/breakout_assessor.py` |
| 14 | Gap detection (abertura, measuring gaps) | Medio | Novo: `src/market/gap_detector.py` |
| 15 | Key levels tracking (S/R, yesterday H/L) | Medio | Novo: `src/market/key_levels.py` |

### P3 — Frontend (apos P0-P1)

| # | Item | Esforco | Arquivo alvo |
|---|---|---|---|
| 16 | Painel multi-cenario com probabilidades | Alto | `dashboard/app.py` |
| 17 | Probabilidade direcional visual (barras Bull/Bear/Flat) | Medio | `dashboard/app.py` |
| 18 | Contadores de estado (12 campos da spec) | Medio | `src/market/feature_engine.py` + `dashboard/app.py` |
| 19 | Key levels no grafico candlestick | Medio | `dashboard/app.py` |
| 20 | Qualidade setup grade A+/B/C/D | Baixo | `src/ai/decision_scorer.py` + `dashboard/app.py` |
