# market_analyzer — Project State

> Current implementation state as of 2026-03-21.
> Update this file when major features are completed.

---

## Test Suite

- **Total tests: 2266** (as of 2026-03-21, collected by pytest)
- All passing: yes (confirmed by `pytest --co -q`)
- Test locations:
  - `tests/` — unit tests (~2220 tests)
  - `tests/functional/` — functional integration tests (45 tests, 8 modules)

---

## Recently Completed (2026-03)

Commits in reverse chronological order since 2026-03-01:

| Commit | Description |
|--------|-------------|
| (2026-03-21) | Open source infrastructure — README, CONTRIBUTING, CI, issue templates, SECURITY, CODE_OF_CONDUCT |
| (2026-03-21) | feat: desk management / capital allocation — 6 APIs (DeskSpec, suggest_desk_for_trade, compute_desk_risk_limits, compute_instrument_risk, evaluate_desk_health, rebalance_desks) |
| (2026-03-21) | feat: demo portfolio system — `--demo` flag, `portfolio/trade/close_trade` CLI commands |
| (2026-03-21) | feat: CSP/wheel workflow + covered call analysis |
| (2026-03-21) | feat: assignment risk warning — US American options vs India European (cash-settled) |
| (2026-03-21) | feat: cash vs margin analytics + structure-based margin buffers |
| (2026-03-21) | feat: interest rate risk APIs |
| (2026-03-21) | feat: Alpaca, IBKR, Schwab broker integrations (6 total) |
| (2026-03-21) | feat: Dhan full implementation (India) — was stub, now complete |
| (2026-03-21) | feat: setup wizard — `--setup` flag for first-time onboarding |
| (2026-03-21) | feat: BYOD adapters — CSV, dict, IBKR/Schwab skeleton importers |
| (2026-03-21) | feat: data trust 2-dimensional + calculation modes + fitness-for-purpose |
| (2026-03-21) | feat: monitoring action with closing TradeSpec |
| (2026-03-21) | feat: position stress monitoring |
| (2026-03-21) | docs: USER_MANUAL full rewrite |
| (2026-03-20) | feat: crash sentinel API — GREEN/YELLOW/ORANGE/RED/BLUE signals |
| (2026-03-20) | feat: decision audit framework — 4-level leg/trade/portfolio/risk scoring |
| (2026-03-20) | fix: max_loss POP computation, credit estimation, stress graceful degradation, momentum override, minimum credit filter |
| (2026-03-20) | feat: trading intelligence reform — exit intelligence, position sizing, DTE optimizer, strategy switching, IV rank quality, adjustment outcome tracking |
| (2026-03-20) | feat: entry-level intelligence — strike proximity gate, skew-optimal strikes, entry level score, limit order pricing, pullback alerts |
| (2026-03-20) | feat: earnings blackout gate (validation check #9) |
| (2026-03-20) | feat: Kelly criterion sizing |
| (2026-03-20) | feat: validation framework 10-check daily suite + 3-check adversarial |
| `ce81475` | feat: add validate CLI command for daily pre-trade profitability check |
| `645de9d` | feat: add functional test suite (8 modules, 45 tests, daily/adversarial coverage) |
| `5c53e4e` | feat: wire validation package exports |
| `dee13fd` | fix: remove unused time_of_day param; emit ev_positive WARN when POP unavailable |
| `4f06b96` | fix: remove margin_efficiency severity downgrade in orchestrator; update ideal-conditions test |
| `08b8189` | feat: add daily readiness + adversarial orchestrators |
| `cda5692` | fix: expand long-vega classifications in check_vega_shock |
| `744b551` | feat: add adversarial stress checks (gamma, vega shock, breakeven spread) |
| `681cbdb` | fix: correct commission drag and margin efficiency thresholds to spec values |
| `8c301c9` | feat: add profitability audit checks (commission drag, fill quality, margin efficiency) |
| `d80076d` | fix: use @computed_field on ValidationReport properties for Pydantic serialization |
| `fa7400b` | feat: add validation models (CheckResult, Severity, ValidationReport) |
| `29546f7` | ETRADING_INTEGRATION.md updates |
| `7df1be0` | major miscellaneous changes |
| `ef382b2` | Display this in the daily pre-market dashboard |

### Validation Framework (2026-03-19) — COMPLETED

A complete pre-trade profitability validation framework implemented as pure functions (no broker required).

**Package:** `market_analyzer/validation/`
- `models.py` — `CheckResult`, `Severity` (PASS/WARN/FAIL), `Suite` (DAILY/ADVERSARIAL), `ValidationReport` (Pydantic with `summary`, `passed`, `failed`, `warned` computed fields)
- `profitability_audit.py` — 3 profitability audit checks
- `stress_scenarios.py` — 3 adversarial stress checks
- `daily_readiness.py` — orchestrators: `run_daily_checks()` (7 checks) and `run_adversarial_checks()` (3 checks)

**Daily Suite — `run_daily_checks()` — 7 checks:**

1. `commission_drag` — round-trip fees vs credit; PASS < 10% drag, WARN 10-25%, FAIL >= 25% (or zero credit)
2. `fill_quality` — bid-ask spread viability; PASS <= 1.5%, WARN 1.5-3%, FAIL > 3%
3. `margin_efficiency` — annualized ROC via `compute_income_yield()`; PASS >= 15%, WARN 10-15%, FAIL < 10%
4. `pop_gate` — probability of profit via `estimate_pop()`; PASS >= 65%, WARN >= 55%, FAIL < 55%
5. `ev_positive` — expected value in dollars per contract; PASS > 0, WARN > -10, FAIL <= -10
6. `entry_quality` — IV rank / DTE / RSI / regime via `check_income_entry()`; PASS if confirmed, WARN if score >= 0.45, FAIL otherwise
7. `exit_discipline` — trade spec has `profit_target_pct`, `stop_loss_pct`, `exit_dte` set; PASS if all present

**Adversarial Suite — `run_adversarial_checks()` — 3 checks:**

1. `gamma_stress` — max loss at 2σ move; R:R ratio vs wing width; PASS R:R <= 5:1, WARN 5-10:1, FAIL > 10:1
2. `vega_shock` — IV +30% spike impact; long-vega structures auto-PASS; FAIL if estimated loss >= 50% of credit
3. `breakeven_spread` — finds bid-ask spread % at which EV turns negative; FAIL if edge lost at <= 1%, WARN <= 2%, PASS > 2%

**CLI:** `do_validate` — runs both suites on a representative TradeSpec, displays PASS/WARN/FAIL per check

**Functional Tests:** `tests/functional/` — 8 modules, 45 tests
- `test_commission_drag.py`, `test_fill_quality.py`, `test_margin_efficiency.py`
- `test_profitability_gates.py` (POP gate + EV), `test_exit_discipline.py`
- `test_daily_workflow.py`, `test_adversarial_stress.py`, `test_drawdown_circuit.py`

---

### Entry-Level Intelligence (2026-03-20) — COMPLETED

Six new pure functions in `features/entry_levels.py` wired into IC strike selection and daily validation:

1. **`check_strike_proximity(trade_spec, levels)`** — gates entry when short strikes are within 0.5 ATR of key S/R levels; returns `StrikeProximityResult` with flags per leg
2. **`get_skew_optimal_strikes(ticker, vol_surface, regime_id)`** — uses skew slope to shift put/call strikes for better premium collection (R1/R2) or directional bias (R3)
3. **`compute_entry_level_score(trade_spec, technicals, levels, regime_id)`** — composite 0–1 score combining IV rank quality, DTE optimality, strike proximity, and regime alignment
4. **`compute_limit_order_price(trade_spec, quotes, slippage_pct)`** — returns a chase-limit price between mid and bid (credit) or mid and ask (debit) to avoid legging into bad fills
5. **`detect_pullback_alert(ticker, technicals, regime_id)`** — detects short-term pullback within a trend for better entry timing in R3; returns `PullbackAlert` with strength and suggested action
6. **`validate_entry_conditions(trade_spec, technicals, levels, vol_surface, regime_id)`** — orchestrates all entry checks into a single `EntryValidation` report (wired as validation check #10)

**CLI:** `do_entry_analysis TICKER` — displays full entry-level scoring with sub-component breakdown

---

### Trading Intelligence Reform (2026-03-20) — COMPLETED

10 features across exit intelligence, position sizing, DTE optimization, strategy switching, and IV rank quality.

#### Exit Intelligence (`features/exit_intelligence.py`)

- **`compute_regime_contingent_stops(trade_spec, regime_id, atr_pct)`** — tighter stops in R4, wider in R1; returns `RegimeStop` with `stop_trigger`, `urgency`, and rationale
- **`compute_trailing_profit_target(trade_spec, current_pnl_pct, regime_id)`** — ratchets profit target upward as trade profits; locks in gains at 40% then trails at 25% below high-water mark
- **`compute_theta_decay_curve(trade_spec, days_elapsed)`** — models expected P&L trajectory from entry to expiry using empirical theta decay curve; useful for "is this trade on track?" comparison

#### Position Sizing (`features/position_sizing.py` — expanded)

- **`compute_correlated_kelly(trade_spec, portfolio_positions, regime_id)`** — reduces Kelly fraction when new trade is correlated with existing positions (same sector or similar delta direction)
- **`compute_margin_regime_interaction(trade_spec, account_balance, regime_id)`** — scales position size down in R4 (max 0.5× normal) and up in R1 (max 1.2× normal) based on regime confidence
- **`compute_position_size(trade_spec, capital, risk_pct, regime_id, portfolio_positions)`** — unified entry point: calls Kelly → correlation adjustment → margin-regime interaction → returns `PositionSizeResult` with `contracts`, `capital_at_risk`, `rationale`

#### DTE Optimizer (`features/dte_optimizer.py`)

- **`compute_optimal_dte(ticker, vol_surface, regime_id, structure_type)`** — uses term structure slope and skew to find DTE with best theta/vega tradeoff; returns `DTERecommendation` with `optimal_dte`, `rationale`, and `term_structure_context`

**CLI:** `do_optimal_dte TICKER` — shows DTE recommendation with vol surface context

#### Strategy Switching

- **`recommend_strategy_switch(trade_spec, current_regime, new_regime)`** — detects regime change mid-trade and recommends structural conversion; `CONVERT_TO_DIAGONAL` (R1→R3), `CONVERT_TO_CALENDAR` (R2→R1), `CLOSE_FULL` (any→R4)

#### IV Rank Quality

- **`score_iv_rank_quality(ticker, iv_rank, ticker_type)`** — adjusts IV rank interpretation by ticker type (ETF vs equity vs index); ETFs have lower baseline, equities spike higher; returns `IVRankQuality` with adjusted score and `quality` label (premium/elevated/normal/low)
- **Validation check #10** — `iv_rank_quality` check added to daily suite: FAIL if IV rank quality is `low` for income trades

#### Adjustment Outcome Tracking

- **`record_adjustment_outcome(adjustment_type, pre_pnl, post_pnl, regime_id)`** — pure function that returns `AdjustmentOutcome` for eTrading to store and feed back into `calibrate_weights()`

---

### Bug Fixes (2026-03-20) — COMPLETED

Five fixes for correctness and robustness:

1. **max_loss POP computation** — `estimate_pop()` was using wing width before subtracting credit; now correctly uses `(wing_width - credit)` as max loss denominator
2. **Credit estimation** — `compute_income_yield()` was double-counting commissions when `entry_credit` already net of commissions; fixed parameter contract
3. **Stress graceful degradation** — `run_stress_suite()` no longer raises if a scenario has no positions; returns `ScenarioResult` with `skipped=True` instead
4. **Momentum override** — `assess_momentum()` was ignoring regime R4 hard stop and could return trade specs in high-vol trending regime; fixed
5. **Minimum credit filter** — `assess_iron_condor()` now rejects trade specs where total credit < $0.15 per share (un-executable on most brokers)

---

### Decision Audit Framework (2026-03-20) — COMPLETED

4-level audit framework for full decision traceability (`features/decision_audit.py`, `models/decision_audit.py`):

**`audit_decision(trade_spec, regime_result, validation_report, sizing_result, entry_validation)`** → `DecisionAudit`

| Level | What It Audits | Output |
|-------|---------------|--------|
| `leg_scores` | Each leg: strike vs spot distance, delta, premium quality | `LegAudit` per leg |
| `trade_scores` | Full structure: IV rank, DTE fit, regime alignment, exit params | `TradeAudit` |
| `portfolio_scores` | Concentration, correlation, buying power utilization | `PortfolioAudit` |
| `risk_scores` | Expected loss vs budget, gamma exposure, overnight risk flag | `RiskAudit` |

`DecisionAudit.summary` → one-line verdict: `"APPROVED: IC SPY R1 | score 0.82 | 4/4 levels pass"`
`DecisionAudit.blocking_issues` → list of strings for any level with score < 0.5

**CLI:** `do_audit TICKER` — runs full 4-level audit on representative trade, shows per-level scores and blocking issues

---

### Crash Sentinel (2026-03-20) — COMPLETED

Market crash early-warning system (`features/crash_sentinel.py`, `models/sentinel.py`):

**`assess_crash_sentinel(tickers, technicals_map, macro_context, vol_surface_map)`** → `SentinelReport`

Signal levels:

| Signal | Color | Meaning | Portfolio Action |
|--------|-------|---------|-----------------|
| `CLEAR` | GREEN | No crash indicators | Normal trading |
| `WATCH` | YELLOW | 1–2 soft indicators elevated | Monitor, tighten stops |
| `CAUTION` | ORANGE | 3+ indicators elevated or 1 critical | Reduce size, avoid new income |
| `ALERT` | RED | Critical cluster: VIX + credit spread + breadth | Close short premium, hedge |
| `PANIC` | BLUE | Extreme multi-factor spike (COVID/Black Monday type) | Close all short premium immediately |

Indicators assessed (9 total): VIX level + spike, credit spread widening, equity breadth collapse, put/call ratio, term structure inversion, cross-asset correlation spike, dollar spike, bond yield crash, momentum divergence.

`SentinelReport.dominant_signal` — the single signal driving the alert
`SentinelReport.indicator_detail` — dict of indicator name → value + threshold
`SentinelReport.recommended_actions` — list of concrete steps

**CLI:** `do_sentinel [TICKERS]` — displays signal color, dominant driver, and recommended actions

---

### Data Trust Framework (2026-03-20) — COMPLETED

2-dimensional trust assessment on all outputs: **data quality** (broker/yfinance/heuristic) and **context quality** (calculation mode).

**`models/transparency.py`:**
- `CalculationMode` — `"full"` (default, portfolio-aware) or `"standalone"` (CLI/backtest)
- `DataTrust` — source, score, degraded fields
- `TrustReport` — overall trust 0–100%, actionability verdict
- `ContextGap`, `DegradedField` — missing inputs detailed

**Functions in `features/trust.py`:**
- `compute_data_trust(...)` — scores broker/yfinance/heuristic sources
- `compute_context_quality(..., mode="full")` — scores caller-provided context completeness
- `compute_trust_report(..., mode="full")` — combined 2-D report

**Default = full mode:** eTrading does not need signature changes; all calls are portfolio-aware BY DEFAULT. Missing critical context (levels, iv_rank, entry_credit) sets `is_actionable=False`.

**CLI:** `context` and all opportunity assessments show trust breakdown in output.

---

### Monitoring Action with Closing TradeSpec (2026-03-20) — COMPLETED

`MonitoringAction` model extended to include `closing_trade_spec: TradeSpec | None`:

- `monitor_exit_conditions()` returns exit trigger: TP hit / SL hit / DTE expired / time-of-day urgency
- When exit condition met, `closing_trade_spec` populated with pre-built STO/BTC legs to close position
- eTrading directly executes closing spec without secondary computation
- Wired: `check_trade_health()` also returns closing spec when exit urgent

**CLI:** `monitor` command shows exit trigger and closing legs (if available).

---

### Position Stress Monitoring (2026-03-20) — COMPLETED

New service in `service/stress_monitoring.py` and CLI `run_position_stress()`:

- Takes open positions and stresses them on 13 predefined scenarios (-1%, -3%, -5%, -10%, VIX spike, flash crash, Black Monday, COVID, India crash, Fed surprise, etc.)
- Returns `StressResult` per position per scenario: `estimated_loss_pct`, `max_loss_exceeded`, `urgency` flag
- Pure functions — no broker required (uses ATR-based loss estimates)
- Gracefully degrades when position Greeks unavailable

**CLI:** `stress_test` command — runs on open positions with urgency escalation guidance.

---

### India TradeSpec Fixes (2026-03-20) — COMPLETED

3 critical fixes for India equity/index option trade construction:

1. **Strike snapping with `strike_interval` parameter** — India instruments use 5pt or 10pt steps; `snap_strike(price, strike_interval=5 or 10)` now respects market-specific tick sizes
2. **Fallback setup legs** — trend_continuation assessor for NIFTY/BANKNIFTY now falls back to `build_setup_trade_spec()` instead of returning None
3. **Equity long/short trade models** — `StructureType.EQUITY_LONG`, `EQUITY_SHORT` + builders for cash equity positions with ATR-based stops

**Wired:** `AssessorFactory.assess_trend_continuation()` and `MarketRegistry` instrument metadata.

**CLI:** `setup` command works for India tickers; `parse` correctly handles strike_interval.

---

### Crash Sentinel & Monitoring Actions

All pre-trade and post-entry monitoring now wired to provide actionable `TradeSpec` outputs:
- Entry failures → suggest alternative structures via `assess_*()` overflow paths
- Exit triggers → `closing_trade_spec` ready for immediate submission
- Stress alerts → urgency escalation tied to position monitoring

---

## Systematic Gaps — All DONE

All gaps tracked in `SYSTEMATIC_GAPS.md` are complete. 80+ items across 15 categories, all marked DONE.

### Original 9 Systematic Gaps (G01-G09)

| # | Gap | Implementation |
|---|-----|----------------|
| G01 | Deterministic adjustment | `recommend_action()` / `check_trade_health()` — single action, no menu |
| G02 | Execution quality validation | `validate_execution_quality(spec, quotes)` — GO/NO-GO decision |
| G03 | Entry time windows | `spec.entry_window_start/end` on every TradeSpec |
| G04 | Time-of-day urgency | `monitor_exit_conditions(time_of_day=)` — escalates after 15:00/15:30 |
| G05 | Overnight risk | Auto-invoked in `check_trade_health()` after 15:00; `health.overnight_risk` |
| G06 | Auto-select screening | `scan(tickers, min_score=0.6, top_n=10)` |
| G07 | Performance feedback loop | `TradeOutcome` → `compute_performance_report()`, `calibrate_weights()` — pure functions |
| G08 | Debug/commentary mode | `debug=True` on `detect()`, `snapshot()`, `assess()`, `rank()` → `result.commentary` |
| G09 | Data gap identification | `result.data_gaps` on every `RankedEntry` / `PlanTrade` |

### Signal Quality (SQ1-SQ10) — All DONE

IV rank wired into assessors and ranking pipeline, HMM staleness detection, POP with IV calibration, MR/breakout/earnings/momentum assessor overhauls, pivot points in levels.

### Technical Analysis (TA1-TA7) — All DONE

Fibonacci retracements, ADX, Donchian channels, Keltner channels, pivot points, daily VWAP, tradeable instruments in daily context (`MarketContext.tradeable`).

### Machine Learning (ML1-ML3) — All DONE

- **ML1 Drift detection:** `detect_drift(outcomes)` — rolling win rate per (regime, strategy) cell, `DriftAlert` with WARNING/CRITICAL severity
- **ML2 Thompson Sampling:** `build_bandits()`, `update_bandit()`, `select_strategies()` — Beta(α,β) distribution per (regime, strategy) cell
- **ML3 Threshold optimization:** `optimize_thresholds(outcomes, current)` — learns optimal IV rank cutoffs, POP minimums, score minimums from trade history

### Multi-Market (CR6-CR17) — All DONE

Dhan + Zerodha broker stubs, currency/timezone/lot_size handling, India strategy config, India regime detection (NIFTY/BANKNIFTY via yfinance aliases), timezone-aware entry windows, `MarketRegistry`, cache isolation (per-instance), lightweight init (lazy — no network in `__init__`), token expiry (`TokenExpiredError`, `is_token_valid()`), rate limits (`rate_limit_per_second`).

### Hedging (H1-H5) — All DONE

Currency conversion, portfolio exposure, same-ticker hedge assessment (regime-aware: R1=no hedge, R2=collar, R4=protective put/close), currency hedge assessment, cross-market P&L decomposition, CLI commands (`hedge`, `currency`, `exposure`).

### India Support (IN1-IN5) — All DONE

Equity/futures trade models (`StructureType.EQUITY_LONG/SHORT`, `FUTURES_LONG/SHORT`), cash equity trade spec builder with ATR-based stop/target, equity-first for India stocks (NIFTY/BANKNIFTY still get options), market-aware exit notes (European vs American settlement), LEAP blocked for India.

### Cross-Market + Macro (CM1, MC1-MC5) — All DONE

US-India correlation + gap prediction, bond market indicators (TNX/TLT), credit spread proxy (HYG/TLT), dollar strength (UUP), inflation expectations (TIP/TLT), macro dashboard with overall risk level and trading impact guidance.

### Risk Management (PF1, RM1-RM7, GF1-GF2, ST1) — All DONE

Position-aware portfolio filtering (7-step cascade), expected portfolio loss (ATR-based, regime-adjusted — NOT formal VaR), portfolio Greeks limits, strategy/directional/correlation concentration, drawdown circuit breaker, combined risk dashboard, trade gate framework (17 gates: BLOCK/SCALE/WARN), shadow portfolio + gate effectiveness tracking, stress testing (13 predefined scenarios: -1/-3/-5/-10%, VIX spike, flash crash, Black Monday, COVID, India crash, Fed surprise).

### Equity Research (EQ1-EQ3) — All DONE

Stock fundamental analysis (5 strategies: value/growth/dividend/quality_momentum/turnaround), stock screening across universe by composite or strategy-specific score, trader reference flow (`challenge/trader_stocks.py`, US + India, `--market` switch).

### Capital Deployment (CD1-CD7, WH1) — All DONE

Market valuation (deep_value → bubble zones), SIP planner (regime-adjusted, valuation-aware), asset allocation model (equity/gold/debt/cash), core holdings recommender (ETFs + stocks for US and India), rebalancing engine (drift > 5% threshold), LEAP vs stock comparison, wheel strategy analysis, wheel state machine (`decide_wheel_action()`).

### Futures (FT1-FT7) — All DONE

Basis analysis, term structure, roll decision engine (ROLL_FORWARD/HOLD/CLOSE), calendar spread analysis, futures options premium selling, margin estimation (10 US + 3 India instruments), complete futures research report.

### Vol Surface (VS1-VS4) — All DONE

IV percentile by expiration (60-day history), term structure percentile, skew history + percentile, calendar/diagonal assessors wired to use `iv_percentiles`.

### Other Completed Categories

- **Macro Research (MR1-MR8):** 22-asset scorecards, cross-asset correlations, macro regime classification, sentiment dashboard, FRED economic data, India research context, full research report with `research_note` + `key_signals`
- **Universe Scanner (UV1):** 10 presets, 85+ instruments, `registry.get_universe(preset, market, sector)`
- **Trade Quality (TQ1):** `trade_quality_score` (0-1, POP 40% + EV 30% + R:R 30%), `trade_quality` label (excellent/good/marginal/poor)
- **Pre-Market Scanner (PM1):** gap/volume spike/earnings catalyst detection; 4 strategies
- **Leg Execution (LEG1):** safe sequencing for single-leg markets; BUY protective legs first
- **Arbitrage/Pricing (ARB1):** `compute_theoretical_price()` — Black-Scholes for comparison only (not execution)

---

## eTrading Integration Status

See `ETRADING_INTEGRATION.md` for full guide (last updated 2026-03-17).

### MCP Tool Audit Summary (40 tools assessed)

| Category | Wired | Partial | Not Wired | Broken |
|----------|-------|---------|-----------|--------|
| Portfolio | 4 | 0 | 0 | 0 |
| Risk | 0 | 1 | 2 | 1 |
| Trading | 1 | 1 | 0 | 3 |
| Analytics | 2 | 0 | 2 | 0 |
| Intelligence | 3 | 1 | 0 | 1 |
| Stocks | 2 | 2 | 0 | 2 |
| Analysis | 1 | 0 | 0 | 3 |
| Admin | 3 | 0 | 0 | 0 |

### Known eTrading Issues (from 2026-03-17 audit)

- Scan → propose → deploy flow: broken (wrong bandit priors, 0/50 proposals approved)
- Macro dashboard indicators: all null
- Risk dashboard expected loss: all null
- Mark-to-market: broken (zero broker quotes in embedded mode)
- CLI command routing: most commands fall back to `status`
- Regime/Ranking/Adjustment APIs: not exposed as REST endpoints

### eTrading Must Still Wire (E1-E27 from SYSTEMATIC_GAPS.md)

**Immediate (APIs ready in MA):**
- E1-E2: Pass `iv_rank` to all assessor calls and `iv_rank_map` to `rank()`
- E3: Pass `time_of_day` to `check_trade_health()`
- E4-E5: Pass `debug=True`, store `result.commentary` in `decision_lineage` JSON, surface `result.data_gaps` in UI
- E6: Call `validate_execution_quality()` before every order submission
- E9: Use `ma.registry` for lot sizes and strategy routing (especially India)

**Requires eTrading DB + scheduling (E14-E21):**
- TradeOutcome table + construction on close
- Bandit params update on every close
- Drift detection job (daily pre-market)
- Weight calibration (weekly)
- POP factor calibration (weekly)
- Threshold optimization (monthly)

---

## Module Inventory

### service/ — Workflow Services

| Module | Status | Description |
|--------|--------|-------------|
| `service/analyzer.py` | STABLE | `MarketAnalyzer` facade — wires all services |
| `service/regime.py` + `regime_service.py` | STABLE | HMM-based regime detection (R1-R4) |
| `service/technical.py` | STABLE | Technical indicators; broker-first ORB via DXLink |
| `service/ranking.py` | STABLE | `OpportunityRanker.rank()` — 11 strategy types |
| `service/trading_plan.py` | STABLE | Daily trading plan generation with day verdict |
| `service/adjustment.py` | STABLE | Trade adjustment analyzer (broker quotes when available) |
| `service/vol_surface.py` | STABLE | Vol surface service |
| `service/opportunity.py` | STABLE | Opportunity orchestration |
| `service/option_quotes.py` | STABLE | Broker-first quotes; yfinance for chain structure only |
| `service/context.py` | STABLE | Market context assessment |
| `service/screening.py` | STABLE | Universe screening |
| `service/levels.py` | STABLE | S/R levels with pivot points |
| `service/macro.py` | STABLE | Macro indicators + FOMC/RBI calendar |
| `service/entry.py` | STABLE | Entry confirmation checks |
| `service/exit.py` | STABLE | Exit signal generation |
| `service/strategy.py` | STABLE | Strategy selection |
| `service/fundamental.py` | STABLE | Fundamental analysis |
| `service/universe.py` | STABLE | Universe scanning |
| `service/phase.py` | STABLE | Market phase detection |
| `service/intraday.py` | STABLE | Intraday analysis |
| `service/black_swan.py` | STABLE | Black swan event detection |

### features/ — Feature Computers

| Module | Status | Description |
|--------|--------|-------------|
| `features/technicals.py` | STABLE | Core OHLCV features; re-exports VCP, smart money patterns |
| `features/ranking.py` | STABLE | Regime-strategy alignment matrices (11 strategies) |
| `features/screening.py` | STABLE | Screening filter functions |
| `features/levels.py` | STABLE | S/R level computation |
| `features/vol_surface.py` | STABLE | `compute_vol_surface()` pure function |
| `features/pipeline.py` | STABLE | Feature pipeline |
| `features/orb.py` | STABLE | ORB analysis re-export |
| `features/black_swan.py` | STABLE | Black swan indicators |
| `features/entry_levels.py` | STABLE | 6 entry intelligence functions: strike proximity, skew-optimal strikes, limit order price, pullback alert, entry score, entry validation |
| `features/exit_intelligence.py` | NEW (2026-03-20) | Regime-contingent stops, trailing profit targets, theta decay curve |
| `features/dte_optimizer.py` | NEW (2026-03-20) | `compute_optimal_dte()` from vol surface term structure |
| `features/decision_audit.py` | NEW (2026-03-20) | `audit_decision()` — 4-level leg/trade/portfolio/risk scoring |
| `features/crash_sentinel.py` | NEW (2026-03-20) | `assess_crash_sentinel()` — 9-indicator crash early-warning |
| `features/position_sizing.py` | EXPANDED (2026-03-20) | Correlated Kelly, margin-regime interaction, `compute_position_size()` unified entry point |
| `features/patterns/vcp.py` | STABLE | VCP pattern detection |
| `features/patterns/smart_money.py` | STABLE | Order Blocks, FVGs, Smart Money Concepts |
| `features/patterns/orb.py` | STABLE | Opening Range Breakout analysis |

### opportunity/ — Assessors

| Module | Status | Description |
|--------|--------|-------------|
| `opportunity/setups/breakout.py` | STABLE | Breakout setup assessor |
| `opportunity/setups/momentum.py` | STABLE | Momentum setup assessor |
| `opportunity/setups/mean_reversion.py` | STABLE | Mean reversion setup assessor |
| `opportunity/setups/orb.py` | STABLE | ORB setup assessor (intraday ORBData required) |
| `opportunity/option_plays/iron_condor.py` | STABLE | #1 income strategy; R1 ideal, R2 acceptable |
| `opportunity/option_plays/iron_butterfly.py` | STABLE | ATM straddle + wings; R2 ideal |
| `opportunity/option_plays/calendar.py` | STABLE | Front/back month IV differential; IV percentiles wired |
| `opportunity/option_plays/diagonal.py` | STABLE | Calendar with different strikes; IV percentiles wired |
| `opportunity/option_plays/ratio_spread.py` | STABLE | Buy 1 ATM / sell 2 OTM; naked leg warning |
| `opportunity/option_plays/zero_dte.py` | STABLE | 0DTE with Iron Man strategy + full ORB integration |
| `opportunity/option_plays/leap.py` | STABLE | LEAP assessor; blocked for India instruments |
| `opportunity/option_plays/earnings.py` | STABLE | Earnings play assessor |
| `opportunity/option_plays/_trade_spec_helpers.py` | STABLE | Shared strike snapping, DTE matching, leg building |

### validation/ — NEW (2026-03-19)

| Module | Status | Description |
|--------|--------|-------------|
| `validation/__init__.py` | COMPLETE | Package exports |
| `validation/models.py` | COMPLETE | `CheckResult`, `Severity`, `Suite`, `ValidationReport` |
| `validation/profitability_audit.py` | COMPLETE | `check_commission_drag`, `check_fill_quality`, `check_margin_efficiency` |
| `validation/stress_scenarios.py` | COMPLETE | `check_gamma_stress`, `check_vega_shock`, `check_breakeven_spread` |
| `validation/daily_readiness.py` | COMPLETE | `run_daily_checks()` (7 checks), `run_adversarial_checks()` (3 checks) |

### broker/ — Broker Integrations

| Module | Status | Description |
|--------|--------|-------------|
| `broker/base.py` | STABLE | ABCs: `BrokerSession`, `MarketDataProvider`, `MarketMetricsProvider`, `AccountProvider`, `WatchlistProvider` |
| `broker/tastytrade/` | STABLE | Full TastyTrade: session, market_data, dxlink, symbols, metrics, account, watchlist |
| `broker/zerodha/` | COMPLETE | Full Zerodha Kite Connect: live chains, candles, computed IV rank, account, instrument master |
| `broker/dhan/` | COMPLETE | Full Dhan implementation (India) — was stub, now complete |
| `broker/alpaca/` | COMPLETE | Alpaca Markets integration (US equities + options) |
| `broker/ibkr/` | COMPLETE | Interactive Brokers integration |
| `broker/schwab/` | COMPLETE | Charles Schwab integration |

### models/ — Data Models

| Module | Status | Description |
|--------|--------|-------------|
| `models/opportunity.py` | STABLE | `LegAction`, `LegSpec`, `StructureType`, `OrderSide`, `TradeSpec` |
| `models/ranking.py` | STABLE | `StrategyType` (11 entries), `RankedEntry`, `RankingResult` |
| `models/regime.py` | STABLE | `RegimeState`, `RegimeResult` |
| `models/quotes.py` | STABLE | `OptionQuote`, `QuoteSnapshot`, `MarketMetrics` |
| `models/adjustment.py` | STABLE | `AdjustmentType`, `PositionStatus`, `TestedSide`, `AdjustmentAnalysis` |
| `models/trading_plan.py` | STABLE | `DayVerdict`, `PlanHorizon`, `PlanTrade`, `DailyTradingPlan` |
| `models/vol_surface.py` | STABLE | `VolatilitySurface`, `TermStructurePoint`, `SkewSlice` |
| `models/universe.py` | STABLE | `UniverseFilter`, `UniverseCandidate`, `UniverseScanResult` |
| `models/feedback.py` | STABLE | `TradeOutcome`, `TradeExitReason`, `StrategyBandit`, `DriftAlert`, `ThresholdConfig` |
| `models/technicals.py` | STABLE | `TechnicalSnapshot` (Fibonacci, ADX, Donchian, Keltner, pivots, VWAP) |
| `models/transparency.py` | STABLE | Debug/commentary trace models |
| `models/context.py` | STABLE | `MarketContext`, `InstrumentAvailability` |
| `models/exit.py` | EXPANDED (2026-03-20) | `RegimeStop`, `TrailingProfitTarget`, `ThetaDecayCurve`, `StrategySwitchRecommendation` |
| `models/entry.py` | EXPANDED (2026-03-20) | `StrikeProximityResult`, `EntryLevelScore`, `PullbackAlert`, `EntryValidation`, `IVRankQuality` |
| `models/decision_audit.py` | NEW (2026-03-20) | `DecisionAudit`, `LegAudit`, `TradeAudit`, `PortfolioAudit`, `RiskAudit` |
| `models/sentinel.py` | NEW (2026-03-20) | `SentinelReport`, `SentinelSignal` (GREEN/YELLOW/ORANGE/RED/BLUE), indicator detail |
| (other models) | STABLE | entry, exit_plan, levels, macro, phase, intraday, instrument, data, fundamentals, black_swan, learning |

### data/ — Data Layer

| Module | Status | Description |
|--------|--------|-------------|
| `data/service.py` | STABLE | `DataService` — provider abstraction |
| `data/registry.py` | STABLE | Instrument registry (lot sizes, market hours, strategy availability) |
| `data/providers/yfinance.py` | STABLE | OHLCV, options chain, ticker aliases (SPX→^GSPC etc.) |
| `data/providers/cboe.py` | STABLE | CBOE data provider |
| `data/providers/fred.py` | STABLE | FRED economic data |
| `data/providers/tastytrade.py` | STABLE | TastyTrade REST data provider |
| `data/cache/parquet_cache.py` | STABLE | Parquet cache with staleness detection; 4hr threshold for snapshot data |
| `data/exceptions.py` | STABLE | Typed exceptions — distinguishes "no data exists" from "fetch failed" |

### macro/ — Calendar + Events

| Module | Status | Description |
|--------|--------|-------------|
| `macro/expiry.py` | STABLE | `ExpiryType`, monthly OpEx, VIX settlement, quad witching detection |
| `macro/calendar.py` | STABLE | Economic calendar integration |
| `macro/_fomc_dates.py` | STABLE | FOMC meeting dates |
| `macro/_rbi_dates.py` | STABLE | RBI meeting dates (India) |
| `macro/_econ_schedule.py` | STABLE | CPI/NFP/PCE schedule |

### Top-Level Modules

| Module | Status | Description |
|--------|--------|-------------|
| `trade_lifecycle.py` | STABLE | 10 pure-function APIs: `compute_income_yield`, `estimate_pop`, `check_income_entry`, `monitor_exit_conditions`, `check_trade_health`, `get_adjustment_recommendation`, `aggregate_greeks`, `filter_trades_by_account`, `compute_breakevens`, `align_strikes_to_levels` |
| `trade_spec_factory.py` | STABLE | `create_trade_spec()`, builders, DXLink conversion (`from_dxlink_symbols`, `to_dxlink_symbols`) |
| `risk.py` | STABLE | Portfolio risk functions (`filter_trades_with_portfolio`, `estimate_portfolio_loss`) |
| `gate_framework.py` | STABLE | `evaluate_trade_gates()` — 17 gates, BLOCK/SCALE/WARN tiers; `analyze_gate_effectiveness()` |
| `performance.py` | STABLE | `compute_performance_report()`, `compute_sharpe()`, `compute_drawdown()`, `compute_regime_performance()` |
| `arbitrage.py` | STABLE | `compute_theoretical_price()` — Black-Scholes for comparison only (not execution) |
| `capital_deployment.py` | STABLE | SIP planner, asset allocation, core holdings, rebalancing |
| `cross_market.py` | STABLE | US-India correlation, gap prediction |
| `currency.py` | STABLE | Currency conversion, FX risk, portfolio exposure |
| `equity_research.py` | STABLE | Stock fundamental analysis (5 strategies), screening |
| `execution_quality.py` | STABLE | `validate_execution_quality()` |
| `futures_analysis.py` | STABLE | Basis, term structure, roll decision, margin estimation |
| `hedging.py` | STABLE | Same-ticker hedges, currency hedges |
| `leg_execution.py` | STABLE | `plan_leg_execution()` — safe sequencing for single-leg markets |
| `macro_indicators.py` | STABLE | Bond, credit spread, dollar, inflation indicators |
| `macro_research.py` | STABLE | `generate_research_report()` — 22 assets, full macro report |
| `premarket_scanner.py` | STABLE | `scan_premarket()` — gap/volume/earnings alerts, 4 strategies |
| `registry.py` | STABLE | `MarketRegistry` — instruments, 10 universe presets, 85+ instruments |
| `stress_testing.py` | STABLE | `run_stress_test()`, `run_stress_suite()` — 13 predefined scenarios |
| `vol_history.py` | STABLE | IV history and percentile computation |
| `wheel_strategy.py` | STABLE | `analyze_wheel_strategy()`, `decide_wheel_action()` |
| `hmm/` | STABLE | HMM model fitting, inference, feature computation |
| `fundamentals/` | STABLE | Earnings fetching (skips ETFs/indexes to avoid yfinance noise) |
| `challenge/` | REFERENCE ONLY | `trader.py`, `trader_stocks.py`, `portfolio.py` — do NOT import from eTrading |

---

## CLI Command Inventory (80+ `do_*` methods)

Note: Current count in `cli/interactive.py` is 80+ `do_*` methods (including `do_quit` / `do_exit`).

### Trading Intelligence
| Command | Description |
|---------|-------------|
| `context` | Market context assessment (regime, phase, tradeable instruments) |
| `analyze` | Full analysis for a ticker |
| `screen` | Universe screening |
| `entry` | Entry confirmation check |
| `strategy` | Strategy selection for current regime |
| `exit_plan` | Exit plan generation |
| `rank` | Rank tickers by opportunity score (accepts `--watchlist`, `--account`) |
| `plan` | Daily trading plan (horizon-bucketed, chase limits, expiry notes) |
| `opportunity` | Opportunity assessment |
| `setup` | Price-based setups (breakout, momentum, mr, orb, all) |
| `validate` | Daily pre-trade profitability gate (7 daily + 3 adversarial checks) |
| `entry_analysis` | **NEW** — Entry-level intelligence: strike proximity, skew-optimal strikes, limit price, pullback |
| `kelly` | **NEW** — Kelly criterion position sizing (correlated Kelly + margin-regime interaction) |
| `optimal_dte` | **NEW** — DTE optimizer from vol surface term structure |
| `exit_intelligence` | **NEW** — Regime-contingent stops, trailing profit targets, theta decay curve |
| `audit` | **NEW** — 4-level decision audit (leg/trade/portfolio/risk scoring) |
| `sentinel` | **NEW** — Crash sentinel signal (GREEN/YELLOW/ORANGE/RED/BLUE) |

### Regime & Technical
| Command | Description |
|---------|-------------|
| `regime` | Regime detection (accepts `--watchlist`) |
| `technicals` | Technical snapshot (indicators, patterns, VWAP) |
| `levels` | Support/resistance levels with pivot points |
| `macro` | Macro context (FOMC/CPI/NFP calendar, expiry events) |
| `macro_indicators` | Bond/credit/dollar/inflation macro dashboard |
| `stress` | Black swan / stress event check |
| `vol` | Volatility surface |

### Trade Lifecycle
| Command | Description |
|---------|-------------|
| `yield` | Income yield computation |
| `pop` | Probability of profit estimate |
| `income_entry` | Income entry quality check |
| `parse` | Parse DXLink option symbol |
| `monitor` | Monitor exit conditions for open position |
| `health` | Trade health check (overnight risk, urgency escalation) |
| `greeks` | Aggregate Greeks for a position |
| `size` | Position sizing |

### Broker & Quotes
| Command | Description |
|---------|-------------|
| `adjust` | Adjustment analysis for an open position |
| `balance` | Account balance and buying power |
| `quotes` | Option chain with bid/ask/Greeks (requires broker) |
| `broker` | Broker connection status |
| `quality` | Execution quality validation |

### Risk
| Command | Description |
|---------|-------------|
| `risk` | Combined risk dashboard |
| `overnight` | Overnight risk assessment |
| `stress_test` | Stress test suite (13 scenarios) |
| `margin` | Margin estimation |
| `sharpe` | Sharpe ratio from trade outcomes |
| `drawdown` | Drawdown analysis |

### Machine Learning / Feedback
| Command | Description |
|---------|-------------|
| `performance` | Performance report from trade outcomes |
| `drift` | Drift detection (regime/strategy win rate degradation) |
| `bandit` | Thompson Sampling bandit strategy selection |

### Watchlist & Universe
| Command | Description |
|---------|-------------|
| `watchlist` | List/show broker watchlists |
| `universe` | Scan + filter broker universe |
| `scan_universe` | Scan registry universe presets |
| `registry` | MarketRegistry instrument lookup |

### Hedging & Currency
| Command | Description |
|---------|-------------|
| `hedge` | Same-ticker hedge assessment |
| `currency` | Currency conversion |
| `exposure` | Portfolio currency exposure |

### Cross-Market & Research
| Command | Description |
|---------|-------------|
| `crossmarket` | US-India correlation analysis |
| `india_context` | India market context |
| `research` | Macro research report (daily/weekly/monthly) |

### Execution
| Command | Description |
|---------|-------------|
| `leg_plan` | Leg execution sequencing for single-leg markets |

### Equity Research
| Command | Description |
|---------|-------------|
| `stock` | Stock fundamental analysis |
| `stock_screen` | Stock screening across universe |

### Capital Deployment
| Command | Description |
|---------|-------------|
| `valuation` | Market valuation (deep_value → bubble zones) |
| `deploy` | Systematic deployment planner (SIP) |
| `allocate` | Asset allocation model |
| `rebalance` | Portfolio rebalance check |
| `leap_vs_stock` | LEAP vs stock comparison |
| `wheel` | Wheel strategy analysis |

### System
| Command | Description |
|---------|-------------|
| `quit` / `exit` | Exit REPL |

---

### Desk Management / Capital Allocation (2026-03-21) — COMPLETED

6 pure-function APIs in `capital_allocation.py` (or `desk_management.py`) for structured capital deployment:

| API | Description |
|-----|-------------|
| `recommend_desk_structure(account_balance, trading_style)` | Returns `DeskRecommendation` — 4-desk default (0DTE/income/directional/hedge) with capital splits |
| `suggest_desk_for_trade(trade_spec, desks, existing_positions_by_desk)` | Returns best desk for a new trade (DTE fit, strategy type, capacity, correlation) |
| `compute_desk_risk_limits(desk_key, ...)` | Regime-adjusted position limits: max positions, max single pct, circuit breaker |
| `compute_instrument_risk(ticker, instrument_type, position_value, regime_id)` | Per-instrument risk: max_loss, expected_loss_1d, margin_required, risk_category |
| `evaluate_desk_health(desk_key, closed_trades)` | Win rate, Sharpe, avg hold time, strategy efficiency from closed trades |
| `rebalance_desks(desks, account_balance, regime_id)` | Drift detection + reallocation recommendations when actual capital drifts >5% from target |

Asset class hierarchy: asset class → risk type → desks. Income and directional have sub-desks.

**CLI:** `desk` command — shows desk structure, capital allocation, regime-adjusted limits.

---

### Demo Portfolio System (2026-03-21) — COMPLETED

Paper-trading simulation without requiring a broker connection:

- **`--demo` flag** on CLI startup — initializes a virtual $50K portfolio with simulated positions
- **`portfolio` command** — shows demo portfolio with positions, P&L, Greeks (simulated)
- **`trade` command** — executes a demo trade (records in memory, no broker order)
- **`close_trade` command** — closes a demo position, records outcome for ML feedback

Demo portfolio flows through the full MA analysis stack: regime detection, entry gates, risk checks, exit monitoring. Outcomes can be used with `calibrate_weights()` to seed the learning loop without real capital.

---

### CSP/Wheel Workflow + Assignment Risk (2026-03-21) — COMPLETED

- **CSP/wheel workflow** — `decide_wheel_action()` extended with covered call assessment phase; full state machine from cash-secured put → assignment → covered call → called away
- **Covered call analysis** — `assess_covered_call(ticker, cost_basis, regime_id)` returns optimal strike, DTE, and annualized yield given current position cost basis
- **Assignment risk warning** — options expiry behavior documented and checked per market:
  - US options: American-style, can be assigned early (especially dividend dates for calls)
  - India options: European-style, cash-settled, no early assignment risk
  - `TradeSpec.assignment_style` field: `"american"` or `"european"` per instrument
- **`check_assignment_risk(trade_spec, days_to_expiry, stock_yield)` — flags early assignment risk for US short calls near dividend dates

**CLI:** `wheel` command extended; `csp` command for standalone CSP analysis.

---

### Cash vs Margin Analytics + Interest Rate Risk (2026-03-21) — COMPLETED

- **Cash vs margin analytics** — `compute_margin_efficiency(trade_spec, cash_available, margin_rate)` compares cost of capital (margin interest) vs trade yield; surfaces when trade yield < margin cost
- **Structure-based margin buffers** — different buffer multipliers by structure type: IC=1.0× (defined), ratio_spread=2.0× (undefined exposure), straddle=1.5×
- **Interest rate risk APIs** — `compute_interest_rate_sensitivity(trade_spec, rate_change_bps)`: how much does portfolio cost change per 25bps rate move; `get_rho_exposure(trade_spec, quotes)`: aggregate rho from broker Greeks

**CLI:** `margin` command extended with cash_vs_margin toggle; `interest_risk` command.

---

### BYOD Adapters (2026-03-21) — COMPLETED

Bring-Your-Own-Data adapters for users without supported brokers:

- **`broker/adapters/csv_adapter.py`** — loads positions and quotes from CSV files; maps column names to MA's `OptionQuote`/`QuoteSnapshot` models
- **`broker/adapters/dict_adapter.py`** — accepts Python dicts; useful for API callers sending data in custom format
- **`broker/adapters/ibkr_skeleton.py`** — skeleton for Interactive Brokers TWS API (placeholder for future full implementation)
- **`broker/adapters/schwab_skeleton.py`** — skeleton for Schwab API (placeholder for future full implementation)

All adapters implement `MarketDataProvider` ABC — plug into `MarketAnalyzer` the same way as real brokers.

**CLI:** `--data-file path/to/quotes.csv` startup flag loads CSV adapter.

---

### Open Source Infrastructure (2026-03-21) — COMPLETED

Repository made OSS-ready:

- **README.md** — full project README with quick-start, feature overview, philosophy, contributing guide
- **CONTRIBUTING.md** — development setup, PR process, test requirements, code style
- **`.github/workflows/ci.yml`** — GitHub Actions CI: test on Python 3.12, lint, type-check
- **`.github/ISSUE_TEMPLATE/`** — bug report and feature request templates
- **SECURITY.md** — responsible disclosure policy, credential handling guidelines
- **CODE_OF_CONDUCT.md** — Contributor Covenant v2.1

---

## Known Limitations / Tech Debt

### Thin Implementations (functional but basic)

- **Setup signals** — `opportunity/setups/breakout.py`, `momentum.py`, `mean_reversion.py` use basic indicators; would benefit from multi-factor scoring (volume confirmation, sector relative strength, options flow)
- **Option play logic** — `opportunity/option_plays/leap.py` and `earnings.py` are thin; need deeper fundamental integration (earnings growth rate for LEAP scoring, vol crush magnitude history for earnings)
- **`check_vega_shock`** — uses `iv_spike_pct * 1.2` as a conservative approximation; actual vega impact should use broker Greeks when available

### ML / Learning (not started in production)

- **ML regime validation** — no system to track regime predictions against actual price behavior; HMM weights are not auto-retrained
- **POP calibration in production** — `calibrate_pop_factors(outcomes)` is implemented as a pure function but requires eTrading to supply trade outcome history; the live feedback loop is not running

### Documentation

- **USER_MANUAL.md** — 7 new CLI commands from 2026-03-20 not yet documented: `entry_analysis`, `kelly`, `optimal_dte`, `exit_intelligence`, `audit`, `sentinel`, and the expanded `validate`
- **SYSTEMATIC_GAPS.md** — test count header is stale; actual count is now 1715
- **MEMORY.md** — CLI command count is stale; actual count is now 67

### eTrading Integration Gaps

- Most MA APIs are fully implemented but not yet wired in eTrading (see E1-E27 in SYSTEMATIC_GAPS.md)
- Scan → propose → deploy flow is broken in eTrading (wrong bandit priors)
- REST endpoint exposure for Regime/Ranking/Adjustment APIs still needed
- Mark-to-market broken in eTrading embedded mode (zero broker quotes)

### Architecture Notes

- `challenge/` contains reference implementations only — eTrading must NOT import from it
- `rank()` output is NOT safe to execute directly — eTrading MUST call `filter_trades_with_portfolio()` and `evaluate_trade_gates()` before execution
- `risk.py` function `estimate_portfolio_loss()` is ATR-based, NOT formal VaR; use `run_stress_suite()` for scenario analysis
- Dhan broker is now fully implemented (was a stub as of 2026-03-20; completed 2026-03-21)
- IBKR and Schwab have skeleton adapters (pattern established, full TWS/API wiring is P2)
