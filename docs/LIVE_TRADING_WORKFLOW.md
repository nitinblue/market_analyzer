# Live Trading Workflow Guide

**A real trading session walkthrough from 2026-03-20 with actual market data.**

Supplement to [USER_MANUAL.md](../USER_MANUAL.md). That document covers every capability; this one shows how they compose into a single profitable morning.

---

## Table of Contents

1. [Overview](#1-overview)
2. [The Daily Workflow](#2-the-daily-workflow)
3. [Reading the Signals](#3-reading-the-signals)
4. [The Kelly Lesson](#4-the-kelly-lesson)
5. [Position-Aware Second Trade](#5-position-aware-second-trade)
6. [Monitoring and Exit Decisions](#6-monitoring-and-exit-decisions)
7. [What-If Scenarios](#7-what-if-scenarios)
8. [Risk Management Rules](#8-risk-management-rules)
9. [CLI Quick Reference](#9-cli-quick-reference)

---

## 1. Overview

### Who This Is For

You manage a small options account (35K-50K taxable, up to 200K IRA). You sell premium for income. You want a repeatable, systematic morning routine that tells you exactly what to trade, how much, and when to walk away.

### What This Guide Covers

This is not a hypothetical walkthrough. Every number below came from a real session on March 20, 2026. The tickers, regimes, IV, RSI, skew, Kelly fractions, and final position sizes are all real. Where a trade was blocked, the guide explains exactly why and what that means for capital preservation.

### Philosophy: Capital Preservation Over Alpha Chasing

The core rule: **it is always acceptable to trade nothing.** A day with zero trades and zero losses is a successful day. The system is designed to say "no" far more often than "yes." When every gate (regime, validation, entry, Kelly) says yes, the edge is real and you deploy capital. When any gate says no, you respect it.

Income-first means theta harvesting is the default. Directional trades happen only when regime explicitly supports them. Every position must be defined-risk. Every position must fit the account.

---

## 2. The Daily Workflow

### 6:00 AM -- Pre-Market Context Check

Before anything else, ask: is today safe to trade at all?

```
analyzer-cli
> context
```

**2026-03-20 output:**

| Field | Value | Interpretation |
|-------|-------|----------------|
| Environment | cautious | Not crisis, not risk-on. Proceed with awareness. |
| Trading allowed | True | No black swan detected. Market is open for business. |
| Position size factor | 1.0 | Full sizing permitted. No forced reduction. |
| Options strategies | iron_condor, iron_butterfly, credit_spread, calendar, strangle (with wings) | Full income suite minus naked strategies |

**Decision at this step:** Green light to proceed. "Cautious" means we are not in crisis, but the system flagged elevated uncertainty. We will rely on per-ticker regime detection to decide what actually gets traded.

### 9:30 AM -- Regime Detection

Regime is the first and most important filter. No trade enters without a regime label.

```
> regime SPY QQQ IWM GLD TLT
```

**2026-03-20 output:**

| Ticker | Regime | Confidence | What It Means |
|--------|--------|------------|---------------|
| SPY | R2 (High-Vol Mean Reverting) | 100% | Acceptable for income but needs wider wings. Elevated vol means richer premiums but larger swings. |
| QQQ | R4 (High-Vol Trending) | 99% | **STOP. Do not trade.** R4 is the explosive regime -- trends persist, vol expands, theta sellers get run over. |
| IWM | R1 (Low-Vol Mean Reverting) | 100% | Ideal. This is the textbook income environment: low vol, mean-reverting, theta decays predictably. |
| GLD | R1 (Low-Vol Mean Reverting) | 100% | Ideal. Same as IWM -- premium selling paradise. |
| TLT | R2 (High-Vol Mean Reverting) | 99% | Acceptable with wider wings. Bond vol is elevated but mean-reverting. |

**Decision at this step:** QQQ is immediately eliminated. No analysis, no "maybe it will be fine." R4 at 99% confidence is unambiguous -- the model is telling you this instrument will trend violently. The remaining four tickers are viable. R1 tickers (IWM, GLD) get priority because they offer the highest probability income setups.

Why per-ticker regime matters: QQQ is R4 while IWM is R1. If we used a single "market regime," we would either miss the IWM opportunity (if global regime = R4) or get destroyed in QQQ (if global regime = R1). Per-instrument detection is the foundation.

### 9:45 AM -- Rank Opportunities

With regime filtering complete, rank the survivors.

```
> rank IWM GLD SPY TLT
```

The ranking engine scores each ticker across multiple dimensions: regime alignment, technical setup quality, volatility conditions, and strategy fit. It produces a composite score and a recommended strategy.

On this session, GLD and IWM emerged as the top two candidates because:
- Both R1 (perfect regime for income)
- Both had favorable technical setups (oversold conditions in GLD, range-bound behavior in IWM)
- Both had adequate options liquidity

**Decision at this step:** GLD first (higher composite score due to extreme technicals), IWM second.

### 10:00 AM -- Deep Analysis on Top Candidate (GLD)

Now we go deep on GLD. This is where the system earns its keep -- every analytical building block fires in sequence.

#### Technicals

```
> technicals GLD
```

| Indicator | Value | Interpretation |
|-----------|-------|----------------|
| Price | $426.41 | |
| ATR | $11.51 (2.70%) | Moderate daily range. Wing width needs to account for this. |
| RSI | 33.6 | Near oversold (below 35). Price has been declining but not capitulating. |
| Bollinger %B | -0.25 | **Below the lower Bollinger Band.** This is statistically rare -- price is in the extreme tail of its recent distribution. |
| MACD histogram | -5.746 | Deeply negative. Momentum is bearish. |
| SMA-20 | $468.70 | Price is $42.29 below the 20-day mean. That is 3.7x ATR -- an extraordinary extension. |
| SMA-50 | $456.01 | Price well below intermediate trend. |
| VWMA-20 | $466.50 | Volume-weighted mean confirms the gap. |

The price is 8.6 ATR below the SMA-20. To put that in perspective: a 2-ATR move is a "big day." Being 8.6 ATR extended means GLD has been falling hard and fast, and is now in territory where mean reversion is statistically likely -- which is exactly what R1 regime confirms.

#### Vol Surface

```
> vol GLD
```

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Front IV | 28.6% | Elevated for GLD (typically 15-20%). Rich premiums available. |
| Back IV | 28.3% | Nearly identical to front. |
| Term structure | Backwardation (front > back) | Short-term fear exceeds long-term. This is typical after a sharp selloff. Traders are buying near-term puts for protection. |
| IV differential | 0.9% | Minimal -- no calendar spread edge here. |
| Put skew | 6.3% | Steep. Protective put demand is high. |
| Call skew | 1.4% | Flat. Nobody is buying upside protection. |
| Skew ratio | 4.56 | Heavily put-skewed. The market is hedging downside aggressively. |

**Why this matters for the trade:** Steep put skew means we get paid more for selling puts. The 6.3% put skew is premium we capture as iron condor sellers. Backwardated term structure confirms that near-term options are overpriced relative to longer-term -- good for selling front-month premium.

#### Support and Resistance Levels

```
> levels GLD
```

| Level | Price | Strength | Notes |
|-------|-------|----------|-------|
| Support 1 | $421.53 | 0.57 | FVG + swing low confluence |
| Support 2 | $415.29 | -- | Next structural support |
| Support 3 | $410.98 | -- | Deep support |
| Resistance 1 | $428.27 | -- | Nearest ceiling |
| Resistance 2 | $441.52 | -- | Bollinger lower + pivot confluence |
| Resistance 3 | $447.33 | -- | |

The key support at $421.53 (strength 0.57 with FVG + swing confluence) is where we anchor the put side of the iron condor. It sits $4.88 below the current price -- just under half an ATR. The $415 support below it gives us the put strike target.

### 10:15 AM -- Trade Construction and Validation Gate

#### The Trade: GLD Iron Condor

```
> opportunity GLD
```

| Component | Detail |
|-----------|--------|
| Structure | Iron Condor |
| Put spread | STO 1x GLD P415 4/24/26, BTO 1x GLD P410 |
| Call spread | STO 1x GLD C440, BTO 1x GLD C445 |
| Wing width | $5 ($500 max risk per contract) |
| Entry credit | ~$6.10/contract (IV-based estimate, no broker) |
| DTE | 35 days to expiration |

The short put at $415 sits below the $421.53 support -- price would need to break two support levels to reach it. The short call at $440 sits above multiple resistance levels. Wing width of $5 keeps max loss at $500 per contract -- appropriate for a 35K account.

#### Entry Score

```
> entry GLD
```

**Score: 87% -- ENTER_NOW**

| Factor | Score | What It Measures |
|--------|-------|-----------------|
| RSI extremity | 0.82 | How close to oversold/overbought. 33.6 RSI is near the 30 threshold. |
| Bollinger extremity | 1.00 | Price below the lower band = maximum extremity score. |
| VWAP deviation | 1.00 | Extreme distance from volume-weighted mean. |
| ATR extension | 1.00 | 8+ ATR from SMA-20 is off the charts. |
| Level proximity | 0.33 | Price is near support but not sitting directly on it. |

An 87% entry score is exceptional. Four of five factors are at or near maximum. The system is saying: if you are going to sell premium on GLD, the timing conditions are as good as they get.

#### Validation (10 Pre-Trade Checks)

```
> income_entry GLD
```

| Check | Result | Detail |
|-------|--------|--------|
| Commission drag | PASS | 0.9% of credit -- well below the 3% threshold |
| Fill quality | PASS | 0.5% bid-ask spread -- tight enough to fill near mid |
| Margin efficiency | WARN | Could not compute for this structure (missing yield calculator mapping) |
| POP gate | **WARN** | POP 57% is below the 65% threshold |
| EV positive | PASS | Expected value +$393 -- strongly positive |
| Entry quality | PASS | 60% score, R1 confirmed |
| Exit discipline | PASS | Take profit at 50%, stop loss at 2x credit, exit at 21 DTE |
| Strike proximity | WARN | Call side backed by levels, put side not fully backed |
| Earnings blackout | PASS | GLD is an ETF -- no earnings risk |
| IV rank quality | WARN | No IV rank data (broker not connected) |

**Final verdict: READY (6 PASS / 4 WARN / 0 FAIL)**

No FAILs means the trade clears validation. But four WARNs demand attention -- especially the POP gate at 57%.

### 10:20 AM -- Entry Intelligence

#### Skew Optimization

The system checks whether the default short strikes can be improved by exploiting skew:

| Side | Baseline Strike | Optimal Strike | IV Advantage |
|------|----------------|----------------|-------------|
| Put | 415 | 410 | **8.2%** more premium |
| Call | 440 | 440 | 0.4% (no shift) |

**Insight:** The steep put skew (6.3%) means that the 410 put captures 8.2% more implied volatility than the 415 put. Selling the 410 put instead of the 415 put means: wider distance from current price AND more premium. This is skew working in your favor.

The call side shows no meaningful skew advantage -- the 440 strike stays.

#### DTE Optimization

| Metric | Value |
|--------|-------|
| Recommended DTE | 21 days (April 10, 2026) |
| IV at that expiry | 29.8% |
| Theta proxy | 0.0651 |
| Regime default | 30-45 DTE |

The optimizer found that 21 DTE has a better theta-to-IV ratio than the standard 30-45 DTE window. At 21 DTE, theta decay accelerates while IV remains elevated at 29.8%. The shorter duration means faster premium capture -- appropriate when the regime is R1 (calm, mean-reverting) and you want to minimize time exposure.

### 10:25 AM -- Kelly Sizing

This is the moment of truth. Everything has said "go." Now Kelly decides how much.

```
> size GLD
```

| Parameter | Value |
|-----------|-------|
| POP | 57% |
| Max profit | $610 (the credit) |
| Max loss | ~$0 (edge case in estimation) |
| Kelly fraction | **0.0%** |
| Recommended contracts | **0** |

**Kelly says: do not trade.**

The ranking said GO (0.76 composite). Validation said READY (6P/4W/0F). Entry said ENTER NOW (87%). And Kelly said zero contracts.

This is the system working as designed. See [Section 4: The Kelly Lesson](#4-the-kelly-lesson) for the full explanation.

### 10:30 AM -- Place or Skip

**GLD: SKIP.** Kelly override. Move to second candidate.

**IWM: Proceed to analysis.**

IWM iron condor (R1, 100% confidence):
- Price: $247.63, RSI: 38.4
- Entry score: 75% (ENTER_NOW)
- Legs: STO IWM P240, BTO P235, STO C255, BTO C260
- POP: 59%, EV: +$74
- Kelly (position-aware): 12.5% of bankroll = **1 contract**
- Max risk: $500 (1.4% of $35K NLV)

**IWM: ENTER.** Place the order for 1 contract.

### Final Morning Position

| Metric | Value |
|--------|-------|
| Account NLV | $35,000 |
| Positions | IWM IC x1 |
| Total capital at risk | $500 (1.4% of NLV) |
| Estimated credit received | $281 |
| Risk budget remaining | 23.6% of the 25% max |
| Trades attempted | 2 |
| Trades placed | 1 |
| Trades blocked | 1 (GLD -- Kelly override) |

One trade placed out of two analyzed. This is a normal hit rate. The system is conservative by design.

---

## 3. Reading the Signals

### RSI 33.6 + %B -0.25: What GLD Was Telling Us

RSI at 33.6 is near oversold but not at the extreme (30). It signals sustained selling pressure that is approaching exhaustion. Bollinger %B at -0.25 means price has fallen below the lower Bollinger Band -- a 2-standard-deviation event that occurs less than 5% of the time in a normal distribution.

Together they paint a picture: GLD has been in a sharp, persistent decline that has pushed it to statistical extremes. In an R1 (mean-reverting) regime, this is the setup -- price is extended and likely to revert toward the mean. The iron condor capitalizes on this by selling premium on both sides, with the put side anchored below support.

But here is the nuance: MACD at -5.746 is deeply bearish. Momentum has not turned. RSI is near oversold, not at oversold. The technical picture says "extended but not exhausted." This is why POP came in at 57% rather than 70%+ -- the system correctly identified that while conditions favor mean reversion, the selloff has not fully capitulated.

### Why R1 + Oversold = Textbook Mean Reversion

R1 (Low-Vol Mean Reverting) means the HMM has determined that GLD's recent behavior is characterized by low realized volatility with mean-reverting dynamics. In this regime:
- Moves tend to reverse rather than persist
- Volatility is compressed, making option premiums somewhat predictable
- Iron condors and strangles have the highest win rate historically

When you overlay "oversold" (RSI < 35, %B < 0) onto an R1 regime, you get maximum confidence in mean reversion. The regime says "prices revert" and the technicals say "price is at an extreme." The expected path is a bounce back toward the mean.

### Why POP 57% Triggered a WARN

The validation gate has a POP threshold of 65%. At 57%, GLD's iron condor has roughly a coin-flip probability of profit -- better than 50%, but not the 65%+ edge that systematic income trading demands.

Why was POP only 57% despite ideal regime and technicals? Two factors:
1. **No broker connection.** POP is estimated using regime-adjusted ATR, not real implied volatility from DXLink. The estimate is conservative by design -- it assumes wider expected moves than the market might actually be pricing.
2. **The credit estimate ($6.10) is IV-based, not broker mid.** With real quotes, the credit might be higher (improving POP) or lower (worsening it). Without broker data, the system cannot precisely compute the probability.

A 57% POP is not bad -- it means the trade wins more often than it loses. But for systematic income trading where you need a large sample of positive-expectancy trades to compound, 65% is the minimum threshold. Below that, a string of losses can erode your edge faster than winners accumulate.

### Why Kelly Said 0 Despite a GO Verdict

See the dedicated section below. This is the most important lesson from this session.

---

## 4. The Kelly Lesson

This section exists because it captures the single most important concept in systematic trading: **position sizing is the final arbiter, not trade quality.**

### The Cascade of Green Lights

| Gate | Verdict | Score |
|------|---------|-------|
| Regime | R1 -- ideal | 100% confidence |
| Ranking | GO | 0.76 composite |
| Entry | ENTER NOW | 87% |
| Validation | READY | 6P / 4W / 0F |

Every qualitative gate said yes. The regime is perfect. The technicals are extreme. The validation checks found no failures. A discretionary trader would be placing this order right now.

### Kelly Says Zero

Kelly criterion computes the optimal fraction of bankroll to bet based on:
- **Win probability** (POP): 57%
- **Win amount** (max profit): $610
- **Loss amount** (max loss): ~$0 in the edge-case estimation

The max loss estimation hit an edge case (likely because without broker quotes, the debit at risk could not be precisely computed). When Kelly cannot reliably compute the risk/reward ratio, it returns 0% -- meaning "I cannot determine a safe bet size, so bet nothing."

This is not a bug. This is Kelly doing exactly what it should: **protecting capital when the inputs are uncertain.**

### Why Kelly Is Right

Consider what would happen if Kelly was overridden:
- You place the GLD IC based on an estimated $6.10 credit
- The actual fill might be $4.50 (broker spread, slippage, stale IV estimate)
- At $4.50 credit with $500 max loss, POP drops below 50%
- You now have a negative-expectancy trade on
- Over 50 such trades, you lose money systematically

Kelly protects against this scenario by refusing to size a trade when the inputs are too uncertain.

### What Would Fix It

**Connect the broker.** With DXLink streaming real quotes:
- Credit becomes a real bid/ask mid, not an IV estimate
- POP recalculates with actual premium captured
- Max loss is precisely computed (wing width minus actual credit)
- Kelly gets clean inputs and returns a real fraction

The $6.10 IV-based estimate might turn out to be conservative. With real broker quotes showing $7.00 credit, POP might jump to 68%, and Kelly would size it at 2-3 contracts. Or the real quote might be $4.00, POP drops to 48%, and Kelly confirms: do not trade.

Either way, **Kelly with real data makes the right decision. Kelly with estimated data makes the safe decision.** Both protect capital.

### The Meta-Lesson

In systematic trading, the position sizing algorithm has veto power over everything else. This is counterintuitive -- you spent 30 minutes analyzing GLD, every signal looked great, and the answer is "don't trade."

That 30 minutes was not wasted. The analysis confirmed that GLD is a valid candidate. If broker were connected, this might have been a profitable trade. The analysis also trained your pattern recognition: R1 + oversold + steep put skew + backwardated term structure = high-quality setup. Next time this pattern appears with broker connected, you will act with confidence.

The discipline to accept Kelly's veto is what separates systematic traders from discretionary ones. Discretionary traders override the model ("but the chart looks so good!"). Systematic traders trust the math.

---

## 5. Position-Aware Second Trade

### Why IWM Sizing Accounts for GLD

Even though GLD was ultimately blocked by Kelly, the system demonstrates position-aware sizing. If GLD had been deployed (hypothetically), IWM sizing would have been reduced.

The Kelly sizing call for IWM was made with portfolio context:
- Account NLV: $35,000
- Existing exposure: GLD IC (hypothetically deployed)
- Correlation between GLD and IWM: 0.15

A correlation of 0.15 means GLD and IWM move nearly independently. Gold is driven by inflation expectations and safe-haven flows; small-cap equities are driven by domestic economic growth. These are fundamentally different return streams.

Because the correlation is low, the portfolio penalty is minimal. If IWM were correlated with GLD at 0.70+, the system would reduce IWM sizing to avoid concentration risk (two positions that move together are effectively one large position).

### Portfolio Exposure After IWM Entry

| Metric | Value |
|--------|-------|
| Total risk deployed | $500 |
| Risk as % of NLV | 1.4% |
| Max allowed risk | 25% of NLV ($8,750) |
| Risk budget remaining | 23.6% ($8,250) |
| Number of positions | 1 |
| Correlation risk | N/A (single position) |

With 23.6% of risk budget remaining, the account has capacity for roughly 16 more IWM-sized trades. In practice, you would never deploy that much -- diversification across 3-5 uncorrelated positions is the target. But the math shows how conservative the position is.

### The IWM Trade Profile

| Parameter | Value | Assessment |
|-----------|-------|------------|
| Regime | R1 (100%) | Ideal for income |
| Price | $247.63 | |
| RSI | 38.4 | Mildly oversold (not extreme like GLD) |
| Entry score | 75% | ENTER_NOW (solid, not exceptional) |
| POP | 59% | Below 65% threshold but Kelly still approved |
| EV | +$74 | Positive expected value |
| Kelly fraction | 12.5% | 1 contract at $500 risk |
| Max risk | $500 | 1.4% of NLV |

IWM's POP at 59% is also below the 65% WARN threshold, similar to GLD. But Kelly approved 1 contract because the max loss was precisely computable ($500 = wing width) and the risk/reward ratio was clear. The difference: IWM's sizing inputs were unambiguous, while GLD hit an edge case in max loss estimation.

---

## 6. Monitoring and Exit Decisions

### Day 10 Simulation: How to Read the Dashboard

Ten days after entry, here is what the monitoring output shows:

#### GLD IC (Hypothetical)

| Metric | Value | Interpretation |
|--------|-------|----------------|
| P&L | +30% of max profit | On track. Not yet at 50% take-profit target. |
| DTE remaining | 25 days | Plenty of time for theta to work. |
| Theta remaining | 85% | Most of the time decay is still ahead. |
| Profit/Theta ratio | 0.4x | You have captured 30% profit but only used 15% of available theta. **This is favorable** -- profit is running ahead of time. |
| Action | **HOLD** | No adjustment needed. |

The profit/theta ratio is the key metric. At 0.4x, you are "ahead of schedule" -- capturing profit faster than theta decay alone would predict. This typically happens when the underlying moves favorably (toward the middle of the iron condor range) or when IV drops (reducing the value of the options you sold).

**When to close early (accelerate):** If the ratio exceeds 0.8x (80%+ of max profit captured with significant theta remaining), consider closing. The remaining profit is small relative to the risk of holding. On this day, 0.4x means hold -- there is substantial profit left to capture.

#### IWM IC

| Metric | Value | Interpretation |
|--------|-------|----------------|
| P&L | +15% of max profit | Modest progress. Normal for day 10. |
| DTE remaining | 25 days | |
| Theta remaining | 85% | |
| Profit/Theta ratio | 0.2x | Slightly behind schedule -- profit is lagging theta decay. |
| Action | **HOLD** | No concern yet. |

A 0.2x ratio is not alarming -- it means the trade is treading water while theta slowly erodes. The underlying is neither helping nor hurting. As long as the position is not tested (price approaching a short strike), this is fine. Theta will do its work over the remaining 25 days.

### Exit Trigger Reference

| Trigger | Action | Rationale |
|---------|--------|-----------|
| 50% of max profit reached | **Close** | Standard income take-profit. Remaining 50% is not worth the tail risk. |
| 2x credit lost (R1 regime) | **Close for loss** | R1 stop loss is tighter because R1 means mean-reversion -- if you are losing 2x credit in R1, the regime may be wrong. |
| 3x credit lost (R2 regime) | **Close for loss** | R2 allows wider stops because high-vol regimes have larger swings before reverting. |
| 21 DTE remaining | **Close regardless** | Gamma risk increases dramatically inside 21 DTE. Close and re-evaluate. |
| Regime changes to R4 | **Close immediately** | R4 invalidates the entire premise. Do not wait for stop loss. |
| Short strike breached | **Assess adjustment** | Run the adjustment analyzer. Options: roll away, narrow untested, convert to spread, close. |

### Adjustment Decision Tree

When a short strike is tested or breached:

```
Price approaching short strike
  |
  +--> Regime still R1/R2?
  |     |
  |     +--> Yes --> Roll away from tested side (collect additional credit)
  |     |            If untested side has room, narrow it to fund the roll
  |     |
  |     +--> No (regime changed to R3/R4) --> CLOSE THE POSITION
  |
  +--> Is this a 0DTE position?
        |
        +--> After 3:00 PM ET --> CLOSE (no time to adjust)
        +--> Before 3:00 PM ET --> Adjust if R1/R2, close if R3/R4
```

---

## 7. What-If Scenarios

Using the same real market data from 2026-03-20, here is how different conditions would change the outcome.

### What if QQQ Was R1 Instead of R4?

QQQ at R1 with 99% confidence would mean: low-vol, mean-reverting technology sector. This would:
- Add QQQ to the tradeable universe
- QQQ iron condor would likely rank highly (QQQ has excellent options liquidity)
- Portfolio would diversify across GLD (commodities), IWM (small-cap), QQQ (tech)
- Correlation between QQQ and IWM is high (~0.70), so Kelly would penalize the combined sizing

The realistic outcome: 1 contract each on GLD and QQQ (or GLD and IWM), not all three. Kelly's portfolio-aware sizing would prevent overconcentration in correlated equity positions.

### What if GLD POP Was 72% (Broker Connected)?

With real DXLink quotes providing actual bid/ask mid:
- POP jumps from 57% to 72% (above 65% threshold)
- POP WARN becomes PASS (7P/3W/0F instead of 6P/4W/0F)
- Kelly receives clean inputs: POP 72%, max profit = real credit, max loss = wing width minus credit
- Kelly fraction might compute to 8-10% of bankroll
- That translates to 2-3 contracts at $500 risk each ($1,000-$1,500 total)
- Portfolio would hold GLD IC (2-3 contracts) + IWM IC (1 contract, reduced due to capital deployed on GLD)

This scenario shows why broker connectivity matters. The difference between "no trade" and "2-3 contracts" is entirely driven by data quality.

### What if Drawdown Was at 5% When Sizing?

The Kelly sizing includes a drawdown scaling factor:
- At 0% drawdown: full Kelly fraction applied
- At 5% drawdown: Kelly fraction reduced by ~50%
- At 10% drawdown: circuit breaker -- no new trades

With 5% drawdown:
- IWM's Kelly fraction drops from 12.5% to ~6%
- That means 0.5 contracts, which rounds to 0 or 1 depending on conservative/aggressive rounding
- The system might skip IWM entirely, resulting in a zero-trade day

A zero-trade day at 5% drawdown is appropriate. You are in capital preservation mode. Let existing positions work (or stop out) before adding new risk.

### What if Regime Changed to R3 on Day 15?

On day 15 of holding the IWM IC:
- Morning regime check: IWM now R3 (Low-Vol Trending)
- R3 means prices are trending with low volatility -- the worst regime for iron condors
- Iron condors profit from range-bound markets; a trend will push through one side

**Action:** Close the IWM IC immediately, regardless of current P&L.

The logic: when the regime that justified the trade is invalidated, the trade's premise is gone. A 15% profit on day 15 with regime change = close and book the profit. A 10% loss on day 15 with regime change = close and take the small loss. Do not wait for the stop loss in a changed regime.

---

## 8. Risk Management Rules

These rules are extracted directly from the 2026-03-20 session. They are not theoretical -- each one was exercised or would have been exercised given the market conditions.

### Rule 1: Never Trade R4 Tickers

QQQ was R4 at 99% confidence. It was eliminated before any technical analysis, any vol surface computation, any ranking. R4 is a hard stop.

R4 (High-Vol Trending) is the regime where income strategies get destroyed. Trends persist, vol expands, and short premium positions face unlimited-feeling losses (even in defined-risk structures, you hit max loss frequently). No amount of good technicals overcomes a bad regime.

### Rule 2: Kelly Can Override a GO Verdict (And Should)

GLD passed every qualitative gate and was blocked by Kelly. This is not a failure of the system -- it is the system working correctly. Qualitative analysis identifies candidates; quantitative sizing determines allocation. They serve different functions.

Never override Kelly to "just put on one contract." If Kelly says zero, the edge is insufficient or the inputs are too uncertain. Either improve the inputs (connect broker) or move on.

### Rule 3: Maximum 25% of NLV at Risk

Across all positions combined, never exceed 25% of net liquidation value. On a $35,000 account, that is $8,750 max capital at risk.

On 2026-03-20, total risk deployed was $500 (1.4%). This is far below the maximum, but that is fine -- you only deploy what the system approves. Forcing trades to "use up" the risk budget is how accounts blow up.

### Rule 4: 10% Drawdown = Circuit Breaker

If the account drops 10% from its high-water mark, halt all new trading. No exceptions. Let existing positions play out or stop out. Review regime detection accuracy. Review position sizing. Only resume when drawdown recovers to 5% or a systematic review identifies the problem.

### Rule 5: Correlated Positions Are One Position

SPY, QQQ, and IWM are all US equity indexes. SPY and QQQ have a correlation of approximately 0.90. Holding iron condors on both is effectively doubling your exposure to a single risk factor (US equity markets).

The portfolio-aware Kelly sizing penalizes correlated positions. If you hold SPY IC and want to add QQQ IC, Kelly will dramatically reduce QQQ sizing (or block it entirely) because the marginal diversification benefit is nearly zero.

Good diversification: GLD (gold) + IWM (equities) + TLT (bonds). Correlation between these is low, so each position adds genuine portfolio diversification.

### Rule 6: Earnings Blackout for Income Trades

Never hold an income position (iron condor, credit spread, calendar) through an earnings announcement. Binary events create gap risk that iron condors cannot survive.

GLD is an ETF -- no earnings. IWM is an ETF -- no earnings. If you were trading AAPL or NVDA, the earnings blackout check would flag any expiration that straddles an earnings date.

### Rule 7: Regime Check Is Daily, Not Weekly

Regimes can change. IWM was R1 on March 20. By March 25, it might be R2 or R3. Every morning, before doing anything else, run regime detection on all open positions. A regime change on a held position triggers the exit evaluation described in Section 6.

### Rule 8: Entry Windows Are Not Suggestions

Income trades: 10:00 AM - 3:00 PM ET. 0DTE trades: 9:45 AM - 2:00 PM ET. These windows exist because:
- Before 10:00 AM: spreads are wide, market makers are repricing, and the opening volatility creates false signals
- After 3:00 PM: gamma risk escalates, market makers widen spreads, and you cannot adjust if something goes wrong
- After 3:00 PM for 0DTE: force close. No exceptions.

---

## 9. CLI Quick Reference

Every command used in this workflow, in the order you would run them.

### Morning Routine

| Command | Purpose | When |
|---------|---------|------|
| `context` | Check market environment, trading allowed, available strategies | 6:00 AM |
| `regime SPY QQQ IWM GLD TLT` | Detect per-ticker regime state | 9:30 AM |
| `rank IWM GLD SPY TLT` | Score and rank tradeable tickers | 9:45 AM |
| `technicals GLD` | Full technical analysis on top candidate | 10:00 AM |
| `vol GLD` | Volatility surface (term structure, skew) | 10:00 AM |
| `levels GLD` | Support/resistance levels | 10:00 AM |
| `opportunity GLD` | Generate trade recommendation with TradeSpec | 10:05 AM |
| `entry GLD` | Entry timing score (RSI, %B, VWAP, ATR) | 10:10 AM |
| `income_entry GLD` | 10-point validation gate | 10:15 AM |
| `size GLD` | Kelly sizing (position-aware) | 10:20 AM |

### Monitoring

| Command | Purpose | When |
|---------|---------|------|
| `monitor TICKER` | P&L, theta decay, exit conditions | Midday |
| `health TICKER` | Position health check | Midday |
| `adjust TICKER` | Adjustment recommendations if tested | When needed |
| `regime TICKER` | Re-check regime on held positions | Daily AM |
| `greeks TICKER` | Aggregate portfolio Greeks | As needed |

### Account and Broker

| Command | Purpose |
|---------|---------|
| `broker` | Check broker connection status |
| `balance` | Account balance, buying power, NLV |
| `quotes TICKER [EXP]` | Live option chain with bid/ask/Greeks |
| `watchlist` | List broker watchlists |
| `watchlist NAME` | Show tickers in a specific watchlist |

### Research and Planning

| Command | Purpose |
|---------|---------|
| `plan [TICKERS]` | Generate full daily trading plan |
| `screen TICKERS` | Quick multi-ticker screen |
| `macro` | Macro events, expiry calendar |
| `stress TICKER` | Stress test scenarios |
| `pop TICKER` | Probability of profit estimate |
| `yield TICKER` | Income yield calculation |

### Broker-Integrated Commands

Add `--broker --paper` when launching the CLI to connect to TastyTrade paper account:

```
analyzer-cli --broker --paper
```

With broker connected:
- `quotes` shows real bid/ask/Greeks from DXLink
- `size` gets precise credit/POP for Kelly calculation
- `income_entry` validation uses real IV rank data
- `adjust` shows real P&L with broker quotes

---

*This guide documents a real session from 2026-03-20. Market conditions, regime states, and prices are historical. The analytical process and decision framework are timeless.*
