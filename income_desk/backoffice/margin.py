"""Broker-specific margin requirements — pure computation.

No I/O, no state, no side effects.  eTrading calls this instead of
hardcoding margin percentages so every broker gets accurate numbers.

Usage::

    from income_desk.backoffice.margin import compute_margin_requirements

    req = compute_margin_requirements(
        structure_type="iron_condor",
        broker_type="tastytrade",
        wing_width=5.0,
        lot_size=100,
        underlying_price=550.0,
    )
"""

from __future__ import annotations

from pydantic import BaseModel


class MarginRequirements(BaseModel):
    """Margin requirements for a given structure type and broker."""

    broker_type: str  # "tastytrade", "schwab", "dhan", "zerodha", "ibkr", "fidelity"
    structure_type: str  # "iron_condor", "credit_spread", etc.
    margin_type: str  # "portfolio", "reg_t", "span"
    initial_margin_pct: float  # % of notional or wing width
    maintenance_margin_pct: float
    buying_power_reduction: float  # Per contract in dollars/INR
    notes: str = ""


# ---------------------------------------------------------------------------
# Defined-risk structures — margin = max loss = wing_width * lot_size
# ---------------------------------------------------------------------------
_DEFINED_RISK_STRUCTURES = frozenset({
    "iron_condor",
    "iron_butterfly",
    "credit_spread",
    "debit_spread",
    "vertical",
    "butterfly",
})

# Undefined-risk / naked structures
_NAKED_STRUCTURES = frozenset({
    "naked_put",
    "naked_call",
    "short_straddle",
    "short_strangle",
    "ratio_spread",
})

# Calendar / diagonal — margin ≈ debit paid (defined risk in practice)
_CALENDAR_STRUCTURES = frozenset({
    "calendar",
    "diagonal",
})

# Equity positions
_EQUITY_STRUCTURES = frozenset({
    "equity_long",
    "equity_short",
    "covered_call",
    "cash_secured_put",
})


def compute_margin_requirements(
    structure_type: str,
    broker_type: str,
    wing_width: float = 5.0,
    lot_size: int = 100,
    underlying_price: float = 0.0,
    currency: str = "USD",
) -> MarginRequirements:
    """Compute broker-specific margin for a given structure.

    Parameters
    ----------
    structure_type:
        One of the known structure types (iron_condor, credit_spread,
        naked_put, equity_long, etc.).
    broker_type:
        Broker identifier — tastytrade, schwab, fidelity, dhan, zerodha, ibkr.
    wing_width:
        Width between strikes for defined-risk spreads (dollars / INR).
    lot_size:
        Contract multiplier (100 for US equity options, varies for India).
    underlying_price:
        Current price of the underlying — needed for naked / equity calcs.
    currency:
        "USD" or "INR".  Dhan/Zerodha default to INR.

    Returns
    -------
    MarginRequirements
        Pydantic model with initial/maintenance margin and BPR.
    """
    broker = broker_type.lower().strip()
    struct = structure_type.lower().strip().replace(" ", "_").replace("-", "_")

    if broker in ("tastytrade", "ibkr"):
        return _portfolio_margin(struct, broker, wing_width, lot_size, underlying_price, currency)
    if broker in ("schwab", "fidelity"):
        return _reg_t_margin(struct, broker, wing_width, lot_size, underlying_price, currency)
    if broker in ("dhan", "zerodha"):
        return _span_margin(struct, broker, wing_width, lot_size, underlying_price, currency)

    # Unknown broker — fall back to conservative Reg-T rules
    return _reg_t_margin(struct, broker, wing_width, lot_size, underlying_price, currency)


# ---------------------------------------------------------------------------
# Portfolio margin (TastyTrade / IBKR)
# ---------------------------------------------------------------------------

def _portfolio_margin(
    struct: str,
    broker: str,
    wing_width: float,
    lot_size: int,
    price: float,
    currency: str,
) -> MarginRequirements:
    if struct in _DEFINED_RISK_STRUCTURES:
        bpr = wing_width * lot_size
        return MarginRequirements(
            broker_type=broker,
            structure_type=struct,
            margin_type="portfolio",
            initial_margin_pct=100.0,  # 100% of max loss
            maintenance_margin_pct=100.0,
            buying_power_reduction=bpr,
            notes=f"Defined risk — BPR = wing width ({wing_width}) × lot size ({lot_size})",
        )

    if struct in _NAKED_STRUCTURES:
        if price <= 0:
            raise ValueError("underlying_price required for naked / undefined-risk structures")
        bpr = 0.20 * price * lot_size
        return MarginRequirements(
            broker_type=broker,
            structure_type=struct,
            margin_type="portfolio",
            initial_margin_pct=20.0,
            maintenance_margin_pct=15.0,
            buying_power_reduction=bpr,
            notes=f"Naked — 20% of underlying ({price}) × lot size ({lot_size})",
        )

    if struct in _CALENDAR_STRUCTURES:
        # Calendar / diagonal: debit paid is max loss; approximate as wing_width * lot_size
        bpr = wing_width * lot_size
        return MarginRequirements(
            broker_type=broker,
            structure_type=struct,
            margin_type="portfolio",
            initial_margin_pct=100.0,
            maintenance_margin_pct=100.0,
            buying_power_reduction=bpr,
            notes="Calendar/diagonal — BPR ≈ net debit paid (approximated via wing_width × lot_size)",
        )

    if struct in _EQUITY_STRUCTURES:
        if price <= 0:
            raise ValueError("underlying_price required for equity structures")
        notional = price * lot_size
        # Portfolio margin on equities: ~15% initial, ~12% maintenance
        init_pct = 15.0
        maint_pct = 12.0
        if struct == "cash_secured_put":
            # Full cash-secured
            init_pct = 100.0
            maint_pct = 100.0
            notional = price * lot_size  # strike × lot really, but price is proxy
        bpr = notional * init_pct / 100.0
        return MarginRequirements(
            broker_type=broker,
            structure_type=struct,
            margin_type="portfolio",
            initial_margin_pct=init_pct,
            maintenance_margin_pct=maint_pct,
            buying_power_reduction=bpr,
            notes=f"Equity — {init_pct}% initial on notional ({price} × {lot_size})",
        )

    # Fallback — treat as defined risk
    bpr = wing_width * lot_size
    return MarginRequirements(
        broker_type=broker,
        structure_type=struct,
        margin_type="portfolio",
        initial_margin_pct=100.0,
        maintenance_margin_pct=100.0,
        buying_power_reduction=bpr,
        notes=f"Unknown structure '{struct}' — defaulting to wing_width × lot_size",
    )


# ---------------------------------------------------------------------------
# Reg-T margin (Schwab / Fidelity)
# ---------------------------------------------------------------------------

def _reg_t_margin(
    struct: str,
    broker: str,
    wing_width: float,
    lot_size: int,
    price: float,
    currency: str,
) -> MarginRequirements:
    if struct in _DEFINED_RISK_STRUCTURES:
        bpr = wing_width * lot_size
        return MarginRequirements(
            broker_type=broker,
            structure_type=struct,
            margin_type="reg_t",
            initial_margin_pct=100.0,
            maintenance_margin_pct=100.0,
            buying_power_reduction=bpr,
            notes=f"Defined risk — BPR = wing width ({wing_width}) × lot size ({lot_size})",
        )

    if struct in _NAKED_STRUCTURES:
        if price <= 0:
            raise ValueError("underlying_price required for naked / undefined-risk structures")
        # Reg-T naked: max(20% underlying, strike − OTM amount) × lot + premium
        # Without strike info we use 20% of underlying as the standard approximation
        bpr = 0.20 * price * lot_size
        return MarginRequirements(
            broker_type=broker,
            structure_type=struct,
            margin_type="reg_t",
            initial_margin_pct=20.0,
            maintenance_margin_pct=15.0,
            buying_power_reduction=bpr,
            notes=(
                f"Reg-T naked — 20% of underlying ({price}) × lot size ({lot_size}). "
                "Actual may be max(20% underlying, strike−OTM) + premium."
            ),
        )

    if struct in _CALENDAR_STRUCTURES:
        bpr = wing_width * lot_size
        return MarginRequirements(
            broker_type=broker,
            structure_type=struct,
            margin_type="reg_t",
            initial_margin_pct=100.0,
            maintenance_margin_pct=100.0,
            buying_power_reduction=bpr,
            notes="Calendar/diagonal — BPR ≈ net debit paid (approximated via wing_width × lot_size)",
        )

    if struct in _EQUITY_STRUCTURES:
        if price <= 0:
            raise ValueError("underlying_price required for equity structures")
        notional = price * lot_size
        if struct == "cash_secured_put":
            return MarginRequirements(
                broker_type=broker,
                structure_type=struct,
                margin_type="reg_t",
                initial_margin_pct=100.0,
                maintenance_margin_pct=100.0,
                buying_power_reduction=notional,
                notes=f"Cash-secured put — full cash required ({price} × {lot_size})",
            )
        # Reg-T equity: 50% initial, 25% maintenance
        init_pct = 50.0
        maint_pct = 25.0
        bpr = notional * init_pct / 100.0
        return MarginRequirements(
            broker_type=broker,
            structure_type=struct,
            margin_type="reg_t",
            initial_margin_pct=init_pct,
            maintenance_margin_pct=maint_pct,
            buying_power_reduction=bpr,
            notes=f"Reg-T equity — 50% initial, 25% maintenance on {price} × {lot_size}",
        )

    # Fallback
    bpr = wing_width * lot_size
    return MarginRequirements(
        broker_type=broker,
        structure_type=struct,
        margin_type="reg_t",
        initial_margin_pct=100.0,
        maintenance_margin_pct=100.0,
        buying_power_reduction=bpr,
        notes=f"Unknown structure '{struct}' — defaulting to wing_width × lot_size",
    )


# ---------------------------------------------------------------------------
# SPAN margin (Dhan / Zerodha — India)
# ---------------------------------------------------------------------------

def _span_margin(
    struct: str,
    broker: str,
    wing_width: float,
    lot_size: int,
    price: float,
    currency: str,
) -> MarginRequirements:
    # Force INR for Indian brokers
    effective_currency = "INR"

    if struct in _DEFINED_RISK_STRUCTURES:
        bpr = wing_width * lot_size
        return MarginRequirements(
            broker_type=broker,
            structure_type=struct,
            margin_type="span",
            initial_margin_pct=100.0,
            maintenance_margin_pct=100.0,
            buying_power_reduction=bpr,
            notes=(
                f"SPAN defined risk — wing width ({wing_width}) × lot size ({lot_size}). "
                f"Currency: {effective_currency}. Actual SPAN may differ slightly."
            ),
        )

    if struct in _NAKED_STRUCTURES:
        if price <= 0:
            raise ValueError("underlying_price required for naked / undefined-risk structures")
        # SPAN: ~15-20% of underlying × lot_size for naked options
        span_pct = 17.5  # midpoint of 15-20% range
        bpr = span_pct / 100.0 * price * lot_size
        return MarginRequirements(
            broker_type=broker,
            structure_type=struct,
            margin_type="span",
            initial_margin_pct=span_pct,
            maintenance_margin_pct=span_pct,  # SPAN: initial ≈ maintenance
            buying_power_reduction=bpr,
            notes=(
                f"SPAN naked — ~{span_pct}% of underlying ({price}) × lot size ({lot_size}). "
                f"Currency: {effective_currency}. Actual SPAN computed by exchange."
            ),
        )

    if struct in _CALENDAR_STRUCTURES:
        bpr = wing_width * lot_size
        return MarginRequirements(
            broker_type=broker,
            structure_type=struct,
            margin_type="span",
            initial_margin_pct=100.0,
            maintenance_margin_pct=100.0,
            buying_power_reduction=bpr,
            notes=(
                f"SPAN calendar/diagonal — approximated as debit paid. "
                f"Currency: {effective_currency}."
            ),
        )

    if struct in _EQUITY_STRUCTURES:
        if price <= 0:
            raise ValueError("underlying_price required for equity structures")
        notional = price * lot_size
        # India equity: VAR + ELM ≈ 20%
        var_elm_pct = 20.0
        bpr = notional * var_elm_pct / 100.0
        return MarginRequirements(
            broker_type=broker,
            structure_type=struct,
            margin_type="span",
            initial_margin_pct=var_elm_pct,
            maintenance_margin_pct=var_elm_pct,
            buying_power_reduction=bpr,
            notes=(
                f"India equity — VAR + ELM ≈ {var_elm_pct}% of {price} × {lot_size}. "
                f"Currency: {effective_currency}."
            ),
        )

    # Fallback
    bpr = wing_width * lot_size
    return MarginRequirements(
        broker_type=broker,
        structure_type=struct,
        margin_type="span",
        initial_margin_pct=100.0,
        maintenance_margin_pct=100.0,
        buying_power_reduction=bpr,
        notes=(
            f"Unknown structure '{struct}' — defaulting to wing_width × lot_size. "
            f"Currency: {effective_currency}."
        ),
    )
