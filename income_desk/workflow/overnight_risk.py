"""Overnight Risk — end-of-day risk assessment for held positions."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel
from income_desk.workflow._types import OpenPosition, WorkflowMeta

class OvernightRiskRequest(BaseModel):
    positions: list[OpenPosition]
    market: str = "India"

class OvernightRiskEntry(BaseModel):
    trade_id: str
    ticker: str
    risk_level: str  # "low", "medium", "high", "close_before_close"
    action: str
    rationale: str = ""

class OvernightRiskResponse(BaseModel):
    meta: WorkflowMeta
    entries: list[OvernightRiskEntry]
    high_risk_count: int
    close_before_close_count: int

def assess_overnight_risk(request: OvernightRiskRequest, ma: "object | None" = None) -> OvernightRiskResponse:
    """Assess overnight risk for all held positions."""
    from income_desk.trade_lifecycle import assess_overnight_risk as _assess

    timestamp = datetime.now()
    entries = []

    for pos in request.positions:
        try:
            result = _assess(
                trade_id=pos.trade_id, ticker=pos.ticker,
                structure_type=pos.structure_type, order_side=pos.order_side,
                dte_remaining=pos.dte_remaining, regime_id=pos.regime_id,
                position_status=pos.position_status,
            )
            entries.append(OvernightRiskEntry(
                trade_id=pos.trade_id, ticker=pos.ticker,
                risk_level=result.risk_level,
                action=result.action if hasattr(result, 'action') else "hold",
                rationale=result.rationale if hasattr(result, 'rationale') else "",
            ))
        except Exception as e:
            entries.append(OvernightRiskEntry(
                trade_id=pos.trade_id, ticker=pos.ticker,
                risk_level="medium", action="review", rationale=str(e),
            ))

    return OvernightRiskResponse(
        meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source="calculation"),
        entries=entries,
        high_risk_count=sum(1 for e in entries if e.risk_level in ("high", "close_before_close")),
        close_before_close_count=sum(1 for e in entries if e.risk_level == "close_before_close"),
    )
