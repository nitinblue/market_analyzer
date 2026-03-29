"""Calibration functions — pure computation for prediction accuracy tracking.

All functions are stateless. eTrading captures predictions and outcomes,
passes them in as lists, and receives calibration analysis back.
No I/O, no state, no side effects.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict

from income_desk.benchmarking.models import (
    CalibrationReport,
    OutcomeRecord,
    PopBucket,
    PredictionRecord,
    RegimeAccuracy,
)


def calibrate_pop(
    predictions: list[PredictionRecord],
    outcomes: list[OutcomeRecord],
    bucket_width: float = 10.0,
) -> list[PopBucket]:
    """Bucket trades by predicted POP range, compute actual win rate per bucket.

    Buckets: [40-50), [50-60), [60-70), [70-80), [80-90), [90-100]
    Only includes predictions that have pop_pct set.
    Matches predictions to outcomes by trade_id.
    """
    outcome_map: dict[str, OutcomeRecord] = {o.trade_id: o for o in outcomes}

    # Collect matched pairs with POP data
    bucket_data: dict[float, list[bool]] = defaultdict(list)
    for pred in predictions:
        if pred.pop_pct is None:
            continue
        outcome = outcome_map.get(pred.trade_id)
        if outcome is None:
            continue

        # Determine bucket lower bound
        # Clamp to [0, 100] range
        pop = max(0.0, min(100.0, pred.pop_pct))
        bucket_low = (pop // bucket_width) * bucket_width
        # Cap at 90 for the last bucket [90-100]
        if bucket_low >= 100.0:
            bucket_low = 100.0 - bucket_width
        bucket_data[bucket_low].append(outcome.is_win)

    # Build sorted buckets
    buckets: list[PopBucket] = []
    for low in sorted(bucket_data.keys()):
        wins = bucket_data[low]
        high = low + bucket_width
        mid = low + bucket_width / 2.0
        actual = (sum(wins) / len(wins)) * 100.0 if wins else 0.0
        buckets.append(
            PopBucket(
                predicted_low=low,
                predicted_high=high,
                predicted_mid=mid,
                actual_win_rate=actual,
                count=len(wins),
                error=actual - mid,
            )
        )

    return buckets


def regime_accuracy(
    predictions: list[PredictionRecord],
    outcomes: list[OutcomeRecord],
) -> list[RegimeAccuracy]:
    """For each regime, compute what % of trades had the same regime at exit.

    Only considers outcomes where regime_persisted is not None.
    """
    outcome_map: dict[str, OutcomeRecord] = {o.trade_id: o for o in outcomes}

    regime_stats: dict[int, dict[str, int]] = defaultdict(lambda: {"count": 0, "persisted": 0})

    for pred in predictions:
        outcome = outcome_map.get(pred.trade_id)
        if outcome is None:
            continue
        if outcome.regime_persisted is None:
            continue

        stats = regime_stats[pred.regime_id]
        stats["count"] += 1
        if outcome.regime_persisted:
            stats["persisted"] += 1

    results: list[RegimeAccuracy] = []
    for regime_id in sorted(regime_stats.keys()):
        stats = regime_stats[regime_id]
        rate = stats["persisted"] / stats["count"] if stats["count"] > 0 else 0.0
        results.append(
            RegimeAccuracy(
                regime_id=regime_id,
                count=stats["count"],
                persisted_count=stats["persisted"],
                persistence_rate=rate,
            )
        )

    return results


def score_vs_outcome(
    predictions: list[PredictionRecord],
    outcomes: list[OutcomeRecord],
) -> dict:
    """Compute correlation between composite_score and is_win.

    Returns: {correlation: float|None, avg_score_winners: float|None, avg_score_losers: float|None}
    Uses Pearson correlation from stdlib. No numpy needed.
    """
    outcome_map: dict[str, OutcomeRecord] = {o.trade_id: o for o in outcomes}

    scores: list[float] = []
    wins: list[float] = []
    winner_scores: list[float] = []
    loser_scores: list[float] = []

    for pred in predictions:
        if pred.composite_score is None:
            continue
        outcome = outcome_map.get(pred.trade_id)
        if outcome is None:
            continue

        scores.append(pred.composite_score)
        wins.append(1.0 if outcome.is_win else 0.0)
        if outcome.is_win:
            winner_scores.append(pred.composite_score)
        else:
            loser_scores.append(pred.composite_score)

    result: dict = {
        "correlation": None,
        "avg_score_winners": None,
        "avg_score_losers": None,
    }

    if winner_scores:
        result["avg_score_winners"] = statistics.mean(winner_scores)
    if loser_scores:
        result["avg_score_losers"] = statistics.mean(loser_scores)

    # Pearson correlation: need at least 2 data points and non-zero variance
    if len(scores) >= 2:
        try:
            result["correlation"] = statistics.correlation(scores, wins)
        except statistics.StatisticsError:
            # Zero variance in one of the series
            result["correlation"] = None

    return result


def generate_calibration_report(
    predictions: list[PredictionRecord],
    outcomes: list[OutcomeRecord],
    period: str = "",
) -> CalibrationReport:
    """Full calibration report combining all analyses.

    Joins predictions to outcomes by trade_id.
    Computes POP calibration, regime accuracy, score correlation, and overall stats.
    """
    outcome_map: dict[str, OutcomeRecord] = {o.trade_id: o for o in outcomes}

    # Only count trades that have both prediction and outcome
    matched_outcomes = [outcome_map[p.trade_id] for p in predictions if p.trade_id in outcome_map]
    total_trades = len(matched_outcomes)

    # POP calibration
    pop_buckets = calibrate_pop(predictions, outcomes)
    pop_rmse: float | None = None
    if pop_buckets:
        mse = sum(b.error**2 for b in pop_buckets) / len(pop_buckets)
        pop_rmse = math.sqrt(mse)

    # Regime accuracy
    regime_acc = regime_accuracy(predictions, outcomes)
    regime_persistence: float | None = None
    if regime_acc:
        total_regime = sum(r.count for r in regime_acc)
        total_persisted = sum(r.persisted_count for r in regime_acc)
        regime_persistence = total_persisted / total_regime if total_regime > 0 else None

    # Score correlation
    score_data = score_vs_outcome(predictions, outcomes)

    # Overall stats
    win_rate: float | None = None
    avg_pnl: float | None = None
    if matched_outcomes:
        win_rate = sum(1 for o in matched_outcomes if o.is_win) / len(matched_outcomes)
        avg_pnl = statistics.mean(o.pnl for o in matched_outcomes)

    # Build summary
    parts: list[str] = []
    if total_trades > 0:
        parts.append(f"{total_trades} trades analyzed")
    if win_rate is not None:
        parts.append(f"win rate {win_rate:.0%}")
    if pop_rmse is not None:
        parts.append(f"POP RMSE {pop_rmse:.1f}pp")
    if regime_persistence is not None:
        parts.append(f"regime persistence {regime_persistence:.0%}")
    summary = ", ".join(parts) if parts else "No data"

    return CalibrationReport(
        period=period,
        total_trades=total_trades,
        pop_buckets=pop_buckets,
        pop_rmse=pop_rmse,
        regime_persistence_rate=regime_persistence,
        regime_accuracy=regime_acc,
        score_win_correlation=score_data["correlation"],
        avg_score_winners=score_data["avg_score_winners"],
        avg_score_losers=score_data["avg_score_losers"],
        win_rate=win_rate,
        avg_pnl=avg_pnl,
        summary=summary,
    )
