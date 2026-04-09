# NOGRAN.TRADER.AGENT v3 — Arquitetura Completa

> Planejamento final para hackathon AI Trading Agents.
> Evolucao: v1 (RAG basico) -> v2 (Risk Engine + AI Layer) -> v3 (Decision Scoring + Learning Loop + Alpha explicito).

---

## 1. VISAO GERAL DO SISTEMA

O nogran.trader.agent opera em **5 estagios sequenciais com veto independente e scoring unificado**:

```
PERCEPCAO --> INTERPRETACAO --> AI OVERLAY --> RISCO --> EXECUCAO
 (Python) (RAG/LLM) (Python) (Python) (Python)
 | | | | |
 v v v v v
 [Market [Strategy [AI Overlay [Risk [Execution
 Quality Score] Score] Score] Gate]
 Score] \ | /
 \ | /
 v v v
 ┌─────────────────────────────────┐
 │ DECISION SCORE (0-100) │
 │ Executa SOMENTE se score > 65 │
 └─────────────────────────────────┘
 |
 v
 ┌─────────────────────────────────┐
 │ ERC-8004 LAYER │
 │ TradeIntent + Log + Reputacao │
 └─────────────────────────────────┘
```

**Principio central:** Nenhuma camada sozinha pode forcar um trade. Cada estagio contribui com um sub-score. O Decision Score unificado e o gatilho final. O LLM nunca toca em dados brutos. O Risk Engine nunca depende do LLM.

### Evolucao v2 -> v3

| Aspecto | v2 | v3 |
|---|---|---|
| Criterio de execucao | Confianca do LLM > 40 + Risk approved | Decision Score composto > 65 |
| Explicabilidade | Razao textual do LLM | Score decomposto em 4 sub-scores auditaveis |
| Adaptacao | Parametros fixos | Learning Loop ajusta thresholds por performance |
| Edge (alpha) | Implicito no RAG | Explicito: 4 fontes de alpha documentadas |
| Referencias | Nenhuma | Mapeadas por componente com o que foi usado/ignorado |
| Reputacao | Score generico 0-1000 | Alimentado pelo Decision Score historico |

---

## 2. ARQUITETURA DETALHADA

```
 MARKET DATA LAYER
 ┌─────────────────────────────┐
 │ Kraken WebSocket │
 │ BTC/USD 1m + 5m │
 └──────────┬──────────────────┘
 │
 ┌──────────▼──────────────────┐
 │ FEATURE ENGINE │
 │ (Python - local) │
 │ │
 │ OHLCV parser │
 │ EMA(20) calculator │
 │ ATR(14) calculator │
 │ ADX(14) calculator │
 │ Candle classifier │
 │ Bar counting │
 │ Tail/body ratios │
 │ Volume delta │
 │ Consecutive tracker │
 │ Multi-TF aggregator │
 │ │
 │ Output: FeatureSnapshot │
 └──────────┬──────────────────┘
 │
 ┌──────────▼──────────────────┐
 │ PRE-FILTER + MQ SCORE │
 │ (Python - local) │
 │ │
 │ Chop detector │
 │ Volatility gate │
 │ Session filter │
 │ Cooldown timer │
 │ │
 │ Output: market_quality │
 │ score (0-100) │
 │ VETA se MQ < 30 │
 └──────────┬──────────────────┘
 │ (so passa se MQ >= 30)
 │
 ┌──────────▼──────────────────┐
 │ STRATEGY ENGINE │
 │ (Strategy Engine (Python LLM) Top-Down) │
 │ │
 │ Camada 1: Tipo do Dia │
 │ Camada 2: Macro / Always-In│
 │ Camada 3: Estrutura │
 │ Camada 4: Micro / Barra │
 │ Camada 5: Setup / Gatilho │
 │ │
 │ Output: TradeSignal + │
 │ strategy_score (0-100) │
 └──────────┬──────────────────┘
 │
 ┌──────────▼──────────────────┐
 │ AI OVERLAY │
 │ (Python - local) │
 │ │
 │ Regime classifier │
 │ Confidence adjuster │
 │ Multi-TF confirmation │
 │ Target optimizer │
 │ Overtrading brake │
 │ │
 │ Output: ai_overlay_score │
 │ (0-100) │
 └──────────┬──────────────────┘
 │
 ┌──────────▼──────────────────┐
 │ RISK ENGINE │
 │ (Python - local) │
 │ │
 │ Position sizer │
 │ Drawdown controller │
 │ Exposure manager │
 │ Stop adjuster │
 │ Circuit breakers │
 │ │
 │ Output: RiskApproval + │
 │ risk_score (0-100) │
 └──────────┬──────────────────┘
 │
 ┌──────────▼──────────────────┐
 │ DECISION SCORER │
 │ (Python - local) │
 │ │
 │ Combina 4 sub-scores │
 │ Aplica pesos adaptativos │
 │ Threshold: score > 65 │
 │ │
 │ Output: DecisionScore │
 │ {total, breakdown, go/nogo}│
 └──────────┬──────────────────┘
 │
 ┌──────────▼──────────────────┐
 │ ERC-8004 LAYER │
 │ │
 │ TradeIntent + score │
 │ EIP-712 signer │
 │ Decision logger │
 │ Reputation (score-based) │
 └──────────┬──────────────────┘
 │
 ┌──────────▼──────────────────┐
 │ EXECUTION ENGINE │
 │ (Python - Kraken CLI) │
 │ │
 │ OCO order builder │
 │ Order lifecycle mgr │
 │ Fill tracker │
 │ PnL calculator │
 └──────────┬──────────────────┘
 │
 ┌──────────▼──────────────────┐
 │ LEARNING LOOP │
 │ (Python - pos-trade) │
 │ │
 │ Atualiza metricas │
 │ Ajusta thresholds │
 │ Alimenta reputacao │
 └──────────┬──────────────────┘
 │
 ┌──────────▼──────────────────┐
 │ TELEMETRY │
 │ │
 │ Trade journal (JSONL) │
 │ Performance metrics │
 │ ERC-8004 audit trail │
 │ Decision Score historico │
 └─────────────────────────────┘
```

### Fluxo de veto (qualquer estagio pode parar)

```
Pre-Filter VETA --> "MQ score 22/100 — mercado em chop" (nao gasta API)
Strategy VETA --> "AGUARDAR — signal bar reprovado" (Price Action)
AI Overlay VETA --> "Regime TRANSITIONING, confianca < 40" (filtro local)
Risk Engine VETA --> "Drawdown 6.2%, circuit breaker ativo" (protecao de capital)
Decision Score VETA --> "Score 58/100 < threshold 65" (qualidade insuficiente)
```

---

## 3. DECISION SCORING SYSTEM

### 3.1 Conceito

O Decision Score e o numero unico que determina se um trade acontece. Em vez de um binario "LLM disse compra / Risk Engine aprovou", cada camada contribui com um sub-score de 0-100, e o score final composto e o criterio de execucao.

**Por que isso importa:**
- **Explicabilidade:** qualquer trade (executado ou vetado) pode ser explicado por seus 4 sub-scores
- **Auditoria:** o ERC-8004 TradeIntent inclui o score decomposto — juizes veem exatamente por que cada decisao foi tomada
- **Calibracao:** o Learning Loop ajusta os thresholds com base no historico de scores vs resultados
- **Reputacao:** o score medio historico alimenta diretamente o reputation tracker

### 3.2 Sub-Scores

```
SUB-SCORE | FONTE | O QUE MEDE | RANGE
-------------------------|----------------|-------------------------------------------|-------
Market Quality (MQ) | Pre-Filter | Operabilidade do mercado | 0-100
Strategy Score (SS) | Strategy Engine (Python LLM) | Qualidade do setup segundo Nogran PA | 0-100
AI Overlay Score (AO) | AI Layer | Confirmacao por regime, volume, multi-TF | 0-100
Risk Score (RS) | Risk Engine | Saude do capital e viabilidade de risco | 0-100
```

### 3.3 Calculo de cada Sub-Score

**Market Quality Score (MQ):**

```python
def calculate_mq_score(features: FeatureSnapshot) -> int:
 score = 100

 # Chop penalty: sobreposicao entre barras
 overlap = features.bar_overlap_ratio # 0.0 a 1.0
 if overlap > 0.7:
 score -= 40 # Chop severo
 elif overlap > 0.5:
 score -= 20 # Chop moderado

 # Volatilidade: ATR relativo a media
 atr_ratio = features.atr / features.atr_sma20
 if atr_ratio < 0.5:
 score -= 30 # Mercado morto
 elif atr_ratio < 0.8:
 score -= 15 # Volatilidade baixa

 # Alternancia de direcao (ruido)
 direction_changes = features.direction_change_ratio # 0.0 a 1.0
 if direction_changes > 0.6:
 score -= 20

 # Bonus por sessao de alta liquidez
 if features.is_peak_session: # 13:00-21:00 UTC
 score += 10

 return clamp(score, 0, 100)
```

**Strategy Score (SS):**

O LLM ja retorna `confianca` (0-100) no JSON. O Strategy Score usa esse valor como base, mas penaliza inconsistencias:

```python
def calculate_ss_score(trade_signal: TradeSignal) -> int:
 score = trade_signal.confidence # Base do LLM

 # Penaliza se signal bar reprovado mas LLM sugere trade mesmo assim
 if trade_signal.signal_bar_quality == "REPROVADO" and trade_signal.action != "AGUARDAR":
 score -= 30

 # Penaliza se setup e fraco na hierarquia do Nogran PA
 setup_quality = {
 "second_entry_H2": 0, # Melhor — sem penalidade
 "breakout_pullback": -5,
 "H2_ema": -10,
 "ii_breakout": -15,
 "shaved_bar": -20,
 "none": -50
 }
 score += setup_quality.get(trade_signal.setup, -25)

 # Bonus se tipo do dia e claro (nao indefinido)
 if trade_signal.day_type != "indefinido":
 score += 5

 return clamp(score, 0, 100)
```

**AI Overlay Score (AO):**

```python
def calculate_ao_score(trade_signal, features, regime, recent_trades) -> int:
 score = 70 # Base neutra

 # Regime alignment
 trending_setups = ["second_entry_H2", "breakout_pullback", "shaved_bar"]
 if regime == "TRENDING" and trade_signal.setup in trending_setups:
 score += 15 # Alinhado
 elif regime == "TRENDING" and trade_signal.action == "VENDA" and trade_signal.setup not in trending_setups:
 score -= 15 # Contra-tendencia em trend forte
 elif regime == "TRANSITIONING":
 score -= 20 # Incerteza

 # Multi-TF confirmation
 if features.tf_5m_direction == trade_signal.action:
 score += 10 # 5m confirma
 elif features.tf_5m_direction is not None and features.tf_5m_direction != trade_signal.action:
 score -= 15 # 5m contradiz

 # Volume
 if features.volume_ratio > 1.2:
 score += 5 # Volume acima da media
 elif features.volume_ratio < 0.5:
 score -= 10 # Volume muito baixo

 # ATR expansion (breakout real vs falso)
 if features.atr_expanding:
 score += 5
 elif features.atr_contracting:
 score -= 10

 # Revenge trade penalty
 if len(recent_trades) > 0:
 last = recent_trades[-1]
 if last.pnl < 0 and last.side == trade_signal.action:
 score -= 10 # Mesmo lado do ultimo loss

 # Overtrading penalty
 trades_last_hour = sum(1 for t in recent_trades if t.age_minutes < 60)
 if trades_last_hour >= 3:
 score -= 15
 elif trades_last_hour >= 2:
 score -= 5

 return clamp(score, 0, 100)
```

**Risk Score (RS):**

```python
def calculate_rs_score(capital, drawdown, atr, trade_signal, metrics) -> int:
 score = 100

 # Drawdown penalty (escala progressiva)
 if drawdown > 0.08:
 score = 0 # Circuit breaker
 elif drawdown > 0.05:
 score -= 50 # Modo minimo
 elif drawdown > 0.03:
 score -= 25 # Modo defensivo

 # Trader's Equation
 risk = abs(trade_signal.entry_price - trade_signal.stop_loss)
 reward = abs(trade_signal.take_profit - trade_signal.entry_price)
 rr = reward / risk if risk > 0 else 0
 if rr < 1.5:
 score = 0 # Veto absoluto
 elif rr < 2.0:
 score -= 10
 elif rr >= 3.0:
 score += 10 # Excelente R/R

 # Sharpe rolling
 if metrics.sharpe_rolling < -1.0:
 score -= 30
 elif metrics.sharpe_rolling < 0:
 score -= 15
 elif metrics.sharpe_rolling > 1.0:
 score += 10

 # Consecutive losses
 if metrics.consecutive_losses >= 3:
 score -= 25

 # Position viability (sizing minimo)
 min_size = calculate_min_viable_size(capital, atr)
 if min_size < MIN_ORDER_SIZE:
 score = 0 # Capital insuficiente para operar

 return clamp(score, 0, 100)
```

### 3.4 Formula do Decision Score

```python
class DecisionScorer:
 """
 Combina os 4 sub-scores em um score final unico.
 Pesos sao adaptativos (ajustados pelo Learning Loop).
 """

 # Pesos iniciais (somam 1.0)
 DEFAULT_WEIGHTS = {
 "market_quality": 0.20, # 20% — mercado operavel?
 "strategy": 0.35, # 35% — Price Action aprova?
 "ai_overlay": 0.20, # 20% — confirmacao por AI?
 "risk": 0.25, # 25% — capital saudavel?
 }

 EXECUTION_THRESHOLD = 65 # So executa se score > 65

 def calculate(self, mq, ss, ao, rs, weights=None) -> DecisionScore:
 w = weights or self.DEFAULT_WEIGHTS

 total = (
 mq * w["market_quality"] +
 ss * w["strategy"] +
 ao * w["ai_overlay"] +
 rs * w["risk"]
 )

 # Veto absoluto: se QUALQUER sub-score < 20, nao executa
 hard_veto = any(s < 20 for s in [mq, ss, ao, rs])

 return DecisionScore(
 total=round(total, 1),
 go=total >= self.EXECUTION_THRESHOLD and not hard_veto,
 breakdown={
 "market_quality": {"score": mq, "weight": w["market_quality"]},
 "strategy": {"score": ss, "weight": w["strategy"]},
 "ai_overlay": {"score": ao, "weight": w["ai_overlay"]},
 "risk": {"score": rs, "weight": w["risk"]},
 },
 threshold=self.EXECUTION_THRESHOLD,
 hard_veto=hard_veto
 )
```

### 3.5 Exemplos de Decisao

```
EXEMPLO 1: Trade executado (score 78.5)
──────────────────────────────────────
 Market Quality: 85 x 0.20 = 17.0 (trending, ATR saudavel)
 Strategy: 82 x 0.35 = 28.7 (Second Entry H2, tipo_dia claro)
 AI Overlay: 75 x 0.20 = 15.0 (regime alinhado, 5m confirma)
 Risk: 71 x 0.25 = 17.8 (drawdown 1.5%, R/R 2.1)
 ────────────────────────────────
 TOTAL: 78.5 > 65 --> EXECUTA
 Hard veto: nenhum sub-score < 20

EXEMPLO 2: Trade vetado (score 52.3)
──────────────────────────────────────
 Market Quality: 42 x 0.20 = 8.4 (overlap alto, ATR baixo)
 Strategy: 70 x 0.35 = 24.5 (setup ok mas dia indefinido)
 AI Overlay: 45 x 0.20 = 9.0 (regime transitioning, 5m contra)
 Risk: 41 x 0.25 = 10.3 (drawdown 4.1%, sizing reduzido)
 ────────────────────────────────
 TOTAL: 52.3 < 65 --> AGUARDAR
 Razao: score insuficiente (MQ e AO fracos)

EXEMPLO 3: Trade vetado por hard veto (score 61.0)
──────────────────────────────────────
 Market Quality: 80 x 0.20 = 16.0
 Strategy: 15 x 0.35 = 5.3 <-- HARD VETO (< 20)
 AI Overlay: 70 x 0.20 = 14.0
 Risk: 85 x 0.25 = 21.3
 ────────────────────────────────
 TOTAL: 56.5 --> AGUARDAR (hard veto no Strategy)
 Razao: LLM com baixissima confianca no setup
```

### 3.6 Como o Decision Score conecta com ERC-8004

Cada TradeIntent agora inclui o score decomposto:

```json
{
 "intent_id": "uuid-aqui",
 "decision_score": {
 "total": 78.5,
 "threshold": 65,
 "executed": true,
 "breakdown": {
 "market_quality": {"score": 85, "weight": 0.20, "contribution": 17.0},
 "strategy": {"score": 82, "weight": 0.35, "contribution": 28.7},
 "ai_overlay": {"score": 75, "weight": 0.20, "contribution": 15.0},
 "risk": {"score": 71, "weight": 0.25, "contribution": 17.8}
 },
 "hard_veto": false
 }
}
```

Isso permite:
- **Juizes** verem exatamente por que cada trade aconteceu
- **Reputacao** ser calculada sobre scores historicos (nao apenas PnL)
- **Auditoria** verificar se o agente seguiu seus proprios criterios

---

## 4. LEARNING LOOP (ADAPTATIVO) — PLANEJADO, NAO IMPLEMENTADO

> **Status:** src/learning/ esta vazio. A secao abaixo descreve o design planejado para v3.
> O codigo atual NAO implementa nenhuma das funcionalidades abaixo.

### 4.1 Principio

O Learning Loop NAO usa ML pesado. Ele e um **sistema de calibracao deterministica** que ajusta parametros operacionais com base em metricas de performance recentes. Totalmente explicavel — cada ajuste tem uma regra clara e um motivo documentado.

### 4.2 O que o Learning Loop ajusta

```
Parametro | Mecanismo de ajuste | Frequencia
--------------------------|----------------------------------|------------------
Execution threshold | Sobe se winrate < 35% | A cada 10 trades
 | Desce se winrate > 55% |
Pesos do Decision Score | Aumenta peso de sub-scores | A cada 20 trades
 | com melhor correlacao com PnL |
Position sizing base | Reduz se drawdown subindo | A cada trade
 | Aumenta se equity em ATH |
Max trades/hora | Reduz se overtrade detectado | A cada hora
R/R minimo | Aumenta se winrate < 40% | A cada 10 trades
Cooldown pos-trade | Aumenta apos 3 losses seguidos | A cada trade
```

### 4.3 Implementacao

```python
class LearningLoop:
 """
 Calibracao deterministica pos-trade.
 Sem ML, sem black box. Cada ajuste e uma regra if/then documentada.
 """

 def __init__(self, decision_scorer: DecisionScorer):
 self.scorer = decision_scorer
 self.trade_history = []

 def on_trade_closed(self, trade_result):
 """Chamado toda vez que um trade fecha (win ou loss)."""
 self.trade_history.append(trade_result)

 # So ajusta apos janela minima (evita overfitting a ruido)
 if len(self.trade_history) < 10:
 return

 recent = self.trade_history[-20:] # Janela de 20 trades
 metrics = self._compute_metrics(recent)

 self._adjust_threshold(metrics)
 self._adjust_weights(metrics)
 self._adjust_sizing(metrics)
 self._adjust_cooldown(metrics)

 def _adjust_threshold(self, metrics):
 """
 Se estamos perdendo muito, exige trades de maior qualidade.
 Se estamos ganhando consistentemente, pode relaxar levemente.
 """
 current = self.scorer.EXECUTION_THRESHOLD

 if metrics.win_rate < 0.35:
 # Perdendo muito -> exige score maior
 new_threshold = min(current + 3, 80) # Teto em 80
 reason = f"Winrate {metrics.win_rate:.0%} < 35% — aumentando exigencia"
 elif metrics.win_rate > 0.55 and metrics.sharpe > 0.5:
 # Ganhando bem -> pode relaxar levemente
 new_threshold = max(current - 2, 55) # Piso em 55
 reason = f"Winrate {metrics.win_rate:.0%} > 55% com Sharpe {metrics.sharpe:.1f} — relaxando"
 else:
 return # Sem ajuste

 self.scorer.EXECUTION_THRESHOLD = new_threshold
 self._log_adjustment("threshold", current, new_threshold, reason)

 def _adjust_weights(self, metrics):
 """
 Analisa correlacao simples entre cada sub-score e resultado do trade.
 Sub-scores que melhor predizem wins ganham mais peso.
 """
 # Calcula correlacao rank (Spearman) entre cada sub-score e PnL
 correlations = {}
 for key in ["market_quality", "strategy", "ai_overlay", "risk"]:
 scores = [t.decision_score.breakdown[key]["score"] for t in metrics.trades]
 pnls = [t.pnl for t in metrics.trades]
 correlations[key] = spearman_correlation(scores, pnls)

 # Normaliza correlacoes para pesos (soma = 1.0)
 total_corr = sum(max(c, 0.05) for c in correlations.values) # Floor em 0.05
 new_weights = {k: max(c, 0.05) / total_corr for k, c in correlations.items}

 # Aplica com suavizacao (80% peso anterior + 20% novo)
 for key in new_weights:
 old = self.scorer.weights[key]
 self.scorer.weights[key] = old * 0.8 + new_weights[key] * 0.2

 self._log_adjustment("weights", None, self.scorer.weights, "Correlacao score-PnL")

 def _adjust_sizing(self, metrics):
 """Ajusta position sizing base conforme equity curve."""
 if metrics.drawdown > 0.05:
 self.sizing_multiplier = 0.5
 elif metrics.drawdown > 0.03:
 self.sizing_multiplier = 0.7
 elif metrics.equity_at_ath:
 self.sizing_multiplier = min(self.sizing_multiplier + 0.05, 1.0)

 def _adjust_cooldown(self, metrics):
 """Aumenta cooldown apos losses consecutivos."""
 if metrics.consecutive_losses >= 3:
 self.cooldown_candles = 5 # 5 min
 elif metrics.consecutive_losses >= 2:
 self.cooldown_candles = 3 # 3 min
 else:
 self.cooldown_candles = 2 # Default

 def _log_adjustment(self, param, old_value, new_value, reason):
 """Registra cada ajuste no audit trail — transparencia total."""
 log_entry = {
 "timestamp": datetime.utcnow.isoformat,
 "parameter": param,
 "old_value": old_value,
 "new_value": new_value,
 "reason": reason,
 "trade_count": len(self.trade_history)
 }
 # Append ao log de ajustes
 with open("logs/learning_adjustments.jsonl", "a") as f:
 f.write(json.dumps(log_entry) + "\n")
```

### 4.4 Limites de Seguranca (guardrails)

```
Parametro | Minimo | Maximo | Justificativa
-------------------------|--------|--------|---------------------------
Execution threshold | 55 | 80 | Abaixo de 55 = aceita lixo. Acima de 80 = nunca opera
Peso de qualquer score | 0.10 | 0.50 | Nenhum score domina sozinho
Position sizing mult. | 0.3 | 1.0 | Nunca mais que 100% do sizing base
Cooldown candles | 2 | 10 | Minimo 2 min entre trades
R/R minimo | 1.5 | 3.0 | Abaixo de 1.5 = matematicamente ruim
Max trades/hora | 2 | 6 | Limites firmes de overtrading
```

Esses guardrails garantem que o Learning Loop **nunca** desestabiliza o sistema. Ele calibra dentro de faixas seguras — nao reinventa a estrategia.

---

## 5. ALPHA (EDGE) DO SISTEMA

### 5.1 O que e alpha

Alpha e a vantagem sistematica do agente sobre o mercado. Sem alpha, qualquer bot perde dinheiro no longo prazo (comissoes + slippage > retorno aleatorio). O nogran.trader.agent tem **4 fontes de alpha complementares**:

### 5.2 Fonte 1: Comportamento repetitivo em Price Action

**Tese:** O mercado de crypto em timeframes baixos (1m-5m) apresenta padroes de price action que se repetem com frequencia estatisticamente significativa. Esses padroes foram documentados extensivamente por Nogran PA em mais de 20 anos de trading.

**Como exploramos:** O RAG Top-Down consulta a teoria de Nogran PA em 5 camadas ordenadas, aplicando regras especificas para cada contexto. O LLM nao "inventa" padroes — ele reconhece padroes ja catalogados pelo autor.

**Por que funciona em crypto:** Crypto tem alta participacao de bots e retail traders que criam padroes repetitivos de price action (spikes, climaxes, failed breakouts). Esses padroes sao os mesmos que Nogran PA documenta em futuros — a microestrutura e similar.

**Quantificavel:** O setup de maior hierarquia (Second Entry) tem taxa de acerto documentada de 60-70% segundo Nogran PA (Cap. 10). Combinado com R/R minimo de 1.5, a expectativa matematica e positiva.

### 5.3 Fonte 2: Filtragem superior de sinais ruins

**Tese:** A maioria dos bots perde dinheiro nao por falta de bons sinais, mas por executar sinais ruins. O alpha vem de NAO operar quando o mercado nao oferece edge.

**Como exploramos:** O pipeline de 5 estagios com veto independente filtra agressivamente:
- Pre-filter elimina ~40-60% das velas (chop, baixa volatilidade, sessao ruim)
- Strategy elimina ~60-70% dos sinais restantes (signal bar reprovado, setup fraco)
- AI Overlay elimina ~20-30% dos aprovados (regime conflitante, revenge trade)
- Risk Engine elimina ~10-20% finais (drawdown, sizing inviavel)
- Decision Score faz o corte final (< 65)

**Resultado estimado:** De cada 100 velas analisadas, o agente opera ~3-5. Isso e uma taxa de selectividade altissima que preserva capital.

### 5.4 Fonte 3: Risk management como alpha

**Tese:** Position sizing dinamico e controle de drawdown geram alpha real — nao apenas protegem capital. Apostar mais quando o edge e claro e menos quando e duvidoso gera retorno superior ao sizing fixo.

**Como exploramos:**
- Sizing proporcional ao Decision Score: score 75 = sizing cheio, score 65 = sizing minimo
- Drawdown bands reduzem exposicao gradualmente (nao binario)
- Stop adaptativo por ATR garante risco constante em $ independente da volatilidade
- Target otimizado por regime: mais agressivo em tendencia, conservador em range

**Quantificavel:** O Kelly criterion (simplificado) com winrate 55% e R/R 2.0 sugere sizing de ~15% do capital por trade. Nossas bandas de drawdown limitam isso a 1-2% de risco por trade, sacrificando crescimento por sobrevivencia (prioridade no hackathon).

### 5.5 Fonte 4: Tempo como filtro (nao operar e uma posicao)

**Tese:** Em trading de alta frequencia relativa (1m candles), a maioria do tempo o mercado esta em chop — operar nesse periodo destroi PnL. O alpha vem de esperar.

**Como exploramos:**
- Chop detector: evita mercados laterais sem direcao
- Cooldown pos-trade: evita revenge trading e overtrading emocional
- Circuit breakers: para antes de drawdown catastrofico
- Overtrading brake: limita trades/hora para manter disciplina

**Resultado:** O agente passa a maior parte do tempo em modo AGUARDAR. Isso e by design — cada trade que NAO fazemos em mercado choppy e capital preservado.

---

## 6. REFERENCIAS TECNICAS E INSPIRACAO

### 6.1 Principio de uso de referencias

Este projeto usa referencias externas como **fonte de ideias e validacao**, nao como template. Cada referencia foi avaliada e apenas componentes especificos foram aproveitados — a arquitetura, a estrategia, e a integracao sao originais.

### 6.2 Mapeamento por componente

```
COMPONENTE | REFERENCIA | O QUE FOI APROVEITADO | O QUE FOI IGNORADO/ADAPTADO
----------------------------|----------------------|---------------------------------|-----------------------------
Feature Engineering | Qlib (Microsoft) | Conceito de features como | Framework inteiro, porque
(market/feature_engine.py) | | funcoes puras sobre OHLCV. | nosso scope e 3 indicadores
 | | Separacao dados/logica. | (EMA, ATR, ADX), nao 158.
 | | | Qlib e para portfolio, nos
 | | | operamos 1 par.
 | | |
Risk Metrics | pyfolio / ffn | Formulas de Sharpe ratio, | Visualizacao e tear sheets.
(risk/metrics.py) | | max drawdown, profit factor. | Nosso calculo e rolling e
 | | Definicoes padrao da industria. | em tempo real, nao pos-hoc.
 | | | Nao usamos returns-based
 | | | analysis (nosso e trade-based).
 | | |
Execution Layer | freqtrade | Pattern de order lifecycle: | Todo o framework. Freqtrade
(execution/*) | | create -> fill -> track -> | e um bot completo com
 | | close. Conceito de OCO. | backtesting, UI, plugins.
 | | Uso de CCXT como adapter. | Nos usamos Kraken CLI
 | | | (subprocess) para execucao.
 | | |
ERC-8004 / Smart Contracts | OpenZeppelin | Patterns de EIP-712 signing. | Contracts em Solidity.
(compliance/*) | | Conceito de metadata hash | Nos simulamos em Python
 | | para identidade. Estrutura | porque o hackathon nao
 | | de TradeIntent inspirada | exige deploy on-chain.
 | | em ERC-721 metadata. | Reputacao e calculada
 | | | localmente, nao em contract.
 | | |
RAG Top-Down | Nogran PA (livro) | Toda a teoria de Price Action. | Capitulos narrativos,
(LLM/*, strategy/*) | + conceito proprio | 9 capitulos essenciais. | psicologia, ETFs.
 | | Hierarquia de camadas e | A arquitetura de 5 camadas
 | | design ORIGINAL do projeto. | com tabelas pgvector
 | | | separadas e invencao nossa.
 | | |
Regime Detection | Papers academicos | Conceito de regime switching | HMM e modelos estatisticos
(ai/regime_detector.py) | (Hamilton 1989, | em mercados financeiros. | complexos. Nosso detector
 | Ang & Bekaert 2002) | Uso de ADX como proxy. | e rule-based com ADX + ATR
 | | | + overlap (mais rapido,
 | | | mais explicavel, sem
 | | | treinamento necessario).
 | | |
Decision Scoring | Credit scoring | Conceito de score composto | ML-based scoring. Nosso
(ai/decision_scorer.py) | (industria financeira)| com sub-scores ponderados. | scoring e deterministico
 | | Threshold como cutoff. | com pesos adaptativos
 | | Conceito de hard veto. | (nao treinados).
```

### 6.3 O que NAO foi usado

```
Referencia | Por que NAO usamos
---------------------|-------------------------------------------------------
Reinforcement Learn. | Requer milhoes de episodios de treinamento. Hackathon
 | tem tempo limitado. Nao e explicavel. Nosso edge vem
 | de regras verificaveis, nao de policy gradient.
 |
Sentiment Analysis | Dados de sentimento sao ruidosos e atrasados.
 | Price Action ja incorpora sentimento (o preco E o
 | consenso do mercado). Adicionar sentiment e redundante.
 |
LLM como decisor | Alucinacao. Latencia. Custo. Inconsistencia.
unico | O LLM e um componente de interpretacao, nao o cerebro.
 |
Backtesting pesado | Tempo de hackathon nao permite backtest robusto.
 | Preferimos regras com edge teorico documentado
 | (Nogran PA) + validacao por replay com figuras do livro.
 |
Multi-asset | Complexidade desnecessaria. 1 par (BTC/USD) permite
 | foco total e otimizacao profunda.
```

---

## 7. RISK ENGINE (DETALHADO)

### 7.1 Position Sizing Dinamico

```python
def calculate_position_size(capital, atr, decision_score, drawdown):
 # 1. Risco base: 1.5% do capital
 base_risk_pct = 0.015

 # 2. Escala pelo Decision Score (65-100 -> 0.6x a 1.0x)
 score_multiplier = map_range(decision_score.total, 65, 95, 0.6, 1.0)

 # 3. Escala pelo drawdown (bandas progressivas)
 dd_multiplier = 1.0
 if drawdown > 0.05:
 dd_multiplier = 0.3
 elif drawdown > 0.03:
 dd_multiplier = 0.6

 # 4. Learning Loop multiplier
 ll_multiplier = learning_loop.sizing_multiplier # 0.3 a 1.0

 # 5. Stop distance por ATR
 stop_distance = atr * 1.5
 risk_in_dollars = capital * base_risk_pct

 position_size = (risk_in_dollars / stop_distance) \
 * score_multiplier \
 * dd_multiplier \
 * ll_multiplier

 return clamp(position_size, MIN_SIZE, MAX_SIZE)
```

### 7.2 Drawdown Controller

```
Drawdown Bands:
 0% a 3% --> Normal (100% sizing, threshold 65)
 3% a 5% --> Defensivo (60% sizing, threshold +5, so melhores setups)
 5% a 8% --> Minimo (30% sizing, threshold +10)
 > 8% --> CIRCUIT BREAKER: para por 15 min, reinicia gradual
```

### 7.3 Stop Adaptativo

```python
def calculate_adaptive_stop(entry_price, side, atr, features):
 # Base: 1.5x ATR
 base_stop = atr * 1.5

 # Ajuste por tipo de barra
 if features.body_pct > 70: # Trend bar forte
 stop_distance = atr * 1.2 # Apertado (momentum claro)
 elif features.body_pct < 30: # Doji / indecisao
 stop_distance = atr * 2.0 # Largo (mais ruido)
 else:
 stop_distance = base_stop

 # Ancora estrutural (swing point)
 structural_stop = find_nearest_swing(side, features.recent_bars)
 if structural_stop:
 stop_distance = max(stop_distance, abs(entry_price - structural_stop) * 1.05)

 return entry_price - stop_distance if side == 'buy' else entry_price + stop_distance
```

### 7.4 Circuit Breakers

```
Trigger | Acao
---------------------------------|----------------------------------------
3 losses consecutivos | Cooldown de 15 min (ajustavel pelo LL)
Drawdown > 8% do capital | Para de operar, reinicia gradual
Sharpe rolling < -1.0 | Risk Score cai para < 20 (hard veto)
Latencia LLM > 10s | AGUARDAR (dado stale)
Erro de execucao Kraken CLI | Retry 1x, depois para e alerta
Posicao aberta > 30 candles | Force close a mercado
```

### 7.5 Metricas em Tempo Real

```python
class RiskMetrics:
 def update(self, trade_result):
 self.trades.append(trade_result)
 self.equity_curve.append(self.equity_curve[-1] + trade_result.pnl)
 self.total_pnl = sum(t.pnl for t in self.trades)
 self.max_drawdown = calculate_max_drawdown(self.equity_curve)
 self.current_drawdown = 1 - (self.equity_curve[-1] / max(self.equity_curve))
 self.win_rate = sum(1 for t in self.trades if t.pnl > 0) / len(self.trades)
 self.avg_win = mean([t.pnl for t in self.trades if t.pnl > 0]) or 0
 self.avg_loss = mean([t.pnl for t in self.trades if t.pnl < 0]) or 0
 self.expectancy = (self.win_rate * self.avg_win) + ((1 - self.win_rate) * self.avg_loss)
 self.sharpe_rolling = calculate_rolling_sharpe(self.returns[-20:])
 self.profit_factor = abs(sum(t.pnl for t in self.trades if t.pnl > 0) /
 sum(t.pnl for t in self.trades if t.pnl < 0)) \
 if any(t.pnl < 0 for t in self.trades) else float('inf')
 self.consecutive_losses = count_tail_losses(self.trades)
 self.equity_at_ath = self.equity_curve[-1] >= max(self.equity_curve)
```

---

## 8. AI LAYER (DETALHADO)

### 8.1 Regime Detector

```python
class RegimeDetector:
 def classify(self, bars_5m, bars_1m):
 adx = calculate_adx(bars_5m, period=14)
 atr_ratio = current_atr / sma(atr_values, 20)
 bar_overlap = calculate_overlap_ratio(bars_1m[-10:])

 if adx > 25 and atr_ratio > 1.1 and bar_overlap < 0.4:
 return "TRENDING"
 elif adx < 20 and bar_overlap > 0.6:
 return "RANGING"
 else:
 return "TRANSITIONING"
```

### 8.2 Multi-Timeframe Confirmation

```
5m (confirmacao):
 - Buffer de ultimas 50 velas de 5m
 - Calcula EMA(20), ATR(14), direcao, consecutivas
 - NAO envia ao RAG (economia de custo/latencia)
 - Contribui para AI Overlay Score

1m (execucao):
 - A cada vela fechada, gera fato matematico v2
 - Inclui contexto do 5m no fato enviado ao LLM
 - Recebe decisao e passa pelo pipeline completo
```

### 8.3 Fato Matematico v2 (enriquecido)

```
"Vela 1m #47 fechou em ALTA.
 OHLCV: O=$67822.0 H=$67890.5 L=$67810.2 C=$67859.3 V=12.4 BTC.
 Corpo: 80.3% do range. Cauda superior: 7.2%. Cauda inferior: 12.5%.
 Tendencia: 3 barras bull consecutivas.
 EMA(20): $67801.0. Preco acima da EMA. Distancia: +0.09%.
 ATR(14): $45.2. ATR relativo a media: 1.15 (volatilidade normal-alta).
 Contexto 5m: ultima vela ALTA, preco acima EMA(20) 5m, 2 barras bull consecutivas.
 Regime detectado: TRENDING."
```

---

## 9. NOGRAN PA KNOWLEDGE BASE & HALLUCINATION DETECTOR

### 9.1 Conceito

Camada de enriquecimento que combina o LLM (Strategy Engine (Python LLM)) com uma **knowledge base estruturada de 62 setups Nogran PA**, atuando como cross-check independente para detectar e auditar alucinacoes do LLM em tempo real.

Roda no Stage 4 do pipeline (apos o LLM retornar e antes do AI Overlay). NAO altera a logica do Decision Scorer (ver CLAUDE.md regra: pesos MQ 20%, SS 35%, AO 20%, RS 25% sao invioluveis).

### 9.2 A knowledge base

`data/probabilities/pa_probabilities.json` (62 setups + 22 hard rules)

Cada setup tem:
- `setup_id`, `name_en`, `name_pt`
- `category` (trend_continuation | breakout | reversal | range_fade | scalp | anti_pattern)
- `direction` (long | short | both)
- `context` (lista de condicoes — bull_trend, after_pullback_to_ma, etc.)
- `probability_pct` (numero base do Nogran PA)
- `probability_range` ([min, max])
- `probability_confidence` (explicit | implied | inferred)
- `min_reward_risk` (R/R recomendado pelo Nogran PA)
- `book_refs` (livro + capitulo + pagina PDF — para audit trail e citacoes)
- `notes_pt` (descricao parafraseada em portugues)

**Origem:** extracao via LLM dos 3 livros do Nogran PA (trilogia "Trading Price Action") + cross-check independente vs `github.com/ByteBard/ict-stradegy registry.json` (32 estrategias codificadas por analistas chineses, com win rates e R/R explicitos).

**88% dos setups tem probabilidade explicita do livro** (`probability_confidence: explicit`). Os outros 12% sao `implied` (Nogran PA fala "high probability") ou `inferred` (cross-check externo).

### 9.3 Lookup direction-aware

O LLM retorna 6 SetupTypes (`second_entry_H2`, `breakout_pullback`, `H2_ema`, `ii_breakout`, `shaved_bar`, `none`). A KB tem 62 setups mais granulares. O lookup mapeia (SetupType + Action) -> setup_id da KB:

```
LLM setup | direction | KB setup_id
--------------------|-----------|---------------------------
second_entry_H2 | long | high_2_pullback_ma_bull
second_entry_H2 | short | low_2_pullback_ma_bear
breakout_pullback | long | breakout_pullback_bull_flag
breakout_pullback | short | breakout_pullback_bear_flag
H2_ema | long | limit_quiet_bull_flag_at_ma
H2_ema | short | limit_quiet_bear_flag_at_ma
ii_breakout | both | tr_breakout_setup
shaved_bar | - | (no match — graceful degradation)
```

### 9.4 Blend formula (Strategy Score enriquecido)

Quando o lookup encontra um match, o Strategy Score final e um blend ponderado:

```
SS_final = SS_llm * 0.6 + SS_pa * 0.4
```

- **0.6 LLM:** preserva a inteligencia contextual do RAG Top-Down 5 camadas
- **0.4 Nogran PA:** ancora numerica em probabilidades verificaveis da KB

Quando nao ha match (`shaved_bar`, setups novos), `SS_final = SS_llm` (degradacao graciosa, zero impacto).

O Decision Scorer recebe `ss = SS_final` e calcula normalmente com os pesos imutaveis. Os 12 testes existentes do Decision Scorer continuam verdes.

### 9.5 Hallucination detector

Quando o gap entre LLM e Nogran PA ultrapassa um limiar, dispara um alarme estruturado:

```
gap = SS_llm - probability_pct (do Nogran PA)

|gap| < 25 -> sem alarme (concordancia)
|gap| 25-39 -> warning (LLM divergiu moderadamente)
|gap| >= 40 -> critical (provavel alucinacao)
```

O alarme e:
1. **Logado** no audit JSONL (`hallucination_alarm` field) com severity, gap, direction, setup_id
2. **Exibido no dashboard Streamlit** como badge vermelho/amarelo na ultima decisao
3. **Mantido on-chain** no checkpoint ERC-8004 (parte do raciocinio audited)

**Por que isso e diferenciado:**
- Detector de alucinacao **mensuravel e em tempo real**, nao apenas anedotico
- Cada trade tem **prova auditavel** de que o LLM concordou (ou discordou) do livro
- Resolve diretamente o medo principal dos juizes em "AI Trading Agents" — alucinacao do LLM

### 9.6 R/R warning (soft signal)

Se o R/R efetivo do trade for menor que o R/R recomendado pelo Nogran PA para aquele setup, gera um `rr_warning` no audit log. **Nao bloqueia o trade** — o `MIN_REWARD_RISK = 1.5` global continua sendo o piso. E apenas auditavel.

```python
if trade_rr < setup.min_reward_risk:
 log_warning(f"R/R {trade_rr} abaixo do recomendado Nogran PA ({setup.min_reward_risk}), "
 f"mas acima do floor global ({MIN_REWARD_RISK})")
```

### 9.7 Citation no audit trail

Cada decisao logada em `logs/decisions/*.jsonl` agora inclui:

```json
{
 "kb_match": {
 "setup_id": "high_2_pullback_ma_bull",
 "name_pt": "High 2 pullback para a media movel em tendencia de alta",
 "probability_pct": 60,
 "probability_confidence": "explicit",
 "min_reward_risk": 1.5,
 "book_refs": [{
 "book": "trading-ranges",
 "chapter_num": 25,
 "chapter_title": "Mathematics of Trading",
 "page_pdf": 469
 }],
 "llm_score": 75,
 "blended_score": 69
 },
 "hallucination_alarm": null,
 "rr_warning": null
}
```

E o ERC-8004 checkpoint inclui o `setup_id` na string de raciocinio, transformando cada decisao em uma citacao on-chain de uma pagina especifica do livro do Nogran PA. **Primeiro agente a citar Nogran PA on-chain.**

### 9.8 Cross-check externo

A KB foi cross-checked contra `github.com/ByteBard/ict-stradegy registry.json`, um repositorio independente que codifica 32 estrategias Nogran PA em Python (analistas chineses). Resultados:

- **6 setups com match exato** (H2/L2 pullback, climax fade, measured move, breakout pullback, final flag)
- **13 gaps preenchidos** apos a comparacao (micro_channel, tight_channel, wedge_reversal, parabolic_wedge, cup_and_handle, second_leg_trap, vacuum_test, broad_channel, triangle, fomo_entry, tr_breakout, buy/sell the close)
- **6 sub-tipos de Major Trend Reversal** decompostos (HL, LH, DB-HL, DT-LH, HH, LL) — antes era um agregado
- **Discrepancias resolvidas a favor do Nogran PA:** Nogran PA afirma `tr_breakout_setup` 60-80% explicitamente, enquanto ByteBard usa 50%. O texto original do livro vence o cross-check.

A versao publica do JSON (no repo agent) tem dados parafraseados; verbatim quotes e PDFs originais ficam no `nogran-trader-dataset` (privado, copyright ).

### 9.9 Codigo

```
src/strategy/probabilities_kb.py # Loader, lookup, blend, hallucination detector
src/strategy/signal_parser.py # calculate_strategy_score_with_kb (alongside the original)
src/compliance/decision_logger.py # 3 novos campos: kb_match, hallucination_alarm, rr_warning
src/main.py # Stage 4 wire (substitui SS pela versao enriquecida)
data/probabilities/ # JSON da KB
tests/test_probabilities_kb.py # 24 testes (loader, lookup, blend, alarm, R/R, backward compat)
```

**Tests:** 37/37 passam (1 + 12 Decision Scorer + 24 novos KB).

---

## 10. INTEGRACAO ERC-8004

### 9.1 TradeIntent com Decision Score

Cada decisao gera um TradeIntent assinado que agora inclui o Decision Score completo:

```python
class TradeIntent:
 def build(self, trade_signal, risk_approval, decision_score, agent_identity):
 return {
 "agent_address": agent_identity.address,
 "intent_id": str(uuid4),
 "timestamp": datetime.utcnow.isoformat,

 # Decisao
 "action": trade_signal.action,
 "symbol": trade_signal.symbol,
 "entry_price": trade_signal.entry_price,
 "stop_loss": risk_approval.adjusted_stop,
 "take_profit": risk_approval.adjusted_target,
 "position_size": risk_approval.position_size,

 # Decision Score (explicabilidade total)
 "decision_score": {
 "total": decision_score.total,
 "threshold": decision_score.threshold,
 "breakdown": decision_score.breakdown,
 "hard_veto": decision_score.hard_veto
 },

 # Contexto
 "strategy_reasoning": {
 "day_type": trade_signal.day_type,
 "always_in": trade_signal.always_in,
 "setup": trade_signal.setup,
 "reasoning": trade_signal.reasoning
 },

 "risk_context": {
 "current_drawdown": risk_approval.current_drawdown,
 "regime": risk_approval.regime,
 "atr": risk_approval.atr,
 "sharpe_rolling": risk_approval.sharpe_rolling
 },

 "learning_loop_state": {
 "current_threshold": decision_score.threshold,
 "current_weights": decision_score.weights,
 "sizing_multiplier": learning_loop.sizing_multiplier,
 "adjustments_count": learning_loop.total_adjustments
 },

 "signature": "EIP-712 signature here"
 }
```

### 9.2 Reputation baseada em Decision Score

```python
class ReputationTracker:
 def calculate(self, trade_history):
 # Performance (40%)
 pnl_score = normalize(total_pnl, -10, 10) # % do capital
 sharpe_score = normalize(sharpe, -2, 3)

 # Consistencia (30%)
 dd_score = 1 - normalize(max_drawdown, 0, 0.15) # Menor DD = melhor
 stability = 1 - std(decision_scores) / 100 # Scores estaveis = melhor

 # Disciplina (20%)
 compliance = count(trades where executed == (score > threshold)) / total
 selectivity = 1 - (trades_per_hour / MAX_TRADES_PER_HOUR)

 # Transparencia (10%)
 all_signed = all(t.has_valid_signature for t in trade_history)
 avg_reasoning_length = mean(len(t.reasoning) for t in trade_history)
 reasoning_score = 1 if avg_reasoning_length > 50 else 0.5

 reputation = (
 (pnl_score * 0.20 + sharpe_score * 0.20) +
 (dd_score * 0.15 + stability * 0.15) +
 (compliance * 0.10 + selectivity * 0.10) +
 (all_signed * 0.05 + reasoning_score * 0.05)
 )

 return int(reputation * 1000) # 0-1000
```

---

## 11. ESTRUTURA DE CODIGO

```
nogran.trader.agent/
├── src/
│ ├── main.py # Entry point
│ │
│ ├── domain/
│ │ ├── models.py # TradeSignal, RiskApproval, DecisionScore, TradeResult
│ │ ├── enums.py # Action, Regime, DayType, SetupType
│ │ └── events.py # CandleClosed, SignalGenerated, OrderFilled
│ │
│ ├── market/
│ │ ├── websocket_client.py # Kraken WS: 1m + 5m
│ │ ├── feature_engine.py # EMA, ATR, ADX, caudas, consecutivas
│ │ ├── candle_buffer.py # Ring buffer (1m e 5m)
│ │ └── pre_filter.py # Chop detector + MQ score
│ │
│ ├── strategy/
│ │ ├── brain.py # HTTP client para LLM
│ │ ├── fact_builder.py # Fato matematico v2
│ │ └── signal_parser.py # Parse + Strategy Score
│ │
│ ├── ai/
│ │ ├── regime_detector.py # TRENDING / RANGING / TRANSITIONING
│ │ ├── confidence_adjuster.py # Multi-TF + regime + volume
│ │ ├── target_optimizer.py # Target por regime e winrate
│ │ ├── overtrading_brake.py # Limite trades/hora
│ │ └── decision_scorer.py # Score composto (4 sub-scores)
│ │
│ ├── risk/
│ │ ├── position_sizer.py # Sizing (ATR + score + drawdown + LL)
│ │ ├── stop_adjuster.py # Stop adaptativo ATR + swing
│ │ ├── drawdown_controller.py # Bandas + circuit breakers
│ │ ├── exposure_manager.py # Max 1 posicao, cooldown, tempo max
│ │ └── metrics.py # Sharpe, DD, winrate, expectancy
│ │
│ ├── learning/
│ │ └── learning_loop.py # Calibracao deterministica pos-trade
│ │
│ ├── compliance/
│ │ ├── agent_identity.py # ERC-721 simulado
│ │ ├── trade_intent.py # TradeIntent + Decision Score + EIP-712
│ │ ├── decision_logger.py # Audit trail JSONL
│ │ └── reputation.py # Score 0-1000 (score-based)
│ │
│ ├── execution/
│ │ ├── order_builder.py # OCO orders
│ │ ├── executor.py # Kraken CLI + retry
│ │ ├── fill_tracker.py # Fills + slippage
│ │ └── pnl_calculator.py # PnL por trade e acumulado
│ │
│ ├── telemetry/
│ │ ├── trade_journal.py # Journal completo
│ │ ├── performance_report.py # Relatorio de metricas
│ │ └── logger.py # Logging estruturado JSON
│ │
│ └── infra/
│ ├── config.py # .env + constantes
│ └── indicators.py # EMA, ATR, ADX, SMA (funcoes puras)
│
├── LLM/
│ └── nogran-trader-agent-LLM.json
│
├── data/chunks/ # JSONs por camada para pgvector
├── logs/decisions/ # Audit trail JSONL
├── logs/learning_adjustments.jsonl # Log de ajustes do Learning Loop
├── tests/
├── scripts/
├── requirements.txt
├── .env.example
├── README.md
├── SETUP.md
└── ARCHITECTURE.md
```

---

## 12. DIFERENCIAL COMPETITIVO

### 12.1 O campo de batalha

A maioria dos agentes de hackathon cai em duas armadilhas:

**Armadilha 1: "LLM decide tudo"**
- O LLM analisa o grafico (ou dados), decide compra/venda, define stop/target
- Resultado: alucinacao inevitavel, sem controle de risco, performance erratica
- Problema: LLMs nao sao bons com numeros e inventam padroes visuais

**Armadilha 2: "Bot quant com IA colada"**
- Bot classico de indicadores com um LLM que gera um "comentario" ou "sentimento"
- A IA e decorativa — remove-la nao muda o resultado
- Problema: nao demonstra uso real de AI para os juizes

### 12.2 Nossa posicao: o terceiro caminho

O nogran.trader.agent nao e nem LLM-first nem quant-first. E um **sistema hibrido com separacao de responsabilidades**:

```
COMPONENTE | QUEM FAZ | POR QUE
-------------------------|-----------------------|--------------------------------
Perceber o mercado | Python (deterministico)| Zero alucinacao — fatos matematicos
Interpretar o mercado | LLM (via RAG Top-Down)| Conhecimento verificavel (Nogran PA)
Filtrar sinais | Python (AI local) | Rapido, gratuito, explicavel
Controlar risco | Python (Risk Engine) | Independente do LLM — capital protegido
Decidir executar | Decision Score | Score composto auditavel
Adaptar parametros | Learning Loop | Deterministico, com guardrails
Rastrear decisoes | ERC-8004 | Transparencia total
```

### 12.3 8 camadas contra alucinacao

```
# | Camada | O que previne
---|----------------------------------|------------------------------------------
1 | Fato matematico (nao grafico) | LLM nao "ve" patterns que nao existem
2 | RAG Top-Down (nao bottom-up) | Contexto macro determina significado micro
3 | 5 tabelas pgvector isoladas | Chunks nao contaminam entre camadas
4 | Temperature 0.1 | Minimiza criatividade (queremos consistencia)
5 | Validador JSON + R/R | Bloqueia output malformado
6 | AI Overlay pos-LLM | Python verifica coerencia com dados reais
7 | Decision Score < 65 = veto | Qualidade insuficiente nao passa
8 | PA KB hallucination detector | Cross-check independente do LLM com 62 setups Nogran PA; alarme em tempo real se gap >= 25 pts
```

### 12.4 Como maximiza risk-adjusted return (Sharpe)

```
Mecanismo | Impacto direto
----------------------------------|----------------------------------
Position sizing por Decision Score| Aposta mais quando o edge e claro
Drawdown bands progressivas | Reduz exposicao antes do desastre
Circuit breakers | Para antes de drawdown catastrofico
Chop filter (MQ score) | Evita trades de expectativa zero
Overtrading brake | Reduz custos e slippage
Regime-aware targets | Targets maiores em trend, menores em range
Multi-TF confirmation | Filtra sinais contra o timeframe maior
Learning Loop | Calibra continuamente por performance
Stop adaptativo ATR | Risco constante em $ por trade
Cooldown adaptativo | Evita revenge trading apos losses
```

### 12.5 Resumo: por que este agente ganha

1. **Uso correto de AI:** LLM interpreta com RAG verificavel, Python filtra e controla risco. Nao e decorativo.
2. **Explicabilidade total:** Decision Score decomposto em 4 sub-scores. Cada trade tem justificativa auditavel.
3. **Risk-adjusted return:** Position sizing por score + drawdown bands + Learning Loop = Sharpe otimizado.
4. **Transparencia ERC-8004:** Cada decisao e assinada, logada, e alimenta reputacao calculavel. Primeiro agente a citar Nogran PA on-chain.
5. **Disciplina extrema:** O agente sabe quando NAO operar — e isso e o alpha principal.
6. **Anti-alucinacao mensuravel:** PA KB com 62 setups + hallucination detector em tempo real. LLM e cross-checked vs livro a cada decisao, com alarme estruturado e citacao auditavel. Resolve o medo central dos juizes em "AI Trading Agents".

---

## 13. PITCH FINAL

> **O problema:** Bots de trading com IA falham porque o LLM alucina padroes que nao existem no grafico, ou porque a IA e apenas um enfeite colado num bot de indicadores. Em ambos os casos, nao ha controle real de risco — o agente opera cegamente ate destruir o capital.

> **A solucao:** O nogran.trader.agent separa quem percebe (Python calcula fatos matematicos), quem interpreta (LLM consulta teoria verificavel do Nogran PA via RAG Top-Down em 5 camadas), quem filtra (AI local detecta regime e ajusta confianca), e quem protege (Risk Engine independente com circuit breakers). O LLM nunca toca dados brutos. O Risk Engine nunca depende do LLM.

> **O diferencial:** Cada trade passa por um Decision Score composto de 4 sub-scores auditaveis — so executa acima de 65/100. Um Learning Loop deterministico calibra thresholds por performance real. Cada decisao gera um TradeIntent assinado (ERC-8004) com rastreabilidade completa. De cada 100 velas, o agente opera 3-5. Essa selectividade extrema e o verdadeiro alpha.

> **A frase que fica:** *O agente mais disciplinado do hackathon. Ele nao ganha por operar mais — ganha por saber quando nao operar.*

---

## 14. ROADMAP DE IMPLEMENTACAO

```
FASE 1 — FUNDACAO (Prioridade maxima)
 [1] domain/models.py + enums.py (30 min)
 [2] infra/config.py + indicators.py (1h)
 [3] market/feature_engine.py (EMA, ATR, ADX, etc.) (2h)
 [4] market/candle_buffer.py (30 min)
 [5] strategy/fact_builder.py (fato v2) (1h)

FASE 2 — RISK ENGINE (Prioridade maxima)
 [6] risk/metrics.py (1h)
 [7] risk/position_sizer.py (1.5h)
 [8] risk/stop_adjuster.py (1h)
 [9] risk/drawdown_controller.py (1h)
 [10] risk/exposure_manager.py (30 min)

FASE 3 — AI LAYER + DECISION SCORE (Prioridade maxima)
 [11] ai/regime_detector.py (1.5h)
 [12] ai/confidence_adjuster.py (1h)
 [13] ai/overtrading_brake.py (30 min)
 [14] ai/decision_scorer.py (1.5h)
 [15] market/pre_filter.py (MQ score) (1h)

FASE 4 — LEARNING LOOP (Prioridade alta)
 [16] learning/learning_loop.py (2h)

FASE 5 — INTEGRACAO (Prioridade alta)
 [17] Refatorar market_data.py -> websocket_client.py (1h)
 [18] Refatorar brain.py -> strategy/* (1h)
 [19] Refatorar execution.py -> execution/* (1.5h)
 [20] main.py: pipeline completo com scoring (2h)

FASE 6 — ERC-8004 (Prioridade alta)
 [21] compliance/agent_identity.py (1h)
 [22] compliance/trade_intent.py (com Decision Score)(1.5h)
 [23] compliance/decision_logger.py (1h)
 [24] compliance/reputation.py (score-based) (1h)

FASE 7 — TELEMETRIA + POLISH (Prioridade media)
 [25] telemetry/trade_journal.py (1h)
 [26] telemetry/performance_report.py (1h)
 [27] scripts/replay.py (2h)
 [28] Atualizar README.md e SETUP.md (1h)

FASE 8 — INGESTAO E DADOS (Paralelo)
 [29] Reestruturar chunks em 5 JSONs por camada (3h)
 [30] scripts/ingest_chunks.py para 5 tabelas (1h)
 [31] Testar RAG no LLM com dados reais (2h)
```

**Se o tempo for curto, priorize:** Fases 1-3 + Fase 5 (integracao). O Decision Score + Risk Engine sao o maior diferencial. Learning Loop e ERC-8004 podem ser simplificados sem perder a essencia.
