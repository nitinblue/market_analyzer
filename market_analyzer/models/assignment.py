"""Models for assignment/exercise event handling."""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel

from market_analyzer.models.opportunity import TradeSpec


class AssignmentType(StrEnum):
    PUT_ASSIGNED = "put_assigned"      # Short put exercised → you bought 100 shares
    CALL_ASSIGNED = "call_assigned"    # Short call exercised → you sold/shorted 100 shares
    LONG_EXERCISED = "long_exercised"  # You chose to exercise your long option


# ---------------------------------------------------------------------------
# Assignment RISK models (BEFORE assignment — early warning)
# ---------------------------------------------------------------------------


class AssignmentRisk(StrEnum):
    NONE = "none"           # Short options are OTM
    LOW = "low"             # Slightly ITM but time value protects
    MODERATE = "moderate"   # ITM, approaching expiry or dividend
    HIGH = "high"           # Deep ITM, near expiry, likely assigned
    IMMINENT = "imminent"   # <2 DTE, ITM, expect assignment tonight


class AssignmentRiskResult(BaseModel):
    """Result of assessing assignment risk on active short options — BEFORE assignment happens."""

    ticker: str
    risk_level: AssignmentRisk
    at_risk_legs: list[dict]    # [{role, strike, itm_amount, itm_pct, risk_level}]
    exercise_style: str         # "american" or "european"
    urgency: str                # "none", "monitor", "prepare", "act_now"
    reasons: list[str]
    recommended_action: str     # "hold", "roll_before_expiry", "close_itm_leg", "prepare_for_assignment"
    response_trade_spec: TradeSpec | None = None  # Roll or close spec if action needed

    # India-specific
    european_note: str | None = None  # "European style — assignment only at expiry, not before"


class AssignmentAction(StrEnum):
    SELL_IMMEDIATELY = "sell_immediately"       # Sell assigned shares ASAP
    HOLD_AND_WHEEL = "hold_and_wheel"           # Keep shares, sell covered call
    HOLD_CORE = "hold_core"                     # Keep as core equity position
    PARTIAL_SELL = "partial_sell"               # Sell some, keep some
    COVER_SHORT = "cover_short"                 # Buy back shares if short assigned


class AssignmentAnalysis(BaseModel):
    """Complete analysis of an assignment event."""

    ticker: str
    assignment_type: AssignmentType
    shares: int                          # Usually 100 per contract
    assignment_price: float              # Strike price where assigned
    current_price: float

    # P&L from assignment
    unrealized_pnl: float                # (current - assignment) * shares (put) or reverse (call)
    unrealized_pnl_pct: float

    # Capital impact
    capital_tied_up: float               # assignment_price * shares
    capital_pct_of_nlv: float            # What % of account this represents
    margin_impact: str                   # "within_limits" / "margin_warning" / "margin_call"

    # Decision
    recommended_action: AssignmentAction
    urgency: str                         # "immediate", "today", "this_week"
    reasons: list[str]

    # Concrete TradeSpec for the recommended action
    response_trade_spec: TradeSpec | None = None   # Sell order, covered call, etc.

    # If wheel strategy recommended
    wheel_trade_spec: TradeSpec | None = None      # Covered call to sell against shares
    wheel_rationale: str | None = None

    # Trust
    regime_id: int
    regime_rationale: str
