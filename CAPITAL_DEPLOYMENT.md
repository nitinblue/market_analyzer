# Capital Deployment Engine — Design Document

**Context:** User has been uninvested for a decade. Has significant cash to deploy. Markets volatile (NIFTY -12%, gold +67%, crude +67%). Goal: systematic long-term capital deployment into core holdings without getting killed by timing.

**Principle:** Never deploy all at once. Never try to time the bottom. Systematic, valuation-aware, regime-adjusted deployment over 6-18 months.

---

## What MA Builds (Pure Computation APIs)

### CD1: Market Valuation Framework

**What:** Track valuation metrics for major indices vs their own history. Answer: "Is the market cheap, fair, or expensive right now?"

```python
class MarketValuation(BaseModel):
    """Valuation context for a market/index."""
    ticker: str
    name: str
    current_pe: float | None
    pe_5y_avg: float | None         # 5-year average P/E
    pe_10y_avg: float | None        # 10-year average P/E
    pe_percentile: float | None     # Where current P/E sits in 5yr range (0-100)
    earnings_yield: float | None    # 1/PE as % — comparable to bond yields
    dividend_yield: float | None
    from_52w_high_pct: float
    from_52w_low_pct: float

    zone: str                       # "deep_value", "value", "fair", "expensive", "bubble"
    zone_score: float               # -1 (deep value) to +1 (bubble)

    # Historical return context
    historical_return_at_this_pe: str | None  # "When PE was this level, 3yr avg return was X%"

    commentary: list[str]


def compute_market_valuation(
    ticker: str,
    ohlcv: pd.DataFrame,
    current_pe: float | None = None,
    dividend_yield: float | None = None,
    bond_yield: float | None = None,     # 10Y yield for equity risk premium
) -> MarketValuation:
    """Compute valuation zone from price history and fundamentals."""
```

**Valuation zones:**
- **Deep Value (score < -0.5):** P/E in bottom 20% of 5yr range AND >15% below 52wk high
- **Value (-0.5 to -0.2):** P/E below 5yr average AND >8% below high
- **Fair (-0.2 to +0.2):** P/E near 5yr average
- **Expensive (+0.2 to +0.5):** P/E above 5yr average, near highs
- **Bubble (> +0.5):** P/E in top 20% of range AND at/near all-time high

### CD2: Systematic Deployment Planner (SIP Intelligence)

**What:** Given total capital and a deployment horizon, compute a monthly allocation schedule that's valuation-aware and regime-adjusted.

```python
class DeploymentSchedule(BaseModel):
    """Monthly capital deployment plan."""
    total_capital: float
    currency: str
    deployment_months: int
    start_date: date

    monthly_allocations: list[MonthlyAllocation]

    base_monthly: float           # Equal split: total / months
    regime_adjustment: str        # How regime affects the plan
    valuation_adjustment: str     # How valuation affects the plan

    total_equity_pct: float       # % going to equity
    total_gold_pct: float         # % going to gold
    total_debt_pct: float         # % going to debt/bonds
    total_cash_reserve_pct: float # % kept in cash

    commentary: list[str]
    summary: str


class MonthlyAllocation(BaseModel):
    """What to invest in a single month."""
    month: int                    # 1, 2, 3, ...
    date: date                    # Approximate date
    amount: float                 # Total for this month

    equity_amount: float
    equity_instruments: list[str] # What to buy
    gold_amount: float
    debt_amount: float
    cash_reserve: float

    acceleration_reason: str | None  # "Market dropped further — deploying more"
    deceleration_reason: str | None  # "Market rallied — slowing deployment"


def plan_deployment(
    total_capital: float,
    currency: str = "INR",
    deployment_months: int = 12,
    market: str = "INDIA",
    current_regime_id: int = 2,
    valuation_zone: str = "fair",
    risk_tolerance: str = "moderate",  # "conservative", "moderate", "aggressive"
) -> DeploymentSchedule:
    """Create a systematic capital deployment plan.

    Rules:
    - Base: equal split across months (total / months)
    - Regime adjustment: R4 (volatile) → accelerate 20% (buy fear). R1 (calm) → normal.
    - Valuation adjustment: deep_value → accelerate 30%. Expensive → decelerate 30%.
    - Risk tolerance: conservative → more debt/gold. Aggressive → more equity.
    - Always keep 10% cash reserve minimum
    """
```

**Deployment acceleration/deceleration logic:**

```
NORMAL:     Base amount each month
ACCELERATE: Deploy more this month (market is cheaper)
  - Valuation zone = deep_value → +30% this month
  - Valuation zone = value → +15%
  - Regime R4 (volatility = opportunity for long-term) → +20%
  - Market dropped >5% since last deployment → +25%

DECELERATE: Deploy less this month (market is frothy)
  - Valuation zone = expensive → -30%
  - Valuation zone = bubble → -50% (keep cash)
  - Market rallied >10% since last deployment → -20%
```

### CD3: Asset Allocation Model

**What:** How to split capital between equity, gold, debt, and cash based on macro regime and valuation.

```python
class AssetAllocation(BaseModel):
    """Recommended asset allocation."""
    equity_pct: float         # % in stocks
    gold_pct: float           # % in gold (GLD, Sovereign Gold Bonds)
    debt_pct: float           # % in bonds/FDs/debt funds
    cash_pct: float           # % in liquid cash

    equity_split: dict[str, float]  # {"india_large_cap": 40, "india_mid_cap": 10, "us_sp500": 15, ...}

    rationale: list[str]
    regime_context: str
    rebalance_trigger: str    # "Rebalance when any asset class drifts >5% from target"


def compute_asset_allocation(
    market: str = "INDIA",
    regime: str = "risk_off",
    valuation_zone: str = "value",
    risk_tolerance: str = "moderate",
    age: int | None = None,           # Optional: adjust equity% by age
    has_existing_equity: bool = False, # Already have equity exposure?
    has_existing_gold: bool = False,
) -> AssetAllocation:
    """Compute recommended asset allocation.

    Base allocation (moderate risk):
      Equity 60% | Gold 15% | Debt 15% | Cash 10%

    Regime adjustments:
      RISK_ON:      Equity +10%, Gold -5%, Debt -5%
      RISK_OFF:     Equity -10%, Gold +10%
      STAGFLATION:  Equity -15%, Gold +15%, add commodity
      DEFLATIONARY: Equity -20%, Debt +10%, Cash +10%

    Valuation adjustments:
      DEEP_VALUE:   Equity +10% (it's cheap — buy more)
      EXPENSIVE:    Equity -10%, Cash +10% (wait for pullback)
    """
```

### CD4: Core Holdings Recommender

**What:** Specifically for India — which stocks/ETFs for core long-term holdings.

```python
class CoreHolding(BaseModel):
    """A single recommended core holding."""
    ticker: str
    name: str
    allocation_pct: float      # % of equity allocation
    category: str              # "large_cap_index", "sectoral", "thematic", "gold", "debt"
    instrument_type: str       # "etf", "stock", "mf", "sgb"
    rationale: str
    entry_approach: str        # "lump_sum", "sip_6m", "sip_12m"


class CorePortfolio(BaseModel):
    """Recommended core portfolio for long-term deployment."""
    market: str
    total_capital: float
    currency: str
    holdings: list[CoreHolding]
    total_equity_pct: float
    total_gold_pct: float
    total_debt_pct: float
    commentary: list[str]

    # Deployment plan
    deployment: DeploymentSchedule | None


def recommend_core_portfolio(
    total_capital: float,
    currency: str = "INR",
    market: str = "INDIA",
    regime_id: int = 2,
    valuation_zone: str = "value",
    risk_tolerance: str = "moderate",
    deployment_months: int = 12,
) -> CorePortfolio:
    """Recommend a core portfolio for long-term capital deployment.

    India-specific holdings:
    - NIFTY 50 ETF (Nifty BeES / UTI Nifty) — 30-40% of equity
    - NIFTY Next 50 ETF — 10-15% of equity
    - Banking/Financial ETF — 10-15% if banking sector undervalued
    - Individual stocks from screen_stocks(strategy=value) — 20-30%
    - Gold ETF / Sovereign Gold Bonds — 10-20% of total
    - Short-term debt fund / FDs — 10-20% of total

    US-specific holdings:
    - S&P 500 ETF (SPY/VOO) — 40-50% of equity
    - QQQ (tech) — 15-20% if not expensive
    - Individual stocks from screen_stocks(strategy=quality_momentum) — 20-30%
    - GLD — 10-15% of total
    - TLT/SHY — 10-15% of total
    """
```

### CD5: Rebalancing Engine

**What:** When and how to rebalance between asset classes.

```python
class RebalanceAction(BaseModel):
    """A single rebalancing action."""
    asset: str                # "equity", "gold", "debt"
    current_pct: float
    target_pct: float
    drift_pct: float          # How far from target
    action: str               # "buy", "sell", "hold"
    amount: float             # How much to buy/sell
    rationale: str


class RebalanceCheck(BaseModel):
    """Rebalancing assessment."""
    needs_rebalance: bool
    actions: list[RebalanceAction]
    trigger: str              # "drift >5%", "quarterly schedule", "regime change"
    commentary: list[str]


def check_rebalance(
    current_allocation: dict[str, float],  # {"equity": 70, "gold": 12, "debt": 8, "cash": 10}
    target_allocation: AssetAllocation,
    portfolio_value: float,
    drift_threshold_pct: float = 5.0,
) -> RebalanceCheck:
    """Check if portfolio needs rebalancing.

    Triggers:
    - Any asset class > drift_threshold from target
    - Quarterly schedule (even if within threshold)
    - Regime change (shift allocation targets)
    """
```

---

## What eTrading Builds (Framework)

### eTrading Responsibilities

| What | How | When |
|------|-----|------|
| **Capital deployment scheduler** | Store DeploymentSchedule, trigger monthly allocations | Monthly on scheduled date |
| **SIP execution** | On deployment date: get MA's allocation → place orders → confirm fills | Monthly |
| **Portfolio tracking** | Track actual allocation vs target. Store current values. | Continuous |
| **Rebalance trigger** | Run `check_rebalance()` quarterly or on regime change. Display actions. | Quarterly |
| **Deployment acceleration UI** | When MA says "accelerate" — show user why, get confirmation, execute | When triggered |
| **Holdings dashboard** | Show core holdings with P&L, allocation %, drift from target | Always |
| **Tax-aware execution** | India: LTCG vs STCG rules. Suggest tax-loss harvesting. | At rebalance |

### eTrading Integration Flow

```python
# ═══ Monthly SIP Execution (eTrading scheduler) ═══

# 1. Get current state
regime = ma.regime.detect("NIFTY")
valuation = compute_market_valuation("NIFTY", nifty_ohlcv, current_pe=pe)

# 2. Get deployment plan (or load existing)
plan = plan_deployment(
    total_capital=remaining_capital,
    deployment_months=months_remaining,
    current_regime_id=int(regime.regime),
    valuation_zone=valuation.zone,
)

# 3. This month's allocation
this_month = plan.monthly_allocations[0]
print(f"Deploy {this_month.amount:,.0f} this month")
print(f"  Equity: {this_month.equity_amount:,.0f}")
print(f"  Gold: {this_month.gold_amount:,.0f}")
print(f"  Debt: {this_month.debt_amount:,.0f}")

# 4. For equity portion — get specific stocks
top_stocks = screen_stocks(
    tickers=registry.get_universe(preset="nifty50"),
    strategy=InvestmentStrategy.VALUE,
    horizon=InvestmentHorizon.LONG_TERM,
    market="INDIA",
)

# 5. Place orders
for holding in this_month.equity_instruments:
    place_buy_order(holding, amount=this_month.equity_amount / len(instruments))

# 6. Track deployment progress
update_deployment_progress(plan, month_completed=True)


# ═══ Quarterly Rebalance Check ═══

current = get_current_allocation()  # From portfolio DB
target = compute_asset_allocation(regime=regime.regime, valuation_zone=valuation.zone)
rebalance = check_rebalance(current, target, portfolio_value)

if rebalance.needs_rebalance:
    for action in rebalance.actions:
        if action.action == "sell":
            place_sell_order(action.asset, action.amount)  # Consider tax implications
        elif action.action == "buy":
            place_buy_order(action.asset, action.amount)
```

### eTrading Data Requirements

| What eTrading Stores | Purpose |
|---------------------|---------|
| `DeploymentSchedule` | Track progress — how much deployed, how much remaining |
| `monthly_executed: list[dict]` | What was actually bought each month |
| `current_allocation: dict[str, float]` | Real-time asset class weights |
| `portfolio_value: float` | Current total value |
| `deployment_start_date` | When deployment started |
| `remaining_capital` | Undeployed cash |

---

## Implementation Order

| # | What | MA builds | Priority |
|---|------|-----------|----------|
| CD1 | Market valuation framework | `compute_market_valuation()` | HIGH — answers "is it cheap?" |
| CD2 | Deployment planner | `plan_deployment()` | HIGH — the core SIP intelligence |
| CD3 | Asset allocation model | `compute_asset_allocation()` | HIGH — equity/gold/debt split |
| CD4 | Core holdings recommender | `recommend_core_portfolio()` | HIGH — what to actually buy |
| CD5 | Rebalancing engine | `check_rebalance()` | MEDIUM — quarterly check |
| CD6 | CLI commands | `deploy`, `valuation`, `allocate`, `rebalance` | HIGH |
| CD7 | Reference flow | `challenge/trader_deploy.py` | MEDIUM |

---

## Key Principles for Long-Term Deployment

1. **Never deploy all at once.** Systematic over 6-18 months.
2. **Buy fear, not greed.** R4 regime + NIFTY -12% = accelerate deployment (counterintuitive but historically correct).
3. **Diversify across asset classes.** Gold rallying 67% while stocks fall = they're doing their job as hedge.
4. **Index first, stocks second.** NIFTY 50 ETF as the core. Individual stocks for satellite positions.
5. **Rebalance, don't predict.** Quarterly rebalance mechanically. Don't try to call tops/bottoms.
6. **Keep cash reserve.** Always 10% minimum. Dry powder for genuine crashes (>20% down).
7. **Ignore daily noise.** Review monthly. Act quarterly. Think in decades.
