# Hedging & Currency — Design Plan

**Context:** User trades in both US (USD) and India (INR) markets. Needs currency conversion, cross-market P&L, and hedging capabilities.

**Principle:** MA is stateless. All hedging analysis is pure computation — eTrading stores positions, MA computes hedge recommendations. Same-ticker hedging only (per trading philosophy).

---

## Implementation Scope

### Building in MA (this session):

| # | What | File | APIs |
|---|------|------|------|
| H1 | Currency conversion + portfolio exposure | `currency.py` | `convert_amount()`, `compute_portfolio_exposure()`, `compute_currency_pnl()` |
| H2 | Same-ticker hedge assessment (regime-aware) | `hedging.py` | `assess_hedge()` — protective put, collar, delta hedge, roll-down |
| H3 | Currency hedge assessment | `hedging.py` | `assess_currency_exposure()` — FX risk %, recommendation |
| H4 | Cross-market P&L decomposition | `currency.py` | `decompose_pnl()` — trading P&L vs FX P&L |
| H5 | CLI commands | `cli/interactive.py` | `hedge`, `currency`, `exposure` |
| CR14 | SaaS: cache isolation | `service/option_quotes.py` | Verify per-instance, document thread safety |
| CR15 | SaaS: lightweight init | `service/analyzer.py` | Confirm lazy, document |
| CR16 | SaaS: token expiry | `broker/base.py` | `TokenExpiredError`, `is_token_valid()` |
| CR17 | SaaS: rate limits | `broker/base.py` | `rate_limit_per_second`, `supports_batch` |

### NOT building (eTrading's job):
- Live FX rate fetching (eTrading passes rates to MA)
- FX futures/options execution
- Cross-ticker portfolio hedging (violates same-ticker rule)
- Beta-weighted index hedging

---

## What to Build

### 1. Currency Conversion Service

Pure functions for converting between currencies. No live FX rates (that's eTrading's job) — MA accepts exchange rates as input.

```python
# market_analyzer/currency.py

class CurrencyPair(BaseModel):
    base: str       # "USD"
    quote: str      # "INR"
    rate: float     # 1 USD = 83.5 INR
    as_of: date

class PortfolioExposure(BaseModel):
    """Cross-market portfolio exposure in a common currency."""
    base_currency: str          # "USD" — reporting currency
    exposures: dict[str, float] # {"USD": 45000, "INR": 3750000}
    converted: dict[str, float] # {"USD": 45000, "INR": 44910}  (INR→USD)
    total_exposure: float       # 89910 USD
    currency_risk_pct: float    # % of portfolio in non-base currency

def convert_amount(amount: float, from_currency: str, to_currency: str,
                   rates: dict[str, CurrencyPair]) -> float:
    """Convert amount between currencies."""

def compute_portfolio_exposure(
    positions: list[PositionExposure],  # ticker, notional, currency
    rates: dict[str, CurrencyPair],
    base_currency: str = "USD",
) -> PortfolioExposure:
    """Aggregate cross-market portfolio in base currency."""

def compute_currency_pnl(
    entry_rate: float,      # USD/INR at trade entry
    current_rate: float,    # USD/INR now
    position_inr: float,   # Position value in INR
) -> CurrencyPnL:
    """Compute P&L impact from currency movement."""
```

### 2. Hedging Assessment Service

**Current CLAUDE.md rule: "Hedging is same-ticker only."** This means no beta-weighted index hedging. But we CAN provide:

#### What MA CAN do (same-ticker hedging):
- **Protective puts** for long equity positions
- **Collar** (long stock + short call + long put) sizing
- **Hedge ratio** computation (delta-neutral hedge for existing position)
- **Roll-down** hedge (replace expiring hedge with cheaper one)

#### What MA should NOT do (per trading philosophy):
- Cross-ticker hedging (e.g., buy SPY puts to hedge AAPL calls)
- Beta-weighted portfolio hedging
- Correlation-based hedge selection

#### Currency hedging (NEW — user has cross-market exposure):
- **Natural hedge assessment**: "Your INR income offsets INR expenses — no hedge needed"
- **Currency impact on P&L**: "Your NIFTY IC made ₹5,000 but INR depreciated 2% → USD P&L reduced"
- **Hedge sizing**: "To hedge ₹500K India exposure, you'd need X USD/INR futures"

```python
# market_analyzer/hedging.py

class HedgeType(StrEnum):
    PROTECTIVE_PUT = "protective_put"
    COLLAR = "collar"
    DELTA_HEDGE = "delta_hedge"
    ROLL_DOWN = "roll_down"
    NO_HEDGE = "no_hedge"

class HedgeRecommendation(BaseModel):
    hedge_type: HedgeType
    ticker: str
    rationale: str
    legs: list[LegSpec]        # What to trade
    cost_estimate: float | None # Premium for hedge (None if no broker)
    protection_level: float    # Price level protected to
    max_loss_with_hedge: float
    max_loss_without_hedge: float
    hedge_efficiency: float    # Cost of hedge / risk reduction

class CurrencyHedgeAssessment(BaseModel):
    base_currency: str
    foreign_currency: str
    foreign_exposure: float
    exchange_rate: float
    currency_risk_pct: float   # How much P&L swings per 1% FX move
    recommendation: str        # "natural hedge sufficient" / "consider hedging"
    hedge_cost_estimate: str   # "~0.5% per quarter via futures"

def assess_hedge(
    ticker: str,
    position_type: str,       # "long_equity", "short_put", "iron_condor"
    position_value: float,
    regime: RegimeResult,
    technicals: TechnicalSnapshot,
    vol_surface: VolatilitySurface | None = None,
) -> HedgeRecommendation:
    """Recommend same-ticker hedge for an existing position."""

def assess_currency_exposure(
    positions: list[PositionExposure],
    rates: dict[str, CurrencyPair],
    base_currency: str = "USD",
) -> CurrencyHedgeAssessment:
    """Assess currency risk across multi-market portfolio."""
```

### 3. Hedging Decision Tree (Same-Ticker)

```
Position: Long equity (RELIANCE at ₹1,380)
  R1 (Low-Vol MR): NO_HEDGE — theta decay on protective puts wastes money in range
  R2 (High-Vol MR): COLLAR — sell OTM call, buy OTM put (zero-cost hedge in high IV)
  R3 (Low-Vol Trend): NO_HEDGE if trend is favorable, PROTECTIVE_PUT if counter-trend
  R4 (High-Vol Trend): PROTECTIVE_PUT — buy ATM put immediately

Position: Short iron condor (NIFTY)
  R1: NO_HEDGE — IC is already defined risk
  R2: NO_HEDGE — IC wings are the hedge
  R3: DELTA_HEDGE — add directional leg if trend threatens short strike
  R4: CLOSE — don't hedge, just close (IC in R4 = wrong trade)

Position: Short straddle (BANKNIFTY)
  R1: NO_HEDGE — MR regime supports straddle
  R2: ADD_WING — convert to iron butterfly (define risk)
  R3: DELTA_HEDGE — add directional spread on trending side
  R4: CLOSE — undefined risk in R4 = immediate exit
```

### 4. Currency P&L Tracking

```python
class CrossMarketPnL(BaseModel):
    """P&L breakdown showing trading P&L vs currency P&L."""
    ticker: str
    market: str
    trading_pnl_local: float     # P&L in local currency (INR or USD)
    trading_pnl_base: float      # P&L converted to base currency
    currency_pnl: float          # P&L from FX movement alone
    total_pnl_base: float        # trading_pnl_base + currency_pnl
    fx_rate_at_entry: float
    fx_rate_current: float
    fx_impact_pct: float         # How much FX moved against you
```

---

## What NOT to Build (eTrading's job)

- Live FX rate fetching (eTrading gets from broker/API, passes to MA)
- FX futures/options order execution
- Portfolio-level cross-ticker hedging (violates same-ticker rule)
- Currency hedging execution (MA recommends, eTrading executes)

---

## Implementation Order

1. **Currency conversion** — `currency.py` with CurrencyPair, convert, portfolio exposure
2. **Same-ticker hedge assessment** — `hedging.py` with regime-aware recommendations
3. **Currency P&L decomposition** — trade P&L vs FX P&L breakdown
4. **CLI commands** — `hedge TICKER`, `currency`, `exposure`

---

## Also: CR-14 to CR-17 (SaaS requirements)

While building hedging, also implement the pending SaaS CRs:
- CR-14: Verify cache isolation (per-instance, not class-level)
- CR-15: Confirm lazy init (no heavy work in __init__)
- CR-16: TokenExpiredError + is_token_valid() on providers
- CR-17: rate_limit_per_second + supports_batch on MarketDataProvider
