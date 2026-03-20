"""Daily readiness and adversarial check orchestrators.

run_daily_checks() — 8-check pre-trade validation.
run_adversarial_checks() — 3-check stress test.

Both return a ValidationReport that is consumed by the CLI and functional tests.
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from market_analyzer.models.opportunity import TradeSpec

if TYPE_CHECKING:
    from market_analyzer.models.levels import LevelsAnalysis
from market_analyzer.trade_lifecycle import (
    check_income_entry,
    compute_income_yield,
    estimate_pop,
)
from market_analyzer.validation.models import CheckResult, Severity, Suite, ValidationReport
from market_analyzer.validation.profitability_audit import (
    check_commission_drag,
    check_fill_quality,
    check_margin_efficiency,
)
from market_analyzer.validation.stress_scenarios import (
    check_breakeven_spread,
    check_gamma_stress,
    check_vega_shock,
)


def run_daily_checks(
    ticker: str,
    trade_spec: TradeSpec,
    entry_credit: float,
    regime_id: int,
    atr_pct: float,
    current_price: float,
    avg_bid_ask_spread_pct: float,
    dte: int,
    rsi: float,
    iv_rank: float | None = None,
    iv_percentile: float | None = None,
    contracts: int = 1,
    levels: LevelsAnalysis | None = None,
    days_to_earnings: int | None = None,
) -> ValidationReport:
    """Run the 9-check daily pre-trade validation suite.

    Checks (in order):
      1. commission_drag    — fees vs credit
      2. fill_quality       — bid-ask spread viability
      3. margin_efficiency  — annualized ROC
      4. pop_gate           — probability of profit >= 65%
      5. ev_positive        — expected value is positive
      6. entry_quality      — IV rank, DTE, RSI, regime confirmation
      7. exit_discipline    — trade spec has profit target, stop loss, exit DTE
      8. strike_proximity   — short strikes backed by S/R levels
      9. earnings_blackout  — no earnings event within trade DTE (HARD FAIL)

    Args:
        ticker: Underlying symbol.
        trade_spec: The proposed trade.
        entry_credit: Net credit per spread (dollars per share, e.g., 1.50).
        regime_id: Current regime (1=R1, 2=R2, 3=R3, 4=R4).
        atr_pct: ATR as % of underlying price.
        current_price: Current underlying price.
        avg_bid_ask_spread_pct: Average bid-ask spread of the options chain.
        dte: Days to expiration of the front/target leg.
        rsi: Current RSI value.
        iv_rank: IV rank 0–100 (optional, improves POP accuracy).
        iv_percentile: IV percentile 0–100 (optional).
        contracts: Number of contracts for yield computation.
        levels: LevelsAnalysis from ma.levels.analyze() (optional, enables strike proximity check).
        days_to_earnings: Days until next earnings event (from FundamentalsSnapshot). None for ETFs/no data.
    """
    checks: list[CheckResult] = []

    # 1. Commission drag
    checks.append(check_commission_drag(trade_spec, entry_credit))

    # 2. Fill quality
    checks.append(check_fill_quality(avg_bid_ask_spread_pct))

    # 3. Margin efficiency
    income = compute_income_yield(trade_spec, entry_credit, contracts)
    if income is not None:
        checks.append(check_margin_efficiency(income))
    else:
        checks.append(CheckResult(
            name="margin_efficiency",
            severity=Severity.WARN,
            message="Cannot compute ROC — trade structure not supported by yield calculator",
        ))

    # 4 & 5. POP and EV
    pop_estimate = estimate_pop(
        trade_spec=trade_spec,
        entry_price=entry_credit,
        regime_id=regime_id,
        atr_pct=atr_pct,
        current_price=current_price,
        contracts=contracts,
        iv_rank=iv_rank,
    )
    if pop_estimate is not None:
        # pop_pct is stored as a fraction (0.70 = 70%) — convert to percentage for display/compare
        pop_pct = pop_estimate.pop_pct * 100.0
        pop_sev = Severity.PASS if pop_pct >= 65.0 else (
            Severity.WARN if pop_pct >= 55.0 else Severity.FAIL
        )
        checks.append(CheckResult(
            name="pop_gate",
            severity=pop_sev,
            message=f"POP {pop_pct:.1f}% "
                    f"({'≥' if pop_pct >= 65 else '<'} 65% threshold)",
            value=round(pop_pct, 1),
            threshold=65.0,
        ))

        ev = pop_estimate.expected_value
        ev_sev = Severity.PASS if ev > 0 else (Severity.WARN if ev > -10 else Severity.FAIL)
        checks.append(CheckResult(
            name="ev_positive",
            severity=ev_sev,
            message=f"EV {'+' if ev >= 0 else ''}${ev:.0f} per contract "
                    f"({'positive edge' if ev > 0 else 'negative edge — avoid'})",
            value=round(ev, 0),
            threshold=0.0,
        ))
    else:
        checks.append(CheckResult(
            name="pop_gate",
            severity=Severity.WARN,
            message="POP not computable for this structure",
        ))
        checks.append(CheckResult(
            name="ev_positive",
            severity=Severity.WARN,
            message="EV not computable — POP unavailable for this structure",
        ))

    # 6. Entry quality (IV rank, RSI, regime, DTE)
    has_earnings_within_dte = (
        days_to_earnings is not None
        and days_to_earnings <= dte
    )
    entry_check = check_income_entry(
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        dte=dte,
        rsi=rsi,
        atr_pct=atr_pct,
        regime_id=regime_id,
        has_earnings_within_dte=has_earnings_within_dte,
    )
    entry_sev = Severity.PASS if entry_check.confirmed else (
        Severity.WARN if entry_check.score >= 0.45 else Severity.FAIL
    )
    checks.append(CheckResult(
        name="entry_quality",
        severity=entry_sev,
        message=entry_check.summary,
        value=round(entry_check.score, 2),
        threshold=0.60,
    ))

    # 7. Exit discipline — does the trade spec have an exit plan?
    has_exit = (
        trade_spec.profit_target_pct is not None
        and trade_spec.stop_loss_pct is not None
        and trade_spec.exit_dte is not None
    )
    exit_sev = Severity.PASS if has_exit else Severity.WARN
    exit_msg = (
        f"TP {trade_spec.profit_target_pct:.0%} | "
        f"SL {trade_spec.stop_loss_pct}× | "
        f"exit ≤{trade_spec.exit_dte} DTE"
        if has_exit else "Trade spec missing exit rules — add profit_target_pct, stop_loss_pct, exit_dte"
    )
    checks.append(CheckResult(
        name="exit_discipline",
        severity=exit_sev,
        message=exit_msg,
    ))

    # ── Check 8: Strike proximity to S/R levels ──
    if levels is not None:
        from market_analyzer.features.entry_levels import compute_strike_support_proximity
        atr_value = current_price * atr_pct / 100
        proximity = compute_strike_support_proximity(trade_spec, levels, atr=atr_value)
        if proximity.all_backed:
            checks.append(CheckResult(
                name="strike_proximity",
                severity=Severity.PASS,
                message=f"Short strikes backed by S/R levels (score {proximity.overall_score:.0%})",
                detail=proximity.summary,
                value=proximity.overall_score,
                threshold=0.5,
            ))
        else:
            checks.append(CheckResult(
                name="strike_proximity",
                severity=Severity.WARN,
                message=f"Short strikes not fully backed (score {proximity.overall_score:.0%})",
                detail=proximity.summary,
                value=proximity.overall_score,
                threshold=0.5,
            ))
    else:
        checks.append(CheckResult(
            name="strike_proximity",
            severity=Severity.WARN,
            message="No levels data — cannot assess strike proximity to S/R",
            detail="Pass levels from ma.levels.analyze() for strike proximity check",
        ))

    # ── Check 9: Earnings blackout ──
    if days_to_earnings is not None and days_to_earnings <= dte:
        checks.append(CheckResult(
            name="earnings_blackout",
            severity=Severity.FAIL,
            message=f"Earnings in {days_to_earnings}d — trade expires in {dte}d (earnings within DTE)",
            detail="Do not enter income trades that straddle earnings. Gap risk destroys the structure's assumptions.",
            value=float(days_to_earnings),
            threshold=float(dte),
        ))
    elif days_to_earnings is not None and days_to_earnings <= dte + 5:
        # Earnings just outside DTE but close — warn
        checks.append(CheckResult(
            name="earnings_blackout",
            severity=Severity.WARN,
            message=f"Earnings in {days_to_earnings}d — close to {dte}d DTE (monitor)",
            detail="Earnings is close to expiration. Consider shorter DTE or different ticker.",
            value=float(days_to_earnings),
            threshold=float(dte),
        ))
    else:
        checks.append(CheckResult(
            name="earnings_blackout",
            severity=Severity.PASS,
            message=f"No earnings conflict" + (f" (next earnings in {days_to_earnings}d)" if days_to_earnings else " (no earnings data)"),
        ))

    return ValidationReport(
        ticker=ticker,
        suite=Suite.DAILY,
        as_of=date.today(),
        checks=checks,
    )


def run_adversarial_checks(
    ticker: str,
    trade_spec: TradeSpec,
    entry_credit: float,
    atr_pct: float,
) -> ValidationReport:
    """Run the 3-check adversarial stress test suite.

    Checks:
      1. gamma_stress     — max loss at 2σ move
      2. vega_shock       — IV spike impact
      3. breakeven_spread — edge survival at natural fills

    Args:
        ticker: Underlying symbol.
        trade_spec: The proposed trade.
        entry_credit: Net credit per spread (dollars per share).
        atr_pct: ATR as % of underlying price.
    """
    checks = [
        check_gamma_stress(trade_spec, entry_credit, atr_pct),
        check_vega_shock(trade_spec, entry_credit),
        check_breakeven_spread(trade_spec, entry_credit, atr_pct),
    ]

    return ValidationReport(
        ticker=ticker,
        suite=Suite.ADVERSARIAL,
        as_of=date.today(),
        checks=checks,
    )
