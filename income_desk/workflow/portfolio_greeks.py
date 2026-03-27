"""Portfolio Greeks — aggregate risk factors by underlying.

eTrading sends all open positions. ID aggregates delta, gamma, theta,
vega per underlying. Answers: "What is my combined delta exposure on MSFT?"
"""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel

from income_desk.workflow._types import WorkflowMeta


class PositionLeg(BaseModel):
    """One leg of an options position with Greeks."""
    ticker: str           # underlying: MSFT, NIFTY, etc.
    option_type: str      # "call", "put", "stock"
    strike: float = 0.0
    expiration: str = ""  # ISO date
    contracts: int = 1
    lot_size: int = 100
    action: str = "long"  # "long" or "short"
    # Per-contract Greeks (from broker)
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    implied_volatility: float = 0.0
    market_value: float = 0.0


class PortfolioGreeksRequest(BaseModel):
    """All positions in the portfolio."""
    legs: list[PositionLeg]
    market: str = "India"


class UnderlyingRisk(BaseModel):
    """Aggregated risk for one underlying."""
    ticker: str
    position_count: int       # number of legs
    net_delta: float          # sum of (delta * contracts * lot_size * sign)
    net_gamma: float
    net_theta: float          # daily theta decay in currency
    net_vega: float           # exposure to 1% IV move
    weighted_iv: float        # position-weighted average IV
    total_market_value: float
    delta_dollars: float      # net_delta * underlying_price (if available)
    is_delta_neutral: bool    # abs(net_delta) < threshold
    risk_summary: str         # "short 125 delta, long 8.2 vega"


class PortfolioGreeksResponse(BaseModel):
    """Aggregated Greeks by underlying + portfolio totals."""
    meta: WorkflowMeta
    by_underlying: dict[str, UnderlyingRisk]
    # Portfolio totals
    portfolio_delta: float
    portfolio_gamma: float
    portfolio_theta: float
    portfolio_vega: float
    portfolio_market_value: float
    largest_delta_exposure: str   # "NIFTY: -250 delta"
    largest_vega_exposure: str    # "BANKNIFTY: +15.3 vega"
    risk_warnings: list[str]


def aggregate_portfolio_greeks(
    request: PortfolioGreeksRequest,
    ma: "MarketAnalyzer | None" = None,
) -> PortfolioGreeksResponse:
    """Aggregate Greeks by underlying across all positions.

    For each underlying:
    - Net delta = sum of (delta * contracts * lot_size * direction_sign)
    - Net gamma = sum of (gamma * contracts * lot_size * direction_sign)
    - Net theta = sum of (theta * contracts * lot_size * direction_sign)
    - Net vega = sum of (vega * contracts * lot_size * direction_sign)

    direction_sign: +1 for long, -1 for short
    """
    from collections import defaultdict

    timestamp = datetime.now()
    warnings: list[str] = []

    # Group legs by underlying
    by_ticker: dict[str, list[PositionLeg]] = defaultdict(list)
    for leg in request.legs:
        by_ticker[leg.ticker.upper()].append(leg)

    # Aggregate per underlying
    underlying_risks: dict[str, UnderlyingRisk] = {}

    for ticker, legs in by_ticker.items():
        net_delta = 0.0
        net_gamma = 0.0
        net_theta = 0.0
        net_vega = 0.0
        total_iv_weight = 0.0
        total_weight = 0.0
        total_mv = 0.0

        for leg in legs:
            sign = 1.0 if leg.action == "long" else -1.0
            multiplier = leg.contracts * leg.lot_size * sign

            net_delta += leg.delta * multiplier
            net_gamma += leg.gamma * multiplier
            net_theta += leg.theta * multiplier
            net_vega += leg.vega * multiplier
            total_mv += leg.market_value * leg.contracts * (1 if leg.action == "long" else -1)

            # IV weighting by absolute vega exposure
            abs_vega = abs(leg.vega * leg.contracts * leg.lot_size)
            if abs_vega > 0 and leg.implied_volatility > 0:
                total_iv_weight += leg.implied_volatility * abs_vega
                total_weight += abs_vega

        weighted_iv = total_iv_weight / total_weight if total_weight > 0 else 0.0

        # Delta dollars (need underlying price)
        delta_dollars = 0.0
        if ma is not None and ma.market_data is not None:
            try:
                price = ma.market_data.get_underlying_price(ticker)
                if price:
                    delta_dollars = net_delta * price
            except Exception:
                pass

        is_neutral = abs(net_delta) < (10 * legs[0].lot_size)  # less than 10 lots equivalent

        # Build summary
        parts = []
        if abs(net_delta) > 0.01:
            direction = "short" if net_delta < 0 else "long"
            parts.append(f"{direction} {abs(net_delta):.0f} delta")
        if abs(net_vega) > 0.01:
            direction = "short" if net_vega < 0 else "long"
            parts.append(f"{direction} {abs(net_vega):.1f} vega")
        if abs(net_theta) > 0.01:
            parts.append(f"theta {net_theta:+.1f}/day")

        underlying_risks[ticker] = UnderlyingRisk(
            ticker=ticker,
            position_count=len(legs),
            net_delta=round(net_delta, 2),
            net_gamma=round(net_gamma, 4),
            net_theta=round(net_theta, 2),
            net_vega=round(net_vega, 2),
            weighted_iv=round(weighted_iv, 4),
            total_market_value=round(total_mv, 2),
            delta_dollars=round(delta_dollars, 2),
            is_delta_neutral=is_neutral,
            risk_summary=" | ".join(parts) if parts else "flat",
        )

    # Portfolio totals
    port_delta = sum(r.net_delta for r in underlying_risks.values())
    port_gamma = sum(r.net_gamma for r in underlying_risks.values())
    port_theta = sum(r.net_theta for r in underlying_risks.values())
    port_vega = sum(r.net_vega for r in underlying_risks.values())
    port_mv = sum(r.total_market_value for r in underlying_risks.values())

    # Find largest exposures
    sorted_by_delta = sorted(underlying_risks.values(), key=lambda r: abs(r.net_delta), reverse=True)
    sorted_by_vega = sorted(underlying_risks.values(), key=lambda r: abs(r.net_vega), reverse=True)

    largest_delta = f"{sorted_by_delta[0].ticker}: {sorted_by_delta[0].net_delta:+.0f} delta" if sorted_by_delta else "none"
    largest_vega = f"{sorted_by_vega[0].ticker}: {sorted_by_vega[0].net_vega:+.1f} vega" if sorted_by_vega else "none"

    # Risk warnings
    risk_warnings = []
    for ticker, risk in underlying_risks.items():
        if abs(risk.net_delta) > 500:
            risk_warnings.append(f"{ticker}: large delta exposure ({risk.net_delta:+.0f})")
        if abs(risk.net_vega) > 50:
            risk_warnings.append(f"{ticker}: large vega exposure ({risk.net_vega:+.1f})")
    if abs(port_delta) > 1000:
        risk_warnings.append(f"Portfolio net delta {port_delta:+.0f} — consider hedging")

    return PortfolioGreeksResponse(
        meta=WorkflowMeta(
            as_of=timestamp,
            market=request.market,
            data_source="broker_greeks",
            warnings=warnings,
        ),
        by_underlying=underlying_risks,
        portfolio_delta=round(port_delta, 2),
        portfolio_gamma=round(port_gamma, 4),
        portfolio_theta=round(port_theta, 2),
        portfolio_vega=round(port_vega, 2),
        portfolio_market_value=round(port_mv, 2),
        largest_delta_exposure=largest_delta,
        largest_vega_exposure=largest_vega,
        risk_warnings=risk_warnings,
    )
