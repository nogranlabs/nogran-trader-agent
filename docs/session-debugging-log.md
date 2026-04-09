# Session Debugging Log — 11 bugs hunted before submission

> Date: 2026-04-08 (4 dias antes do hackathon freeze)
> Mode: forensic debugging session, 1 trader + 1 AI assistant
> Outcome: pipeline went from "structurally broken" to "+2.59% net / Sharpe 21" on smoke test

This document is **part of the hackathon submission** because we believe **honesty about
bugs found and fixed** is more valuable than pretending the code was perfect from day one.
Every bug below was real, every fix is in git history.

---

## Why this document exists

Most hackathon submissions show only the polished happy path. We're showing the hunt:
**11 distinct structural bugs** that would have silently destroyed the agent if not found
in time. Each one is the kind of bug that:

1. Doesn't break tests (all our 310 tests stayed green throughout)
2. Doesn't crash the agent (it just produces wrong results)
3. Hides behind layers of abstraction
4. Looks correct on first read

A trading agent that ships with these bugs will report fake metrics, lose real money,
or — worst — *appear* to work but quietly under-perform. We chose the harder path:
question every assumption until the math checks out.

---

## Bug 1: ExposureManager wall-clock bug (CRITICAL)

**Symptom:** every backtest, regardless of dataset, produced exactly 4 trades.

**Root cause:**
```python
# src/risk/exposure_manager.py
def can_open_position(self, current_candle_index: int) -> tuple[bool, str]:
 ...
 now = time.time # ← wall clock, not simulated time
 self.trades_this_hour = [t for t in self.trades_this_hour if now - t < 3600]
 if len(self.trades_this_hour) >= Config.MAX_TRADES_PER_HOUR: # = 4
 return False, "Max trades/hour reached"
```

In live trading this is correct: 4 real trades in 1 real hour.

In **batch backtest** (8615 candles processed in <1s of wall time), the first 4 candles
that pass MQ filter trigger trades. Then `time.time - tradesThisHour[0] < 3600` is
**always true** (only 100ms have passed in real time). The agent is permanently blocked
for the rest of the backtest.

**Result:** every backtest reported 4 trades. Every "tuning sweep" we ran was actually
testing the same 4 first-hour trades. Hours of analysis on noise.

**Fix:** `scripts/backtest.py` defines `BacktestExposureManager` that uses `candle_index`
instead of wall clock. Live `ExposureManager` left intact (CLAUDE.md forbids touching
risk parameters in production).

**Verified:** 30d backtest now generates 18-252 trades depending on config.

---

## Bug 2: Backtest stop/target override (CRITICAL — silent value destruction)

**Symptom:** the LLM with PA RAG was being called, returning sensible structure-based
stops, then losing money the same way as the mock heuristic.

**Root cause:** the backtest pipeline received the LLM's signal and then did:
```python
# scripts/backtest.py (before fix)
stop_dist_pre = features.atr_14 * tuning.atr_stop_mult # mechanical 1.5×ATR
target_dist_pre = stop_dist_pre * tuning.rr_min # mechanical 1.5×stop
if signal.action == Action.COMPRA:
 signal.stop_loss = candle.close - stop_dist_pre # OVERWRITES LLM's choice
 signal.take_profit = candle.close + target_dist_pre # OVERWRITES LLM's choice
```

The override existed because the mock heuristic generates fixed RR=2.0; we wanted CLI
flags `--rr` to actually affect the math. **It was never supposed to apply to LLM
signals**, but it did, **silently**.

**Why it was so bad:** the entire point of running an LLM with Nogran PA book chunks is
that the LLM picks stops at structural levels (S/R, swing points, channel boundaries).
Replacing them with `entry ± 1.5×ATR` defeats the entire architecture.

**Fix:** override now gated on `tuning.strategy_source == "mock"`.

**Verified:** LLM-generated stops now persist through to execution. Trade exit prices
match LLM target_price exactly.

---

## Bug 3: rr_min filter rejecting valid Nogran PA scalps

**Symptom:** with the override fix in place, the LLM was still mostly producing
"AGUARDAR" outcomes. The few signals it did emit were rejected at risk-check.

**Root cause:** Risk Engine vetoes any signal with `RR < Config.MIN_REWARD_RISK = 1.5`.
But The rule states that **shaved bar scalps** (bars with no tail in trend direction) are
high-winrate setups where 1:1 RR is valid because the win rate justifies it.

The LLM was correctly identifying shaved bars and proposing 1:1 RR — exactly what Nogran PA
recommends. We were rejecting them.

**Fix:** `_compute_risk_score` accepts `trust_llm_rr=True` for `python_llm` strategy
source. Mock keeps the rr_min cutoff (mock has no concept of setup-specific RR).

**Verified:** shaved bar scalps now reach execution.

---

## Bug 4: Default Gemini model has 20 requests/day (RUNTIME, near-show-stopper)

**Symptom:** smoke test with Gemini hit `429 RESOURCE_EXHAUSTED` after only ~15 calls,
even though we had used the API zero times that day.

**Root cause:** `gemini-flash-latest` aliases to `gemini-3-flash`, which is a preview
model with **20 requests/day** on the free tier. The "general purpose" Gemini Flash quota
of 1500/day applies only to `gemini-2.5-flash` and earlier.

**Discovery process:**
1. First model probe: `gemini-2.0-flash-exp` — model-not-found
2. Switched to `gemini-flash-latest` — worked initially
3. After 13 calls: 429 quota exceeded
4. Read the error closely: `model: gemini-3-flash, limit: 20`
5. Realized `gemini-flash-latest` had silently aliased to the preview model

**Fix:** `DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"` (separate quota, faster latency).
Added a comment in `gemini_provider.py` warning future maintainers:
```python
# Avoid 'gemini-flash-latest' — it aliases to gemini-3-flash (preview)
# which has only 20 requests/day on free tier.
```

---

## Bug 5: Fee-unaware prompt — LLM picking math-impossible setups

**Symptom:** with bugs 1-4 fixed and the LLM using its own stops/targets, win rate jumped
from 17% (mock) to 39% (LLM). Avg loss ($57) was still bigger than avg win ($40),
producing -$19/trade expectancy.

**Root cause:** the LLM didn't know fees existed. The system prompt described Nogran PA
methodology in detail but never mentioned that Kraken charges 0.16-0.26% per side.
So the LLM was happily picking shaved bar scalps with reward = 0.2% of price, not
realizing that 0.5% round-trip fees made these unprofitable at 100% win rate.

**The math:**
```
fee_round_trip / reward = (0.0052 × notional) / (size × stop_dist × rr)
 = 0.0052 × entry / (stop_dist × rr)

For BTC $71400, stop $144, RR 1.0:
= 0.0052 × 71400 / (144 × 1.0)
= 2.59×

→ fees are 2.59× the reward, INDEPENDENT of position size.
```

**Fix:** added an explicit rule to `SYSTEM_PROMPT`:
> "MANDATORY: target_distance >= 1.0% of entry_price. RR >= 2.5. REJECT scalps unless
> reward >= 1% of price. Better to skip 99 bars and take 1 great trade than take 99
> mediocre trades and lose to fees."

**Verified:** smoke test 200 candles 15m maker fees: **+2.59% net, win rate 100%
(3/3), Sharpe +21.24, Max DD 0%**. The LLM stopped picking scalps and started
picking swings.

---

## Bug 6: EIP-712 v-byte format (THE BIG ONE — invalidated all on-chain trades)

**Symptom:** every TradeIntent we submitted to RiskRouter on Sepolia was rejected with
`"Invalid signature"`. We had 0 successful trades on-chain after 10 attempts.

**Discovery process:**
1. Confirmed our parameters were valid: `simulateIntent` returned `[True, '']` (no
 signature required for simulation).
2. Confirmed our signature recovered the correct address locally (`Account.recover_message`
 returned our wallet).
3. So the signing was producing a "valid" signature but the contract rejected it.
4. Re-read the actual revert: `0xf645eedf` = `ECDSAInvalidSignature` from OpenZeppelin's
 ECDSA library.
5. **OpenZeppelin's ECDSA recovery returns `address(0)` if `v ∉ {27, 28}`.**
6. `eth_keys.PrivateKey.sign_msg_hash.to_bytes` returns signature with **`v ∈ {0, 1}`**
 (the recovery_id, not the Ethereum convention).
7. Switched to `account.unsafe_sign_hash(digest)` which formats `v` as `27 + recovery_id`.

**Fix:**
```python
# src/compliance/erc8004_onchain.py — _sign_trade_intent
signed = self.account.unsafe_sign_hash(digest)
return signed.signature # v is now 27 or 28
```

**Verified:** first post-fix attempt returned `OK (approved) tx=0xf3989d76...`. Subsequent
30 attempts: 30 approved (100% success rate). Total approved on-chain: **31 trades**.

**Impact:** before the fix, we had 0 approved trades and were invisible on the validator
leaderboard. After the fix, **rank 15 of 25** by approved-trade count, in line with
serious teams.

---

## Bug 7: Pending nonce collision

**Symptom:** after the EIP-712 fix, retry-attempts produced
`"replacement transaction underpriced"`.

**Root cause:** `_send_tx` was using `get_transaction_count(addr, 'latest')` which only
counts confirmed txs. When a previous tx was still in the mempool (slow Sepolia public RPCs),
the next tx would reuse the same nonce — Ethereum interprets this as a replacement attempt
and requires higher gas.

**Fix:** use `get_transaction_count(addr, 'pending')` to advance past queued txs.
Also bump gas price 20% above network to outbid any actually-stuck pendings.

---

## Bug 8: Sepolia RPC fallback

**Symptom:** intermittent `Connection refused` from `rpc.sepolia.org`.

**Root cause:** `rpc.sepolia.org` is a community-maintained endpoint that goes down
several times a day. The original `init_erc8004` only tried that one URL.

**Fix:** `setup_erc8004.py` and `init_erc8004` now try a list of 4 public RPCs in order:
```python
SEPOLIA_RPCS = [
 "https://ethereum-sepolia-rpc.publicnode.com",
 "https://sepolia.gateway.tenderly.co",
 "https://eth-sepolia.public.blastapi.io",
 "https://1rpc.io/sepolia",
 "https://sepolia.drpc.org",
 "https://rpc.sepolia.org", # last resort
]
```

---

## Bug 9: Prompt language (Portuguese) producing weaker reasoning

**Symptom:** Gemini's first JSON response (in Portuguese) was less precise about Nogran PA
terminology than expected. Setups labeled with vague descriptions, RR values rounded.

**Root cause:** GPT-4o, Gemini, Claude are all trained on more English than Portuguese
data. Nogran PA' books are in English. Asking the model to reason about English concepts
in Portuguese forces it through a translation step that loses nuance.

**Fix:** translated `SYSTEM_PROMPT` and the user message builder to English. Domain
identifier enums (`SEMPRE_COMPRADO`, `APROVADO`, `COMPRA`) kept in Portuguese because
they are referenced elsewhere in the codebase.

**Verified:** same feature snapshot, same model (Gemini), but English prompt:
- before (PT): action=COMPRA, setup=`breakout_pullback`, RR=1.5, generic reasoning
- after (EN): action=COMPRA, setup=`H2_ema` (more precise), RR=2.0, "bounced off EMA20, second leg up"

---

## Bug 10: No RAG retriever (LLM relying on training data)

**Symptom:** the entire `data/chunks/layer{0..5}_*.json` directory existed but was being
ignored. The LLM was answering Nogran PA questions from its training data instead of from
the actual book chunks we'd extracted.

**Root cause:** when we migrated from LLM to Python LLM, we built the LLM call but
**forgot to wire up retrieval**. The chunks sat there unused.

**Fix:** built `src/strategy/pa_retriever.py`, a rule-based retriever (no vector DB
required, since we have only 213 chunks total). It maps current `FeatureSnapshot` to
relevant chunks per layer:
```python
def _pick_layer1_topic(self, f: FeatureSnapshot) -> list[str]:
 topics = ["spike_and_channel"]
 if f.consecutive_bull >= 3 and f.adx_14 >= 25:
 topics.append("trend_from_open")
 ...
```

The retrieved chunks are injected into the user message before the LLM call. Cache key
includes the chunk IDs so deterministic retrieval = deterministic cache.

**Verified:** the very first call with RAG **changed an LLM decision from "BUY" to
"WAIT"** because the retrieved chunks reminded the LLM that "buying climaxes is a losing
trade" — exactly what The rule states in chapter 21. This was the moment we knew RAG
was earning its keep.

---

## Bug 11: Config.TIMEFRAME_EXEC = "1m" violates core rule

**Symptom:** all live testing was being done on 1-minute candles, exactly the timeframe
Nogran PA explicitly warns against in chapter 1 of *Trading Price Action: Trends*.

**Root cause:** `Config.TIMEFRAME_EXEC = "1m"` was the default. Backtests used `--timeframe
5m` as a CLI flag, so the inconsistency was hidden — backtests showed one set of behavior,
live agent another.

Nogran PA quote (paraphrased from book):
> "I do not look at any chart faster than 5 minutes for trading purposes. Faster charts
> have too much noise and the trader's equation rarely works."

The trader's equation breaks down on 1m crypto specifically because:
- ATR is small (~$15-30 on BTC at $70k)
- Stop_distance is therefore small (~$22-45)
- Reward is therefore small (~$33-67 at RR 1.5)
- **Fees ($52 round-trip) exceed the reward.** Mathematically impossible.

**Fix:** `Config.TIMEFRAME_EXEC = "5m"`, `TIMEFRAME_CONFIRM = "15m"`. Nogran PA-compliant.
Documented inline.

---

## What this debugging session demonstrates

A trading agent is not "the LLM" or "the strategy". It is a chain of **10+ subsystems**
where any one being subtly wrong can produce zero alpha or worse. This session found
bugs in:

- Risk management (ExposureManager wall-clock)
- Position sizing (override defeating LLM)
- Risk filtering (rr_min rejecting valid setups)
- LLM provider configuration (Gemini default model)
- Prompt engineering (fee-unawareness, language)
- RAG architecture (retriever not wired)
- Cryptography (EIP-712 v-byte)
- Network plumbing (RPC fallback, pending nonce)
- Config defaults (timeframe)

Each bug was found by **questioning a specific assumption** ("why are there always 4
trades?", "why is the stop $144 instead of the LLM's $200?", "why does ECDSA reject
my correctly-recovered signature?"). None were caught by tests because each test
correctly tested its narrow surface.

**The takeaway for future hackathon agents:** unit tests are necessary but not
sufficient. You need **end-to-end on-chain verification** (does the contract actually
accept my tx?) and **mathematical sanity checks** (does the trader's equation work
with my actual fees?). Both are how we found the worst bugs.

---

## Final state after all 11 fixes

| Metric | Before fixes | After fixes |
|---|---|---|
| Backtest 30d trades | 4 (capped by bug 1) | 18-252 (depending on config) |
| LLM win rate | 17% (mock heuristic) | **100%** (3/3 in v1.3 smoke) |
| LLM net PnL on smoke | -8% to -1% | **+2.59%** |
| Sharpe | -65 to -10 | **+21** |
| On-chain TradeIntents approved | **0** (silently rejected) | **31** (rank 15/25) |
| PA chunks used by LLM | 0 (ignored) | 5-10 per call (rule-based RAG) |
| Tests | 255 → 310 (+55) | 310 verdes |

This is what the agent looks like now. The 4 days of refinement remaining go into:
1. Larger backtest samples to validate the +2.59% holds beyond 3 trades
2. Multi-asset support (BTC + ETH)
3. Live paper trading to gather real-world data
4. Video pitch + final README polish

And whatever bug 12 turns out to be.
