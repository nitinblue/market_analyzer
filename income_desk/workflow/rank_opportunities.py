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
        except Exception as e:
            warnings.append(f"{ticker}: technicals failed: {e}")
            # Try broker price before falling back
            current_price = 100.0
            if ma.market_data is not None:
                try:
                    bp = ma.market_data.get_underlying_price(ticker)
                    if bp and bp > 0:
                        current_price = bp
                except Exception:
                    pass
            atr_pct = 1.0

        # Compute wing width from legs if trade_spec reports 0
        wing_from_spec = ts.wing_width_points or 0.0
        if wing_from_spec == 0 and ts.legs and len(ts.legs) >= 2:
            strikes = sorted(set(leg.strike for leg in ts.legs))
            if len(strikes) >= 2:
                wing_from_spec = strikes[1] - strikes[0]

        # Reject trades with degenerate legs (same strike on both sides)
        if ts.legs and len(ts.legs) >= 2:
            unique_strikes = set(leg.strike for leg in ts.legs)
            if len(unique_strikes) < 2:
                blocked.append(BlockedTrade(
                    ticker=ticker, structure=str(st),
                    reason=f"Degenerate trade: all legs at same strike ({unique_strikes})",
                    score=entry.composite_score,
                ))
                continue

        # Estimate entry credit
        entry_credit = 0.0
        if ts.max_entry_price:
            entry_credit = ts.max_entry_price
        elif wing_from_spec > 0:
            entry_credit = wing_from_spec * 0.28  # rough estimate

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
        except Exception as e:
            warnings.append(f"{ticker}: POP estimation failed: {e} (entry={entry_credit:.4f}, regime={regime_id}, atr={atr_pct:.2f}, price={current_price:.2f}, st={st})")

        # If POP couldn't be estimated, block the trade (no guessing)
        if pop_pct is None:
            blocked.append(BlockedTrade(
                ticker=ticker, structure=str(st),
                reason="POP estimation failed — cannot assess profitability",
                score=entry.composite_score,
            ))
            continue

        # POP floor
        if pop_pct is not None and pop_pct < request.min_pop:
            blocked.append(BlockedTrade(
                ticker=ticker, structure=str(st),
                reason=f"POP {pop_pct:.0%} below {request.min_pop:.0%} floor",
                score=entry.composite_score,
            ))
            continue

        # Position sizing — use realistic margin, not just wing width
        contracts = 1
        max_risk = 0.0
        max_profit = 0.0
        try:
            from income_desk import MarketRegistry
            _reg = MarketRegistry()

            wing_width = wing_from_spec or ts.wing_width_points or 5.0
            order_side = getattr(ts, "order_side", "credit")
            order_side_str = getattr(order_side, "value", str(order_side)) if order_side else "credit"

            if order_side_str == "debit":
                # Debit spread: we pay entry_credit, max profit = wing - debit
                max_loss_per = entry_credit * lot_size  # what we pay
                max_profit_per = max((wing_width * lot_size) - max_loss_per, 0)
            else:
                # Credit spread: we receive entry_credit, max loss = wing - credit
                max_profit_per = entry_credit * lot_size
                max_loss_per = (wing_width * lot_size) - max_profit_per

            # India margin: SPAN + exposure is much higher than theoretical max loss.
            # Real SPAN margin for short options = ~15-20% of underlying notional.
            # For iron condors (defined risk), margin is lower but still significant.
            if request.market == "India":
                # Defined-risk (IC/IFly): ~8-12% of notional per lot
                # Undefined-risk (straddle/strangle): ~15-20% of notional per lot
                is_defined = st in ("iron_condor", "iron_butterfly", "credit_spread", "debit_spread")
                margin_pct = 0.10 if is_defined else 0.18
                margin_per_lot = current_price * lot_size * margin_pct
            else:
                # US: max loss is a reasonable proxy for margin (Reg-T)
                margin_per_lot = max_loss_per

            # Two constraints for India:
            # 1. Kelly uses actual max_loss (wing width) for risk/reward math
            # 2. Capital allocation uses margin (SPAN) for "how many lots can I afford"
            risk_per = max(max_loss_per, 1.0)  # Kelly risk = theoretical max loss

            if st not in ("equity_long", "equity_short"):
                # Kelly sizing on actual risk/reward
                sz = compute_position_size(
                    pop_pct=pop_pct or 0.60,
                    max_profit=max_profit_per, max_loss=max_loss_per,
                    capital=request.capital, risk_per_contract=risk_per,
                    regime_id=regime_id, wing_width=wing_width,
                    safety_factor=0.5, max_contracts=20,
                )
                contracts = sz.recommended_contracts

                # Cap by margin affordability (India: can't deploy more margin than we have)
                max_risk_per_trade = request.capital * 0.04  # 4% max per trade
                max_contracts_by_margin = max(1, int(max_risk_per_trade / margin_per_lot)) if margin_per_lot > 0 else contracts
                contracts = min(contracts, max_contracts_by_margin)

            # Report margin as the capital tied up (not just theoretical max loss)
            max_risk = margin_per_lot * contracts
            max_profit = max_profit_per * contracts
        except Exception as e:
            warnings.append(f"{ticker}: position sizing failed: {e}")
            blocked.append(BlockedTrade(
                ticker=ticker, structure=str(st),
                reason=f"Position sizing failed: {e}",
                score=entry.composite_score,
            ))
            continue

        if contracts == 0:
            blocked.append(BlockedTrade(
                ticker=ticker, structure=str(st),
                reason="Kelly sizing = 0 contracts",
                score=entry.composite_score,
            ))
            continue

        # --- Liquidity verification (only propose what's actually tradeable) ---
        liquid_strikes = None
        if st == "credit_spread" and ma.market_data is not None:
            from income_desk.workflow.liquidity_filter import get_liquid_credit_spread_strikes
            import time as _time
            _time.sleep(3.5)
            direction = entry.direction or "neutral"
            cs = get_liquid_credit_spread_strikes(
                ticker, current_price, direction, ma,
                short_distance_pct=0.03 if regime_id == 1 else 0.04,
            )
            if cs is None:
                blocked.append(BlockedTrade(
                    ticker=ticker, structure=str(st),
                    reason="No liquid credit spread strikes in broker chain",
                    score=entry.composite_score,
                ))
                continue
            entry_credit = cs["net_credit_est"]
            wing_width = cs["width"]
            max_profit_per = entry_credit * lot_size
            max_profit = max_profit_per * contracts
            # Map to IC-style fields for uniform output
            if cs["option_type"] == "put":
                liquid_strikes = {
                    "short_put": cs["short_strike"], "long_put": cs["long_strike"],
                    "short_call": 0, "long_call": 0,
                    "short_put_oi": cs["short_oi"], "short_call_oi": 0,
                    "net_credit_est": cs["net_credit_est"],
                    "put_wing": cs["width"], "call_wing": 0,
                }
            else:
                liquid_strikes = {
                    "short_put": 0, "long_put": 0,
                    "short_call": cs["short_strike"], "long_call": cs["long_strike"],
                    "short_put_oi": 0, "short_call_oi": cs["short_oi"],
                    "net_credit_est": cs["net_credit_est"],
                    "put_wing": 0, "call_wing": cs["width"],
                }

        if st in ("iron_condor", "iron_butterfly") and ma.market_data is not None:
            from income_desk.workflow.liquidity_filter import get_liquid_ic_strikes
            import time as _time
            _time.sleep(3.5)  # Dhan rate limit for chain call
            liquid_strikes = get_liquid_ic_strikes(
                ticker, current_price, ma,
                short_distance_pct=0.03 if regime_id == 1 else 0.04,
            )
            if liquid_strikes is None:
                blocked.append(BlockedTrade(
                    ticker=ticker, structure=str(st),
                    reason="No liquid strikes found in broker chain",
                    score=entry.composite_score,
                ))
                continue
            # Update entry_credit with actual chain data
            entry_credit = liquid_strikes["net_credit_est"]
            wing_width = max(liquid_strikes["put_wing"], liquid_strikes["call_wing"])
            # Recalc profit with real credit
            max_profit_per = entry_credit * lot_size
            max_profit = max_profit_per * contracts

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
            wing_width=wing_width if liquid_strikes else ts.wing_width_points,
            target_dte=ts.target_dte,
            lot_size=lot_size,
            currency=currency,
            rationale=entry.rationale or "",
            data_gaps=[g.reason for g in entry.data_gaps] if entry.data_gaps else [],
            # Actual liquid strikes from broker chain
            short_put=liquid_strikes["short_put"] if liquid_strikes else None,
            long_put=liquid_strikes["long_put"] if liquid_strikes else None,
            short_call=liquid_strikes["short_call"] if liquid_strikes else None,
            long_call=liquid_strikes["long_call"] if liquid_strikes else None,
            short_put_oi=liquid_strikes["short_put_oi"] if liquid_strikes else None,
            short_call_oi=liquid_strikes["short_call_oi"] if liquid_strikes else None,
            net_credit_per_unit=liquid_strikes["net_credit_est"] if liquid_strikes else None,
        ))

    return RankResponse(
        meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source=data_source, warnings=warnings),
        trades=trades,
        blocked=blocked,
        regime_summary=regimes,
        tradeable_count=len(tradeable),
        total_assessed=ranking.total_assessed if ranking else 0,
    )
