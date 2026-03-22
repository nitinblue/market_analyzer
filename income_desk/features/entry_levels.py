"""Entry-level intelligence: strike proximity, skew selection, entry scoring.

Pure functions — no data fetching, no broker required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from income_desk.models.entry import (
    ConditionalEntry,
    EntryLevelScore,
    IVRankQuality,
    PullbackAlert,
    SkewOptimalStrike,
    StrikeProximityLeg,
    StrikeProximityResult,
)
from income_desk.models.vol_surface import SkewSlice

if TYPE_CHECKING:
    from income_desk.models.levels import LevelsAnalysis
    from income_desk.models.opportunity import TradeSpec
    from income_desk.models.technicals import TechnicalSnapshot


def compute_strike_support_proximity(
    trade_spec: TradeSpec,
    levels: LevelsAnalysis,
    atr: float,
    min_strength: float = 0.5,
    max_distance_atr: float = 1.0,
) -> StrikeProximityResult:
    from income_desk.models.opportunity import LegAction

    leg_results: list[StrikeProximityLeg] = []

    for leg in trade_spec.legs:
        if leg.action != LegAction.SELL_TO_OPEN:
            continue

        if leg.option_type == "put":
            candidate_levels = levels.support_levels
        else:
            candidate_levels = levels.resistance_levels

        best_level = None
        best_dist = float("inf")

        for lvl in candidate_levels:
            dist = abs(leg.strike - lvl.price)
            if dist < best_dist:
                best_dist = dist
                best_level = lvl

        if best_level is not None:
            distance_atr = best_dist / atr if atr > 0 else float("inf")
            backed = distance_atr <= max_distance_atr and best_level.strength >= min_strength
            leg_results.append(StrikeProximityLeg(
                role=leg.role, strike=leg.strike,
                nearest_level_price=best_level.price,
                nearest_level_strength=best_level.strength,
                nearest_level_sources=[s.value for s in best_level.sources],
                distance_points=round(best_dist, 2),
                distance_atr=round(distance_atr, 2),
                backed_by_level=backed,
            ))
        else:
            leg_results.append(StrikeProximityLeg(
                role=leg.role, strike=leg.strike,
                nearest_level_price=0.0, nearest_level_strength=0.0,
                nearest_level_sources=[], distance_points=0.0,
                distance_atr=float("inf"), backed_by_level=False,
            ))

    if not leg_results:
        overall_score = 1.0
        all_backed = True
    else:
        backed_count = sum(1 for l in leg_results if l.backed_by_level)
        overall_score = backed_count / len(leg_results)
        all_backed = backed_count == len(leg_results)

    parts = []
    for lr in leg_results:
        status = "backed" if lr.backed_by_level else "UNBACKED"
        sources = ", ".join(lr.nearest_level_sources[:2]) if lr.nearest_level_sources else "none"
        parts.append(
            f"{lr.role} at {lr.strike} {status} "
            f"({sources} at {lr.nearest_level_price}, {lr.distance_atr:.1f} ATR)"
        )
    summary = "; ".join(parts) if parts else "No short legs to analyze"

    return StrikeProximityResult(
        legs=leg_results, overall_score=round(overall_score, 2),
        all_backed=all_backed, summary=summary,
    )


def select_skew_optimal_strike(
    underlying_price: float, atr: float, regime_id: int,
    skew: SkewSlice, option_type: str,
    min_distance_atr: float = 0.8, max_distance_atr: float = 2.0,
) -> SkewOptimalStrike:
    from income_desk.opportunity.option_plays._trade_spec_helpers import snap_strike

    short_mult = 1.0 if regime_id == 1 else 1.5
    if option_type == "put":
        baseline_raw = underlying_price - (short_mult * atr)
        relevant_skew = skew.put_skew
    else:
        baseline_raw = underlying_price + (short_mult * atr)
        relevant_skew = skew.call_skew

    baseline_strike = snap_strike(baseline_raw, underlying_price)
    baseline_iv = skew.atm_iv + relevant_skew * (short_mult / 1.5)

    min_skew_threshold = 0.01
    if relevant_skew < min_skew_threshold:
        return SkewOptimalStrike(
            option_type=option_type, baseline_strike=baseline_strike,
            optimal_strike=baseline_strike, baseline_iv=round(baseline_iv, 4),
            optimal_iv=round(baseline_iv, 4), iv_advantage_pct=0.0,
            distance_atr=round(short_mult, 2),
            rationale=f"Skew too flat ({relevant_skew:.1%}) — no adjustment from baseline",
        )

    skew_factor = min(relevant_skew / 0.10, 1.0)
    target_mult = short_mult + skew_factor * (max_distance_atr - short_mult)
    target_mult = max(min_distance_atr, min(target_mult, max_distance_atr))

    if option_type == "put":
        optimal_raw = underlying_price - (target_mult * atr)
    else:
        optimal_raw = underlying_price + (target_mult * atr)

    optimal_strike = snap_strike(optimal_raw, underlying_price)
    optimal_iv = skew.atm_iv + relevant_skew * (target_mult / 1.5)
    iv_advantage = (optimal_iv - baseline_iv) / baseline_iv * 100 if baseline_iv > 0 else 0.0

    return SkewOptimalStrike(
        option_type=option_type, baseline_strike=baseline_strike,
        optimal_strike=optimal_strike, baseline_iv=round(baseline_iv, 4),
        optimal_iv=round(optimal_iv, 4), iv_advantage_pct=round(iv_advantage, 1),
        distance_atr=round(target_mult, 2),
        rationale=(
            f"{optimal_strike} {option_type} IV {optimal_iv:.0%} vs baseline "
            f"{baseline_strike} IV {baseline_iv:.0%} — "
            f"{iv_advantage:.1f}% richer at {target_mult:.1f} ATR OTM"
        ),
    )


def score_entry_level(
    technicals: TechnicalSnapshot,
    levels: LevelsAnalysis,
    direction: str = "neutral",
) -> EntryLevelScore:
    """Multi-factor entry score combining RSI, Bollinger, VWAP, ATR extension, and level proximity.

    Weights: RSI=35%, Bollinger=30%, VWAP=10%, ATR_extension=15%, level_proximity=10%.
    RSI extremity uses a /20 divisor (sensitive to moderate overbought/oversold).
    Bollinger extremity uses a /0.30 divisor (sensitive to moderate %B deviation).
    Actions: >=0.70 = enter_now, >=0.40 = wait, <0.40 = not_yet.
    """
    price = technicals.current_price
    atr = technicals.atr
    rsi = technicals.rsi.value if technicals.rsi else 50.0
    percent_b = technicals.bollinger.percent_b if technicals.bollinger else 0.5
    vwap = technicals.vwma_20 if technicals.vwma_20 is not None else price
    sma_20 = (
        technicals.moving_averages.sma_20
        if technicals.moving_averages and technicals.moving_averages.sma_20 is not None
        else price
    )

    # RSI extremity — /20 divisor for sensitivity at moderate overbought/oversold
    if direction == "bullish":
        rsi_score = max(0.0, (50.0 - rsi) / 20.0)
    elif direction == "bearish":
        rsi_score = max(0.0, (rsi - 50.0) / 20.0)
    else:
        rsi_score = abs(rsi - 50.0) / 20.0
    rsi_score = min(1.0, rsi_score)

    # Bollinger %B extremity — /0.30 divisor for sensitivity
    if direction == "bullish":
        bb_score = max(0.0, (0.5 - percent_b) / 0.30)
    elif direction == "bearish":
        bb_score = max(0.0, (percent_b - 0.5) / 0.30)
    else:
        bb_score = abs(percent_b - 0.5) / 0.30
    bb_score = min(1.0, bb_score)

    # VWAP deviation
    vwap_score = min(1.0, abs(price - vwap) / atr / 2.0) if atr > 0 else 0.0

    # ATR extension from SMA-20
    atr_score = min(1.0, abs(price - sma_20) / atr / 1.5) if atr > 0 else 0.0

    # Level proximity
    if direction == "bullish":
        candidate_levels = list(levels.support_levels)
    elif direction == "bearish":
        candidate_levels = list(levels.resistance_levels)
    else:
        candidate_levels = list(levels.support_levels) + list(levels.resistance_levels)

    level_score = 0.0
    for lvl in candidate_levels:
        dist = abs(price - lvl.price)
        dist_atr = dist / atr if atr > 0 else float("inf")
        if dist_atr <= 1.0 and lvl.strength >= 0.5:
            prox = (1.0 - dist_atr) * lvl.strength
            if prox > level_score:
                level_score = prox

    # Weighted sum — RSI and Bollinger carry most weight as primary momentum signals
    overall = (
        rsi_score * 0.35
        + bb_score * 0.30
        + vwap_score * 0.10
        + atr_score * 0.15
        + level_score * 0.10
    )

    # Momentum safety: if MACD histogram is extreme against the entry direction,
    # cap the score to prevent "catching a falling knife" when selling is accelerating.
    macd_hist = technicals.macd.histogram if technicals.macd else 0.0
    atr_for_norm = atr if atr > 0 else 1.0
    momentum_z = abs(macd_hist) / atr_for_norm
    momentum_cap = 1.0
    momentum_override_note: str | None = None

    if direction == "bullish" and macd_hist < 0 and momentum_z > 1.0:
        # Strong selling momentum — cap score at "wait" threshold
        momentum_cap = 0.65
        momentum_override_note = (
            f"Momentum override: MACD hist {macd_hist:.2f} ({momentum_z:.1f}x ATR) — selling accelerating"
        )
    elif direction == "bearish" and macd_hist > 0 and momentum_z > 1.0:
        # Strong buying momentum — cap score at "wait" threshold
        momentum_cap = 0.65
        momentum_override_note = (
            f"Momentum override: MACD hist {macd_hist:.2f} ({momentum_z:.1f}x ATR) — buying accelerating"
        )

    overall = min(overall, momentum_cap)

    if overall >= 0.70:
        action = "enter_now"
    elif overall >= 0.40:
        action = "wait"
    else:
        action = "not_yet"

    rationale_parts = []
    if momentum_override_note:
        rationale_parts.append(momentum_override_note)
    if rsi_score > 0.5:
        rationale_parts.append(f"RSI {rsi:.0f} extremity ({rsi_score:.2f})")
    if bb_score > 0.5:
        rationale_parts.append(f"%B {percent_b:.2f} extremity ({bb_score:.2f})")
    if atr_score > 0.5:
        rationale_parts.append(f"Price extended from SMA-20 ({atr_score:.2f})")
    if level_score > 0.3:
        rationale_parts.append(f"Near key level ({level_score:.2f})")
    if not rationale_parts:
        rationale_parts.append("No strong entry signal")

    return EntryLevelScore(
        overall_score=round(overall, 4),
        action=action,
        components={
            "rsi_extremity": round(rsi_score, 4),
            "bollinger_extremity": round(bb_score, 4),
            "vwap_deviation": round(vwap_score, 4),
            "atr_extension": round(atr_score, 4),
            "level_proximity": round(level_score, 4),
        },
        rationale=" | ".join(rationale_parts),
    )


def compute_limit_entry_price(
    current_mid: float,
    bid_ask_spread: float,
    urgency: str = "normal",
    is_credit: bool = False,
) -> ConditionalEntry:
    """Compute limit order entry price based on urgency and order direction.

    Credits and debits have inverted urgency logic:
    - Debits:  patient=0.30 (save most), normal=0.10, aggressive=0.00 (pay mid)
    - Credits: patient=0.00 (hold at mid), normal=0.10, aggressive=0.30 (concede most)
    """
    if is_credit:
        factors = {"patient": 0.0, "normal": 0.10, "aggressive": 0.30}
    else:
        factors = {"patient": 0.30, "normal": 0.10, "aggressive": 0.0}

    factor = factors.get(urgency, 0.10)
    limit_price = current_mid - factor * bid_ask_spread

    # Determine entry mode
    if not is_credit and factor == 0.0:
        entry_mode = "market"
    else:
        entry_mode = "limit"

    # Improvement pct
    if current_mid > 0 and factor > 0:
        improvement_pct = round((current_mid - limit_price) / current_mid * 100, 2)
    else:
        improvement_pct = 0.0

    side = "credit" if is_credit else "debit"
    rationale = (
        f"{urgency.capitalize()} {side} entry: "
        f"limit at ${limit_price:.2f} "
        f"(mid ${current_mid:.2f} - {factor:.0%} of ${bid_ask_spread:.2f} spread)"
    )

    return ConditionalEntry(
        entry_mode=entry_mode,
        limit_price=round(limit_price, 4),
        current_mid=current_mid,
        improvement_pct=improvement_pct,
        urgency=urgency,
        rationale=rationale,
    )


def compute_pullback_levels(
    current_price: float,
    levels: LevelsAnalysis,
    atr: float,
    min_strength: float = 0.4,
    max_distance_atr: float = 2.0,
    min_roc_improvement_pct: float = 1.0,
) -> list[PullbackAlert]:
    """Compute pullback alert levels where patient entry would improve trade quality.

    Returns alerts sorted nearest first (highest alert_price first).
    Only considers support levels below current price within 2 ATR.
    """
    alerts: list[PullbackAlert] = []

    for lvl in levels.support_levels:
        # Only pullbacks below current price
        if lvl.price >= current_price:
            continue
        # Minimum strength filter
        if lvl.strength < min_strength:
            continue
        # Distance filter
        distance = current_price - lvl.price
        distance_atr = distance / atr if atr > 0 else float("inf")
        if distance_atr > max_distance_atr:
            continue
        # ROC improvement estimate
        roc_improvement = (distance / (atr * 0.5)) * 2.0
        if roc_improvement < min_roc_improvement_pct:
            continue

        source = lvl.sources[0].value if lvl.sources else "support"
        improvement_desc = (
            f"Pullback to {lvl.price:.1f} ({source}) improves short put placement "
            f"by ~{distance:.1f}pt ({distance_atr:.1f} ATR)"
        )

        alerts.append(PullbackAlert(
            alert_price=round(lvl.price, 2),
            current_price=current_price,
            level_source=source,
            level_strength=lvl.strength,
            improvement_description=improvement_desc,
            roc_improvement_pct=round(roc_improvement, 2),
        ))

    # Sort nearest first (highest alert_price first)
    alerts.sort(key=lambda a: a.alert_price, reverse=True)
    return alerts


# Ticker type -> (good_threshold, wait_threshold)
_IV_RANK_THRESHOLDS: dict[str, tuple[float, float]] = {
    "etf": (30.0, 20.0),
    "equity": (45.0, 30.0),
    "index": (25.0, 15.0),
}


def compute_iv_rank_quality(
    current_iv_rank: float,
    ticker_type: str = "etf",
) -> IVRankQuality:
    """Assess IV rank quality relative to ticker-type-specific thresholds.

    ETF IV is structurally lower — IV rank 30+ is already elevated.
    Individual equities need 45+ for equivalent signal quality.
    Indexes (SPX, NDX) run even lower — 25+ is meaningful.

    Args:
        current_iv_rank: Current IV rank (0-100 scale).
        ticker_type: "etf", "equity", or "index".

    Returns:
        IVRankQuality with quality assessment and thresholds.
    """
    ticker_type = ticker_type.lower()
    good_thresh, wait_thresh = _IV_RANK_THRESHOLDS.get(
        ticker_type, (30.0, 20.0),
    )

    if current_iv_rank >= good_thresh:
        quality = "good"
        rationale = (
            f"IV rank {current_iv_rank:.0f} >= {good_thresh:.0f} ({ticker_type}) — "
            f"elevated IV, good premium for income trades"
        )
    elif current_iv_rank >= wait_thresh:
        quality = "wait"
        rationale = (
            f"IV rank {current_iv_rank:.0f} in {wait_thresh:.0f}-{good_thresh:.0f} range ({ticker_type}) — "
            f"marginal premium, consider waiting for IV expansion"
        )
    else:
        quality = "avoid"
        rationale = (
            f"IV rank {current_iv_rank:.0f} < {wait_thresh:.0f} ({ticker_type}) — "
            f"low IV, poor premium for income trades"
        )

    return IVRankQuality(
        current_iv_rank=current_iv_rank,
        ticker_type=ticker_type,
        threshold_good=good_thresh,
        threshold_wait=wait_thresh,
        quality=quality,
        rationale=rationale,
    )
