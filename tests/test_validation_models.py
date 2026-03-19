"""Tests for validation result models."""
from market_analyzer.validation.models import (
    CheckResult, Severity, Suite, ValidationReport,
)
from datetime import date


def test_check_result_creation() -> None:
    r = CheckResult(
        name="commission_drag",
        severity=Severity.PASS,
        message="Credit covers fees",
        value=1.50,
        threshold=0.52,
    )
    assert r.severity == Severity.PASS
    assert r.name == "commission_drag"


def test_validation_report_summary_ready() -> None:
    report = ValidationReport(
        ticker="SPY",
        suite=Suite.DAILY,
        as_of=date(2026, 3, 18),
        checks=[
            CheckResult(name="a", severity=Severity.PASS, message="ok"),
            CheckResult(name="b", severity=Severity.WARN, message="marginal"),
        ],
    )
    assert report.is_ready is True
    assert report.passed == 1
    assert report.warnings == 1
    assert report.failures == 0
    assert "READY TO TRADE" in report.summary


def test_validation_report_summary_not_ready() -> None:
    report = ValidationReport(
        ticker="SPY",
        suite=Suite.DAILY,
        as_of=date(2026, 3, 18),
        checks=[
            CheckResult(name="a", severity=Severity.PASS, message="ok"),
            CheckResult(name="b", severity=Severity.FAIL, message="bad"),
        ],
    )
    assert report.is_ready is False
    assert "NOT READY" in report.summary


def test_validation_report_serializes_computed_fields() -> None:
    """model_dump() must include is_ready and summary for MCP consumers."""
    report = ValidationReport(
        ticker="SPY",
        suite=Suite.DAILY,
        as_of=date(2026, 3, 18),
        checks=[
            CheckResult(name="a", severity=Severity.PASS, message="ok"),
        ],
    )
    d = report.model_dump()
    assert "is_ready" in d
    assert "summary" in d
    assert d["is_ready"] is True
