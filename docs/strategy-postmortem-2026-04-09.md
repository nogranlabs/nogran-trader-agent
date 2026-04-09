# Auditoria Nogran PA — Gaps Estruturais

> **Data:** 2026-04-09
> **Status:** Documento crítico de retrospectiva
> **Contexto:** Auditoria após constatação de que a estratégia perde dinheiro
> consistentemente em walk-forward porque o LLM recebe **estatísticas single-bar**
> em vez de **padrões de sequência Nogran PA**.

---

## 0. Mea culpa

Esse documento existe porque o projeto foi descrito como "PA-based AI trading
agent" mas o `feature_engine.py` foi implementado num paradigma **quant tradicional**
(indicadores agregados sobre 1 candle) que é **incompatível** com a metodologia
Nogran PA (leitura de sequências de 5-10 bars + swing structure + EMA dinâmica + always-in).

A consequência é que o LLM foi colocado numa posição impossível: receber input
quant e raciocinar Nogran PA. Isso explica os resultados:
- Window A (bear -22%): -5.07% PnL, 9% WR
- Window B (flat -1%): -4.36% PnL, **0% WR**
- Window C (flat 0%): -0.15% PnL, 37% WR
- **Média: -3.19%/mês**

A causa raiz **não é** ajuste de parâmetro, prompt, RR floor ou tuning do detector
de hallucination. É **feature engineering errado desde o dia zero**.

---

## 1. Como Nogran PA REALMENTE pensa

Para cada bar Nogran PA olha (mentalmente):

1. **Sequência das últimas 5-10 bars** — pattern matching visual
2. **Swing high / swing low recentes** — estrutura de HH/HL ou LH/LL
3. **EMA20** — tocou? Quebrou? Veio de cima ou de baixo?
4. **Trendlines** — micro (5 bars) e major (20+ bars)
5. **Always-in bias** — bulls dominam? bears dominam? transição?
6. **Trading range vs trend** — primeira coisa do dia
7. **Tentativas falhas recentes** — a 2ª tentativa funciona 60% das vezes
8. **Climactic exhaustion** — bar grande no extremo do move
9. **Inside / outside / engulfing bars** — patterns de 1-2 bars
10. **Spike vs channel** — depois de um spike, vem um channel
11. **Wedge** — 3 pushes na mesma direção, cada um menor
12. **Round numbers e prior swing** — magnetos de preço

Cada um desses requer **memória de N bars anteriores**. Nenhum cabe num "feature
single-bar".

---

## 2. O que o feature engine ATUAL produz

```python
class FeatureSnapshot:
 candle: Candle # current bar only
 candle_index: int
 ema_20: float # current value
 atr_14: float # current value
 atr_sma_20: float
 adx_14: float # current value
 price_vs_ema: float # current bar's distance from EMA
 atr_ratio: float # current ATR / SMA20
 body_pct: float # current bar's body
 upper_tail_pct: float # current bar's tail
 lower_tail_pct: float # current bar's tail
 consecutive_bull: int # current run length
 consecutive_bear: int
 bar_overlap_ratio: float # last 10 bars overlap
 direction_change_ratio: float
 volume_ratio: float # current vol / SMA20
 tf_5m_* # multi-TF (DEAD CODE — never populated on 15m)
 is_peak_session: bool
 atr_expanding/contracting: bool
 # added 2026-04-09:
 is_at_5bar_high/low: bool
 bars_since_5bar_high/low: int
 recent_bars: list[Candle] # NEW Fix A
```

**Tudo que tem aqui descreve o ESTADO do bar atual.** Nada descreve PADRÃO em
sequência, swing structure, EMA testing, always-in, ou qualquer outra coisa
Nogran PA-específica.

---

## 3. Tabela completa de gaps

### 🚨 P0 — Foundational gaps (estratégia inteira não funciona sem isso)

| # | Conceito Nogran PA | O que existe hoje | Esforço | Status |
|---|---|---|---|---|
| 1 | **Sequência de bars** | Single-bar stats | 1h | ✅ Fix A em #69 |
| 2 | **Swing high / swing low tracking** | NADA | 2h | ❌ |
| 3 | **HH / HL / LH / LL structure** | NADA | 1h (depois do #2) | ❌ |
| 4 | **EMA test detection** (touched? broke?) | só `price_vs_ema` (número) | 1h | ❌ |
| 5 | **Always-in bias COMPUTADO** | LLM classifica (layer 2) sem dados | 2h | ❌ |
| 6 | **Trading range vs trend classifier** | só ADX | 2h | ❌ |
| 7 | **Multi-TF 1h** | tf_5m_* dead code, sem 1h | 2h | ❌ |
| 8 | **Stops/targets em SWING (não %)** | 0.5%/1% guards (fee-based) | 1h | ❌ |

**Total:** ~12-13h de trabalho

### 🟡 P1 — Setup detection (Nogran PA setups que NÃO computamos)

| # | Setup Nogran PA | Importância | Como detectar | Status |
|---|---|---|---|---|
| 9 | **Inside bar (ii)** | Alta — Nogran PA ii setup | high<prev_high E low>prev_low | ❌ |
| 10 | **Outside bar (oo)** | Alta — reversal signal | high>prev_high E low<prev_low | ❌ |
| 11 | **Engulfing bar** | Alta — reversal | body engulfs prior body | ❌ |
| 12 | **Climactic bar** | Crítica — exhaustion | body>80% E range>2x ATR | ❌ |
| 13 | **Pinbar / hammer** | Média | tail >60% on rejection side | ❌ |
| 14 | **Failed breakout** | **CRÍTICA** — Nogran PA #1 setup | break level then reverse | ❌ |
| 15 | **Second attempt rule** | Crítica — 60% rule | 1 fail, then 2nd succeeds | ❌ |
| 16 | **Wedge top/bottom** | Média — reversal | 3 decreasing pushes | ❌ |
| 17 | **Spike-and-channel** | Alta — Nogran PA day type | spike then slowdown | ❌ |
| 18 | **Two-legged move** | Média | impulse-pullback-impulse | ❌ |
| 19 | **Inside-inside (ii)** | Média — Nogran PA ii setup | 2 consecutive inside bars | ❌ |
| 20 | **Inside-outside-inside (ioi)** | Baixa — niche | sequence pattern | ❌ |

### 🟠 P2 — Context features (Nogran PA usa, nós não)

| # | Conceito Nogran PA | O que falta | Esforço |
|---|---|---|---|
| 21 | Round numbers ($70000, $75000) | tracking + distance | 30min |
| 22 | Prior session high/low | PDH/PDL | 30min |
| 23 | Time of day Nogran PA | "first hour" / "midday" / "last hour" | 30min |
| 24 | Volume on signal bar | comparar com prior 5 bars | 30min |
| 25 | Bar size in ATR units | range / ATR | 15min |
| 26 | Strong trend bar boolean | body >50% AND in trend direction | 30min |
| 27 | Distance from EMA in ATR | mean reversion proxy | 15min |
| 28 | Bars since last EMA test | trend persistence | 30min |
| 29 | Direction of EMA slope | bull/bear/flat | 15min |
| 30 | Trendline tracking (micro 5-bar) | line fitting | 1h |
| 31 | Trendline tracking (major 20-bar) | line fitting | 1h |

### 🟢 P3 — Architectural gaps (não-feature, mas Nogran PA-relevantes)

| # | Issue | Onde |
|---|---|---|
| 32 | **LLM faz tudo de uma vez** (classify + decide + size) — Nogran PA separa cognitivamente | system prompt |
| 33 | **KB lookup é name-based, não pattern-based** | `probabilities_kb.py` |
| 34 | **Decision Scorer regime-blind** (mesmos pesos em trend vs range) | `decision_scorer.py` |
| 35 | **RR floor é fixo** — Nogran PA varia com regime (1:1 em trend forte, 2:1 em range) | `llm_strategy.py` |
| 36 | **Sem "second attempt" tracking** entre candles | `local_signal.py` / pipeline |
| 37 | **Mock heuristic é igualmente blinded** — `local_signal.py` usa as mesmas features quant | `local_signal.py` |
| 38 | **Stops não validados em structure** — LLM escolhe livre, guard é só % | `llm_strategy.py` |
| 39 | **Nogran PA 6-rule prompt usa termos abstratos** sem mostrar exemplos | `llm_prompts.py` |

---

## 4. Plano de correção realista

### Cenário A: Hackathon-critical (3 dias até freeze)

**Não dá pra refatorar tudo.** Foco no que move o ponteiro:

| Ordem | Fix | Razão |
|---|---|---|
| 1 | Fix A (last 6 bars) | ✅ DONE |
| 2 | **Swing points + HH/HL structure** | Nogran PA #1 — sem isso nada faz sentido |
| 3 | **Multi-TF 1h** (popular tf_1h_*) | Contexto que falta pra trade-with-trend |
| 4 | **Climactic bar + inside bar booleans** | Nogran PA setups básicos |
| 5 | **Regime classifier explícito** ("trending" vs "range") | Decisões dependem disso |
| 6 | **Failed-attempt tracker** | A second-attempt rule é o setup #1 do Nogran PA |

**Esforço:** 8-10h. **Custo:** zero. **Outcome esperado:** estratégia tem chance real de virar lucrativa em walk-forward.

### Cenário B: Pós-hackathon refactor completo

| Fase | Conteúdo | Esforço |
|---|---|---|
| 1 | Refatorar `feature_engine.py` em módulos: pattern_features, swing_features, ema_features, regime_classifier | 1 dia |
| 2 | Implementar setups P1 #9-20 | 2 dias |
| 3 | Implementar context P2 #21-31 | 1 dia |
| 4 | Refatorar mock heuristic (`local_signal.py`) pra usar novos features | 1 dia |
| 5 | Adicionar testes unit por setup | 2 dias |
| 6 | Walk-forward 6 meses pra validar | 1 dia (rodando) |

**Total:** ~1 semana.

---

## 5. Lessons learned

### Para o usuário (Mateus)
- A premissa "LLM consegue raciocinar com features quant" é **falsa pra Nogran PA**
- Nogran PA é leitura visual de padrão. LLM precisa receber padrões, não estatísticas.
- **NUNCA** confiar que o feature engine implementa a metodologia descrita no README
 sem cruzar feature por feature contra a metodologia explícita

### Para mim (Claude)
- **Auditar premissa fundamental ANTES de tunar superfície.** Eu deveria ter feito
 esse documento DIA UM da sessão, não no dia 4 depois de gastar $5 em backtest e
 10 horas de tuning.
- Quando o usuário diz "estratégia X", a primeira coisa é abrir a documentação de
 X (ou a KB do projeto, que JÁ EXISTIA em `data/probabilities/pa_probabilities.json`)
 e listar todos os elementos estruturais antes de tocar em qualquer arquivo.
- "O código tem o nome 'Nogran PA' espalhado" ≠ "o código implementa Nogran PA".

---

## 6. Decisão pendente

Com 3 dias até freeze do hackathon, o usuário precisa decidir:

**Opção A — Pivot honesto:**
- Documentar esses gaps no pitch
- Apresentar como "anti-hype: aqui está o que NÃO funciona, e por quê"
- Mostrar walk-forward + análise honesta
- Diferencial: única equipe com auditoria de causa raiz pública

**Opção B — Sprint Nogran PA features:**
- Implementar P0 #2-8 (swing, multi-TF 1h, EMA test, regime, second-attempt)
- ~8-10h de trabalho
- Re-rodar walk-forward
- Risco: pode não dar tempo OU pode não melhorar suficiente

**Opção C — Combo:**
- Implementar SÓ os 3 mais críticos: swing structure, multi-TF 1h, regime classifier
- ~4-5h de trabalho
- Re-rodar walk-forward
- Pitch acomoda os 2 cenários: "v1 walk-forward" e "v2 com Nogran PA structure"

Opção C é a mais pragmática.
