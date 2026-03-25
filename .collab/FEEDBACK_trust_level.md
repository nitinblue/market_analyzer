# FEEDBACK: Trust Level Everywhere

**From:** income-desk
**Date:** 2026-03-24
**Status:** ANSWERED

---

## Current State

`compute_trust_report()` exists and returns overall trust. But eTrading needs **per-ticker** and **per-position** trust — not just global.

## What ID Will Provide

### 1. Per-Ticker Trust (will build)

```python
def compute_ticker_trust(
    ticker: str,
    market_data: MarketDataProvider | None = None,
    has_ohlcv: bool = True,
) -> TickerTrust:
    """Trust level for a specific ticker.

    Returns:
        TickerTrust with:
        - data_source: "broker_live" | "yfinance_delayed" | "cached" | "none"
        - trust_level: "HIGH" | "MEDIUM" | "LOW" | "NONE"
        - price_staleness_seconds: int | None
        - has_greeks: bool
        - has_iv: bool
        - fit_for: str  # "execution" | "research" | "display_only"
    """
```

### 2. Per-Position Trust (will build)

```python
def compute_position_trust(
    legs: list[LegTrust],
    marked_at: str | None = None,
) -> PositionTrust:
    """Trust level for a position based on its legs' data quality.

    Returns:
        PositionTrust with:
        - overall_trust: "HIGH" | "MEDIUM" | "LOW"
        - pnl_reliable: bool
        - greeks_reliable: bool
        - stale_legs: int  # how many legs have no current quote
        - last_marked: str | None
    """
```

### 3. Global Trust Badge (already exists)

`compute_trust_report()` already returns what eTrading needs for the top bar. Just wire it:

```python
from income_desk import compute_trust_report
trust = compute_trust_report(
    has_broker=broker_connected,
    has_iv_rank=has_iv_data,
    has_vol_surface=has_vol_data,
)
# trust.overall_level → "HIGH" | "MEDIUM" | "LOW"
# trust.fit_for → "ALL purposes including live execution"
```

### 4. DataService Source Tracking

DataService does NOT currently track which source it used per ticker. I'll add:

```python
# After fetching
ds.last_fetch_source  # dict[str, str] — {"SPY": "yfinance", "NIFTY": "yfinance"}
ds.last_fetch_time    # dict[str, datetime]
```

This lets eTrading show "Prices from yfinance (delayed 15 min)" vs "Prices from TastyTrade (live)".

## Timeline

Will build per-ticker and per-position trust alongside the `mark_positions_to_market()` function — they're naturally paired.
