# NOGRAN.TRADER.AGENT v3 — Full Architecture

> Final design for the AI Trading Agents hackathon.
> Evolution: v1 (basic RAG) → v2 (Risk Engine + AI Layer) → v3 (Decision Scoring + Learning Loop + explicit alpha).

---

## 1. SYSTEM OVERVIEW

nogran.trader.agent operates in **5 sequential stages with independent vetoes and unified scoring**:

```
PERCEPTION --> INTERPRETATION --> AI OVERLAY --> RISK --> EXECUTION
 (Python)      (RAG/LLM)         (Python)       (Python)  (Python)
    |             |                  |             |          |
    v             v                  v             v          v
 [Market      [Strategy          [AI Overlay    [Risk      [Execution
  Quality      Score]              Score]        Score]      Gate]
  Score]            \                |            /
                     \               |           /
                      v              v          v
                  ┌─────────────────────────────────┐
                  │   DECISION SCORE (0-100)        │
                  │   Executes ONLY if score > 65   │
                  └─────────────────────────────────┘
                                  |
                                  v
                  ┌─────────────────────────────────┐
                  │   ERC-8004 LAYER                │
                  │   TradeIntent + Log + Reputation│
                  └─────────────────────────────────┘
```

**Core principle:** No single layer can force a trade. Each stage contributes a sub-score. The unified Decision Score is the final gate. The LLM never touches raw data. The Risk Engine never depends on the LLM.

### v2 → v3 evolution

| Aspect | v2 | v3 |
|---|---|---|
| Execution criterion | LLM confidence > 40 + Risk approved | Composite Decision Score > 65 |
| Explainability | LLM textual reason | Score decomposed into 4 auditable sub-scores |
| Adaptation | Fixed parameters | Learning Loop tunes thresholds against performance |
| Edge (alpha) | Implicit in the RAG | Explicit: 4 documented alpha sources |
| References | None | Mapped per component with what was used / ignored |
| Reputation | Generic 0–1000 score | Driven by historical Decision Score |

---

## 2. DETAILED ARCHITECTURE

```
                MARKET DATA LAYER
        ┌─────────────────────────────┐
        │  Kraken WebSocket           │
        │  BTC/USD 15m + 1h HTF       │
        └──────────┬──────────────────┘
                   │
        ┌──────────▼──────────────────┐
        │  FEATURE ENGINE             │
        │  (Python - local)           │
        │                             │
        │  OHLCV parser               │
        │  EMA(20) calculator         │
        │  ATR(14) calculator         │
        │  ADX(14) calculator         │
        │  Candle classifier          │
        │  Bar counting               │
        │  Tail/body ratios           │
        │  Volume delta               │
        │  Consecutive tracker        │
        │  Swing structure (HH/HL)    │
        │  Failed-attempt tracker     │
        │  EMA test detection         │
        │  Always-in (computed)       │
        │  1h HTF aggregation         │
        │                             │
        │  Output: FeatureSnapshot    │
        └──────────┬──────────────────┘
                   │
        ┌──────────▼──────────────────┐
        │  PRE-FILTER + MQ SCORE      │
        │  (Python - local)           │
        │                             │
        │  Chop detector              │
        │  Volatility gate            │
        │  Session filter             │
        │  Cooldown timer             │
        │                             │
        │  Output: market_quality     │
        │          score (0-100)      │
        │  VETO if MQ < 30            │
        └──────────┬──────────────────┘
                   │ (only passes if MQ >= 30)
                   │
        ┌──────────▼──────────────────┐
        │  STRATEGY ENGINE            │
        │  (Python LLM, Top-Down RAG) │
        │                             │
        │  Layer 1: Day Type          │
        │  Layer 2: Macro / Always-In │
        │  Layer 3: Structure         │
        │  Layer 4: Micro / Bar       │
        │  Layer 5: Setup / Trigger   │
        │                             │
        │  Output: TradeSignal +      │
        │          strategy_score 0-100│
        └──────────┬──────────────────┘
                   │
        ┌──────────▼──────────────────┐
        │  PA KB ENRICHMENT           │
        │  blend (LLM 60% + PA 40%)   │
        │  hallucination detector     │
        │                             │
        │  Output: enriched SS +      │
        │          structured alarm   │
        └──────────┬──────────────────┘
                   │
        ┌──────────▼──────────────────┐
        │  AI OVERLAY                 │
        │  (Python - local)           │
        │                             │
        │  Regime classifier          │
        │  Confidence adjuster        │
        │  Multi-TF confirmation      │
        │  Target optimizer           │
        │  Overtrading brake          │
        │                             │
        │  Output: ai_overlay_score   │
        │          (0-100)            │
        └──────────┬──────────────────┘
                   │
        ┌──────────▼──────────────────┐
        │  RISK ENGINE                │
        │  (Python - local)           │
        │                             │
        │  Position sizer             │
        │  Drawdown controller        │
        │  Exposure manager           │
        │  Stop adjuster              │
        │  Circuit breakers           │
        │                             │
        │  Output: RiskApproval +     │
        │          risk_score (0-100) │
        └──────────┬──────────────────┘
                   │
        ┌──────────▼──────────────────┐
        │  DECISION SCORER            │
        │  (Python - local)           │
        │                             │
        │  Combines 4 sub-scores      │
        │  Applies adaptive weights   │
        │  Threshold: score > 65      │
        │                             │
        │  Output: DecisionScore      │
        │  {total, breakdown, go/nogo}│
        └──────────┬──────────────────┘
                   │
        ┌──────────▼──────────────────┐
        │  ERC-8004 LAYER             │
        │                             │
        │  TradeIntent + score        │
        │  EIP-712 signer             │
        │  Decision logger            │
        │  Reputation (score-based)   │
        └──────────┬──────────────────┘
                   │
        ┌──────────▼──────────────────┐
        │  EXECUTION ENGINE           │
        │  (Python - Kraken CLI)      │
        │                             │
        │  OCO order builder          │
        │  Order lifecycle mgr        │
        │  Fill tracker               │
        │  PnL calculator             │
        └──────────┬──────────────────┘
                   │
        ┌──────────▼──────────────────┐
        │  LEARNING LOOP              │
        │  (Python - post-trade)      │
        │                             │
        │  Updates metrics            │
        │  Tunes thresholds           │
        │  Feeds reputation           │
        └──────────┬──────────────────┘
                   │
        ┌──────────▼──────────────────┐
        │  TELEMETRY                  │
        │                             │
        │  Trade journal (JSONL)      │
        │  Performance metrics        │
        │  ERC-8004 audit trail       │
        │  Decision Score history     │
        └─────────────────────────────┘
```

### Veto flow (any stage can stop a trade)

```
Pre-Filter VETO       --> "MQ score 22/100 — market in chop" (no API spend)
Strategy VETO         --> "AGUARDAR — signal bar rejected" (Price Action)
AI Overlay VETO       --> "Regime TRANSITIONING, confidence < 40" (local filter)
Risk Engine VETO      --> "Drawdown 6.2%, circuit breaker active" (capital protection)
Decision Score VETO   --> "Score 58/100 < threshold 65" (insufficient quality)
```

---

## 3. DECISION SCORING SYSTEM

### 3.1 Concept

The Decision Score is the single number that determines whether a trade happens. Instead of a binary "LLM said buy / Risk Engine approved", every layer contributes a sub-score from 0–100, and the composite final score is the execution criterion.

**Why this matters:**
- **Explainability:** any trade (executed or vetoed) can be explained by its 4 sub-scores
- **Audit:** the ERC-8004 TradeIntent includes the decomposed score — judges see exactly why each decision was made
- **Calibration:** the Learning Loop tunes thresholds based on the historical score-vs-outcome record
- **Reputation:** the historical mean score directly feeds the reputation tracker

### 3.2 Sub-scores

```
SUB-SCORE                | SOURCE         | WHAT IT MEASURES                          | RANGE
-------------------------|----------------|-------------------------------------------|-------
Market Quality (MQ)      | Pre-Filter     | How tradeable the market is               | 0-100
Strategy Score (SS)      | Strategy Engine| Setup quality per the Nogran PA KB        | 0-100
AI Overlay Score (AO)    | AI Layer       | Confirmation by regime, volume, multi-TF  | 0-100
Risk Score (RS)          | Risk Engine    | Capital health and risk feasibility       | 0-100
```

### 3.3 Computing each sub-score

**Market Quality Score (MQ):**

```python
def calculate_mq_score(features: FeatureSnapshot) -> int:
    score = 100

    # Chop penalty: bar overlap
    overlap = features.bar_overlap_ratio  # 0.0 to 1.0
    if overlap > 0.7:
        score -= 40   # Severe chop
    elif overlap > 0.5:
        score -= 20   # Moderate chop

    # Volatility: ATR vs its mean
    atr_ratio = features.atr / features.atr_sma20
    if atr_ratio < 0.5:
        score -= 30   # Dead market
    elif atr_ratio < 0.8:
        score -= 15   # Low volatility

    # Direction flips (noise)
    direction_changes = features.direction_change_ratio  # 0.0 to 1.0
    if direction_changes > 0.6:
        score -= 20

    # Bonus for high-liquidity session
    if features.is_peak_session:  # 13:00-21:00 UTC
        score += 10

    return clamp(score, 0, 100)
```

**Strategy Score (SS):**

The LLM already returns `confidence` (0–100) in its JSON. The Strategy Score uses that as a baseline but penalises inconsistencies:

```python
def calculate_ss_score(trade_signal: TradeSignal) -> int:
    score = trade_signal.confidence   # LLM baseline

    # Penalise if signal bar is rejected but the LLM still suggests a trade
    if trade_signal.signal_bar_quality == "REPROVADO" and trade_signal.action != "AGUARDAR":
        score -= 30

    # Penalise weak setups in the Nogran PA hierarchy
    setup_quality = {
        "second_entry_H2": 0,    # Best — no penalty
        "breakout_pullback": -5,
        "H2_ema": -10,
        "ii_breakout": -15,
        "shaved_bar": -20,
        "none": -50
    }
    score += setup_quality.get(trade_signal.setup, -25)

    # Bonus when day type is clear (not undefined)
    if trade_signal.day_type != "indefinido":
        score += 5

    return clamp(score, 0, 100)
```

**AI Overlay Score (AO):**

```python
def calculate_ao_score(trade_signal, features, regime, recent_trades) -> int:
    score = 70   # Neutral baseline

    # Regime alignment
    trending_setups = ["second_entry_H2", "breakout_pullback", "shaved_bar"]
    if regime == "TRENDING" and trade_signal.setup in trending_setups:
        score += 15   # Aligned
    elif regime == "TRENDING" and trade_signal.action == "VENDA" and trade_signal.setup not in trending_setups:
        score -= 15   # Counter-trend in a strong trend
    elif regime == "TRANSITIONING":
        score -= 20   # Uncertainty

    # Multi-TF confirmation
    if features.tf_1h_direction == trade_signal.action:
        score += 10   # 1h confirms
    elif features.tf_1h_direction is not None and features.tf_1h_direction != trade_signal.action:
        score -= 15   # 1h contradicts

    # Volume
    if features.volume_ratio > 1.2:
        score += 5   # Above-average volume
    elif features.volume_ratio < 0.5:
        score -= 10  # Very low volume

    # ATR expansion (real breakout vs fake)
    if features.atr_expanding:
        score += 5
    elif features.atr_contracting:
        score -= 10

    # Revenge trade penalty
    if len(recent_trades) > 0:
        last = recent_trades[-1]
        if last.pnl < 0 and last.side == trade_signal.action:
            score -= 10  # Same side as the last loss

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

    # Drawdown penalty (progressive scale)
    if drawdown > 0.08:
        score = 0    # Circuit breaker
    elif drawdown > 0.05:
        score -= 50  # Minimum mode
    elif drawdown > 0.03:
        score -= 25  # Defensive mode

    # Trader's Equation
    risk = abs(trade_signal.entry_price - trade_signal.stop_loss)
    reward = abs(trade_signal.take_profit - trade_signal.entry_price)
    rr = reward / risk if risk > 0 else 0
    if rr < 1.5:
        score = 0    # Hard veto
    elif rr < 2.0:
        score -= 10
    elif rr >= 3.0:
        score += 10  # Excellent R/R

    # Rolling Sharpe
    if metrics.sharpe_rolling < -1.0:
        score -= 30
    elif metrics.sharpe_rolling < 0:
        score -= 15
    elif metrics.sharpe_rolling > 1.0:
        score += 10

    # Consecutive losses
    if metrics.consecutive_losses >= 3:
        score -= 25

    # Position viability (minimum size)
    min_size = calculate_min_viable_size(capital, atr)
    if min_size < MIN_ORDER_SIZE:
        score = 0    # Insufficient capital to operate

    return clamp(score, 0, 100)
```

### 3.4 Decision Score formula

```python
class DecisionScorer:
    """
    Combines the 4 sub-scores into a single final score.
    Weights are adaptive (tuned by the Learning Loop).
    """

    # Initial weights (sum to 1.0)
    DEFAULT_WEIGHTS = {
        "market_quality": 0.20,  # 20% — is the market tradeable?
        "strategy":       0.35,  # 35% — does Price Action approve?
        "ai_overlay":     0.20,  # 20% — does the AI confirm?
        "risk":           0.25,  # 25% — is the capital healthy?
    }

    EXECUTION_THRESHOLD = 65   # Only executes when score > 65

    def calculate(self, mq, ss, ao, rs, weights=None) -> DecisionScore:
        w = weights or self.DEFAULT_WEIGHTS

        total = (
            mq * w["market_quality"] +
            ss * w["strategy"] +
            ao * w["ai_overlay"] +
            rs * w["risk"]
        )

        # Hard veto: if ANY sub-score < 20, do not execute
        hard_veto = any(s < 20 for s in [mq, ss, ao, rs])

        return DecisionScore(
            total=round(total, 1),
            go=total >= self.EXECUTION_THRESHOLD and not hard_veto,
            breakdown={
                "market_quality": {"score": mq, "weight": w["market_quality"]},
                "strategy":       {"score": ss, "weight": w["strategy"]},
                "ai_overlay":     {"score": ao, "weight": w["ai_overlay"]},
                "risk":           {"score": rs, "weight": w["risk"]},
            },
            threshold=self.EXECUTION_THRESHOLD,
            hard_veto=hard_veto
        )
```

### 3.5 Decision examples

```
EXAMPLE 1: Trade executed (score 78.5)
──────────────────────────────────────
  Market Quality: 85 x 0.20 = 17.0   (trending, healthy ATR)
  Strategy:       82 x 0.35 = 28.7   (Second Entry H2, clear day type)
  AI Overlay:     75 x 0.20 = 15.0   (regime aligned, HTF confirms)
  Risk:           71 x 0.25 = 17.8   (drawdown 1.5%, R/R 2.1)
  ────────────────────────────────
  TOTAL: 78.5 > 65 --> EXECUTE
  Hard veto: no sub-score < 20

EXAMPLE 2: Trade vetoed (score 52.3)
──────────────────────────────────────
  Market Quality: 42 x 0.20 = 8.4    (high overlap, low ATR)
  Strategy:       70 x 0.35 = 24.5   (setup OK but day undefined)
  AI Overlay:     45 x 0.20 = 9.0    (regime transitioning, HTF against)
  Risk:           41 x 0.25 = 10.3   (drawdown 4.1%, sizing reduced)
  ────────────────────────────────
  TOTAL: 52.3 < 65 --> AGUARDAR
  Reason: insufficient score (MQ and AO weak)

EXAMPLE 3: Trade vetoed by hard veto (score 56.5)
──────────────────────────────────────
  Market Quality: 80 x 0.20 = 16.0
  Strategy:       15 x 0.35 = 5.3   <-- HARD VETO (< 20)
  AI Overlay:     70 x 0.20 = 14.0
  Risk:           85 x 0.25 = 21.3
  ────────────────────────────────
  TOTAL: 56.5 --> AGUARDAR (Strategy hard veto)
  Reason: LLM had very low confidence in the setup
```

### 3.6 How the Decision Score connects to ERC-8004

Every TradeIntent now includes the decomposed score:

```json
{
  "intent_id": "uuid-here",
  "decision_score": {
    "total": 78.5,
    "threshold": 65,
    "executed": true,
    "breakdown": {
      "market_quality": {"score": 85, "weight": 0.20, "contribution": 17.0},
      "strategy":       {"score": 82, "weight": 0.35, "contribution": 28.7},
      "ai_overlay":     {"score": 75, "weight": 0.20, "contribution": 15.0},
      "risk":           {"score": 71, "weight": 0.25, "contribution": 17.8}
    },
    "hard_veto": false
  }
}
```

This lets:
- **Judges** see exactly why every trade happened
- **Reputation** be computed over historical scores (not just PnL)
- **Audits** verify the agent followed its own criteria

---

## 4. LEARNING LOOP (ADAPTIVE) — PLANNED, NOT YET IMPLEMENTED

> **Status:** `src/learning/` is empty. The section below describes the planned design for v3.
> The current code does NOT implement any of the functionality below.

### 4.1 Principle

The Learning Loop does NOT use heavy ML. It is a **deterministic calibration system** that adjusts operational parameters based on recent performance metrics. Fully explainable — every adjustment has a clear rule and a documented motivation.

### 4.2 What the Learning Loop adjusts

```
Parameter                 | Adjustment mechanism             | Frequency
--------------------------|----------------------------------|------------------
Execution threshold       | Up if win rate < 35%             | Every 10 trades
                          | Down if win rate > 55%           |
Decision Score weights    | Increase weight of sub-scores    | Every 20 trades
                          | with the best PnL correlation    |
Position sizing base      | Reduces if drawdown rising       | Every trade
                          | Increases at equity ATH          |
Max trades / hour         | Reduces if overtrading detected  | Every hour
Minimum R/R               | Up if win rate < 40%             | Every 10 trades
Post-trade cooldown       | Up after 3 consecutive losses    | Every trade
```

### 4.3 Implementation

```python
class LearningLoop:
    """
    Deterministic post-trade calibration.
    No ML, no black box. Every adjustment is a documented if/then rule.
    """

    def __init__(self, decision_scorer: DecisionScorer):
        self.scorer = decision_scorer
        self.trade_history = []

    def on_trade_closed(self, trade_result):
        """Called whenever a trade closes (win or loss)."""
        self.trade_history.append(trade_result)

        # Only tune after a minimum window (avoids overfitting to noise)
        if len(self.trade_history) < 10:
            return

        recent = self.trade_history[-20:]   # 20-trade window
        metrics = self._compute_metrics(recent)

        self._adjust_threshold(metrics)
        self._adjust_weights(metrics)
        self._adjust_sizing(metrics)
        self._adjust_cooldown(metrics)

    def _adjust_threshold(self, metrics):
        """
        If we're losing too much, demand higher-quality trades.
        If we're winning consistently, we can relax slightly.
        """
        current = self.scorer.EXECUTION_THRESHOLD

        if metrics.win_rate < 0.35:
            # Losing a lot -> raise the bar
            new_threshold = min(current + 3, 80)   # Cap at 80
            reason = f"Win rate {metrics.win_rate:.0%} < 35% — raising the bar"
        elif metrics.win_rate > 0.55 and metrics.sharpe > 0.5:
            # Winning well -> relax slightly
            new_threshold = max(current - 2, 55)   # Floor at 55
            reason = f"Win rate {metrics.win_rate:.0%} > 55% with Sharpe {metrics.sharpe:.1f} — relaxing"
        else:
            return   # No adjustment

        self.scorer.EXECUTION_THRESHOLD = new_threshold
        self._log_adjustment("threshold", current, new_threshold, reason)

    def _adjust_weights(self, metrics):
        """
        Computes a simple correlation between each sub-score and the trade outcome.
        Sub-scores that better predict wins gain more weight.
        """
        # Spearman rank correlation between each sub-score and PnL
        correlations = {}
        for key in ["market_quality", "strategy", "ai_overlay", "risk"]:
            scores = [t.decision_score.breakdown[key]["score"] for t in metrics.trades]
            pnls = [t.pnl for t in metrics.trades]
            correlations[key] = spearman_correlation(scores, pnls)

        # Normalise correlations to weights (sum = 1.0)
        total_corr = sum(max(c, 0.05) for c in correlations.values())  # 0.05 floor
        new_weights = {k: max(c, 0.05) / total_corr for k, c in correlations.items()}

        # Apply with smoothing (80% old + 20% new)
        for key in new_weights:
            old = self.scorer.weights[key]
            self.scorer.weights[key] = old * 0.8 + new_weights[key] * 0.2

        self._log_adjustment("weights", None, self.scorer.weights, "Score-PnL correlation")

    def _adjust_sizing(self, metrics):
        """Adjusts the base position sizing according to the equity curve."""
        if metrics.drawdown > 0.05:
            self.sizing_multiplier = 0.5
        elif metrics.drawdown > 0.03:
            self.sizing_multiplier = 0.7
        elif metrics.equity_at_ath:
            self.sizing_multiplier = min(self.sizing_multiplier + 0.05, 1.0)

    def _adjust_cooldown(self, metrics):
        """Increases cooldown after consecutive losses."""
        if metrics.consecutive_losses >= 3:
            self.cooldown_candles = 5   # 5 min
        elif metrics.consecutive_losses >= 2:
            self.cooldown_candles = 3   # 3 min
        else:
            self.cooldown_candles = 2   # default

    def _log_adjustment(self, param, old_value, new_value, reason):
        """Log every adjustment in the audit trail — full transparency."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "parameter": param,
            "old_value": old_value,
            "new_value": new_value,
            "reason": reason,
            "trade_count": len(self.trade_history)
        }
        with open("logs/learning_adjustments.jsonl", "a") as f:
            f.write(json.dumps(log_entry) + "\n")
```

### 4.4 Safety guardrails

```
Parameter                 | Min    | Max    | Justification
-------------------------|--------|--------|---------------------------
Execution threshold       | 55     | 80     | Below 55 = accepts garbage. Above 80 = never trades.
Weight of any sub-score   | 0.10   | 0.50   | No score dominates alone.
Position sizing mult.     | 0.3    | 1.0    | Never above 100% of base sizing.
Cooldown candles          | 2      | 10     | Minimum 2 minutes between trades.
Minimum R/R               | 1.5    | 3.0    | Below 1.5 = mathematically bad.
Max trades / hour         | 2      | 6      | Hard overtrading limits.
```

These guardrails guarantee the Learning Loop **never** destabilises the system. It calibrates inside safe ranges — it does not reinvent the strategy.

---

## 5. SYSTEM ALPHA (EDGE)

### 5.1 What "alpha" means here

Alpha is the agent's systematic edge over the market. With no alpha, any bot loses money over the long run (commissions + slippage > random return). nogran.trader.agent has **4 complementary alpha sources**:

### 5.2 Source 1: Repetitive behaviour in price action

**Thesis:** Crypto on low timeframes (1m–15m) shows price action patterns that repeat with statistical significance. These patterns have been documented for decades in price action literature.

**How we exploit it:** The Top-Down RAG queries the Nogran PA KB across 5 ordered layers, applying setup-specific rules per context. The LLM does not "invent" patterns — it recognises patterns already catalogued by the methodology.

**Why it works in crypto:** Crypto has heavy bot and retail participation, which produces repetitive price action patterns (spikes, climaxes, failed breakouts). These are the same patterns the methodology documents in futures — the microstructure is similar.

**Quantifiable:** The top-tier setup (Second Entry) has a documented 60–70% hit rate. Combined with a minimum R/R of 1.5, the mathematical expectation is positive.

### 5.3 Source 2: Superior filtering of bad signals

**Thesis:** Most bots lose money not because they lack good signals, but because they execute bad ones. The alpha comes from NOT trading when the market offers no edge.

**How we exploit it:** The 5-stage pipeline with independent vetoes filters aggressively:
- The pre-filter eliminates ~40–60% of candles (chop, low volatility, bad session)
- Strategy eliminates ~60–70% of remaining signals (rejected signal bar, weak setup)
- AI Overlay eliminates ~20–30% of those that pass (regime conflict, revenge trade)
- Risk Engine eliminates the final ~10–20% (drawdown, sizing infeasibility)
- Decision Score makes the final cut (< 65)

**Estimated outcome:** Out of every 100 candles analysed, the agent trades ~3–5. That is an extreme selectivity rate that preserves capital.

### 5.4 Source 3: Risk management as alpha

**Thesis:** Dynamic position sizing and drawdown control generate real alpha — they don't just protect capital. Betting more when the edge is clear and less when it isn't beats fixed sizing.

**How we exploit it:**
- Sizing proportional to the Decision Score: score 75 = full sizing, score 65 = minimum sizing
- Drawdown bands reduce exposure progressively (not binary)
- Adaptive ATR stops keep the dollar risk constant regardless of volatility
- Targets optimised by regime: more aggressive in trends, conservative in ranges

**Quantifiable:** A simplified Kelly criterion with 55% win rate and 2.0 R/R suggests sizing around 15% of capital per trade. Our drawdown bands cap that at 1–2% risk per trade, trading growth for survival (the priority for the hackathon).

### 5.5 Source 4: Time as a filter (not trading is a position)

**Thesis:** In relatively high-frequency trading (15m candles), most of the time the market is in chop — trading then destroys PnL. The alpha comes from waiting.

**How we exploit it:**
- Chop detector: avoids sideways no-direction markets
- Post-trade cooldown: prevents revenge trading and emotional overtrading
- Circuit breakers: stops before catastrophic drawdown
- Overtrading brake: caps trades/hour for discipline

**Result:** The agent spends most of its time in AGUARDAR (wait) mode. That is by design — every trade we DO NOT take in a choppy market is preserved capital.

---

## 6. TECHNICAL REFERENCES AND INSPIRATION

### 6.1 Reference usage principle

This project uses external references as a **source of ideas and validation**, not as a template. Each reference was evaluated and only specific components were leveraged — the architecture, the strategy, and the integration are original.

### 6.2 Per-component map

```
COMPONENT                   | REFERENCE            | WHAT WE KEPT                    | WHAT WE IGNORED / ADAPTED
----------------------------|----------------------|---------------------------------|-----------------------------
Feature Engineering         | Qlib (Microsoft)     | Concept of features as pure     | The whole framework, because
(market/feature_engine.py)  |                      | functions over OHLCV.           | our scope is 3 indicators
                            |                      | Data/logic separation.          | (EMA, ATR, ADX), not 158.
                            |                      |                                 | Qlib is for portfolios; we
                            |                      |                                 | trade a single pair.
                            |                      |                                 |
Risk Metrics                | pyfolio / ffn        | Sharpe, max drawdown, profit    | Visualisation and tear sheets.
(risk/metrics.py)           |                      | factor formulas. Industry-      | Our calculation is rolling and
                            |                      | standard definitions.           | real-time, not post-hoc.
                            |                      |                                 | We don't use returns-based
                            |                      |                                 | analysis (ours is trade-based).
                            |                      |                                 |
Execution Layer             | freqtrade            | Order lifecycle pattern:        | The whole framework. Freqtrade
(execution/*)               |                      | create -> fill -> track ->      | is a complete bot with
                            |                      | close. OCO concept.             | backtesting, UI, plugins.
                            |                      | CCXT as adapter.                | We use Kraken CLI (subprocess)
                            |                      |                                 | for execution.
                            |                      |                                 |
ERC-8004 / Smart Contracts  | OpenZeppelin         | EIP-712 signing patterns.       | Solidity contracts.
(compliance/*)              |                      | Metadata hash concept for       | We sign in Python because the
                            |                      | identity. TradeIntent struct    | hackathon does not require
                            |                      | inspired by ERC-721 metadata.   | on-chain deployment.
                            |                      |                                 | Reputation is computed locally,
                            |                      |                                 | not in a contract.
                            |                      |                                 |
RAG Top-Down                | Nogran PA KB         | All of the price action theory. | Narrative chapters, psychology,
(strategy/*)                | (in-house) +         | The 5-layer hierarchy is an     | ETFs.
                            | original design      | ORIGINAL design of the project. | The 5-layer architecture is
                            |                      |                                 | our own invention.
                            |                      |                                 |
Regime Detection            | Academic papers      | Concept of regime switching     | HMM and complex statistical
(ai/regime_detector.py)     | (Hamilton 1989,      | in financial markets.           | models. Our detector is rule-
                            | Ang & Bekaert 2002)  | ADX as a proxy.                 | based with ADX + ATR + overlap
                            |                      |                                 | (faster, more explainable, no
                            |                      |                                 | training needed).
                            |                      |                                 |
Decision Scoring            | Credit scoring       | Composite score with weighted   | ML-based scoring. Ours is
(ai/decision_scorer.py)     | (financial industry) | sub-scores. Threshold cutoff.   | deterministic with adaptive
                            |                      | Hard veto concept.              | weights (not trained).
```

### 6.3 What we did NOT use

```
Reference            | Why not
---------------------|-------------------------------------------------------
Reinforcement Learn. | Requires millions of training episodes. The hackathon
                     | has limited time. Not explainable. Our edge comes from
                     | verifiable rules, not policy gradient.
                     |
Sentiment Analysis   | Sentiment data is noisy and lagging. Price action
                     | already incorporates sentiment (the price IS the
                     | market consensus). Adding sentiment is redundant.
                     |
LLM as sole          | Hallucination. Latency. Cost. Inconsistency.
decision-maker       | The LLM is an interpretation component, not the brain.
                     |
Heavy backtesting    | Hackathon time does not allow a robust backtest.
                     | We prefer rules with documented theoretical edge
                     | (Nogran PA KB) + replay validation against canonical
                     | price action figures.
                     |
Multi-asset          | Unnecessary complexity. A single pair (BTC/USD)
                     | enables full focus and deep optimisation.
```

---

## 7. RISK ENGINE (DETAILED)

### 7.1 Dynamic position sizing

```python
def calculate_position_size(capital, atr, decision_score, drawdown):
    # 1. Base risk: 1.5% of capital
    base_risk_pct = 0.015

    # 2. Scale by Decision Score (65-100 -> 0.6x to 1.0x)
    score_multiplier = map_range(decision_score.total, 65, 95, 0.6, 1.0)

    # 3. Scale by drawdown (progressive bands)
    dd_multiplier = 1.0
    if drawdown > 0.05:
        dd_multiplier = 0.3
    elif drawdown > 0.03:
        dd_multiplier = 0.6

    # 4. Learning Loop multiplier
    ll_multiplier = learning_loop.sizing_multiplier   # 0.3 to 1.0

    # 5. Stop distance via ATR
    stop_distance = atr * 1.5
    risk_in_dollars = capital * base_risk_pct

    position_size = (risk_in_dollars / stop_distance) \
                    * score_multiplier \
                    * dd_multiplier \
                    * ll_multiplier

    return clamp(position_size, MIN_SIZE, MAX_SIZE)
```

### 7.2 Drawdown controller

```
Drawdown bands:
   0% to 3%   --> Normal       (100% sizing, threshold 65)
   3% to 5%   --> Defensive    (60% sizing, threshold +5, only best setups)
   5% to 8%   --> Minimum      (30% sizing, threshold +10)
   > 8%       --> CIRCUIT BREAKER: stops for 15 min, resumes gradually
```

### 7.3 Adaptive stop

```python
def calculate_adaptive_stop(entry_price, side, atr, features):
    # Base: 1.5x ATR
    base_stop = atr * 1.5

    # Adjust by bar type
    if features.body_pct > 70:        # Strong trend bar
        stop_distance = atr * 1.2     # Tight (clear momentum)
    elif features.body_pct < 30:      # Doji / indecision
        stop_distance = atr * 2.0     # Wide (more noise)
    else:
        stop_distance = base_stop

    # Structural anchor (swing point)
    structural_stop = find_nearest_swing(side, features.recent_bars)
    if structural_stop:
        stop_distance = max(stop_distance, abs(entry_price - structural_stop) * 1.05)

    return entry_price - stop_distance if side == 'buy' else entry_price + stop_distance
```

### 7.4 Circuit breakers

```
Trigger                          | Action
---------------------------------|----------------------------------------
3 consecutive losses             | 15-minute cooldown (tunable by the LL)
Drawdown > 8% of capital         | Stops trading, resumes gradually
Rolling Sharpe < -1.0            | Risk Score drops < 20 (hard veto)
LLM latency > 10s                | AGUARDAR (stale data)
Kraken CLI execution error       | 1 retry, then stop and alert
Open position > 32 candles (8h)  | Force close at market
```

### 7.5 Real-time metrics

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

## 8. AI LAYER (DETAILED)

### 8.1 Regime detector

```python
class RegimeDetector:
    def classify(self, bars_15m, bars_1h):
        adx = calculate_adx(bars_15m, period=14)
        atr_ratio = current_atr / sma(atr_values, 20)
        bar_overlap = calculate_overlap_ratio(bars_15m[-10:])

        if adx > 25 and atr_ratio > 1.1 and bar_overlap < 0.4:
            return "TRENDING"
        elif adx < 20 and bar_overlap > 0.6:
            return "RANGING"
        else:
            return "TRANSITIONING"
```

### 8.2 Multi-timeframe confirmation

```
1h (confirmation):
  - Aggregated from 15m exec buffer (group_size=4)
  - Computes EMA(20), ATR(14), direction, consecutive bars, ADX
  - Does NOT call the LLM (cost/latency saving)
  - Contributes to the AI Overlay Score

15m (execution):
  - On every closed candle, generates a mathematical fact
  - Includes the 1h context in the fact sent to the LLM
  - Receives the decision and runs through the full pipeline
```

### 8.3 Mathematical fact v2 (enriched)

```
"Candle 15m #47 closed BULL.
 OHLCV: O=$67822.0 H=$67890.5 L=$67810.2 C=$67859.3 V=12.4 BTC.
 Body: 80.3% of range. Upper tail: 7.2%. Lower tail: 12.5%.
 Trend: 3 consecutive bull bars.
 EMA(20): $67801.0. Price above EMA. Distance: +0.09%.
 ATR(14): $45.2. ATR vs mean: 1.15 (normal-high volatility).
 1h context: last candle BULL, price above 1h EMA(20), 2 consecutive bull bars, 1h ADX 22.
 Detected regime: TRENDING."
```

---

## 9. NOGRAN PA KNOWLEDGE BASE & HALLUCINATION DETECTOR

### 9.1 Concept

An enrichment layer that combines the LLM (Strategy Engine) with a **structured knowledge base of 62 Nogran PA setups**, acting as an independent cross-check to detect and audit LLM hallucinations in real time.

It runs in Stage 4 of the pipeline (after the LLM returns and before the AI Overlay). It does NOT alter the Decision Scorer logic (per CLAUDE.md rule: weights MQ 20%, SS 35%, AO 20%, RS 25% are inviolable).

### 9.2 The knowledge base

`data/probabilities/pa_probabilities.json` (62 setups + 22 hard rules)

Each setup carries:
- `setup_id`, `name_en`, `name_pt`
- `category` (trend_continuation | breakout | reversal | range_fade | scalp | anti_pattern)
- `direction` (long | short | both)
- `context` (list of conditions — bull_trend, after_pullback_to_ma, etc.)
- `probability_pct` (base figure)
- `probability_range` ([min, max])
- `probability_confidence` (explicit | implied | inferred)
- `min_reward_risk` (recommended R/R for that setup)
- `notes_pt` (paraphrased description in Portuguese)

**Origin:** curated in-house, with cross-checks against public open-source price action references. The verbatim source material lives in the private `nogran-trader-dataset` repo.

### 9.3 Direction-aware lookup

The LLM returns 6 SetupTypes (`second_entry_H2`, `breakout_pullback`, `H2_ema`, `ii_breakout`, `shaved_bar`, `none`). The KB has 62 more granular setups. The lookup maps (SetupType + Action) -> KB setup_id:

```
LLM setup           | direction | KB setup_id
--------------------|-----------|---------------------------
second_entry_H2     | long      | high_2_pullback_ma_bull
second_entry_H2     | short     | low_2_pullback_ma_bear
breakout_pullback   | long      | breakout_pullback_bull_flag
breakout_pullback   | short     | breakout_pullback_bear_flag
H2_ema              | long      | limit_quiet_bull_flag_at_ma
H2_ema              | short     | limit_quiet_bear_flag_at_ma
ii_breakout         | both      | tr_breakout_setup
shaved_bar          | -         | (no match — graceful degradation)
```

### 9.4 Blend formula (enriched Strategy Score)

When the lookup finds a match, the final Strategy Score is a weighted blend:

```
SS_final = SS_llm * 0.6 + SS_pa * 0.4
```

- **0.6 LLM:** preserves the contextual intelligence of the 5-layer top-down RAG
- **0.4 Nogran PA:** numeric anchor in the verifiable KB probabilities

When there is no match (`shaved_bar`, novel setups), `SS_final = SS_llm` (graceful degradation, zero impact).

The Decision Scorer receives `ss = SS_final` and computes normally with the immutable weights. The 12 existing Decision Scorer tests remain green.

### 9.5 Hallucination detector

When the gap between the LLM and the Nogran PA KB exceeds a threshold, a structured alarm fires:

```
gap = SS_llm - probability_pct (from Nogran PA)

|gap| < 25       -> no alarm (agreement)
|gap| 25 to 39   -> warning  (LLM diverged moderately)
|gap| >= 40      -> critical (likely hallucination)
```

The alarm is:
1. **Logged** in the audit JSONL (`hallucination_alarm` field) with severity, gap, direction, setup_id
2. **Surfaced in the Streamlit dashboard** as a red/yellow badge on the latest decision
3. **Anchored on-chain** in the ERC-8004 checkpoint (part of the audited reasoning)

**Why this is differentiated:**
- A **measurable, real-time** hallucination detector — not just anecdotal
- Every trade has **auditable proof** that the LLM agreed (or disagreed) with the KB
- Directly addresses the central judge fear in "AI Trading Agents" — LLM hallucination

### 9.6 R/R warning (soft signal)

If the trade's effective R/R is lower than the recommended R/R for that setup, an `rr_warning` is added to the audit log. **This does not block the trade** — the global `MIN_REWARD_RISK = 1.5` remains the hard floor. It is auditable only.

```python
if trade_rr < setup.min_reward_risk:
    log_warning(f"R/R {trade_rr} below the recommended Nogran PA value ({setup.min_reward_risk}), "
                f"but above the global floor ({MIN_REWARD_RISK})")
```

### 9.7 Citations in the audit trail

Every decision logged in `logs/decisions/*.jsonl` now includes:

```json
{
  "kb_match": {
    "setup_id": "high_2_pullback_ma_bull",
    "name_pt": "High 2 pullback to the moving average in an uptrend",
    "probability_pct": 60,
    "probability_confidence": "explicit",
    "min_reward_risk": 1.5,
    "llm_score": 75,
    "blended_score": 69
  },
  "hallucination_alarm": null,
  "rr_warning": null
}
```

And the ERC-8004 checkpoint includes the `setup_id` in the reasoning string, turning every decision into an on-chain citation of a specific PA KB entry. **First agent to cite a structured PA KB on-chain.**

### 9.8 External cross-check

The KB was cross-checked against `github.com/ByteBard/ict-stradegy registry.json`, an independent repository that codifies 32 price action strategies in Python. Results:

- **6 setups with exact match** (H2/L2 pullback, climax fade, measured move, breakout pullback, final flag)
- **13 gaps filled** after the comparison (micro_channel, tight_channel, wedge_reversal, parabolic_wedge, cup_and_handle, second_leg_trap, vacuum_test, broad_channel, triangle, fomo_entry, tr_breakout, buy/sell the close)
- **6 sub-types of Major Trend Reversal** decomposed (HL, LH, DB-HL, DT-LH, HH, LL) — previously aggregated
- **Discrepancies resolved in favour of the in-house KB:** the KB asserts `tr_breakout_setup` 60–80% explicitly, while ByteBard uses 50%. The original KB wins the cross-check.

The public version of the JSON (in this agent repo) contains paraphrased data; the verbatim quotes and original source material live in `nogran-trader-dataset` (private).

### 9.9 Code

```
src/strategy/probabilities_kb.py     # Loader, lookup, blend, hallucination detector
src/strategy/signal_parser.py        # calculate_strategy_score_with_kb (alongside the original)
src/compliance/decision_logger.py    # 3 new fields: kb_match, hallucination_alarm, rr_warning
src/main.py                          # Stage 4 wire (replaces SS with the enriched version)
data/probabilities/                  # KB JSON
tests/test_probabilities_kb.py       # 24 tests (loader, lookup, blend, alarm, R/R, backward compat)
```

**Tests:** 386/386 pass (full suite, including the 12 Decision Scorer tests + 24 KB tests).

---

## 10. ERC-8004 INTEGRATION

### 10.1 TradeIntent with Decision Score

Every decision generates a signed TradeIntent that now includes the full Decision Score:

```python
class TradeIntent:
    def build(self, trade_signal, risk_approval, decision_score, agent_identity):
        return {
            "agent_address": agent_identity.address,
            "intent_id": str(uuid4()),
            "timestamp": datetime.utcnow().isoformat(),

            # Decision
            "action": trade_signal.action,
            "symbol": trade_signal.symbol,
            "entry_price": trade_signal.entry_price,
            "stop_loss": risk_approval.adjusted_stop,
            "take_profit": risk_approval.adjusted_target,
            "position_size": risk_approval.position_size,

            # Decision Score (full explainability)
            "decision_score": {
                "total": decision_score.total,
                "threshold": decision_score.threshold,
                "breakdown": decision_score.breakdown,
                "hard_veto": decision_score.hard_veto
            },

            # Context
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

### 10.2 Reputation driven by the Decision Score

```python
class ReputationTracker:
    def calculate(self, trade_history):
        # Performance (40%)
        pnl_score = normalize(total_pnl, -10, 10)            # % of capital
        sharpe_score = normalize(sharpe, -2, 3)

        # Consistency (30%)
        dd_score = 1 - normalize(max_drawdown, 0, 0.15)      # Smaller DD = better
        stability = 1 - std(decision_scores) / 100           # Stable scores = better

        # Discipline (20%)
        compliance = count(trades where executed == (score > threshold)) / total
        selectivity = 1 - (trades_per_hour / MAX_TRADES_PER_HOUR)

        # Transparency (10%)
        all_signed = all(t.has_valid_signature for t in trade_history)
        avg_reasoning_length = mean(len(t.reasoning) for t in trade_history)
        reasoning_score = 1 if avg_reasoning_length > 50 else 0.5

        reputation = (
            (pnl_score * 0.20 + sharpe_score * 0.20) +
            (dd_score * 0.15 + stability * 0.15) +
            (compliance * 0.10 + selectivity * 0.10) +
            (all_signed * 0.05 + reasoning_score * 0.05)
        )

        return int(reputation * 1000)   # 0–1000
```

---

## 11. CODE LAYOUT

```
nogran.trader.agent/
├── src/
│   ├── main.py                       # Entry point
│   │
│   ├── domain/
│   │   ├── models.py                 # TradeSignal, RiskApproval, DecisionScore, TradeResult
│   │   ├── enums.py                  # Action, Regime, DayType, SetupType
│   │   └── events.py                 # CandleClosed, SignalGenerated, OrderFilled
│   │
│   ├── market/
│   │   ├── websocket_client.py       # Kraken WS
│   │   ├── feature_engine.py         # EMA, ATR, ADX, tails, consecutives, swings, HTF
│   │   ├── candle_buffer.py          # Ring buffer
│   │   ├── pre_filter.py             # Chop detector + MQ score
│   │   ├── swing_points.py           # Swing high/low + HH/HL classification
│   │   ├── failed_attempts.py        # Failed-breakout / second-entry tracker
│   │   ├── always_in.py              # Always-in bias (computed)
│   │   └── regime_classifier.py      # Explicit regime classifier
│   │
│   ├── strategy/
│   │   ├── llm_strategy.py           # LLM strategy orchestrator
│   │   ├── llm_prompts.py            # System prompt + JSON schema
│   │   ├── llm_providers/            # OpenAI / Gemini providers
│   │   ├── pa_retriever.py           # Rule-based RAG retriever
│   │   ├── llm_cache.py              # Disk cache for LLM responses
│   │   ├── fact_builder.py           # Mathematical fact for the LLM
│   │   ├── signal_parser.py          # Pydantic LLMSignalSchema + parsers
│   │   ├── probabilities_kb.py       # PA KB loader + lookup + blend + alarm
│   │   └── local_signal.py           # Mock heuristic (no LLM)
│   │
│   ├── ai/
│   │   ├── regime_detector.py        # TRENDING / RANGING / TRANSITIONING
│   │   ├── confidence_adjuster.py    # Multi-TF + regime + volume
│   │   ├── target_optimizer.py       # Target by regime and win rate
│   │   ├── overtrading_brake.py      # Trades/hour cap
│   │   └── decision_scorer.py        # Composite score (4 sub-scores)
│   │
│   ├── risk/
│   │   ├── position_sizer.py         # Sizing (ATR + score + drawdown + LL)
│   │   ├── stop_adjuster.py          # ATR + swing-anchored stop
│   │   ├── drawdown_controller.py    # Bands + circuit breakers
│   │   ├── exposure_manager.py       # Max 1 position, cooldown, max hold
│   │   └── metrics.py                # Sharpe, DD, win rate, expectancy
│   │
│   ├── learning/
│   │   └── learning_loop.py          # Deterministic post-trade calibration (planned)
│   │
│   ├── compliance/
│   │   ├── erc8004_onchain.py        # AgentRegistry + RiskRouter + Reputation + Validation
│   │   ├── decision_logger.py        # Audit trail JSONL
│   │   └── agent0_discovery.py       # Optional Agent0 SDK discovery layer
│   │
│   ├── execution/
│   │   ├── kraken_cli.py             # Kraken CLI subprocess wrapper
│   │   └── executor.py               # Order lifecycle
│   │
│   ├── thinking/
│   │   ├── narrator.py               # Narrative trace per candle
│   │   ├── detector.py               # Mind-change detector
│   │   └── models.py                 # ThoughtStream models
│   │
│   ├── telemetry/
│   │   └── (planned)
│   │
│   └── infra/
│       ├── config.py                 # .env + constants
│       └── indicators.py             # EMA, ATR, ADX, SMA (pure functions)
│
├── data/probabilities/               # PA KB JSON
├── data/chunks/                      # Per-layer JSON chunks (gitignored)
├── logs/decisions/                   # Audit trail JSONL
├── tests/                            # 386 pytest suite
├── scripts/                          # backtest.py, simulate_market.py, setup_erc8004.py
├── requirements.txt
├── .env.example
├── LICENSE                           # MIT
├── THIRD_PARTY.md                    # Third-party disclosure
├── README.md
├── SETUP.md
└── ARCHITECTURE.md
```

---

## 12. COMPETITIVE DIFFERENTIATOR

### 12.1 The battlefield

Most hackathon agents fall into one of two traps:

**Trap 1: "The LLM decides everything"**
- The LLM analyses the chart (or data), decides buy/sell, sets stop/target
- Result: inevitable hallucination, no risk control, erratic performance
- Problem: LLMs are not good with numbers and invent visual patterns

**Trap 2: "Quant bot with AI bolted on"**
- Classic indicator bot with an LLM that outputs a "comment" or "sentiment"
- The AI is decorative — removing it does not change the result
- Problem: does not demonstrate real AI use to the judges

### 12.2 Our position: the third path

nogran.trader.agent is neither LLM-first nor quant-first. It is a **hybrid system with separation of responsibilities**:

```
COMPONENT                | WHO DOES IT             | WHY
-------------------------|-------------------------|--------------------------------
Perceive the market      | Python (deterministic)  | Zero hallucination — math facts
Interpret the market     | LLM (via Top-Down RAG)  | Verifiable knowledge (Nogran PA)
Filter signals           | Python (local AI)       | Fast, free, explainable
Control risk             | Python (Risk Engine)    | Independent of the LLM — capital protected
Decide to execute        | Decision Score          | Auditable composite score
Adapt parameters         | Learning Loop           | Deterministic, with guardrails
Track decisions          | ERC-8004                | Full transparency
```

### 12.3 8 layers against hallucination

```
# | Layer                            | What it prevents
---|----------------------------------|------------------------------------------
1 | Mathematical fact (not chart)    | LLM does not "see" patterns that don't exist
2 | Top-down RAG (not bottom-up)     | Macro context determines micro meaning
3 | Per-layer chunk isolation        | Chunks do not contaminate across layers
4 | Temperature 0.1                  | Minimises creativity (we want consistency)
5 | JSON validator + R/R guard       | Blocks malformed output
6 | Post-LLM AI Overlay              | Python checks coherence with real data
7 | Decision Score < 65 = veto       | Insufficient quality does not pass
8 | PA KB hallucination detector     | Independent cross-check vs the 62 KB setups; real-time alarm if gap >= 25 pts
```

### 12.4 How it maximises risk-adjusted return (Sharpe)

```
Mechanism                          | Direct impact
-----------------------------------|----------------------------------
Position sizing by Decision Score  | Bets more when the edge is clear
Progressive drawdown bands         | Reduces exposure before disaster
Circuit breakers                   | Stops before catastrophic drawdown
Chop filter (MQ score)             | Avoids zero-expectancy trades
Overtrading brake                  | Reduces costs and slippage
Regime-aware targets               | Larger targets in trends, smaller in ranges
Multi-TF confirmation              | Filters signals against the higher timeframe
Learning Loop                      | Continuous calibration against performance
ATR adaptive stop                  | Constant dollar risk per trade
Adaptive cooldown                  | Avoids revenge trading after losses
```

### 12.5 Summary: why this agent wins

1. **Correct AI usage:** the LLM interprets via verifiable RAG; Python filters and controls risk. Not decorative.
2. **Total explainability:** Decision Score decomposed into 4 sub-scores. Every trade has an auditable justification.
3. **Risk-adjusted return:** position sizing by score + drawdown bands + Learning Loop = Sharpe optimised.
4. **ERC-8004 transparency:** every decision is signed, logged, and feeds a computable reputation. First agent to cite a PA KB on-chain.
5. **Extreme discipline:** the agent knows when NOT to trade — and that is the main alpha.
6. **Measurable anti-hallucination:** PA KB with 62 setups + a real-time hallucination detector. The LLM is cross-checked against the KB on every decision, with a structured alarm and an auditable citation. Directly resolves the central judge fear in "AI Trading Agents".

---

## 13. FINAL PITCH

> **The problem:** AI trading bots fail because the LLM hallucinates patterns that don't exist on the chart, or because the AI is just decoration glued onto an indicator bot. In both cases there is no real risk control — the agent trades blindly until capital is destroyed.

> **The solution:** nogran.trader.agent separates who perceives (Python computes mathematical facts), who interprets (LLM consults the verifiable Nogran PA KB via top-down RAG across 5 layers), who filters (local AI detects regime and adjusts confidence), and who protects (independent Risk Engine with circuit breakers). The LLM never touches raw data. The Risk Engine never depends on the LLM.

> **The differentiator:** every trade goes through a Decision Score made of 4 auditable sub-scores — only executes above 65/100. A deterministic Learning Loop calibrates thresholds against real performance. Every decision generates a signed TradeIntent (ERC-8004) with full traceability. Out of every 100 candles, the agent trades 3–5. That extreme selectivity is the true alpha.

> **The line that sticks:** *the most disciplined agent in the hackathon. It doesn't win by trading more — it wins by knowing when not to trade.*

---

## 14. IMPLEMENTATION ROADMAP

```
PHASE 1 — FOUNDATION (highest priority)
  [1] domain/models.py + enums.py             (30 min)
  [2] infra/config.py + indicators.py         (1h)
  [3] market/feature_engine.py (EMA, ATR, ADX)(2h)
  [4] market/candle_buffer.py                 (30 min)
  [5] strategy/fact_builder.py (fact v2)      (1h)

PHASE 2 — RISK ENGINE (highest priority)
  [6] risk/metrics.py                         (1h)
  [7] risk/position_sizer.py                  (1.5h)
  [8] risk/stop_adjuster.py                   (1h)
  [9] risk/drawdown_controller.py             (1h)
  [10] risk/exposure_manager.py               (30 min)

PHASE 3 — AI LAYER + DECISION SCORE (highest priority)
  [11] ai/regime_detector.py                  (1.5h)
  [12] ai/confidence_adjuster.py              (1h)
  [13] ai/overtrading_brake.py                (30 min)
  [14] ai/decision_scorer.py                  (1.5h)
  [15] market/pre_filter.py (MQ score)        (1h)

PHASE 4 — LEARNING LOOP (high priority)
  [16] learning/learning_loop.py              (2h)

PHASE 5 — INTEGRATION (high priority)
  [17] Refactor market_data.py -> websocket_client.py (1h)
  [18] Refactor brain.py -> strategy/*                 (1h)
  [19] Refactor execution.py -> execution/*           (1.5h)
  [20] main.py: full pipeline with scoring             (2h)

PHASE 6 — ERC-8004 (high priority)
  [21] compliance/agent_identity.py                    (1h)
  [22] compliance/trade_intent.py (with Decision Score)(1.5h)
  [23] compliance/decision_logger.py                   (1h)
  [24] compliance/reputation.py (score-based)          (1h)

PHASE 7 — TELEMETRY + POLISH (medium priority)
  [25] telemetry/trade_journal.py             (1h)
  [26] telemetry/performance_report.py        (1h)
  [27] scripts/replay.py                      (2h)
  [28] Update README.md and SETUP.md          (1h)

PHASE 8 — INGESTION AND DATA (parallel)
  [29] Restructure chunks into 5 per-layer JSONs (3h)
  [30] scripts/ingest_chunks.py for 5 tables     (1h)
  [31] Test the LLM RAG with real data           (2h)
```

**If time is tight, prioritise:** Phases 1–3 + Phase 5 (integration). The Decision Score + Risk Engine are the biggest differentiators. Learning Loop and ERC-8004 can be simplified without losing the essence.
