# New APIs for eTrading — April 2026

> Published: 2026-04-01 | Status: READY FOR CONSUMPTION

## Summary

Three major new capabilities now exported from `income_desk`. All available via `from income_desk import ...`.

## 1. ChainBundle + ChainFetcher

Single-fetch, pass-everywhere option chain architecture. Replaces the old pattern of fetching chains 4-5x per ticker.

```python
from income_desk import ChainBundle, ChainFetcher

fetcher = ChainFetcher(market_data=md)
bundles = fetcher.fetch_batch(["SPY", "QQQ", "GLD"])

for b in bundles:
    print(f"{b.ticker}: usable={b.is_usable}, quality={b.quality_pct}%")
    # Contains: raw_chain, chain_df, vol_surface, chain_context, fetch_meta
```

**eTrading action:** Use `ChainFetcher.fetch_batch()` for pre-fetching chains instead of calling `get_option_chain()` per ticker.

## 2. InstrumentSnapshot + SnapshotService

Pre-market snapshot for zero-network-call trading. Captures full chain topology with OI data.

```python
from income_desk import SnapshotService, MarketSnapshot

# Build during market hours
snap = SnapshotService.build(market_data=md, tickers=["SPY", "QQQ"])
SnapshotService.save(snap, market="US")

# Load any time (zero network)
snap = SnapshotService.load(market="US")
inst = snap.instruments["SPY"]
exp = inst.nearest_expiry("weekly")
```

**eTrading action:** Build snapshots pre-market, load during day for faster ranking.

## 3. TradeValidator

Structure-aware configurable validation engine. Validates trades after generation but before ranking output.

```python
from income_desk import TradeValidator, ValidationConfig, STRUCTURE_RULES

validator = TradeValidator()
result = validator.validate(trade_spec)

# result.status: "valid", "flagged", or "rejected"
# result.economics: ValidatedEconomics (non-null for valid/flagged only)
# result.rejections: list[ValidationRejection] with root_cause + suggestion
```

**9 structures supported:** iron_condor, iron_butterfly, credit_spread, debit_spread, calendar, diagonal, strangle, straddle, ratio_spread, double_calendar

**eTrading action:** Use `TradeValidator.validate()` as a gate before execution. Catches same-strike wings, suspicious POP, zero-credit trades.

## 4. SimulatedMarketData

For testing without broker connection:

```python
from income_desk import SimulatedMarketData, SimulatedMetrics, SimulatedAccount

sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18, "iv_rank": 43}})
mm = SimulatedMetrics(sim)
acct = SimulatedAccount(nlv=100_000.0)
```

Presets: `create_calm_market()`, `create_volatile_market()`, `create_crash_scenario()`, `create_india_trading()`, `create_ideal_income()`

## 5. POP Multi-Source IV

`estimate_pop()` now uses 4 IV sources in priority order:
1. `broker_leg_ivs` — per-leg IV from DXLink Greeks (most accurate)
2. `iv_30_day` — 30-day IV from market metrics (now wired through RankRequest)
3. `leg.atm_iv_at_expiry` — IV from vol surface
4. ATR-based (backward-looking fallback)

**eTrading action:** Pass `iv_30_day_map` in `RankRequest` alongside `iv_rank_map`:

```python
req = RankRequest(
    tickers=tickers,
    iv_rank_map=iv_rank_map,
    iv_30_day_map=iv_30_day_map,  # NEW
)
```

## Breaking Changes

- `_fetch_iv_rank_map()` in trader.py renamed to `_fetch_iv_maps()`, returns tuple `(iv_rank_map, iv_30_day_map)`
- `RankRequest` and `DailyPlanRequest` have new optional field `iv_30_day_map`
- Ratio spread now generates 3 LegSpec objects (was 2 with quantity=2)
- Equity trades always have `lot_size=1` (was inheriting 100 from options registry)

## Integration Doc

Full integration guide updated: `docs/project_integration_living.md` section 1b.
