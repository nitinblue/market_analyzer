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


def _blocked_from_ts(ts) -> dict:
    """Extract strike/expiry fields from a TradeSpec for BlockedTrade."""
    if ts is None or not ts.legs:
        return {}
    result: dict = {}
    sp = _extract_strike(ts, "short_put", "put", "STO")
    lp = _extract_strike(ts, "long_put", "put", "BTO")
    sc = _extract_strike(ts, "short_call", "call", "STO")
    lc = _extract_strike(ts, "long_call", "call", "BTO")
    if sp: result["short_put"] = sp
    if lp: result["long_put"] = lp
    if sc: result["short_call"] = sc
    if lc: result["long_call"] = lc
    exps = [l.expiration for l in ts.legs if l.expiration]
    if exps:
        result["expiry"] = str(min(exps))
    return result


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
    model_config = {"arbitrary_types_allowed": True}

    tickers: list[str]
    capital: float = 5_000_000
    market: str = "India"
    risk_tolerance: str = "moderate"
    iv_rank_map: dict[str, float] | None = None
    skip_intraday: bool = True
    max_trades: int = 10
    min_pop: float = 0.40
    snapshot: object | None = None  # MarketSnapshot — skips REST discovery in ChainFetcher


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

    # ── 1b. Fetch all chains upfront (single fetch per ticker) ──
    chains = None
    if ma.market_data is not None:
        try:
            from income_desk.service.chain_fetcher import ChainFetcher
            fetcher = ChainFetcher(market_data=ma.market_data, data_service=ma.data)
            chains = fetcher.fetch_batch(tradeable, snapshot=request.snapshot)
            for ticker, bundle in chains.items():
                if bundle.fetch_meta.is_partial:
                    warnings.append(
                        f"{ticker}: partial chain ({bundle.missing_count} symbols missing)"
                    )
                if bundle.fetch_meta.error:
                    warnings.append(
                        f"{ticker}: chain fetch error — {bundle.fetch_meta.error}"
                    )
        except Exception as e:
            warnings.append(f"ChainFetcher failed: {e}")

    # ── 2. Ranking from assessors ──
    ranking = None
    try:
        ranking = ma.ranking.rank(
            tradeable,
            skip_intraday=request.skip_intraday,
            iv_rank_map=request.iv_rank_map or {},
            chains=chains,
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
            # Assessor returned NO_GO — no trade spec generated
            verdict_str = entry.verdict.value if hasattr(entry.verdict, 'value') else str(entry.verdict)
            blocked.append(BlockedTrade(
                ticker=entry.ticker,
                structure=entry.strategy_name or str(entry.strategy_type or ""),
                reason=entry.rationale or f"Assessor verdict: {verdict_str}",
                score=entry.composite_score,
            ))
            continue
        ts = entry.trade_spec

        # Reject degenerate legs (same strike on both sides)
        # Exception: calendars and diagonals legitimately have same strike, different expiry
        structure = str(ts.structure_type or "").lower()
        is_calendar_type = any(t in structure for t in ("calendar", "diagonal"))
        if ts.legs and len(ts.legs) >= 2 and not is_calendar_type:
            unique_strikes = set(leg.strike for leg in ts.legs)
            if len(unique_strikes) < 2:
                blocked.append(BlockedTrade(
                    ticker=entry.ticker, structure=str(ts.structure_type or ""),
                    reason=f"Degenerate trade: all legs at same strike ({unique_strikes})",
                    score=entry.composite_score,
                    **_blocked_from_ts(ts),
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

    repriced_list = batch_reprice(entries, ma.market_data, ma.technicals, chains=chains)

    # ── 4. Validate + POP + Size → TradeProposal ──
    from income_desk.trade_lifecycle import estimate_pop
    from income_desk.features.position_sizing import compute_position_size
    from income_desk.service.trade_validator import TradeValidator

    validator = TradeValidator()
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
                **_blocked_from_ts(ts),
            ))
            continue

        # 4b. Block if illiquid
        if not repriced.liquidity_ok:
            blocked.append(BlockedTrade(
                ticker=ticker, structure=st,
                reason="Illiquid strikes (wide spread or low OI)", score=entry.composite_score,
                **_blocked_from_ts(ts),
            ))
            continue

        # 4c. POP estimation
        pop_pct = None
        ev = None
        pop_result = None
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
            warnings.append(f"{ticker}: POP failed: {e}")

        # 4d. Validate trade through structure-aware rules engine
        vr = validator.validate(ts, repriced_trade=repriced, pop_estimate=pop_result)

        if vr.status == "rejected":
            reasons = "; ".join(r.root_cause for r in vr.rejections)
            blocked.append(BlockedTrade(
                ticker=ticker, structure=st,
                reason=f"Validation rejected: {reasons}",
                score=entry.composite_score,
                **_blocked_from_ts(ts),
            ))
            continue

        # Use validated economics (guaranteed non-null for valid/flagged trades)
        econ = vr.economics
        if econ is None:
            blocked.append(BlockedTrade(
                ticker=ticker, structure=st,
                reason="Validator produced no economics",
                score=entry.composite_score,
                **_blocked_from_ts(ts),
            ))
            continue

        # Override pop/ev with validated values
        pop_pct = econ.pop_pct
        ev = econ.expected_value
        max_profit_total = econ.max_profit * econ.contracts
        max_loss_total = (econ.max_loss or 0.0) * econ.contracts
        contracts = max(1, int(econ.contracts)) if econ.contracts >= 1 else econ.contracts

        # EV gate
        if ev is not None and ev < 0:
            blocked.append(BlockedTrade(
                ticker=ticker, structure=st,
                reason=f"Negative EV: {ev:.0f} (POP {pop_pct:.0%})",
                score=entry.composite_score,
                **_blocked_from_ts(ts),
            ))
            continue

        if len(trades) >= request.max_trades:
            break

        # Build data_gaps from validation flags + assessor gaps
        data_gaps = [g.reason for g in entry.data_gaps] if entry.data_gaps else []
        for flag in vr.flags:
            data_gaps.append(f"{flag.field}: {flag.message}")

        # 4e. Build TradeProposal
        badge = ts.strategy_badge if ts.strategy_badge else str(st)
        trades.append(TradeProposal(
            rank=len(trades) + 1,
            ticker=ticker,
            structure=st,
            direction=entry.direction or "neutral",
            strategy_badge=badge,
            composite_score=entry.composite_score,
            verdict="caution" if vr.status == "flagged" else (entry.verdict or "go"),
            pop_pct=pop_pct,
            expected_value=ev,
            contracts=int(contracts) if contracts >= 1 else 1,
            max_risk=max_loss_total,
            max_profit=max_profit_total,
            entry_credit=econ.entry_credit,
            credit_source=repriced.credit_source,
            wing_width=econ.wing_width,
            target_dte=ts.target_dte,
            expiry=repriced.expiry,
            current_price=repriced.current_price,
            regime_id=repriced.regime_id,
            atr_pct=repriced.atr_pct,
            lot_size=econ.lot_size,
            currency=ts.currency or ("INR" if request.market == "India" else "USD"),
            rationale=entry.rationale or "",
            data_gaps=data_gaps,
            short_put=_extract_strike(ts, "short_put", "put", "STO"),
            long_put=_extract_strike(ts, "long_put", "put", "BTO"),
            short_call=_extract_strike(ts, "short_call", "call", "STO"),
            long_call=_extract_strike(ts, "long_call", "call", "BTO"),
            net_credit_per_unit=econ.entry_credit,
        ))

    return RankResponse(
        meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source=data_source, warnings=warnings),
        trades=trades,
        blocked=blocked,
        regime_summary=regimes,
        tradeable_count=len(tradeable),
        total_assessed=ranking.total_assessed if ranking else 0,
    )
