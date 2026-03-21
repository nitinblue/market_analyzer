"""Pure functions for portfolio desk management and capital allocation.

All functions are stateless — no I/O, no broker calls, no side effects.
They accept data and return structured recommendations for eTrading to act on.
"""
from __future__ import annotations

from market_analyzer.models.portfolio import (
    DeskAdjustment,
    DeskHealth,
    DeskHealthReport,
    DeskRecommendation,
    DeskRiskLimits,
    DeskSpec,
    InstrumentRisk,
    RebalanceRecommendation,
    RiskTolerance,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_US_INCOME_UNDERLYINGS = ["SPY", "QQQ", "IWM", "GLD", "TLT", "IEF", "XLF", "EEM"]
_US_CORE_UNDERLYINGS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN"]
_US_0DTE_UNDERLYINGS = ["SPY", "QQQ", "IWM"]
_US_DIRECTIONAL_UNDERLYINGS = ["SPY", "QQQ", "IWM", "AAPL", "NVDA", "META", "TSLA"]
_US_GROWTH_UNDERLYINGS = ["QQQ", "AAPL", "NVDA", "META", "TSLA", "AMZN"]

_INDIA_EXPIRY_UNDERLYINGS = ["NIFTY", "BANKNIFTY"]
_INDIA_INCOME_UNDERLYINGS = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
_INDIA_CORE_UNDERLYINGS = ["NIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK"]


def _dominant_regime(regime: dict[str, int] | None) -> int | None:
    """Return the most common regime value, or the max if tied."""
    if not regime:
        return None
    values = list(regime.values())
    if not values:
        return None
    # Return max regime (most adverse for safety)
    from collections import Counter
    counts = Counter(values)
    most_common_val, most_common_count = counts.most_common(1)[0]
    # If R4 appears anywhere, treat it as dominant for risk purposes
    if 4 in counts:
        return 4
    return most_common_val


def _has_any_regime(regime: dict[str, int] | None, target: int) -> bool:
    if not regime:
        return False
    return any(v == target for v in regime.values())


def _majority_regime(regime: dict[str, int] | None, target: int) -> bool:
    """True if more than half of tickers are in the target regime."""
    if not regime:
        return False
    values = list(regime.values())
    return values.count(target) > len(values) / 2


def _build_risk_limits(
    desk_key: str,
    max_positions: int,
    max_single_pct: float,
    circuit_breaker_pct: float,
    max_delta: float = 0.30,
    max_daily_loss_pct: float = 0.02,
    max_correlated: int = 3,
    size_factor: float = 1.0,
) -> dict:
    return {
        "max_positions": max_positions,
        "max_single_position_pct": max_single_pct,
        "circuit_breaker_pct": circuit_breaker_pct,
        "max_portfolio_delta": max_delta,
        "max_daily_loss_pct": max_daily_loss_pct,
        "max_correlated_positions": max_correlated,
        "position_size_factor": size_factor,
    }


# ---------------------------------------------------------------------------
# 1. recommend_desk_structure
# ---------------------------------------------------------------------------

def recommend_desk_structure(
    total_capital: float,
    risk_tolerance: str = "moderate",
    market: str = "US",
    regime: dict[str, int] | None = None,
    existing_desks: list[dict] | None = None,
    broker_capabilities: list[str] | None = None,
) -> DeskRecommendation:
    """Recommend a desk structure (capital allocation per trading style).

    Pure function — no broker calls, no I/O.

    Args:
        total_capital: Total investable capital (USD or local currency).
        risk_tolerance: "conservative" | "moderate" | "aggressive"
        market: "US" | "India"
        regime: Current regime map {ticker: regime_id}. Used to adjust allocations.
        existing_desks: Currently active desks (used to avoid disrupting live positions).
        broker_capabilities: List of capabilities broker supports (e.g. ["naked_options"]).

    Returns:
        DeskRecommendation with per-desk specs summing to total_capital.
    """
    tol = risk_tolerance.lower()
    mkt = market.upper()
    dominant = _dominant_regime(regime)

    # ── Base allocations by tolerance ────────────────────────────────────────
    if tol == RiskTolerance.CONSERVATIVE:
        cash_reserve_pct = 0.10
        desks_raw = _conservative_desks(total_capital, cash_reserve_pct, mkt)
    elif tol == RiskTolerance.AGGRESSIVE:
        cash_reserve_pct = 0.05
        desks_raw = _aggressive_desks(total_capital, cash_reserve_pct, mkt)
    else:  # moderate (default)
        cash_reserve_pct = 0.08
        desks_raw = _moderate_desks(total_capital, cash_reserve_pct, mkt)

    # ── Regime adjustments ────────────────────────────────────────────────────
    regime_context = "No regime data — using base allocations."
    if dominant == 4:
        # R4: increase cash, reduce 0DTE and directional by 50%
        cash_reserve_pct = min(cash_reserve_pct + 0.15, 0.30)
        desks_raw = _apply_r4_adjustment(desks_raw, total_capital, cash_reserve_pct)
        regime_context = (
            "R4 (High-Vol Trending) detected — cash reserve increased to "
            f"{cash_reserve_pct:.0%}, 0DTE/directional desks halved."
        )
    elif dominant == 2 and _majority_regime(regime, 2):
        # R2 across board: reduce 0DTE by 25%, increase income
        desks_raw = _apply_r2_adjustment(desks_raw, total_capital, cash_reserve_pct)
        regime_context = "R2 (High-Vol Mean Reverting) majority — 0DTE reduced, income desk expanded."
    elif dominant == 3:
        # R3: increase directional, reduce pure income
        desks_raw = _apply_r3_adjustment(desks_raw, total_capital, cash_reserve_pct)
        regime_context = "R3 (Low-Vol Trending) detected — directional desk expanded, income reduced."
    elif dominant is not None:
        regime_context = f"R{dominant} detected — base allocations suitable."

    # ── Compute cash reserve ──────────────────────────────────────────────────
    allocated = sum(d.capital_allocation for d in desks_raw)
    unallocated = total_capital - allocated

    # ── Build rationale ───────────────────────────────────────────────────────
    rationale = (
        f"{risk_tolerance.capitalize()} desk structure for {mkt} market. "
        f"Cash reserve: {cash_reserve_pct:.0%} (${unallocated:,.0f}). "
        f"{len(desks_raw)} active desks covering income, core, and "
        + ("expiry-day" if mkt == "INDIA" else "0DTE")
        + " strategies."
    )

    return DeskRecommendation(
        desks=desks_raw,
        total_capital=total_capital,
        unallocated_cash=unallocated,
        cash_reserve_pct=cash_reserve_pct,
        rationale=rationale,
        regime_context=regime_context,
    )


def _conservative_desks(total: float, cash_pct: float, market: str) -> list[DeskSpec]:
    allocated = total * (1 - cash_pct)
    if market == "INDIA":
        return _india_desks(total, cash_pct, allow_undefined=False)

    income_alloc = allocated * (0.40 / 0.90)   # 40% of total
    core_alloc = allocated * (0.40 / 0.90)     # 40% of total
    dte0_alloc = allocated * (0.10 / 0.90)     # 10% of total

    # Normalize to (1 - cash_pct)
    income_alloc = total * 0.40
    core_alloc = total * 0.40
    dte0_alloc = total * 0.10

    return [
        DeskSpec(
            desk_key="desk_0dte",
            name="0DTE Income",
            capital_allocation=dte0_alloc,
            capital_pct=0.10,
            dte_min=0,
            dte_max=0,
            preferred_underlyings=_US_0DTE_UNDERLYINGS,
            strategy_types=["iron_condor", "credit_spread"],
            max_positions=2,
            risk_limits=_build_risk_limits("desk_0dte", 2, 0.10, 0.05),
            instrument_type="options",
            allow_undefined_risk=False,
            rationale="Conservative 0DTE: only R1/R2 regimes, defined risk, small allocation.",
        ),
        DeskSpec(
            desk_key="desk_income",
            name="Medium-Term Income",
            capital_allocation=income_alloc,
            capital_pct=0.40,
            dte_min=30,
            dte_max=60,
            preferred_underlyings=_US_INCOME_UNDERLYINGS,
            strategy_types=["iron_condor", "credit_spread", "iron_butterfly", "calendar"],
            max_positions=6,
            risk_limits=_build_risk_limits("desk_income", 6, 0.15, 0.08),
            instrument_type="options",
            allow_undefined_risk=False,
            rationale="Core theta income: ICs and credit spreads at 30-60 DTE, defined risk only.",
        ),
        DeskSpec(
            desk_key="desk_core",
            name="Core Holdings",
            capital_allocation=core_alloc,
            capital_pct=0.40,
            dte_min=180,
            dte_max=730,
            preferred_underlyings=_US_CORE_UNDERLYINGS,
            strategy_types=["leap", "equity_long", "pmcc"],
            max_positions=5,
            risk_limits=_build_risk_limits("desk_core", 5, 0.20, 0.10),
            instrument_type="mixed",
            allow_undefined_risk=False,
            rationale="Long-term equity and LEAP positions. Buy-and-hold bias.",
        ),
    ]


def _moderate_desks(total: float, cash_pct: float, market: str) -> list[DeskSpec]:
    if market == "INDIA":
        return _india_desks(total, cash_pct, allow_undefined=False)

    dte0_alloc = total * 0.15
    income_alloc = total * 0.35
    core_alloc = total * 0.30
    growth_alloc = total * 0.12

    return [
        DeskSpec(
            desk_key="desk_0dte",
            name="0DTE Income",
            capital_allocation=dte0_alloc,
            capital_pct=0.15,
            dte_min=0,
            dte_max=0,
            preferred_underlyings=_US_0DTE_UNDERLYINGS,
            strategy_types=["iron_condor", "iron_man", "credit_spread"],
            max_positions=3,
            risk_limits=_build_risk_limits("desk_0dte", 3, 0.08, 0.04),
            instrument_type="options",
            allow_undefined_risk=False,
            rationale="0DTE income focus, defined risk. Paused in R4.",
        ),
        DeskSpec(
            desk_key="desk_income",
            name="Medium-Term Income",
            capital_allocation=income_alloc,
            capital_pct=0.35,
            dte_min=21,
            dte_max=60,
            preferred_underlyings=_US_INCOME_UNDERLYINGS,
            strategy_types=["iron_condor", "credit_spread", "iron_butterfly", "calendar", "diagonal"],
            max_positions=8,
            risk_limits=_build_risk_limits("desk_income", 8, 0.12, 0.07),
            instrument_type="options",
            allow_undefined_risk=False,
            rationale="Primary income engine: 21-60 DTE theta strategies.",
        ),
        DeskSpec(
            desk_key="desk_core",
            name="Core Holdings",
            capital_allocation=core_alloc,
            capital_pct=0.30,
            dte_min=180,
            dte_max=730,
            preferred_underlyings=_US_CORE_UNDERLYINGS,
            strategy_types=["leap", "equity_long", "pmcc"],
            max_positions=6,
            risk_limits=_build_risk_limits("desk_core", 6, 0.18, 0.10),
            instrument_type="mixed",
            allow_undefined_risk=False,
            rationale="Long-term compounding via LEAPs and PMCC on core ETFs/stocks.",
        ),
        DeskSpec(
            desk_key="desk_growth",
            name="Growth & Momentum",
            capital_allocation=growth_alloc,
            capital_pct=0.12,
            dte_min=14,
            dte_max=45,
            preferred_underlyings=_US_GROWTH_UNDERLYINGS,
            strategy_types=["debit_spread", "calendar", "diagonal"],
            max_positions=4,
            risk_limits=_build_risk_limits("desk_growth", 4, 0.10, 0.06),
            instrument_type="options",
            allow_undefined_risk=False,
            rationale="Directional spreads on trending tickers. Active in R3.",
        ),
    ]


def _aggressive_desks(total: float, cash_pct: float, market: str) -> list[DeskSpec]:
    if market == "INDIA":
        return _india_desks(total, cash_pct, allow_undefined=True)

    dte0_alloc = total * 0.20
    income_alloc = total * 0.30
    directional_alloc = total * 0.25
    core_alloc = total * 0.20

    return [
        DeskSpec(
            desk_key="desk_0dte",
            name="0DTE Income",
            capital_allocation=dte0_alloc,
            capital_pct=0.20,
            dte_min=0,
            dte_max=0,
            preferred_underlyings=_US_0DTE_UNDERLYINGS,
            strategy_types=["iron_condor", "iron_man", "credit_spread", "straddle_strangle"],
            max_positions=5,
            risk_limits=_build_risk_limits("desk_0dte", 5, 0.07, 0.03),
            instrument_type="options",
            allow_undefined_risk=True,
            rationale="Aggressive 0DTE: strangles and undefined risk allowed with active monitoring.",
        ),
        DeskSpec(
            desk_key="desk_income",
            name="Medium-Term Income",
            capital_allocation=income_alloc,
            capital_pct=0.30,
            dte_min=14,
            dte_max=45,
            preferred_underlyings=_US_INCOME_UNDERLYINGS,
            strategy_types=["iron_condor", "credit_spread", "iron_butterfly", "ratio_spread", "calendar"],
            max_positions=10,
            risk_limits=_build_risk_limits("desk_income", 10, 0.10, 0.06),
            instrument_type="options",
            allow_undefined_risk=True,
            rationale="Income desk with ratio spreads allowed. Tighter DTE range for higher theta decay.",
        ),
        DeskSpec(
            desk_key="desk_directional",
            name="Directional Trading",
            capital_allocation=directional_alloc,
            capital_pct=0.25,
            dte_min=7,
            dte_max=30,
            preferred_underlyings=_US_DIRECTIONAL_UNDERLYINGS,
            strategy_types=["debit_spread", "ratio_spread", "diagonal", "long_option"],
            max_positions=6,
            risk_limits=_build_risk_limits("desk_directional", 6, 0.12, 0.05),
            instrument_type="options",
            allow_undefined_risk=True,
            rationale="Directional plays in R3/R4. Debit spreads and ratio spreads for leverage.",
        ),
        DeskSpec(
            desk_key="desk_core",
            name="Core Holdings",
            capital_allocation=core_alloc,
            capital_pct=0.20,
            dte_min=180,
            dte_max=730,
            preferred_underlyings=_US_CORE_UNDERLYINGS,
            strategy_types=["leap", "equity_long", "pmcc"],
            max_positions=5,
            risk_limits=_build_risk_limits("desk_core", 5, 0.20, 0.10),
            instrument_type="mixed",
            allow_undefined_risk=False,
            rationale="Concentrated LEAP and equity core. Fewer positions, larger size.",
        ),
    ]


def _india_desks(total: float, cash_pct: float, allow_undefined: bool) -> list[DeskSpec]:
    """India market desk structure — weekly expiry focus."""
    expiry_alloc = total * 0.20
    income_alloc = total * 0.35
    core_alloc = total * 0.30
    # Remaining goes to unallocated cash (1 - 0.20 - 0.35 - 0.30 = 0.15 pre cash_pct adjustment)
    # But we fix allocations so they sum to (1 - cash_pct)
    deployed = 1.0 - cash_pct
    expiry_alloc = total * deployed * (0.20 / 0.85)
    income_alloc = total * deployed * (0.35 / 0.85)
    core_alloc = total * deployed * (0.30 / 0.85)

    return [
        DeskSpec(
            desk_key="desk_expiry_day",
            name="Expiry Day Trading",
            capital_allocation=round(expiry_alloc, 2),
            capital_pct=round(deployed * (0.20 / 0.85), 4),
            dte_min=0,
            dte_max=2,
            preferred_underlyings=_INDIA_EXPIRY_UNDERLYINGS,
            strategy_types=["iron_condor", "credit_spread", "straddle_strangle"],
            max_positions=3,
            risk_limits=_build_risk_limits(
                "desk_expiry_day", 3, 0.08, 0.04,
                size_factor=0.75 if not allow_undefined else 1.0,
            ),
            instrument_type="options",
            allow_undefined_risk=allow_undefined,
            rationale=(
                "India weekly expiry day desk (NIFTY/BANKNIFTY). "
                "Lot size awareness: NIFTY=75 lots, BANKNIFTY=50 lots. "
                "Define max_lots in position limits before entry."
            ),
        ),
        DeskSpec(
            desk_key="desk_income",
            name="Medium-Term Income (India)",
            capital_allocation=round(income_alloc, 2),
            capital_pct=round(deployed * (0.35 / 0.85), 4),
            dte_min=7,
            dte_max=30,
            preferred_underlyings=_INDIA_INCOME_UNDERLYINGS,
            strategy_types=["iron_condor", "credit_spread", "iron_butterfly"],
            max_positions=6,
            risk_limits=_build_risk_limits("desk_income", 6, 0.15, 0.07),
            instrument_type="options",
            allow_undefined_risk=allow_undefined,
            rationale="Weekly/monthly options income on NIFTY/BANKNIFTY/FINNIFTY.",
        ),
        DeskSpec(
            desk_key="desk_core",
            name="Core Holdings (India)",
            capital_allocation=round(core_alloc, 2),
            capital_pct=round(deployed * (0.30 / 0.85), 4),
            dte_min=90,
            dte_max=365,
            preferred_underlyings=_INDIA_CORE_UNDERLYINGS,
            strategy_types=["equity_long", "leap"],
            max_positions=8,
            risk_limits=_build_risk_limits("desk_core", 8, 0.15, 0.10),
            instrument_type="mixed",
            allow_undefined_risk=False,
            rationale="Long-term equity holdings in NSE large-caps and NIFTY index.",
        ),
    ]


def _apply_r4_adjustment(
    desks: list[DeskSpec],
    total: float,
    new_cash_pct: float,
) -> list[DeskSpec]:
    """R4: increase cash reserve, halve 0DTE and directional allocations."""
    result = []
    for desk in desks:
        if "0dte" in desk.desk_key or "directional" in desk.desk_key or "expiry" in desk.desk_key:
            new_alloc = desk.capital_allocation * 0.50
            new_pct = desk.capital_pct * 0.50
            result.append(desk.model_copy(update={
                "capital_allocation": round(new_alloc, 2),
                "capital_pct": round(new_pct, 4),
                "rationale": desk.rationale + " [R4: allocation halved]",
            }))
        else:
            result.append(desk)

    # Re-normalize to respect new cash level
    allocated = sum(d.capital_allocation for d in result)
    target_allocated = total * (1 - new_cash_pct)
    if allocated > target_allocated:
        # Scale down proportionally
        scale = target_allocated / allocated
        result = [
            d.model_copy(update={
                "capital_allocation": round(d.capital_allocation * scale, 2),
                "capital_pct": round(d.capital_pct * scale, 4),
            })
            for d in result
        ]
    return result


def _apply_r2_adjustment(
    desks: list[DeskSpec],
    total: float,
    cash_pct: float,
) -> list[DeskSpec]:
    """R2: reduce 0DTE by 25%, add freed capital to income desk."""
    result = []
    freed = 0.0
    for desk in desks:
        if "0dte" in desk.desk_key or "expiry" in desk.desk_key:
            reduction = desk.capital_allocation * 0.25
            freed += reduction
            new_alloc = desk.capital_allocation - reduction
            result.append(desk.model_copy(update={
                "capital_allocation": round(new_alloc, 2),
                "capital_pct": round(desk.capital_pct * 0.75, 4),
                "rationale": desk.rationale + " [R2: 0DTE reduced 25%]",
            }))
        else:
            result.append(desk)

    # Add freed capital to income desk
    for i, desk in enumerate(result):
        if "income" in desk.desk_key:
            result[i] = desk.model_copy(update={
                "capital_allocation": round(desk.capital_allocation + freed, 2),
                "capital_pct": round((desk.capital_allocation + freed) / total, 4),
                "rationale": desk.rationale + " [R2: expanded from 0DTE reallocation]",
            })
            break

    return result


def _apply_r3_adjustment(
    desks: list[DeskSpec],
    total: float,
    cash_pct: float,
) -> list[DeskSpec]:
    """R3: increase directional/growth, reduce income."""
    result = []
    freed = 0.0
    for desk in desks:
        if "income" in desk.desk_key:
            reduction = desk.capital_allocation * 0.15
            freed += reduction
            new_alloc = desk.capital_allocation - reduction
            result.append(desk.model_copy(update={
                "capital_allocation": round(new_alloc, 2),
                "capital_pct": round((new_alloc) / total, 4),
                "rationale": desk.rationale + " [R3: income reduced, capital shifted to directional]",
            }))
        else:
            result.append(desk)

    # Add freed capital to growth/directional desk if it exists
    directional_keys = ["directional", "growth"]
    for i, desk in enumerate(result):
        if any(k in desk.desk_key for k in directional_keys):
            result[i] = desk.model_copy(update={
                "capital_allocation": round(desk.capital_allocation + freed, 2),
                "capital_pct": round((desk.capital_allocation + freed) / total, 4),
                "rationale": desk.rationale + " [R3: expanded from income reallocation]",
            })
            break

    return result


# ---------------------------------------------------------------------------
# 2. rebalance_desks
# ---------------------------------------------------------------------------

def rebalance_desks(
    current_desks: list[dict],
    target_desks: list[dict],
    account_drawdown_pct: float = 0.0,
    regime_changed: bool = False,
    days_since_last_rebalance: int = 0,
    drift_threshold_pct: float = 0.20,
) -> RebalanceRecommendation:
    """Determine whether desks need rebalancing and what changes to make.

    Checks 4 triggers in priority order:
    1. Regime change — dominant regime shifted
    2. Drawdown > 5% — reduce all proportionally
    3. Drift — any desk >20% away from target
    4. Periodic — >30 days since last rebalance

    Args:
        current_desks: List of dicts with {desk_key, current_capital}.
        target_desks: List of dicts with {desk_key, target_capital}.
        account_drawdown_pct: Current account drawdown as fraction (e.g. 0.07 = 7%).
        regime_changed: Whether the dominant regime shifted since last rebalance.
        days_since_last_rebalance: Calendar days since last rebalance.
        drift_threshold_pct: Max allowed drift before triggering rebalance (default 20%).

    Returns:
        RebalanceRecommendation with adjustments and trigger reason.
    """
    # Build lookup maps
    current_map = {d["desk_key"]: d["current_capital"] for d in current_desks}
    target_map = {d["desk_key"]: d["target_capital"] for d in target_desks}

    adjustments: list[DeskAdjustment] = []
    trigger = ""
    needs_rebalance = False
    rationale_parts: list[str] = []

    # ── Trigger 1: Regime change ──────────────────────────────────────────────
    if regime_changed:
        needs_rebalance = True
        trigger = "regime_change"
        rationale_parts.append("Dominant regime shifted — reallocating to match new regime profile.")
        for desk_key, target_cap in target_map.items():
            current_cap = current_map.get(desk_key, 0.0)
            change = target_cap - current_cap
            if abs(change) > 1.0:  # ignore trivial changes
                adjustments.append(DeskAdjustment(
                    desk_key=desk_key,
                    current_capital=current_cap,
                    recommended_capital=target_cap,
                    change=round(change, 2),
                    reason="Regime change reallocation",
                ))

    # ── Trigger 2: Drawdown > 5% ──────────────────────────────────────────────
    elif account_drawdown_pct > 0.05:
        needs_rebalance = True
        trigger = "drawdown"
        reduction_factor = 1.0 - (account_drawdown_pct * 2.0)  # proportional reduction
        reduction_factor = max(reduction_factor, 0.50)  # floor at 50%
        rationale_parts.append(
            f"Account drawdown {account_drawdown_pct:.1%} exceeds 5% threshold — "
            f"reducing all desks by {(1 - reduction_factor):.1%}."
        )
        for desk_key, current_cap in current_map.items():
            target_cap = current_cap * reduction_factor
            change = target_cap - current_cap
            adjustments.append(DeskAdjustment(
                desk_key=desk_key,
                current_capital=current_cap,
                recommended_capital=round(target_cap, 2),
                change=round(change, 2),
                reason=f"Drawdown protection: reduce to {reduction_factor:.0%} of current",
            ))

    # ── Trigger 3: Drift > threshold ─────────────────────────────────────────
    else:
        drifted_desks = []
        for desk_key, target_cap in target_map.items():
            current_cap = current_map.get(desk_key, 0.0)
            if target_cap == 0:
                continue
            drift = abs(current_cap - target_cap) / target_cap
            if drift > drift_threshold_pct:
                drifted_desks.append((desk_key, current_cap, target_cap, drift))

        if drifted_desks:
            needs_rebalance = True
            trigger = "performance_drift"
            rationale_parts.append(
                f"{len(drifted_desks)} desk(s) drifted >{drift_threshold_pct:.0%} from target."
            )
            for desk_key, current_cap, target_cap, drift in drifted_desks:
                change = target_cap - current_cap
                adjustments.append(DeskAdjustment(
                    desk_key=desk_key,
                    current_capital=current_cap,
                    recommended_capital=round(target_cap, 2),
                    change=round(change, 2),
                    reason=f"Drift {drift:.1%} from target — rebalancing",
                ))

        # ── Trigger 4: Periodic (30 days) ────────────────────────────────────
        elif days_since_last_rebalance > 30:
            needs_rebalance = True
            trigger = "periodic"
            rationale_parts.append(
                f"Periodic rebalance triggered ({days_since_last_rebalance} days since last)."
            )
            for desk_key, target_cap in target_map.items():
                current_cap = current_map.get(desk_key, 0.0)
                change = target_cap - current_cap
                if abs(change) > 1.0:
                    adjustments.append(DeskAdjustment(
                        desk_key=desk_key,
                        current_capital=current_cap,
                        recommended_capital=round(target_cap, 2),
                        change=round(change, 2),
                        reason="Periodic rebalance to target",
                    ))

    if not needs_rebalance:
        trigger = "none"
        rationale_parts.append("All desks within tolerance. No rebalance needed.")

    return RebalanceRecommendation(
        needs_rebalance=needs_rebalance,
        adjustments=adjustments,
        trigger=trigger,
        rationale=" ".join(rationale_parts),
    )


# ---------------------------------------------------------------------------
# 3. evaluate_desk_health
# ---------------------------------------------------------------------------

def evaluate_desk_health(
    desk_key: str,
    trade_history: list[dict],
    capital_deployed: float,
    current_regime: int | None = None,
    desk_strategy_types: list[str] | None = None,
) -> DeskHealthReport:
    """Evaluate desk health from trade history.

    Args:
        desk_key: Desk identifier (e.g. "desk_income").
        trade_history: List of trade outcome dicts with keys:
            - pnl: float (realized P&L)
            - days_held: float
            - won: bool (True if trade closed profitably)
        capital_deployed: Total capital allocated to this desk.
        current_regime: Current regime ID (1-4) for regime fit assessment.
        desk_strategy_types: Strategy types this desk uses.

    Returns:
        DeskHealthReport with health score, metrics, issues, and suggestions.
    """
    issues: list[str] = []
    suggestions: list[str] = []

    # ── Compute metrics ───────────────────────────────────────────────────────
    win_rate: float | None = None
    profit_factor: float | None = None
    avg_days_held: float | None = None
    capital_efficiency: float = 0.0

    if trade_history:
        wins = [t for t in trade_history if t.get("won", False)]
        losses = [t for t in trade_history if not t.get("won", False)]

        win_rate = len(wins) / len(trade_history) if trade_history else None

        gross_profit = sum(t.get("pnl", 0) for t in wins)
        gross_loss = abs(sum(t.get("pnl", 0) for t in losses))
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        days_values = [t.get("days_held", 0) for t in trade_history if t.get("days_held") is not None]
        avg_days_held = sum(days_values) / len(days_values) if days_values else None

        total_pnl = sum(t.get("pnl", 0) for t in trade_history)
        if capital_deployed > 0 and avg_days_held and avg_days_held > 0:
            # Annualized ROC
            annual_factor = 365 / avg_days_held
            capital_efficiency = (total_pnl / capital_deployed) * annual_factor
        elif capital_deployed > 0:
            capital_efficiency = total_pnl / capital_deployed

    # ── Regime fit ────────────────────────────────────────────────────────────
    regime_fit = "neutral"
    if current_regime is not None and desk_strategy_types:
        income_strategies = {"iron_condor", "credit_spread", "iron_butterfly", "calendar", "iron_man"}
        directional_strategies = {"debit_spread", "diagonal", "long_option", "ratio_spread"}
        theta_strategies = income_strategies | {"straddle_strangle"}

        desk_is_income = bool(set(desk_strategy_types) & income_strategies)
        desk_is_directional = bool(set(desk_strategy_types) & directional_strategies)

        if current_regime in (1, 2) and desk_is_income:
            regime_fit = "well_suited"
        elif current_regime == 3 and desk_is_directional:
            regime_fit = "well_suited"
        elif current_regime == 4:
            if desk_is_income and not desk_is_directional:
                regime_fit = "poor_fit"
                issues.append("R4 detected — income strategies face adverse volatility.")
                suggestions.append("Reduce position sizes or pause new income trades until R4 resolves.")
            elif desk_is_directional:
                regime_fit = "well_suited"
        elif current_regime in (3, 4) and desk_is_income and not desk_is_directional:
            regime_fit = "poor_fit"
            issues.append(f"R{current_regime} regime is trending — income desk underperforms in trending markets.")
            suggestions.append("Consider reducing IC/credit spread positions and opening diagonal or directional spreads.")

    # ── Issue and suggestion detection ────────────────────────────────────────
    if win_rate is not None and win_rate < 0.45:
        issues.append(f"Win rate {win_rate:.0%} below 45% threshold.")
        suggestions.append("Review strategy selection or regime alignment. Consider tightening entry criteria.")

    if profit_factor is not None and profit_factor < 1.0:
        issues.append(f"Profit factor {profit_factor:.2f} — losing desk (losses outpace gains).")
        suggestions.append("Pause new positions until root cause identified. Review exit discipline.")

    if capital_efficiency < 0:
        issues.append(f"Negative capital efficiency ({capital_efficiency:.1%}) — desk losing money.")
        suggestions.append("Pause desk, analyze losing trades for pattern (regime mismatch, sizing errors).")

    if not trade_history:
        issues.append("No trade history — cannot assess performance.")
        suggestions.append("Log trade outcomes to enable health monitoring.")

    # ── Score and health label ────────────────────────────────────────────────
    score = _compute_health_score(win_rate, profit_factor, capital_efficiency, regime_fit, issues)
    health = _score_to_health(score)

    return DeskHealthReport(
        desk_key=desk_key,
        health=health,
        score=round(score, 3),
        win_rate=round(win_rate, 3) if win_rate is not None else None,
        profit_factor=round(profit_factor, 3) if profit_factor is not None and profit_factor != float("inf") else profit_factor,
        avg_days_held=round(avg_days_held, 1) if avg_days_held is not None else None,
        capital_efficiency=round(capital_efficiency, 4),
        issues=issues,
        suggestions=suggestions,
        regime_fit=regime_fit,
    )


def _compute_health_score(
    win_rate: float | None,
    profit_factor: float | None,
    capital_efficiency: float,
    regime_fit: str,
    issues: list[str],
) -> float:
    """Compute 0-1 health score."""
    score = 0.5  # neutral default

    if win_rate is not None:
        if win_rate >= 0.65:
            score += 0.20
        elif win_rate >= 0.50:
            score += 0.10
        elif win_rate < 0.45:
            score -= 0.20
        else:
            score -= 0.05

    if profit_factor is not None and profit_factor != float("inf"):
        if profit_factor >= 2.0:
            score += 0.20
        elif profit_factor >= 1.5:
            score += 0.10
        elif profit_factor >= 1.0:
            score += 0.05
        elif profit_factor < 1.0:
            score -= 0.20

    if capital_efficiency > 0.20:
        score += 0.10
    elif capital_efficiency < 0:
        score -= 0.15

    if regime_fit == "well_suited":
        score += 0.05
    elif regime_fit == "poor_fit":
        score -= 0.10

    return max(0.0, min(1.0, score))


def _score_to_health(score: float) -> DeskHealth:
    if score >= 0.80:
        return DeskHealth.EXCELLENT
    elif score >= 0.65:
        return DeskHealth.GOOD
    elif score >= 0.50:
        return DeskHealth.CAUTION
    elif score >= 0.30:
        return DeskHealth.POOR
    else:
        return DeskHealth.CRITICAL


# ---------------------------------------------------------------------------
# 4. suggest_desk_for_trade
# ---------------------------------------------------------------------------

def suggest_desk_for_trade(
    desks: list[dict],
    trade_dte: int,
    strategy_type: str,
    ticker: str | None = None,
    existing_positions_by_desk: dict[str, list[str]] | None = None,
) -> dict:
    """Suggest which desk a proposed trade should be routed to.

    Matching criteria in priority order:
    1. DTE range (primary match)
    2. Strategy type (secondary match)
    3. Available capacity (don't overload a desk)
    4. Ticker correlation (spread exposure across desks)

    Args:
        desks: List of desk dicts with keys: desk_key, dte_min, dte_max,
               strategy_types, max_positions, capital_allocation.
        trade_dte: DTE of the proposed trade.
        strategy_type: Strategy type string (e.g. "iron_condor").
        ticker: Underlying ticker (for correlation check).
        existing_positions_by_desk: {desk_key: [ticker, ...]} current positions.

    Returns:
        dict with keys: desk_key, reason, score, alternatives.
    """
    existing = existing_positions_by_desk or {}

    scored: list[tuple[float, str, str]] = []  # (score, desk_key, reason)

    for desk in desks:
        desk_key = desk.get("desk_key", "")
        dte_min = desk.get("dte_min", 0)
        dte_max = desk.get("dte_max", 999)
        desk_strategies = desk.get("strategy_types", [])
        max_positions = desk.get("max_positions", 10)

        # Check capacity
        current_count = len(existing.get(desk_key, []))
        if current_count >= max_positions:
            scored.append((0.0, desk_key, "Desk at capacity"))
            continue

        desk_score = 0.0
        reason_parts = []

        # ── DTE match (50 points) ─────────────────────────────────────────────
        if dte_min <= trade_dte <= dte_max:
            desk_score += 0.50
            reason_parts.append(f"DTE {trade_dte} fits [{dte_min}-{dte_max}]")
        else:
            # Partial credit for near-miss
            dte_miss = min(abs(trade_dte - dte_min), abs(trade_dte - dte_max))
            dte_range = max(dte_max - dte_min, 1)
            proximity = max(0.0, 1.0 - dte_miss / dte_range)
            desk_score += 0.20 * proximity
            if proximity > 0:
                reason_parts.append(f"DTE partial match ({dte_miss} days outside range)")

        # ── Strategy match (30 points) ────────────────────────────────────────
        if strategy_type in desk_strategies:
            desk_score += 0.30
            reason_parts.append(f"Strategy '{strategy_type}' supported")
        else:
            # Partial credit for compatible families
            _income_family = {"iron_condor", "credit_spread", "iron_butterfly", "iron_man", "calendar"}
            _directional_family = {"debit_spread", "diagonal", "long_option", "ratio_spread"}
            trade_family = (
                "income" if strategy_type in _income_family
                else "directional" if strategy_type in _directional_family
                else "core"
            )
            desk_family_strategies = set(desk_strategies)
            desk_is_income = bool(desk_family_strategies & _income_family)
            desk_is_directional = bool(desk_family_strategies & _directional_family)

            if trade_family == "income" and desk_is_income:
                desk_score += 0.15
                reason_parts.append("Strategy family (income) compatible")
            elif trade_family == "directional" and desk_is_directional:
                desk_score += 0.15
                reason_parts.append("Strategy family (directional) compatible")

        # ── Capacity headroom (15 points) ─────────────────────────────────────
        capacity_used = current_count / max(max_positions, 1)
        headroom_score = (1.0 - capacity_used) * 0.15
        desk_score += headroom_score
        reason_parts.append(f"Capacity: {current_count}/{max_positions}")

        # ── Ticker correlation (5 points) ─────────────────────────────────────
        if ticker:
            existing_tickers = existing.get(desk_key, [])
            ticker_already_in_desk = ticker in existing_tickers
            if not ticker_already_in_desk:
                desk_score += 0.05
                reason_parts.append("No correlated ticker in desk")
            else:
                desk_score -= 0.05
                reason_parts.append("Same ticker already in desk (correlation risk)")

        scored.append((desk_score, desk_key, "; ".join(reason_parts)))

    if not scored:
        return {
            "desk_key": None,
            "reason": "No desks available",
            "score": 0.0,
            "alternatives": [],
        }

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_key, best_reason = scored[0]

    alternatives = [
        {"desk_key": dk, "score": round(s, 3), "reason": r}
        for s, dk, r in scored[1:4]
        if s > 0
    ]

    return {
        "desk_key": best_key,
        "reason": best_reason,
        "score": round(best_score, 3),
        "alternatives": alternatives,
    }


# ---------------------------------------------------------------------------
# 5. compute_desk_risk_limits
# ---------------------------------------------------------------------------

def compute_desk_risk_limits(
    desk_key: str,
    base_max_positions: int,
    base_max_single_position_pct: float,
    base_circuit_breaker_pct: float,
    regime_id: int = 1,
    account_drawdown_pct: float = 0.0,
    base_max_portfolio_delta: float = 0.30,
    base_max_daily_loss_pct: float = 0.02,
    base_max_correlated_positions: int = 3,
) -> DeskRiskLimits:
    """Compute regime-adjusted risk limits for a desk.

    Base limits are scaled by regime:
    - R1: full limits (1.0x)
    - R2: 80% of full
    - R3: 70% for income desks, 100% for directional desks
    - R4: 50% of full, 0.5x position_size_factor

    Drawdown overlay: if account drawdown > 5%, reduce all limits by 50%.

    Args:
        desk_key: Desk identifier (used to distinguish income vs directional).
        base_max_positions: Maximum positions at full limits.
        base_max_single_position_pct: Max single position as fraction of desk capital.
        base_circuit_breaker_pct: Stop-all threshold as fraction of desk capital.
        regime_id: Current regime (1-4).
        account_drawdown_pct: Current account drawdown as fraction.
        base_max_portfolio_delta: Max portfolio delta at full limits.
        base_max_daily_loss_pct: Max daily loss as fraction of desk capital.
        base_max_correlated_positions: Max positions in same underlying.

    Returns:
        DeskRiskLimits with regime-adjusted values.
    """
    is_directional = any(k in desk_key for k in ["directional", "growth", "momentum"])

    # ── Regime multiplier ─────────────────────────────────────────────────────
    if regime_id == 1:
        regime_mult = 1.0
        size_factor = 1.0
        regime_note = "R1 (Low-Vol MR): full limits"
    elif regime_id == 2:
        regime_mult = 0.80
        size_factor = 0.80
        regime_note = "R2 (High-Vol MR): 80% limits"
    elif regime_id == 3:
        if is_directional:
            regime_mult = 1.0
            size_factor = 1.0
            regime_note = "R3 (Trending): full limits for directional desk"
        else:
            regime_mult = 0.70
            size_factor = 0.70
            regime_note = "R3 (Trending): 70% limits for income desk (adverse regime)"
    else:  # R4
        regime_mult = 0.50
        size_factor = 0.50
        regime_note = "R4 (High-Vol Trending): 50% limits, all desks"

    # ── Drawdown overlay ──────────────────────────────────────────────────────
    drawdown_note = ""
    if account_drawdown_pct > 0.05:
        regime_mult *= 0.50
        size_factor *= 0.50
        drawdown_note = f" + drawdown {account_drawdown_pct:.1%} overlay (50% reduction)"

    # ── Apply multipliers ─────────────────────────────────────────────────────
    adjusted_max_positions = max(1, int(base_max_positions * regime_mult))
    adjusted_single_pct = base_max_single_position_pct * regime_mult
    adjusted_circuit_breaker = base_circuit_breaker_pct  # circuit breaker doesn't scale (it's a hard stop)
    adjusted_delta = base_max_portfolio_delta * regime_mult
    adjusted_daily_loss = base_max_daily_loss_pct * regime_mult
    adjusted_correlated = max(1, int(base_max_correlated_positions * regime_mult))

    rationale = f"{regime_note}{drawdown_note}."

    return DeskRiskLimits(
        desk_key=desk_key,
        max_positions=adjusted_max_positions,
        max_single_position_pct=round(adjusted_single_pct, 4),
        max_portfolio_delta=round(adjusted_delta, 4),
        max_daily_loss_pct=round(adjusted_daily_loss, 4),
        circuit_breaker_pct=round(adjusted_circuit_breaker, 4),
        max_correlated_positions=adjusted_correlated,
        position_size_factor=round(size_factor, 4),
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# 6. compute_instrument_risk
# ---------------------------------------------------------------------------

# Regime factors for expected loss scaling
_REGIME_FACTORS = {1: 0.40, 2: 0.70, 3: 1.10, 4: 1.50}


def compute_instrument_risk(
    ticker: str,
    instrument_type: str,
    position_value: float,
    regime_id: int = 1,
    # option_spread params
    wing_width: float | None = None,
    lot_size: int = 100,
    # equity_long params
    atr_pct: float | None = None,
    # futures params
    contract_value: float | None = None,
    margin_pct: float = 0.10,
    # naked_option params
    underlying_price: float | None = None,
) -> InstrumentRisk:
    """Compute risk metrics per instrument type.

    Per instrument type:
    - option_spread: defined risk = wing_width × lot_size
    - equity_long: atr_based = position_value × atr_pct × regime_factor
    - futures: margin_based = contract_value × margin_pct × regime_factor
    - naked_option: max theoretical (flag as undefined risk)

    Args:
        ticker: Instrument symbol.
        instrument_type: "option_spread" | "equity_long" | "futures" | "naked_option"
        position_value: Total position value (debit paid or credit received × multiplier).
        regime_id: Current regime (1-4) for scaling expected loss.
        wing_width: Width of option spread in points (option_spread only).
        lot_size: Contract multiplier (default 100 for US equity options).
        atr_pct: ATR as percentage of price (equity_long only).
        contract_value: Full contract value (futures only).
        margin_pct: Margin as fraction of contract value (futures only).
        underlying_price: Current underlying price (naked_option only).

    Returns:
        InstrumentRisk with max_loss, expected_loss_1d, margin_required.
    """
    regime_factor = _REGIME_FACTORS.get(regime_id, 1.0)

    if instrument_type == "option_spread":
        return _option_spread_risk(
            ticker, position_value, regime_factor, wing_width, lot_size
        )
    elif instrument_type == "equity_long":
        return _equity_long_risk(
            ticker, position_value, regime_factor, atr_pct
        )
    elif instrument_type == "futures":
        return _futures_risk(
            ticker, position_value, regime_factor, contract_value, margin_pct
        )
    elif instrument_type == "naked_option":
        return _naked_option_risk(
            ticker, position_value, regime_factor, underlying_price, lot_size
        )
    else:
        # Unknown type: conservative fallback
        max_loss = position_value
        return InstrumentRisk(
            ticker=ticker,
            instrument_type=instrument_type,
            max_loss=round(max_loss, 2),
            expected_loss_1d=round(max_loss * regime_factor * 0.10, 2),
            margin_required=round(max_loss, 2),
            risk_category="undefined",
            risk_method="max_loss",
            regime_factor=regime_factor,
            rationale=f"Unknown instrument type '{instrument_type}' — conservative max_loss estimate.",
        )


def _option_spread_risk(
    ticker: str,
    position_value: float,
    regime_factor: float,
    wing_width: float | None,
    lot_size: int,
) -> InstrumentRisk:
    if wing_width is not None:
        max_loss = wing_width * lot_size
        rationale = f"Defined risk: wing_width {wing_width} × lot_size {lot_size} = ${max_loss:,.0f}."
    else:
        # Fallback: assume position_value is the max loss (debit paid)
        max_loss = position_value
        rationale = f"Defined risk (wing_width not provided): position_value ${position_value:,.0f} used as max loss."

    expected_loss_1d = max_loss * regime_factor * 0.05  # 5% of max loss per day in expected scenario
    margin_required = max_loss  # SPAN margin = max loss for defined-risk spreads

    return InstrumentRisk(
        ticker=ticker,
        instrument_type="option_spread",
        max_loss=round(max_loss, 2),
        expected_loss_1d=round(expected_loss_1d, 2),
        margin_required=round(margin_required, 2),
        risk_category="defined",
        risk_method="max_loss",
        regime_factor=regime_factor,
        rationale=rationale,
    )


def _equity_long_risk(
    ticker: str,
    position_value: float,
    regime_factor: float,
    atr_pct: float | None,
) -> InstrumentRisk:
    if atr_pct is not None:
        expected_loss_1d = position_value * atr_pct * regime_factor
        max_loss = position_value  # full position value at risk
        method = "atr_based"
        rationale = (
            f"ATR-based: position ${position_value:,.0f} × ATR {atr_pct:.2%} × "
            f"regime_factor {regime_factor:.2f} = ${expected_loss_1d:,.0f} expected 1-day loss."
        )
    else:
        # Conservative fallback: 2% daily loss
        expected_loss_1d = position_value * 0.02 * regime_factor
        max_loss = position_value
        method = "atr_based"
        rationale = (
            f"ATR not provided — using 2% daily fallback × regime_factor {regime_factor:.2f}."
        )

    margin_required = position_value  # equity: full cash required (or 50% margin)

    return InstrumentRisk(
        ticker=ticker,
        instrument_type="equity_long",
        max_loss=round(max_loss, 2),
        expected_loss_1d=round(expected_loss_1d, 2),
        margin_required=round(margin_required, 2),
        risk_category="equity",
        risk_method=method,
        regime_factor=regime_factor,
        rationale=rationale,
    )


def _futures_risk(
    ticker: str,
    position_value: float,
    regime_factor: float,
    contract_value: float | None,
    margin_pct: float,
) -> InstrumentRisk:
    cv = contract_value if contract_value is not None else position_value
    margin_required = cv * margin_pct * regime_factor
    max_loss = cv  # full contract value at risk theoretically
    expected_loss_1d = cv * 0.02 * regime_factor  # 2% daily move as baseline

    rationale = (
        f"Margin-based: contract ${cv:,.0f} × margin {margin_pct:.0%} × "
        f"regime_factor {regime_factor:.2f} = ${margin_required:,.0f} margin. "
        f"Max loss = full contract value ${max_loss:,.0f}."
    )

    return InstrumentRisk(
        ticker=ticker,
        instrument_type="futures",
        max_loss=round(max_loss, 2),
        expected_loss_1d=round(expected_loss_1d, 2),
        margin_required=round(margin_required, 2),
        risk_category="undefined",
        risk_method="margin_based",
        regime_factor=regime_factor,
        rationale=rationale,
    )


def _naked_option_risk(
    ticker: str,
    position_value: float,
    regime_factor: float,
    underlying_price: float | None,
    lot_size: int,
) -> InstrumentRisk:
    # Naked option: theoretical max loss = underlying_price × lot_size (for naked call)
    # Use underlying_price if available, else position_value × 10 as conservative proxy
    if underlying_price is not None:
        max_loss = underlying_price * lot_size
        rationale = (
            f"UNDEFINED RISK — naked option. Theoretical max loss = "
            f"underlying ${underlying_price:,.2f} × lot {lot_size} = ${max_loss:,.0f}. "
            f"eTrading MUST confirm undefined risk is approved for this account."
        )
    else:
        max_loss = position_value * 10  # conservative proxy
        rationale = (
            f"UNDEFINED RISK — naked option (underlying price unavailable). "
            f"Estimated max loss = position_value ${position_value:,.0f} × 10 = ${max_loss:,.0f}. "
            f"eTrading MUST confirm undefined risk is approved for this account."
        )

    expected_loss_1d = max_loss * 0.05 * regime_factor
    margin_required = max_loss * 0.20  # approximate CBOE naked option margin

    return InstrumentRisk(
        ticker=ticker,
        instrument_type="naked_option",
        max_loss=round(max_loss, 2),
        expected_loss_1d=round(expected_loss_1d, 2),
        margin_required=round(margin_required, 2),
        risk_category="undefined",
        risk_method="max_loss",
        regime_factor=regime_factor,
        rationale=rationale,
    )
