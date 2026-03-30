# Refactoring Summary — 2026-03-30

## What Was Wrong

The ranking pipeline (`rank_opportunities.py`) was a 430-line monolith that computed `entry_credit` **6 times across 3 files**. Each layer could overwrite the previous:

```
Assessors → Chain Reprice → POP → Liquidity Filter (OVERWRITES!) → Sizing → Output
               credit=13       uses 13      credit=1.8                uses 1.8
```

POP was computed with credit=13 but the final output had credit=1.8. The trader would see inconsistent numbers.

## What We Built

### New: `PricingService` (`income_desk/workflow/pricing_service.py`)

Three components:

1. **`LegDetail`** (Pydantic model) — per-leg pricing: strike, bid, ask, mid, IV, delta, OI
2. **`RepricedTrade`** (frozen Pydantic model) — immutable repricing result. `entry_credit` set once, cannot be changed.
3. **`reprice_trade()`** — takes TradeSpec + broker chain → RepricedTrade. Single source of truth.
4. **`batch_reprice()`** — groups by ticker, fetches chain ONCE per ticker, reprices all structures.

### Rewritten: `rank_opportunities()` (430 → ~250 lines)

New flow:
```
Regimes → Assessors → batch_reprice() → POP → Size → Output
                         credit=13        uses 13  uses 13  shows 13
```

**Key principle:** `entry_credit` from `RepricedTrade` flows through untouched. No layer overwrites it.

### What Was Removed
- 6 separate `entry_credit =` assignments
- `liquidity_filter.py` calls (absorbed into PricingService)
- `time.sleep(3.5)` in ranking loop (rate limiting moved to batch_reprice, Dhan-only)
- `current_price = 100.0` fallback (blocks instead)
- `wing_width or 5.0` US default (market-specific from registry)
- `lot_size or 100` US default (MarketRegistry lookup)

### New Fields on `TradeProposal`
- `credit_source`: "chain" | "estimated" | "blocked" — tells trader if credit is real
- `current_price`: underlying at time of ranking
- `regime_id`, `atr_pct`: context for downstream workflows
- `expiry`: ISO date from trade legs

## How It Connects

```
┌─────────────┐     ┌──────────────────┐     ┌────────────────────┐
│ Broker      │     │ PricingService   │     │ rank_opportunities │
│ (Dhan/TT)   │────>│ batch_reprice()  │────>│ (thin orchestrator)│
│ get_chain() │     │ reprice_trade()  │     │ POP → Size → Out   │
└─────────────┘     │ RepricedTrade    │     └────────────────────┘
                    │ (frozen, immutable)│
                    └──────────────────┘
```

## Files Changed

| File | Lines Changed | What |
|------|---------------|------|
| `workflow/pricing_service.py` | +200 (new) | PricingService, RepricedTrade, LegDetail |
| `workflow/rank_opportunities.py` | -180, +100 (rewrite) | Thin orchestrator |
| `workflow/_types.py` | +5 | credit_source, current_price, regime_id, atr_pct |
| `trade_lifecycle.py` | +10 | DTE from leg dates, wing_width guard |
| `broker/dhan/market_data.py` | +15 | 30s chain cache |
| `trader/trader.py` | +20 | Expiry, instrument key, IV display, credit_source column |
| `trader/support.py` | +80 | Position loading, what-if positions |

## Test Coverage

- `tests/test_pricing_service.py`: 13 tests (new)
- All 165 rank+pricing tests pass
- Full suite: 2971 passed (3 pre-existing failures)

## Impact on Go-Live Score

India: **20% → 65%** in one session.
