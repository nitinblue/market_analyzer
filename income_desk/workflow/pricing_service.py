"""PricingService — single source of truth for option trade repricing.

Fetches chain ONCE per ticker. Reprices all structures. Returns immutable result.
No downstream code should overwrite entry_credit after this.
"""

from __future__ import annotations

from pydantic import BaseModel

from income_desk.models.opportunity import TradeSpec
from income_desk.models.quotes import OptionQuote


class LegDetail(BaseModel):
    """Per-leg pricing from the broker chain."""

    strike: float
    option_type: str  # "call" | "put"
    action: str  # "sell" | "buy"
    bid: float
    ask: float
    mid: float
    iv: float | None = None
    delta: float | None = None
    open_interest: int = 0
    volume: int = 0


class RepricedTrade(BaseModel):
    """Immutable repricing result. Created once, never modified.

    This is the single source of truth for entry_credit.
    No downstream code may overwrite it.
    """

    model_config = {"frozen": True}

    ticker: str
    structure: str
    entry_credit: float  # Net credit (positive) or debit (negative)
    credit_source: str  # "chain" | "estimated" | "blocked"
    wing_width: float
    lot_size: int
    current_price: float
    atr_pct: float
    regime_id: int
    expiry: str | None = None
    legs_found: bool  # All legs matched in liquid chain
    liquidity_ok: bool  # OI and spread checks passed
    block_reason: str | None = None
    leg_details: list[LegDetail] = []


# ── Constants ──

MIN_OI = 100
MAX_SPREAD_PCT = 0.30  # 30% of mid


# ── Helpers ──

_SELL_ACTIONS = {"STO", "STC"}
_BUY_ACTIONS = {"BTO", "BTC"}


def _blocked(
    ticker: str,
    trade_spec: TradeSpec,
    current_price: float,
    atr_pct: float,
    regime_id: int,
    reason: str,
) -> RepricedTrade:
    """Return a blocked RepricedTrade with zero credit."""
    return RepricedTrade(
        ticker=ticker,
        structure=trade_spec.structure_type or "unknown",
        entry_credit=0.0,
        credit_source="blocked",
        wing_width=trade_spec.wing_width_points or 0.0,
        lot_size=100,
        current_price=current_price,
        atr_pct=atr_pct,
        regime_id=regime_id,
        expiry=str(trade_spec.target_expiration) if trade_spec.target_expiration else None,
        legs_found=False,
        liquidity_ok=False,
        block_reason=reason,
        leg_details=[],
    )


# ── Main function ──


def reprice_trade(
    trade_spec: TradeSpec,
    chain: list[OptionQuote],
    ticker: str,
    current_price: float,
    atr_pct: float,
    regime_id: int,
) -> RepricedTrade:
    """Reprice a TradeSpec against a live option chain.

    This is the SINGLE SOURCE OF TRUTH for entry_credit. The credit is
    computed exactly once from broker chain mid prices. No downstream
    code may overwrite it.

    Args:
        trade_spec: TradeSpec from assessors (contains legs).
        chain: list[OptionQuote] from broker for this ticker/expiration.
        ticker: Underlying symbol.
        current_price: Current underlying price.
        atr_pct: ATR as percentage of price.
        regime_id: Current regime (1-4).

    Returns:
        RepricedTrade — frozen Pydantic model. Check ``credit_source``
        for "chain" (success) or "blocked" (failure with ``block_reason``).
    """
    # Gate 1: price sanity
    if current_price <= 0:
        return _blocked(ticker, trade_spec, current_price, atr_pct, regime_id,
                        "current_price <= 0")

    # Gate 2: chain and legs exist
    if not chain or not trade_spec.legs:
        return _blocked(ticker, trade_spec, current_price, atr_pct, regime_id,
                        "No chain data or no legs")

    # Build chain lookup — only quotes with valid bid/ask
    chain_lookup: dict[tuple[float, str], OptionQuote] = {
        (q.strike, q.option_type): q
        for q in chain
        if q.bid > 0 and q.ask > 0
    }

    # Match each leg
    all_found = True
    liquidity_ok = True
    net_credit = 0.0
    leg_details: list[LegDetail] = []

    for leg in trade_spec.legs:
        key = (leg.strike, leg.option_type)
        quote = chain_lookup.get(key)

        if quote is None:
            all_found = False
            continue

        # Determine direction from action
        action_str = leg.action.value  # "STO", "STC", "BTO", "BTC"
        if action_str in _SELL_ACTIONS:
            direction = "sell"
            net_credit += quote.mid
        else:
            direction = "buy"
            net_credit -= quote.mid

        # Liquidity checks
        spread = quote.ask - quote.bid
        spread_pct = spread / quote.mid if quote.mid > 0 else 1.0
        leg_liq_ok = True
        if spread_pct > MAX_SPREAD_PCT:
            leg_liq_ok = False
        if quote.open_interest < MIN_OI:
            leg_liq_ok = False
        if not leg_liq_ok:
            liquidity_ok = False

        leg_details.append(LegDetail(
            strike=quote.strike,
            option_type=quote.option_type,
            action=direction,
            bid=quote.bid,
            ask=quote.ask,
            mid=quote.mid,
            iv=quote.implied_volatility,
            delta=quote.delta,
            open_interest=quote.open_interest,
            volume=quote.volume,
        ))

    # Gate 3: all legs must match
    if not all_found:
        return _blocked(ticker, trade_spec, current_price, atr_pct, regime_id,
                        "Missing strikes in liquid chain")

    # Compute wing_width from spec or from strikes
    wing_width = trade_spec.wing_width_points or 0.0
    if wing_width == 0.0 and len(leg_details) >= 2:
        strikes = sorted(ld.strike for ld in leg_details)
        # For spreads/condors, wing width is smallest gap between adjacent strikes
        gaps = [strikes[i + 1] - strikes[i] for i in range(len(strikes) - 1)]
        wing_width = min(gaps) if gaps else 0.0

    # Lot size from chain (first quote)
    lot_size = chain[0].lot_size if chain else 100

    return RepricedTrade(
        ticker=ticker,
        structure=trade_spec.structure_type or "unknown",
        entry_credit=round(net_credit, 4),
        credit_source="chain",
        wing_width=wing_width,
        lot_size=lot_size,
        current_price=current_price,
        atr_pct=atr_pct,
        regime_id=regime_id,
        expiry=str(trade_spec.target_expiration) if trade_spec.target_expiration else None,
        legs_found=True,
        liquidity_ok=liquidity_ok,
        block_reason=None,
        leg_details=leg_details,
    )
