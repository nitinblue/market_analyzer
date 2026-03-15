"""Leg execution sequencing for single-leg markets (India).

India brokers execute multi-leg options orders one leg at a time.
This module computes the safest execution order, slippage estimates,
and partial fill risk for each intermediate state.

All functions are pure computation — eTrading handles actual order placement.

Key principle: ALWAYS execute the long (protective) leg BEFORE the short (risky) leg.
This ensures you never have naked short exposure during execution.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from market_analyzer.models.opportunity import LegAction, LegSpec, TradeSpec


class LegRisk(StrEnum):
    """Risk level of holding a partial position after this leg fills."""

    SAFE = "safe"            # Only long legs filled — defined risk
    MODERATE = "moderate"    # Spread completed on one side
    HIGH = "high"            # Naked short exposure
    CRITICAL = "critical"    # Naked short without protective wing


class ExecutionLeg(BaseModel):
    """A single leg in the execution sequence with risk context."""

    sequence: int            # 1, 2, 3, 4 (order of execution)
    leg: LegSpec
    action_desc: str         # "BUY NIFTY 22500CE" (human readable)
    risk_after: LegRisk      # Risk level AFTER this leg fills
    risk_description: str    # What your exposure is after this leg
    slippage_side: str       # "pay_ask" (buying) or "receive_bid" (selling)
    estimated_slippage_pct: float  # Expected slippage as % of mid


class ExecutionPlan(BaseModel):
    """Complete leg execution plan for a multi-leg trade."""

    ticker: str
    structure_type: str
    total_legs: int
    execution_order: list[ExecutionLeg]
    total_estimated_slippage_pct: float  # Aggregate slippage across all legs
    max_naked_exposure: str              # Worst-case intermediate state
    abort_rule: str                      # When to abort if a leg doesn't fill
    notes: list[str]                     # Execution guidance
    market: str                          # "INDIA" or "US"


def plan_leg_execution(
    trade_spec: TradeSpec,
    market: str = "INDIA",
    avg_spread_pct: float = 0.5,  # Average bid-ask spread as % of mid per leg
) -> ExecutionPlan:
    """Plan the safest execution order for a multi-leg trade.

    Rules:
    1. BUY (protective) legs BEFORE SELL (risky) legs
    2. Within buys: buy the further OTM leg first (cheaper, less slippage)
    3. Within sells: sell the further OTM leg first (higher premium, better fill)
    4. For credit spreads: buy wing first, then sell short strike
    5. For iron condors: buy both wings, then sell both shorts

    Args:
        trade_spec: The trade to execute
        market: "INDIA" (single-leg) or "US" (multi-leg native)
        avg_spread_pct: Expected bid-ask spread per leg

    Returns:
        ExecutionPlan with ordered legs and risk assessment
    """
    if not trade_spec.legs:
        return ExecutionPlan(
            ticker=trade_spec.ticker,
            structure_type=trade_spec.structure_type or "unknown",
            total_legs=0,
            execution_order=[],
            total_estimated_slippage_pct=0.0,
            max_naked_exposure="none",
            abort_rule="n/a",
            notes=["No legs to execute"],
            market=market,
        )

    if market.upper() == "US":
        # US: multi-leg native — submit as single order
        return ExecutionPlan(
            ticker=trade_spec.ticker,
            structure_type=trade_spec.structure_type or "unknown",
            total_legs=len(trade_spec.legs),
            execution_order=[
                ExecutionLeg(
                    sequence=i + 1,
                    leg=leg,
                    action_desc=f"{leg.action.value} {trade_spec.ticker} {leg.strike:.0f}{leg.option_type[0].upper()}",
                    risk_after=LegRisk.SAFE,
                    risk_description="Multi-leg order — all legs fill simultaneously",
                    slippage_side="net",
                    estimated_slippage_pct=avg_spread_pct * 0.5,
                )
                for i, leg in enumerate(trade_spec.legs)
            ],
            total_estimated_slippage_pct=avg_spread_pct * 0.5,  # Net spread on combo
            max_naked_exposure="none — multi-leg order",
            abort_rule="Order fills or cancels as a unit",
            notes=["US multi-leg order — all legs execute atomically"],
            market=market,
        )

    # INDIA: single-leg execution — need careful sequencing
    legs = list(trade_spec.legs)

    # Separate into buy (protective) and sell (risky)
    buy_legs = [l for l in legs if l.action == LegAction.BUY_TO_OPEN]
    sell_legs = [l for l in legs if l.action == LegAction.SELL_TO_OPEN]

    # Sort buys: further OTM first (cheaper, lower slippage risk)
    buy_legs.sort(key=lambda l: -abs(l.strike - trade_spec.underlying_price))

    # Sort sells: further OTM first (safer to have first)
    sell_legs.sort(key=lambda l: -abs(l.strike - trade_spec.underlying_price))

    # Execution order: ALL buys first, then ALL sells
    ordered = buy_legs + sell_legs

    # Build execution legs with risk assessment
    execution_order: list[ExecutionLeg] = []
    filled_buys = 0
    filled_sells = 0
    max_risk = LegRisk.SAFE

    for i, leg in enumerate(ordered):
        is_buy = leg.action == LegAction.BUY_TO_OPEN

        if is_buy:
            filled_buys += 1
            slippage_side = "pay_ask"
            # After buying: only long exposure — safe
            risk = LegRisk.SAFE
            risk_desc = f"Holding {filled_buys} long leg(s) — defined risk, no short exposure"
        else:
            filled_sells += 1
            slippage_side = "receive_bid"

            # After selling: check if there's a protective buy
            if filled_buys >= filled_sells:
                risk = LegRisk.MODERATE
                risk_desc = f"Short leg #{filled_sells} covered by long leg — spread position"
            else:
                risk = LegRisk.CRITICAL
                risk_desc = f"NAKED SHORT — no protective wing yet! Close immediately if next leg doesn't fill"

        if _risk_level(risk) > _risk_level(max_risk):
            max_risk = risk

        p_or_c = leg.option_type[0].upper()
        action_desc = f"{leg.action.value} {trade_spec.ticker} {leg.strike:.0f}{p_or_c}"

        execution_order.append(ExecutionLeg(
            sequence=i + 1,
            leg=leg,
            action_desc=action_desc,
            risk_after=risk,
            risk_description=risk_desc,
            slippage_side=slippage_side,
            estimated_slippage_pct=round(avg_spread_pct, 2),
        ))

    total_slippage = avg_spread_pct * len(ordered)

    # Max naked exposure description
    if max_risk == LegRisk.CRITICAL:
        max_naked = "NAKED SHORT exposure during execution — critical risk"
    elif max_risk == LegRisk.HIGH:
        max_naked = "Partial spread — one side exposed"
    elif max_risk == LegRisk.MODERATE:
        max_naked = "Spread position — moderate intermediate risk"
    else:
        max_naked = "All protective legs first — minimal intermediate risk"

    # Abort rules
    structure = (trade_spec.structure_type or "").lower()
    if structure in ("iron_condor", "iron_butterfly", "iron_man"):
        abort_rule = (
            "If any BUY leg fails: ABORT — do not proceed to SELL legs. "
            "If a SELL leg fails after BUYs filled: you hold long options (safe, just losing premium). "
            "If only one side of IC fills: you have a credit spread (acceptable, manage as spread)."
        )
    elif structure in ("credit_spread",):
        abort_rule = (
            "BUY wing first. If BUY fails: ABORT. "
            "If SELL fails after BUY: you hold a long option (safe). "
            "NEVER sell the short strike without the long wing."
        )
    elif structure in ("straddle", "strangle"):
        abort_rule = (
            "Execute one side at a time. If first leg fills but second doesn't: "
            "you have a naked short (CLOSE the filled leg immediately or buy a wing)."
        )
    else:
        abort_rule = "If any protective leg fails, do not proceed with short legs."

    # Notes
    notes = [
        "India market: multi-leg orders execute one leg at a time",
        "ALWAYS buy protective legs BEFORE selling short legs",
        f"Expected total slippage: {total_slippage:.1f}% across {len(ordered)} legs",
        f"Each leg's spread costs ~{avg_spread_pct:.1f}% of mid",
    ]

    if structure in ("straddle", "strangle") and trade_spec.order_side == "credit":
        notes.append(
            "WARNING: Short straddle/strangle has NAKED risk between legs. "
            "Consider adding wings (convert to IC) before selling."
        )

    if len(sell_legs) > 0 and len(buy_legs) == 0:
        notes.append("CRITICAL: No protective legs — all short. Extremely risky in single-leg market.")

    return ExecutionPlan(
        ticker=trade_spec.ticker,
        structure_type=trade_spec.structure_type or "unknown",
        total_legs=len(ordered),
        execution_order=execution_order,
        total_estimated_slippage_pct=round(total_slippage, 2),
        max_naked_exposure=max_naked,
        abort_rule=abort_rule,
        notes=notes,
        market=market,
    )


def _risk_level(risk: LegRisk) -> int:
    """Numeric risk level for comparison."""
    return {"safe": 0, "moderate": 1, "high": 2, "critical": 3}[risk]
