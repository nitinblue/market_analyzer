"""Pydantic models for eTrading snapshot regression validation."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


# ── Snapshot parsing models ──


class SnapshotLeg(BaseModel):
    """A single leg parsed from the snapshot JSON."""

    id: str | None = None
    symbol_ticker: str | None = None
    asset_type: str | None = None
    option_type: str | None = None
    strike: float | None = None
    expiration: str | None = None
    quantity: int = 1
    side: str | None = None
    entry_price: float | None = 0.0
    current_price: float | None = None
    exit_price: float | None = None
    delta: float | None = 0.0
    gamma: float | None = 0.0
    theta: float | None = 0.0
    vega: float | None = 0.0
    entry_delta: float | None = 0.0
    entry_gamma: float | None = 0.0
    entry_theta: float | None = 0.0
    entry_vega: float | None = 0.0
    dxlink_symbol: str | None = None
    action: str | None = None
    lot_size: int | None = None


class SnapshotTrade(BaseModel):
    """A trade parsed from the snapshot JSON."""

    id: str
    ticker: str
    trade_type: str = "real"
    trade_status: str | None = None
    trade_source: str | None = None
    is_open: bool = True
    desk_key: str | None = None
    portfolio_id: str | None = None
    portfolio_name: str | None = None
    strategy_type: str | None = None
    entry_price: float | None = 0.0
    current_price: float | None = None
    total_pnl: float | None = 0.0
    delta_pnl: float | None = 0.0
    gamma_pnl: float | None = 0.0
    theta_pnl: float | None = 0.0
    vega_pnl: float | None = 0.0
    unexplained_pnl: float | None = 0.0
    max_risk: float | None = None
    health_status: str | None = None
    trade_quality: str | None = None
    trade_quality_score: float | None = None
    max_profit_dollars: float | None = None
    max_loss_dollars: float | None = None
    income_yield_roc: float | None = None
    credit_to_width_pct: float | None = None
    breakeven_low: float | None = None
    breakeven_high: float | None = None
    wing_width: float | None = None
    risk_profile: str | None = None
    regime_at_entry: str | None = None
    pop_at_entry: float | None = None
    ev_at_entry: float | None = None
    decision_lineage: dict[str, Any] | None = None
    entry_analytics: dict[str, Any] | None = None
    exit_plan: dict[str, Any] | None = None
    legs: list[SnapshotLeg] = Field(default_factory=list)

    @property
    def is_shadow(self) -> bool:
        return self.trade_type == "shadow"

    @property
    def is_equity(self) -> bool:
        return any(leg.asset_type == "equity" for leg in self.legs)

    @property
    def has_option_legs(self) -> bool:
        return any(leg.asset_type == "option" for leg in self.legs)

    @property
    def has_entry(self) -> bool:
        return self.entry_price != 0.0


# ── Validation result models ──


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class CheckFailure(BaseModel):
    """A single check failure."""

    trade_id: str | None = None
    check: str
    expected: Any = None
    actual: Any = None
    severity: str = "warning"
    message: str = ""


class DomainResult(BaseModel):
    """Validation result for one domain."""

    passed: int = 0
    failed: int = 0
    total: int = 0
    failures: list[CheckFailure] = Field(default_factory=list)

    def record_pass(self) -> None:
        self.passed += 1
        self.total += 1

    def record_fail(self, failure: CheckFailure) -> None:
        self.failed += 1
        self.total += 1
        self.failures.append(failure)


class OverallResult(BaseModel):
    """Overall validation summary."""

    total_checks: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    verdict: str = "GREEN"


class RegressionFeedback(BaseModel):
    """Full feedback output matching the Integration Test Spec format."""

    snapshot_id: str
    validated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    domains: dict[str, DomainResult] = Field(default_factory=dict)

    overall: OverallResult = Field(default_factory=OverallResult)

    recommendations: list[str] = Field(default_factory=list)
    simulated_data_available: bool = False

    def compute_overall(self) -> None:
        """Recompute overall from domain results."""
        total = sum(d.total for d in self.domains.values())
        passed = sum(d.passed for d in self.domains.values())
        failed = sum(d.failed for d in self.domains.values())
        rate = (passed / total * 100) if total > 0 else 0.0

        if rate >= 90:
            verdict = "GREEN"
        elif rate >= 75:
            verdict = "AMBER"
        else:
            verdict = "RED"

        self.overall = OverallResult(
            total_checks=total,
            passed=passed,
            failed=failed,
            pass_rate=round(rate, 1),
            verdict=verdict,
        )
