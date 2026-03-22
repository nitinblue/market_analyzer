"""Portfolio-level hedge orchestrator.

Master function: takes all positions as dicts → resolves strategy per position
→ builds TradeSpecs → aggregates into a single PortfolioHedgeAnalysis.

Positions are plain dicts for ease of CSV import:
    {"ticker": "RELIANCE", "shares": 250, "value": 625000, "current_price": 2500}

Optional keys: "delta" (default 1.0 for long equity), "atr".
"""

from __future__ import annotations

from income_desk.hedging.direct import build_protective_put
from income_desk.hedging.futures_hedge import build_futures_hedge
from income_desk.hedging.models import (
    HedgeTier,
    PortfolioHedgeAnalysis,
    PositionHedge,
)
from income_desk.hedging.proxy import build_index_hedge
from income_desk.hedging.resolver import resolve_hedge_strategy
from income_desk.hedging.universe import get_proxy_instrument, get_sector_beta
from income_desk.models.opportunity import TradeSpec
from income_desk.registry import MarketRegistry


def analyze_portfolio_hedge(
    positions: list[dict],
    account_nlv: float,
    regime: int | dict[str, int] = 2,
    target_hedge_pct: float = 0.80,
    max_cost_pct: float = 3.0,
    market: str = "US",
    atr_by_ticker: dict[str, float] | None = None,
    futures_prices: dict[str, float] | None = None,
    index_price: float | None = None,
    registry: MarketRegistry | None = None,
) -> PortfolioHedgeAnalysis:
    """Analyze and recommend hedges for an entire portfolio.

    Each position dict must have: ticker, shares (int), value (float), current_price (float).
    Optional keys: delta (float, default 1.0), atr (float).

    For each position:
    1. Resolve hedge strategy (resolver decides tier)
    2. Build the recommended TradeSpec using tier-specific builder
    3. Aggregate all hedges, check budget

    If total cost exceeds max_cost_pct × portfolio_value, cheaper positions are
    prioritized (positions sorted by value descending; cheapest hedge tier wins).

    Args:
        positions: List of position dicts with ticker/shares/value/current_price.
        account_nlv: Net liquidating value of the account.
        regime: Regime ID (1-4) — either a single int (applied to all) or
                dict mapping ticker → regime_id.
        target_hedge_pct: Target fraction of portfolio to hedge (0-1).
        max_cost_pct: Maximum total hedge cost as % of portfolio value.
        market: "US" or "INDIA".
        atr_by_ticker: ATR in price units per ticker (estimated from price if absent).
        futures_prices: Futures prices per ticker (for Tier 2 hedges).
        index_price: Index price for proxy hedges.
        registry: MarketRegistry instance.

    Returns:
        PortfolioHedgeAnalysis with per-position hedges and aggregated TradeSpecs.
    """
    reg = registry or MarketRegistry()
    market = market.upper()
    atr_map = atr_by_ticker or {}
    futures_map = futures_prices or {}

    # Normalise regime to per-ticker dict
    if isinstance(regime, int):
        regime_map: dict[str, int] = {}
        _default_regime = regime
    else:
        regime_map = dict(regime)
        _default_regime = 2

    position_hedges: list[PositionHedge] = []
    all_trade_specs: list[TradeSpec] = []
    total_cost = 0.0
    tier_counts: dict[str, int] = {"direct": 0, "futures_synthetic": 0, "proxy_index": 0, "none": 0}
    tier_values: dict[str, float] = {"direct": 0.0, "futures_synthetic": 0.0, "proxy_index": 0.0, "none": 0.0}
    total_position_value = 0.0
    portfolio_delta_before = 0.0
    portfolio_delta_after = 0.0
    alerts: list[str] = []

    # Sort positions by value descending (hedge largest first)
    sorted_positions = sorted(positions, key=lambda p: float(p.get("value", 0)), reverse=True)

    hedged_value = 0.0
    total_value_for_target = sum(float(p.get("value", 0)) for p in sorted_positions)
    max_hedgeable_value = total_value_for_target * target_hedge_pct

    for pos in sorted_positions:
        ticker = pos.get("ticker", "UNKNOWN")
        pos_value = float(pos.get("value", 0))
        current_price = float(pos.get("current_price", 0))
        shares = int(pos.get("shares", 0))
        pos_delta = float(pos.get("delta", 1.0))  # Default 1.0 for long equity

        total_position_value += pos_value
        portfolio_delta_before += pos_delta

        # Cannot hedge without price
        if current_price <= 0:
            position_hedges.append(PositionHedge(
                ticker=ticker,
                position_value=pos_value,
                shares=shares,
                tier=HedgeTier.NONE,
                hedge_type=None,
                trade_spec=None,
                cost_estimate=None,
                delta_before=pos_delta,
                delta_after=pos_delta,
                rationale="Cannot hedge: no valid price data",
            ))
            tier_counts["none"] += 1
            tier_values["none"] += pos_value
            portfolio_delta_after += pos_delta
            continue

        # Estimate shares from value if not provided
        if shares <= 0 and pos_value > 0:
            shares = max(1, int(pos_value / current_price))

        regime_id = regime_map.get(ticker, _default_regime)
        atr = atr_map.get(ticker, pos.get("atr", current_price * 0.015))  # Default: 1.5% of price

        # Skip if we've already hedged enough
        if hedged_value >= max_hedgeable_value:
            position_hedges.append(PositionHedge(
                ticker=ticker,
                position_value=pos_value,
                shares=shares,
                tier=HedgeTier.NONE,
                hedge_type=None,
                trade_spec=None,
                cost_estimate=None,
                delta_before=pos_delta,
                delta_after=pos_delta,
                rationale=f"Skipped: target hedge {target_hedge_pct:.0%} already reached",
            ))
            tier_counts["none"] += 1
            tier_values["none"] += pos_value
            portfolio_delta_after += pos_delta
            continue

        # Resolve strategy
        approach = resolve_hedge_strategy(
            ticker=ticker,
            position_value=pos_value,
            shares=shares,
            current_price=current_price,
            regime_id=regime_id,
            market=market,
            account_nlv=account_nlv,
            registry=reg,
        )

        # Build TradeSpec based on recommended tier
        trade_spec: TradeSpec | None = None
        hedge_type: str | None = None
        cost_estimate: float | None = None
        delta_reduction = 0.0

        if approach.recommended_tier == HedgeTier.DIRECT:
            try:
                result = build_protective_put(
                    ticker, shares, current_price, regime_id, atr, 30, market, reg,
                )
                trade_spec = result.trade_spec
                hedge_type = result.hedge_type
                cost_estimate = result.cost_estimate
                delta_reduction = result.delta_reduction
            except Exception as e:
                alerts.append(f"{ticker}: direct hedge failed — {e}")

        elif approach.recommended_tier == HedgeTier.FUTURES_SYNTHETIC:
            try:
                fut_price = futures_map.get(ticker)
                result = build_futures_hedge(
                    ticker, shares, current_price, fut_price, 30, 1.0, market, reg,
                )
                trade_spec = result.trade_spec
                hedge_type = result.hedge_type
                cost_estimate = result.cost_estimate
                delta_reduction = result.delta_reduction
            except Exception as e:
                alerts.append(f"{ticker}: futures hedge failed — {e}")

        elif approach.recommended_tier == HedgeTier.PROXY_INDEX:
            if index_price is not None:
                try:
                    proxy = get_proxy_instrument(ticker, market, reg)
                    beta = get_sector_beta(ticker, proxy, market)
                    result = build_index_hedge(
                        pos_value, beta, proxy, index_price, regime_id, 30, market, 1.0, reg,
                    )
                    trade_spec = result.trade_spec
                    hedge_type = result.hedge_type
                    cost_estimate = result.cost_estimate
                    delta_reduction = result.delta_reduction
                except Exception as e:
                    alerts.append(f"{ticker}: proxy hedge failed — {e}")
            else:
                alerts.append(f"{ticker}: proxy hedge skipped — no index price provided")

        # Record tier
        tier_str = approach.recommended_tier.value
        tier_counts[tier_str] = tier_counts.get(tier_str, 0) + 1
        tier_values[tier_str] = tier_values.get(tier_str, 0.0) + pos_value

        delta_after = pos_delta * (1.0 - delta_reduction)
        portfolio_delta_after += delta_after

        if trade_spec is not None:
            all_trade_specs.append(trade_spec)
            hedged_value += pos_value
            if cost_estimate:
                total_cost += cost_estimate

        position_hedges.append(PositionHedge(
            ticker=ticker,
            position_value=pos_value,
            shares=shares,
            tier=approach.recommended_tier,
            hedge_type=hedge_type,
            trade_spec=trade_spec,
            cost_estimate=cost_estimate,
            delta_before=pos_delta,
            delta_after=round(delta_after, 4),
            rationale=approach.rationale,
        ))

    # Aggregate metrics
    hedge_cost_pct = (total_cost / total_position_value * 100) if total_position_value > 0 else 0.0
    coverage_pct = (hedged_value / total_position_value * 100) if total_position_value > 0 else 0.0

    # Budget alert
    if hedge_cost_pct > max_cost_pct and total_cost > 0:
        alerts.append(
            f"Total hedge cost {hedge_cost_pct:.1f}% exceeds budget {max_cost_pct:.1f}% — "
            f"consider switching to cheaper hedges (collars, futures)"
        )

    # Unhedged positions alert
    unhedged_count = tier_counts.get("none", 0)
    if unhedged_count > 0:
        alerts.append(f"{unhedged_count} position(s) have no hedge (skipped or unavailable)")

    summary = (
        f"{len(all_trade_specs)} hedge(s) across {len(position_hedges)} position(s), "
        f"{coverage_pct:.0f}% coverage, "
        f"total cost {hedge_cost_pct:.1f}% of portfolio"
    )

    return PortfolioHedgeAnalysis(
        market=market,
        account_nlv=account_nlv,
        total_positions=len(positions),
        total_position_value=round(total_position_value, 2),
        tier_counts=tier_counts,
        tier_values={k: round(v, 2) for k, v in tier_values.items()},
        position_hedges=position_hedges,
        total_hedge_cost=round(total_cost, 2),
        hedge_cost_pct=round(hedge_cost_pct, 2),
        portfolio_delta_before=round(portfolio_delta_before, 4),
        portfolio_delta_after=round(portfolio_delta_after, 4),
        portfolio_beta_before=None,  # Would require historical returns
        portfolio_beta_after=None,
        trade_specs=all_trade_specs,
        coverage_pct=round(coverage_pct, 1),
        target_hedge_pct=target_hedge_pct * 100,
        summary=summary,
        alerts=alerts,
    )
