"""Exit intelligence: regime-contingent stops, time-adjusted targets, theta decay.

Pure functions — no data fetching, no broker required.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from market_analyzer.models.exit import MonitoringAction, RegimeStop, ThetaDecayResult, TimeAdjustedTarget

if TYPE_CHECKING:
    from market_analyzer.models.opportunity import TradeSpec

# Regime → stop-loss multiplier
# R1: calm MR — standard 2x, breaches are unusual
# R2: high-vol MR — wider swings are normal, let mean-reversion work
# R3: trending — trends persist, cut fast
# R4: explosive — max risk, tightest stop
_REGIME_STOP_MULTIPLIERS: dict[int, tuple[float, str]] = {
    1: (2.0, "R1 calm MR: standard stop — breaches are unusual, respect the stop"),
    2: (3.0, "R2 high-vol MR: wider swings are normal — let mean-reversion work"),
    3: (1.5, "R3 trending: trends persist — cut losses fast"),
    4: (1.5, "R4 explosive: maximum risk — tightest stop"),
}


def compute_regime_stop(
    regime_id: int,
    structure_type: str = "iron_condor",
) -> RegimeStop:
    """Compute regime-contingent stop-loss multiplier.

    Args:
        regime_id: Current regime (1-4).
        structure_type: Trade structure type (for rationale context).

    Returns:
        RegimeStop with multiplier and rationale.
    """
    multiplier, rationale = _REGIME_STOP_MULTIPLIERS.get(
        regime_id, (2.0, f"Unknown regime R{regime_id}: defaulting to 2.0x standard stop"),
    )
    return RegimeStop(
        regime_id=regime_id,
        base_multiplier=multiplier,
        structure_type=structure_type,
        rationale=rationale,
    )


def compute_time_adjusted_target(
    days_held: int,
    dte_at_entry: int,
    current_profit_pct: float,
    original_target_pct: float = 0.50,
) -> TimeAdjustedTarget:
    """Compute time-based profit target acceleration.

    If profit is accumulating faster than expected (velocity > 2.0), close early
    and redeploy capital. If time is running out with minimal profit, lower the
    target to salvage what you can.

    Args:
        days_held: Number of calendar days since entry.
        dte_at_entry: DTE at time of entry.
        current_profit_pct: Current profit as fraction of max profit (0-1).
        original_target_pct: Original profit target as fraction (0-1).

    Returns:
        TimeAdjustedTarget with adjusted target and acceleration reason.
    """
    if dte_at_entry <= 0:
        return TimeAdjustedTarget(
            original_target_pct=original_target_pct,
            adjusted_target_pct=original_target_pct,
            days_held=days_held,
            dte_at_entry=dte_at_entry,
            time_elapsed_pct=1.0,
            profit_velocity=0.0,
            acceleration_reason=None,
        )

    time_elapsed_pct = days_held / dte_at_entry
    profit_velocity = current_profit_pct / max(time_elapsed_pct, 0.01)

    adjusted = original_target_pct
    reason: str | None = None

    # Fast profit: earning >= 2x expected pace with meaningful profit
    if profit_velocity > 2.0 and current_profit_pct >= 0.25:
        adjusted = max(0.25, original_target_pct - 0.15)
        reason = f"Capital velocity: {profit_velocity:.1f}x expected pace"

    # Theta exhausted: 60%+ of time gone, < 15% profit
    elif time_elapsed_pct > 0.60 and current_profit_pct < 0.15:
        adjusted = max(current_profit_pct, 0.10)
        reason = (
            f"Theta exhausted: {time_elapsed_pct:.0%} of time, "
            f"only {current_profit_pct:.0%} profit"
        )

    return TimeAdjustedTarget(
        original_target_pct=original_target_pct,
        adjusted_target_pct=round(adjusted, 4),
        days_held=days_held,
        dte_at_entry=dte_at_entry,
        time_elapsed_pct=round(time_elapsed_pct, 4),
        profit_velocity=round(profit_velocity, 4),
        acceleration_reason=reason,
    )


def compute_remaining_theta_value(
    dte_remaining: int,
    dte_at_entry: int,
    current_profit_pct: float,
) -> ThetaDecayResult:
    """Compare realized profit against remaining theta to inform hold/close.

    Theta decay is non-linear — approximated by sqrt(DTE). When profit/theta
    ratio is high, the remaining theta isn't worth the continued risk exposure.

    Args:
        dte_remaining: Days to expiration remaining.
        dte_at_entry: DTE at time of entry.
        current_profit_pct: Current profit as fraction of max profit (0-1).

    Returns:
        ThetaDecayResult with hold/close recommendation and rationale.
    """
    if dte_at_entry <= 0:
        return ThetaDecayResult(
            dte_remaining=dte_remaining,
            dte_at_entry=dte_at_entry,
            remaining_theta_pct=0.0,
            current_profit_pct=current_profit_pct,
            profit_to_theta_ratio=float("inf") if current_profit_pct > 0 else 0.0,
            recommendation="close_and_redeploy",
            rationale="Invalid DTE at entry — close position",
        )

    remaining_theta_pct = math.sqrt(max(dte_remaining, 0)) / math.sqrt(dte_at_entry)
    profit_to_theta_ratio = current_profit_pct / max(remaining_theta_pct, 0.01)

    if profit_to_theta_ratio > 3.0:
        recommendation = "close_and_redeploy"
        rationale = (
            f"Captured {current_profit_pct:.0%} profit with only {remaining_theta_pct:.0%} "
            f"theta remaining (ratio {profit_to_theta_ratio:.1f}x). "
            f"Diminishing returns to hold — close and redeploy capital."
        )
    elif profit_to_theta_ratio > 1.5:
        recommendation = "approaching_decay_cliff"
        rationale = (
            f"Profit {current_profit_pct:.0%} vs {remaining_theta_pct:.0%} remaining theta "
            f"(ratio {profit_to_theta_ratio:.1f}x). "
            f"Approaching decay cliff — monitor closely, prepare exit order."
        )
    else:
        recommendation = "hold"
        rationale = (
            f"Theta still working: {remaining_theta_pct:.0%} remaining with "
            f"{current_profit_pct:.0%} profit captured (ratio {profit_to_theta_ratio:.1f}x)."
        )

    return ThetaDecayResult(
        dte_remaining=dte_remaining,
        dte_at_entry=dte_at_entry,
        remaining_theta_pct=round(remaining_theta_pct, 4),
        current_profit_pct=current_profit_pct,
        profit_to_theta_ratio=round(profit_to_theta_ratio, 4),
        recommendation=recommendation,
        rationale=rationale,
    )


def compute_monitoring_action(
    trade_spec: "TradeSpec",
    entry_price: float,
    current_mid: float,
    current_price: float,
    dte_remaining: int,
    regime_id: int,
    atr_pct: float,
    entry_regime_id: int | None = None,
    days_held: int = 0,
    dte_at_entry: int = 30,
    contracts: int = 1,
) -> MonitoringAction:
    """Master monitoring function: exit check + stress check -> concrete action.

    Chains ``monitor_exit_conditions`` and ``run_position_stress`` then
    returns a ``MonitoringAction``.  When the action is "close", the returned
    object contains a ``closing_trade_spec`` with the exact inverse legs to
    submit to the broker.

    Args:
        trade_spec: The open TradeSpec.
        entry_price: Original fill price (credit received or debit paid).
        current_mid: Current mid price to close the position.
        current_price: Current underlying spot price.
        dte_remaining: Days to expiration remaining.
        regime_id: Current regime (1-4).
        atr_pct: Current ATR as percentage of underlying price.
        entry_regime_id: Regime at time of entry (for regime-change detection).
        days_held: Calendar days since entry.
        dte_at_entry: DTE at time of entry.
        contracts: Number of contracts.

    Returns:
        MonitoringAction with action/urgency/reason and optional closing_trade_spec.
    """
    from market_analyzer.validation.stress_scenarios import run_position_stress
    from market_analyzer.trade_lifecycle import monitor_exit_conditions
    from market_analyzer.opportunity.option_plays._trade_spec_helpers import build_closing_trade_spec

    # --- Compute current P&L fraction -----------------------------------------
    order_side = trade_spec.order_side or "credit"
    if order_side == "credit":
        # Credit trades: profit = (entry - current) / entry
        pnl_pct = (entry_price - current_mid) / entry_price if entry_price > 0 else 0.0
    else:
        # Debit trades: profit = (current - entry) / entry
        pnl_pct = (current_mid - entry_price) / entry_price if entry_price > 0 else 0.0

    # --- Regime-contingent stop and time-adjusted target ----------------------
    stop = compute_regime_stop(regime_id, trade_spec.structure_type or "iron_condor")
    adjusted_target = compute_time_adjusted_target(
        days_held=days_held,
        dte_at_entry=dte_at_entry,
        current_profit_pct=max(0.0, pnl_pct),
        original_target_pct=trade_spec.profit_target_pct or 0.50,
    )

    # --- Exit conditions check ------------------------------------------------
    exit_result = monitor_exit_conditions(
        trade_id="monitoring",
        ticker=trade_spec.ticker,
        structure_type=order_side,          # monitor uses this for credit/debit calc
        order_side=order_side,
        entry_price=entry_price,
        current_mid_price=current_mid,
        contracts=contracts,
        dte_remaining=dte_remaining,
        regime_id=regime_id,
        entry_regime_id=entry_regime_id,
        profit_target_pct=adjusted_target.adjusted_target_pct,
        stop_loss_pct=stop.base_multiplier,
        exit_dte=trade_spec.exit_dte,
        regime_stop_multiplier=stop.base_multiplier,
        days_held=days_held,
        dte_at_entry=dte_at_entry,
    )

    # --- Position stress check ------------------------------------------------
    stress = run_position_stress(
        trade_spec=trade_spec,
        current_credit_value=current_mid,
        current_atr_pct=atr_pct,
        entry_credit=entry_price,
        days_held=days_held,
        dte_remaining=dte_remaining,
    )
    stress_failures = [c for c in stress.checks if c.severity.value == "fail"]
    stress_dict = stress.model_dump()

    # --- Determine action: priority order is exit > stress > theta > hold -----

    if exit_result.should_close:
        reason_text = (
            exit_result.most_urgent.rule
            if exit_result.most_urgent is not None
            else "exit_triggered"
        )
        closing_spec = build_closing_trade_spec(trade_spec, reason_text, current_price)
        return MonitoringAction(
            action="close",
            urgency="immediate",
            reason=f"Exit triggered: {reason_text}",
            closing_trade_spec=closing_spec,
            stress_report=stress_dict,
        )

    if stress_failures:
        fail_names = ", ".join(c.name for c in stress_failures)
        closing_spec = build_closing_trade_spec(
            trade_spec, f"stress_fail: {fail_names}", current_price
        )
        return MonitoringAction(
            action="close",
            urgency="soon",
            reason=f"Stress failure: {fail_names}",
            closing_trade_spec=closing_spec,
            stress_report=stress_dict,
        )

    # Check theta decay curve
    theta = compute_remaining_theta_value(
        dte_remaining=dte_remaining,
        dte_at_entry=dte_at_entry,
        current_profit_pct=max(0.0, pnl_pct),
    )
    if theta.recommendation == "close_and_redeploy":
        closing_spec = build_closing_trade_spec(trade_spec, "theta_exhausted", current_price)
        return MonitoringAction(
            action="close",
            urgency="soon",
            reason=f"Theta exhausted: {theta.rationale}",
            closing_trade_spec=closing_spec,
            stress_report=stress_dict,
        )

    # All good — hold
    urgency = "monitor" if theta.recommendation == "approaching_decay_cliff" else "none"
    return MonitoringAction(
        action="hold",
        urgency=urgency,
        reason=f"Position healthy. {theta.rationale}",
        closing_trade_spec=None,
        stress_report=stress_dict,
    )
