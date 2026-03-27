"""Size Position — Kelly criterion with lot-size awareness."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel
from income_desk.workflow._types import WorkflowMeta

class SizeRequest(BaseModel):
    pop_pct: float
    max_profit: float
    max_loss: float
    capital: float
    risk_per_contract: float
    regime_id: int = 1
    wing_width: float = 5.0
    safety_factor: float = 0.5
    max_contracts: int = 20

class SizeResponse(BaseModel):
    meta: WorkflowMeta
    recommended_contracts: int
    kelly_fraction: float
    risk_per_contract: float
    total_risk: float
    risk_pct_of_capital: float

def size_position(request: SizeRequest, ma: "object | None" = None) -> SizeResponse:
    """Compute position size via Kelly criterion."""
    from income_desk.features.position_sizing import compute_position_size
    timestamp = datetime.now()

    sz = compute_position_size(
        pop_pct=request.pop_pct, max_profit=request.max_profit,
        max_loss=request.max_loss, capital=request.capital,
        risk_per_contract=request.risk_per_contract,
        regime_id=request.regime_id, wing_width=request.wing_width,
        safety_factor=request.safety_factor, max_contracts=request.max_contracts,
    )

    total_risk = sz.recommended_contracts * request.risk_per_contract
    return SizeResponse(
        meta=WorkflowMeta(as_of=timestamp, market="", data_source="calculation"),
        recommended_contracts=sz.recommended_contracts,
        kelly_fraction=sz.kelly_fraction,
        risk_per_contract=request.risk_per_contract,
        total_risk=total_risk,
        risk_pct_of_capital=total_risk / request.capital if request.capital > 0 else 0,
    )
