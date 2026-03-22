"""Profitability validation framework — pure functions, no broker required.

Usage::

    from income_desk.validation import run_daily_checks, run_adversarial_checks
    from income_desk.validation.models import ValidationReport, CheckResult, Severity, Suite

    report = run_daily_checks(
        ticker="SPY",
        trade_spec=spec,
        entry_credit=1.50,
        regime_id=1,
        atr_pct=1.0,
        current_price=580.0,
        avg_bid_ask_spread_pct=0.8,
        dte=30,
        rsi=50.0,
    )
    print(report.summary)
"""
from income_desk.validation.daily_readiness import run_adversarial_checks, run_daily_checks
from income_desk.validation.models import CheckResult, Severity, Suite, ValidationReport
from income_desk.validation.profitability_audit import (
    check_commission_drag,
    check_fill_quality,
    check_margin_efficiency,
)
from income_desk.validation.stress_scenarios import (
    check_breakeven_spread,
    check_gamma_stress,
    check_vega_shock,
    run_position_stress,
)

__all__ = [
    "run_daily_checks",
    "run_adversarial_checks",
    "ValidationReport",
    "CheckResult",
    "Severity",
    "Suite",
    "check_commission_drag",
    "check_fill_quality",
    "check_margin_efficiency",
    "check_gamma_stress",
    "check_vega_shock",
    "check_breakeven_spread",
    "run_position_stress",
]
