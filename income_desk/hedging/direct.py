"""Tier 1 direct hedging — protective puts, collars, put spreads.

For instruments with liquid options (options_liquidity "high" or "medium").
All functions return HedgeResult with concrete TradeSpec legs.
Regime-aware: R1=cheap OTM, R2=collar (sell call to fund put), R3=context-dependent, R4=ATM.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from income_desk.hedging.models import CollarResult, HedgeResult, HedgeTier
from income_desk.models.opportunity import (
    LegAction,
    LegSpec,
    OrderSide,
    StructureType,
    TradeSpec,
)
from income_desk.registry import MarketRegistry


def _snap_strike(price: float, strike_interval: float, direction: str = "down") -> float:
    """Snap a price to the nearest valid strike."""
    if direction == "down":
        return math.floor(price / strike_interval) * strike_interval
    return math.ceil(price / strike_interval) * strike_interval


def _default_expiry(dte: int, market: str) -> date:
    """Compute a default expiry date."""
    return date.today() + timedelta(days=dte)


def _compute_lots(shares: int, lot_size: int) -> int:
    """How many option lots to cover the position."""
    if lot_size <= 0:
        return 1
    return max(1, shares // lot_size)


def _make_leg(
    action: LegAction,
    option_type: str,
    strike: float,
    expiration: date,
    dte: int,
    quantity: int = 1,
    atm_iv: float = 0.25,
) -> LegSpec:
    """Build a LegSpec with all required fields."""
    role = f"{'long' if action == LegAction.BUY_TO_OPEN else 'short'}_{option_type}"
    return LegSpec(
        role=role,
        action=action,
        option_type=option_type,
        strike=strike,
        strike_label=f"{strike:.0f} {option_type}",
        expiration=expiration,
        days_to_expiry=dte,
        atm_iv_at_expiry=atm_iv,
        quantity=quantity,
    )


def build_protective_put(
    ticker: str,
    shares: int,
    price: float,
    regime_id: int,
    atr: float,
    dte: int = 30,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> HedgeResult:
    """Build a protective put hedge with TradeSpec.

    Strike placement by regime:
        R1: 1.5 ATR OTM (cheap, insurance only)
        R2: 1.0 ATR OTM (moderate protection)
        R3: 0.75 ATR OTM (tighter if trend is against)
        R4: 0.25 ATR OTM (near ATM, maximum protection)

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        price: Current price per share.
        regime_id: Current regime (1-4).
        atr: Average True Range in price units.
        dte: Days to expiration for the put.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        HedgeResult with protective put TradeSpec.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(ticker, market)
        lot_size = inst.lot_size
        strike_interval = inst.strike_interval
    except KeyError:
        lot_size = 100 if market == "US" else 1
        strike_interval = 1.0

    # Regime-based strike distance
    atr_mult = {1: 1.5, 2: 1.0, 3: 0.75, 4: 0.25}.get(regime_id, 1.0)
    raw_strike = price - (atr * atr_mult)
    put_strike = _snap_strike(raw_strike, strike_interval, "down")

    lots = _compute_lots(shares, lot_size)
    expiry = _default_expiry(dte, market)

    # Rough cost estimate: regime-based as % of position value
    cost_pct = {1: 0.3, 2: 1.5, 3: 0.8, 4: 2.5}.get(regime_id, 1.0)
    position_value = shares * price
    cost_estimate = position_value * cost_pct / 100

    trade_spec = TradeSpec(
        ticker=ticker,
        underlying_price=price,
        target_dte=dte,
        target_expiration=expiry,
        spec_rationale=f"R{regime_id} protective put {atr_mult}x ATR OTM",
        structure_type=StructureType.LONG_OPTION,
        order_side=OrderSide.DEBIT,
        legs=[
            _make_leg(LegAction.BUY_TO_OPEN, "put", put_strike, expiry, dte, lots),
        ],
        max_profit_desc="Unlimited downside protection below strike",
        max_loss_desc=f"Premium paid (~{cost_estimate:,.0f})",
    )

    protection_pct = (price - put_strike) / price * 100
    commentary = [
        f"ATR={atr:.2f}, regime R{regime_id} → {atr_mult}x ATR offset",
        f"Put strike: {put_strike} ({protection_pct:.1f}% below current price)",
        f"Lots: {lots} (lot_size={lot_size}, covering {shares} shares)",
        f"Expiry: {expiry.isoformat()} ({dte} DTE)",
    ]

    regime_names = {1: "Low-Vol MR", 2: "High-Vol MR", 3: "Low-Vol Trending", 4: "High-Vol Trending"}

    return HedgeResult(
        ticker=ticker,
        market=market,
        tier=HedgeTier.DIRECT,
        hedge_type="protective_put",
        trade_spec=trade_spec,
        cost_estimate=cost_estimate,
        cost_pct=cost_pct,
        delta_reduction=0.85 if regime_id >= 3 else 0.60,
        protection_level=f"Put at {put_strike} ({protection_pct:.1f}% OTM)",
        max_loss_after_hedge=cost_estimate + (price - put_strike) * shares,
        rationale=f"R{regime_id} {regime_names.get(regime_id, '')} — protective put {atr_mult}x ATR OTM",
        regime_context=f"R{regime_id}: {'near ATM for max protection' if regime_id == 4 else 'OTM for cost efficiency'}",
        commentary=commentary,
    )


def build_collar(
    ticker: str,
    shares: int,
    price: float,
    cost_basis: float,
    regime_id: int,
    atr: float,
    dte: int = 30,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> CollarResult:
    """Build a collar (long put + short call) with TradeSpec.

    Best in R2 where high IV makes the short call expensive enough to
    offset or exceed the put cost (zero-cost or credit collar).

    Put placement: 1 ATR below current price.
    Call placement: 1 ATR above current price (or above cost basis).

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        price: Current price per share.
        cost_basis: Average cost basis per share (call strike must be above).
        regime_id: Current regime (1-4).
        atr: Average True Range in price units.
        dte: Days to expiration.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        CollarResult with put and call details.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(ticker, market)
        lot_size = inst.lot_size
        strike_interval = inst.strike_interval
    except KeyError:
        lot_size = 100 if market == "US" else 1
        strike_interval = 1.0

    # Put: 1 ATR below
    raw_put = price - atr
    put_strike = _snap_strike(raw_put, strike_interval, "down")

    # Call: 1 ATR above, but at least above cost basis
    raw_call = max(price + atr, cost_basis + strike_interval)
    call_strike = _snap_strike(raw_call, strike_interval, "up")

    lots = _compute_lots(shares, lot_size)
    expiry = _default_expiry(dte, market)

    # In R2 (high IV), call premium ~= put premium → near zero cost
    # In R1 (low IV), put is cheap but call is also cheap → small debit
    net_cost = {1: -0.3, 2: 0.0, 3: -0.5, 4: -1.5}.get(regime_id, -0.5)
    # Negative means debit (net cost), positive means credit

    trade_spec = TradeSpec(
        ticker=ticker,
        underlying_price=price,
        target_dte=dte,
        target_expiration=expiry,
        spec_rationale=f"R{regime_id} collar: put {put_strike} / call {call_strike}",
        structure_type=StructureType.CREDIT_SPREAD,  # Collar is economically a spread
        order_side=OrderSide.CREDIT if net_cost >= 0 else OrderSide.DEBIT,
        legs=[
            _make_leg(LegAction.BUY_TO_OPEN, "put", put_strike, expiry, dte, lots),
            _make_leg(LegAction.SELL_TO_OPEN, "call", call_strike, expiry, dte, lots),
        ],
        max_profit_desc=f"Capped at call strike {call_strike}",
        max_loss_desc=f"Capped at put strike {put_strike}",
    )

    downside_pct = (price - put_strike) / price * 100
    upside_pct = (call_strike - price) / price * 100

    return CollarResult(
        ticker=ticker,
        market=market,
        put_strike=put_strike,
        call_strike=call_strike,
        net_cost=net_cost,
        downside_protection_pct=round(downside_pct, 1),
        upside_cap_pct=round(upside_pct, 1),
        trade_spec=trade_spec,
        rationale=f"R{regime_id} collar: put at {put_strike}, call at {call_strike} — {'zero cost' if abs(net_cost) < 0.1 else f'net cost ~{abs(net_cost):.1f}%'}",
    )


def build_put_spread_hedge(
    ticker: str,
    shares: int,
    price: float,
    budget_pct: float,
    dte: int = 30,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> HedgeResult:
    """Build a put spread hedge (buy put, sell lower put) to reduce cost.

    Capped protection: protects between long put and short put strikes.
    Cheaper than naked put but limited protection range.

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        price: Current price per share.
        budget_pct: Max hedge cost as % of position value.
        dte: Days to expiration.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        HedgeResult with put spread TradeSpec.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(ticker, market)
        lot_size = inst.lot_size
        strike_interval = inst.strike_interval
    except KeyError:
        lot_size = 100 if market == "US" else 1
        strike_interval = 1.0

    # Long put: 3% below current price
    long_put_strike = _snap_strike(price * 0.97, strike_interval, "down")
    # Short put: 8% below current price
    short_put_strike = _snap_strike(price * 0.92, strike_interval, "down")

    lots = _compute_lots(shares, lot_size)
    expiry = _default_expiry(dte, market)

    position_value = shares * price
    cost_estimate = position_value * budget_pct / 100
    spread_width = long_put_strike - short_put_strike

    trade_spec = TradeSpec(
        ticker=ticker,
        underlying_price=price,
        target_dte=dte,
        target_expiration=expiry,
        spec_rationale=f"Put spread: {long_put_strike}/{short_put_strike}, budget {budget_pct}%",
        structure_type=StructureType.DEBIT_SPREAD,
        order_side=OrderSide.DEBIT,
        legs=[
            _make_leg(LegAction.BUY_TO_OPEN, "put", long_put_strike, expiry, dte, lots),
            _make_leg(LegAction.SELL_TO_OPEN, "put", short_put_strike, expiry, dte, lots),
        ],
        max_profit_desc=f"Max protection: {spread_width} points per lot",
        max_loss_desc=f"Premium paid (~{cost_estimate:,.0f})",
    )

    return HedgeResult(
        ticker=ticker,
        market=market,
        tier=HedgeTier.DIRECT,
        hedge_type="put_spread",
        trade_spec=trade_spec,
        cost_estimate=cost_estimate,
        cost_pct=budget_pct,
        delta_reduction=0.40,
        protection_level=f"Protection between {long_put_strike} and {short_put_strike}",
        max_loss_after_hedge=None,  # Below short put strike, protection ends
        rationale=f"Put spread: cost-efficient hedge within {budget_pct}% budget",
        regime_context="Budget-constrained hedge — partial protection",
        commentary=[
            f"Long put at {long_put_strike} (3% OTM), short put at {short_put_strike} (8% OTM)",
            f"Spread width: {spread_width} points, {lots} lots",
        ],
    )
