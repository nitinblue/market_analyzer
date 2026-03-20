"""Pydantic models for exit intelligence."""

from __future__ import annotations

from pydantic import BaseModel


class RegimeStop(BaseModel):
    """Regime-contingent stop-loss multiplier."""

    regime_id: int
    base_multiplier: float
    structure_type: str
    rationale: str


class TimeAdjustedTarget(BaseModel):
    """Time-based profit target acceleration."""

    original_target_pct: float
    adjusted_target_pct: float
    days_held: int
    dte_at_entry: int
    time_elapsed_pct: float
    profit_velocity: float
    acceleration_reason: str | None  # None if no adjustment


class ThetaDecayResult(BaseModel):
    """Theta decay curve comparison for hold vs close decision."""

    dte_remaining: int
    dte_at_entry: int
    remaining_theta_pct: float  # 0-1, how much theta is left (sqrt approximation)
    current_profit_pct: float
    profit_to_theta_ratio: float
    recommendation: str  # "hold" / "close_and_redeploy" / "approaching_decay_cliff"
    rationale: str
