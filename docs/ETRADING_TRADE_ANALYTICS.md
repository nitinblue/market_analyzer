# Trade Analytics Integration Guide

## Overview
income_desk now provides all trade-level and portfolio-level calculation APIs. eTrading should call these instead of computing P&L, Greeks, structure risk, performance metrics, or circuit breakers inline.

**Install/upgrade:** `pip install --upgrade income-desk`

**Single import:**
```python
from income_desk.trade_analytics import (
    compute_pnl_attribution, PnLAttribution,
    compute_trade_pnl, TradePnL, LegPnLInput, LegPnL,
    compute_structure_risk, StructureRisk,
    compute_portfolio_analytics, PortfolioAnalytics, PositionSnapshot, UnderlyingExposure,
    compute_performance_ledger, PerformanceLedger,
    evaluate_circuit_breakers, CircuitBreakerResult, CircuitBreakerConfig, BreakerTripped,
)
```

## API Reference

### 1. P&L Attribution — `compute_pnl_attribution()`

**Replaces:** `domain.py:Leg.get_pnl_attribution()` and `Position.get_pnl_attribution()`

**What it does:** Decomposes observed P&L into delta, gamma, theta, vega components via Taylor expansion. The unexplained residual captures higher-order effects.

**Signature:**
```python
compute_pnl_attribution(
    entry_delta: float,      # position delta at entry
    entry_gamma: float,      # position gamma at entry
    entry_theta: float,      # per-day theta at entry
    entry_vega: float,       # position vega at entry
    underlying_change: float, # current_underlying - entry_underlying
    iv_change: float,        # current_iv - entry_iv (vol points, e.g. 0.03)
    days_elapsed: float,     # calendar days since entry
    actual_pnl: float,       # observed P&L from market prices
    multiplier: int = 100,
    quantity: int = 1,       # signed: +1 long, -1 short
) -> PnLAttribution
```

**Returns:** PnLAttribution with delta_pnl, gamma_pnl, theta_pnl, vega_pnl, model_pnl, actual_pnl, unexplained_pnl

**eTrading migration:**
```python
# BEFORE (domain.py inline):
delta_pnl = delta * dS * multiplier
gamma_pnl = 0.5 * gamma * dS * dS * multiplier
# etc.

# AFTER:
from income_desk.trade_analytics import compute_pnl_attribution
attr = compute_pnl_attribution(
    entry_delta=trade.entry_delta,
    entry_gamma=trade.entry_gamma,
    entry_theta=trade.entry_theta,
    entry_vega=trade.entry_vega,
    underlying_change=trade.current_underlying_price - trade.entry_underlying_price,
    iv_change=(trade.current_iv or 0) - (trade.entry_iv or 0),
    days_elapsed=(datetime.now() - trade.executed_at).days,
    actual_pnl=trade.total_pnl,
    quantity=trade.total_quantity_signed,
)
# Store: trade.delta_pnl = attr.delta_pnl, etc.
```

### 2. Trade P&L — `compute_trade_pnl()`

**Replaces:** P&L calculations in `mark_to_market.py:_update_trade_aggregates()` and `trade_lifecycle.py`

**What it does:** Computes P&L since trade inception AND since today's market open, with per-leg breakdown.

**Signature:**
```python
compute_trade_pnl(legs: list[LegPnLInput]) -> TradePnL
```

**LegPnLInput fields:** quantity (signed), entry_price, current_price, open_price (today's open), multiplier

**Returns:** TradePnL with pnl_inception, pnl_inception_pct, pnl_today, pnl_today_pct, entry_cost, current_value, open_value, legs (per-leg breakdown)

**eTrading migration:**
```python
# BEFORE (mark_to_market.py):
leg_value = current_price * abs(qty) * multiplier
pnl = net_current - entry_price

# AFTER:
from income_desk.trade_analytics import compute_trade_pnl, LegPnLInput
legs = [
    LegPnLInput(
        quantity=leg.quantity,  # signed
        entry_price=leg.entry_price,
        current_price=leg.current_price,  # from DXLink
        open_price=leg.price_at_open,     # cached at market open
        multiplier=leg.multiplier,
    )
    for leg in trade.legs
]
pnl = compute_trade_pnl(legs)
# Use: pnl.pnl_inception, pnl.pnl_today, pnl.pnl_inception_pct, pnl.pnl_today_pct
```

**Important:** eTrading must cache each leg's price at market open (9:30 ET) to populate `open_price`. This enables accurate daily P&L.

### 3. Structure Risk — `compute_structure_risk()`

**Replaces:** `strategy_templates.py:calculate_max_profit()` and `calculate_max_loss()`, plus scattered breakeven/risk-reward calculations

**What it does:** Computes max profit, max loss, breakevens, risk/reward ratio, and wing width for ANY structure type — credit AND debit.

**Signature:**
```python
compute_structure_risk(
    structure_type: str,        # "iron_condor", "debit_spread", "long_option", etc.
    legs: list[LegSpec],        # from income_desk.models.opportunity
    net_credit_debit: float,    # positive = credit, negative = debit
    multiplier: int = 100,
    contracts: int = 1,
    underlying_price: float | None = None,  # needed for covered_call
) -> StructureRisk
```

**Returns:** StructureRisk with max_profit, max_loss (None = unlimited), breakeven_low, breakeven_high, risk_reward_ratio, wing_width, risk_profile ("defined"/"undefined"), strategy_label

**Supported structures:** iron_condor, iron_butterfly, iron_man, credit_spread, debit_spread, strangle (credit/debit), straddle (credit/debit), long_option, cash_secured_put, covered_call, jade_lizard, pmcc, calendar, diagonal, double_calendar, ratio_spread

**eTrading migration:**
```python
# BEFORE (strategy_templates.py):
max_p = calculate_max_profit(strategy_type, net_credit, width, 100)
max_l = calculate_max_loss(strategy_type, net_credit, width, 100)

# AFTER:
from income_desk.trade_analytics import compute_structure_risk
from income_desk import from_dxlink_symbols
legs = from_dxlink_symbols(trade.dxlink_symbols, trade.quantities, trade.actions)
risk = compute_structure_risk(
    structure_type=trade.strategy_type,
    legs=legs,
    net_credit_debit=trade.entry_price,  # positive=credit, negative=debit
    contracts=trade.contracts,
    underlying_price=trade.current_underlying_price,
)
# Store: trade.max_profit_dollars = risk.max_profit
#        trade.max_loss_dollars = risk.max_loss
#        trade.breakeven_low = risk.breakeven_low
#        trade.breakeven_high = risk.breakeven_high
#        trade.risk_reward_ratio = risk.risk_reward_ratio
```

### 4. Portfolio Analytics — `compute_portfolio_analytics()`

**Replaces:** Greeks aggregation in `snapshot_service.py`, `api_trading_sheet.py:_build_whatif_risk_factors()`, and portfolio-level P&L in `performance_metrics_service.py`

**Signature:**
```python
compute_portfolio_analytics(
    positions: list[PositionSnapshot],
    account_nlv: float,
) -> PortfolioAnalytics
```

**PositionSnapshot fields:** ticker, structure_type, entry_price, current_price, open_price, quantity, multiplier, delta, gamma, theta, vega, underlying_price, max_loss

**Returns:** PortfolioAnalytics with total_pnl_inception, total_pnl_today, total_pnl_pct, net Greeks, delta_dollars, theta_dollars_per_day, total_margin_at_risk, margin_utilization_pct, by_underlying (dict of UnderlyingExposure)

**eTrading migration:**
```python
from income_desk.trade_analytics import compute_portfolio_analytics, PositionSnapshot
snapshots = [
    PositionSnapshot(
        ticker=t.underlying_symbol,
        structure_type=t.strategy_type,
        entry_price=t.entry_price,
        current_price=t.current_price,
        open_price=t.price_at_open,
        quantity=t.total_quantity_signed,
        delta=t.current_delta,
        gamma=t.current_gamma,
        theta=t.current_theta,
        vega=t.current_vega,
        underlying_price=t.current_underlying_price,
        max_loss=t.max_loss_dollars,
    )
    for t in open_trades
]
analytics = compute_portfolio_analytics(snapshots, account.net_liquidation_value)
# Use: analytics.net_delta, analytics.delta_dollars, analytics.total_pnl_today, etc.
```

### 5. Performance Ledger — `compute_performance_ledger()`

**Replaces:** `performance_metrics_service.py` — win rate, profit factor, Sharpe, CAGR, MAR, max drawdown, consecutive streaks

**Signature:**
```python
compute_performance_ledger(
    outcomes: list[TradeOutcome],  # from income_desk.models.feedback
    initial_capital: float,
    risk_free_rate: float = 0.05,
) -> PerformanceLedger
```

**Returns:** PerformanceLedger with total_trades, total_pnl, win_rate, profit_factor, sharpe_ratio, max_drawdown_pct, cagr_pct, mar_ratio, max_consecutive_wins/losses, avg_holding_days, best/worst_trade_pnl, expectancy_per_trade, current_equity, return_pct

**eTrading migration:**
```python
from income_desk.trade_analytics import compute_performance_ledger
from income_desk.models.feedback import TradeOutcome

# Convert closed TradeORM -> TradeOutcome (already done in ml_learning_service.py)
outcomes = [trade_to_outcome(t) for t in closed_trades]
ledger = compute_performance_ledger(outcomes, initial_capital=50000.0)
# Use: ledger.win_rate, ledger.sharpe_ratio, ledger.cagr_pct, ledger.mar_ratio, etc.
```

### 6. Circuit Breakers — `evaluate_circuit_breakers()`

**Replaces:** Circuit breaker logic in `sentinel.py:_check_circuit_breakers()`

**Signature:**
```python
evaluate_circuit_breakers(
    daily_pnl_pct: float,
    weekly_pnl_pct: float,
    vix: float | None = None,
    portfolio_drawdown_pct: float = 0,
    consecutive_losses: int = 0,
    config: CircuitBreakerConfig | None = None,
) -> CircuitBreakerResult
```

**Default thresholds:** daily_loss=2%, weekly_loss=5%, vix_halt=35, max_drawdown=10%, consecutive_pause=3, consecutive_halt=5

**Returns:** CircuitBreakerResult with is_halted, is_paused, can_open_new, breakers_tripped (list of BreakerTripped with name/threshold/value/severity), resume_conditions

**eTrading migration:**
```python
from income_desk.trade_analytics import evaluate_circuit_breakers, CircuitBreakerConfig

# Custom config (optional -- defaults are sensible)
config = CircuitBreakerConfig(daily_loss_pct=1.5, max_drawdown_pct=8.0)

result = evaluate_circuit_breakers(
    daily_pnl_pct=portfolio.daily_pnl_pct,
    weekly_pnl_pct=portfolio.weekly_pnl_pct,
    vix=market_data.vix,
    portfolio_drawdown_pct=portfolio.drawdown_pct,
    consecutive_losses=desk.consecutive_losses,
    config=config,
)
if not result.can_open_new:
    log.warning(f"Trading halted: {result.resume_conditions}")
```

## Files to Update in eTrading

| eTrading File | What to Remove | What to Call Instead |
|---------------|---------------|---------------------|
| `core/models/domain.py` (lines 531-584) | `Leg.get_pnl_attribution()` | `compute_pnl_attribution()` |
| `core/models/domain.py` (lines 968-1000) | `Position.get_pnl_attribution()` | `compute_pnl_attribution()` |
| `services/mark_to_market.py` (lines 239-351) | P&L aggregation math | `compute_trade_pnl()` |
| `core/models/strategy_templates.py` (lines 622-751) | `calculate_max_profit()`, `calculate_max_loss()` | `compute_structure_risk()` |
| `services/snapshot_service.py` (lines 101-170) | Portfolio Greeks aggregation | `compute_portfolio_analytics()` |
| `web/api_trading_sheet.py` (lines 329-543) | `_compute_max_risk()`, `_build_whatif_risk_factors()` | `compute_structure_risk()` + `compute_portfolio_analytics()` |
| `services/performance_metrics_service.py` (lines 333-519) | `_compute_metrics()`, `_calculate_max_drawdown()`, `_calculate_cagr()`, `_calculate_sharpe()` | `compute_performance_ledger()` |
| `agents/domain/sentinel.py` (lines 133-197) | Circuit breaker checks | `evaluate_circuit_breakers()` |
| `services/risk/margin.py` (lines 78-106) | `analyze_portfolio()` aggregation | `compute_portfolio_analytics()` (margin_utilization_pct) |
| `services/trade_lifecycle.py` (lines 71-76) | Final P&L calculation | `compute_trade_pnl()` |

## Key Requirement: Daily P&L (open_price)

`compute_trade_pnl()` requires each leg's price at today's market open. eTrading must:

1. **At market open (9:30 ET):** Snapshot each leg's current price -> store as `price_at_open`
2. **During the day:** Pass `price_at_open` as `open_price` to `LegPnLInput`
3. **Result:** `pnl_today` gives accurate intraday P&L change

If `open_price` is not available (e.g., trade opened today), use `entry_price` as fallback.

## NVDA Bug Fix

The NVDA trade that lost $1,366 but showed Greek P&L summing to +$68 is fixed by this module. The new `compute_pnl_attribution()`:
- Uses consistent formulas with proper rounding
- Returns `unexplained_pnl` explicitly -- large unexplained values signal data problems
- eTrading should flag trades where `abs(unexplained_pnl) > 0.5 * abs(actual_pnl)` for review
