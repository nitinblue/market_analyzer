"""Rank Opportunities — score and size trade proposals.

eTrading sends tickers + capital. ID returns ranked, sized, POP-estimated
trade proposals ready for execution, plus blocked trades with reasons.

Single-pass pipeline: regime detect -> rank -> batch reprice -> POP/size -> output.
entry_credit is computed ONCE by PricingService and never overwritten.
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


def _extract_strike(ts, role: str, opt_type: str, action_prefix: str) -> float | None:
    """Extract a strike from trade spec legs by role or type+action."""
    if not ts or not ts.legs:
        return None
    for leg in ts.legs:
        if hasattr(leg, 'role') and leg.role == role:
            return leg.strike
        action_str = getattr(leg.action, 'value', str(leg.action))
        if leg.option_type == opt_type and action_str.startswith(action_prefix):
            return leg.strike
    return None

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
    """Score, rank, and size trade opportunities.

    Pipeline: regime detect -> assessor rank -> batch reprice -> POP/size -> output.
    entry_credit is set ONCE by PricingService and never overwritten downstream.
    """
    timestamp = datetime.now()
    warnings: list[str] = []
    blocked: list[BlockedTrade] = []
    data_source = getattr(ma.market_data, 'provider_name', 'yfinance') if ma.market_data else "yfinance"

    # ── 1. Regime detection (unchanged) ──
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

    tradeable = [t for t, r in regimes.items() if r.tradeable]
    if not tradeable:
        return RankResponse(
            meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source=data_source, warnings=warnings + ["All tickers in R4 — no income plays"]),
            trades=[], blocked=[], regime_summary=regimes,
            tradeable_count=0, total_assessed=0,
        )

    # ── 2. Ranking from assessors (unchanged) ──
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

    # ── 3. Batch reprice all trades at once ──
    from income_desk.workflow.pricing_service import batch_reprice

    entries: list[dict] = []
    valid_ranking_entries = []

    for entry in ranking.top_trades:
        if entry.trade_spec is None:
            continue
        ts = entry.trade_spec

        # Reject degenerate legs (same strike on both sides)
        if ts.legs and len(ts.legs) >= 2:
            unique_strikes = set(leg.strike for leg in ts.legs)
            if len(unique_strikes) < 2:
                blocked.append(BlockedTrade(
                    ticker=entry.ticker, structure=str(ts.structure_type or ""),
                    reason=f"Degenerate trade: all legs at same strike ({unique_strikes})",
                    score=entry.composite_score,
                ))
                continue

        regime_id = regimes.get(
            entry.ticker,
            TickerRegime(ticker=entry.ticker, regime_id=1, regime_label="", confidence=0, tradeable=True),
        ).regime_id

        entries.append({
            "ticker": entry.ticker,
            "trade_spec": ts,
            "regime_id": regime_id,
        })
        valid_ranking_entries.append(entry)

    repriced_list = batch_reprice(entries, ma.market_data, ma.technicals)

    # ── 4. Single pass: POP -> size -> output ──
    from income_desk.trade_lifecycle import estimate_pop
    from income_desk.features.position_sizing import compute_position_size

    trades: list[TradeProposal] = []

    for entry, repriced in zip(valid_ranking_entries, repriced_list):
        ts = entry.trade_spec
        ticker = entry.ticker
        st = str(ts.structure_type or "")

        # 4a. Block if repricing failed
        if repriced.block_reason:
            blocked.append(BlockedTrade(
                ticker=ticker, structure=st,
                reason=repriced.block_reason, score=entry.composite_score,
            ))
            continue

        # 4b. Block if illiquid
        if not repriced.liquidity_ok:
            blocked.append(BlockedTrade(
                ticker=ticker, structure=st,
                reason="Illiquid strikes (wide spread or low OI)", score=entry.composite_score,
            ))
            continue

        # 4c. POP estimation — uses repriced.entry_credit (FINAL, immutable)
        pop_pct = None
        ev = None
        try:
            pop_result = estimate_pop(
                trade_spec=ts, entry_price=max(repriced.entry_credit, 0.01),
                regime_id=repriced.regime_id, atr_pct=repriced.atr_pct,
                current_price=repriced.current_price,
            )
            if pop_result:
                pop_pct = pop_result.pop_pct
                ev = pop_result.expected_value
        except Exception as e:
            warnings.append(f"{ticker}: POP estimation failed: {e} (entry={repriced.entry_credit:.4f}, regime={repriced.regime_id}, atr={repriced.atr_pct:.2f}, price={repriced.current_price:.2f}, st={st})")

        if pop_pct is None:
            blocked.append(BlockedTrade(
                ticker=ticker, structure=st,
                reason="POP estimation failed — cannot assess profitability",
                score=entry.composite_score,
            ))
            continue

        # POP floor
        if pop_pct < request.min_pop:
            blocked.append(BlockedTrade(
                ticker=ticker, structure=st,
                reason=f"POP {pop_pct:.0%} below {request.min_pop:.0%} floor",
                score=entry.composite_score,
            ))
            continue

        # 4d. Position sizing — uses repriced values
        contracts = 1
        max_risk = 0.0
        max_profit = 0.0
        try:
            lot_size = repriced.lot_size
            wing_width = repriced.wing_width or (50.0 if request.market == "India" else 5.0)
            currency = ts.currency or ("INR" if request.market == "India" else "USD")
            order_side = getattr(ts, "order_side", "credit")
            order_side_str = getattr(order_side, "value", str(order_side)) if order_side else "credit"

            if order_side_str == "debit":
                max_loss_per = repriced.entry_credit * lot_size
                max_profit_per = max((wing_width * lot_size) - max_loss_per, 0)
            else:
                max_profit_per = repriced.entry_credit * lot_size
                max_loss_per = (wing_width * lot_size) - max_profit_per

            # Use actual max loss as margin proxy for defined-risk trades.
            # SPAN margin is broker-specific — don't hardcode percentages.
            margin_per_lot = max_loss_per

            risk_per = max(max_loss_per, 1.0)

            if st not in ("equity_long", "equity_short"):
                sz = compute_position_size(
                    pop_pct=pop_pct or 0.60,
                    max_profit=max_profit_per, max_loss=max_loss_per,
                    capital=request.capital, risk_per_contract=risk_per,
                    regime_id=repriced.regime_id, wing_width=wing_width,
                    safety_factor=0.5, max_contracts=20,
                )
                contracts = sz.recommended_contracts

                max_risk_per_trade = request.capital * 0.04
                max_contracts_by_margin = max(1, int(max_risk_per_trade / margin_per_lot)) if margin_per_lot > 0 else contracts
                contracts = min(contracts, max_contracts_by_margin)

            max_risk = max_loss_per * contracts
            max_profit = max_profit_per * contracts
        except Exception as e:
            warnings.append(f"{ticker}: position sizing failed: {e}")
            blocked.append(BlockedTrade(
                ticker=ticker, structure=st,
                reason=f"Position sizing failed: {e}",
                score=entry.composite_score,
            ))
            continue

        if contracts == 0:
            blocked.append(BlockedTrade(
                ticker=ticker, structure=st,
                reason="Kelly sizing = 0 contracts",
                score=entry.composite_score,
            ))
            continue

        if len(trades) >= request.max_trades:
            break

        # 4e. Build TradeProposal
        badge = ts.strategy_badge if ts.strategy_badge else str(st)
        trades.append(TradeProposal(
            rank=len(trades) + 1,
            ticker=ticker,
            structure=st,
            direction=entry.direction or "neutral",
            strategy_badge=badge,
            composite_score=entry.composite_score,
            verdict=entry.verdict or "go",
            pop_pct=pop_pct,
            expected_value=ev,
            contracts=contracts,
            max_risk=max_risk,
            max_profit=max_profit,
            entry_credit=repriced.entry_credit,
            credit_source=repriced.credit_source,
            wing_width=repriced.wing_width,
            target_dte=ts.target_dte,
            expiry=repriced.expiry,
            current_price=repriced.current_price,
            regime_id=repriced.regime_id,
            atr_pct=repriced.atr_pct,
            lot_size=repriced.lot_size,
            currency=ts.currency or ("INR" if request.market == "India" else "USD"),
            rationale=entry.rationale or "",
            data_gaps=[g.reason for g in entry.data_gaps] if entry.data_gaps else [],
            short_put=_extract_strike(ts, "short_put", "put", "STO"),
            long_put=_extract_strike(ts, "long_put", "put", "BTO"),
            short_call=_extract_strike(ts, "short_call", "call", "STO"),
            long_call=_extract_strike(ts, "long_call", "call", "BTO"),
            net_credit_per_unit=repriced.entry_credit,
        ))

    return RankResponse(
        meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source=data_source, warnings=warnings),
        trades=trades,
        blocked=blocked,
        regime_summary=regimes,
        tradeable_count=len(tradeable),
        total_assessed=ranking.total_assessed if ranking else 0,
    )
