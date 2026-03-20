"""Entry-level intelligence: strike proximity, skew selection, entry scoring.

Pure functions — no data fetching, no broker required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from market_analyzer.models.entry import (
    SkewOptimalStrike,
    StrikeProximityLeg,
    StrikeProximityResult,
)
from market_analyzer.models.vol_surface import SkewSlice

if TYPE_CHECKING:
    from market_analyzer.models.levels import LevelsAnalysis
    from market_analyzer.models.opportunity import TradeSpec


def compute_strike_support_proximity(
    trade_spec: TradeSpec,
    levels: LevelsAnalysis,
    atr: float,
    min_strength: float = 0.5,
    max_distance_atr: float = 1.0,
) -> StrikeProximityResult:
    from market_analyzer.models.opportunity import LegAction

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
    from market_analyzer.opportunity.option_plays._trade_spec_helpers import snap_strike

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
