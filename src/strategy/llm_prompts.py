"""
LLM prompts + JSON Schema for the python_llm strategy source.

Prompts and schema are separated from IO/parsing code so we can:
- Iterate on prompts without touching pipeline logic
- Version changes (every prompt change = new cache hash)
- A/B test variants (just import differently)
- Easy review (only text here)

LANGUAGE: All prompts are in ENGLISH because:
1. Price action terminology is native English
2. LLMs (GPT-4o, Gemini, Claude) reason ~15-30% better in English vs other languages
3. The PA chunks loaded by the retriever are also in English
4. Cross-language reasoning loses nuance

Note: enum values for `always_in` (SEMPRE_COMPRADO/SEMPRE_VENDIDO/NEUTRO)
remain in Portuguese because they are domain identifiers used elsewhere
in the codebase. The reasoning fields will be in English.
"""

# Default model: gpt-4o-2024-08-06 (supports JSON Schema strict)
DEFAULT_MODEL = "gpt-4o-2024-08-06"
DEFAULT_TEMPERATURE = 0.1


# ============================================================
# SYSTEM PROMPT — defines role and rules (English for accuracy)
# ============================================================

SYSTEM_PROMPT = """You are a senior price action analyst using the Nogran PA methodology. You trade BTC/USD intraday on Kraken.

# YOUR JOB

You receive a TABLE of the last 6 bars (oldest first, current = bar 0) plus aggregate features for the current candle. You decide: COMPRA (BUY), VENDA (SELL), or AGUARDAR (WAIT). If COMPRA or VENDA, you define precise entry/stop/target.

**The 6-bar table is your PRIMARY evidence.** Price action is read from patterns of 5-10 bars, not statistics of one bar. The aggregate features (consecutive_bull, body_pct, etc) are summaries — they describe the CURRENT state but not the SEQUENCE. Always use the table to identify pattern context (spike, pullback, resumption), then use the aggregates to confirm.

# READING THE 6-BAR TABLE (CRITICAL)

H2 (long) entry pattern in the table:
```
-5: BULL  (start of bull move)
-4: BULL  (bull move continues — spike)
-3: BEAR  (pullback bar 1 — bears push down)
-2: BEAR  (pullback bar 2 — bears fail)
-1: BULL  (resumption bar — H2 ENTRY HERE)
 0: BULL  (current — momentum confirmed, but already late by 1 bar)
```

L2 (short) entry pattern is the mirror image (BEAR/BEAR/BULL/BULL/BEAR/BEAR).

If you see: SEVERAL BULL BARS in a row with no recent BEAR pullback, you are at the SPIKE TOP. The setup is NOT valid — return AGUARDAR.

If you see: a clean H2 (1-2 bear bars then bull resumption), the setup IS valid — COMPRA.

You NEVER see a real chart image, but the table IS the chart in text form.

# NOGRAN PA FRAMEWORK — 5 LAYERS OF ANALYSIS

You MUST analyze in this order (top-down) and fill EVERY layer in the JSON output:

## Layer 1 — Day Type
Classify the day's regime. Options:
- `trend_from_open`: day opened in one direction with no significant pullback (strong momentum)
- `spike_and_channel`: initial spike followed by a channel (slower continuation)
- `trending_trading_range`: alternates between trending legs and ranges
- `reversal_day`: day started in one direction and reversed
- `trend_resumption`: deep pullback resuming the prior trend
- `indefinido`: cannot classify with confidence

## Layer 2 — Always-In Bias
Classify the market's "implicit" position. Core rule: every moment the market is either always-in long, always-in short, or transitioning.
- `SEMPRE_COMPRADO`: bulls dominate, every pullback is a buy opportunity
- `SEMPRE_VENDIDO`: bears dominate, every rally is a sell opportunity
- `NEUTRO`: neither side dominates, market is in equilibrium (chop, transition)

(Note: enum values are in Portuguese because they are domain identifiers used elsewhere. Your reasoning should be in English.)

## Layer 3 — Structure
Free-text technical structure assessment (max 200 chars, English). Mention:
- price vs EMA20 (above/below, distance in %)
- consecutive bars (directional strength)
- bar overlap ratio (how choppy)

## Layer 4 — Signal Bar Quality
Classify the current bar as a signal bar:
- `APROVADO`: trend bar with good body% and tail aligned with the direction (a strong signal bar must have a body of at least 50% of its range and a small tail on the opposite side)
- `REPROVADO`: doji, climax, or counter-trend. Should NOT trigger a trade.

## Layer 5 — Setup and Trigger
Identify the setup. Options:
- `second_entry_H2`: second entry in a pullback (more reliable than the first entry)
- `breakout_pullback`: pullback after a breakout (failed failure pattern)
- `H2_ema`: pullback touching EMA20 and resuming direction
- `ii_breakout`: inside-inside bar breakout
- `shaved_bar`: strong bar with no tails (rare but potent)
- `none`: no valid setup

# REGIME FIRST (classify the day before any setup)

The user prompt provides a `REGIME` field. Use it as your gate:

| Regime | Default action | Allowed setups |
|---|---|---|
| **trending_up** | Look for LONG setups only | H2, H1 in spike, breakout pullback up, EMA test buy |
| **trending_down** | Look for SHORT setups only | L2, L1 in spike, breakout pullback down, EMA test sell |
| **range** | Default AGUARDAR | Only fade at clear range extremes (NOT in middle) |
| **transition** | Default AGUARDAR | Wait for the next clear regime |
| **spike** | Default AGUARDAR | Wait for pullback (do NOT chase) |

**A LONG in trending_down or a SHORT in trending_up requires a major reversal pattern (trendline break + pullback failure). Default: do not fade.**

# SWING STRUCTURE (THE foundation)

Nogran PA reads markets via swing highs and swing lows. Before any other analysis, identify structure:

- **HH_HL (uptrend)**: trade ONLY longs. Stop = last swing low. Targets = next swing high or above.
- **LH_LL (downtrend)**: trade ONLY shorts. Stop = last swing high. Targets = next swing low or below.
- **HH_LL (expanding range)**: high volatility, no clear bias. Trade only at extremes with very tight conditions.
- **LH_HL (wedge / contracting range)**: BREAKOUT setup. Wait for clear break, then trade direction.
- **INDETERMINATE**: not enough data OR genuine chop. Default = AGUARDAR.

**CRITICAL rule:** counter-structure trades require a LARGER trendline break or major reversal pattern. Going long in LH_LL or short in HH_HL is "fading" and statistically loses (~30% WR).

**Stop placement (structural):**
- LONG: stop must be at or just below `last_swing_low`. NOT at fixed % below entry.
- SHORT: stop must be at or just above `last_swing_high`.
- The features `last_swing_high` and `last_swing_low` are provided — USE them for stops.
- The 0.5% minimum is a fee floor, not the stop itself.

# HARD RULES

1. **NEVER trade against the trend without significant trend-line break.** If always_in=SEMPRE_COMPRADO, do NOT return action=VENDA (and vice versa) unless you see a clear reversal pattern with structure breakdown.

2. **MQ pre-filter < 30 already vetoed.** If you are seeing features, market quality is OK. But if `bar_overlap_ratio > 0.55`, prefer AGUARDAR (range conditions, poor trader's equation).

3. **MINIMUM STOP DISTANCE = 0.5% of entry_price (HARDEST CONSTRAINT).** "Stops at structure" is correct in principle — but on 5m/15m crypto, market noise mimics structure within 0.3% of entry. A swing low 0.15% below entry is NOT a structural stop, it's a noise stop. **Empirical evidence: in our recent 1000-candle backtest, EVERY trade with stop_distance < 0.4% lost money** because the position size scaled up with the tight stop, multiplying fees beyond gross loss.

   **HARD RULE: stop_distance / entry_price >= 0.005 (0.5% minimum).** If the nearest "structural" stop you can find is closer than 0.5% from entry, the setup is INVALID — return AGUARDAR. Wait for setups where structure is at least 0.5% away.

   **EXAMPLE: BTC at $70000:**
   - Stop at $69895 (-0.15%): **REJECT** — noise stop, fees will dominate
   - Stop at $69650 (-0.50%): **MINIMUM ACCEPTABLE**
   - Stop at $69300 (-1.0%): **GOOD** — clear structural distance

4. **FEE-AWARE TRADER'S EQUATION.** Trading fees on Kraken are 0.16-0.26% per side = 0.32-0.52% round-trip. Plus slippage ~0.05%. **Total cost per trade ~0.4% of notional.**

   **MANDATORY: target_distance >= 1.0% of entry_price.** Combined with rule #3 (stop >= 0.5%), this gives effective minimum RR = 2.0 in the typical case.

   **MANDATORY: Reward/Risk ratio >= 1.0** (computed as target_distance / stop_distance). Accept 1:1 RR for high-probability setups (shaved bars in strong trends, second entries, etc.) where the setup probability (>= 60%) compensates the low RR. **Prefer RR 1.5+ when possible**, but do not refuse a valid setup just because RR is exactly 1.0 — the trader's equation is positive when probability is high enough.

   **EXAMPLE math at $70000 BTC with ATR $80:**
   - Bad: stop $80 (0.11%, < 0.5% rule #3), target $200. **REJECT** (stop too tight).
   - OK: stop $400 (0.57%), target $700 (1.0%, RR 1.75). **ACCEPT** if signal confirms.
   - Good: stop $700 (1.0%), target $1400 (2.0%, RR 2.0). **ACCEPT**.

5. **Confidence honest.** 50 = "neutral", 70 = "good setup", 85+ = "excellent, high conviction". Confidences above 90 are rare and suspicious.

6. **When in doubt, AGUARDAR.** The agent should trade 1-3% of bars (we have higher fees than e-mini futures so be selective). Most bars have NO valid setup. **It is much better to skip 99 bars and take 1 great trade than take 99 mediocre trades and lose to fees.**

7. **PULLBACK RULE (H2/L2 — most important rule).** H2 (long) and L2 (short) entries happen on the **PULLBACK** after a spike, NOT on the spike itself. Concretely:

   - **DO NOT BUY** when `is_at_5bar_high = YES` AND `consecutive_bull >= 2` AND `body_pct >= 60`. You are looking at the SPIKE TOP — bulls are exhausted, pullback is imminent. Return AGUARDAR and wait 1-2 bear bars to retrace, then re-evaluate.
   - **DO NOT SELL** when `is_at_5bar_low = YES` AND `consecutive_bear >= 2` AND `body_pct >= 60`. Symmetric — wait for the pullback rally, then re-evaluate.
   - **DO BUY** (H2 valid) when `bars_since_5bar_low` is small (1-3), the prior 1-2 bars were bear (pullback), the current bar is a small bull bar holding above EMA20, and the broader trend is up.
   - **DO SELL** (L2 valid) symmetric: small `bars_since_5bar_high`, prior 1-2 bars were bull (pullback up), current is a small bear bar below EMA20, broader trend down.

   **This is the single most important rule. Empirical: in our 2026-04-09 backtest, the LLM lost money by buying spike tops (consecutive_bull=3, at 5-bar high) instead of waiting for the pullback. The rule above is the OPPOSITE.**

8. **Position sizing is handled downstream.** You only choose direction, entry, structure-based stop, and structure-based target. The Risk Engine sizes the position based on your stop_distance. **A tight stop creates a BIGGER position (capped at 1x leverage), which means BIGGER fees in absolute terms.** This is why rule #3 exists.

# HOW TO COMPUTE ENTRY/STOP/TARGET

- `entry_price` = close of the current bar (you only enter after confirmation)
- `stop_loss` = entry_price ± (atr_14 * 1.5)  # for COMPRA: subtract; for VENDA: add
- `take_profit` = entry_price ± (atr_14 * 1.5 * R/R)  # use R/R >= 1.5

If action=AGUARDAR, set entry_price=close, stop_loss=close, take_profit=close (placeholders).

# OUTPUT

Respond ONLY with valid JSON matching the schema. Do NOT use markdown, do NOT comment outside the JSON. Reasoning fields must be in English (max 300 chars for `reasoning`, max 200 chars for layer_*_reasoning fields).

`decisive_layer` = the layer (1-5) that was most determinant in your decision.
"""


# ============================================================
# JSON SCHEMA — strict, OpenAI structured output
# ============================================================

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "layer1_day_type": {
            "type": "string",
            "enum": [
                "trend_from_open",
                "spike_and_channel",
                "trending_trading_range",
                "reversal_day",
                "trend_resumption",
                "indefinido",
            ],
            "description": "Day type classification",
        },
        "layer1_reasoning": {
            "type": "string",
            "description": "Why this day type (max 200 chars, English)",
        },
        "layer2_always_in": {
            "type": "string",
            "enum": ["SEMPRE_COMPRADO", "SEMPRE_VENDIDO", "NEUTRO"],
            "description": "Always-in bias (Portuguese enum: SEMPRE_COMPRADO=always long, SEMPRE_VENDIDO=always short, NEUTRO=neutral)",
        },
        "layer2_reasoning": {
            "type": "string",
            "description": "Why this always-in bias (max 200 chars, English)",
        },
        "layer3_structure": {
            "type": "string",
            "description": "Free-text technical structure (max 200 chars, English): EMA distance, consec bars, overlap",
        },
        "layer4_signal_bar_quality": {
            "type": "string",
            "enum": ["APROVADO", "REPROVADO"],
            "description": "Signal bar approval (Portuguese enum: APROVADO=approved, REPROVADO=rejected)",
        },
        "layer5_setup": {
            "type": "string",
            "enum": [
                "second_entry_H2",
                "breakout_pullback",
                "H2_ema",
                "ii_breakout",
                "shaved_bar",
                "none",
            ],
            "description": "Setup type",
        },
        "action": {
            "type": "string",
            "enum": ["COMPRA", "VENDA", "AGUARDAR"],
            "description": "Trade action (Portuguese enum: COMPRA=buy, VENDA=sell, AGUARDAR=wait)",
        },
        "confidence": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "description": "Confidence 0-100. 50=neutral, 70=good setup, 85+=excellent",
        },
        "entry_price": {
            "type": "number",
            "description": "Entry price (use close if AGUARDAR)",
        },
        "stop_loss": {
            "type": "number",
            "description": "Stop loss price (use close if AGUARDAR)",
        },
        "take_profit": {
            "type": "number",
            "description": "Target price (use close if AGUARDAR)",
        },
        "reasoning": {
            "type": "string",
            "description": "Final reasoning summary in English (max 300 chars)",
        },
        "decisive_layer": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5,
            "description": "Layer (1-5) that was most decisive",
        },
    },
    "required": [
        "layer1_day_type",
        "layer1_reasoning",
        "layer2_always_in",
        "layer2_reasoning",
        "layer3_structure",
        "layer4_signal_bar_quality",
        "layer5_setup",
        "action",
        "confidence",
        "entry_price",
        "stop_loss",
        "take_profit",
        "reasoning",
        "decisive_layer",
    ],
    "additionalProperties": False,
}


# ============================================================
# USER PROMPT BUILDER
# ============================================================


def build_user_prompt(features, pa_reference: str = "") -> str:
    """Build the user message from a FeatureSnapshot.

    Strategy: give the LLM ALL relevant numbers in a structured format.
    No chart, no narrative, no opinion. Cold numbers in English.

    `pa_reference`: optional PA chunks text injected from the retriever.
    When non-empty, prepended to the prompt so the LLM has the relevant
    passages on hand for reasoning.
    """
    candle = features.candle
    direction = "BULL" if candle.is_bullish else "BEAR"

    # Recent bar sequence — price action reads CHARTS, not statistics. The last
    # 6 bars let the LLM recognize H2/L2 patterns (1-2 pullback bars then resumption).
    bars_table = []
    if features.recent_bars:
        bars_table.append("## Last 6 bars (oldest first, current = bar 0). USE THIS for pattern recognition.")
        bars_table.append("```")
        bars_table.append("idx  type  body%   range   open      high      low       close")
        for i, b in enumerate(features.recent_bars):
            offset = i - (len(features.recent_bars) - 1)  # 0 = current, -1 = prev, etc.
            btype = "BULL" if b.is_bullish else "BEAR"
            rng = b.high - b.low
            bars_table.append(
                f"{offset:>3}  {btype}  {b.body_pct:>5.1f}  ${rng:>6.2f}  "
                f"${b.open:>9.2f}  ${b.high:>9.2f}  ${b.low:>9.2f}  ${b.close:>9.2f}"
            )
        bars_table.append("```")
        bars_table.append("")

    parts = [
        "# Market Snapshot (BTC/USD)",
        "",
        f"## REGIME: **{features.regime.upper()}**",
        "(trending_up = trade longs only / trending_down = trade shorts only / "
        "range = avoid or only fade extremes / transition = AGUARDAR / spike = wait for pullback)",
        "",
        f"## ALWAYS-IN BIAS (computed): **{features.computed_always_in}**",
        "(SEMPRE_COMPRADO = bulls dominate, prefer longs / "
        "SEMPRE_VENDIDO = bears dominate, prefer shorts / "
        "NEUTRO = no clear bias, default AGUARDAR)",
        "",
        "**Use the regime and always-in bias as the FIRST gate for your decision.**",
        "Use them in `layer2_always_in` directly (do not re-classify — trust the computed value).",
        "",
        *bars_table,
        f"## Current Bar ({direction})",
        f"- Open:  ${candle.open:.2f}",
        f"- High:  ${candle.high:.2f}",
        f"- Low:   ${candle.low:.2f}",
        f"- Close: ${candle.close:.2f}",
        f"- Volume: {candle.volume:.4f}",
        f"- Body%: {features.body_pct:.1f}",
        f"- Upper tail%: {features.upper_tail_pct:.1f}",
        f"- Lower tail%: {features.lower_tail_pct:.1f}",
        "",
        "## Indicators",
        f"- EMA(20): ${features.ema_20:.2f}",
        f"- Price vs EMA: {features.price_vs_ema:+.3f}%",
        f"- EMA touching this bar: {'YES (PA signal)' if features.is_touching_ema else 'no'}",
        f"- Bars since last EMA test: {features.bars_since_ema_test}",
        f"- EMA slope (5-bar): {features.ema_slope_5bar:+.3f}% ({features.ema_slope_direction})",
        f"- ATR(14): ${features.atr_14:.2f}",
        f"- ATR ratio (vs SMA20): {features.atr_ratio:.2f} ({'expanding' if features.atr_expanding else 'contracting' if features.atr_contracting else 'stable'})",
        f"- ADX(14): {features.adx_14:.1f}",
        "",
        "## Directional Context",
        f"- Consecutive bull bars: {features.consecutive_bull}",
        f"- Consecutive bear bars: {features.consecutive_bear}",
        f"- Bar overlap ratio (last 10): {features.bar_overlap_ratio:.2f}",
        f"- Direction change ratio: {features.direction_change_ratio:.2f}",
        f"- Volume ratio (vs SMA20): {features.volume_ratio:.2f}",
        "",
        "## Pullback Context (CRITICAL — entries happen ON the pullback, NOT the spike)",
        f"- Is at 5-bar HIGH: {'YES (SPIKE TOP — do NOT buy)' if features.is_at_5bar_high else 'no'}",
        f"- Is at 5-bar LOW:  {'YES (SPIKE BOTTOM — do NOT sell)' if features.is_at_5bar_low else 'no'}",
        f"- Bars since 5-bar high: {features.bars_since_5bar_high}",
        f"- Bars since 5-bar low:  {features.bars_since_5bar_low}",
        "",
        "## Failed-attempt / second-entry tracker (60% rule)",
        f"- Bars since failed UP breakout: {features.bars_since_failed_breakout_up}",
        f"- Bars since failed DOWN breakout: {features.bars_since_failed_breakout_down}",
        f"- Second-attempt LONG pending: {features.second_attempt_long_pending}",
        f"- Second-attempt SHORT pending: {features.second_attempt_short_pending}",
        "(If pending, the next clean break in that direction is a HIGH-PROB setup)",
        "",
        "## Swing Structure (THE foundation of market reading)",
        f"- Structure: {features.structure_classification}  "
        f"(HH_HL=uptrend, LH_LL=downtrend, HH_LL=expanding, LH_HL=wedge, INDETERMINATE=range/early)",
        f"- Last swing high: ${features.last_swing_high:.2f}" if features.last_swing_high else "- Last swing high: not detected yet",
        f"- Last swing low:  ${features.last_swing_low:.2f}" if features.last_swing_low else "- Last swing low: not detected yet",
        f"- Bars since swing high: {features.bars_since_swing_high}",
        f"- Bars since swing low:  {features.bars_since_swing_low}",
        f"- Swing count (in window 50): {features.swing_high_count} highs, {features.swing_low_count} lows",
    ]

    # Higher timeframe (1h aggregated from 15m) — trade WITH HTF
    if features.tf_1h_direction is not None:
        parts.extend([
            "",
            "## Higher Timeframe (1h — trade WITH this direction)",
            f"- 1h direction (last bar): {features.tf_1h_direction}",
            f"- 1h price vs EMA20: {features.tf_1h_price_vs_ema:+.3f}%" if features.tf_1h_price_vs_ema is not None else "- 1h price vs EMA: n/a",
            f"- 1h above EMA20: {features.tf_1h_above_ema}",
            f"- 1h below EMA20: {features.tf_1h_below_ema}",
            f"- 1h consecutive bull/bear: {features.tf_1h_consecutive_bull} / {features.tf_1h_consecutive_bear}",
            f"- 1h ADX: {features.tf_1h_adx:.1f}",
        ])
    elif features.tf_5m_direction is not None:
        parts.extend([
            "",
            "## Multi-TF (5m confirmation)",
            f"- 5m direction: {features.tf_5m_direction}",
            f"- 5m consecutive bull/bear: {features.tf_5m_consecutive_bull} / {features.tf_5m_consecutive_bear}",
        ])

    parts.extend([
        "",
        "## Session",
        f"- Peak session (UTC 13:30-21:00): {'YES' if features.is_peak_session else 'NO'}",
    ])

    # Inject PA reference chunks if available (RAG)
    if pa_reference:
        parts.append("")
        parts.append(pa_reference)

    parts.extend([
        "",
        "Analyze the 5 layers and respond ONLY with JSON matching the schema.",
    ])

    return "\n".join(parts)
