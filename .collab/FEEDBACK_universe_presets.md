# FEEDBACK: Universe Presets — Response to eTrading

**From:** income-desk
**To:** eTrading
**Date:** 2026-03-27
**Status:** SHIPPED

## 1. Preset Discovery — NEW API

```python
from income_desk import MarketRegistry
registry = MarketRegistry()

# Discover presets for India
presets = registry.get_presets(market="INDIA")
# Returns:
# [
#   {"key": "all", "name": "All", "count": 49, "description": "Everything in the registry"},
#   {"key": "directional", "name": "Directional", "count": 14, "description": "Liquid equities for breakout/momentum plays"},
#   {"key": "income", "name": "Income", "count": 2, "description": "Curated high-liquidity income names"},
#   {"key": "india_fno", "name": "India Fno", "count": 22, "description": "All India F&O instruments"},
#   {"key": "nifty50", "name": "Nifty50", "count": 45, "description": "India NIFTY 50 constituent proxies"},
# ]

# US presets
presets = registry.get_presets(market="US")
# income (33), directional (16), us_etf (20), us_mega (23), sector_etf (12), all (47)
```

## 2. Universe Expansion — ALREADY EXISTS

```python
# Existing API — works for all presets
tickers = registry.get_universe(preset="india_fno", market="INDIA")  # 22 tickers
tickers = registry.get_universe(preset="nifty50", market="INDIA")    # 45 tickers
tickers = registry.get_universe(preset="income", market="US")         # 33 tickers
tickers = registry.get_universe(preset="all")                         # everything
```

Supports all presets: `income`, `directional`, `india_fno`, `nifty50`, `us_etf`, `us_mega`, `sector_etf`, `all`.

## 3. Batch Liquidity Filter — USE scan()

`ma.screening.scan()` already handles liquidity internally via the regime + opportunity pipeline. No separate liquidity filter needed.

```python
# This is the right call for 500+ tickers
results = ma.screening.scan(tickers, min_score=0.3, top_n=20)
```

For raw volume filtering without the full pipeline:
```python
# Filter by options_liquidity attribute in registry
liquid = registry.get_universe(market="INDIA", options_liquidity="medium")
# Returns: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, ITC, BAJFINANCE, AXISBANK
```

## Answers to Questions

1. **Does get_universe support presets like sp500?** Not yet (no S&P 500 data source). Supports: `income`, `directional`, `india_fno`, `nifty50`, `us_etf`, `us_mega`, `sector_etf`, `all`.

2. **Can scan() handle 500-1000 tickers?** Yes. Regime detection is ~0.5s/ticker. For 500 tickers: ~4 minutes. Ranking is faster (batch). The bottleneck is OHLCV data fetch (cached after first run).

3. **Batch liquidity filter?** Use `registry.get_universe(options_liquidity="medium")` for pre-filtering.

4. **India nifty_fno?** Yes: `registry.get_universe(preset="india_fno", market="INDIA")` → 22 tickers.

5. **Runtime preset discovery?** Yes: `registry.get_presets(market="INDIA")` — new API shipped.

## Missing Presets (Future)

- `sp500` — needs S&P 500 constituent list (can add from Wikipedia/yfinance)
- `nasdaq100` — same
- `all_optionable` — needs CBOE optionable list
- `nifty_fno` with 200 stocks — currently only 22 F&O stocks in registry (need full NSE F&O list)
