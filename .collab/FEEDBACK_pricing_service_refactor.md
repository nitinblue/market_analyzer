# FEEDBACK: PricingService Refactor — Breaking Change for eTrading

**From:** income-desk
**To:** eTrading
**Date:** 2026-03-30

## Summary

Refactoring the ranking pipeline to fix a month-long pricing bug. `rank_opportunities` workflow output will have new fields and changed behavior. eTrading must update its consumer.

## What Changed

### 1. New field: `credit_source` on TradeProposal
- Values: `"chain"` (real broker data), `"estimated"` (fallback), `"blocked"` (could not price)
- **eTrading action:** Only execute trades with `credit_source == "chain"`. Display warning for `"estimated"`. Never execute `"blocked"`.

### 2. New field: `current_price` on TradeProposal
- Underlying price at time of ranking (from broker)
- **eTrading action:** Use this for margin calculations instead of fetching price separately.

### 3. New field: `expiry` on TradeProposal
- ISO date string of option expiration (e.g., "2026-03-30")
- **eTrading action:** Use for expiry-day logic, DTE calculations.

### 4. New field: `regime_id` and `atr_pct` on TradeProposal
- Regime and ATR at time of ranking
- **eTrading action:** Use for position monitoring context.

### 5. entry_credit now comes from real chain data (not estimated)
- Previously: `entry_credit` could be `wing_width * 0.28` (fabricated)
- Now: `entry_credit` is computed from actual broker chain bid/ask mids
- Trades where chain data unavailable are BLOCKED (not shown with fake credit)
- **eTrading action:** Trust `entry_credit` when `credit_source == "chain"`. No need for independent repricing.

### 6. POP now uses real DTE from leg expiration dates
- Previously: `target_dte` or fallback 30 days (wrong for 0DTE)
- Now: actual calendar days from leg expiration to today
- **eTrading action:** POP values are more accurate. No change needed.

### 7. Lot size from MarketRegistry (not hardcoded 100)
- Previously: `lot_size = ts.lot_size or 100` (US default)
- Now: looked up from MarketRegistry per ticker
- **eTrading action:** `lot_size` on TradeProposal is now reliable for India.

## New Architecture: RepricedTrade

The ranking pipeline now uses a `RepricedTrade` (frozen Pydantic model) as intermediate:

```python
from income_desk.workflow.pricing_service import RepricedTrade, LegDetail

# RepricedTrade has:
# - entry_credit (float) — computed once, never overwritten
# - credit_source (str) — "chain", "estimated", "blocked"
# - leg_details (list[LegDetail]) — per-leg bid/ask/mid/iv/delta
# - liquidity_ok (bool) — OI and spread checks passed
# - block_reason (str | None) — why trade was blocked
```

eTrading can also use `RepricedTrade` directly if it needs to reprice independently:

```python
from income_desk.workflow.pricing_service import reprice_trade

result = reprice_trade(
    trade_spec=ts,
    chain=md.get_option_chain(ticker),
    ticker=ticker,
    current_price=price,
    atr_pct=2.5,
    regime_id=1,
)
# result.entry_credit is the single source of truth
```

## Migration Checklist for eTrading

| # | Check | Action |
|---|-------|--------|
| 1 | Read `credit_source` from TradeProposal | Filter on "chain" for execution |
| 2 | Read `current_price` from TradeProposal | Use for margin, stop loss calculations |
| 3 | Read `expiry` from TradeProposal | Use for expiry-day handling |
| 4 | Stop independent repricing | Trust entry_credit when credit_source="chain" |
| 5 | Update lot_size handling | TradeProposal.lot_size is now market-correct |
| 6 | Handle blocked trades | Trades with missing chain data no longer appear in trades list — they're in blocked list with reason |

## Go-Live Status

India: 59% (was 20% yesterday). Pricing pipeline refactor in progress. Expected 75%+ after completion.
US: UNTESTED (needs market hours with TastyTrade tomorrow).
