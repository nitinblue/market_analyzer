"""Trading Activity Retrospection — ID-side analysis engine.

Polls for eTrading input, performs independent analysis, writes feedback.

Contract: see RETROSPECTION_CONTRACT.md

Usage::

    from income_desk.retrospection import RetrospectionEngine

    engine = RetrospectionEngine()
    engine.poll_and_analyze()  # One-shot: read input, analyze, write feedback
"""

from income_desk.retrospection.engine import (
    RetrospectionEngine,
    RetrospectionResult,
)
from income_desk.retrospection.models import (
    DecisionAuditResult,
    DecisionCommentary,
    DecisionRecord,
    DimensionFinding,
    RetrospectionFeedback,
    RetrospectionInput,
    RetrospectionRequest,
    RiskSnapshot,
    TradeAuditResult,
    TradeClosed,
    TradeCommentary,
    TradeOpened,
    TradeSnapshot,
)

__all__ = [
    "RetrospectionEngine",
    "RetrospectionResult",
    "RetrospectionInput",
    "RetrospectionFeedback",
    "RetrospectionRequest",
    "DecisionRecord",
    "TradeOpened",
    "TradeClosed",
    "TradeSnapshot",
    "RiskSnapshot",
    "TradeAuditResult",
    "DecisionAuditResult",
    "DimensionFinding",
    "TradeCommentary",
    "DecisionCommentary",
]
