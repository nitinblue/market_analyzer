# Pipeline Migration Guide — March 30 to April 1

> Published: 2026-04-01 | For: eTrading integration team

## What Changed (Big Picture)

The trading pipeline was fundamentally restructured. Before: assessors generated trades from ATR math, then pricing tried to match to real chain. Now: chain data drives everything from the start.

### Old Pipeline (pre-April)
```
ticker → regime → ATR-based strikes → price at mid → POP from ATR → size → output
                   ↑ wrong strikes     ↑ wrong price   ↑ wrong POP
```

### New Pipeline (April 1)
```
ticker → regime → ChainBundle fetch → chain-based strikes → bid/ask pricing → IV-based POP → validate → size → output
                   ↑ single fetch       ↑ real strikes       ↑ real credit      ↑ 4 IV sources  ↑ structure rules
```

## Key Architecture Changes

### 1. ChainBundle (single-fetch-per-ticker)
- **Before:** Chain fetched 4-5x per ticker (ranking, vol_surface, reprice, assessors)
- **Now:** `ChainFetcher.fetch_batch()` fetches once, `ChainBundle` passed everywhere
- **Impact on eTrading:** If you were calling `get_option_chain()` directly, use `ChainFetcher` instead

### 2. TradeValidator (post-generation validation)
- **Before:** No validation — garbage input reached sizing and output
- **Now:** Every trade passes through `TradeValidator.validate()` before output
- **What it catches:** Same-strike wings, zero credit, suspicious POP (>95%), wrong leg count
- **Impact on eTrading:** Trades in `RankResponse.trades` are now validated. `RankResponse.blocked` has detailed rejection reasons

### 3. POP Multi-Source IV
- **Before:** POP used ATR-only, with arbitrary regime factors (R1=0.40)
- **Now:** 4 sources: broker_leg_iv → iv_30_day → vol_surface_iv → ATR (fallback)
- **Impact on eTrading:** Pass `iv_30_day_map` in `RankRequest` for Source 2

### 4. Unlimited-Risk POP
- **Before:** Strangle/straddle POP returned 0% (tried wing_width, got None → broke)
- **Now:** Separate code path for unlimited risk. POP from breakevens, EV uses 1-sigma adverse proxy
- **Impact on eTrading:** `POPEstimate.max_loss` for strangles is now a proxy value with data_gap noting "unlimited risk"

### 5. Wing Width Floor
- **Before:** ATR*0.5 could be < strike interval → same-strike wings → rejected
- **Now:** Wing width floored at 1 strike interval minimum
- **Impact on eTrading:** Fewer rejected trades, more tradeable IC/IB suggestions

### 6. Data Trust Banner
- **Before:** Data source shown in banner but easy to miss
- **Now:** Prominent `** DATA: SIMULATED — NOT for trading decisions **` or `** DATA: LIVE (broker) **`
- **Impact on eTrading:** Use `BannerMeta.data_source` to check if simulated

## New Fields in Existing Models

### RankRequest
```python
class RankRequest:
    iv_30_day_map: dict[str, float] | None = None  # NEW — pass from market_metrics.get_metrics()
```

### DailyPlanRequest
```python
class DailyPlanRequest:
    iv_30_day_map: dict[str, float] | None = None  # NEW
```

### TradeProposal (already had these, now populated correctly)
- `regime_id` — now always set
- `atr_pct` — now always set
- `short_put`, `long_put`, `short_call`, `long_call` — from real chain
- `entry_credit` — from bid/ask (not mid)
- `credit_source` — "chain" or "estimated"

## Breaking Changes

1. `_fetch_iv_rank_map()` → `_fetch_iv_maps()` returns `(iv_rank_map, iv_30_day_map)`
2. Ratio spread: 3 LegSpec objects (was 2 with qty=2)
3. Equity trades: `lot_size=1` (was inheriting 100 from options)
4. `STRUCTURE_RULES` has new entry: `double_calendar`

## How to Test (No Broker Needed)

```python
from income_desk import SimulatedMarketData, SimulatedMetrics, MarketAnalyzer, DataService
from income_desk.adapters.simulated import create_ideal_income
from income_desk.workflow.rank_opportunities import RankRequest, rank_opportunities

sim = create_ideal_income()
mm = SimulatedMetrics(sim)
ma = MarketAnalyzer(data_service=DataService(), market_data=sim, market_metrics=mm)

metrics = mm.get_metrics(sim.supported_tickers())
req = RankRequest(
    tickers=sim.supported_tickers(),
    capital=100_000.0,
    market="US",
    iv_rank_map={t: m.iv_rank for t, m in metrics.items() if m.iv_rank},
    iv_30_day_map={t: m.iv_30_day for t, m in metrics.items() if m.iv_30_day},
)
resp = rank_opportunities(req, ma)
# resp.trades = validated GO trades
# resp.blocked = rejected with reasons
```
