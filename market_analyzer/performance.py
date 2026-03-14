"""Performance analysis and weight calibration from trade outcomes.

All functions are pure computation. eTrading stores TradeOutcome records,
passes them to these functions, and receives performance reports and
weight calibration suggestions.

No state, no I/O, no side effects.
"""

from __future__ import annotations

import math
from collections import defaultdict

from market_analyzer.features.ranking import REGIME_STRATEGY_ALIGNMENT
from market_analyzer.models.feedback import (
    CalibrationResult,
    PerformanceReport,
    StrategyPerformance,
    TradeOutcome,
    WeightAdjustment,
)
from market_analyzer.models.ranking import StrategyType


def _compute_stats(
    outcomes: list[TradeOutcome],
    strategy_type: StrategyType,
    regime_id: int | None,
) -> StrategyPerformance:
    """Compute performance stats from a list of outcomes.

    All outcomes should already be filtered to the desired
    strategy_type and regime_id before calling.
    """
    total = len(outcomes)
    if total == 0:
        return StrategyPerformance(
            strategy_type=strategy_type,
            regime_id=regime_id,
            total_trades=0,
            wins=0,
            losses=0,
            win_rate=0.0,
            avg_pnl_pct=0.0,
            avg_win_pct=0.0,
            avg_loss_pct=0.0,
            total_pnl_dollars=0.0,
            avg_holding_days=0.0,
            profit_factor=0.0,
            best_trade_pnl_pct=0.0,
            worst_trade_pnl_pct=0.0,
            avg_score_at_entry=0.0,
        )

    wins = [o for o in outcomes if o.pnl_dollars > 0]
    losses = [o for o in outcomes if o.pnl_dollars <= 0]

    gross_profit = sum(o.pnl_dollars for o in wins)
    gross_loss = abs(sum(o.pnl_dollars for o in losses))

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0

    win_pcts = [o.pnl_pct for o in wins]
    loss_pcts = [o.pnl_pct for o in losses]

    # Compute optional averages from new fields (only if data present)
    dte_values = [o.dte_at_entry for o in outcomes if o.dte_at_entry is not None]
    avg_dte = sum(dte_values) / len(dte_values) if dte_values else None

    iv_values = [o.iv_rank_at_entry for o in outcomes if o.iv_rank_at_entry is not None]
    avg_iv = sum(iv_values) / len(iv_values) if iv_values else None

    return StrategyPerformance(
        strategy_type=strategy_type,
        regime_id=regime_id,
        total_trades=total,
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / total,
        avg_pnl_pct=sum(o.pnl_pct for o in outcomes) / total,
        avg_win_pct=sum(win_pcts) / len(win_pcts) if win_pcts else 0.0,
        avg_loss_pct=sum(loss_pcts) / len(loss_pcts) if loss_pcts else 0.0,
        total_pnl_dollars=sum(o.pnl_dollars for o in outcomes),
        avg_holding_days=sum(o.holding_days for o in outcomes) / total,
        profit_factor=profit_factor,
        best_trade_pnl_pct=max(o.pnl_pct for o in outcomes),
        worst_trade_pnl_pct=min(o.pnl_pct for o in outcomes),
        avg_score_at_entry=sum(o.composite_score_at_entry for o in outcomes) / total,
        avg_dte_at_entry=avg_dte,
        avg_iv_rank_at_entry=avg_iv,
    )


def compute_strategy_performance(
    outcomes: list[TradeOutcome],
    strategy_type: StrategyType | None = None,
    regime_id: int | None = None,
) -> StrategyPerformance:
    """Compute performance stats for a strategy, optionally filtered by regime.

    Args:
        outcomes: List of completed trade outcomes.
        strategy_type: Filter to this strategy. If None, uses the strategy_type
            of the first outcome (all outcomes should be same type).
        regime_id: Filter to outcomes where regime_at_entry matches.
            None means all regimes combined.

    Returns:
        StrategyPerformance with win rate, PnL, profit factor, etc.
    """
    filtered = outcomes

    if strategy_type is not None:
        filtered = [o for o in filtered if o.strategy_type == strategy_type]

    if regime_id is not None:
        filtered = [o for o in filtered if o.regime_at_entry == regime_id]

    # Determine the strategy_type for the result
    st = strategy_type
    if st is None and filtered:
        st = filtered[0].strategy_type
    if st is None:
        st = StrategyType.ZERO_DTE  # fallback for empty list

    return _compute_stats(filtered, st, regime_id)


def _pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Compute Pearson correlation coefficient.

    Returns None if fewer than 5 data points or zero variance.
    """
    n = len(xs)
    if n < 5 or n != len(ys):
        return None

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)

    denom = math.sqrt(var_x * var_y)
    if denom == 0:
        return None

    return cov / denom


def compute_performance_report(
    outcomes: list[TradeOutcome],
) -> PerformanceReport:
    """Full performance analysis across all strategies and regimes.

    Args:
        outcomes: All completed trade outcomes to analyze.

    Returns:
        PerformanceReport with per-strategy stats, per-regime breakdowns,
        and score-to-PnL correlation.
    """
    if not outcomes:
        return PerformanceReport(
            total_trades=0,
            total_pnl_dollars=0.0,
            overall_win_rate=0.0,
            by_strategy=[],
            by_regime={},
            score_correlation=None,
            summary="No trade outcomes to analyze.",
        )

    # Group by strategy
    by_strat: dict[StrategyType, list[TradeOutcome]] = defaultdict(list)
    for o in outcomes:
        by_strat[o.strategy_type].append(o)

    strategy_perfs: list[StrategyPerformance] = []
    for st in sorted(by_strat.keys(), key=lambda s: s.value):
        strategy_perfs.append(_compute_stats(by_strat[st], st, regime_id=None))

    # Group by regime x strategy
    by_regime: dict[int, list[StrategyPerformance]] = {}
    regime_ids = sorted({o.regime_at_entry for o in outcomes})
    for rid in regime_ids:
        regime_outcomes = [o for o in outcomes if o.regime_at_entry == rid]
        regime_strats: dict[StrategyType, list[TradeOutcome]] = defaultdict(list)
        for o in regime_outcomes:
            regime_strats[o.strategy_type].append(o)

        regime_perfs: list[StrategyPerformance] = []
        for st in sorted(regime_strats.keys(), key=lambda s: s.value):
            regime_perfs.append(_compute_stats(regime_strats[st], st, regime_id=rid))
        by_regime[rid] = regime_perfs

    # Score correlation
    scores = [o.composite_score_at_entry for o in outcomes]
    pnls = [o.pnl_pct for o in outcomes]
    score_corr = _pearson_correlation(scores, pnls)

    # Overall stats
    total = len(outcomes)
    wins = sum(1 for o in outcomes if o.pnl_dollars > 0)
    total_pnl = sum(o.pnl_dollars for o in outcomes)

    # Build summary
    best_strat = max(strategy_perfs, key=lambda s: s.win_rate) if strategy_perfs else None
    worst_strat = min(strategy_perfs, key=lambda s: s.win_rate) if strategy_perfs else None

    lines = [
        f"{total} trades, {wins}/{total} wins ({wins / total:.0%}), "
        f"total PnL ${total_pnl:+,.0f}.",
    ]
    if best_strat and best_strat.total_trades > 0:
        lines.append(
            f"Best strategy: {best_strat.strategy_type.value} "
            f"({best_strat.win_rate:.0%} win rate, {best_strat.total_trades} trades)."
        )
    if worst_strat and worst_strat.total_trades > 0 and worst_strat != best_strat:
        lines.append(
            f"Worst strategy: {worst_strat.strategy_type.value} "
            f"({worst_strat.win_rate:.0%} win rate, {worst_strat.total_trades} trades)."
        )
    if score_corr is not None:
        direction = "positive" if score_corr > 0 else "negative"
        strength = (
            "strong" if abs(score_corr) > 0.5
            else "moderate" if abs(score_corr) > 0.3
            else "weak"
        )
        lines.append(
            f"Score-PnL correlation: {score_corr:+.2f} ({strength} {direction})."
        )

    # POP accuracy by regime: what % of trades won in each regime?
    pop_accuracy: dict[int, float] = {}
    for regime_id_val in range(1, 5):
        regime_trades = [o for o in outcomes if o.regime_at_entry == regime_id_val]
        if len(regime_trades) >= 5:
            regime_wins = sum(1 for t in regime_trades if t.pnl_pct > 0)
            pop_accuracy[regime_id_val] = round(regime_wins / len(regime_trades), 3)

    return PerformanceReport(
        total_trades=total,
        total_pnl_dollars=total_pnl,
        overall_win_rate=wins / total,
        by_strategy=strategy_perfs,
        by_regime=by_regime,
        score_correlation=score_corr,
        summary=" ".join(lines),
        pop_accuracy=pop_accuracy if pop_accuracy else None,
    )


def calibrate_weights(
    outcomes: list[TradeOutcome],
    min_trades: int = 10,
    max_adjustment: float = 0.2,
) -> CalibrationResult:
    """Suggest weight adjustments based on actual trade performance.

    Compares actual win rates per (regime, strategy) cell against
    the current REGIME_STRATEGY_ALIGNMENT weights. If a strategy
    consistently wins in a regime where the weight is low, suggest
    increasing it (and vice versa).

    Uses REGIME_STRATEGY_ALIGNMENT from features/ranking.py as the baseline.

    Args:
        outcomes: Completed trade outcomes to analyze.
        min_trades: Minimum trades per (regime, strategy) cell to suggest
            an adjustment. Cells with fewer trades are skipped.
        max_adjustment: Maximum change in weight from current value.
            Prevents wild swings from small sample sizes.

    Returns:
        CalibrationResult with suggested weight adjustments and summary.
    """
    if not outcomes:
        return CalibrationResult(
            adjustments=[],
            summary="No trade outcomes for calibration.",
        )

    # Group outcomes by (regime, strategy)
    cells: dict[tuple[int, StrategyType], list[TradeOutcome]] = defaultdict(list)
    for o in outcomes:
        cells[(o.regime_at_entry, o.strategy_type)].append(o)

    adjustments: list[WeightAdjustment] = []

    for (regime_id, strategy_type), cell_outcomes in sorted(cells.items()):
        if len(cell_outcomes) < min_trades:
            continue

        wins = sum(1 for o in cell_outcomes if o.pnl_dollars > 0)
        actual_win_rate = wins / len(cell_outcomes)

        current_weight = REGIME_STRATEGY_ALIGNMENT.get(
            (regime_id, strategy_type), 0.5
        )

        # Only suggest adjustment if win rate differs significantly
        # from current weight (threshold: 0.1)
        diff = actual_win_rate - current_weight
        if abs(diff) <= 0.1:
            continue

        # Blend: 70% actual performance + 30% current weight
        blended = actual_win_rate * 0.7 + current_weight * 0.3

        # Clamp to [0.0, 1.0]
        blended = max(0.0, min(1.0, blended))

        # Clamp change to max_adjustment
        change = blended - current_weight
        if abs(change) > max_adjustment:
            change = max_adjustment if change > 0 else -max_adjustment
            blended = current_weight + change

        # Final clamp
        blended = max(0.0, min(1.0, blended))

        if diff > 0:
            reason = (
                f"Win rate {actual_win_rate:.0%} exceeds current weight "
                f"{current_weight:.2f} in R{regime_id} "
                f"({len(cell_outcomes)} trades). Suggest increase."
            )
        else:
            reason = (
                f"Win rate {actual_win_rate:.0%} below current weight "
                f"{current_weight:.2f} in R{regime_id} "
                f"({len(cell_outcomes)} trades). Suggest decrease."
            )

        adjustments.append(
            WeightAdjustment(
                regime_id=regime_id,
                strategy_type=strategy_type,
                current_weight=current_weight,
                suggested_weight=round(blended, 3),
                reason=reason,
            )
        )

    # Build summary
    if not adjustments:
        summary = (
            f"Analyzed {len(outcomes)} trades across "
            f"{len(cells)} regime-strategy cells. "
            f"No adjustments needed (all within 0.1 of current weights, "
            f"or fewer than {min_trades} trades per cell)."
        )
    else:
        increases = sum(1 for a in adjustments if a.suggested_weight > a.current_weight)
        decreases = len(adjustments) - increases
        summary = (
            f"Analyzed {len(outcomes)} trades. "
            f"{len(adjustments)} adjustments suggested: "
            f"{increases} increases, {decreases} decreases. "
            f"Max adjustment clamped to +/-{max_adjustment:.2f}."
        )

    return CalibrationResult(adjustments=adjustments, summary=summary)


def calibrate_pop_factors(
    outcomes: list[TradeOutcome],
    min_trades_per_regime: int = 10,
) -> dict[int, float]:
    """Compute regime-specific move factors from actual trade outcomes.

    Compares the actual price moves during trades against ATR predictions
    to calibrate the regime factors used in estimate_pop().

    Current hard-coded factors: {1: 0.40, 2: 0.70, 3: 1.10, 4: 1.50}

    Returns:
        dict mapping regime_id to calibrated factor. Only includes regimes
        with >= min_trades_per_regime outcomes. Missing regimes should use
        the default hard-coded factors.
    """
    # Group outcomes by entry regime
    by_regime: dict[int, list[TradeOutcome]] = defaultdict(list)
    for o in outcomes:
        by_regime[o.regime_at_entry].append(o)

    default_factors = {1: 0.40, 2: 0.70, 3: 1.10, 4: 1.50}
    calibrated: dict[int, float] = {}

    for regime_id, trades in by_regime.items():
        if len(trades) < min_trades_per_regime:
            continue

        default = default_factors.get(regime_id, 0.70)

        # Win rate as signal: high win rate means factor is too conservative
        # (actual moves smaller than predicted), low win rate means factor
        # is too aggressive (actual moves larger than predicted)
        wins = sum(1 for t in trades if t.pnl_pct > 0)
        win_rate = wins / len(trades)

        # If 70% POP trades are winning 80% -> factor is conservative, reduce it
        # If 70% POP trades are winning 50% -> factor is aggressive, increase it
        # Win rate 0.8 -> trades staying in range more -> reduce factor (moves smaller)
        # Win rate 0.4 -> trades breaking out more -> increase factor (moves larger)
        actual_signal = 1.0 - win_rate  # Higher win rate = smaller actual moves
        # Scale to factor range (0.2 to 2.0)
        actual_factor = 0.2 + actual_signal * 1.8

        # Blend: 60% actual signal + 40% current factor
        calibrated_factor = actual_factor * 0.6 + default * 0.4
        # Clamp to reasonable range
        calibrated_factor = max(0.15, min(2.0, calibrated_factor))

        calibrated[regime_id] = round(calibrated_factor, 3)

    return calibrated
