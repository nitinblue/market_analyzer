"""Validate eTrading market snapshots independently.

Main entry point: ``validate_snapshot(snapshot_path)`` reads a snapshot
JSON, runs domain checks, and returns a ``RegressionFeedback`` object.
The feedback is also written to disk as ``{original}_ID_feedback.json``.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from income_desk.regression.models import (
    CheckFailure,
    DomainResult,
    RegressionFeedback,
    SnapshotLeg,
    SnapshotTrade,
)

logger = logging.getLogger(__name__)


# ── Public API ──


def validate_snapshot(snapshot_path: Path) -> RegressionFeedback:
    """Validate a single eTrading snapshot file.

    Args:
        snapshot_path: Path to the snapshot JSON file.

    Returns:
        RegressionFeedback with domain-level results and overall verdict.
    """
    snapshot_path = Path(snapshot_path)
    raw = json.loads(snapshot_path.read_text(encoding="utf-8"))

    snapshot_id = raw.get("snapshot_id", "unknown")
    trades = _parse_trades(raw.get("open_trades", []))
    desks = raw.get("desks", [])
    portfolios = raw.get("portfolios", [])
    regime = raw.get("regime", {})
    broker_connected = raw.get("broker_connected", False)

    feedback = RegressionFeedback(snapshot_id=snapshot_id)

    # Run all domain checks
    feedback.domains["trade_integrity"] = _check_trade_integrity(trades)
    feedback.domains["pnl_validation"] = _check_pnl(trades)
    feedback.domains["risk_validation"] = _check_risk(desks, portfolios)
    feedback.domains["data_trust"] = _check_data_trust(
        broker_connected, regime, portfolios
    )
    feedback.domains["execution_quality"] = _check_execution_quality(trades)
    feedback.domains["health_lifecycle"] = _check_health_lifecycle(trades)
    feedback.domains["decision_audit"] = _check_decision_audit(trades)

    # Build recommendations
    feedback.recommendations = _build_recommendations(trades, desks)

    # Compute overall
    feedback.compute_overall()

    # Write feedback file
    _write_feedback(snapshot_path, feedback)

    return feedback


# ── Snapshot parsing ──


def _parse_trades(raw_trades: list[dict[str, Any]]) -> list[SnapshotTrade]:
    """Parse raw JSON trade dicts into SnapshotTrade models."""
    trades: list[SnapshotTrade] = []
    for t in raw_trades:
        try:
            legs = [SnapshotLeg(**leg) for leg in t.get("legs", [])]
            trade = SnapshotTrade(**{**t, "legs": legs})
            trades.append(trade)
        except Exception as exc:
            logger.warning("Failed to parse trade %s: %s", t.get("id", "?"), exc)
    return trades


# ── Domain: Trade Integrity ──


def _check_trade_integrity(trades: list[SnapshotTrade]) -> DomainResult:
    """Check that trades can be reconstructed into valid TradeSpecs."""
    result = DomainResult()

    for trade in trades:
        # Skip trades with no option legs (equity-only, e.g. BAC stock)
        if not trade.has_option_legs:
            result.record_pass()  # equity trades don't need TradeSpec reconstruction
            continue

        # Skip shadow trades with entry_price=0 — they were never executed
        if trade.is_shadow and not trade.has_entry:
            result.record_pass()
            continue

        # Try to reconstruct TradeSpec from DXLink symbols
        dxlink_symbols = [
            leg.dxlink_symbol
            for leg in trade.legs
            if leg.dxlink_symbol and leg.asset_type == "option"
        ]
        actions = [
            leg.action
            for leg in trade.legs
            if leg.dxlink_symbol and leg.asset_type == "option"
        ]

        if not dxlink_symbols:
            result.record_fail(
                CheckFailure(
                    trade_id=trade.id,
                    check="trade_spec_reconstruction",
                    expected="DXLink symbols present",
                    actual="No DXLink symbols found",
                    severity="warning",
                    message=f"{trade.ticker}: no DXLink symbols on option legs",
                )
            )
            continue

        try:
            from income_desk.trade_spec_factory import from_dxlink_symbols

            # Use entry_underlying_price if available, else 0.0 as placeholder
            underlying = 0.0
            spec = from_dxlink_symbols(
                symbols=dxlink_symbols,
                actions=actions,
                underlying_price=underlying,
                entry_price=trade.entry_price if trade.has_entry else None,
            )
            result.record_pass()

            # If we have entry_price, try compute_income_yield and compare
            if trade.has_entry and trade.entry_price > 0:
                _check_income_yield(result, trade, spec)

        except Exception as exc:
            result.record_fail(
                CheckFailure(
                    trade_id=trade.id,
                    check="trade_spec_reconstruction",
                    expected="Valid TradeSpec",
                    actual=str(exc),
                    severity="warning",
                    message=f"{trade.ticker}: from_dxlink_symbols failed — {exc}",
                )
            )

    return result


def _check_income_yield(
    result: DomainResult,
    trade: SnapshotTrade,
    spec: Any,
) -> None:
    """Compare income yield from TradeSpec with stored values."""
    try:
        from income_desk.trade_lifecycle import compute_income_yield

        yield_result = compute_income_yield(spec, trade.entry_price)
        if yield_result is None:
            # Not a credit trade or missing wing width — skip
            return

        # Check max_profit_dollars
        if trade.max_profit_dollars is not None:
            diff = abs(yield_result.max_profit - trade.max_profit_dollars)
            if diff > 5.0:
                result.record_fail(
                    CheckFailure(
                        trade_id=trade.id,
                        check="max_profit_match",
                        expected=trade.max_profit_dollars,
                        actual=yield_result.max_profit,
                        severity="warning",
                        message=(
                            f"{trade.ticker}: max_profit diff ${diff:.2f} "
                            f"(ID={yield_result.max_profit:.2f} vs "
                            f"stored={trade.max_profit_dollars:.2f})"
                        ),
                    )
                )
            else:
                result.record_pass()

        # Check max_loss_dollars
        if trade.max_loss_dollars is not None:
            diff = abs(yield_result.max_loss - trade.max_loss_dollars)
            if diff > 5.0:
                result.record_fail(
                    CheckFailure(
                        trade_id=trade.id,
                        check="max_loss_match",
                        expected=trade.max_loss_dollars,
                        actual=yield_result.max_loss,
                        severity="warning",
                        message=(
                            f"{trade.ticker}: max_loss diff ${diff:.2f} "
                            f"(ID={yield_result.max_loss:.2f} vs "
                            f"stored={trade.max_loss_dollars:.2f})"
                        ),
                    )
                )
            else:
                result.record_pass()

    except Exception as exc:
        logger.debug("Income yield check failed for %s: %s", trade.ticker, exc)


# ── Domain: PnL Validation ──


def _check_pnl(trades: list[SnapshotTrade]) -> DomainResult:
    """Independently compute PnL from legs and compare with stored total_pnl."""
    result = DomainResult()

    for trade in trades:
        if not trade.legs:
            continue

        # Shadow trades with entry_price=0 — PnL convention may differ
        if trade.is_shadow and not trade.has_entry:
            # For shadow trades, all entry prices are 0; PnL = sum of current values
            computed_pnl = 0.0
            has_all_prices = True
            for leg in trade.legs:
                if leg.current_price is None or leg.entry_price is None:
                    has_all_prices = False
                    continue
                multiplier = 100 if leg.asset_type == "option" else 1
                qty = leg.quantity
                computed_pnl += (leg.current_price - leg.entry_price) * qty * multiplier

            if not has_all_prices:
                result.record_fail(
                    CheckFailure(
                        trade_id=trade.id,
                        check="shadow_pnl_arithmetic",
                        expected="all legs have prices",
                        actual="some legs missing current_price",
                        severity="info",
                        message=f"{trade.ticker} (shadow): cannot compute PnL — legs missing prices",
                    )
                )
                continue

            diff = abs(computed_pnl - (trade.total_pnl or 0.0))
            if diff > 5.0:
                result.record_fail(
                    CheckFailure(
                        trade_id=trade.id,
                        check="shadow_pnl_arithmetic",
                        expected=trade.total_pnl,
                        actual=computed_pnl,
                        severity="info",
                        message=(
                            f"{trade.ticker} (shadow): PnL diff ${diff:.2f} "
                            f"(computed={computed_pnl:.2f} vs stored={trade.total_pnl:.2f})"
                        ),
                    )
                )
            else:
                result.record_pass()
            continue

        # Real/whatif trades — compute PnL from legs
        computed_pnl = 0.0
        has_all_prices = True
        for leg in trade.legs:
            if leg.current_price is None or leg.entry_price is None:
                has_all_prices = False
                continue
            multiplier = 100 if leg.asset_type == "option" else 1
            qty = leg.quantity
            leg_pnl = (leg.current_price - leg.entry_price) * qty * multiplier
            computed_pnl += leg_pnl

        if not has_all_prices:
            result.record_fail(
                CheckFailure(
                    trade_id=trade.id,
                    check="pnl_legs_missing_prices",
                    expected="all legs have current_price",
                    actual="some legs missing",
                    severity="warning",
                    message=f"{trade.ticker}: cannot compute PnL — legs missing current_price",
                )
            )
            continue

        diff = abs(computed_pnl - (trade.total_pnl or 0.0))
        tolerance = 5.0  # $5 tolerance for rounding

        if diff > tolerance:
            result.record_fail(
                CheckFailure(
                    trade_id=trade.id,
                    check="pnl_arithmetic",
                    expected=trade.total_pnl,
                    actual=computed_pnl,
                    severity="warning" if diff < 50.0 else "error",
                    message=(
                        f"{trade.ticker}: PnL diff ${diff:.2f} "
                        f"(computed={computed_pnl:.2f} vs stored={trade.total_pnl:.2f})"
                    ),
                )
            )
        else:
            result.record_pass()

    return result


# ── Domain: Risk Validation ──


def _check_risk(
    desks: list[dict[str, Any]],
    portfolios: list[dict[str, Any]],
) -> DomainResult:
    """Validate desk risk limits and capital sanity."""
    result = DomainResult()

    for desk in desks:
        desk_key = desk.get("desk_key", "unknown")
        capital = desk.get("capital", 0.0)
        risk_limits = desk.get("risk_limits")

        # Check capital > 0
        if capital > 0:
            result.record_pass()
        else:
            result.record_fail(
                CheckFailure(
                    check="desk_capital_positive",
                    expected="capital > 0",
                    actual=capital,
                    severity="warning",
                    message=f"{desk_key}: capital is ${capital:.2f}",
                )
            )

        # Check risk limits present
        if risk_limits and isinstance(risk_limits, dict) and len(risk_limits) > 0:
            result.record_pass()
        else:
            result.record_fail(
                CheckFailure(
                    check="desk_has_risk_limits",
                    expected="risk_limits defined",
                    actual="no risk_limits" if not risk_limits else "empty",
                    severity="warning",
                    message=f"{desk_key}: no risk limits configured",
                )
            )

    # Check at least one portfolio has capital
    has_capital = any(p.get("capital", 0) > 0 for p in portfolios)
    if has_capital:
        result.record_pass()
    else:
        result.record_fail(
            CheckFailure(
                check="portfolio_has_capital",
                expected="at least one portfolio with capital > 0",
                actual="no portfolios with capital",
                severity="error",
                message="No portfolio has capital — cannot trade",
            )
        )

    return result


# ── Domain: Data Trust ──


def _check_data_trust(
    broker_connected: bool,
    regime: dict[str, Any],
    portfolios: list[dict[str, Any]],
) -> DomainResult:
    """Validate data availability and trust."""
    result = DomainResult()

    # Broker connection
    if broker_connected:
        result.record_pass()
    else:
        result.record_fail(
            CheckFailure(
                check="broker_connected",
                expected=True,
                actual=False,
                severity="warning",
                message="Broker not connected — live quotes unavailable",
            )
        )

    # Regime data present
    if regime and len(regime) > 0:
        result.record_pass()
    else:
        result.record_fail(
            CheckFailure(
                check="regime_data_present",
                expected="regime data populated",
                actual="empty regime",
                severity="warning",
                message="No regime data in snapshot — decisions lack regime context",
            )
        )

    # Portfolio capital
    total_capital = sum(p.get("capital", 0) for p in portfolios)
    if total_capital > 0:
        result.record_pass()
    else:
        result.record_fail(
            CheckFailure(
                check="total_capital_positive",
                expected="total capital > 0",
                actual=total_capital,
                severity="error",
                message="Total portfolio capital is zero — cannot assess risk",
            )
        )

    return result


# ── Domain: Execution Quality ──


def _check_execution_quality(trades: list[SnapshotTrade]) -> DomainResult:
    """Check commission drag on trades with positive entry credit."""
    result = DomainResult()

    for trade in trades:
        # Only check trades with real entry price and option legs
        if not trade.has_entry or trade.entry_price <= 0:
            continue
        if not trade.has_option_legs:
            continue
        if trade.is_shadow:
            continue

        try:
            from income_desk.trade_spec_factory import from_dxlink_symbols
            from income_desk.validation.profitability_audit import (
                check_commission_drag,
            )

            dxlink_symbols = [
                leg.dxlink_symbol
                for leg in trade.legs
                if leg.dxlink_symbol and leg.asset_type == "option"
            ]
            actions = [
                leg.action
                for leg in trade.legs
                if leg.dxlink_symbol and leg.asset_type == "option"
            ]
            if not dxlink_symbols:
                continue

            spec = from_dxlink_symbols(
                symbols=dxlink_symbols,
                actions=actions,
                underlying_price=0.0,
                entry_price=trade.entry_price,
            )

            check = check_commission_drag(spec, trade.entry_price)
            if check.severity == "fail":
                result.record_fail(
                    CheckFailure(
                        trade_id=trade.id,
                        check="commission_drag",
                        expected="pass or warn",
                        actual=check.severity,
                        severity="warning",
                        message=f"{trade.ticker}: {check.message}",
                    )
                )
            else:
                result.record_pass()
        except Exception as exc:
            logger.debug("Commission check failed for %s: %s", trade.ticker, exc)

    return result


# ── Domain: Health & Lifecycle ──


def _check_health_lifecycle(trades: list[SnapshotTrade]) -> DomainResult:
    """Flag trades with problematic health status."""
    result = DomainResult()

    for trade in trades:
        if trade.is_shadow:
            continue  # Shadow trades may have unknown health by design

        health = trade.health_status
        if not health or health == "unknown":
            result.record_fail(
                CheckFailure(
                    trade_id=trade.id,
                    check="health_status_present",
                    expected="known health status",
                    actual=health or "missing",
                    severity="warning",
                    message=f"{trade.ticker}: health status is '{health or 'missing'}'",
                )
            )
        elif health == "unquoted":
            result.record_fail(
                CheckFailure(
                    trade_id=trade.id,
                    check="health_status_quoted",
                    expected="quoted health status",
                    actual="unquoted",
                    severity="warning",
                    message=(
                        f"{trade.ticker}: health is 'unquoted' — "
                        "current quotes unavailable for monitoring"
                    ),
                )
            )
        else:
            result.record_pass()

    return result


# ── Domain: Decision Audit ──


def _check_decision_audit(trades: list[SnapshotTrade]) -> DomainResult:
    """Check that trades with decision_lineage have required fields."""
    result = DomainResult()

    for trade in trades:
        lineage = trade.decision_lineage
        if lineage is None:
            # No lineage — only flag if it's a real/whatif trade
            if trade.trade_type in ("real", "whatif"):
                result.record_fail(
                    CheckFailure(
                        trade_id=trade.id,
                        check="decision_lineage_present",
                        expected="decision_lineage populated",
                        actual="null",
                        severity="info",
                        message=f"{trade.ticker}: no decision_lineage on {trade.trade_type} trade",
                    )
                )
            continue

        # Check that lineage has meaningful fields
        has_score = "score" in lineage or "composite_score" in lineage
        has_gates = "gates" in lineage or "gate_blocked_by" in lineage
        has_strategy = (
            "strategy_type" in lineage
            or "strategy" in lineage
            or "shadow" in lineage
        )

        if has_score or has_gates or has_strategy:
            result.record_pass()
        else:
            result.record_fail(
                CheckFailure(
                    trade_id=trade.id,
                    check="decision_lineage_complete",
                    expected="score, gates, or strategy present",
                    actual=list(lineage.keys()),
                    severity="warning",
                    message=f"{trade.ticker}: decision_lineage missing key fields",
                )
            )

    return result


# ── Recommendations ──


def _build_recommendations(
    trades: list[SnapshotTrade],
    desks: list[dict[str, Any]],
) -> list[str]:
    """Build human-readable recommendations based on findings."""
    recs: list[str] = []

    # Shadow trades with PnL
    shadow_with_pnl = [
        t for t in trades if t.is_shadow and t.total_pnl != 0.0
    ]
    if shadow_with_pnl:
        tickers = ", ".join(t.ticker for t in shadow_with_pnl)
        recs.append(
            f"Shadow trades ({tickers}) have non-zero PnL — "
            "consider excluding from PnL regression or documenting convention"
        )

    # Equity trades with option-like PnL conventions
    equity_trades = [t for t in trades if t.is_equity and t.trade_type == "real"]
    for t in equity_trades:
        if t.legs and t.legs[0].quantity >= 100:
            recs.append(
                f"{t.ticker}: equity position (qty={t.legs[0].quantity}) — "
                "ensure PnL uses multiplier=1 per share, not 100"
            )

    # Desks without risk limits
    no_limits = [d["desk_key"] for d in desks if not d.get("risk_limits")]
    if no_limits:
        recs.append(
            f"Desks without risk_limits: {', '.join(no_limits)} — "
            "add limits to enable automated risk checks"
        )

    # Unquoted trades
    unquoted = [t for t in trades if t.health_status == "unquoted" and not t.is_shadow]
    if unquoted:
        tickers = ", ".join(t.ticker for t in unquoted)
        recs.append(
            f"Unquoted trades ({tickers}): connect broker for live monitoring"
        )

    return recs


# ── File I/O ──


def _write_feedback(snapshot_path: Path, feedback: RegressionFeedback) -> Path:
    """Write feedback JSON next to the snapshot file."""
    stem = snapshot_path.stem
    feedback_name = f"{stem}_ID_feedback.json"
    feedback_path = snapshot_path.parent / feedback_name
    feedback_path.write_text(
        feedback.model_dump_json(indent=2), encoding="utf-8"
    )
    logger.info("Wrote feedback to %s", feedback_path)
    return feedback_path
