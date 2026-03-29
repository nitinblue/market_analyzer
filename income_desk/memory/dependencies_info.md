# External Dependencies

> Type: INFO | Last updated: 2026-03-29

## eTrading (cotrader)
- Collaboration protocol via .collab/ channel
- REQUEST_, FEEDBACK_, CONTRACT_ files for async communication
- Retrospection shared files in ~/.income_desk/retrospection/

## TastyTrade
- DXLink streaming for live quotes and Greeks
- OAuth tokens, paper + live modes
- DXLinkStreamer, DXGreeks, DXQuote imports

## Dhan
- REST API for India market (NSE F&O)
- Rate limits: 25 req/s general, 1 per 3s for option_chain
- Token refresh: manual (no auto-refresh implemented)
- Auth: DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN in .env

## yfinance
- OHLCV historical data, free, no API key
- Chain structure (strikes/expirations) only — NOT for live pricing

## FRED
- Macro data (put/call ratios, economic indicators)
- EQUITPC discontinued, using PCRATIOPCE as fallback

## PyPI
- Package: income-desk
- Distribution channel for library releases

## GitHub Actions
- CI/CD pipeline
- Secret: PYPI_PUBLISH for releases

## Claude Scheduled Agents
- Daily harness runs (India 9:15 IST, US 9:30 ET)
- Cannot access local .env — run on simulated data only
