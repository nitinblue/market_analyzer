"""Validate Trade — run 10-check gate on a TradeSpec."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel
from income_desk.workflow._types import WorkflowMeta

class ValidateRequest(BaseModel):
    ticker: str
    entry_credit: float
    regime_id: int
    atr_pct: float
    current_price: float
    dte: int = 30
    rsi: float = 50.0
    iv_rank: float = 50.0
    contracts: int = 1
    avg_bid_ask_spread_pct: float = 0.03
    trade_spec: object | None = None  # TradeSpec if available

class GateResult(BaseModel):
    name: str
    passed: bool
    severity: str  # "pass", "warn", "fail"
    detail: str = ""

class ValidateResponse(BaseModel):
    meta: WorkflowMeta
    is_ready: bool
    gates: list[GateResult]
    failed_gates: list[str]
    warnings: list[str]

def validate_trade(request: ValidateRequest, ma: "object | None" = None) -> ValidateResponse:
    """Run 10-check validation gate."""
    from income_desk.validation import run_daily_checks
    timestamp = datetime.now()
    warnings: list[str] = []

    # Build a minimal trade_spec if none provided (some checks need .legs)
    trade_spec = request.trade_spec
    if trade_spec is None:
        try:
            from income_desk.models.opportunity import TradeSpec, LegSpec, LegAction
            from datetime import date, timedelta
            expiry = date.today() + timedelta(days=request.dte)
            price = request.current_price
            # Dummy IC legs so validation checks don't crash
            trade_spec = TradeSpec(
                ticker=request.ticker,
                legs=[
                    LegSpec(role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
                            strike=round(price * 0.97, -1), strike_label="SP",
                            expiration=expiry, days_to_expiry=request.dte, atm_iv_at_expiry=0.0),
                    LegSpec(role="long_put", action=LegAction.BUY_TO_OPEN, option_type="put",
                            strike=round(price * 0.95, -1), strike_label="LP",
                            expiration=expiry, days_to_expiry=request.dte, atm_iv_at_expiry=0.0),
                    LegSpec(role="short_call", action=LegAction.SELL_TO_OPEN, option_type="call",
                            strike=round(price * 1.03, -1), strike_label="SC",
                            expiration=expiry, days_to_expiry=request.dte, atm_iv_at_expiry=0.0),
                    LegSpec(role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call",
                            strike=round(price * 1.05, -1), strike_label="LC",
                            expiration=expiry, days_to_expiry=request.dte, atm_iv_at_expiry=0.0),
                ],
                underlying_price=price, target_dte=request.dte, target_expiration=expiry,
                spec_rationale="validation check", structure_type="iron_condor",
                order_side="credit",
            )
            warnings.append("trade_spec auto-generated for validation (no actual legs provided)")
        except Exception as e:
            warnings.append(f"Could not build trade_spec: {e}")

    try:
        rpt = run_daily_checks(
            ticker=request.ticker, trade_spec=trade_spec,
            entry_credit=request.entry_credit, regime_id=request.regime_id,
            atr_pct=request.atr_pct, current_price=request.current_price,
            avg_bid_ask_spread_pct=request.avg_bid_ask_spread_pct,
            dte=request.dte, rsi=request.rsi, iv_rank=request.iv_rank,
            contracts=request.contracts,
        )
    except Exception as e:
        return ValidateResponse(
            meta=WorkflowMeta(as_of=timestamp, market="", data_source="", warnings=warnings + [str(e)]),
            is_ready=False, gates=[], failed_gates=[str(e)], warnings=warnings + [str(e)],
        )

    gates = []
    failed = []
    if rpt:
        for c in rpt.checks:
            sev = c.severity.value if hasattr(c.severity, 'value') else str(c.severity)
            gates.append(GateResult(name=c.name, passed=sev != "fail", severity=sev, detail=getattr(c, 'detail', '')))
            if sev == "fail":
                failed.append(c.name)

    return ValidateResponse(
        meta=WorkflowMeta(as_of=timestamp, market="", data_source="validation", warnings=warnings),
        is_ready=rpt.is_ready if rpt else False,
        gates=gates, failed_gates=failed, warnings=warnings,
    )
