"""Position-aware Kelly criterion sizing.

Pure functions — no data fetching, no broker required.
Computes optimal position size based on trade quality (POP, R:R),
current portfolio exposure, and drawdown state.
"""

from __future__ import annotations

import math as _math
from typing import Callable

from pydantic import BaseModel


class KellyResult(BaseModel):
    """Result of Kelly criterion computation."""

    full_kelly_fraction: float  # Theoretical optimal bet fraction (0-1)
    half_kelly_fraction: float  # Conservative: full / 2 (industry standard)
    portfolio_adjusted_fraction: float  # After exposure + drawdown adjustment
    recommended_contracts: int  # Final integer answer
    max_contracts_by_risk: int  # Hard cap from risk budget
    rationale: str
    components: dict[str, float]  # Breakdown of adjustments


class PortfolioExposure(BaseModel):
    """Current portfolio state for Kelly adjustment."""

    open_position_count: int = 0
    max_positions: int = 5
    current_risk_pct: float = 0.0  # Total deployed risk as % of NLV (0-1)
    max_risk_pct: float = 0.25  # Max portfolio risk (25%)
    drawdown_pct: float = 0.0  # Current drawdown from peak (0-1)
    drawdown_halt_pct: float = 0.10  # Circuit breaker threshold


class CorrelationAdjustment(BaseModel):
    """Result of adjusting Kelly fraction for portfolio correlation."""

    original_kelly_fraction: float
    correlation_penalty: float
    adjusted_kelly_fraction: float
    correlated_pairs: list[tuple[str, str, float]]  # (ticker_a, ticker_b, corr)
    effective_position_count: float  # How many "unique" positions this represents
    rationale: str


class RegimeMarginEstimate(BaseModel):
    """Regime-adjusted buying power estimate per contract."""

    base_bp_per_contract: float
    regime_id: int
    regime_multiplier: float
    adjusted_bp_per_contract: float
    max_contracts_by_margin: int
    rationale: str


def compute_kelly_fraction(
    pop_pct: float,
    max_profit: float,
    max_loss: float,
) -> float:
    """Compute raw Kelly fraction from trade parameters.

    Kelly formula: f* = (p * b - (1-p)) / b
    where p = win probability, b = payoff ratio (profit/loss)

    Args:
        pop_pct: Probability of profit (0-1 fraction, NOT percentage)
        max_profit: Maximum profit in dollars
        max_loss: Maximum loss in dollars (positive number)

    Returns:
        Raw Kelly fraction (0-1). Negative means don't trade.
        Capped at 0.25 (never bet more than 25% on one trade).
    """
    if max_loss <= 0 or max_profit <= 0:
        return 0.0

    b = max_profit / max_loss  # Payoff ratio
    p = max(0.0, min(1.0, pop_pct))  # Clamp to valid range

    kelly = (p * b - (1 - p)) / b

    # Cap at 25% — never bet more than quarter of capital on one trade
    # Floor at 0 — negative Kelly means don't trade
    return max(0.0, min(kelly, 0.25))


def compute_kelly_position_size(
    capital: float,
    pop_pct: float,
    max_profit: float,
    max_loss: float,
    risk_per_contract: float,
    exposure: PortfolioExposure | None = None,
    safety_factor: float = 0.5,
    max_contracts: int = 50,
) -> KellyResult:
    """Compute position-aware Kelly-optimal position size.

    Args:
        capital: Account NLV in dollars.
        pop_pct: Probability of profit (0-1).
        max_profit: Max profit per contract in dollars.
        max_loss: Max loss per contract in dollars (positive).
        risk_per_contract: Capital at risk per contract (usually max_loss or wing_width * 100).
        exposure: Current portfolio state. None = no adjustment.
        safety_factor: Fraction of Kelly to use (0.5 = half Kelly, industry standard).
        max_contracts: Hard cap on contracts.

    Returns:
        KellyResult with full, adjusted, and recommended sizing.
    """
    # Step 1: Raw Kelly
    full_kelly = compute_kelly_fraction(pop_pct, max_profit, max_loss)
    half_kelly = full_kelly * safety_factor

    components: dict[str, float] = {
        "full_kelly": round(full_kelly, 4),
        "safety_factor": safety_factor,
        "after_safety": round(half_kelly, 4),
    }

    # Step 2: Portfolio exposure adjustment
    adjusted = half_kelly

    if exposure is not None:
        # Slots remaining
        slots_remaining = max(0, exposure.max_positions - exposure.open_position_count)
        if slots_remaining == 0:
            adjusted = 0.0
            components["slots_remaining"] = 0
        else:
            slot_factor = slots_remaining / exposure.max_positions
            components["slot_factor"] = round(slot_factor, 2)

        # Risk budget remaining
        risk_remaining = max(0.0, exposure.max_risk_pct - exposure.current_risk_pct)
        risk_factor = risk_remaining / exposure.max_risk_pct if exposure.max_risk_pct > 0 else 0
        adjusted *= risk_factor
        components["risk_remaining_pct"] = round(risk_remaining * 100, 1)
        components["risk_factor"] = round(risk_factor, 2)

        # Drawdown adjustment — scale down as drawdown increases
        if exposure.drawdown_pct >= exposure.drawdown_halt_pct:
            adjusted = 0.0
            components["drawdown_halt"] = 1.0
        elif exposure.drawdown_pct > 0:
            dd_factor = 1.0 - (exposure.drawdown_pct / exposure.drawdown_halt_pct)
            adjusted *= dd_factor
            components["drawdown_factor"] = round(dd_factor, 2)

    components["portfolio_adjusted"] = round(adjusted, 4)

    # Step 3: Convert fraction to contracts
    if adjusted <= 0 or risk_per_contract <= 0 or capital <= 0:
        recommended = 0
    else:
        kelly_dollars = capital * adjusted
        recommended = max(1, min(int(kelly_dollars / risk_per_contract), max_contracts))

    # Hard cap from risk budget (fallback safety)
    max_by_risk = int(capital * 0.02 / risk_per_contract) if risk_per_contract > 0 else 0
    max_by_risk = max(1, min(max_by_risk, max_contracts))

    # Never exceed the fixed-risk cap
    recommended = min(recommended, max_by_risk)

    # Rationale
    parts = []
    if full_kelly > 0:
        parts.append(f"Kelly {full_kelly:.1%}")
        parts.append(f"x{safety_factor} safety = {half_kelly:.1%}")
    else:
        parts.append("Kelly negative (EV-negative trade)")

    if exposure and exposure.drawdown_pct >= exposure.drawdown_halt_pct:
        parts.append("HALTED: drawdown circuit breaker")
    elif exposure and exposure.open_position_count >= exposure.max_positions:
        parts.append("HALTED: max positions reached")

    parts.append(f"-> {recommended} contracts")

    return KellyResult(
        full_kelly_fraction=round(full_kelly, 4),
        half_kelly_fraction=round(half_kelly, 4),
        portfolio_adjusted_fraction=round(adjusted, 4),
        recommended_contracts=recommended,
        max_contracts_by_risk=max_by_risk,
        rationale=" | ".join(parts),
        components=components,
    )


def compute_pairwise_correlation(
    returns_a: list[float],
    returns_b: list[float],
    lookback: int = 60,
) -> float:
    """Compute Pearson correlation between two return series.

    Pure Python — no pandas dependency. Uses last `lookback` values from
    each series. Both series must have at least `lookback` elements.

    Args:
        returns_a: Daily log returns for ticker A.
        returns_b: Daily log returns for ticker B.
        lookback: Number of trailing observations to use.

    Returns:
        Pearson correlation coefficient (-1.0 to 1.0).
        Returns 0.0 if insufficient data or zero variance.
    """
    n = min(len(returns_a), len(returns_b), lookback)
    if n < 5:
        return 0.0

    a = returns_a[-n:]
    b = returns_b[-n:]

    mean_a = sum(a) / n
    mean_b = sum(b) / n

    cov = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n)) / n
    var_a = sum((x - mean_a) ** 2 for x in a) / n
    var_b = sum((x - mean_b) ** 2 for x in b) / n

    if var_a <= 0 or var_b <= 0:
        return 0.0

    return max(-1.0, min(1.0, cov / _math.sqrt(var_a * var_b)))


def adjust_kelly_for_correlation(
    kelly_result: KellyResult,
    new_ticker: str,
    open_tickers: list[str],
    correlation_fn: Callable[[str, str], float],
) -> CorrelationAdjustment:
    """Reduce Kelly sizing when new trade is correlated with existing positions.

    Penalty logic: if max correlation with any existing position > 0.70,
    apply penalty = max_corr * 0.5 to reduce the kelly fraction.

    Args:
        kelly_result: Output from compute_kelly_position_size().
        new_ticker: Ticker being sized.
        open_tickers: List of tickers already in portfolio.
        correlation_fn: Callable(ticker_a, ticker_b) -> correlation float.

    Returns:
        CorrelationAdjustment with adjusted fraction and penalty details.
    """
    original = kelly_result.portfolio_adjusted_fraction
    pairs: list[tuple[str, str, float]] = []
    max_corr = 0.0

    for existing in open_tickers:
        if existing == new_ticker:
            continue
        corr = correlation_fn(new_ticker, existing)
        pairs.append((new_ticker, existing, round(corr, 4)))
        max_corr = max(max_corr, corr)

    penalty = max_corr * 0.5 if max_corr > 0.70 else 0.0
    adjusted = original * (1 - penalty)

    # Effective position count: 1 / (1 - penalty) when correlated
    effective_count = 1.0 / (1.0 - penalty) if penalty < 1.0 else float("inf")

    if penalty > 0:
        rationale = (
            f"Max correlation {max_corr:.2f} with existing positions — "
            f"{penalty:.0%} penalty applied. Effective position count: {effective_count:.1f}"
        )
    else:
        rationale = "No significant correlation with existing positions — no penalty"

    return CorrelationAdjustment(
        original_kelly_fraction=round(original, 4),
        correlation_penalty=round(penalty, 4),
        adjusted_kelly_fraction=round(adjusted, 4),
        correlated_pairs=pairs,
        effective_position_count=round(effective_count, 2),
        rationale=rationale,
    )


_REGIME_MARGIN_MULTIPLIERS: dict[int, tuple[float, str]] = {
    1: (1.0, "R1 standard margin"),
    2: (1.3, "R2 high-vol: broker raises margin ~30%"),
    3: (1.1, "R3 trending: slight margin increase"),
    4: (1.5, "R4 explosive: maximum margin expansion"),
}


def compute_regime_adjusted_bp(
    wing_width: float,
    regime_id: int,
    lot_size: int = 100,
    available_bp: float | None = None,
) -> RegimeMarginEstimate:
    """Compute regime-aware buying power requirement per contract.

    In high-vol regimes, brokers typically expand margin requirements.
    This estimates the effective BP needed so position sizing doesn't
    over-allocate.

    Args:
        wing_width: Spread width in points (e.g., 5.0 for 5-wide IC).
        regime_id: Current regime (1-4).
        lot_size: Options multiplier (default 100).
        available_bp: Available buying power (optional, for max contracts).

    Returns:
        RegimeMarginEstimate with adjusted BP per contract.
    """
    base_bp = wing_width * lot_size
    multiplier, rationale = _REGIME_MARGIN_MULTIPLIERS.get(
        regime_id, (1.0, f"Unknown regime R{regime_id}: standard margin"),
    )
    adjusted_bp = base_bp * multiplier

    max_contracts = 0
    if available_bp is not None and adjusted_bp > 0:
        max_contracts = int(available_bp / adjusted_bp)

    return RegimeMarginEstimate(
        base_bp_per_contract=base_bp,
        regime_id=regime_id,
        regime_multiplier=multiplier,
        adjusted_bp_per_contract=adjusted_bp,
        max_contracts_by_margin=max_contracts,
        rationale=rationale,
    )


def compute_position_size(
    pop_pct: float,
    max_profit: float,
    max_loss: float,
    capital: float,
    risk_per_contract: float,
    regime_id: int = 1,
    wing_width: float = 5.0,
    exposure: PortfolioExposure | None = None,
    open_tickers: list[str] | None = None,
    new_ticker: str = "",
    correlation_fn: Callable[[str, str], float] | None = None,
    safety_factor: float = 0.5,
    max_contracts: int = 50,
) -> KellyResult:
    """Unified position sizing: Kelly -> correlation -> regime margin -> final.

    This is the master sizing function that chains all sizing intelligence:
    1. compute_kelly_position_size() — raw Kelly from POP and R:R
    2. adjust_kelly_for_correlation() — reduce for correlated positions
    3. compute_regime_adjusted_bp() — cap by regime-aware margin
    4. Return final KellyResult with all adjustments shown

    Args:
        pop_pct: Probability of profit (0-1 fraction).
        max_profit: Max profit per contract in dollars.
        max_loss: Max loss per contract in dollars (positive).
        capital: Account NLV in dollars.
        risk_per_contract: Capital at risk per contract.
        regime_id: Current regime (1-4).
        wing_width: Spread width in points for margin calculation.
        exposure: Current portfolio state. None = no adjustment.
        open_tickers: Tickers currently in portfolio (for correlation check).
        new_ticker: Ticker being sized (for correlation check).
        correlation_fn: Callable(ticker_a, ticker_b) -> correlation.
        safety_factor: Fraction of Kelly to use (default 0.5 = half Kelly).
        max_contracts: Hard cap on contracts.

    Returns:
        KellyResult with all adjustments reflected.
    """
    # Step 1: Base Kelly
    kelly = compute_kelly_position_size(
        capital=capital,
        pop_pct=pop_pct,
        max_profit=max_profit,
        max_loss=max_loss,
        risk_per_contract=risk_per_contract,
        exposure=exposure,
        safety_factor=safety_factor,
        max_contracts=max_contracts,
    )

    # Step 2: Correlation adjustment
    corr_adj: CorrelationAdjustment | None = None
    if open_tickers and correlation_fn and new_ticker:
        corr_adj = adjust_kelly_for_correlation(
            kelly, new_ticker, open_tickers, correlation_fn,
        )

    # Step 3: Regime margin cap
    margin = compute_regime_adjusted_bp(
        wing_width, regime_id, available_bp=capital * 0.25,
    )

    # Compose final recommendation
    effective_fraction = kelly.portfolio_adjusted_fraction
    components = dict(kelly.components)

    if corr_adj is not None and corr_adj.correlation_penalty > 0:
        effective_fraction = corr_adj.adjusted_kelly_fraction
        components["correlation_penalty"] = corr_adj.correlation_penalty
        components["after_correlation"] = round(effective_fraction, 4)

    # Convert fraction to contracts
    if effective_fraction <= 0 or risk_per_contract <= 0 or capital <= 0:
        recommended = 0
    else:
        kelly_dollars = capital * effective_fraction
        recommended = max(1, min(int(kelly_dollars / risk_per_contract), max_contracts))

    # Cap by regime-adjusted margin
    if margin.max_contracts_by_margin > 0:
        recommended = min(recommended, margin.max_contracts_by_margin)
        components["regime_margin_cap"] = margin.max_contracts_by_margin

    # Cap by base risk limit
    max_by_risk = kelly.max_contracts_by_risk
    recommended = min(recommended, max_by_risk)

    # Build rationale
    parts = [kelly.rationale.split(" -> ")[0]]  # Base Kelly part
    if corr_adj and corr_adj.correlation_penalty > 0:
        parts.append(f"corr penalty -{corr_adj.correlation_penalty:.0%}")
    parts.append(f"R{regime_id} margin {margin.regime_multiplier:.1f}x")
    parts.append(f"-> {recommended} contracts")

    return KellyResult(
        full_kelly_fraction=kelly.full_kelly_fraction,
        half_kelly_fraction=kelly.half_kelly_fraction,
        portfolio_adjusted_fraction=round(effective_fraction, 4),
        recommended_contracts=recommended,
        max_contracts_by_risk=max_by_risk,
        rationale=" | ".join(parts),
        components=components,
    )


from market_analyzer.models.adjustment import AdjustmentEffectiveness, AdjustmentOutcome  # noqa: E402


def analyze_adjustment_effectiveness(
    outcomes: list[AdjustmentOutcome],
) -> AdjustmentEffectiveness:
    """Analyze historical adjustment outcomes to learn which adjustments work.

    Groups outcomes by adjustment type and regime, computes win rates and
    average P&L, and generates actionable recommendations.

    Args:
        outcomes: List of past adjustment outcomes.

    Returns:
        AdjustmentEffectiveness with per-type and per-regime statistics.
    """
    if not outcomes:
        return AdjustmentEffectiveness(
            by_type={}, by_regime={}, recommendations=["No adjustment data available"],
            total_outcomes=0,
        )

    # Group by type
    by_type: dict[str, list[AdjustmentOutcome]] = {}
    for o in outcomes:
        by_type.setdefault(o.adjustment_type, []).append(o)

    type_stats: dict[str, dict] = {}
    for adj_type, type_outcomes in by_type.items():
        wins = sum(1 for o in type_outcomes if o.was_profitable)
        total = len(type_outcomes)
        type_stats[adj_type] = {
            "count": total,
            "win_rate": round(wins / total, 2) if total > 0 else 0.0,
            "avg_cost": round(sum(o.cost for o in type_outcomes) / total, 2),
            "avg_subsequent_pnl": round(sum(o.subsequent_pnl for o in type_outcomes) / total, 2),
        }

    # Group by regime
    by_regime_raw: dict[int, list[AdjustmentOutcome]] = {}
    for o in outcomes:
        by_regime_raw.setdefault(o.regime_at_adjustment, []).append(o)

    regime_stats: dict[int, dict] = {}
    for regime_id, regime_outcomes in by_regime_raw.items():
        # Find best adjustment type for this regime
        regime_by_type: dict[str, list[AdjustmentOutcome]] = {}
        for o in regime_outcomes:
            regime_by_type.setdefault(o.adjustment_type, []).append(o)

        best_type = ""
        best_rate = 0.0
        for adj_type, adj_outcomes in regime_by_type.items():
            wins = sum(1 for o in adj_outcomes if o.was_profitable)
            rate = wins / len(adj_outcomes) if adj_outcomes else 0.0
            if rate > best_rate:
                best_rate = rate
                best_type = adj_type

        regime_stats[regime_id] = {
            "count": len(regime_outcomes),
            "best_type": best_type,
            "best_win_rate": round(best_rate, 2),
        }

    # Generate recommendations
    recommendations: list[str] = []
    for adj_type, stats in type_stats.items():
        if stats["count"] >= 3:
            rate_pct = stats["win_rate"] * 100
            if stats["win_rate"] >= 0.60:
                recommendations.append(
                    f"{adj_type.upper()} wins {rate_pct:.0f}% of the time "
                    f"(n={stats['count']}, avg P&L ${stats['avg_subsequent_pnl']:.0f})"
                )
            elif stats["win_rate"] < 0.40:
                recommendations.append(
                    f"Avoid {adj_type.upper()} — only {rate_pct:.0f}% win rate "
                    f"(n={stats['count']})"
                )

    if not recommendations:
        recommendations.append("Insufficient data for reliable recommendations (need 3+ per type)")

    return AdjustmentEffectiveness(
        by_type=type_stats,
        by_regime=regime_stats,
        recommendations=recommendations,
        total_outcomes=len(outcomes),
    )
