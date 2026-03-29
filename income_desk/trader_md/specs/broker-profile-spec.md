# Broker Profile Specification

**Version:** 1.0
**Status:** Draft
**File extension:** `.broker.md`

## Overview

A broker profile file configures how the TradingRunner connects to a brokerage for live or simulated data. Each workflow references a broker profile via the `broker:` frontmatter field. The runner uses the profile to determine which broker SDK to initialize, what credentials to load, and what fallback behavior to use when the connection fails or markets are closed.

## File Structure

```
---
name: <identifier>
broker_type: <type>
mode: <mode>
market: <market_code>
currency: <currency_code>
credentials: <env_file_path>
fallback: <fallback_type>
---

# Title (ignored by parser)

<body text ignored by parser>
```

## Frontmatter Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| name | string | no | file stem | Unique identifier for the broker profile |
| broker_type | string | no | `"simulated"` | Broker SDK to use. One of: `"tastytrade"`, `"dhan"`, `"simulated"` |
| mode | string | no | `"live"` | Connection mode. One of: `"live"`, `"paper"`, `"simulated"` |
| market | string | no | `"US"` | Market this broker serves. One of: `"US"`, `"India"` |
| currency | string | no | `"USD"` | Account currency. One of: `"USD"`, `"INR"` |
| credentials | string | no | `".env.trading"` | Path to the environment file containing broker credentials, relative to the trader_md base directory |
| fallback | string | no | `"simulated"` | What to use when broker connection fails. One of: `"simulated"`, `"none"` |

## Body Sections

The body text is ignored by the parser. It is used for human-readable documentation such as connection details, timeout settings, and required credential variable names.

## Examples

### Minimal Example

```markdown
---
name: simulated
broker_type: simulated
---

# Simulated Broker

No credentials required.
```

### Full Example

```markdown
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
```

### India Broker Example

```markdown
---
name: dhan_live
broker_type: dhan
mode: live
market: India
currency: INR
credentials: .env.trading
fallback: simulated
---

# Dhan Live

## Required Credentials (.env.trading)
- DHAN_CLIENT_ID
- DHAN_ACCESS_TOKEN
```

## Parser Behavior

- Only frontmatter is parsed; the entire body is ignored
- The `credentials` field (named `credentials` in YAML, stored as `credentials_source` in the model) specifies an env file path. The runner loads this file via `python-dotenv` before attempting broker connection
- If the credentials env file does not exist at the resolved path, the runner falls back to loading the default `.env` file
- When `broker_type` is `"simulated"`, no broker connection is attempted and preset market data is used
- When `broker_type` is `"tastytrade"` and `mode` is `"paper"`, the runner connects to the TastyTrade paper trading environment
- When markets are closed (determined by `is_market_open()`), the runner switches to simulated quotes even if the broker connection succeeds, appending "(market closed, simulated quotes)" to the data source label
- When broker connection fails and `fallback` is `"simulated"`, the runner silently falls back to simulated data. When `fallback` is `"none"`, no fallback occurs
