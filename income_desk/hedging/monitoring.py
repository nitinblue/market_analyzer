"""Hedge monitoring — expiry tracking, rolling, effectiveness measurement.

Pure functions:
- monitor_hedge_status() — check active hedges for expiry/roll needs
- compute_hedge_effectiveness() — simulate market move, measure hedge savings

Hedges are passed as plain dicts for simplicity:
    {"ticker": "SPY", "hedge_type": "protective_put", "dte_remaining": 3, "delta_coverage": 0.7}
"""

from __future__ import annotations

from datetime import date, timedelta

from income_desk.hedging.models import (
    HedgeEffectiveness,
    HedgeMonitorEntry,
    HedgeMonitorResult,
)
from income_desk.models.opportunity import (
    LegAction,
    LegSpec,
    OrderSide,
    StructureType,
    TradeSpec,
)


def monitor_hedge_status(
    hedges: list[dict],
    dte_warning_threshold: int = 5,
) -> HedgeMonitorResult:
    """Monitor active hedges for expiry and roll needs.

    Args:
        hedges: List of active hedge dicts, each with:
            - ticker: str
            - hedge_type: str ("protective_put", "futures_short", "index_put", "collar", etc.)
            - dte_remaining: int (days to expiration)
            - delta_coverage: float (0-1, fraction of position delta the hedge covers)
        dte_warning_threshold: Days remaining to flag as expiring (default 5).

    Returns:
        HedgeMonitorResult with status entries, roll specs, and alerts.
    """
    entries: list[HedgeMonitorEntry] = []
    roll_specs: list[TradeSpec] = []
    expiring_count = 0
    expired_count = 0
    alerts: list[str] = []

    for h in hedges:
        ticker = h.get("ticker", "UNKNOWN")
        hedge_type = h.get("hedge_type", "unknown")
        dte = int(h.get("dte_remaining", 0))
        delta_cov = float(h.get("delta_coverage", 0.0))

        is_expired = dte <= 0
        is_expiring = (not is_expired) and (dte <= dte_warning_threshold)

        roll_spec: TradeSpec | None = None

        if is_expired:
            expired_count += 1
            action = "replace"
            rationale = f"{ticker} {hedge_type} has expired — build new hedge immediately"
            alerts.append(f"EXPIRED: {ticker} {hedge_type} (DTE={dte})")

        elif is_expiring:
            expiring_count += 1
            action = "roll"
            rationale = (
                f"{ticker} {hedge_type} expiring in {dte} day(s) — "
                f"roll forward to maintain protection"
            )
            alerts.append(f"EXPIRING SOON: {ticker} {hedge_type} ({dte} DTE)")
            roll_spec = _build_roll_spec(ticker, hedge_type)
            if roll_spec:
                roll_specs.append(roll_spec)

        elif delta_cov < 0.30:
            action = "replace"
            rationale = (
                f"{ticker} {hedge_type} delta coverage degraded to {delta_cov:.0%} "
                f"— replace with fresh hedge"
            )
            alerts.append(f"WEAK COVERAGE: {ticker} {hedge_type} ({delta_cov:.0%} delta coverage)")

        else:
            action = "hold"
            rationale = (
                f"{ticker} {hedge_type} is healthy — "
                f"{dte} DTE remaining, {delta_cov:.0%} delta coverage"
            )

        entries.append(HedgeMonitorEntry(
            ticker=ticker,
            hedge_type=hedge_type,
            dte_remaining=dte,
            is_expiring_soon=is_expiring,
            is_expired=is_expired,
            current_delta_coverage=delta_cov,
            action=action,
            roll_spec=roll_spec,
            rationale=rationale,
        ))

    # Total roll cost is None — would need broker quotes to compute
    total_roll_cost = None

    # Build summary
    summary_parts: list[str] = []
    if expired_count:
        summary_parts.append(f"{expired_count} expired")
    if expiring_count:
        summary_parts.append(f"{expiring_count} expiring soon")
    healthy = len(entries) - expired_count - expiring_count
    if healthy > 0:
        summary_parts.append(f"{healthy} healthy")

    if summary_parts:
        summary = f"{len(entries)} hedge(s): {', '.join(summary_parts)}"
    else:
        summary = "No active hedges"

    return HedgeMonitorResult(
        hedges=entries,
        expiring_count=expiring_count,
        expired_count=expired_count,
        total_roll_cost=total_roll_cost,
        roll_specs=roll_specs,
        alerts=alerts,
        summary=summary,
    )


def _build_roll_spec(ticker: str, hedge_type: str) -> TradeSpec | None:
    """Build a roll TradeSpec for an expiring hedge.

    Roll = close current position + open new 30-day position.
    Returns a placeholder TradeSpec with strike=0 (needs current price to finalize).
    """
    new_dte = 30
    new_expiry = date.today() + timedelta(days=new_dte)

    if hedge_type in ("protective_put", "index_put"):
        return TradeSpec(
            ticker=ticker,
            underlying_price=0.0,  # Placeholder — roll needs current price to finalize
            target_dte=new_dte,
            target_expiration=new_expiry,
            spec_rationale=f"Roll: new {hedge_type} ({new_dte} DTE) — strikes TBD at execution",
            structure_type=StructureType.LONG_OPTION,
            order_side=OrderSide.DEBIT,
            legs=[
                LegSpec(
                    role="long_put",
                    action=LegAction.BUY_TO_OPEN,
                    option_type="put",
                    strike=0.0,  # Placeholder — finalize with current price
                    strike_label="TBD (roll — needs current price)",
                    expiration=new_expiry,
                    days_to_expiry=new_dte,
                    atm_iv_at_expiry=0.25,
                    quantity=1,
                ),
            ],
            max_profit_desc=f"Roll: new {hedge_type} ({new_dte} DTE)",
            max_loss_desc="Roll cost = close old + premium on new put",
        )

    elif hedge_type == "futures_short":
        return TradeSpec(
            ticker=ticker,
            underlying_price=0.0,  # Placeholder — finalize with current futures price
            target_dte=new_dte,
            target_expiration=new_expiry,
            spec_rationale=f"Roll: new short futures ({new_dte} DTE) — price TBD at execution",
            structure_type=StructureType.FUTURES_SHORT,
            order_side=OrderSide.CREDIT,
            legs=[
                LegSpec(
                    role="short_future",
                    action=LegAction.SELL_TO_OPEN,
                    option_type="future",
                    strike=0.0,  # Placeholder — finalize with current futures price
                    strike_label="TBD (roll — needs current futures price)",
                    expiration=new_expiry,
                    days_to_expiry=new_dte,
                    atm_iv_at_expiry=0.0,
                    quantity=1,
                ),
            ],
            max_profit_desc=f"Roll: new short futures ({new_dte} DTE)",
            max_loss_desc="Roll cost = basis change on close + open",
        )

    elif hedge_type == "collar":
        # Roll both legs
        return TradeSpec(
            ticker=ticker,
            underlying_price=0.0,
            target_dte=new_dte,
            target_expiration=new_expiry,
            spec_rationale=f"Roll: new collar ({new_dte} DTE) — strikes TBD at execution",
            structure_type=StructureType.CREDIT_SPREAD,
            order_side=OrderSide.DEBIT,
            legs=[
                LegSpec(
                    role="long_put",
                    action=LegAction.BUY_TO_OPEN,
                    option_type="put",
                    strike=0.0,
                    strike_label="TBD (roll put leg)",
                    expiration=new_expiry,
                    days_to_expiry=new_dte,
                    atm_iv_at_expiry=0.25,
                    quantity=1,
                ),
                LegSpec(
                    role="short_call",
                    action=LegAction.SELL_TO_OPEN,
                    option_type="call",
                    strike=0.0,
                    strike_label="TBD (roll call leg)",
                    expiration=new_expiry,
                    days_to_expiry=new_dte,
                    atm_iv_at_expiry=0.25,
                    quantity=1,
                ),
            ],
            max_profit_desc=f"Roll: new collar ({new_dte} DTE)",
            max_loss_desc="Roll cost = close old collar + open new",
        )

    # Unknown hedge type — no roll spec
    return None


def compute_hedge_effectiveness(
    positions: list[dict],
    hedges: list[dict],
    market_move_pct: float,
) -> HedgeEffectiveness:
    """Simulate a market move and measure how much hedges saved.

    Uses a linear delta approximation: loss = value × delta × move_pct.

    Args:
        positions: List of position dicts with:
            - ticker: str
            - value: float (total position value)
            - delta: float (position delta; default 1.0 for long equity)
        hedges: List of hedge dicts with:
            - ticker: str
            - delta_reduction: float (0-1, fraction of position loss the hedge offsets)
            - cost: float (total hedge cost already paid)
        market_move_pct: Simulated move (e.g., -0.05 = -5% drop).

    Returns:
        HedgeEffectiveness with unhedged vs hedged P&L analysis.
    """
    # Build hedge lookup
    hedge_by_ticker: dict[str, dict] = {h["ticker"]: h for h in hedges}

    # Unhedged loss: sum(value × delta × |move|) for directional positions
    unhedged_loss = 0.0
    for pos in positions:
        pos_value = float(pos.get("value", 0))
        pos_delta = float(pos.get("delta", 1.0))
        # Loss = value × delta × |move| (for a drop, delta-positive position loses)
        pos_loss = pos_value * pos_delta * market_move_pct
        unhedged_loss += pos_loss

    # Take absolute value (we measure loss magnitude, not signed P&L)
    unhedged_loss = abs(unhedged_loss)

    # Hedged loss: subtract savings from each hedged position
    hedged_loss = unhedged_loss
    total_hedge_cost = 0.0

    for pos in positions:
        ticker = pos.get("ticker", "")
        hedge = hedge_by_ticker.get(ticker)
        if hedge:
            pos_value = float(pos.get("value", 0))
            pos_delta = float(pos.get("delta", 1.0))
            delta_reduction = float(hedge.get("delta_reduction", 0.0))
            # Savings = what the hedge offsets from the unhedged loss
            pos_savings = abs(pos_value * pos_delta * market_move_pct) * delta_reduction
            hedged_loss -= pos_savings
            total_hedge_cost += float(hedge.get("cost", 0.0))

    hedged_loss = max(hedged_loss, 0.0)

    savings = unhedged_loss - hedged_loss
    savings_pct = (savings / unhedged_loss * 100) if unhedged_loss > 0 else 0.0
    net_benefit = savings - total_hedge_cost
    roi = (net_benefit / total_hedge_cost) if total_hedge_cost > 0 else 0.0

    # Commentary
    move_pct_abs = abs(market_move_pct) * 100
    if net_benefit > 0:
        commentary = (
            f"Hedges saved {savings_pct:.0f}% of potential loss in a {move_pct_abs:.1f}% move. "
            f"Hedge cost: {total_hedge_cost:,.0f}. Net benefit: {net_benefit:,.0f}. "
            f"ROI on hedge: {roi:.1f}x."
        )
    elif savings > 0:
        commentary = (
            f"Hedges reduced loss by {savings_pct:.0f}% but cost ({total_hedge_cost:,.0f}) "
            f"exceeded savings ({savings:,.0f}). "
            f"The move was too small to justify hedge cost."
        )
    else:
        commentary = (
            f"No meaningful hedge benefit in a {move_pct_abs:.1f}% move scenario. "
            f"Consider cheaper hedges or different strike placement."
        )

    return HedgeEffectiveness(
        market_move_pct=market_move_pct,
        portfolio_loss_unhedged=round(unhedged_loss, 2),
        portfolio_loss_hedged=round(hedged_loss, 2),
        hedge_savings=round(savings, 2),
        hedge_savings_pct=round(savings_pct, 1),
        cost_of_hedges=round(total_hedge_cost, 2),
        net_benefit=round(net_benefit, 2),
        roi_on_hedge=round(roi, 2),
        commentary=commentary,
    )
