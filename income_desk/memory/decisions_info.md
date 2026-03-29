# Key Decisions

> Type: INFO | Last updated: 2026-03-29

## Naming Conventions
- "base" = live market data, "scenario" = stressed/tweaked data
- trader/ = Python path, trader_md/ = MD path, same engine
- Market Pulse = user-facing name for sentinel (internal code unchanged)

## Architecture Decisions
- Scenario engine is production risk infrastructure, not dev tooling
- One library on PyPI, open format specs
- MD as universal trading language — three distribution layers
- Single-leg execution for India (NSE limitation)
- Broker creds in .env.trading, never in MD files

## Integration Decisions
- eTrading collaboration via .collab/ channel, REQUEST_/FEEDBACK_/CONTRACT_ files
- Never relay through Nitin — use shared files directly
- `rank()` output is NOT safe to execute directly — must pass through filter + gate
