"""Tier 2 futures hedging — short futures, synthetic puts, synthetic collars.

For instruments where options are illiquid but stock futures exist (common in India).
Connects to futures_analysis.py for basis cost and roll decisions.

Synthetic put  = short futures + long call (payoff identical to long put)
Synthetic collar = short futures + long call + short put equivalent

All functions return HedgeResult or SyntheticOptionResult with TradeSpec.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from income_desk.futures_analysis import FuturesBasisAnalysis, analyze_futures_basis
from income_desk.hedging.models import (
    HedgeResult,
    HedgeTier,
    SyntheticOptionResult,
)
from income_desk.models.opportunity import (
    LegAction,
    LegSpec,
    OrderSide,
    StructureType,
    TradeSpec,
)
from income_desk.registry import MarketRegistry


def compute_hedge_ratio(
    shares: int,
    lot_size: int,
    target_delta: float = 1.0,
) -> int:
    """Compute number of futures lots needed to hedge a position.

    Args:
        shares: Number of shares to hedge.
        lot_size: Futures lot size.
        target_delta: Target hedge ratio (1.0 = full hedge, 0.5 = half hedge).

    Returns:
        Number of lots (minimum 1 if shares > 0).
    """
    if lot_size <= 0 or shares <= 0:
        return 0
    raw = (shares * target_delta) / lot_size
    return max(1, round(raw))


def _make_futures_leg(
    futures_price: float,
    expiry: date,
    dte: int,
    lots: int,
) -> LegSpec:
    """Build a short futures LegSpec."""
    return LegSpec(
        role="short_future",
        action=LegAction.SELL_TO_OPEN,
        option_type="future",
        strike=futures_price,
        strike_label=f"Futures at {futures_price:.0f}",
        expiration=expiry,
        days_to_expiry=dte,
        atm_iv_at_expiry=0.0,  # Futures have no IV
        quantity=lots,
    )


def _make_call_leg(
    call_strike: float,
    expiry: date,
    dte: int,
    lots: int,
) -> LegSpec:
    """Build a long call LegSpec."""
    return LegSpec(
        role="long_call",
        action=LegAction.BUY_TO_OPEN,
        option_type="call",
        strike=call_strike,
        strike_label=f"ATM call at {call_strike:.0f}",
        expiration=expiry,
        days_to_expiry=dte,
        atm_iv_at_expiry=0.25,  # Default IV estimate
        quantity=lots,
    )


def build_futures_hedge(
    ticker: str,
    shares: int,
    price: float,
    futures_price: float | None = None,
    futures_dte: int = 30,
    hedge_ratio: float = 1.0,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> HedgeResult:
    """Build a short futures hedge for a long equity position.

    Uses futures_analysis.analyze_futures_basis() for cost assessment.

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        price: Current spot price per share.
        futures_price: Current futures price (if None, estimates from spot + typical basis).
        futures_dte: Days to futures expiry.
        hedge_ratio: 1.0 = full hedge, 0.5 = half hedge.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        HedgeResult with FUTURES_SHORT TradeSpec.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(ticker, market)
        lot_size = inst.lot_size
    except KeyError:
        lot_size = 100 if market == "US" else 1

    lots = compute_hedge_ratio(shares, lot_size, hedge_ratio)
    fut_price = futures_price or (price * 1.005)  # Default: 0.5% contango

    # Use futures_analysis for basis
    expiry_date = date.today() + timedelta(days=futures_dte)
    basis_analysis: FuturesBasisAnalysis = analyze_futures_basis(
        ticker=ticker,
        spot_price=price,
        futures_price=fut_price,
        futures_dte=futures_dte,
        futures_expiry=expiry_date,
    )

    # Cost = basis (premium you give up by shorting futures above spot)
    cost_estimate = basis_analysis.basis * lots * lot_size
    position_value = shares * price
    cost_pct = (abs(cost_estimate) / position_value * 100) if position_value > 0 else 0

    trade_spec = TradeSpec(
        ticker=ticker,
        underlying_price=price,
        target_dte=futures_dte,
        target_expiration=expiry_date,
        spec_rationale=f"Short futures hedge: {lots} lot(s) at {fut_price:.0f}",
        structure_type=StructureType.FUTURES_SHORT,
        order_side=OrderSide.CREDIT,  # Short futures receives margin, not premium
        legs=[
            _make_futures_leg(fut_price, expiry_date, futures_dte, lots),
        ],
        max_profit_desc=f"Offset equity loss below {fut_price:.0f}",
        max_loss_desc="Unlimited (if underlying rallies and equity is closed)",
    )

    actual_hedge_pct = (lots * lot_size) / shares * 100 if shares > 0 else 0

    return HedgeResult(
        ticker=ticker,
        market=market,
        tier=HedgeTier.FUTURES_SYNTHETIC,
        hedge_type="futures_short",
        trade_spec=trade_spec,
        cost_estimate=abs(cost_estimate),
        cost_pct=round(cost_pct, 2),
        delta_reduction=min(actual_hedge_pct / 100, 1.0),
        protection_level=f"Short {lots} lot(s) futures at {fut_price:.0f}",
        max_loss_after_hedge=None,  # Futures hedge is continuous, not capped
        rationale=f"Short {lots} futures lot(s) covering {actual_hedge_pct:.0f}% of {shares} shares",
        regime_context=f"Basis: {basis_analysis.basis_pct:.2f}% ({basis_analysis.structure})",
        commentary=[
            f"Futures price: {fut_price:.2f}, spot: {price:.2f}",
            f"Basis: {basis_analysis.basis:.2f} ({basis_analysis.basis_pct:.2f}%)",
            f"Annualized basis: {basis_analysis.annualized_basis_pct:.2f}%",
            f"Lots: {lots} x {lot_size} = {lots * lot_size} shares hedged",
        ],
    )


def build_synthetic_put(
    ticker: str,
    shares: int,
    price: float,
    futures_price: float,
    lot_size: int | None = None,
    dte: int = 30,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> SyntheticOptionResult:
    """Build a synthetic put = short futures + long call.

    Payoff: identical to owning a put.
    - If underlying drops → futures profit offsets equity loss
    - If underlying rises → call profit offsets futures loss
    - Net: loss is limited to basis + call premium (like a put premium)

    Used when options are illiquid but futures + ATM calls are available.

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        price: Current spot price.
        futures_price: Current futures price.
        lot_size: Override lot size (else from registry).
        dte: Days to expiration for the call option.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        SyntheticOptionResult with combined TradeSpec.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    strike_interval = 1.0
    if lot_size is None:
        try:
            inst = reg.get_instrument(ticker, market)
            lot_size = inst.lot_size
            strike_interval = inst.strike_interval
        except KeyError:
            lot_size = 100 if market == "US" else 1
    else:
        try:
            inst = reg.get_instrument(ticker, market)
            strike_interval = inst.strike_interval
        except KeyError:
            pass

    lots = compute_hedge_ratio(shares, lot_size, 1.0)
    expiry = date.today() + timedelta(days=dte)

    # Call strike = ATM (at current spot price, snapped to interval)
    call_strike = math.ceil(price / strike_interval) * strike_interval

    # Synthetic put = short futures + long call
    trade_spec = TradeSpec(
        ticker=ticker,
        underlying_price=price,
        target_dte=dte,
        target_expiration=expiry,
        spec_rationale=f"Synthetic put: short {lots} futures + long {lots} ATM calls at {call_strike:.0f}",
        structure_type=StructureType.FUTURES_SHORT,  # Primary structure is futures
        order_side=OrderSide.DEBIT,  # Net debit (call premium)
        legs=[
            _make_futures_leg(futures_price, expiry, dte, lots),
            _make_call_leg(call_strike, expiry, dte, lots),
        ],
        max_profit_desc="Equivalent to protective put — unlimited downside protection",
        max_loss_desc="Basis cost + call premium",
    )

    basis_cost = (futures_price - price) * lots * lot_size
    # Call premium estimate (rough): 2% of spot for ATM 30-day
    call_premium_est = price * 0.02 * lots * lot_size
    net_cost = basis_cost + call_premium_est

    return SyntheticOptionResult(
        ticker=ticker,
        market=market,
        synthetic_type="synthetic_put",
        futures_direction="short",
        futures_lots=lots,
        option_strike=call_strike,
        option_type="call",
        option_lots=lots,
        net_cost_estimate=net_cost,
        trade_spec=trade_spec,
        rationale=(
            f"Synthetic put: short {lots} futures + long {lots} ATM calls at {call_strike}. "
            f"Options illiquid — using futures + call for put-equivalent payoff."
        ),
    )


def build_synthetic_collar(
    ticker: str,
    shares: int,
    price: float,
    futures_price: float,
    call_strike: float,
    dte: int = 30,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> SyntheticOptionResult:
    """Build a synthetic collar = short futures + long OTM call.

    Like a collar but using futures for the downside protection
    and buying an OTM call to cap the upside loss on futures.

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        price: Current spot price.
        futures_price: Current futures price.
        call_strike: Strike for the protective call (OTM).
        dte: Days to expiration.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        SyntheticOptionResult with combined TradeSpec.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(ticker, market)
        lot_size = inst.lot_size
    except KeyError:
        lot_size = 100 if market == "US" else 1

    lots = compute_hedge_ratio(shares, lot_size, 1.0)
    expiry = date.today() + timedelta(days=dte)

    call_leg = LegSpec(
        role="long_call",
        action=LegAction.BUY_TO_OPEN,
        option_type="call",
        strike=call_strike,
        strike_label=f"OTM call at {call_strike:.0f}",
        expiration=expiry,
        days_to_expiry=dte,
        atm_iv_at_expiry=0.25,
        quantity=lots,
    )

    trade_spec = TradeSpec(
        ticker=ticker,
        underlying_price=price,
        target_dte=dte,
        target_expiration=expiry,
        spec_rationale=f"Synthetic collar: short {lots} futures at {futures_price:.0f} + long {lots} calls at {call_strike:.0f}",
        structure_type=StructureType.FUTURES_SHORT,
        order_side=OrderSide.DEBIT,
        legs=[
            _make_futures_leg(futures_price, expiry, dte, lots),
            call_leg,
        ],
        max_profit_desc=f"Downside protection via futures, capped at call strike {call_strike}",
        max_loss_desc=f"Futures loss capped at {call_strike - futures_price:.0f} per lot if rallies above call",
    )

    return SyntheticOptionResult(
        ticker=ticker,
        market=market,
        synthetic_type="synthetic_collar",
        futures_direction="short",
        futures_lots=lots,
        option_strike=call_strike,
        option_type="call",
        option_lots=lots,
        net_cost_estimate=None,  # Depends on call premium (broker quote needed)
        trade_spec=trade_spec,
        rationale=(
            f"Synthetic collar: short {lots} futures at {futures_price:.0f} + "
            f"long {lots} calls at {call_strike:.0f}. "
            f"Protects downside, caps futures loss if underlying rallies."
        ),
    )
