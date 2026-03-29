# Trade Analytics Service — Design Spec

**Date:** 2026-03-23
**Goal:** Move ALL trade-level and portfolio-level calculations out of eTrading into income_desk. eTrading calls income_desk for every number; eTrading stores results and renders UI.

## Problem

eTrading currently computes P&L attribution, max profit/loss, performance metrics (CAGR, MAR), circuit breakers, and margin estimates inline. This:
1. Led to the NVDA bug: Greek P&L attribution didn't reconcile (-$1,366 loss but greeks summed to +$68)
2. Exit reason recorded as "profit_target" on a losing trade — no library validation
3. Duplicates income_desk's existing performance module (Sharpe, drawdown, win rate)
4. Makes it impossible for income_desk to unit-test these calculations

## What Already Exists in income_desk (NO duplication)

| Capability | Function | File |
|-----------|----------|------|
| Greeks aggregation | `aggregate_greeks()` | trade_lifecycle.py |
| Breakevens | `compute_breakevens()` | trade_lifecycle.py |
| Income yield (credit only) | `compute_income_yield()` | trade_lifecycle.py |
| POP estimation | `estimate_pop()` | trade_lifecycle.py |
| Win rate, Sharpe, drawdown | `compute_performance_report()`, `compute_sharpe()`, `compute_drawdown()` | performance.py |
| Portfolio risk (VaR, concentration) | `compute_risk_dashboard()` | risk.py |
| Position sizing / margin | `compute_margin_analysis()` | features/position_sizing.py |
| Stress testing | `run_stress_suite()` | stress_testing.py |
| Structure profiles | `get_structure_profile()` | models/opportunity.py |

## What Must Be Built (net-new)

### Module: `income_desk/trade_analytics.py`

Six new public functions + Pydantic models:

### 1. `compute_pnl_attribution()`
Greek-based P&L decomposition using Taylor expansion.

```python
def compute_pnl_attribution(
    entry_delta: float,
    entry_gamma: float,
    entry_theta: float,
    entry_vega: float,
    underlying_change: float,  # current_price - entry_price (underlying)
    iv_change: float,          # current_iv - entry_iv (in vol points, e.g. 0.03 = 3%)
    days_elapsed: float,       # calendar days since entry
    actual_pnl: float,         # observed P&L from market prices
    multiplier: int = 100,     # contract multiplier
    quantity: int = 1,         # signed quantity (+1 long, -1 short)
) -> PnLAttribution:
```

**Formula:**
- delta_pnl = delta × dS × multiplier × quantity
- gamma_pnl = 0.5 × gamma × dS² × multiplier × quantity
- theta_pnl = theta × dt × multiplier × quantity  (dt in days, theta is per-day)
- vega_pnl = vega × dIV × multiplier × quantity  (dIV in vol points)
- model_pnl = sum of above
- unexplained_pnl = actual_pnl - model_pnl

**Model:**
```python
class PnLAttribution(BaseModel):
    delta_pnl: float
    gamma_pnl: float
    theta_pnl: float
    vega_pnl: float
    model_pnl: float       # sum of greek P&Ls
    actual_pnl: float      # observed from market
    unexplained_pnl: float # actual - model
    underlying_change: float
    iv_change: float
    days_elapsed: float
```

### 2. `compute_trade_pnl()`
P&L since inception and P&L since today's open.

```python
def compute_trade_pnl(
    legs: list[LegPnLInput],  # per-leg entry/current/open prices
    multiplier: int = 100,
) -> TradePnL:
```

**Input model:**
```python
class LegPnLInput(BaseModel):
    quantity: int           # signed: +1 long, -1 short
    entry_price: float      # price at trade open
    current_price: float    # price right now
    open_price: float       # price at today's market open (for daily P&L)
    multiplier: int = 100
```

**Output model:**
```python
class TradePnL(BaseModel):
    pnl_inception: float      # total P&L since trade was opened
    pnl_inception_pct: float  # as % of entry cost
    pnl_today: float          # P&L change since today's market open
    pnl_today_pct: float      # as % of today's open value
    entry_cost: float         # total entry cost (absolute)
    current_value: float      # total current value
    open_value: float         # total value at today's open
    legs: list[LegPnL]        # per-leg breakdown
```

```python
class LegPnL(BaseModel):
    pnl_inception: float
    pnl_today: float
    entry_price: float
    current_price: float
    open_price: float
    quantity: int
```

### 3. `compute_structure_risk()`
Max profit, max loss, breakevens, risk/reward for ANY structure type (credit AND debit).

```python
def compute_structure_risk(
    structure_type: str,         # StructureType value
    legs: list[LegSpec],         # from TradeSpec
    net_credit_debit: float,     # positive = credit received, negative = debit paid
    multiplier: int = 100,
    contracts: int = 1,
    underlying_price: float | None = None,
) -> StructureRisk:
```

**Output model:**
```python
class StructureRisk(BaseModel):
    max_profit: float | None      # None = unlimited
    max_loss: float | None        # None = unlimited
    breakeven_low: float | None
    breakeven_high: float | None
    risk_reward_ratio: float | None  # max_profit / max_loss
    wing_width: float | None      # distance between strikes
    risk_profile: str             # "defined" or "undefined"
    strategy_label: str           # human-readable description
```

Covers all 22 StructureType values including debit spreads, LEAPs, straddles, etc.

### 4. `compute_portfolio_analytics()`
Portfolio-level aggregations that eTrading currently scatters across 3+ files.

```python
def compute_portfolio_analytics(
    positions: list[PositionSnapshot],
    account_nlv: float,
) -> PortfolioAnalytics:
```

**Input model:**
```python
class PositionSnapshot(BaseModel):
    ticker: str
    structure_type: str
    entry_price: float          # net cost basis
    current_price: float        # current market value per unit
    open_price: float           # value at today's open
    quantity: int               # number of contracts/shares
    multiplier: int = 100
    delta: float = 0
    gamma: float = 0
    theta: float = 0
    vega: float = 0
    underlying_price: float = 0
    max_loss: float | None = None
```

**Output model:**
```python
class PortfolioAnalytics(BaseModel):
    total_pnl_inception: float
    total_pnl_today: float
    total_pnl_pct: float          # vs account NLV
    net_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float
    delta_dollars: float          # net_delta × underlying_price
    theta_dollars_per_day: float  # daily theta in dollars
    total_margin_at_risk: float   # sum of max_loss across positions
    margin_utilization_pct: float # margin_at_risk / NLV
    by_underlying: dict[str, UnderlyingExposure]
```

```python
class UnderlyingExposure(BaseModel):
    ticker: str
    net_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float
    delta_dollars: float
    pnl_inception: float
    pnl_today: float
    position_count: int
```

### 5. `compute_performance_ledger()`
Extends existing performance module with CAGR, MAR ratio, consecutive wins/losses.

```python
def compute_performance_ledger(
    outcomes: list[TradeOutcome],
    initial_capital: float,
    risk_free_rate: float = 0.05,
) -> PerformanceLedger:
```

**Output model:**
```python
class PerformanceLedger(BaseModel):
    # From existing performance module
    total_trades: int
    total_pnl: float
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float
    # New fields
    cagr_pct: float | None         # None if < 1 year of data
    mar_ratio: float | None        # CAGR / max_drawdown
    max_consecutive_wins: int
    max_consecutive_losses: int
    avg_holding_days: float
    best_trade: TradeOutcome | None
    worst_trade: TradeOutcome | None
    expectancy_per_trade: float    # avg $ per trade
    current_equity: float          # initial + total_pnl
    return_pct: float              # total_pnl / initial_capital
```

### 6. `evaluate_circuit_breakers()`
Risk halt logic — currently in eTrading's sentinel agent.

```python
def evaluate_circuit_breakers(
    daily_pnl_pct: float,
    weekly_pnl_pct: float,
    vix: float | None,
    portfolio_drawdown_pct: float,
    consecutive_losses: int,
    config: CircuitBreakerConfig | None = None,
) -> CircuitBreakerResult:
```

**Models:**
```python
class CircuitBreakerConfig(BaseModel):
    daily_loss_pct: float = 2.0       # halt if daily loss > 2%
    weekly_loss_pct: float = 5.0      # halt if weekly loss > 5%
    vix_halt_threshold: float = 35.0  # halt if VIX > 35
    max_drawdown_pct: float = 10.0    # halt if drawdown > 10%
    consecutive_loss_pause: int = 3   # pause after 3 consecutive losses
    consecutive_loss_halt: int = 5    # halt after 5 consecutive losses

class BreakerTripped(BaseModel):
    name: str             # "daily_loss", "vix_halt", etc.
    threshold: float
    current_value: float
    severity: str         # "pause" or "halt"

class CircuitBreakerResult(BaseModel):
    is_halted: bool
    is_paused: bool
    breakers_tripped: list[BreakerTripped]
    can_open_new: bool        # False if halted or paused
    resume_conditions: list[str]  # What needs to change before resuming
```

## Integration Contract

eTrading replaces inline calculations with these imports:

```python
from income_desk.trade_analytics import (
    # P&L
    compute_pnl_attribution, PnLAttribution,
    compute_trade_pnl, TradePnL, LegPnLInput, LegPnL,
    # Structure risk
    compute_structure_risk, StructureRisk,
    # Portfolio
    compute_portfolio_analytics, PortfolioAnalytics, PositionSnapshot, UnderlyingExposure,
    # Performance
    compute_performance_ledger, PerformanceLedger,
    # Circuit breakers
    evaluate_circuit_breakers, CircuitBreakerResult, CircuitBreakerConfig, BreakerTripped,
)
```

## Testing

Each function gets unit tests with:
- Known inputs → expected outputs (hand-calculated)
- Edge cases: zero Greeks, zero prices, single-leg, undefined risk
- The NVDA trade as a regression test case
- Credit vs debit structures for `compute_structure_risk()`

## CLI

New CLI command: `analytics` subcommand group with:
- `pnl-attr` — P&L attribution for a sample trade
- `structure-risk` — max profit/loss for a given structure
- `circuit-breakers` — evaluate breaker status

## Files Changed

1. **NEW:** `income_desk/trade_analytics.py` — all 6 functions + models
2. **EDIT:** `income_desk/__init__.py` — export new public API
3. **NEW:** `tests/test_trade_analytics.py` — unit tests
4. **EDIT:** `income_desk/cli/interactive.py` — CLI commands
5. **NEW:** `docs/ETRADING_TRADE_ANALYTICS.md` — integration guide for eTrading
