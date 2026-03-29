# income-desk

**The brain behind your trading desk.**

Every trade suggestion is bespoke to your portfolio, your risk profile, your capital. This isn't a signal service — it's a personal trading intelligence system for income-first options traders.

[![PyPI](https://img.shields.io/pypi/v/income-desk.svg)](https://pypi.org/project/income-desk/)
[![Tests](https://github.com/nitinblue/income-desk/actions/workflows/test.yml/badge.svg)](https://github.com/nitinblue/income-desk/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)

```bash
pip install income-desk
income-desk --trader us       # See it in action immediately
income-desk --trader india    # India market version
```

---

## Quick Start: Workflow Harness

**New to the codebase?** The workflow harness walks you through every API in the system, step by step, with real outputs.

```bash
# Interactive — pick a market, explore each phase
python -m challenge.harness

# Run all 15 workflows non-interactively (daily stability check)
python -m challenge.harness --all --market=US
python -m challenge.harness --all --market=India

# Run a specific phase
python -m challenge.harness --phase=2 --market=US    # Scanning only
```

The harness auto-connects to your broker (TastyTrade for US, Dhan for India). If the market is closed or no credentials are available, it falls back to simulated data seamlessly.

**7 Phases, 15 Workflows:**

| Phase | What it tests | Workflows |
|-------|--------------|-----------|
| 1. Pre-Market | Is it safe to trade today? | health check, daily plan, market snapshot |
| 2. Scanning | What should I trade? | scan universe, rank opportunities |
| 3. Trade Entry | Is this trade ready? | validate, size (Kelly), price |
| 4. Monitoring | How are my positions? | monitor, adjust, overnight risk |
| 5. Portfolio Risk | What's my exposure? | Greeks aggregation, stress test |
| 6. Calendar | Any expiries today? | expiry day check |
| 7. Reporting | How did today go? | daily report |

Every workflow prints its API signature, inputs, and tabular results. See `challenge/harness.py` for the full implementation.

---

## The Trading Workflow

Trading doesn't start with placing an order. It starts with setting up your desk.

income-desk supports the complete lifecycle — from portfolio construction to AI/ML learning. Each step below shows what the library provides and what you can build on top.

---

### Step 1: Set Up Your Portfolio & Investment Capital

Define your starting capital and risk tolerance. The library models your account and recommends how to structure it.

| Library Features | Platform Ideas |
|-----------------|----------------|
| `recommend_desk_structure(capital, risk_tolerance)` | Onboarding wizard that creates portfolio on signup |
| `PortfolioAllocation` model with asset class breakdown | Dashboard showing capital allocation pie chart |
| `SimulatedAccount(nlv, cash, bp)` for demo | Paper trading mode with virtual capital |
| Account providers for 6 brokers | Auto-fetch real account balance |

```bash
income-desk --demo           # Creates $100K simulated portfolio
> desk 100000 --risk moderate
```

---

### Step 2: Set Up Your Desks — Allocate Capital & Risk Limits

Split capital across trading desks, each with its own mandate. Desks are the organizational unit — income desk, 0DTE desk, wheel desk, directional desk.

| Library Features | Platform Ideas |
|-----------------|----------------|
| Asset class allocation: Options, Stocks, Metals, Futures | Visual desk builder with drag-and-drop allocation |
| `compute_desk_risk_limits(desk, capital, regime)` | Dynamic risk limits that adjust with market conditions |
| Regime-aware allocation (R4 → +15% cash reserve) | Auto-rebalance alert when regime shifts |
| India-specific: `desk_expiry_day` for weekly expiry | Separate India desk with lot-size awareness |

```bash
> portfolio    # View all desks with capital allocation
```

---

### Step 3: Define Asset Types Per Desk

Each desk has a strategy whitelist, DTE range, and instrument type. The 0DTE desk only takes same-day expiries. The income desk only takes 21-60 DTE defined-risk structures.

| Library Features | Platform Ideas |
|-----------------|----------------|
| Per-desk strategy whitelist (IC, credit spread, calendar...) | Strategy selector dropdown per desk |
| DTE ranges per desk (0DTE desk: 0-1, income desk: 21-60) | Trade routing engine based on DTE |
| `suggest_desk_for_trade(desks, dte, strategy)` | Auto-route trades to correct desk |
| Instrument type per desk (options, equities, mixed) | Desk-level P&L tracking |

---

### Step 4: Define Risk Profile — Defined vs Undefined Risk

Choose how much of your capital can be in undefined-risk positions. This controls what structures the system will suggest.

| Library Features | Platform Ideas |
|-----------------|----------------|
| Conservative: 100% defined risk (no naked options) | Risk profile selector during onboarding |
| Moderate: 80% defined, 20% undefined | Per-desk risk type enforcement |
| Aggressive: 60% defined, 40% undefined | Warning when undefined risk allocation exceeded |
| `compute_margin_buffer(trade_spec, regime)` | Margin utilization dashboard |
| `compute_margin_analysis(trade_spec, nlv, bp)` | Cash vs margin comparison before every trade |

```bash
> margin_buffer SPY    # Margin impact preview
> margin SPY 35000     # Full margin analysis
```

---

### Step 5: Define Universe of Underlyings

Pick what you trade. Built-in presets get you started. Broker watchlists sync automatically.

| Library Features | Platform Ideas |
|-----------------|----------------|
| Built-in presets: income (12 tickers), nifty50, sector_etf | Universe manager with save/load |
| `ma.registry.get_universe(preset="income")` | Custom watchlist builder |
| Broker watchlists via WatchlistProvider | Sync from broker app |
| 85+ instruments with sector, liquidity rating | Filter by sector, options liquidity, market |

```bash
> scan_universe income
> watchlist --list          # Show broker watchlists
```

---

### Step 6: Screen the Universe

Filter your universe down to actionable candidates. Multiple screen types catch different setups.

| Library Features | Platform Ideas |
|-----------------|----------------|
| 4 screens: breakout, momentum, mean reversion, income | Multi-screen dashboard |
| `ma.screening.scan(tickers, min_score, top_n)` | Daily auto-scan with email alerts |
| Liquidity filter (ATR < 0.3% auto-removed) | Candidate pipeline with scoring |
| Correlation dedup (same-regime, same-RSI deduplicated) | Heatmap of correlated candidates |

```bash
> screen SPY QQQ IWM GLD TLT
> screen --watchlist income_etfs
```

---

### Step 7: Rank Tickers

Rank surviving candidates by composite score: regime alignment, phase, IV rank, income bias. Every score is explainable.

| Library Features | Platform Ideas |
|-----------------|----------------|
| `ma.ranking.rank(tickers)` — 11 strategies per ticker | Ranked trade table with sort/filter |
| Composite score: regime alignment + phase + income bias | Score breakdown tooltip |
| IV rank map integration | IV rank overlay on ranking |
| Data gaps tracked per entry | Data quality indicator per candidate |

```bash
> rank SPY QQQ IWM GLD TLT --debug
> rank --watchlist income_etfs --account 35000
```

---

### Step 8: Build Scenario Trades (No Checks)

Generate trade structures for top candidates. These are proposals — not yet validated against your portfolio.

| Library Features | Platform Ideas |
|-----------------|----------------|
| `assess_iron_condor(ticker, regime, tech, vol)` | Trade builder with structure selector |
| `assess_calendar()`, `assess_diagonal()`, etc. | Visual payoff diagram |
| 11 option play assessors | Side-by-side structure comparison |
| TradeSpec with legs, strikes, DTE, exit rules | Trade spec preview card |
| `select_skew_optimal_strike()` | Skew heatmap for strike selection |
| `select_optimal_dte()` from vol surface | DTE comparison chart |

```bash
> opportunity SPY
> opportunity IWM --debug    # Full commentary trace
```

---

### Step 9: Promote to What-If Trade — Full Checks

This is where income-desk's validation engine kicks in. The scenario trade gets tested against your portfolio, risk limits, and real market data.

| Library Features | Platform Ideas |
|-----------------|----------------|
| `run_daily_checks()` — 10-check profitability gate | Pre-trade compliance dashboard |
| `run_adversarial_checks()` — gamma stress, vega shock, breakeven spread | Stress test visualization |
| `audit_decision()` — 4-level scoring (leg/trade/portfolio/risk) | Decision report card UI |
| `compute_position_size()` — Kelly + correlation + margin | Position sizer with slider |
| `compute_trust_report()` — data quality + context quality | Trust badge on every trade |
| `assess_crash_sentinel()` — market health signal | Traffic light dashboard widget |
| `score_entry_level()` — enter now vs wait | Entry timing indicator |
| `compute_limit_entry_price()` — patient/normal/aggressive | Limit order price suggestion |
| `compute_pullback_levels()` — where trade gets better | Alert manager for pullback levels |
| `assess_assignment_risk()` — US american / India european | Assignment warning badge |
| `compute_margin_analysis()` + `compute_margin_buffer()` | Margin impact preview |
| `assess_rate_risk()` — interest rate sensitivity | Rate risk overlay |

```bash
> validate SPY              # 10-check profitability gate
> audit SPY 35000           # 4-level decision audit
> kelly SPY 35000           # Position sizing
> sentinel                  # Crash sentinel status
```

---

### Step 10: Execute & Book Trade

The validated trade becomes a real position. TradeSpec carries everything the broker needs — legs, strikes, expiration, order type, chase limit.

| Library Features | Platform Ideas |
|-----------------|----------------|
| TradeSpec with complete legs, strikes, expiration | One-click order from trade spec |
| `build_closing_trade_spec()` for exit orders | Pre-built close orders |
| `suggest_desk_for_trade()` — routes to correct desk | Auto-routing with confirmation |
| Demo portfolio: `add_demo_position()` | Paper trading execution |
| `max_entry_price` — chase limit | Fill quality monitoring |
| Entry window (time of day gates) | Execution window enforcement |

```bash
> trade SPY                 # Place trade in demo portfolio
> close_trade abc123        # Close position and record P&L
```

---

### Step 11: Monitor Trades

Ongoing position monitoring with actionable signals. Every check returns a concrete action — hold, close, or adjust — with a closing TradeSpec when needed.

| Library Features | Platform Ideas |
|-----------------|----------------|
| `compute_monitoring_action()` — hold/close/adjust with closing TradeSpec | Position dashboard with action buttons |
| `monitor_exit_conditions()` — profit target, stop loss, DTE exit, regime change | Real-time P&L with exit trigger alerts |
| `compute_regime_stop()` — R1=2x, R2=3x, R3=1.5x, R4=1.5x | Dynamic stop visualization |
| `compute_time_adjusted_target()` — close early if profitable fast | Trailing profit target chart |
| `compute_remaining_theta_value()` — hold vs close vs redeploy | Theta decay curve |
| `run_position_stress()` — ongoing adversarial stress | Position stress heatmap |
| `check_trade_health()` — unified health with overnight risk | Position health cards |
| `assess_assignment_risk()` — ITM warning before expiry | Assignment countdown alert |

```bash
> health SPY                           # Position health check
> monitor SPY                          # Exit condition scan
> exit_intelligence SPY 10 0.30        # Exit analysis with DTE and P&L
> assignment_risk SPY                  # Assignment risk assessment
```

---

### Step 12: Adjust Trades & Manage Lifecycle

When a position is tested, income-desk returns a deterministic adjustment decision — not a menu of options. Roll, convert, or close, with the exact TradeSpec to execute.

| Library Features | Platform Ideas |
|-----------------|----------------|
| `recommend_action()` — deterministic adjustment decision | One-click adjustment execution |
| `CONVERT_TO_DIAGONAL` — strategy switching on regime change | Strategy conversion wizard |
| `handle_assignment()` — sell/wheel/hold decision with TradeSpec | Assignment handler workflow |
| `analyze_cash_secured_put()` — CSP/wheel analysis | Wheel strategy tracker |
| `analyze_covered_call()` — CC after assignment | Post-assignment action plan |
| `rebalance_desks()` — periodic desk rebalancing | Monthly rebalance scheduler |
| `evaluate_desk_health()` — desk performance scoring | Desk performance dashboard |

```bash
> adjust SPY                           # Get adjustment recommendation
> assignment SPY 570 put               # Handle assignment scenario
> csp IWM 240 2.50                     # Cash-secured put analysis
> covered_call IWM 240                 # Covered call after assignment
```

---

### Step 13: Feed AI/ML for Learning

Close the loop. Every trade outcome flows back into the system. Ranking weights calibrate, gate thresholds tune, and the system gets sharper over time.

| Library Features | Platform Ideas |
|-----------------|----------------|
| `calibrate_weights(outcomes)` — adjusts ranking from real results | Weekly auto-calibration job |
| `analyze_adjustment_effectiveness(outcomes)` — which adjustments work | Adjustment analytics dashboard |
| `analyze_gate_effectiveness(gate_history, shadow, actual)` — are gates too tight? | Gate tuning interface |
| TradeOutcome model — captures entry, exit, regime, P&L | Trade journal with tagging |
| PerformanceReport — by strategy, by regime | Performance analytics |
| Shadow portfolio tracking — blocked trades' hypothetical P&L | "What if" tracker for rejected trades |

```bash
> performance                          # Performance report
> sharpe                               # Sharpe ratio analysis
> drift                                # Portfolio drift detection
```

---

## Try It Now

```bash
pip install income-desk

# Full US trading simulation
income-desk --trader us

# Full India trading simulation
income-desk --trader india

# Interactive demo with $100K portfolio
income-desk --demo

# Offline (weekends/after hours)
income-desk --sim income      # Ideal income day (elevated IV, R1)
income-desk --sim recovery    # Post-crash rich premiums (R2, IV rank 80%+)
income-desk --sim crash       # Test crash playbook
```

## Supported Brokers

| Broker | Market | Cost |
|--------|--------|------|
| Alpaca | US | Free (delayed) |
| TastyTrade | US | Account required |
| IBKR | US/Global | Account required |
| Schwab / thinkorswim | US | Account required |
| Dhan | India | Free API |
| Zerodha | India | Account required |

> **Note:** thinkorswim is Schwab's trading platform. The Schwab broker integration covers both — connecting via the Schwab API gives you access to thinkorswim accounts. No separate integration needed.

```bash
income-desk --setup    # Connect your broker
```

Works without any broker (yfinance free data). Connect a broker for real-time quotes, Greeks, and HIGH trust analysis.

## Multi-Account Consolidation

Many traders have accounts across multiple brokers — TastyTrade for options, Schwab for equities, Fidelity for retirement. income-desk treats ALL your accounts as one portfolio.

| Library Features | Platform Ideas |
|-----------------|----------------|
| Pluggable broker ABCs — connect multiple simultaneously | Unified portfolio dashboard across brokers |
| `PortfolioExposure` aggregates across all positions | Cross-broker risk dashboard |
| `compute_position_size()` considers ALL open positions | Sizing that knows about your Fidelity IRA AND your TastyTrade options |
| CSV import from any broker | Consolidate without API — just upload trade exports |
| Correlation checks across all tickers regardless of account | One correlation matrix, all accounts |
| Crash sentinel monitors all positions | Single alert for all accounts |

**Example:** You have 3 accounts:
- TastyTrade: 2 iron condors (API connected)
- Schwab IRA: 5 equity positions (API connected)
- Fidelity 401K: index funds (CSV import)

income-desk sees all 10 positions as ONE portfolio. Kelly sizing accounts for the Fidelity positions. Correlation checks catch SPY IC + SPY index fund overlap. The crash sentinel monitors everything.

**CSV import for non-API brokers:**

```bash
> import_trades ~/Downloads/fidelity_trades.csv
Detected: fidelity | Imported: 12 positions | Skipped: 2
```

Supported formats: thinkorswim, TastyTrade, Schwab, IBKR, Fidelity, Webull, generic.

## Trust Framework

Every output tells you how much to trust it:

```
TRUST: 85% HIGH
  Data: 90% HIGH (broker_live) | Context: 85% HIGH (full mode)
  Fit for: ALL purposes including live execution
```

No broker? Trust = LOW — fit for research only. [Full trust framework docs](docs/TRUST_FRAMEWORK.md)

## Forward Testing, Not Backtesting

income-desk has no backtesting engine. Deliberately.

Start with 1 contract. Validation gates protect your capital. System learns from YOUR real outcomes. Kelly scales up as edge is proven.

```
1 contract → validation gates protect → record outcome →
calibrate_weights() learns → Kelly scales up → repeat
```

## Workflow APIs

15 high-level operations — one function call per trading action. All rate limiting, caching, and orchestration handled internally. Trades only propose strikes verified liquid in the broker's option chain.

```python
from income_desk.workflow import generate_daily_plan, DailyPlanRequest

plan = generate_daily_plan(
    DailyPlanRequest(tickers=["NIFTY", "BANKNIFTY", "RELIANCE", "TCS"], capital=5_000_000, market="India"),
    ma,
)
# plan.proposed_trades[0].short_put = 2300 (verified OI=305,000)
```

| Category | Workflows |
|----------|-----------|
| Pre-market | `generate_daily_plan`, `snapshot_market` |
| Scanning | `scan_universe`, `rank_opportunities` |
| Trade entry | `validate_trade`, `size_position`, `price_trade` |
| Positions | `monitor_positions`, `adjust_position`, `assess_overnight_risk` |
| Portfolio risk | `aggregate_portfolio_greeks`, `check_portfolio_health` |
| Stress testing | `stress_test_portfolio` (18 macro scenarios) |
| Expiry | `check_expiry_day` |
| Reporting | `generate_daily_report` |

Every workflow: Pydantic request in, Pydantic response out, `WorkflowMeta` with timestamp and warnings.

---

## Simulated Market Data — Weekend & After-Hours Testing

Full pipeline works without broker, internet, or market hours. Swap one line to go from live to simulated.

```python
from income_desk.adapters.simulated import create_india_trading, create_ideal_income, SimulatedMetrics

# India: 22 tickers (5 indices + 17 F&O stocks, correct strike intervals & lot sizes)
sim = create_india_trading()

# US: 16 tickers (SPY/QQQ/IWM + AAPL/MSFT/NVDA/TSLA + sector ETFs)
sim = create_ideal_income()

# Create analyzer — all 15 workflows work identically
ma = MarketAnalyzer(data_service=DataService(), market_data=sim, market_metrics=SimulatedMetrics(sim))

# Discovery: what tickers does this simulation support?
sim.supported_tickers()   # ["NIFTY", "BANKNIFTY", "RELIANCE", ...]
sim.has_ticker("NIFTY")   # True
sim.ticker_info()         # {"NIFTY": {"price": 23000, "iv": 0.18, ...}}
```

**Available presets:** `create_calm_market`, `create_volatile_market`, `create_crash_scenario`, `create_post_crash_recovery`, `create_wheel_opportunity`, `create_india_market`, `create_india_trading`, `create_ideal_income`.

---

## Portfolio Stress Testing

Run all 18 macro scenarios against your portfolio in one call. Factor model with correlations, IV leverage effect, and Monte Carlo confidence intervals.

```python
from income_desk.workflow import stress_test_portfolio, StressTestRequest

result = stress_test_portfolio(
    StressTestRequest(positions=my_positions, capital=5_000_000, market="India"),
    ma,
)
# result.risk_score = "safe"
# result.worst_scenario = "black_monday" (INR -8,814 loss)
# result.scenarios_breaching_limit = []
```

**18 scenarios:** S&P corrections (-5/-10/-20%), Black Monday, NIFTY crash, FII sell-off, RBI rate hike, commodity meltup, gold crash, rate shock, inflation/deflation, tech rotation, geopolitical shock, correlation spike.

**Scenario engine** (`income_desk/scenarios/`) also available standalone for stress-testing market data:

```python
from income_desk.scenarios import apply_scenario
stressed_sim, result = apply_scenario(baseline, "nifty_down_10")
# stressed_sim is a new SimulatedMarketData — use with any workflow
```

---

## Daily Profitability Test

Run every market day to verify the pipeline is production-ready:

```bash
.venv_312/Scripts/python.exe scripts/daily_profitability_test.py          # live Dhan
.venv_312/Scripts/python.exe scripts/daily_profitability_test.py --sim    # simulated
```

Produces a **GO / CAUTION / NO-GO** verdict based on: broker connectivity, option chain quality, regime detection, trade recommendation quality, validation gate pass rate, and position sizing sanity. Reports saved to `~/.income_desk/profitability_reports/`.

---

## Documentation

- [User Manual](USER_MANUAL.md) — complete guide by purpose, geography, user journey
- [Trust Framework](docs/TRUST_FRAMEWORK.md) — 3-dimensional data reliability scoring
- [Data Interfaces](docs/DATA_INTERFACES.md) — bring your own data source
- [Crash Playbook](docs/CRASH_PLAYBOOK.md) — systematic crash response protocol
- [Launch Plan](docs/LAUNCH_PLAN.md) — project roadmap
- [API Reference](API.md) — full Python API
- [Workflow API Spec](docs/superpowers/specs/2026-03-27-workflow-apis-design.md) — workflow architecture

## 90+ CLI Commands

```
Workflows:  daily_plan, snapshot, portfolio_greeks, profitability, presets, expiry_check, scenario, stress_portfolio
Trading:    validate, rank, screen, opportunity, entry_analysis, kelly, audit, sentinel
Monitoring: health, monitor, exit_intelligence, adjust, assignment_risk
Portfolio:  desk, portfolio, trade, close_trade, rebalance
Sizing:     kelly, size, margin, margin_buffer, csp, covered_call
Research:   regime, technicals, vol, levels, research, stress, rate_risk
Account:    balance, quotes, watchlist, wizard
```

Run `help` in the CLI for the full list.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Adding a broker = ~170 lines of field mapping, zero core changes.

## License

MIT — see [LICENSE](LICENSE).
