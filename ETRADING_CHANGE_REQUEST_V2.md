# eTrading Change Request V2 for income_desk
# Date: 2026-03-14 | From: eTrading (Session 41)
# Status: OPEN — Review and implement

## Context

eTrading completed full MA integration (25/27 gaps, 185 tests). All Phase 1 CRs (CR-1 to CR-5) are done.
This CR covers the NEXT wave: multi-broker support, global markets, and enhanced intelligence.

See `SAAS.md` in eTrading for full cloud go-live plan.

---

## CR-6: Multi-Broker Provider Framework

### Problem
MA currently has broker implementations only for TastyTrade. eTrading needs to onboard:
- **Dhan** (India NSE/BSE — F&O, equities, commodities)
- **Zerodha** (India NSE/BSE — Kite Connect API)
- Future: Schwab (US), IBKR (Global)

### Ask
Implement the 4 ABCs for each new broker. eTrading will pass pre-authenticated sessions (same pattern as TastyTrade's `connect_from_sessions()`).

#### Dhan (`income_desk/broker/dhan/`)

```python
def connect_dhan(api_key: str, access_token: str) -> tuple[
    DhanMarketData, DhanMetrics, DhanAccount, DhanWatchlist
]:
    """Create providers from Dhan credentials."""

# Or SaaS pattern:
def connect_dhan_from_session(session) -> tuple[...]:
    """Create providers from pre-authenticated Dhan session."""
```

| ABC | Dhan API | Notes |
|-----|----------|-------|
| MarketDataProvider | Market Feed API, Options Chain (`/v2/optionchain`) | WebSocket for real-time. Lot sizes vary (NIFTY=25). |
| MarketMetricsProvider | Computed from chain (IV, OI, volume) | Dhan may not provide IV rank natively — compute from historical IV. |
| AccountProvider | Funds API (`/v2/fundlimit`) | Returns INR. Margin = SEBI peak margin rules. |
| WatchlistProvider | Dhan watchlists / portfolio holdings | Map to ticker list. |

#### Zerodha (`income_desk/broker/zerodha/`)

```python
def connect_zerodha(api_key: str, access_token: str) -> tuple[
    ZerodhaMarketData, ZerodhaMetrics, ZerodhaAccount, ZerodhaWatchlist
]:
    """Create providers from Kite Connect credentials."""
```

| ABC | Zerodha API | Notes |
|-----|-------------|-------|
| MarketDataProvider | Kite Ticker WebSocket, Instruments API | `GET /instruments` for master list. Ticker for streaming. |
| MarketMetricsProvider | Computed from options chain | Kite doesn't provide IV rank — compute from chain. |
| AccountProvider | Margins API (`GET /user/margins`) | Returns INR. Segment-wise margins. |
| WatchlistProvider | GTT orders / holdings as proxy | Or custom: store in MA config. |

### Key Differences from TastyTrade

| Aspect | TastyTrade (US) | Dhan / Zerodha (India) |
|--------|----------------|----------------------|
| Currency | USD | INR |
| Contract size | 100 (standard) | Varies: NIFTY=25, BANKNIFTY=15, stocks=lot-specific |
| Strike format | Decimal (580.00) | Integer (22500) |
| Expiry | Weekly Fri, Monthly 3rd Fri | Weekly Thu, Monthly last Thu |
| Settlement | Physical (assignment risk) | Cash-settled (no assignment) |
| Market hours | 9:30-16:00 ET | 9:15-15:30 IST |
| IV rank | Provided by broker | Must compute from historical IV |
| Options chain | NestedOptionChain (SDK) | REST API per expiry |

### What MA Must Handle
1. **Lot size on OptionQuote**: Add `lot_size: int = 100` field. India contracts have varying lot sizes.
2. **Currency on AccountBalance**: Already has `source` field. Add explicit `currency: str = "USD"`.
3. **Market hours on provider**: Each provider should expose `market_hours() -> tuple[time, time, timezone]`.
4. **IV rank computation**: When broker doesn't provide IV rank, compute from 1-year IV history: `rank = percentile(current_iv, iv_history)`.

---

## CR-7: Currency and Timezone Awareness

### Problem
All MA models assume USD and US Eastern time. For India (INR, IST) and future markets, MA must be currency and timezone aware.

### Ask

#### On AccountBalance:
```python
class AccountBalance(BaseModel):
    # ... existing fields ...
    currency: str = "USD"  # NEW: "USD", "INR", "EUR"
    timezone: str = "US/Eastern"  # NEW: "Asia/Kolkata", "Europe/London"
```

#### On MarketDataProvider ABC:
```python
class MarketDataProvider(ABC):
    @property
    def currency(self) -> str:
        """Currency of this market. 'USD', 'INR', etc."""
        return "USD"

    @property
    def timezone(self) -> str:
        """Timezone of this market. 'US/Eastern', 'Asia/Kolkata', etc."""
        return "US/Eastern"

    @property
    def market_hours(self) -> tuple[time, time]:
        """Market open and close times in local timezone."""
        return (time(9, 30), time(16, 0))

    @property
    def lot_size_default(self) -> int:
        """Default contract multiplier. 100 for US, varies for India."""
        return 100
```

#### On TradeSpec:
```python
class TradeSpec(BaseModel):
    # ... existing fields ...
    currency: str = "USD"  # NEW
    lot_size: int = 100    # NEW: per-contract multiplier
```

#### On OptionQuote:
```python
class OptionQuote(BaseModel):
    # ... existing fields ...
    lot_size: int = 100  # NEW: NIFTY=25, BANKNIFTY=15, US=100
```

### Impact on Existing Functions
- `position_size()`: Must use `lot_size` instead of hardcoded 100
- `compute_income_yield()`: Wing width × `lot_size` (not × 100)
- `compute_breakevens()`: Same math, different lot size
- `monitor_exit_conditions()`: P&L calculation uses lot_size
- `filter_trades_by_account()`: Buying power in local currency

---

## CR-8: India-Specific Strategy Assessors

### Problem
Current assessors are calibrated for US markets (SPY, QQQ, GLD). India F&O has different characteristics:
- NIFTY/BANKNIFTY are the primary underlyings (like SPY/QQQ but with different volatility)
- Weekly expiry on Thursday (not Friday)
- Straddle/strangle selling is popular (higher premiums)
- No LEAPs in India F&O (max ~3 months)
- Bank NIFTY has extreme intraday moves

### Ask

#### New assessor parameters for India:
```python
# In assessor configs:
INDIA_DEFAULTS = {
    'weekly_expiry_day': 'thursday',
    'max_dte': 90,  # No LEAPs
    'primary_underlyings': ['NIFTY', 'BANKNIFTY', 'FINNIFTY'],
    'lot_sizes': {'NIFTY': 25, 'BANKNIFTY': 15, 'FINNIFTY': 40},
    'typical_iv_range': (12, 35),  # NIFTY IV range
    'banknifty_iv_range': (15, 45),  # Higher vol
}
```

#### Modified assessors for India:
- **Iron Condor**: Same logic, but lot_size=25 (NIFTY). Wing width in points (e.g., 200 points = 200 × 25 = ₹5,000 risk).
- **Straddle/Strangle**: More common in India. Add `assess_straddle_india()` with India-specific IV thresholds.
- **Weekly 0DTE**: Thursday expiry, not Friday. Adjust `entry_window` accordingly.
- **No LEAPs**: LEAP assessor should return NO_GO for India tickers.

#### Market-aware assessor routing:
```python
# In ranking service:
def rank(tickers, market: str = "US", ...):
    """Market param selects assessor config."""
    if market == "INDIA":
        assessor_config = INDIA_DEFAULTS
        # Skip LEAP assessor
        # Adjust IV thresholds
        # Use Thursday expiry
```

---

## CR-9: Regime Detection for India Markets

### Problem
HMM regime detection is trained on US market data (SPY returns). India markets (NIFTY) have different volatility characteristics, correlation structure, and regime transitions.

### Ask
- **Separate HMM for India**: Train on NIFTY 50 daily returns. R1-R4 will have different state means.
- **Or**: Parametric: allow `RegimeConfig(market="INDIA")` with India-calibrated thresholds.
- **Cross-market regime**: When US is R4 (crisis), India often follows. Provide `regime.detect(ticker, reference_regime=us_regime)` for cross-market awareness.

### Minimum:
```python
# Regime detection should work for any ticker with sufficient history
regime = ma.regime.detect("NIFTY")  # Should work out of box
# DataService must fetch NIFTY data (yfinance supports ^NSEI)
```

---

## CR-10: Entry Window for India Markets

### Problem
`entry_window_start/end` is hardcoded for US market hours. India has different hours: 9:15 AM - 3:30 PM IST.

### Ask
Entry window should be timezone-aware:
```python
class TradeSpec(BaseModel):
    entry_window_start: time | None  # In market's local timezone
    entry_window_end: time | None
    entry_window_timezone: str = "US/Eastern"  # NEW

# For India:
# entry_window_start = time(9, 30)  # 9:30 AM IST
# entry_window_end = time(14, 0)    # 2:00 PM IST
# entry_window_timezone = "Asia/Kolkata"
```

For 0DTE-equivalent (India weekly expiry Thursday):
```python
# India weekly:
entry_window_start = time(9, 30)
entry_window_end = time(13, 30)  # Theta decay best before 1:30 PM
entry_window_timezone = "Asia/Kolkata"
```

---

## CR-11: Performance Analytics — Enhanced

### Problem
eTrading needs richer analytics from MA for the Desk Performance page and daily reports.

### Ask

#### Sharpe Ratio from outcomes:
```python
from income_desk import compute_sharpe

sharpe = compute_sharpe(outcomes: list[TradeOutcome], risk_free_rate: float = 0.05)
# Returns: SharpeResult(sharpe_ratio, annualized_return, annualized_vol, sortino_ratio)
```

#### Profit Factor:
```python
from income_desk import compute_profit_factor

pf = compute_profit_factor(outcomes)
# Returns: ProfitFactor(gross_wins, gross_losses, profit_factor, avg_win, avg_loss)
```

#### Drawdown Analysis:
```python
from income_desk import compute_drawdown

dd = compute_drawdown(outcomes)
# Returns: DrawdownResult(max_drawdown_pct, max_drawdown_dollars, drawdown_duration_days, current_drawdown)
```

#### Win Rate by Regime:
```python
from income_desk import compute_regime_performance

rp = compute_regime_performance(outcomes)
# Returns: dict[int, RegimePerf] with win_rate, avg_pnl, trade_count per R1-R4
```

These are pure functions — eTrading passes outcomes, MA returns analytics. Already partially in `compute_performance_report()` but need dedicated functions for specific metrics.

---

## CR-12: Data Service for India Markets

### Problem
MA's DataService uses yfinance for historical data. India tickers need special handling:
- NIFTY 50: `^NSEI` on yfinance
- BANKNIFTY: `^NSEBANK` on yfinance
- Individual stocks: `RELIANCE.NS`, `TCS.NS` (append `.NS`)

### Ask
DataService should handle India ticker mapping:
```python
class DataService:
    def _resolve_ticker(self, ticker: str, market: str = "US") -> str:
        """Map human ticker to yfinance ticker."""
        if market == "INDIA":
            INDIA_MAP = {
                'NIFTY': '^NSEI',
                'BANKNIFTY': '^NSEBANK',
                'FINNIFTY': 'NIFTY_FIN_SERVICE.NS',
            }
            if ticker in INDIA_MAP:
                return INDIA_MAP[ticker]
            if not ticker.endswith('.NS'):
                return f"{ticker}.NS"
        return ticker
```

Or simpler: accept both `NIFTY` and `^NSEI`, auto-detect.

---

---

## CR-13: Market Static Data Service

### Problem
Market mechanics (lot sizes, strike intervals, expiry conventions, settlement types, margin rules, trading hours, symbol formats) are currently not captured anywhere in MA. eTrading needs this data from MA — it should NOT hardcode market-specific rules.

### Ask
Build a `MarketRegistry` or `StaticDataService` in MA that provides market/exchange reference data.

See `MARKETS.md` in MA repo for the full reference data that needs to be codified.

```python
from income_desk import MarketRegistry

registry = MarketRegistry()

# Market info
market = registry.get_market("US")   # or "INDIA"
market.currency          # "USD"
market.timezone          # "US/Eastern"
market.open_time         # time(9, 30)
market.close_time        # time(16, 0)
market.settlement_days   # 1 (T+1)
market.expiry_day        # "friday" (US), "thursday" (India NIFTY)

# Instrument info
inst = registry.get_instrument("NIFTY", market="INDIA")
inst.lot_size            # 25
inst.strike_interval     # 50
inst.expiry_types        # ["weekly_thursday", "monthly_last_thursday"]
inst.settlement          # "cash"
inst.exercise_style      # "european"
inst.has_0dte            # True (weekly expiry day)
inst.has_leaps           # False
inst.max_dte             # 90

inst = registry.get_instrument("SPY", market="US")
inst.lot_size            # 100
inst.strike_interval     # 1
inst.expiry_types        # ["daily", "weekly_friday", "monthly", "quarterly", "leaps"]
inst.settlement          # "physical"
inst.exercise_style      # "american"
inst.has_0dte            # True
inst.has_leaps           # True
inst.max_dte             # 1095 (3 years)

# Strategy availability
registry.strategy_available("iron_condor", "NIFTY", "INDIA")   # True
registry.strategy_available("leaps", "NIFTY", "INDIA")         # False
registry.strategy_available("straddle", "BANKNIFTY", "INDIA")  # True (popular)

# Symbol mapping
registry.to_yfinance("NIFTY", "INDIA")    # "^NSEI"
registry.to_yfinance("RELIANCE", "INDIA") # "RELIANCE.NS"
registry.to_yfinance("SPY", "US")         # "SPY"

# Margin estimation
registry.estimate_margin("iron_condor", "NIFTY", wing_width=200, market="INDIA")
# Returns: MarginEstimate(span=28000, exposure=8000, total=36000, currency="INR")
```

### What Should Be in MarketRegistry (from MARKETS.md)
1. **Exchange metadata**: hours, timezone, currency, holidays, settlement
2. **Instrument specs**: lot sizes (all India F&O), strike intervals, expiry conventions
3. **Strategy availability matrix**: which strategies work in which market
4. **Symbol mapping**: human → yfinance → exchange format per market
5. **Exit rule defaults per market**: DTE exit 21 (US) vs 5 (India), force close times
6. **Margin estimation per market**: Reg-T rules (US), SEBI SPAN rules (India)

### Why This Belongs in MA
- MA's assessors need lot_size to compute risk/reward
- MA's `position_size()` needs lot_size for contract sizing
- MA's screening needs to know which strategies are available per market
- MA's DataService needs symbol mapping for historical data
- eTrading should call `registry.get_instrument()` — not hardcode lot sizes

---

## Summary

| CR | What | Priority | Status |
|----|------|----------|--------|
| **CR-6** | Dhan + Zerodha broker stubs (4 ABCs each) | HIGH | **DONE** (2026-03-14) |
| **CR-7** | Currency + timezone + lot_size on all models | HIGH | **DONE** (2026-03-14) |
| **CR-8** | India strategy assessor configs | MEDIUM | **DONE** (2026-03-14) |
| **CR-9** | Regime detection for NIFTY/BANKNIFTY | MEDIUM | **DONE** (2026-03-14) |
| **CR-10** | Timezone-aware entry windows | MEDIUM | **DONE** (2026-03-14) |
| **CR-11** | Sharpe, drawdown, regime perf analytics | HIGH | **DONE** (2026-03-14) |
| **CR-12** | DataService India ticker mapping | HIGH | **DONE** (2026-03-14) |
| **CR-13** | MarketRegistry static data service | CRITICAL | **DONE** (2026-03-14) |

### Recommended Order
1. **CR-7** (currency/timezone) + **CR-12** (India data) — foundation
2. **CR-6** (Dhan provider) — first India broker
3. **CR-11** (analytics) — Sharpe, drawdown, profit factor
4. **CR-8** + **CR-9** + **CR-10** — India-specific intelligence

---

## SaaS Requirements for MA

These are changes MA needs for the cloud/multi-tenant version of eTrading.

### CR-14: Per-User Provider Isolation

**Problem:** In SaaS, multiple users share the same MA library but each has their own broker connection. MA must ensure zero cross-contamination between users.

**Current state:** MA is already stateless — providers are injected. This is correct. But some services may cache data (OptionQuoteService has TTL cache). In multi-user, cache must be per-provider, not global.

**Ask:**
- Verify OptionQuoteService cache is per-instance (not class-level). If class-level → make per-instance.
- Verify no service stores state between calls that could leak across users.
- Document thread-safety: can two workers call the same MarketAnalyzer instance concurrently? Or must each worker create its own?

**Recommendation:** Each worker task creates its own MarketAnalyzer instance with user-specific providers. No sharing. Cache lives and dies with the instance.

### CR-15: Lightweight MarketAnalyzer Init

**Problem:** Creating a MarketAnalyzer instance is the first thing every task does. In SaaS with 100 users × 48 cycles/day = 4,800 init calls. Must be fast.

**Ask:**
- Profile `MarketAnalyzer.__init__()` — how long does it take?
- DataService init: does it download data on __init__? Or lazily?
- If any service does heavy init → defer to first call.

**Current:** Probably fine (DataService is lazy). Just need confirmation.

### CR-16: Broker Token Refresh

**Problem:** TastyTrade session tokens expire (24h?). Dhan/Zerodha access tokens expire daily. eTrading needs to know when to re-auth.

**Ask:**
- Each `connect_*()` should return token expiry time if available.
- Or: add `is_token_valid()` method on each provider that does a lightweight check.
- On token expiry: provider should raise `TokenExpiredError` (not generic exception).

```python
class TokenExpiredError(Exception):
    """Broker session token has expired. Re-authenticate."""
    pass

# In each provider method:
try:
    result = self._make_request(...)
except AuthenticationError:
    raise TokenExpiredError(f"{self.provider_name} token expired")
```

### CR-17: Rate Limit Awareness

**Problem:** India brokers have strict rate limits (Zerodha: 3 req/sec, Dhan: 25 req/sec). In SaaS with multiple users on same broker → must not exceed aggregate limits.

**Ask:**
- Each provider should expose `rate_limit: int` (requests per second).
- OptionQuoteService should respect this when batch-fetching.
- Consider: token bucket or simple sleep between requests.

```python
class MarketDataProvider(ABC):
    @property
    def rate_limit_per_second(self) -> int:
        """Max requests per second for this provider."""
        return 10  # default conservative

    @property
    def supports_batch(self) -> bool:
        """Can this provider batch multiple tickers in one call?"""
        return False
```

---

## CR-14: Benchmark Returns API

### Problem
eTrading has a new "Board Member" agent (Vidura) that needs to benchmark desk P&L against market indices. Currently no MA API provides simple benchmark returns for comparison.

### Ask
```python
from income_desk import compute_benchmark_returns

benchmarks = compute_benchmark_returns(
    tickers=['SPY', 'QQQ', '^NSEI', '^TNX'],
    days=30,
)
# Returns: dict[str, BenchmarkReturn]
# BenchmarkReturn: ticker, label, return_pct, start_price, end_price, period_days

# Alpha calculation:
from income_desk import compute_alpha
alpha = compute_alpha(
    portfolio_return_pct=5.2,
    benchmark_return_pct=3.1,  # SPY
    risk_free_rate=0.05,
)
# Returns: AlphaResult: alpha_pct, beating_benchmark, information_ratio
```

### Why This Belongs in MA
- MA owns all market data (yfinance, DataService)
- eTrading should NOT call yfinance directly
- Benchmark computation is market analysis, not portfolio management
- Keeps the boundary clean: MA computes, eTrading displays

### Priority
MEDIUM — Vidura works without this (shows desk P&L only). Full benchmark comparison needs this API.

---

## CR-15: Opportunity Scanner for Vidura

### Problem
Vidura needs to proactively identify opportunities the system is NOT currently trading — not just from the screening universe, but from the broader market. "Crude oil broke $90 — are we positioned? Gold ATH — do we have exposure?"

### What MR1-MR6 Already Provides
- MR1: Asset scorecards with signal_score for 22 tickers ✓
- MR2: Cross-asset correlations with divergence alerts ✓
- MR3: Macro regime (growth/deflation/stagflation) ✓
- MR4: Sentiment (fear/greed) ✓

### What's Still Needed
A **proactive opportunity scanner** that combines MR1-MR4 signals into actionable recommendations:

```python
from income_desk import scan_vidura_opportunities

opps = scan_vidura_opportunities(
    scorecards=scorecards,
    correlations=correlations,
    macro_regime=macro_regime,
    sentiment=sentiment,
    current_positions=['SPY', 'GLD'],  # What we already hold
)
# Returns: list[ViduraOpportunity]
# ViduraOpportunity:
#   ticker, signal_score, thesis, suggested_strategy,
#   timeframe, risk_level, macro_alignment
```

Example output:
- "XLE signal_score +0.8, crude above 90, energy sector momentum. Consider bull call spread."
- "TLT signal_score -0.7, rates rising. Short TLT via put spread or bear call."
- "GLD diverging from USD — unusual. Investigate gold breakout thesis."

### Priority
HIGH for Vidura — this is his core value proposition.

---

### eTrading Side (will implement in parallel)
- Broker connection UI per user
- Per-broker desk configuration in YAML
- Currency-aware P&L display
- Timezone-aware scheduling (India + US market hours)
- SEBI margin handling for India desks
