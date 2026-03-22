"""Pydantic models for exit intelligence."""

from __future__ import annotations

from typing import Any

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


class MonitoringAction(BaseModel):
    """Concrete action from position monitoring — includes closing TradeSpec when applicable.

    Returned by ``compute_monitoring_action()``.  When ``action == "close"``,
    ``closing_trade_spec`` contains the exact inverse legs needed to close the
    position at the broker.

    ``closing_trade_spec`` is typed ``Any`` to avoid a circular import between
    ``models/exit.py`` and ``models/opportunity.py``.  At runtime it holds a
    ``TradeSpec`` instance (or ``None``).  Callers can safely use it as such.
    Pydantic will serialise it correctly via ``model_dump()`` since TradeSpec
    is itself a Pydantic model.
    """

    model_config = {"arbitrary_types_allowed": True}

    action: str              # "hold", "close", "adjust", "hedge"
    urgency: str             # "none", "monitor", "soon", "immediate"
    reason: str              # Why this action
    closing_trade_spec: Any = None   # TradeSpec | None at runtime
    stress_report: dict | None = None  # Serialised PositionStressReport

    @property
    def has_closing_order(self) -> bool:
        """True when a concrete closing TradeSpec is attached."""
        return self.closing_trade_spec is not None
