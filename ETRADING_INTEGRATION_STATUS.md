# eTrading Integration Status vs Gaps
*Tested: 2026-03-17 against http://localhost:8080*

---

## Summary

| Category | Status |
|----------|--------|
| Broker connection | ✅ Working |
| Cross-market analysis | ✅ Working |
| Portfolio/position sync | ✅ Working |
| Macro research report | ✅ Working |
| Deployment plan | ⚠️ Partial (hardcoded capital) |
| Macro dashboard indicators | ❌ All null |
| Risk dashboard (VaR) | ❌ All null |
| Chat/CLI command routing | ❌ All commands fall back to `status` |
| Regime/Ranking/Adjustment APIs | ❌ Not exposed as REST endpoints |
| Stock screener data quality | ❌ Wrong OHLCV period, wrong dividend yield |
| Positions group endpoint | ❌ 404 broken |
| VIX live data | ❌ Shows "?" |

---

## Feature-by-Feature Status

### 1. Pre-Market: Is Today Safe?

#### 1a. Market Context (`ma.context.assess()`)
- **CLI:** `context` → returns `status` output instead. **BROKEN — command not routed.**
- **REST:** No `/api/v2/context` endpoint exists.
- **Gap:** `environment_label`, `trading_allowed`, `position_size_factor`, `tradeable` fields never surfaced to UI.

#### 1b. Black Swan Alert (`ma.black_swan.alert()`)
- **CLI:** No `stress` command routed — falls back to `status`.
- **REST:** No `/api/v2/black-swan` endpoint.
- **Gap:** `alert_level`, `composite_score` never shown. If BLACK SWAN CRITICAL fires, eTrading won't know.

#### 1c. Macro Calendar (`ma.macro.calendar()`)
- **CLI:** `macro` tool is called from chat ✅ (seen in `tools_called`)
- **REST:** `/api/v2/macro` returns data but `bond_market`, `credit_spreads`, `dollar_strength`, `inflation_expectations` are ALL `null`.
- **Root cause:** `compute_macro_dashboard()` requires OHLCV for TNX, TLT, HYG, UUP, TIP. These are not being fetched and passed in. The function is called with empty/None data.
- **Impact:** Macro risk assessment is blind — overall_risk="moderate" is a default, not computed.

#### 1d. Full Macro Research Report (`generate_research_report()`)
- **CLI:** ✅ Working — chat `research` tool calls it, returns full STAGFLATION regime, sentiment, India analysis.
- **REST:** `/api/v2/macro/intelligence` — not tested directly but CLI confirms it works.
- **Data used:** 22 assets, real OHLCV, correct.
- **Issue:** Report dated 2026-03-16 (yesterday) — caching is serving stale report.

#### 1e. Cross-Market Analysis (`analyze_cross_market()`)
- **REST:** `/api/v2/cross-market` ✅ Working.
- **Data:** Real correlation (0.15), real regimes (US=R2, India=R4), predicted gap (+0.09%).
- **Issue:** `signals: []` — no signals generated despite R4 India and FII outflow. MA should generate signals here.

---

### 2. Market Open: Find Opportunities

#### 2a. Regime Detection (`ma.regime.detect()`)
- **CLI:** `regime SPY` → falls back to `status`. **BROKEN — command not routed.**
- **REST:** No `/api/v2/regime` endpoint.
- **Critical gap:** Regime is the foundation of ALL trading decisions. eTrading has no way to fetch per-instrument regime. The macro research report gives a macro regime (STAGFLATION) but per-instrument HMM regime (R1-R4) is completely missing.

#### 2b. Technical Analysis (`ma.technicals.snapshot()`)
- **CLI:** `technicals SPY` → falls back to `status`. **BROKEN.**
- **REST:** No `/api/v2/technicals` endpoint.
- **Gap:** RSI, ATR, MACD, support/resistance levels — none surfaced.

#### 2c. Universe / Screening
- **CLI:** `screen` → falls back to `status`. **BROKEN.**
- **REST:** `/api/v2/stocks/screen` exists but has data quality issues:
  - QQQ `period_return_pct: 452.68%` — **wrong period**, returning long-term cumulative return instead of daily
  - QQQ `atr_pct: 13.34%` — massively wrong daily ATR (should be ~1.5%)
  - JNJ `dividend_yield: 214%`, JPM `dividend_yield: 210%` — **fundamentals calculation broken** (likely raw value not divided by price, or wrong field from yfinance)
  - GLD `period_return_pct: -3.55%` — this one looks correct for daily
- **Root cause:** OHLCV period selector using wrong lookback for some tickers.

#### 2d. Levels Analysis (`ma.levels.analyze()`)
- **CLI:** `levels SPY` → falls back to `status`. **BROKEN.**
- **REST:** No endpoint.

---

### 3. Trade Selection: Score and Filter

#### 3a. Ranking (`ma.ranking.rank()`)
- **CLI:** `rank SPY GLD QQQ` → falls back to `status`. **BROKEN — command not routed.**
- **REST:** No `/api/v2/rank` endpoint.
- **Critical gap:** This is the primary trade selection tool. Without it, eTrading has no ranked trade list and no `TradeSpec` objects to execute.
- **iv_rank_map:** Unknown if broker IV rank is ever passed to ranking. Likely not since ranking isn't called.

#### 3b. Portfolio-Aware Filtering (`filter_trades_with_portfolio()`)
- **Status:** Cannot be called — depends on ranking which is broken.
- **Gap:** `open_positions` from broker are synced but never passed to MA's filter. Portfolio risk limits never enforced at entry.

#### 3c. Trade Gate Framework (`evaluate_trade_gates()`)
- **Status:** Not called anywhere visible.
- **Gap:** No BLOCK/SCALE/WARN enforcement before any trade.

#### 3d. Risk Dashboard (`compute_risk_dashboard()`)
- **REST:** `/api/v2/risk` returns all nulls for VaR, macro:
  ```json
  "var": { "var_95": null, "var_99": null }
  "macro": { "regime": null, "vix": null }
  ```
- **Root cause:** `compute_risk_dashboard()` not being called with real `PortfolioPosition` objects. Portfolio has BAC equity (delta=100) but VaR=0.
- **Portfolio shows `var_1d_95: 0.0`** — not computed, defaulted to zero.
- **Impact:** `dashboard.can_open_new_trades` cannot be trusted. The drawdown gate (HALT at 10%) never fires.

#### 3e. Daily Trading Plan (`ma.plan.generate()`)
- **CLI:** `plan SPY GLD QQQ` → falls back to `status`. **BROKEN.**
- **REST:** No endpoint.

---

### 4. Pre-Entry Validation

#### 4a. POP Estimate (`estimate_pop()`)
- **CLI:** `pop` → falls back to `status`. **BROKEN.**
- **REST:** No endpoint.
- **Gap:** `iv_rank` never passed (broker connected, IV rank available). POP calculation uses default regime factor.

#### 4b. Income Entry Check (`check_income_entry()`)
- **CLI:** Not routed.
- **Gap:** `iv_rank`, `iv_percentile` from broker never passed in.

#### 4c. Execution Quality (`validate_execution_quality()`)
- **Status:** Not called. No quotes validation before entry.

#### 4d. Entry Window
- **Status:** `TradeSpec.entry_window_start/end` exist but never checked. Orders could be submitted outside entry window.

---

### 5. At Entry

#### 5a. Position Sizing (`spec.position_size()`)
- **Status:** Not called. `contracts=1` hardcoded on all trades.
- **Gap:** Account size ($32K actual) never used for sizing.

#### 5b. Income Yield (`compute_income_yield()`)
- **CLI:** `yield` → falls back to `status`. **BROKEN.**

#### 5c. Greeks Aggregation (`aggregate_greeks()`)
- **Portfolio Greeks:** `portfolio_delta: 100.0` for BAC equity — this appears correct (100 shares = delta 100).
- **Options Greeks:** `portfolio_theta: 0.0`, `portfolio_vega: 0.0` — no options in portfolio yet so not testable.
- **Gap:** `aggregate_greeks()` from MA not called — portfolio Greeks appear to be broker-synced raw values, not MA-computed net Greeks.

---

### 6. Position Monitoring

#### 6a. Exit Condition Monitoring (`monitor_exit_conditions()`)
- **Status:** `exit_signals: 0` shown in status — endpoint exists in workflow.
- **Gap:** `current_mid_price` for open legs — unknown if real broker prices or null. BAC position shows `current_price: null` at position level.

#### 6b. Trade Health Check (`check_trade_health()`)
- **CLI:** `health` → falls back to `status`. **BROKEN.**
- **Gap:** `regime` and `technicals` parameters — unknown if live regime passed or defaulted.

#### 6c. Adjustment (`ma.adjustment.recommend_action()`)
- **CLI:** `adjust BAC` → falls back to `status`. **BROKEN.**
- **REST:** No `/api/v2/adjust` endpoint.
- **Critical gap:** Open position (BAC equity) has no adjustment analysis. No BREACHED/MAX_LOSS detection running.

---

### 7. Capital Deployment

#### 7a. Deployment Plan (`plan_deployment()`)
- **REST:** `/api/v2/deployment/plan` ✅ Working — generates 12-month schedule.
- **Issue 1:** Uses hardcoded `total_capital: 50000.0` instead of real account equity ($32,261).
- **Issue 2:** All 12 months identical — no `acceleration_reason` ever triggered. MA's regime-based acceleration (R4 + deep value = accelerate) is not connected to real regime signal.
- **Fix:** Pass `capital=portfolio.total_equity` and `regime=ma.regime.detect("SPY").regime`.

#### 7b. Allocation (`recommend_core_portfolio()`)
- **REST:** `/api/v2/allocation` ✅ Returns allocation split.
- **Issue:** Regime shows "stagflation" (from research) but macro regime from HMM is R2. These are different regime types. eTrading is correctly using the research macro regime for allocation.

---

### 8. Data & Infrastructure

#### 8a. Broker Connection
- **TastyTrade:** ✅ Connected (data mode), `can_execute: false`.
- **Issue:** `can_execute: false` means no real orders. This is correct for now but needs to be wired when ready.

#### 8b. Position Sync
- **BAC equity position** synced from broker ✅
- `entry_underlying_price: null`, `current_price: null` at position level — underlying price not fetched at sync time.

#### 8c. VIX
- **Status shows VIX: ?** — VIX not being fetched. MA has VIX in `reference_tickers`. Should call `data_service.get_ohlcv("VIX")` on startup.

#### 8d. Chat/CLI Command Router
- **CRITICAL:** Every command except `macro`, `research`, `status` falls back to `status`.
- Commands tested that all returned `status`: `rank`, `plan`, `context`, `adjust`, `regime`, `health`, `technicals`, `levels`, `screen`.
- The CLI chat interface recognizes `macro` and `research` tools but nothing else from the MA CLI command set.
- **This means the entire MA command surface (30+ commands) is unreachable from eTrading's CLI.**

---

## Priority Fix List

### P0 — Blocking (no trading system without these)

| # | Fix | Impact |
|---|-----|--------|
| P0-1 | **Wire regime detection** — call `ma.regime.detect(ticker)` and expose as `/api/v2/regime/{ticker}`. Pass result into ranking, plan, adjustments. | Without regime, nothing in MA works correctly |
| P0-2 | **Fix CLI command router** — `rank`, `plan`, `context`, `adjust`, `health`, `regime` must route to MA CLI, not fall back to `status` | 30+ commands unreachable |
| P0-3 | **Wire ranking** — call `ma.ranking.rank(tickers, iv_rank_map=broker_iv_ranks)` and expose as `/api/v2/rank`. Pass `iv_rank_map` from broker `get_metrics()`. | No trade selection without this |
| P0-4 | **Wire adjustment** — call `ma.adjustment.recommend_action(trade_spec, regime, technicals)` on each open position in monitoring loop | No position protection without this |

### P1 — High (risk management broken)

| # | Fix | Impact |
|---|-----|--------|
| P1-1 | **Fix VaR** — call `compute_risk_dashboard(positions, account_nlv, peak_nlv, regime_id)` with real `PortfolioPosition` objects built from synced positions | VaR=0 is dangerous — drawdown gate never fires |
| P1-2 | **Fix macro dashboard** — fetch OHLCV for TNX, TLT, HYG, UUP, TIP and pass to `compute_macro_dashboard()` | bond_market, credit_spreads, dollar_strength all null |
| P1-3 | **Wire trade gates** — call `evaluate_trade_gates()` before every order submission | No BLOCK/SCALE/WARN protection |
| P1-4 | **Fix deployment plan capital** — use `portfolio.total_equity` not hardcoded 50000 | Wrong sizing for real account |

### P2 — Medium (data quality)

| # | Fix | Impact |
|---|-----|--------|
| P2-1 | **Fix stock screener OHLCV period** — QQQ showing 452% daily return, ATR 13%. Wrong lookback window. | Screener scores meaningless |
| P2-2 | **Fix dividend yield calculation** — JNJ 214%, JPM 210% are wrong. Check `dividendYield` field from yfinance (already a ratio, don't divide again). | Income screener useless |
| P2-3 | **Fetch VIX on startup** — call `data_service.get_ohlcv("VIX")` so status shows real VIX | Shows "?" |
| P2-4 | **Pass `iv_rank_map` to ranking** — broker is connected, `get_metrics(ticker)` returns IV rank. This must be passed to `ma.ranking.rank()` | Without IV rank, ranking uses defaults — wrong trade selection |
| P2-5 | **Fix deployment plan acceleration** — pass live regime from `ma.regime.detect("SPY")` to `plan_deployment()` | All months identical — regime-based acceleration never triggers |

### P3 — Lower (completeness)

| # | Fix | Impact |
|---|-----|--------|
| P3-1 | **Add `/api/v2/context`** — expose `ma.context.assess()` | Trading allowed / position size factor never shown |
| P3-2 | **Add `/api/v2/black-swan`** — expose `ma.black_swan.alert()` | Black swan critical state never surfaced |
| P3-3 | **Fix position group endpoint** — `/api/v2/positions/group` returns 404 | UI component broken |
| P3-4 | **Wire entry window check** — validate `TradeSpec.entry_window_start/end` before order submission | Orders placed outside optimal window |
| P3-5 | **Wire position sizing** — call `spec.position_size(capital, risk_pct)` instead of hardcoding `contracts=1` | All trades sized at 1 contract regardless of account |
| P3-6 | **Wire `filter_trades_with_portfolio()`** — pass real open positions from broker sync | Portfolio risk limits never enforced |

---

## What's Working Well

- TastyTrade broker connection and position sync ✅
- Cross-market analysis (US→India gap prediction) ✅
- Full macro research report (22 assets, STAGFLATION detected) ✅
- Portfolio account data (equity, buying power, margin) ✅
- Deployment plan structure (12-month schedule) ✅
- India-specific: regime for ^NSEI (R4), India VIX, FII flow direction ✅
