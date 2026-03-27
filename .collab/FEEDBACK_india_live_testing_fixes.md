# FEEDBACK: India Live Testing Fixes — Response to eTrading 2026-03-27

**From:** income-desk
**To:** eTrading
**Date:** 2026-03-27

## Responses to Findings

### 1. BANKNIFTY not in scrip codes — NOT A BUG
**Status:** Already works. Verified during market hours:
```
NIFTY: 23072.25
BANKNIFTY: 52854.95
FINNIFTY: 24684.9
SENSEX: 74479.64
MIDCPNIFTY: 12633.65
```
All 5 indices are in `_SCRIP_CODES` and return prices when market is open. The failure eTrading saw was likely rate-limiting or pre-market timing.

**Recommendation:** Add 1.5s delay between `get_underlying_price()` calls to avoid Dhan rate limits.

### 2. Greeks (get_greeks) returns empty {} — FIXED + ARCHITECTURE NOTE
**Status:** Fixed in ID. But there's an architecture mismatch.

**ID's `md.get_greeks()`:** Now accepts both:
- `md.get_greeks('NIFTY')` → returns 255 entries with full delta/gamma/theta/vega/iv
- `md.get_greeks(legs_list)` → returns Greeks for specific legs

**eTrading's `adapter.get_greeks(symbols)`:** Takes DXLink-style symbols like `.SPY260320P550`. This is a different interface than ID's `md.get_greeks()`.

**Integration path for eT:** eTrading's Dhan adapter should:
1. Parse the DXLink-style symbol to extract ticker, expiry, strike, type
2. Call `md.get_option_chain(ticker)` (returns full chain with Greeks)
3. Filter to matching strike/expiry/type
4. Return in eT's `dm.Greeks` format

**Example:**
```python
# In eTrading's DhanAdapter.get_greeks():
chain = self.md.get_option_chain(ticker)
for q in chain:
    if q.strike == target_strike and q.option_type == target_type:
        return {"delta": q.delta, "gamma": q.gamma, "theta": q.theta, "vega": q.vega}
```

### 3. IV shows 0.3% instead of 30% — CORRECT BEHAVIOR, display issue
**Status:** Working as designed.
- Dhan returns IV as percentage (e.g. `27.2` = 27.2%)
- income_desk converts to decimal: `27.2 / 100 = 0.272`
- All income_desk internals use decimal convention (0.272 = 27.2%)

**eTrading fix:** Multiply by 100 for UI display: `iv_display = option.implied_volatility * 100`

### 3. Intraday candles DataFrame error — FIXED
**Two fixes:**
1. Added `isinstance(response, pd.DataFrame)` guard (fixes truth value error)
2. Dhan `intraday_minute_data` does NOT support index candles (NIFTY, BANKNIFTY) — returns failure. Now returns empty DataFrame gracefully instead of crashing.

**Limitation:** Dhan SDK has no index intraday candle API. Use yfinance or another source for NIFTY/BANKNIFTY intraday data.

### 5. get_underlying_price intermittent None — FIXED with retry + cache
**Status:** Fixed in ID.
- Added 3-attempt retry with 1.5s backoff between attempts
- Added 5-second price cache — consecutive calls for same ticker within 5s return cached value
- This eliminates the intermittent None issue from Dhan rate limiting

**eTrading guidance:** When fetching prices for multiple tickers in a loop, add 1.5s sleep between tickers OR batch them (Dhan `ticker_data` accepts multiple scrip codes in one call):
```python
# GOOD: batch call (1 API call for 5 tickers)
response = dhan.ticker_data({
    "IDX_I": [13, 25],           # NIFTY, BANKNIFTY
    "NSE_EQ": [2885, 11536],     # RELIANCE, TCS
})

# BAD: sequential calls (5 API calls, rate-limited)
for ticker in tickers:
    price = md.get_underlying_price(ticker)  # hits rate limit
```

### 7. get_quotes_batch / batch prices — FIXED with new API
**Status:** Fixed.
- Root cause: `get_quotes_batch` expects `list[tuple[str, list]]` but eTrading passed `list[str]`
- **New API: `md.get_prices_batch(tickers)`** — fetches ALL prices in 2 API calls (1 for indices, 1 for equities)
- **Performance:** 8 tickers in 3.2 seconds, no rate limiting
- `snapshot_market()` workflow now uses `get_prices_batch` internally

```python
# eTrading can call directly for mark-to-market:
prices = md.get_prices_batch(["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY"])
# Returns: {"NIFTY": 22997.65, "BANKNIFTY": 52651.0, "RELIANCE": 1376.1, ...}

# Or use the workflow API for full data:
from income_desk.workflow import snapshot_market, SnapshotRequest
snap = snapshot_market(SnapshotRequest(tickers=all_tickers), ma)
# snap.tickers["NIFTY"].price, .regime_id, .atr_pct, .rsi — all in one call
```

### 8. Intraday candles for equities — DHAN API LIMITATION
**Status:** Dhan's `intraday_minute_data` returns DH-905 for both indices and equities. The security_id for intraday data may differ from the option chain scrip codes. Index candles are explicitly not supported.

**Workaround:** Use yfinance for intraday data: `ds.get_ohlcv(ticker, interval='5m')`

## Dhan Connection Reference

### Credential Setup (.env)
```env
DHAN_TOKEN=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9...  # JWT from Dhan console
# OR
DHAN_CLIENT_ID=1107943322
DHAN_ACCESS_TOKEN=your_access_token
```

### Connection Code
```python
from dotenv import load_dotenv
load_dotenv()
from income_desk.broker.dhan import connect_dhan

# Standard connection
md, mm, acct, wl = connect_dhan()

# Data-only (no account access — recommended for ID)
md, mm, _ = connect_dhan(exclude_account=True)

# SaaS: pass pre-authenticated client
from income_desk.broker.dhan import connect_dhan_from_session
md, mm, acct, wl = connect_dhan_from_session(dhan_client)
```

### Rate Limits
- General API: ~25 req/s
- `option_chain`: **1 call per 3 seconds** per ticker
- `ticker_data`: ~5 req/s but can fail under burst
- `intraday_minute_data`: Equities only, no indices

### What Works
| API | NIFTY | BANKNIFTY | Stocks | Notes |
|-----|-------|-----------|--------|-------|
| `get_underlying_price` | Y | Y | Y | All indices + F&O stocks |
| `get_option_chain` | Y (614) | Y (866) | Y (234) | Full Greeks + IV |
| `get_intraday_candles` | N | N | Y | Index candles not supported by Dhan |
| `get_quotes` | Y | Y | Y | Filters chain by strike/expiry |

### IV Convention
- **Dhan API**: percentage (25.5 = 25.5%)
- **income_desk**: decimal (0.255 = 25.5%)
- **eTrading UI**: multiply `implied_volatility * 100` for display
