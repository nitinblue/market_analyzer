"""Earnings play opportunity assessment — go/no-go for earnings-related trades."""

from __future__ import annotations

import math
from datetime import date, time
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel

from income_desk.models.opportunity import (
    HardStop,
    OpportunitySignal,
    StrategyRecommendation,
    TradeSpec,
    Verdict,
)
from income_desk.models.regime import RegimeID
from income_desk.models.transparency import DataGap

if TYPE_CHECKING:
    from income_desk.models.fundamentals import FundamentalsSnapshot
    from income_desk.models.regime import RegimeResult
    from income_desk.models.technicals import TechnicalSnapshot
    from income_desk.models.vol_surface import VolatilitySurface


class EarningsPlayStrategy(StrEnum):
    """Strategy types for earnings plays."""

    PRE_EARNINGS_STRADDLE = "pre_earnings_straddle"
    POST_EARNINGS_DRIFT = "post_earnings_drift"
    IV_CRUSH_SELL = "iv_crush_sell"
    NO_TRADE = "no_trade"


class EarningsOpportunity(BaseModel):
    """Result container for earnings play assessment."""

    ticker: str
    as_of_date: date
    verdict: Verdict
    confidence: float
    strategy: str
    direction: str
    signals: list[OpportunitySignal]
    hard_stops: list[HardStop]
    days_to_earnings: int | None
    regime_id: int
    trade_spec: TradeSpec | None = None
    summary: str
    data_gaps: list[DataGap] = []


def assess_earnings_play(
    ticker: str,
    regime: RegimeResult,
    technicals: TechnicalSnapshot,
    fundamentals: FundamentalsSnapshot | None = None,
    vol_surface: VolatilitySurface | None = None,
    as_of: date | None = None,
    iv_rank: float | None = None,
) -> EarningsOpportunity:
    """Assess earnings play opportunity for a single instrument.

    Pure function — consumes pre-computed analysis, produces structured assessment.
    """
    today = as_of or date.today()
    hard_stops: list[HardStop] = []
    signals: list[OpportunitySignal] = []
    score = 0.3  # Start slightly below neutral

    days_to_earnings: int | None = None
    if fundamentals is not None:
        days_to_earnings = fundamentals.upcoming_events.days_to_earnings

    # --- Hard stops ---
    if days_to_earnings is None:
        hard_stops.append(HardStop(
            name="No earnings date",
            description="Earnings date unknown — cannot assess earnings play without known event date",
        ))

    # IV rank hard stop
    if iv_rank is not None and iv_rank < 25:
        hard_stops.append(HardStop(
            name="IV rank too low",
            description=f"IV rank {iv_rank:.0f}% — no crush to capture for earnings play",
        ))

    if hard_stops:
        return EarningsOpportunity(
            ticker=ticker,
            as_of_date=today,
            verdict=Verdict.NO_GO,
            confidence=0.0,
            strategy=EarningsPlayStrategy.NO_TRADE,
            direction="neutral",
            signals=signals,
            hard_stops=hard_stops,
            days_to_earnings=days_to_earnings,
            regime_id=int(regime.regime),
            summary=f"NO_GO: {hard_stops[0].description}",
        )

    assert days_to_earnings is not None  # Guarded by hard stop above

    # --- Proximity signals ---
    if 5 <= days_to_earnings <= 14:
        signals.append(OpportunitySignal(
            name="Earnings window", favorable=True, weight=0.3,
            description=f"Earnings in {days_to_earnings} days — IV expansion likely",
        ))
        score += 0.2
        strategy = EarningsPlayStrategy.PRE_EARNINGS_STRADDLE
    elif 1 <= days_to_earnings <= 4:
        signals.append(OpportunitySignal(
            name="Earnings imminent", favorable=True, weight=0.25,
            description=f"Earnings in {days_to_earnings} days — peak IV",
        ))
        score += 0.25
        strategy = EarningsPlayStrategy.IV_CRUSH_SELL
    elif days_to_earnings == 0:
        signals.append(OpportunitySignal(
            name="Earnings today", favorable=True, weight=0.2,
            description="Earnings today — IV crush imminent",
        ))
        score += 0.15
        strategy = EarningsPlayStrategy.IV_CRUSH_SELL
    else:
        strategy = EarningsPlayStrategy.NO_TRADE
        signals.append(OpportunitySignal(
            name="Earnings too far", favorable=False, weight=0.2,
            description=f"Earnings in {days_to_earnings} days — too far for earnings play",
        ))

    # --- Regime context ---
    if regime.regime in (RegimeID.R1_LOW_VOL_MR, RegimeID.R2_HIGH_VOL_MR):
        signals.append(OpportunitySignal(
            name="MR regime + earnings", favorable=True, weight=0.15,
            description="Mean-reverting regime — post-earnings drift less likely",
        ))
        score += 0.1
    elif regime.regime == RegimeID.R3_LOW_VOL_TREND:
        signals.append(OpportunitySignal(
            name="Trending + earnings", favorable=True, weight=0.15,
            description="Trending regime — post-earnings drift possible",
        ))
        score += 0.15

    # --- ATR context ---
    if technicals.atr_pct >= 1.5:
        signals.append(OpportunitySignal(
            name="High ATR", favorable=True, weight=0.1,
            description=f"ATR% {technicals.atr_pct:.2f} — good premium potential",
        ))
        score += 0.1

    # --- IV rank signal ---
    if iv_rank is not None:
        iv_favorable = iv_rank > 60
        signals.append(OpportunitySignal(
            name="IV rank", favorable=iv_favorable, weight=0.15,
            description=f"IV rank {iv_rank:.0f}% — {'significant crush expected' if iv_favorable else 'moderate crush potential'}",
        ))
        if iv_favorable:
            score += 0.1

    # --- Historical earnings surprise ---
    if fundamentals is not None and fundamentals.recent_earnings:
        last_surprise = fundamentals.recent_earnings[0]
        if last_surprise.surprise_pct is not None and abs(last_surprise.surprise_pct) >= 5:
            signals.append(OpportunitySignal(
                name="Surprise history", favorable=True, weight=0.1,
                description=f"Last surprise: {last_surprise.surprise_pct:+.1f}%",
            ))
            score += 0.1

    # --- Implied move from vol surface ---
    if vol_surface is not None and vol_surface.front_iv > 0:
        # Implied 1-day move = front-month ATM IV * sqrt(1/365)
        atm_iv = vol_surface.front_iv
        implied_move_pct = atm_iv * math.sqrt(1 / 365) * 100  # 1-day implied move %

        # Compare to historical ATR-based move
        historical_move_pct = technicals.atr_pct
        if historical_move_pct > 0:
            iv_vs_realized = implied_move_pct / historical_move_pct
            sell_premium = iv_vs_realized > 1.3
            signals.append(OpportunitySignal(
                name="implied_vs_realized",
                favorable=sell_premium,
                weight=0.20,
                description=(
                    f"Implied move {implied_move_pct:.1f}% vs historical {historical_move_pct:.1f}% "
                    f"(ratio {iv_vs_realized:.1f}x — "
                    f"{'rich premium, sell' if sell_premium else 'fair or cheap, skip'})"
                ),
            ))
            if sell_premium:
                score += 0.1
            if iv_vs_realized < 0.7:
                hard_stops.append(HardStop(
                    name="underpriced_iv",
                    description=f"Implied/realized ratio {iv_vs_realized:.1f}x — market underpricing the event",
                ))

    # Direction
    direction = "neutral"  # Most earnings plays are non-directional

    # Clamp
    confidence = max(0.0, min(1.0, score))

    # Late hard stops force NO_GO
    if hard_stops:
        verdict = Verdict.NO_GO
        confidence = 0.0
    elif confidence >= 0.55:
        verdict = Verdict.GO
    elif confidence >= 0.35:
        verdict = Verdict.CAUTION
    else:
        verdict = Verdict.NO_GO

    # --- Trade spec ---
    trade_spec = None
    if verdict != Verdict.NO_GO and strategy != EarningsPlayStrategy.NO_TRADE:
        trade_spec = _build_earnings_trade_spec(
            ticker, technicals, strategy, vol_surface, days_to_earnings,
        )

    summary_parts = [f"{verdict.upper()}: {ticker}"]
    if days_to_earnings is not None:
        summary_parts.append(f"Earnings in {days_to_earnings}d")
    summary_parts.append(f"Score: {confidence:.0%}")

    # --- Data gaps ---
    gaps: list[DataGap] = []
    if days_to_earnings is None:
        gaps.append(DataGap(field="days_to_earnings", reason="no earnings date available", impact="high", affects="DTE selection and strategy timing"))
    if trade_spec is not None and trade_spec.max_entry_price is None:
        gaps.append(DataGap(field="max_entry_price", reason="broker not connected", impact="high", affects="entry pricing and POP"))
    if iv_rank is None:
        gaps.append(DataGap(field="iv_rank", reason="market metrics unavailable", impact="medium", affects="premium assessment"))
    if vol_surface is None:
        gaps.append(DataGap(field="implied_move", reason="vol surface unavailable — cannot compute implied vs realized move", impact="high", affects="earnings play edge assessment"))

    return EarningsOpportunity(
        ticker=ticker,
        as_of_date=today,
        verdict=verdict,
        confidence=confidence,
        strategy=strategy,
        direction=direction,
        signals=signals,
        hard_stops=hard_stops,
        days_to_earnings=days_to_earnings,
        regime_id=int(regime.regime),
        trade_spec=trade_spec,
        summary=" | ".join(summary_parts),
        data_gaps=gaps,
    )


def _build_earnings_trade_spec(
    ticker: str,
    technicals: TechnicalSnapshot,
    strategy: EarningsPlayStrategy,
    vol_surface: VolatilitySurface | None,
    days_to_earnings: int,
) -> TradeSpec | None:
    """Build trade spec for earnings play."""
    from income_desk.opportunity.option_plays._trade_spec_helpers import (
        _populate_market_fields,
        build_iron_butterfly_legs,
        build_straddle_legs,
        find_best_expiration,
    )
    from income_desk.models.opportunity import OrderSide, StructureType

    if vol_surface is None or not vol_surface.term_structure:
        return None

    # Market-aware fields: currency, lot_size, settlement, exercise_style, timezone
    mkt = _populate_market_fields(ticker)
    currency_sym = "₹" if mkt.get("currency") == "INR" else "$"

    price = technicals.current_price
    atr = technicals.atr

    # Target expiration close to earnings
    target_dte = max(days_to_earnings, 1)
    exp_pt = find_best_expiration(vol_surface.term_structure, target_dte, target_dte + 7)
    if exp_pt is None:
        exp_pt = find_best_expiration(vol_surface.term_structure, 0, 30)
    if exp_pt is None:
        return None

    try:
        if strategy == EarningsPlayStrategy.PRE_EARNINGS_STRADDLE:
            legs = build_straddle_legs(
                price, "buy", exp_pt.expiration, exp_pt.days_to_expiry, exp_pt.atm_iv,
            )
            return TradeSpec(
                ticker=ticker, legs=legs, underlying_price=price,
                target_dte=exp_pt.days_to_expiry, target_expiration=exp_pt.expiration,
                spec_rationale=f"Pre-earnings long straddle. {exp_pt.days_to_expiry} DTE, earnings in {days_to_earnings}d.",
                structure_type=StructureType.STRADDLE,
                order_side=OrderSide.DEBIT,
                profit_target_pct=0.50,
                stop_loss_pct=0.50,
                max_profit_desc="Unlimited (long straddle — profits from big move either direction)",
                max_loss_desc="Net debit paid (both premiums)",
                exit_notes=["Close morning after earnings release",
                            "IV crush will reduce value — need big move to overcome",
                            "Close at 50% loss if move doesn't materialize pre-earnings"],
                entry_window_start=time(10, 0),
                entry_window_end=time(14, 30),
                **mkt,
            )

        elif strategy == EarningsPlayStrategy.IV_CRUSH_SELL:
            legs, wing_width = build_iron_butterfly_legs(
                price, atr, 2, exp_pt.expiration, exp_pt.days_to_expiry, exp_pt.atm_iv,
            )
            return TradeSpec(
                ticker=ticker, legs=legs, underlying_price=price,
                target_dte=exp_pt.days_to_expiry, target_expiration=exp_pt.expiration,
                wing_width_points=wing_width,
                spec_rationale=f"IV crush iron butterfly. {exp_pt.days_to_expiry} DTE, earnings in {days_to_earnings}d.",
                structure_type=StructureType.IRON_BUTTERFLY,
                order_side=OrderSide.CREDIT,
                profit_target_pct=0.50,
                stop_loss_pct=2.0,
                max_profit_desc="Credit received (amplified by IV crush post-earnings)",
                max_loss_desc=f"Wing width ({currency_sym}{wing_width:.0f}) minus credit",
                exit_notes=["Close morning after earnings release",
                            "IV crush is your edge — close quickly to capture",
                            "Close if underlying gaps beyond wing strikes"],
                entry_window_start=time(10, 0),
                entry_window_end=time(14, 30),
                **mkt,
            )
    except Exception:
        return None

    return None
