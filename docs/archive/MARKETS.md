# Market & Exchange Reference — Static Data
# Last Updated: 2026-03-14
# Supported: USA (TastyTrade) | India (Zerodha, Dhan)

---

## EXCHANGES

| Exchange | Country | Currency | Timezone | Open | Close | Lunch Break | Settlement |
|----------|---------|----------|----------|------|-------|-------------|------------|
| **CBOE / NYSE / NASDAQ** | USA | USD | US/Eastern | 9:30 AM | 4:00 PM | None | T+1 |
| **NSE** (National Stock Exchange) | India | INR | Asia/Kolkata | 9:15 AM | 3:30 PM | None | T+1 |
| **BSE** (Bombay Stock Exchange) | India | INR | Asia/Kolkata | 9:15 AM | 3:30 PM | None | T+1 |

### Pre/Post Market

| Exchange | Pre-Market | Post-Market | After-Hours Trading |
|----------|-----------|-------------|---------------------|
| US (NYSE/NASDAQ) | 4:00-9:30 AM ET | 4:00-8:00 PM ET | Options: NO |
| NSE | 9:00-9:15 AM IST (pre-open) | 3:30-3:40 PM IST (closing) | F&O: NO |
| BSE | 9:00-9:15 AM IST | 3:30-3:40 PM IST | NO |

### Trading Holidays

| Market | Holiday Calendar | Key Closures |
|--------|-----------------|--------------|
| US | NYSE holiday calendar | MLK, Presidents Day, Good Friday, Memorial, Independence, Labor, Thanksgiving, Christmas |
| India | NSE holiday calendar | Republic Day (Jan 26), Holi, Good Friday, Independence (Aug 15), Gandhi Jayanti (Oct 2), Diwali, Christmas |

---

## OPTIONS — Product Specifications

### US Options (CBOE/OCC)

| Attribute | Value |
|-----------|-------|
| Contract multiplier | **100 shares per contract** (standard) |
| Strike intervals | $0.50 (< $30), $1 (< $200), $2.50 ($200+), $5 (indexes) |
| Expiry types | Weekly (Friday), Monthly (3rd Friday), Quarterly, LEAPs (1-3 years) |
| Expiry day | **Friday** (or Thursday before Good Friday) |
| 0DTE availability | SPY, QQQ, IWM, SPX — daily expirations M-F |
| Settlement | **Physical** (equity options: shares delivered on assignment) |
| Settlement | **Cash** (index options: SPX, NDX, RUT) |
| Exercise style | **American** (equity options: can exercise any time) |
| Exercise style | **European** (index options: exercise at expiry only) |
| Assignment risk | YES for American options. ITM short legs can be assigned. |
| Margin | Reg-T (standard) or Portfolio Margin (> $125K) |
| Option symbol | OCC format: `SPY   260320P00580000` |
| Streamer symbol | DXLink format: `.SPY260320P580` |
| Minimum price | $0.01 (penny increments for liquid names) |
| Position limits | Varies by underlying (typically 250K-500K contracts) |

### India Options — NSE F&O

| Attribute | NIFTY 50 | BANKNIFTY | FINNIFTY | Stock Options |
|-----------|----------|-----------|----------|---------------|
| Contract multiplier (lot size) | **25** | **15** | **40** | **Varies** (see table below) |
| Strike intervals | 50 points | 100 points | 50 points | Varies by price |
| Expiry types | Weekly (Thu), Monthly (last Thu) | Weekly (Wed), Monthly (last Thu) | Weekly (Tue), Monthly (last Thu) | Monthly only |
| Expiry day | **Thursday** | **Wednesday** | **Tuesday** | **Last Thursday of month** |
| 0DTE equivalent | Weekly expiry day | Weekly expiry day | Weekly expiry day | N/A (monthly only) |
| Settlement | **Cash settled** (no share delivery) | **Cash settled** | **Cash settled** | **Physical** (since Oct 2019) |
| Exercise style | **European** (exercise at expiry only) | **European** | **European** | **European** |
| Assignment risk | **NO** (European + cash settled) | **NO** | **NO** | YES (physical, but European so only at expiry) |
| Margin | SEBI SPAN + Exposure margin | Same | Same | Same |
| Option symbol (NSE) | `NIFTY26MAR22500CE` | `BANKNIFTY26MAR48000CE` | `FINNIFTY26MAR22000CE` | `RELIANCE26MAR2800CE` |
| Minimum price | ₹0.05 | ₹0.05 | ₹0.05 | ₹0.05 |
| Max orders/second | 20 (per user) | 20 | 20 | 20 |

### India Stock Options — Lot Sizes (Top 20)

| Stock | Symbol | Lot Size | Typical Strike Interval |
|-------|--------|----------|------------------------|
| Reliance | RELIANCE | 250 | ₹20 |
| TCS | TCS | 150 | ₹25 |
| Infosys | INFY | 300 | ₹25 |
| HDFC Bank | HDFCBANK | 550 | ₹10 |
| ICICI Bank | ICICIBANK | 700 | ₹10 |
| SBI | SBIN | 1500 | ₹5 |
| Bharti Airtel | BHARTIARTL | 475 | ₹10 |
| ITC | ITC | 1600 | ₹5 |
| Bajaj Finance | BAJFINANCE | 125 | ₹50 |
| Tata Motors | TATAMOTORS | 1125 | ₹5 |
| HUL | HINDUNILVR | 300 | ₹10 |
| L&T | LT | 150 | ₹25 |
| Axis Bank | AXISBANK | 600 | ₹10 |
| Kotak Bank | KOTAKBANK | 400 | ₹10 |
| Maruti | MARUTI | 100 | ₹50 |
| Asian Paints | ASIANPAINT | 300 | ₹10 |
| Titan | TITAN | 175 | ₹25 |
| Sun Pharma | SUNPHARMA | 350 | ₹10 |
| HDFC Life | HDFCLIFE | 1100 | ₹5 |
| Wipro | WIPRO | 1500 | ₹5 |

*Lot sizes change periodically. NSE publishes updates quarterly.*

---

## MARGIN SYSTEMS

### US — Reg-T Margin

| Strategy | Margin Requirement |
|----------|-------------------|
| Long option (buy) | Full premium paid |
| Short naked put | 20% of underlying + premium - OTM amount (min $250/contract) |
| Short naked call | 20% of underlying + premium - OTM amount (min $250/contract) |
| Credit spread (defined risk) | Width of spread × 100 |
| Iron condor (defined risk) | Max of put spread width or call spread width × 100 |
| Calendar spread | Full debit paid |
| Covered call | Stock cost - call premium received |

### India — SEBI SPAN + Exposure

| Component | Description |
|-----------|-------------|
| **SPAN margin** | Calculated by NSE SPAN system. Based on VaR of position. |
| **Exposure margin** | Additional 2-3% of contract value. Safety buffer. |
| **Peak margin** | Since Dec 2021: 80% of peak margin during the day. Checked 4 times/day. |
| **Calendar spread margin** | Reduced margin for spread positions (offset recognized). |
| **Delivery margin** | Physical delivery stocks: 50% of contract value from T-4 days to expiry. |

| Strategy (India) | Approximate Margin |
|----------|-------------------|
| Naked short option | SPAN + Exposure (~15-20% of contract value) |
| Credit spread | Reduced: SPAN on spread (offset recognized) |
| Iron condor | Reduced: max leg SPAN (offset recognized) |
| Long option (buy) | Full premium only |
| Straddle/strangle (short) | Higher of put/call SPAN + other leg premium |

---

## BROKER SPECIFICATIONS

### TastyTrade (USA)

| Attribute | Value |
|-----------|-------|
| Markets | US equities + options |
| Auth | Username + password → session token |
| SDK | `tastytrade` Python package |
| Streaming | DXLink (DXFeed protocol) |
| Options chain | `NestedOptionChain.get()` via SDK |
| Order types | Limit, Market, Stop, Stop-Limit |
| Fees | $0 equity, $1.00/contract options (capped $10/leg) |
| Paper trading | Yes (separate paper account) |
| API rate limit | No published limit (reasonable use) |
| Symbol format | DXLink: `.SPY260320P580` |
| Watchlists | Public + private, API accessible |
| Account types | Individual, IRA, Joint |
| Min account | $0 (no minimum) |
| Portfolio margin | Available (> $125K NLV) |

### Zerodha / Kite Connect (India)

| Attribute | Value |
|-----------|-------|
| Markets | NSE, BSE (equities + F&O + commodities + currency) |
| Auth | Kite Connect API key + OAuth2 redirect → access token (daily) |
| SDK | `kiteconnect` Python package |
| Streaming | Kite Ticker (WebSocket, binary protocol) |
| Options chain | `GET /instruments` (master list) + filter by expiry |
| Order types | Limit, Market, SL, SL-M |
| Fees | ₹20/order (F&O), ₹0 (equity delivery) |
| Paper trading | No native paper mode |
| API rate limit | 3 requests/sec, 200 orders/min |
| Symbol format | Exchange token (numeric) or tradingsymbol (`NIFTY26MAR22500CE`) |
| Watchlists | Via GTT / API |
| Account types | Individual (Demat + trading) |
| Min account | ₹0 (no minimum) |
| Things to watch | Access token expires daily (must re-auth each morning) |

### Dhan (India)

| Attribute | Value |
|-----------|-------|
| Markets | NSE, BSE (equities + F&O + commodities + currency) |
| Auth | Client ID + API access token (valid for 1 day, refresh via login) |
| SDK | `dhanhq` Python package |
| Streaming | Dhan Market Feed (WebSocket) |
| Options chain | `GET /v2/optionchain/{underlying}` |
| Order types | Limit, Market, SL, SL-M, BO (bracket), CO (cover) |
| Fees | ₹20/order (F&O), ₹0 (equity delivery) |
| Paper trading | No native paper mode |
| API rate limit | 25 requests/sec |
| Symbol format | Security ID (numeric) or exchange symbol |
| Watchlists | Dhan watchlist API |
| Account types | Individual (Demat + trading) |
| Min account | ₹0 |
| Things to watch | Access token daily refresh. Bracket/cover orders have auto-SL. |

---

## SYMBOL MAPPING

### US Symbols
```
Human ticker:  SPY
yfinance:      SPY
DXLink:        .SPY260320P580
OCC:           SPY   260320P00580000
TastyTrade:    SPY (equity), .SPY260320P580 (option)
```

### India Symbols
```
Human ticker:  NIFTY
yfinance:      ^NSEI
NSE code:      NIFTY 50
NSE symbol:    NIFTY
Option:        NIFTY26MAR22500CE
Zerodha:       256265 (instrument token) or NIFTY26MAR22500CE (tradingsymbol)
Dhan:          13 (security ID for NIFTY index)

Human ticker:  RELIANCE
yfinance:      RELIANCE.NS
NSE symbol:    RELIANCE
Option:        RELIANCE26MAR2800CE
Zerodha:       738561 (instrument token)
Dhan:          2885 (security ID)
```

### Ticker Resolution Map (for DataService)

| Human | yfinance | NSE Symbol | Type |
|-------|----------|------------|------|
| NIFTY | ^NSEI | NIFTY 50 | Index |
| BANKNIFTY | ^NSEBANK | NIFTY BANK | Index |
| FINNIFTY | NIFTY_FIN_SERVICE.NS | NIFTY FIN SERVICE | Index |
| RELIANCE | RELIANCE.NS | RELIANCE | Equity |
| TCS | TCS.NS | TCS | Equity |
| INFY | INFY.NS | INFOSYS | Equity |
| HDFCBANK | HDFCBANK.NS | HDFCBANK | Equity |
| ICICIBANK | ICICIBANK.NS | ICICIBANK | Equity |
| SBIN | SBIN.NS | SBIN | Equity |
| SPY | SPY | — | US ETF |
| QQQ | QQQ | — | US ETF |
| IWM | IWM | — | US ETF |

---

## STRATEGY AVAILABILITY BY MARKET

| Strategy | US (TastyTrade) | India (NSE F&O) | Notes |
|----------|----------------|-----------------|-------|
| Iron Condor | YES | YES | India: cash-settled, no assignment risk. Lower margin. |
| Iron Butterfly | YES | YES | Same structure, different lot sizes. |
| Credit Spread (vertical) | YES | YES | India: offset margin recognized by SEBI SPAN. |
| Debit Spread | YES | YES | |
| Calendar Spread | YES | LIMITED | India: max 3-month expiry. No LEAPs calendar. |
| Diagonal Spread | YES | LIMITED | Same limitation as calendar. |
| Straddle (short) | YES | YES (popular) | India: very popular strategy. Higher premiums. |
| Strangle (short) | YES | YES (popular) | Same — common Indian F&O strategy. |
| Covered Call | YES | YES (stock options) | India: physical delivery stock options only. |
| LEAPs | YES | NO | India max expiry ~3 months for F&O. |
| 0DTE | YES (SPY/QQQ daily) | YES (weekly expiry day) | India: Thursday for NIFTY, Wednesday for BANKNIFTY. |
| Ratio Spread | YES | YES | India: higher margin for naked legs. |
| PMCC (Poor Man's Covered Call) | YES | NO | Requires LEAPs. Not available in India. |
| Jade Lizard | YES | YES | India: margin advantage from cash-settled. |
| Earnings Play | YES | LIMITED | India: quarterly results. Less predictable timing. |

---

## EXIT RULE DIFFERENCES BY MARKET

| Rule | US | India |
|------|-----|-------|
| Profit target (credit) | 50% of credit | 50% of credit (same logic) |
| Stop loss (credit) | 2x credit | 2x credit (same logic) |
| DTE exit | Close at 21 DTE | Close at 5 DTE (shorter cycles) |
| 0DTE force close | 3:00 PM ET | 3:00 PM IST (30 min before close) |
| Expiry handling | Let expire or close before 3:30 PM | Auto-settled at close (cash) |
| Assignment risk | YES — must manage ITM short legs | NO for index options (cash-settled) |
| Overnight gap risk | Moderate (overnight trading exists) | Higher (no overnight trading, gap open) |

---

## KEY DIFFERENCES SUMMARY

| Aspect | USA | India |
|--------|-----|-------|
| Currency | USD ($) | INR (₹) |
| Timezone | US/Eastern (ET) | Asia/Kolkata (IST) |
| Contract size | 100 (uniform) | Varies (25-1600 per stock) |
| Expiry day | Friday | Thursday (NIFTY), Wednesday (BANKNIFTY), Tuesday (FINNIFTY) |
| Settlement | Physical (equity), Cash (index) | Cash (index), Physical (stock since 2019) |
| Exercise | American (equity), European (index) | European (all F&O) |
| Assignment risk | High (American exercise) | Low (European, cash-settled indexes) |
| LEAPs available | Yes (1-3 years) | No (max ~3 months) |
| IV rank from broker | Yes (TastyTrade provides) | No (must compute from historical) |
| Broker fees | $1/contract (capped $10/leg) | ₹20/order (flat) |
| Margin system | Reg-T / Portfolio Margin | SEBI SPAN + Exposure + Peak |
| Market hours | 6.5 hours (9:30-4:00 ET) | 6.25 hours (9:15-3:30 IST) |
| Gap between open/close | 17.5 hours | 17.75 hours |
| Paper trading | Yes (TastyTrade paper) | No (simulate with WhatIf) |
