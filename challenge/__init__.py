"""$30K Trading Challenge — YAML-backed portfolio tracker.

Usage::

    from challenge.portfolio import Portfolio

    port = Portfolio()
    status = port.get_status()
    check = port.check_risk(trade_spec, contracts=2, entry_price=0.72)
    record = port.book_trade(trade_spec, entry_price=0.72, contracts=2)
    port.close_trade(record.trade_id, exit_price=0.35, reason="profit_target")
"""

from challenge.models import (
    PortfolioStatus,
    RiskCheckResult,
    RiskLimits,
    TradeRecord,
    TradeStatus,
)
from challenge.portfolio import Portfolio

__all__ = [
    "Portfolio",
    "PortfolioStatus",
    "RiskCheckResult",
    "RiskLimits",
    "TradeRecord",
    "TradeStatus",
]
