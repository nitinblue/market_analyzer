"""Shared helper functions for computing TradeSpec across all option play assessors.

Pure functions — no data fetching, no side effects.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from income_desk.models.opportunity import LegAction, LegSpec, OrderSide, StructureType, TradeSpec
from income_desk.models.vol_surface import SkewSlice, TermStructurePoint, VolatilitySurface


def _get_instrument_info(ticker: str):
    """Look up instrument info from MarketRegistry. Returns None if unknown."""
    try:
        from income_desk.registry import MarketRegistry
        return MarketRegistry().get_instrument(ticker)
    except (KeyError, ImportError):
        return None


def _get_strike_interval(ticker: str) -> float | None:
    """Return the registry strike_interval for ticker, or None if unknown."""
    inst = _get_instrument_info(ticker)
    if inst is not None and inst.strike_interval > 0:
        return inst.strike_interval
    return None


def _assignment_exit_note(ticker: str) -> str:
    """Generate market-aware assignment risk exit note for dual-expiry structures."""
    inst = _get_instrument_info(ticker)
    if inst is not None:
        if inst.exercise_style == "european" and inst.settlement == "cash":
            return "Front leg auto-settles at expiry (cash, European — no assignment risk)"
        elif inst.exercise_style == "european" and inst.settlement == "physical":
            return "Close before front leg expiry to manage physical delivery risk (European — no early assignment)"
    # American + physical (US default) or unknown ticker — conservative default
    return "Close before front leg expiry to avoid assignment risk"


def _populate_instrument_fields(ticker: str) -> dict:
    """Return settlement/exercise_style kwargs for TradeSpec construction."""
    inst = _get_instrument_info(ticker)
    if inst is not None:
        return {"settlement": inst.settlement, "exercise_style": inst.exercise_style}
    return {}


def _populate_market_fields(ticker: str) -> dict:
    """Return ALL market-specific kwargs for TradeSpec construction.

    Pulls currency, lot_size, timezone, settlement, exercise_style from
    MarketRegistry so that TradeSpec is never constructed with US defaults
    for India instruments (or any other non-US market).
    """
    try:
        from income_desk.registry import MarketRegistry
        reg = MarketRegistry()
        inst = reg.get_instrument(ticker)
        if inst is None:
            return {}
        market = reg.get_market(inst.market)
        result: dict = {
            "currency": market.currency if market else "USD",
            "lot_size": inst.lot_size or 100,
            "settlement": inst.settlement,
            "exercise_style": inst.exercise_style,
        }
        if market:
            result["entry_window_timezone"] = market.timezone
        return result
    except (KeyError, ImportError):
        return {}


def _market_timezone(ticker: str) -> str:
    """Return the market timezone for a ticker, defaulting to US/Eastern."""
    try:
        from income_desk.registry import MarketRegistry
        reg = MarketRegistry()
        inst = reg.get_instrument(ticker)
        if inst:
            market = reg.get_market(inst.market)
            if market:
                return market.timezone
    except (KeyError, ImportError):
        pass
    return "US/Eastern"


def _market_force_close_time(ticker: str) -> time:
    """Return the force-close time for a ticker's market."""
    try:
        from income_desk.registry import MarketRegistry
        reg = MarketRegistry()
        inst = reg.get_instrument(ticker)
        if inst:
            market = reg.get_market(inst.market)
            if market and market.force_close_time:
                return market.force_close_time
    except (KeyError, ImportError):
        pass
    return time(15, 45)  # US default


def _market_close_label(ticker: str) -> str:
    """Return a human-readable close time label like '3:15 PM IST' or '3:45 PM ET'."""
    try:
        from income_desk.registry import MarketRegistry
        reg = MarketRegistry()
        inst = reg.get_instrument(ticker)
        if inst:
            market = reg.get_market(inst.market)
            if market and market.force_close_time:
                ft = market.force_close_time
                tz_abbr = {
                    "Asia/Kolkata": "IST",
                    "US/Eastern": "ET",
                    "America/New_York": "ET",
                }.get(market.timezone, market.timezone)
                hour = ft.hour % 12 or 12
                am_pm = "AM" if ft.hour < 12 else "PM"
                minute_str = f":{ft.minute:02d}" if ft.minute else ""
                return f"{hour}{minute_str} {am_pm} {tz_abbr}"
    except (KeyError, ImportError):
        pass
    return "3:45 PM ET"


def _is_india_instrument(ticker: str) -> bool:
    """Return True if ticker belongs to INDIA market."""
    inst = _get_instrument_info(ticker)
    return inst is not None and inst.market == "INDIA"


def _entry_window_for_market(
    ticker: str,
    strategy: str = "income",
) -> tuple[time, time, str]:
    """Return (start, end, timezone) entry window for a ticker's market and strategy.

    Entry windows from CLAUDE.md:
    - 0DTE: 09:45-14:00 (US) / 09:30-14:00 (India)
    - Income: 10:00-15:00 (US) / 09:45-14:30 (India)
    - Default: 10:00-15:00 (US) / 09:30-15:00 (India)
    """
    tz = _market_timezone(ticker)

    if _is_india_instrument(ticker):
        if strategy == "zero_dte":
            return time(9, 30), time(14, 0), tz
        elif strategy == "income":
            return time(9, 45), time(14, 30), tz
        else:
            return time(9, 30), time(15, 0), tz
    else:
        # US defaults
        if strategy == "zero_dte":
            return time(9, 45), time(14, 0), tz
        elif strategy == "income":
            return time(10, 0), time(15, 0), tz
        else:
            return time(10, 0), time(15, 0), tz


def action_from_role(role: str) -> LegAction:
    """Derive BTO/STO from a leg role string.

    Roles starting with 'short' or 'sell' → STO, everything else → BTO.
    """
    lower = role.lower()
    if lower.startswith("short") or lower.startswith("sell"):
        return LegAction.SELL_TO_OPEN
    return LegAction.BUY_TO_OPEN


def snap_strike(
    raw_strike: float,
    underlying_price: float,
    strike_interval: float | None = None,
) -> float:
    """Snap a raw strike to the nearest valid option strike.

    If ``strike_interval`` is provided (e.g., from market registry), snap to
    that interval — needed for India instruments (NIFTY: 50 pts, BANKNIFTY: 100 pts).
    Otherwise, use standard US OCC tick sizes:
      <$50 -> $0.50 ticks, <$200 -> $1.00 ticks, >= $200 -> $5.00 ticks.
    """
    if strike_interval is not None and strike_interval > 0:
        return round(round(raw_strike / strike_interval) * strike_interval, 2)

    # US OCC default tick sizes
    if underlying_price < 50:
        tick = 0.50
    elif underlying_price < 200:
        tick = 1.00
    else:
        tick = 5.00
    return round(round(raw_strike / tick) * tick, 2)


def find_best_expiration(
    term_structure: list[TermStructurePoint],
    target_dte_min: int,
    target_dte_max: int,
) -> TermStructurePoint | None:
    """Find the expiration closest to target DTE range from vol surface term structure."""
    if not term_structure:
        return None

    # Prefer expirations within range
    in_range = [pt for pt in term_structure if target_dte_min <= pt.days_to_expiry <= target_dte_max]
    if in_range:
        mid = (target_dte_min + target_dte_max) / 2
        return min(in_range, key=lambda pt: abs(pt.days_to_expiry - mid))

    # Fallback: closest to the range
    mid = (target_dte_min + target_dte_max) / 2
    return min(term_structure, key=lambda pt: abs(pt.days_to_expiry - mid))


def compute_otm_strike(
    price: float,
    atr: float,
    multiplier: float,
    direction: str,
    underlying_price: float,
) -> float:
    """Compute OTM strike = price +/- (multiplier * ATR), snapped to tick.

    direction: "put" means below price, "call" means above price.
    """
    if direction == "put":
        raw = price - (multiplier * atr)
    else:
        raw = price + (multiplier * atr)
    return snap_strike(raw, underlying_price)


def compute_atm_strike(price: float) -> float:
    """Nearest ATM strike, snapped to tick."""
    return snap_strike(price, price)


def build_iron_condor_legs(
    price: float,
    atr: float,
    regime_id: int,
    expiration: date,
    dte: int,
    atm_iv: float,
    skew: SkewSlice | None = None,
) -> tuple[list[LegSpec], float]:
    """Build iron condor legs. Returns (legs, wing_width_points)."""
    # Short strike distance from price (in ATR multiples)
    short_mult = 1.0 if regime_id == 1 else 1.5
    # Wing width beyond short strike
    wing_mult = 0.5 if regime_id == 1 else 0.7

    wing_width = atr * wing_mult

    short_put = compute_otm_strike(price, atr, short_mult, "put", price)
    short_call = compute_otm_strike(price, atr, short_mult, "call", price)

    # Skew adjustment: shift short strikes toward richest IV premium
    if skew is not None:
        from income_desk.features.entry_levels import select_skew_optimal_strike
        put_optimal = select_skew_optimal_strike(price, atr, regime_id, skew, "put")
        if put_optimal.iv_advantage_pct >= 5.0:
            short_put = put_optimal.optimal_strike
        call_optimal = select_skew_optimal_strike(price, atr, regime_id, skew, "call")
        if call_optimal.iv_advantage_pct >= 5.0:
            short_call = call_optimal.optimal_strike
    long_put = snap_strike(short_put - wing_width, price)
    long_call = snap_strike(short_call + wing_width, price)

    # Degenerate spread guard: wing width < strike interval → both legs same strike
    if short_put == long_put or short_call == long_call:
        return [], 0.0

    wing_width_points = short_put - long_put

    legs = [
        LegSpec(
            role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put", strike=short_put,
            strike_label=f"{short_mult:.1f} ATR OTM put",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
        LegSpec(
            role="long_put", action=LegAction.BUY_TO_OPEN, option_type="put", strike=long_put,
            strike_label=f"wing {wing_mult:.1f} ATR below short put",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
        LegSpec(
            role="short_call", action=LegAction.SELL_TO_OPEN, option_type="call", strike=short_call,
            strike_label=f"{short_mult:.1f} ATR OTM call",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
        LegSpec(
            role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call", strike=long_call,
            strike_label=f"wing {wing_mult:.1f} ATR above short call",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
    ]
    return legs, wing_width_points


def build_inverse_iron_condor_legs(
    price: float,
    atr: float,
    regime_id: int,
    expiration: date,
    dte: int,
    atm_iv: float,
    orb_range_high: float | None = None,
    orb_range_low: float | None = None,
) -> tuple[list[LegSpec], float]:
    """Build inverse iron condor (Iron Man) legs. Returns (legs, wing_width_points).

    Net debit structure — profits from big moves in either direction.
    BTO closer-to-ATM strikes, STO further OTM strikes (wings).

    If ORB range is provided, inner (long) strikes are placed near ORB boundaries
    so that the trade profits when price breaks out of the opening range.
    """
    # Inner (long) strike distance — closer to ATM
    if orb_range_high is not None and orb_range_low is not None:
        # ORB-aware: place long strikes at ORB range edges
        long_put = snap_strike(orb_range_low, price)
        long_call = snap_strike(orb_range_high, price)
    else:
        # Default: 0.5 ATR from price (tighter than standard IC)
        inner_mult = 0.5 if regime_id in (1, 2) else 0.3
        long_put = compute_otm_strike(price, atr, inner_mult, "put", price)
        long_call = compute_otm_strike(price, atr, inner_mult, "call", price)

    # Outer (short) strikes — wings, further OTM
    wing_mult = 0.5 if regime_id in (1, 2) else 0.4
    wing_width = atr * wing_mult
    short_put = snap_strike(long_put - wing_width, price)
    short_call = snap_strike(long_call + wing_width, price)

    # Degenerate spread guard: wing width < strike interval → both legs same strike
    if long_put == short_put or long_call == short_call:
        return [], 0.0

    wing_width_points = long_put - short_put

    legs = [
        LegSpec(
            role="long_put", action=LegAction.BUY_TO_OPEN, option_type="put", strike=long_put,
            strike_label="inner put (near ORB low)" if orb_range_low else "inner put",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
        LegSpec(
            role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put", strike=short_put,
            strike_label="wing put (further OTM)",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
        LegSpec(
            role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call", strike=long_call,
            strike_label="inner call (near ORB high)" if orb_range_high else "inner call",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
        LegSpec(
            role="short_call", action=LegAction.SELL_TO_OPEN, option_type="call", strike=short_call,
            strike_label="wing call (further OTM)",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
    ]
    return legs, wing_width_points


def build_iron_butterfly_legs(
    price: float,
    atr: float,
    regime_id: int,
    expiration: date,
    dte: int,
    atm_iv: float,
) -> tuple[list[LegSpec], float]:
    """Build iron butterfly legs. Returns (legs, wing_width_points)."""
    atm = compute_atm_strike(price)
    wing_mult = 1.0 if regime_id == 2 else 1.2

    wing_width = atr * wing_mult
    long_put = snap_strike(atm - wing_width, price)
    long_call = snap_strike(atm + wing_width, price)

    # Degenerate spread guard: wings must differ from center strike
    if long_put == atm or long_call == atm:
        return [], 0.0

    wing_width_points = atm - long_put

    legs = [
        LegSpec(
            role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put", strike=atm,
            strike_label="ATM put (short straddle)",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
        LegSpec(
            role="short_call", action=LegAction.SELL_TO_OPEN, option_type="call", strike=atm,
            strike_label="ATM call (short straddle)",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
        LegSpec(
            role="long_put", action=LegAction.BUY_TO_OPEN, option_type="put", strike=long_put,
            strike_label=f"wing {wing_mult:.1f} ATR below ATM",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
        LegSpec(
            role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call", strike=long_call,
            strike_label=f"wing {wing_mult:.1f} ATR above ATM",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
    ]
    return legs, wing_width_points


def build_calendar_legs(
    price: float,
    front_exp: TermStructurePoint,
    back_exp: TermStructurePoint,
    strategy_type: str,
    atr: float | None = None,
) -> list[LegSpec]:
    """Build calendar spread legs (same strike, different expirations)."""
    # Determine strike based on strategy variant
    if strategy_type in ("otm_call_calendar", "otm_call"):
        if atr:
            strike = snap_strike(price + 0.5 * atr, price)
            label = "0.5 ATR OTM call"
        else:
            strike = snap_strike(price * 1.02, price)
            label = "~2% OTM call"
        opt_type = "call"
    elif strategy_type in ("otm_put_calendar", "otm_put"):
        if atr:
            strike = snap_strike(price - 0.5 * atr, price)
            label = "0.5 ATR OTM put"
        else:
            strike = snap_strike(price * 0.98, price)
            label = "~2% OTM put"
        opt_type = "put"
    else:
        # ATM calendar (default)
        strike = compute_atm_strike(price)
        label = "ATM"
        opt_type = "call"  # Convention: ATM calendars use calls

    legs = [
        LegSpec(
            role="short_front", action=LegAction.SELL_TO_OPEN, option_type=opt_type, strike=strike,
            strike_label=f"sell front {label}",
            expiration=front_exp.expiration, days_to_expiry=front_exp.days_to_expiry,
            atm_iv_at_expiry=front_exp.atm_iv,
        ),
        LegSpec(
            role="long_back", action=LegAction.BUY_TO_OPEN, option_type=opt_type, strike=strike,
            strike_label=f"buy back {label}",
            expiration=back_exp.expiration, days_to_expiry=back_exp.days_to_expiry,
            atm_iv_at_expiry=back_exp.atm_iv,
        ),
    ]
    return legs


def build_double_calendar_legs(
    price: float,
    front_exp: TermStructurePoint,
    back_exp: TermStructurePoint,
    atr: float | None = None,
) -> list[LegSpec]:
    """Build double calendar: put calendar below + call calendar above = 4 legs.

    Put calendar at put_strike (below price), call calendar at call_strike (above price).
    Each calendar: sell front, buy back at the same strike.
    """
    offset = 0.5 * atr if atr else price * 0.02
    call_strike = snap_strike(price + offset, price)
    put_strike = snap_strike(price - offset, price)

    return [
        # Put calendar (below price)
        LegSpec(
            role="short_front_put", action=LegAction.SELL_TO_OPEN, option_type="put", strike=put_strike,
            strike_label="sell front put (below)",
            expiration=front_exp.expiration, days_to_expiry=front_exp.days_to_expiry,
            atm_iv_at_expiry=front_exp.atm_iv,
        ),
        LegSpec(
            role="long_back_put", action=LegAction.BUY_TO_OPEN, option_type="put", strike=put_strike,
            strike_label="buy back put (below)",
            expiration=back_exp.expiration, days_to_expiry=back_exp.days_to_expiry,
            atm_iv_at_expiry=back_exp.atm_iv,
        ),
        # Call calendar (above price)
        LegSpec(
            role="short_front_call", action=LegAction.SELL_TO_OPEN, option_type="call", strike=call_strike,
            strike_label="sell front call (above)",
            expiration=front_exp.expiration, days_to_expiry=front_exp.days_to_expiry,
            atm_iv_at_expiry=front_exp.atm_iv,
        ),
        LegSpec(
            role="long_back_call", action=LegAction.BUY_TO_OPEN, option_type="call", strike=call_strike,
            strike_label="buy back call (above)",
            expiration=back_exp.expiration, days_to_expiry=back_exp.days_to_expiry,
            atm_iv_at_expiry=back_exp.atm_iv,
        ),
    ]


def build_diagonal_legs(
    price: float,
    front_exp: TermStructurePoint,
    back_exp: TermStructurePoint,
    trend_direction: str,
    strategy_type: str,
    atr: float | None = None,
) -> list[LegSpec]:
    """Build diagonal spread legs (different strike, different expiration)."""
    if strategy_type == "pmcc_diagonal" or (trend_direction == "bullish" and strategy_type != "bear_put_diagonal"):
        # Bull diagonal / PMCC: sell OTM front call, buy ATM/ITM back call
        if atr:
            front_strike = snap_strike(price + 0.5 * atr, price)
        else:
            front_strike = snap_strike(price * 1.02, price)
        back_strike = compute_atm_strike(price)

        if strategy_type == "pmcc_diagonal":
            # PMCC: buy deep ITM back call
            if atr:
                back_strike = snap_strike(price - 1.0 * atr, price)
            else:
                back_strike = snap_strike(price * 0.95, price)
            back_label = "deep ITM back call (PMCC)"
        else:
            back_label = "ATM back call"

        legs = [
            LegSpec(
                role="short_front", action=LegAction.SELL_TO_OPEN, option_type="call", strike=front_strike,
                strike_label="OTM front call",
                expiration=front_exp.expiration, days_to_expiry=front_exp.days_to_expiry,
                atm_iv_at_expiry=front_exp.atm_iv,
            ),
            LegSpec(
                role="long_back", action=LegAction.BUY_TO_OPEN, option_type="call", strike=back_strike,
                strike_label=back_label,
                expiration=back_exp.expiration, days_to_expiry=back_exp.days_to_expiry,
                atm_iv_at_expiry=back_exp.atm_iv,
            ),
        ]
    else:
        # Bear diagonal: sell OTM front put, buy ATM/ITM back put
        if atr:
            front_strike = snap_strike(price - 0.5 * atr, price)
        else:
            front_strike = snap_strike(price * 0.98, price)
        back_strike = compute_atm_strike(price)

        legs = [
            LegSpec(
                role="short_front", action=LegAction.SELL_TO_OPEN, option_type="put", strike=front_strike,
                strike_label="OTM front put",
                expiration=front_exp.expiration, days_to_expiry=front_exp.days_to_expiry,
                atm_iv_at_expiry=front_exp.atm_iv,
            ),
            LegSpec(
                role="long_back", action=LegAction.BUY_TO_OPEN, option_type="put", strike=back_strike,
                strike_label="ATM back put",
                expiration=back_exp.expiration, days_to_expiry=back_exp.days_to_expiry,
                atm_iv_at_expiry=back_exp.atm_iv,
            ),
        ]
    return legs


def build_ratio_spread_legs(
    price: float,
    atr: float,
    direction: str,
    expiration: date,
    dte: int,
    atm_iv: float,
) -> list[LegSpec]:
    """Build ratio spread legs (buy 1 ATM, sell 2 OTM)."""
    atm = compute_atm_strike(price)

    if direction == "bullish":
        otm_strike = compute_otm_strike(price, atr, 1.0, "call", price)
        # Degenerate spread guard: ATM and OTM at same strike
        if atm == otm_strike:
            return []
        legs = [
            LegSpec(
                role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call", strike=atm,
                strike_label="buy 1 ATM call",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
            LegSpec(
                role="short_call", action=LegAction.SELL_TO_OPEN,
                option_type="call", strike=otm_strike,
                strike_label="sell 1.0 ATR OTM call (1 of 2)",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
            LegSpec(
                role="short_call", action=LegAction.SELL_TO_OPEN,
                option_type="call", strike=otm_strike,
                strike_label="sell 1.0 ATR OTM call (2 of 2)",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
        ]
    else:
        otm_strike = compute_otm_strike(price, atr, 1.0, "put", price)
        # Degenerate spread guard: ATM and OTM at same strike
        if atm == otm_strike:
            return []
        legs = [
            LegSpec(
                role="long_put", action=LegAction.BUY_TO_OPEN, option_type="put", strike=atm,
                strike_label="buy 1 ATM put",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
            LegSpec(
                role="short_put", action=LegAction.SELL_TO_OPEN,
                option_type="put", strike=otm_strike,
                strike_label="sell 1.0 ATR OTM put (1 of 2)",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
            LegSpec(
                role="short_put", action=LegAction.SELL_TO_OPEN,
                option_type="put", strike=otm_strike,
                strike_label="sell 1.0 ATR OTM put (2 of 2)",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
        ]
    return legs


def build_single_expiry_trade_spec(
    ticker: str,
    price: float,
    atr: float,
    regime_id: int,
    vol_surface: VolatilitySurface,
    structure_type: str,
    target_dte_min: int = 30,
    target_dte_max: int = 45,
    direction: str | None = None,
) -> TradeSpec | None:
    """Build a TradeSpec for single-expiry structures (IC, IFly, ratio)."""
    exp_pt = find_best_expiration(vol_surface.term_structure, target_dte_min, target_dte_max)
    if exp_pt is None:
        return None

    mkt = _populate_market_fields(ticker)

    if structure_type == "iron_condor":
        legs, wing_width = build_iron_condor_legs(
            price, atr, regime_id, exp_pt.expiration, exp_pt.days_to_expiry, exp_pt.atm_iv,
        )
        if not legs:
            return None  # Degenerate — wing width < strike interval
        rationale = f"Target {target_dte_min}-{target_dte_max} DTE, matched {exp_pt.expiration} ({exp_pt.days_to_expiry}d). " \
                     f"Short strikes at {'1.0' if regime_id == 1 else '1.5'} ATR OTM, " \
                     f"wings {'0.5' if regime_id == 1 else '0.7'} ATR wide."
        return TradeSpec(
            ticker=ticker, legs=legs, underlying_price=price,
            target_dte=exp_pt.days_to_expiry, target_expiration=exp_pt.expiration,
            wing_width_points=wing_width,
            max_risk_per_spread=f"Wing {wing_width:.0f} pts - credit received",
            spec_rationale=rationale,
            structure_type=StructureType.IRON_CONDOR,
            order_side=OrderSide.CREDIT,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
            exit_dte=21,
            max_profit_desc="Credit received",
            max_loss_desc=f"Wing width ({wing_width:.0f} pts) minus credit",
            exit_notes=["Close at 50% of credit received",
                        "Close if short strike tested on either side",
                        "Close at 21 DTE to avoid gamma risk"],
            entry_window_start=time(10, 0),
            entry_window_end=time(15, 0),
            **mkt,
        )

    if structure_type == "iron_butterfly":
        legs, wing_width = build_iron_butterfly_legs(
            price, atr, regime_id, exp_pt.expiration, exp_pt.days_to_expiry, exp_pt.atm_iv,
        )
        if not legs:
            return None  # Degenerate — wing width < strike interval
        rationale = f"Target {target_dte_min}-{target_dte_max} DTE, matched {exp_pt.expiration} ({exp_pt.days_to_expiry}d). " \
                     f"Short straddle at ATM, wings {'1.0' if regime_id == 2 else '1.2'} ATR."
        return TradeSpec(
            ticker=ticker, legs=legs, underlying_price=price,
            target_dte=exp_pt.days_to_expiry, target_expiration=exp_pt.expiration,
            wing_width_points=wing_width,
            max_risk_per_spread=f"Wing {wing_width:.0f} pts - credit received",
            spec_rationale=rationale,
            structure_type=StructureType.IRON_BUTTERFLY,
            order_side=OrderSide.CREDIT,
            profit_target_pct=0.25,
            stop_loss_pct=2.0,
            exit_dte=14,
            max_profit_desc="Credit received (larger than IC due to ATM straddle)",
            max_loss_desc=f"Wing width ({wing_width:.0f} pts) minus credit",
            exit_notes=["Close at 25% of credit received",
                        "Close if underlying moves beyond ATM strike significantly",
                        "Close at 14 DTE to avoid pin risk"],
            entry_window_start=time(10, 0),
            entry_window_end=time(15, 0),
            **mkt,
        )

    if structure_type == "ratio_spread":
        dir_ = direction or "bullish"
        legs = build_ratio_spread_legs(
            price, atr, dir_, exp_pt.expiration, exp_pt.days_to_expiry, exp_pt.atm_iv,
        )
        if not legs:
            return None  # Degenerate — ATR too small for strike interval
        rationale = f"Target {target_dte_min}-{target_dte_max} DTE, matched {exp_pt.expiration} ({exp_pt.days_to_expiry}d). " \
                     f"Buy 1 ATM, sell 2 OTM at 1.0 ATR. {dir_.title()} direction."
        return TradeSpec(
            ticker=ticker, legs=legs, underlying_price=price,
            target_dte=exp_pt.days_to_expiry, target_expiration=exp_pt.expiration,
            spec_rationale=rationale,
            structure_type=StructureType.RATIO_SPREAD,
            order_side=OrderSide.CREDIT,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
            exit_dte=21,
            max_profit_desc="Net credit + OTM decay (max profit at short strike at expiry)",
            max_loss_desc="UNLIMITED beyond naked short strike",
            exit_notes=["NAKED LEG RISK: unlimited loss beyond short strikes",
                        "Close at 50% of credit or if short strike tested",
                        "Close at 21 DTE — gamma risk on naked leg"],
            entry_window_start=time(10, 0),
            entry_window_end=time(15, 0),
            **mkt,
        )

    return None


def build_dual_expiry_trade_spec(
    ticker: str,
    price: float,
    atr: float,
    vol_surface: VolatilitySurface,
    structure_type: str,
    strategy_type: str,
    front_dte_min: int = 20,
    front_dte_max: int = 30,
    back_dte_min: int = 50,
    back_dte_max: int = 70,
    trend_direction: str = "neutral",
) -> TradeSpec | None:
    """Build a TradeSpec for dual-expiry structures (calendar, diagonal)."""
    # Use best_calendar_expiries from vol surface if available
    front_pt = find_best_expiration(vol_surface.term_structure, front_dte_min, front_dte_max)
    back_pt = find_best_expiration(vol_surface.term_structure, back_dte_min, back_dte_max)

    if front_pt is None or back_pt is None:
        # Try with broader ranges
        if len(vol_surface.term_structure) >= 2:
            sorted_ts = sorted(vol_surface.term_structure, key=lambda p: p.days_to_expiry)
            front_pt = sorted_ts[0]
            back_pt = sorted_ts[-1]
        else:
            return None

    # Ensure front < back
    if front_pt.days_to_expiry >= back_pt.days_to_expiry:
        return None

    iv_diff = (front_pt.atm_iv - back_pt.atm_iv) / back_pt.atm_iv * 100 if back_pt.atm_iv > 0 else 0.0

    # Market-aware assignment note for dual-expiry structures
    _assign_note = _assignment_exit_note(ticker)
    mkt = _populate_market_fields(ticker)

    if structure_type == "calendar" and strategy_type == "double_calendar":
        legs = build_double_calendar_legs(price, front_pt, back_pt, atr)
        rationale = (
            f"Double calendar: put cal + call cal bracketing price. "
            f"Front {front_pt.expiration} ({front_pt.days_to_expiry}d, IV {front_pt.atm_iv:.1%}) / "
            f"Back {back_pt.expiration} ({back_pt.days_to_expiry}d, IV {back_pt.atm_iv:.1%}). "
            f"IV diff: {iv_diff:+.1f}%."
        )
        st = StructureType.DOUBLE_CALENDAR
        exit_dte = max(front_pt.days_to_expiry - 7, 0)
        exit_notes = [_assign_note,
                      "Roll front legs on 25% profit",
                      "Close if underlying moves beyond either strike"]
    elif structure_type == "calendar":
        legs = build_calendar_legs(price, front_pt, back_pt, strategy_type, atr)
        rationale = (
            f"Front {front_pt.expiration} ({front_pt.days_to_expiry}d, IV {front_pt.atm_iv:.1%}) / "
            f"Back {back_pt.expiration} ({back_pt.days_to_expiry}d, IV {back_pt.atm_iv:.1%}). "
            f"IV diff: {iv_diff:+.1f}%."
        )
        st = StructureType.CALENDAR
        exit_dte = max(front_pt.days_to_expiry - 7, 0)
        exit_notes = [_assign_note,
                      "Roll front leg on 25% profit",
                      "Close if underlying moves >1 ATR from strike"]
    elif structure_type == "diagonal":
        legs = build_diagonal_legs(
            price, front_pt, back_pt, trend_direction, strategy_type, atr,
        )
        rationale = (
            f"Front {front_pt.expiration} ({front_pt.days_to_expiry}d) sell OTM / "
            f"Back {back_pt.expiration} ({back_pt.days_to_expiry}d) buy ATM. "
            f"{trend_direction.title()} diagonal. IV diff: {iv_diff:+.1f}%."
        )
        st = StructureType.DIAGONAL
        exit_dte = max(front_pt.days_to_expiry - 7, 0)
        exit_notes = ["Roll front leg on profit for recurring income",
                      "Close if underlying moves against back leg significantly",
                      "Monitor back leg delta — adjust if trend reverses"]
    else:
        return None

    return TradeSpec(
        ticker=ticker,
        legs=legs,
        underlying_price=price,
        target_dte=front_pt.days_to_expiry,
        target_expiration=front_pt.expiration,
        front_expiration=front_pt.expiration,
        front_dte=front_pt.days_to_expiry,
        back_expiration=back_pt.expiration,
        back_dte=back_pt.days_to_expiry,
        iv_at_front=front_pt.atm_iv,
        iv_at_back=back_pt.atm_iv,
        iv_differential_pct=iv_diff,
        spec_rationale=rationale,
        structure_type=st,
        order_side=OrderSide.DEBIT,
        profit_target_pct=0.25,
        stop_loss_pct=0.50,
        exit_dte=exit_dte,
        max_profit_desc="Front leg decay minus back leg decay",
        max_loss_desc="Net debit paid",
        exit_notes=exit_notes,
        entry_window_start=time(10, 0),
        entry_window_end=time(15, 0),
        **mkt,
    )


# --- Simple structure builders (for 0DTE, LEAP, earnings, setups) ---


def build_long_option_legs(
    price: float,
    option_type: str,
    expiration: date,
    dte: int,
    atm_iv: float,
    otm_multiplier: float | None = None,
    atr: float | None = None,
) -> list[LegSpec]:
    """Build a single long option leg.

    If otm_multiplier and atr are provided, strike is OTM. Otherwise ATM.
    """
    if otm_multiplier is not None and atr is not None:
        strike = compute_otm_strike(price, atr, otm_multiplier, option_type, price)
        label = f"{otm_multiplier:.1f} ATR OTM {option_type}"
    else:
        strike = compute_atm_strike(price)
        label = f"ATM {option_type}"

    return [
        LegSpec(
            role=f"long_{option_type}", action=LegAction.BUY_TO_OPEN,
            option_type=option_type, strike=strike, strike_label=label,
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
    ]


def build_debit_spread_legs(
    price: float,
    atr: float,
    direction: str,
    expiration: date,
    dte: int,
    atm_iv: float,
    width_multiplier: float = 0.5,
) -> list[LegSpec]:
    """Build a debit spread (bullish call spread or bearish put spread).

    Long leg near ATM, short leg OTM by width_multiplier * ATR.
    """
    if direction == "bullish":
        long_strike = compute_atm_strike(price)
        short_strike = compute_otm_strike(price, atr, width_multiplier, "call", price)
        # Degenerate spread guard: both legs at same strike
        if long_strike == short_strike:
            return []
        return [
            LegSpec(
                role="long_call", action=LegAction.BUY_TO_OPEN,
                option_type="call", strike=long_strike, strike_label="ATM call",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
            LegSpec(
                role="short_call", action=LegAction.SELL_TO_OPEN,
                option_type="call", strike=short_strike,
                strike_label=f"{width_multiplier:.1f} ATR OTM call",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
        ]
    else:
        long_strike = compute_atm_strike(price)
        short_strike = compute_otm_strike(price, atr, width_multiplier, "put", price)
        # Degenerate spread guard: both legs at same strike
        if long_strike == short_strike:
            return []
        return [
            LegSpec(
                role="long_put", action=LegAction.BUY_TO_OPEN,
                option_type="put", strike=long_strike, strike_label="ATM put",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
            LegSpec(
                role="short_put", action=LegAction.SELL_TO_OPEN,
                option_type="put", strike=short_strike,
                strike_label=f"{width_multiplier:.1f} ATR OTM put",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
        ]


def build_credit_spread_legs(
    price: float,
    atr: float,
    direction: str,
    expiration: date,
    dte: int,
    atm_iv: float,
    short_multiplier: float = 1.0,
    wing_multiplier: float = 0.5,
) -> tuple[list[LegSpec], float]:
    """Build a credit spread. Returns (legs, wing_width_points).

    direction='bullish' -> bull put credit spread (sell put, buy lower put).
    direction='bearish' -> bear call credit spread (sell call, buy higher call).
    """
    if direction == "bullish":
        short_strike = compute_otm_strike(price, atr, short_multiplier, "put", price)
        wing_width = atr * wing_multiplier
        long_strike = snap_strike(short_strike - wing_width, price)
        # Degenerate spread guard: wing width < strike interval
        if short_strike == long_strike:
            return [], 0.0
        wing_pts = short_strike - long_strike
        return [
            LegSpec(
                role="short_put", action=LegAction.SELL_TO_OPEN,
                option_type="put", strike=short_strike,
                strike_label=f"{short_multiplier:.1f} ATR OTM put",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
            LegSpec(
                role="long_put", action=LegAction.BUY_TO_OPEN,
                option_type="put", strike=long_strike,
                strike_label=f"wing {wing_multiplier:.1f} ATR below short",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
        ], wing_pts
    else:
        short_strike = compute_otm_strike(price, atr, short_multiplier, "call", price)
        wing_width = atr * wing_multiplier
        long_strike = snap_strike(short_strike + wing_width, price)
        # Degenerate spread guard: wing width < strike interval
        if short_strike == long_strike:
            return [], 0.0
        wing_pts = long_strike - short_strike
        return [
            LegSpec(
                role="short_call", action=LegAction.SELL_TO_OPEN,
                option_type="call", strike=short_strike,
                strike_label=f"{short_multiplier:.1f} ATR OTM call",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
            LegSpec(
                role="long_call", action=LegAction.BUY_TO_OPEN,
                option_type="call", strike=long_strike,
                strike_label=f"wing {wing_multiplier:.1f} ATR above short",
                expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
            ),
        ], wing_pts


def build_straddle_legs(
    price: float,
    action: str,
    expiration: date,
    dte: int,
    atm_iv: float,
    otm_offset_multiplier: float | None = None,
    atr: float | None = None,
) -> list[LegSpec]:
    """Build straddle/strangle legs.

    action: 'buy' or 'sell'.
    If otm_offset_multiplier + atr provided, builds OTM strangle instead of ATM straddle.
    """
    leg_action = LegAction.BUY_TO_OPEN if action == "buy" else LegAction.SELL_TO_OPEN
    role_prefix = "long" if action == "buy" else "short"

    if otm_offset_multiplier is not None and atr is not None:
        put_strike = compute_otm_strike(price, atr, otm_offset_multiplier, "put", price)
        call_strike = compute_otm_strike(price, atr, otm_offset_multiplier, "call", price)
        label = f"{otm_offset_multiplier:.1f} ATR OTM"
    else:
        atm = compute_atm_strike(price)
        put_strike = atm
        call_strike = atm
        label = "ATM"

    return [
        LegSpec(
            role=f"{role_prefix}_put", action=leg_action,
            option_type="put", strike=put_strike,
            strike_label=f"{label} put",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
        LegSpec(
            role=f"{role_prefix}_call", action=leg_action,
            option_type="call", strike=call_strike,
            strike_label=f"{label} call",
            expiration=expiration, days_to_expiry=dte, atm_iv_at_expiry=atm_iv,
        ),
    ]


def build_pmcc_legs(
    price: float,
    atr: float,
    front_exp: TermStructurePoint,
    back_exp: TermStructurePoint,
) -> list[LegSpec]:
    """Build PMCC legs: deep ITM back LEAP call + OTM front short call."""
    # Back: deep ITM call (~1.0 ATR ITM)
    back_strike = snap_strike(price - 1.0 * atr, price)
    # Front: OTM call (~0.5 ATR OTM)
    front_strike = snap_strike(price + 0.5 * atr, price)

    return [
        LegSpec(
            role="long_back", action=LegAction.BUY_TO_OPEN,
            option_type="call", strike=back_strike,
            strike_label="deep ITM LEAP call",
            expiration=back_exp.expiration, days_to_expiry=back_exp.days_to_expiry,
            atm_iv_at_expiry=back_exp.atm_iv,
        ),
        LegSpec(
            role="short_front", action=LegAction.SELL_TO_OPEN,
            option_type="call", strike=front_strike,
            strike_label="OTM front call",
            expiration=front_exp.expiration, days_to_expiry=front_exp.days_to_expiry,
            atm_iv_at_expiry=front_exp.atm_iv,
        ),
    ]


def _build_fallback_setup_trade_spec(
    ticker: str,
    price: float,
    atr: float,
    direction: str,
    regime_id: int,
    target_dte_min: int,
    target_dte_max: int,
    inst_fields: dict | None = None,
) -> TradeSpec | None:
    """Fallback TradeSpec when vol_surface is None but instrument has options.

    Uses ATR-based strike selection and registry strike_interval for snapping.
    Target expiration is estimated from today + midpoint of DTE range.
    """
    mkt = _populate_market_fields(ticker)
    today = date.today()
    target_dte = (target_dte_min + target_dte_max) // 2
    expiration = today + timedelta(days=target_dte)

    # Use registry strike_interval so India instruments snap correctly
    si = _get_strike_interval(ticker)

    # For strike snapping in helpers below, temporarily use custom snap
    def _snap(raw: float) -> float:
        return snap_strike(raw, price, strike_interval=si)

    short_mult = 1.0 if regime_id == 1 else 1.5
    wing_mult = 0.5

    # Determine wing_width using registry strike_interval for rounding
    raw_wing = atr * wing_mult
    wing_width = si * max(1, round(raw_wing / si)) if si is not None else raw_wing

    if direction == "neutral" and regime_id in (1, 2):
        short_put = _snap(price - short_mult * atr)
        long_put = _snap(short_put - wing_width)
        short_call = _snap(price + short_mult * atr)
        long_call = _snap(short_call + wing_width)
        legs = [
            LegSpec(
                role="short_put", action=LegAction.SELL_TO_OPEN,
                option_type="put", strike=short_put,
                strike_label=f"{short_mult:.1f} ATR OTM put",
                expiration=expiration, days_to_expiry=target_dte, atm_iv_at_expiry=0.0,
            ),
            LegSpec(
                role="long_put", action=LegAction.BUY_TO_OPEN,
                option_type="put", strike=long_put,
                strike_label="wing below short put",
                expiration=expiration, days_to_expiry=target_dte, atm_iv_at_expiry=0.0,
            ),
            LegSpec(
                role="short_call", action=LegAction.SELL_TO_OPEN,
                option_type="call", strike=short_call,
                strike_label=f"{short_mult:.1f} ATR OTM call",
                expiration=expiration, days_to_expiry=target_dte, atm_iv_at_expiry=0.0,
            ),
            LegSpec(
                role="long_call", action=LegAction.BUY_TO_OPEN,
                option_type="call", strike=long_call,
                strike_label="wing above short call",
                expiration=expiration, days_to_expiry=target_dte, atm_iv_at_expiry=0.0,
            ),
        ]
        return TradeSpec(
            ticker=ticker, legs=legs, underlying_price=price,
            target_dte=target_dte, target_expiration=expiration,
            wing_width_points=wing_width,
            max_risk_per_spread=f"Wing {wing_width:.0f} pts - credit received",
            spec_rationale=(
                f"ATR-based iron condor (no vol surface, R{regime_id}). "
                f"~{target_dte} DTE. Strike interval: {si or 'US default'}."
            ),
            structure_type=StructureType.IRON_CONDOR,
            order_side=OrderSide.CREDIT,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
            exit_dte=21,
            max_profit_desc="Credit received",
            max_loss_desc=f"Wing width ({wing_width:.0f} pts) minus credit",
            exit_notes=[
                "ATR-based strikes — no vol surface available",
                "Close at 50% of credit received",
                "Close if short strike tested on either side",
            ],
            **mkt,
        )

    if regime_id in (1, 2):
        cr_dir = direction if direction in ("bullish", "bearish") else "bullish"
        if cr_dir == "bullish":
            short_strike = _snap(price - short_mult * atr)
            long_strike = _snap(short_strike - wing_width)
            wing_pts = short_strike - long_strike
            legs = [
                LegSpec(
                    role="short_put", action=LegAction.SELL_TO_OPEN,
                    option_type="put", strike=short_strike,
                    strike_label=f"{short_mult:.1f} ATR OTM put",
                    expiration=expiration, days_to_expiry=target_dte, atm_iv_at_expiry=0.0,
                ),
                LegSpec(
                    role="long_put", action=LegAction.BUY_TO_OPEN,
                    option_type="put", strike=long_strike,
                    strike_label="wing below short put",
                    expiration=expiration, days_to_expiry=target_dte, atm_iv_at_expiry=0.0,
                ),
            ]
        else:
            short_strike = _snap(price + short_mult * atr)
            long_strike = _snap(short_strike + wing_width)
            wing_pts = long_strike - short_strike
            legs = [
                LegSpec(
                    role="short_call", action=LegAction.SELL_TO_OPEN,
                    option_type="call", strike=short_strike,
                    strike_label=f"{short_mult:.1f} ATR OTM call",
                    expiration=expiration, days_to_expiry=target_dte, atm_iv_at_expiry=0.0,
                ),
                LegSpec(
                    role="long_call", action=LegAction.BUY_TO_OPEN,
                    option_type="call", strike=long_strike,
                    strike_label="wing above short call",
                    expiration=expiration, days_to_expiry=target_dte, atm_iv_at_expiry=0.0,
                ),
            ]
        return TradeSpec(
            ticker=ticker, legs=legs, underlying_price=price,
            target_dte=target_dte, target_expiration=expiration,
            wing_width_points=wing_pts,
            max_risk_per_spread=f"Wing {wing_pts:.0f} pts - credit received",
            spec_rationale=(
                f"ATR-based {cr_dir} credit spread (no vol surface, R{regime_id}). "
                f"~{target_dte} DTE. Strike interval: {si or 'US default'}."
            ),
            structure_type=StructureType.CREDIT_SPREAD,
            order_side=OrderSide.CREDIT,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
            exit_dte=21,
            max_profit_desc="Credit received",
            max_loss_desc=f"Wing width ({wing_pts:.0f} pts) minus credit",
            exit_notes=[
                "ATR-based strikes — no vol surface available",
                "Close at 50% of credit received",
                "Close if short strike tested",
            ],
            **mkt,
        )

    # R3/R4: debit spread (directional, risk-defined)
    db_dir = direction if direction in ("bullish", "bearish") else "bullish"
    if db_dir == "bullish":
        long_strike = _snap(price)
        short_strike = _snap(price + wing_mult * atr)
        wing_pts = short_strike - long_strike
        legs = [
            LegSpec(
                role="long_call", action=LegAction.BUY_TO_OPEN,
                option_type="call", strike=long_strike,
                strike_label="ATM call",
                expiration=expiration, days_to_expiry=target_dte, atm_iv_at_expiry=0.0,
            ),
            LegSpec(
                role="short_call", action=LegAction.SELL_TO_OPEN,
                option_type="call", strike=short_strike,
                strike_label=f"{wing_mult:.1f} ATR OTM call",
                expiration=expiration, days_to_expiry=target_dte, atm_iv_at_expiry=0.0,
            ),
        ]
    else:
        long_strike = _snap(price)
        short_strike = _snap(price - wing_mult * atr)
        wing_pts = long_strike - short_strike
        legs = [
            LegSpec(
                role="long_put", action=LegAction.BUY_TO_OPEN,
                option_type="put", strike=long_strike,
                strike_label="ATM put",
                expiration=expiration, days_to_expiry=target_dte, atm_iv_at_expiry=0.0,
            ),
            LegSpec(
                role="short_put", action=LegAction.SELL_TO_OPEN,
                option_type="put", strike=short_strike,
                strike_label=f"{wing_mult:.1f} ATR OTM put",
                expiration=expiration, days_to_expiry=target_dte, atm_iv_at_expiry=0.0,
            ),
        ]
    return TradeSpec(
        ticker=ticker, legs=legs, underlying_price=price,
        target_dte=target_dte, target_expiration=expiration,
        wing_width_points=wing_pts,
        spec_rationale=(
            f"ATR-based {db_dir} debit spread (no vol surface, R{regime_id}). "
            f"~{target_dte} DTE. Strike interval: {si or 'US default'}."
        ),
        structure_type=StructureType.DEBIT_SPREAD,
        order_side=OrderSide.DEBIT,
        profit_target_pct=0.50,
        stop_loss_pct=0.50,
        exit_dte=14,
        max_profit_desc="Spread width minus debit paid",
        max_loss_desc="Net debit paid",
        exit_notes=[
            "ATR-based strikes — no vol surface available",
            "Target 50% of max profit",
            "Close at 50% loss of debit paid",
        ],
        **mkt,
    )


def build_setup_trade_spec(
    ticker: str,
    price: float,
    atr: float,
    direction: str,
    regime_id: int,
    vol_surface: VolatilitySurface | None,
    target_dte_min: int = 30,
    target_dte_max: int = 45,
) -> TradeSpec | None:
    """Build a suggested default TradeSpec for a setup (breakout, momentum, MR, ORB).

    Income-first bias: credit spreads in R1/R2, debit spreads in R3.
    R4: debit spreads only (directional, risk-defined) — no theta selling in R4.

    When vol_surface is None but the instrument has options (e.g., India F&O indices),
    falls back to ATR-based strike selection using the registry's strike_interval.
    """

    mkt = _populate_market_fields(ticker)

    if vol_surface is None or not vol_surface.term_structure:
        # Fallback: check if this instrument has options via registry
        inst = _get_instrument_info(ticker)
        if inst is not None and inst.max_dte > 0:
            # Any instrument with options (India indices, India F&O stocks, US ETFs)
            # Clamp DTE range to instrument's max_dte
            clamped_max = min(target_dte_max, inst.max_dte)
            clamped_min = min(target_dte_min, clamped_max)
            return _build_fallback_setup_trade_spec(
                ticker, price, atr, direction, regime_id,
                clamped_min, clamped_max,
            )
        # For non-options instruments or unknown tickers, return None
        return None

    exp_pt = find_best_expiration(vol_surface.term_structure, target_dte_min, target_dte_max)
    if exp_pt is None:
        return None

    if direction == "neutral" and regime_id in (1, 2):
        # Iron condor for neutral setups
        legs, wing_width = build_iron_condor_legs(
            price, atr, regime_id, exp_pt.expiration, exp_pt.days_to_expiry, exp_pt.atm_iv,
        )
        rationale = f"Suggested default: iron condor (neutral + R{regime_id}). {exp_pt.days_to_expiry} DTE."
        return TradeSpec(
            ticker=ticker, legs=legs, underlying_price=price,
            target_dte=exp_pt.days_to_expiry, target_expiration=exp_pt.expiration,
            wing_width_points=wing_width,
            max_risk_per_spread=f"Wing {wing_width:.0f} pts - credit received",
            spec_rationale=rationale,
            structure_type=StructureType.IRON_CONDOR,
            order_side=OrderSide.CREDIT,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
            exit_dte=21,
            max_profit_desc="Credit received",
            max_loss_desc=f"Wing width ({wing_width:.0f} pts) minus credit",
            exit_notes=["Suggested default structure for neutral setup",
                        "Close at 50% of credit received",
                        "Close if short strike tested on either side"],
            **mkt,
        )

    if regime_id in (1, 2):
        # Credit spread (income-first)
        cr_dir = direction if direction in ("bullish", "bearish") else "bullish"
        legs, wing_pts = build_credit_spread_legs(
            price, atr, cr_dir, exp_pt.expiration, exp_pt.days_to_expiry, exp_pt.atm_iv,
        )
        rationale = (
            f"Suggested default: {cr_dir} credit spread (income-first, R{regime_id}). "
            f"{exp_pt.days_to_expiry} DTE."
        )
        return TradeSpec(
            ticker=ticker, legs=legs, underlying_price=price,
            target_dte=exp_pt.days_to_expiry, target_expiration=exp_pt.expiration,
            wing_width_points=wing_pts,
            max_risk_per_spread=f"Wing {wing_pts:.0f} pts - credit received",
            spec_rationale=rationale,
            structure_type=StructureType.CREDIT_SPREAD,
            order_side=OrderSide.CREDIT,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
            exit_dte=21,
            max_profit_desc="Credit received",
            max_loss_desc=f"Wing width ({wing_pts:.0f} pts) minus credit",
            exit_notes=["Suggested default structure for setup",
                        "Close at 50% of credit received",
                        "Close if short strike tested"],
            **mkt,
        )

    # R3: debit spread (directional)
    db_dir = direction if direction in ("bullish", "bearish") else "bullish"
    legs = build_debit_spread_legs(
        price, atr, db_dir, exp_pt.expiration, exp_pt.days_to_expiry, exp_pt.atm_iv,
    )
    rationale = (
        f"Suggested default: {db_dir} debit spread (directional, R{regime_id}). "
        f"{exp_pt.days_to_expiry} DTE."
    )
    return TradeSpec(
        ticker=ticker, legs=legs, underlying_price=price,
        target_dte=exp_pt.days_to_expiry, target_expiration=exp_pt.expiration,
        spec_rationale=rationale,
        structure_type=StructureType.DEBIT_SPREAD,
        order_side=OrderSide.DEBIT,
        profit_target_pct=0.50,
        stop_loss_pct=0.50,
        exit_dte=14,
        max_profit_desc="Spread width minus debit paid",
        max_loss_desc="Net debit paid",
        exit_notes=["Suggested default structure for setup",
                    "Target 50% of max profit",
                    "Close at 50% loss of debit paid"],
        **mkt,
    )


# --- Fill price estimation (broker quotes only) ---


def compute_max_entry_price_from_quotes(
    net_price: float,
    order_side: str | None,
    slippage_pct: float = 0.20,
) -> float | None:
    """Max price cotrader should pay/accept, computed from broker mid prices.

    Args:
        net_price: Net mid price from broker quotes (positive=credit, negative=debit).
        order_side: "credit" or "debit" (from TradeSpec.order_side).
        slippage_pct: Slippage tolerance (default 20%).

    Returns absolute value of max entry price, or None if price is zero.
    """
    if net_price > 0:
        # Net credit — don't accept less than (1 - slippage) of broker mid
        return round(net_price * (1.0 - slippage_pct), 2)
    elif net_price < 0:
        # Net debit — don't pay more than (1 + slippage) of broker mid
        return round(abs(net_price) * (1.0 + slippage_pct), 2)
    return None


# --- Equity / futures fallback (India market) ---


def _should_use_equity(ticker: str) -> bool:
    """Check if this ticker should use cash equity instead of options.

    India F&O stocks (RELIANCE, TCS, INFY, etc.) have monthly options
    with reasonable liquidity on Dhan — use options-based strategies for
    them.  Only fall back to equity for stocks with truly poor options
    liquidity (e.g. micro-caps not in F&O).
    """
    inst = _get_instrument_info(ticker)
    if inst is None:
        return False

    # Non-India: never force equity
    if inst.market != "INDIA":
        return False

    # India indices (NIFTY, BANKNIFTY): always use options
    if inst.asset_type == "index":
        return False

    # India F&O stocks: use options if they have decent liquidity
    # (all stocks in the registry are F&O-eligible with monthly options)
    liquidity = getattr(inst, "options_liquidity", None)
    if liquidity in ("high", "medium"):
        return False

    # Stocks without options_liquidity info: they're in the F&O list,
    # so default to options (the whole point of being in the registry)
    if liquidity is None:
        return False

    # Only truly illiquid stocks fall back to equity
    return True


def build_equity_trade_spec(
    ticker: str,
    price: float,
    atr: float,
    direction: str,
    setup_type: str,
    regime_id: int,
    lot_size: int = 1,
    currency: str = "USD",
) -> TradeSpec:
    """Build a cash equity trade spec when options are illiquid.

    Used for India stocks where options lack depth.  Builds a simple
    directional equity position with ATR-based stop and target.
    """
    if direction == "bullish":
        structure = StructureType.EQUITY_LONG
        order_side = OrderSide.DEBIT
        stop_price = round(price - 1.5 * atr, 2)
        target_price = round(price + 2.0 * atr, 2)
        profit_desc = f"Target {target_price:.2f} (+{2.0 * atr:.2f})"
        loss_desc = f"Stop {stop_price:.2f} (-{1.5 * atr:.2f})"
    else:
        structure = StructureType.EQUITY_SHORT
        order_side = OrderSide.CREDIT
        stop_price = round(price + 1.5 * atr, 2)
        target_price = round(price - 2.0 * atr, 2)
        profit_desc = f"Target {target_price:.2f} (-{2.0 * atr:.2f})"
        loss_desc = f"Stop {stop_price:.2f} (+{1.5 * atr:.2f})"

    mkt = _populate_market_fields(ticker)
    # Equity trades: lot_size is always 1 (shares, not contracts)
    # Registry lot_size=100 is for options — using it here causes 100x P&L errors
    mkt["lot_size"] = 1
    mkt["currency"] = currency

    return TradeSpec(
        ticker=ticker,
        legs=[],
        underlying_price=price,
        target_dte=0,
        target_expiration=date.today(),
        spec_rationale=(
            f"Cash equity {direction} — {setup_type} setup. "
            f"Options illiquid for {ticker}."
        ),
        structure_type=structure,
        order_side=order_side,
        profit_target_pct=0.50,
        stop_loss_pct=0.05,
        max_profit_desc=profit_desc,
        max_loss_desc=loss_desc,
        exit_notes=[
            f"Stop loss at {stop_price:.2f} (1.5 ATR)",
            f"Target at {target_price:.2f} (2.0 ATR, R:R 1.33)",
            "Trail stop by 1 ATR after 50% profit",
            "Cash equity — no time decay, no expiry pressure",
        ],
        max_entry_price=price,
        **mkt,
    )


# --- Closing trade helpers ---


def build_closing_trade_spec(
    open_trade_spec: TradeSpec,
    close_reason: str,
    current_price: float | None = None,
) -> TradeSpec:
    """Build the inverse TradeSpec to close an open position.

    Flips every leg's action: STO -> BTC, BTO -> STC.
    Inherits ticker, strikes, expirations from the open trade.

    Args:
        open_trade_spec: The trade that is currently open.
        close_reason: Why we are closing ("stress_fail", "profit_target", "stop_loss", etc.)
        current_price: Current underlying price (for rationale). Falls back to open spec price.

    Returns:
        TradeSpec with inverted legs, order_side flipped, and close rationale.
    """
    closing_legs = []
    for leg in open_trade_spec.legs:
        # Flip action: STO -> BTC, BTO -> STC
        if leg.action == LegAction.SELL_TO_OPEN:
            close_action = LegAction.BUY_TO_CLOSE
        else:
            close_action = LegAction.SELL_TO_CLOSE

        closing_legs.append(LegSpec(
            role=leg.role,
            action=close_action,
            quantity=leg.quantity,
            option_type=leg.option_type,
            strike=leg.strike,
            strike_label=leg.strike_label,
            expiration=leg.expiration,
            days_to_expiry=leg.days_to_expiry,
            atm_iv_at_expiry=leg.atm_iv_at_expiry,
        ))

    # Flip order side: opening credit closes as debit (buy back) and vice versa
    if open_trade_spec.order_side == "credit":
        close_side: str | None = "debit"
    elif open_trade_spec.order_side == "debit":
        close_side = "credit"
    else:
        close_side = open_trade_spec.order_side

    price = current_price if current_price is not None else open_trade_spec.underlying_price
    mkt = _populate_market_fields(open_trade_spec.ticker)
    # Explicit fields from open_trade_spec override registry defaults
    mkt.update({
        "currency": open_trade_spec.currency,
        "lot_size": open_trade_spec.lot_size,
        "settlement": open_trade_spec.settlement,
        "exercise_style": open_trade_spec.exercise_style,
    })

    return TradeSpec(
        ticker=open_trade_spec.ticker,
        legs=closing_legs,
        underlying_price=price,
        target_dte=open_trade_spec.target_dte,
        target_expiration=open_trade_spec.target_expiration,
        spec_rationale=f"CLOSE: {close_reason}",
        structure_type=open_trade_spec.structure_type,
        order_side=close_side,
        wing_width_points=open_trade_spec.wing_width_points,
        **mkt,
    )


# ---------------------------------------------------------------------------
# Chain-aware strike selection  (Task 3 — additive, no existing code touched)
# ---------------------------------------------------------------------------

from income_desk.models.chain import AvailableStrike, ChainContext  # noqa: E402


def _atr_mult_for_regime(regime_id: int) -> float:
    """ATR multiplier for short-strike distance by regime."""
    return 1.0 if regime_id == 1 else 0.8


def pick_ic_strikes_from_chain(
    chain: ChainContext,
    atr: float,
    regime_id: int,
) -> dict[str, AvailableStrike] | None:
    """Pick iron condor strikes from broker chain.

    Returns dict with keys short_put, long_put, short_call, long_call
    (each an AvailableStrike), or None if not enough liquid strikes.
    """
    price = chain.underlying_price
    mult = _atr_mult_for_regime(regime_id)

    target_short_put = price - (mult * atr)
    target_short_call = price + (mult * atr)

    short_put = chain.nearest_put(target_short_put)
    short_call = chain.nearest_call(target_short_call)
    if short_put is None or short_call is None:
        return None

    # Long strikes: next available beyond the short strike
    long_puts = chain.put_below(short_put.strike, n=1)
    long_calls = chain.call_above(short_call.strike, n=1)
    if not long_puts or not long_calls:
        return None

    # Degenerate spread guard: wing width < strike interval
    if long_puts[0].strike == short_put.strike or long_calls[0].strike == short_call.strike:
        return None

    return {
        "short_put": short_put,
        "long_put": long_puts[0],
        "short_call": short_call,
        "long_call": long_calls[0],
    }


def pick_ifly_strikes_from_chain(
    chain: ChainContext,
    atr: float,
    regime_id: int,
) -> dict[str, AvailableStrike] | None:
    """Pick iron butterfly strikes from broker chain.

    ATM short put + call at same strike, long put below, long call above.
    Returns dict with keys short_put, short_call, long_put, long_call
    (each an AvailableStrike), or None if not enough liquid strikes.
    """
    price = chain.underlying_price

    # ATM short strikes — find nearest put and call to current price
    short_put = chain.nearest_put(price)
    short_call = chain.nearest_call(price)
    if short_put is None or short_call is None:
        return None

    # Use same ATM strike for both (pick the one nearest to price)
    atm_strike = short_put.strike
    if abs(short_call.strike - price) < abs(short_put.strike - price):
        atm_strike = short_call.strike
    # Re-pick so both are at the same strike
    short_put = chain.nearest_put(atm_strike)
    short_call = chain.nearest_call(atm_strike)
    if short_put is None or short_call is None:
        return None

    # Wing distance based on regime
    wing_mult = 1.0 if regime_id == 2 else 1.2
    wing_distance = atr * wing_mult

    target_long_put = atm_strike - wing_distance
    target_long_call = atm_strike + wing_distance

    long_put = chain.nearest_put(target_long_put)
    long_call = chain.nearest_call(target_long_call)
    if long_put is None or long_call is None:
        return None
    # Wings must be strictly beyond center (catches degenerate same-strike)
    if long_put.strike >= atm_strike or long_call.strike <= atm_strike:
        return None

    return {
        "short_put": short_put,
        "short_call": short_call,
        "long_put": long_put,
        "long_call": long_call,
    }


def pick_credit_spread_from_chain(
    chain: ChainContext,
    atr: float,
    regime_id: int,
    direction: str,
) -> dict[str, AvailableStrike] | None:
    """Pick credit spread strikes from broker chain.

    direction: "put" for bull put spread, "call" for bear call spread.
    Returns dict with keys short, long (each an AvailableStrike),
    or None if not enough liquid strikes.
    """
    price = chain.underlying_price
    mult = _atr_mult_for_regime(regime_id)

    if direction == "put":
        target_short = price - (mult * atr)
        short = chain.nearest_put(target_short)
        if short is None:
            return None
        longs = chain.put_below(short.strike, n=1)
        if not longs:
            return None
        # Degenerate spread guard
        if short.strike == longs[0].strike:
            return None
        return {"short": short, "long": longs[0]}
    else:
        target_short = price + (mult * atr)
        short = chain.nearest_call(target_short)
        if short is None:
            return None
        longs = chain.call_above(short.strike, n=1)
        if not longs:
            return None
        # Degenerate spread guard
        if short.strike == longs[0].strike:
            return None
        return {"short": short, "long": longs[0]}


def build_trade_spec_from_chain(
    chain: ChainContext,
    structure_type: str,
    strikes: dict[str, AvailableStrike],
    regime_id: int,
) -> TradeSpec:
    """Build a TradeSpec using chain-validated strikes and broker metadata.

    Uses chain.lot_size, chain.expiration, and real IV from each strike.
    """
    price = chain.underlying_price
    expiration = chain.expiration
    today = date.today()
    dte = (expiration - today).days

    # Market fields from registry (currency, settlement, exercise_style)
    mkt = _populate_market_fields(chain.ticker)

    # Override lot_size with broker's value
    mkt["lot_size"] = chain.lot_size

    # Determine order_side and build legs based on structure_type
    if structure_type == StructureType.IRON_CONDOR:
        sp = strikes["short_put"]
        lp = strikes["long_put"]
        sc = strikes["short_call"]
        lc = strikes["long_call"]
        wing_width = sp.strike - lp.strike

        legs = [
            LegSpec(
                role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
                strike=sp.strike, strike_label=f"chain put @ {sp.strike}",
                expiration=expiration, days_to_expiry=dte,
                atm_iv_at_expiry=sp.iv or 0.0,
            ),
            LegSpec(
                role="long_put", action=LegAction.BUY_TO_OPEN, option_type="put",
                strike=lp.strike, strike_label=f"chain put wing @ {lp.strike}",
                expiration=expiration, days_to_expiry=dte,
                atm_iv_at_expiry=lp.iv or 0.0,
            ),
            LegSpec(
                role="short_call", action=LegAction.SELL_TO_OPEN, option_type="call",
                strike=sc.strike, strike_label=f"chain call @ {sc.strike}",
                expiration=expiration, days_to_expiry=dte,
                atm_iv_at_expiry=sc.iv or 0.0,
            ),
            LegSpec(
                role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call",
                strike=lc.strike, strike_label=f"chain call wing @ {lc.strike}",
                expiration=expiration, days_to_expiry=dte,
                atm_iv_at_expiry=lc.iv or 0.0,
            ),
        ]
        order_side = OrderSide.CREDIT

    elif structure_type == StructureType.IRON_BUTTERFLY:
        sp = strikes["short_put"]
        sc = strikes["short_call"]
        lp = strikes["long_put"]
        lc = strikes["long_call"]
        wing_width = sp.strike - lp.strike

        legs = [
            LegSpec(
                role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
                strike=sp.strike, strike_label=f"chain ATM put @ {sp.strike}",
                expiration=expiration, days_to_expiry=dte,
                atm_iv_at_expiry=sp.iv or 0.0,
            ),
            LegSpec(
                role="short_call", action=LegAction.SELL_TO_OPEN, option_type="call",
                strike=sc.strike, strike_label=f"chain ATM call @ {sc.strike}",
                expiration=expiration, days_to_expiry=dte,
                atm_iv_at_expiry=sc.iv or 0.0,
            ),
            LegSpec(
                role="long_put", action=LegAction.BUY_TO_OPEN, option_type="put",
                strike=lp.strike, strike_label=f"chain put wing @ {lp.strike}",
                expiration=expiration, days_to_expiry=dte,
                atm_iv_at_expiry=lp.iv or 0.0,
            ),
            LegSpec(
                role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call",
                strike=lc.strike, strike_label=f"chain call wing @ {lc.strike}",
                expiration=expiration, days_to_expiry=dte,
                atm_iv_at_expiry=lc.iv or 0.0,
            ),
        ]
        order_side = OrderSide.CREDIT

    elif structure_type == StructureType.CREDIT_SPREAD:
        s = strikes["short"]
        l = strikes["long"]
        wing_width = abs(s.strike - l.strike)
        opt_type = s.option_type

        legs = [
            LegSpec(
                role=f"short_{opt_type}", action=LegAction.SELL_TO_OPEN,
                option_type=opt_type, strike=s.strike,
                strike_label=f"chain {opt_type} @ {s.strike}",
                expiration=expiration, days_to_expiry=dte,
                atm_iv_at_expiry=s.iv or 0.0,
            ),
            LegSpec(
                role=f"long_{opt_type}", action=LegAction.BUY_TO_OPEN,
                option_type=opt_type, strike=l.strike,
                strike_label=f"chain {opt_type} wing @ {l.strike}",
                expiration=expiration, days_to_expiry=dte,
                atm_iv_at_expiry=l.iv or 0.0,
            ),
        ]
        order_side = OrderSide.CREDIT

    else:
        raise ValueError(f"Unsupported structure_type for chain build: {structure_type}")

    # Entry window from market
    entry_start, entry_end, entry_tz = _entry_window_for_market(chain.ticker, "income")

    return TradeSpec(
        ticker=chain.ticker,
        legs=legs,
        underlying_price=price,
        target_dte=dte,
        target_expiration=expiration,
        wing_width_points=wing_width,
        spec_rationale=f"Strikes from broker chain ({chain.expiration}), regime R{regime_id}",
        structure_type=structure_type,
        order_side=order_side,
        entry_window_start=entry_start,
        entry_window_end=entry_end,
        entry_window_timezone=entry_tz,
        **mkt,
    )
