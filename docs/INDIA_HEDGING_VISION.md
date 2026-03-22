# India Hedging Suite — Comprehensive Vision

> Building the most complete hedging intelligence for Indian retail traders.
> Nobody in India is solving this systematically. We will.

---

## The Problem

India has the world's largest options market by volume (NSE). But the hedging infrastructure is broken for retail:

| Reality | Impact |
|---------|--------|
| Only ~180 stocks have F&O out of ~5000 | 96% of stocks cannot be directly hedged |
| Of ~180 F&O stocks, maybe 30 have liquid options | Even F&O stocks may have wide spreads |
| Lot sizes are large (NIFTY=25, BANKNIFTY=15) | A ₹10L portfolio can barely afford 1 lot |
| No sector ETF options | Can't buy "banking sector put" |
| European exercise on index options | No early exercise flexibility |
| SEBI peak margin rules | Hedging is more expensive than it should be |
| Weekly expiry = cheap but expires fast | Must roll hedges weekly |

**Result:** Indian retail traders either don't hedge (90%) or hedge incorrectly (buy expensive NIFTY puts on a midcap portfolio).

---

## The Three Hedging Tiers

### Tier 1: Direct Hedging (Liquid Options Available)

**~30 stocks** with liquid options: RELIANCE, HDFC BANK, INFY, TCS, ICICI, SBI, BAJAJ FINANCE, TATA MOTORS, etc.

**Strategies available:**
- Protective put (buy OTM put)
- Collar (buy put + sell call = zero/low cost)
- Put spread (buy put + sell lower put = defined cost)
- Covered call (sell OTM call for income while holding)

**APIs needed:**
```python
def build_protective_put(ticker, shares, current_price, regime_id, atr, dte) -> HedgeResult
def build_collar(ticker, shares, current_price, cost_basis, regime_id, atr, dte) -> HedgeResult
def build_put_spread_hedge(ticker, shares, current_price, budget, dte) -> HedgeResult
```

### Tier 2: Synthetic Hedging (Futures Available, Options Illiquid)

**~150 stocks** with futures but illiquid/no options.

**Key insight:** You can BUILD options from futures:

| Synthetic Position | Construction | Equivalent To |
|---|---|---|
| Synthetic long put | Short futures + Long call | Protective put |
| Synthetic long call | Long futures + Long put | Bullish exposure |
| Synthetic covered call | Long stock + Short futures (partial) | Income on held stock |
| Synthetic collar | Long stock + Short futures + Long OTM call (on index) | Zero-cost protection |
| Delta hedge | Long stock + Short futures (hedge ratio × lots) | Reduce downside exposure |

**Example: Hedging TATA STEEL (has futures, illiquid options)**

```
Position: 500 shares TATA STEEL at ₹150 (₹75,000 value)
Problem: Options exist but spreads are 5-10% wide. Unusable.
Solution: Sell TATA STEEL futures

  Lot size: 500 shares (= exactly your position!)
  Futures price: ₹151 (slight premium to spot)
  Action: Sell 1 lot TATA STEEL futures

Result:
  Stock goes to ₹130: Stock loses ₹10,000. Futures gains ₹10,500. Net: +₹500
  Stock goes to ₹170: Stock gains ₹10,000. Futures loses ₹9,500. Net: +₹500
  You're fully hedged. Cost = futures premium (~₹500/month).
```

**Partial hedge (stay 50% exposed):**
```
Position: 1000 shares TATA STEEL
Action: Sell 1 lot (500 shares) futures
Result: 50% hedged, 50% exposed to upside
```

**APIs needed:**
```python
def build_futures_hedge(ticker, shares, current_price, lot_size, hedge_ratio, regime_id) -> FuturesHedgeResult
def build_synthetic_put(ticker, shares, futures_price, call_strike, dte) -> SyntheticOptionResult
def build_synthetic_collar(ticker, shares, futures_price, call_strike, dte) -> SyntheticOptionResult
def compute_futures_hedge_ratio(ticker, target_delta, shares, lot_size) -> HedgeRatioResult
```

### Tier 3: Proxy/Index Hedging (No F&O at All)

**~4800 stocks** with no futures or options.

**Strategy:** Hedge with correlated index proxy.

| Stock Sector | Proxy Index | Typical Beta |
|---|---|---|
| IT services (TCS, Infosys, Wipro, HCLTech) | NIFTY IT / NIFTY | 0.7-0.9 |
| Banking (HDFC, Kotak, Axis, IndusInd) | BANKNIFTY | 0.8-1.2 |
| Auto (Maruti, M&M, Bajaj Auto, Hero) | NIFTY Auto / NIFTY | 0.8-1.0 |
| Pharma (Sun, Dr Reddy, Cipla, Lupin) | NIFTY Pharma / NIFTY | 0.5-0.7 |
| FMCG (HUL, ITC, Nestlé, Dabur) | NIFTY FMCG / NIFTY | 0.4-0.6 |
| Metals (Tata Steel, JSW, Hindalco) | NIFTY Metal / NIFTY | 1.0-1.4 |
| Realty (DLF, Godrej, Oberoi) | NIFTY Realty / NIFTY | 1.2-1.5 |
| Energy (ONGC, BPCL, IOC, NTPC) | NIFTY Energy / NIFTY | 0.6-0.8 |

**Example: Hedging a ₹20L midcap basket (no F&O)**

```
Portfolio:
  ₹3L in Dmart (Avenue Supermarts) — Retail/FMCG — beta 0.7 to NIFTY
  ₹4L in PI Industries — Agri/Chemical — beta 0.6 to NIFTY
  ₹5L in Tube Investments — Auto ancillary — beta 0.9 to NIFTY
  ₹4L in Persistent Systems — IT midcap — beta 0.8 to NIFTY
  ₹4L in Aarti Industries — Chemical — beta 0.7 to NIFTY
  Total: ₹20L, portfolio beta to NIFTY = 0.74

Hedge:
  Portfolio notional × beta = ₹20L × 0.74 = ₹14.8L to hedge
  NIFTY lot value = 25 × ₹24,500 = ₹6.125L per lot
  Lots needed = ₹14.8L / ₹6.125L = 2.4 → 2 lots

  Action: Buy 2 lots NIFTY OTM puts (3% OTM, weekly expiry)
  Cost: ~₹3,000-5,000/week (0.15-0.25% of portfolio)

  Or: Sell 2 lots NIFTY futures (zero cost hedge)
```

**APIs needed:**
```python
def analyze_fno_coverage(tickers, values) -> FnOCoverageResult
def compute_portfolio_beta(tickers, values, index="NIFTY") -> PortfolioBetaResult
def recommend_proxy_hedge(tickers, values, regime_id) -> ProxyHedgeResult
def build_index_hedge(portfolio_value, portfolio_beta, index, regime_id, dte) -> IndexHedgeResult
```

---

## Portfolio-Level Hedging API

The portfolio-level API orchestrates all three tiers:

```python
def analyze_portfolio_hedge(
    positions: list[PortfolioPosition],
    account_nlv: float,
    regime: dict[str, int],       # Per-ticker regime
    target_hedge_pct: float = 0.80,  # Hedge 80% of portfolio delta
    max_hedge_cost_pct: float = 0.02,  # Max 2% of portfolio/month
    market: str = "India",
) -> PortfolioHedgeAnalysis:
    """Master hedging function — analyzes entire portfolio.

    1. Classifies each position: Tier 1 (direct), Tier 2 (futures), Tier 3 (proxy)
    2. Builds optimal hedge for each position
    3. Aggregates to portfolio level
    4. Checks cost budget
    5. Returns concrete TradeSpecs for every hedge leg
    """
```

**Return model:**
```python
class PortfolioHedgeAnalysis(BaseModel):
    # Coverage analysis
    tier1_positions: list[dict]      # Direct hedge available
    tier2_positions: list[dict]      # Futures hedge available
    tier3_positions: list[dict]      # Proxy hedge only
    unhedgeable: list[dict]          # Nothing available (very rare)
    coverage_pct: float              # % of portfolio value that CAN be hedged

    # Recommended hedges
    hedge_trades: list[TradeSpec]     # Concrete orders to place
    total_hedge_cost: float          # Monthly cost estimate
    hedge_cost_pct: float            # As % of portfolio

    # Portfolio risk before/after
    portfolio_delta_before: float
    portfolio_delta_after: float
    portfolio_beta_before: float
    portfolio_beta_after: float
    max_loss_before: float           # Unhedged worst case (5% market drop)
    max_loss_after: float            # Hedged worst case

    # Per-position detail
    position_hedges: list[PositionHedge]

    # Summary
    regime_context: str
    rationale: str
    warnings: list[str]


class PositionHedge(BaseModel):
    ticker: str
    position_value: float
    hedge_tier: str                  # "direct", "futures_synthetic", "proxy_index"
    hedge_instrument: str            # "RELIANCE PE", "TATA STEEL FUT", "NIFTY PE"
    hedge_trade_spec: TradeSpec | None  # Concrete order
    hedge_cost: float
    delta_reduction: float
    rationale: str
```

---

## India F&O Universe Database

We need a comprehensive database of what's available:

```python
class IndiaFnOInstrument(BaseModel):
    ticker: str
    name: str
    sector: str                      # IT, Banking, Auto, Pharma, etc.
    market_cap: str                  # Large, Mid, Small

    # Options availability
    has_options: bool
    option_lot_size: int
    option_strike_interval: float
    option_expiry_type: str          # "weekly" (indices), "monthly" (stocks)
    option_liquidity: str            # "high", "medium", "low", "none"
    exercise_style: str              # "european" (indices), "american" (stocks)

    # Futures availability
    has_futures: bool
    futures_lot_size: int
    futures_margin_pct: float        # SPAN + exposure margin

    # Correlation data
    beta_nifty: float
    beta_banknifty: float | None     # Only for banking stocks
    sector_index: str | None         # NIFTY IT, NIFTY Bank, etc.

    # Hedging classification
    hedge_tier: int                  # 1=direct options, 2=futures, 3=proxy only


# Pre-built database
INDIA_FNO_UNIVERSE = {
    # Tier 1: Liquid options
    "RELIANCE": IndiaFnOInstrument(ticker="RELIANCE", sector="Energy", has_options=True,
        option_lot_size=250, option_liquidity="high", has_futures=True,
        futures_lot_size=250, beta_nifty=1.1, hedge_tier=1),
    "HDFCBANK": IndiaFnOInstrument(ticker="HDFCBANK", sector="Banking", has_options=True,
        option_lot_size=550, option_liquidity="high", has_futures=True,
        futures_lot_size=550, beta_nifty=0.9, beta_banknifty=1.1, hedge_tier=1),
    "INFY": IndiaFnOInstrument(ticker="INFY", sector="IT", has_options=True,
        option_lot_size=400, option_liquidity="high", has_futures=True,
        futures_lot_size=400, beta_nifty=0.8, hedge_tier=1),
    "TCS": IndiaFnOInstrument(ticker="TCS", sector="IT", has_options=True,
        option_lot_size=175, option_liquidity="high", has_futures=True,
        futures_lot_size=175, beta_nifty=0.7, hedge_tier=1),

    # Tier 2: Futures available, options illiquid
    "TATASTEEL": IndiaFnOInstrument(ticker="TATASTEEL", sector="Metal", has_options=True,
        option_lot_size=500, option_liquidity="low", has_futures=True,
        futures_lot_size=500, beta_nifty=1.2, hedge_tier=2),

    # Indices
    "NIFTY": IndiaFnOInstrument(ticker="NIFTY", sector="Index", has_options=True,
        option_lot_size=25, option_strike_interval=50, option_expiry_type="weekly",
        option_liquidity="highest", exercise_style="european", has_futures=True,
        futures_lot_size=25, beta_nifty=1.0, hedge_tier=1),
    "BANKNIFTY": IndiaFnOInstrument(ticker="BANKNIFTY", sector="Index", has_options=True,
        option_lot_size=15, option_strike_interval=100, option_expiry_type="weekly",
        option_liquidity="highest", exercise_style="european", has_futures=True,
        futures_lot_size=15, beta_nifty=1.1, beta_banknifty=1.0, hedge_tier=1),

    # ... 180+ instruments total
}
```

---

## Synthetic Options Engine

### How synthetics work in India

**Synthetic Long Put** (protect downside without buying a put):
```
Long stock + Short futures = Synthetic long put
  ↳ If stock drops: futures profit offsets stock loss
  ↳ If stock rises: futures loss caps your upside
  ↳ Cost: futures premium (usually 0.5-2% annualized)
  ↳ No options needed!
```

**Synthetic Covered Call** (earn income without selling a call):
```
Long stock + Short futures (partial, e.g., 50% of position)
  ↳ 50% of position is hedged (locked in)
  ↳ 50% participates in upside
  ↳ The "locked in" portion earns the futures premium as income
```

**Synthetic Collar** (zero-cost protection range):
```
Long stock + Short futures + Long OTM NIFTY call
  ↳ Futures hedge gives downside protection
  ↳ NIFTY call gives some upside participation if market rallies
  ↳ Works even if the stock has no options at all
```

**Conversion/Reversal** (arbitrage between options and futures):
```
Long stock + Long put + Short call (same strike) = Synthetic short futures
  ↳ If actual futures are mispriced vs this synthetic, arbitrage exists
  ↳ For hedging: if puts are expensive, use futures instead
```

### APIs:

```python
def build_synthetic_put_from_futures(
    ticker: str,
    shares: int,
    current_price: float,
    futures_price: float,
    lot_size: int,
    dte: int,
) -> SyntheticOptionResult:
    """Build a synthetic put by shorting futures.

    Returns TradeSpec for the futures short + cost analysis.
    """

def build_synthetic_collar_from_futures(
    ticker: str,
    shares: int,
    current_price: float,
    futures_price: float,
    lot_size: int,
    index_call_strike: float,   # OTM NIFTY call for upside
    dte: int,
) -> SyntheticOptionResult

def compare_hedge_methods(
    ticker: str,
    shares: int,
    current_price: float,
    regime_id: int,
    atr: float,
) -> HedgeComparisonResult:
    """Compare all available hedging methods for this position.

    Returns ranked list:
    1. Direct put (if available + liquid) — cost, delta reduction
    2. Futures short (if futures available) — cost, delta reduction
    3. Synthetic collar (futures + index call) — cost, delta reduction
    4. Proxy NIFTY hedge — cost, delta reduction, basis risk

    Each with concrete TradeSpec.
    """
```

---

## Trade-Level Hedging

Every income trade should have a hedge consideration:

```python
def recommend_trade_hedge(
    trade_spec: TradeSpec,
    portfolio_positions: list[dict],
    regime_id: int,
    market: str = "India",
) -> TradeHedgeRecommendation:
    """For a new trade, what hedge should accompany it?

    IC on NIFTY: already defined risk — no additional hedge needed
    CSP on RELIANCE: undefined risk — recommend protective put or futures collar
    Equity purchase: full stock risk — recommend Tier 1/2/3 hedge
    """
```

---

## Hedge Monitoring & Rolling

Hedges expire. Weekly NIFTY puts need rolling every week. Futures need rolling monthly.

```python
def monitor_hedge_status(
    hedges: list[dict],        # Active hedge positions
    dte_remaining: dict,       # Days to expiry per hedge
) -> HedgeMonitorResult:
    """Check which hedges need rolling.

    Returns:
    - expiring_soon: hedges with < 3 DTE (need rolling)
    - roll_specs: TradeSpecs to close expiring + open new hedges
    - cost_to_roll: estimated cost
    """

def compute_hedge_effectiveness(
    portfolio_positions: list[dict],
    hedge_positions: list[dict],
    market_move_pct: float,    # Simulate: what if market drops 5%?
) -> HedgeEffectivenessResult:
    """How effective are current hedges?

    Simulates a market move and computes:
    - Portfolio loss without hedges
    - Portfolio loss with hedges
    - Hedge P&L
    - Net portfolio impact
    - "Your hedges saved you ₹X on a Y% move"
    """
```

---

## The Complete API Surface

### Portfolio Level
| API | What it does |
|-----|-------------|
| `analyze_portfolio_hedge()` | Master function — classifies, builds, costs, returns TradeSpecs |
| `analyze_fno_coverage()` | Which stocks have F&O? Coverage % |
| `compute_portfolio_beta()` | Weighted beta vs NIFTY/BANKNIFTY |
| `recommend_proxy_hedge()` | Sector-weighted index hedge for non-F&O stocks |
| `compute_hedge_effectiveness()` | Simulate market move — how much do hedges save? |
| `compute_hedge_cost_budget()` | Monthly hedge cost vs budget |
| `monitor_hedge_status()` | Which hedges expire soon? Roll specs. |

### Trade Level
| API | What it does |
|-----|-------------|
| `recommend_trade_hedge()` | What hedge should accompany this trade? |
| `compare_hedge_methods()` | Rank all available hedges for a position |
| `build_protective_put()` | Direct put hedge (Tier 1) |
| `build_collar()` | Zero-cost collar (Tier 1) |
| `build_put_spread_hedge()` | Defined-cost put spread (Tier 1) |
| `build_futures_hedge()` | Futures short hedge (Tier 2) |
| `build_synthetic_put_from_futures()` | Synthetic put via futures (Tier 2) |
| `build_synthetic_collar_from_futures()` | Synthetic collar (Tier 2) |
| `build_index_hedge()` | Beta-adjusted NIFTY/BANKNIFTY hedge (Tier 3) |
| `compute_futures_hedge_ratio()` | How many futures lots for target delta |

### Data / Reference
| API | What it does |
|-----|-------------|
| `INDIA_FNO_UNIVERSE` | Complete database of ~180 F&O instruments |
| `get_instrument_hedge_tier()` | Classify: direct/futures/proxy |
| `get_sector_beta()` | Sector → NIFTY beta mapping |
| `get_futures_margin()` | SPAN + exposure margin by instrument |

---

## Implementation Priority

| Phase | What | APIs | Effort |
|-------|------|------|--------|
| **1** | India F&O universe database | `INDIA_FNO_UNIVERSE`, `analyze_fno_coverage`, `get_instrument_hedge_tier` | Medium |
| **2** | Portfolio-level hedging | `analyze_portfolio_hedge`, `compute_portfolio_beta`, `recommend_proxy_hedge` | Large |
| **3** | Futures synthetic hedging | `build_futures_hedge`, `build_synthetic_put_from_futures`, `build_synthetic_collar_from_futures` | Large |
| **4** | Direct option hedging | `build_protective_put`, `build_collar`, `build_put_spread_hedge` | Medium |
| **5** | Hedge comparison + monitoring | `compare_hedge_methods`, `monitor_hedge_status`, `compute_hedge_effectiveness` | Medium |
| **6** | Trade-level integration | `recommend_trade_hedge` wired into every assessor | Medium |

---

## Revenue Connection

This suite powers **Service 7: Hedging-as-a-Service** from THE_FUNNEL.md:

```
Client uploads CSV portfolio
  → analyze_fno_coverage() — "65% of your portfolio can be hedged"
  → analyze_portfolio_hedge() — "here are your 15 hedge trades"
  → Each hedge has a concrete TradeSpec
  → Client places hedges via Dhan/Zerodha
  → Weekly: monitor_hedge_status() — "3 hedges expiring, here are roll specs"
  → Monthly: compute_hedge_effectiveness() — "hedges saved you ₹1.2L this month"
```

**This is the service nobody in India offers.** Professional-grade portfolio hedging, personalized to each client's holdings, with concrete executable orders.
