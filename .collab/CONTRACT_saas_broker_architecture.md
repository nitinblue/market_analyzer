# CONTRACT: SaaS Multi-Tenant Broker Architecture

**Status:** DRAFT — proposed to eTrading, awaiting response
**Date:** 2026-03-24

---

## Summary

Per-user broker connections in SaaS. ID provides `create_user_analyzer(broker, session, data_service)` factory. eTrading owns credential storage, session lifecycle, token refresh.

## Key Design Decisions (Pending eTrading Input)

1. Cache MA instances per user, or create fresh per request?
2. One MA per market for multi-broker users, or single MA with delegation?
3. Hot-swap free → connected, or force new session?
4. Concurrent user budget (determines pooling strategy)
5. WebSocket management for streaming quotes

## What ID Provides (Already Built)

- `MarketDataProvider` / `MarketMetricsProvider` ABCs
- `connect_*_from_session()` for all 6 brokers
- `MarketAnalyzer` with injectable providers
- `exclude_account=True` for clean data-only connections

## What ID Will Build (After Agreement)

- `create_user_analyzer(broker, session, data_service)` — one-line factory
- Routes to correct `connect_*_from_session()` internally
- Returns `MarketAnalyzer` with user's broker data injected

## Full Contract

See `eTrading/collaboration/id-etrading/CONTRACT_saas_broker_architecture.md`
