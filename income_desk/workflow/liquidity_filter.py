"""Liquidity Filter — validate and adjust trade strikes against live chain data.

Ensures every proposed strike actually exists in the broker's option chain
with sufficient OI, volume, and reasonable bid-ask spread. Snaps theoretical
strikes to the nearest liquid strike when needed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from income_desk.service.analyzer import MarketAnalyzer

logger = logging.getLogger(__name__)

# Minimum thresholds for a strike to be considered "liquid"
MIN_OI = 1_000          # minimum open interest
MIN_BID = 0.05          # minimum bid (not zero)
MAX_SPREAD_PCT = 0.20   # max bid-ask spread as % of mid (20%)


@dataclass
class LiquidStrike:
    """A strike that exists and is liquid in the broker chain."""
    strike: float
    option_type: str    # "call" or "put"
    bid: float
    ask: float
    mid: float
    spread_pct: float   # (ask-bid)/mid
    open_interest: int
    volume: int
    iv: float | None
    delta: float | None
    is_liquid: bool     # meets all thresholds


@dataclass
class LiquidityReport:
    """Result of checking a trade's strikes against the live chain."""
    ticker: str
    all_strikes_available: bool
    all_strikes_liquid: bool
    legs: list[LiquidStrike]      # one per proposed leg
    snapped_legs: list[LiquidStrike]  # adjusted to nearest liquid strike
    warnings: list[str]
    total_oi: int                 # sum of OI across all legs
    avg_spread_pct: float         # average bid-ask spread
    fill_quality: str             # "good", "fair", "poor", "unfillable"


def check_trade_liquidity(
    ticker: str,
    proposed_strikes: list[tuple[float, str]],  # [(strike, "put"/"call"), ...]
    ma: MarketAnalyzer,
    min_oi: int = MIN_OI,
) -> LiquidityReport:
    """Check if proposed trade strikes are liquid in the live chain.

    Args:
        ticker: Underlying ticker.
        proposed_strikes: List of (strike, option_type) tuples.
        ma: MarketAnalyzer with live broker data.
        min_oi: Minimum OI threshold.

    Returns:
        LiquidityReport with per-leg analysis and snapped alternatives.
    """
    warnings: list[str] = []
    legs: list[LiquidStrike] = []
    snapped: list[LiquidStrike] = []

    # Get live chain
    chain = []
    if ma.market_data is not None:
        try:
            chain = ma.market_data.get_option_chain(ticker)
        except Exception as e:
            warnings.append(f"Chain fetch failed: {e}")

    if not chain:
        return LiquidityReport(
            ticker=ticker, all_strikes_available=False, all_strikes_liquid=False,
            legs=[], snapped_legs=[], warnings=["No option chain available"],
            total_oi=0, avg_spread_pct=0, fill_quality="unfillable",
        )

    # Index chain by (strike, option_type) for fast lookup
    chain_map: dict[tuple[float, str], object] = {}
    for q in chain:
        chain_map[(q.strike, q.option_type)] = q

    # Also build list of liquid strikes per option type for snapping
    liquid_puts = sorted(
        [q for q in chain if q.option_type == "put" and (q.open_interest or 0) >= min_oi and (q.bid or 0) > MIN_BID],
        key=lambda q: q.strike,
    )
    liquid_calls = sorted(
        [q for q in chain if q.option_type == "call" and (q.open_interest or 0) >= min_oi and (q.bid or 0) > MIN_BID],
        key=lambda q: q.strike,
    )

    all_available = True
    all_liquid = True

    for strike, opt_type in proposed_strikes:
        q = chain_map.get((strike, opt_type))

        if q is None:
            # Strike doesn't exist in chain
            all_available = False
            all_liquid = False
            legs.append(LiquidStrike(
                strike=strike, option_type=opt_type,
                bid=0, ask=0, mid=0, spread_pct=0,
                open_interest=0, volume=0, iv=None, delta=None,
                is_liquid=False,
            ))
            warnings.append(f"{ticker} {strike} {opt_type}: strike not in chain")
        else:
            bid = q.bid or 0
            ask = q.ask or 0
            mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
            spread_pct = (ask - bid) / mid if mid > 0 else 0
            oi = q.open_interest or 0
            vol = q.volume or 0
            is_liq = oi >= min_oi and bid > MIN_BID and spread_pct < MAX_SPREAD_PCT

            if not is_liq:
                all_liquid = False
                reasons = []
                if oi < min_oi:
                    reasons.append(f"OI={oi:,d}<{min_oi:,d}")
                if bid <= MIN_BID:
                    reasons.append(f"bid={bid:.2f}")
                if spread_pct >= MAX_SPREAD_PCT:
                    reasons.append(f"spread={spread_pct:.0%}")
                warnings.append(f"{ticker} {strike} {opt_type}: illiquid ({', '.join(reasons)})")

            legs.append(LiquidStrike(
                strike=strike, option_type=opt_type,
                bid=bid, ask=ask, mid=mid, spread_pct=spread_pct,
                open_interest=oi, volume=vol,
                iv=getattr(q, "implied_volatility", None),
                delta=getattr(q, "delta", None),
                is_liquid=is_liq,
            ))

        # Snap to nearest liquid strike
        liquid_list = liquid_puts if opt_type == "put" else liquid_calls
        if liquid_list:
            nearest = min(liquid_list, key=lambda lq: abs(lq.strike - strike))
            nq = nearest
            nbid = nq.bid or 0
            nask = nq.ask or 0
            nmid = (nbid + nask) / 2 if (nbid + nask) > 0 else 0
            nspread = (nask - nbid) / nmid if nmid > 0 else 0

            snapped.append(LiquidStrike(
                strike=nq.strike, option_type=opt_type,
                bid=nbid, ask=nask, mid=nmid, spread_pct=nspread,
                open_interest=nq.open_interest or 0,
                volume=nq.volume or 0,
                iv=getattr(nq, "implied_volatility", None),
                delta=getattr(nq, "delta", None),
                is_liquid=True,
            ))
            if nq.strike != strike:
                warnings.append(f"{ticker} {strike} {opt_type}: snapped to {nq.strike} (nearest liquid)")
        else:
            snapped.append(legs[-1])  # no liquid alternative

    # Aggregate metrics
    total_oi = sum(l.open_interest for l in legs)
    spreads = [l.spread_pct for l in legs if l.spread_pct > 0]
    avg_spread = sum(spreads) / len(spreads) if spreads else 0

    if not all_available:
        fill_quality = "unfillable"
    elif all_liquid and avg_spread < 0.05:
        fill_quality = "good"
    elif all_liquid:
        fill_quality = "fair"
    else:
        fill_quality = "poor"

    return LiquidityReport(
        ticker=ticker,
        all_strikes_available=all_available,
        all_strikes_liquid=all_liquid,
        legs=legs,
        snapped_legs=snapped,
        warnings=warnings,
        total_oi=total_oi,
        avg_spread_pct=avg_spread,
        fill_quality=fill_quality,
    )


def get_liquid_ic_strikes(
    ticker: str,
    underlying_price: float,
    ma: MarketAnalyzer,
    wing_width_target: float = 0.0,
    short_distance_pct: float = 0.03,
    min_oi: int = MIN_OI,
) -> dict | None:
    """Find the best liquid iron condor strikes from the live chain.

    Instead of computing theoretical strikes and hoping they exist,
    this scans the actual chain for liquid OTM puts and calls.

    Args:
        ticker: Underlying.
        underlying_price: Current price.
        ma: MarketAnalyzer with broker.
        wing_width_target: Desired wing width in points (0 = auto from chain).
        short_distance_pct: How far OTM to place short strikes (% of price).
        min_oi: Minimum OI for a strike to be considered.

    Returns:
        Dict with short_put, long_put, short_call, long_call strikes + metadata,
        or None if no liquid strikes found.
    """
    chain = []
    if ma.market_data is not None:
        try:
            chain = ma.market_data.get_option_chain(ticker)
        except Exception:
            return None

    if not chain:
        return None

    # Filter to liquid strikes
    liquid_puts = sorted(
        [q for q in chain if q.option_type == "put"
         and (q.open_interest or 0) >= min_oi
         and (q.bid or 0) > MIN_BID
         and q.strike < underlying_price],
        key=lambda q: q.strike, reverse=True,  # highest first (closest to ATM)
    )
    liquid_calls = sorted(
        [q for q in chain if q.option_type == "call"
         and (q.open_interest or 0) >= min_oi
         and (q.bid or 0) > MIN_BID
         and q.strike > underlying_price],
        key=lambda q: q.strike,  # lowest first (closest to ATM)
    )

    if len(liquid_puts) < 2 or len(liquid_calls) < 2:
        return None

    # Short strikes: first liquid OTM beyond short_distance_pct
    target_put = underlying_price * (1 - short_distance_pct)
    target_call = underlying_price * (1 + short_distance_pct)

    short_put_q = None
    for q in liquid_puts:
        if q.strike <= target_put:
            short_put_q = q
            break
    if short_put_q is None:
        short_put_q = liquid_puts[0]  # closest OTM liquid put

    short_call_q = None
    for q in liquid_calls:
        if q.strike >= target_call:
            short_call_q = q
            break
    if short_call_q is None:
        short_call_q = liquid_calls[0]  # closest OTM liquid call

    # Long strikes: next liquid strike beyond short strike
    long_put_q = None
    for q in liquid_puts:
        if q.strike < short_put_q.strike:
            long_put_q = q
            break

    long_call_q = None
    for q in liquid_calls:
        if q.strike > short_call_q.strike:
            long_call_q = q
            break

    if long_put_q is None or long_call_q is None:
        return None

    # Compute metrics
    put_wing = short_put_q.strike - long_put_q.strike
    call_wing = long_call_q.strike - short_call_q.strike
    short_put_mid = ((short_put_q.bid or 0) + (short_put_q.ask or 0)) / 2
    long_put_mid = ((long_put_q.bid or 0) + (long_put_q.ask or 0)) / 2
    short_call_mid = ((short_call_q.bid or 0) + (short_call_q.ask or 0)) / 2
    long_call_mid = ((long_call_q.bid or 0) + (long_call_q.ask or 0)) / 2

    net_credit = (short_put_mid - long_put_mid) + (short_call_mid - long_call_mid)

    return {
        "short_put": short_put_q.strike,
        "long_put": long_put_q.strike,
        "short_call": short_call_q.strike,
        "long_call": long_call_q.strike,
        "put_wing": put_wing,
        "call_wing": call_wing,
        "net_credit_est": round(net_credit, 2),
        "short_put_oi": short_put_q.open_interest or 0,
        "short_call_oi": short_call_q.open_interest or 0,
        "short_put_delta": short_put_q.delta,
        "short_call_delta": short_call_q.delta,
        "short_put_iv": short_put_q.implied_volatility,
        "short_call_iv": short_call_q.implied_volatility,
        "fill_quality": "good",
    }


def get_liquid_credit_spread_strikes(
    ticker: str,
    underlying_price: float,
    direction: str,
    ma: MarketAnalyzer,
    short_distance_pct: float = 0.03,
    min_oi: int = MIN_OI,
) -> dict | None:
    """Find liquid credit spread strikes from the live chain.

    Args:
        ticker: Underlying.
        underlying_price: Current price.
        direction: "bullish" (sell put spread) or "bearish" (sell call spread).
        ma: MarketAnalyzer with broker.
        short_distance_pct: How far OTM to place short strike.
        min_oi: Minimum OI.

    Returns:
        Dict with short_strike, long_strike, option_type, net_credit, OI, or None.
    """
    chain = []
    if ma.market_data is not None:
        try:
            chain = ma.market_data.get_option_chain(ticker)
        except Exception:
            return None

    if not chain:
        return None

    if direction == "bullish":
        # Bull put spread: sell OTM put, buy further OTM put
        opt_type = "put"
        liquid = sorted(
            [q for q in chain if q.option_type == "put"
             and (q.open_interest or 0) >= min_oi
             and (q.bid or 0) > MIN_BID
             and q.strike < underlying_price],
            key=lambda q: q.strike, reverse=True,
        )
        target = underlying_price * (1 - short_distance_pct)
    else:
        # Bear call spread: sell OTM call, buy further OTM call
        opt_type = "call"
        liquid = sorted(
            [q for q in chain if q.option_type == "call"
             and (q.open_interest or 0) >= min_oi
             and (q.bid or 0) > MIN_BID
             and q.strike > underlying_price],
            key=lambda q: q.strike,
        )
        target = underlying_price * (1 + short_distance_pct)

    if len(liquid) < 2:
        return None

    # Short strike: first liquid beyond target
    short_q = None
    if direction == "bullish":
        for q in liquid:
            if q.strike <= target:
                short_q = q
                break
    else:
        for q in liquid:
            if q.strike >= target:
                short_q = q
                break

    if short_q is None:
        short_q = liquid[0]

    # Long strike: next liquid beyond short
    long_q = None
    if direction == "bullish":
        for q in liquid:
            if q.strike < short_q.strike:
                long_q = q
                break
    else:
        for q in liquid:
            if q.strike > short_q.strike:
                long_q = q
                break

    if long_q is None:
        return None

    short_mid = ((short_q.bid or 0) + (short_q.ask or 0)) / 2
    long_mid = ((long_q.bid or 0) + (long_q.ask or 0)) / 2
    net_credit = short_mid - long_mid
    width = abs(short_q.strike - long_q.strike)

    return {
        "short_strike": short_q.strike,
        "long_strike": long_q.strike,
        "option_type": opt_type,
        "width": width,
        "net_credit_est": round(net_credit, 2),
        "short_oi": short_q.open_interest or 0,
        "long_oi": long_q.open_interest or 0,
        "short_delta": short_q.delta,
        "short_iv": short_q.implied_volatility,
        "fill_quality": "good",
    }
