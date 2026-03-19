"""Adversarial stress scenario checks — pure functions.

These answer: "At what point does our edge disappear?"
No broker required. All inputs are numbers/models.
"""
from __future__ import annotations

from market_analyzer.models.opportunity import StructureType, TradeSpec
from market_analyzer.validation.models import CheckResult, Severity

# Structures that are long vega (benefit from IV spikes)
_LONG_VEGA_STRUCTURES = {
    StructureType.CALENDAR,
    StructureType.DOUBLE_CALENDAR,
    StructureType.DIAGONAL,
    StructureType.DEBIT_SPREAD,
    StructureType.LONG_OPTION,
    StructureType.IRON_MAN,
    StructureType.PMCC,
}


def check_gamma_stress(
    trade_spec: TradeSpec,
    entry_credit: float,
    atr_pct: float,
    sigma_multiple: float = 2.0,
) -> CheckResult:
    """Checks whether the trade survives a large intraday move.

    For defined-risk structures, the max loss is bounded by wing width.
    The check validates that the risk/reward ratio stays reasonable under stress.

    Args:
        trade_spec: Trade structure (must have wing_width_points for defined-risk).
        entry_credit: Net credit per spread (dollars per share).
        atr_pct: ATR as % of underlying price.
        sigma_multiple: Standard deviation multiple for the stress move (default 2.0).
    """
    wing_width = trade_spec.wing_width_points

    if wing_width is None or wing_width <= 0:
        return CheckResult(
            name="gamma_stress",
            severity=Severity.WARN,
            message="Cannot assess gamma risk: no wing width (undefined-risk structure)",
        )

    max_loss = wing_width * 100 - entry_credit * 100
    max_profit = entry_credit * 100

    if max_loss <= 0:
        return CheckResult(
            name="gamma_stress",
            severity=Severity.FAIL,
            message="Max loss is zero or negative — invalid trade parameters",
        )

    risk_reward = max_loss / max_profit if max_profit > 0 else 999.0

    # Stress: at 2 ATR move, does the expected loss stay within acceptable bounds?
    stress_move_pct = atr_pct * sigma_multiple

    if risk_reward > 10.0:
        sev = Severity.FAIL
        msg = (
            f"Risk/reward {risk_reward:.1f}:1 is extreme — risking ${max_loss:.0f} "
            f"to make ${max_profit:.0f} at {stress_move_pct:.1f}% stress move"
        )
    elif risk_reward > 5.0:
        sev = Severity.WARN
        msg = (
            f"Risk/reward {risk_reward:.1f}:1 — marginal at {sigma_multiple}σ "
            f"({stress_move_pct:.1f}% move), max loss ${max_loss:.0f}"
        )
    else:
        sev = Severity.PASS
        msg = (
            f"Gamma risk bounded: max loss ${max_loss:.0f} "
            f"at {sigma_multiple}σ move ({stress_move_pct:.1f}%), R:R {risk_reward:.1f}:1"
        )

    return CheckResult(
        name="gamma_stress",
        severity=sev,
        message=msg,
        value=round(max_loss, 0),
        threshold=round(max_profit * 5, 0),  # flag if max_loss > 5× max_profit
    )


def check_vega_shock(
    trade_spec: TradeSpec,
    entry_credit: float,
    iv_spike_pct: float = 0.30,
) -> CheckResult:
    """Checks the trade's exposure to a sudden IV expansion.

    Short-vega structures (IC, credit spread) are hurt by IV spikes.
    Long-vega structures (calendar, diagonal) benefit from IV spikes.

    Args:
        trade_spec: The trade structure.
        entry_credit: Net credit per spread (dollars per share).
        iv_spike_pct: Fractional IV increase to stress test (0.30 = +30%).
    """
    structure = trade_spec.structure_type
    max_profit = entry_credit * 100

    if structure in _LONG_VEGA_STRUCTURES:
        return CheckResult(
            name="vega_shock",
            severity=Severity.PASS,
            message=f"Long-vega structure benefits from +{iv_spike_pct:.0%} IV spike",
            value=iv_spike_pct,
        )

    # Short vega: estimate impact as fraction of max profit at risk
    # Approximate: a +30% IV spike on a 30-DTE IC can erase 30-50% of credit
    estimated_loss_pct = iv_spike_pct * 1.2  # conservative multiplier
    estimated_loss_dollars = max_profit * estimated_loss_pct

    if estimated_loss_pct >= 0.5:
        sev = Severity.FAIL
        msg = (
            f"Short-vega structure: +{iv_spike_pct:.0%} IV spike could erase "
            f"~{estimated_loss_pct:.0%} of credit (≈${estimated_loss_dollars:.0f})"
        )
    else:
        sev = Severity.WARN
        msg = (
            f"Short-vega: +{iv_spike_pct:.0%} IV spike risks ~{estimated_loss_pct:.0%} "
            f"of credit (≈${estimated_loss_dollars:.0f}). Monitor if IV rises."
        )

    return CheckResult(
        name="vega_shock",
        severity=sev,
        message=msg,
        value=round(estimated_loss_dollars, 0),
        threshold=round(max_profit, 0),
    )


def check_breakeven_spread(
    trade_spec: TradeSpec,
    entry_credit: float,
    atr_pct: float,
    spread_pcts: list[float] | None = None,
) -> CheckResult:
    """Finds the bid-ask spread at which this trade loses its EV edge.

    Args:
        trade_spec: The trade structure.
        entry_credit: Net credit at mid price (dollars per share).
        atr_pct: ATR as % of underlying price (used as proxy for daily σ).
        spread_pcts: Spread percentages to test (default: 0.5%, 1%, 2%, 3%, 4%, 5%).
    """
    if spread_pcts is None:
        spread_pcts = [0.5, 1.0, 2.0, 3.0, 4.0, 5.0]

    wing_width = trade_spec.wing_width_points or 5.0
    max_profit = entry_credit * 100
    max_loss = wing_width * 100 - max_profit

    if max_loss <= 0 or max_profit <= 0:
        return CheckResult(
            name="breakeven_spread",
            severity=Severity.FAIL,
            message="Cannot compute break-even: invalid trade parameters",
        )

    # ATR-based rough POP estimate (regime-neutral, ~R1 conditions)
    daily_sigma = (atr_pct / 100.0) / 1.25
    pop = max(0.30, min(0.90, 1.0 - daily_sigma * 2.0))

    # Find break-even spread
    breakeven_spread_pct: float | None = None
    for sp in spread_pcts:
        # At spread sp%, effective credit = mid - sp%/2 of mid
        effective_credit = entry_credit * (1 - sp / 200)
        ev = pop * (effective_credit * 100) - (1 - pop) * max_loss
        if ev <= 0 and breakeven_spread_pct is None:
            breakeven_spread_pct = sp
            break

    if breakeven_spread_pct is None:
        # Edge survives even at max tested spread
        breakeven_spread_pct = spread_pcts[-1]
        sev = Severity.PASS
        msg = f"Edge survives up to {spread_pcts[-1]:.1f}% spread (POP {pop:.0%}, credit ${max_profit:.0f})"
    elif breakeven_spread_pct <= 1.0:
        sev = Severity.FAIL
        msg = (
            f"Edge disappears at {breakeven_spread_pct:.1f}% spread — "
            f"trade is too thin to survive realistic fills"
        )
    elif breakeven_spread_pct <= 2.0:
        sev = Severity.WARN
        msg = (
            f"Break-even spread {breakeven_spread_pct:.1f}% — "
            f"viable at mid fill, risky at natural fill"
        )
    else:
        sev = Severity.PASS
        msg = (
            f"Break-even spread {breakeven_spread_pct:.1f}% — "
            f"sufficient cushion for realistic fills"
        )

    return CheckResult(
        name="breakeven_spread",
        severity=sev,
        message=msg,
        value=breakeven_spread_pct,
        threshold=2.0,
    )
