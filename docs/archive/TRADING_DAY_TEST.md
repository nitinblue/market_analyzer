# TRADING DAY FUNCTIONAL TEST

**Date:** 2026-03-23 (Sunday — after-hours, using cached OHLCV from Friday 2026-03-20)
**Mode:** Tested BOTH yfinance-only AND broker-connected (TastyTrade paper)
**Test command:** `python scripts/research_report.py --market us` / `--market india`
**Unit tests:** 466 passed, 1 pre-existing failure (broker test), 2 skipped

---

## PIPELINE WALKTHROUGH

### Step 1: Crash Sentinel

| Check | Result |
|-------|--------|
| Signal | GREEN |
| Phase | normal |
| SPY | R2 (100% conf, 0% R4 prob) |
| QQQ | R3 (100% conf) |
| IWM | R3 (100% conf) |
| GLD | R3 (100% conf) |
| TLT | R2 (100% conf) |

**Trader verdict:** GREEN is correct. No R4 in US benchmarks. SPY/TLT are R2 (high-vol mean-reverting), tech and gold are R3 (trending). This matches the current macro picture — broad correction, not a crash.

**Status: PASS**

---

### Step 2: Market Context

| Check | Result |
|-------|--------|
| Environment | cautious |
| Trading allowed | Yes |
| Position size factor | 0.75 (reduced) |
| Black swan | elevated (0.28) |
| Macro events next 7d | 1 (PCE Mar 27) |

**Trader verdict:** Correct. Cautious with 75% sizing makes sense — elevated vol, PCE this week. Would be wrong to go full size.

**Status: PASS**

---

### Step 3: Macro Calendar

| Event | Date | Days | Impact |
|-------|------|------|--------|
| PCE Price Index | Mar 27 | 4d | MEDIUM |
| Non-Farm Payrolls | Apr 3 | 11d | HIGH |
| RBI MPC | Apr 8 | 16d | HIGH |
| CPI Report | Apr 14 | 22d | HIGH |
| FOMC | Apr 29 | 37d | HIGH |

**Trader verdict:** Calendar correctly shows both US and India events. RBI MPC is now wired (new today). PCE in 4 days — should factor into DTE selection (avoid 4-DTE positions).

**Status: PASS**

---

### Step 4: US Regime Scan

| Ticker | Regime | RSI | ATR% | Price | Assessment |
|--------|--------|-----|------|-------|------------|
| SPY | R2 | 30.4 | 1.60 | 648.57 | Approaching oversold in high-vol MR. Income candidate with wider wings. |
| QQQ | R3 | 35.2 | 1.85 | 582.06 | Trending down. Not for income. |
| IWM | R3 | 33.6 | 2.56 | 242.22 | Trending. High ATR. Avoid income. |
| GLD | R3 | 29.8 | 2.93 | 413.38 | Trending with very high ATR. Avoid. |
| TLT | R2 | 35.6 | 0.94 | 85.83 | R2 with low ATR. Income candidate. |
| **AAPL** | **R1** | 34.9 | 2.05 | 247.99 | **Calm regime. Best income candidate.** |
| MSFT | R3 | 32.2 | 2.02 | 381.85 | Trending. Avoid income. |
| NVDA | R3 | 38.0 | 3.10 | 172.93 | Trending, high vol. Avoid. |
| **AMZN** | **R1** | 40.6 | 2.61 | 205.37 | **Calm. Income candidate.** |
| META | R3 | 32.7 | 3.02 | 593.66 | Trending. Avoid. |

**Trader verdict:** R1 on AAPL and AMZN while the broader market is R2-R3 — these are decoupled, exactly the kind of selectivity income_desk should show. SPY and TLT as R2 income candidates makes sense. Avoiding income on R3 tickers is correct.

**Status: PASS**

---

### Step 5: India Regime Scan

| Ticker | Regime | RSI | ATR% | Price | Assessment |
|--------|--------|-----|------|-------|------------|
| **NIFTY** | **R4** | 26.9 | 2.09 | 22,513 | Explosive. No income. Cash only. |
| **BANKNIFTY** | **R4** | 23.5 | 2.68 | 51,438 | Explosive. Deeply oversold. Cash only. |
| TCS | R1 | 29.0 | 2.53 | 2,398 | Calm + oversold. First deploy candidate. |
| HDFCBANK | R3 | 24.0 | 3.20 | 781 | Trending down. Deeply oversold but don't catch knife. |
| RELIANCE | R2 | 51.3 | 2.71 | 1,414 | High-vol MR. Not oversold yet. Wait. |

**Trader verdict:** NIFTY R4 at RSI 26.9 is a clear "do not deploy" signal for India indices. TCS R1 decoupling from NIFTY R4 is the classic IT-sector-leads-recovery pattern. System correctly identifies this.

**Status: PASS**

---

### Step 6: Ranking (6 US tickers)

| Rank | Ticker | Strategy | Score | Verdict | Spec |
|------|--------|----------|-------|---------|------|
| 1 | IWM | momentum | 0.615 | go | DS |
| 2 | IWM | diagonal | 0.590 | go | DIAG |
| 3 | AAPL | zero_dte | 0.563 | go | IC |
| 4 | QQQ | diagonal | 0.552 | go | DIAG |
| 5 | IWM | mean_reversion | 0.527 | go | DS |
| 6 | SPY | mean_reversion | 0.521 | go | CS |
| 7 | AAPL | mean_reversion | 0.511 | go | CS |
| 8 | SPY | calendar | 0.497 | go | DCAL |

**Assessed:** 66 strategies across 6 tickers. **27 actionable** (41% pass rate).

**Trader concern:** IWM momentum as #1 is questionable — IWM is R3 (trending down). A momentum play on a downtrending small-cap ETF is aggressive. AAPL IC (R1) at #3 is the safer income play. The ranking seems to prioritize momentum/directional over income-first approach.

**Issue: RANKING_INCOME_BIAS** — The income-first bias may not be strong enough. R1 tickers (AAPL, AMZN) should rank higher than R3 directional plays.

**Status: CONCERN**

---

### Step 7: Daily Trading Plan

| Check | Result |
|-------|--------|
| Verdict | TRADE_LIGHT |
| Reason | Black swan ELEVATED (0.28) |
| Total trades | 10 |

| Ticker | Strategy | Score | Horizon | Spec |
|--------|----------|-------|---------|------|
| AAPL | zero_dte | 0.545 | 0dte | Yes |
| SPY | mean_reversion | 0.521 | monthly | Yes |
| AAPL | mean_reversion | 0.511 | monthly | Yes |
| SPY | calendar | 0.497 | monthly | Yes |
| TLT | calendar | 0.497 | monthly | Yes |
| TLT | zero_dte | 0.478 | 0dte | Yes |
| TLT | mean_reversion | 0.476 | monthly | Yes |
| AAPL | leap | 0.466 | leap | Yes |

**Warning:** No broker connected — all entry prices unavailable.

**Trader verdict:** TRADE_LIGHT is correct (elevated black swan). Plan correctly has TradeSpecs for all trades. The IWM directional plays correctly dropped off the plan (plan is more conservative than raw ranking). AAPL and SPY income plays are front and center.

**Status: PASS (with warning about no broker pricing)**

---

### Step 8: Pre-Trade Validation (IWM momentum DS, $1.50 credit)

| Check | Severity | Message |
|-------|----------|---------|
| commission_drag | PASS | Credit $150 covers $2.60 fees (1.7% drag) |
| fill_quality | PASS | Spread 0.8% — survives natural fill |
| margin_efficiency | WARN | Cannot compute ROC — debit spread not supported by yield calc |
| pop_gate | **FAIL** | POP 45.5% (< 65% threshold) |
| ev_positive | WARN | EV +$0 per contract |
| entry_quality | **FAIL** | Income entry NOT CONFIRMED (score 40%) |
| exit_discipline | PASS | TP 50% | SL 0.5x | exit <=14 DTE |
| strike_proximity | WARN | No levels data (no broker) |
| earnings_blackout | PASS | No earnings conflict |
| iv_rank_quality | WARN | IV rank unavailable (no broker) |

**Result: NOT READY (4/10 passed, 4 warnings, 2 failures)**

**Trader verdict:** Validation correctly rejects this trade. POP 45.5% on a momentum debit spread in R3 is not an income trade — the validator correctly gates it. This is the safety net working. The entry_quality check also correctly flags R3 as not income-friendly.

**Status: PASS (validator correctly rejected a bad trade)**

---

### Step 9: Adversarial Stress (same IWM trade)

| Check | Severity | Message |
|-------|----------|---------|
| gamma_stress | WARN | No wing width (debit spread) |
| vega_shock | PASS | Long-vega benefits from IV spike |
| breakeven_spread | PASS | Edge survives up to 5.0% spread |

**Result: READY TO TRADE (stress perspective only)**

**Status: PASS**

---

## BUGS FOUND & FIXED THIS SESSION

### BUG-1: KeyError on unimplemented StrategyTypes (CRITICAL)

**File:** `income_desk/service/ranking.py:273`
**Symptom:** `KeyError: <StrategyType.EQUITY_BREAKOUT: 'equity_breakout'>` when `TradingPlanService.generate()` passes all StrategyType values to `rank()`.
**Root cause:** 4 new StrategyTypes (`equity_breakout`, `equity_momentum`, `equity_mean_reversion`, `futures_directional`) were added to the enum but NOT to `_ASSESS_METHODS`. The `rank()` method used `_ASSESS_METHODS[strategy]` (hard crash) instead of `.get()` (skip gracefully).
**Fix:** Changed `_ASSESS_METHODS[strategy]` to `_ASSESS_METHODS.get(strategy)` with `if method_name is None: continue`.
**Impact:** Daily trading plan was completely broken. Any `plan` command would crash.

### BUG-2: _report_footer w() helper missing default arg (CRITICAL)

**File:** `scripts/research_report.py:115`
**Symptom:** `TypeError: list.append() takes exactly one argument (0 given)` when generating India report.
**Root cause:** `_report_footer` used `w = lines.append` which doesn't support `w()` (empty line). The per-report functions used `def w(line=""): lines.append(line)`.
**Fix:** Changed `_report_footer` to use the same `def w(line="")` pattern.
**Impact:** India report generation completely broken.

### BUG-3: TATAMOTORS.NS delisted on yfinance

**File:** `scripts/research_report.py:35`
**Symptom:** `404 Not Found` when scanning India universe.
**Fix:** Replaced TATAMOTORS with MARUTI in `INDIA_UNIVERSE`.

### BUG-4: Null values crashing web page

**File:** `scripts/research_report.py:97`
**Symptom:** Error entries from `scan_market()` had only `ticker` and `error` keys — missing `regime`, `rsi`, etc. Web renderer crashes on null access.
**Fix:** Error entries now include all keys with safe defaults.

### BUG-5: `ma` not passed to `generate_report()`

**File:** `scripts/research_report.py:111`
**Symptom:** Entire macro indicators section silently failed (NameError swallowed by try/except).
**Fix:** Added `ma` as first parameter, updated call site.

### BUG-6: INDIAVIX not in yfinance aliases

**File:** `income_desk/data/providers/yfinance.py`
**Symptom:** India VIX regime detection silently fails.
**Fix:** Added `"INDIAVIX": "^INDIAVIX"` to `_YFINANCE_ALIASES`.

### BUG-7: India bank stocks missing from rate_risk

**File:** `income_desk/features/rate_risk.py`
**Symptom:** India rate risk section shows empty table.
**Fix:** Added HDFCBANK, ICICIBANK, SBIN, AXISBANK, KOTAKBANK to sensitivity table.

---

## STILL NOT WORKING / KNOWN GAPS

### GAP-1: Paper mode has no IV rank (TastyTrade cert API limitation)

`api.cert.tastyworks.com/market-metrics` returns HTTP 404. IV rank/percentile only available on the **production** API (`api.tastyworks.com`).

**Live mode confirmed working (2026-03-23 10:30 ET):**
- SPY: IVR=34.4%, IVP=76.6%
- QQQ: IVR=33.4%
- GLD: IVR=77.5% (extremely elevated — confirms research report signal)
- AAPL: IVR=17.3%
- TLT: IVR=31.2%

**Workaround:** Use `--broker` with live credentials (not `--paper`) for metrics. Paper mode still works for quotes and account balance.

### GAP-2: India VIX data unavailable from yfinance

`^INDIAVIX` returns insufficient data from yfinance. The alias was added but yfinance simply doesn't serve this data reliably.
- **Workaround:** Connect Dhan/Zerodha broker for India VIX
- **Fallback:** Report shows "India VIX: Unavailable (insufficient data)"

### GAP-3: Ranking income bias may be too weak

R3 momentum plays outranking R1 income plays suggests the `income_bias_boost` may need tuning. AAPL (R1, RSI 34.9) should rank above IWM (R3, RSI 33.6) for an income-first trader.
- **Impact:** Medium — the daily plan correctly filters these out
- **Fix:** Increase `income_bias_boost` or add regime penalty for R3/R4 in income scoring

### GAP-4: Margin efficiency can't compute ROC for debit spreads

The `check_margin_efficiency` validator depends on `compute_income_yield()` which only works for credit structures. Debit spreads get a WARN.
- **Impact:** Low — debit spreads aren't income trades, so the WARN is correct behavior
- **Decision:** Accept as-is — WARN is the right severity for non-income structures

### GAP-5: Strike proximity requires broker (levels data)

`strike_proximity` check always warns without broker-provided levels data.
- **Impact:** Medium — can't validate strike placement without live S/R levels
- **Workaround:** yfinance OHLCV gives historical S/R, but not as precise

### GAP-6: Pre-existing broker test failure

`tests/test_cli_broker.py::test_returns_none_tuple_on_connection_failure` — test mocks TastyTrade to fail, but `connect_broker()` falls through to Alpaca (which succeeds from env creds). Not related to any session changes.
- **Fix needed:** Mock ALL broker backends in the test, not just TastyTrade

### GAP-7: Rate risk labels are raw enums

India rate risk table shows `reduce_exposure` instead of human-readable "Reduce income positions ahead of RBI MPC". The `_RATE_SENSITIVITY` table stores tuples, not the full recommendation strings.
- **Impact:** Low — affects report readability only

---

## TEST SUITE STATUS

| Suite | Count | Status |
|-------|-------|--------|
| Unit tests | 466 | PASS |
| Functional tests | 60 | PASS |
| Macro tests | 20 | PASS (including new RBI MPC test) |
| Pre-existing failures | 1 | broker test fallthrough (GAP-6) |

---

## BROKER-CONNECTED TEST RESULTS

Tested with TastyTrade paper account (5WY28619) on Sunday after-hours.

### What works with broker

| Step | Result |
|------|--------|
| Broker connect | TastyTrade paper OK |
| Crash Sentinel | GREEN (same as yfinance) |
| Ranking | AAPL IC #1, SPY CS #2 (income-first — better than yfinance ranking) |
| Trading Plan | 10 trades, all with **real entry prices** ($1.04, $0.88, $1.12, etc.) |
| Validation | Runs with live data, commission drag correct |
| Account balance | Accessible (NLV, BP, cash) |

### Issues found with broker (weekend)

| Issue | Severity | Detail |
|-------|----------|--------|
| IV rank None for all tickers | Expected | Markets closed (Sunday). DXLink doesn't stream metrics after hours. |
| TLT quote fetch failed | Expected | DXLink streaming intermittent on weekends. |
| Unicode crash on Windows | BUG-8 | `\u2264` (<=) in exit_discipline message crashes cp1252 console. Not a data issue. |
| POP 41.9% on AAPL 0DTE IC | Correct | Weekend, 0 DTE remaining. Validator correctly rejects. |

### Broker vs No-Broker comparison

| Feature | No Broker | With Broker |
|---------|-----------|-------------|
| IV rank | None everywhere | None (weekend) / Live (market hours) |
| Entry pricing | None | Real DXLink mid prices |
| Ranking quality | R3 momentum ranked #1 | R1 income ranked #1 (better) |
| Account filtering | Not possible | Available (BP-aware) |
| Validation accuracy | 4 warnings for missing data | Fewer warnings when data available |

### Full Service Test (15 services, broker connected)

| Service | Status | Detail |
|---------|--------|--------|
| technicals | PASS | price=648.57 RSI=30.4 ATR=1.60 |
| levels | PASS | support=0 resistance=8 |
| screening | PASS | 3 candidates from SPY/AAPL/TLT |
| entry | PASS | confirm() works (wrong enum in first test) |
| strategy | PASS | StrategyParameters returned |
| exit | PASS | ExitPlan returned |
| adjustment | PASS | analyze() works |
| us_report | PASS | 137 lines generated |
| india_report | PASS | 114 lines generated |
| vol_surface | PASS | surface() works |
| account | PASS | NLV=$1,000,000 (paper) |
| fundamentals | PASS | get() works |
| black_swan | PASS | level=elevated score=0.26 |
| quotes | PASS | 2549 options, source=yfinance |
| watchlist | PASS | broker watchlists accessible |

**Result: 15/15 services operational with broker.**

**Conclusion:** Broker connection is essential for production use. Weekend testing confirms pipeline works end-to-end but IV rank data requires market hours.

---

## SESSION CHANGES SUMMARY

| Change | Files | Tests |
|--------|-------|-------|
| Null safety in scan_market | scripts/research_report.py | Syntax verified |
| RBI MPC in macro calendar | models/macro.py, macro/calendar.py | 20 macro tests pass |
| Report split India/US | scripts/research_report.py | India report generated |
| India macro data gaps | data/providers/yfinance.py, features/rate_risk.py | 61 tests pass |
| --market required | scripts/research_report.py | Syntax verified |
| Ranking KeyError fix | service/ranking.py | 466 tests pass |
| Footer w() bug fix | scripts/research_report.py | Report generates |
| TATAMOTORS -> MARUTI | scripts/research_report.py | India scan works |
| Memory cleanup | 12 memory files | All refs updated |
