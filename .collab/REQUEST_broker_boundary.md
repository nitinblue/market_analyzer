# REQUEST: Broker Connection Boundary — Data vs Execution Split

**From:** eTrading (session 48)
**Date:** 2026-03-24
**Priority:** P1 — architectural boundary
**Status:** REQUESTING

---

## Summary

`connect_*()` functions currently return 4 providers: (MarketData, Metrics, Account, Watchlist).

**Change to 3:** (MarketData, Metrics, Watchlist). Drop AccountProvider.

## Why

| Concern | Owner |
|---------|-------|
| Data providers (quotes, chains, Greeks) | **ID** — must swap freely |
| Execution + account state (orders, balance, margin) | **eTrading** — orchestrator owns |

- ID is open-source. Users shouldn't give it account access.
- Account credentials stay in the orchestrator, not the library.
- Data providers are swappable. Account access is not.

## Action

1. Audit which ID functions use AccountProvider internally
2. Change `connect_tastytrade/dhan/zerodha/alpaca/schwab()` to return 3-tuple
3. Refactor functions that read account state → accept `account_nlv`, `buying_power` as params
4. Confirm via FEEDBACK in eTrading collab channel

## Full Details

See `eTrading/collaboration/id-etrading/REQUEST_broker_boundary.md` for implementation spec.
