"""Pipeline validation functions for trade data sanity and end-to-end health.

Three validation layers:
    1. ``validate_trade_data_sanity`` — single-trade field-level checks
    2. ``validate_pipeline_health`` — cross-trade aggregate health
    3. ``validate_full_pipeline`` — end-to-end simulation smoke test
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Models ──


class SanityIssue(BaseModel):
    """A single data sanity problem on a trade."""

    field: str
    severity: str  # "critical", "warning"
    message: str
    current_value: Any = None


class HealthCheck(BaseModel):
    """Result of a single pipeline health check."""

    name: str
    passed: bool
    detail: str


class PipelineHealthReport(BaseModel):
    """Aggregate health of the trading pipeline."""

    overall_health: str  # "GREEN", "YELLOW", "RED"
    checks: list[HealthCheck] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PipelineTestResult(BaseModel):
    """Result of an end-to-end pipeline simulation test."""

    passed: bool
    stages_passed: list[str] = Field(default_factory=list)
    stages_failed: list[tuple[str, str]] = Field(default_factory=list)
    sample_trade: dict | None = None


# ── Multi-leg structure types ──

_MULTI_LEG_STRUCTURES = frozenset({
    "iron_condor",
    "iron_butterfly",
    "strangle",
    "straddle",
    "calendar",
    "diagonal",
    "ratio_spread",
    "credit_spread",
    "debit_spread",
    "put_spread",
    "call_spread",
    "double_diagonal",
    "jade_lizard",
    "broken_wing_butterfly",
})

_EQUITY_STRUCTURES = frozenset({
    "equity_long",
    "equity_short",
    "equity_value",
    "equity_quality_momentum",
})


# ── Function 1: validate_trade_data_sanity ──


def validate_trade_data_sanity(trade: dict) -> list[SanityIssue]:
    """Check a single trade dict for obvious data problems.

    Args:
        trade: A trade dictionary with fields like entry_price, structure_type,
            current_price, total_pnl, legs, etc.

    Returns:
        List of SanityIssue objects. Empty list means the trade looks clean.
    """
    issues: list[SanityIssue] = []

    entry_price = trade.get("entry_price")
    structure_type = (trade.get("structure_type") or "").lower().replace(" ", "_")
    current_price = trade.get("current_price")
    total_pnl = trade.get("total_pnl")
    legs = trade.get("legs") or []
    lot_size = trade.get("lot_size")
    multiplier = trade.get("multiplier")

    # ── entry_price <= 0 → critical ──
    if entry_price is not None and entry_price <= 0:
        issues.append(SanityIssue(
            field="entry_price",
            severity="critical",
            message=f"entry_price is {entry_price} — must be positive",
            current_value=entry_price,
        ))

    # ── equity with lot_size/multiplier = 100 → critical ──
    if "equity" in structure_type:
        effective_lot = lot_size or multiplier
        if effective_lot == 100:
            issues.append(SanityIssue(
                field="lot_size",
                severity="critical",
                message=(
                    f"Equity structure '{structure_type}' has lot_size/multiplier=100 — "
                    "should be 1 for equity"
                ),
                current_value=effective_lot,
            ))

    # ── stale mark: current_price == entry_price when held > 0 days ──
    opened_at = trade.get("opened_at")
    days_held = _compute_days_held(opened_at)
    if (
        current_price is not None
        and current_price > 0
        and entry_price is not None
        and entry_price > 0
        and current_price == entry_price
        and days_held is not None
        and days_held > 0
    ):
        issues.append(SanityIssue(
            field="current_price",
            severity="warning",
            message=(
                f"current_price ({current_price}) == entry_price after "
                f"{days_held} day(s) held — likely stale mark"
            ),
            current_value=current_price,
        ))

    # ── quantity doubling: current_price > 2 * entry_price for equity ──
    if "equity" in structure_type:
        if (
            current_price is not None
            and entry_price is not None
            and entry_price > 0
            and current_price > 2 * entry_price
        ):
            issues.append(SanityIssue(
                field="current_price",
                severity="critical",
                message=(
                    f"Equity current_price ({current_price}) > 2× entry_price "
                    f"({entry_price}) — likely quantity doubling bug"
                ),
                current_value=current_price,
            ))

    # ── total_pnl is None or 0 when held > 0 and prices differ ──
    if (
        days_held is not None
        and days_held > 0
        and current_price is not None
        and entry_price is not None
        and current_price != entry_price
        and (total_pnl is None or total_pnl == 0)
    ):
        issues.append(SanityIssue(
            field="total_pnl",
            severity="warning",
            message=(
                f"total_pnl is {total_pnl} but trade held {days_held} day(s) "
                f"with entry={entry_price}, current={current_price}"
            ),
            current_value=total_pnl,
        ))

    # ── option legs without strike → critical ──
    for i, leg in enumerate(legs):
        asset_type = (leg.get("asset_type") or "").lower()
        if asset_type == "option" and not leg.get("strike"):
            issues.append(SanityIssue(
                field=f"legs[{i}].strike",
                severity="critical",
                message=f"Option leg {i} has no strike price",
                current_value=None,
            ))

    # ── negative prices → critical ──
    for price_field in ("entry_price", "current_price"):
        val = trade.get(price_field)
        if val is not None and val < 0:
            issues.append(SanityIssue(
                field=price_field,
                severity="critical",
                message=f"{price_field} is negative ({val})",
                current_value=val,
            ))

    # ── multi-leg structure with < 2 legs → critical ──
    if structure_type in _MULTI_LEG_STRUCTURES:
        option_legs = [
            lg for lg in legs
            if (lg.get("asset_type") or "").lower() == "option"
        ]
        if len(option_legs) < 2:
            issues.append(SanityIssue(
                field="legs",
                severity="critical",
                message=(
                    f"Structure '{structure_type}' requires >=2 option legs, "
                    f"found {len(option_legs)}"
                ),
                current_value=len(option_legs),
            ))

    return issues


# ── Function 2: validate_pipeline_health ──


def validate_pipeline_health(
    trades: list[dict],
    decisions: list[dict],
    marks: list[dict] | None = None,
    min_option_trades: int = 1,
) -> PipelineHealthReport:
    """Check aggregate pipeline health across trades and decisions.

    Args:
        trades: List of trade dicts (open positions).
        decisions: List of decision/log dicts from the decision pipeline.
        marks: Optional list of mark-to-market results.
        min_option_trades: Minimum number of option trades expected.

    Returns:
        PipelineHealthReport with overall health color.
    """
    checks: list[HealthCheck] = []
    blocking: list[str] = []
    warnings: list[str] = []

    # ── Check 1: option_trades_exist ──
    option_trades = [
        t for t in trades
        if (t.get("structure_type") or "").lower().replace(" ", "_")
        not in _EQUITY_STRUCTURES
    ]
    has_options = len(option_trades) >= min_option_trades
    checks.append(HealthCheck(
        name="option_trades_exist",
        passed=has_options,
        detail=(
            f"{len(option_trades)} option trade(s) found "
            f"(min={min_option_trades})"
        ),
    ))
    if not has_options:
        blocking.append(
            f"No option trades found (need >= {min_option_trades})"
        )

    # ── Check 2: pnl_not_stale ──
    stale_pnl_trades: list[str] = []
    for t in trades:
        days = _compute_days_held(t.get("opened_at"))
        if days is not None and days > 1:
            pnl = t.get("total_pnl")
            if pnl is None or pnl == 0:
                ticker = t.get("ticker", "unknown")
                stale_pnl_trades.append(ticker)
    pnl_ok = len(stale_pnl_trades) == 0
    checks.append(HealthCheck(
        name="pnl_not_stale",
        passed=pnl_ok,
        detail=(
            "All positions have non-zero PnL"
            if pnl_ok
            else f"Stale PnL on: {', '.join(stale_pnl_trades)}"
        ),
    ))
    if not pnl_ok:
        warnings.append(f"Stale PnL detected on: {', '.join(stale_pnl_trades)}")

    # ── Check 3: prices_updated ──
    stale_price_trades: list[str] = []
    for t in trades:
        cp = t.get("current_price")
        ep = t.get("entry_price")
        days = _compute_days_held(t.get("opened_at"))
        if (
            cp is not None
            and ep is not None
            and cp == ep
            and days is not None
            and days > 0
        ):
            stale_price_trades.append(t.get("ticker", "unknown"))
    prices_ok = len(stale_price_trades) == 0
    checks.append(HealthCheck(
        name="prices_updated",
        passed=prices_ok,
        detail=(
            "All prices updated after mark"
            if prices_ok
            else f"Stale prices on: {', '.join(stale_price_trades)}"
        ),
    ))
    if not prices_ok:
        warnings.append(
            f"Prices unchanged since entry on: {', '.join(stale_price_trades)}"
        )

    # ── Check 4: no_quantity_doubling ──
    doubling_trades: list[str] = []
    for t in trades:
        st = (t.get("structure_type") or "").lower()
        if "equity" in st:
            cp = t.get("current_price")
            ep = t.get("entry_price")
            if cp and ep and ep > 0 and cp > 2 * ep:
                doubling_trades.append(t.get("ticker", "unknown"))
    no_doubling = len(doubling_trades) == 0
    checks.append(HealthCheck(
        name="no_quantity_doubling",
        passed=no_doubling,
        detail=(
            "No quantity doubling detected"
            if no_doubling
            else f"Quantity doubling suspected: {', '.join(doubling_trades)}"
        ),
    ))
    if not no_doubling:
        blocking.append(
            f"Quantity doubling bug suspected on: {', '.join(doubling_trades)}"
        )

    # ── Check 5: decisions_include_options ──
    _option_strategy_names = {
        "iron_condor", "iron_butterfly", "credit_spread", "debit_spread",
        "calendar", "diagonal", "strangle", "straddle", "ratio_spread",
        "put_spread", "call_spread", "zero_dte", "leap",
    }
    option_decisions = [
        d for d in decisions
        if (d.get("strategy_type") or d.get("structure_type") or "").lower().replace(" ", "_")
        in _option_strategy_names
    ]
    has_opt_decisions = len(option_decisions) > 0
    checks.append(HealthCheck(
        name="decisions_include_options",
        passed=has_opt_decisions,
        detail=(
            f"{len(option_decisions)} option decision(s) in log"
            if has_opt_decisions
            else "No option strategy decisions found in decision log"
        ),
    ))
    if not has_opt_decisions:
        warnings.append("Decision log has no option strategy decisions")

    # ── Check 6: approval_rate_sane ──
    total_decisions = len(decisions)
    approved = [
        d for d in decisions
        if d.get("approved") or d.get("action") == "approved"
        or d.get("status") == "approved"
    ]
    if total_decisions > 0:
        rate = len(approved) / total_decisions
        rate_ok = 0.02 <= rate <= 0.50
        checks.append(HealthCheck(
            name="approval_rate_sane",
            passed=rate_ok,
            detail=(
                f"Approval rate: {rate:.1%} "
                f"({len(approved)}/{total_decisions})"
            ),
        ))
        if not rate_ok:
            if rate < 0.02:
                warnings.append(
                    f"Approval rate too low ({rate:.1%}) — gates may be too strict"
                )
            else:
                warnings.append(
                    f"Approval rate too high ({rate:.1%}) — gates may be too loose"
                )
    else:
        checks.append(HealthCheck(
            name="approval_rate_sane",
            passed=True,
            detail="No decisions to evaluate approval rate",
        ))

    # ── Compute overall health ──
    if blocking:
        overall = "RED"
    elif warnings:
        overall = "YELLOW"
    else:
        overall = "GREEN"

    return PipelineHealthReport(
        overall_health=overall,
        checks=checks,
        blocking_issues=blocking,
        warnings=warnings,
    )


# ── Function 3: validate_full_pipeline ──


def validate_full_pipeline(
    simulation: str = "ideal_income",
) -> PipelineTestResult:
    """Run an end-to-end pipeline smoke test using simulated data.

    Args:
        simulation: Which simulation preset to use.
            "ideal_income" (default) or "india".

    Returns:
        PipelineTestResult with pass/fail per stage.
    """
    stages_passed: list[str] = []
    stages_failed: list[tuple[str, str]] = []
    sample_trade: dict | None = None

    # ── Stage 1: Create simulation ──
    try:
        from income_desk.adapters.simulated import (
            create_ideal_income,
            create_india_trading,
        )

        if simulation == "india":
            sim = create_india_trading()
        else:
            sim = create_ideal_income()

        sim_tickers = list(sim._tickers.keys())
        stages_passed.append("create_simulation")
    except Exception as exc:
        stages_failed.append(("create_simulation", str(exc)))
        return PipelineTestResult(
            passed=False,
            stages_passed=stages_passed,
            stages_failed=stages_failed,
        )

    # ── Stage 2: Init MarketAnalyzer ──
    try:
        from income_desk.service.analyzer import MarketAnalyzer
        from income_desk.data.service import DataService

        ma = MarketAnalyzer(
            data_service=DataService(),
            market_data=sim,
        )
        stages_passed.append("init_market_analyzer")
    except Exception as exc:
        stages_failed.append(("init_market_analyzer", str(exc)))
        return PipelineTestResult(
            passed=False,
            stages_passed=stages_passed,
            stages_failed=stages_failed,
        )

    # ── Stage 3: Rank trades ──
    try:
        result = ma.ranking.rank(sim_tickers, skip_intraday=True)
        assert result.top_trades, "No top_trades returned from ranking"

        # Verify at least one trade has legs
        has_legs = any(
            t.trade_spec and t.trade_spec.legs
            for t in result.top_trades
        )
        assert has_legs, "No TradeSpec with legs found in top_trades"

        stages_passed.append("rank_trades")
    except Exception as exc:
        stages_failed.append(("rank_trades", str(exc)))
        return PipelineTestResult(
            passed=False,
            stages_passed=stages_passed,
            stages_failed=stages_failed,
        )

    # Find the best trade with a trade_spec for subsequent stages
    best = None
    for entry in result.top_trades:
        if entry.trade_spec and entry.trade_spec.legs:
            best = entry
            break

    if best is None:
        stages_failed.append(("select_best_trade", "No trade with trade_spec found"))
        return PipelineTestResult(
            passed=False,
            stages_passed=stages_passed,
            stages_failed=stages_failed,
        )

    trade_spec = best.trade_spec
    ticker = best.ticker
    # TradeSpec uses limit_price (not entry_price) for the estimated fill price
    entry_price = trade_spec.limit_price or trade_spec.max_entry_price or 1.0
    underlying = trade_spec.underlying_price or 100.0
    sample_trade = {
        "ticker": ticker,
        "strategy": best.strategy_name,
        "score": best.composite_score,
        "structure_type": str(trade_spec.structure_type) if trade_spec else None,
    }

    # ── Stage 4: estimate_pop ──
    try:
        from income_desk.trade_lifecycle import estimate_pop
        pop = estimate_pop(
            trade_spec=trade_spec,
            entry_price=entry_price,
            regime_id=1,
            atr_pct=1.0,
            current_price=underlying,
        )
        if pop is not None:
            assert pop.pop_pct > 0, f"POP is {pop.pop_pct}, expected > 0"
            sample_trade["pop_pct"] = pop.pop_pct
        # pop can be None for unsupported structure types — acceptable
        stages_passed.append("estimate_pop")
    except Exception as exc:
        stages_failed.append(("estimate_pop", str(exc)))

    # ── Stage 5: run_daily_checks ──
    try:
        from income_desk.validation.daily_readiness import run_daily_checks

        report = run_daily_checks(
            ticker=ticker,
            trade_spec=trade_spec,
            entry_credit=entry_price,
            regime_id=1,
            atr_pct=1.0,
            current_price=underlying,
            avg_bid_ask_spread_pct=0.3,
            dte=trade_spec.target_dte or 30,
            rsi=50.0,
            iv_rank=50.0,
        )
        # Just check it doesn't crash — report may have failures in sim
        stages_passed.append("run_daily_checks")
    except Exception as exc:
        stages_failed.append(("run_daily_checks", str(exc)))

    # ── Stage 6: compute_position_size ──
    try:
        from income_desk.features.position_sizing import compute_position_size
        from income_desk.trade_lifecycle import compute_income_yield

        yield_result = compute_income_yield(trade_spec, entry_price)

        if yield_result is not None:
            size = compute_position_size(
                pop_pct=70.0,
                max_profit=yield_result.max_profit,
                max_loss=yield_result.max_loss,
                capital=50_000.0,
                risk_per_contract=yield_result.max_loss,
                regime_id=1,
                wing_width=yield_result.wing_width,
            )
            assert size.recommended_contracts > 0, (
                f"recommended_contracts={size.recommended_contracts}, expected > 0"
            )
            stages_passed.append("compute_position_size")
            sample_trade["contracts"] = size.recommended_contracts
        else:
            # Non-credit trade — try with synthetic values
            size = compute_position_size(
                pop_pct=70.0,
                max_profit=150.0,
                max_loss=350.0,
                capital=50_000.0,
                risk_per_contract=350.0,
                regime_id=1,
                wing_width=5.0,
            )
            assert size.recommended_contracts > 0, (
                f"recommended_contracts={size.recommended_contracts}, expected > 0"
            )
            stages_passed.append("compute_position_size")
            sample_trade["contracts"] = size.recommended_contracts
    except Exception as exc:
        stages_failed.append(("compute_position_size", str(exc)))

    # ── Stage 7: compute_income_yield ──
    try:
        from income_desk.trade_lifecycle import compute_income_yield

        yield_result = compute_income_yield(trade_spec, entry_price)
        if yield_result is not None:
            assert yield_result.roc_pct > 0, f"ROC is {yield_result.roc_pct}, expected > 0"
            sample_trade["roc_pct"] = yield_result.roc_pct
        # yield_result can be None for non-credit trades — that's OK
        stages_passed.append("compute_income_yield")
    except Exception as exc:
        stages_failed.append(("compute_income_yield", str(exc)))

    # ── Stage 8: monitor_exit_conditions ──
    try:
        from income_desk.trade_lifecycle import monitor_exit_conditions, ExitMonitorResult

        st = str(trade_spec.structure_type or "iron_condor")
        exit_result = monitor_exit_conditions(
            trade_id="test-pipeline-001",
            ticker=ticker,
            structure_type=st,
            order_side=str(trade_spec.order_side or "sell"),
            entry_price=entry_price,
            current_mid_price=entry_price * 0.6,  # simulate 40% profit
            contracts=1,
            dte_remaining=trade_spec.target_dte or 30,
            regime_id=1,
        )
        assert isinstance(exit_result, ExitMonitorResult), (
            f"Expected ExitMonitorResult, got {type(exit_result)}"
        )
        stages_passed.append("monitor_exit_conditions")
    except Exception as exc:
        stages_failed.append(("monitor_exit_conditions", str(exc)))

    passed = len(stages_failed) == 0
    return PipelineTestResult(
        passed=passed,
        stages_passed=stages_passed,
        stages_failed=stages_failed,
        sample_trade=sample_trade,
    )


# ── Helpers ──


def _compute_days_held(opened_at: Any) -> int | None:
    """Compute days held from an opened_at value.

    Returns None if opened_at is missing or unparseable.
    """
    if opened_at is None:
        return None
    try:
        if isinstance(opened_at, str):
            # Try ISO format
            dt = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
        elif isinstance(opened_at, datetime):
            dt = opened_at
        else:
            return None

        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = now - dt
        return max(0, delta.days)
    except (ValueError, TypeError):
        return None
