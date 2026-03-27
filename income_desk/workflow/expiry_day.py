"""Expiry Day — expiry-day-specific logic for India/US markets."""
from __future__ import annotations
from datetime import date, datetime
from pydantic import BaseModel
from income_desk.workflow._types import OpenPosition, WorkflowMeta

class ExpiryDayRequest(BaseModel):
    positions: list[OpenPosition]
    market: str = "India"
    today: date | None = None

class ExpiryPosition(BaseModel):
    trade_id: str
    ticker: str
    is_expiry_today: bool
    urgency: str  # "none", "monitor", "close_before_close", "critical"
    action: str
    deadline: str = ""  # "15:00 IST" or "15:30 IST"
    rationale: str = ""

class ExpiryDayResponse(BaseModel):
    meta: WorkflowMeta
    expiry_index: str | None  # "NIFTY", "BANKNIFTY", "FINNIFTY" or None
    positions: list[ExpiryPosition]
    expiry_positions_count: int
    critical_count: int

def check_expiry_day(request: ExpiryDayRequest, ma: "object | None" = None) -> ExpiryDayResponse:
    """Check expiry-day positions and urgency."""
    today = request.today or date.today()
    timestamp = datetime.now()
    weekday = today.strftime("%A")

    expiry_map = {"Tuesday": "FINNIFTY", "Wednesday": "BANKNIFTY", "Thursday": "NIFTY"}
    expiry_index = expiry_map.get(weekday)

    positions = []
    for pos in request.positions:
        is_expiry = pos.dte_remaining == 0 or (expiry_index and pos.ticker == expiry_index)

        if is_expiry:
            urgency = "close_before_close"
            action = "close"
            deadline = "15:00 IST" if request.market == "India" else "15:45 ET"
            rationale = f"Expiry day — close before {deadline} to avoid settlement risk"
            if pos.regime_id == 4:
                urgency = "critical"
                rationale = f"R4 + expiry day — CLOSE IMMEDIATELY"
        elif pos.dte_remaining <= 1:
            urgency = "monitor"
            action = "monitor"
            deadline = ""
            rationale = "Expiry tomorrow — prepare exit plan"
        else:
            urgency = "none"
            action = "hold"
            deadline = ""
            rationale = ""

        positions.append(ExpiryPosition(
            trade_id=pos.trade_id, ticker=pos.ticker,
            is_expiry_today=is_expiry, urgency=urgency,
            action=action, deadline=deadline, rationale=rationale,
        ))

    return ExpiryDayResponse(
        meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source="calendar"),
        expiry_index=expiry_index, positions=positions,
        expiry_positions_count=sum(1 for p in positions if p.is_expiry_today),
        critical_count=sum(1 for p in positions if p.urgency == "critical"),
    )
