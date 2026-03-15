# market_analyzer — Trader's Manual

**A systematic options & equity trading library for US and India markets.**

This manual follows a trader's day — what you do first in the morning, how you find and execute trades, how you monitor positions, and how you close the day. Every feature is shown in context of when a trader actually uses it.

---

## Table of Contents

1. [Your Trading Day](#1-your-trading-day)
2. [Pre-Market: Is Today Safe?](#2-pre-market-is-today-safe)
3. [Market Open: Find Opportunities](#3-market-open-find-opportunities)
4. [Trade Selection: Score and Filter](#4-trade-selection-score-and-filter)
5. [Pre-Entry: Validate the Trade](#5-pre-entry-validate-the-trade)
6. [At Entry: Size and Execute](#6-at-entry-size-and-execute)
7. [During Day: Monitor Positions](#7-during-day-monitor-positions)
8. [End of Day: Close or Hold](#8-end-of-day-close-or-hold)
9. [After Close: Review and Learn](#9-after-close-review-and-learn)
10. [Weekend: Plan and Calibrate](#10-weekend-plan-and-calibrate)
11. [Capability Reference](#11-capability-reference)
12. [Multi-Market: US + India](#12-multi-market-us--india)
13. [Appendix: Models & Data Structures](#13-appendix-models--data-structures)

---

## 1. Your Trading Day

```
6:00 AM   Pre-market checks (macro, black swan, cross-market)
9:15 AM   Market open (India) / wait for US
9:30 AM   Market open (US) — scan, rank, select trades
10:00 AM  Entry window opens — place orders
12:00 PM  Midday monitoring — health check open positions
2:00 PM   Entry window closes for most strategies
3:00 PM   0DTE force-close check (US: 3:00 PM ET, India: 3:00 PM IST)
3:30 PM   EOD escalation — tested positions get urgent
3:45 PM   Overnight risk assessment
4:00 PM   Market close (US) — journal, review, plan
```

MA provides a deterministic API for every step. No human judgment required during execution — the system decides, the trader (or platform) acts.

---

## 2. Pre-Market: Is Today Safe?

**First thing every morning: check if it's safe to trade at all.**

### Market Context Assessment

```python
ctx = ma.context.assess(debug=True)
# → MarketContext: environment_label, trading_allowed, position_size_factor
```

| Field | What it tells you |
|-------|------------------|
| `environment_label` | "risk-on", "cautious", "defensive", "crisis" |
| `trading_allowed` | False if black swan critical — DON'T TRADE |
| `position_size_factor` | 1.0 (normal), 0.75 (elevated), 0.50 (high), 0.0 (crisis) |

**CLI:** `context`

### Black Swan Alert

```python
alert = ma.black_swan.alert()
# → BlackSwanAlert: alert_level, composite_score, indicators
```

| Alert Level | Action |
|------------|--------|
| NORMAL | Trade normally |
| ELEVATED | Reduce position sizes by 25% |
| HIGH | Reduce by 50%, defined risk only |
| CRITICAL | NO TRADING — protect capital |

**CLI:** `stress`

### Macro Calendar

```python
macro = ma.macro.calendar()
# → MacroCalendar: events today, next 7 days
```

Key events that affect trading: FOMC, CPI, NFP, PCE, quad witching, monthly OpEx, VIX settlement.

**Day verdict logic:**
- FOMC day → AVOID (no new trades)
- CPI/NFP/PCE → TRADE_LIGHT (max 1 new position)
- OpEx day → TRADE_LIGHT
- Normal → TRADE

**CLI:** `macro`

### Macro Economic Indicators

```python
from market_analyzer import compute_macro_dashboard
dashboard = compute_macro_dashboard(tnx, tlt, hyg, uup, tip)
# → MacroIndicatorDashboard: bond market, credit spreads, dollar, inflation
```

| Indicator | What it tracks | Data source |
|-----------|---------------|-------------|
| **Bond market** | 10Y yield trend, basis point changes | TNX (^TNX), TLT |
| **Credit spreads** | HYG/TLT ratio — fear vs greed | HYG, TLT |
| **Dollar strength** | USD trend, India/US impact | UUP |
| **Inflation expectations** | TIP/TLT breakeven inflation proxy | TIP, TLT |

Overall risk: LOW → MODERATE → ELEVATED → HIGH

**CLI:** `macro_indicators`

### Cross-Market Analysis (US → India)

US closes at 4:00 PM ET = 1:30 AM IST. India opens at 9:15 AM IST. US closing behavior predicts India's opening.

```python
from market_analyzer import analyze_cross_market
cm = analyze_cross_market("SPY", "NIFTY", us_ohlcv, india_ohlcv,
                           us_regime_id, india_regime_id)
# → CrossMarketAnalysis: correlation, gap prediction, regime sync, signals
```

| Field | What it tells you |
|-------|------------------|
| `correlation_20d` | How much India moves with US (0-1) |
| `predicted_india_gap_pct` | Expected India opening gap based on US close |
| `prediction_confidence` | R-squared of the prediction model |
| `sync_status` | SYNCHRONIZED / DIVERGENT / LEADING / LAGGING |

**Signals generated:**
- US closes -2%+ → "crash_warning: India likely gap-down"
- US closes +2%+ → "rally_signal: India likely gap-up"
- Both R4 → "regime_sync_risk: correlated risk amplified"

**CLI:** `crossmarket` or `india_context`

---

## 3. Market Open: Find Opportunities

### Step 1: Regime Detection

Every analysis starts with regime. Regime determines which strategies are appropriate.

```python
regime = ma.regime.detect("SPY", debug=True)
# → RegimeResult: regime (R1-R4), confidence, trend_direction
```

| Regime | Name | What to trade | What to avoid |
|--------|------|--------------|---------------|
| R1 | Low-Vol Mean Reverting | Iron condors, strangles (theta) | Directional |
| R2 | High-Vol Mean Reverting | Wider wings, defined risk | Directional |
| R3 | Low-Vol Trending | Directional spreads | Heavy theta |
| R4 | High-Vol Trending | Risk-defined only, long vega | Theta selling |

**Model health indicators:**
- `regime.model_age_days` — if > 60, model may be stale (retrain)
- `regime.regime_stability` — if > 4 flips in 20 days, model is churning
- `regime.data_gaps` — warnings about confidence, staleness

**CLI:** `regime SPY GLD QQQ`

### Step 2: Technical Analysis

```python
tech = ma.technicals.snapshot("SPY", debug=True)
# → TechnicalSnapshot: 25+ indicators
```

**Core indicators:**

| Indicator | What it tells you | Trading use |
|-----------|------------------|-------------|
| RSI | Overbought (>70) / Oversold (<30) | MR entry, momentum confirmation |
| ATR / ATR% | Volatility level | Position sizing, stop distance |
| MACD | Momentum direction | Trend confirmation |
| Bollinger Bands | Price vs range | Squeeze = breakout setup |
| Stochastic | Short-term momentum | Entry timing |
| ADX | Trend strength (0-100) | >25 = trending, <20 = ranging |
| Fibonacci | Retracement levels (38.2%-78.6%) | Pullback targets, MR targets |
| Donchian | 20-day high/low channels | Breakout confirmation |
| Keltner | ATR-based bands + squeeze | Volatility compression |
| Pivot Points | PP, S1-S3, R1-R3 | Key S/R levels |
| VWAP | Volume-weighted average | Mean reversion anchor |
| VCP | Volatility Contraction Pattern | Breakout base forming |
| Smart Money | Order blocks, fair value gaps | Institutional S/R zones |

**CLI:** `technicals SPY`

### Step 3: Screening

Scan a universe of tickers for trading setups.

```python
result = ma.screening.scan(["SPY", "GLD", "QQQ", "TLT", "NIFTY"],
                            min_score=0.6, top_n=10)
# → ScreeningResult: candidates sorted by score, filtered by quality
```

**4 screens:**
- **Breakout:** VCP, Bollinger squeeze, near resistance
- **Momentum:** MACD crossover, RSI zone, MA alignment, ADX trend
- **Mean Reversion:** RSI extreme, Bollinger bands, stochastic
- **Income:** R1/R2 regime, neutral RSI, stable ATR

Liquidity filter (ATR < 0.3% auto-removed) and correlation dedup (same-regime, same-RSI-bucket deduplicated) applied automatically.

**CLI:** `screen SPY GLD QQQ --watchlist MA-Income`

### Step 4: Levels Analysis

Support/resistance from 21 sources (including pivot points), clustered by proximity, weighted by conviction.

```python
levels = ma.levels.analyze("SPY")
# → LevelsAnalysis: support/resistance levels, R:R ratios, stop/target
```

Sources: swing highs/lows, SMA 20/50/200, EMA 9/21, Bollinger bands, VWMA, VCP pivot, order blocks, fair value gaps, pivot points (PP/R1/R2/S1/S2).

**CLI:** `levels SPY`

---

## 4. Trade Selection: Score and Filter

### Ranking: Score All Opportunities

```python
ranking = ma.ranking.rank(
    tickers=["SPY", "GLD", "QQQ"],
    skip_intraday=True,
    debug=True,                      # Populates commentary
    iv_rank_map={"SPY": 45, "GLD": 32, "QQQ": 55},  # From broker
)
# → TradeRankingResult: top_trades sorted by composite_score
```

**Scoring formula:**
```
composite_score = verdict_score × confidence
                 + regime_alignment + phase_alignment
                 + income_bias_boost
                 - black_swan_penalty - macro_penalty - earnings_penalty
```

Each `RankedEntry` includes:
- `trade_spec` — complete legs, strikes, expiration (ready to trade)
- `composite_score` — 0-1 quality score
- `data_gaps` — what's missing in the analysis
- `commentary` — step-by-step reasoning (when debug=True)

**11 strategies assessed per ticker:**
Iron condor, iron butterfly, calendar, diagonal, ratio spread, credit spread, debit spread, zero DTE, LEAP, earnings, mean reversion, breakout, momentum

**CLI:** `rank SPY GLD QQQ --debug --account 50000`

### Account Filtering

```python
from market_analyzer import filter_trades_by_account
filtered = filter_trades_by_account(
    ranked_entries=ranking.top_trades,
    available_buying_power=24000,
    allowed_structures=["iron_condor", "credit_spread", "calendar"],
    max_risk_per_trade=1500,
)
# → FilteredTrades: affordable + filtered_out with reasons
```

**CLI:** Part of `rank --account 30000`

### Daily Trading Plan

```python
plan = ma.plan.generate(tickers=["SPY", "GLD", "QQQ"], skip_intraday=True)
# → DailyTradingPlan: day_verdict, trades_by_horizon, risk_budget
```

Trades bucketed by horizon: 0DTE, weekly, monthly, LEAP. Each with entry window, exit rules, and data warnings.

**CLI:** `plan SPY GLD QQQ`

---

## 5. Pre-Entry: Validate the Trade

### Trade Quality Assessment (POP + EV + R:R)

```python
from market_analyzer import estimate_pop
pop = estimate_pop(spec, entry_price=0.80, regime_id=1,
                   atr_pct=1.2, current_price=580.0, iv_rank=45)
# → POPEstimate: pop_pct, expected_value, max_profit, max_loss,
#                risk_reward_ratio, trade_quality, trade_quality_score
```

**What you see:**
```
POP: 65%  |  EV: +$12  |  R:R 5.2:1  |  Quality: good (0.58)
```

**Trade quality scoring (combined POP + EV + R:R):**

| Quality | Score | Meaning |
|---------|-------|---------|
| Excellent | ≥ 0.70 | High POP, positive EV, favorable R:R |
| Good | ≥ 0.50 | Acceptable on all three metrics |
| Marginal | ≥ 0.30 | One metric is weak |
| Poor | < 0.30 | Negative EV or terrible R:R — skip |

**CLI:** `pop SPY 0.80 iron_condor`

### Income Entry Check

```python
from market_analyzer import check_income_entry
entry = check_income_entry(
    iv_rank=45, iv_percentile=50, dte=35, rsi=50, atr_pct=1.2,
    regime_id=1, has_earnings_within_dte=False, has_macro_event_today=False,
)
# → IncomeEntryCheck: confirmed (bool), score, conditions
```

Checks: IV rank sufficient, DTE in sweet spot, RSI neutral, ATR stable, no earnings/macro risk.

**CLI:** `income_entry SPY`

### Execution Quality Gate

```python
from market_analyzer import validate_execution_quality
quality = validate_execution_quality(spec, quotes,
                                      max_spread_pct=15, min_open_interest=50)
# → ExecutionQuality: overall_verdict (GO/WIDE_SPREAD/ILLIQUID/NO_QUOTE)
```

**Don't enter if:** spread too wide, open interest too low, no quotes available.

**CLI:** `quality SPY iron_condor`

### Entry Window

Every TradeSpec carries `entry_window_start` and `entry_window_end`:
- **0DTE:** 09:45-14:00 (US) / 09:30-13:30 (India)
- **Income (IC, IFly, calendar):** 10:00-15:00 (US) / 09:30-14:30 (India)
- **Earnings:** 10:00-14:30 (US) / 09:30-14:00 (India)

Only submit orders within the window. Outside the window = unfavorable fills.

---

## 6. At Entry: Size and Execute

### Position Sizing

```python
contracts = spec.position_size(capital=50000, risk_pct=0.02)
# → int: number of contracts for your account
```

Uses `lot_size` from the instrument (100 for US, 25 for NIFTY, 250 for RELIANCE).

**CLI:** `size SPY 50000`

### Income Yield

```python
from market_analyzer import compute_income_yield
yield_info = compute_income_yield(spec, entry_credit=0.80)
# → IncomeYield: credit_to_width_pct, return_on_capital_pct, annualized_roc_pct
```

**What you see:**
```
Credit/Width: 16%  |  ROC: 19%  |  Annualized: 198%  |  Max P: $80  |  Max L: $420
```

**CLI:** `yield SPY 0.80 5 35`

### Greeks Aggregation

```python
from market_analyzer import aggregate_greeks
greeks = aggregate_greeks(spec, leg_quotes, contracts=2)
# → AggregatedGreeks: net_delta, net_gamma, net_theta, net_vega, daily_theta_dollars
```

**CLI:** `greeks SPY`

### Breakevens

```python
from market_analyzer import compute_breakevens
be = compute_breakevens(spec, entry_price=0.80)
# → Breakevens: low, high
```

**CLI:** Part of `yield`

---

## 7. During Day: Monitor Positions

### Exit Condition Monitoring

```python
from market_analyzer import monitor_exit_conditions
from datetime import time
result = monitor_exit_conditions(
    trade_id="SPY-IC-001", ticker="SPY",
    structure_type="iron_condor", order_side="credit",
    entry_price=0.80, current_mid_price=0.40,
    contracts=1, dte_remaining=25, regime_id=1,
    profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
    entry_regime_id=1,
    time_of_day=time(15, 30),  # Triggers EOD urgency
    lot_size=100,
)
# → ExitMonitorResult: should_close, signals, pnl_pct, summary
```

**4 exit rules checked:**
1. **Profit target** — close at 50% of max profit (credit decayed 50%)
2. **Stop loss** — close if loss > 2× credit received
3. **DTE exit** — close when ≤21 DTE (gamma risk)
4. **Regime change** — close if regime shifted from MR to trending

**Time-of-day escalation:**
- 0DTE after 15:00 → force close (immediate)
- Tested position after 15:30 → escalate to immediate

**CLI:** `monitor SPY 0.80 0.40 25`

### Full Health Check

```python
from market_analyzer import check_trade_health
health = check_trade_health(
    trade_id="SPY-IC-001", trade_spec=spec,
    entry_price=0.80, contracts=1, current_mid_price=0.55,
    dte_remaining=30, regime=regime, technicals=tech,
    time_of_day=time(15, 30),
)
# → TradeHealthCheck: status, overall_action, overnight_risk
```

| Status | Action |
|--------|--------|
| `healthy` | Hold — theta working |
| `tested` | Monitor closely, consider adjustment |
| `breached` | Adjust or close |
| `exit_triggered` | Close immediately |

**Includes overnight risk** (auto-checked after 15:00):
- 0DTE → CLOSE_BEFORE_CLOSE (expires today)
- R4 + tested → CLOSE_BEFORE_CLOSE
- Earnings tomorrow → HIGH risk
- Safe + R1 → LOW

**CLI:** `health SPY 0.80 0.55 30`

### Deterministic Adjustment

```python
decision = ma.adjustment.recommend_action(spec, regime, technicals)
# → AdjustmentDecision: single action, no menu
```

**Decision tree (no human judgment):**

| Condition | Action |
|-----------|--------|
| SAFE + any regime | DO_NOTHING |
| TESTED + R1/R2 | DO_NOTHING (swings revert) |
| TESTED + R3 | ROLL_AWAY |
| TESTED + R4 | CLOSE_FULL |
| BREACHED + R1/R2 | ROLL_AWAY |
| BREACHED + R3/R4 | CLOSE_FULL |
| MAX_LOSS | CLOSE_FULL (always) |

**CLI:** `adjust SPY`

### Hedging Assessment

```python
from market_analyzer import assess_hedge
hedge = assess_hedge("SPY", "long_equity", 50000, regime, technicals)
# → HedgeRecommendation: hedge_type, urgency, rationale, protection_level
```

**Same-ticker hedging only** (per trading philosophy):

| Position | R1 | R2 | R3 | R4 |
|----------|-----|-----|-----|-----|
| Long equity | No hedge | Collar | Protective put (if bearish) | Protective put (immediate) |
| Short straddle | No hedge | Add wing (define risk) | Delta hedge | CLOSE |
| Iron condor | No hedge | No hedge | Delta hedge (if tested) | CLOSE |

**CLI:** `hedge SPY long_equity`

---

## 8. End of Day: Close or Hold

### Overnight Risk Assessment

```python
from market_analyzer import assess_overnight_risk
risk = assess_overnight_risk(
    trade_id="SPY-IC-001", ticker="SPY",
    structure_type="iron_condor", order_side="credit",
    dte_remaining=14, regime_id=4, position_status="tested",
)
# → OvernightRisk: risk_level, reasons, summary
```

| Risk Level | Action |
|-----------|--------|
| LOW | Hold overnight (safe) |
| MEDIUM | Hold with caution |
| HIGH | Consider closing |
| CLOSE_BEFORE_CLOSE | Close before market close |

**CLI:** `overnight SPY --dte 14 --status tested`

### Currency P&L (Multi-Market)

For traders in both US and India:

```python
from market_analyzer import compute_currency_pnl
pnl = compute_currency_pnl(
    ticker="NIFTY", trading_pnl_local=5000,  # ₹5,000 from trade
    position_value_local=500000,
    local_currency="INR", base_currency="USD",
    fx_rate_at_entry=83.0, fx_rate_current=84.5,
)
# → CurrencyPnL: trading_pnl_base, currency_pnl_base, total_pnl_base
```

**What you see:**
```
NIFTY: trade $59 + FX -$53 = $6 total (FX +1.8% against you)
```

The trade made ₹5,000 but INR weakened 1.8% — most of the gain was eaten by currency.

**CLI:** `currency 100000 INR USD --entry-rate 83.0`

---

## 9. After Close: Review and Learn

### Performance Tracking

```python
from market_analyzer import compute_performance_report, compute_sharpe, compute_drawdown
report = compute_performance_report(outcomes)  # list[TradeOutcome]
sharpe = compute_sharpe(outcomes)
drawdown = compute_drawdown(outcomes)
regime_perf = compute_regime_performance(outcomes)
```

| Metric | What it tells you |
|--------|------------------|
| Win rate by regime | Are R1 iron condors really working? |
| Sharpe ratio | Risk-adjusted returns |
| Sortino ratio | Downside-only risk-adjusted returns |
| Max drawdown | Worst peak-to-trough decline |
| Profit factor | Gross wins / gross losses |
| POP accuracy | Are 70% POP trades winning 70%? |

**CLI:** `performance`, `sharpe`, `drawdown`

### Drift Detection

```python
from market_analyzer import detect_drift
alerts = detect_drift(outcomes, window=20)
# → list[DriftAlert]: strategy cells where win rate dropped
```

| Severity | Meaning | Action |
|----------|---------|--------|
| WARNING | >15 percentage point drop from baseline | Reduce allocation by 50% |
| CRITICAL | >25 percentage point drop | Suspend this (regime, strategy) cell |

**CLI:** `drift`

---

## 10. Weekend: Plan and Calibrate

### Weight Calibration

```python
from market_analyzer import calibrate_weights
calibration = calibrate_weights(outcomes)
# → CalibrationResult: suggested weight adjustments per (regime, strategy) cell
```

Compares actual win rates against the static regime-strategy alignment matrix. If iron condors in R1 are winning 85% (matrix says 1.0), the weight is confirmed. If they're winning only 40%, the weight should decrease.

### POP Factor Calibration

```python
from market_analyzer import calibrate_pop_factors
factors = calibrate_pop_factors(outcomes, min_trades_per_regime=10)
# → {1: 0.38, 2: 0.65, 3: 1.05, 4: 1.42}  # Calibrated from real data
```

Default factors: {R1: 0.40, R2: 0.70, R3: 1.10, R4: 1.50}. Calibrated factors replace these based on actual price behavior in each regime.

### Thompson Sampling Strategy Selection

```python
from market_analyzer import build_bandits, select_strategies, update_bandit
bandits = build_bandits(outcomes)  # Initial build from history
selected = select_strategies(bandits, regime_id=1, available_strategies, n=5)
# → [(StrategyType.IRON_CONDOR, 0.83), (StrategyType.CALENDAR, 0.71), ...]
```

Replaces static strategy list with adaptive selection. Proven winners get selected more often. Underexplored strategies get tried occasionally (exploration).

**CLI:** `bandit`

### Threshold Optimization

```python
from market_analyzer import optimize_thresholds, ThresholdConfig
optimized = optimize_thresholds(outcomes, current=ThresholdConfig())
# → ThresholdConfig with learned cutoffs
```

Optimizes: IC IV rank minimum (default 15), POP minimum (default 50%), score minimum (default 0.60), ADX thresholds, credit/width minimum.

---

## 11. Capability Reference

### By Category

**Market Analysis (8 services):**
`context`, `regime`, `technicals`, `levels`, `phase`, `fundamentals`, `macro`, `vol_surface`

**Opportunity Assessment (12 assessors):**
`iron_condor`, `iron_butterfly`, `calendar`, `diagonal`, `ratio_spread`, `zero_dte`, `leap`, `earnings`, `breakout`, `momentum`, `mean_reversion`, `orb`

**Trade Planning (4 services):**
`screening`, `ranking`, `plan`, `strategy`

**Trade Lifecycle (10 functions):**
`estimate_pop`, `compute_income_yield`, `compute_breakevens`, `check_income_entry`, `filter_trades_by_account`, `aggregate_greeks`, `monitor_exit_conditions`, `check_trade_health`, `assess_overnight_risk`, `recommend_adjustment_action`

**Risk & Hedging (4 functions):**
`assess_hedge`, `validate_execution_quality`, `assess_currency_exposure`, `compute_portfolio_exposure`

**Performance & Learning (12 functions):**
`compute_performance_report`, `compute_sharpe`, `compute_drawdown`, `compute_regime_performance`, `calibrate_weights`, `calibrate_pop_factors`, `optimize_thresholds`, `detect_drift`, `build_bandits`, `update_bandit`, `select_strategies`

**Cross-Market (3 functions):**
`analyze_cross_market`, `compute_cross_market_correlation`, `predict_gap`

**Macro Indicators (5 functions):**
`compute_macro_dashboard`, `compute_bond_market`, `compute_credit_spreads`, `compute_dollar_strength`, `compute_inflation_expectations`

**Currency (4 functions):**
`convert_amount`, `compute_portfolio_exposure`, `compute_currency_pnl`, `assess_currency_exposure`

**Market Registry (6 methods):**
`get_market`, `get_instrument`, `list_instruments`, `strategy_available`, `to_yfinance`, `estimate_margin`

### CLI Commands (48 total)

| Category | Commands |
|----------|----------|
| Context | `context`, `stress`, `macro`, `macro_indicators` |
| Analysis | `regime`, `technicals`, `levels`, `analyze`, `vol` |
| Screening | `screen`, `rank`, `plan`, `universe`, `watchlist` |
| Opportunity | `opportunity`, `setup`, `entry`, `strategy`, `exit_plan` |
| Trade Analytics | `yield`, `pop`, `income_entry`, `greeks`, `size`, `parse` |
| Monitoring | `monitor`, `health`, `adjust`, `overnight`, `quality` |
| Risk & Hedging | `hedge`, `currency`, `exposure` |
| Cross-Market | `crossmarket`, `india_context` |
| Performance | `performance`, `sharpe`, `drawdown`, `drift`, `bandit` |
| Registry | `registry`, `margin` |
| Broker | `broker`, `balance`, `quotes` |

---

## 12. Multi-Market: US + India

### Key Differences

| Aspect | US | India |
|--------|-----|-------|
| Currency | USD | INR |
| Lot size | 100 (all) | Varies: NIFTY=25, BANKNIFTY=15, stocks=250-1600 |
| Expiry day | Friday | Thu (NIFTY), Wed (BANKNIFTY), Tue (FINNIFTY) |
| Settlement | Physical (equity), Cash (index) | Cash (index), Physical (stocks) |
| Exercise | American (equity), European (index) | European (all) |
| Assignment risk | YES (American exercise) | NO for indices (European + cash) |
| LEAPs | Yes (1-3 years) | No (max ~90 days) |
| Market hours | 9:30-16:00 ET | 9:15-15:30 IST |
| VIX | ^VIX | ^INDIAVIX |

### India: Options vs Cash Equity

**For India index options (NIFTY, BANKNIFTY):** Full options strategies work — iron condors, straddles, credit spreads. Weekly expiry, good liquidity.

**For India stock options:** Limited depth, wide spreads, monthly-only expiry. MA automatically recommends **cash equity trades** instead of options for India stocks.

```
RELIANCE breakout → EQ↑ bullish · defined
  Action: BUY 1 lot (250 shares) at ₹1,380
  Stop: ₹1,326 (1.5 ATR)
  Target: ₹1,454 (2.0 ATR, R:R 1.33)
```

The system decides: NIFTY → options, RELIANCE → cash equity. No human judgment needed.

### India-Specific Configuration

- Entry windows: 09:30-13:30 IST (0DTE), 09:30-14:30 IST (income)
- LEAP assessor returns NO_GO for all India tickers
- Calendar/diagonal assessors enforce max 90-day DTE
- Exit notes: "no assignment risk" for cash-settled European options
- Macro: India VIX (^INDIAVIX), RBI MPC dates

### Registry Lookup

```python
registry = ma.registry
inst = registry.get_instrument("NIFTY")
# lot_size=25, strike_interval=50, settlement="cash",
# exercise_style="european", has_0dte=True, has_leaps=False

registry.strategy_available("leaps", "NIFTY")   # False
registry.strategy_available("iron_condor", "NIFTY")  # True
registry.to_yfinance("RELIANCE")  # "RELIANCE.NS"
registry.estimate_margin("iron_condor", "NIFTY", wing_width=200)
# → INR 5,000 (200 × 25 × 1)
```

**CLI:** `registry NIFTY`, `margin NIFTY ic --width 200`

---

## 13. Appendix: Models & Data Structures

### TradeSpec — The Universal Trade Contract

Every trade recommendation produces a `TradeSpec`:

```python
spec.ticker              # "SPY"
spec.structure_type      # "iron_condor"
spec.order_side          # "credit"
spec.legs                # [LegSpec(STO P570, BTO P565, STO C590, BTO C595)]
spec.max_entry_price     # 0.80 (don't pay more)
spec.profit_target_pct   # 0.50 (close at 50% max profit)
spec.stop_loss_pct       # 2.0 (close if loss = 2× credit)
spec.exit_dte            # 21 (close when ≤21 DTE)
spec.entry_window_start  # time(10, 0)
spec.entry_window_end    # time(15, 0)
spec.lot_size            # 100 (US) or 25 (NIFTY)
spec.currency            # "USD" or "INR"
spec.settlement          # "cash" or "physical"
spec.exercise_style      # "european" or "american"

# Computed properties
spec.strategy_badge      # "IC neutral · defined"
spec.exit_summary        # "TP 50% | SL 2× credit | close ≤21 DTE"
spec.order_data          # Machine-readable for broker order submission
spec.position_size(50000)# Number of contracts for $50K account
```

### RegimeResult

```python
regime.regime              # RegimeID.R1_LOW_VOL_MR
regime.confidence          # 0.82
regime.trend_direction     # "bullish" / "bearish" / None
regime.model_fit_date      # date(2026, 3, 13)
regime.model_age_days      # 1
regime.regime_stability    # 2 (flips in 20 days)
regime.commentary          # ["HMM fitted on...", "R1 selected..."] (debug=True)
regime.data_gaps           # [DataGap("regime", "model stale", "high")]
```

### POPEstimate

```python
pop.pop_pct                # 0.65
pop.expected_value         # 12.50
pop.max_profit             # 80.00
pop.max_loss               # 420.00
pop.risk_reward_ratio      # 5.25
pop.trade_quality          # "good"
pop.trade_quality_score    # 0.58
```

### DataGap — Transparency About Missing Data

Every analysis result can carry `data_gaps`:

```python
DataGap(
    field="iv_rank",
    reason="broker not connected",
    impact="medium",
    affects="premium assessment — POP may be 10-15% off",
)
```

The system never hides what it doesn't know. If broker is down, IV rank is missing, or the model is stale — it tells you. Trust is built on transparency.

---

*market_analyzer — making money, not theory.*
*1331 tests. 48 CLI commands. Zero open gaps.*
