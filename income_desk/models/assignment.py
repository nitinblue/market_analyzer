"""Models for assignment/exercise event handling."""
from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from income_desk.models.opportunity import TradeSpec


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


# ---------------------------------------------------------------------------
# Cash-Secured Put (CSP) models — BEFORE assignment (intentional entry)
# ---------------------------------------------------------------------------


class CSPIntent(StrEnum):
    """Why are you selling this put?"""

    ACQUIRE_STOCK = "acquire_stock"   # Want to own the stock at strike price
    INCOME_ONLY = "income_only"       # Just want premium, don't want stock
    WHEEL_ENTRY = "wheel_entry"       # First leg of wheel strategy (CSP → assignment → CC)


class CSPAnalysis(BaseModel):
    """Analysis of a cash-secured put trade."""

    ticker: str
    strike: float
    expiration: date
    dte: int
    intent: CSPIntent

    # Economics
    premium_collected: float                     # Credit per share
    effective_buy_price: float                   # strike - premium (cost basis if assigned)
    discount_from_current_pct: float             # How much cheaper than current price
    annualized_yield_if_not_assigned: float      # Premium / cash_secured * (365/DTE)

    # Cash requirement
    cash_to_secure: float                        # strike * lot_size (full cash, no margin)
    margin_to_secure: float                      # With margin (typically 20-25% of cash)

    # Assignment probability
    assignment_probability: str                  # "low" (<30%), "moderate" (30-60%), "high" (>60%)

    # If assigned: what's the plan?
    post_assignment_plan: str                    # "hold_long_term", "sell_covered_call", "sell_immediately"
    covered_call_spec: TradeSpec | None          # Pre-built CC for after assignment

    # Risk
    max_loss: float                              # strike * lot_size - premium (stock goes to $0)
    breakeven: float                             # strike - premium

    # Decision
    trade_spec: TradeSpec                        # The CSP order itself
    margin_analysis: dict[str, Any] | None       # Cash vs margin breakdown

    summary: str


class CoveredCallAnalysis(BaseModel):
    """Analysis for selling a covered call against owned shares."""

    ticker: str
    shares_owned: int
    cost_basis: float                  # Cost per share
    current_price: float

    # Recommended call
    call_strike: float
    call_expiration: date
    call_dte: int
    estimated_premium: float

    # Scenarios
    if_called_away_profit: float       # (strike - cost_basis + premium) * shares
    if_called_away_pct: float
    if_not_called_income: float        # Premium only
    annualized_yield: float

    # Risk
    upside_cap: float                  # Max price you benefit from = strike
    downside_from_current: float       # Still exposed to stock decline

    # Decision
    trade_spec: TradeSpec              # The CC order
    summary: str
