"""Wheel strategy state machine — MA decides the next action, eTrading executes.

The Wheel: sell put → assigned → sell covered call → called away → repeat.

eTrading passes current wheel state, MA returns the next action.
eTrading builds the state machine (persistence, execution).
MA provides the decision intelligence (what to do next, at what price).

State flow:
    IDLE → SELLING_PUT → PUT_OPEN → ASSIGNED → SELLING_CALL → CALL_OPEN → CALLED_AWAY → IDLE
                           ↓                                      ↓
                       PUT_EXPIRED                            CALL_EXPIRED
                       (keep premium,                         (keep premium + stock,
                        go to SELLING_PUT)                     go to SELLING_CALL)
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class WheelState(StrEnum):
    """Current state in the wheel cycle."""

    IDLE = "idle"                     # No position — ready to start
    SELLING_PUT = "selling_put"       # Ready to sell a cash-secured put
    PUT_OPEN = "put_open"             # Put is open, waiting for expiry/assignment
    ASSIGNED = "assigned"             # Put was assigned — we own the stock
    SELLING_CALL = "selling_call"     # Ready to sell a covered call
    CALL_OPEN = "call_open"           # Call is open, waiting for expiry/called away
    CALLED_AWAY = "called_away"      # Call was exercised — stock sold
    PUT_EXPIRED = "put_expired"       # Put expired worthless — keep premium
    CALL_EXPIRED = "call_expired"     # Call expired worthless — keep premium + stock


class WheelAction(StrEnum):
    """Action MA recommends for next step."""

    SELL_PUT = "sell_put"             # Sell a cash-secured put
    HOLD_PUT = "hold_put"             # Put is open — wait
    CLOSE_PUT = "close_put"           # Close put early (take profit or cut loss)
    ACCEPT_ASSIGNMENT = "accept_assignment"  # Get assigned — buy the stock
    SELL_CALL = "sell_call"           # Sell a covered call on owned stock
    HOLD_CALL = "hold_call"           # Call is open — wait
    CLOSE_CALL = "close_call"        # Close call early
    ACCEPT_CALLAWAY = "accept_callaway"  # Let stock be called away
    WAIT = "wait"                     # Don't act — conditions not right
    STOP_WHEEL = "stop_wheel"         # Exit wheel entirely (regime change, etc.)


class WheelPosition(BaseModel):
    """Current wheel position — eTrading provides this, MA decides next action."""

    ticker: str
    state: WheelState
    # Put leg (if open)
    put_strike: float | None = None
    put_premium_received: float | None = None
    put_expiration: date | None = None
    put_current_price: float | None = None  # Current mid price of put
    # Stock (if assigned)
    stock_entry_price: float | None = None  # What we paid (= put strike)
    stock_quantity: int = 0
    effective_cost_basis: float | None = None  # Entry - premiums collected
    # Call leg (if open)
    call_strike: float | None = None
    call_premium_received: float | None = None
    call_expiration: date | None = None
    call_current_price: float | None = None
    # Cumulative
    total_premiums_collected: float = 0.0
    cycles_completed: int = 0
    # Market
    current_underlying_price: float = 0.0


class WheelDecision(BaseModel):
    """MA's decision for the next wheel action."""

    ticker: str
    current_state: WheelState
    recommended_action: WheelAction
    next_state: WheelState        # State after action is executed

    # Trade details (if action involves a trade)
    strike: float | None = None
    premium_target: float | None = None
    expiration_dte: int | None = None
    delta_target: float | None = None

    # Risk context
    regime_context: str
    regime_suitable: bool         # Is current regime good for wheel?
    urgency: str                  # "immediate", "soon", "when_ready", "wait"

    # P&L context
    total_premiums_collected: float
    effective_cost_basis: float | None
    unrealized_pnl: float | None

    rationale: str
    commentary: list[str]


def decide_wheel_action(
    position: WheelPosition,
    regime_id: int = 1,
    iv: float = 0.20,
    atr_pct: float = 1.5,
    put_delta_target: float = 0.30,
    call_delta_target: float = 0.30,
    target_dte: int = 35,
    profit_take_pct: float = 0.50,   # Close at 50% of max profit
) -> WheelDecision:
    """Given current wheel state, decide the next action.

    eTrading calls this with the current position state.
    MA returns what to do next + trade parameters.
    eTrading executes and updates state.
    """
    regime_names = {1: "R1 Low-Vol MR", 2: "R2 High-Vol MR",
                    3: "R3 Low-Vol Trend", 4: "R4 High-Vol Trend"}
    regime_name = regime_names.get(regime_id, f"R{regime_id}")

    # Regime suitability
    regime_suitable = regime_id in (1, 2)
    regime_context = f"Regime R{regime_id} ({regime_name})"
    if regime_id == 4:
        regime_context += " — DANGEROUS for wheel"
    elif regime_id == 3:
        regime_context += " — risky (trending)"
    elif regime_id == 2:
        regime_context += " — good (high premiums, mean reverting)"
    elif regime_id == 1:
        regime_context += " — ideal (low vol, stable)"

    price = position.current_underlying_price
    commentary: list[str] = []

    # ── STATE: IDLE or SELLING_PUT ──
    if position.state in (WheelState.IDLE, WheelState.SELLING_PUT, WheelState.PUT_EXPIRED):

        if regime_id == 4:
            return WheelDecision(
                ticker=position.ticker, current_state=position.state,
                recommended_action=WheelAction.WAIT, next_state=position.state,
                regime_context=regime_context, regime_suitable=False,
                urgency="wait",
                total_premiums_collected=position.total_premiums_collected,
                effective_cost_basis=position.effective_cost_basis,
                unrealized_pnl=None,
                rationale="R4 explosive — do NOT sell puts. Wait for regime to calm.",
                commentary=["Wheel paused: R4 regime too volatile for put selling",
                            "Assignment risk too high — could catch a falling knife"],
            )

        # Calculate put parameters
        put_strike = round(price * (1 - put_delta_target * iv * (target_dte / 365) ** 0.5), 2)
        # Snap to nearest dollar
        put_strike = round(put_strike)
        premium_est = round(price * iv * (target_dte / 365) ** 0.5 * put_delta_target * 1.5, 2)

        commentary.append(f"Sell {put_strike}P at ~${premium_est:.2f} ({target_dte}d)")
        commentary.append(f"If assigned: buy {position.ticker} at ${put_strike} (effective ${put_strike - premium_est:.2f})")
        commentary.append(f"Capital required: ${put_strike * 100:,.0f} (cash secured)")

        return WheelDecision(
            ticker=position.ticker, current_state=position.state,
            recommended_action=WheelAction.SELL_PUT,
            next_state=WheelState.PUT_OPEN,
            strike=put_strike, premium_target=premium_est,
            expiration_dte=target_dte, delta_target=put_delta_target,
            regime_context=regime_context, regime_suitable=regime_suitable,
            urgency="when_ready",
            total_premiums_collected=position.total_premiums_collected,
            effective_cost_basis=None,
            unrealized_pnl=None,
            rationale=f"Sell {put_strike}P — collect premium while waiting to buy at discount",
            commentary=commentary,
        )

    # ── STATE: PUT_OPEN ──
    elif position.state == WheelState.PUT_OPEN:

        if position.put_current_price is None or position.put_premium_received is None:
            return WheelDecision(
                ticker=position.ticker, current_state=position.state,
                recommended_action=WheelAction.HOLD_PUT, next_state=WheelState.PUT_OPEN,
                regime_context=regime_context, regime_suitable=regime_suitable,
                urgency="wait",
                total_premiums_collected=position.total_premiums_collected,
                effective_cost_basis=None, unrealized_pnl=None,
                rationale="Holding put — waiting for data to decide",
                commentary=["Need current put price to evaluate"],
            )

        # Check if we should take profit early
        pnl_pct = (position.put_premium_received - position.put_current_price) / position.put_premium_received
        commentary.append(f"Put P&L: {pnl_pct:.0%} of max profit")

        if pnl_pct >= profit_take_pct:
            commentary.append(f"Profit target hit ({pnl_pct:.0%} >= {profit_take_pct:.0%}) — close and re-sell")
            return WheelDecision(
                ticker=position.ticker, current_state=position.state,
                recommended_action=WheelAction.CLOSE_PUT,
                next_state=WheelState.SELLING_PUT,
                regime_context=regime_context, regime_suitable=regime_suitable,
                urgency="soon",
                total_premiums_collected=position.total_premiums_collected,
                effective_cost_basis=None,
                unrealized_pnl=round((position.put_premium_received - position.put_current_price) * 100, 2),
                rationale=f"Take profit at {pnl_pct:.0%} — close put and sell new one",
                commentary=commentary,
            )

        # Check regime change — should we bail?
        if regime_id == 4:
            commentary.append("REGIME CHANGED to R4 — close put to avoid assignment at bad price")
            return WheelDecision(
                ticker=position.ticker, current_state=position.state,
                recommended_action=WheelAction.CLOSE_PUT,
                next_state=WheelState.IDLE,
                regime_context=regime_context, regime_suitable=False,
                urgency="immediate",
                total_premiums_collected=position.total_premiums_collected,
                effective_cost_basis=None,
                unrealized_pnl=round((position.put_premium_received - position.put_current_price) * 100, 2),
                rationale="R4 regime — close put immediately to avoid assignment in crash",
                commentary=commentary,
            )

        # Otherwise hold
        commentary.append("Put working — theta decaying in your favor")
        return WheelDecision(
            ticker=position.ticker, current_state=position.state,
            recommended_action=WheelAction.HOLD_PUT, next_state=WheelState.PUT_OPEN,
            regime_context=regime_context, regime_suitable=regime_suitable,
            urgency="wait",
            total_premiums_collected=position.total_premiums_collected,
            effective_cost_basis=None,
            unrealized_pnl=round((position.put_premium_received - position.put_current_price) * 100, 2),
            rationale=f"Hold put — {pnl_pct:.0%} profit, waiting for {profit_take_pct:.0%} target or expiry",
            commentary=commentary,
        )

    # ── STATE: ASSIGNED or SELLING_CALL or CALL_EXPIRED ──
    elif position.state in (WheelState.ASSIGNED, WheelState.SELLING_CALL, WheelState.CALL_EXPIRED):

        entry = position.stock_entry_price or price
        effective_basis = position.effective_cost_basis or entry

        if regime_id == 4:
            # In R4 with stock — consider hedging instead of selling call
            commentary.append("R4 regime — stock at risk. Consider protective put instead of covered call.")
            commentary.append("If you sell a call, you cap upside but still have full downside.")
            return WheelDecision(
                ticker=position.ticker, current_state=position.state,
                recommended_action=WheelAction.WAIT,
                next_state=position.state,
                regime_context=regime_context, regime_suitable=False,
                urgency="wait",
                total_premiums_collected=position.total_premiums_collected,
                effective_cost_basis=effective_basis,
                unrealized_pnl=round((price - effective_basis) * (position.stock_quantity or 100), 2),
                rationale="R4 — wait before selling call. Consider hedging stock position.",
                commentary=commentary,
            )

        # Sell covered call above cost basis
        call_strike = round(max(price * 1.03, effective_basis * 1.02))  # At least 2-3% above basis
        call_premium_est = round(price * iv * (target_dte / 365) ** 0.5 * call_delta_target * 1.5, 2)

        commentary.append(f"Sell {call_strike}C at ~${call_premium_est:.2f} ({target_dte}d)")
        commentary.append(f"If called away: sell at ${call_strike} + ${call_premium_est:.2f} premium")
        commentary.append(f"Effective cost basis: ${effective_basis:.2f} (breakeven)")

        # Don't sell call below cost basis (would lock in a loss)
        if call_strike < effective_basis:
            commentary.append(f"WARNING: call strike ${call_strike} below cost basis ${effective_basis:.2f}")
            commentary.append("Selling here locks in a loss if called. Consider waiting for stock to recover.")

        return WheelDecision(
            ticker=position.ticker, current_state=position.state,
            recommended_action=WheelAction.SELL_CALL,
            next_state=WheelState.CALL_OPEN,
            strike=call_strike, premium_target=call_premium_est,
            expiration_dte=target_dte, delta_target=call_delta_target,
            regime_context=regime_context, regime_suitable=regime_suitable,
            urgency="when_ready",
            total_premiums_collected=position.total_premiums_collected,
            effective_cost_basis=effective_basis,
            unrealized_pnl=round((price - effective_basis) * (position.stock_quantity or 100), 2),
            rationale=f"Sell {call_strike}C — collect premium while waiting to sell at profit",
            commentary=commentary,
        )

    # ── STATE: CALL_OPEN ──
    elif position.state == WheelState.CALL_OPEN:

        if position.call_current_price is None or position.call_premium_received is None:
            return WheelDecision(
                ticker=position.ticker, current_state=position.state,
                recommended_action=WheelAction.HOLD_CALL, next_state=WheelState.CALL_OPEN,
                regime_context=regime_context, regime_suitable=regime_suitable,
                urgency="wait",
                total_premiums_collected=position.total_premiums_collected,
                effective_cost_basis=position.effective_cost_basis,
                unrealized_pnl=None,
                rationale="Holding call — waiting for data",
                commentary=["Need current call price to evaluate"],
            )

        pnl_pct = (position.call_premium_received - position.call_current_price) / position.call_premium_received

        if pnl_pct >= profit_take_pct:
            commentary.append(f"Call profit target hit ({pnl_pct:.0%}) — close and re-sell")
            return WheelDecision(
                ticker=position.ticker, current_state=position.state,
                recommended_action=WheelAction.CLOSE_CALL,
                next_state=WheelState.SELLING_CALL,
                regime_context=regime_context, regime_suitable=regime_suitable,
                urgency="soon",
                total_premiums_collected=position.total_premiums_collected,
                effective_cost_basis=position.effective_cost_basis,
                unrealized_pnl=round((position.call_premium_received - position.call_current_price) * 100, 2),
                rationale=f"Take profit at {pnl_pct:.0%} — close call and sell new one",
                commentary=commentary,
            )

        # Hold
        commentary.append(f"Call working — {pnl_pct:.0%} profit, holding")
        return WheelDecision(
            ticker=position.ticker, current_state=position.state,
            recommended_action=WheelAction.HOLD_CALL, next_state=WheelState.CALL_OPEN,
            regime_context=regime_context, regime_suitable=regime_suitable,
            urgency="wait",
            total_premiums_collected=position.total_premiums_collected,
            effective_cost_basis=position.effective_cost_basis,
            unrealized_pnl=round((position.call_premium_received - position.call_current_price) * 100, 2),
            rationale=f"Hold call — {pnl_pct:.0%} profit, target {profit_take_pct:.0%}",
            commentary=commentary,
        )

    # ── STATE: CALLED_AWAY ──
    elif position.state == WheelState.CALLED_AWAY:

        commentary.append(f"Stock called away. Cycle complete ({position.cycles_completed + 1} total)")
        commentary.append(f"Total premiums collected: ${position.total_premiums_collected:,.2f}")
        commentary.append("Ready to start new cycle — sell put to re-enter")

        return WheelDecision(
            ticker=position.ticker, current_state=position.state,
            recommended_action=WheelAction.SELL_PUT,
            next_state=WheelState.PUT_OPEN,
            strike=round(price * (1 - put_delta_target * iv * (target_dte / 365) ** 0.5)),
            premium_target=round(price * iv * (target_dte / 365) ** 0.5 * put_delta_target * 1.5, 2),
            expiration_dte=target_dte, delta_target=put_delta_target,
            regime_context=regime_context, regime_suitable=regime_suitable,
            urgency="when_ready",
            total_premiums_collected=position.total_premiums_collected,
            effective_cost_basis=None,
            unrealized_pnl=None,
            rationale="Cycle complete — sell new put to restart wheel",
            commentary=commentary,
        )

    # Fallback
    return WheelDecision(
        ticker=position.ticker, current_state=position.state,
        recommended_action=WheelAction.WAIT, next_state=position.state,
        regime_context=regime_context, regime_suitable=regime_suitable,
        urgency="wait",
        total_premiums_collected=position.total_premiums_collected,
        effective_cost_basis=position.effective_cost_basis,
        unrealized_pnl=None,
        rationale=f"Unhandled state: {position.state}",
        commentary=[f"State {position.state} not handled — wait"],
    )
