"""Validation result models for the profitability testing framework."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, computed_field

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): ...


class Severity(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class Suite(StrEnum):
    DAILY = "daily"
    ADVERSARIAL = "adversarial"
    FULL = "full"


class CheckResult(BaseModel):
    """Result of a single profitability check."""
    name: str
    severity: Severity
    message: str
    detail: str = ""
    value: float | None = None
    threshold: float | None = None


class ValidationReport(BaseModel):
    """Aggregated result of a validation suite run."""
    ticker: str
    suite: Suite
    as_of: date
    checks: list[CheckResult]

    @computed_field
    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.severity == Severity.PASS)

    @computed_field
    @property
    def warnings(self) -> int:
        return sum(1 for c in self.checks if c.severity == Severity.WARN)

    @computed_field
    @property
    def failures(self) -> int:
        return sum(1 for c in self.checks if c.severity == Severity.FAIL)

    @computed_field
    @property
    def is_ready(self) -> bool:
        return self.failures == 0

    @computed_field
    @property
    def summary(self) -> str:
        status = "READY TO TRADE" if self.is_ready else "NOT READY"
        total = len(self.checks)
        return f"{status} ({self.passed}/{total} passed, {self.warnings} warnings)"
