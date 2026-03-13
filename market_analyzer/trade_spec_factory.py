"""Public API for creating valid TradeSpec objects.

eTrading and other consumers call these functions to build TradeSpec
objects that are compatible with market_analyzer's portfolio tracker,
plan output, and adjustment service.

Usage::

    from market_analyzer.trade_spec_factory import create_trade_spec

    # Create an iron condor from known strikes
    spec = create_trade_spec(
        ticker="GLD",
        structure_type="iron_condor",
        legs=[
            {"action": "STO", "option_type": "put",  "strike": 218.0, "expiration": "2026-04-17"},
            {"action": "BTO", "option_type": "put",  "strike": 213.0, "expiration": "2026-04-17"},
            {"action": "STO", "option_type": "call", "strike": 225.0, "expiration": "2026-04-17"},
            {"action": "BTO", "option_type": "call", "strike": 230.0, "expiration": "2026-04-17"},
        ],
        underlying_price=221.50,
        entry_price=0.72,
    )

    # Or use a builder for common structures
    spec = build_iron_condor(
        ticker="SPY",
        underlying_price=600.0,
        short_put=585.0,
        long_put=580.0,
        short_call=615.0,
        long_call=620.0,
        expiration="2026-04-17",
    )
"""

from __future__ import annotations

from datetime import date

from market_analyzer.models.opportunity import (
    LegAction,
    LegSpec,
    OrderSide,
    StructureType,
    TradeSpec,
)


def _parse_date(d: str | date) -> date:
    """Accept ISO string or date object."""
    if isinstance(d, date):
        return d
    return date.fromisoformat(d)


def _parse_action(a: str) -> LegAction:
    """Accept 'BTO', 'STO', 'BUY_TO_OPEN', 'SELL_TO_OPEN'."""
    upper = a.upper().strip()
    if upper in ("BTO", "BUY_TO_OPEN"):
        return LegAction.BUY_TO_OPEN
    if upper in ("STO", "SELL_TO_OPEN"):
        return LegAction.SELL_TO_OPEN
    raise ValueError(f"Invalid action: {a!r}. Use 'BTO' or 'STO'.")


def _dte(expiration: date) -> int:
    return max(0, (expiration - date.today()).days)


def create_trade_spec(
    ticker: str,
    structure_type: str,
    legs: list[dict],
    underlying_price: float,
    *,
    entry_price: float | None = None,
    order_side: str | None = None,
    profit_target_pct: float | None = None,
    stop_loss_pct: float | None = None,
    exit_dte: int | None = None,
    notes: str = "",
) -> TradeSpec:
    """Create a valid TradeSpec from raw inputs.

    This is the public API for eTrading and external consumers.

    Args:
        ticker: Underlying symbol (e.g., "SPY", "GLD").
        structure_type: One of StructureType values (e.g., "iron_condor").
        legs: List of leg dicts, each with:
            - action: "BTO" or "STO"
            - option_type: "call" or "put"
            - strike: float
            - expiration: "YYYY-MM-DD" or date object
            - quantity: int (default 1)
            - role: str (optional, auto-derived if missing)
        underlying_price: Current underlying price.
        entry_price: Fill price (net credit or debit per spread).
        order_side: "credit" or "debit" (auto-detected if omitted).
        profit_target_pct: Close at X% of max profit.
        stop_loss_pct: Credit: X× credit; Debit: X fraction loss.
        exit_dte: Close when DTE drops to this.
        notes: Rationale or notes.

    Returns:
        A valid TradeSpec ready for booking or analysis.
    """
    # Build LegSpec objects
    leg_specs: list[LegSpec] = []
    for i, leg_dict in enumerate(legs):
        action = _parse_action(leg_dict["action"])
        opt_type = leg_dict["option_type"].lower()
        strike = float(leg_dict["strike"])
        exp = _parse_date(leg_dict["expiration"])
        qty = int(leg_dict.get("quantity", 1))
        role = leg_dict.get("role") or _derive_role(action, opt_type, i)

        leg_specs.append(LegSpec(
            role=role,
            action=action,
            quantity=qty,
            option_type=opt_type,
            strike=strike,
            strike_label=f"{strike:.0f} {opt_type}",
            expiration=exp,
            days_to_expiry=_dte(exp),
            atm_iv_at_expiry=0.0,  # Unknown — broker will provide
        ))

    # Determine target expiration (latest leg)
    target_exp = max(leg.expiration for leg in leg_specs)
    target_dte_val = _dte(target_exp)

    # Auto-detect order side from legs
    if order_side is None:
        order_side = _detect_order_side(structure_type, leg_specs)

    # Compute wing width for defined-risk structures
    wing_width = _compute_wing_width(structure_type, leg_specs)

    # Apply default exit rules if not specified
    defaults = _default_exit_rules(structure_type, order_side)
    if profit_target_pct is None:
        profit_target_pct = defaults.get("profit_target_pct")
    if stop_loss_pct is None:
        stop_loss_pct = defaults.get("stop_loss_pct")
    if exit_dte is None:
        exit_dte = defaults.get("exit_dte")

    return TradeSpec(
        ticker=ticker,
        legs=leg_specs,
        underlying_price=underlying_price,
        target_dte=target_dte_val,
        target_expiration=target_exp,
        wing_width_points=wing_width,
        max_risk_per_spread=(
            f"${wing_width * 100:.0f} - credit" if wing_width and order_side == "credit"
            else f"${entry_price * 100:.0f}" if entry_price and order_side == "debit"
            else None
        ),
        spec_rationale=notes or f"Manual {structure_type} via create_trade_spec",
        structure_type=structure_type,
        order_side=order_side,
        profit_target_pct=profit_target_pct,
        stop_loss_pct=stop_loss_pct,
        exit_dte=exit_dte,
        max_entry_price=entry_price,
        max_profit_desc=_max_profit_desc(structure_type, order_side),
        max_loss_desc=_max_loss_desc(structure_type, order_side, wing_width),
        exit_notes=[],
    )


# ── Builders for common structures ──


# ── DXLink Symbol Conversion ──


import re as _re

_DXLINK_PATTERN = _re.compile(
    r"^\.?(?P<ticker>[A-Z]+)"        # ticker (optional leading dot)
    r"(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})"  # YYMMDD
    r"(?P<pc>[CP])"                   # call/put
    r"(?P<strike>[\d.]+)$"            # strike price
)


def parse_dxlink_symbol(symbol: str) -> dict:
    """Parse a DXLink streamer symbol into components.

    Accepts both ``.GLD260417P455`` and ``GLD260417P455``.

    Returns:
        dict with keys: ticker, expiration (date), option_type, strike (float)

    Raises:
        ValueError if the symbol doesn't match the expected format.
    """
    m = _DXLINK_PATTERN.match(symbol.strip())
    if not m:
        raise ValueError(f"Invalid DXLink symbol: {symbol!r}")

    return {
        "ticker": m.group("ticker"),
        "expiration": date(
            2000 + int(m.group("yy")),
            int(m.group("mm")),
            int(m.group("dd")),
        ),
        "option_type": "call" if m.group("pc") == "C" else "put",
        "strike": float(m.group("strike")),
    }


def from_dxlink_symbols(
    symbols: list[str],
    actions: list[str],
    underlying_price: float,
    structure_type: str | None = None,
    *,
    quantities: list[int] | None = None,
    entry_price: float | None = None,
    order_side: str | None = None,
    profit_target_pct: float | None = None,
    stop_loss_pct: float | None = None,
    exit_dte: int | None = None,
) -> TradeSpec:
    """Build a TradeSpec from DXLink streamer symbols + actions.

    This is the reverse of ``TradeSpec.dxlink_symbols``. eTrading reads
    positions from the broker as DXLink symbols and calls this to get a
    TradeSpec for analysis (POP, breakevens, health checks, adjustments).

    Args:
        symbols: DXLink symbols, e.g. [".GLD260417P455", ".GLD260417P450", ...]
        actions: Matching actions per leg: ["STO", "BTO", ...].
        underlying_price: Current underlying price.
        structure_type: Optional structure hint (auto-detected if omitted).
        quantities: Per-leg quantities (default all 1).
        entry_price: Fill price (net credit or debit per spread).
        order_side: "credit" or "debit" (auto-detected if omitted).
        profit_target_pct: Close at X% of max profit.
        stop_loss_pct: Credit: X x credit; Debit: X fraction loss.
        exit_dte: Close when DTE drops to this.

    Returns:
        A valid TradeSpec.

    Example::

        spec = from_dxlink_symbols(
            symbols=[".GLD260417P455", ".GLD260417P450",
                     ".GLD260417C480", ".GLD260417C485"],
            actions=["STO", "BTO", "STO", "BTO"],
            underlying_price=466.88,
        )
        # Auto-detects: iron_condor, credit, default exit rules
    """
    if len(symbols) != len(actions):
        raise ValueError(f"symbols ({len(symbols)}) and actions ({len(actions)}) must match")

    qtys = quantities or [1] * len(symbols)
    if len(qtys) != len(symbols):
        raise ValueError(f"quantities ({len(qtys)}) must match symbols ({len(symbols)})")

    parsed = [parse_dxlink_symbol(s) for s in symbols]
    ticker = parsed[0]["ticker"]

    # Auto-detect structure type from leg pattern
    if structure_type is None:
        structure_type = _detect_structure_from_legs(parsed, actions)

    legs = []
    for i, (p, action_str) in enumerate(zip(parsed, actions)):
        legs.append({
            "action": action_str,
            "option_type": p["option_type"],
            "strike": p["strike"],
            "expiration": p["expiration"],
            "quantity": qtys[i],
        })

    return create_trade_spec(
        ticker=ticker,
        structure_type=structure_type,
        legs=legs,
        underlying_price=underlying_price,
        entry_price=entry_price,
        order_side=order_side,
        profit_target_pct=profit_target_pct,
        stop_loss_pct=stop_loss_pct,
        exit_dte=exit_dte,
    )


def to_dxlink_symbols(spec: TradeSpec) -> list[str]:
    """Convert a TradeSpec to DXLink streamer symbols.

    Convenience wrapper around ``spec.dxlink_symbols``.
    """
    return spec.dxlink_symbols


def _detect_structure_from_legs(parsed: list[dict], actions: list[str]) -> str:
    """Auto-detect structure type from leg pattern."""
    n = len(parsed)
    puts = [p for p in parsed if p["option_type"] == "put"]
    calls = [p for p in parsed if p["option_type"] == "call"]
    sto_count = sum(1 for a in actions if a.upper() in ("STO", "SELL_TO_OPEN"))
    bto_count = sum(1 for a in actions if a.upper() in ("BTO", "BUY_TO_OPEN"))

    if n == 4 and len(puts) == 2 and len(calls) == 2:
        # 4 legs, 2 puts + 2 calls
        put_strikes = sorted(p["strike"] for p in puts)
        call_strikes = sorted(p["strike"] for p in calls)
        if put_strikes[1] == call_strikes[0]:
            # Same strike for short put and short call = iron butterfly
            return "iron_butterfly"
        if sto_count == 2 and bto_count == 2:
            return "iron_condor"
        if bto_count == 2 and sto_count == 2:
            # Inner legs are BTO = iron man (inverse IC)
            return "iron_man"

    if n == 2:
        exps = [p["expiration"] for p in parsed]
        if exps[0] != exps[1]:
            # Different expirations
            strikes = [p["strike"] for p in parsed]
            if strikes[0] == strikes[1]:
                return "calendar"
            return "diagonal"
        # Same expiration, 2 legs
        if len(puts) == 2 or len(calls) == 2:
            if sto_count == 1 and bto_count == 1:
                return "credit_spread" if sto_count == 1 else "debit_spread"
            return "credit_spread"
        if len(puts) == 1 and len(calls) == 1:
            return "straddle"

    if n == 1:
        return "long_option"

    return "iron_condor"  # fallback


# ── Builders for common structures ──


def build_iron_condor(
    ticker: str,
    underlying_price: float,
    short_put: float,
    long_put: float,
    short_call: float,
    long_call: float,
    expiration: str | date,
    *,
    entry_price: float | None = None,
    profit_target_pct: float = 0.50,
    stop_loss_pct: float = 2.0,
    exit_dte: int = 21,
) -> TradeSpec:
    """Build an iron condor TradeSpec from known strikes."""
    exp = _parse_date(expiration)
    return create_trade_spec(
        ticker=ticker,
        structure_type="iron_condor",
        legs=[
            {"action": "STO", "option_type": "put", "strike": short_put, "expiration": exp, "role": "short_put"},
            {"action": "BTO", "option_type": "put", "strike": long_put, "expiration": exp, "role": "long_put"},
            {"action": "STO", "option_type": "call", "strike": short_call, "expiration": exp, "role": "short_call"},
            {"action": "BTO", "option_type": "call", "strike": long_call, "expiration": exp, "role": "long_call"},
        ],
        underlying_price=underlying_price,
        entry_price=entry_price,
        order_side="credit",
        profit_target_pct=profit_target_pct,
        stop_loss_pct=stop_loss_pct,
        exit_dte=exit_dte,
    )


def build_credit_spread(
    ticker: str,
    underlying_price: float,
    short_strike: float,
    long_strike: float,
    option_type: str,
    expiration: str | date,
    *,
    entry_price: float | None = None,
    profit_target_pct: float = 0.50,
    stop_loss_pct: float = 2.0,
    exit_dte: int = 21,
) -> TradeSpec:
    """Build a credit spread (bull put or bear call)."""
    exp = _parse_date(expiration)
    return create_trade_spec(
        ticker=ticker,
        structure_type="credit_spread",
        legs=[
            {"action": "STO", "option_type": option_type, "strike": short_strike, "expiration": exp, "role": f"short_{option_type}"},
            {"action": "BTO", "option_type": option_type, "strike": long_strike, "expiration": exp, "role": f"long_{option_type}"},
        ],
        underlying_price=underlying_price,
        entry_price=entry_price,
        order_side="credit",
        profit_target_pct=profit_target_pct,
        stop_loss_pct=stop_loss_pct,
        exit_dte=exit_dte,
    )


def build_debit_spread(
    ticker: str,
    underlying_price: float,
    long_strike: float,
    short_strike: float,
    option_type: str,
    expiration: str | date,
    *,
    entry_price: float | None = None,
    profit_target_pct: float = 0.50,
    stop_loss_pct: float = 0.50,
    exit_dte: int = 14,
) -> TradeSpec:
    """Build a debit spread (bull call or bear put)."""
    exp = _parse_date(expiration)
    return create_trade_spec(
        ticker=ticker,
        structure_type="debit_spread",
        legs=[
            {"action": "BTO", "option_type": option_type, "strike": long_strike, "expiration": exp, "role": f"long_{option_type}"},
            {"action": "STO", "option_type": option_type, "strike": short_strike, "expiration": exp, "role": f"short_{option_type}"},
        ],
        underlying_price=underlying_price,
        entry_price=entry_price,
        order_side="debit",
        profit_target_pct=profit_target_pct,
        stop_loss_pct=stop_loss_pct,
        exit_dte=exit_dte,
    )


def build_calendar(
    ticker: str,
    underlying_price: float,
    strike: float,
    option_type: str,
    front_expiration: str | date,
    back_expiration: str | date,
    *,
    entry_price: float | None = None,
) -> TradeSpec:
    """Build a calendar spread (same strike, different expirations)."""
    front = _parse_date(front_expiration)
    back = _parse_date(back_expiration)
    return create_trade_spec(
        ticker=ticker,
        structure_type="calendar",
        legs=[
            {"action": "STO", "option_type": option_type, "strike": strike, "expiration": front, "role": "short_front"},
            {"action": "BTO", "option_type": option_type, "strike": strike, "expiration": back, "role": "long_back"},
        ],
        underlying_price=underlying_price,
        entry_price=entry_price,
        order_side="debit",
    )


# ── Internal helpers ──


def _derive_role(action: LegAction, option_type: str, index: int) -> str:
    prefix = "short" if action == LegAction.SELL_TO_OPEN else "long"
    return f"{prefix}_{option_type}_{index}"


def _detect_order_side(structure_type: str, legs: list[LegSpec]) -> str:
    """Auto-detect credit vs debit from structure type."""
    credit_structures = {
        "iron_condor", "iron_butterfly", "credit_spread",
        "ratio_spread", "strangle", "straddle",
    }
    if structure_type in credit_structures:
        return "credit"
    return "debit"


def _compute_wing_width(structure_type: str, legs: list[LegSpec]) -> float | None:
    """Compute wing width (distance between short and long strikes)."""
    if structure_type in ("iron_condor", "iron_butterfly", "iron_man"):
        puts = [l for l in legs if l.option_type == "put"]
        if len(puts) >= 2:
            strikes = sorted([l.strike for l in puts])
            return round(strikes[-1] - strikes[0], 2)
    if structure_type in ("credit_spread", "debit_spread"):
        strikes = sorted([l.strike for l in legs])
        if len(strikes) >= 2:
            return round(strikes[-1] - strikes[0], 2)
    return None


def _default_exit_rules(structure_type: str, order_side: str) -> dict:
    """Default exit rules by structure type."""
    if order_side == "credit":
        return {
            "profit_target_pct": 0.50,
            "stop_loss_pct": 2.0,
            "exit_dte": 21,
        }
    return {
        "profit_target_pct": 0.50,
        "stop_loss_pct": 0.50,
        "exit_dte": 14,
    }


def _max_profit_desc(structure_type: str, order_side: str) -> str:
    if order_side == "credit":
        return "Credit received"
    if structure_type in ("debit_spread",):
        return "Spread width minus debit paid"
    if structure_type in ("calendar", "diagonal"):
        return "Front leg decay minus back leg decay"
    return "Depends on price movement"


def _max_loss_desc(
    structure_type: str, order_side: str, wing_width: float | None,
) -> str:
    if order_side == "credit" and wing_width:
        return f"Wing width (${wing_width:.0f}) minus credit"
    if order_side == "debit":
        return "Net debit paid"
    if structure_type == "ratio_spread":
        return "UNLIMITED beyond naked short strike"
    return "Depends on structure"
