"""Build ChainContext from broker option chain.

Filters to a single expiration and selects liquid strikes around ATM.
Each ChainContext represents one tradeable expiry — assessors pick
the expiry that matches their DTE target.
"""
from __future__ import annotations

from datetime import date

from income_desk.models.chain import AvailableStrike, ChainContext

MIN_OI = 50


def build_chain_context(
    ticker: str,
    chain: list,
    underlying_price: float,
    target_expiry: date | None = None,
    target_dte: int | None = None,
) -> ChainContext | None:
    """Build a ChainContext for a single expiry from broker chain data.

    Strike selection: only includes strikes with real bid/ask > 0.
    Expiry selection (in priority order):
        1. ``target_expiry`` — exact date if provided
        2. ``target_dte`` — nearest expiry to that DTE
        3. Default: nearest expiry with at least 5 quoted strikes

    Args:
        ticker: Underlying symbol.
        chain: list[OptionQuote] from broker.
        underlying_price: Current underlying price (center point).
        target_expiry: Exact expiry date to use.
        target_dte: Target DTE (picks nearest available expiry).
    """
    if not chain:
        return None

    # Collect all available expiries that have quoted strikes
    today = date.today()
    expiry_strikes: dict[date, int] = {}
    for q in chain:
        if q.expiration and q.expiration >= today:
            if q.bid and q.bid > 0 and q.ask and q.ask > 0:
                expiry_strikes[q.expiration] = expiry_strikes.get(q.expiration, 0) + 1

    if not expiry_strikes:
        return None

    # Pick expiry
    if target_expiry and target_expiry in expiry_strikes:
        chosen_exp = target_expiry
    elif target_dte is not None:
        # Nearest expiry to target DTE
        target_date = date.fromordinal(today.toordinal() + target_dte)
        chosen_exp = min(expiry_strikes.keys(), key=lambda e: abs((e - target_date).days))
    else:
        # Default: nearest expiry with at least 5 quoted strikes (skip illiquid 0DTE)
        viable = {e: c for e, c in expiry_strikes.items() if c >= 5}
        if viable:
            chosen_exp = min(viable.keys())
        else:
            chosen_exp = min(expiry_strikes.keys())

    # Filter chain to chosen expiry only
    lot_size = 100  # Default for US
    put_strikes: list[AvailableStrike] = []
    call_strikes: list[AvailableStrike] = []

    for q in chain:
        if q.expiration != chosen_exp:
            continue
        if not q.bid or q.bid <= 0 or not q.ask or q.ask <= 0:
            continue
        # Only filter on OI if broker actually provides it (non-zero).
        # TastyTrade REST chain returns OI=0 for all strikes.
        if q.open_interest is not None and q.open_interest > 0 and q.open_interest < MIN_OI:
            continue

        if q.lot_size and q.lot_size > 0:
            lot_size = q.lot_size

        strike = AvailableStrike(
            strike=q.strike,
            option_type=q.option_type,
            bid=q.bid,
            ask=q.ask,
            mid=(q.bid + q.ask) / 2,
            iv=q.implied_volatility,
            delta=q.delta,
            open_interest=q.open_interest or 0,
            volume=q.volume or 0,
        )

        if q.option_type == "put":
            put_strikes.append(strike)
        else:
            call_strikes.append(strike)

    if not put_strikes and not call_strikes:
        return None

    put_strikes.sort(key=lambda s: s.strike)
    call_strikes.sort(key=lambda s: s.strike)

    return ChainContext(
        ticker=ticker,
        expiration=chosen_exp,
        lot_size=lot_size,
        underlying_price=underlying_price,
        put_strikes=put_strikes,
        call_strikes=call_strikes,
    )
