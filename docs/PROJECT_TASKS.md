# income_desk — Task Board

> Single source of truth for what's being worked on and what comes next.
> Update this file as tasks are completed or added.
> Last updated: 2026-03-21

---

## Recently Completed

### March 2026 — OSS Infrastructure + Desk Management + Demo Portfolio + 6 Brokers + PyPI (2026-03-21)

- **PyPI publication** — `income-desk` v0.3.1 published; package renamed from market-analyzer; ready for public use
- **Trader runners** — Trader-US.py and Trader-IND.py in `scripts/` — trade-ready simulation presets with full position lifecycle
- **Open source infrastructure** — README, CONTRIBUTING, CI (GitHub Actions), issue templates, SECURITY, CODE_OF_CONDUCT
- **Desk management / capital allocation** — 6 APIs: `recommend_desk_structure`, `suggest_desk_for_trade`, `compute_desk_risk_limits`, `compute_instrument_risk`, `evaluate_desk_health`, `rebalance_desks`; asset class → risk type → desks hierarchy
- **Demo portfolio system** — `--demo` CLI flag, `portfolio/trade/close_trade` commands; full stack simulation without broker
- **CSP/wheel workflow** — covered call analysis, full wheel state machine, `assess_covered_call()`
- **Assignment risk warning** — US American vs India European; `check_assignment_risk()`, `TradeSpec.assignment_style`
- **Cash vs margin analytics** — `compute_margin_efficiency()`, structure-based margin buffers, interest rate risk APIs
- **Alpaca, IBKR, Schwab broker integrations** — 6 total supported brokers (tastytrade, zerodha, dhan, alpaca, ibkr, schwab)
- **Dhan full implementation** — was stub, now complete
- **Setup wizard** — `--setup` flag for first-time onboarding
- **BYOD adapters** — CSV, dict, IBKR/Schwab skeletons in `broker/adapters/`
- **Data trust 2-dimensional** — calculation modes + fitness-for-purpose (wired into transparency models)
- **Monitoring action with closing TradeSpec** — `monitor_exit_conditions()` returns closing legs
- **Position stress monitoring** — `service/stress_monitoring.py`, 13 scenarios, urgency escalation
- **USER_MANUAL full rewrite** — all 80+ CLI commands documented

### March 2026 — Trading Intelligence Reform + Decision Audit + Crash Sentinel (2026-03-20)

- **Entry-level intelligence** — 6 pure functions: `check_strike_proximity`, `get_skew_optimal_strikes`, `compute_entry_level_score`, `compute_limit_order_price`, `detect_pullback_alert`, `validate_entry_conditions`; wired into IC strike selection and daily validation (check #10)
- **Earnings blackout gate** — validation check #9; blocks income entries within 5 days of earnings
- **Kelly criterion sizing** — `compute_position_size()` unified entry: Kelly → correlated Kelly → margin-regime interaction; `do_kelly` CLI command
- **Regime-contingent stops** — tighter in R4, wider in R1; `compute_regime_contingent_stops()`
- **Trailing profit targets** — ratchets at 40% then trails 25% below high-water; `compute_trailing_profit_target()`
- **Theta decay curve** — expected P&L trajectory model; `compute_theta_decay_curve()`
- **Correlated position sizing** — reduces Kelly when new trade correlated with portfolio; `compute_correlated_kelly()`
- **Margin-regime interaction** — scales 0.5× in R4, 1.2× in R1; `compute_margin_regime_interaction()`
- **DTE optimization** — term structure slope + skew → `compute_optimal_dte()`; `do_optimal_dte` CLI command
- **Strategy switching** — `recommend_strategy_switch()` on regime change; CONVERT_TO_DIAGONAL/CALENDAR/CLOSE_FULL
- **IV rank quality by ticker type** — `score_iv_rank_quality()`; validation check #10
- **Adjustment outcome tracking** — `record_adjustment_outcome()` for eTrading feedback loop
- **Decision audit framework** — `audit_decision()` → 4-level `DecisionAudit` (leg/trade/portfolio/risk); `do_audit` CLI command
- **Crash sentinel** — `assess_crash_sentinel()` → `SentinelReport` with GREEN/YELLOW/ORANGE/RED/BLUE signals; 9-indicator model; `do_sentinel` CLI command
- **Bug fixes** — max_loss POP computation, credit estimation double-count, stress graceful degradation, momentum R4 override, minimum credit filter ($0.15/share)

### March 2026 — Functional Testing / Validation Framework
- Built `income_desk/validation/` package: `models.py` (CheckResult, Severity, Suite, ValidationReport), `profitability_audit.py`, `daily_readiness.py`, `stress_scenarios.py`
- 8 functional test modules in `tests/functional/`: daily workflow, commission drag, fill quality, margin efficiency, adversarial stress, profitability gates, exit discipline, drawdown circuit
- Added `do_validate` CLI command for daily pre-market use and MCP consumption
- ~45 functional tests added (see git commits 2026-03-18 / 2026-03-19)

### March 2026 — All 9 Systematic Gaps Complete (G01–G09)
- G01: Deterministic adjustment (`recommend_action()` — single action, no menus)
- G02: Execution quality validation (`validate_execution_quality()`)
- G03: Entry time windows on every TradeSpec
- G04: Time-of-day urgency escalation (0DTE force-close, tested escalation)
- G05: Overnight risk auto-check after 15:00
- G06: Auto-select screening (`scan()` with min_score and top_n)
- G07: Performance feedback loop (TradeOutcome → calibrate_weights())
- G08: Debug/commentary mode on 4 services, threaded through ranking
- G09: Data gap self-identification in 8 assessors

### March 2026 — Signal Quality Overhaul (SQ1–SQ10)
- IV rank wired into all assessors and ranking (SQ1, SQ9)
- HMM staleness detection — `model_age_days` (SQ2)
- POP with IV rank + calibration — `calibrate_pop_factors()` (SQ3)
- Technical indicators: Fibonacci, ADX, Donchian, Keltner, Pivots, VWAP (TA1–TA6)
- Assessor overhauls: MR, breakout, earnings, screening, momentum, pivots in levels (SQ4–SQ10)

### March 2026 — ML Learning Stack (ML1–ML3)
- ML1: Drift detection — `detect_drift()`, rolling win rate per regime/strategy cell, DriftAlert model
- ML2: Thompson Sampling bandits — `build_bandits()`, `update_bandit()`, `select_strategies()`
- ML3: Threshold optimization — `optimize_thresholds()`, learns IV/POP cutoffs from outcomes, ThresholdConfig model

### March 2026 — Multi-Market / India / SaaS (CR6–CR17, IN1–IN5, H1–H5, CM1, MC1–MC5)
- Dhan + Zerodha broker stubs (CR6), currency + timezone + lot_size on all models (CR7)
- India strategy config (CR8), regime detection for NIFTY/BANKNIFTY (CR9), timezone-aware entry windows (CR10)
- Sharpe, drawdown, regime performance analytics (CR11), India ticker mapping (CR12), MarketRegistry (CR13)
- Cache isolation, lightweight init, TokenExpiredError, rate_limit_per_second verified (CR14–CR17)
- Currency conversion, same-ticker hedge assessment, currency hedge, cross-market P&L decomposition (H1–H4)
- India equity-first: equity trade models, equity TradeSpec builder, LEAP blocked for India, market-aware exit notes (IN1–IN5)
- Cross-market US-India correlation (CM1), macro indicators: bonds, credit spreads, dollar, inflation (MC1–MC5)

### March 2026 — Research, Risk, Capital Deployment (MR1–MR8, PF1, RM1–RM7, GF1–GF2, ST1, EQ1–EQ3, CD1–CD7, WH1, FT1–FT7, VS1–VS4, and others)
- Full macro research: 22 assets, correlations, macro regime, sentiment, FRED, India context, commentary generation (MR1–MR8)
- Position-aware portfolio filtering, expected portfolio loss, portfolio Greeks limits, concentration checks, drawdown circuit breaker, combined risk dashboard (PF1, RM1–RM7)
- Trade gate framework BLOCK/SCALE/WARN (17 gates), shadow portfolio + gate effectiveness (GF1–GF2)
- Stress testing: 13 predefined scenarios (ST1)
- Equity research: 5 strategies, stock screening, trader_stocks.py (EQ1–EQ3)
- Capital deployment planner, asset allocation, core holdings recommender, rebalancing, LEAP vs stock, wheel strategy (CD1–CD7)
- Wheel state machine (WH1), full futures analysis suite (FT1–FT7)
- IV percentile / vol surface: term structure percentile, skew percentile, calendar/diagonal signals wired (VS1–VS4)
- Pre-market unusual activity scanner (PM1), trade quality scoring POP+EV+R:R composite (TQ1)
- Zerodha Kite Connect full integration (ZRD), India leg execution sequencing (LEG1)
- Universe scanner with 10 presets, 85+ instruments (UV1)

### March 2026 — Trade Lifecycle APIs + TradeSpec Factory
- 10 pure-function APIs for eTrading: compute_income_yield, compute_breakevens, estimate_pop, check_income_entry, filter_trades_by_account, align_strikes_to_levels, aggregate_greeks, monitor_exit_conditions, check_trade_health, get_adjustment_recommendation
- trade_spec_factory.py: create_trade_spec(), build_iron_condor/credit_spread/debit_spread/calendar()
- DXLink conversion: from_dxlink_symbols(), to_dxlink_symbols(), parse_dxlink_symbol()

### February 2026 — TradeSpec Standardization + Iron Man + ORB Integration
- TradeSpec standardized with structure_type, order_side, profit_target_pct, stop_loss_pct, exit_dte, leg_codes, order_data
- Iron Man (inverse IC) for narrow ORB range, ORB integrated into all 5 zero-DTE strategies
- Daily trading plan service (TradingPlanService), day verdict logic, horizon buckets

### February 2026 — Broker Integration (TastyTrade)
- Pluggable multi-broker architecture: 5 ABCs
- TastyTrade implementation: 8 files in broker/tastytrade/
- OptionQuoteService, DXLink intraday streaming, MarketAnalyzer facade wired with broker providers

---

## In Progress

None. All known gaps are DONE per SYSTEMATIC_GAPS.md (2376 tests passing as of 2026-03-21).

---

## Next Up (Prioritized Backlog)

### P2 — Nice to Have (Library Quality)

Most P1 items from the March 20 review were completed on March 21. Simulation layer, Alpaca integration, 6-broker stack, demo portfolio, desk management, and PyPI publication all shipped 2026-03-21. Remaining backlog:

| # | Task | Why |
|---|------|-----|
| P2-0 | **Republish to PyPI** — v0.3.1 now pending with latest features (Traders, desk_key bug fix, sim enhancements) | Income-desk 0.3.0 live on PyPI; next release bundles final session changes |
| P2-1 | Multi-factor setup scoring — volume profile, relative strength, IV/RV spread in breakout/momentum/mean_reversion assessors | Current assessors use basic indicators; need multi-factor for stronger signal |
| P2-2 | Richer LEAP/earnings assessors — earnings growth rate for LEAP scoring, vol crush magnitude history | leap/earnings assessors are thin; need deeper fundamental integration |
| P2-3 | ML regime validation — track regime predictions vs actual price behavior; auto-retrain HMM | Track whether R2 actually mean-reverted, R3 actually trended |
| P2-4 | POP calibration from actual outcomes — `calibrate_pop_factors(outcomes)` exists; requires eTrading to send closed trade outcomes | The live feedback loop is not running |
| P2-5 | Documentation site — ReadTheDocs or GitHub Pages from existing doc files | OSS infrastructure is in place; auto-generated API docs would reduce onboarding friction |
| P2-6 | More broker integrations — Webull, E*Trade, Robinhood (low priority; existing 6 cover most user cases) | Community request; patterns established with BYOD adapters |
| P2-7 | Full IBKR TWS wiring — skeleton exists; full TWS API integration | IBKR is the preferred broker for institutional users |
| P2-8 | Stock screener OHLCV period mismatch — eTrading calls `get_ohlcv(ticker, period='1y')` but MA expects `days=` param. Dividend yield double-division (yfinance ratio × 100 again). | eTrading must fix: use `days=365` and remove dividend yield multiplication |

### P0 — Critical / Blocking eTrading

| # | Issue | Status | MA Action |
|---|-------|--------|-----------|
| P0-1 | Scan → propose → deploy broken: 0/50 proposals | eTrading-side: Initialize bandit priors from `REGIME_STRATEGY_ALIGNMENT` | No MA change needed |
| P0-2 | Scan takes 2+ min, HTTP timeout | eTrading-side: Make scan async with polling | No MA change needed |
| P0-3 | NIFTY trend_continuation no trade_spec | ✅ DONE (2026-03-20) | Fallback to `build_setup_trade_spec()` + strike_interval support |
| P0-4 | Mark-to-market: zero broker quotes for equity | eTrading-side: DXLink equity Quote subscription path | No MA change (API working) |
| P0-5 | Risk dashboard expected_loss null | eTrading-side: Call `compute_risk_dashboard()` with positions | No MA change (API ready) |

### P1 — High Value (eTrading Bugs)

#### eTrading P1 Bugs (risk management incomplete, from ETRADING_INTEGRATION.md)

| # | Issue | Fix |
|---|-------|-----|
| P1-5 | Adjustment recommendations not wired | `ma.adjustment.recommend_action()` not called in eTrading monitoring loop |
| P1-6 | Overnight risk not assessed for equities | `assess_overnight_risk()` not called for equity_long positions |
| P1-7 | Macro dashboard all null | OHLCV for TNX, TLT, HYG, UUP, TIP not fetched and passed to `compute_macro_dashboard()` |
| P1-8 | Equity exit conditions not monitored | `monitor_exit_conditions()` not wired for equity_long in eTrading |
| P1-9 | Trade gates not enforced at entry | `evaluate_trade_gates()` not called before any order submission in eTrading |
| P1-10 | Deployment plan uses hardcoded capital and no live regime | Use `portfolio.total_equity` and `ma.regime.detect("SPY")` for regime-based acceleration |

### P2 — Nice to Have (eTrading)

| # | Task | Source |
|---|------|--------|
| P2-E1 | Benchmark returns API: `compute_benchmark_returns(tickers, days)`, `compute_alpha(portfolio_return, benchmark_return)` | CR-14 in ETRADING_CHANGE_REQUEST_V2.md — needed by Vidura agent |
| P2-E2 | Opportunity scanner for Vidura: `scan_vidura_opportunities(scorecards, correlations, macro_regime, sentiment, current_positions)` combining MR1–MR4 signals into actionable list | CR-15 in ETRADING_CHANGE_REQUEST_V2.md |
| P2-E3 | Fix eTrading P2 data mismatches: valuation uses `period=` instead of `days=`, MonthlyAllocation.equity rename, EquityScreenResult.total_passed rename, AssetAllocation.equity_sub_split rename, dividend yield double-division, VIX not fetched on startup | ETRADING_INTEGRATION.md P2 items 12–22 |
| P2-E4 | Fix eTrading P3 routing: MCP tool `id` param not mapped to CLI positional arg (levels/hedge/strategies broken), add /api/v2/context and /api/v2/black-swan endpoints, fix CLI command router (30+ commands fall back to status) | ETRADING_INTEGRATION.md P3 items 23–29 |

---

## Documentation TODOs

- [x] ~~Update USER_MANUAL.md with all 7 new CLI commands from 2026-03-20~~ — USER_MANUAL fully rewritten 2026-03-21; all 80+ commands documented
- [x] ~~Document data trust framework in USER_MANUAL.md~~ — done in rewrite
- [x] ~~Document position stress monitoring API~~ — done in rewrite
- [ ] Update SYSTEMATIC_GAPS.md test count to 2266
- [ ] Document `compute_benchmark_returns()` and `compute_alpha()` in USER_MANUAL.md if/when P2-E1 is implemented
- [ ] Document `scan_vidura_opportunities()` in USER_MANUAL.md if/when P2-E2 is implemented
- [ ] Set up ReadTheDocs / GitHub Pages from existing doc files (P2-5)

---

## eTrading Integration Tasks

Summary from MA_CHANGE_REQUEST_FOR_ETRADING.md, ETRADING_CHANGE_REQUEST.md, and SYSTEMATIC_GAPS.md. All MA APIs are ready — eTrading must wire them.

### Immediate (Wire Now — APIs Ready)

| # | What eTrading Must Do | MA API | Priority |
|---|----------------------|--------|----------|
| E1 | Pass `iv_rank` to all assessor calls | `ma.quotes.get_metrics(ticker).iv_rank` → `assess_*(iv_rank=)` | HIGH |
| E2 | Pass `iv_rank_map` to ranking | `{ticker: iv_rank}` → `rank(iv_rank_map=...)` | HIGH |
| E3 | Pass `time_of_day` to health check | `check_trade_health(..., time_of_day=datetime.now().time())` | HIGH |
| E4 | Pass `debug=True` and store commentary | `detect(debug=True)`, store in `decision_lineage` JSON | HIGH |
| E5 | Surface `data_gaps` in UI | `result.data_gaps` on every RankedEntry/PlanTrade — discount confidence, show warnings | HIGH |
| E6 | Call `validate_execution_quality()` before orders | Block if not GO | HIGH |
| E7 | Respect `entry_window_start/end` on TradeSpec | Only submit within window | MEDIUM |
| E8 | Read `entry_window_timezone` for India trades | Convert to local timezone for scheduler | MEDIUM |
| E9 | Use `ma.registry` for lot sizes and strategy routing | `registry.get_instrument()` for lot_size, `strategy_available()` to skip LEAP in India | HIGH |
| E10 | Check `regime.model_age_days` and retrain stale models | If > 60 → `ma.regime.fit(ticker)` | MEDIUM |
| E11 | Pass `lot_size` correctly for India trades | `TradeSpec.lot_size`, `monitor_exit_conditions(lot_size=)` | HIGH |
| E12 | Call `assess_hedge()` for open positions | Daily or on regime change | MEDIUM |
| E13 | Pass FX rates to `compute_currency_pnl()` | For cross-market P&L decomposition in dashboard | MEDIUM |

### Build Pipeline (Requires DB + Scheduling)

| # | What eTrading Must Build | MA API | Frequency |
|---|--------------------------|--------|-----------|
| E14 | TradeOutcome table + construction on trade close | Capture regime/IV/composite_score/dte at entry | On every close |
| E15 | Bandit params table + update on close | `update_bandit(bandit, won)` | On every close |
| E16 | Drift detection job | `detect_drift(outcomes)` → suspend/reduce strategy cells | Daily pre-market |
| E17 | Bandit strategy selection in daily plan | `select_strategies(bandits, regime)` → `rank(strategies=)` | Daily plan |
| E18 | Weight calibration job | `calibrate_weights(outcomes)` | Weekly |
| E19 | POP factor calibration job | `calibrate_pop_factors(outcomes)` | Weekly |
| E20 | Threshold optimization job | `optimize_thresholds(outcomes)` → apply as config override | Monthly |
| E21 | Performance dashboard | `compute_performance_report()`, `compute_sharpe()`, `compute_drawdown()`, `compute_regime_performance()` | Monthly |

### SaaS Infrastructure

| # | What eTrading Must Handle | MA Provides |
|---|--------------------------|-------------|
| E22 | Per-user MarketAnalyzer instance — no sharing across users | Cache is per-instance (verified CR-14) |
| E23 | Token refresh for India brokers | `TokenExpiredError`, `is_token_valid()` on providers |
| E24 | Rate limiting for India brokers | `rate_limit_per_second` on MarketDataProvider |
| E25 | Broker connection UI per user | `connect_dhan_from_session()`, `connect_zerodha_from_session()` |
| E26 | Currency-aware P&L display | `compute_currency_pnl()`, `compute_portfolio_exposure()` |
| E27 | Timezone-aware scheduling | `registry.get_market("INDIA").market_hours` |

### MA ↔ eTrading Feedback Contract (3 Things MA Needs to Learn)

| # | What eTrading Sends | When | What MA Does With It |
|---|---------------------|------|----------------------|
| F1 | `list[TradeOutcome]` | Weekly batch + every close for bandit | `calibrate_weights()`, `calibrate_pop_factors()`, `detect_drift()`, `optimize_thresholds()`, `compute_performance_report()`. **Without this, the entire learning stack returns empty results.** |
| F2 | `list[RejectedTrade]` with hypothetical P&L | Monthly | `analyze_gate_effectiveness()` — detects gates too tight (blocking winners) or too loose (allowing losers) |
| F3 | `peak_nlv: float` | Every call to `compute_risk_dashboard()` | Drawdown calculation. MA is stateless and cannot remember peak across calls. |

---

## Decisions Log

Key architectural decisions that must not be reversed or forgotten.

| Decision | Rationale |
|----------|-----------|
| **No Black-Scholes pricing — ever (for execution)** | All option prices/Greeks come from broker via DXLink. If no broker, value is None. BS exists only in `compute_theoretical_price()` for "cheap/rich" comparison display, never for execution or risk sizing. |
| **`rank()` output is NOT safe to execute directly** | rank() scores on market merit only — zero knowledge of open positions, portfolio concentration, or risk limits. eTrading MUST call `filter_trades_with_portfolio()` and `evaluate_trade_gates()` before execution. |
| **MA is stateless — eTrading owns all state** | No positions, fills, P&L history, or session state in MA. Every function is pure computation: eTrading passes context in, MA computes and returns. |
| **Same-ticker hedging only** | No beta-weighted index hedging. All hedges must be on the same underlying. |
| **Per-instrument regime detection, not global** | Gold can trend while tech chops. Regime is detected per-ticker via HMM. There is no global "market regime." The macro regime (growth/deflation/stagflation) from MR3 is separate from the R1–R4 HMM regime. |
| **No decision without a regime label** | Core invariant. Every strategy selection and trade recommendation requires a valid R1–R4 regime label. |
| **Income-first, directional only when regime permits** | Default to theta harvesting (IC, calendar, straddle). Directional only in R3/R4, and only with defined risk. |
| **DXLink is the only path for live option data** | `from tastytrade.streamer import DXLinkStreamer`. yfinance provides historical OHLCV and chain structure (strikes/expirations) only. |
| **Additive changes preferred** | Never move or delete existing files without strong reason. Add new files. Maintain backward-compatible re-exports. |
| **NO fake data, NO placeholder values** | If data is unavailable, return None or raise a typed exception. A missing value is infinitely better than a wrong one. |
| **Provider failures are not silent** | Raise typed exceptions. Callers must distinguish "no data exists" from "fetch failed." |
| **Every new capability gets a CLI command** | Non-negotiable. CLI is the dev/exploration interface and doubles as MCP tool surface. |
| **eTrading passes pre-authenticated sessions (SaaS mode)** | MA never authenticates or manages broker connections in embedded mode. Caller passes providers via `connect_from_sessions()`. |
| **`trade_quality_score >= 0.50` gates systematic execution** | Composite of POP (40%) + EV (30%) + R:R (30%). Trades below this score should not reach execution. |
| **`filter_trades_with_portfolio()` 7-step cascade is mandatory** | All 7 steps — position limits, ticker/sector concentration, portfolio risk budget, buying power — must run before any trade is submitted. |
