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
11. [Equity Research: Stock Selection for Core Holdings](#11-equity-research)
11b. [Capital Deployment: Systematic Long-Term Investing](#11b-capital-deployment)
11c. [Futures Trading Guide](#11c-futures-trading-guide)
12. [Capability Reference](#12-capability-reference)
13. [Multi-Market: US + India](#13-multi-market-us--india)
14. [Appendix: Models & Data Structures](#14-appendix-models--data-structures)
15. [Quant's Cookbook: Creative API Combinations](#15-quants-cookbook--creative-api-combinations)

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
| `tradeable` | What instruments are available today (options/stocks/futures + strategies) |

### Tradeable Instruments — What Can You Trade Today?

Every `context.assess()` now publishes exactly which instruments and strategies are viable:

```python
ctx = ma.context.assess()
t = ctx.tradeable

# Options
t.options_available     # True/False
t.options_note          # "R2 high-vol MR — rich premiums. Wider strikes, defined risk."
t.options_strategies    # ["iron_condor", "iron_butterfly", "credit_spread", ...]

# Stocks
t.stocks_available      # True/False
t.stocks_strategies     # ["value", "growth", "dividend", ...]

# Futures
t.futures_available     # True/False
t.futures_strategies    # ["futures options (iron condor)", "calendar spread", ...]

# India
t.india_weekly_expiry_today  # True if expiry day
t.india_expiry_instrument    # "NIFTY" (Thu), "BANKNIFTY" (Wed), "FINNIFTY" (Tue)
```

**Regime determines what's available:**

| Regime | Options | Stocks | Futures |
|--------|---------|--------|---------|
| R1 (calm) | Full suite (8 strategies) | All 5 | All strategies |
| R2 (high vol) | Defined risk (5) | All 5 | Premium selling |
| R3 (trending) | Directional only (3) | All 5 | Trend-following |
| R4 (explosive) | Defined risk ONLY | Value + turnaround | EXTREME CAUTION |
| Black Swan | **NO OPTIONS** | **NO STOCKS** | **NO FUTURES** |

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

### Full Macro Research Report

The most comprehensive pre-market analysis — covers 22 assets across equities, bonds, commodities, currencies, and volatility. Classifies the macro regime, computes sentiment, and generates a research note.

```python
from market_analyzer import generate_research_report, RESEARCH_ASSETS

# Fetch data for all 22 research assets
data = {ticker: ds.get_ohlcv(ticker) for ticker in RESEARCH_ASSETS}
report = generate_research_report(data, "daily", fred_api_key=None, spy_pe=26.3)
```

**What you get:**

| Field | What it tells you |
|-------|------------------|
| `report.regime.regime` | RISK_ON / RISK_OFF / STAGFLATION / REFLATION / DEFLATIONARY / TRANSITION |
| `report.regime.position_size_factor` | 1.0 (risk on) down to 0.2 (deflationary) — scale ALL trades |
| `report.regime.favor_sectors` | Where to look (e.g., ["energy", "commodity"] in stagflation) |
| `report.regime.avoid_sectors` | Where to stay away (e.g., ["tech", "bonds"] in stagflation) |
| `report.sentiment.overall_sentiment` | extreme_fear / fear / neutral / greed / extreme_greed |
| `report.sentiment.vix_term_structure` | contango (complacent) / backwardation (panic) |
| `report.sentiment.equity_risk_premium` | Negative = bonds yield more than stocks |
| `report.research_note` | 10-20 sentence research note (ready for daily email) |
| `report.key_signals` | Actionable bullet points |
| `report.india` | India VIX, FII flows, NIFTY-SPY correlation, banking health |

**22 assets tracked:** SPY, QQQ, IWM, DIA (US equity) | NIFTY, BANKNIFTY (India) | EFA, EEM (global) | GLD, SLV, USO, COPX (commodities) | TLT, SHY, ^TNX, TIP (bonds) | HYG, LQD (credit) | UUP (dollar) | VIX, VIX3M, India VIX (volatility)

**14 correlation pairs tracked** with divergence detection: SPY/TLT, SPY/GLD, SPY/VIX, GLD/yields, HYG/TLT, UUP/EEM, NIFTY/SPY, and more.

**Macro regime classification rules:**
- **RISK_ON:** Stocks up + credit tightening + VIX down + gold flat
- **RISK_OFF:** Stocks down + gold/bonds up + VIX elevated
- **STAGFLATION:** Stocks down + yields up + gold/oil up (growth slowing, inflation persistent)
- **REFLATION:** Stocks up + yields up + oil/copper up (growth + inflation both rising)
- **DEFLATIONARY:** Everything falling (liquidity crisis)

**Economic fundamentals (optional, requires free FRED API key):**
GDP growth, CPI, unemployment, Fed funds rate, M2 money supply, yield curve 2s10s, consumer sentiment, high yield spread, initial claims. Graceful without key.

**CLI:** `research` or `research weekly` or `research monthly --fred-key YOUR_KEY`

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

### Step 2.5: Universe — What to Scan

Before screening, decide WHAT to scan. MA ships with built-in universes — no broker needed.

```python
# Built-in presets
tickers = ma.registry.get_universe(preset="income")        # 12 tickers (high options liquidity)
tickers = ma.registry.get_universe(preset="nifty50")       # 43 India NIFTY 50 stocks
tickers = ma.registry.get_universe(preset="sector_etf")    # 12 US sector ETFs
tickers = ma.registry.get_universe(preset="directional")   # 31 liquid equities (US + India)
tickers = ma.registry.get_universe(preset="india_fno")     # 23 India F&O instruments

# Filter by market/sector
tickers = ma.registry.get_universe(market="INDIA", sector="finance")  # 10 India finance tickers

# Custom: add your own instruments at runtime
ma.registry.add_instrument(InstrumentInfo(ticker="COIN", market="US", ...))
```

**10 presets available:** income, directional, us_etf, us_mega, sector_etf, india_fno, india_index, nifty50, macro, all

**85+ instruments** with sector, options liquidity rating (high/medium/low), and scan group tags.

**CLI:** `scan_universe income` or `scan_universe nifty50 --market INDIA`

**Also works in rank/screen:**
```
rank --preset income              # Scan income universe
rank --preset nifty50             # Scan NIFTY 50 stocks
screen --preset sector_etf        # Screen US sector ETFs
rank                              # Auto-default: income (US) or india_fno (India)
```

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

### Account Filtering (Basic)

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

### Portfolio-Aware Filtering (Full Risk Gate)

When you have open positions, use the portfolio-aware filter instead. It enforces:
- **Max positions** (don't open more than 5 total)
- **Per-ticker limit** (max 2 on same underlying)
- **Sector concentration** (max 40% of NLV in one sector)
- **Portfolio risk budget** (max 25% total risk deployed)

```python
from market_analyzer import (
    filter_trades_with_portfolio, OpenPosition, RiskLimits
)

# eTrading builds this from portfolio DB
open_positions = [
    OpenPosition(ticker="SPY", structure_type="iron_condor", sector="index",
                 max_loss=420, buying_power_used=500),
    OpenPosition(ticker="GLD", structure_type="credit_spread", sector="commodity",
                 max_loss=300, buying_power_used=300),
]

result = filter_trades_with_portfolio(
    ranked_entries=ranking.top_trades,
    open_positions=open_positions,
    account_nlv=50000,
    available_buying_power=total_bp - sum(p.buying_power_used for p in open_positions),
    risk_limits=RiskLimits(
        max_positions=5,
        max_per_ticker=2,
        max_sector_concentration_pct=0.40,
        max_portfolio_risk_pct=0.25,
    ),
    allowed_structures=["iron_condor", "credit_spread", "calendar"],
    max_risk_per_trade=2500,
)
# → PortfolioFilterResult
#   approved: trades that pass ALL gates
#   rejected: trades with specific rejection reasons
#   portfolio_risk_pct: current risk as % of NLV
#   slots_remaining: how many more positions can be opened
```

**7-step filter cascade:**
1. Structure whitelist
2. Total position limit
3. Per-ticker limit
4. Buying power check
5. Single trade risk limit
6. Sector concentration
7. Portfolio risk budget

**CLI:** Part of `rank --account 30000`

### Trade Gate Framework — BLOCK / SCALE / WARN

Not all gates should block trades. The framework classifies every check into three tiers:

```python
from market_analyzer import evaluate_trade_gates

report = evaluate_trade_gates(
    ticker="SPY", strategy="iron_condor",
    trade_quality_score=0.45,           # Below 0.50 threshold
    macro_regime="risk_off",            # Cautious regime
    position_count=3, max_positions=5,  # Room for 2 more
    bp_sufficient=True,
    strategy_concentrated=True,         # >50% in IC
)

print(report.final_action)       # "scale" (not blocked — just reduced)
print(report.final_scale_factor) # 0.38 (trade at 38% of normal size)
print(report.can_proceed)        # True (it's a scale, not a block)
print(report.commentary)         # "SCALED to 38% by trade_quality_score, macro_regime_caution..."
```

**Three tiers:**

| Tier | Action | What fires it | Effect |
|------|--------|--------------|--------|
| **BLOCK** | Trade does NOT proceed | Drawdown breaker, portfolio full, no BP, macro DEFLATIONARY | `can_proceed = False` |
| **SCALE** | Reduce position size | Low quality score, macro caution, wide spreads, no IV rank | `final_scale_factor < 1.0` |
| **WARN** | Log + alert, allow trade | Strategy/directional/sector concentration, model stale, data gaps | `can_proceed = True`, full size |

**17 gates classified:**
- 5 BLOCK gates (capital preservation — non-negotiable)
- 5 SCALE gates (quality — trade allowed at reduced size)
- 7 WARN gates (informational — logged but don't affect sizing)

**Shadow Portfolio — Learning from Rejections:**

eTrading should track trades that were BLOCKED to see if they would have been profitable:

```python
from market_analyzer import analyze_gate_effectiveness

# eTrading stores rejected trades and tracks hypothetical P&L
effectiveness = analyze_gate_effectiveness(gate_history, shadow_outcomes, actual_outcomes)

# If rejected trades consistently win:
if effectiveness.shadow_win_rate and effectiveness.shadow_win_rate > 0.60:
    print("Gates too tight — relaxing thresholds")
    # effectiveness.gates_too_tight shows which gates to loosen
```

This creates a **feedback loop**: gates that block profitable trades get flagged for loosening. Gates that let losing trades through get flagged for tightening.

### Portfolio Risk Dashboard

Before placing ANY new trade, check the full risk picture:

```python
from market_analyzer import (
    compute_risk_dashboard, PortfolioPosition, GreeksLimits
)

positions = [
    PortfolioPosition(ticker="SPY", structure_type="iron_condor", direction="neutral",
                      sector="index", max_loss=420, delta=0.03, theta=0.04, vega=-0.10),
    PortfolioPosition(ticker="GLD", structure_type="credit_spread", direction="bullish",
                      sector="commodity", max_loss=300, delta=-0.15, theta=0.02),
]

dashboard = compute_risk_dashboard(
    positions=positions,
    account_nlv=50000,
    peak_nlv=52000,      # Highest NLV ever (for drawdown check)
    regime_id=2,          # Current macro regime
)
```

**What you get:**

```
Overall Risk: MODERATE
Can open new trades: YES (scaled to 75%)

Portfolio VaR (1d 95%): $512 (1.0% of NLV)
Net Delta: -0.12 (slightly bearish) — OK
Net Theta: +$6/day (earning) — OK
Strategy: 50% iron_condor, 50% credit_spread — diversified
Direction: 1 neutral, 1 bullish — OK
Drawdown: -3.8% from peak (threshold: 10%) — OK

Alerts: none
Slots remaining: 3 of 5
```

**7 risk dimensions checked:**

| Dimension | What it checks | Gate |
|-----------|---------------|------|
| **Expected Loss** | ATR-based worst-case 1-day loss estimate | Loss > 5% of NLV → reduce size |
| **Greeks** | Net delta, theta, vega vs limits | Excessive directional exposure → hedge |
| **Strategy** | >50% in one strategy type? | Diversify strategy mix |
| **Directional** | Net bullish/bearish score | >0.5 → directional concentration alert |
| **Correlation** | Positions moving together? | Corr > 0.85 between positions → effectively same trade |
| **Drawdown** | Current NLV vs peak | >10% drawdown → **HALT ALL TRADING** |
| **Macro** | Macro regime from research | DEFLATIONARY → halt, STAGFLATION → 30% size |

**Master gate:** `dashboard.can_open_new_trades` — False if any critical gate fails.

**CLI:** `risk`

### Stress Testing

"What happens to my portfolio if the market crashes 5% tomorrow?"

```python
from market_analyzer import run_stress_suite, run_stress_test, PortfolioPosition

positions = [
    PortfolioPosition(ticker="SPY", structure_type="iron_condor", max_loss=420,
                      delta=0.03, vega=-0.10, notional_value=66000),
    PortfolioPosition(ticker="GLD", structure_type="equity_long", max_loss=5000,
                      delta=1.0, notional_value=25000, direction="bullish"),
]

# Run full suite (7 scenarios)
suite = run_stress_suite(positions, account_nlv=50000)
print(suite.summary)
# → "Stress tested 7 scenarios | Worst: Flash Crash (-8.2%) | Survives all: YES"

# Single scenario
from market_analyzer import get_predefined_scenario
crash = get_predefined_scenario("market_down_5pct")
result = run_stress_test(positions, crash, account_nlv=50000)
# → StressTestResult: total_impact_dollars, per-position impacts, recommended_action
```

**13 predefined scenarios:**

| Scenario | Price | Vol | What it simulates |
|----------|-------|-----|------------------|
| Market -1% | -1% | +10% | Mild selloff |
| Market -3% | -3% | +30% | Significant drop |
| Market -5% | -5% | +60% | Sharp selloff |
| Market -10% | -10% | +150% | Crash |
| Market +3% | +3% | -20% | Strong rally |
| VIX Spike 50% | — | +50% | Volatility shock |
| VIX Doubles | — | +100% | Vol explosion |
| Flash Crash | -7% | +200% | 2015-style flash crash |
| Black Monday | -20% | +300% | 1987 scenario |
| COVID March | -12% | +200% | March 2020 crash |
| India Crash | -5% | +80% | India-specific selloff + INR weakness |
| Fed Surprise | -2% | +20% | Unexpected hawkish signal |
| Rate Shock | -2% | +15% | 10Y yield +50bp |

**Per-position impact** shows exactly which positions survive and which hit max loss.

**Capital preservation rule:** If `suite.survives_all == False` → reduce positions until it does.

**CLI:** `stress_test` (full suite) or `stress_test flash_crash` (single scenario)

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

### Profitability Gate — do_validate

Before placing any trade, run the profitability gate. This runs 7 checks that answer one question: **is this trade actually profitable for a small account after fees, slippage, and real-world constraints?**

```
validate SPY
validate SPY --suite adversarial
validate SPY --suite full
```

**What it checks (daily suite):**

| Check | What it catches | Threshold |
|-------|----------------|-----------|
| `commission_drag` | Fees eating your credit — $0.65×4 legs on a $0.50 IC is a loser | PASS <10% drag, WARN 10-25%, FAIL >25% |
| `fill_quality` | Wide bid/ask means you'll get filled at the offer, not the mid | PASS ≤1.5% spread, WARN 1.5-3%, FAIL >3% |
| `margin_efficiency` | Low ROC means capital is tied up for nothing | PASS ≥15% annualized ROC, WARN 10-15%, FAIL <10% |
| `pop_gate` | Is the probability of profit high enough to overcome the risk/reward? | PASS ≥65% POP |
| `ev_positive` | Expected value: (POP × profit) - ((1-POP) × max_loss) must be positive | PASS if EV > 0 |
| `entry_quality` | Is today's regime and timing appropriate for this strategy? | PASS in entry window + regime match |
| `exit_discipline` | Does the trade have a defined 50% profit target, 2× stop, and DTE exit? | PASS if all three defined |

**What it checks (adversarial suite):**

| Check | What it tests | Threshold |
|-------|--------------|-----------|
| `gamma_stress` | Your IC if underlying moves 2σ in 24 hours — P&L impact | PASS if risk:reward <5×, WARN <10×, FAIL ≥10× |
| `vega_shock` | Your IC if VIX spikes 30% overnight — long vs short vega structures | PASS if loss <25% of credit received |
| `breakeven_spread` | What bid/ask spread makes this trade EV-negative? | PASS if breakeven >2% spread |

**Reading the output:**

```
DAILY VALIDATION — SPY — 2026-03-19
─────────────────────────────────────────
PASS  commission_drag       IC credit $1.80 covers $0.52 round-trip fees (drag: 7.1%)
PASS  fill_quality          Spread 1.2% — survives natural fill
WARN  margin_efficiency     ROC 11.4% annualized — marginal (target ≥15%)
PASS  pop_gate              POP 71.4% ≥ 65% minimum
PASS  ev_positive           EV +$52 per contract
PASS  entry_quality         R1 regime, entry window open
PASS  exit_discipline       TP 50%, SL 2× credit, close ≤21 DTE
─────────────────────────────────────────
RESULT: READY TO TRADE (6/7 passed, 1 warning)
```

**Decision rule:** `is_ready = True` when there are zero FAIL checks. Warnings are tradeable but log them. A FAIL on `commission_drag` means the math doesn't work — don't trade it regardless of how good the setup looks.

**Python API (for programmatic use):**

```python
from market_analyzer import run_daily_checks, run_adversarial_checks

# Daily profitability gate
report = run_daily_checks(
    ticker="SPY",
    trade_spec=trade_spec,        # From assess_iron_condor or any assessor
    entry_credit=1.80,            # From broker quotes
    regime_id=1,                  # From ma.regime.detect()
    atr_pct=0.85,                 # From technicals.snapshot().atr_pct
    current_price=580.0,
    avg_bid_ask_spread_pct=1.2,   # From vol_surface or broker
    dte=35,
    rsi=52.0,
    iv_rank=42.0,
)

if report.is_ready:
    # Proceed to sizing and execution
    pass
else:
    for check in report.failures:
        print(f"BLOCKED by {check.name}: {check.message}")

# Adversarial gate (run before any income trade)
stress = run_adversarial_checks(
    ticker="SPY",
    trade_spec=trade_spec,
    entry_credit=1.80,
    atr_pct=0.85,
)
```

**Key insight:** The daily gate catches trades that look good on paper but fail in execution. The adversarial gate catches trades that survive normal markets but blow up in stress. Run both before entering any income trade.

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

### Leg Execution Plan (India)

India brokers execute multi-leg orders **one leg at a time**. MA plans the safest execution order.

```python
from market_analyzer import plan_leg_execution
plan = plan_leg_execution(spec, market="INDIA")
# → ExecutionPlan: ordered legs with risk assessment per intermediate state
```

**For an iron condor on NIFTY:**
```
Execution Order:
  1. BTO NIFTY 22300P  [SAFE]      — long put wing (protective)
  2. BTO NIFTY 22800C  [SAFE]      — long call wing (protective)
  3. STO NIFTY 22500P  [MODERATE]  — short put (covered by wing)
  4. STO NIFTY 22600C  [MODERATE]  — short call (covered by wing)

Abort rule: If any BUY fails → ABORT. Never sell short without protective wing.
```

**Key rule:** ALWAYS buy protective legs BEFORE selling short legs. This prevents naked exposure.

**Risk levels per intermediate state:**
- **SAFE** — only long legs filled, defined risk
- **MODERATE** — spread completed on one side
- **HIGH** — partial naked exposure
- **CRITICAL** — naked short without protective wing

US trades don't need this — multi-leg orders execute atomically.

**CLI:** `leg_plan NIFTY ic`

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

## 11. Equity Research: Stock Selection for Core Holdings

For core portfolio construction — especially India where options depth is limited.

### Single Stock Analysis

```python
from market_analyzer import analyze_stock, InvestmentHorizon

rec = analyze_stock("RELIANCE", ohlcv=ohlcv_data, horizon=InvestmentHorizon.LONG_TERM, market="INDIA")
# → StockRecommendation with composite_score, rating, entry/stop/target, thesis
```

**5 strategies scored per stock:**

| Strategy | What it looks for | Best for |
|----------|------------------|----------|
| **Value** | Low P/E, low P/B, high dividend, strong balance sheet | Beaten-down quality stocks |
| **Growth** | High revenue/EPS growth, expanding margins, low PEG | Tech, pharma, consumer growth |
| **Dividend** | High sustainable yield, low payout ratio, growing dividends | Income generation, retirees |
| **Quality + Momentum** | High ROE + positive price momentum (GARP) | Core holdings, best of both worlds |
| **Turnaround** | Down 30%+ from high with improving fundamentals | Contrarian, higher risk |

Each strategy returns a **0-100 score** with factors, strengths, and risks.

**Composite score** (horizon-dependent weighting):
- Long-term: 25% value + 20% growth + 20% dividend + 25% quality + 10% turnaround
- Medium-term: 15% value + 15% growth + 10% dividend + 40% quality + 20% turnaround

### Stock Screening

```python
from market_analyzer import screen_stocks, InvestmentStrategy

result = screen_stocks(
    tickers=ma.registry.get_universe(preset="nifty50"),
    ohlcv_data=ohlcv_data,
    strategy=InvestmentStrategy.VALUE,      # Or: growth, dividend, quality_momentum, turnaround
    horizon=InvestmentHorizon.LONG_TERM,
    market="INDIA",
    top_n=10,
    min_score=55.0,
)
# → EquityScreenResult with top_picks, sector_allocation, summary
```

### Entry / Stop / Target Framework

Every `StockRecommendation` includes:

| Field | How it's computed | Example |
|-------|------------------|---------|
| `entry_price` | Current price (buy at market) | ₹1,380 |
| `stop_loss` | Price - 2.0 × ATR (long-term) or 1.5 × ATR (medium-term) | ₹1,307 (5.3% risk) |
| `target_price` | Price + 4.0 × ATR (long-term) or 3.0 × ATR (medium-term) | ₹1,527 (10.6% reward) |
| `risk_reward` | (target - entry) / (entry - stop) | 2.0:1 |

**Position sizing:** `risk_per_share × shares ≤ account × risk_pct`
- US: risk_pct = 3% of account, round to whole shares
- India: same, but round to lot size

### Exit Rules for Equity

| Rule | Trigger | Action |
|------|---------|--------|
| **Stop loss** | Price hits stop | Sell immediately — no exceptions |
| **Target reached** | Price hits target | Take 50% profit, trail stop on rest |
| **Trailing stop** | After +1 ATR: move stop to breakeven. Then trail by 2 ATR | Protects gains |
| **Regime change** | DEFLATIONARY → close all. RISK_OFF → reduce 50% | Capital preservation |
| **Fundamental break** | Revenue negative, dividend cut, debt doubles, ROE < 8% | Sell — thesis broken |
| **Time review** | Long: 6 months. Medium: 4 weeks. | If no progress, exit |
| **Earnings** | Before every earnings report | Review thesis, tighten stop |

**CLI:** `stock RELIANCE --horizon long`, `stock_screen --strategy value --preset nifty50 --market INDIA`

**Reference flow:** `challenge/trader_stocks.py --market India --strategy value --top 10`

---

## 11b. Capital Deployment: Systematic Long-Term Investing

For deploying a large cash position systematically over 6-18 months.

### Market Valuation — Is It Cheap?

```python
from market_analyzer import compute_market_valuation
val = compute_market_valuation("NIFTY", nifty_ohlcv)
# → MarketValuation: zone="deep_value", zone_score=-0.53
# "NIFTY is in deep value territory — historically attractive for long-term entry"
```

| Zone | Score | What it means | Action |
|------|-------|--------------|--------|
| Deep Value | < -0.5 | Significant discount to history | Accelerate deployment +30% |
| Value | -0.5 to -0.2 | Below average | Accelerate +15% |
| Fair | -0.2 to +0.2 | Normal | Deploy at base rate |
| Expensive | +0.2 to +0.5 | Above average | Decelerate -30% |
| Bubble | > +0.5 | Extreme premium | Decelerate -50%, hold cash |

**CLI:** `valuation NIFTY` or `valuation SPY`

### Deployment Plan — How Much Per Month?

```python
from market_analyzer import plan_deployment
plan = plan_deployment(
    total_capital=500000, currency="INR", deployment_months=12,
    market="INDIA", current_regime_id=4, valuation_zone="deep_value",
)
# → DeploymentSchedule: ₹65,000/month (accelerated from ₹41,667 base)
#   equity ₹39,000 / gold ₹9,750 / debt ₹9,750 per month
```

**Acceleration logic:** R4 (buy fear) + deep_value = +56% above base rate. The system deploys more when markets are cheap and volatile.

**CLI:** `deploy 500000 --market India --months 12`

### Asset Allocation — Equity vs Gold vs Debt vs Cash

```python
from market_analyzer import compute_asset_allocation
alloc = compute_asset_allocation(market="INDIA", regime="risk_off", valuation_zone="deep_value")
# → Equity 60% | Gold 25% | Debt 10% | Cash 5%
```

Adjusted by regime, valuation, risk tolerance, and age. Gold increases in risk_off/stagflation. Equity increases when cheap.

**CLI:** `allocate --market India --regime risk_off`

### Core Portfolio — What to Actually Buy

```python
from market_analyzer import recommend_core_portfolio
portfolio = recommend_core_portfolio(500000, "INR", "INDIA", regime_id=4, valuation_zone="deep_value")
# → CorePortfolio with specific holdings:
#   NIFTYBEES (40% of equity), JUNIORBEES (15%), BANKBEES (10%),
#   top 5 value stocks (20%), MIDCAPBEES (15%)
#   + Gold ETF/SGB (25% of total) + debt fund (10%)
```

**CLI:** `deploy 500000 --market India --months 12`

### Rebalancing — When to Adjust

```python
from market_analyzer import check_rebalance
rebalance = check_rebalance(
    current_allocation={"equity": 70, "gold": 12, "debt": 8, "cash": 10},
    target_allocation=alloc,
    portfolio_value=500000,
)
# → RebalanceCheck: needs_rebalance=True
#   "Sell: gold drifted -13% from 25% target"
#   "Buy: equity drifted +10% from 60% target"
```

**CLI:** `rebalance`

### LEAP vs Buying Stock (US Only)

For core US holdings, compare buying 100 shares outright vs a deep ITM LEAP call:

```python
from market_analyzer import compare_leap_vs_stock
leap = compare_leap_vs_stock("SPY", current_price=662.0, dividend_yield_pct=1.3, iv=0.20)
```

| Factor | Buy 100 SPY Shares | Buy 1 LEAP Call (80Δ, 12mo) |
|--------|-------------------|----------------------------|
| Capital | $66,200 | ~$18,500 |
| Upside | 100% | ~85% (delta) |
| Max loss | Unlimited below entry | Premium paid only |
| Dividends | YES (~$860/yr) | NO |
| Theta decay | None | ~$15/day |
| Tax | Simple LTCG | Complex (each roll taxable) |

**When LEAP wins:** Capital efficiency > 5x AND net annual cost < 2% of stock cost. You want exposure with less capital tied up.

**When stock wins:** You want dividends, simplicity, no expiry pressure, and clean tax treatment. For most core holdings, **stock is preferred**.

**Not available for India** — max DTE ~90 days (no LEAPs).

**CLI:** `leap_vs_stock SPY` or `leap_vs_stock AAPL --iv 0.25 --div-yield 0.5`

### The Wheel Strategy (US — Income from Stock Ownership)

The Wheel: sell put → get assigned → sell covered call → called away → repeat.

```python
from market_analyzer import analyze_wheel_strategy
wheel = analyze_wheel_strategy("AAPL", current_price=227.0, iv=0.25, regime_id=1)
# → put yield 37%/yr, call yield 36%/yr, effective basis 7% below market
```

**How it works:**

```
STEP 1: SELL CASH-SECURED PUT
  You want to buy AAPL at $222 (5% below market)
  Sell $222 put, collect $7.91 premium
  If AAPL stays above $222 → put expires, keep premium, repeat
  If AAPL drops below $222 → you buy 100 shares at $222 (you wanted to anyway)
  Your effective cost: $222 - $7.91 = $214.09

STEP 2: SELL COVERED CALL (if assigned)
  You now own 100 AAPL at $214.09 effective basis
  Sell $227 call, collect $7.72 premium
  If AAPL stays below $227 → call expires, keep premium, sell another call
  If AAPL rises above $227 → stock called away at $227 + $7.72 = effective $234.72
  Profit: $234.72 - $214.09 = $20.63 per share

STEP 3: REPEAT
  Stock called away → back to Step 1
```

**Wheel State Machine — MA decides, eTrading executes:**

```python
from market_analyzer import decide_wheel_action, WheelPosition, WheelState
position = WheelPosition(
    ticker="AAPL", state=WheelState.ASSIGNED,
    stock_entry_price=222.0, stock_quantity=100,
    effective_cost_basis=214.09,
    current_underlying_price=225.0,
)
decision = decide_wheel_action(position, regime_id=1)
# → SELL_CALL at $227 for ~$7.72 premium (35d)
```

eTrading builds the state machine (persistence, transitions). MA provides the decision on every state change.

**Best in R1/R2** (mean-reverting, rich premiums). **Avoid in R4** (explosive moves = assignment at bad prices).

**CLI:** `wheel AAPL` or `wheel SPY --iv 0.20 --regime 1`

### 7 Principles for Deployment

1. **Never deploy all at once** — systematic over 6-18 months
2. **Buy fear, not greed** — accelerate when market is down + volatile
3. **Diversify across asset classes** — equity + gold + debt + cash
4. **Index first, stocks second** — NIFTY ETF as core, individual stocks as satellite
5. **Rebalance mechanically** — quarterly, don't predict
6. **Keep cash reserve** — always 10% minimum (5% in deep value)
7. **Ignore daily noise** — review monthly, act quarterly, think in decades

---

## 11c. Futures Trading Guide

### What is a Futures Contract?

A **binding agreement** to buy/sell an asset at a fixed price on a future date. Unlike stocks (you own a piece of a company), futures are **contracts** — promises to transact later.

**Why trade futures?**
- **Leverage:** Control $66,000 of S&P 500 with $3,300 margin (20x leverage)
- **Hedging:** Lock in prices for commodities, currencies, interest rates
- **Nearly 24-hour trading:** Futures trade almost around the clock (unlike stocks)
- **No uptick rule:** Can go short as easily as long

**Key risks:** Leverage amplifies losses. A 1% adverse move on 20x leverage = 20% loss on your margin. **Daily mark-to-market** means losses are deducted from your account every day.

### Futures Basics — What MA Tracks

| Concept | What it is | MA API |
|---------|-----------|--------|
| **Basis** | Futures price - Spot price. Positive = contango, negative = backwardation. | `analyze_futures_basis()` |
| **Term Structure** | How futures prices change across expiry months. Curve shape = carry cost. | `analyze_term_structure()` |
| **Roll** | Closing expiring contract, opening next month. Has a cost in contango. | `decide_futures_roll()` |
| **Calendar Spread** | Buy one expiry, sell another. Profits from curve shape changes. | `analyze_calendar_spread()` |
| **Margin** | Performance bond deposit (not borrowing). Typically 3-12% of contract value. | `estimate_futures_margin()` |

### Contango vs Backwardation (The Most Important Concept)

```
CONTANGO (normal):
  Spot: $100  |  Mar: $101  |  Jun: $103  |  Sep: $106
  Curve slopes UP. Each month costs more.
  YOU PAY to hold longs (negative roll yield).
  Most markets are in contango most of the time.

BACKWARDATION (stress):
  Spot: $100  |  Mar: $98  |  Jun: $95  |  Sep: $92
  Curve slopes DOWN. Near-term costs more than far-term.
  YOU EARN by holding longs (positive roll yield).
  Signals supply shortage or panic demand.
```

**Trading implication:** In contango, long futures positions lose ~5-15%/year just from rolling costs. In backwardation, you get PAID to hold. Knowing the term structure is essential before entering a futures position.

### Rolling — Why and When

Futures expire. To maintain a position, you "roll" — close the expiring contract, open the next month.

**When to roll:** 3-5 days before expiry (watch open interest shift to next month)

**Roll cost example (contango):**
```
You're long March oil at $68.00
June oil trades at $69.50
Roll cost: $1.50 per barrel (you sell low, buy high)
On a 1,000-barrel contract: $1,500 lost to rolling
```

```python
from market_analyzer import decide_futures_roll
roll = decide_futures_roll("CL", current_dte=4, current_price=68.0, next_month_price=69.5)
# → ROLL_FORWARD, cost +2.2%, urgency "soon"
```

### Futures Options — Key Differences from Stock Options

| Aspect | Stock Options | Futures Options |
|--------|-------------|----------------|
| **Underlying** | Stock (shares) | Futures contract |
| **Settlement** | Cash or stock delivery | **Settles into a futures position** |
| **Assignment** | Get 100 shares | Get 1 futures contract (leveraged!) |
| **Margin** | Reg-T (20% of underlying) | SPAN (portfolio-based, often lower) |
| **Size** | 100 shares × price | 1 futures contract × multiplier |
| **Expiry** | Monthly + weeklies | Varies — often before futures expiry |
| **Trading hours** | Market hours only | Nearly 24 hours |
| **Exercise** | American (equity), European (index) | Varies by product |

**CRITICAL:** If you sell a put on ES futures and get assigned, you now have a **long ES futures position** — controlling $330,000 of S&P 500 with ~$16,000 margin. This is NOT like getting 100 shares of a stock. The leverage is extreme.

**Expiry timing:** Futures options typically expire **before** the underlying futures contract. For ES options, they expire on the 3rd Friday of the month. The underlying ES futures expire on the 3rd Friday of the quarter month. Make sure you know BOTH expiry dates.

### Premium Selling on Futures

Same theta-harvesting philosophy as stock options, but with more leverage:

```python
from market_analyzer import analyze_futures_options
opts = analyze_futures_options("ES", futures_price=5200, iv=0.15, regime_id=1)
# → Put: sell 5100P at $45 (35%/yr)
#   Call: sell 5300C at $42 (33%/yr)
#   Strangle: $87/contract (34%/yr combined)
#   Margin: ~$26,000 per strangle
```

**Always use defined risk on futures** (iron condors, not naked strangles) unless you have significant experience and capital. A 5% overnight gap in ES = $13,000 P&L per contract.

### 13 Futures Instruments in MA

| Ticker | Name | Multiplier | Approx Margin | Market |
|--------|------|-----------|---------------|--------|
| ES | S&P 500 E-mini | $50/point | 5% | US |
| NQ | Nasdaq 100 E-mini | $20/point | 6% | US |
| YM | Dow E-mini | $5/point | 5% | US |
| RTY | Russell 2000 | $50/point | 6% | US |
| CL | Crude Oil | $1,000/barrel | 8% | US |
| GC | Gold | $100/oz | 7% | US |
| SI | Silver | $5,000/oz | 10% | US |
| ZB | 30Y Treasury Bond | $1,000/point | 3% | US |
| ZN | 10Y Treasury Note | $1,000/point | 2% | US |
| NG | Natural Gas | $10,000/mmBtu | 12% | US |
| NIFTY_FUT | NIFTY 50 | ₹25/point | 12% | India |
| BANKNIFTY_FUT | Bank NIFTY | ₹15/point | 12% | India |
| FINNIFTY_FUT | Fin NIFTY | ₹40/point | 12% | India |

### Complete Futures Research Report

```python
from market_analyzer import generate_futures_report
report = generate_futures_report("CL", spot_price=68.0, futures_price=69.5,
                                  futures_dte=25, iv=0.30, regime_id=2)
# → FuturesResearchReport with:
#   basis analysis, term structure, roll decision, options opportunities,
#   margin requirements, educational notes
```

Every field includes `educational_notes` — beginner-friendly explanations of what each number means and why it matters.

**CLI:** `futures ES` (when implemented) — eTrading will expose via trading platform

---

## 12. Capability Reference

### By Category

**Market Analysis (8 services):**
`context`, `regime`, `technicals`, `levels`, `phase`, `fundamentals`, `macro`, `vol_surface`

**Opportunity Assessment (12 assessors):**
`iron_condor`, `iron_butterfly`, `calendar`, `diagonal`, `ratio_spread`, `zero_dte`, `leap`, `earnings`, `breakout`, `momentum`, `mean_reversion`, `orb`

**Trade Planning (4 services):**
`screening`, `ranking`, `plan`, `strategy`

**Trade Lifecycle (11 functions):**
`estimate_pop`, `compute_income_yield`, `compute_breakevens`, `check_income_entry`, `filter_trades_by_account`, `filter_trades_with_portfolio`, `aggregate_greeks`, `monitor_exit_conditions`, `check_trade_health`, `assess_overnight_risk`, `recommend_adjustment_action`

**Risk Management (7 functions):**
`compute_risk_dashboard`, `estimate_portfolio_loss`, `check_portfolio_greeks`, `check_strategy_concentration`, `check_directional_concentration`, `check_correlation_risk`, `check_drawdown_circuit_breaker`

**Trade Gates (2 functions):**
`evaluate_trade_gates` (BLOCK/SCALE/WARN for 17 gates), `analyze_gate_effectiveness` (shadow portfolio learning)

**Stress Testing (3 functions):**
`run_stress_test`, `run_stress_suite`, `get_predefined_scenario` (13 predefined scenarios)

**Equity Research (3 functions):**
`analyze_stock`, `screen_stocks`, `fetch_fundamental_profile` (5 strategies, 2 horizons)

**Capital Deployment (8 functions):**
`compute_market_valuation`, `plan_deployment`, `compute_asset_allocation`, `recommend_core_portfolio`, `check_rebalance`, `compare_leap_vs_stock`, `analyze_wheel_strategy`, `decide_wheel_action`

**Futures Analysis (7 functions):**
`analyze_futures_basis`, `analyze_term_structure`, `decide_futures_roll`, `analyze_calendar_spread`, `analyze_futures_options`, `estimate_futures_margin`, `generate_futures_report`

**Hedging & Execution (5 functions):**
`assess_hedge`, `validate_execution_quality`, `assess_currency_exposure`, `compute_portfolio_exposure`, `plan_leg_execution`

**Performance & Learning (12 functions):**
`compute_performance_report`, `compute_sharpe`, `compute_drawdown`, `compute_regime_performance`, `calibrate_weights`, `calibrate_pop_factors`, `optimize_thresholds`, `detect_drift`, `build_bandits`, `update_bandit`, `select_strategies`

**Cross-Market (3 functions):**
`analyze_cross_market`, `compute_cross_market_correlation`, `predict_gap`

**Macro Research (8 functions):**
`generate_research_report`, `compute_all_scorecards`, `compute_correlation_matrix`, `compute_sentiment`, `classify_macro_regime`, `compute_india_context`, `compute_economic_snapshot`, `compute_asset_score`

**Macro Indicators (5 functions):**
`compute_macro_dashboard`, `compute_bond_market`, `compute_credit_spreads`, `compute_dollar_strength`, `compute_inflation_expectations`

**Pre-Market Scanner (2 functions):**
`scan_premarket`, `fetch_premarket_data` (gap detection, volume spikes, 4 strategies)

**Option Pricing (3 functions):**
`compute_theoretical_price` (BS, market-mechanics-aware: American/European, lot size), `check_put_call_parity`, `scan_arbitrage`

**Vol History (2 functions):**
`compute_iv_percentiles`, `build_iv_snapshot_from_surface` (historical IV context for calendar/diagonal)

**Wheel Strategy (1 function):**
`decide_wheel_action` (state machine decision engine — eTrading owns state)

**Currency (4 functions):**
`convert_amount`, `compute_portfolio_exposure`, `compute_currency_pnl`, `assess_currency_exposure`

**Execution (1 function):**
`plan_leg_execution` — leg sequencing for India single-leg markets

**Market Registry (8 methods):**
`get_market`, `get_instrument`, `list_instruments`, `get_universe`, `strategy_available`, `to_yfinance`, `estimate_margin`, `add_instrument`

### CLI Commands (61 total)

| Category | Commands |
|----------|----------|
| Context & Macro | `context`, `stress`, `macro`, `macro_indicators`, `research` |
| Cross-Market | `crossmarket`, `india_context` |
| Analysis | `regime`, `technicals`, `levels`, `analyze`, `vol` |
| Screening | `screen`, `rank`, `plan`, `universe`, `watchlist`, `scan_universe` |
| Opportunity | `opportunity`, `setup`, `entry`, `strategy`, `exit_plan` |
| Trade Analytics | `yield`, `pop`, `income_entry`, `greeks`, `size`, `parse` |
| Monitoring | `monitor`, `health`, `adjust`, `overnight`, `quality`, `leg_plan` |
| Risk | `risk`, `stress_test`, `hedge`, `currency`, `exposure` |
| Performance | `performance`, `sharpe`, `drawdown`, `drift`, `bandit` |
| Equity Research | `stock`, `stock_screen` |
| Capital Deployment | `valuation`, `deploy`, `allocate`, `rebalance`, `leap_vs_stock`, `wheel` |
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

### Zerodha Integration (Live Broker Data for India)

```python
from market_analyzer.broker.zerodha import connect_zerodha
md, mm, acct, wl = connect_zerodha(api_key="xxx", access_token="yyy")

ma = MarketAnalyzer(
    data_service=DataService(), market="India",
    market_data=md, market_metrics=mm,
    account_provider=acct, watchlist_provider=wl,
)

# Now you get REAL bid/ask/OI for India options
chain = ma.quotes.get_chain("NIFTY")       # Live option chain
quality = validate_execution_quality(spec, chain)  # Real liquidity check
balance = acct.get_balance()               # Account in INR
```

**What Zerodha provides:**
- Live bid/ask spreads per option strike (via Kite Connect REST)
- Open interest and volume per strike
- Account balance and margins in INR
- F&O instrument master (all lot sizes, expiries)
- Intraday candles via historical data API
- IV rank computed from chain data

**Credentials:** `zerodha_credentials.yaml` (copy from template). Access token expires daily — re-auth each morning. In SaaS mode, eTrading handles OAuth and passes the KiteConnect session.

**India leg execution:** Multi-leg orders execute one leg at a time on Zerodha. Use `plan_leg_execution(spec, market="INDIA")` to get the safest execution order. See `leg_plan` CLI command.

### Built-in Scanning Universes

No broker needed — MA ships with curated instrument lists:

```
scan_universe income          → 12 tickers (high options liquidity)
scan_universe nifty50         → 43 NIFTY 50 stocks
scan_universe india_fno       → 23 India F&O instruments
scan_universe sector_etf      → 12 US sector ETFs
scan_universe us_mega         → 17 US mega-cap equities
scan_universe directional     → 31 liquid equities (US + India)
```

**CLI:** `scan_universe`, `rank --preset income`, `screen --preset nifty50`

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

*market_analyzer — capital preservation first, income second, growth third.*
*1331 tests. 61 CLI commands. US + India markets. Zerodha + TastyTrade brokers.*
*Options + equities + futures + capital deployment. 75 position-aware functions.*
*5 investment strategies. 13 stress test scenarios. 17 trade gates. 22 macro assets tracked.*

---

## 15. Quant's Cookbook — Creative API Combinations

> Think of market_analyzer as a set of Lego blocks. Each individual API tells you one thing. But the real edge comes from **combining them** — stacking regime detection with vol surface with profitability gates to make decisions no single metric could make alone.
>
> This section is written from a quant's perspective: not "here's what the API returns" but "here's how a systematic trader would USE these together to find and execute high-probability trades."

---

### Recipe 1: The Full Entry Decision Stack

**The problem:** A trade might look good by any single metric — high IV rank, clean regime, good technicals — but still be a loser after fees, slippage, and adverse market conditions.

**The solution:** Gate every entry through a 5-layer decision stack, each layer eliminating a different failure mode.

```python
# Layer 1: Is today safe to trade at all?
ctx = ma.context.assess()
if not ctx.trading_allowed:
    return  # Black swan — protect capital

# Layer 2: Is this instrument in the right regime?
regime = ma.regime.detect("SPY")
if regime.regime == RegimeID.R4:
    return  # Explosive vol — no income trades

# Layer 3: Does the opportunity have positive expected value?
ic = assess_iron_condor("SPY", regime, technicals, vol_surface)
if ic.verdict == Verdict.NO_GO:
    return  # Assessor found a hard stop

# Layer 4: Does it survive the profitability gate?
report = run_daily_checks("SPY", ic.trade_spec, entry_credit=1.80,
                           regime_id=regime.regime.value, ...)
if not report.is_ready:
    return  # Commission drag, fill quality, or ROC failure

# Layer 5: Does it survive adversarial stress?
stress = run_adversarial_checks("SPY", ic.trade_spec, 1.80, atr_pct=0.85)
if stress.failures:
    return  # Doesn't survive 2σ move or vol shock

# All gates passed — now size and execute
```

**Why this works:** Each layer catches a different failure mode. The assessor catches structural problems (wrong regime, flat skew). The profitability gate catches economic problems (fees, fill quality). The adversarial gate catches tail risk. A trade that passes all 5 layers is genuinely high-probability.

---

### Recipe 2: Regime-Adaptive Position Sizing (Kelly-Inspired)

**The problem:** A 5-wide IC on SPY has the same structure whether it's R1 (calm) or R3 (trending), but the actual risk is radically different. Fixed sizing ignores regime.

**The solution:** Scale position size by regime confidence AND current drawdown state.

```python
regime = ma.regime.detect("SPY")
dashboard = compute_risk_dashboard(open_positions, account_nlv=50000, peak_nlv=52000,
                                    regime_id=regime.regime.value)

# Regime-based base size (contracts)
regime_factors = {
    RegimeID.R1: 1.0,   # Full size — calm, mean-reverting
    RegimeID.R2: 0.75,  # 75% — elevated vol, wider swings
    RegimeID.R3: 0.50,  # 50% — trending, income trades underperform
    RegimeID.R4: 0.25,  # 25% — explosive, defined risk only
}
base_factor = regime_factors[regime.regime]

# Confidence adjustment: scale down if HMM isn't sure
# 80%+ confidence → full; 60-80% → partial; <60% → half
confidence_factor = min(1.0, regime.confidence / 0.80)

# Drawdown adjustment: ease off as you approach circuit breaker
# 0-5% drawdown → full; 5-8% → 75%; 8-10% → 50%; >10% → HALT
drawdown_pct = dashboard.drawdown_pct
if drawdown_pct >= 0.10:
    return  # Circuit breaker — no new trades
drawdown_factor = max(0.50, 1.0 - (drawdown_pct / 0.10))

# Final size
contracts = max(1, round(base_contracts * base_factor * confidence_factor * drawdown_factor))
```

**The insight:** A regime at 60% confidence is saying "I'm not sure." That uncertainty should translate directly into position size, not just a warning message.

---

### Recipe 3: Volatility Term Structure Timing (When to Enter Calendars)

**The problem:** Calendar spreads look the same structurally whether vol is in contango or backwardation — but they only make money in one condition.

**The solution:** Use the vol surface to time calendar entries with mathematical precision.

```python
vol = ma.vol_surface.compute("SPY")

# The calendar edge: front month IV must be elevated vs back month
iv_differential = vol.iv_differential_pct  # (front_iv - back_iv) / back_iv * 100

# Entry conditions ranked by quality:
if iv_differential >= 10 and vol.is_backwardation:
    # IDEAL: Front IV significantly elevated, term structure inverted
    # → Enter calendar (sell expensive front, buy cheap back)
    # → IV crush on front will compress faster than back
    quality = "ideal"

elif iv_differential >= 5:
    # GOOD: Decent differential
    quality = "good"

elif iv_differential >= 2:
    # MARGINAL: Thin edge — run check_margin_efficiency first
    report = run_daily_checks(..., iv_rank=iv_rank)
    # Only enter if ROC ≥ 15% despite thin differential
    quality = "marginal"

else:
    # NO EDGE: Front and back IV are flat — calendar has no structural advantage
    # A calendar with flat vol is a coin flip on direction
    return  # No trade

# Add profitability gate to confirm economics work
calendar = assess_calendar("SPY", regime, technicals, vol)
report = run_daily_checks("SPY", calendar.trade_spec, entry_credit, ...)
```

**The insight:** The IV differential is the "reason" a calendar makes money. When it's near zero, you're not selling overpriced vol — you're just taking on gamma risk for no compensation. The vol surface API makes this quantifiable: `vol.iv_differential_pct >= 5%` is your entry filter.

---

### Recipe 4: The 0DTE ORB Decision Engine

**The problem:** On 0DTE, you have one decision in the first 30 minutes: is today a range day or a breakout day? The wrong answer is expensive.

**The solution:** Combine ORB range analysis with regime to make a data-driven call.

```python
# After 10:00 AM — ORB window complete
technicals = ma.technicals.snapshot("SPY")  # ORB auto-fetched if broker connected
zero_dte = assess_zero_dte("SPY", regime, technicals, vol_surface, phase)

# The ORB tells you everything:
orb = zero_dte.orb_decision

if orb.range_pct < 0.30:
    # Narrow range (less than 0.3% of price) = energy compressed = breakout coming
    # → Iron Man (long IC) profits from explosive move in either direction
    # → Set strikes just outside ORB range to catch the move
    strategy = ZeroDTEStrategy.IRON_MAN

elif orb.range_pct > 1.5:
    # Wide range already set = market showed its hand
    # → Standard short IC, put short strike at ORB low, call short strike at ORB high
    # → The range is the range — collect theta within it
    strategy = ZeroDTEStrategy.IRON_CONDOR

elif orb.direction == "bullish" and regime.regime in (RegimeID.R1, RegimeID.R3):
    # Directional bias from first 30 min + regime confirms trend
    # → Bull call spread above ORB range, capturing continuation
    strategy = ZeroDTEStrategy.DIRECTIONAL_SPREAD

# The zero_dte assessor already made this decision — read it
print(zero_dte.strategy)       # Which strategy was selected
print(orb.decision_text)       # Plain English: why this strategy
print(orb.key_levels)          # ORB high, low, extension targets T1/T2
```

**The insight:** Most 0DTE traders pick a strategy before the market opens. This approach waits 30 minutes for real data, then makes a systematic decision. A 0.3% ORB on SPY means an expected move of ~$1.74 on a $580 underlying — the market is coiled. An Iron Man bought at ORB edges profits from any move >= the ORB range width.

---

### Recipe 5: Cross-Market Morning Edge (US -> India Gap Fade)

**The problem:** India opens 13+ hours after US closes. Most retail traders guess the NIFTY opening. You can calculate it.

**The solution:** Use cross-market analysis to predict the India opening gap, then fade it when regime says mean-revert.

```python
# At 9:00 AM IST (before India opens):
us_analysis = analyze_cross_market("SPY", "NIFTY", us_ohlcv, india_ohlcv,
                                    us_regime_id=1, india_regime_id=1)

predicted_gap = us_analysis.predicted_india_gap_pct
confidence = us_analysis.prediction_confidence

# US closed -1.8% → predicting NIFTY gap-down ~1.0%
if predicted_gap < -0.8 and confidence > 0.6:
    india_regime = ma.regime.detect("NIFTY")

    if india_regime.regime in (RegimeID.R1, RegimeID.R2):
        # Mean-reverting regime + predicted gap = gap fade opportunity
        # NIFTY opens at -1% → sell puts 50-80 pts below opening price
        # Gap fills 65% of the time within first 30 minutes

        # Gate: India black swan check first
        india_ctx = ma.context.assess()  # With India market set
        if india_ctx.trading_allowed:
            # Enter NIFTY credit spread: sell put 80 pts below open, buy put 150 pts below
            entry_level = nifty_open_price - 80  # Short put strike
            wing = entry_level - 70              # Long put strike
```

**The insight:** The `prediction_confidence` (R-squared) tells you how reliable the correlation has been recently. When R-squared > 0.60, the US->India overnight linkage is strong enough to trade. When < 0.40, the markets are diverging — don't use the prediction.

**Advanced:** Combine with `analyze_cross_market` sync_status. DIVERGENT markets (where India has been going its own way) are better for standalone NIFTY analysis. SYNCHRONIZED markets are better for cross-market gap fades.

---

### Recipe 6: The Regime Transition Early Warning System

**The problem:** By the time a regime is officially detected as R4, half the damage is done. You want to start defending your portfolio when the transition is just beginning.

**The solution:** Watch the HMM probability vector — not just the current label — for regime transition signals.

```python
regime = ma.regime.detect("SPY", debug=True)

# The probability vector is the leading indicator:
probs = regime.regime_probabilities  # {1: 0.52, 2: 0.31, 3: 0.08, 4: 0.09}

# Current: R1 (52% confidence) — normal income trade day
# But R2 probability is 31% — elevated, watching

# Early warning thresholds:
r2_rising = probs[2] > 0.30   # R2 probability elevated
r4_rising = probs[4] > 0.15   # R4 creeping in — danger signal

if r4_rising:
    # Don't wait for R4 confirmation — start de-risking NOW
    # 1. No new IC entries (even if current label is R1)
    # 2. Close any ICs with DTE > 30 (too much time for R4 to do damage)
    # 3. Tighten stops on existing ICs from 2× to 1.5× credit
    print("EARLY WARNING: R4 probability rising. Defensive mode.")

elif r2_rising:
    # R1 → R2 transition forming
    # 1. Widen IC wings by 10-15% on any new entries
    # 2. Reduce position size by 25%
    # 3. Prefer iron butterfly over IC (profits from vol expansion in R2)

# Combine with ATR trend to confirm:
tech = ma.technicals.snapshot("SPY")
if r2_rising and tech.atr_pct > 1.2:  # ATR expanding
    # Both regime model AND price action saying vol is picking up
    # Higher conviction signal — act more aggressively
```

**The insight:** A 15% R4 probability in the HMM is saying "1 in 7 chance we're already in explosive vol." That's not a small tail risk — it's your model telling you to stay alert. The probability vector is your actual conviction signal; the regime label is just the argmax.

---

### Recipe 7: Sector Rotation from Macro Research

**The problem:** You're scanning the same 10 tickers every day. But macro shifts — REFLATION, STAGFLATION, RISK_OFF — move money into different sectors. You should be scanning where the money is flowing.

**The solution:** Use macro research to identify sectors of strength, then screen within those sectors.

```python
from market_analyzer import generate_research_report, RESEARCH_ASSETS

# Weekly (or daily pre-market with fresh data)
data = {ticker: ds.get_ohlcv(ticker) for ticker in RESEARCH_ASSETS}
report = generate_research_report(data, "daily")

# Read where money is flowing
favor = report.regime.favor_sectors    # e.g., ["energy", "commodity"] in stagflation
avoid = report.regime.avoid_sectors    # e.g., ["tech", "bonds"]
size_factor = report.regime.position_size_factor  # 0.5 in risk-off

# Map sectors to tickers
sector_to_tickers = {
    "energy": ["XLE", "USO", "MRO"],
    "commodity": ["GLD", "SLV", "COPX"],
    "tech": ["QQQ", "XLK", "NVDA"],
    "bonds": ["TLT", "SHY"],
    "finance": ["XLF", "JPM"],
    "healthcare": ["XLV", "JNJ"],
}

scan_universe = []
for sector in favor:
    scan_universe.extend(sector_to_tickers.get(sector, []))

# Now rank within the high-conviction sectors
ranking = ma.ranking.rank(
    tickers=scan_universe,
    skip_intraday=True,
    debug=True,
)

# Apply macro sizing to all approved trades
approved = filter_trades_with_portfolio(ranking.top_trades, open_positions, ...)
for trade in approved.approved:
    trade.trade_spec.leg_quantity = round(trade.trade_spec.leg_quantity * size_factor)
```

**The insight:** In a STAGFLATION regime, scanning SPY, QQQ, and IWM is exactly wrong — those are the sectors to avoid. The research report's `favor_sectors` list is forward-looking: it tells you where to hunt. Combine this with the regime-specific strategy selection (R1=income, R3=directional) and you have sector + structure simultaneously.

---

### Recipe 8: The Mechanical Adjustment Protocol

**The problem:** Most traders know intellectually to "roll at 21 DTE" or "close at 2x loss" but execute it inconsistently under pressure. The system should make this decision without emotion.

**The solution:** Run `check_trade_health` on every open position, then feed the result into the adjustment analyzer. One deterministic action per position.

```python
from market_analyzer import check_trade_health, monitor_exit_conditions
from market_analyzer import AdjustmentService

adj_service = AdjustmentService(quote_service=ma.quotes)

for position in open_positions:
    # Step 1: Should we exit?
    exit_signal = monitor_exit_conditions(
        trade_spec=position.trade_spec,
        current_price=current_price,
        entry_price=position.entry_price,
        days_held=position.days_held,
        regime=current_regime,
    )

    if exit_signal.should_exit:
        print(f"EXIT {position.ticker}: {exit_signal.reason}")
        # Reason: "profit_target_hit" / "stop_loss_hit" / "dte_exit" / "regime_change"
        continue

    # Step 2: If not exiting, should we adjust?
    health = check_trade_health(
        trade_spec=position.trade_spec,
        current_price=current_price,
        entry_price=position.entry_price,
        regime=current_regime,
    )

    if health.status == "BREACHED":
        adjustment = adj_service.analyze(position.trade_spec, current_regime, technicals)
        # The top recommendation is the deterministic action
        action = adjustment.recommended_adjustments[0]
        print(f"ADJUST {position.ticker}: {action.description}")
        # Never "wait and see" — always the defined action
```

**The insight:** `monitor_exit_conditions` returns `exit_signal.reason` — which is one of four things: profit target hit, stop loss hit, DTE exit, or regime change. The adjustment analyzer returns a ranked list of actions — the first one is always the right move. This eliminates the "should I roll or close?" paralysis that costs small account traders thousands of dollars per year.

---

### Recipe 9: Shadow Portfolio — Learning Whether Your Gates Work

**The problem:** Your quality gate blocks 30% of trades. Are those blocked trades actually losers? Or are you leaving money on the table?

**The solution:** Track what would have happened to every blocked trade, then analyze whether the gate is calibrated correctly.

```python
from market_analyzer import analyze_gate_effectiveness

# eTrading stores: (a) trades that were BLOCKED with their gate reason
# (b) what price the trade would have closed at (shadow P&L)
# (c) actual P&L of trades that DID go through

effectiveness = analyze_gate_effectiveness(
    gate_history=gate_history,           # Every gate decision, reason, trade spec
    shadow_outcomes=shadow_pnl,          # Hypothetical P&L if blocked trades had gone through
    actual_outcomes=actual_pnl,          # Real P&L of approved trades
)

# The key numbers:
print(f"Approved win rate: {effectiveness.actual_win_rate:.0%}")    # 67%
print(f"Shadow win rate: {effectiveness.shadow_win_rate:.0%}")      # 71%

# If shadow > actual → gates are too tight (blocking good trades)
if effectiveness.gates_too_tight:
    print("Gates too tight — these gates are blocking winners:")
    for gate in effectiveness.gates_too_tight:
        print(f"  {gate.name}: {gate.shadow_win_rate:.0%} win rate when blocked")
        # e.g., "quality_score: 73% win rate when blocked" → lower the threshold

# If actual > shadow → gates are working (blocking losers correctly)
if effectiveness.actual_win_rate > effectiveness.shadow_win_rate:
    print("Gates working correctly — blocked trades were losers")
```

**The insight:** This is how the system learns from its own decisions. Most trading systems backtest entry logic but never analyze their risk filters. A quality gate that blocks trades with 70% win rates is destroying your edge. This API makes that visible in production, not just in hindsight.

---

### Recipe 10: The Full Weekly Calibration Loop

**The problem:** The system was calibrated on historical data. Markets change. Rankings that worked 3 months ago may be over-weighting factors that no longer predict well.

**The solution:** Every Sunday, feed the week's trade outcomes back into the system and let it re-calibrate its own scoring weights.

```python
from market_analyzer import calibrate_weights, TradeOutcome

# Build TradeOutcome list from your journal/eTrading DB
outcomes = [
    TradeOutcome(
        ticker="SPY", strategy="iron_condor",
        entry_date=date(2026, 3, 11), exit_date=date(2026, 3, 18),
        entry_credit=1.80, exit_debit=0.90,   # Closed at 50% — WINNER
        max_profit=180, max_loss=320,
        regime_at_entry=RegimeID.R1, actual_pop=1,  # 1=won, 0=lost
        exit_reason="profit_target",
    ),
    # ... more outcomes
]

new_weights = calibrate_weights(outcomes)

# What changed?
print(new_weights.regime_weight_delta)    # R1 weight +0.05 (R1 trades outperforming)
print(new_weights.iv_rank_weight_delta)   # IV rank weight +0.03 (high IV rank trades winning)
print(new_weights.commentary)             # "Iron condor win rate 71% in R1 — increase R1 alignment weight"

# Apply to next week's ranking
ranking = ma.ranking.rank(tickers, weights=new_weights.weights)
```

**The insight:** `calibrate_weights` is running a lightweight regression: which features in your ranked trades best predicted actual outcomes? If high IV-rank trades are winning at 75% and low IV-rank trades at 52%, the calibrator increases IV-rank weight. If R2 iron condors are losing more than expected, it reduces R2 alignment for IC specifically. This is live, production learning without needing a full ML pipeline.

---

### Recipe 11: Multi-Leg Arbitrage — Diagonal vs Calendar Decision

**The problem:** Both calendars and diagonals profit from IV decay, but in different market conditions. Choosing wrong costs ROC.

**The solution:** Let the regime + vol surface combination tell you which structure to enter.

```python
vol = ma.vol_surface.compute("SPY")
regime = ma.regime.detect("SPY")
tech = ma.technicals.snapshot("SPY")

calendar = assess_calendar("SPY", regime, tech, vol)
diagonal = assess_diagonal("SPY", regime, tech, vol)

# Decision framework:
if regime.regime in (RegimeID.R1, RegimeID.R2) and vol.iv_differential_pct >= 5:
    # CALENDAR: neutral market, IV differential present
    # Want ATM strikes, no directional bias
    # Best in R1: theta works, vol steady
    pick = calendar

elif regime.regime == RegimeID.R3 and tech.rsi.value > 55:
    # DIAGONAL (bull call diagonal): mild uptrend, want some directional exposure
    # Buy deep ITM long-dated call (lower strike), sell short-dated OTM call (higher)
    # Profits from both theta AND the uptrend
    pick = diagonal

elif regime.regime == RegimeID.R3 and tech.rsi.value < 45:
    # DIAGONAL (bear put diagonal): mild downtrend
    # Buy deep ITM long-dated put, sell short-dated OTM put
    pick = diagonal

# Confirm economics on the chosen structure
report = run_daily_checks(
    "SPY", pick.trade_spec, entry_credit=pick.trade_spec.max_profit / 100,
    regime_id=regime.regime.value, ...
)
# Only enter if ROC ≥ 15% — calendars and diagonals can have marginal ROC
```

**The insight:** The assessors give you GO/NO_GO + a trade spec. But you're choosing between two GO assessors — this is where the qualitative logic lives. R1 + IV differential = calendar. R3 + trend = diagonal. The vol surface `iv_differential_pct` and the regime label together make this a systematic rule, not a judgment call.

---

### Recipe 12: The Earnings Volatility Harvest

**The problem:** IV spikes into earnings — often to extreme levels. Most traders avoid earnings because of the binary risk. But IV always collapses after earnings. Can you harvest the IV crush systematically?

**The solution:** Combine the earnings assessor, IV rank, and vega shock check to find earnings plays where the IV crush math works.

```python
from market_analyzer import assess_earnings

# Find earnings in next 5-14 days in your watchlist
for ticker in watchlist:
    earnings = assess_earnings(ticker, regime, technicals, vol_surface, fundamentals)

    if earnings.verdict == Verdict.NO_GO:
        continue

    # Key metrics for earnings vol harvesting:
    iv_rank = metrics.iv_rank  # Should be > 70% for good crush potential
    iv_pct = vol.front_iv      # Actual IV level — is it overpriced?

    # The crush math: if IV is 60% pre-earnings and typically drops to 35% post
    # → IV crush of ~40% = significant premium collapse
    if iv_rank > 70 and vol.front_iv > 0.45:
        # High IV rank + elevated front IV = premium is likely overpriced

        # Structure choice by regime:
        # R1/R2: Short straddle/strangle (defined by wings) — sell the vol crush
        # R3: Iron condor centered on expected move — sell vol but bounded
        # R4: NO TRADE on earnings — explosive moves + high IV = max uncertainty

        # Adversarial check: will the trade survive if the stock moves MORE than expected?
        stress = run_adversarial_checks(ticker, earnings.trade_spec,
                                         entry_credit, atr_pct)

        if not stress.failures:
            # Trade survives stress → earnings crush play is valid
            print(f"{ticker}: IV {vol.front_iv:.0%} → crush candidate (IV rank {iv_rank})")
```

**The insight:** Earnings plays lose when: (1) the stock moves 2x the expected move — use `check_gamma_stress`; (2) you can't fill at the mid — use `check_fill_quality`; (3) fees eat the small credit — use `check_commission_drag`. These three checks together filter 80% of bad earnings plays before you even look at the company.

---

### Recipe 13: The Position-Level Greeks Budget

**The problem:** You have 4 open ICs and they all have negative vega. A VIX spike hits and your whole portfolio bleeds simultaneously — correlated loss you didn't see coming.

**The solution:** Use the risk dashboard to monitor portfolio-level Greeks, not just position-level.

```python
dashboard = compute_risk_dashboard(open_positions, account_nlv=50000, ...)

# Portfolio-level Greeks view:
net_delta = dashboard.greeks_summary.net_delta      # -0.08 (slightly bearish exposure)
net_theta = dashboard.greeks_summary.net_theta      # +$18/day (earning time value)
net_vega = dashboard.greeks_summary.net_vega        # -0.45 (short vol — VIX spike = pain)

# VIX is at 16. If it spikes to 25 (+56%):
# Estimated P&L impact = net_vega × IV_move = -0.45 × 0.09 × 100 × contracts
# → This is why check_vega_shock exists — it quantifies this at trade level

# Greeks-based decision rules:
if abs(net_delta) > 0.25:
    # Portfolio is directionally biased — add hedge or reduce delta
    print("WARNING: Portfolio delta too high — add neutral position")

if net_vega < -0.60:
    # Too much short vol exposure — VIX spike will hurt everything simultaneously
    # Solution: add a long vega trade (debit spread, long calendar) to reduce net vega
    print("WARNING: Portfolio short vega concentration — add long vol position")

    # The hedge: an SPY debit spread (buy call spread) adds positive delta AND positive vega
    # Alternatively: a VIX call spread is a direct vol hedge
```

**The insight:** Short vol strategies (IC, iron butterfly, credit spreads) all have negative vega. If you have 5 of them, you've built a portfolio that loses money every time VIX rises. The `net_vega` check in the risk dashboard flags this before it becomes a problem. Target net_vega > -0.40 by periodically adding a long vol trade (PMCC, calendar, debit spread) to offset.

---

### Recipe 14: The Systematic India Expiry Day Play

**The problem:** India options expire weekly — NIFTY on Thursday, BANKNIFTY on Wednesday, FINNIFTY on Tuesday. Expiry day has different dynamics (vol crush, gamma spikes) than normal days.

**The solution:** Use the India context to detect expiry day, then select the right 0DTE strategy.

```python
ctx = ma.context.assess()

if ctx.tradeable.india_weekly_expiry_today:
    instrument = ctx.tradeable.india_expiry_instrument  # "NIFTY", "BANKNIFTY", or "FINNIFTY"

    # Expiry day dynamics:
    # 1. ATM options have very high gamma — any move is amplified
    # 2. OTM options lose value rapidly — theta is maximal
    # 3. First 30 min sets the range for the day (ORB is critical)

    india_regime = ma.regime.detect(instrument)
    india_vol = ma.vol_surface.compute(instrument)
    india_tech = ma.technicals.snapshot(instrument)

    # On expiry day: 0DTE is the ONLY structure (everything expires today)
    zero_dte = assess_zero_dte(instrument, india_regime, india_tech, india_vol)

    # Expiry day bias rules:
    if india_regime.regime in (RegimeID.R1, RegimeID.R2):
        # IC wins: sell ATM straddle ± 1.5 ATR wings, collect theta decay
        # Key: must enter by 10:00 AM IST — the theta curve steepens after noon
        pass

    elif zero_dte.orb_decision.range_pct < 0.25:
        # Narrow ORB on expiry = explosive move coming
        # Iron Man: buy inner wings at ORB edges, sell farther wings
        # Size: 50% of normal (gamma is dangerous on expiry day)
        pass
```

**The insight:** India expiry day creates a mechanical edge: OTM options lose value 3x faster than normal on expiry morning. The BankNIFTY ICs entered at 9:30 AM with strikes 200 pts wide from spot have collected their premium by 1:00 PM in most sessions. The key filter is regime — R4 on expiry day means gaps are possible and the IC will breach. Use the regime gate without exception.

---

### Summary: The Mental Model

Think of the MA API as having three tiers:

```
TIER 1 — WHAT IS THE MARKET DOING?
  ma.regime.detect()           → Are we in R1/R2/R3/R4?
  ma.context.assess()          → Is it safe to trade at all?
  ma.technicals.snapshot()     → What is the price structure?
  ma.vol_surface.compute()     → What is the vol surface saying?
  generate_research_report()   → What is the macro environment?

TIER 2 — WHAT SHOULD I TRADE?
  assess_iron_condor() etc.    → Is this specific structure valid?
  ma.ranking.rank()            → What ranks highest across all opportunities?
  filter_trades_with_portfolio() → What fits my portfolio today?
  evaluate_trade_gates()       → Scale or block any specific trade?

TIER 3 — IS THIS TRADE ACTUALLY PROFITABLE?
  run_daily_checks()           → Commission drag, fill quality, ROC, POP, EV
  run_adversarial_checks()     → Survives gamma stress, vega shock, breakeven spread?
  check_trade_health()         → Status of existing positions
  monitor_exit_conditions()    → Should I exit now?
```

The Tier 1 APIs answer "what world are we in." The Tier 2 APIs answer "what fits this world." The Tier 3 APIs answer "will this actually make money after real-world constraints." All three tiers together = a complete systematic trading decision.

**The edge is in Tier 3.** Most systematic platforms have Tier 1 and Tier 2. The profitability gate (Tier 3) is what separates a platform that makes money from one that only looks like it should make money.
