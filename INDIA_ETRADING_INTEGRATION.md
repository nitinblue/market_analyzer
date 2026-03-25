# India Market — eTrading Integration Guide

This document captures everything eTrading needs to know to consume income_desk for India markets. Updated: 2026-03-23.

---

## 1. Broker Connection (Dhan)

### Setup
```python
from income_desk.broker.dhan import connect_dhan

# Auto-detects client_id from JWT, reads DHAN_TOKEN from .env
md, mm, acct, wl = connect_dhan()

# Or explicit:
md, mm, acct, wl = connect_dhan(client_id="1107943322", access_token="eyJ...")
```

### Env Vars
- `DHAN_TOKEN` — Daily JWT access token (expires every 24h)
- `DHAN_CLIENT_ID` — Optional, auto-extracted from JWT

### Token Refresh
Dhan tokens expire daily. eTrading must refresh via Dhan OAuth flow each morning before market open (9:15 IST). **No auto-refresh in income_desk** — this is eTrading's responsibility.

### Data API Subscription
Dhan Data APIs (quotes, option chain, historical) require a paid subscription (₹499/month). Without it, only account/order APIs work.

### Rate Limits
- `ticker_data` / `ohlc_data`: 25 req/sec aggregate (but easily throttled — 805 errors common)
- `option_chain`: 1 unique request per 3 seconds
- `expiry_list`: Same rate as option_chain
- **Best practice:** Cache option chain data, refresh every 30-60 seconds

---

## 2. Key Differences from US Market

### Single-Leg Execution (CRITICAL)
**India has NO multi-leg orders.** Every strategy is executed one leg at a time.

eTrading must implement:
1. **Leg ordering** — Execute most liquid / hardest-to-fill leg first
2. **Fill timeout** — 30 seconds per leg (configurable)
3. **Rollback** — If a leg doesn't fill, cancel and close previously filled legs
4. **Partial-fill safety** — If long leg fills but short doesn't, position is already hedged (safe to hold). If short leg fills but long doesn't, you have naked exposure (must close immediately).

`TradeSpec.legs` provides an ordered list. eTrading should execute in order unless it has a better heuristic.

### Lot Sizes
India lot sizes vary per instrument (25 for NIFTY, 15 for BANKNIFTY, 250 for RELIANCE, etc.). **income_desk now populates `TradeSpec.lot_size` from registry** — eTrading should use this, not hardcode 100.

### Currency
All amounts in TradeSpec are in **INR** for India instruments (`TradeSpec.currency = "INR"`). eTrading must display ₹, not $.

### European Exercise / Cash Settlement
- **Index options** (NIFTY, BANKNIFTY, FINNIFTY): Cash-settled, European exercise — NO early assignment risk
- **Stock options** (RELIANCE, TCS, etc.): Physical delivery, European exercise — no early assignment but physical delivery at expiry

`TradeSpec.settlement` and `TradeSpec.exercise_style` are now populated from registry.

### Market Hours
- **Open:** 9:15 IST
- **Close:** 3:30 PM IST
- **Force-close time:** 3:15 PM IST (for 0DTE/EOD positions)
- **Pre-market:** 9:00–9:15 IST

`TradeSpec.entry_window_timezone` is now `Asia/Kolkata` for India instruments.

### Expiry Conventions
| Instrument | Expiry Day | Frequency |
|------------|-----------|-----------|
| NIFTY | Thursday | Weekly + Monthly |
| BANKNIFTY | Wednesday (weekly), Thursday (monthly) | Weekly + Monthly |
| FINNIFTY | Tuesday | Weekly + Monthly |
| Stock options | Last Thursday of month | Monthly ONLY |

**No LEAPs.** India max DTE = 90 days for all instruments.

---

## 3. Strategy Availability (India)

### Available
- Iron condor (indices + stocks)
- Iron butterfly (indices + stocks)
- Credit/debit spreads (indices + stocks)
- Strangles/straddles (indices — high margin for stocks)
- 0DTE (NIFTY, BANKNIFTY, FINNIFTY only — weekly expiry)
- Ratio spreads (indices preferred)

### NOT Available
- **LEAPs** — Max 90 DTE, no long-dated options exist
- **PMCC** (Poor Man's Covered Call) — Requires LEAPs
- **Calendars/Diagonals for stocks** — Monthly-only expiry = insufficient term structure
- Calendars/Diagonals for indices — Possible (weekly + monthly) but limited

### Gate Settings (India-specific)
India gates should be MORE conservative than US:

| Gate | US Setting | India Recommended | Reason |
|------|-----------|-------------------|--------|
| Max single position % | 5% | 3% | Less liquidity, wider spreads |
| Min OI for entry | 500 | 1,000 | Ensure exit liquidity |
| Max spread width (bid-ask) | 5% of mid | 3% of mid | India spreads are wider |
| Min daily volume | 100 | 500 | Filter illiquid strikes |
| Max positions per desk | 10 | 5 | Legging risk multiplies |
| Legging risk penalty | N/A | -0.15 score | Reduce score for 4-leg structures |

### Legging Risk Score
eTrading should penalize multi-leg strategies in India:
- **2 legs** (vertical spread): No penalty
- **3 legs** (butterfly): -0.10 score penalty
- **4 legs** (iron condor/butterfly): -0.15 score penalty

This discourages complex structures where single-leg execution creates fill risk.

---

## 4. Dhan API Field Mapping

### Option Chain Response
Dhan's option_chain returns a dict keyed by strike:
```json
{
  "data": {
    "data": {
      "last_price": 22670,
      "oc": {
        "22500.000000": {
          "ce": {
            "top_bid_price": 250.0,
            "top_ask_price": 255.0,
            "last_price": 252.0,
            "implied_volatility": 18.5,
            "greeks": {"delta": 0.55, "gamma": 0.01, "theta": -5.0, "vega": 10.0},
            "volume": 5000,
            "oi": 100000,
            "security_id": 43952
          },
          "pe": { ... }
        }
      }
    }
  }
}
```

### Underlying Price
Use `ticker_data` with `IDX_I` segment for indices, `NSE_EQ` for stocks:
```python
client.ticker_data({"IDX_I": [13]})  # NIFTY
client.ticker_data({"NSE_EQ": [2885]})  # RELIANCE
```

### Known Dhan Quirks
- `option_chain` `last_price` may not match `IDX_I` ticker value — use ticker_data for underlying price
- `expiry_list` only returns monthly expiries for the option_chain endpoint — weekly options may need different handling
- Security IDs are **int**, not string — passing string causes 814 errors
- Rate limiting (805) is aggressive — add 500ms delay between data calls

---

## 5. Income_desk API Usage for India

### Regime Detection (works same as US)
```python
from income_desk import MarketAnalyzer, DataService

ma = MarketAnalyzer(data_service=DataService(), market="India")
r = ma.regime.detect("NIFTY")
# r.regime, r.confidence, r.trend_direction
```

### Ranking with Dhan Broker
```python
from income_desk.broker.dhan import connect_dhan

md, mm, acct, _ = connect_dhan()
ma = MarketAnalyzer(
    data_service=DataService(),
    market="India",
    market_data=md,
    market_metrics=mm,
    account_provider=acct,
)

result = ma.ranking.rank(["NIFTY", "BANKNIFTY", "TCS", "RELIANCE"])
```

### TradeSpec Fields for India
After ranking, `TradeSpec` now includes:
- `currency = "INR"`
- `lot_size = 25` (NIFTY), `15` (BANKNIFTY), etc.
- `entry_window_timezone = "Asia/Kolkata"`
- `entry_window_start / end` — IST times
- `settlement = "cash"` (indices) or `"physical"` (stocks)
- `exercise_style = "european"`

### Safety Reminder
`rank()` output is NOT safe to execute directly. eTrading MUST:
1. Call `filter_trades_with_portfolio()`
2. Call `evaluate_trade_gates()`
3. Apply India-specific gates (legging risk, OI minimums)
4. Execute legs individually with timeout/rollback

---

## 6. Watchlist Segments (India)

### Cash (Equity)
Regime-screened NIFTY 50 + sectoral leaders. No broker needed — yfinance provides OHLCV.

### Futures
NIFTY/BANKNIFTY/FINNIFTY futures for directional views. Requires Dhan for live data.

### Options (F&O)
- **Index weekly options** — NIFTY/BANKNIFTY/FINNIFTY (0DTE, income strategies)
- **Index monthly options** — All three indices (income + directional)
- **Stock monthly options** — Top 30 NIFTY 50 stocks by OI/liquidity

### Recommended Universe (₹50L portfolio)
| Segment | Tickers | Capital Allocation |
|---------|---------|-------------------|
| Index weekly (income) | NIFTY, BANKNIFTY | 40% (₹20L) |
| Index monthly | NIFTY, BANKNIFTY, FINNIFTY | 20% (₹10L) |
| Stock F&O | RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK | 20% (₹10L) |
| Cash reserve | — | 20% (₹10L) |

---

## 7. P0 Issues for India eTrading

1. **Single-leg execution engine** — Must build before any India trading
2. **Daily token refresh for Dhan** — Automate OAuth flow
3. **Legging risk gates** — Score penalty for multi-leg structures
4. **OI/volume gates** — India stocks have thin options markets
5. **Physical delivery risk** — Stock options near expiry need forced exit (3 days before)
6. **Margin management** — SPAN margins for India differ from Reg-T (US)
