"""Daily Report — end-of-day trading summary."""
from __future__ import annotations
from datetime import date, datetime
from pydantic import BaseModel
from income_desk.workflow._types import WorkflowMeta

class TradeRecord(BaseModel):
    ticker: str
    structure: str
    action: str  # "opened", "closed", "adjusted"
    pnl: float = 0.0
    contracts: int = 1
    entry_price: float = 0.0
    exit_price: float | None = None

class DailyReportRequest(BaseModel):
    trades_today: list[TradeRecord]
    positions_open: int = 0
    capital: float = 5_000_000
    total_risk_deployed: float = 0.0
    regime_summary: dict[str, int] = {}  # {ticker: regime_id}
    market: str = "India"

class DailyReportResponse(BaseModel):
    meta: WorkflowMeta
    date: str
    trades_opened: int
    trades_closed: int
    trades_adjusted: int
    realized_pnl: float
    win_count: int
    loss_count: int
    win_rate: float | None
    best_trade: str
    worst_trade: str
    risk_deployed_pct: float
    positions_open: int
    summary: str

def generate_daily_report(request: DailyReportRequest, ma: "object | None" = None) -> DailyReportResponse:
    """Generate end-of-day trading summary."""
    timestamp = datetime.now()
    today_str = date.today().isoformat()

    opened = [t for t in request.trades_today if t.action == "opened"]
    closed = [t for t in request.trades_today if t.action == "closed"]
    adjusted = [t for t in request.trades_today if t.action == "adjusted"]

    realized = sum(t.pnl for t in closed)
    winners = [t for t in closed if t.pnl > 0]
    losers = [t for t in closed if t.pnl < 0]
    win_rate = len(winners) / len(closed) if closed else None

    best = max(closed, key=lambda t: t.pnl).ticker if closed else "none"
    worst = min(closed, key=lambda t: t.pnl).ticker if closed else "none"
    risk_pct = request.total_risk_deployed / request.capital if request.capital > 0 else 0

    currency = "INR" if request.market == "India" else "USD"
    parts = [
        f"{len(opened)} opened, {len(closed)} closed, {len(adjusted)} adjusted.",
        f"Realized P&L: {currency} {realized:,.0f}.",
    ]
    if win_rate is not None:
        parts.append(f"Win rate: {win_rate:.0%}.")
    parts.append(f"{request.positions_open} positions open, {risk_pct:.1%} risk deployed.")
    summary = " ".join(parts)

    return DailyReportResponse(
        meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source="records"),
        date=today_str, trades_opened=len(opened), trades_closed=len(closed),
        trades_adjusted=len(adjusted), realized_pnl=realized,
        win_count=len(winners), loss_count=len(losers), win_rate=win_rate,
        best_trade=best, worst_trade=worst, risk_deployed_pct=risk_pct,
        positions_open=request.positions_open, summary=summary,
    )
