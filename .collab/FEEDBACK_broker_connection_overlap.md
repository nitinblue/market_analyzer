# FEEDBACK: Broker Connection Overlap — Full Answers

**From:** income-desk
**Date:** 2026-03-24
**Status:** ANSWERED

---

## 1. `connect_*()` Contract — Exactly What Goes In, What Comes Out

**Two modes per broker:**

| Mode | Function | Who Authenticates | What Goes In | What Comes Out |
|------|----------|-------------------|-------------|----------------|
| **Standalone** | `connect_tastytrade(config_path, is_paper)` | **ID** reads YAML/env | Config path or env vars | 3-tuple (MarketData, Metrics, Watchlist) |
| **SaaS/Embedded** | `connect_from_sessions(sdk_session)` | **eTrading** authenticates first | Pre-authenticated SDK session object | 3-tuple (MarketData, Metrics, Watchlist) |

**For SaaS: eTrading MUST use the `_from_session()` variants.** eTrading authenticates, gets the SDK session, passes it to ID. ID wraps it in providers. ID never touches credentials.

**What `session` needs to be:**
- TastyTrade: `tastytrade.Session` (already authenticated)
- Dhan: `dhanhq` client instance (already initialized with client_id + token)
- Zerodha: `KiteConnect` instance (already logged in)
- Schwab: `schwab.Client` (already authenticated via OAuth)
- IBKR: IBKR gateway connection object
- Alpaca: `alpaca.TradingClient` (already authenticated)

## 2. Provider Lifecycle — Stateful vs Stateless

**MarketDataProvider: stateful for streaming brokers, stateless for REST.**
- TastyTrade: holds DXLink WebSocket for streaming quotes. Long-lived.
- Dhan: REST calls per request. Stateless. Can be created/destroyed freely.
- All others: REST. Stateless.

**Caching:** Providers do NOT cache internally. Each `get_option_chain()` call hits the broker. eTrading should cache at its layer if needed.

**Expiry:** Providers don't expire, but the underlying session might. ID raises `TokenExpiredError` when a broker call fails due to auth. eTrading catches, refreshes token, creates new providers.

**Lifecycle recommendation:**
- REST brokers (Dhan, Schwab, Alpaca): create per-request or cache — doesn't matter, they're cheap
- WebSocket brokers (TastyTrade): cache per-user for session duration, destroy on logout/idle

## 3. MarketAnalyzer Fallback Behavior

**If `market_data=None` and `market_metrics=None`:**
- `ma.ranking.rank()` still works — uses `DataService` (yfinance) for OHLCV
- Vol surface is estimated from historical data (not from live chain)
- TradeSpecs are generated with strikes from ATR-based estimation
- Trust level: LOW
- **Option chains are synthetic** — computed from vol surface estimation, not real broker data

**This is exactly how the test produced 44 option trades for NVDA/GOOG/MSFT/JPM without a broker.** It used `SimulatedMarketData` which provides synthetic chains. Without even simulation, `rank()` falls back to OHLCV-only estimation.

**DataService does NOT fetch option chains.** It only provides OHLCV. When no `MarketDataProvider` is injected, the ranking pipeline uses internal estimation for strike selection.

## 4. How rank() Got Option Chains Without Broker

The test used `SimulatedMarketData`:
```python
sim = SimulatedMarketData({"NVDA": {"price": 175, "iv": 0.40, "iv_rank": 55}})
ma = MarketAnalyzer(data_service=DataService(), market_data=sim, market_metrics=SimulatedMetrics(sim))
result = ma.ranking.rank(["NVDA"])  # 44 option trades
```

SimulatedMarketData generates synthetic option chains with realistic strikes/Greeks. For production without a broker, eTrading can either:
1. Use `create_ideal_income()` or `create_from_snapshot()` for offline testing
2. Accept LOW trust and use estimation-based TradeSpecs (strikes from ATR, no real Greeks)
3. Require broker connection for option trading (recommended)

## 5. Session Ownership — Final Answer

| Step | Owner | Detail |
|------|-------|--------|
| Store credentials | eTrading | Encrypted DB |
| Authenticate with broker | eTrading | Gets SDK session |
| Pass session to ID | eTrading | `connect_from_sessions(session)` |
| Create data providers | ID | Wraps session in MarketData/Metrics |
| Use providers in MA | ID | `ma.ranking.rank()` calls `market_data.get_option_chain()` |
| Detect token expiry | ID | Raises `TokenExpiredError` |
| Handle token refresh | eTrading | Catches error, re-auths, creates new providers |
| Destroy providers | eTrading | On logout/idle, drops references |
