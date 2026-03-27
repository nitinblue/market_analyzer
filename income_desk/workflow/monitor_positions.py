"""Monitor Positions — exit signals and P&L for all open positions."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel
from income_desk.workflow._types import OpenPosition, PositionStatus, WorkflowMeta

class MonitorRequest(BaseModel):
    positions: list[OpenPosition]
    market: str = "India"

class MonitorResponse(BaseModel):
    meta: WorkflowMeta
    statuses: list[PositionStatus]
    actions_needed: int  # count of non-"hold" positions
    critical_count: int  # count of "critical" urgency

def monitor_positions(request: MonitorRequest, ma: "object | None" = None) -> MonitorResponse:
    """Check exit conditions for all open positions."""
    from income_desk.trade_lifecycle import monitor_exit_conditions
    from income_desk.features.exit_intelligence import (
        compute_regime_stop, compute_remaining_theta_value, compute_time_adjusted_target,
    )

    timestamp = datetime.now()
    warnings = []
    statuses = []

    for pos in request.positions:
        try:
            result = monitor_exit_conditions(
                trade_id=pos.trade_id, ticker=pos.ticker,
                structure_type=pos.structure_type, order_side=pos.order_side,
                entry_price=pos.entry_price,
                current_mid_price=pos.current_mid_price or pos.entry_price * 0.7,
                contracts=pos.contracts, dte_remaining=pos.dte_remaining,
                regime_id=pos.regime_id, profit_target_pct=pos.profit_target_pct,
                stop_loss_pct=pos.stop_loss_pct, exit_dte=pos.exit_dte,
                lot_size=pos.lot_size,
            )

            stop = compute_regime_stop(pos.regime_id)
            theta = compute_remaining_theta_value(
                pos.dte_remaining, pos.dte_remaining + 10, 0.30,
            )

            action = result.action if hasattr(result, 'action') else "hold"
            urgency = "low"
            if action in ("close", "close_and_redeploy"):
                urgency = "high"
            if pos.dte_remaining <= 1:
                urgency = "critical"

            statuses.append(PositionStatus(
                trade_id=pos.trade_id, ticker=pos.ticker,
                action=action, urgency=urgency,
                pnl=result.pnl_dollars if hasattr(result, 'pnl_dollars') else 0,
                pnl_pct=result.pnl_pct if hasattr(result, 'pnl_pct') else 0,
                profit_target=f"{pos.profit_target_pct:.0%}",
                stop_level=f"{stop.base_multiplier}x",
                theta_recommendation=theta.recommendation if hasattr(theta, 'recommendation') else "hold",
                rationale=result.rationale if hasattr(result, 'rationale') else "",
            ))
        except Exception as e:
            warnings.append(f"{pos.ticker}: monitoring failed: {e}")
            statuses.append(PositionStatus(
                trade_id=pos.trade_id, ticker=pos.ticker,
                action="review", urgency="medium", rationale=f"Error: {e}",
            ))

    actions_needed = sum(1 for s in statuses if s.action != "hold")
    critical = sum(1 for s in statuses if s.urgency == "critical")

    return MonitorResponse(
        meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source="calculation", warnings=warnings),
        statuses=statuses, actions_needed=actions_needed, critical_count=critical,
    )
