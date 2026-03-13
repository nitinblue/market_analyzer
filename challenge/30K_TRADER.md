# $30K Options Trader — market_analyzer Demo

**Goal:** Capital preservation + income generation with a $30K account.
**Constraint:** Small account = margin matters. Every dollar of buying power is precious.
**Philosophy:** Income-first (theta harvesting). Directional only when regime allows.

This document walks through a realistic trading day using market_analyzer, from opening the terminal to placing trades. It demonstrates the package's **money-making capability** — and honestly documents where gaps exist.

---

## Step 0: Account Reality Check

$30K opens up more room but discipline still matters:
- Defined-risk preferred (iron condors, verticals, calendars)
- Max 5 positions open at once
- Each trade risks ~$300-600 max (1-2% of account)
- $500-1500 buying power per iron condor ($5-wide)

**What market_analyzer provides:** `StrategyService.size()` with `account_size=30_000` gives contract counts and max risk. Config: `strategy.default_account_size: 30000`.

**What the challenge portfolio tracker provides:** `challenge.Portfolio` tracks booked trades, enforces risk limits (max positions, per-ticker, sector concentration, BP reserve), and computes portfolio heat/P&L. All inputs come via API — eTrading calls `book_trade()`, `close_trade()`, `check_risk()`.

**~~GAP-F1~~ RESOLVED:** Portfolio tracking now lives in `challenge.Portfolio`. Tracks open positions, buying power used, concentration by ticker and sector. eTrading calls `port.check_risk(trade_spec)` before booking and `port.book_trade(trade_spec, entry_price, contracts)` to record.

---

## Step 1: Is Today Safe to Trade?

```
analyzer-cli --broker
> context
```

The `context` command answers: "Should I trade at all today?"

**What it checks:**
- Black swan alert (VIX spike, credit spreads blowing out, TLT crashing)
- Macro calendar (FOMC today? CPI? NFP?)
- Expiry events (quad witching? monthly OpEx? VIX settlement?)
- Intermarket regime dashboard (are reference tickers aligned or divergent?)

**Decision tree:**
- NO_TRADE (black swan critical) → Close the terminal. Protect capital.
- AVOID (FOMC day, quad witching) → No new trades. Monitor existing.
- TRADE_LIGHT (CPI/NFP/OpEx day) → Max 1 new position, small size.
- TRADE → Normal operations.

**For a $30K account:** Even on TRADE days, we cap at 2-3 new positions. On TRADE_LIGHT, only 1.

**~~GAP-F2~~ RESOLVED:** `port.get_status()` returns `portfolio_heat` ("cool"/"warm"/"hot") and `heat_pct`. Risk checks enforce BP reserve (20% default). eTrading checks heat before opening new trades.

**~~GAP-F3~~ RESOLVED:** `AccountProvider.get_balance()` now provides real broker NLV and buying power. `TradingPlanService` uses broker balance when connected. Portfolio tracker accepts `update_config(account_size=...)` from broker data.

---

## Step 2: Find Opportunities

```
> screen SPX QQQ GLD TLT IWM AAPL MSFT
```

Screening runs 4 screens (breakout, momentum, mean_reversion, income) across tickers. With $30K and income-first philosophy, we focus on the `income` screen results.

**What "income" screen looks for:**
- R1 or R2 regime (mean-reverting = safe for theta)
- RSI near 50 (not trending)
- Reasonable ATR (not too volatile, not dead)

```
> rank SPX QQQ GLD TLT IWM
```

Ranking evaluates every ticker × every strategy (11 strategies × 5 tickers = 55 assessments). Outputs ranked trades with composite scores.

**For $30K income account, we care about:**
1. Iron condors (R1/R2, defined risk, margin-efficient)
2. Credit spreads (smaller, single-side, less capital)
3. Calendars (if vol surface supports it)

**We ignore:**
- LEAPs (too much capital tied up for $30K)
- Ratio spreads (naked leg, margin)
- Breakout/momentum (directional, not income)

**GAP-F4: No account-size-aware ranking filter.** Ranking scores strategies by regime alignment and signal quality, but doesn't know that a $30K account can't do ratio spreads or $20-wide iron condors. The `income_bias_boost` helps but doesn't eliminate impossible trades. **Need: Account-size filter that removes strategies requiring more buying power than available.**

**GAP-F5: No "income yield" metric on ranked trades.** For income trading, the key metric is: "How much credit do I collect per dollar of buying power?" A $0.80 credit on a $5-wide IC = 16% potential return. A $0.30 credit = 6%. The ranking doesn't show this — it scores by regime alignment, not by capital efficiency. **Need: Credit-to-width ratio and annualized yield in RankedEntry when trade_spec is present.**

---

## Step 3: Deep-Dive the Top Pick

Say ranking suggests: `#1 GLD IRON_CONDOR GO 0.78`

```
> analyze GLD
> opportunity GLD ic
> vol GLD
```

**What we learn:**
- `analyze GLD`: R1 (low-vol mean reverting), Phase 1 (accumulation), RSI 48 (neutral), ATR 0.8% (calm)
- `opportunity GLD ic`: STANDARD_IRON_CONDOR, GO, confidence 0.82. Short strikes ~1.0% OTM, wings +0.5% beyond.
- `vol GLD`: Front IV 18%, back IV 16%, contango (normal). Put skew slight. Calendar edge low.

**This tells us:** GLD is range-bound, IV is modest but tradeable. Standard IC is the play.

```
> levels GLD
```

Levels gives us support/resistance for strike selection:
- Support at $218, $215
- Resistance at $224, $228
- Current price: $221

**GAP-F6: No strike selection from levels.** The `opportunity` assessor picks strikes based on ATR distance (e.g., "1.0 ATR OTM"). But it doesn't check if those strikes align with actual support/resistance from `levels`. An IC with short put at $218 (support) is better than $217 (random). **Need: Levels-informed strike selection in TradeSpec — snap short strikes to nearest support/resistance rather than pure ATR distance.**

**GAP-F7: No probability of profit (POP) calculation.** For income trading, POP is the north star metric. A 70% POP iron condor on GLD is very different from a 55% POP one. We have regime + IV + ATR but don't compute a POP estimate. **Need: POP estimation from regime-adjusted probability distributions (not BS — from historical regime-specific return distributions).**

---

## Step 4: Check the Trade Spec

```
> opportunity GLD ic
```

The assessor returns a `TradeSpec` with concrete legs:

```
STO 1x GLD P218 4/17/26    (short put at support)
BTO 1x GLD P213 4/17/26    (long put wing)
STO 1x GLD C225 4/17/26    (short call at resistance)
BTO 1x GLD C230 4/17/26    (long call wing)
```

**Width:** $5 on each side. **Max risk:** $500 - credit. **Buying power:** ~$500.

For $30K, this uses 5% of capital per contract. We can do 1-2 contracts.

**What we need from broker (--broker flag):**
- Bid/ask on each leg → net credit
- Greeks (delta of short strikes)

```
> quotes GLD 2026-04-17
```

Shows live bid/ask. Say net credit = $0.72 per spread.
- Max profit: $72 per contract
- Max loss: $428 per contract
- Risk/reward: 1:6 (typical for IC)
- Breakevens: $217.28 and $225.72

**GAP-F8: No breakeven calculation on TradeSpec.** We have max_profit_desc and max_loss_desc but no breakeven prices. For strike placement validation, breakevens tell you exactly where you lose money. **Need: `trade_spec.breakeven_low` and `trade_spec.breakeven_high` computed from strikes and credit.**

**GAP-F9: No Greeks aggregation on TradeSpec.** When broker is connected and we have Greeks per leg, we should show portfolio Greeks for the entire structure: net delta, net theta (daily income!), net vega. For income trading, theta is literally your daily paycheck. **Need: `trade_spec.net_delta`, `trade_spec.net_theta`, `trade_spec.net_vega` from broker quotes.**

---

## Step 5: Validate Entry Timing

```
> entry GLD mean_reversion
```

Entry confirmation checks:
- RSI not extreme (confirmed)
- Bollinger not squeezed (confirmed)
- No MACD divergence (confirmed)
- Volume normal (confirmed)

For income trades (selling premium), "boring is good." We WANT confirmation that nothing exciting is happening.

**GAP-F10: No income-specific entry confirmation.** The entry service is designed for directional triggers (BREAKOUT_CONFIRMED, PULLBACK_TO_SUPPORT). For income trades, the confirmation is different: "Is IV high enough to sell? Is the range stable? Is theta decay accelerating (approaching 45 DTE sweet spot)?". **Need: `EntryTriggerType.INCOME_OPTIMAL` — checks IV percentile, DTE sweet spot, range stability, no upcoming events.**

---

## Step 6: Size the Position

```
> strategy GLD
```

Strategy service gives:
- Primary: iron condor, neutral, defined risk
- DTE range: 30-45
- Delta range: 0.15-0.30
- Wing width: 5-wide

```python
# Programmatic:
size = ma.strategy.size(params, current_price=221.0, account_size=10_000)
# suggested_contracts: 1
# max_contracts: 2
# max_risk_dollars: $428
```

For $30K: 1 contract uses $428 risk (4.3% of account). 2 contracts = 8.6%. Conservative = 1.

**GAP-F11: No "how many of these can I open" answer.** Strategy sizes one trade in isolation. If I already have 1 SPY IC using $500 and 1 QQQ IC using $500, I have $9K left. But strategy still says "max 2 contracts" based on full $30K. **Need: Available buying power as input to sizing, not just account size.**

---

## Step 7: Set Exit Plan

```
> exit_plan GLD 0.72
```

Exit plan:
- **Profit target:** Close at 50% profit ($0.36 credit → buy back at $0.36). This is ~$36 per contract.
- **Stop loss:** Close at 2x credit ($1.44 debit). Max loss ~$72 per contract (better than full $428).
- **Time exit:** Close at 7 DTE regardless (gamma risk increases).
- **Regime change:** If GLD moves to R3/R4, review immediately.

**This is actually well-built.** The exit service gives actionable rules. For income trading on $30K, the 50% profit target is ideal — it captures the easy money and avoids the last 50% where gamma risk spikes.

**GAP-F12: No automated exit monitoring.** The exit plan is a set of rules, but there's no service that says "right now, your GLD IC is at 40% profit, approaching target." The `IntradayService.monitor()` exists but is 0DTE-focused. **Need: Multi-day position monitoring that checks exit conditions against current prices/Greeks and generates alerts.**

---

## Step 8: Manage the Trade (Day 2+)

After entry, the trade needs monitoring:
- Is GLD still in R1? Run `regime GLD` daily.
- Is the position being tested? Run `adjust GLD` if price approaches short strike.
- Is profit target hit? Check broker P&L.

```
> adjust GLD
```

Adjustment service analyzes:
- Position status: SAFE (price > 1 ATR from short strikes)
- Recommended: DO_NOTHING (good)
- If TESTED: roll away, narrow untested side, or close

**~~GAP-F13~~ RESOLVED:** `challenge.Portfolio` tracks entry price, exit price, realized P&L, win/loss stats, and portfolio-level returns. `TradeRecord.max_profit`, `max_loss`, `risk_reward_ratio` computed automatically. eTrading calls `close_trade()` with fill data for P&L tracking.

---

## The Complete Flow (Summary)

```
1. context          → Is today safe?               [WORKS]
2. screen/rank      → Where are opportunities?     [WORKS, but no account-size filter]
3. analyze/vol      → Deep-dive the ticker         [WORKS]
4. opportunity      → Get trade structure + legs    [WORKS, but no POP/breakeven]
5. quotes           → Get live pricing              [WORKS with --broker]
6. strategy/size    → How many contracts?           [WORKS, but isolated from portfolio]
7. exit_plan        → Set rules                     [WORKS well]
8. adjust           → Manage day 2+                 [WORKS, but no daily monitoring]
```

---

## Feature Gaps Summary (Prioritized for $30K Income Trader)

### Must-Have for Money-Making

| ID | Gap | Status | Where |
|----|-----|--------|-------|
| F1 | Portfolio-level position tracking | **DONE** | `challenge.Portfolio` |
| F2 | Portfolio heat calculation | **DONE** | `port.get_status().portfolio_heat` |
| F3 | Broker account balance integration | **DONE** | `AccountProvider` + `TradingPlanService` |
| F5 | Income yield metric (credit/width, annualized) | **DONE** | `trade_lifecycle.compute_income_yield()` |
| F8 | Breakeven calculation | **DONE** | `trade_lifecycle.compute_breakevens()` |
| F9 | Greeks aggregation on trade | **DONE** | `trade_lifecycle.aggregate_greeks()` |
| F11 | Sizing ignores existing positions | **DONE** | `port.check_risk()` enforces limits |
| F13 | Daily P&L tracking | **DONE** | `challenge.Portfolio` tracks all P&L |

### Should-Have for Edge

| ID | Gap | Impact | Where |
|----|-----|--------|-------|
| F4 | Account-size trade filtering | **DONE** | `trade_lifecycle.filter_trades_by_account()` |
| F6 | Strikes aligned to S/R levels | **DONE** | `trade_lifecycle.align_strikes_to_levels()` |
| F7 | Probability of profit estimate | **DONE** | `trade_lifecycle.estimate_pop()` |
| F10 | Income-specific entry check | **DONE** | `trade_lifecycle.check_income_entry()` |
| F12 | Multi-day exit monitoring | **DONE** | `trade_lifecycle.monitor_exit_conditions()` + `check_trade_health()` |

### eTrading Responsibility (Now via challenge.Portfolio)

| ID | Gap | Status |
|----|-----|--------|
| F1 | Portfolio position tracking | **DONE** — `challenge.Portfolio` |
| F2 | Portfolio heat calculation | **DONE** — `port.get_status()` |
| F13 | Daily P&L tracking | **DONE** — `port.close_trade()` computes P&L |

---

## Honest Assessment

**What works well:**
- The regime → strategy pipeline is sound. R1 = sell premium, R4 = hide. This alone prevents the #1 retail trader mistake (selling iron condors in a crash).
- Trade specs with concrete legs, expirations, and exit rules are genuinely actionable.
- The 11-strategy assessor suite covers the real playbook for small accounts.
- Data transparency (showing source, warning when broker is down) builds trust.
- The adjustment analyzer gives real-time position management guidance.

**What's now complete:**
- Portfolio management via `challenge.Portfolio` — position tracking, risk checks, P&L, heat monitoring.
- POP and expected value via `estimate_pop()` — regime-adjusted, not Black-Scholes.
- Income yield and capital efficiency via `compute_income_yield()` — credit/width, ROC, annualized.
- Exit monitoring via `monitor_exit_conditions()` — profit target, stop loss, DTE exit, regime change.
- Trade health via `check_trade_health()` — combined exit + adjustment in one call.
- Account filtering via `filter_trades_by_account()` — removes trades exceeding account limits.
- `TradeSpec.strategy_symbol` and `strategy_badge` — compact trade identification (e.g., "IC neutral · defined").

**The system says NO when conditions aren't right.** This is by design. On 2026-03-12 with QQQ in R4 and elevated black swan, the trader correctly proposed zero trades — discipline over activity.

**Bottom line:** market_analyzer is a complete *decision support system* covering the full trade lifecycle from screening to exit monitoring. With eTrading providing execution and `challenge.Portfolio` tracking positions, this is a legitimate edge for a $30K options account.
