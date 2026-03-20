"""Position-aware Kelly criterion sizing.

Pure functions — no data fetching, no broker required.
Computes optimal position size based on trade quality (POP, R:R),
current portfolio exposure, and drawdown state.
"""

from __future__ import annotations

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
