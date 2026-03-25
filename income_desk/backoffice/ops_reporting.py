"""
Operations Reporting — pure computation functions for business ops dashboards.

eTrading queries DB, constructs inputs, calls these functions, serves via API.
No I/O, no state, no side effects.
"""

from collections import Counter
from datetime import datetime, timedelta

from pydantic import BaseModel


# ── Input Models ──────────────────────────────────────────────────────────────


class DecisionRecord(BaseModel):
    """Single pipeline decision (entry/exit/adjustment)."""
    ticker: str
    strategy: str
    score: float | None = None
    response: str
    gate_result: str | None = None
    timestamp: str


class ShadowRecord(BaseModel):
    """Trade that scored well but got blocked by a gate."""
    ticker: str
    structure: str
    score: float
    blocked_by: str


class BookedRecord(BaseModel):
    """Trade that made it through all gates and was booked."""
    ticker: str
    strategy: str
    score: float
    entry_price: float
    trade_type: str


class DeskUtilization(BaseModel):
    """Single desk's capital usage."""
    desk_name: str
    allocated_capital: float
    deployed_capital: float
    utilization_pct: float
    open_positions: int
    position_limit: int
    position_utilization_pct: float
    realized_pnl: float
    unrealized_pnl: float


class BrokerAccountStatus(BaseModel):
    """Broker connection status."""
    broker_name: str
    account_id: str
    connected: bool
    portfolio_name: str


class ClosedTradeRecord(BaseModel):
    """Completed trade for P&L rollup."""
    trade_id: str
    ticker: str
    strategy: str
    total_pnl: float
    closed_at: str
    entry_date: str


# ── Output Models ─────────────────────────────────────────────────────────────


class RejectionBreakdown(BaseModel):
    """Categorized rejection reasons with counts."""
    reason: str
    count: int
    pct: float


class DailyOpsSummary(BaseModel):
    """Full daily pipeline summary."""
    date: str
    total_decisions: int
    approved: int
    rejected: int
    approval_rate: float
    shadow_count: int
    booked_count: int
    rejections_by_reason: list[RejectionBreakdown]
    shadows: list[ShadowRecord]
    booked: list[BookedRecord]
    top_rejection_reason: str
    opportunity_cost_note: str


class CapitalUtilization(BaseModel):
    """Full capital deployment picture."""
    total_allocated: float
    total_deployed: float
    total_utilization_pct: float
    total_open_positions: int
    total_realized_pnl: float
    total_unrealized_pnl: float
    desks: list[DeskUtilization]
    brokers: list[BrokerAccountStatus]


class PeriodPnL(BaseModel):
    """P&L for a single time period."""
    period_label: str
    period_start: str
    period_end: str
    closed_trades: int
    winners: int
    losers: int
    win_rate: float
    total_pnl: float
    cumulative_pnl: float


class StrategyAttribution(BaseModel):
    """P&L attributed to a single strategy."""
    strategy: str
    trade_count: int
    total_pnl: float
    win_rate: float
    avg_pnl_per_trade: float


class TickerAttribution(BaseModel):
    """P&L attributed to a single underlying."""
    ticker: str
    trade_count: int
    total_pnl: float


class PnLRollup(BaseModel):
    """Full P&L rollup with attribution."""
    period_type: str
    periods: list[PeriodPnL]
    by_strategy: list[StrategyAttribution]
    by_ticker: list[TickerAttribution]
    total_pnl: float
    total_closed: int
    overall_win_rate: float
    best_trade: TickerAttribution | None = None
    worst_trade: TickerAttribution | None = None


class PlatformMetrics(BaseModel):
    """Platform business metrics."""
    waitlist_total: int
    waitlist_this_week: int
    knack_by_step: dict[int, int]
    model_portfolio_open: int
    model_portfolio_pnl: float
    model_portfolio_win_rate: float | None = None


# ── Functions ─────────────────────────────────────────────────────────────────


def compute_daily_ops_summary(
    decisions: list[DecisionRecord],
    shadows: list[ShadowRecord],
    booked: list[BookedRecord],
    date: str = "",
) -> DailyOpsSummary:
    """Summarize a single day's pipeline activity."""
    approved = sum(1 for d in decisions if d.response == "approved")
    rejected = sum(1 for d in decisions if d.response == "rejected")
    total = len(decisions)
    approval_rate = approved / total if total > 0 else 0.0

    # Categorize rejection reasons
    rejection_reasons: Counter[str] = Counter()
    for d in decisions:
        if d.response != "rejected":
            continue
        reason = d.gate_result or "unknown"
        lower = reason.lower()
        if "no_go" in lower:
            rejection_reasons["NO_GO"] += 1
        elif "no_trade" in lower or reason == "no_trade":
            rejection_reasons["no_trade"] += 1
        elif "structure" in lower:
            rejection_reasons["structure_blocked"] += 1
        elif "portfolio" in lower:
            rejection_reasons["portfolio_full"] += 1
        elif "score" in lower:
            rejection_reasons["low_score"] += 1
        else:
            rejection_reasons[reason] += 1

    rejections_list = sorted(
        [
            RejectionBreakdown(
                reason=r,
                count=c,
                pct=round(c / rejected, 4) if rejected > 0 else 0.0,
            )
            for r, c in rejection_reasons.items()
        ],
        key=lambda x: x.count,
        reverse=True,
    )

    top_reason = rejections_list[0].reason if rejections_list else "none"

    high_score_blocked = sum(1 for s in shadows if s.score >= 0.60)
    opp_note = (
        f"{high_score_blocked} trades with score >= 0.60 blocked"
        if high_score_blocked > 0
        else "No high-scoring trades blocked"
    )

    return DailyOpsSummary(
        date=date,
        total_decisions=total,
        approved=approved,
        rejected=rejected,
        approval_rate=round(approval_rate, 4),
        shadow_count=len(shadows),
        booked_count=len(booked),
        rejections_by_reason=rejections_list,
        shadows=shadows,
        booked=booked,
        top_rejection_reason=top_reason,
        opportunity_cost_note=opp_note,
    )


def compute_capital_utilization(
    desks: list[DeskUtilization],
    brokers: list[BrokerAccountStatus],
) -> CapitalUtilization:
    """Aggregate desk-level capital data into portfolio-wide view."""
    total_alloc = sum(d.allocated_capital for d in desks)
    total_deployed = sum(d.deployed_capital for d in desks)
    total_open = sum(d.open_positions for d in desks)
    total_realized = sum(d.realized_pnl for d in desks)
    total_unrealized = sum(d.unrealized_pnl for d in desks)

    return CapitalUtilization(
        total_allocated=total_alloc,
        total_deployed=round(total_deployed, 2),
        total_utilization_pct=round(total_deployed / total_alloc, 4) if total_alloc > 0 else 0.0,
        total_open_positions=total_open,
        total_realized_pnl=round(total_realized, 2),
        total_unrealized_pnl=round(total_unrealized, 2),
        desks=desks,
        brokers=brokers,
    )


def compute_pnl_rollup(
    trades: list[ClosedTradeRecord],
    period_type: str = "daily",
) -> PnLRollup:
    """Bucket P&L by time period with strategy and ticker attribution."""
    if not trades:
        return PnLRollup(
            period_type=period_type,
            periods=[],
            by_strategy=[],
            by_ticker=[],
            total_pnl=0.0,
            total_closed=0,
            overall_win_rate=0.0,
        )

    sorted_trades = sorted(trades, key=lambda t: t.closed_at)

    def _period_key(dt_str: str) -> tuple[str, str, str]:
        dt = datetime.fromisoformat(dt_str)
        if period_type == "daily":
            d = dt.date().isoformat()
            return d, d, d
        elif period_type == "weekly":
            start = dt.date() - timedelta(days=dt.weekday())
            end = start + timedelta(days=6)
            label = f"Week of {start.isoformat()}"
            return label, start.isoformat(), end.isoformat()
        else:  # monthly
            label = dt.strftime("%B %Y")
            start = dt.replace(day=1).date().isoformat()
            if dt.month == 12:
                end_dt = dt.replace(year=dt.year + 1, month=1, day=1)
            else:
                end_dt = dt.replace(month=dt.month + 1, day=1)
            return label, start, end_dt.date().isoformat()

    buckets: dict[str, list[ClosedTradeRecord]] = {}
    bucket_meta: dict[str, tuple[str, str]] = {}
    for t in sorted_trades:
        label, start, end = _period_key(t.closed_at)
        buckets.setdefault(label, []).append(t)
        bucket_meta[label] = (start, end)

    cumulative = 0.0
    periods = []
    for label in sorted(buckets.keys()):
        bucket = buckets[label]
        w = sum(1 for t in bucket if t.total_pnl > 0)
        l = sum(1 for t in bucket if t.total_pnl < 0)
        pnl = sum(t.total_pnl for t in bucket)
        cumulative += pnl
        start, end = bucket_meta[label]
        periods.append(PeriodPnL(
            period_label=label,
            period_start=start,
            period_end=end,
            closed_trades=len(bucket),
            winners=w,
            losers=l,
            win_rate=round(w / len(bucket), 4) if bucket else 0.0,
            total_pnl=round(pnl, 2),
            cumulative_pnl=round(cumulative, 2),
        ))

    # Strategy attribution
    strat_map: dict[str, list[ClosedTradeRecord]] = {}
    for t in sorted_trades:
        strat_map.setdefault(t.strategy, []).append(t)
    by_strategy = sorted(
        [
            StrategyAttribution(
                strategy=s,
                trade_count=len(ts),
                total_pnl=round(sum(t.total_pnl for t in ts), 2),
                win_rate=round(sum(1 for t in ts if t.total_pnl > 0) / len(ts), 4) if ts else 0.0,
                avg_pnl_per_trade=round(sum(t.total_pnl for t in ts) / len(ts), 2) if ts else 0.0,
            )
            for s, ts in strat_map.items()
        ],
        key=lambda x: x.total_pnl,
        reverse=True,
    )

    # Ticker attribution
    ticker_map: dict[str, list[ClosedTradeRecord]] = {}
    for t in sorted_trades:
        ticker_map.setdefault(t.ticker, []).append(t)
    by_ticker = sorted(
        [
            TickerAttribution(
                ticker=tk,
                trade_count=len(ts),
                total_pnl=round(sum(t.total_pnl for t in ts), 2),
            )
            for tk, ts in ticker_map.items()
        ],
        key=lambda x: x.total_pnl,
        reverse=True,
    )

    total_pnl = sum(t.total_pnl for t in sorted_trades)
    winners = sum(1 for t in sorted_trades if t.total_pnl > 0)

    return PnLRollup(
        period_type=period_type,
        periods=periods,
        by_strategy=by_strategy,
        by_ticker=by_ticker,
        total_pnl=round(total_pnl, 2),
        total_closed=len(sorted_trades),
        overall_win_rate=round(winners / len(sorted_trades), 4) if sorted_trades else 0.0,
        best_trade=by_ticker[0] if by_ticker else None,
        worst_trade=by_ticker[-1] if by_ticker else None,
    )


def compute_platform_metrics(
    waitlist_total: int,
    waitlist_this_week: int,
    knack_progress: dict[int, int],
    model_trades_open: int,
    model_trades_closed_pnl: float,
    model_trades_win_rate: float | None,
) -> PlatformMetrics:
    """Aggregate platform business metrics."""
    return PlatformMetrics(
        waitlist_total=waitlist_total,
        waitlist_this_week=waitlist_this_week,
        knack_by_step=knack_progress,
        model_portfolio_open=model_trades_open,
        model_portfolio_pnl=round(model_trades_closed_pnl, 2),
        model_portfolio_win_rate=(
            round(model_trades_win_rate, 4) if model_trades_win_rate is not None else None
        ),
    )
