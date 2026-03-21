"""Pure functions for handling assignment/exercise events.

When a short option is assigned, the trader needs a systematic decision:
sell the shares, hold and wheel, or cover a short position.

Also provides BEFORE-assignment risk warnings via assess_assignment_risk().

All functions are stateless — no I/O, no side effects.
"""
from __future__ import annotations

from datetime import date, timedelta

from market_analyzer.models.assignment import (
    AssignmentAction,
    AssignmentAnalysis,
    AssignmentRisk,
    AssignmentRiskResult,
    AssignmentType,
)
from market_analyzer.models.opportunity import LegAction, LegSpec, OrderSide, StructureType, TradeSpec
from market_analyzer.opportunity.option_plays._trade_spec_helpers import snap_strike


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_equity_sell_spec(
    ticker: str,
    shares: int,
    current_price: float,
    reason: str,
) -> TradeSpec:
    """Build a TradeSpec to sell assigned shares at market."""
    return TradeSpec(
        ticker=ticker,
        legs=[LegSpec(
            role="equity_sell",
            action=LegAction.SELL_TO_CLOSE,
            quantity=shares,
            option_type="equity",
            strike=0,
            strike_label=f"Sell {shares} shares at market",
            expiration=date.today(),
            days_to_expiry=0,
            atm_iv_at_expiry=0.0,
        )],
        underlying_price=current_price,
        target_dte=0,
        target_expiration=date.today(),
        spec_rationale=f"ASSIGNMENT RESPONSE: Sell {shares} shares of {ticker} — {reason}",
        structure_type=StructureType.EQUITY_SELL,
        order_side=OrderSide.CREDIT,
        entry_mode="market",
    )


def _build_partial_sell_spec(
    ticker: str,
    shares_to_sell: int,
    current_price: float,
    reason: str,
) -> TradeSpec:
    """Build a TradeSpec to sell a portion of assigned shares."""
    return TradeSpec(
        ticker=ticker,
        legs=[LegSpec(
            role="equity_sell",
            action=LegAction.SELL_TO_CLOSE,
            quantity=shares_to_sell,
            option_type="equity",
            strike=0,
            strike_label=f"Sell {shares_to_sell} shares at market (partial)",
            expiration=date.today(),
            days_to_expiry=0,
            atm_iv_at_expiry=0.0,
        )],
        underlying_price=current_price,
        target_dte=0,
        target_expiration=date.today(),
        spec_rationale=f"ASSIGNMENT RESPONSE (PARTIAL): Sell {shares_to_sell} shares of {ticker} — {reason}",
        structure_type=StructureType.EQUITY_SELL,
        order_side=OrderSide.CREDIT,
        entry_mode="market",
    )


def _build_cover_short_spec(
    ticker: str,
    shares: int,
    current_price: float,
) -> TradeSpec:
    """Build a TradeSpec to buy to cover a short stock position."""
    return TradeSpec(
        ticker=ticker,
        legs=[LegSpec(
            role="equity_buy",
            action=LegAction.BUY_TO_CLOSE,
            quantity=shares,
            option_type="equity",
            strike=0,
            strike_label=f"Buy {shares} shares at market (cover short)",
            expiration=date.today(),
            days_to_expiry=0,
            atm_iv_at_expiry=0.0,
        )],
        underlying_price=current_price,
        target_dte=0,
        target_expiration=date.today(),
        spec_rationale=f"ASSIGNMENT RESPONSE: Cover short {shares} shares of {ticker} — naked short risk",
        structure_type=StructureType.EQUITY_BUY,
        order_side=OrderSide.DEBIT,
        entry_mode="market",
    )


def _build_covered_call_spec(
    ticker: str,
    contracts: int,
    current_price: float,
    atr: float,
    iv_rank: float | None,
) -> TradeSpec:
    """Build a covered call TradeSpec for the wheel strategy.

    Sell call at 1 ATR above current price, targeting 30 DTE.
    """
    raw_call_strike = current_price + atr
    call_strike = snap_strike(raw_call_strike, current_price)
    # Ensure strike is strictly above current price after snapping
    if call_strike <= current_price:
        call_strike = snap_strike(current_price + atr * 1.1, current_price)

    target_dte = 30
    exp = date.today() + timedelta(days=target_dte)
    atm_iv = (iv_rank / 100.0) if iv_rank is not None else 0.25

    return TradeSpec(
        ticker=ticker,
        legs=[LegSpec(
            role="covered_call",
            action=LegAction.SELL_TO_OPEN,
            quantity=contracts,
            option_type="call",
            strike=call_strike,
            strike_label=f"Covered call ~1 ATR above ({call_strike:.0f})",
            expiration=exp,
            days_to_expiry=target_dte,
            atm_iv_at_expiry=atm_iv,
        )],
        underlying_price=current_price,
        target_dte=target_dte,
        target_expiration=exp,
        spec_rationale=f"WHEEL: Sell covered call on assigned shares of {ticker} — 1 ATR above @ {call_strike:.0f}",
        structure_type=StructureType.COVERED_CALL,
        order_side=OrderSide.CREDIT,
        profit_target_pct=0.50,
        stop_loss_pct=None,  # Covered call: shares are collateral, no stop needed
        exit_dte=7,
        exit_notes=[
            "Close at 50% profit to free capital for next cycle",
            "Do not set stop-loss — shares serve as collateral",
            "Roll out if challenged before expiry",
        ],
    )


def _compute_margin_impact(capital_tied_up: float, available_bp: float) -> str:
    """Classify margin impact given capital tied up and available buying power."""
    if available_bp < capital_tied_up * 0.25:
        return "margin_call"
    elif available_bp < capital_tied_up * 0.5:
        return "margin_warning"
    return "within_limits"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def handle_assignment(
    ticker: str,
    assignment_type: AssignmentType,
    strike_price: float,
    contracts: int,
    current_price: float,
    regime_id: int,
    regime_confidence: float,
    atr: float,
    atr_pct: float,
    account_nlv: float,
    available_bp: float,
    rsi: float | None = None,
    iv_rank: float | None = None,
    existing_shares: int = 0,
    is_etf: bool = True,
    lot_size: int = 100,
) -> AssignmentAnalysis:
    """Analyze an assignment event and return a concrete action with TradeSpec.

    Args:
        ticker:            Underlying symbol.
        assignment_type:   PUT_ASSIGNED, CALL_ASSIGNED, or LONG_EXERCISED.
        strike_price:      Strike at which assignment occurred.
        contracts:         Number of contracts assigned.
        current_price:     Current market price of the underlying.
        regime_id:         Current regime (1=R1 low-vol MR, 2=R2 high-vol MR,
                           3=R3 low-vol trending, 4=R4 high-vol trending).
        regime_confidence: Regime detection confidence (0-1).
        atr:               Average True Range in dollars.
        atr_pct:           ATR as % of current price.
        account_nlv:       Total account Net Liquidating Value.
        available_bp:      Available buying power.
        rsi:               RSI (optional, used for individual stock wheel logic).
        iv_rank:           IV rank 0-100 (optional).
        existing_shares:   Shares already owned (used for call assignment).
        is_etf:            True if ticker is an ETF (ETFs are preferred for wheel).
        lot_size:          Shares per contract (default 100).

    Returns:
        AssignmentAnalysis with recommended_action and response_trade_spec.
    """
    shares = contracts * lot_size
    capital_tied_up = strike_price * shares
    capital_pct = capital_tied_up / account_nlv if account_nlv > 0 else 1.0

    margin_impact = _compute_margin_impact(capital_tied_up, available_bp)

    # Compute unrealized P&L
    if assignment_type == AssignmentType.PUT_ASSIGNED:
        # Assigned on put → bought shares at strike. Loss if price fell below strike.
        unrealized_pnl = (current_price - strike_price) * shares
    elif assignment_type == AssignmentType.CALL_ASSIGNED:
        # Assigned on call → sold shares at strike. Gain if price was above strike (they were called away).
        unrealized_pnl = (strike_price - current_price) * shares
    else:
        # LONG_EXERCISED — same as put assigned for P&L purposes
        unrealized_pnl = (current_price - strike_price) * shares

    unrealized_pnl_pct = unrealized_pnl / capital_tied_up if capital_tied_up > 0 else 0.0

    # -----------------------------------------------------------------------
    # CALL ASSIGNMENT LOGIC
    # -----------------------------------------------------------------------
    if assignment_type == AssignmentType.CALL_ASSIGNED:
        if existing_shares >= shares:
            # Covered call was assigned — shares called away. This is the ideal outcome.
            regime_rationale = (
                f"R{regime_id} — covered call assigned as intended; shares delivered at profit up to strike."
            )
            return AssignmentAnalysis(
                ticker=ticker,
                assignment_type=assignment_type,
                shares=shares,
                assignment_price=strike_price,
                current_price=current_price,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                capital_tied_up=0.0,  # Shares are gone
                capital_pct_of_nlv=0.0,
                margin_impact="within_limits",
                recommended_action=AssignmentAction.SELL_IMMEDIATELY,
                urgency="this_week",
                reasons=["Covered call assigned — shares delivered at strike price, premium retained"],
                response_trade_spec=None,
                wheel_trade_spec=None,
                wheel_rationale=None,
                regime_id=regime_id,
                regime_rationale=regime_rationale,
            )
        else:
            # Naked short call assigned → short stock. Extremely dangerous for small accounts.
            reason = f"Short call assigned without owning shares — now short {shares} shares of {ticker}"
            cover_spec = _build_cover_short_spec(ticker, shares, current_price)
            regime_rationale = (
                f"R{regime_id} — naked short stock position; cover immediately to prevent unlimited loss."
            )
            return AssignmentAnalysis(
                ticker=ticker,
                assignment_type=assignment_type,
                shares=shares,
                assignment_price=strike_price,
                current_price=current_price,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                capital_tied_up=current_price * shares,
                capital_pct_of_nlv=min(current_price * shares / account_nlv, 1.0) if account_nlv > 0 else 1.0,
                margin_impact="margin_call",
                recommended_action=AssignmentAction.COVER_SHORT,
                urgency="immediate",
                reasons=[reason],
                response_trade_spec=cover_spec,
                wheel_trade_spec=None,
                wheel_rationale=None,
                regime_id=regime_id,
                regime_rationale=regime_rationale,
            )

    # -----------------------------------------------------------------------
    # PUT ASSIGNMENT LOGIC (and LONG_EXERCISED treated similarly)
    # -----------------------------------------------------------------------

    # RULE 1: Capital concentration > 50% → sell immediately (hardcoded emergency)
    if capital_pct > 0.50:
        reason = (
            f"Position size ${capital_tied_up:,.0f} is {capital_pct:.0%} of NLV ${account_nlv:,.0f} "
            f"— exceeds 50% concentration limit; unacceptable single-name risk"
        )
        sell_spec = _build_equity_sell_spec(ticker, shares, current_price, reason)
        regime_rationale = f"R{regime_id} ({regime_confidence:.0%} confidence) — capital concentration overrides regime logic."
        return AssignmentAnalysis(
            ticker=ticker,
            assignment_type=assignment_type,
            shares=shares,
            assignment_price=strike_price,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            capital_tied_up=capital_tied_up,
            capital_pct_of_nlv=capital_pct,
            margin_impact=margin_impact,
            recommended_action=AssignmentAction.SELL_IMMEDIATELY,
            urgency="immediate",
            reasons=[reason],
            response_trade_spec=sell_spec,
            wheel_trade_spec=None,
            wheel_rationale=None,
            regime_id=regime_id,
            regime_rationale=regime_rationale,
        )

    # RULE 2: R4 explosive trending → sell regardless of size (regime check before partial sell)
    if regime_id == 4:
        reason = (
            f"R4 high-vol trending regime — do not hold equity long in explosive regime; "
            f"assignment likely to worsen significantly"
        )
        sell_spec = _build_equity_sell_spec(ticker, shares, current_price, reason)
        regime_rationale = f"R4 ({regime_confidence:.0%} confidence): explosive high-vol trend. Equity holding unsuitable."
        return AssignmentAnalysis(
            ticker=ticker,
            assignment_type=assignment_type,
            shares=shares,
            assignment_price=strike_price,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            capital_tied_up=capital_tied_up,
            capital_pct_of_nlv=capital_pct,
            margin_impact=margin_impact,
            recommended_action=AssignmentAction.SELL_IMMEDIATELY,
            urgency="immediate",
            reasons=[reason],
            response_trade_spec=sell_spec,
            wheel_trade_spec=None,
            wheel_rationale=None,
            regime_id=regime_id,
            regime_rationale=regime_rationale,
        )

    # RULE 3: R3 trending → assignment likely to get worse (regime check before partial sell)
    if regime_id == 3:
        reason = (
            f"R3 low-vol trending regime — directional trend means assignment likely to deepen; "
            f"exit to prevent larger loss"
        )
        sell_spec = _build_equity_sell_spec(ticker, shares, current_price, reason)
        regime_rationale = f"R3 ({regime_confidence:.0%} confidence): directional trend. Mean-reversion unlikely; sell assigned shares."
        return AssignmentAnalysis(
            ticker=ticker,
            assignment_type=assignment_type,
            shares=shares,
            assignment_price=strike_price,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            capital_tied_up=capital_tied_up,
            capital_pct_of_nlv=capital_pct,
            margin_impact=margin_impact,
            recommended_action=AssignmentAction.SELL_IMMEDIATELY,
            urgency="today",
            reasons=[reason],
            response_trade_spec=sell_spec,
            wheel_trade_spec=None,
            wheel_rationale=None,
            regime_id=regime_id,
            regime_rationale=regime_rationale,
        )

    # RULE 4: Capital 30–50% → partial sell to reduce concentration
    if capital_pct > 0.30:
        target_capital = account_nlv * 0.20  # Reduce to 20% of NLV
        shares_to_keep = int(target_capital / strike_price / lot_size) * lot_size
        shares_to_sell = shares - max(shares_to_keep, 0)
        shares_to_sell = max(shares_to_sell, lot_size)  # Sell at least one lot

        reason = (
            f"Position size ${capital_tied_up:,.0f} is {capital_pct:.0%} of NLV "
            f"— reduce to ~20% of NLV by selling {shares_to_sell} of {shares} shares"
        )
        partial_spec = _build_partial_sell_spec(ticker, shares_to_sell, current_price, reason)
        regime_rationale = f"R{regime_id} ({regime_confidence:.0%} confidence) — size reduction required before regime logic applies."
        return AssignmentAnalysis(
            ticker=ticker,
            assignment_type=assignment_type,
            shares=shares,
            assignment_price=strike_price,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            capital_tied_up=capital_tied_up,
            capital_pct_of_nlv=capital_pct,
            margin_impact=margin_impact,
            recommended_action=AssignmentAction.PARTIAL_SELL,
            urgency="today",
            reasons=[reason],
            response_trade_spec=partial_spec,
            wheel_trade_spec=None,
            wheel_rationale=f"After partial sell, consider covered call on remaining {shares - shares_to_sell} shares if R1/R2.",
            regime_id=regime_id,
            regime_rationale=regime_rationale,
        )

    # RULE 5: Margin pressure → sell immediately even if position size is OK
    if available_bp < capital_tied_up * 0.5:
        reason = (
            f"Insufficient buying power (${available_bp:,.0f} available vs ${capital_tied_up * 0.5:,.0f} required) "
            f"— selling to prevent margin call"
        )
        sell_spec = _build_equity_sell_spec(ticker, shares, current_price, reason)
        regime_rationale = f"R{regime_id} ({regime_confidence:.0%} confidence) — margin pressure overrides regime logic."
        return AssignmentAnalysis(
            ticker=ticker,
            assignment_type=assignment_type,
            shares=shares,
            assignment_price=strike_price,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            capital_tied_up=capital_tied_up,
            capital_pct_of_nlv=capital_pct,
            margin_impact=margin_impact,
            recommended_action=AssignmentAction.SELL_IMMEDIATELY,
            urgency="immediate",
            reasons=[reason],
            response_trade_spec=sell_spec,
            wheel_trade_spec=None,
            wheel_rationale=None,
            regime_id=regime_id,
            regime_rationale=regime_rationale,
        )

    # RULE 6: R1/R2 mean-reverting + manageable size → consider wheel
    if regime_id in (1, 2) and capital_pct <= 0.30:
        if is_etf:
            # ETFs: wheel preferred in R1/R2 — diversified, typically stable
            covered_call = _build_covered_call_spec(ticker, contracts, current_price, atr, iv_rank)
            regime_label = "R1 low-vol mean-reverting" if regime_id == 1 else "R2 high-vol mean-reverting"
            wheel_rationale = (
                f"{regime_label} + ETF + {capital_pct:.0%} of NLV — "
                f"sell covered call to collect theta while waiting for mean reversion; "
                f"ATR target strike: {covered_call.legs[0].strike:.0f}"
            )
            regime_rationale = f"R{regime_id} ({regime_confidence:.0%} confidence): mean-reverting. ETF assignment → wheel is optimal income strategy."
            reasons = [
                f"{regime_label} — mean reversion expected; holding makes sense",
                f"ETF provides diversification; single-name risk is limited",
                f"Position is {capital_pct:.0%} of NLV — within manageable limits",
                f"Selling covered call at {covered_call.legs[0].strike:.0f} generates income while waiting",
            ]
            return AssignmentAnalysis(
                ticker=ticker,
                assignment_type=assignment_type,
                shares=shares,
                assignment_price=strike_price,
                current_price=current_price,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                capital_tied_up=capital_tied_up,
                capital_pct_of_nlv=capital_pct,
                margin_impact=margin_impact,
                recommended_action=AssignmentAction.HOLD_AND_WHEEL,
                urgency="this_week",
                reasons=reasons,
                response_trade_spec=None,  # No immediate sell — hold shares
                wheel_trade_spec=covered_call,
                wheel_rationale=wheel_rationale,
                regime_id=regime_id,
                regime_rationale=regime_rationale,
            )

        else:
            # Individual stock: wheel only if IV rank is elevated enough to justify holding
            iv_sufficient = iv_rank is not None and iv_rank > 30
            if iv_sufficient:
                covered_call = _build_covered_call_spec(ticker, contracts, current_price, atr, iv_rank)
                regime_label = "R1 low-vol mean-reverting" if regime_id == 1 else "R2 high-vol mean-reverting"
                wheel_rationale = (
                    f"{regime_label} + individual stock + IV rank {iv_rank:.0f} > 30 — "
                    f"elevated IV justifies covered call yield; "
                    f"target strike: {covered_call.legs[0].strike:.0f}"
                )
                regime_rationale = f"R{regime_id} ({regime_confidence:.0%} confidence): mean-reverting. Individual stock with elevated IV → wheel viable."
                reasons = [
                    f"{regime_label} — mean reversion favors holding",
                    f"IV rank {iv_rank:.0f} > 30 — sufficient premium to justify covered call",
                    f"Position is {capital_pct:.0%} of NLV — within limits",
                ]
                return AssignmentAnalysis(
                    ticker=ticker,
                    assignment_type=assignment_type,
                    shares=shares,
                    assignment_price=strike_price,
                    current_price=current_price,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                    capital_tied_up=capital_tied_up,
                    capital_pct_of_nlv=capital_pct,
                    margin_impact=margin_impact,
                    recommended_action=AssignmentAction.HOLD_AND_WHEEL,
                    urgency="this_week",
                    reasons=reasons,
                    response_trade_spec=None,
                    wheel_trade_spec=covered_call,
                    wheel_rationale=wheel_rationale,
                    regime_id=regime_id,
                    regime_rationale=regime_rationale,
                )
            else:
                iv_note = f"IV rank {iv_rank:.0f} ≤ 30" if iv_rank is not None else "IV rank unavailable"
                reason = (
                    f"R{regime_id} mean-reverting but individual stock with low IV ({iv_note}) — "
                    f"covered call yield insufficient to justify holding; sell to redeploy capital"
                )
                sell_spec = _build_equity_sell_spec(ticker, shares, current_price, reason)
                regime_rationale = f"R{regime_id} ({regime_confidence:.0%} confidence): individual stock, low IV — selling is more efficient."
                return AssignmentAnalysis(
                    ticker=ticker,
                    assignment_type=assignment_type,
                    shares=shares,
                    assignment_price=strike_price,
                    current_price=current_price,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                    capital_tied_up=capital_tied_up,
                    capital_pct_of_nlv=capital_pct,
                    margin_impact=margin_impact,
                    recommended_action=AssignmentAction.SELL_IMMEDIATELY,
                    urgency="today",
                    reasons=[reason],
                    response_trade_spec=sell_spec,
                    wheel_trade_spec=None,
                    wheel_rationale=None,
                    regime_id=regime_id,
                    regime_rationale=regime_rationale,
                )

    # RULE 7: Default — small accounts should not hold equity from assignment
    reason = (
        f"Default: sell assigned shares to preserve capital — "
        f"no strong case for holding in current conditions (R{regime_id}, {capital_pct:.0%} of NLV)"
    )
    sell_spec = _build_equity_sell_spec(ticker, shares, current_price, reason)
    regime_rationale = f"R{regime_id} ({regime_confidence:.0%} confidence) — default rule: sell assigned shares."
    return AssignmentAnalysis(
        ticker=ticker,
        assignment_type=assignment_type,
        shares=shares,
        assignment_price=strike_price,
        current_price=current_price,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        capital_tied_up=capital_tied_up,
        capital_pct_of_nlv=capital_pct,
        margin_impact=margin_impact,
        recommended_action=AssignmentAction.SELL_IMMEDIATELY,
        urgency="today",
        reasons=[reason],
        response_trade_spec=sell_spec,
        wheel_trade_spec=None,
        wheel_rationale=None,
        regime_id=regime_id,
        regime_rationale=regime_rationale,
    )


# ---------------------------------------------------------------------------
# BEFORE-assignment risk warning
# ---------------------------------------------------------------------------

def _classify_leg_risk(
    option_type: str,
    strike: float,
    current_price: float,
    dte_remaining: int,
    exercise_style: str,
    is_dividend_pending: bool,
    ex_dividend_days: int | None,
) -> tuple[AssignmentRisk, float, float, list[str]]:
    """Classify assignment risk for a single short leg.

    Returns:
        (risk_level, itm_amount, itm_pct, reasons)
        itm_amount is positive when ITM, negative when OTM.
    """
    if option_type == "put":
        itm_amount = strike - current_price   # Positive = ITM
    else:  # call
        itm_amount = current_price - strike   # Positive = ITM

    reasons: list[str] = []

    if itm_amount <= 0:
        # OTM — no assignment risk
        return AssignmentRisk.NONE, itm_amount, 0.0, reasons

    itm_pct = itm_amount / current_price

    if exercise_style == "european":
        # European options can only be assigned at expiration (0 DTE = expiry day)
        if dte_remaining >= 1:
            reasons.append(
                f"European style — {dte_remaining} DTE remaining, no early assignment possible"
            )
            return AssignmentRisk.NONE, itm_amount, itm_pct, reasons
        elif itm_pct > 0.005:
            reasons.append(
                f"European style — expiry day, {itm_pct:.1%} ITM → assignment at expiry likely"
            )
            return AssignmentRisk.HIGH, itm_amount, itm_pct, reasons
        else:
            reasons.append(
                f"European style — expiry day but barely ITM ({itm_pct:.2%}), time value may protect"
            )
            return AssignmentRisk.LOW, itm_amount, itm_pct, reasons

    # American-style logic
    # Dividend early-assignment check for ITM calls
    if option_type == "call" and is_dividend_pending and itm_pct > 0:
        days_note = f"ex-dividend in {ex_dividend_days}d" if ex_dividend_days is not None else "ex-dividend pending"
        reasons.append(
            f"ITM call + {days_note} — early assignment risk: holder may exercise to capture dividend"
        )
        return AssignmentRisk.HIGH, itm_amount, itm_pct, reasons

    if dte_remaining <= 2 and itm_pct > 0.005:
        reasons.append(f"{dte_remaining} DTE, {itm_pct:.1%} ITM — expect assignment tonight or at expiry")
        return AssignmentRisk.IMMINENT, itm_amount, itm_pct, reasons
    elif dte_remaining <= 5 and itm_pct > 0.01:
        reasons.append(f"{dte_remaining} DTE with {itm_pct:.1%} ITM — high probability of early assignment")
        return AssignmentRisk.HIGH, itm_amount, itm_pct, reasons
    elif itm_pct > 0.03:
        reasons.append(f"Deep ITM ({itm_pct:.1%}) — time value eroded, assignment likely")
        return AssignmentRisk.HIGH, itm_amount, itm_pct, reasons
    elif itm_pct > 0.01:
        reasons.append(f"ITM by {itm_pct:.1%} with {dte_remaining} DTE — monitor closely")
        return AssignmentRisk.MODERATE, itm_amount, itm_pct, reasons
    else:
        reasons.append(f"Slightly ITM ({itm_pct:.2%}) — time value still present, low immediate risk")
        return AssignmentRisk.LOW, itm_amount, itm_pct, reasons


def _build_close_leg_spec(
    ticker: str,
    option_type: str,
    strike: float,
    dte_remaining: int,
    current_price: float,
) -> TradeSpec:
    """Build a BTO spec to close a short option leg."""
    exp = date.today() + timedelta(days=dte_remaining)
    return TradeSpec(
        ticker=ticker,
        legs=[LegSpec(
            role=f"close_short_{option_type}",
            action=LegAction.BUY_TO_CLOSE,
            quantity=1,
            option_type=option_type,
            strike=strike,
            strike_label=f"BTC {strike:.0f} {option_type.upper()}",
            expiration=exp,
            days_to_expiry=dte_remaining,
            atm_iv_at_expiry=0.0,
        )],
        underlying_price=current_price,
        target_dte=dte_remaining,
        target_expiration=exp,
        spec_rationale=(
            f"ASSIGNMENT RISK: Close short {option_type.upper()} {strike:.0f} "
            f"— {dte_remaining} DTE, ITM"
        ),
        structure_type=StructureType.CREDIT_SPREAD,
        order_side=OrderSide.DEBIT,
        entry_mode="limit",
    )


_RISK_RANK: dict[AssignmentRisk, int] = {
    AssignmentRisk.NONE: 0,
    AssignmentRisk.LOW: 1,
    AssignmentRisk.MODERATE: 2,
    AssignmentRisk.HIGH: 3,
    AssignmentRisk.IMMINENT: 4,
}


def assess_assignment_risk(
    trade_spec: TradeSpec,
    current_price: float,
    dte_remaining: int,
    exercise_style: str = "american",
    is_dividend_pending: bool = False,
    ex_dividend_days: int | None = None,
) -> AssignmentRiskResult:
    """Assess probability and urgency of assignment on short options BEFORE it happens.

    Scans all STO legs in the TradeSpec for assignment risk. Returns the
    aggregate risk level and a concrete action recommendation.

    American options (US): Can be assigned ANY time the option is ITM.
    European options (India): Can only be assigned at expiration.

    Key risk factors:
    - How deep ITM is the short strike?
    - How close to expiration?
    - Is there a dividend approaching? (early assignment risk for calls)
    - Exercise style (American vs European)?

    Args:
        trade_spec:          The open trade to assess.
        current_price:       Current market price of the underlying.
        dte_remaining:       Calendar days to expiration.
        exercise_style:      "american" (US equity options) or "european" (SPX, India NIFTY).
        is_dividend_pending: Whether an ex-dividend date is upcoming (call assignment risk).
        ex_dividend_days:    Days until ex-dividend date (if is_dividend_pending=True).

    Returns:
        AssignmentRiskResult with risk level, at-risk legs, and recommended action.
    """
    ticker = trade_spec.ticker
    at_risk_legs: list[dict] = []
    all_reasons: list[str] = []
    worst_risk = AssignmentRisk.NONE

    for leg in trade_spec.legs:
        # Only short (STO) option legs can be assigned
        if leg.action != LegAction.SELL_TO_OPEN:
            continue
        if leg.option_type not in ("put", "call"):
            continue

        leg_risk, itm_amount, itm_pct, leg_reasons = _classify_leg_risk(
            option_type=leg.option_type,
            strike=leg.strike,
            current_price=current_price,
            dte_remaining=dte_remaining,
            exercise_style=exercise_style,
            is_dividend_pending=is_dividend_pending,
            ex_dividend_days=ex_dividend_days,
        )

        leg_entry = {
            "role": leg.role,
            "option_type": leg.option_type,
            "strike": leg.strike,
            "itm_amount": round(itm_amount, 2),
            "itm_pct": round(itm_pct, 4),
            "risk_level": leg_risk,
        }
        at_risk_legs.append(leg_entry)
        all_reasons.extend(leg_reasons)

        if _RISK_RANK[leg_risk] > _RISK_RANK[worst_risk]:
            worst_risk = leg_risk

    # Build response trade spec if action needed (for first high/imminent leg)
    response_spec: TradeSpec | None = None
    highest_risk_leg: dict | None = None
    for entry in at_risk_legs:
        if _RISK_RANK[entry["risk_level"]] >= _RISK_RANK[AssignmentRisk.HIGH]:
            if highest_risk_leg is None or _RISK_RANK[entry["risk_level"]] > _RISK_RANK[highest_risk_leg["risk_level"]]:
                highest_risk_leg = entry

    if highest_risk_leg is not None:
        response_spec = _build_close_leg_spec(
            ticker=ticker,
            option_type=highest_risk_leg["option_type"],
            strike=highest_risk_leg["strike"],
            dte_remaining=dte_remaining,
            current_price=current_price,
        )

    # Determine urgency and recommended action
    if worst_risk == AssignmentRisk.IMMINENT:
        urgency = "act_now"
        recommended_action = "close_itm_leg"
    elif worst_risk == AssignmentRisk.HIGH:
        urgency = "prepare"
        recommended_action = "close_itm_leg" if dte_remaining <= 5 else "roll_before_expiry"
    elif worst_risk == AssignmentRisk.MODERATE:
        urgency = "monitor"
        recommended_action = "monitor"
    else:
        urgency = "none"
        recommended_action = "hold"

    # European note
    european_note: str | None = None
    if exercise_style == "european":
        european_note = (
            "European style — assignment only at expiry, not before. "
            "No early assignment risk regardless of ITM amount."
        )

    if not all_reasons:
        all_reasons.append("All short legs are OTM — no assignment risk")

    return AssignmentRiskResult(
        ticker=ticker,
        risk_level=worst_risk,
        at_risk_legs=at_risk_legs,
        exercise_style=exercise_style,
        urgency=urgency,
        reasons=all_reasons,
        recommended_action=recommended_action,
        response_trade_spec=response_spec,
        european_note=european_note,
    )
