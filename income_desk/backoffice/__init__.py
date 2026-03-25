"""Back-Office — business operations reporting and analytics.

Pure computation functions for eTrading's Operations dashboard.
No I/O, no state, no side effects.

Usage::

    from income_desk.backoffice import (
        compute_daily_ops_summary,
        compute_capital_utilization,
        compute_pnl_rollup,
        compute_platform_metrics,
    )
"""

from income_desk.backoffice.ops_reporting import (
    BookedRecord,
    BrokerAccountStatus,
    CapitalUtilization,
    ClosedTradeRecord,
    DailyOpsSummary,
    DeskUtilization,
    PeriodPnL,
    PlatformMetrics,
    PnLRollup,
    RejectionBreakdown,
    ShadowRecord,
    StrategyAttribution,
    TickerAttribution,
    compute_capital_utilization,
    compute_daily_ops_summary,
    compute_platform_metrics,
    compute_pnl_rollup,
)

# Margin requirements (broker-specific)
from income_desk.backoffice.margin import (
    MarginRequirements,
    compute_margin_requirements,
)

# Re-export DecisionRecord with qualified name to avoid collision
# with retrospection.models.DecisionRecord
from income_desk.backoffice.ops_reporting import DecisionRecord as OpsDecisionRecord

__all__ = [
    "BookedRecord",
    "BrokerAccountStatus",
    "CapitalUtilization",
    "ClosedTradeRecord",
    "DailyOpsSummary",
    "DeskUtilization",
    "OpsDecisionRecord",
    "PeriodPnL",
    "PlatformMetrics",
    "PnLRollup",
    "RejectionBreakdown",
    "ShadowRecord",
    "StrategyAttribution",
    "TickerAttribution",
    "compute_capital_utilization",
    "compute_daily_ops_summary",
    "compute_margin_requirements",
    "compute_platform_metrics",
    "compute_pnl_rollup",
    "MarginRequirements",
]
