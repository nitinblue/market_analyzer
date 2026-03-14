"""Execution quality validation for systematic trading.

Checks bid-ask spread, open interest, and volume per leg before
recommending trade execution. Returns a deterministic GO/NO_GO.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel

from market_analyzer.models.opportunity import TradeSpec, LegSpec
from market_analyzer.models.quotes import OptionQuote


class ExecutionVerdict(StrEnum):
    GO = "go"
    WIDE_SPREAD = "wide_spread"
    ILLIQUID = "illiquid"
    NO_QUOTE = "no_quote"


# Severity ordering: higher = worse.
_VERDICT_SEVERITY: dict[ExecutionVerdict, int] = {
    ExecutionVerdict.GO: 0,
    ExecutionVerdict.ILLIQUID: 1,
    ExecutionVerdict.WIDE_SPREAD: 2,
    ExecutionVerdict.NO_QUOTE: 3,
}


class LegQuality(BaseModel):
    """Execution quality for a single leg."""

    strike: float
    option_type: str
    expiration: date
    bid: float | None
    ask: float | None
    spread_pct: float | None  # (ask - bid) / mid * 100
    open_interest: int | None
    volume: int | None
    verdict: ExecutionVerdict
    issue: str | None = None  # Description of problem if not GO


class ExecutionQuality(BaseModel):
    """Execution quality assessment for a complete trade."""

    ticker: str
    overall_verdict: ExecutionVerdict  # Worst leg determines overall
    legs: list[LegQuality]
    total_spread_cost_pct: float | None  # Aggregate spread drag as % of trade
    summary: str
    tradeable: bool  # True only if overall_verdict == GO


def _find_quote(
    leg: LegSpec,
    quotes: list[OptionQuote],
) -> OptionQuote | None:
    """Find the matching quote for a leg by strike, option_type, expiration."""
    for q in quotes:
        if (
            q.strike == leg.strike
            and q.option_type == leg.option_type
            and q.expiration == leg.expiration
        ):
            return q
    return None


def _assess_leg(
    leg: LegSpec,
    quote: OptionQuote | None,
    max_spread_pct: float,
    min_open_interest: int,
    min_volume: int,
) -> LegQuality:
    """Assess execution quality for a single leg."""
    if quote is None:
        return LegQuality(
            strike=leg.strike,
            option_type=leg.option_type,
            expiration=leg.expiration,
            bid=None,
            ask=None,
            spread_pct=None,
            open_interest=None,
            volume=None,
            verdict=ExecutionVerdict.NO_QUOTE,
            issue=f"No quote found for {leg.strike} {leg.option_type} {leg.expiration}",
        )

    bid = quote.bid
    ask = quote.ask

    # Zero bid or ask means no real market
    if bid <= 0 or ask <= 0:
        return LegQuality(
            strike=leg.strike,
            option_type=leg.option_type,
            expiration=leg.expiration,
            bid=bid,
            ask=ask,
            spread_pct=None,
            open_interest=quote.open_interest,
            volume=quote.volume,
            verdict=ExecutionVerdict.NO_QUOTE,
            issue=f"Zero {'bid' if bid <= 0 else 'ask'} — no real market",
        )

    mid = (bid + ask) / 2.0
    spread_pct = ((ask - bid) / mid) * 100.0 if mid > 0 else None

    # Check spread width
    if spread_pct is not None and spread_pct > max_spread_pct:
        return LegQuality(
            strike=leg.strike,
            option_type=leg.option_type,
            expiration=leg.expiration,
            bid=bid,
            ask=ask,
            spread_pct=round(spread_pct, 2),
            open_interest=quote.open_interest,
            volume=quote.volume,
            verdict=ExecutionVerdict.WIDE_SPREAD,
            issue=f"Spread {spread_pct:.1f}% exceeds {max_spread_pct:.0f}% limit",
        )

    # Check open interest
    if quote.open_interest < min_open_interest:
        return LegQuality(
            strike=leg.strike,
            option_type=leg.option_type,
            expiration=leg.expiration,
            bid=bid,
            ask=ask,
            spread_pct=round(spread_pct, 2) if spread_pct is not None else None,
            open_interest=quote.open_interest,
            volume=quote.volume,
            verdict=ExecutionVerdict.ILLIQUID,
            issue=f"OI {quote.open_interest} below minimum {min_open_interest}",
        )

    # Check volume
    if quote.volume < min_volume:
        return LegQuality(
            strike=leg.strike,
            option_type=leg.option_type,
            expiration=leg.expiration,
            bid=bid,
            ask=ask,
            spread_pct=round(spread_pct, 2) if spread_pct is not None else None,
            open_interest=quote.open_interest,
            volume=quote.volume,
            verdict=ExecutionVerdict.ILLIQUID,
            issue=f"Volume {quote.volume} below minimum {min_volume}",
        )

    # All checks pass
    return LegQuality(
        strike=leg.strike,
        option_type=leg.option_type,
        expiration=leg.expiration,
        bid=bid,
        ask=ask,
        spread_pct=round(spread_pct, 2) if spread_pct is not None else None,
        open_interest=quote.open_interest,
        volume=quote.volume,
        verdict=ExecutionVerdict.GO,
        issue=None,
    )


def validate_execution_quality(
    trade_spec: TradeSpec,
    quotes: list[OptionQuote],
    max_spread_pct: float = 15.0,
    min_open_interest: int = 50,
    min_volume: int = 5,
) -> ExecutionQuality:
    """Validate execution quality for a trade before submission.

    Checks bid-ask spread, open interest, and volume for every leg.
    Returns a deterministic GO/NO_GO assessment.

    Args:
        trade_spec: The trade to validate.
        quotes: Broker quotes to match against each leg.
        max_spread_pct: Maximum bid-ask spread as % of mid price (default 15%).
        min_open_interest: Minimum open interest per leg (default 50).
        min_volume: Minimum daily volume per leg (default 5).

    Returns:
        ExecutionQuality with per-leg assessments and overall verdict.
    """
    leg_qualities: list[LegQuality] = []
    for leg in trade_spec.legs:
        quote = _find_quote(leg, quotes)
        lq = _assess_leg(leg, quote, max_spread_pct, min_open_interest, min_volume)
        leg_qualities.append(lq)

    # Overall verdict = worst leg
    overall = ExecutionVerdict.GO
    for lq in leg_qualities:
        if _VERDICT_SEVERITY[lq.verdict] > _VERDICT_SEVERITY[overall]:
            overall = lq.verdict

    # Compute total spread cost as % of trade value
    total_spread_cost_pct = _compute_total_spread_cost(trade_spec, leg_qualities)

    # Build summary
    if overall == ExecutionVerdict.GO:
        summary = f"All {len(leg_qualities)} legs pass execution quality checks"
    else:
        issues = [lq for lq in leg_qualities if lq.verdict != ExecutionVerdict.GO]
        issue_descs = [f"{lq.strike} {lq.option_type}: {lq.issue}" for lq in issues]
        summary = f"{len(issues)}/{len(leg_qualities)} legs failed: " + "; ".join(issue_descs)

    return ExecutionQuality(
        ticker=trade_spec.ticker,
        overall_verdict=overall,
        legs=leg_qualities,
        total_spread_cost_pct=total_spread_cost_pct,
        summary=summary,
        tradeable=overall == ExecutionVerdict.GO,
    )


def _compute_total_spread_cost(
    trade_spec: TradeSpec,
    leg_qualities: list[LegQuality],
) -> float | None:
    """Compute aggregate spread cost as % of underlying price.

    Each leg's spread cost = (ask - bid) * quantity.  The total is
    summed and expressed as a percentage of the underlying price
    (per-share, so multiply by 100 for per-contract).
    """
    total_spread = 0.0
    for leg, lq in zip(trade_spec.legs, leg_qualities):
        if lq.bid is not None and lq.ask is not None and lq.bid > 0 and lq.ask > 0:
            total_spread += (lq.ask - lq.bid) * leg.quantity
        else:
            # Can't compute if any leg is missing quotes
            return None

    underlying = trade_spec.underlying_price
    if underlying <= 0:
        return None

    return round((total_spread / underlying) * 100.0, 4)
