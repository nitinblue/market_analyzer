# MA Gap Tracker

**Goal:** MA enables a fully systematic trading system that makes money.

**Boundary:** MA is stateless. eTrading passes context in, MA computes and returns.

**Stats:** 1167 tests passing. 95 in test_systematic.py.

---

## Master Status

| # | Category | Gap | Status | Detail |
|---|----------|-----|--------|--------|
| G01 | Infrastructure | Deterministic adjustment decisions | **DONE** | `recommend_action()` → single action. Wired into health check + CLI. |
| G02 | Infrastructure | Execution quality validation | **DONE** | `validate_execution_quality()` checks spread/OI/volume. CLI `do_quality`. |
| G03 | Infrastructure | Entry time windows on TradeSpec | **DONE** | Assessors set windows: 0DTE=(09:45,14:00), income=(10:00,15:00), earnings=(10:00,14:30). |
| G04 | Infrastructure | Time-of-day urgency in exit monitoring | **DONE** | `time_of_day` param. 0DTE force-close after 15:00, tested escalation after 15:30. |
| G05 | Infrastructure | Overnight risk assessment | **DONE** | `assess_overnight_risk()`. Auto-invoked in `check_trade_health()` after 15:00. CLI `do_overnight`. |
| G06 | Infrastructure | Auto-select screening | **DONE** | `min_score=0.6` + `top_n` on `scan()`. `filtered_count` in output. |
| G07 | Intelligence | Performance feedback loop | **DONE** | `TradeOutcome` + `compute_performance_report()` + `calibrate_weights()`. CLI `do_performance`. |
| G08 | Intelligence | Debug/commentary mode | **DONE** | `debug=True` on `detect()`, `snapshot()`, `assess()`, `rank()`. Threads to assessors via ranking. CLI `--debug`. |
| G09 | Intelligence | Data gap self-identification | **DONE** | `data_gaps` populated by 8 assessors + regime service. Propagated through ranking. |
| SQ1 | Signal Quality | IV rank integration in assessors | **DONE** | `iv_rank` param on IC (<15 stop), IFly (<20), earnings (<25), LEAP (>70). Data gaps when None. |
| SQ2 | Signal Quality | HMM model staleness & validation | **DONE** | `model_fit_date`, `model_age_days`, `regime_stability` on RegimeResult. Data gaps for stale/uncertain/churn. |
| SQ3 | Signal Quality | POP calibration from outcomes + IV | **DONE** | `iv_rank` on `estimate_pop()`. `calibrate_pop_factors()` from real win rates. `pop_accuracy` on report. |
| SQ4 | Signal Quality | Mean reversion assessor overhaul | **OPEN** | Volatility-adjusted RSI thresholds, divergence check, bars-at-extreme filter, support target, volume on bounce. |
| SQ5 | Signal Quality | Breakout volume confirmation | **OPEN** | Breakout bar volume > 1.5x avg, failed breakout history, support distance for stop. |
| SQ6 | Signal Quality | Earnings implied move | **OPEN** | Compute implied move from straddle price (broker), compare vs historical. IV crush from term structure. |
| SQ7 | Signal Quality | Screening liquidity & correlation | **OPEN** | Min volume 500K, correlation dedup >0.85, IV rank on income screen. |
| SQ8 | Signal Quality | Momentum pullback quality | **OPEN** | Fibonacci retracement, bars in pullback, trend maturity (wave count). |

---

## eTrading Integration Instructions

### SQ1: IV Rank — eTrading Must Pass It

```python
metrics = ma.quotes.get_metrics(ticker)
iv_rank = metrics.iv_rank if metrics else None
result = ma.opportunity.assess_iron_condor(ticker, iv_rank=iv_rank)
```

If no broker: `iv_rank=None` → assessors work but add `DataGap(field="iv_rank")`.

### SQ2: Regime Staleness — eTrading Should Check

```python
regime = ma.regime.detect(ticker)
# Check: regime.model_age_days, regime.regime_stability, regime.data_gaps
# If model_age_days > 60, consider calling ma.regime.fit(ticker) to retrain
```

### SQ3: POP with IV + Calibration

```python
# Per-trade: pass iv_rank for more accurate POP
pop = estimate_pop(spec, entry_price, regime_id, atr_pct, price, iv_rank=iv_rank)

# Weekly: calibrate regime factors from closed trades
new_factors = calibrate_pop_factors(outcomes, min_trades_per_regime=10)
report = compute_performance_report(outcomes)  # report.pop_accuracy per regime
```

---

## eTrading Gaps (Not MA's Responsibility)

| # | Category | Gap |
|---|----------|-----|
| E01-E04 | Risk | Position dedup, portfolio Greeks, concentration limits, margin tracking |
| E05-E08 | Execution | Order types, fill retry, scale-in, partial fills |
| E09-E10 | Orchestration | Regime polling schedule, exit monitoring polling |

---

## History

| Date | Work | Tests | Total |
|------|------|-------|-------|
| 2026-03-14 | G01-G05: Core systematic loop | +37 | 1109 |
| 2026-03-14 | G06-G09: Screening & intelligence | +24 | 1133 |
| 2026-03-14 | eTrading CRs (CR-3, CR-4, CR-5) | +13 | 1146 |
| 2026-03-14 | P1-P5: Wire pending (entry_window, data_gaps, debug, overnight, CLI) | +0 | 1146 |
| 2026-03-14 | SQ1-SQ3: IV integration, HMM staleness, POP calibration | +21 | 1167 |
