# eTrading ↔ market_analyzer Integration Guide
*Last updated: 2026-03-21 | Broker: tastytrade (data mode) | Server: localhost:8080*

---

## Contents

1. [Status Summary](#1-status-summary)
2. [Priority Fix List](#2-priority-fix-list)
3. [MCP Tool Audit (40 tools)](#3-mcp-tool-audit)
4. [Feature Integration Status](#4-feature-integration-status)
5. [Risk API Guide](#5-risk-api-guide)
6. [Expected Value (EV) Guide](#6-expected-value-ev-guide)
7. [Adjustment Integration Guide](#7-adjustment-integration-guide)
8. [SaaS Broker Authentication Guide](#8-saas-broker-authentication-guide)
9. [New Trading Intelligence APIs (March 2026)](#9-new-trading-intelligence-apis-march-2026)
10. [Decision Audit Framework (March 20)](#10-decision-audit-framework-march-20)
11. [March 20 Addenda — Behavior Changes](#11-march-20-addenda--behavior-changes)
12. [Crash Sentinel — Market Health Monitoring](#12-crash-sentinel--market-health-monitoring)
13. [Context-Aware Calculations — Full Mode Checklist](#13-context-aware-calculations--full-mode-checklist)
14. [MonitoringAction with Closing TradeSpec](#14-monitoringaction-with-closing-tradespec)
15. [Position Stress Monitoring API](#15-position-stress-monitoring-api)
16. [India TradeSpec Fixes (P0-3 Done)](#16-india-tradespec-fixes-p0-3-done)
17. [Stock Screener Data Quality](#17-stock-screener-data-quality)
18. [All Recommendations Return TradeSpec](#18-all-recommendations-return-tradespec)
19. [Supported Brokers — What eTrading Needs to Know](#19-supported-brokers--what-etrading-needs-to-know)
20. [India Market: eTrading Delayed Data Service (Planned)](#20-india-market-etrading-delayed-data-service-planned)
21. [Desk Management APIs (March 21, 2026)](#21-desk-management-apis-march-21-2026)

---

## 1. Status Summary

### MCP Tool Results

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

### Feature Coverage

| Category | Status |
|----------|--------|
| Broker connection | ✅ Working |
| Cross-market analysis | ✅ Working |
| Portfolio/position sync | ✅ Working |
| Macro research report | ✅ Working |
| Deployment plan structure | ✅ Working |
| Scan → propose → deploy flow | ❌ Broken (wrong bandit priors, 0/50 proposals approved) |
| Macro dashboard indicators | ❌ All null |
| Risk dashboard (expected loss) | ❌ All null |
| Mark-to-market | ❌ Broken (zero broker quotes) |
| CLI command routing | ❌ Most commands fall back to `status` |
| Regime/Ranking/Adjustment APIs | ❌ Not exposed as REST endpoints |
| Stock screener data quality | ❌ Wrong OHLCV period, wrong dividend yield |

---

## 2. Priority Fix List

### 🔴 P0 — Blocking (system cannot trade without these)

| # | Fix | Root Cause | Impact |
|---|-----|-----------|--------|
| 1 | **Fix bandit strategy priors** | Thompson Sampling arms not seeded from MA's `REGIME_STRATEGY_ALIGNMENT` matrix — R1 selects `earnings, diagonal, leap` instead of `iron_condor, straddle, iron_butterfly` | 0/50 proposals ever approved — scan runs but all trades rejected |
| 2 | **Make scan async** | Scan takes 2+ min — synchronous HTTP request times out. Needs background task + polling endpoint | `scan` tool returns no response |
| 3 | **Fix TradeSpec missing from assessors** | Some assessors (e.g. trend_continuation for NIFTY) run but produce no legs — "No trade_spec / no legs" rejection | Proposals rejected even when bandit is correct |
| 4 | **Fix mark-to-market** | `[mark_to_market] Zero quotes returned for 1 symbols` — DXLink quote fetch returning empty for BAC equity | All P&L, current_price, Greeks on open positions are stale |
| 5 | **Wire risk dashboard** | `compute_risk_dashboard()` not called with real `PortfolioPosition` objects | `expected_loss` always null — drawdown gate never fires |

### 🟠 P1 — High (risk management incomplete)

| # | Fix | Root Cause | Impact |
|---|-----|-----------|--------|
| 6 | **Wire adjustment recommendations** | `ma.adjustment.recommend_action()` not called in monitoring loop | `health` tool shows no adjustments — no position protection |
| 7 | **Fix overnight risk for equities** | `assess_overnight_risk()` not called for equity_long positions | BAC overnight gap risk not assessed |
| 8 | **Fix macro dashboard** | OHLCV for TNX, TLT, HYG, UUP, TIP not fetched and passed to `compute_macro_dashboard()` | bond_market, credit_spreads, dollar_strength, inflation_expectations all null |
| 9 | **Wire equity exit conditions** | `monitor_exit_conditions()` not called for equity_long positions | No stop loss or profit target monitoring for BAC |
| 10 | **Wire trade gates** | `evaluate_trade_gates()` not called before any order submission | No BLOCK/SCALE/WARN protection at entry |
| 11 | **Fix deployment plan capital** | Hardcoded `total_capital: 50000.0` instead of `portfolio.total_equity` ($32,261) | Wrong sizing for real account |

### 🟡 P2 — Medium (data quality / model mismatches)

| # | Fix | Root Cause |
|---|-----|-----------|
| 12 | **`valuation` broken** | eTrading calls `get_ohlcv(ticker, period='1y')` — MA expects `days=365` |
| 13 | **`deploy-plan` broken** | `MonthlyAllocation.equity` field renamed in MA — eTrading not updated |
| 14 | **`stock-screen` broken** | `EquityScreenResult.total_passed` renamed — eTrading not updated |
| 15 | **`allocate` broken** | `AssetAllocation.equity_sub_split` renamed — eTrading not updated |
| 16 | **`stock` render error** | `None` field being string-formatted — add null guard |
| 17 | **ML strategy rankings wrong** | Thompson Sampling priors not seeded from `REGIME_STRATEGY_ALIGNMENT` — R4 recommending diagonal/earnings (wrong, should be defined-risk only) |
| 18 | **Fix stock screener OHLCV period** | QQQ showing 452% daily return, ATR 13% — wrong lookback window |
| 19 | **Fix dividend yield calculation** | JNJ 214%, JPM 210% — `dividendYield` from yfinance is already a ratio, don't divide again |
| 20 | **Fetch VIX on startup** | VIX not fetched — `data_service.get_ohlcv("VIX")` missing from startup cycle |
| 21 | **Pass `iv_rank_map` to ranking** | Broker is connected and `get_metrics(ticker)` returns IV rank, but it's never passed to `ma.ranking.rank()` |
| 22 | **Fix deployment plan acceleration** | Pass live regime from `ma.regime.detect("SPY")` to `plan_deployment()` — all 12 months identical, regime-based acceleration never triggers |

### 🟢 P3 — Lower (completeness)

| # | Fix | Impact |
|---|-----|--------|
| 23 | **Fix `strategies`, `levels`, `hedge` parameter mismatch** | MCP tool definition uses `id` param but CLI handler expects positional arg — returns usage string instead of executing |
| 24 | **Add `connect` to MCP tools** | `connect` only in CLI handler — broker cannot be connected via webapp |
| 25 | **Add `/api/v2/context`** | `ma.context.assess()` not exposed — trading allowed / position size factor never shown |
| 26 | **Add `/api/v2/black-swan`** | `ma.black_swan.alert()` not exposed — black swan critical state never surfaced to UI |
| 27 | **Fix CLI command router** | `rank`, `plan`, `context`, `adjust`, `regime`, `health`, `technicals`, `levels`, `screen` all fall back to `status` — 30+ commands unreachable from chat |
| 28 | **Research report stale** | Cache TTL too long — report from 2026-03-16 served on 2026-03-17 |
| 29 | **Wire position sizing** | `spec.position_size(capital, risk_pct)` not called — all trades hardcoded at 1 contract |

---

## 3. MCP Tool Audit

### PORTFOLIO

#### `positions` — ✅ WIRED
- Shows BAC equity_long, P&L -$4,788, Delta +100
- Greeks shown per position, health status and desk assignment present
- **Gap:** `current_price` null at position level — mark not running (see mark-to-market issue)

#### `portfolios` — ✅ WIRED
- Real account data: equity $32,262, cash $27,531, buying_power shown, Greeks totals present
- **Gap:** `expected_loss` not computed — `compute_risk_dashboard()` not wired with real positions

#### `capital` — ✅ WIRED
- Tastytrade 5WZ78765 at 14.7% deployed, $27,531 idle
- **Gap:** Capital: $0 initial — initial capital not set from broker sync

#### `greeks` — ✅ WIRED
- Delta +100.0 / 500 limit (20% used), limit thresholds wired correctly
- What-If Portfolio section present

---

### RISK

#### `risk` — ⚠️ PARTIAL
- `risk_dashboard: None` — `compute_risk_dashboard()` not called with real `PortfolioPosition` objects
- `expected_loss`: null, macro regime: null
- trades_today: 1, halted: False — these work

#### `health` — ⚠️ PARTIAL
- Reports "1 checked, 0 healthy, 0 need action"
- **Gap:** equity_long health check uses options adjustment logic — should show N/A for non-option positions
- **MA API not wired:** `ma.adjustment.recommend_action()` — no adjustment shown for any position

#### `overnight` — ❌ NOT WIRED
- Returns "No open positions or no overnight risk detected" despite 1 open BAC position
- **MA API not wired:** `assess_overnight_risk()` — not called for equity positions

#### `syshealth` — ❌ BROKEN
- Status: DEGRADED
- Error: `[mark_to_market] Zero quotes returned for 1 symbols — all trades UNMARKABLE`
- **Root cause:** BAC mark-to-market failing — DXLink quote fetch returning zero quotes
- All P&L, current_price, Greeks on open positions are stale

---

### TRADING

#### `scan` — ⚠️ PARTIAL (slow, 2+ min)
- Scan **does complete** but takes >2 minutes — HTTP request times out before response returns
- Background run confirmed: Scout populates 37 regime, 39 technicals, 39 opportunities, 39 levels
- Phase 1 screen: 12 candidates; Phase 2 rank: 40 ranked from 8 candidates; Phase 3: 10 equity picks
- **Critical gap:** `Bandits: R1 → earnings, diagonal, leap` — **WRONG for R1**
  - R1 (Low-Vol Mean Reverting) should select: iron_condor, straddle, iron_butterfly
  - Thompson Sampling priors not seeded from MA's `REGIME_STRATEGY_ALIGNMENT` matrix
- **Fix needed:** (1) async scan with polling, (2) fix bandit strategy priors per regime

#### `propose` — ❌ BROKEN (0/50 approved)
- Returns: 0 proposed, 50 rejected
- **Root cause 1:** Bandits select wrong strategies for R1 → assessors return NO_GO for earnings/diagonal/leap in R1
- **Root cause 2:** `No trade_spec / no legs` for NIFTY trend_continuation — assessor produces no legs
- `POST /api/v2/ranking` directly confirms MSFT IC score=0.739 "go" — the opportunity exists but can't get through the pipeline

#### `deploy` — ❌ BROKEN (no proposals to deploy)
- "No proposals to deploy" — upstream propose never approves any trades
- **MSFT Iron Condor:** Could NOT be booked via scan flow
- **Fix needed:** Fix bandit priors first, then scan→propose→deploy will flow

#### `mark` — ✅ WIRED (structure correct, data broken)
- Table structure correct: Underlying, Strategy, Entry, Current, P&L, Health, Legs columns
- **BUT:** All rows empty — mark failing due to zero broker quotes (syshealth error)

#### `exits` — ✅ WIRED
- "All 0 open trades within limits" — correct for BAC equity (no DTE/profit target exit rules)
- **Gap:** equity_long has no exit conditions monitored — no stop loss, profit target checks

#### `close` — NOT TESTED (no triggered exits)

---

### ANALYTICS

#### `perf` — ✅ WIRED
- Desk structure correct: desk_0dte ($10K), desk_medium ($15K), etc.
- "No closed trades yet" — expected on fresh system

#### `explain` — NOT TESTED (need trade ID)

#### `learn` — ✅ WIRED
- ML gate thresholds visible: pop_min=0.5, score_min=0.6, ic_iv_rank_min=15.0
- Thompson Sampling rankings per regime present (R1-R4)
- **Gap:** Rankings wrong for income-first philosophy:
  - R1 top: mean_reversion, leap, earnings (should be iron_condor, straddle)
  - R2 top: ratio_spread, calendar (ratio_spread in R2 has naked exposure)
  - R4 top: diagonal, earnings (both inappropriate for R4 — should be long_option/defined_risk only)
  - These are random priors, not MA's `REGIME_STRATEGY_ALIGNMENT` matrix

#### `shadow` — ✅ WIRED
- 0 shadow trades — expected on fresh system
- Structure correct: would_have_won, would_have_lost, gate_effectiveness keys present

---

### INTELLIGENCE

#### `plan` — ❌ BROKEN
- Request timed out / returned empty response
- **MA API not wired:** `ma.plan.generate()` — daily trading plan not exposed
- `POST /api/v2/plan` returns `{"status":"generating","message":"refresh in ~60-90 seconds"}` — async but no GET to retrieve result

#### `research` — ✅ WIRED
- Full 22-asset macro research report, STAGFLATION regime 60% confidence
- India section: VIX 21.6, FII outflow, NIFTY-SPY corr 0.12
- **Gap:** Report dated yesterday — stale cache being served

#### `macro` — ⚠️ PARTIAL
- Returns "Overall risk: ?" — risk level unknown
- **MA APIs not wired:** `compute_macro_dashboard()` — bond_market, credit_spreads, dollar_strength, inflation_expectations all null
- OHLCV for TNX, TLT, HYG, UUP, TIP not being fetched and passed in

#### `crossmarket` — ✅ WIRED
- Real data: correlation 0.15, US regime R2, India R4, predicted gap +0.09%
- `analyze_cross_market()` fully wired

#### `board` — ✅ WIRED
- Independent Vidura review: 15 blind spots listed
- Universe list wired, blind spot detection working

---

### STOCKS

#### `stock` (MSFT) — ⚠️ PARTIAL
- Rating: BUY, Score: 71/100, strategy scores present
- **BROKEN:** `Error: unsupported format string passed to NoneType.__format__` — a numeric field (likely `entry_price`) is None when string-formatted. Add null guard.

#### `valuation` (MSFT) — ❌ BROKEN
- `Error: DataService.get_ohlcv() got an unexpected keyword argument 'period'`
- **Fix:** Change `get_ohlcv(ticker, period='1y')` → `get_ohlcv(ticker, days=365)`

#### `strategies` (MSFT) — ❌ NOT WIRED
- Returns usage string: "Usage: strategies <ticker>"
- **Root cause:** MCP tool definition uses param name `id` but handler expects positional arg

#### `stock-screen` — ❌ BROKEN
- `Error: 'EquityScreenResult' object has no attribute 'total_passed'`
- MA model field renamed — update eTrading field reference

#### `allocate` — ⚠️ PARTIAL
- Allocation percentages shown: Equity 45%, Gold 30%, Debt 15%, Cash 10%
- **BROKEN:** `Error: 'AssetAllocation' object has no attribute 'equity_sub_split'`
- MA model changed — update eTrading field reference

#### `deploy-plan` — ❌ BROKEN
- `Error: 'MonthlyAllocation' object has no attribute 'equity'`
- MA model changed — update eTrading field reference

#### `rebalance` — ✅ WIRED
- Real drift: EQUITY 3.9% vs 60% target (-56.1%), CASH 96.1% vs 10% target (+86.1%)
- Rebalance needed: YES

#### `universe` — ✅ WIRED
- All 10 presets listed with correct ticker counts, MA registry correctly integrated

---

### ANALYSIS

#### `levels` (MSFT) — ❌ NOT WIRED (parameter mismatch)
#### `hedge` (MSFT) — ❌ NOT WIRED (parameter mismatch)
#### `strategies` (MSFT) — ❌ NOT WIRED (see above)

All three return usage string — MCP `id` param not mapped to CLI positional arg.

---

### ADMIN

#### `status` — ✅ WIRED
- Shows broker, state, cycle, open trades
- **Gap:** VIX always null — not fetched

#### `ml` — ✅ WIRED (see Analytics → `learn`)

#### `report` — ✅ WIRED
- Desk P&L structure correct
- **Gap:** Capital shows $1,545,000 total — paper portfolios inflating the number

#### `env-check` — ✅ WIRED
- Returns success, env vars hidden correctly

---

## 4. Feature Integration Status

### Pre-Market: Is Today Safe?

#### Market Context (`ma.context.assess()`)
- **CLI:** `context` → falls back to `status`. Command not routed.
- **REST:** No `/api/v2/context` endpoint.
- **Gap:** `environment_label`, `trading_allowed`, `position_size_factor` never surfaced.

#### Black Swan Alert (`ma.black_swan.alert()`)
- **CLI/REST:** Not exposed anywhere.
- **Gap:** If BLACK SWAN CRITICAL fires, eTrading won't know.

#### Macro Calendar (`ma.macro.calendar()`)
- **REST:** `/api/v2/macro` returns data but `bond_market`, `credit_spreads`, `dollar_strength`, `inflation_expectations` are ALL null.
- **Root cause:** `compute_macro_dashboard()` requires OHLCV for TNX, TLT, HYG, UUP, TIP — these are not fetched.
- **Impact:** `overall_risk="moderate"` is a hardcoded default, not computed.

#### Full Macro Research Report
- **CLI/REST:** ✅ Working — STAGFLATION regime, 22 assets, real data.
- **Issue:** Stale cache — yesterday's report served as today's.

#### Cross-Market Analysis
- **REST:** `/api/v2/cross-market` ✅ Working. Real correlation, regimes, gap prediction.
- **Issue:** `signals: []` — no signals generated despite R4 India and FII outflow.

---

### Trade Selection

#### Regime Detection (`ma.regime.detect()`)
- **CLI:** `regime SPY` → falls back to `status`. Not routed.
- **REST:** No `/api/v2/regime/{ticker}` endpoint.
- **Critical:** Per-instrument HMM regime (R1-R4) completely missing. Macro regime (STAGFLATION) is available from research but is a different regime type.

#### Ranking (`ma.ranking.rank()`)
- **CLI:** `rank SPY GLD QQQ` → falls back to `status`. Not routed.
- **REST:** `POST /api/v2/ranking` ✅ **Works** — accepts `{"tickers":["MSFT"]}`, returns ranked TradeSpec with score/legs/rationale. FAST.
- **Gap:** `iv_rank_map` from broker never passed in — ranking uses defaults, not real IV rank.

#### Risk Dashboard (`compute_risk_dashboard()`)
- **REST:** `/api/v2/risk` returns all nulls for `expected_loss`, macro.
- **Root cause:** Not called with real `PortfolioPosition` objects.
- **Impact:** `can_open_new_trades` cannot be trusted. Drawdown gate never fires.

#### Daily Trading Plan (`ma.plan.generate()`)
- **REST:** `POST /api/v2/plan` returns "generating, refresh in 60-90s" — async, no GET to retrieve.
- **MCP:** `plan` tool times out.

---

### Pre-Entry Validation

#### POP Estimate (`estimate_pop()`)
- Not exposed via REST or CLI.
- `iv_rank` from broker never passed — POP uses default regime factor.

#### Trade Gate Framework (`evaluate_trade_gates()`)
- Not called anywhere. No BLOCK/SCALE/WARN enforcement before any trade.

#### Entry Window
- `TradeSpec.entry_window_start/end` exist but never checked. Orders could be placed outside optimal window.

---

### At Entry

#### Position Sizing (`spec.position_size()`)
- Not called. `contracts=1` hardcoded on all trades.
- Account size ($32K actual) never used for sizing.

#### Greeks Aggregation (`aggregate_greeks()`)
- Portfolio Greeks appear to be broker-synced raw values, not MA-computed net Greeks.

---

### Position Monitoring

#### Exit Condition Monitoring (`monitor_exit_conditions()`)
- `exit_signals: 0` shown in status — endpoint exists.
- **Gap:** `current_mid_price` for open legs likely null. BAC shows `current_price: null`.

#### Trade Health (`check_trade_health()`)
- **CLI:** `health` → falls back to `status`.
- **Gap:** `regime` and `technicals` params — unknown if live regime passed or defaulted.

#### Adjustment (`ma.adjustment.recommend_action()`)
- **CLI:** `adjust BAC` → falls back to `status`.
- **REST:** No `/api/v2/adjust` endpoint.
- **Critical:** Open BAC position has no adjustment analysis running. No BREACHED/MAX_LOSS detection.

---

### Capital Deployment

#### Deployment Plan (`plan_deployment()`)
- **REST:** `/api/v2/deployment/plan` ✅ Working — generates 12-month schedule.
- **Issue 1:** Hardcoded `total_capital: 50000.0` — use `portfolio.total_equity` ($32,261).
- **Issue 2:** All 12 months identical — regime-based acceleration not connected to live regime.
- **Fix:** `capital=portfolio.total_equity`, `regime=ma.regime.detect("SPY").regime`

#### Allocation (`recommend_core_portfolio()`)
- **REST:** `/api/v2/allocation` ✅ Returns allocation split (broken rendering — see P2 fix #15).

---

## 5. Risk API Guide

### Two Separate Risk Tools — Not Interchangeable

| | `estimate_portfolio_loss()` | `run_stress_suite()` |
|---|---|---|
| **Question answered** | "How much could I lose today?" | "What happens if market drops X%?" |
| **Method** | ATR × regime factor (practical) | Scenario simulation (Greeks-driven) |
| **When to call** | Every monitoring cycle | On demand / pre-market |
| **File** | `risk.py` | `stress_testing.py` |
| **Returns** | `ExpectedLossResult` | `StressSuiteResult` |
| **Lives on dashboard** | `RiskDashboard.expected_loss` | Standalone result |

**Why not formal VaR?** Statistical VaR assumes normally distributed returns and works best on large portfolios of hundreds of positions. With a 5-position income portfolio, ATR-based expected loss is more honest and actionable — it uses what we actually know (ATR, regime, max_loss) rather than assumptions we can't validate.

---

### RM1: `estimate_portfolio_loss()` — Daily Expected Loss

```python
from market_analyzer.risk import estimate_portfolio_loss, PortfolioPosition

result = estimate_portfolio_loss(
    positions=[
        PortfolioPosition(
            ticker="SPY",
            structure_type="iron_condor",   # defined risk → uses max_loss
            max_loss=500.0,                  # capped loss in dollars
            buying_power_used=500.0,
            notional_value=55000.0,
            delta=0.02, gamma=0.001, theta=-1.5, vega=-0.8,
            regime_at_entry=1,
            dte_remaining=21,
        ),
        PortfolioPosition(
            ticker="AAPL",
            structure_type="equity_long",    # undefined risk → uses ATR
            max_loss=0,
            notional_value=18000.0,
            buying_power_used=18000.0,
        ),
    ],
    account_nlv=50000.0,
    atr_by_ticker={"SPY": 0.012, "AAPL": 0.018},   # ATR as decimal %
    regime_by_ticker={"SPY": 1, "AAPL": 3},          # R1-R4
    correlation_data={("SPY", "AAPL"): 0.75},        # optional
)

# result.expected_loss_1d    — 1-day expected loss at 95th percentile
# result.severe_loss_1d      — 1-day loss at 99th percentile
# result.expected_loss_5d    — 5-day expected loss
# result.loss_pct_of_nlv     — loss as % of account NLV
# result.total_max_loss       — worst case: sum of all capped max losses
# result.per_position         — [{ticker, structure_type, var_1d_95, method}, ...]
# result.commentary           — human-readable risk level
```

**How loss is estimated per position:**

| Structure type | Method |
|---|---|
| iron_condor, credit_spread, debit_spread, iron_butterfly, iron_man, calendar, diagonal, pmcc, long_option | `max_loss` (capped — worst case known) |
| equity_long, undefined_risk, ratio_spread | `notional × ATR% × regime_factor` |

**Regime factors** (in `_REGIME_LOSS_FACTORS`):

| Regime | Factor | Rationale |
|---|---|---|
| R1 (Low-Vol MR) | 0.40 | Small moves expected |
| R2 (High-Vol MR) | 0.70 | Larger but bounded |
| R3 (Low-Vol Trend) | 1.10 | Persistent directional moves |
| R4 (High-Vol Trend) | 1.50 | Explosive moves |

---

### Stress Scenarios: `run_stress_suite()` — Scenario Impact

```python
from market_analyzer.stress_testing import run_stress_suite, run_stress_test
from market_analyzer.stress_testing import ScenarioParams, ScenarioType

# Run all predefined scenarios at once
suite = run_stress_suite(positions, account_nlv=50000.0)
# suite.worst_scenario — name of scenario causing most damage
# suite.results        — list of StressTestResult per scenario

# Run a single named scenario
result = run_stress_test(
    positions=positions,
    params=ScenarioParams(
        name="market_down_5pct",
        scenario_type=ScenarioType.MARKET_SHOCK,
        price_shock_pct=-5.0,
    ),
    account_nlv=50000.0,
)
# result.total_impact_dollars  — portfolio P&L under this scenario
# result.per_position          — impact per trade
# result.action_needed         — "hold" / "close" / "hedge"
```

**Predefined scenarios available:** `MARKET_DOWN_1/3/5/10`, `MARKET_UP_3`, `VIX_SPIKE_50/100`, `RATE_SHOCK`, `FLASH_CRASH`, `BLACK_MONDAY`, `COVID_MARCH`, `INDIA_CRASH`, `FED_SURPRISE`

---

### RM7: `compute_risk_dashboard()` — Full Risk View

Calls all 6 RM functions and returns a single `RiskDashboard`. This is what eTrading should call every monitoring cycle.

```python
from market_analyzer.risk import compute_risk_dashboard

dashboard = compute_risk_dashboard(
    positions=positions,
    account_nlv=50000.0,
    account_peak=52000.0,           # Highest NLV recorded
    max_positions=5,
    atr_by_ticker={"SPY": 0.012},
    regime_by_ticker={"SPY": 1},
    correlation_data={("SPY", "QQQ"): 0.92},
    macro_regime="STAGFLATION",
    macro_position_factor=0.75,     # From ma.macro.research_report()
)

# dashboard.expected_loss          — ExpectedLossResult (was: dashboard.var)
# dashboard.overall_risk_level     — "low" / "moderate" / "elevated" / "high" / "critical"
# dashboard.can_open_new_trades    — master gate: False if drawdown/max_positions/risk exceeded
# dashboard.max_new_trade_size_pct — scale factor for next trade (0.0–1.0)
# dashboard.alerts                 — list[str] of active risk flags
# dashboard.drawdown               — DrawdownStatus with circuit breaker
# dashboard.greeks                 — PortfolioGreeks | None
```

**IMPORTANT — field rename for eTrading:**
`dashboard.var` no longer exists. Use `dashboard.expected_loss`.

---

### Integration Checklist — Risk

- [ ] Build `PortfolioPosition` objects from eTrading's position DB + broker Greeks after each mark-to-market cycle
- [ ] Call `compute_risk_dashboard()` after mark-to-market (not just on demand)
- [ ] Pass `atr_by_ticker` from `ma.technicals.analyze(ticker).atr_pct` per open ticker
- [ ] Pass `regime_by_ticker` from `ma.regime.detect(ticker).regime` per open ticker
- [ ] Use `dashboard.can_open_new_trades` as a gate before any new trade
- [ ] Use `dashboard.max_new_trade_size_pct` to scale position size on new entries
- [ ] Run `run_stress_suite()` pre-market once per day — surface worst scenario in UI
- [ ] `dashboard.expected_loss` field (NOT `.var`) — update any code that read `.var`

---

## 6. Expected Value (EV) Guide

EV, POP, and R:R are computed together by a single function — `estimate_pop()` — and bundled into a `POPEstimate` result. These are not separate APIs.

**Formula:**
```
EV = POP × max_profit - (1 - POP) × max_loss
```
A positive EV means the trade has statistical edge. Negative EV means you're paying for the privilege of being in the trade — avoid unless there's a strong directional thesis.

---

### `estimate_pop()` — POP + EV + R:R in one call

```python
from market_analyzer.trade_lifecycle import estimate_pop

pop = estimate_pop(
    trade_spec=trade_spec,      # TradeSpec from ma.ranking.rank() or assessor
    entry_price=2.50,           # Net credit (credit trade) or net debit (debit trade)
    regime_id=1,                # From ma.regime.detect(ticker).regime  (int 1-4)
    atr_pct=1.2,                # From ma.technicals.analyze(ticker).atr_pct  (e.g. 1.2 = 1.2%)
    current_price=580.0,        # Current underlying price
    contracts=1,
    iv_rank=35.0,               # From ma.quotes.get_metrics(ticker).iv_rank — pass if available
)

# pop.pop_pct              — probability of profit, e.g. 0.72 = 72%
# pop.expected_value       — EV in dollars, e.g. +$48 or -$12
# pop.max_profit           — dollars at full profit
# pop.max_loss             — dollars at max loss (positive number)
# pop.risk_reward_ratio    — max_loss / max_profit (lower = better, e.g. 3.5 = risk $3.50 to make $1)
# pop.trade_quality        — "excellent" / "good" / "marginal" / "poor"
# pop.trade_quality_score  — 0-1 composite (40% POP + 30% EV + 30% R:R)
# pop.notes                — explanation: expected move, regime factor, IV adjustment
# pop.data_gaps            — list of DataGap if iv_rank missing or structure unsupported
```

**Returns `None`** if the structure type is not supported (e.g. calendar, diagonal — these don't have simple breakeven math).

---

### How POP is computed — no Black-Scholes

POP uses regime-adjusted ATR to estimate the expected price move over the trade's DTE, then computes the probability that price stays within the profit range using a normal approximation.

**For credit trades** (iron_condor, credit_spread, strangle, straddle, iron_butterfly):
```
daily_sigma  = ATR% / 1.25          # ATR ≈ 1.25σ
iv_factor    = 0.7 + (iv_rank/100) × 0.6   # 0.7 at IV rank 0, 1.3 at IV rank 100
expected_move = daily_sigma × iv_factor × √DTE × current_price
adjusted_move = expected_move × regime_factor
POP = P(price stays between both breakevens over DTE)
```

**For debit trades** (debit_spread, long_option):
```
POP = P(price moves past breakeven in the right direction over DTE)
```

**Regime factors** (same as expected loss):

| Regime | Factor | Effect |
|---|---|---|
| R1 (Low-Vol MR) | 0.40 | Compresses expected move → credit trades look better |
| R2 (High-Vol MR) | 0.70 | Moderate compression |
| R3 (Low-Vol Trend) | 1.10 | Widens expected move → debit trades / directional look better |
| R4 (High-Vol Trend) | 1.50 | Wide expected moves → hard to sell premium profitably |

---

### `trade_quality_score` — the gate-ready signal

The `trade_quality_score` (0-1) is already wired into the gate framework:

```python
from market_analyzer.gate_framework import evaluate_trade_gates

gates = evaluate_trade_gates(
    trade_spec=trade_spec,
    regime_result=regime_result,
    account_nlv=50000.0,
    trade_quality_score=pop.trade_quality_score,   # ← pass this in
    ...
)
# gates.can_trade     — True / False
# gates.size_factor   — 0.0-1.0 (how much to scale position size)
```

**Gate behaviour by score:**

| Score | Label | Gate action |
|---|---|---|
| ≥ 0.70 | excellent | PASS — full size |
| 0.50–0.70 | good | PASS — full size |
| 0.30–0.50 | marginal | SCALE — half size (score / min_quality threshold) |
| < 0.30 | poor | BLOCK — do not trade |

---

### EV in the CLI

The `pop` and `income_entry` commands show EV today:

```
pop SPY                 # POP + EV for default IC structure
income_entry SPY 2.50   # Entry check including EV
```

Example output:
```
  POP:      72.4%
  EV:       +$48   (positive edge)
  R:R:      3.5:1  (risk $3.50 per $1 reward)
  Quality:  good (0.61)
```

---

### Integration Checklist — EV

- [ ] Call `estimate_pop()` after getting a `TradeSpec` from `ma.ranking.rank()`, before submitting any order
- [ ] Pass `iv_rank` from `ma.quotes.get_metrics(ticker).iv_rank` — improves POP accuracy by 10-15%
- [ ] Pass `trade_quality_score` into `evaluate_trade_gates()` — gate already knows what to do with it
- [ ] **Never execute a trade with negative EV** unless there is an explicit override reason (e.g. hedge)
- [ ] Display `pop.notes` in the UI — it explains the expected move and regime factor used
- [ ] If `estimate_pop()` returns `None` — structure not supported (calendar, diagonal). Use `trade_spec.pop_estimate` from the assessor if present, or skip the EV gate for that trade
- [ ] Log `pop_pct`, `expected_value`, and `trade_quality_score` per trade at entry — needed for future POP calibration

---

## 7. Adjustment Integration Guide

All adjustment logic operates at **strategy level**, not leg level.
MA tells eTrading: "close these legs, open these legs." eTrading executes the orders.

---

### APIs

#### `AdjustmentService.analyze()` — Full ranked menu (for human review UI)

```python
analysis: AdjustmentAnalysis = ma.adjustment.analyze(
    trade_spec=trade_spec,   # TradeSpec — the original trade as entered
    regime=regime_result,    # RegimeResult from ma.regime.detect(ticker)
    technicals=tech,         # TechnicalSnapshot from ma.technicals.analyze(ticker)
    vol_surface=None,        # Optional
)
```

Returns `AdjustmentAnalysis` — ranked list of adjustment options, best first. Use for "show me my options" UI.

#### `AdjustmentService.recommend_action()` — Single deterministic action (for automation)

```python
decision: AdjustmentDecision = ma.adjustment.recommend_action(
    trade_spec=trade_spec,
    regime=regime_result,
    technicals=tech,
)
```

Returns exactly ONE action. Use for systematic/automated trading — no human in the loop.

**Decision table:**

| Position Status | Regime | Action |
|----------------|--------|--------|
| MAX_LOSS | any | CLOSE_FULL (immediate) |
| BREACHED | R3 or R4 | CLOSE_FULL (immediate) |
| BREACHED | R1 or R2 | ROLL_AWAY (soon) |
| TESTED | R4 | CLOSE_FULL (immediate) |
| TESTED | R3 | ROLL_AWAY (soon) |
| TESTED | R1 or R2 | DO_NOTHING |
| SAFE | any | DO_NOTHING |

#### `get_adjustment_recommendation()` — Wrapper in trade_lifecycle.py

```python
from market_analyzer.trade_lifecycle import get_adjustment_recommendation

decision = get_adjustment_recommendation(
    trade_spec=trade_spec,
    regime=regime_result,
    technicals=tech,
    adjustment_service=ma.adjustment,
)
```

---

### Key Fields

#### `AdjustmentAnalysis` (from `analyze()`)

| Field | Type | Use |
|-------|------|-----|
| `position_status` | `PositionStatus` | SAFE / TESTED / BREACHED / MAX_LOSS |
| `tested_side` | `TestedSide` | NONE / PUT / CALL / BOTH |
| `distance_to_short_put_pct` | `float \| None` | % distance from price to short put |
| `distance_to_short_call_pct` | `float \| None` | % distance from price to short call |
| `mark_pnl` | `float \| None` | Current mark P&L from broker mid prices (None = DXLink failed) |
| `remaining_dte` | `int` | Days left on trade |
| `adjustments` | `list[AdjustmentOption]` | Ranked list, best first |
| `recommendation` | `str` | One-line top recommendation |

#### `AdjustmentOption` (each item in `adjustments`)

| Field | Type | Use |
|-------|------|-----|
| `adjustment_type` | `AdjustmentType` | DO_NOTHING / CLOSE_FULL / ROLL_AWAY / ADD_WING / etc. |
| `close_legs` | `list[LegSpec]` | Legs to close — build close orders from these |
| `new_legs` | `list[LegSpec]` | Legs to open — build open orders from these |
| `mid_cost` | `float \| None` | Net cost from broker mid prices. Negative = credit received. None = DXLink failed |
| `risk_change` | `float` | Dollar risk removed (negative = good) |
| `urgency` | `str` | "none" / "monitor" / "soon" / "immediate" |
| `rationale` | `str` | Human-readable explanation |

#### `AdjustmentDecision` (from `recommend_action()`)

| Field | Type | Use |
|-------|------|-----|
| `action` | `AdjustmentType` | The single chosen action |
| `urgency` | `str` | How fast to act |
| `rationale` | `str` | Why this action was chosen |
| `detail` | `AdjustmentOption \| None` | Full adjustment spec if action != DO_NOTHING |
| `position_status` | `PositionStatus` | Status that triggered this decision |

---

### Position Status Thresholds

| Status | Condition |
|--------|-----------|
| SAFE | Price > 1 ATR from short strike |
| TESTED | Price within 0–1 ATR of short strike |
| BREACHED | Price past short strike |
| MAX_LOSS | Price past protective wing |

---

### Executing an Adjustment

MA returns `close_legs` and `new_legs`. eTrading translates to broker orders.

```python
option = analysis.adjustments[0]  # or decision.detail

# Step 1: Close legs — FLIP the action (STO→BTC, BTO→STC)
for leg in option.close_legs:
    close_action = "BTC" if leg.action == LegAction.SELL_TO_OPEN else "STC"
    submit_order(
        ticker=trade_spec.ticker,
        option_type=leg.option_type,
        strike=leg.strike,
        expiration=leg.expiration,
        action=close_action,
        quantity=leg.quantity,
    )

# Step 2: Open new legs — use leg.action as-is
for leg in option.new_legs:
    submit_order(
        ticker=trade_spec.ticker,
        option_type=leg.option_type,
        strike=leg.strike,
        expiration=leg.expiration,
        action=leg.action,
        quantity=leg.quantity,
    )
```

Submit close + open as a **single multi-leg order** where possible — reduces slippage and partial-fill risk.

---

### Structure Support Matrix

| `StructureType` | Adjustments Available |
|----------------|----------------------|
| `IRON_CONDOR` / `IRON_MAN` / `IRON_BUTTERFLY` | ROLL_AWAY (put/call), NARROW_UNTESTED, CONVERT (to butterfly), ROLL_OUT |
| `CREDIT_SPREAD` | ROLL_AWAY, ROLL_OUT |
| `CALENDAR` / `DOUBLE_CALENDAR` | ROLL_OUT (front leg) |
| `RATIO_SPREAD` | ADD_WING (to cap naked risk) |
| `DEBIT_SPREAD` | CLOSE_FULL at profit target |
| `STRADDLE` / `STRANGLE` | ADD_WING (define risk), CLOSE_FULL (tested side) |

All structures also get DO_NOTHING and CLOSE_FULL as baseline options.

---

### Integration Checklist

**Broker / Data**
- [ ] Pass `market_data` and `market_metrics` when constructing `MarketAnalyzer` — wires `OptionQuoteService` and enables real `mid_cost` values from DXLink quotes
- [ ] If `mid_cost` is `None` despite broker being connected — DXLink pricing failed. Log it, do not execute the adjustment blindly
- [ ] If `mark_pnl` is `None` — DXLink failed to price one or more legs. Do not show $0

**Calling the APIs**
- [ ] Call `analyze()` for UI showing adjustment options to a human
- [ ] Call `recommend_action()` for any automated/systematic path
- [ ] Pass `RegimeResult` from `ma.regime.detect(ticker)` — not a hardcoded regime
- [ ] Pass `TechnicalSnapshot` from `ma.technicals.analyze(ticker)` — current price and ATR matter

**Executing Orders**
- [ ] Use `close_legs` to build close orders — **flip the action** (STO→BTC, BTO→STC)
- [ ] Use `new_legs` to build open orders — use `leg.action` as-is
- [ ] Send as a single multi-leg order where broker supports it

**Urgency Handling**
- [ ] `"immediate"` → execute within current bar, alert user if manual
- [ ] `"soon"` → execute within current session
- [ ] `"monitor"` → check again next bar, no action needed now
- [ ] `"none"` → position healthy, no action

**DO_NOTHING Handling**
- [ ] `DO_NOTHING` always appears first in `analysis.adjustments` — it is the baseline, not a bug
- [ ] For `recommend_action()` returning DO_NOTHING: take no order action, just log

---

### Monitoring Frequency

| Position Type | Check Interval |
|--------------|----------------|
| 0DTE positions | Every bar (5 min) |
| Weekly income trades | Every 30 min |
| Monthly income trades | Hourly |
| After regime change | Immediately re-check all open trades |

---

## 8. SaaS Broker Authentication Guide

**Core problem:** The current `.env` file pattern stores a single set of TastyTrade credentials. That works for Nitin's personal dev machine, but breaks in a SaaS/multi-tenant deployment where each user has their own TastyTrade account.

---

### How TastyTrade Auth Works (OAuth 2.0)

TastyTrade uses **standard OAuth 2.0** (fully deployed since Dec 2024, username/password deprecated). Two distinct credential types:

| Credential | Scope | Where it lives |
|---|---|---|
| `client_secret` (aka `provider_secret`) | **One per app** — your OAuth application identity | Server-side env var / secrets manager. Never changes. |
| `refresh_token` | **One per user** — that user's authorization for your app | DB row per user, encrypted at rest |
| `access_token` | Per user, 15-min lifetime | In memory only — SDK auto-refreshes it |

Your app's `client_secret` is like a password for your app as a whole. Every user who connects their TastyTrade account gets their own `refresh_token`. You store one `client_secret`, you store N `refresh_tokens` (one per user).

---

### The Right Architecture for SaaS

```
User clicks "Connect TastyTrade"
    │
    ▼
1. Generate PKCE verifier + state, store in session
    │
    ▼
2. Redirect → https://my.tastytrade.com/auth.html
   ?client_id=YOUR_APP_CLIENT_ID
   &redirect_uri=https://app.etrading.com/broker/callback
   &response_type=code
   &scope=read-account write-order
   &state=<random>
   &code_challenge=<pkce>
    │
    ▼
3. TastyTrade auth page — user logs in with their TastyTrade creds
    │
    ▼
4. TastyTrade redirects back to your callback:
   https://app.etrading.com/broker/callback?code=AUTH_CODE&state=<same>
    │
    ▼
5. eTrading server exchanges code for tokens:
   POST https://api.tastyworks.com/oauth/token
   { grant_type: authorization_code, code: AUTH_CODE,
     client_secret: YOUR_CLIENT_SECRET, redirect_uri: ..., code_verifier: ... }
    │
    ▼
6. TastyTrade returns { refresh_token, access_token, account_numbers }
    │
    ▼
7. eTrading stores: User.tastytrade_refresh_token = encrypt(refresh_token)
                     User.tastytrade_account_number = account_numbers[0]
    │
    ▼
8. Each API call: Session(provider_secret=CLIENT_SECRET, refresh_token=user_refresh_token)
```

**Do NOT use the SDK's built-in OAuth helper** — it hard-codes `localhost:8000` and is designed for single-user CLI apps, not SaaS.

---

### market_analyzer Integration (Already Correct)

MA already supports this pattern via `connect_from_sessions()`:

```python
from market_analyzer.broker.tastytrade import connect_from_sessions
from tastytrade import Session

# eTrading does the auth — MA never touches credentials
def get_ma_for_user(user: User) -> MarketAnalyzer:
    refresh_token = decrypt(user.tastytrade_refresh_token)

    sdk_session = Session(
        provider_secret=settings.TASTYTRADE_CLIENT_SECRET,  # one app-level env var
        refresh_token=refresh_token,                         # per-user DB value
    )

    market_data, metrics, account, watchlist = connect_from_sessions(
        sdk_session=sdk_session,
        data_session=sdk_session,   # reuse for DXLink streaming
    )

    return MarketAnalyzer(
        data_service=DataService(),
        market_data=market_data,
        market_metrics=metrics,
        account_provider=account,
    )
```

MA never sees credentials. eTrading owns auth. `connect_from_sessions()` wraps the pre-authenticated session in MA's `ExternalBrokerSession` — which is exactly what multi-tenancy requires.

---

### Storing Credentials

| What | Where | How |
|---|---|---|
| `TASTYTRADE_CLIENT_SECRET` | Server env var | One value for the whole platform. Never in DB. |
| `tastytrade_refresh_token` | Per-user DB row | Encrypt at rest — use `django-encrypted-model-fields` or equivalent. This is a permanent credential. |
| `tastytrade_account_number` | Per-user DB row | Plaintext fine — not a secret |
| Access token | In memory only | SDK manages 15-min lifecycle. Never persist. |

**Never store the `client_secret` in the database.** Never store `refresh_token` in plaintext. A leaked `refresh_token` gives full account access until the user revokes it.

---

### Session Lifecycle Per Request

TastyTrade `Session` is a per-user, per-request object. Do not cache it between requests:

```python
# ✅ Correct — create per request/task
session = Session(provider_secret=CLIENT_SECRET, refresh_token=user.refresh_token)
result = ma_for_user(session).ranking.rank(tickers)

# ❌ Wrong — caching creates cross-user leakage risk and stale session bugs
_session_cache[user_id] = session   # don't do this
```

Session creation overhead is a few hundred milliseconds (one token refresh API call). This is acceptable — the SDK handles it.

---

### Multi-Account Users

If a user has multiple TastyTrade accounts (e.g. taxable + IRA), `Account.get(session)` returns all of them. eTrading should:
- Let the user select which account to use for trading
- Store `tastytrade_account_number` per user
- Pass it when constructing `TastyTradeBrokerSession` (or pass it to the SDK's `Account` directly)

---

### "Disconnect Account" Flow

Always provide a revocation path:

```python
# User clicks "Disconnect TastyTrade"
DELETE https://api.tastyworks.com/oauth/token  # revoke the grant
user.tastytrade_refresh_token = None
user.tastytrade_account_number = None
```

This is a legal and security requirement — users must be able to revoke access.

---

### Sandbox vs Production

| | Sandbox | Production |
|---|---|---|
| API base URL | `api.cert.tastyworks.com` | `api.tastyworks.com` |
| SDK flag | `is_test=True` in `Session()` | `is_test=False` (default) |
| Credentials | Separate sandbox client_secret | Live client_secret |
| Capital | Simulated | Real money |

Keep separate `TASTYTRADE_CLIENT_SECRET_SANDBOX` and `TASTYTRADE_CLIENT_SECRET_LIVE` env vars. Never mix them.

---

### Developer Registration

To get a production `client_secret`:
1. Go to `developer.tastytrade.com`
2. Register an OAuth application — provide your redirect URIs, select scopes
3. TastyTrade issues your `client_id` and `client_secret`
4. Request sandbox access for development (`api.cert.tastyworks.com`)

---

### Migration from .env File Pattern

The current `.env` file approach (`TASTYTRADE_REFRESH_TOKEN_LIVE`) is fine for **Nitin's personal CLI**. To migrate to SaaS:

1. Register the app on developer.tastytrade.com — get a proper `client_id` + `client_secret`
2. Build the OAuth authorization flow (steps 1–7 above)
3. Replace `.env` token loading with per-user DB lookup
4. Switch from `connect_tastytrade()` → `connect_from_sessions()` (already supported in MA)
5. The `TASTYTRADE_CLIENT_SECRET` stays as a single env var on the server — just the app identity changes from "Nitin's personal token" to "the eTrading OAuth application"

**Nothing in market_analyzer needs to change.** MA's architecture is already SaaS-ready. The work is entirely in eTrading.

---

### Summary

| | Current (.env) | Target (SaaS) |
|---|---|---|
| Auth owner | Nitin's machine | eTrading server |
| Credentials | One set in .env | `client_secret` in env, `refresh_token` per user in DB |
| MA interface | `connect_tastytrade()` | `connect_from_sessions()` |
| Multi-user | No | Yes — each user connects their own TastyTrade account |
| Token storage | Plaintext .env | Encrypted DB field |
| MA code changes needed | None | None |

---

## What Is Working Well

| Capability | Status |
|-----------|--------|
| Broker connection (6 brokers: TastyTrade, Alpaca, IBKR, Schwab, Zerodha, Dhan) | ✅ |
| Portfolio/position sync from broker | ✅ |
| Cross-market analysis (US→India) | ✅ |
| Full macro research report (22 assets) | ✅ |
| MA universe/registry integration | ✅ |
| Board/Vidura blind spot detection | ✅ |
| ML gate thresholds + Thompson Sampling (structure) | ✅ |
| Greeks display vs limits | ✅ |
| Capital utilization view | ✅ |
| Shadow portfolio framework | ✅ |
| Rebalance drift detection | ✅ |
| `POST /api/v2/ranking` direct (MSFT IC: score=0.739 "go") | ✅ |

---

## 9. New Trading Intelligence APIs (March 2026)

Six new API surfaces built into market_analyzer as pure functions. All are stateless, require no broker connection (though some produce richer results with broker data), and return Pydantic models. eTrading is the sole consumer.

**Import convention:** all functions and models are re-exported from the top-level package unless noted otherwise.

```python
# Top-level imports for everything in this section
from market_analyzer import (
    # Validation
    # Note: validation lives in its own sub-package
)
from market_analyzer.validation import (
    run_daily_checks,
    run_adversarial_checks,
    ValidationReport,
    CheckResult,
    Severity,
)
from market_analyzer import (
    # Entry intelligence
    compute_strike_support_proximity,
    select_skew_optimal_strike,
    score_entry_level,
    compute_limit_entry_price,
    compute_pullback_levels,
    compute_iv_rank_quality,
    # Position sizing
    compute_position_size,
    PortfolioExposure,
    # Exit intelligence
    compute_regime_stop,
    compute_time_adjusted_target,
    compute_remaining_theta_value,
    # DTE optimization
    select_optimal_dte,
    # Adjustment learning
    AdjustmentOutcome,
    AdjustmentEffectiveness,
    analyze_adjustment_effectiveness,
)
```

---

### 9.1 Pre-Trade Validation (10-Check Gate)

**File:** `market_analyzer/validation/daily_readiness.py`
**Models:** `market_analyzer/validation/models.py`

eTrading MUST call `run_daily_checks()` before placing ANY income trade. This is the profitability gate. A trade that fails validation should never reach the broker.

```python
from market_analyzer.validation import run_daily_checks, run_adversarial_checks, Severity

report = run_daily_checks(
    ticker="SPY",
    trade_spec=trade_spec,          # From any assessor (assess_iron_condor, etc.)
    entry_credit=1.80,              # From broker quotes (DXLink mid price)
    regime_id=1,                    # From ma.regime.detect().regime.value
    atr_pct=0.85,                   # From technicals.snapshot().atr_pct
    current_price=580.0,            # Current underlying price
    avg_bid_ask_spread_pct=1.2,     # Average bid-ask spread % across the chain legs
    dte=35,                         # DTE of the target expiration
    rsi=52.0,                       # From technicals.snapshot().rsi.value
    iv_rank=42.0,                   # From broker metrics (optional, improves accuracy)
    iv_percentile=55.0,             # From broker metrics (optional)
    contracts=1,                    # Number of contracts for yield computation
    levels=levels_analysis,         # From ma.levels.analyze() (optional, enables check #8)
    days_to_earnings=None,          # From fundamentals (None for ETFs)
    ticker_type="etf",              # "etf", "equity", or "index"
)

if not report.is_ready:
    # DO NOT TRADE -- at least one FAIL check
    for check in report.checks:
        if check.severity == Severity.FAIL:
            log(f"BLOCKED: {check.name} -- {check.message}")
    return

# Also run adversarial stress tests for income trades
stress = run_adversarial_checks(ticker, trade_spec, entry_credit, atr_pct)
if not stress.is_ready:
    for check in stress.checks:
        if check.severity == Severity.FAIL:
            log(f"STRESS FAIL: {check.name} -- {check.message}")
    return
```

**10 checks in `run_daily_checks()` (all must pass for `report.is_ready == True`):**

| # | Check Name | What It Catches | FAIL Means |
|---|---|---|---|
| 1 | `commission_drag` | Fees >= 25% of credit, or net credit <= 0 | Math doesn't work after fees |
| 2 | `fill_quality` | Bid-ask spread > 3% | Won't get filled at expected price |
| 3 | `margin_efficiency` | Annualized ROC < 10% | Capital tied up for insufficient return |
| 4 | `pop_gate` | POP < 55% (FAIL) or < 65% (WARN) | Probability too low for income trade |
| 5 | `ev_positive` | Expected value <= -$10 | Losing trade on average |
| 6 | `entry_quality` | Entry score < 0.45 + wrong regime conditions | Wrong time/conditions to enter |
| 7 | `exit_discipline` | Missing TP, SL, or exit_dte on TradeSpec | No defined exit plan (WARN, not FAIL) |
| 8 | `strike_proximity` | Short strikes not backed by S/R levels | Strikes floating in thin air (WARN without levels data) |
| 9 | `earnings_blackout` | Earnings within DTE window | Gap risk destroys the structure (HARD FAIL) |
| 10 | `iv_rank_quality` | IV rank below ticker-type threshold | Not enough premium to sell |

**3 checks in `run_adversarial_checks()`:**

| # | Check Name | What It Tests |
|---|---|---|
| 1 | `gamma_stress` | Max loss at 2-sigma move; risk/reward > 10:1 = FAIL |
| 2 | `vega_shock` | +30% IV spike impact; short-vega structures lose ~36% of credit = FAIL |
| 3 | `breakeven_spread` | Bid-ask spread at which EV goes negative; < 1% = FAIL |

**ValidationReport model:**
- `report.is_ready: bool` -- True only if zero FAIL checks
- `report.passed: int` -- count of PASS checks
- `report.warnings: int` -- count of WARN checks
- `report.failures: int` -- count of FAIL checks
- `report.summary: str` -- e.g., "READY TO TRADE (8/10 passed, 2 warnings)"
- `report.checks: list[CheckResult]` -- individual results with `.name`, `.severity`, `.message`, `.value`, `.threshold`

---

### 9.2 Entry-Level Intelligence (6 Functions)

**File:** `market_analyzer/features/entry_levels.py`
**Models:** `market_analyzer/models/entry.py`

Call these AFTER validation passes, BEFORE placing the order. They answer: "Where should I enter, and at what price?"

#### 9.2.1 `score_entry_level()` -- Enter Now vs Wait

Multi-factor score combining RSI extremity (35%), Bollinger %B (30%), ATR extension (15%), VWAP deviation (10%), and level proximity (10%).

```python
from market_analyzer import score_entry_level

score = score_entry_level(
    technicals=technicals_snapshot,  # From ma.technicals.snapshot(ticker)
    levels=levels_analysis,          # From ma.levels.analyze(ticker)
    direction="neutral",             # "neutral" for IC/straddle, "bullish"/"bearish" for directional
)

if score.action == "enter_now":     # overall_score >= 0.70
    place_order()
elif score.action == "wait":        # overall_score >= 0.40
    set_pullback_alerts(ticker)
else:                               # "not_yet", overall_score < 0.40
    skip_trade()
```

**EntryLevelScore model:** `overall_score: float` (0-1), `action: str`, `components: dict[str, float]`, `rationale: str`.

#### 9.2.2 `compute_limit_entry_price()` -- Limit Order Price

Maps regime to urgency, then computes optimal limit price based on bid-ask spread.

```python
from market_analyzer import compute_limit_entry_price

# Map regime to urgency
urgency_map = {1: "patient", 2: "normal", 3: "aggressive", 4: "aggressive"}
urgency = urgency_map[regime_id]

limit = compute_limit_entry_price(
    current_mid=broker_mid_price,     # Mid price from DXLink quotes
    bid_ask_spread=broker_spread,     # Bid-ask spread in dollars
    urgency=urgency,
    is_credit=True,                   # True for IC, credit spread; False for debit spread
)

# Place limit order at limit.limit_price -- NEVER market order for income trades
```

**Urgency logic:**
- Credits: patient=hold at mid (0% concession), normal=concede 10% of spread, aggressive=concede 30%
- Debits: patient=save 30% of spread, normal=save 10%, aggressive=pay mid (0% improvement)

**ConditionalEntry model:** `entry_mode: str` ("limit"/"market"), `limit_price: float`, `improvement_pct: float`, `urgency: str`, `rationale: str`.

#### 9.2.3 `compute_strike_support_proximity()` -- S/R Backing

Checks whether short strikes are placed near support/resistance levels. Also used internally by `run_daily_checks()` check #8.

```python
from market_analyzer import compute_strike_support_proximity

proximity = compute_strike_support_proximity(
    trade_spec=trade_spec,
    levels=levels_analysis,   # From ma.levels.analyze(ticker)
    atr=atr_value,            # ATR in dollar terms (not pct)
    min_strength=0.5,         # Minimum S/R level strength (0-1)
    max_distance_atr=1.0,     # Maximum distance in ATR units
)

if not proximity.all_backed:
    log(f"WARNING: {proximity.summary}")
    # Consider adjusting strikes or skipping trade
```

**StrikeProximityResult model:** `legs: list[StrikeProximityLeg]`, `overall_score: float` (0-1), `all_backed: bool`, `summary: str`.

#### 9.2.4 `select_skew_optimal_strike()` -- IV Skew Strike Selection

When vol surface data is available, finds the strike where IV is richest (most premium to sell).

```python
from market_analyzer import select_skew_optimal_strike

optimal = select_skew_optimal_strike(
    underlying_price=580.0,
    atr=5.2,
    regime_id=1,
    skew=vol_surface.skew_at_dte(35),  # SkewSlice from vol surface
    option_type="put",
    min_distance_atr=0.8,
    max_distance_atr=2.0,
)

# Use optimal.optimal_strike instead of ATR-only baseline
# optimal.iv_advantage_pct shows how much richer the premium is
```

**SkewOptimalStrike model:** `baseline_strike`, `optimal_strike`, `baseline_iv`, `optimal_iv`, `iv_advantage_pct`, `distance_atr`, `rationale`.

#### 9.2.5 `compute_pullback_levels()` -- Price Alerts for Patient Entry

Returns support levels below current price where entering would materially improve trade quality.

```python
from market_analyzer import compute_pullback_levels

alerts = compute_pullback_levels(
    current_price=580.0,
    levels=levels_analysis,
    atr=5.2,
    min_strength=0.4,
    max_distance_atr=2.0,
)

for alert in alerts:  # Sorted nearest-first (highest alert_price first)
    set_price_alert(alert.alert_price, alert.improvement_description)
```

**PullbackAlert model:** `alert_price`, `level_source`, `level_strength`, `improvement_description`, `roc_improvement_pct`.

#### 9.2.6 `compute_iv_rank_quality()` -- Ticker-Type IV Thresholds

ETFs, equities, and indexes have different IV rank thresholds. Also used internally by `run_daily_checks()` check #10.

```python
from market_analyzer import compute_iv_rank_quality

iv_quality = compute_iv_rank_quality(current_iv_rank=42.0, ticker_type="etf")
# iv_quality.quality: "good" (>= 30 for ETF), "wait" (20-30), "avoid" (< 20)
```

**Thresholds by ticker type:**

| Type | Good (sell premium) | Wait | Avoid |
|---|---|---|---|
| ETF | >= 30 | 20-30 | < 20 |
| Equity | >= 45 | 30-45 | < 30 |
| Index | >= 25 | 15-25 | < 15 |

---

### 9.3 Position Sizing (Kelly + Correlation + Regime Margin)

**File:** `market_analyzer/features/position_sizing.py`
**Models:** defined in same file (KellyResult, PortfolioExposure, CorrelationAdjustment, RegimeMarginEstimate)

eTrading MUST use `compute_position_size()` for all position sizing. This replaces any hardcoded contract counts. The function chains three sizing stages: Kelly criterion, correlation penalty, and regime-adjusted margin cap.

```python
from market_analyzer import compute_position_size, PortfolioExposure

# Build exposure from eTrading's portfolio DB
exposure = PortfolioExposure(
    open_position_count=3,
    max_positions=5,
    current_risk_pct=0.15,        # Sum of (max_loss / NLV) for all open positions
    max_risk_pct=0.25,            # Hard cap: 25% of NLV at risk
    drawdown_pct=0.03,            # (peak_nlv - current_nlv) / peak_nlv
    drawdown_halt_pct=0.10,       # Circuit breaker: stop trading at 10% drawdown
)

result = compute_position_size(
    pop_pct=0.72,                  # From estimate_pop() -- fraction, NOT percentage
    max_profit=150.0,              # Max profit per contract in dollars
    max_loss=350.0,                # Max loss per contract in dollars (positive)
    capital=50000.0,               # Account NLV
    risk_per_contract=350.0,       # Usually max_loss, or wing_width * 100
    regime_id=1,                   # Current regime (1-4)
    wing_width=5.0,                # Spread width in points (for margin calc)
    exposure=exposure,             # Current portfolio state
    open_tickers=["QQQ", "IWM"],   # Tickers already in portfolio
    new_ticker="SPY",              # Ticker being sized
    correlation_fn=my_corr_lookup, # Callable(ticker_a, ticker_b) -> float
    safety_factor=0.5,             # Half Kelly (conservative, industry standard)
    max_contracts=50,              # Hard cap
)

contracts = result.recommended_contracts  # USE THIS
```

**Sizing pipeline:**
1. **Kelly criterion:** `f* = (p*b - (1-p)) / b` where p=POP, b=profit/loss ratio. Capped at 25%.
2. **Safety factor:** Half Kelly by default (multiply by 0.5).
3. **Portfolio adjustment:** Reduce for occupied position slots, remaining risk budget, and drawdown.
4. **Correlation penalty:** If max correlation with any open position > 0.70, apply `max_corr * 50%` penalty.
5. **Regime margin cap:** R1=1.0x, R2=1.3x, R3=1.1x, R4=1.5x of base buying power. Accounts for broker margin expansion in high-vol regimes.
6. **Hard cap:** 2% of capital per position, and max_contracts.

**Circuit breakers (result.recommended_contracts = 0):**
- `drawdown_pct >= drawdown_halt_pct` -- stop trading entirely
- `open_position_count >= max_positions` -- no slots left
- Kelly fraction is negative (EV-negative trade -- should already be blocked by validation)

**KellyResult model:** `full_kelly_fraction`, `half_kelly_fraction`, `portfolio_adjusted_fraction`, `recommended_contracts: int`, `max_contracts_by_risk: int`, `rationale: str`, `components: dict[str, float]`.

**eTrading must maintain:**
- `PortfolioExposure` -- build from portfolio DB on every sizing call
- `correlation_fn` -- pre-compute weekly using `compute_pairwise_correlation()` on daily log returns. Signature: `(ticker_a: str, ticker_b: str) -> float`. Use 60-day lookback.
- `drawdown_pct` -- track peak NLV and current NLV in account DB

**Helper: `compute_pairwise_correlation()`:**
```python
from market_analyzer.features.position_sizing import compute_pairwise_correlation

# Pure Python, no pandas needed
corr = compute_pairwise_correlation(
    returns_a=spy_daily_log_returns,  # list[float]
    returns_b=qqq_daily_log_returns,
    lookback=60,
)
# Returns Pearson correlation -1.0 to 1.0
```

---

### 9.4 Exit Intelligence (3 Functions)

**File:** `market_analyzer/features/exit_intelligence.py`
**Models:** `market_analyzer/models/exit.py`

Call these on every position monitoring cycle. They supplement the existing `monitor_exit_conditions()` from `trade_lifecycle.py` with regime-aware and time-aware exit logic.

#### 9.4.1 `compute_regime_stop()` -- Regime-Contingent Stop Multiplier

```python
from market_analyzer import compute_regime_stop

stop = compute_regime_stop(
    regime_id=current_regime_id,        # 1-4
    structure_type="iron_condor",       # For rationale context
)
# stop.base_multiplier: 2.0 (R1), 3.0 (R2), 1.5 (R3), 1.5 (R4)
# Use as: effective_stop = trade_spec.stop_loss_pct * stop.base_multiplier
```

**Regime stop rationale:**
| Regime | Multiplier | Why |
|---|---|---|
| R1 | 2.0x | Calm MR: breaches are unusual, respect the stop |
| R2 | 3.0x | High-vol MR: wider swings are normal, let mean-reversion work |
| R3 | 1.5x | Trending: trends persist, cut losses fast |
| R4 | 1.5x | Explosive: maximum risk, tightest stop |

**RegimeStop model:** `regime_id`, `base_multiplier`, `structure_type`, `rationale`.

#### 9.4.2 `compute_time_adjusted_target()` -- Trailing Profit Target

Adjusts profit target based on how fast profit is accumulating relative to time elapsed.

```python
from market_analyzer import compute_time_adjusted_target

target = compute_time_adjusted_target(
    days_held=10,
    dte_at_entry=35,
    current_profit_pct=0.40,        # 40% of max profit captured
    original_target_pct=0.50,       # Original target was 50%
)

if target.acceleration_reason:
    # Target was adjusted -- use adjusted target instead
    effective_target = target.adjusted_target_pct
    log(f"TARGET ADJUSTED: {target.acceleration_reason}")
else:
    effective_target = target.original_target_pct
```

**Adjustment triggers:**
- **Fast profit (velocity > 2.0x, profit >= 25%):** Lower target by 15% (min 25%). Close early and redeploy capital.
- **Theta exhausted (60%+ time gone, < 15% profit):** Lower target to current profit or 10% (whichever is higher). Salvage what you can.

**TimeAdjustedTarget model:** `original_target_pct`, `adjusted_target_pct`, `days_held`, `dte_at_entry`, `time_elapsed_pct`, `profit_velocity`, `acceleration_reason: str | None`.

#### 9.4.3 `compute_remaining_theta_value()` -- Hold vs Close Advisory

Compares realized profit against remaining theta (approximated by sqrt curve) to determine if holding is still worthwhile.

```python
from market_analyzer import compute_remaining_theta_value

theta = compute_remaining_theta_value(
    dte_remaining=12,
    dte_at_entry=35,
    current_profit_pct=0.38,
)

if theta.recommendation == "close_and_redeploy":
    # Ratio > 3.0: captured most of what theta can give
    log(f"THETA ADVISORY: {theta.rationale}")
    execute_close(position)
elif theta.recommendation == "approaching_decay_cliff":
    # Ratio 1.5-3.0: prepare exit order
    set_closing_order(position)
else:
    # "hold": theta still working
    pass
```

**Decision thresholds:**
- `profit_to_theta_ratio > 3.0` --> "close_and_redeploy" (captured profit >> remaining theta)
- `profit_to_theta_ratio > 1.5` --> "approaching_decay_cliff" (prepare exit)
- Otherwise --> "hold" (theta still working)

**ThetaDecayResult model:** `dte_remaining`, `dte_at_entry`, `remaining_theta_pct`, `current_profit_pct`, `profit_to_theta_ratio`, `recommendation`, `rationale`.

**Recommended monitoring loop integration:**
```python
# On every monitoring cycle for each open position:
exit_result = monitor_exit_conditions(...)  # existing trade_lifecycle function
stop = compute_regime_stop(current_regime_id, structure_type)
target = compute_time_adjusted_target(days_held, dte_at_entry, current_profit_pct)
theta = compute_remaining_theta_value(dte_remaining, dte_at_entry, current_profit_pct)

# Priority: exit_result.should_close first, then theta advisory, then target adjustment
if exit_result.should_close:
    execute_close(position, exit_result.most_urgent.reason)
elif theta.recommendation == "close_and_redeploy":
    execute_close(position, "theta_exhausted")
elif target.acceleration_reason:
    update_profit_target(position, target.adjusted_target_pct)
```

---

### 9.5 DTE Optimization

**File:** `market_analyzer/features/dte_optimizer.py`

Before building a TradeSpec, use the DTE optimizer to select the expiration with the best theta-per-day from the vol surface term structure.

```python
from market_analyzer import select_optimal_dte

dte_rec = select_optimal_dte(
    vol_surface=vol_surface,       # From ma.vol_surface.compute(ticker)
    regime_id=regime.regime.value,
    strategy="income",             # Context for rationale
    min_dte=14,
    max_dte=60,
)

if dte_rec is not None:
    target_dte = dte_rec.recommended_dte
    target_expiration = dte_rec.recommended_expiration
else:
    # No valid candidates in vol surface -- fall back to regime default
    target_dte = {1: 35, 2: 25, 3: 25, 4: 17}[regime_id]
```

**How it works:**
- Computes `theta_proxy = atm_iv * sqrt(1/DTE)` for each expiration in the valid range
- Higher theta_proxy = more daily theta per unit of IV = better for income trades
- Candidates within the regime-preferred DTE range get a 10% bonus (tiebreaker)

**Regime DTE preferences:**

| Regime | Preferred Range | Rationale |
|---|---|---|
| R1 | 30-45 DTE | Standard theta harvesting window |
| R2 | 21-30 DTE | Shorter exposure to vol swings |
| R3 | 21-30 DTE | Minimize time in adverse trend |
| R4 | 14-21 DTE | Defined risk, minimum exposure |

**DTERecommendation model:** `recommended_dte: int`, `recommended_expiration: date`, `theta_proxy: float`, `iv_at_expiration: float`, `all_candidates: list[dict]`, `regime_preference: str`, `rationale: str`.

Returns `None` if no expirations in the vol surface fall within `[min_dte, max_dte]`.

---

### 9.6 Adjustment Outcome Tracking (Learning Loop)

**File:** `market_analyzer/features/position_sizing.py` (analyze function)
**Models:** `market_analyzer/models/adjustment.py` (AdjustmentOutcome, AdjustmentEffectiveness)

eTrading should record every adjustment outcome for the feedback loop. Over time, this reveals which adjustments actually work in which regimes.

```python
from market_analyzer import AdjustmentOutcome, AdjustmentEffectiveness
from market_analyzer import analyze_adjustment_effectiveness

# After closing a position that was adjusted, record the outcome:
outcome = AdjustmentOutcome(
    trade_id="SPY-IC-20260301",
    adjustment_type="roll_away",        # AdjustmentType value string
    adjustment_date=adjustment_date,
    cost=-0.25,                          # Negative = received credit for the adjustment
    subsequent_pnl=85.0,                # P&L from adjustment date to final close
    was_profitable=True,                # (cost + subsequent_pnl) > 0
    regime_at_adjustment=2,             # Regime when adjustment was made
    position_status_at_adjustment="tested",  # PositionStatus value
)
# Store outcome in eTrading's trade journal DB

# Weekly batch: analyze which adjustments work
all_outcomes = load_adjustment_outcomes_from_db()  # eTrading's responsibility
effectiveness = analyze_adjustment_effectiveness(all_outcomes)

# effectiveness.by_type: {"roll_away": {"count": 12, "win_rate": 0.67, "avg_cost": -15.50, ...}}
# effectiveness.by_regime: {2: {"count": 8, "best_type": "roll_away", "best_win_rate": 0.75}}
# effectiveness.recommendations: ["ROLL_AWAY wins 67% of the time (n=12, avg P&L $85)"]
```

**AdjustmentOutcome fields:** `trade_id`, `adjustment_type`, `adjustment_date`, `cost`, `subsequent_pnl`, `was_profitable`, `regime_at_adjustment`, `position_status_at_adjustment`.

**AdjustmentEffectiveness fields:** `by_type: dict`, `by_regime: dict`, `recommendations: list[str]`, `total_outcomes: int`.

**Minimum data for reliable recommendations:** 3+ outcomes per adjustment type. Below that, the function returns "Insufficient data" instead of spurious recommendations.

---

### 9.7 Integration Checklist

**Pre-trade flow (required for every income trade):**

| Step | API Call | When | Required? |
|---|---|---|---|
| 1 | `run_daily_checks()` | Before EVERY income trade | **YES -- gate** |
| 2 | `run_adversarial_checks()` | Before income trades | **YES -- gate** |
| 3 | `select_optimal_dte()` | At trade construction (before assessor) | Recommended |
| 4 | `score_entry_level()` | After validation passes | Recommended |
| 5 | `compute_limit_entry_price()` | At order placement | Recommended |
| 6 | `compute_position_size()` | At order placement | **YES -- sizing** |

**Post-trade flow (required on every monitoring cycle):**

| Step | API Call | When | Required? |
|---|---|---|---|
| 7 | `monitor_exit_conditions()` | Every monitoring cycle | **YES** |
| 8 | `compute_regime_stop()` | Every monitoring cycle | Recommended |
| 9 | `compute_time_adjusted_target()` | Every monitoring cycle | Recommended |
| 10 | `compute_remaining_theta_value()` | Every monitoring cycle | Recommended |
| 11 | Store `AdjustmentOutcome` | After closing adjusted positions | Recommended |
| 12 | `analyze_adjustment_effectiveness()` | Weekly batch | Recommended |

---

### 9.8 Data eTrading Must Maintain

These fields are NOT stored by market_analyzer (it is stateless). eTrading must persist them and pass them back on each API call.

| Data | Where to Store | Passed To | Why |
|---|---|---|---|
| `entry_regime_id` | Position DB | `monitor_exit_conditions()`, adjustment service | Detect regime changes since entry |
| `days_held` | Position DB (computed from entry date) | `compute_time_adjusted_target()` | Time-based target adjustment |
| `dte_at_entry` | Position DB | `compute_time_adjusted_target()`, `compute_remaining_theta_value()` | Theta curve comparison |
| `entry_price` | Position DB | `monitor_exit_conditions()` | P&L calculation |
| `peak_nlv` | Account DB | `PortfolioExposure.drawdown_pct` | Drawdown circuit breaker |
| `current_risk_pct` | Portfolio DB (sum of max_loss/NLV) | `PortfolioExposure` | Kelly portfolio adjustment |
| `correlation_data` | Pre-computed weekly | `compute_position_size()` via `correlation_fn` | Correlation-adjusted sizing |
| `AdjustmentOutcome` records | Trade journal DB | `analyze_adjustment_effectiveness()` | Learning loop |

---

### 9.9 Complete Pre-Trade Example (End-to-End)

```python
# 1. Detect regime
regime = ma.regime.detect("SPY")
technicals = ma.technicals.snapshot("SPY")
levels = ma.levels.analyze("SPY")

# 2. Select optimal DTE
vol_surface = ma.vol_surface.compute("SPY")
dte_rec = select_optimal_dte(vol_surface, regime.regime.value)
target_dte = dte_rec.recommended_dte if dte_rec else 35

# 3. Build trade (via assessor)
from market_analyzer import assess_iron_condor
opp = assess_iron_condor(regime, technicals, target_dte=target_dte)
trade_spec = opp.trade_spec

# 4. Validate (10 checks + 3 adversarial)
report = run_daily_checks(
    ticker="SPY", trade_spec=trade_spec, entry_credit=1.80,
    regime_id=regime.regime.value, atr_pct=technicals.atr_pct,
    current_price=technicals.current_price,
    avg_bid_ask_spread_pct=1.2, dte=target_dte,
    rsi=technicals.rsi.value, iv_rank=42.0,
    levels=levels, ticker_type="etf",
)
if not report.is_ready:
    return  # BLOCKED

stress = run_adversarial_checks("SPY", trade_spec, 1.80, technicals.atr_pct)
if not stress.is_ready:
    return  # BLOCKED

# 5. Entry scoring
score = score_entry_level(technicals, levels, direction="neutral")
if score.action == "not_yet":
    return  # Wait for better entry

# 6. Position sizing
result = compute_position_size(
    pop_pct=0.72, max_profit=150, max_loss=350,
    capital=50000, risk_per_contract=350,
    regime_id=regime.regime.value, wing_width=5.0,
    exposure=portfolio_exposure,
    open_tickers=["QQQ", "IWM"], new_ticker="SPY",
    correlation_fn=corr_lookup,
)
if result.recommended_contracts == 0:
    return  # Portfolio constraints prevent this trade

# 7. Limit price
limit = compute_limit_entry_price(
    current_mid=1.80, bid_ask_spread=0.15,
    urgency="patient", is_credit=True,
)

# 8. Place order
place_limit_order(
    trade_spec=trade_spec,
    contracts=result.recommended_contracts,
    limit_price=limit.limit_price,
)
```

---

## 10. Decision Audit Framework (March 20)

**File:** `market_analyzer/features/decision_audit.py`
**Models:** `market_analyzer/models/decision_audit.py`

A 4-level scoring framework that audits a proposed trade before execution. Returns a single `DecisionReport` with a grade and `approved: bool`. This supplements (not replaces) `run_daily_checks()` — validation gates block bad trades, the audit grades good trades so you can prioritize.

**Overall score weights:** Trade 35% | Risk 30% | Portfolio 20% | Legs 15% (when leg data present).
**Approved:** `overall_score >= 70`.

### 10.1 `audit_decision()` — Top-Level Entry Point

```python
from market_analyzer.features.decision_audit import audit_decision
from market_analyzer.models.decision_audit import DecisionReport

report: DecisionReport = audit_decision(
    ticker="SPY",
    trade_spec=trade_spec,          # TradeSpec from any assessor
    # --- Leg level (optional but improves score accuracy) ---
    levels=levels_analysis,         # From ma.levels.analyze(ticker). None = no S/R credit
    skew=vol_surface.skew_slice,    # SkewSlice from vol surface. None = no skew credit
    atr=5.20,                       # ATR in dollar terms (technicals.atr)
    # --- Trade level ---
    pop_pct=0.72,                   # From estimate_pop().pop_pct (0-1 fraction)
    expected_value=48.0,            # From estimate_pop().expected_value (dollars)
    entry_credit=1.80,              # Net credit received
    entry_score=0.75,               # From score_entry_level().overall_score
    regime_id=1,                    # From ma.regime.detect().regime.value
    atr_pct=0.85,                   # ATR as % of price
    # --- Portfolio level ---
    open_position_count=3,          # Current open trades (eTrading position DB)
    max_positions=5,                # Account max concurrent trades
    portfolio_risk_pct=0.15,        # Sum(max_loss / NLV) across open positions
    correlation_with_existing=0.25, # Max pairwise correlation (from compute_pairwise_correlation)
    strategy_concentration_pct=0.40, # Fraction of open trades with same structure_type
    directional_score=0.05,         # Net delta direction (-1 to +1). 0 = balanced
    # --- Risk level ---
    capital=50000.0,                # Account NLV
    contracts=1,                    # Proposed contract count (from compute_position_size)
    drawdown_pct=0.03,              # Current drawdown fraction (eTrading account DB)
    stress_passed=True,             # From run_adversarial_checks().is_ready
    kelly_fraction=0.12,            # From compute_position_size().full_kelly_fraction
)

if report.approved:
    # overall_score >= 70 — trade clears the quality bar
    place_order(...)
else:
    log(f"AUDIT REJECTED ({report.overall_score}/100 {report.overall_grade}): {report.summary}")
```

### 10.2 Individual Audit Functions

These are called internally by `audit_decision()`. eTrading can call them directly if partial audits are needed (e.g., only leg quality or only risk audit).

```python
from market_analyzer.features.decision_audit import (
    audit_legs,        # Level 1: strike placement, S/R backing, skew edge, wing width
    audit_trade,       # Level 2: regime fit, POP, EV, commission drag, exit plan, entry timing
    audit_portfolio,   # Level 3: slot availability, correlation, risk budget, concentration
    audit_risk,        # Level 4: position size, drawdown headroom, stress survival, Kelly
)
```

### 10.3 Score Breakdown per Level

**Level 1 — Legs (`LegAudit`):** Scored per short leg. Four sub-checks, each 0–100:

| Sub-check | Weight | Best Score Conditions |
|---|---|---|
| `sr_proximity` | equal | Short strike backed within 1 ATR of an S/R level |
| `skew_advantage` | equal | Short leg IV ≥5% above ATM IV (sell rich premium) |
| `atr_distance` | equal | Short strike 1.0–1.5 ATR from underlying |
| `wing_width` | equal | Wing ≥5 points wide |

Without `levels` data: `sr_proximity` scores 0 (no S/R credit awarded). Without `skew` data: 5/100 (minimal credit, not penalized).

**Level 2 — Trade (`TradeAudit`):** Six sub-checks:

| Sub-check | What It Measures |
|---|---|
| `regime_alignment` | Structure-regime fit (e.g., IC in R1 = 100, IC in R4 = 0) |
| `pop_quality` | POP scaled: 75%+ = A, 40% = F |
| `expected_value` | EV relative to credit collected |
| `commission_drag` | Round-trip commissions as % of credit |
| `exit_plan` | Has profit_target_pct + stop_loss_pct + exit_dte (35+35+30 pts) |
| `entry_timing` | `entry_score` from `score_entry_level()` |

**Level 3 — Portfolio (`PortfolioAudit`):** Five sub-checks — slot availability, correlation with existing positions, risk budget remaining, strategy concentration, directional balance.

**Level 4 — Risk (`RiskAudit`):** Four sub-checks — position size as % of NLV (≤2% = A), drawdown headroom to circuit breaker, stress survival, Kelly alignment.

### 10.4 DecisionReport Model

| Field | Type | Meaning |
|---|---|---|
| `ticker` | `str` | Underlying symbol |
| `structure_type` | `str` | e.g. "iron_condor" |
| `leg_audit` | `LegAudit \| None` | None if trade has no legs |
| `trade_audit` | `TradeAudit` | Level 2 result |
| `portfolio_audit` | `PortfolioAudit` | Level 3 result |
| `risk_audit` | `RiskAudit` | Level 4 result |
| `overall_score` | `float` | Weighted average 0–100 |
| `overall_grade` | `str` | A/B+/B/C/D/F |
| `approved` | `bool` | True if overall_score >= 70 |
| `summary` | `str` | e.g. "82/100 B+ — APPROVED \| Legs: B | Trade: A | Portfolio: B+ | Risk: B" |

### 10.5 Grade Scale

| Score | Grade |
|---|---|
| ≥ 93 | A |
| ≥ 85 | B+ |
| ≥ 77 | B |
| ≥ 70 | C |
| ≥ 60 | D |
| < 60 | F |

### 10.6 Integration Checklist — Decision Audit

- [ ] Call `audit_decision()` after `run_daily_checks()` passes and before placing any order
- [ ] Pass `stress_passed` from `run_adversarial_checks().is_ready` — avoids duplicate stress computation
- [ ] Pass `entry_score` from `score_entry_level().overall_score` — same call, no extra cost
- [ ] Pass `kelly_fraction` from `compute_position_size().full_kelly_fraction` — negative Kelly = severe risk penalty
- [ ] If `report.approved == False` and `overall_score >= 60`: consider logging as shadow trade for learning
- [ ] Store `(ticker, structure_type, overall_score, overall_grade, approved, as_of_date)` in trade journal for quality calibration over time
- [ ] eTrading must provide: `open_position_count`, `portfolio_risk_pct`, `correlation_with_existing`, `strategy_concentration_pct`, `directional_score`, `drawdown_pct` — all from its own position/account DB

---

## 11. March 20 Addenda — Behavior Changes

These are behavior changes to existing APIs (not new APIs). eTrading must update existing call sites.

### 11.1 Minimum Credit Pre-Filter in `run_daily_checks()`

`run_daily_checks()` now returns immediately (before running any of the 10 checks) if `entry_credit < $0.50`. The returned `ValidationReport` contains a single `FAIL` check named `"minimum_credit"` and `report.is_ready == False`.

**What eTrading must do:** The existing check `if not report.is_ready: return` already handles this correctly. No code changes needed. However, the rejection reason should be surfaced to the user — check `report.checks[0].name == "minimum_credit"` to show a specific "credit too low" message rather than a generic validation failure.

```python
report = run_daily_checks(ticker, trade_spec, entry_credit=0.30, ...)
if not report.is_ready:
    if report.checks and report.checks[0].name == "minimum_credit":
        log(f"SKIPPED (credit ${entry_credit:.2f} below minimum $0.50) — not viable after commissions")
    else:
        log(f"BLOCKED: {report.failures} check(s) failed")
    return
```

The pre-filter threshold is `$0.50` per spread ($50/contract). Below this, commissions (~$1.30/contract round-trip for a 2-leg spread) consume a material fraction of the credit and the trade has no edge.

### 11.2 Momentum Override in `score_entry_level()`

`score_entry_level()` now **caps the score at 0.65** (the "wait" threshold) when MACD momentum strongly opposes the entry direction. This prevents "catching a falling knife" — a trade that looks oversold by RSI/Bollinger but has accelerating selling momentum will not score above "wait".

**Trigger conditions:**
- `direction="bullish"` and `macd_histogram < 0` and `|macd_histogram| > 1 ATR` → cap at 0.65
- `direction="bearish"` and `macd_histogram > 0` and `|macd_histogram| > 1 ATR` → cap at 0.65

The `EntryLevelScore.rationale` field includes a `"Momentum override: MACD hist X.XX (Y.Yz ATR) — selling/buying accelerating"` note when the cap fires.

**What eTrading must do:** No API changes. The score itself is already capped — just display `score.rationale` in the UI so the trader sees why the score is "wait" despite other indicators being favorable. For `direction="neutral"` (IC, straddle), the cap never fires.

### 11.3 Strategy Switching in `AdjustmentService.recommend_action()`

`recommend_action()` now accepts an optional `entry_regime_id` parameter. When provided, it enables a new decision branch:

**New decision rule:** If `position_status == TESTED` and `entry_regime_id` was R1/R2 (mean-reverting) but `current_regime_id == R3` (trending), the recommendation is `CONVERT_TO_DIAGONAL` instead of DO_NOTHING.

```python
decision: AdjustmentDecision = ma.adjustment.recommend_action(
    trade_spec=trade_spec,
    regime=current_regime_result,
    technicals=tech,
    entry_regime_id=2,   # NEW: regime at trade entry, stored in position DB
)

# If regime shifted from MR to trending while the IC was open:
# decision.action == AdjustmentType.CONVERT_TO_DIAGONAL (urgency: "soon")
# decision.rationale == "Regime shifted R2->R3 (trending): convert to bearish diagonal..."
```

**`CONVERT_TO_CALENDAR`** is defined in `AdjustmentType` but not yet wired into any decision path. It is reserved for future use when IV term structure analysis is available. Do not check for it in the current monitoring loop.

**Two new `AdjustmentType` values** (added to the existing enum — update any exhaustive match/switch statements):

| Value | Status | Meaning |
|---|---|---|
| `CONVERT_TO_DIAGONAL` | Active | Close IC, open diagonal aligned with trend direction |
| `CONVERT_TO_CALENDAR` | Reserved (not yet wired) | Convert to calendar spread (future use) |

**What eTrading must do:**
- Store `entry_regime_id` in position DB when trade is entered (already required per section 9.8)
- Pass `entry_regime_id` to `recommend_action()` in the monitoring loop
- Handle `CONVERT_TO_DIAGONAL` in the order execution layer (same mechanics as `CONVERT`: close all IC legs, open diagonal legs from `decision.detail.new_legs`)
- Add `CONVERT_TO_DIAGONAL` and `CONVERT_TO_CALENDAR` to any exhaustive switch/match on `AdjustmentType` to avoid unhandled-case errors

### 11.4 IV Rank Quality by Ticker Type (Check #10)

Check #10 (`iv_rank_quality`) added to `run_daily_checks()` uses ticker-type-specific thresholds — not a single global threshold. The `ticker_type` parameter (`"etf"`, `"equity"`, or `"index"`) must be set correctly:

| Ticker type | Good (enter) | Wait | Avoid |
|---|---|---|---|
| ETF | IV rank ≥ 30 | 20–30 | < 20 |
| Equity | IV rank ≥ 45 | 30–45 | < 30 |
| Index (SPX, NDX) | IV rank ≥ 25 | 15–25 | < 15 |

The check produces PASS/WARN/FAIL (`is_ready` is only False if FAIL, which requires IV rank below the "avoid" threshold for the type). Passing `ticker_type="etf"` for an individual stock like AAPL will generate spuriously optimistic pass/warn results.

**What eTrading must do:** Determine `ticker_type` from the instrument type stored in the ticker registry or broker metadata, and pass it on every `run_daily_checks()` call. Default `"etf"` is only safe for actual ETFs.

### 11.5 Integration Checklist — March 20 Changes

| Change | eTrading action required |
|---|---|
| Min credit pre-filter | Display `"minimum_credit"` rejection distinctly (no code change to gate logic) |
| Momentum override | Display `score.rationale` in entry UI — no logic change needed |
| `CONVERT_TO_DIAGONAL` | Handle in order execution layer; pass `entry_regime_id` to `recommend_action()` |
| `CONVERT_TO_CALENDAR` | Add to exhaustive match/switch as passthrough (not yet actionable) |
| `ticker_type` in check #10 | Determine from instrument metadata, pass correctly on every `run_daily_checks()` call |
| `audit_decision()` | New API — wire into pre-trade flow after validation passes (see section 10) |

---

## 12. Crash Sentinel — Market Health Monitoring

eTrading MUST run the crash sentinel on every monitoring cycle (minimum every 15 minutes during market hours). The sentinel returns a signal level and playbook phase that directly controls position management.

### API

```python
from market_analyzer import assess_crash_sentinel, SentinelSignal

report = assess_crash_sentinel(
    regime_results={
        "SPY": {"regime_id": 2, "confidence": 1.0, "r4_prob": 0.0},
        "QQQ": {"regime_id": 4, "confidence": 0.96, "r4_prob": 0.96},
        "IWM": {"regime_id": 1, "confidence": 0.99, "r4_prob": 0.0},
        "GLD": {"regime_id": 1, "confidence": 1.0, "r4_prob": 0.0},
        "TLT": {"regime_id": 2, "confidence": 1.0, "r4_prob": 0.0},
    },
    iv_ranks={"SPY": 43, "QQQ": 43, "IWM": 48, "GLD": 68, "TLT": 45},
    environment="cautious",      # From ma.context.assess().environment_label
    trading_allowed=True,        # From ma.context.assess().trading_allowed
    position_size_factor=0.75,   # From ma.context.assess().position_size_factor
    spy_atr_pct=1.6,             # From ma.technicals.snapshot("SPY").atr_pct
    spy_rsi=29.6,                # From ma.technicals.snapshot("SPY").rsi.value
)
```

### Signal Levels

| Signal | Meaning | eTrading Action |
|--------|---------|-----------------|
| **GREEN** | Normal operations | Standard income trading, all gates normal |
| **YELLOW** | Elevated risk | Reduce max_risk_pct to 20%, avoid R4 tickers, tighten stops to 2.0x |
| **ORANGE** | Pre-crash | CLOSE all positions with DTE > 30, tighten stops to 1.5x, NO new entries |
| **RED** | Crash active | CLOSE ALL positions immediately, 100% cash, halt all automated trading |
| **BLUE** | Post-crash opportunity | Deploy per playbook phase (stabilization or recovery) |

### Playbook Phases + Sizing Overrides

eTrading should apply `report.sizing_params` directly to `PortfolioExposure`:

```python
if report.signal == SentinelSignal.RED:
    # HALT — close everything
    for position in open_positions:
        execute_market_close(position)

elif report.signal == SentinelSignal.ORANGE:
    # Close long-dated, tighten stops
    for position in open_positions:
        if position.dte_remaining > 30:
            execute_market_close(position)
        else:
            update_stop(position, multiplier=1.5)

elif report.signal == SentinelSignal.BLUE:
    # Apply playbook sizing
    params = report.sizing_params
    exposure = PortfolioExposure(
        max_positions=params.get("max_positions", 5),
        max_risk_pct=params.get("max_risk_pct", 0.25),
        drawdown_halt_pct=params.get("drawdown_halt_pct", 0.10),
    )
    safety = params.get("safety_factor", 0.50)
    # Use these overrides for all compute_position_size calls
```

| Phase | max_positions | max_risk_pct | safety_factor | drawdown_halt | DTE |
|-------|---------------|--------------|---------------|---------------|-----|
| normal | 5 | 25% | 0.50 (half Kelly) | 10% | 30-45 |
| elevated | 5 | 20% | 0.50 | 10% | 21-35 |
| pre_crash | 0 | 0% | N/A | N/A | close all |
| crash | 0 | 0% | N/A | N/A | 100% cash |
| stabilization | 3 | 15% | 0.25 (quarter Kelly) | 5% | 21 |
| recovery | 5 | 25% | 0.50 | 10% | 21-35 |

### SentinelReport Fields

| Field | Type | What eTrading uses it for |
|-------|------|--------------------------|
| `signal` | SentinelSignal | Master switch for trading automation |
| `playbook_phase` | str | Which phase of crash playbook is active |
| `sizing_params` | dict | Override PortfolioExposure parameters |
| `actions` | list[str] | Human-readable action items (for alerts/dashboard) |
| `reasons` | list[str] | Why the signal was triggered |
| `r4_count` | int | How many tickers are in explosive regime |
| `avg_iv_rank` | float | Average IV rank (high = rich premiums for BLUE phase) |
| `max_r4_probability` | float | Highest R4 probability across universe |

### Monitoring Schedule

| Signal | Check frequency |
|--------|----------------|
| GREEN | Every 30 minutes |
| YELLOW | Every 15 minutes |
| ORANGE | Every 10 minutes |
| RED | Every 5 minutes (watching for R4 -> R2 transition) |
| BLUE | Every 15 minutes (watching for opportunity window close) |

### Integration Requirement

eTrading MUST store the sentinel signal history. This enables:
1. Tracking signal transitions (GREEN -> YELLOW -> ORANGE timeline)
2. Post-crash analysis (how early did the sentinel warn?)
3. Playbook compliance auditing (did we actually close positions on ORANGE?)

---

## 13. Context-Aware Calculations — Full Mode Checklist

MA operates in `full` mode by default. This means every calculation is portfolio-aware, position-aware, and risk-aware. eTrading MUST pass full context for reliable results. If context is missing, the `TrustReport` will flag `is_actionable=False`.

### What "Full Context" Means

Every call should include these inputs where applicable:

| Input | Source (eTrading) | Used By |
|-------|-------------------|---------|
| `regime_id` | `ma.regime.detect(ticker).regime.value` | ALL calculations |
| `technicals` / `atr_pct` / `rsi` | `ma.technicals.snapshot(ticker)` | Entry score, validation, POP |
| `vol_surface` / `skew` | `ma.vol_surface.surface(ticker)` | Skew strike selection, DTE optimizer |
| `levels` | `ma.levels.analyze(ticker)` | Strike proximity, pullback alerts |
| `iv_rank` | `ma.quotes.get_metrics(ticker).iv_rank` | IV rank quality check, ranking |
| `entry_credit` | Real broker mid from `ma.quotes.get_leg_quotes()` | POP, EV, Kelly, validation |
| `days_to_earnings` | `fundamentals.upcoming_events.days_to_earnings` | Earnings blackout gate |
| `ticker_type` | "etf" / "equity" / "index" from registry | IV rank thresholds |
| `open_positions` / `portfolio_exposure` | eTrading portfolio DB | Kelly correlation adjustment, risk budget |
| `correlation_data` | Pre-computed weekly from OHLCV | Correlated position sizing |
| `entry_regime_id` | Stored at trade entry time | Strategy switching, regime change detection |
| `days_held` / `dte_at_entry` | Position DB | Trailing profit targets, theta decay |
| `peak_nlv` | Account DB | Drawdown circuit breaker |

### Context-Aware APIs (eTrading must pass full context)

#### Pre-Trade (called before every new trade)

| # | API | Critical Context | What changes with full context |
|---|-----|-----------------|-------------------------------|
| 1 | `run_daily_checks()` | entry_credit, iv_rank, levels, days_to_earnings, ticker_type | Without: checks 8-10 all WARN. With: real PASS/FAIL on strike proximity, earnings blackout, IV rank quality |
| 2 | `run_adversarial_checks()` | entry_credit, atr_pct | Without: gamma/breakeven WARN on invalid params. With: real stress test |
| 3 | `estimate_pop()` | entry_credit, current_price, iv_rank | Without: POP off by 10-15%. With: regime+IV calibrated probability |
| 4 | `compute_position_size()` | portfolio_exposure, correlation_data, open_tickers | Without: raw Kelly (ignores existing positions). With: correlation-adjusted, drawdown-aware, margin-regime capped |
| 5 | `score_entry_level()` | levels (for level_proximity component) | Without: 20% of score weight is zero. With: S/R proximity factors into enter/wait decision |
| 6 | `compute_limit_entry_price()` | bid_ask_spread from broker | Without: can't compute. With: patient/normal/aggressive limit price |
| 7 | `select_optimal_dte()` | vol_surface (term structure) | Without: can't optimize. With: picks DTE with best theta/IV ratio |
| 8 | `audit_decision()` | ALL of above + stress results + Kelly fraction | Without: several checks score F. With: complete 4-level report card |
| 9 | `assess_crash_sentinel()` | regime_results for 5 tickers, iv_ranks, spy_atr_pct, spy_rsi | Without: can't assess. With: GREEN/YELLOW/ORANGE/RED/BLUE signal |

#### At Entry (called when placing order)

| # | API | Critical Context | What changes with full context |
|---|-----|-----------------|-------------------------------|
| 10 | `compute_strike_support_proximity()` | levels | Without: can't check. With: PASS/FAIL on S/R backing |
| 11 | `select_skew_optimal_strike()` | skew from vol_surface | Without: uses ATR-only baseline. With: shifts to richest IV premium |
| 12 | `compute_pullback_levels()` | levels | Without: no alerts. With: specific price levels for patient entry |
| 13 | `compute_iv_rank_quality()` | iv_rank, ticker_type | Without: quality unknown. With: good/wait/avoid signal |

#### Position Monitoring (called every monitoring cycle)

| # | API | Critical Context | What changes with full context |
|---|-----|-----------------|-------------------------------|
| 14 | `monitor_exit_conditions()` | regime_stop_multiplier, days_held, dte_at_entry, entry_regime_id | Without: fixed 2x stop, static 50% target. With: regime-contingent stop (R2=3x), trailing profit acceleration, regime change detection |
| 15 | `compute_regime_stop()` | regime_id | Standalone OK — only needs current regime |
| 16 | `compute_time_adjusted_target()` | days_held, dte_at_entry, current_profit_pct | Without: static target. With: "close early at 35% — capital velocity" |
| 17 | `compute_remaining_theta_value()` | dte_remaining, dte_at_entry, current_profit_pct | Without: no recommendation. With: hold/close/approaching_cliff |
| 18 | `check_trade_health()` | regime, technicals, vol_surface, entry_regime_id | Without: basic status only. With: adjustment recommendations + overnight risk |
| 19 | `recommend_action()` | entry_regime_id | Without: standard adjustments. With: CONVERT_TO_DIAGONAL on regime change |

#### Risk Management (called on portfolio level)

| # | API | Critical Context | What changes with full context |
|---|-----|-----------------|-------------------------------|
| 20 | `compute_risk_dashboard()` | all positions, regime_id, peak_nlv | Full portfolio-level assessment |
| 21 | `adjust_kelly_for_correlation()` | open_tickers, correlation_fn | Without: no correlation penalty. With: SPY+QQQ treated as ~1 position |
| 22 | `compute_regime_adjusted_bp()` | regime_id | R2 margin is 1.3x R1 — fewer contracts fit |
| 23 | `filter_trades_with_portfolio()` | open_positions, risk_limits | Without: no portfolio awareness. With: slot/sector/correlation filtering |
| 24 | `evaluate_trade_gates()` | full trade context | 17 gates: BLOCK/SCALE/WARN |

#### Post-Trade (called after closing positions)

| # | API | Critical Context | What changes with full context |
|---|-----|-----------------|-------------------------------|
| 25 | `analyze_adjustment_effectiveness()` | list[AdjustmentOutcome] | Learns which adjustments work by type/regime |
| 26 | `calibrate_weights()` | list[TradeOutcome] | Re-weights ranking factors from actual results |
| 27 | `analyze_gate_effectiveness()` | gate_history, shadow/actual outcomes | Identifies gates that are too tight or too loose |

### Implementation Priority for eTrading

**Phase 1 — Critical (do first):**
APIs 1-4, 9, 14, 20: validation, POP, sizing, sentinel, monitoring, risk dashboard

**Phase 2 — Important (next sprint):**
APIs 5-8, 10-13, 15-19: entry intelligence, exit intelligence, audit

**Phase 3 — Learning loop (after Phase 1+2 are stable):**
APIs 21-27: correlation, calibration, gate effectiveness

### Trust Verification

After implementing each API, eTrading should call `compute_trust_report()` and verify:
```python
report = compute_trust_report(mode="full", has_broker=True, has_iv_rank=True, ...)
assert report.is_actionable  # Must be True before executing any trade
```

---

## 14. MonitoringAction with Closing TradeSpec

### New Field: `closing_trade_spec`

`MonitoringAction` (from `models/exit.py`) now includes:
```python
closing_trade_spec: TradeSpec | None  # Pre-built legs to close position
```

### When Closing Spec Is Populated

1. **TP Hit** — Closing spec = STO/BTC legs for profit-taking close
2. **SL Hit** — Closing spec = STO/BTC legs for loss-cutting close
3. **DTE Expired** — Closing spec = STO/BTC legs for DTE close
4. **Urgency Escalation** (after 15:00 ET for 0DTE, 15:30 for others) — Force-close spec provided

### Integration Pattern

```python
from market_analyzer.trade_lifecycle import monitor_exit_conditions

result = monitor_exit_conditions(
    trade_spec=position_trade_spec,
    current_price=latest_price,
    current_pnl_pct=0.35,
    time_of_day=datetime.now().time(),
    dte_remaining=12,
)

if result.exit_signal:
    # Submit closing_trade_spec directly to broker
    order_result = broker.submit_order(
        trade_spec=result.monitoring_action.closing_trade_spec
    )
```

### Benefit

- No re-computation needed at exit time
- Avoids ordering delays due to calculation overhead
- Guaranteed consistency with entry logic (same strike snapping, lot size)

---

## 15. Position Stress Monitoring API

### Overview

`run_position_stress()` in `service/stress_monitoring.py` stresses open positions across 13 predefined scenarios without requiring broker Greeks.

### Scenarios

| Category | Triggers |
|----------|----------|
| **Price Moves** | -1%, -3%, -5%, -10% |
| **Vol Spikes** | VIX +10, +20, +30 points |
| **Tail Events** | Flash crash (-20% 1-day), Black Monday |
| **Systemic Shocks** | COVID crash, India crash, Fed surprise (75bps) |

### API

```python
from market_analyzer.service.stress_monitoring import run_position_stress

result = run_position_stress(
    positions=open_positions,  # list[PortfolioPosition]
    technicals_map={'SPY': technical_snapshot, ...},
    regime_id=current_regime_id,
    atr_pct_map={'SPY': 0.0142, ...},
)

# result: StressSuiteResult
#   .scenarios[i].positions[j].estimated_loss_pct
#   .scenarios[i].positions[j].max_loss_exceeded
#   .scenarios[i].positions[j].urgency  # NORMAL / ESCALATE / FORCE_CLOSE
```

### Urgency Escalation

- **NORMAL** — Loss within expected range; continue monitoring
- **ESCALATE** — Loss > 50% of max_loss; consider adjustment or partial close
- **FORCE_CLOSE** — Loss > 100% of max_loss (only for undefined-risk structures like equity long); close immediately

### When to Call

- **Daily pre-market** — stress scenarios for all open positions
- **After major moves** — re-stress if intraday drawdown > 2%
- **Before earnings** — stress for events in next 7 days

---

## 16. India TradeSpec Fixes (P0-3 Done)

### 1. Strike Snapping with `strike_interval`

`snap_strike()` now respects market-specific tick sizes:

```python
from market_analyzer.opportunity.option_plays._trade_spec_helpers import snap_strike

# US (1pt step)
strike = snap_strike(price=580.5, current_ask=580.55, strike_interval=1)  # → 580.5

# India equity options (5pt step)
strike = snap_strike(price=19250, current_ask=19265, strike_interval=5)  # → 19250

# India index options (10pt step, NIFTY)
strike = snap_strike(price=23450, current_ask=23465, strike_interval=10)  # → 23450
```

**Wired:** `MarketRegistry.get_instrument(ticker)['strike_interval']` auto-loaded.

### 2. Fallback Setup Legs for India Tickers

`trend_continuation` assessor for NIFTY/BANKNIFTY now falls back to `build_setup_trade_spec()`:

```python
# Old: returned None if no trendline found
# New: falls back to setup-based IC/credit spread

result = assess_trend_continuation(
    ticker='NIFTY',
    regime_id=3,  # Low-vol trending
    technicals=snapshot,
)
# Always returns trade_spec (never None) for India tickers
```

### 3. Equity Long/Short Trade Models

New `StructureType` entries for cash equity positions:

```python
from market_analyzer import build_equity_trade_spec

spec = build_equity_trade_spec(
    ticker='NIFTY',
    shares=1,
    entry_price=23450,
    stop_loss_pct=0.02,  # 2% ATR-based stop
    target_price=23750,  # profit target
    regime_id=3,
)
# spec.structure_type = "equity_long"
# spec.legs[0] = equity entry leg
# spec.exit_notes = ["Close at +2% target", "Stop at -2% ATR stop"]
```

**Benefit:** Unified trade model across options + equities. eTrading can execute both via same `TradeSpec` pipeline.

---

## 17. Stock Screener Data Quality

### Known eTrading Mismatches

**Issue P2-5:** Stock screener OHLCV period mismatch + dividend yield double-division.

| Problem | eTrading Call | MA Expectation | Fix |
|---------|---------------|----------------|-----|
| OHLCV period | `get_ohlcv(ticker, period='1y')` | `days=365` parameter | Use `days=365` instead of `period='1y'` |
| Dividend yield | `result.dividend_yield * 100` | Already a ratio (0.042 = 4.2%) | Remove `* 100` (yfinance returns ratio, not percentage) |

**Example Fix (eTrading):**
```python
# Before (broken)
ohlcv = ma.data_service.get_ohlcv(ticker, period='1y')  # Wrong parameter
div_yield = ohlcv.dividend_yield * 100  # Double-divide

# After (fixed)
ohlcv = ma.data_service.get_ohlcv(ticker, days=365)  # Correct parameter
div_yield = ohlcv.dividend_yield  # Already a ratio
```

**MA-Side OK:** APIs are correct; eTrading parameter contracts just need alignment.

---

## 18. All Recommendations Return TradeSpec

### Change Summary

Every opportunity assessor now returns a `trade_spec: TradeSpec | None` field.

### Affected Assessors

| Assessor | Returns TradeSpec |
|----------|-------------------|
| `assess_iron_condor()` | ✅ Yes (structure, legs, exit rules) |
| `assess_iron_butterfly()` | ✅ Yes |
| `assess_calendar()` | ✅ Yes |
| `assess_zero_dte()` | ✅ Yes (+ ORB decision) |
| `assess_ratio_spread()` | ✅ Yes |
| `assess_diagonal()` | ✅ Yes |
| `assess_leap()` | ✅ Yes |
| `assess_earnings()` | ✅ Yes |
| `assess_breakout()` | ✅ Yes (setup credit spread) |
| `assess_momentum()` | ✅ Yes (setup debit spread) |
| `assess_mean_reversion()` | ✅ Yes (setup IC or iron butterfly) |
| `assess_orb()` | ✅ Yes (setup credit spread or iron man) |

### Integration for eTrading

```python
# Every assessor call returns trade_spec
from market_analyzer import ma

result = ma.opportunity.assess_iron_condor(
    ticker='SPY',
    regime_id=1,
    technicals=snapshot,
    vol_surface=surface,
)

if result.trade_spec:
    # Directly submit or score/filter
    score = ma.ranking.score_trade(result.trade_spec, ...)
```

No more "no action" or menu selection — every result is actionable (or None).

If `is_actionable` is False, DO NOT proceed with the trade. Fix the missing context first.

---

## 19. Supported Brokers — What eTrading Needs to Know

MA now supports 6 brokers. eTrading's `connect_from_sessions()` pattern works the same for all — pass pre-authenticated sessions, get the 4-tuple.

| Broker | Market | Status | SDK | connect function |
|--------|--------|--------|-----|-----------------|
| TastyTrade | US | Full | `tastytrade` | `connect_tastytrade()` / `connect_from_sessions()` |
| Alpaca | US | Full | `alpaca-py` | `connect_alpaca(api_key, secret)` |
| IBKR | US/Global | Full | `ib_insync` | `connect_ibkr(host, port)` |
| Schwab | US | Full | `schwab-py` | `connect_schwab(app_key, secret, token_path)` |
| Zerodha | India | Full | `kiteconnect` | `connect_zerodha(api_key, access_token)` |
| Dhan | India | Full | `dhanhq` | `connect_dhan(client_id, access_token)` |

**For eTrading SaaS:** Every broker has a `connect_*_from_session()` variant that accepts pre-authenticated SDK sessions (eTrading manages auth/refresh).

**What changes for eTrading:** NOTHING in the analysis pipeline. All brokers map to the same `OptionQuote`, `MarketMetrics`, `AccountBalance` models. The 27 context-aware APIs work identically regardless of which broker is connected.

**Broker auto-detection:** `connect_broker()` in `cli/_broker.py` checks `~/.market_analyzer/broker.yaml` for `broker_type` field, or probes credentials in order: TastyTrade → Alpaca → Dhan → Schwab → IBKR.

---

## 20. India Market: eTrading Delayed Data Service (Planned)

**Problem:** India has very limited free market data APIs. Unlike the US (where Alpaca offers free delayed quotes), India users without a Dhan/Zerodha account have no way to get option chain data with Greeks.

**Solution:** eTrading hosts a delayed data endpoint using owner's Dhan credentials.

**Architecture:**
```
India user (no broker)
    → MA connects to eTrading data API (like any MarketDataProvider)
        → eTrading server fetches from Dhan (owner's credentials)
            → Cache with 10-20 min TTL
                → Return delayed OptionQuote + Greeks to MA
```

**What eTrading builds:**
1. REST endpoint: `GET /api/v1/india/option-chain/{ticker}` → returns cached Dhan option chain
2. Cache layer: Redis or in-memory, 10-20 min TTL per ticker
3. Rate limit: Dhan allows 20K requests/day, 1 per 3 seconds for option chain
4. Serve: standard `OptionQuote` JSON format (same as all other brokers)

**What MA needs:** A new `EtradingDataProvider` that calls eTrading's REST endpoint instead of Dhan directly. This is a simple HTTP adapter — ~50 lines of code.

**Trust level for delayed data:**
- Data quality: MEDIUM (real Dhan data, but delayed 10-20 min)
- Fit for: screening, research, regime detection, paper trading, forward testing
- NOT fit for: live execution (users need their own Dhan/Zerodha for that)

**eTrading API contract:**
```json
GET /api/v1/india/option-chain/NIFTY

Response:
{
  "ticker": "NIFTY",
  "as_of": "2026-03-21T10:30:00+05:30",
  "delay_minutes": 15,
  "data_source": "dhan_delayed",
  "quotes": [
    {
      "strike": 26000, "option_type": "call", "expiration": "2026-03-27",
      "bid": 150.0, "ask": 155.0, "mid": 152.5,
      "iv": 0.225, "delta": 0.55, "gamma": 0.002, "theta": -8.5, "vega": 12.0,
      "volume": 50000, "open_interest": 250000
    }
  ]
}
```

**Priority:** This unblocks India adoption. Build after Dhan broker is validated in production.

---

## 21. Desk Management APIs (March 21, 2026)

6 pure functions for portfolio desk management, capital allocation, rebalancing, health monitoring, and instrument risk sizing. All stateless — no broker calls, no DB.

### Import

```python
from market_analyzer.features.desk_management import (
    recommend_desk_structure,
    rebalance_desks,
    evaluate_desk_health,
    suggest_desk_for_trade,
    compute_desk_risk_limits,
    compute_instrument_risk,
)
from market_analyzer.models.portfolio import (
    DeskRecommendation, DeskSpec, DeskHealthReport, DeskRiskLimits,
    InstrumentRisk, RebalanceRecommendation, RiskTolerance, DeskHealth,
)
```

---

### API 1: `recommend_desk_structure()`

Recommend how to split capital across trading desks based on risk tolerance and current regime.

```python
rec: DeskRecommendation = recommend_desk_structure(
    total_capital=100_000,
    risk_tolerance="moderate",   # "conservative" | "moderate" | "aggressive"
    market="US",                 # "US" | "India"
    regime={"SPY": 1, "QQQ": 2}, # optional — adjusts allocations
)

# rec.desks: list[DeskSpec]  — one per trading style
# rec.unallocated_cash: float — cash reserve
# rec.cash_reserve_pct: float — reserve as fraction
# rec.regime_context: str     — human-readable regime adjustment explanation

# Invariant: sum(d.capital_allocation for d in rec.desks) + rec.unallocated_cash == total_capital
```

**Desk structure by tolerance:**

| Tolerance | Cash | Desks |
|-----------|------|-------|
| Conservative | 10% | income (40%), core (40%), 0dte (10%) |
| Moderate | 8% | 0dte (15%), income (35%), core (30%), growth (12%) |
| Aggressive | 5% | 0dte (20%), income (30%), directional (25%), core (20%) |

**Regime adjustments applied automatically:**
- R4 anywhere → +15% cash, 0DTE/directional halved
- R2 majority → 0DTE −25%, income +freed capital
- R3 → income −15%, directional +freed capital

**India market:** `desk_expiry_day` replaces `desk_0dte`. Underlyings: NIFTY, BANKNIFTY. Includes lot-size note in rationale.

**eTrading action required:**
- Call on account creation, risk tolerance change, or major regime shift
- Store `DeskSpec` list per user — use `desk_key` as stable identifier
- Pass `regime` map from MA's latest regime detection for best results
- `DeskSpec.risk_limits` dict contains `max_single_position_pct`, `circuit_breaker_pct`, `max_correlated_positions` — enforce these before each trade

---

### API 2: `rebalance_desks()`

Check whether desks need rebalancing and compute adjustment targets.

```python
result: RebalanceRecommendation = rebalance_desks(
    current_desks=[{"desk_key": "desk_income", "current_capital": 40_000}, ...],
    target_desks=[{"desk_key": "desk_income", "target_capital": 35_000}, ...],
    account_drawdown_pct=0.07,     # 7% drawdown
    regime_changed=False,
    days_since_last_rebalance=35,
    drift_threshold_pct=0.20,      # 20% drift = trigger
)

# result.needs_rebalance: bool
# result.trigger: "regime_change" | "drawdown" | "performance_drift" | "periodic" | "none"
# result.adjustments: list[DeskAdjustment]  — each has desk_key, change (+ add / - reduce), reason
```

**Trigger priority:**
1. `regime_changed=True` → reallocate to match new regime profile
2. `account_drawdown_pct > 0.05` → reduce all desks proportionally
3. Any desk drifted >20% from target → rebalance drifted desks only
4. `days_since_last_rebalance > 30` → periodic sweep

**eTrading action required:**
- Check every morning before market open (or on regime change notification)
- For `trigger="drawdown"`: all `adj.change` are negative — reduce positions to free capital
- For `trigger="performance_drift"`: some desks grow (positive change), others shrink
- Do NOT move capital if open positions block it — queue the rebalance for next trade closure

---

### API 3: `evaluate_desk_health()`

Score a desk's performance from trade history.

```python
report: DeskHealthReport = evaluate_desk_health(
    desk_key="desk_income",
    trade_history=[
        {"pnl": 200.0, "won": True, "days_held": 18.0},
        {"pnl": -100.0, "won": False, "days_held": 22.0},
        ...
    ],
    capital_deployed=35_000,
    current_regime=2,                          # optional
    desk_strategy_types=["iron_condor", "credit_spread"],  # optional
)

# report.health: DeskHealth  ("excellent"|"good"|"caution"|"poor"|"critical")
# report.score: float  (0-1)
# report.win_rate: float | None
# report.profit_factor: float | None
# report.capital_efficiency: float  (annualized ROC as fraction)
# report.regime_fit: "well_suited" | "neutral" | "poor_fit"
# report.issues: list[str]
# report.suggestions: list[str]
```

**Health thresholds:**
| Score | Health |
|-------|--------|
| ≥0.80 | excellent |
| ≥0.65 | good |
| ≥0.50 | caution |
| ≥0.30 | poor |
| <0.30 | critical |

**eTrading action required:**
- Build `trade_history` from closed positions (pnl, won=pnl>0, days_held=close_date−open_date)
- Run weekly or after 10+ closed trades per desk
- If `health == "critical"` → pause new entries on that desk until reviewed
- If `regime_fit == "poor_fit"` → surface warning before next trade entry on this desk

---

### API 4: `suggest_desk_for_trade()`

Route a proposed trade to the best-fit desk.

```python
result: dict = suggest_desk_for_trade(
    desks=[d.model_dump() for d in rec.desks],  # from recommend_desk_structure
    trade_dte=45,
    strategy_type="iron_condor",
    ticker="SPY",
    existing_positions_by_desk={"desk_income": ["SPY", "GLD"], "desk_0dte": ["QQQ"]},
)

# result["desk_key"]: str | None   — best desk
# result["reason"]: str            — why this desk was chosen
# result["score"]: float           — match quality 0-1
# result["alternatives"]: list[dict]  — runner-up desks
```

**Match criteria (weighted):**
1. DTE range fit — 50 points
2. Strategy type in desk's supported list — 30 points
3. Capacity headroom (positions remaining) — 15 points
4. Ticker not already in desk (correlation) — 5 points

**eTrading action required:**
- Call after `rank()` produces a candidate trade, before `filter_trades_with_portfolio()`
- If `result["desk_key"]` is None → no desk has capacity, do not enter trade
- If `result["score"] < 0.3` → poor fit, surface warning to trader
- Store `desk_key` on each open position for health monitoring

---

### API 5: `compute_desk_risk_limits()`

Get regime-adjusted position limits for a desk.

```python
limits: DeskRiskLimits = compute_desk_risk_limits(
    desk_key="desk_income",
    base_max_positions=10,
    base_max_single_position_pct=0.12,
    base_circuit_breaker_pct=0.07,
    regime_id=2,
    account_drawdown_pct=0.0,
)

# limits.max_positions: int
# limits.max_single_position_pct: float
# limits.max_portfolio_delta: float
# limits.max_daily_loss_pct: float
# limits.circuit_breaker_pct: float   (NOT scaled — hard stop)
# limits.position_size_factor: float  (multiply base size by this)
# limits.rationale: str
```

**Regime scaling:**
| Regime | Income Desk | Directional Desk | size_factor |
|--------|-------------|------------------|-------------|
| R1 | 100% | 100% | 1.0 |
| R2 | 80% | 80% | 0.8 |
| R3 | 70% | 100% | 0.7 / 1.0 |
| R4 | 50% | 50% | 0.5 |
+ drawdown >5%: additional 50% reduction on top

**eTrading action required:**
- Call on each regime change (or daily morning)
- Apply `position_size_factor` to base contract quantity before entry
- Enforce `circuit_breaker_pct` — if desk P&L hits this loss threshold, pause all new entries
- `max_correlated_positions` applies per underlying (e.g. max 2 SPY trades per desk)

---

### API 6: `compute_instrument_risk()`

Per-instrument risk sizing for position management.

```python
risk: InstrumentRisk = compute_instrument_risk(
    ticker="SPY",
    instrument_type="option_spread",   # "option_spread"|"equity_long"|"futures"|"naked_option"
    position_value=150.0,
    regime_id=2,
    wing_width=5.0,    # option_spread: spread width in points
    lot_size=100,      # US options = 100, NIFTY = 75, BANKNIFTY = 50
)

# risk.max_loss: float          — defined or estimated max loss
# risk.expected_loss_1d: float  — expected 1-day loss (regime-scaled)
# risk.margin_required: float   — margin to reserve
# risk.risk_category: str       — "defined" | "undefined" | "equity"
# risk.risk_method: str         — "max_loss" | "atr_based" | "margin_based"
# risk.regime_factor: float     — multiplier used (R1=0.40, R2=0.70, R3=1.10, R4=1.50)
# risk.rationale: str           — human-readable calculation trace
```

**Per instrument type:**
- `option_spread`: `max_loss = wing_width × lot_size` (defined risk)
- `equity_long`: `expected_loss_1d = position_value × atr_pct × regime_factor`
- `futures`: `margin_required = contract_value × margin_pct × regime_factor`
- `naked_option`: `max_loss = underlying_price × lot_size` — flagged as UNDEFINED RISK

**India lot sizes:** NIFTY=75, BANKNIFTY=50, FINNIFTY=40 — pass via `lot_size` parameter.

**eTrading action required:**
- Call for every new position before entry to get `margin_required`
- Sum `margin_required` across all desk positions to check against `DeskSpec.capital_allocation`
- If `risk_category == "undefined"` and `DeskSpec.allow_undefined_risk == False` → BLOCK trade
- Feed `expected_loss_1d` into risk dashboard for VaR-style reporting
- For naked options: always surface `risk.rationale` to trader before approval

---

### Summary: Where Each API Fits in the Trade Pipeline

```
scan → rank → [suggest_desk_for_trade] → filter_trades_with_portfolio
             → [compute_instrument_risk]  → evaluate_trade_gates
             → [compute_desk_risk_limits] → entry
                       ↓
           [evaluate_desk_health]  (weekly, from closed trades)
           [rebalance_desks]       (daily pre-market)
           [recommend_desk_structure] (on account setup or regime shift)
```

**Critical invariant:** `rank()` output is NOT safe to execute directly. Always call `suggest_desk_for_trade()` → `filter_trades_with_portfolio()` → `evaluate_trade_gates()` before execution.
