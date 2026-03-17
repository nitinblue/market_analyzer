# eTrading Capability Audit — MA Integration
*Tested: 2026-03-17 | Broker: tastytrade (data mode) | Server: localhost:8080*

---

## Summary

| Category | Wired | Partial | Not Wired | Broken |
|----------|-------|---------|-----------|--------|
| Portfolio | 4 | 0 | 0 | 0 |
| Risk | 0 | 1 | 2 | 1 |
| Trading | 2 | 2 | 1 | 1 |
| Analytics | 2 | 0 | 2 | 0 |
| Intelligence | 3 | 1 | 0 | 1 |
| Stocks | 2 | 2 | 0 | 2 |
| Analysis | 1 | 0 | 0 | 3 |
| Admin | 3 | 0 | 0 | 0 |

---

## Tool-by-Tool Results

### PORTFOLIO

#### `positions` — ✅ WIRED
- Shows BAC equity_long, P&L -$4,788, Delta +100
- Greeks shown per position
- **MA integration:** health status field present, desk assignment present
- **Gap:** `current_price` null at position level — mark not running (see syshealth error)

#### `portfolios` — ✅ WIRED
- Real account data: equity $32,262, cash $27,531, buying_power shown
- Greeks totals present
- **Gap:** `var_1d_95: 0.0` — VaR not computed, scenario testing not wired here

#### `capital` — ✅ WIRED
- Shows Tastytrade 5WZ78765 at 14.7% deployed, $27,531 idle
- Zerodha and other portfolios shown
- **Gap:** Capital: $0 initial for tastytrade — initial capital not set from broker sync

#### `greeks` — ✅ WIRED
- Delta +100.0 / 500 limit (20% used) — correct for BAC equity
- Theta, Gamma, Vega all 0 (no options) — expected
- What-If Portfolio section present
- **MA integration:** limit thresholds wired correctly

---

### RISK

#### `risk` — ⚠️ PARTIAL
- VaR 95%: `—` (null) — **not computed**
- Macro regime: null
- `risk_dashboard: None` in data
- trades_today: 1, halted: False — these work
- **Root cause:** `compute_risk_dashboard()` not called with real PortfolioPosition objects
- **MA APIs not wired:** `compute_risk_dashboard()`, scenario stress tests

#### `health` — ⚠️ PARTIAL
- Reports "1 checked, 0 healthy, 0 need action, All positions healthy"
- BAC equity: status shown as healthy
- **Gap:** BAC is equity_long — health check for equity uses adjustment logic meant for options. Should show N/A for non-option positions instead of silently passing.
- **MA APIs not wired:** `ma.adjustment.recommend_action()` — no adjustment shown for any position

#### `overnight` — ❌ NOT WIRED
- Returns "No open positions or no overnight risk detected" despite 1 open BAC position
- BAC equity overnight gap risk not assessed
- **MA APIs not wired:** `assess_overnight_risk()` — not called for equity positions

#### `syshealth` — ❌ BROKEN
- Status: DEGRADED
- Error: `[mark_to_market] Zero quotes returned for 1 symbols — all trades UNMARKABLE`
- **Root cause:** BAC mark-to-market failing — broker quote fetch returning zero quotes
- This means all P&L, current_price, Greeks on open positions are stale

---

### TRADING

#### `scan` — ⚠️ PARTIAL (slow, 2+ min)
- Scan **does complete** but takes >2 minutes — HTTP request times out before response returns
- Background run confirmed: Scout populates 37 regime, 39 technicals, 39 opportunities, 39 levels
- Phase 1 screen: 12 candidates; Phase 2 rank: 40 ranked from 8 candidates; Phase 3: 10 equity picks
- **Critical gap:** `Bandits: R1 → earnings, diagonal, leap` — **WRONG for R1**
  - R1 (Low-Vol Mean Reverting) should select: iron_condor, straddle, iron_butterfly
  - Thompson Sampling priors not seeded from MA's `REGIME_STRATEGY_ALIGNMENT` matrix
  - This is why 0/50 proposals are approved — wrong strategies being attempted for the regime
- **Fix needed:** (1) async scan with polling, (2) fix bandit strategy priors for each regime

#### `propose` — ❌ BROKEN (0/50 approved)
- Returns: 0 proposed, 50 rejected (confirmed by background scan run)
- Rejection reasons: "No trade_spec / no legs", "NO_GO verdict", "Score 0.34 < 0.35"
- **Root cause 1:** Bandits select wrong strategies for R1 → assessors return NO_GO for earnings/diagonal/leap in R1
- **Root cause 2:** `No trade_spec / no legs` for NIFTY trend_continuation — assessor ran but produced no legs
- Even with correct bandit selections, some assessors not returning TradeSpec (failing silently)

#### `deploy` — ❌ BROKEN (no proposals to deploy)
- "No proposals to deploy" — correct behavior, but upstream propose never approves any trades
- **MSFT Iron Condor:** Could NOT be booked — scan selects wrong strategies, all proposals rejected
- `POST /api/v2/ranking` directly confirms MSFT IC score=0.739 "go" verdict — the opportunity exists
- **Fix needed:** Fix bandit priors first, then scan→propose→deploy will flow correctly

#### `mark` — ✅ WIRED (structure correct, data broken)
- Table structure correct with columns: Underlying, Strategy, Entry, Current, P&L, Health, Legs
- **BUT:** All rows empty — mark failing due to syshealth error (zero quotes from broker)
- **MA integration:** health column wired

#### `exits` — ✅ WIRED
- "All 0 open trades within limits" — correct (BAC equity has no exit rules like options DTE/profit target)
- **Gap:** equity_long positions have no exit conditions monitored — no stop loss, profit target checks

#### `close` — NOT TESTED (no triggered exits)

---

### ANALYTICS

#### `perf` — ✅ WIRED
- Shows desks: desk_0dte ($10K), desk_medium ($15K), etc.
- "No closed trades yet" — expected on fresh system
- Desk structure correct

#### `explain` — NOT TESTED (need trade ID)

#### `learn` — ✅ WIRED
- ML gate thresholds visible: pop_min=0.5, score_min=0.6, ic_iv_rank_min=15.0
- Thompson Sampling rankings per regime present (R1-R4)
- POP calibration factors present: R1=0.89
- **MA integration:** Regime-stratified bandit — R1/R2/R3/R4 strategy preferences wired
- **Gap:** Rankings look wrong for income-first trading philosophy:
  - R1 top: mean_reversion, leap, earnings (should be iron_condor, straddle)
  - R2 top: ratio_spread, calendar (ratio_spread in R2 is risky — naked exposure)
  - R4 top: diagonal, earnings (both inappropriate for R4 — should be long_option/defined_risk only)
  - **These are random Thompson Sampling priors, not MA's regime-strategy alignment matrix**

#### `shadow` — ✅ WIRED
- 0 shadow trades — expected on fresh system
- Structure correct: would_have_won, would_have_lost, gate_effectiveness keys present

---

### INTELLIGENCE

#### `plan` — ❌ BROKEN
- Request timed out / returned empty response
- **MA APIs not wired:** `ma.plan.generate()` — daily trading plan not exposed

#### `research` — ✅ WIRED
- Full 22-asset macro research report
- STAGFLATION regime, 60% confidence
- India section: VIX 21.6, FII outflow, NIFTY-SPY corr 0.12
- **Gap:** Report dated 2026-03-16 (yesterday) — stale cache being served

#### `macro` — ⚠️ PARTIAL
- Returns "Overall risk: ?" — risk level unknown
- **MA APIs not wired:** `compute_macro_dashboard()` — bond_market, credit_spreads, dollar_strength, inflation_expectations all null
- OHLCV for TNX, TLT, HYG, UUP, TIP not being fetched and passed in

#### `crossmarket` — ✅ WIRED
- Real data: correlation 0.15, US regime R2, India R4, predicted gap +0.09%
- **MA integration:** `analyze_cross_market()` fully wired

#### `board` — ✅ WIRED
- Independent Vidura review: 15 blind spots listed (tickers in MA universe with no position)
- **MA integration:** universe list wired, blind spot detection working

---

### STOCKS

#### `stock` (MSFT) — ⚠️ PARTIAL
- Rating: BUY, Score: 71/100
- Strategy scores present: growth 90, dividend 85, quality_momentum 75
- **BROKEN:** `Error: unsupported format string passed to NoneType.__format__` — a field is None when string formatting is attempted. Likely `entry_price` or similar numeric field is None.
- **MA integration:** fundamentals scoring wired, but rendering broken

#### `valuation` (MSFT) — ❌ BROKEN
- `Error: DataService.get_ohlcv() got an unexpected keyword argument 'period'`
- **Root cause:** eTrading calling `data_service.get_ohlcv(ticker, period='1y')` — MA's `get_ohlcv()` doesn't accept `period` kwarg. Must use `days=365` instead.
- All valuation zone assessments broken

#### `strategies` (MSFT) — ❌ NOT WIRED
- Returns usage string: "Usage: strategies <ticker>"
- Tool definition says parameter name is `id` but implementation expects positional arg
- **MCP parameter name mismatch** — `id` vs positional CLI arg

#### `stock-screen` — ❌ BROKEN
- `Error: 'EquityScreenResult' object has no attribute 'total_passed'`
- MA model mismatch — eTrading expecting old field name `total_passed`, MA now uses different attribute

#### `allocate` — ⚠️ PARTIAL
- Allocation percentages shown: Equity 45%, Gold 30%, Debt 15%, Cash 10%
- **BROKEN:** `Error: 'AssetAllocation' object has no attribute 'equity_sub_split'`
- MA model changed — `equity_sub_split` field removed or renamed

#### `deploy-plan` — ❌ BROKEN
- `Error: 'MonthlyAllocation' object has no attribute 'equity'`
- MA model changed — `MonthlyAllocation` field names changed, eTrading not updated

#### `rebalance` — ✅ WIRED
- Shows real drift: EQUITY 3.9% vs 60% target (-56.1%)
- CASH 96.1% vs 10% target (+86.1%)
- Rebalance needed: YES
- **Note:** Portfolio shows $263K total — sum across all portfolios including paper

#### `universe` — ✅ WIRED
- All 10 presets listed with correct ticker counts
- MA registry correctly integrated

---

### ANALYSIS

#### `levels` (MSFT) — ❌ NOT WIRED (parameter mismatch)
- Returns usage string — same MCP `id` vs positional CLI arg mismatch as `strategies`

#### `hedge` (MSFT) — ❌ NOT WIRED (parameter mismatch)
- Returns usage string — same mismatch

#### `strategies` (MSFT) — ❌ NOT WIRED (see above)

---

### ADMIN

#### `status` — ✅ WIRED
- Shows broker, state, cycle, VIX (null), open trades
- **Gap:** VIX always null — not fetched

#### `ml` — ✅ WIRED (see Analytics section)

#### `report` — ✅ WIRED
- Desk P&L structure correct
- **Gap:** Capital shows $1,545,000 total — paper portfolios inflating the total

#### `env-check` — ✅ WIRED (returns success, empty text — env vars hidden correctly)

---

## Capabilities Not Wired — Priority List

### 🔴 P0 — Blocking (system cannot function without these)

| # | Capability | MA API | Impact |
|---|-----------|--------|--------|
| 1 | **Daily Trading Plan** | `ma.plan.generate()` | `plan` tool times out — no daily trade plan |
| 2 | **Scan too slow + wrong bandit priors** | `ma.ranking.rank()` + `REGIME_STRATEGY_ALIGNMENT` | Scan takes 2+ min (async needed); R1 bandits select earnings/diagonal/leap instead of iron_condor/straddle — 0/50 proposals ever approved |
| 3 | **TradeSpec missing from proposals** | Option play assessors | 50 rejections include "No trade_spec / no legs" — assessors not building specs |
| 4 | **Mark-to-market broken** | `ma.quotes.get_leg_quotes()` | Zero quotes from broker — all positions unmarkable, P&L stale |
| 5 | **VaR/Scenario not wired** | `compute_risk_dashboard()` / `run_stress_suite()` | VaR always null, no scenario stress results |

### 🟠 P1 — High (risk management incomplete)

| # | Capability | MA API | Impact |
|---|-----------|--------|--------|
| 6 | **Adjustment recommendations** | `ma.adjustment.recommend_action()` | health tool shows no adjustments for any position |
| 7 | **Overnight risk for equities** | `assess_overnight_risk()` | overnight tool ignores equity positions |
| 8 | **Macro dashboard indicators** | `compute_macro_dashboard()` | bond_market, credit_spreads, dollar all null |
| 9 | **Exit conditions for equities** | `monitor_exit_conditions()` | equity_long has no exit monitoring |

### 🟡 P2 — Medium (data quality / model mismatches)

| # | Capability | Fix |
|---|-----------|-----|
| 10 | **`valuation` broken** | `get_ohlcv(ticker, period='1y')` → use `days=365` |
| 11 | **`deploy-plan` broken** | `MonthlyAllocation.equity` field renamed — update eTrading |
| 12 | **`stock-screen` broken** | `EquityScreenResult.total_passed` renamed — update eTrading |
| 13 | **`allocate` broken** | `AssetAllocation.equity_sub_split` renamed — update eTrading |
| 14 | **`stock` render error** | None field being string-formatted — add null guard |
| 15 | **ML strategy rankings wrong** | Thompson Sampling priors not seeded from MA's `REGIME_STRATEGY_ALIGNMENT` matrix — R4 recommending diagonal/earnings (wrong) |

### 🟢 P3 — Lower (completeness)

| # | Capability | Fix |
|---|-----------|-----|
| 16 | **`strategies`, `levels`, `hedge` parameter mismatch** | MCP tool definition uses `id` but CLI handler expects positional arg — fix arg mapping |
| 17 | **`connect` not in MCP tools** | Add `connect` tool to TOOL_DEFINITIONS so broker can be connected via webapp |
| 18 | **VIX always null** | Fetch VIX OHLCV on startup cycle |
| 19 | **Research report stale** | Cache TTL too long — report from 2026-03-16 served on 2026-03-17 |
| 20 | **Chat keyword router missing commands** | `rank`, `plan`, `context`, `adjust`, `regime`, `connect` not in keyword map → all fall back to `status` |

---

## MSFT Iron Condor — Booking Status

**Could not book** — scan timed out before generating proposals. Underlying issue:
- `scan` makes MA ranking calls across the full watchlist universe which exceeds HTTP timeout
- Even when scan completes (from prior run), 0 proposals approved due to TradeSpec missing from assessors

**To book manually:** Need a direct REST endpoint `POST /api/v2/positions` with whatif trade payload, or fix scan timeout first.

---

## What Is Working Well

| Capability | Status |
|-----------|--------|
| Broker connection (tastytrade data mode) | ✅ |
| Portfolio/position sync from broker | ✅ |
| Cross-market analysis (US→India) | ✅ |
| Full macro research report (22 assets) | ✅ |
| MA universe/registry integration | ✅ |
| Board/Vidura blind spot detection | ✅ |
| ML gate thresholds + Thompson Sampling | ✅ |
| Greeks display vs limits | ✅ |
| Capital utilization view | ✅ |
| Shadow portfolio framework | ✅ |
| Rebalance drift detection | ✅ |
