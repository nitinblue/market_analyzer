# FEEDBACK: India Market Live Trading Readiness

**Date:** 2026-03-26
**Direction:** ID → eT
**Status:** ACTIVE — fixes shipped, integration changes needed

## Summary

income_desk India pipeline tested against live Dhan data. Profitability score improved from **49% (CAUTION) → 80% (GO)** after fixing critical trade generation bugs.

## What Was Broken (Now Fixed in ID)

### 1. Dhan Data Not Used by Trader Pipeline
- `run_trader()` ignored the live MarketAnalyzer and created simulated data
- **Fixed:** `run_trader()` now accepts `ma=` parameter for pre-built analyzers
- **eT impact:** If eT calls `run_trader()`, pass the live MA via `ma=` parameter

### 2. Zero Income Trades for India Stocks
- `_should_use_equity()` forced ALL India stocks to equity_long/equity_short
- RELIANCE, TCS, INFY have monthly F&O options with decent liquidity
- **Fixed:** India stocks with `options_liquidity="medium"` or `"high"` now generate option-based strategies (iron condors, credit spreads)
- **eT impact:** None — transparent to callers

### 3. Vol Surface Not Using Dhan Chains
- `VolSurfaceService` only used yfinance (no India option chains)
- **Fixed:** `VolSurfaceService` now tries broker `market_data` first, falls back to yfinance
- **eT impact:** When passing a live broker MarketDataProvider, vol surface will automatically use it. No code change needed.

### 4. Dhan Rate Limiting
- Multiple assessors calling `get_option_chain` per ticker hit Dhan's 1-call-per-3-sec limit
- **Fixed:** Session-level cache + 3.5s throttle in `VolSurfaceService`
- **eT impact:** If eT caches option chains separately, coordinate to avoid double-fetching

### 5. Low POP Trades Leaking Through
- 20% POP equity trades were passing validation
- **Fixed:** 40% POP hard floor added in `run_trader()`
- **eT impact:** eT's own POP gate should enforce ≥55% for income trades

## Current Profitability Scores (2026-03-26)

| Section | Score |
|---------|-------|
| Dhan connectivity | 100% |
| Option chain quality | 100% (614 NIFTY, 866 BANKNIFTY strikes) |
| Regime detection | 60% (3/6 in R4 — correct, market is volatile) |
| Trade quality | 68% (7 income, 3 directional, 0 equity) |
| Validation gate | 60% (3/5 pass — 2 blocked on POP/EV) |
| Position sizing | 100% |
| **Overall** | **80% — GO** |

## Integration Notes for eT

### New API: `run_trader(ma=)`
```python
from income_desk.demo.trader import run_trader

# Pass pre-built MA with live broker
report = run_trader(market="India", capital=5_000_000, ma=live_ma)
```

### Daily Profitability Test Script
```bash
# eT can run this as a health check
python scripts/daily_profitability_test.py          # live Dhan
python scripts/daily_profitability_test.py --sim    # offline
```
Reports saved to `~/.income_desk/profitability_reports/YYYY-MM-DD.json`

### Remaining Gaps (ID-side, no eT action needed)
- Dhan stock option chains (RELIANCE/TCS/INFY) have zero bid/ask pre-market — vol surface uses IV column instead
- 2 of 5 validation checks fail on POP/EV for certain stocks — investigating
- HMM models are 6 days old — will refresh when market data accumulates

## Action Items for eT
1. **Use `ma=` parameter** when calling `run_trader()` with live broker
2. **Enforce POP ≥ 55%** in eT's own execution gate (E01-E10)
3. **Run `daily_profitability_test.py`** as pre-market health check
4. **Coordinate chain caching** if eT also fetches Dhan option chains
