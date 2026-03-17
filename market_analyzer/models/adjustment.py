"""Pydantic models for trade adjustment analysis."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel

from market_analyzer.models.opportunity import LegSpec, TradeSpec


class AdjustmentType(StrEnum):
    """Types of trade adjustments."""

    DO_NOTHING = "do_nothing"
    CLOSE_FULL = "close_full"
    ROLL_OUT = "roll_out"
    ROLL_AWAY = "roll_away"
    NARROW_UNTESTED = "narrow_untested"
    ADD_WING = "add_wing"
    CONVERT = "convert"


class PositionStatus(StrEnum):
    """Current status of the position relative to short strikes."""

    SAFE = "safe"
    TESTED = "tested"
    BREACHED = "breached"
    MAX_LOSS = "max_loss"


class TestedSide(StrEnum):
    """Which side of the position is under pressure."""

    NONE = "none"
    PUT = "put"
    CALL = "call"
    BOTH = "both"


class AdjustmentOption(BaseModel):
    """A single ranked adjustment alternative."""

    adjustment_type: AdjustmentType
    description: str
    new_legs: list[LegSpec]
    close_legs: list[LegSpec]
    mid_cost: float | None  # Net cost from broker mid prices. None = DXLink fetch failed
    risk_change: float
    efficiency: float | None
    urgency: str
    rationale: str


class AdjustmentDecision(BaseModel):
    """Single deterministic adjustment action for systematic trading.

    Unlike AdjustmentAnalysis (which provides a ranked menu of options for
    human review), this model returns exactly ONE action chosen by a
    deterministic decision tree based on position status and regime.
    """

    action: AdjustmentType  # DO_NOTHING, CLOSE_FULL, ROLL_AWAY, etc.
    urgency: str  # "none", "monitor", "soon", "immediate"
    rationale: str  # Why this specific action
    detail: AdjustmentOption | None  # Full adjustment option if action != DO_NOTHING/CLOSE_FULL
    position_status: PositionStatus
    regime_id: int


class AdjustmentAnalysis(BaseModel):
    """Complete adjustment analysis for an open trade."""

    ticker: str
    as_of_date: date
    original_trade: TradeSpec
    current_price: float
    position_status: PositionStatus
    tested_side: TestedSide
    distance_to_short_put_pct: float | None
    distance_to_short_call_pct: float | None
    mark_pnl: float | None  # P&L at current broker mid (mark-to-market). None = DXLink fetch failed
    remaining_dte: int
    regime_id: int
    adjustments: list[AdjustmentOption]
    recommendation: str
    summary: str
