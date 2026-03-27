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
    warnings: list[str] = []

    # Validate inputs
    if request.capital <= 0:
        warnings.append("capital must be positive; defaulting to 0 contracts")
    if request.risk_per_contract <= 0:
        warnings.append("risk_per_contract must be positive; defaulting to 0 contracts")
    if not (0 < request.pop_pct <= 1.0):
        warnings.append(f"pop_pct={request.pop_pct} outside (0,1]; sizing may be unreliable")

    try:
        sz = compute_position_size(
            pop_pct=request.pop_pct, max_profit=request.max_profit,
            max_loss=request.max_loss, capital=request.capital,
            risk_per_contract=request.risk_per_contract,
            regime_id=request.regime_id, wing_width=request.wing_width,
            safety_factor=request.safety_factor, max_contracts=request.max_contracts,
        )
        recommended = sz.recommended_contracts
        kelly_frac = sz.kelly_fraction
    except Exception as e:
        warnings.append(f"Kelly sizing failed: {e}")
        recommended = 0
        kelly_frac = 0.0

    total_risk = recommended * request.risk_per_contract
    return SizeResponse(
        meta=WorkflowMeta(as_of=timestamp, market="", data_source="calculation", warnings=warnings),
        recommended_contracts=recommended,
        kelly_fraction=kelly_frac,
        risk_per_contract=request.risk_per_contract,
        total_risk=total_risk,
        risk_pct_of_capital=total_risk / request.capital if request.capital > 0 else 0,
    )
