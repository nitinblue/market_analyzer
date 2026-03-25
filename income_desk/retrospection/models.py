"""Pydantic models for the retrospection contract.

Matches RETROSPECTION_CONTRACT.md exactly.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


# ── eTrading Input Models ──────────────────────────────────────────────


class LegRecord(BaseModel):
    """Single option/equity leg in a trade."""
    symbol: str = ""
    action: str = ""  # STO, BTO, etc.
    quantity: int = 0
    entry_price: float = 0.0
    current_price: float | None = None
    strike: float | None = None
    expiration: str | None = None
    option_type: str | None = None  # call, put, equity
    delta: float | None = None          # Delta at snapshot time (eTrading sends this)
    entry_delta: float | None = None     # Delta at entry (if tracked separately)
    entry_theta: float | None = None
    entry_iv: float | None = None
    current_delta: float | None = None
    theta: float | None = None           # Theta at snapshot time


class EntryAnalytics(BaseModel):
    """Analytics captured at trade entry."""
    pop_at_entry: float | None = None
    ev_at_entry: float | None = None
    regime_at_entry: str | None = None
    income_yield_roc: float | None = None
    breakeven_low: float | None = None
    breakeven_high: float | None = None
    max_profit: float | None = None
    max_loss: float | None = None
    trade_quality: str | None = None
    trade_quality_score: float | None = None
    gate_scale_factor: float | None = None
    data_gaps: list[str] = []


class GateRecord(BaseModel):
    """Single gate pass/fail record."""
    gate: str
    passed: bool
    value: float | None = None
    threshold: float | None = None


class MarketContext(BaseModel):
    """Market context at decision time."""
    regime_id: int | None = None
    vix: float | None = None
    spy_rsi: float | None = None
    black_swan_level: str | None = None


class DecisionLineage(BaseModel):
    """Full decision audit trail."""
    gates: list[GateRecord] = []
    market_context: MarketContext | None = None


class PositionSize(BaseModel):
    """Position sizing details."""
    contracts: int = 0
    kelly_fraction: float | None = None
    capital_at_risk: float = 0.0
    capital_at_risk_pct: float = 0.0


class DecisionRecord(BaseModel):
    """A single decision made by eTrading."""
    id: str = ""
    ticker: str = ""
    strategy: str = ""
    score: float = 0.0
    gate_result: str = ""  # PASS, FAIL
    response: str = ""  # approved, rejected
    regime_at_entry: str | None = None
    pop_at_entry: float | None = None
    ev_at_entry: float | None = None
    income_entry_score: float | None = None
    desk_key: str | None = None
    presented_at: str | None = None
    trade_id: str | None = None
    rationale: Any = None


class TradeOpened(BaseModel):
    """A trade opened during the period."""
    trade_id: str = ""
    ticker: str = ""
    strategy_type: str = ""
    desk_key: str = ""
    market: str = "US"
    entry_price: float = 0.0
    entry_underlying_price: float = 0.0
    opened_at: str = ""
    legs: list[LegRecord] = []
    entry_analytics: EntryAnalytics | None = None
    decision_lineage: DecisionLineage | None = None
    position_size: PositionSize | None = None


class PnLPoint(BaseModel):
    """Single point in PnL journey."""
    ts: str = ""
    pnl_pct: float = 0.0
    delta: float | None = None
    dte: int | None = None


class TradeClosed(BaseModel):
    """A trade closed during the period."""
    trade_id: str = ""
    ticker: str = ""
    strategy_type: str = ""
    desk_key: str = ""
    market: str = "US"
    entry_price: float = 0.0
    exit_price: float = 0.0
    total_pnl: float = 0.0
    pnl_pct: float = 0.0
    holding_days: int = 0
    exit_reason: str = ""
    exit_at: str = ""
    entry_regime: str | None = None
    exit_regime: str | None = None
    max_pnl_during_hold: float | None = None
    min_pnl_during_hold: float | None = None
    pnl_journey: list[PnLPoint] = []


class TradeSnapshot(BaseModel):
    """Current state of an open trade."""
    trade_id: str = ""
    ticker: str = ""
    strategy_type: str = ""
    desk_key: str = ""
    market: str = "US"
    entry_price: float = 0.0
    current_pnl: float = 0.0
    current_pnl_pct: float = 0.0
    dte_remaining: int | None = None
    health_status: str | None = None
    current_delta: float | None = None
    current_theta: float | None = None
    underlying_price_at_entry: float | None = None
    underlying_price_now: float | None = None
    legs: list[LegRecord] = []


class MarkToMarketEvent(BaseModel):
    """A mark-to-market event."""
    timestamp: str = ""
    trades_marked: int = 0
    trades_failed: int = 0
    total_portfolio_pnl: float = 0.0
    pnl_change_since_last_mark: float = 0.0


class ExitSignal(BaseModel):
    """An exit signal triggered."""
    trade_id: str = ""
    ticker: str = ""
    signal_type: str = ""
    severity: str = ""
    message: str = ""
    triggered_at: str = ""
    action_taken: str = ""


class RiskSnapshot(BaseModel):
    """Risk state at a point in time."""
    timestamp: str = ""
    desk_key: str = ""
    portfolio_delta: float = 0.0
    portfolio_theta: float = 0.0
    portfolio_vega: float = 0.0
    var_1d_95: float = 0.0
    capital_deployed_pct: float = 0.0
    positions_open: int = 0
    max_positions: int = 0
    drawdown_pct: float = 0.0
    can_open_new: bool = True


class SystemHealth(BaseModel):
    """System health snapshot."""
    broker_connected: bool = False
    broker_name: str = ""
    data_trust_score: float = 0.0
    unresolved_errors: int = 0
    regression_pass_rate: float = 0.0
    regression_total_checks: int = 0
    stale_positions_count: int = 0


class BanditState(BaseModel):
    """Multi-armed bandit state."""
    total_cells: int = 0
    cells_from_trades: int = 0
    cells_from_priors: int = 0
    top_strategies_by_regime: dict[str, list[str]] = {}


class FeedbackBlocker(BaseModel):
    """Issue blocking eTrading from using ID output."""
    type: str = ""
    ticker: str = ""
    strategy: str = ""
    message: str = ""


class Period(BaseModel):
    """Time period for retrospection."""
    start: str = ""
    end: str = ""
    market_hours: dict[str, dict[str, str]] = {}


class RetrospectionInput(BaseModel):
    """Complete input from eTrading for retrospection analysis."""
    version: str = "1.0"
    generated_at: str = ""
    timeframe: str = "daily"  # daily, weekly, monthly
    period: Period = Field(default_factory=Period)

    decisions: list[DecisionRecord] = []
    trades_opened: list[TradeOpened] = []
    trades_closed: list[TradeClosed] = []
    trades_open_snapshot: list[TradeSnapshot] = []
    mark_to_market_events: list[MarkToMarketEvent] = []
    exit_signals: list[ExitSignal] = []
    risk_snapshots: list[RiskSnapshot] = []
    system_health: SystemHealth = Field(default_factory=SystemHealth)
    bandit_state: BanditState = Field(default_factory=BanditState)
    id_feedback_blockers: list[FeedbackBlocker] = []


# ── ID Feedback Models ─────────────────────────────────────────────────


class MissedOpportunity(BaseModel):
    """A trade that was rejected but would have been profitable."""
    ticker: str = ""
    strategy: str = ""
    score: float = 0.0
    reason_rejected: str = ""
    id_assessment: str = ""
    recommendation: str = ""


class GateConsistency(BaseModel):
    """Gate performance assessment."""
    score_gate_correct: int = 0
    score_gate_wrong: int = 0
    portfolio_filter_correct: int = 0
    missed_opportunities: list[MissedOpportunity] = []


class DecisionAuditResult(BaseModel):
    """Overall decision quality assessment."""
    total_decisions: int = 0
    approved: int = 0
    rejected: int = 0
    approval_rate_pct: float = 0.0
    avg_approved_score: float = 0.0
    avg_rejected_score: float = 0.0
    score_separation: str = ""  # GOOD, POOR, MIXED
    gate_consistency: GateConsistency = Field(default_factory=GateConsistency)


class TradeAuditResult(BaseModel):
    """Per-trade retrospection grade."""
    trade_id: str = ""
    ticker: str = ""
    id_entry_grade: str = ""  # A, B+, B, C, D, F
    id_entry_score: int = 0
    stored_quality_score: float | None = None
    score_match: bool = True
    pnl_verified: bool = True
    pnl_stored: float = 0.0
    pnl_computed: float = 0.0
    entry_timing_grade: str = ""
    strike_placement_grade: str = ""
    sizing_grade: str = ""
    issues: list[str] = []
    improvements: list[str] = []


class DimensionFinding(BaseModel):
    """Single dimension of trade commentary — grade + narrative."""
    dimension: str          # "regime_alignment", "strike_placement", etc.
    grade: str              # A/B/C/D/F
    score: int              # 0-100
    narrative: str          # Human-readable sentence
    details: dict[str, Any] = {}  # Structured data for eTrading rendering


class TradeCommentary(BaseModel):
    """Per-trade narrative commentary — structured for eTrading, readable for humans."""
    trade_id: str
    ticker: str
    strategy: str
    market: str = "US"
    overall_narrative: str              # 2-3 sentence summary
    dimensions: list[DimensionFinding] = []
    should_have_avoided: bool = False
    avoidance_reason: str | None = None
    key_lesson: str | None = None       # One actionable takeaway


class DecisionCommentary(BaseModel):
    """Commentary on the day's decision quality — approval/rejection patterns."""
    near_misses: list[dict[str, Any]] = []        # Score 0.35-0.50, gate rejected
    missed_opportunities: list[dict[str, Any]] = []  # Score >= 0.50, gate rejected
    rejection_summary: dict[str, int] = {}        # Counts by rejection reason
    narrative: str = ""                            # Human-readable summary


class RiskAuditResult(BaseModel):
    """Risk management assessment."""
    portfolio_delta_assessment: str = ""
    theta_harvest_efficiency: str = ""
    var_vs_actual: dict[str, Any] = {}
    concentration_risk: str = ""
    drawdown_status: str = ""


class PnLVerification(BaseModel):
    """PnL accuracy verification."""
    trades_checked: int = 0
    all_match: bool = True
    mismatches: list[dict[str, Any]] = []
    convention_issues: list[str] = []


class BanditFeedback(BaseModel):
    """Bandit/ML feedback."""
    regime_strategy_alignment: str = ""
    exploration_vs_exploitation: str = ""
    recommended_adjustments: list[str] = []


class BlockerResponse(BaseModel):
    """Response to an eTrading-reported blocker."""
    blocker: str = ""
    id_status: str = ""
    workaround: str = ""


class SystemHealthFeedback(BaseModel):
    """System health assessment."""
    data_trust: str = ""
    regression_trend: str = ""
    error_handling: str = ""
    blocker_response: list[BlockerResponse] = []


class LearningRecommendations(BaseModel):
    """Recommendations for ML/AI improvement."""
    ml_updates: list[str] = []
    gate_tuning: list[str] = []
    desk_management: list[str] = []


class RetrospectionFeedback(BaseModel):
    """Complete feedback from ID to eTrading."""
    version: str = "1.0"
    analyzed_at: str = ""
    timeframe: str = "daily"
    period: dict[str, str] = {}

    overall_grade: str = ""  # A, B, C, D, F
    overall_score: int = 0
    summary: str = ""

    decision_audit: DecisionAuditResult = Field(default_factory=DecisionAuditResult)
    trade_audit: list[TradeAuditResult] = []
    risk_audit: RiskAuditResult = Field(default_factory=RiskAuditResult)
    pnl_verification: PnLVerification = Field(default_factory=PnLVerification)
    bandit_feedback: BanditFeedback = Field(default_factory=BanditFeedback)
    system_health_feedback: SystemHealthFeedback = Field(default_factory=SystemHealthFeedback)
    learning_recommendations: LearningRecommendations = Field(default_factory=LearningRecommendations)

    # v1.1: Per-trade narrative commentary
    trade_commentaries: list[TradeCommentary] = []
    decision_commentary: DecisionCommentary | None = None


# ── ID Request Models ──────────────────────────────────────────────────


class DataRequest(BaseModel):
    """A single data request from ID to eTrading."""
    request_id: str = ""
    type: str = ""  # trade_detail, decision_context, desk_history, update_input
    trade_id: str | None = None
    decision_id: str | None = None
    desk_key: str | None = None
    period: str | None = None
    fields_needed: list[str] = []
    reason: str = ""
    message: str | None = None
    corrections: dict[str, str] | None = None


class RetrospectionRequest(BaseModel):
    """Request from ID to eTrading for additional data."""
    version: str = "1.0"
    requested_at: str = ""
    requests: list[DataRequest] = []
