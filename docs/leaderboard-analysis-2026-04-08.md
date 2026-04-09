# Leaderboard Analysis & Strategy Pivot

> **Date:** 2026-04-08 (afternoon, 4 dias antes do hackathon freeze)
> **Source:** lablab.ai live leaderboard at https://lablab.ai/ai-hackathons/ai-trading-agents/live
> **Status:** STRATEGIC PIVOT — earlier assumptions about validation scoring were wrong

---

## Snapshot: where we are

| Metric | Value |
|---|---|
| **Rank** | **40 / 40** (last) |
| **Validation score** | **0** |
| **Reputation score** | **10** (floor) |
| **Trade intents submitted** | 31 (approved on-chain) |
| **Capital allocated** | 0.0010 ETH (vault claimed) |
| **Registered** | Apr 8, 2026 (latest registration in the field) |

---

## Critical insight: validation score is NOT volume-driven

The most important pattern in the leaderboard is the **lack of correlation** between trade activity and validation score:

| Rank | Agent | Intents | Validation | Reputation |
|---|---|---|---|---|
| 2 | **APEX** | **4** | **100** | 74 |
| 3 | **Swiftward Alpha** | **21** | **100** | 70 |
| 7 | AI Trading Agent | 404 | 97 | 97 |
| 9 | **DeltaHedge** | **1** | **92** | 71 |
| 10 | **Symbolic Trader** | **5** | **92** | 45 |
| 14 | **Sentinel** | **1** | **85** | 58 |
| 16 | **AlphaBot** | **1** | **82** | 64 |
| 17 | HackathonTradingAgent | 376 | 81 | 87 |
| 22 | **Riptide** | **438** | **77** | 88 |

**Key proof points:**

- **APEX with 4 intents has score 100. Riptide with 438 has 77.** Volume hurts more than helps.
- **DeltaHedge with 1 single intent has score 92.** A single trade can score top 10.
- **Bottom 13 agents (rank 28-40) all have validation 0**, regardless of activity (1 to 31 intents).
- **All bottom-cohort agents have reputation between 10-37** (we are at 10, the floor).

**Conclusion:** the validation score is **decoupled from intent volume**. Some other criterion drives it.

---

## What it might be

Without official documentation, my best hypotheses (in order of plausibility):

1. **Time-since-registration based.** Validators may run periodic batch jobs that score agents older than N days. Top scorers registered Apr 6-7. We registered Apr 8. **Counter-evidence:** DeFi Guardian registered Apr 4 and is still val=0.

2. **Manual lablab assignment.** The validator wallet (`0x075DC84C...`) is the same address as registered agent "Riptide" (id 24). Maybe lablab whitelisted Riptide as a peer validator and they review agents manually.

3. **External oracle / trade quality assessment.** A backend service may be reading trade intents and rating quality (R/R, format compliance, asset diversity, sustained activity, etc.) and posting attestations.

4. **Account age / wallet reputation.** Wallets with prior on-chain activity may get higher validation. Our wallet is brand new.

5. **Random / seed-bias.** Some test agents (rank 1-3) might be operator-seeded to provide a baseline.

---

## What this changes about our strategy

### What we WERE planning (now invalid)
- ❌ "Submit 50-100 more trade intents to climb the leaderboard" — **WON'T WORK**
- ❌ "Activity = visibility = validation score" — **PROVEN FALSE**
- ❌ "Scale on-chain submissions" — **PURE COST, NO BENEFIT**

### What we should do INSTEAD

| Priority | Action | Why |
|---|---|---|
| **P0** | **Ask in Discord `#participants-chat-ai-trading-...`** how validation score is determined | Direct answer from organizers |
| **P0** | **Attend Q&A Thursday April 9, 6PM CEST** in Discord general Q&A stage | Live answers if no async response |
| **P1** | **Check the official template** `github.com/Stephen-Kimoi/ai-trading-agent-template` for any validator integration we might be missing | The template may show "expected" patterns |
| **P1** | **Read `SHARED_CONTRACTS.md`** in the template repo carefully | Official guidance on what each contract expects |
| **P2** | **Stop submitting more intents** beyond the 31 we already have | They cost gas and don't help score |
| **P2** | **Focus on what we control:** PnL leaderboard (live trading), pitch quality, code documentation, multi-asset diversity | These are uncoupled from the validator scoring mystery |
| **P3** | **Add ETH as second pair** (PRISM API gives free multi-asset data) | Diversification might be a soft signal |
| **P3** | **Wait 24h** to see if a periodic validator job catches us | Cheapest option |

---

## Discord channel data dump from 2026-04-08

Important hackathon info we didn't have before:

### Dates (correct)
- **Start:** March 30, 2026
- **End:** April 12, 2026 (4 days remaining)

### Vault claim is OPTIONAL (Apr 6 announcement)
> "Judging is based on your on-chain trade activity and validation scores, **not the vault claim**."
> — Steve | lablab.ai

We already claimed it (won't hurt). But this confirms the focus should be elsewhere.

### Surge submission is required
- Submit project at **early.surge.xyz** to be eligible for prizes
- DM @Nathan Kay on Discord for Surge Discovery profile polish + badge allocation
- "Build in public" is encouraged (livestream)

### Kraken docs corrections (Apr 1)
- Use `BTCUSD` standard ticker, NOT `XBTUSD` (we have 4 references in src/main.py to fix)
- Use `kraken paper init --balance 10000 --currency USD` first
- `kraken -o json balance` (NOT `--json`)
- `ticker BTCUSD` (positional, not `--pair`)
- `order buy BTCUSD 0.001 --type market` (NOT `order add`)
- Paper trading commands: `kraken paper buy BTCUSD 0.001`, `kraken paper sell BTCUSD 0.001`, etc.
- MCP runs over stdio, NOT `--port`. Example config:
 ```json
 {
 "mcpServers": {
 "kraken": {
 "command": "kraken",
 "args": ["mcp", "-s", "all", "--allow-dangerous"]
 }
 }
 }
 ```

### Aerodrome added as DEX option
- Optional execution layer for swaps/liquidity strategies
- Not required for our submission (we use Kraken)

### PRISM API ($10 free credits with code `LABLAB`)
- https://prismapi.ai/
- Multi-asset market data (crypto, stocks, forex)
- Endpoints:
 - `/resolve/{asset}` → universal asset identity
 - `/crypto/{symbol}/price` → real-time prices
 - `/signals/{symbol}` → AI signals
 - `/risk/{symbol}` → volatility + metrics
- **Could resolve our multi-asset support need** without writing CCXT code per pair

### Reference template
- https://github.com/Stephen-Kimoi/ai-trading-agent-template
- Key file: `SHARED_CONTRACTS.md`
- Production patterns we may be missing

---

## Action plan (final, replacing previous)

### Today (rest of session, ~1h)
- [x] Document this analysis (this file)
- [ ] Fix XBTUSD → BTCUSD in `src/main.py` (4 references)
- [ ] Read template repo's SHARED_CONTRACTS.md and `src/agent/`
- [ ] Update `docs/competitive-analysis.md` with leaderboard data
- [ ] **STOP** the in-progress smoke 1000c if not finished by midnight (it's slow)

### Tomorrow (April 9)
- [ ] **You** submit project on early.surge.xyz
- [ ] **You** DM @Nathan Kay on Discord for Surge Discovery polish
- [ ] **You** ask in `#participants-chat-ai-trading-...` how validation works
- [ ] **You** attend Q&A 6PM CEST
- [ ] **Me** integrate PRISM API for multi-asset data (BTC + ETH)
- [ ] **Me** start live paper trading agent in background (Gemini + RAG)
- [ ] **Me** add EIP-712 signing tests (deferred from earlier)

### Day 3 (April 10)
- [ ] Run agent live for 24h, collect real trade data
- [ ] Update README with live numbers
- [ ] Polish dashboard
- [ ] Validate validation score updated (re-check leaderboard)

### Day 4 (April 11) — Freeze day
- [ ] Record video pitch (script ready in `docs/pitch-script.md`)
- [ ] Final commit + tag
- [ ] Submit on lablab portal
- [ ] Submit Kraken API key form
- [ ] Post Surge profile + tag @lablabai @Surgexyz_

---

## What this analysis cost us to learn

Roughly 6 hours of debugging + on-chain submissions thinking that "more activity = better score". The 31 trade intents we submitted (and the EIP-712 fix that enabled them) are not wasted — they validate the pipeline works end-to-end. But the **strategic assumption was wrong**, and now we have a much clearer picture.

**The single most valuable thing** in the rest of the hackathon: **getting the validation score updated above 0**. If we crack that (even to score 50), we jump from rank 40 to rank ~28. If to score 80, rank ~20.

**The second most valuable thing:** the qualitative judging dimensions (4 criteria × 25%). Validation+PnL leaderboard is half the score; the other half is application/presentation/impact/uniqueness, where we can WIN with the materials we already have.

---

## 🚨 MAJOR UPDATE 2026-04-08 — Steve announces validation is judge-only

**Steve | lablab — today 5:17 AM CEST:**

> "**Validation scores are now judge only.** We've closed open validation on the
> ValidationRegistry. Going forward, only the official judge bot can post validation
> attestations. This ensures scores are objective and consistent across all teams."
>
> "If you previously submitted self-attestations, those remain on-chain but **your
> Reputation score (which drives your actual rank) is computed solely by the judge
> bot**, so nothing changes for how you're evaluated."
>
> "**The judge bot handles all attestations automatically every 4 hours based on
> your on-chain activity.**"

### What this means

1. **Reputation** is the new primary ranking metric (not validation)
2. **Judge bot is the only validator** going forward
3. **Runs every 4 hours**
4. **Based on on-chain activity** (volume + quality of trade intents)
5. **Self-posting was killed** because of the C.luna80-style farming

### Re-correlating reputation with activity

Looking at the data again with this lens:

| Agent | Intents | Validation (legacy) | **Reputation** | Rank |
|---|---|---|---|---|
| AI Trading Agent | 404 | 97 | **97** | 7 |
| ARIA-MASTER | 87 | 99 | **99** | 5 |
| Actura | 75 | 99 | **99** | 4 |
| HackathonTradingAgent | 376 | 81 | **87** | 17 |
| Riptide | 438 | 77 | **88** | 22 |
| APEX (legacy self-attest) | 4 | 100 | **74** | 2 |
| DeltaHedge (legacy) | 1 | 92 | **71** | 9 |
| **nogran (us)** | **31** | 0 | **10** | **40** |

**Reputation IS volume-correlated.** The agents with 75-438 intents have 87-99 reputation.
The agents with 1-4 intents have 71-74 reputation (close to floor).

Our 31 intents should put us around **70-80 reputation** once the judge bot processes us.
That would jump us from rank 40 to **rank ~12-18**.

### Display bug confirmed

> "We're aware of the issue where trade counts appeared to decrease or reset unexpectedly.
> **This was a display bug, the leaderboard was reading a rolling 1-hour window instead
> of your total lifetime trades.** The fix is being rolled out now."

Our "31 trade intents" was the rolling 1h count, not lifetime. Other agents may have many more.

### Strategic pivot AGAIN

| Old plan (valid yesterday) | New plan (valid 5:17 AM today) |
|---|---|
| ❌ Stop submitting trades (validation not volume-based) | ✅ **Submit MORE trades** (reputation IS volume-based) |
| ❌ Open ticket asking about validation criteria | ✅ Open ticket asking about reputation precisely |
| ❌ Wait for validator attestation | ✅ Wait for judge bot cycle (4h) |
| ✅ Q&A Thursday | ✅ Q&A Thursday — ask about leaderboard weight in final scoring |

### Open questions still unanswered

vikram asked (today, no answer yet):
> "what's the point of the leaderboard if the main criteria is validation score and this score is controlled by us... how much percent of leaderboard is considered for final evaluation?"

The first half is now answered (judge bot, not self). The second half — **what % of final scoring is the leaderboard vs the 4 qualitative criteria** — remains the most important unanswered question.

---

## Smoking gun from `#participants-chat` (2026-03-12, GhostAgent)

> "Where did `validationRequest` come from? It's in the ERC-8004 spec document
> (ERC8004SPEC.md) as a described mechanism, and it was stored as a mandatory
> requirement. The spec describes the concept but the **ValidationRegistry was
> never deployed** — no contract with that function selector exists at any of
> the deployed addresses. **The confusion came from treating spec docs as
> deployed reality.**"

**This confirms our hypothesis.** The ERC-8004 spec describes a `validationRequest`
mechanism that does NOT exist in the deployed RiskRouter/ValidationRegistry. So
validation scoring **must be running through some off-chain mechanism** (manual
review, periodic batch job, oracle, or whitelisted validator wallets) that nobody
has documented publicly. We can't trigger it from our agent's calls.

This means: the only realistic ways to get validated are:
1. **Wait** for whatever periodic/batch process is running
2. **Open a ticket** in Discord `#create-a-ticket` and ask directly
3. **Attend Q&A Thursday April 9** and ask live

## Open question for organizers

**"Hi team, our agent (id 44, nogran.trader.agent, 0xe852...) has 31 approved trade intents on RiskRouter, all post-EIP712 fix, but our ValidationRegistry score is still 0 after 8 hours. Looking at the leaderboard, I see APEX with 4 intents at score 100 and DeltaHedge with 1 intent at score 92, while Riptide with 438 intents is only at 77. What determines the validation score? Is it time-based, validator-discretion, or do we need to do something specific to be picked up? Thanks."**

This is the question to ask in Discord.
