# FEEDBACK: Options Pipeline Without Broker + Mark-to-Market

**From:** income-desk
**Date:** 2026-03-24
**Status:** ANSWERED + WILL BUILD

---

## Options Without Broker — How It Works

**Answer: rank() DOES produce option trades without a broker.** But eTrading must inject SimulatedMarketData or accept estimation-based results.

### Three modes:

| Mode | Data Source | Trust | Option Chains | Recommendation |
|------|-----------|-------|---------------|----------------|
| **Connected** | User's broker via MarketDataProvider | HIGH | Real chains with Greeks | Production trading |
| **Simulated** | `create_ideal_income()` or snapshot | UNRELIABLE | Synthetic chains | Demo, testing, weekend |
| **Estimation** | yfinance OHLCV only (no provider) | LOW | ATR-based strike estimation | Research only — NOT for execution |

**For Maverick to book option trades without a live broker:**
```python
from income_desk import create_ideal_income, SimulatedMetrics, MarketAnalyzer, DataService

# Use simulation layer
sim = create_ideal_income()  # or create_from_snapshot() for saved real data
ma = MarketAnalyzer(
    data_service=DataService(),
    market_data=sim,
    market_metrics=SimulatedMetrics(sim),
)
result = ma.ranking.rank(["SPY", "NVDA", "GOOG"])
# Returns full TradeSpecs with legs, strikes, Greeks
```

**Recommended approach for production:**
- Broker connected → real data, TRUST: HIGH
- Broker disconnected → `create_from_snapshot()` (last captured real data), TRUST: LOW, flag in UI
- No snapshot available → estimation only, TRUST: LOW, block execution (WhatIf only)

## Mark-to-Market — ID Will Build

eTrading is right — PnL computation is ID's job. I'll build:

### `mark_positions_to_market()`

```python
def mark_positions_to_market(
    positions: list[PositionInput],
    market_data: MarketDataProvider | None = None,
    data_service: DataService | None = None,
) -> MarkedPositions:
    """Mark open positions to current market prices.

    Fetches current prices from:
    1. market_data provider (broker — preferred, HIGH trust)
    2. data_service / yfinance (fallback — delayed, LOW trust)

    Returns per-position: current_price, pnl, pnl_pct, data_source, trust_level.
    """
```

### `get_current_prices()`

```python
def get_current_prices(
    tickers: list[str],
    market_data: MarketDataProvider | None = None,
    data_service: DataService | None = None,
) -> dict[str, PriceResult]:
    """Get current prices with source attribution.

    Returns: {ticker: PriceResult(price, source="broker_live"|"yfinance_delayed", trust="HIGH"|"LOW")}
    """
```

Both functions try broker first, fall back to yfinance. eTrading passes whatever providers it has. ID handles the fallback logic.

**Will add to `income_desk/trade_analytics.py` and export from top-level.**

## PnL = $0 on Equity Positions — Root Cause

eTrading's mark-to-market service calls `compute_trade_pnl()` which works correctly. But if `leg.current_price` is never updated (because mark-to-market never runs, or broker returns no quotes), PnL stays at $0.

**Fix chain:**
1. eTrading calls `mark_positions_to_market()` (new ID function) periodically
2. ID fetches prices (broker or yfinance fallback)
3. eTrading updates DB with returned prices
4. PnL is computed from updated prices

The current mark-to-market service in eTrading tries to fetch quotes from the broker adapter — which fails when broker isn't connected. With ID's new function, yfinance fallback means PnL is never $0 on held positions.
