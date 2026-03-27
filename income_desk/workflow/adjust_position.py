"""Adjust Position — recommend adjustment for one open position."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel
from income_desk.workflow._types import WorkflowMeta

class AdjustRequest(BaseModel):
    trade_id: str
    ticker: str
    structure_type: str
    order_side: str
    entry_price: float
    current_mid_price: float
    contracts: int = 1
    dte_remaining: int = 30
    regime_id: int = 1
    pnl_pct: float = 0.0

class AdjustmentAction(BaseModel):
    action: str  # "hold", "close", "roll_out", "roll_up", "roll_down", "widen", "add_hedge"
    urgency: str  # "low", "medium", "high"
    rationale: str
    target_dte: int | None = None
    target_strike_delta: float | None = None

class AdjustResponse(BaseModel):
    meta: WorkflowMeta
    trade_id: str
    ticker: str
    recommendation: AdjustmentAction
    alternatives: list[AdjustmentAction]

def adjust_position(request: AdjustRequest, ma: "object | None" = None) -> AdjustResponse:
    """Recommend adjustment for a position."""
    timestamp = datetime.now()

    # Determine adjustment based on P&L, DTE, regime
    action = "hold"
    urgency = "low"
    rationale = "Position within parameters"
    alternatives = []

    # Close if profit target hit
    if request.pnl_pct >= 0.50:
        action = "close"
        urgency = "medium"
        rationale = f"Profit target reached ({request.pnl_pct:.0%})"
        alternatives.append(AdjustmentAction(
            action="hold", urgency="low",
            rationale="Let remaining theta decay — risk increases",
        ))
    # Close if stop hit
    elif request.pnl_pct <= -1.0:
        action = "close"
        urgency = "high"
        rationale = f"Stop loss triggered ({request.pnl_pct:.0%})"
    # Roll if low DTE
    elif request.dte_remaining <= 5 and request.pnl_pct < 0.30:
        action = "roll_out"
        urgency = "medium"
        rationale = f"Low DTE ({request.dte_remaining}d) with unrealized profit < 30%"
        alternatives.append(AdjustmentAction(
            action="close", urgency="medium",
            rationale="Take current P&L and redeploy capital",
        ))
    # Regime change warning
    elif request.regime_id == 4:
        action = "close"
        urgency = "high"
        rationale = "Regime shifted to R4 — close income positions"

    return AdjustResponse(
        meta=WorkflowMeta(as_of=timestamp, market="", data_source="calculation"),
        trade_id=request.trade_id, ticker=request.ticker,
        recommendation=AdjustmentAction(action=action, urgency=urgency, rationale=rationale),
        alternatives=alternatives,
    )
