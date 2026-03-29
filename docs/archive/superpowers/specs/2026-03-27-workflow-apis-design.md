# Workflow APIs Design Spec

**Date:** 2026-03-27
**Status:** APPROVED (inline approval from Nitin)

## Problem

eTrading currently orchestrates 6-8 individual income_desk service calls in sequence to accomplish common trading operations. This causes:

1. **Rate limiting** — Dhan gets hammered with individual calls (1 call per 3s for option chains)
2. **Timestamp inconsistency** — prices fetched at different times within the same operation
3. **Tight coupling** — eTrading must know ID's internal service structure
4. **Fragility** — if ID refactors services, eTrading breaks

## Solution

A `workflow/` package with high-level operations. Each workflow is:
- One function call
- One Pydantic request in, one Pydantic response out
- All rate limiting, caching, throttling handled internally
- Stateless — ID stores nothing between calls

## Workflow Catalog (14 workflows)

### Pre-Market
| Workflow | File | Purpose |
|----------|------|---------|
| `generate_daily_plan` | `daily_plan.py` | Full trading plan: regime scan, rank, validate, size — "what to trade today" |
| `snapshot_market` | `market_snapshot.py` | Batch prices, IV, Greeks, regime for all tickers — single timestamped response |

### Scanning & Selection
| Workflow | File | Purpose |
|----------|------|---------|
| `scan_universe` | `scan_universe.py` | Screen tickers against regime + technical filters → candidates |
| `rank_opportunities` | `rank_opportunities.py` | Score candidates across strategies → ranked trade proposals |

### Trade Entry
| Workflow | File | Purpose |
|----------|------|---------|
| `validate_trade` | `validate_trade.py` | Run 10-check validation gate on a specific TradeSpec |
| `size_position` | `size_position.py` | Kelly sizing with lot-size, capital, regime awareness |
| `price_trade` | `price_trade.py` | Get live quotes for a TradeSpec, compute entry price + max slippage |

### Position Management
| Workflow | File | Purpose |
|----------|------|---------|
| `monitor_positions` | `monitor_positions.py` | Exit signals, theta decay, P&L, regime shift for all open positions |
| `adjust_position` | `adjust_position.py` | Recommend specific adjustment (roll, close, widen) for one position |
| `assess_overnight_risk` | `overnight_risk.py` | End-of-day risk assessment for positions held overnight |

### Expiry & Calendar
| Workflow | File | Purpose |
|----------|------|---------|
| `check_expiry_day` | `expiry_day.py` | Expiry-day urgency escalation, 0DTE close-before-close, time windows |

### Portfolio Level
| Workflow | File | Purpose |
|----------|------|---------|
| `check_portfolio_health` | `portfolio_health.py` | Crash sentinel, regime distribution, risk budget, drawdown circuit |
| `check_profitability` | `profitability_check.py` | Daily GO/CAUTION/NO-GO system readiness verdict |

### Reporting
| Workflow | File | Purpose |
|----------|------|---------|
| `generate_daily_report` | `daily_report.py` | End-of-day summary: trades booked, P&L, regime changes, blocked trades |

## Architecture

### Request/Response Pattern
Every workflow follows the same contract:

```python
# Request: Pydantic model with all inputs
class RankOpportunitiesRequest(BaseModel):
    tickers: list[str]
    capital: float
    market: str = "India"
    risk_tolerance: str = "moderate"
    iv_rank_map: dict[str, float] | None = None
    skip_intraday: bool = True

# Response: Pydantic model with all outputs + metadata
class RankOpportunitiesResponse(BaseModel):
    as_of: datetime
    market: str
    trades: list[RankedTradeProposal]
    blocked: list[BlockedTrade]
    regime_summary: dict[str, int]
    sentinel_signal: str
    data_quality: float
    warnings: list[str]

# Function signature
def rank_opportunities(
    request: RankOpportunitiesRequest,
    ma: MarketAnalyzer,
) -> RankOpportunitiesResponse:
```

### MarketAnalyzer Injection
Workflows take a pre-built `MarketAnalyzer` as a parameter. eTrading creates it once at startup with broker providers, then passes to any workflow.

### Batch Data Fetching
`market_snapshot` is the key workflow for rate-limit management:
- Fetches ALL ticker prices in a single Dhan `ticker_data` call (batch)
- Fetches option chains sequentially with 3.5s throttle
- Returns everything with a single `as_of` timestamp
- Other workflows can accept a pre-fetched snapshot to avoid re-fetching

### Caching Strategy
- VolSurfaceService already has session-level cache (built today)
- Price cache: 5-second TTL (built today)
- Workflows can accept `snapshot: MarketSnapshot | None` to reuse data

## Folder Structure

```
income_desk/workflow/
    __init__.py              # exports all workflow functions
    _types.py                # shared request/response base types
    daily_plan.py            # generate_daily_plan()
    market_snapshot.py       # snapshot_market()
    scan_universe.py         # scan_universe()
    rank_opportunities.py    # rank_opportunities()
    validate_trade.py        # validate_trade()
    size_position.py         # size_position()
    price_trade.py           # price_trade()
    monitor_positions.py     # monitor_positions()
    adjust_position.py       # adjust_position()
    overnight_risk.py        # assess_overnight_risk()
    expiry_day.py            # check_expiry_day()
    portfolio_health.py      # check_portfolio_health()
    profitability_check.py   # check_profitability()
    daily_report.py          # generate_daily_report()
```

## Dependency Flow

```
daily_plan
    ├── scan_universe
    │   └── (ma.regime, ma.technicals, ma.screening)
    ├── rank_opportunities
    │   └── (ma.ranking, ma.vol_surface, ma.opportunity)
    ├── validate_trade (per trade)
    │   └── (validation.run_daily_checks)
    └── size_position (per trade)
        └── (features.position_sizing)

market_snapshot
    └── (ma.market_data.get_underlying_price, get_option_chain, ma.regime.detect)

monitor_positions
    ├── (trade_lifecycle.monitor_exit_conditions)
    ├── (features.exit_intelligence)
    └── market_snapshot (optional, for live prices)

portfolio_health
    ├── (features.crash_sentinel)
    ├── (features.data_trust)
    └── market_snapshot (optional)
```

## eTrading Integration Pattern

```python
# eTrading startup (once per session)
from income_desk.broker.dhan import connect_dhan
md, mm, acct, wl = connect_dhan()
ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm)

# Pre-market
from income_desk.workflow import snapshot_market, generate_daily_plan
snap = snapshot_market(SnapshotRequest(tickers=portfolio_tickers), ma)
plan = generate_daily_plan(DailyPlanRequest(capital=5_000_000, market="India"), ma)

# During market
from income_desk.workflow import monitor_positions
status = monitor_positions(MonitorRequest(positions=open_positions), ma)

# End of day
from income_desk.workflow import assess_overnight_risk, generate_daily_report
risk = assess_overnight_risk(OvernightRiskRequest(positions=held), ma)
report = generate_daily_report(ReportRequest(trades_today=booked, positions=held), ma)
```

## Non-Goals
- Workflows do NOT store state between calls
- Workflows do NOT make broker execution calls (place_order)
- Workflows do NOT manage portfolio persistence
- eTrading owns: auth, DB, execution, position state, scheduling
