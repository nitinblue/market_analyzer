"""Hedge strategy resolver — the central decision engine.

Given a ticker, position details, and market context, resolves which
hedge tier (direct/futures/proxy) to use and returns a complete HedgeApproach
with rationale and alternatives.

The resolver DECIDES — the caller can override by calling tier-specific
builders directly, but the resolver's recommendation is the default.
"""

from __future__ import annotations

from income_desk.hedging.models import (
    HedgeAlternative,
    HedgeApproach,
    HedgeGoal,
    HedgeTier,
)
from income_desk.hedging.universe import (
    classify_hedge_tier,
    get_proxy_instrument,
    get_sector_beta,
)
from income_desk.registry import MarketRegistry


def resolve_hedge_strategy(
    ticker: str,
    position_value: float,
    shares: int,
    current_price: float,
    regime_id: int,
    market: str = "US",
    account_nlv: float | None = None,
    max_hedge_cost_pct: float = 3.0,
    registry: MarketRegistry | None = None,
) -> HedgeApproach:
    """Resolve which hedge strategy to use for a position.

    Decision tree:
    1. Classify instrument via registry → get base tier
    2. Check affordability — can the account handle 1 lot?
    3. If DIRECT + affordable → recommend DIRECT
    4. If DIRECT + too expensive → try FUTURES_SYNTHETIC (lower capital)
    5. If FUTURES_SYNTHETIC → check basis cost, lot affordability
    6. If nothing else → PROXY_INDEX
    7. Apply regime adjustment: R4 → upgrade urgency, R1 → may skip hedge entirely

    Args:
        ticker: Instrument ticker.
        position_value: Total value of the position to hedge (local currency).
        shares: Number of shares/units held.
        current_price: Current price per share.
        regime_id: Current regime (1-4).
        market: "US" or "INDIA".
        account_nlv: Account net liquidating value (for affordability check).
        max_hedge_cost_pct: Maximum acceptable hedge cost as % of position value.
        registry: MarketRegistry instance.

    Returns:
        HedgeApproach with recommended tier, rationale, and alternatives.
    """
    reg = registry or MarketRegistry()
    market = market.upper()

    # Step 1: classify base tier
    base_tier = classify_hedge_tier(ticker, market, reg)

    # Step 2: get instrument details
    try:
        inst = reg.get_instrument(ticker, market)
        lot_size = inst.lot_size
        has_liquid_options = inst.options_liquidity in ("high", "medium")
        has_futures = market == "INDIA"  # All India F&O stocks have stock futures
        # US equity doesn't have single-stock futures (for practical purposes)
    except KeyError:
        lot_size = 100 if market == "US" else 0
        has_liquid_options = market == "US"  # Default: US has options, India unknown
        has_futures = False

    # Step 3: check lot affordability
    lot_value = lot_size * current_price if lot_size > 0 else 0
    lot_affordable = True
    if account_nlv and lot_value > 0:
        # Hedge lot shouldn't be more than 20% of account
        lot_affordable = lot_value < (account_nlv * 0.20)

    # Step 4: build alternatives list
    alternatives: list[HedgeAlternative] = []

    # Step 5: resolve recommendation
    recommended_tier = base_tier
    rationale_parts: list[str] = []
    basis_risk = "none"
    estimated_cost_pct: float | None = None

    if base_tier == HedgeTier.DIRECT:
        rationale_parts.append(f"{ticker} has tradeable options")
        if not lot_affordable:
            # Lot too expensive — try downgrading to futures (smaller margin)
            if has_futures:
                recommended_tier = HedgeTier.FUTURES_SYNTHETIC
                rationale_parts.append(
                    f"but option lot ({lot_size} x {current_price:.0f} = {lot_value:,.0f}) "
                    f"exceeds 20% of account — using futures instead"
                )
                basis_risk = "low"
                alternatives.append(HedgeAlternative(
                    tier=HedgeTier.DIRECT,
                    reason_not_chosen=f"Lot value {lot_value:,.0f} too large for account size",
                    estimated_cost_pct=None,
                ))
            else:
                rationale_parts.append(
                    f"lot is large ({lot_value:,.0f}) but only option available"
                )
                # Still add proxy as a lower-cost alternative
                alternatives.append(HedgeAlternative(
                    tier=HedgeTier.PROXY_INDEX,
                    reason_not_chosen="Proxy has basis risk; direct hedge preferred despite cost",
                    estimated_cost_pct=_estimate_proxy_cost(regime_id),
                ))
        else:
            # Regime-based cost estimate
            estimated_cost_pct = _estimate_direct_cost(regime_id)
            rationale_parts.append(
                f"estimated cost ~{estimated_cost_pct:.1f}% of position value"
            )

            # Add alternatives for comparison
            if has_futures:
                alternatives.append(HedgeAlternative(
                    tier=HedgeTier.FUTURES_SYNTHETIC,
                    reason_not_chosen="Direct options available and preferred",
                    estimated_cost_pct=_estimate_futures_cost(regime_id),
                ))
            alternatives.append(HedgeAlternative(
                tier=HedgeTier.PROXY_INDEX,
                reason_not_chosen="Direct hedge has zero basis risk",
                estimated_cost_pct=_estimate_proxy_cost(regime_id),
            ))

    elif base_tier == HedgeTier.FUTURES_SYNTHETIC:
        rationale_parts.append(
            f"{ticker} options are illiquid — using stock futures for hedge"
        )
        basis_risk = "low"
        estimated_cost_pct = _estimate_futures_cost(regime_id)
        alternatives.append(HedgeAlternative(
            tier=HedgeTier.DIRECT,
            reason_not_chosen="Options are too illiquid for reliable fills",
            estimated_cost_pct=None,
        ))
        alternatives.append(HedgeAlternative(
            tier=HedgeTier.PROXY_INDEX,
            reason_not_chosen="Same-ticker futures have lower basis risk",
            estimated_cost_pct=_estimate_proxy_cost(regime_id),
        ))

    elif base_tier == HedgeTier.PROXY_INDEX:
        proxy = get_proxy_instrument(ticker, market, reg)
        beta = get_sector_beta(ticker, proxy, market)
        rationale_parts.append(
            f"{ticker} has no F&O — using {proxy} as proxy (sector beta ~{beta:.2f})"
        )
        basis_risk = "high"
        estimated_cost_pct = _estimate_proxy_cost(regime_id)
        # No better alternatives — this is the only option
    else:
        rationale_parts.append(f"No hedge available for {ticker}")

    # Step 6: regime context
    regime_context = _regime_hedge_context(regime_id)
    rationale_parts.append(regime_context)

    goal = HedgeGoal.DOWNSIDE  # Default — most hedges protect long positions

    return HedgeApproach(
        ticker=ticker,
        market=market,
        recommended_tier=recommended_tier,
        goal=goal,
        rationale=". ".join(rationale_parts),
        alternatives=alternatives,
        estimated_cost_pct=estimated_cost_pct,
        basis_risk=basis_risk,
        has_liquid_options=has_liquid_options,
        has_futures=has_futures,
        lot_size=lot_size,
        lot_size_affordable=lot_affordable,
    )


def _estimate_direct_cost(regime_id: int) -> float:
    """Rough hedge cost % by regime (protective put)."""
    # R1: cheap OTM puts, low vol → ~0.5%
    # R2: high IV = expensive puts → ~2.0% (but collar can offset)
    # R3: moderate → ~1.0%
    # R4: very expensive → ~3.0%
    return {1: 0.5, 2: 2.0, 3: 1.0, 4: 3.0}.get(regime_id, 1.5)


def _estimate_futures_cost(regime_id: int) -> float:
    """Rough futures hedge cost % (basis + margin cost)."""
    # Futures cost is basis (contango/backwardation) + margin opportunity cost
    return {1: 0.3, 2: 0.8, 3: 0.5, 4: 1.0}.get(regime_id, 0.5)


def _estimate_proxy_cost(regime_id: int) -> float:
    """Rough proxy hedge cost % (basis risk premium + option cost)."""
    # Proxy adds basis risk → slightly more expensive
    return {1: 0.8, 2: 2.5, 3: 1.5, 4: 3.5}.get(regime_id, 2.0)


def _regime_hedge_context(regime_id: int) -> str:
    """Regime-specific hedge rationale."""
    return {
        1: "R1 low-vol MR — hedge is optional, cheap OTM if desired",
        2: "R2 high-vol MR — hedge recommended, high IV makes collars attractive",
        3: "R3 low-vol trending — hedge if trend is against position",
        4: "R4 high-vol trending — hedge IMMEDIATELY, capital preservation priority",
    }.get(regime_id, f"R{regime_id} — unknown regime, hedge conservatively")
