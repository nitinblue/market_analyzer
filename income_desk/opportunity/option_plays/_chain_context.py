"""Build ChainContext from broker option chain."""
from __future__ import annotations
from income_desk.models.chain import AvailableStrike, ChainContext

MIN_OI = 50


def build_chain_context(
    ticker: str,
    chain: list,
    underlying_price: float,
) -> ChainContext | None:
    if not chain:
        return None

    expiration = chain[0].expiration
    lot_size = chain[0].lot_size or 1

    put_strikes = []
    call_strikes = []

    for q in chain:
        if not q.bid or q.bid <= 0 or not q.ask or q.ask <= 0:
            continue
        if q.open_interest is not None and q.open_interest < MIN_OI:
            continue

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
        expiration=expiration,
        lot_size=lot_size,
        underlying_price=underlying_price,
        put_strikes=put_strikes,
        call_strikes=call_strikes,
    )
