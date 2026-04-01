# REQUEST: VT Showcase Portfolio + Platform Market Data Bootstrap

**From:** eTrading
**To:** income-desk
**Date:** 2026-03-31
**Priority:** HIGH — blocks first-user experience

---

## Context

When a new user registers and creates their Virtual Twin (VT), the VT has zero trades and zero market data. The portfolio screens are empty — the user has no reason to trust the platform enough to connect their real broker.

We need two things:
1. VT gets a **curated showcase portfolio** with valid trades
2. Platform-level **market data bootstrap** that works without a broker

## REQUEST 1: `generate_showcase_portfolio(sim, capital, market)` → list[TradeSpec]

A function that, given a SimulatedMarketData instance, returns 5-8 TradeSpecs representing a healthy income portfolio:
- Mix of strategies: iron condor, vertical spread, covered call, calendar
- Mix of tickers from sim.supported_tickers()
- Mix of DTEs: some short (7-14 DTE), some medium (30-45 DTE)
- All structurally valid with legs, strikes, expiries relative to current date
- Sized appropriately for the given capital ($50K default)
- Trades should be valid at any point in time (not hardcoded dates/strikes)
- Each call produces slightly different portfolios (adjusted strikes/expiries)

### Expected Usage
```python
from income_desk import generate_showcase_portfolio, create_ideal_income

sim = create_ideal_income()
trades = generate_showcase_portfolio(sim, capital=50000, market='US')
# trades = [TradeSpec(...), TradeSpec(...), ...]
# Each has .legs, .strategy_type, .ticker, .expiry, etc.
# All tickers are in sim.supported_tickers()
```

## REQUEST 2: Platform-Level Market Data Bootstrap (No Broker)

**Problem:** eTrading passes broker providers to ID. Without a broker connected, ID has no market data to power VT analysis, pipeline scoring, or showcase pricing.

**Question:** Can ID provide a way to bootstrap platform-level market data without a broker? Options we see:

1. **`create_ideal_income()`** — already works, simulated data for 16 tickers. But prices are static/hardcoded. Is this good enough for VT showcase? Can prices be anchored to recent real prices (via yfinance/DataService)?

2. **`create_from_snapshot()`** — uses `~/.income_desk/sim_snapshot.json`. If eTrading runs `refresh_simulation_data()` once daily when any broker IS connected, the snapshot stays fresh. But on first install with no broker, no snapshot exists.

3. **`DataService` yfinance fallback** — ID's DataService can pull delayed OHLCV from yfinance. Can this be used to create a "platform-level" MarketData provider that works without a broker? Something like:
   ```python
   sim = create_from_yfinance(tickers=['SPY', 'QQQ', 'AAPL', ...])
   # Returns SimulatedMarketData with prices from yfinance (delayed but real)
   ```

4. **Hybrid:** Use `create_ideal_income()` for option chains/Greeks (simulated), but anchor underlying prices to yfinance real prices.

**What we need from ID:** Recommendation on which approach, and if a new function is needed, the interface. Key requirement: VT showcase data should be trustworthy (1-2 day staleness OK), not obviously fake.

## What Already Exists in ID

- `create_ideal_income()` — SimulatedMarketData with 16 tickers, full chains, Greeks
- `SimulatedAccount` — fake account balances
- `create_from_snapshot()` — recreate from saved snapshot
- `refresh_simulation_data(ma)` — capture live data to snapshot
- `DataService` — OHLCV from yfinance
- `select_strategies()`, `build_iron_condor()`, etc. — strategy builders

## Fallback

If generate_showcase_portfolio takes time, eTrading will try running its existing pipeline (Scout → Maverick) against SimulatedMarketData. But gates may reject everything without real market context.

---

**Status:** WAITING
