"""Models for multi-level trade decision audit."""
from __future__ import annotations
from pydantic import BaseModel


class GradedCheck(BaseModel):
    """Single audit check with score and commentary."""
    name: str
    score: float  # 0-100
    grade: str  # A/B+/B/C/D/F
    detail: str


class LegAudit(BaseModel):
    """Audit of a single option leg."""
    role: str  # "short_put", "long_call", etc.
    strike: float
    checks: list[GradedCheck]
    score: float  # 0-100 average
    grade: str


class TradeAudit(BaseModel):
    """Audit of the overall trade structure."""
    checks: list[GradedCheck]
    score: float
    grade: str


class PortfolioAudit(BaseModel):
    """Audit of how trade fits the portfolio."""
    checks: list[GradedCheck]
    score: float
    grade: str


class RiskAudit(BaseModel):
    """Audit of risk management quality."""
    checks: list[GradedCheck]
    score: float
    grade: str


class DecisionReport(BaseModel):
    """Complete multi-level trade decision audit."""
    ticker: str
    structure_type: str
    leg_audit: LegAudit | None  # None if no legs to audit
    trade_audit: TradeAudit
    portfolio_audit: PortfolioAudit
    risk_audit: RiskAudit
    overall_score: float  # Weighted average
    overall_grade: str
    approved: bool  # True if overall >= 70
    summary: str
