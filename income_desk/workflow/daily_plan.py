"""Daily Plan — full trading plan orchestrator.

Composes scan → rank → validate → size into a single call.
"What should I trade today?" — one function, one answer.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from income_desk.workflow._types import (
    BlockedTrade,
    TradeProposal,
    TickerRegime,
    WorkflowMeta,
)
from income_desk.workflow.rank_opportunities import RankRequest, rank_opportunities
from income_desk.workflow.portfolio_health import HealthRequest, check_portfolio_health

if TYPE_CHECKING:
    from income_desk.service.analyzer import MarketAnalyzer


class DailyPlanRequest(BaseModel):
    """What eTrading sends to get a full trading plan."""
    tickers: list[str]
    capital: float = 5_000_000
    market: str = "India"
    risk_tolerance: str = "moderate"
    total_risk_deployed: float = 0.0  # existing risk in portfolio
    max_new_trades: int = 5
    iv_rank_map: dict[str, float] | None = None


class DailyPlanResponse(BaseModel):
    """Complete trading plan for the day."""
    meta: WorkflowMeta
    # Health check
    sentinel_signal: str
    is_safe_to_trade: bool
    # Regime
    regimes: dict[str, TickerRegime]
    tradeable_tickers: list[str]
    # Trades
    proposed_trades: list[TradeProposal]
    blocked_trades: list[BlockedTrade]
    # Budget
    capital: float
    risk_deployed: float
    risk_budget_remaining: float
    # Summary
    summary: str


def generate_daily_plan(
    request: DailyPlanRequest,
    ma: MarketAnalyzer,
) -> DailyPlanResponse:
    """Generate a complete daily trading plan.

    Sequence:
    1. Portfolio health check (sentinel, regime distribution)
    2. Rank opportunities (regime → rank → POP → size)
    3. Combine into actionable plan
    """
    timestamp = datetime.now()
    warnings: list[str] = []
    data_source = getattr(ma.market_data, "provider_name", "yfinance") if ma.market_data else "yfinance"

    # --- Step 1: Health check ---
    health = check_portfolio_health(
        HealthRequest(
            tickers=request.tickers,
            capital=request.capital,
            total_risk_deployed=request.total_risk_deployed,
            market=request.market,
        ),
        ma,
    )
    warnings.extend(health.meta.warnings)

    if not health.is_safe_to_trade:
        return DailyPlanResponse(
            meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source=data_source, warnings=warnings),
            sentinel_signal=health.sentinel_signal,
            is_safe_to_trade=False,
            regimes=health.regimes,
            tradeable_tickers=[],
            proposed_trades=[],
            blocked_trades=[],
            capital=request.capital,
            risk_deployed=request.total_risk_deployed,
            risk_budget_remaining=health.risk_budget_remaining,
            summary=f"SENTINEL {health.sentinel_signal} — trading halted. {len(health.regimes)} tickers scanned.",
        )

    # --- Step 2: Rank opportunities ---
    ranked = rank_opportunities(
        RankRequest(
            tickers=request.tickers,
            capital=request.capital,
            market=request.market,
            risk_tolerance=request.risk_tolerance,
            iv_rank_map=request.iv_rank_map,
            skip_intraday=True,
            max_trades=request.max_new_trades,
        ),
        ma,
    )
    warnings.extend(ranked.meta.warnings)

    tradeable = [t for t, r in ranked.regime_summary.items() if r.tradeable]

    # --- Step 3: Build plan ---
    total_new_risk = sum(t.max_risk or 0 for t in ranked.trades)
    total_risk = request.total_risk_deployed + total_new_risk
    budget_remaining = request.capital * 0.30 - total_risk

    n_trades = len(ranked.trades)
    n_blocked = len(ranked.blocked)
    currency = "INR" if request.market == "India" else "USD"

    summary_parts = [
        f"Sentinel: {health.sentinel_signal}",
        f"{len(tradeable)}/{len(request.tickers)} tradeable",
        f"{n_trades} trade(s) proposed",
    ]
    if n_blocked:
        summary_parts.append(f"{n_blocked} blocked")
    summary_parts.append(
        f"Risk: {currency} {total_risk:,.0f} / {currency} {request.capital * 0.30:,.0f} budget"
    )

    return DailyPlanResponse(
        meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source=data_source, warnings=warnings),
        sentinel_signal=health.sentinel_signal,
        is_safe_to_trade=True,
        regimes={**health.regimes, **ranked.regime_summary},
        tradeable_tickers=tradeable,
        proposed_trades=ranked.trades,
        blocked_trades=ranked.blocked,
        capital=request.capital,
        risk_deployed=total_risk,
        risk_budget_remaining=budget_remaining,
        summary=" | ".join(summary_parts),
    )
