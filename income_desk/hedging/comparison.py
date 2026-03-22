"""Compare hedge methods — ranks all available approaches for a single ticker.

Runs all available tiers, builds TradeSpecs for each, then ranks by:
1. Available=True first
2. Cost ascending (lower is better)
3. Delta reduction descending (higher is better)
"""

from __future__ import annotations

from income_desk.hedging.direct import build_collar, build_protective_put, build_put_spread_hedge
from income_desk.hedging.futures_hedge import build_futures_hedge
from income_desk.hedging.models import (
    HedgeComparison,
    HedgeComparisonEntry,
    HedgeTier,
)
from income_desk.hedging.proxy import build_index_hedge
from income_desk.hedging.resolver import resolve_hedge_strategy
from income_desk.hedging.universe import (
    classify_hedge_tier,
    get_proxy_instrument,
    get_sector_beta,
)
from income_desk.registry import MarketRegistry


def compare_hedge_methods(
    ticker: str,
    shares: int,
    current_price: float,
    regime_id: int,
    atr: float,
    market: str = "US",
    account_nlv: float | None = None,
    cost_basis: float | None = None,
    futures_price: float | None = None,
    index_price: float | None = None,
    dte: int = 30,
    registry: MarketRegistry | None = None,
) -> HedgeComparison:
    """Compare all available hedge methods for a ticker.

    Runs every available tier, builds TradeSpecs for each, then ranks them.
    Wraps each builder in try/except so a single failure doesn't abort comparison.

    Args:
        ticker: Instrument ticker.
        shares: Number of shares to hedge.
        current_price: Current price per share.
        regime_id: Current regime (1-4).
        atr: Average True Range in price units.
        market: "US" or "INDIA".
        account_nlv: Account NLV (for resolver affordability check).
        cost_basis: Average cost basis per share (for collar). Defaults to price * 0.95.
        futures_price: Futures price (for futures hedge). Estimated if None.
        index_price: Index price (for proxy hedge). Required for proxy method.
        dte: Days to expiration for built specs (default 30).
        registry: MarketRegistry instance.

    Returns:
        HedgeComparison with ranked methods and recommendation.
    """
    reg = registry or MarketRegistry()
    market = market.upper()
    position_value = shares * current_price
    basis = cost_basis or (current_price * 0.95)

    methods: list[HedgeComparisonEntry] = []

    # Resolve the recommended tier to understand which are available
    approach = resolve_hedge_strategy(
        ticker=ticker,
        position_value=position_value,
        shares=shares,
        current_price=current_price,
        regime_id=regime_id,
        market=market,
        account_nlv=account_nlv,
        registry=reg,
    )

    # ── Tier 1: Direct methods ──
    base_tier = classify_hedge_tier(ticker, market, reg)
    direct_available = base_tier == HedgeTier.DIRECT

    if direct_available:
        # Protective put
        try:
            pp = build_protective_put(
                ticker, shares, current_price, regime_id, atr, dte, market, reg,
            )
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.DIRECT,
                hedge_type="protective_put",
                trade_spec=pp.trade_spec,
                cost_estimate=pp.cost_estimate,
                cost_pct=pp.cost_pct,
                delta_reduction=pp.delta_reduction,
                basis_risk="none",
                pros=["Zero basis risk", "Simple execution", "Unlimited protection below strike"],
                cons=["Premium cost", "Time decay works against you"],
                available=True,
                unavailable_reason=None,
            ))
        except Exception as e:
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.DIRECT,
                hedge_type="protective_put",
                trade_spec=None,
                cost_estimate=None,
                cost_pct=None,
                delta_reduction=0.0,
                basis_risk="none",
                pros=[],
                cons=[],
                available=False,
                unavailable_reason=f"Build failed: {e}",
            ))

        # Collar
        try:
            collar = build_collar(
                ticker, shares, current_price, basis, regime_id, atr, dte, market, reg,
            )
            # Net cost is in % points; convert to dollar estimate
            cost_dollar = abs(collar.net_cost) * position_value / 100 if collar.net_cost else 0.0
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.DIRECT,
                hedge_type="collar",
                trade_spec=collar.trade_spec,
                cost_estimate=cost_dollar,
                cost_pct=abs(collar.net_cost) if collar.net_cost else 0.0,
                delta_reduction=0.80,
                basis_risk="none",
                pros=["Zero or near-zero cost in high IV", "Defined profit range"],
                cons=["Caps upside", "Two legs to manage"],
                available=True,
                unavailable_reason=None,
            ))
        except Exception as e:
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.DIRECT,
                hedge_type="collar",
                trade_spec=None,
                cost_estimate=None,
                cost_pct=None,
                delta_reduction=0.0,
                basis_risk="none",
                pros=[],
                cons=[],
                available=False,
                unavailable_reason=f"Build failed: {e}",
            ))

        # Put spread
        try:
            ps = build_put_spread_hedge(
                ticker, shares, current_price, 0.5, dte, market, reg,
            )
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.DIRECT,
                hedge_type="put_spread",
                trade_spec=ps.trade_spec,
                cost_estimate=ps.cost_estimate,
                cost_pct=ps.cost_pct,
                delta_reduction=ps.delta_reduction,
                basis_risk="none",
                pros=["Cheapest direct hedge", "Defined cost"],
                cons=["Limited protection range", "No protection below short put"],
                available=True,
                unavailable_reason=None,
            ))
        except Exception as e:
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.DIRECT,
                hedge_type="put_spread",
                trade_spec=None,
                cost_estimate=None,
                cost_pct=None,
                delta_reduction=0.0,
                basis_risk="none",
                pros=[],
                cons=[],
                available=False,
                unavailable_reason=f"Build failed: {e}",
            ))
    else:
        # Direct not available — add a single unavailable entry
        methods.append(HedgeComparisonEntry(
            tier=HedgeTier.DIRECT,
            hedge_type="protective_put",
            trade_spec=None,
            cost_estimate=None,
            cost_pct=None,
            delta_reduction=0.0,
            basis_risk="none",
            pros=[],
            cons=[],
            available=False,
            unavailable_reason="Options are illiquid or unavailable for this instrument",
        ))

    # ── Tier 2: Futures hedge (primarily India; US single-stock futures not practical) ──
    has_futures = market == "INDIA"
    if has_futures:
        try:
            fh = build_futures_hedge(
                ticker, shares, current_price, futures_price, dte, 1.0, market, reg,
            )
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.FUTURES_SYNTHETIC,
                hedge_type="futures_short",
                trade_spec=fh.trade_spec,
                cost_estimate=fh.cost_estimate,
                cost_pct=fh.cost_pct,
                delta_reduction=fh.delta_reduction,
                basis_risk="low",
                pros=["Lower capital than options", "No time decay", "Same-ticker exposure"],
                cons=["Basis cost", "Margin requirement", "Must roll before expiry"],
                available=True,
                unavailable_reason=None,
            ))
        except Exception as e:
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.FUTURES_SYNTHETIC,
                hedge_type="futures_short",
                trade_spec=None,
                cost_estimate=None,
                cost_pct=None,
                delta_reduction=0.0,
                basis_risk="low",
                pros=[],
                cons=[],
                available=False,
                unavailable_reason=f"Futures hedge build failed: {e}",
            ))
    else:
        methods.append(HedgeComparisonEntry(
            tier=HedgeTier.FUTURES_SYNTHETIC,
            hedge_type="futures_short",
            trade_spec=None,
            cost_estimate=None,
            cost_pct=None,
            delta_reduction=0.0,
            basis_risk="low",
            pros=[],
            cons=[],
            available=False,
            unavailable_reason="No single-stock futures available in US market",
        ))

    # ── Tier 3: Proxy hedge (always a fallback if index_price provided) ──
    if index_price is not None:
        proxy = get_proxy_instrument(ticker, market, reg)
        beta = get_sector_beta(ticker, proxy, market)
        try:
            ih = build_index_hedge(
                position_value, beta, proxy, index_price, regime_id, dte, market, 1.0, reg,
            )
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.PROXY_INDEX,
                hedge_type="index_put",
                trade_spec=ih.trade_spec,
                cost_estimate=ih.cost_estimate,
                cost_pct=ih.cost_pct,
                delta_reduction=ih.delta_reduction,
                basis_risk="high",
                pros=["Always available", "Liquid index options"],
                cons=["High basis risk", "Index may not track underlying 1:1"],
                available=True,
                unavailable_reason=None,
            ))
        except Exception as e:
            methods.append(HedgeComparisonEntry(
                tier=HedgeTier.PROXY_INDEX,
                hedge_type="index_put",
                trade_spec=None,
                cost_estimate=None,
                cost_pct=None,
                delta_reduction=0.0,
                basis_risk="high",
                pros=[],
                cons=[],
                available=False,
                unavailable_reason=f"Proxy hedge build failed: {e}",
            ))
    else:
        methods.append(HedgeComparisonEntry(
            tier=HedgeTier.PROXY_INDEX,
            hedge_type="index_put",
            trade_spec=None,
            cost_estimate=None,
            cost_pct=None,
            delta_reduction=0.0,
            basis_risk="high",
            pros=[],
            cons=[],
            available=False,
            unavailable_reason="No index price provided — proxy hedge not computed",
        ))

    # ── Rank: available=True first, then cost_pct ascending, delta_reduction descending ──
    _basis_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
    methods.sort(key=lambda m: (
        0 if m.available else 1,
        (m.cost_pct if m.cost_pct is not None else 999.0),
        -(m.delta_reduction or 0.0),
        _basis_rank.get(m.basis_risk, 4),
    ))

    # First available method is recommended
    available_methods = [m for m in methods if m.available]
    recommended = available_methods[0] if available_methods else HedgeComparisonEntry(
        tier=HedgeTier.NONE,
        hedge_type="none",
        trade_spec=None,
        cost_estimate=None,
        cost_pct=None,
        delta_reduction=0.0,
        basis_risk="none",
        pros=[],
        cons=[],
        available=False,
        unavailable_reason="No hedge methods available for this instrument",
    )

    if recommended.available:
        rationale = (
            f"Recommended: {recommended.hedge_type} ({recommended.tier}) — "
            f"delta reduction {recommended.delta_reduction:.0%}, "
            f"cost ~{recommended.cost_pct:.1f}%, "
            f"basis risk {recommended.basis_risk}"
        )
    else:
        rationale = "No viable hedge available for this instrument"

    return HedgeComparison(
        ticker=ticker,
        market=market,
        current_price=current_price,
        position_value=position_value,
        shares=shares,
        regime_id=regime_id,
        methods=methods,
        recommended=recommended,
        recommendation_rationale=rationale,
    )
