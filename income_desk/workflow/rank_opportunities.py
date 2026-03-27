"""Rank Opportunities — score and size trade proposals.

eTrading sends tickers + capital. ID returns ranked, sized, POP-estimated
trade proposals ready for execution, plus blocked trades with reasons.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from income_desk.workflow._types import (
    BlockedTrade, TradeProposal, TickerRegime, WorkflowMeta,
)

if TYPE_CHECKING:
    from income_desk.service.analyzer import MarketAnalyzer

logger = logging.getLogger(__name__)

# Regime labels
_REGIME_LABELS = {1: "R1 Low-Vol MR", 2: "R2 High-Vol MR", 3: "R3 Low-Vol Trend", 4: "R4 High-Vol Trend"}


class RankRequest(BaseModel):
    tickers: list[str]
    capital: float = 5_000_000
    market: str = "India"
    risk_tolerance: str = "moderate"
    iv_rank_map: dict[str, float] | None = None
    skip_intraday: bool = True
    max_trades: int = 10
    min_pop: float = 0.40


class RankResponse(BaseModel):
    meta: WorkflowMeta
    trades: list[TradeProposal]
    blocked: list[BlockedTrade]
    regime_summary: dict[str, TickerRegime]
    tradeable_count: int
    total_assessed: int


def rank_opportunities(
    request: RankRequest,
    ma: MarketAnalyzer,
) -> RankResponse:
    """Score, rank, and size trade opportunities."""
    timestamp = datetime.now()
    warnings: list[str] = []
    data_source = getattr(ma.market_data, 'provider_name', 'yfinance') if ma.market_data else "yfinance"

    # --- Regime detection ---
    regimes: dict[str, TickerRegime] = {}
    for ticker in request.tickers:
        try:
            r = ma.regime.detect(ticker)
            rid = r.regime if isinstance(r.regime, int) else r.regime.value
            regimes[ticker] = TickerRegime(
                ticker=ticker,
                regime_id=rid,
                regime_label=_REGIME_LABELS.get(rid, f"R{rid}"),
                confidence=r.confidence,
                tradeable=rid in (1, 2, 3),
            )
        except Exception as e:
            warnings.append(f"{ticker}: regime failed: {e}")
            regimes[ticker] = TickerRegime(
                ticker=ticker, regime_id=0, regime_label="Unknown",
                confidence=0.0, tradeable=False,
            )

    # Filter tradeable (R1, R2, R3)
    tradeable = [t for t, r in regimes.items() if r.tradeable]
    if not tradeable:
        return RankResponse(
            meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source=data_source, warnings=warnings + ["All tickers in R4 — no income plays"]),
            trades=[], blocked=[], regime_summary=regimes,
            tradeable_count=0, total_assessed=0,
        )

    # --- Ranking ---
    ranking = None
    try:
        ranking = ma.ranking.rank(
            tradeable,
            skip_intraday=request.skip_intraday,
            iv_rank_map=request.iv_rank_map or {},
        )
    except Exception as e:
        warnings.append(f"Ranking failed: {e}")

    if not ranking or not ranking.top_trades:
        return RankResponse(
            meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source=data_source, warnings=warnings),
            trades=[], blocked=[], regime_summary=regimes,
            tradeable_count=len(tradeable), total_assessed=0,
        )

    # --- Process ranked trades ---
    from income_desk.trade_lifecycle import estimate_pop
    from income_desk.features.position_sizing import compute_position_size

    trades: list[TradeProposal] = []
    blocked: list[BlockedTrade] = []
    seen_tickers: set[str] = set()

    for entry in ranking.top_trades:
        if len(trades) >= request.max_trades:
            break
        if entry.trade_spec is None:
            continue
        # Dedup by ticker
        if entry.ticker in seen_tickers:
            continue

        ts = entry.trade_spec
        ticker = entry.ticker
        st = ts.structure_type or ""
        regime_id = regimes.get(ticker, TickerRegime(ticker=ticker, regime_id=1, regime_label="", confidence=0, tradeable=True)).regime_id
        lot_size = ts.lot_size or 100
        currency = ts.currency or ("INR" if request.market == "India" else "USD")

        # Get technicals for POP
        try:
            tech = ma.technicals.snapshot(ticker)
            atr_pct = tech.atr_pct if tech else 1.0
            current_price = tech.current_price if tech else 100.0
        except Exception:
            atr_pct = 1.0
            current_price = 100.0

        # Estimate entry credit
        entry_credit = 0.0
        if ts.max_entry_price:
            entry_credit = ts.max_entry_price
        elif ts.wing_width_points:
            entry_credit = ts.wing_width_points * 0.28  # rough estimate

        # POP estimation
        pop_pct = None
        ev = None
        try:
            pop_result = estimate_pop(
                trade_spec=ts, entry_price=max(entry_credit, 0.01),
                regime_id=regime_id, atr_pct=atr_pct,
                current_price=current_price,
            )
            if pop_result:
                pop_pct = pop_result.pop_pct
                ev = pop_result.expected_value
        except Exception:
            pass

        # POP floor
        if pop_pct is not None and pop_pct < request.min_pop:
            blocked.append(BlockedTrade(
                ticker=ticker, structure=str(st),
                reason=f"POP {pop_pct:.0%} below {request.min_pop:.0%} floor",
                score=entry.composite_score,
            ))
            continue

        # Position sizing
        contracts = 1
        max_risk = 0.0
        max_profit = 0.0
        try:
            wing_width = ts.wing_width_points or 5.0
            max_profit_per = entry_credit * lot_size
            max_loss_per = (wing_width * lot_size) - max_profit_per
            risk_per = max(max_loss_per, 1.0)

            if st not in ("equity_long", "equity_short"):
                sz = compute_position_size(
                    pop_pct=pop_pct or 0.60,
                    max_profit=max_profit_per, max_loss=max_loss_per,
                    capital=request.capital, risk_per_contract=risk_per,
                    regime_id=regime_id, wing_width=wing_width,
                    safety_factor=0.5, max_contracts=20,
                )
                contracts = sz.recommended_contracts

            max_risk = risk_per * contracts
            max_profit = max_profit_per * contracts
        except Exception:
            pass

        if contracts == 0:
            blocked.append(BlockedTrade(
                ticker=ticker, structure=str(st),
                reason="Kelly sizing = 0 contracts",
                score=entry.composite_score,
            ))
            continue

        seen_tickers.add(ticker)

        badge = ts.strategy_badge if ts.strategy_badge else str(st)
        trades.append(TradeProposal(
            rank=len(trades) + 1,
            ticker=ticker,
            structure=str(st),
            direction=entry.direction or "neutral",
            strategy_badge=badge,
            composite_score=entry.composite_score,
            verdict=entry.verdict or "go",
            pop_pct=pop_pct,
            expected_value=ev,
            contracts=contracts,
            max_risk=max_risk,
            max_profit=max_profit,
            entry_credit=entry_credit,
            wing_width=ts.wing_width_points,
            target_dte=ts.target_dte,
            lot_size=lot_size,
            currency=currency,
            rationale=entry.rationale or "",
            data_gaps=[g.reason for g in entry.data_gaps] if entry.data_gaps else [],
        ))

    return RankResponse(
        meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source=data_source, warnings=warnings),
        trades=trades,
        blocked=blocked,
        regime_summary=regimes,
        tradeable_count=len(tradeable),
        total_assessed=ranking.total_assessed if ranking else 0,
    )
