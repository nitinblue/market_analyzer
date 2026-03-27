# FEEDBACK: Simulated Market Data — Weekend Testing Ready

**From:** income-desk
**To:** eTrading
**Date:** 2026-03-27

## Summary

Simulated market data upgraded for comprehensive weekend development/testing. Works without broker, internet, or market hours.

## Available Presets

```python
from income_desk.adapters.simulated import (
    create_ideal_income,        # US: 16 tickers, R1/R2, ideal for income
    create_india_trading,       # India: 22 tickers (5 indices + 17 F&O stocks)
    create_calm_market,         # US: R1, low vol
    create_volatile_market,     # US: R2, elevated IV
    create_crash_scenario,      # US: R4, extreme IV
    create_post_crash_recovery, # US: R2->R1, very elevated IV
    create_wheel_opportunity,   # US: stocks at support for wheel
    SimulatedMetrics,           # IV rank, metrics from sim data
)
```

## Ticker Coverage

**US (create_ideal_income):** 16 tickers
SPY, QQQ, IWM, GLD, TLT, DIA, AAPL, MSFT, AMZN, NVDA, TSLA, META, GOOGL, XLF, XLE, XLK

**India (create_india_trading):** 22 tickers
Indices: NIFTY, BANKNIFTY, FINNIFTY, SENSEX, MIDCPNIFTY
Stocks: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, BHARTIARTL, ITC, BAJFINANCE, AXISBANK, KOTAKBANK, LT, MARUTI, SUNPHARMA, TITAN, HINDUNILVR, WIPRO

## Discovery API

```python
sim = create_india_trading()
sim.supported_tickers()   # ["AXISBANK", "BAJFINANCE", "BANKNIFTY", ...]
sim.has_ticker("NIFTY")   # True
sim.ticker_info()         # {"NIFTY": {"price": 23000, "iv": 0.18, ...}}
```

## Using with Workflows

```python
from income_desk import MarketAnalyzer, DataService
from income_desk.adapters.simulated import create_india_trading, SimulatedMetrics

sim = create_india_trading()
ma = MarketAnalyzer(
    data_service=DataService(),
    market_data=sim,
    market_metrics=SimulatedMetrics(sim),
)

# All 15 workflows work with simulated data
from income_desk.workflow import generate_daily_plan, DailyPlanRequest
plan = generate_daily_plan(
    DailyPlanRequest(tickers=sim.supported_tickers(), capital=5_000_000, market="India"),
    ma,
)
```

## India-Specific Features
- Strike intervals from registry (NIFTY=50, BANKNIFTY=100, RELIANCE=20, TCS=25)
- Per-ticker lot sizes (NIFTY=25, BANKNIFTY=15, RELIANCE=250, etc.)
- India expirations (3, 10, 30, 60 DTE vs US 7, 21, 35, 60)
- INR currency, Asia/Kolkata timezone
- Prices approximate to late March 2026

## Batch APIs (new)
- `sim.get_prices_batch(tickers)` — batch price fetch
- `sim.get_greeks("NIFTY")` — Greeks from chain
- Both match the Dhan adapter interface for code portability
