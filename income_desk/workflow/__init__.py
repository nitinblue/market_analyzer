"""Workflow APIs — high-level trading operations for eTrading.

Each workflow is one function call with a Pydantic request/response.
All rate limiting, caching, and orchestration handled internally.
eTrading never needs to call individual services directly.

15 workflows covering the full trading day::

    # Pre-market
    from income_desk.workflow import generate_daily_plan, snapshot_market

    # Scanning & selection
    from income_desk.workflow import scan_universe, rank_opportunities

    # Trade entry
    from income_desk.workflow import validate_trade, size_position, price_trade

    # Position management
    from income_desk.workflow import monitor_positions, adjust_position, assess_overnight_risk

    # Portfolio risk
    from income_desk.workflow import aggregate_portfolio_greeks, check_portfolio_health

    # Expiry & calendar
    from income_desk.workflow import check_expiry_day

    # Reporting
    from income_desk.workflow import generate_daily_report
"""

# --- Pre-market ---
from income_desk.workflow.daily_plan import (
    DailyPlanRequest,
    DailyPlanResponse,
    generate_daily_plan,
)
from income_desk.workflow.market_snapshot import (
    MarketSnapshot,
    SnapshotRequest,
    snapshot_market,
)

# --- Scanning & selection ---
from income_desk.workflow.scan_universe import (
    ScanRequest,
    ScanResponse,
    scan_universe,
)
from income_desk.workflow.rank_opportunities import (
    RankRequest,
    RankResponse,
    rank_opportunities,
)

# --- Trade entry ---
from income_desk.workflow.validate_trade import (
    ValidateRequest,
    ValidateResponse,
    validate_trade,
)
from income_desk.workflow.size_position import (
    SizeRequest,
    SizeResponse,
    size_position,
)
from income_desk.workflow.price_trade import (
    PriceRequest,
    PriceResponse,
    price_trade,
)

# --- Position management ---
from income_desk.workflow.monitor_positions import (
    MonitorRequest,
    MonitorResponse,
    monitor_positions,
)
from income_desk.workflow.adjust_position import (
    AdjustRequest,
    AdjustResponse,
    adjust_position,
)
from income_desk.workflow.overnight_risk import (
    OvernightRiskRequest,
    OvernightRiskResponse,
    assess_overnight_risk,
)

# --- Portfolio risk ---
from income_desk.workflow.portfolio_greeks import (
    PortfolioGreeksRequest,
    PortfolioGreeksResponse,
    aggregate_portfolio_greeks,
)
from income_desk.workflow.portfolio_health import (
    HealthRequest,
    HealthResponse,
    check_portfolio_health,
)

# --- Expiry & calendar ---
from income_desk.workflow.expiry_day import (
    ExpiryDayRequest,
    ExpiryDayResponse,
    check_expiry_day,
)

# --- Reporting ---
from income_desk.workflow.daily_report import (
    DailyReportRequest,
    DailyReportResponse,
    generate_daily_report,
)

# --- Shared types ---
from income_desk.workflow._types import (
    BlockedTrade,
    OpenPosition,
    PositionStatus,
    TickerRegime,
    TickerSnapshot,
    TradeProposal,
    WorkflowMeta,
)

__all__ = [
    # Functions
    "generate_daily_plan",
    "snapshot_market",
    "scan_universe",
    "rank_opportunities",
    "validate_trade",
    "size_position",
    "price_trade",
    "monitor_positions",
    "adjust_position",
    "assess_overnight_risk",
    "aggregate_portfolio_greeks",
    "check_portfolio_health",
    "check_expiry_day",
    "generate_daily_report",
    # Request types
    "DailyPlanRequest",
    "SnapshotRequest",
    "ScanRequest",
    "RankRequest",
    "ValidateRequest",
    "SizeRequest",
    "PriceRequest",
    "MonitorRequest",
    "AdjustRequest",
    "OvernightRiskRequest",
    "PortfolioGreeksRequest",
    "HealthRequest",
    "ExpiryDayRequest",
    "DailyReportRequest",
    # Response types
    "DailyPlanResponse",
    "MarketSnapshot",
    "ScanResponse",
    "RankResponse",
    "ValidateResponse",
    "SizeResponse",
    "PriceResponse",
    "MonitorResponse",
    "AdjustResponse",
    "OvernightRiskResponse",
    "PortfolioGreeksResponse",
    "HealthResponse",
    "ExpiryDayResponse",
    "DailyReportResponse",
    # Shared types
    "WorkflowMeta",
    "TradeProposal",
    "BlockedTrade",
    "TickerRegime",
    "TickerSnapshot",
    "OpenPosition",
    "PositionStatus",
]
