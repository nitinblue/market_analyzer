"""Profitability audit checks — pure functions, no broker required.

All functions take numbers / models as input and return a CheckResult.
No market_analyzer services are called here.
"""
from __future__ import annotations

from income_desk.models.opportunity import TradeSpec
from income_desk.trade_lifecycle import IncomeYield
from income_desk.validation.models import CheckResult, Severity

# Commission constants
_COMMISSION_PER_CONTRACT = 0.65  # $ per leg per direction (TastyTrade rate)


def check_commission_drag(
    trade_spec: TradeSpec,
    entry_credit: float,
    commission_per_contract: float = _COMMISSION_PER_CONTRACT,
) -> CheckResult:
    """Checks whether the entry credit justifies round-trip commission costs.

    Args:
        trade_spec: The trade structure (used to count legs).
        entry_credit: Net credit received per spread in dollars-per-share (e.g., 1.50).
        commission_per_contract: Cost per leg per direction, default $0.65.

    Returns:
        PASS if commission_drag_pct < 10%.
        WARN if commission_drag_pct >= 10% and < 25%.
        FAIL if net_credit_dollars <= 0 OR commission_drag_pct >= 25%.
    """
    leg_count = len(trade_spec.legs)
    round_trip_cost = commission_per_contract * leg_count * 2  # open + close
    gross_credit_dollars = entry_credit * 100  # per-share → per-contract

    if gross_credit_dollars <= 0:
        return CheckResult(
            name="commission_drag",
            severity=Severity.FAIL,
            message="Entry credit is zero or negative — no edge to cover fees",
            value=0.0,
            threshold=round_trip_cost,
        )

    commission_drag_pct = (round_trip_cost / gross_credit_dollars) * 100
    net_credit_dollars = gross_credit_dollars - round_trip_cost

    if net_credit_dollars <= 0 or commission_drag_pct >= 25.0:
        sev = Severity.FAIL
        msg = (
            f"Fees ${round_trip_cost:.2f} eat {commission_drag_pct:.0f}% of "
            f"${gross_credit_dollars:.0f} credit — trade is not viable after commissions"
        )
    elif commission_drag_pct >= 10.0:
        sev = Severity.WARN
        msg = (
            f"Fees ${round_trip_cost:.2f} ({commission_drag_pct:.0f}% of credit) — "
            f"marginal, net credit ${net_credit_dollars:.2f}"
        )
    else:
        sev = Severity.PASS
        msg = (
            f"Credit ${gross_credit_dollars:.0f} covers ${round_trip_cost:.2f} fees "
            f"({commission_drag_pct:.1f}% drag), net ${net_credit_dollars:.2f}"
        )

    return CheckResult(
        name="commission_drag",
        severity=sev,
        message=msg,
        value=round(net_credit_dollars, 2),
        threshold=round(round_trip_cost, 2),
    )


def check_fill_quality(avg_bid_ask_spread_pct: float) -> CheckResult:
    """Checks whether the bid-ask spread is tight enough to survive a natural fill.

    Args:
        avg_bid_ask_spread_pct: Average bid-ask spread as % of mid price.

    Returns:
        PASS if spread <= 1.5%, WARN if 1.5–3%, FAIL if > 3%.
    """
    if avg_bid_ask_spread_pct > 3.0:
        sev = Severity.FAIL
        msg = f"Spread {avg_bid_ask_spread_pct:.1f}% is too wide — natural fill will destroy edge"
    elif avg_bid_ask_spread_pct > 1.5:
        sev = Severity.WARN
        msg = f"Spread {avg_bid_ask_spread_pct:.1f}% — acceptable at mid, risky at natural fill"
    else:
        sev = Severity.PASS
        msg = f"Spread {avg_bid_ask_spread_pct:.1f}% — survives natural fill"

    return CheckResult(
        name="fill_quality",
        severity=sev,
        message=msg,
        value=avg_bid_ask_spread_pct,
        threshold=3.0,
    )


def check_margin_efficiency(income_yield: IncomeYield) -> CheckResult:
    """Checks whether the trade earns sufficient return on capital deployed.

    Compares annualized ROC against the minimum threshold for small accounts:
    income must justify the margin tie-up.

    Args:
        income_yield: IncomeYield from compute_income_yield().

    Returns:
        PASS if annualized ROC >= 15%, WARN if 10–15%, FAIL if < 10%.
    """
    roc = income_yield.annualized_roc_pct

    if roc < 10.0:
        sev = Severity.FAIL
        msg = f"Annualized ROC {roc:.1f}% — below 10% minimum for small account viability"
    elif roc < 15.0:
        sev = Severity.WARN
        msg = f"Annualized ROC {roc:.1f}% — marginal (target ≥15%)"
    else:
        sev = Severity.PASS
        msg = f"Annualized ROC {roc:.1f}% — capital deployed efficiently"

    return CheckResult(
        name="margin_efficiency",
        severity=sev,
        message=msg,
        value=round(roc, 1),
        threshold=15.0,
    )
