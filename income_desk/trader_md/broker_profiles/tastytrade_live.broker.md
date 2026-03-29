---
name: tastytrade_live
broker_type: tastytrade
mode: live
market: US
currency: USD
credentials: .env.trading
fallback: simulated
---

# TastyTrade Live

## Connection
- Streaming: DXLink
- Timeout: 30s
- Paper fallback: false

## Required Credentials (.env.trading)
- TASTYTRADE_CLIENT_SECRET_LIVE
- TASTYTRADE_REFRESH_TOKEN_LIVE
