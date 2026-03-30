"""PricingService — single source of truth for option trade repricing.

Fetches chain ONCE per ticker. Reprices all structures. Returns immutable result.
No downstream code should overwrite entry_credit after this.
"""

from __future__ import annotations

import logging
import time

from pydantic import BaseModel

from income_desk.models.opportunity import TradeSpec
from income_desk.models.quotes import OptionQuote

logger = logging.getLogger(__name__)


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


def _estimate_credit(
    trade_spec: TradeSpec,
    current_price: float,
    atr_pct: float,
    regime_id: int,
    ticker: str,
) -> RepricedTrade:
    """Produce an estimated RepricedTrade when no broker is connected.

    Uses TradeSpec.max_entry_price if available, otherwise rough
    estimate from wing width.  credit_source = "estimated".
    """
    wing_width = trade_spec.wing_width_points or 0.0
    if wing_width == 0.0 and trade_spec.legs and len(trade_spec.legs) >= 2:
        strikes = sorted(set(leg.strike for leg in trade_spec.legs))
        if len(strikes) >= 2:
            wing_width = strikes[1] - strikes[0]

    # Resolve lot_size
    try:
        lot_size = trade_spec.lot_size
        if not isinstance(lot_size, (int, float)) or lot_size <= 0:
            lot_size = None
    except Exception:
        lot_size = None
    if not lot_size:
        try:
            from income_desk import MarketRegistry
            _reg = MarketRegistry()
            _inst = _reg.get_instrument(ticker)
            lot_size = _inst.lot_size if _inst and _inst.lot_size else 100
        except Exception:
            lot_size = 100

    # Credit estimate
    try:
        max_entry = trade_spec.max_entry_price
        if isinstance(max_entry, (int, float)) and max_entry > 0:
            entry_credit = float(max_entry)
        elif wing_width > 0:
            entry_credit = wing_width * 0.28  # rough estimate
        else:
            entry_credit = 0.0
    except Exception:
        entry_credit = wing_width * 0.28 if wing_width > 0 else 0.0

    if entry_credit <= 0 or current_price <= 0:
        return _blocked(ticker, trade_spec, current_price, atr_pct, regime_id,
                        "Cannot estimate credit (no broker, no wing width)")

    return RepricedTrade(
        ticker=ticker,
        structure=trade_spec.structure_type or "unknown",
        entry_credit=round(entry_credit, 4),
        credit_source="estimated",
        wing_width=wing_width,
        lot_size=lot_size,
        current_price=current_price,
        atr_pct=atr_pct,
        regime_id=regime_id,
        expiry=str(trade_spec.target_expiration) if trade_spec.target_expiration else None,
        legs_found=False,
        liquidity_ok=True,  # Can't check without broker — assume OK
        block_reason=None,
        leg_details=[],
    )


# ── Batch repricing ──


def batch_reprice(
    entries: list[dict],
    market_data=None,
    technicals_service=None,
) -> list[RepricedTrade]:
    """Reprice multiple trades, fetching chain once per ticker.

    Groups entries by ticker so that ``get_option_chain`` is called at most
    once per unique ticker.  A 4-second sleep is inserted between tickers
    to respect Dhan's rate limit (1 req / 3 s).

    Args:
        entries: list of dicts with keys:
            - ticker (str)
            - trade_spec (TradeSpec)
            - regime_id (int)
            - atr_pct (float, optional)
            - current_price (float, optional)
        market_data: MarketDataProvider (has get_option_chain,
            get_underlying_price).
        technicals_service: Optional service with
            ``.snapshot(ticker)`` returning an object with
            ``.current_price`` and ``.atr_pct``.

    Returns:
        list of RepricedTrade in the same order as *entries*.
    """
    if not entries:
        return []

    # --- per-ticker cache ---
    ticker_cache: dict[str, dict] = {}  # ticker -> {price, atr_pct, chain}
    unique_tickers = list(dict.fromkeys(e["ticker"] for e in entries))

    for idx, ticker in enumerate(unique_tickers):
        # Price resolution
        price = 0.0
        atr_pct = 1.0

        if technicals_service is not None:
            try:
                snap = technicals_service.snapshot(ticker)
                if snap is not None:
                    if hasattr(snap, "current_price") and snap.current_price:
                        price = snap.current_price
                    if hasattr(snap, "atr_pct") and snap.atr_pct:
                        atr_pct = snap.atr_pct
            except Exception:
                logger.debug("technicals_service.snapshot(%s) failed", ticker)

        if price <= 0 and market_data is not None:
            try:
                price = market_data.get_underlying_price(ticker) or 0.0
            except Exception:
                logger.debug("market_data.get_underlying_price(%s) failed", ticker)

        # Chain fetch (rate-limited)
        chain: list = []
        if market_data is not None:
            if idx > 0:
                time.sleep(4)
            try:
                chain = market_data.get_option_chain(ticker) or []
            except Exception:
                logger.debug("market_data.get_option_chain(%s) failed", ticker)

        ticker_cache[ticker] = {"price": price, "atr_pct": atr_pct, "chain": chain}

    # --- reprice each entry ---
    results: list[RepricedTrade] = []
    for entry in entries:
        ticker = entry["ticker"]
        trade_spec = entry["trade_spec"]
        regime_id = entry["regime_id"]

        cached = ticker_cache[ticker]
        price = entry.get("current_price") or cached["price"]
        atr = entry.get("atr_pct") or cached["atr_pct"]
        chain = cached["chain"]

        if market_data is None:
            # No broker — produce estimated credit instead of blocking
            estimated = _estimate_credit(trade_spec, price, atr, regime_id, ticker)
            results.append(estimated)
        else:
            results.append(
                reprice_trade(trade_spec, chain, ticker, price, atr, regime_id)
            )

    return results
