# ID Request: Operations Reporting Functions

**From:** eTrading (session 48, 2026-03-24)
**To:** income-desk library
**Purpose:** Back-office / business operations reporting — pure computation functions

---

## Context

eTrading is building a Business Operations reporting suite (Daily Ops, Capital & Desks, P&L Rollup, Platform). Per the "zero calculations in eTrading" rule, all computation lives in income-desk. eTrading queries DB, constructs inputs, calls these functions, serves results via API.

---

## Requested Functions

### 1. `compute_daily_ops_summary()`

Summarizes a single day's pipeline activity — decisions, approvals, rejections, shadow trades.

```python
class DecisionRecord(BaseModel):
    """Single pipeline decision (entry/exit/adjustment)."""
    ticker: str
    strategy: str
    score: float | None
    response: str              # "approved" or "rejected"
    gate_result: str | None    # "PASS", "NO_GO verdict", etc.
    timestamp: str

class ShadowRecord(BaseModel):
    """Trade that scored well but got blocked by a gate."""
    ticker: str
    structure: str
    score: float
    blocked_by: str            # human-readable reason

class BookedRecord(BaseModel):
    """Trade that made it through all gates and was booked."""
    ticker: str
    strategy: str
    score: float
    entry_price: float
    trade_type: str            # "what_if", "real"

class RejectionBreakdown(BaseModel):
    """Categorized rejection reasons with counts."""
    reason: str
    count: int
    pct: float

class DailyOpsSummary(BaseModel):
    """Full daily pipeline summary."""
    date: str
    total_decisions: int
    approved: int
    rejected: int
    approval_rate: float       # 0.0-1.0
    shadow_count: int
    booked_count: int
    rejections_by_reason: list[RejectionBreakdown]
    shadows: list[ShadowRecord]
    booked: list[BookedRecord]
    top_rejection_reason: str
    opportunity_cost_note: str  # "6 trades with score > 0.60 blocked"

def compute_daily_ops_summary(
    decisions: list[DecisionRecord],
    shadows: list[ShadowRecord],
    booked: list[BookedRecord],
) -> DailyOpsSummary:
    """Pure computation: summarize a day's pipeline activity."""
```

### 2. `compute_capital_utilization()`

Portfolio-level capital deployment analysis across desks.

```python
class DeskUtilization(BaseModel):
    """Single desk's capital usage."""
    desk_name: str
    allocated_capital: float
    deployed_capital: float     # sum of max_risk for open trades
    utilization_pct: float      # deployed / allocated
    open_positions: int
    position_limit: int
    position_utilization_pct: float
    realized_pnl: float         # closed trades P&L
    unrealized_pnl: float       # open trades P&L

class BrokerAccountStatus(BaseModel):
    """Broker connection status."""
    broker_name: str
    account_id: str
    connected: bool
    portfolio_name: str

class CapitalUtilization(BaseModel):
    """Full capital deployment picture."""
    total_allocated: float
    total_deployed: float
    total_utilization_pct: float
    total_open_positions: int
    total_realized_pnl: float
    total_unrealized_pnl: float
    desks: list[DeskUtilization]
    brokers: list[BrokerAccountStatus]

def compute_capital_utilization(
    desks: list[DeskUtilization],
    brokers: list[BrokerAccountStatus],
) -> CapitalUtilization:
    """Pure computation: aggregate desk-level capital data."""
```

### 3. `compute_pnl_rollup()`

Time-bucketed P&L with strategy attribution.

```python
class PeriodPnL(BaseModel):
    """P&L for a single time period."""
    period_label: str           # "2026-03-24", "Week 12", "March 2026"
    period_start: str
    period_end: str
    closed_trades: int
    winners: int
    losers: int
    win_rate: float
    total_pnl: float
    cumulative_pnl: float

class StrategyAttribution(BaseModel):
    """P&L attributed to a single strategy."""
    strategy: str
    trade_count: int
    total_pnl: float
    win_rate: float
    avg_pnl_per_trade: float

class TickerAttribution(BaseModel):
    """P&L attributed to a single underlying."""
    ticker: str
    trade_count: int
    total_pnl: float

class PnLRollup(BaseModel):
    """Full P&L rollup with attribution."""
    period_type: str            # "daily", "weekly", "monthly"
    periods: list[PeriodPnL]
    by_strategy: list[StrategyAttribution]
    by_ticker: list[TickerAttribution]
    total_pnl: float
    total_closed: int
    overall_win_rate: float
    best_trade: TickerAttribution | None
    worst_trade: TickerAttribution | None

def compute_pnl_rollup(
    trades: list[dict],         # closed trade records with pnl, strategy, ticker, dates
    period_type: str = "daily", # "daily", "weekly", "monthly"
) -> PnLRollup:
    """Pure computation: bucket P&L by time period with attribution."""
```

### 4. `compute_platform_metrics()`

Waitlist, user progression, model portfolio health.

```python
class PlatformMetrics(BaseModel):
    """Platform business metrics."""
    waitlist_total: int
    waitlist_this_week: int
    knack_by_step: dict[int, int]  # step_number → user_count
    model_portfolio_open: int
    model_portfolio_pnl: float
    model_portfolio_win_rate: float | None

def compute_platform_metrics(
    waitlist_total: int,
    waitlist_this_week: int,
    knack_progress: dict[int, int],
    model_trades_open: int,
    model_trades_closed_pnl: float,
    model_trades_win_rate: float | None,
) -> PlatformMetrics:
    """Pure computation: aggregate platform business metrics."""
```

---

## Integration Pattern

eTrading will:
1. Query DB for raw data (decisions, trades, desks, etc.)
2. Construct input models (DecisionRecord, DeskUtilization, etc.)
3. Call `compute_*()` functions
4. Serve results via `/api/reports/ops/*` endpoints
5. Render in React Operations tab

## Coding Standards

- Pydantic BaseModel for all inputs/outputs
- Pure functions, no I/O, no state
- All imports at top
- Null over fake values
- Add to `__init__.py` exports
- Place in `income_desk/ops_reporting.py` (new file)
