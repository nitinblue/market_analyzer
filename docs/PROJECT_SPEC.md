# market_analyzer — Project Specification

> Single source of truth for what this project is, what it does, and how it works.
> Last updated: 2026-03-21

---

## 1. Mission

`market_analyzer` is a Python library that helps make money trading options. It is a production tool for real capital deployment — not a theoretical exercise.

It brings institutional-grade systematic trading to small accounts ($30-50K). The gap it fills: there are tools for institutions (expensive, closed) and tools for retail (basic, manual). The space in between — **systematic income trading for small accounts with real risk management** — is empty. MA fills it.

It detects per-instrument regime state (R1–R4) using Hidden Markov Models, generates ranked trade recommendations with machine-readable `TradeSpec` outputs, and provides every analytical building block needed to make informed options trading decisions. The library is stateless: eTrading owns authentication, tenant isolation, caching, and execution; MA owns analysis and decisions.

---

## 2. Vision: Learn by Trading, Not by Backtesting

**MA does not have a backtesting engine. This is deliberate.**

Backtesting gives false confidence. It overfits to the past, assumes perfect fills, ignores commissions, and teaches traders to trust historical patterns that may never repeat. The graveyard of blown-up accounts is full of traders who said "but it backtested well."

MA's approach is different:

### Every Trade Is Bespoke to YOU

MA does not generate generic "buy SPY calls" signals. Every suggested trade is tailored to:

- **Your portfolio** — what positions are already open, what's correlated, how much risk is deployed
- **Your risk profile** — drawdown tolerance, max positions, circuit breaker threshold
- **Your capital** — Kelly sizes to YOUR account, not a theoretical $100K model account
- **Your market** — regime detection on YOUR watchlist tickers, not a global "market is bullish"
- **Your history** — as you trade, `calibrate_weights()` tunes the system to YOUR outcomes

Two traders with different accounts, different open positions, and different risk tolerances will get **different trade recommendations** from the same market data. The system doesn't say "this is a good trade." It says "this is a good trade **for you, right now, given what you already have.**"

### The Forward Testing Loop

```
1. START SMALL      → System protects you (validation gates, Kelly quarter-sizing)
2. TRADE REAL       → 1 contract, real money, real fills, real emotions
3. RECORD OUTCOME   → TradeOutcome captures everything: entry, exit, regime, P&L
4. SYSTEM LEARNS    → calibrate_weights() adjusts ranking from YOUR real outcomes
5. SCALE UP         → Kelly automatically increases sizing as win rate is proven
6. REPEAT           → Each cycle makes the system more tuned to YOUR trading
```

### What This Means in Practice

- A new user starts with the system's proven defaults (regime-gated iron condors, 50% profit target, 2× stop)
- The validation gate (10 checks) and Kelly sizing protect capital during the learning phase
- After 20-30 trades, `calibrate_weights()` has real data to work with
- The system gets better over time from REAL outcomes, not from fitting to the past
- No strategy is adopted because "it backtested well" — strategies are adopted because they WORKED in your account

### Why This Matters for Small Accounts

A $35K account can't afford the learning tax of blown-up backtested strategies. It needs:
- **Proven structures** (IC, credit spread, calendar — not exotic strategies)
- **Real risk management** (circuit breakers, regime stops, correlation-aware sizing)
- **Gradual scaling** (1 contract → 2 → 3 as outcomes prove the edge)
- **System-enforced discipline** (validation gates can't be overridden by emotions)

The decision audit, crash sentinel, and profitability gates exist to PROTECT capital during the forward testing phase. They are not optional safety features — they are the core product.

---

## 3. Core Principles

### Reliability Over Cleverness

This library handles real money. Every output must be trustworthy or explicitly marked as unavailable.

### Data Integrity Rules

| Rule | Description |
|------|-------------|
| No fake data | If real data is unavailable, return `None`. Never invent numbers. A missing value is infinitely better than a wrong one. |
| No Black-Scholes — ever | All option prices (bid/ask/mid, Greeks, IV) come from the broker via DXLink streamer. If no broker is connected, the value is `None`. yfinance provides historical OHLCV and chain structure only. |
| Source traceability | Every value must trace to its source. CLI output must show data source for any options-related data. |
| Calculated values need commentary | Regime labels, trend strength, POP estimates — the calculation path must be traceable (inputs, formula, assumptions). |
| Cache before fetch, never silently stale | Cache is an optimization. If cache is stale and fetch fails, say so — don't silently serve yesterday's data as if current. |

### Engineering Rules

- **No module-level mutable state.** All caches, connections, and config must be injectable via constructor.
- **Library only.** No server, no UI. CLI is for dev/exploration only. Imported by cotrader/eTrading.
- **Type everything.** Pydantic models for public interfaces. Type hints on all functions.
- **Provider failures are not silent.** Raise typed exceptions. Callers must distinguish "no data exists" from "fetch failed."
- **No API keys in code.** Credentials from env vars or config files only.
- **Additive changes preferred** over moving existing files.
- **`data/` works without `hmm/`. `hmm/` works with caller-provided DataFrames.** No circular dependencies.

---

## 4. Trading Philosophy

| Principle | Details |
|-----------|---------|
| Income-first | Default to theta harvesting. Directional only when regime permits. |
| Small accounts | 30-50K taxable, 200K IRA. Margin efficiency matters. Every trade must fit. |
| Per-instrument regime | Gold can trend while tech chops. No global "market regime." |
| Regime-gated decisions | No decision without a regime label. This is the core invariant. |
| Same-ticker hedging only | No beta-weighted index hedging. |
| Forward testing only | No backtesting. Start with 1 contract, prove it works, scale up. |
| Capital preservation first | The most valuable thing the system does on a bad day is say "no." |
| Every recommendation is executable | If the system suggests a trade action, it returns a TradeSpec with legs. |
| Trust is earned, not assumed | Every output carries a 2-dimensional trust score (data quality + context quality). |

### What MA Is NOT

- **Not a backtesting engine.** Will never be. Use proven structures, validate forward.
- **Not an order execution system.** MA decides. eTrading (or the trader) executes.
- **Not a signal service.** MA doesn't tell you "buy SPY." It tells you "R1 regime, IC at these strikes, this credit, this sizing, this stop, this exit plan, this trust score."
- **Not a black box.** Every decision is explainable — regime label traces to HMM features, every score traces to its components, every gate shows what passed and what failed.
| Explainability | Every regime label traces to features and model state. Every number has a "why." |

---

## 4. Regime Model

| Regime | Name | Primary Strategy | Avoid |
|--------|------|-----------------|-------|
| R1 | Low-Vol Mean Reverting | Iron condors, strangles (theta harvesting) | Directional trades |
| R2 | High-Vol Mean Reverting | Wider wings, defined risk (selective theta) | Directional trades |
| R3 | Low-Vol Trending | Directional spreads, diagonals | Heavy theta (iron condors) |
| R4 | High-Vol Trending | Risk-defined only, long vega | Theta strategies |

**HMM Features** (computed from 60-day OHLCV): `log_return_1d`, `realized_vol_20d`, `atr_norm`, `trend_strength`, `volume_anomaly` — all reported as z-scores.

**Debug mode output example:**
```
REGIME DETECTION: SPY as of 2026-03-14
  Features computed from 60 days OHLCV (2026-01-02 to 2026-03-14)
  ├─ log_return_1d: -0.0023 (z-score: -0.41)
  ├─ realized_vol_20d: 0.0142 (z-score: +1.23) → elevated
  ├─ atr_norm: 0.0089 (z-score: +0.87)
  ├─ trend_strength: -0.31 (z-score: -0.92) → weak downtrend
  └─ volume_anomaly: 1.34 (z-score: +0.55)
  HMM inference: state probabilities [R1: 0.12, R2: 0.61, R3: 0.08, R4: 0.19]
  Result: R2 (confidence: 61%) — High-Vol Mean Reverting
```

---

## 5. Architecture

### Library Boundary

| Direction | What |
|-----------|------|
| eTrading passes in | Current quotes, trade outcomes, account state |
| MA computes and returns | Rankings, exit signals, adjustments, calibrated weights |
| MA never stores | Positions, fills, P&L history, session state |
| Risk checks (E01-E10) | Belong to eTrading, not MA |

### Module Map

| Module | Description |
|--------|-------------|
| `service/` | All workflow services (see Key Entry Points below). `analyzer.py` is the top-level facade. |
| `models/` | Pydantic models for all public interfaces: `opportunity.py`, `ranking.py`, `trading_plan.py`, `quotes.py`, `adjustment.py`, etc. |
| `opportunity/` | Opportunity assessment split into `setups/` (price-based) and `option_plays/` (option structures) |
| `opportunity/setups/` | `breakout.py`, `momentum.py`, `mean_reversion.py`, `orb.py` |
| `opportunity/option_plays/` | `iron_condor.py`, `iron_butterfly.py`, `calendar.py`, `diagonal.py`, `ratio_spread.py`, `zero_dte.py`, `leap.py`, `earnings.py` |
| `features/` | Feature computation pipeline (`pipeline.py`), technicals, vol surface, black swan, ranking matrices |
| `hmm/` | HMM model training and inference. Accepts caller-provided DataFrames — no data dependency. |
| `data/` | Data fetching, caching, providers. Works without `hmm/`. Parquet cache with staleness checks. |
| `broker/` | Pluggable broker ABCs (`base.py`) and TastyTrade implementation (`tastytrade/`) |
| `validation/` | Profitability validation framework: `run_daily_checks()` (7 checks), `run_adversarial_checks()` (3 checks) |
| `trade_lifecycle.py` | 10 pure-function APIs: pre-trade, entry, monitoring — primary eTrading integration surface |
| `trade_spec_factory.py` | `create_trade_spec()`, `build_iron_condor/credit_spread/debit_spread/calendar()`, DXLink symbol conversion |
| `risk.py` | Portfolio risk management: Greeks, concentration, correlation, drawdown, expected loss |
| `gate_framework.py` | `evaluate_trade_gates()` — BLOCK/SCALE/WARN trade gate classification |
| `performance.py` | Performance feedback: calibration, Sharpe, drawdown, regime performance, Thompson Sampling bandits |
| `macro/` | Macro calendar, expiry events, black swan detection |
| `macro_indicators.py` | Bond market, credit spread, dollar strength, inflation expectation indicators |
| `macro_research.py` | Asset scorecards, correlations, sentiment, economic snapshots, research reports |
| `equity_research.py` | Stock screening and fundamental analysis for core holdings |
| `capital_deployment.py` | Long-term systematic investing: valuation, allocation, rebalance, LEAP vs stock |
| `wheel_strategy.py` | Wheel strategy state machine — MA decides, eTrading executes |
| `stress_testing.py` | Portfolio scenario analysis |
| `arbitrage.py` | Put-call parity check, theoretical pricing, arbitrage scanning |
| `premarket_scanner.py` | Pre-market gap and alert scanning |
| `registry.py` | `MarketRegistry`: market info, instrument info, margin estimates |
| `currency.py` | Currency conversion and cross-market exposure |
| `cross_market.py` | Cross-market correlation, gap prediction |
| `hedging.py` | Same-ticker hedge assessment (HedgeType, HedgeUrgency, HedgeRecommendation) |
| `leg_execution.py` | Leg sequencing for single-leg markets (India) |
| `execution_quality.py` | `validate_execution_quality()`: spread, OI, volume checks |
| `vol_history.py` | IV percentile layer: `DailyIVSnapshot`, `IVPercentiles`, `compute_iv_percentiles()` |
| `futures_analysis.py` | Futures term structure, basis, calendar spread, roll decisions |
| `config/` | All settings classes: `Settings`, `IronCondorSettings`, `CalendarSettings`, `TradingPlanSettings`, `BrokerSettings`, etc. |
| `cli/` | `interactive.py` — `analyzer-cli` REPL entry point (67 commands) |

### Key Entry Points

All accessed through the `MarketAnalyzer` facade:

```python
from market_analyzer import MarketAnalyzer, DataService

ma = MarketAnalyzer(data_service=DataService())
```

| Attribute | Service | Primary Method |
|-----------|---------|---------------|
| `ma.regime` | `RegimeService` | `detect(ticker)` → `RegimeResult` |
| `ma.technicals` | `TechnicalService` | `snapshot(ticker)` → `TechnicalSnapshot` |
| `ma.phase` | `PhaseService` | `detect(ticker)` → `PhaseResult` |
| `ma.fundamentals` | `FundamentalService` | `get(ticker)` → `FundamentalsSnapshot` |
| `ma.macro` | `MacroService` | `calendar()` → `MacroCalendar` |
| `ma.levels` | `LevelsService` | `analyze(ticker)` → `LevelsAnalysis` |
| `ma.vol_surface` | `VolSurfaceService` | `compute(ticker)` → `VolatilitySurface` |
| `ma.opportunity` | `OpportunityService` | `assess_*(ticker)` → opportunity models |
| `ma.ranking` | `TradeRankingService` | `rank(tickers)` → `TradeRankingResult` |
| `ma.black_swan` | `BlackSwanService` | `alert()` → `BlackSwanAlert` |
| `ma.context` | `MarketContextService` | `assess()` → `MarketContext` |
| `ma.instrument` | `InstrumentAnalysisService` | `analyze(ticker)` → `InstrumentAnalysis` |
| `ma.screening` | `ScreeningService` | `scan(tickers)` → `ScreeningResult` |
| `ma.entry` | `EntryService` | `confirm(ticker, trigger)` → `EntryConfirmation` |
| `ma.strategy` | `StrategyService` | `select(ticker, regime, technicals)` → `StrategyParameters` |
| `ma.exit` | `ExitService` | `plan(ticker, ...)` → `ExitPlan` |
| `ma.quotes` | `OptionQuoteService` | `get_chain(ticker)` → `QuoteSnapshot` |
| `ma.adjustment` | `AdjustmentService` | `analyze(trade_spec, ...)` → `AdjustmentAnalysis` |
| `ma.intraday` | `IntradayService` | `monitor(ticker)` → `IntradayMonitorResult` |
| `ma.plan` | `TradingPlanService` | `generate()` → `DailyTradingPlan` |
| `ma.universe` | `UniverseService` | `scan(filter)` → `UniverseScanResult` |

---

## 6. Option Strategies

### Setups (Price-Based)

| Setup | File | Regime Fit | Description |
|-------|------|-----------|-------------|
| Breakout | `setups/breakout.py` | R3 | VCP patterns, Bollinger squeeze, pivot breakouts |
| Momentum | `setups/momentum.py` | R3 | MACD, RSI, MA alignment, structural patterns |
| Mean Reversion | `setups/mean_reversion.py` | R1/R2 | RSI extremes, Bollinger band touches |
| ORB | `setups/orb.py` | R1/R2/R3 | Opening Range Breakout — requires intraday ORBData |

### Option Plays (Structures)

| Strategy | File | Regime Fit | When to Use | Hard Stops |
|----------|------|-----------|-------------|-----------|
| Iron Condor | `option_plays/iron_condor.py` | R1 ideal, R2 acceptable | Neutral range-bound, collect premium on both sides | R4 (trending high vol) |
| Iron Butterfly | `option_plays/iron_butterfly.py` | R2 ideal | ATM straddle + wings — high IV + mean-reverting | R3/R4 |
| Calendar | `option_plays/calendar.py` | R1/R2 ideal | Front vs back month IV differential — time spread | R3/R4 (trending) |
| Diagonal | `option_plays/diagonal.py` | R3 ideal | Calendar with different strikes — mild trend plays | R4, high IV |
| Ratio Spread | `option_plays/ratio_spread.py` | R1 ideal | Buy 1 ATM, sell 2 OTM — caution: naked leg exposure | R4, earnings |
| Zero DTE | `option_plays/zero_dte.py` | R1/R2/R3 | Same-day expiration with ORB integration | R4 (no_trade verdict) |
| LEAP | `option_plays/leap.py` | R3 fundamental | Long-dated calls on strong fundamentals | R2/R4 |
| Earnings | `option_plays/earnings.py` | Pre-earnings | IV expansion plays around events | After event (IV crush) |

### Zero DTE Strategies

The zero_dte assessor auto-selects among these sub-strategies based on ORB data and regime:

| ZeroDTE Strategy | Trigger | Structure |
|-----------------|---------|-----------|
| `IRON_CONDOR` | R1/R2, normal ORB range | Short strikes at ORB range edges |
| `IRON_MAN` | Narrow ORB range (<0.5% or <30% ATR) | BTO inner near ORB edges, STO outer wings |
| `CREDIT_SPREAD` | R3 directional signal | Short strike near ORB level |
| `DIRECTIONAL_SPREAD` | Strong ORB breakout | ORB T1/T2 extension levels in rationale |
| `STRADDLE_STRANGLE` | Elevated vol, unclear direction | OTM offset based on ORB range width |
| `NO_TRADE` | R4 | Hard stop — do not trade |

### Entry Time Windows (on every TradeSpec)

| Horizon | Window |
|---------|--------|
| 0DTE | 09:45–14:00 ET |
| Income (weekly/monthly) | 10:00–15:00 ET |

---

## 7. TradeSpec Standard

`TradeSpec` is the machine-readable contract between MA and eTrading. Every assessor outputs a `trade_spec: TradeSpec | None`.

### Key Fields

| Field | Type | Description |
|-------|------|-------------|
| `ticker` | `str` | Underlying symbol |
| `legs` | `list[LegSpec]` | Option legs with action, strike, expiry |
| `underlying_price` | `float` | Price at time of assessment |
| `structure_type` | `StructureType` | `iron_condor`, `credit_spread`, `calendar`, etc. |
| `order_side` | `OrderSide` | `"credit"` or `"debit"` |
| `target_dte` | `int` | Primary DTE target (e.g., 35) |
| `target_expiration` | `date` | Best matching real expiration |
| `wing_width_points` | `float \| None` | IC/IFly: distance between short and long strike |
| `profit_target_pct` | `float \| None` | Close at X% of max profit (0.50 = 50%) |
| `stop_loss_pct` | `float \| None` | Credit: X× credit received; Debit: X fraction loss |
| `exit_dte` | `int \| None` | Close when DTE drops to this |
| `max_entry_price` | `float \| None` | Do not chase beyond this price |
| `entry_window_start` | `time \| None` | Earliest time to submit (e.g., 09:45 ET) |
| `entry_window_end` | `time \| None` | Latest time to submit (e.g., 14:00 ET) |
| `max_profit_desc` | `str \| None` | Human-readable: "Credit received" |
| `max_loss_desc` | `str \| None` | Human-readable: "Wing width - credit" |
| `exit_notes` | `list[str]` | Structure-specific guidance |
| `currency` | `str` | Default "USD" |
| `lot_size` | `int` | 100 for US equities, 10 for mini options |
| `settlement` | `str \| None` | `"cash"` or `"physical"` (from MarketRegistry) |
| `exercise_style` | `str \| None` | `"european"` or `"american"` |

### LegSpec Fields

| Field | Type | Description |
|-------|------|-------------|
| `role` | `str` | `"short_put"`, `"long_call"`, `"short_straddle"`, etc. |
| `action` | `LegAction` | `BTO` (buy to open) or `STO` (sell to open) |
| `quantity` | `int` | Default 1; ratio spreads use 2 for the short leg |
| `option_type` | `str` | `"call"` or `"put"` |
| `strike` | `float` | Strike price (snapped to tick) |
| `expiration` | `date` | Option expiration date |
| `days_to_expiry` | `int` | DTE at time of assessment |

### Computed Properties

| Property | Example Output |
|----------|---------------|
| `leg.short_code` | `"STO 1x 580P 3/27/26"` |
| `spec.leg_codes` | `["STO 1x SPY P580 3/27/26", ...]` |
| `spec.order_data` | Machine-readable dicts with `instrument_type: "EQUITY_OPTION"` |
| `spec.dxlink_symbols` | `[".SPY260327P580", ...]` |
| `spec.strategy_symbol` | `"IC"`, `"CS"`, `"DS"`, `"CAL"`, `"IFly"`, `"RS"`, etc. |
| `spec.strategy_badge` | `"IC neutral · defined"` |
| `spec.exit_summary` | `"TP 50% \| SL 2x credit \| close ≤21 DTE"` |

### Default Exit Rules (Standard Income Trades)

| Rule | Value |
|------|-------|
| Profit target | 50% of max profit (`profit_target_pct=0.50`) |
| Stop loss (credit) | 2× credit received (`stop_loss_pct=2.0`) |
| Stop loss (debit) | 50% of debit paid (`stop_loss_pct=0.50`) |
| Time exit | Close at ≤21 DTE (`exit_dte=21`) |

### StructureType Values

`iron_condor`, `iron_man`, `iron_butterfly`, `credit_spread`, `debit_spread`, `calendar`, `diagonal`, `ratio_spread`, `straddle`, `strangle`, `double_calendar`, `long_option`, `pmcc`, `equity_long`, `equity_short`, `futures_long`, `futures_short`

### Position Sizing

`TradeSpec.position_size(capital, risk_pct=0.02, max_contracts=50)` computes contracts based on:
1. `wing_width_points * lot_size` (defined-risk structures)
2. Parsed dollar value from `max_risk_per_spread`
3. Fallback: `max_entry_price * lot_size`

---

## 8. Validation Framework

The validation framework (`market_analyzer.validation`) runs pure checks against a `TradeSpec`. No broker required.

### Models

| Model | Description |
|-------|-------------|
| `Severity` | `PASS`, `WARN`, `FAIL` |
| `Suite` | `DAILY`, `ADVERSARIAL`, `FULL` |
| `CheckResult` | `name`, `severity`, `message`, `detail`, `value`, `threshold` |
| `ValidationReport` | `checks`, `passed`, `warnings`, `failures`, `is_ready`, `summary` |

`is_ready = True` if `failures == 0`.

### Daily Suite (7 Checks)

`run_daily_checks(ticker, trade_spec, entry_credit, regime_id, atr_pct, current_price, avg_bid_ask_spread_pct, dte, rsi, ...)`

| Check | PASS Threshold | WARN | FAIL |
|-------|---------------|------|------|
| `commission_drag` | Drag < 10% of credit | 10–25% | ≥25% or net credit ≤0 |
| `fill_quality` | Bid-ask spread ≤1.5% | 1.5–3% | >3% |
| `margin_efficiency` | Annualized ROC ≥15% | 10–15% | <10% |
| `pop_gate` | POP ≥65% | — | POP <65% |
| `ev_positive` | EV > 0 | — | EV ≤0 |
| `entry_quality` | IV rank, DTE, RSI, regime all confirmed | Partial | Regime mismatch |
| `exit_discipline` | TradeSpec has profit target + stop loss + exit DTE | Missing some | Missing all |

Commission assumption: $0.65 per leg per direction (TastyTrade rate), round-trip = `legs × 2 × $0.65`.

### Adversarial Suite (3 Checks)

`run_adversarial_checks(ticker, trade_spec, entry_credit, atr_pct, ...)`

| Check | PASS | WARN | FAIL |
|-------|------|------|------|
| `gamma_stress` | Risk/reward ≤5:1 at 2σ move | 5–10:1 | >10:1 |
| `vega_shock` | Long-vega structure (benefits from +30% IV) | Short-vega: <50% credit at risk | Short-vega: ≥50% credit at risk |
| `breakeven_spread` | Edge survives to >2% bid-ask spread | 1–2% break-even spread | Break-even spread ≤1% |

**Long-vega structures** (benefit from IV spikes): calendar, double_calendar, diagonal, debit_spread, long_option, iron_man, pmcc.

---

## 9. Entry-Level Intelligence

Six pure functions in `features/entry_levels.py`. No broker required for most; vol surface needed for skew-optimal strikes.

| Function | Description |
|----------|-------------|
| `check_strike_proximity(trade_spec, levels)` → `StrikeProximityResult` | Gates entry when short strikes are within 0.5 ATR of key S/R levels; flags each leg independently |
| `get_skew_optimal_strikes(ticker, vol_surface, regime_id)` → `dict` | Uses skew slope to shift put/call strikes for better premium (R1/R2) or directional bias (R3) |
| `compute_entry_level_score(trade_spec, technicals, levels, regime_id)` → `EntryLevelScore` | Composite 0–1 score: IV rank quality + DTE optimality + strike proximity + regime alignment |
| `compute_limit_order_price(trade_spec, quotes, slippage_pct)` → `float \| None` | Chase-limit between mid and bid (credit) or mid and ask (debit); requires broker quotes |
| `detect_pullback_alert(ticker, technicals, regime_id)` → `PullbackAlert \| None` | Short-term pullback within R3 trend; `strength` (0–1), `suggested_action` |
| `validate_entry_conditions(trade_spec, technicals, levels, vol_surface, regime_id)` → `EntryValidation` | Orchestrates all checks; wired as validation check #10 |

Wired into: IC strike selection (skew shift), `run_daily_checks()` (check #10: `entry_conditions`).

**CLI:** `entry_analysis TICKER` — full entry-level score with sub-component breakdown

---

## 10. Exit Intelligence

Pure functions in `features/exit_intelligence.py`. All accept `trade_spec` + `regime_id`.

| Function | Description |
|----------|-------------|
| `compute_regime_contingent_stops(trade_spec, regime_id, atr_pct)` → `RegimeStop` | Stop trigger scaled by regime: R1=wide (3× ATR), R2=normal (2×), R3=tighter (1.5×), R4=tight (1×) |
| `compute_trailing_profit_target(trade_spec, current_pnl_pct, regime_id)` → `TrailingProfitTarget` | Locks in at 40% then trails 25% below high-water mark; `lock_level`, `trail_trigger`, `current_target` |
| `compute_theta_decay_curve(trade_spec, days_elapsed)` → `ThetaDecayCurve` | Expected P&L trajectory from entry to expiry using empirical theta decay; compare actual vs expected |
| `recommend_strategy_switch(trade_spec, current_regime, new_regime)` → `StrategySwitchRecommendation` | On regime change: IC→R3 = CONVERT_TO_DIAGONAL, IC→R1 from R2 = CONVERT_TO_CALENDAR, any→R4 = CLOSE_FULL |

**CLI:** `exit_intelligence TICKER` — shows all exit intelligence for a representative position

---

## 11. Position Sizing

Unified entry point in `features/position_sizing.py`:

```python
result = compute_position_size(
    trade_spec, capital, risk_pct,
    regime_id=regime_id,
    portfolio_positions=open_positions
)
# result.contracts, result.capital_at_risk, result.rationale
```

### Kelly Criterion

`compute_kelly_fraction(pop, profit, loss)` → raw Kelly fraction. Capped at 0.25 (quarter-Kelly default for options).

### Correlated Kelly

`compute_correlated_kelly(trade_spec, portfolio_positions, regime_id)` → `float`

Reduces Kelly fraction when adding a trade correlated with existing positions:
- Same sector or similar delta direction → 0.5–0.7× Kelly reduction
- Uncorrelated → full Kelly

### Margin-Regime Interaction

`compute_margin_regime_interaction(trade_spec, account_balance, regime_id)` → `float` (size multiplier)

| Regime | Multiplier | Rationale |
|--------|-----------|-----------|
| R1 | 1.2× | High-probability environment, allow slightly larger sizing |
| R2 | 1.0× | Normal |
| R3 | 0.8× | Directional risk — reduce income positions |
| R4 | 0.5× | High-vol trending — maximum caution |

**CLI:** `kelly TICKER` — shows Kelly fraction, correlated adjustment, regime multiplier, final contracts

---

## 12. Decision Audit Framework

`audit_decision(trade_spec, regime_result, validation_report, sizing_result, entry_validation)` → `DecisionAudit`

4-level scoring in `features/decision_audit.py`:

| Level | What | Key Metrics |
|-------|------|-------------|
| `leg_scores` | Each leg individually | Strike vs spot distance, delta quality, premium vs spread |
| `trade_scores` | Full structure | IV rank alignment, DTE fit, regime match, exit params completeness |
| `portfolio_scores` | Portfolio impact | Concentration (same ticker/sector), correlation, BP utilization |
| `risk_scores` | Risk budget | Expected loss vs budget, gamma exposure, overnight flag |

Each level produces a score 0–1. `DecisionAudit.overall_score` = weighted average.

`DecisionAudit.summary` → `"APPROVED: IC SPY R1 | score 0.82 | 4/4 levels pass"`
`DecisionAudit.blocking_issues` → list of strings for any level scoring < 0.5

**CLI:** `audit TICKER` — runs 4-level audit on representative trade, shows per-level breakdown

---

## 13. Crash Sentinel

`assess_crash_sentinel(tickers, technicals_map, macro_context, vol_surface_map)` → `SentinelReport`

9 indicators assessed:

| Indicator | Critical Threshold |
|-----------|-------------------|
| VIX level | >30 |
| VIX spike (1-day) | >5 points |
| Credit spread widening | HYG/TLT ratio drops >2% in 2 days |
| Equity breadth collapse | >70% of tickers below 20-day MA |
| Put/call ratio | >1.5 |
| Term structure inversion | VIX front > back (contango → backwardation flip) |
| Cross-asset correlation spike | SPY/GLD/TLT all moving same direction |
| Dollar spike | DXY +1.5% in 1 day |
| Bond yield crash | TNX -20bps in 1 day |

Signal levels:

| Signal | Trigger | Action |
|--------|---------|--------|
| `CLEAR` (GREEN) | 0–1 soft indicators | Normal trading |
| `WATCH` (YELLOW) | 2 soft indicators | Monitor, tighten stops |
| `CAUTION` (ORANGE) | 3+ soft or 1 critical | Reduce size, avoid new income |
| `ALERT` (RED) | Critical cluster (VIX + credit + breadth) | Close short premium, hedge |
| `PANIC` (BLUE) | Extreme multi-factor spike | Close all short premium immediately |

`SentinelReport.dominant_signal` — single indicator driving the alert
`SentinelReport.recommended_actions` — concrete steps list

**CLI:** `sentinel [TICKERS]` — signal color, dominant driver, recommended actions

---

## 18. eTrading Integration

### Three Critical Rules

1. **`rank()` output is NOT safe to execute directly.** It ranks on market merit only — no position awareness. eTrading MUST call `filter_trades_with_portfolio()` and `evaluate_trade_gates()` before execution.

2. **Every trade must pass all gates before broker submission:**
   - Regime filter — right strategy for current market state
   - EV gate — positive expected value, quality score above threshold
   - Risk gate — position fits account size, portfolio risk within limits
   - Entry window — correct time of day, no macro events, not earnings blackout
   - Execution quality — spread is tight, OI is sufficient, fill price is realistic

3. **MA is stateless.** eTrading owns position state, P&L history, and session management.

### Broker Modes

| Mode | How | When |
|------|-----|------|
| Standalone | `connect_tastytrade(is_paper=True)` returns `(MarketDataProvider, MarketMetricsProvider, AccountProvider, WatchlistProvider)` | Library manages credentials |
| Embedded | `connect_from_sessions(sdk_session, data_session)` | eTrading passes pre-authenticated sessions |

```python
# Standalone
from market_analyzer.broker.tastytrade import connect_tastytrade
md, mm, acct, wl = connect_tastytrade(is_paper=True)
ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm)

# Embedded (eTrading/SaaS)
from market_analyzer.broker.tastytrade import connect_from_sessions
md, mm, acct, wl = connect_from_sessions(sdk_session, data_session)
```

### Primary eTrading APIs

All from `market_analyzer.trade_lifecycle`:

| Function | Description |
|----------|-------------|
| `filter_trades_with_portfolio(trades, positions, limits)` | Remove trades that would violate portfolio risk limits |
| `evaluate_trade_gates(trade_spec, ...)` → `TradeGateReport` | BLOCK/SCALE/WARN classification |
| `compute_income_yield(trade_spec, credit, contracts)` → `IncomeYield` | Annualized ROC calculation |
| `compute_breakevens(trade_spec, credit)` → `Breakevens` | Upper/lower breakeven prices |
| `estimate_pop(trade_spec, regime_id, atr_pct, ...)` → `POPEstimate` | Regime-adjusted ATR-based POP |
| `check_income_entry(trade_spec, iv_rank, dte, rsi, regime_id)` → `IncomeEntryCheck` | Entry quality gates |
| `filter_trades_by_account(trades, buying_power)` → `FilteredTrades` | Size filter for account |
| `align_strikes_to_levels(trade_spec, levels)` → `AlignedStrikes` | Snap strikes to key levels |
| `aggregate_greeks(legs, quotes)` → `AggregatedGreeks` | Portfolio Greeks for a trade |
| `monitor_exit_conditions(trade_spec, current_price, ...)` → `ExitMonitorResult` | Check TP/SL/DTE triggers |
| `check_trade_health(trade_spec, regime_id, ...)` → `TradeHealthCheck` | Holistic position health |
| `get_adjustment_recommendation(trade_spec, regime_id, ...)` → `AdjustmentAnalysis` | What to do with tested position |
| `assess_overnight_risk(trade_spec, regime_id, ...)` → `OvernightRisk` | After 15:00 ET — hold or close |

### TradeSpec Factory (from `market_analyzer.trade_spec_factory`)

```python
from market_analyzer import build_iron_condor, build_credit_spread, build_debit_spread, build_calendar
from market_analyzer import from_dxlink_symbols, to_dxlink_symbols, parse_dxlink_symbol
```

### POP Methodology

POP uses **regime-adjusted ATR** (not Black-Scholes):

| Regime | ATR Factor |
|--------|-----------|
| R1 (Low-Vol MR) | 0.40 |
| R2 (High-Vol MR) | 0.70 |
| R3 (Low-Vol Trend) | 1.10 |
| R4 (High-Vol Trend) | 1.50 |

Gap self-report: `"POP estimate uses regime-adjusted ATR — no skew data available (broker not connected)"`

### What MA Never Does

- No authentication or token management
- No tenant isolation
- No position storage or P&L history
- No fill tracking
- No order submission

---

## 19. Data Sources

### yfinance

Used for: historical OHLCV, options chain structure (strikes/expirations), fundamentals.

**Not used for:** option prices, Greeks, IV. Any price from yfinance must be explicitly labeled as such.

### DXLink (TastyTrade Broker)

The only path for live data:
- Real-time option quotes (bid/ask/mid)
- Greeks (delta, gamma, theta, vega)
- Implied volatility
- Intraday candles (5m bars)
- Underlying mid price

```python
from tastytrade.streamer import DXLinkStreamer
from tastytrade.dxfeed import Greeks as DXGreeks, Quote as DXQuote
```

DXLink symbol format: `.SPY260327P580` (dot-prefixed, compact).
OCC symbol format: `SPY   260327P00580000` (padded, 6-char ticker).

### Broker ABC Layer

Five ABCs in `broker/base.py`:
- `BrokerSession` — authentication
- `MarketDataProvider` — quotes, Greeks, intraday candles
- `MarketMetricsProvider` — IV rank, IV percentile, beta, liquidity
- `AccountProvider` — balance, buying power
- `WatchlistProvider` — private and public watchlists from broker

**6 supported broker implementations** (as of 2026-03-21):

| Broker | Module | Market | Status |
|--------|--------|--------|--------|
| TastyTrade | `broker/tastytrade/` | US | STABLE |
| Zerodha | `broker/zerodha/` | India | COMPLETE |
| Dhan | `broker/dhan/` | India | COMPLETE |
| Alpaca | `broker/alpaca/` | US | COMPLETE |
| IBKR | `broker/ibkr/` | US/Global | COMPLETE |
| Schwab | `broker/schwab/` | US | COMPLETE |

**BYOD adapters** in `broker/adapters/` — for users without supported brokers: CSV, dict, IBKR skeleton, Schwab skeleton. All implement `MarketDataProvider` ABC.

### Ticker Aliases

`_YFINANCE_ALIASES` in `data/providers/yfinance.py` translates user-facing tickers to yfinance symbols:
`SPX→^GSPC`, `NDX→^NDX`, `VIX→^VIX`, `RUT→^RUT`, `TNX→^TNX`, etc.
Cache stores under user-facing name; provider fetches via yfinance name.

### Cache

Parquet cache with staleness checks. "Cache before fetch, but never serve stale data silently." Options chain snapshots: 4-hour staleness limit.

---

## 23. Desk Management / Capital Allocation

Structured capital deployment via 6 pure functions. Hierarchy: account → asset class → risk type → desks.

**Default 4-desk structure:**

| Desk | DTE Range | Strategies | Default Allocation |
|------|-----------|------------|-------------------|
| `desk_0dte` | 0 DTE | 0DTE IC, Iron Man, credit spread | 20% |
| `desk_income` | 21–45 DTE | IC, calendar, iron butterfly | 50% |
| `desk_directional` | 14–45 DTE | Diagonal, credit/debit spread | 20% |
| `desk_hedge` | Any | Protective put, collar | 10% |

**APIs in `capital_allocation.py`:**

| Function | Returns | Description |
|----------|---------|-------------|
| `recommend_desk_structure(balance, style)` | `DeskRecommendation` | Initial desk setup; style = "income_first" / "balanced" / "aggressive" |
| `suggest_desk_for_trade(trade_spec, desks, existing)` | `dict` | Best desk match: DTE fit (50pts), strategy (30pts), capacity (15pts), correlation (5pts) |
| `compute_desk_risk_limits(desk_key, regime_id, drawdown_pct)` | `DeskRiskLimits` | Regime-adjusted position/size limits; R4 = 50% of normal |
| `compute_instrument_risk(ticker, type, value, regime_id)` | `InstrumentRisk` | max_loss, expected_loss_1d, margin_required, risk_category |
| `evaluate_desk_health(desk_key, closed_trades)` | `DeskHealth` | Win rate, Sharpe, avg hold, strategy efficiency |
| `rebalance_desks(desks, balance, regime_id)` | `RebalanceReport` | Drift detection + reallocation when >5% off target |

**Pipeline position:** `rank → suggest_desk_for_trade → filter_trades_with_portfolio → compute_desk_risk_limits → entry`

**CLI:** `desk [DESK_KEY]` — shows structure, capital, limits, health.

---

## 24. Demo Portfolio System

Paper-trading simulation without a broker connection. Enables forward testing with the full MA analysis stack.

**CLI flags:**
- `analyzer-cli --demo` — starts with a virtual $50K portfolio (pre-seeded positions for realistic testing)
- `analyzer-cli --setup` — first-time onboarding wizard; guides broker connection or demo mode setup

**Demo-mode CLI commands:**

| Command | Description |
|---------|-------------|
| `portfolio` | Shows demo positions, P&L, Greeks (simulated from yfinance + regime) |
| `trade TICKER STRUCTURE` | Executes a demo trade — records in memory, generates TradeSpec |
| `close_trade TRADE_ID` | Closes a demo position; records `TradeOutcome` for ML feedback |

Demo trades flow through the full validation stack: entry gates, risk checks, Kelly sizing. Closed outcomes can seed `calibrate_weights()` before committing real capital.

---

## 25. Assignment Workflow

**American vs European options:**

| Market | Style | Assignment Risk |
|--------|-------|----------------|
| US (SPY, QQQ, individual equities) | American | Can be assigned early; short calls at risk near ex-dividend dates |
| US index cash-settled (SPX, VIX) | European | No early assignment; settled to cash at expiry |
| India (NIFTY, BANKNIFTY, NSE equity) | European | No early assignment; cash-settled |

`TradeSpec.assignment_style: str` — `"american"` or `"european"` per instrument. Set by `MarketRegistry`.

**`check_assignment_risk(trade_spec, days_to_expiry, stock_yield)` → `AssignmentRisk`:**
- Flags short calls on dividend-paying US stocks when ex-div date is within DTE and extrinsic value < dividend amount
- Returns `risk_level: "none" | "low" | "medium" | "high"`, `rationale: str`

**CSP/Wheel workflow:**
- `decide_wheel_action(ticker, cost_basis, regime_id, current_price)` → `WheelDecision`
- `assess_covered_call(ticker, cost_basis, regime_id)` → `CoveredCallAssessment` (strike, DTE, yield)
- Full state machine: CSP → assigned → covered call → called away → restart

**CLI:** `wheel TICKER` — full wheel state; `csp TICKER` — standalone CSP analysis.

---

## 26. BYOD Adapters

For users without supported brokers. All implement `MarketDataProvider` ABC.

| Adapter | Module | Usage |
|---------|--------|-------|
| CSV | `broker/adapters/csv_adapter.py` | `--data-file quotes.csv`; maps columns to `OptionQuote` |
| Dict | `broker/adapters/dict_adapter.py` | Pass Python dicts directly; for API callers |
| IBKR skeleton | `broker/adapters/ibkr_skeleton.py` | TWS API wiring placeholder |
| Schwab skeleton | `broker/adapters/schwab_skeleton.py` | Schwab API wiring placeholder |

CSV format: `ticker, expiration, strike, option_type, bid, ask, delta, gamma, theta, vega, iv`

---

## 20. CLI Commands

Entry points:
```bash
analyzer-cli                    # Interactive REPL (primary)
analyzer-cli --broker --paper   # With broker connection
analyzer-explore                # Regime exploration
analyzer-plot                   # Regime charts
```

### Core Analysis (12 commands)

| Command | Description |
|---------|-------------|
| `context` | Market environment assessment (black swan, macro, cross-market) |
| `analyze` | Full instrument analysis for a ticker |
| `screen` | Scan tickers for setups (accepts `--watchlist NAME`) |
| `entry` | Entry confirmation for a ticker and trigger type |
| `strategy` | Strategy selection given regime and technicals |
| `exit_plan` | Exit plan for an open position |
| `regime` | Regime detection (accepts `--watchlist NAME`) |
| `technicals` | Technical snapshot for a ticker |
| `levels` | Key price levels (support, resistance, pivots) |
| `macro` | Macro calendar and upcoming events |
| `stress` | Portfolio stress test scenarios |
| `vol` | Volatility surface for a ticker |

### Trading (14 commands)

| Command | Description |
|---------|-------------|
| `rank` | Rank tickers by trade quality (`--watchlist NAME`, `--account AMOUNT`) |
| `plan` | Daily trading plan (`plan [TICKERS] [--date YYYY-MM-DD]`) |
| `opportunity` | Option play assessment for a ticker |
| `setup` | Price-based setup assessment (`breakout`, `momentum`, `mr`, `orb`, `all`) |
| `adjust` | Trade adjustment recommendations for an open position |
| `quotes` | Option chain with bid/ask/Greeks/metrics (`quotes TICKER [EXPIRATION]`) |
| `balance` | Account balance and buying power |
| `broker` | Broker connection status |
| `validate` | Daily pre-trade profitability gate (10 daily + 3 adversarial checks) |
| `entry_analysis` | Entry-level intelligence: strike proximity, skew-optimal strikes, limit price, pullback alert |
| `kelly` | Kelly criterion position sizing (correlated Kelly + margin-regime interaction) |
| `optimal_dte` | DTE optimizer from vol surface term structure |
| `exit_intelligence` | Regime-contingent stops, trailing profit targets, theta decay curve |
| `audit` | 4-level decision audit (leg / trade / portfolio / risk scoring) |
| `sentinel` | Crash sentinel: GREEN/YELLOW/ORANGE/RED/BLUE market condition signal |

### Trade Lifecycle (8 commands)

| Command | Description |
|---------|-------------|
| `yield` | Income yield calculation for a trade |
| `pop` | Probability of profit estimate |
| `income_entry` | Income entry quality gate check |
| `parse` | Parse a TradeSpec from DXLink symbols |
| `monitor` | Exit condition monitoring for a position |
| `health` | Trade health check |
| `greeks` | Aggregate Greeks for a trade |
| `size` | Position sizing given capital and risk budget |

### Watchlist & Universe (2 commands)

| Command | Description |
|---------|-------------|
| `watchlist` | List/show broker watchlists |
| `universe` | Scan and filter broker universe by preset |

### System (2 commands)

| Command | Description |
|---------|-------------|
| `quit` | Exit the REPL |
| `exit` | Exit the REPL |

**Total: 80+ commands** (as of 2026-03-21; includes desk, demo portfolio, CSP/wheel, interest_risk, and other new commands).

### Universe Scanner Presets

| Preset | Filter |
|--------|--------|
| `income` | ETF, IV rank 30–80, liquidity score ≥4 |
| `directional` | ETF + equity, beta 0.8–2.0 |
| `high_vol` | IV rank ≥60 |
| `broad` | Liquidity score ≥2, max 100 results |

---

## 14. Data Trust Framework

Every MA output carries a 2-dimensional trust assessment: **data quality** (how accurate and fresh?) and **context quality** (were all inputs provided?).

### Dimension 1: Data Quality

| Source | Trust Level | Score |
|--------|------------|-------|
| Broker live (DXLink) | HIGH | +0.30 |
| yfinance OHLCV | BASE | 0.30 base |
| Estimated/heuristic | LOW | +0.03 |
| None | UNRELIABLE | 0 |

### Dimension 2: Context Quality — Calculation Modes

| Mode | Expected Inputs | Missing Context | Default? |
|------|-----------------|-----------------|----------|
| **`full`** | regime, technicals, vol_surface, levels, IV rank, entry credit, portfolio exposure, correlation, earnings, ticker type | Sets `is_actionable=False` | YES |
| **`standalone`** | regime, technicals, entry credit (minimum) | OK — expected for CLI/backtest | No |

**Default = `full` mode:** All calculations are portfolio-aware BY DEFAULT. eTrading does not need to change function signatures. Missing critical context automatically demotes `is_actionable` to False.

### Trust Report Output

```
TRUST: 85% HIGH
  Data:    90% HIGH (broker_live)
  Context: 85% HIGH (full mode, all inputs provided)
  >> Actionable: YES
```

vs

```
TRUST: 35% LOW
  Data:    60% MEDIUM (yfinance, no broker)
  Context: 35% LOW — MISSING: entry_credit, iv_rank, levels
  >> Actionable: NO — connect broker and pass full context
```

### Fitness for Purpose

`TrustReport` includes two computed fields that tell callers what the output is suitable for:

| Overall Trust | Fit For |
|---------------|---------|
| ≥ 0.80 | live_execution (all purposes) |
| ≥ 0.70 | position_monitoring, risk_assessment |
| ≥ 0.60 | paper_trading |
| ≥ 0.50 | alerting, calibration |
| ≥ 0.30 | screening |
| ≥ 0.20 | research |
| always | education, journaling |

- `report.fit_for` — `list[str]` of applicable `FitnessCategory` values (serializes via `model_dump()`)
- `report.fit_for_summary` — one-line human-readable string: `"Fit for: screening, research. NOT fit for: live_execution, position_monitoring, risk_assessment"`

eTrading should gate execution on `FitnessCategory.LIVE_EXECUTION in report.fit_for`.

### Models & Functions

- `CalculationMode`, `FitnessCategory` — enums
- `DataTrust`, `TrustReport` — from `models/transparency.py`
- `compute_data_trust()`, `compute_context_quality()`, `compute_trust_report()` — from `features/trust.py`

---

## 15. Monitoring Action with Closing TradeSpec

`MonitoringAction` extended to produce executable `closing_trade_spec: TradeSpec | None`:

### When Closing Spec Is Generated

1. **TP Hit** — `closing_trade_spec` = STO/BTC legs to close profitable position
2. **SL Hit** — `closing_trade_spec` = STO/BTC legs to cut loss
3. **DTE Expired** — `closing_trade_spec` = legs to close expired position
4. **Urgency Escalation** (after 15:00 ET for 0DTE, after 15:30 for others) — force-close spec

### Contract

- `monitor_exit_conditions()` → `ExitMonitorResult` with `exit_signal` and `closing_trade_spec`
- `check_trade_health()` → `TradeHealthCheck` with urgency and `closing_spec`
- eTrading directly submits closing spec without re-computing

**CLI:** `monitor SPEC` — shows exit trigger and closing legs ready to submit.

---

## 16. Position Stress Monitoring

Service in `service/stress_monitoring.py`. Stresses open positions on 13 scenarios:

| Scenario | Trigger |
|----------|---------|
| -1%, -3%, -5%, -10% moves | Price scenarios |
| VIX +10, +20, +30 points | Vol spikes |
| Flash crash (-20% in 1 day) | Tail risk |
| Black Monday scenario | Historical stress |
| COVID crash, India crash | Systemic shocks |
| Fed surprise (rate hike/cut 75bps) | Macro shock |

### Output

`StressResult` per position per scenario:
- `estimated_loss_pct`, `max_loss_exceeded`
- `urgency` flag (NORMAL / ESCALATE / FORCE_CLOSE)
- ATR-based estimates (no broker Greeks required)

**CLI:** `stress_test` — runs on portfolio, shows urgency escalation guidance.

---

## 17. Setup

```bash
# Python 3.12 required (hmmlearn has no 3.14 wheels)
py -3.12 -m venv .venv_312
.venv_312/Scripts/pip install -e ".[dev]"

# Run all tests
.venv_312/Scripts/python -m pytest tests/ -v

# Skip integration (network) tests
.venv_312/Scripts/python -m pytest -m "not integration" -v
```

### Credentials

TastyTrade credentials via `tastytrade_broker.yaml` (YAML format with `${ENV_VAR}` resolution). Template: `tastytrade_broker.yaml.template`. No API keys in code.

### Optional dependency group

```bash
pip install -e ".[tastytrade]"   # Adds tastytrade>=9.0 for broker integration
```

---

## 21. Systematic Trading Readiness

MA's end state: enable a fully systematic trading system where no human decisions are needed during a trading day. eTrading executes; MA decides.

### What's Complete

| Feature | Status |
|---------|--------|
| Deterministic adjustment decisions | Done — single action per situation, no menus |
| Execution quality validation | Done — spread, OI, volume checks on TradeSpec |
| Entry time windows on every TradeSpec | Done — 09:45–14:00 for 0DTE, 10:00–15:00 for income |
| Time-of-day urgency escalation | Done — 0DTE force-close after 15:00, tested escalation after 15:30 |
| Overnight risk assessment | Done — auto-checks in health check after 15:00 |
| Auto-select screening | Done — min_score filtering, top_n limiting |
| Performance feedback loop | Done — `TradeOutcome → calibrate_weights()` pure functions |
| Debug/commentary mode | Done — on 4 services, threading through ranking to assessors |
| Data gap self-identification | Done — in 8 assessors (vol_surface, broker, ORB, fundamentals, earnings) |
| Validation framework | Done — 10-check daily suite + 3 adversarial checks; pure functions, no broker required |
| Entry-level intelligence | Done — 6 functions: proximity gate, skew strikes, limit price, pullback, score, validation |
| Exit intelligence | Done — regime-contingent stops, trailing targets, theta decay, strategy switching |
| Position sizing (Kelly + correlation) | Done — correlated Kelly + margin-regime interaction + unified `compute_position_size()` |
| DTE optimization | Done — `compute_optimal_dte()` from vol surface term structure |
| Decision audit framework | Done — 4-level audit: leg/trade/portfolio/risk scoring |
| Crash sentinel | Done — 9-indicator early-warning; GREEN/YELLOW/ORANGE/RED/BLUE signals |

### What's Next

- **Portfolio-level daily report** — one command for all positions with health, exit conditions, overnight risk
- **Intraday re-evaluation** — re-check blocked trades at 2 PM (IV/regime conditions change intraday)
- **Alternative structure suggestion** — if IC scores < 0.5, auto-suggest calendar/credit spread
- **Credit estimation confidence interval** — `(low, mid, high)` range from bid-ask spread width
- **Richer setup signals**: breakout/momentum/mean_reversion assessors use basic indicators; need multi-factor scoring
- **Richer option play logic**: leap/earnings assessors are thin; need deeper fundamental integration
- **ML regime validation**: track regime predictions against actual price behavior; auto-retrain HMM
- **POP calibration**: compare estimated POP against actual win rates from `TradeOutcome` data

### Pre-Trade Gate Checklist (eTrading responsibility)

A trade should only reach the broker after all 5 gates pass:

| Gate | Check |
|------|-------|
| 1. Regime filter | Right strategy for current R1/R2/R3/R4 state |
| 2. EV gate | Positive expected value, quality score above threshold |
| 3. Risk gate | Position fits account size, portfolio Greeks within limits |
| 4. Entry window | Correct time of day, no macro events, not earnings blackout |
| 5. Execution quality | Spread ≤1.5%, OI sufficient, fill price realistic |

---

## 22. Key Model Files

| File | Key Classes |
|------|-------------|
| `models/opportunity.py` | `TradeSpec`, `LegSpec`, `LegAction`, `StructureType`, `OrderSide`, `Verdict` |
| `models/ranking.py` | `RankedEntry`, `TradeRankingResult`, `ScoreBreakdown`, `StrategyType` |
| `models/trading_plan.py` | `DailyTradingPlan`, `DayVerdict`, `PlanHorizon`, `PlanTrade`, `RiskBudget` |
| `models/adjustment.py` | `AdjustmentAnalysis`, `AdjustmentOption`, `AdjustmentType`, `PositionStatus` |
| `models/quotes.py` | `OptionQuote`, `QuoteSnapshot`, `MarketMetrics`, `AccountBalance` |
| `models/regime.py` | `RegimeResult`, `RegimeID`, `RegimeExplanation`, `RegimeConfig` |
| `models/feedback.py` | `TradeOutcome`, `PerformanceReport`, `CalibrationResult`, `WeightAdjustment` |
| `models/universe.py` | `UniverseFilter`, `UniverseCandidate`, `UniverseScanResult` |
| `models/exit.py` | `RegimeStop`, `TrailingProfitTarget`, `ThetaDecayCurve`, `StrategySwitchRecommendation` |
| `models/entry.py` | `StrikeProximityResult`, `EntryLevelScore`, `PullbackAlert`, `EntryValidation`, `IVRankQuality` |
| `models/decision_audit.py` | `DecisionAudit`, `LegAudit`, `TradeAudit`, `PortfolioAudit`, `RiskAudit` |
| `models/sentinel.py` | `SentinelReport`, `SentinelSignal` (GREEN/YELLOW/ORANGE/RED/BLUE) |
| `validation/models.py` | `ValidationReport`, `CheckResult`, `Severity`, `Suite` |
| `models/transparency.py` | `CalculationMode`, `FitnessCategory`, `DataTrust`, `TrustReport`, `ContextGap`, `DegradedField`, `TrustLevel`, `DataSource` |
