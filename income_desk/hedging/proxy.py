"""Tier 3 proxy/index hedging — beta-adjusted index hedges.

For instruments with no F&O (no options, no futures). Uses a correlated
index (NIFTY, BANKNIFTY, SPY, QQQ) as a proxy hedge.

Beta-adjusted sizing: hedge lots = (position_value x beta) / (index_price x lot_size)

Basis risk is HIGH — the proxy may not move with the underlying.
This is the last resort, used when no direct or futures hedge is available.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from income_desk.hedging.models import HedgeResult, HedgeTier
from income_desk.hedging.universe import get_proxy_instrument, get_sector_beta
from income_desk.models.opportunity import (
    LegAction,
    LegSpec,
    OrderSide,
    StructureType,
    TradeSpec,
)
from income_desk.registry import MarketRegistry


def compute_portfolio_beta(
    tickers: list[str],
    values: list[float],
    index: str,
    market: str = "US",
) -> float:
    """Compute value-weighted portfolio beta vs an index.

    Uses static sector betas from universe.py. For precise beta,
    use historical return regression (not available here — pure computation only).

    Args:
        tickers: List of ticker symbols.
        values: Position values corresponding to each ticker (same currency).
        index: Index ticker to compute beta against.
        market: "US" or "INDIA".

    Returns:
        Value-weighted portfolio beta.
    """
    if not tickers or not values or len(tickers) != len(values):
        return 1.0

    total_value = sum(values)
    if total_value <= 0:
        return 1.0

    weighted_beta = 0.0
    for ticker, value in zip(tickers, values):
        beta = get_sector_beta(ticker, index, market)
        weight = value / total_value
        weighted_beta += beta * weight

    return round(weighted_beta, 3)


def recommend_proxy(
    ticker: str,
    market: str = "US",
    registry: MarketRegistry | None = None,
) -> str:
    """Recommend which index to use as a proxy hedge.

    Delegates to universe.get_proxy_instrument() — this function exists
    as the public API for the proxy module.

    Args:
        ticker: Stock ticker.
        market: "US" or "INDIA".
        registry: MarketRegistry instance.

    Returns:
        Proxy index ticker.
    """
    return get_proxy_instrument(ticker, market, registry)


def build_index_hedge(
    portfolio_value: float,
    portfolio_beta: float,
    index: str,
    index_price: float,
    regime_id: int,
    dte: int = 30,
    market: str = "US",
    hedge_pct: float = 1.0,
    registry: MarketRegistry | None = None,
) -> HedgeResult:
    """Build a beta-adjusted index hedge using index puts.

    Sizing: lots = (portfolio_value x beta x hedge_pct) / (index_price x lot_size)

    Args:
        portfolio_value: Total value of position(s) to hedge.
        portfolio_beta: Beta of position(s) vs the index.
        index: Index ticker (e.g., "NIFTY", "SPY").
        index_price: Current index price.
        regime_id: Current regime (1-4).
        dte: Days to expiration.
        market: "US" or "INDIA".
        hedge_pct: Fraction to hedge (1.0 = full, 0.5 = half).
        registry: MarketRegistry instance.

    Returns:
        HedgeResult with index put TradeSpec.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    try:
        inst = reg.get_instrument(index, market)
        lot_size = inst.lot_size
        strike_interval = inst.strike_interval
    except KeyError:
        lot_size = 100 if market == "US" else 25
        strike_interval = 50.0 if market == "INDIA" else 1.0

    # Beta-adjusted hedge value
    hedge_value = portfolio_value * portfolio_beta * hedge_pct
    notional_per_lot = index_price * lot_size

    lots = max(1, round(hedge_value / notional_per_lot)) if notional_per_lot > 0 else 1

    # Put strike: regime-based OTM distance
    otm_pct = {1: 0.05, 2: 0.03, 3: 0.04, 4: 0.02}.get(regime_id, 0.03)
    raw_strike = index_price * (1 - otm_pct)
    put_strike = math.floor(raw_strike / strike_interval) * strike_interval

    expiry = date.today() + timedelta(days=dte)

    # Cost estimate (rough)
    cost_pct_map = {1: 0.4, 2: 1.8, 3: 0.9, 4: 2.8}
    cost_pct = cost_pct_map.get(regime_id, 1.5)
    cost_estimate = portfolio_value * cost_pct / 100

    trade_spec = TradeSpec(
        ticker=index,
        underlying_price=index_price,
        target_dte=dte,
        target_expiration=expiry,
        spec_rationale=f"R{regime_id} index put: {lots} lots at {put_strike:.0f} ({otm_pct*100:.0f}% OTM)",
        structure_type=StructureType.LONG_OPTION,
        order_side=OrderSide.DEBIT,
        legs=[
            LegSpec(
                role="long_put",
                action=LegAction.BUY_TO_OPEN,
                option_type="put",
                strike=put_strike,
                strike_label=f"{otm_pct*100:.0f}% OTM put at {put_strike:.0f}",
                expiration=expiry,
                days_to_expiry=dte,
                atm_iv_at_expiry=0.25,
                quantity=lots,
            ),
        ],
        max_profit_desc=f"Index put protection: {lots} lots at {put_strike:.0f}",
        max_loss_desc=f"Premium paid (~{cost_estimate:,.0f})",
    )

    actual_coverage = (lots * notional_per_lot) / portfolio_value * 100 if portfolio_value > 0 else 0

    return HedgeResult(
        ticker=index,
        market=market,
        tier=HedgeTier.PROXY_INDEX,
        hedge_type="index_put",
        trade_spec=trade_spec,
        cost_estimate=cost_estimate,
        cost_pct=cost_pct,
        delta_reduction=min(actual_coverage / 100, 1.0) * 0.7,  # 0.7 discount for basis risk
        protection_level=f"{index} put at {put_strike:.0f}, {lots} lot(s)",
        max_loss_after_hedge=None,  # Basis risk makes max loss uncertain
        rationale=(
            f"Proxy hedge: {lots} {index} puts at {put_strike:.0f} "
            f"(beta-adjusted from {portfolio_value:,.0f} at beta {portfolio_beta:.2f})"
        ),
        regime_context=f"R{regime_id}: {otm_pct*100:.0f}% OTM index put",
        commentary=[
            f"Portfolio value: {portfolio_value:,.0f}, beta: {portfolio_beta:.2f}",
            f"Hedge value (beta-adjusted): {hedge_value:,.0f}",
            f"Index: {index} at {index_price:,.0f}, lot_size: {lot_size}",
            f"Lots: {lots} (covering {actual_coverage:.0f}% of position value)",
            "WARNING: Proxy hedge has basis risk — index may diverge from underlying",
        ],
    )
