# Master Strategy — Hackathon Submission

> **Date:** 2026-04-08 (4 dias antes do freeze)
> **Status:** Single source of truth — **leia este antes de qualquer outro doc**
> **Updated after:** Discord chat dump + leaderboard analysis + Steve's 5:17 AM judge-only announcement

This is the **canonical document** consolidating everything we know about the
hackathon, our position, and the path forward. Other docs (`leaderboard-analysis`,
`session-debugging-log`, `pitch-script`) are appendices.

---

## 1. The hackathon at a glance

| Item | Value |
|---|---|
| Name | AI Trading Agents Hackathon |
| Organizer | lablab.ai + Surge + Kraken |
| Dates | March 30 – April 12, 2026 |
| **Days remaining** | **4** (today is April 8) |
| Prize pool | $55,000 in $SURGE tokens (allocated via Surge + Kraken) |
| Submission deadline | April 12 (need to confirm exact time) |
| Submission portal | lablab.ai event page + early.surge.xyz registration |
| Discord | lablab.ai server, #updates-ai-trading-agents-erc-8004 + #participants-chat |
| Our agent | nogran.trader.agent, ID 44, Sepolia: `0xe852...41CCD` |

---

## 2. Two challenges (we're tagging both)

### A. ERC-8004 Challenge ✅ COMPETING

**Requirement:** on-chain activity through HackathonVault and RiskRouter, signed
TradeIntents, attestations on ValidationRegistry.

**Our status:**
- ✅ Agent registered (id 44)
- ✅ Vault claimed (0.0010 ETH on chain — though vault claim is OPTIONAL per Steve 4/6)
- ✅ **31 TradeIntents approved** on RiskRouter (after fixing EIP-712 v-byte bug)
- ✅ EIP-712 signing working (0xf3989d76... was first approved)
- ⏳ Reputation score: **10 / 100** (waiting for judge bot to process us)
- ⏳ Validation score: **0 / 100** (now judge-only, was self-postable until today 5:17 AM)

**Strategy:**
1. Submit MORE trade intents (target: 60-80 total) before judge bot's next 4h cycle
2. Wait for judge bot to score us (next cycle ~4-8 hours from 5:17 AM today)
3. Re-check leaderboard tomorrow morning
4. Open Discord ticket asking how reputation is precisely computed

### B. Kraken Challenge ⚠️ TAGGING ONLY (no leaderboard contention)

**Requirement (per Steve 3/31 + 4/2):**
- Real Kraken CLI execution
- Real money (paper does NOT count for leaderboard)
- Read-only API key submitted in main lablab submission form

**Our reality:**
- ❌ No real money to risk
- ⚠️ Windows: Kraken CLI binary doesn't work natively (need WSL or REST API workaround)
- ✅ We DO have `src/execution/kraken_cli.py` wrapper code

**Strategy:**
- Submit project tagged with **both** challenges (allowed per hackathon rules)
- **Will NOT appear** on the Kraken PnL leaderboard
- **WILL get credit** for "Application of Technology" since the integration code exists
- **Show paper trading demo** in the pitch video (paper data, not for leaderboard)
- Steve confirmed (4/4): "submission form has been updated, you can now submit your kraken API key (read only) in the submission form" — we will leave this field empty or note "paper-only demo"

---

## 3. Judging dimensions (4 × 25%)

| Criterion | Weight | Our state | What helps |
|---|---|---|---|
| **Application of Technology** | 25% | **STRONG** | 9-stage pipeline, 310 tests, RAG real, Nogran PA KB, multi-provider LLM, ERC-8004 5/5 contracts, Kraken CLI integration code, Docker, CI matrix |
| **Presentation** | 25% | **MEDIUM-STRONG** | Streamlit dashboard 8 abas, README hackathon section, pitch-script ready, 8 docs |
| **Impact / practical value** | 25% | **STRONG** | Risk Engine independent of LLM, 31 approved on-chain trades, hard veto matrix, audit trail |
| **Uniqueness & creativity** | 25% | **STRONGEST** | Nogran PA KB hallucination detector, Python rule-based RAG retriever (no vector DB), 11 bugs documented in transparency log |

**+ Leaderboard ranking** (unknown weight): currently rank 40/40 by reputation,
expected to jump to ~12-18 after judge bot processes our 31+ trades.

---

## 4. The 11 bugs we hunted (full list)

Documented in detail in `docs/session-debugging-log.md`. Summary:

1. **`ExposureManager` wall-clock bug** — backtest capped at 4 trades silently
2. **Backtest stop/target override** — overwrote LLM's structure stops with mechanical ATR
3. **`rr_min` filter** rejecting valid Nogran PA scalps (1:1 RR shaved bars)
4. **Default Gemini model alias** to gemini-3-flash (20 req/day quota)
5. **Fee-unaware prompt** — LLM picked math-impossible 0.2% reward setups
6. **EIP-712 v-byte format** (THE CRITICAL ONE) — `eth_keys` returns v∈{0,1}, OpenZeppelin needs v∈{27,28}, all 10 first trade attempts silently rejected
7. **Pending nonce collision** — `get_transaction_count('latest')` instead of `'pending'`
8. **Sepolia RPC fallback** — `rpc.sepolia.org` is unreliable, needs alternatives
9. **Prompt language** — Portuguese gave weaker reasoning than English (Nogran PA original lang)
10. **No RAG retriever** — PA chunks were ignored, LLM relying on training data
11. **`Config.TIMEFRAME_EXEC = "1m"`** — The rule states "never trade <5m"

**This document is part of our submission.** We claim "honesty about bugs found
and fixed" as a competitive differentiator vs polished happy-path pitches.

---

## 5. Critical Discord findings (compiled)

### Steve's clarifications (the timeline matters)

| Date | Source | Content |
|---|---|---|
| 3/31 3:46 AM | Steve | "Kraken Challenge requires real Kraken CLI execution. Rankings based on net PnL verified via read-only API key. **Simulated environment won't show up on the leaderboard**." |
| 3/31 3:46 AM | Steve | "ERC-8004 Challenge requires on-chain activity through Vault and RiskRouter; performance measured on-chain." |
| 4/2 3:20 PM | Steve | Direct confirmation: paper trading "Yes it won't" be counted for leaderboard. |
| 4/4 8:54 AM | Steve | "Submission form has been updated, you can now submit your kraken API key (read only) in the submission form with your GitHub/demo links." |
| 4/6 4:30 AM | Steve | **"Vault claim is OPTIONAL"** — judging based on on-chain activity + validation, not vault claim. |
| 4/8 5:17 AM | Steve | **"Validation scores are now judge only"** — closed open validation. Judge bot handles all attestations every 4 hours based on on-chain activity. **Reputation is the actual rank metric.** |
| 4/8 5:17 AM | Steve | Display bug: trade count was rolling 1h, not lifetime. Fix in progress. |

### Konstantin's consolidated Q&A repo (gold mine)

https://github.com/disciplinedware/swiftward-ai-trading-agents/blob/main/docs/hackathon-discord-qa.md

Key finding: **"the leaderboard ranks agents with validation score as the primary
metric and reputation score as the tiebreaker"** — but this was BEFORE Steve closed
open validation today. Now reputation is primary.

### GhostAgent insight (3/12)

> "Where did `validationRequest` come from? It's in the ERC-8004 spec but
> the ValidationRegistry was **never deployed** with that function. The spec
> describes the concept but the contract doesn't have it."

This explained why we couldn't trigger validation ourselves — the spec/deployed
mismatch. Now resolved by Steve announcing judge bot.

---

## 6. The leaderboard right now (snapshot from user, ~2026-04-08 evening)

40 agents total, we are rank 40. Top 10:

| Rank | Agent | Intents | Val (legacy) | Reputation |
|---|---|---|---|---|
| 1 | Random Trader | 103 | 100 | 77 |
| 2 | APEX | 4 | 100 | 74 |
| 3 | Swiftward Alpha | 21 | 100 | 70 |
| 4 | Actura | 75 | 99 | 99 |
| 5 | ARIA-MASTER | 87 | 99 | 99 |
| 6 | JudyAI WaveRider | 59 | 98 | 90 |
| 7 | AI Trading Agent (C.luna80) | 404 | 97 | 97 |
| 8 | CorrArbAgent-v1 | 28 | 93 | 86 |
| 9 | DeltaHedge | 1 | 92 | 71 |
| 10 | Symbolic Trader | 5 | 92 | 45 |
| ... | ... | ... | ... | ... |
| 40 | **nogran.trader.agent** | **31** | **0** | **10** |

**Important caveats:**
- Validation scores from ranks 1-3, 9, 14, 16 (low intent counts, high val) were posted via the OLD self-attestation (now closed). Their reputation is the real metric.
- The "intents" column was a 1h rolling display bug. Real lifetime counts will show after fix.
- Agent ranking expected to shake out significantly once judge bot runs the next 4h cycle and the display bug is fixed.

---

## 7. Action plan (next 4 days)

### TODAY (rest of session)
- [ ] Submit +30 to +50 more trade intents (push reputation push) — **eu**
- [ ] Stop the slow background smoke 1000c if not done by midnight — **eu**
- [ ] Commit + push all current changes — **eu**

### TOMORROW (April 9)
- [ ] Check leaderboard at 9 AM — see if judge bot scored us — **você**
- [ ] **Submit project on early.surge.xyz** — REQUIRED for prize eligibility — **você**
- [ ] **DM @Nathan Kay on Discord** for Surge Discovery profile polish + badges — **você**
- [ ] **Open ticket in #create-a-ticket** asking how reputation is computed precisely — **você**
- [ ] **Q&A 6PM CEST** — ask Steve about leaderboard weight in final scoring + reputation criteria — **você**
- [ ] Add EIP-712 signing tests (deferred from earlier) — **eu**
- [ ] Live paper trading: run nogran with Gemini + RAG for video pitch material — **eu**

### DAY 3 (April 10)
- [ ] Run agent live for full day, gather data — **eu**
- [ ] Polish dashboard with new approved trades + reputation update — **eu**
- [ ] Update README with final live numbers — **eu**
- [ ] Re-check leaderboard, screenshot for video — **você**
- [ ] Practice video pitch run — **você**

### DAY 4 (April 11) — FREEZE DAY
- [ ] **Record video pitch** (script ready in `docs/pitch-script.md`) — **você**
- [ ] Final commit + tag `v1.0-hackathon` — **eu**
- [ ] **Submit on lablab portal** with: video link, GitHub URL, demo URL, brief description — **você**
- [ ] Submit empty/skip Kraken API key field (we're not on that leaderboard) — **você**
- [ ] **Post on X tagging @lablabai @Surgexyz_** with video — **você**
- [ ] Update Surge Discovery profile if Nathan responded — **você**

---

## 8. What we're NOT doing (and why)

| Not doing | Reason |
|---|---|
| ❌ Real-money Kraken trading | No funds + risk management says no |
| ❌ Multi-asset (BTC + ETH + SOL) | Time-budget tradeoff: pitch quality > diversity |
| ❌ Live Strategy Engine pipeline | Migrated to Python LLM (judges can't run LLM) |
| ❌ Aerodrome DEX integration | Optional, time better spent elsewhere |
| ❌ PRISM API multi-asset data | Optional bonus, time-constrained |
| ❌ Self-attesting validation scores | No longer possible (judge-only as of today 5:17 AM) |
| ❌ Submitting >100 trade intents | Diminishing returns; judge bot looks at quality + volume |

---

## 9. Where we WIN

The hackathon judges rate on 4 dimensions × 25% + leaderboard (unknown weight).
We're strong in 4/4 dimensions:

1. **Application of Tech** — 9-stage pipeline, 310 tests, 11 bugs hunted, multi-provider LLM, full ERC-8004 integration
2. **Presentation** — 8-tab dashboard, 8 docs, video pitch script ready, README with real numbers
3. **Impact** — Risk Engine independent of LLM, 31 approved on-chain trades, hard veto matrix
4. **Uniqueness** — **Nogran PA KB hallucination detector** (no other agent has this), Python rule-based RAG retriever (innovative — no vector DB needed), bug-hunting transparency

**Our pitch story:**
> "We don't claim to be the most profitable. We claim to be the most honest. And in
> trading, the second one outlasts the first."

---

## 10. Open questions for organizers

1. **What % of final scoring is the leaderboard vs the 4 qualitative criteria?** (vikram asked, no answer yet)
2. **How exactly does the judge bot compute reputation?** (volume? approved-rate? quality of signals?)
3. **Will the trade count display fix bring our 31 → higher number?** (Steve confirmed it was rolling 1h)
4. **Is there a deadline by which we must have certain reputation to be considered?**
5. **Submission format:** what fields are mandatory vs optional?

**Plan to get answers:**
- Open ticket in `#create-a-ticket` (formal channel)
- Attend Q&A Thursday April 9 6PM CEST
- DM Steve directly with @Steve | lablab.ai

---

## 11. References (all our docs)

| Doc | Purpose |
|---|---|
| **`docs/master-strategy-2026-04-08.md`** | **THIS FILE — single source of truth** |
| `docs/leaderboard-analysis-2026-04-08.md` | Detailed competitor analysis with ranks |
| `docs/session-debugging-log.md` | 11 bugs hunted in detail (pitch material) |
| `docs/pitch-script.md` | Video pitch script (3 min) + Q&A prep |
| `docs/hackathon-criteria.md` | Original hackathon criteria analysis |
| `docs/trader-requirements.md` | A-G checklist of submission requirements |
| `docs/strategy-fee-drag-finding.md` | Critical fee drag finding |
| `docs/python-llm-migration.md` | LLM → Python LLM migration design |
| `docs/competitive-analysis.md` | First competitive scan (47 agents) |
| `docs/feature-gap-audit.md` | Nogran PA spec audit (56 items) |
| `docs/tech-debt.md` | Tech debts resolved |
| `README.md` | Public-facing summary with live numbers |
