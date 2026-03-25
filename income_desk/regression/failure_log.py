"""Failure capture framework — no failure should ever be silent.

Captures ALL failures from regression validation, ranking, assessors,
and broker calls into a structured, queryable log with JSON-lines
persistence.

Usage::

    from income_desk.regression.failure_log import capture_failure, default_log

    # Quick one-liner (uses module-level singleton)
    capture_failure(
        source="broker",
        severity="error",
        message="DXLink stream disconnected",
        ticker="SPY",
        details={"reconnect_attempts": 3},
    )

    # Direct access to the log
    log = default_log()
    if log.has_critical():
        print(log.summary())
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Enums ──


class FailureSource(StrEnum):
    """Where the failure originated."""

    REGRESSION = "regression"
    RANKING = "ranking"
    ASSESSOR = "assessor"
    BROKER = "broker"
    DATA = "data"


class FailureSeverity(StrEnum):
    """How bad is it."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ── Models ──


class FailureRecord(BaseModel):
    """A single captured failure."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    source: str  # FailureSource value — kept as str for flexibility
    severity: str  # FailureSeverity value
    ticker: str | None = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    category: str = ""


class FailureSummary(BaseModel):
    """Aggregated counts from a FailureLog."""

    total: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)
    has_critical: bool = False


# ── Default log path ──

_DEFAULT_LOG_DIR = Path.home() / ".income_desk"
_DEFAULT_LOG_PATH = _DEFAULT_LOG_DIR / "failure_log.jsonl"


# ── FailureLog ──


class FailureLog:
    """Append-only failure log backed by in-memory list and JSON-lines file.

    Thread-safe: a lock guards both the in-memory list and file writes.

    Args:
        log_path: Path to the JSON-lines file.  Created on first write.
                  Pass ``None`` to disable file persistence (in-memory only).
    """

    def __init__(self, log_path: Path | None = _DEFAULT_LOG_PATH) -> None:
        self._records: list[FailureRecord] = []
        self._log_path = log_path
        self._lock = threading.Lock()

    # ── Recording ──

    def record(
        self,
        source: str,
        severity: str,
        message: str,
        *,
        ticker: str | None = None,
        details: dict[str, Any] | None = None,
        category: str = "",
    ) -> FailureRecord:
        """Record a failure.

        Args:
            source: Origin system (regression/ranking/assessor/broker/data).
            severity: One of info/warning/error/critical.
            message: Human-readable description.
            ticker: Affected ticker symbol, if applicable.
            details: Arbitrary context dict.
            category: Free-form sub-category for grouping.

        Returns:
            The created FailureRecord.
        """
        rec = FailureRecord(
            source=source,
            severity=severity,
            message=message,
            ticker=ticker,
            details=details or {},
            category=category,
        )

        with self._lock:
            self._records.append(rec)
            self._persist(rec)

        # Also emit to standard logging at the appropriate level
        log_level = {
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL,
        }.get(severity, logging.WARNING)
        logger.log(
            log_level,
            "[%s/%s] %s%s",
            source,
            severity,
            f"{ticker}: " if ticker else "",
            message,
        )

        return rec

    # ── Queries ──

    def get_recent(self, n: int = 50) -> list[FailureRecord]:
        """Return the last *n* failures (newest last)."""
        with self._lock:
            return list(self._records[-n:])

    def get_by_severity(self, severity: str) -> list[FailureRecord]:
        """Return all failures matching the given severity."""
        with self._lock:
            return [r for r in self._records if r.severity == severity]

    def get_by_source(self, source: str) -> list[FailureRecord]:
        """Return all failures matching the given source."""
        with self._lock:
            return [r for r in self._records if r.source == source]

    def has_critical(self) -> bool:
        """Return True if any critical failure has been recorded."""
        with self._lock:
            return any(r.severity == FailureSeverity.CRITICAL for r in self._records)

    def summary(self) -> FailureSummary:
        """Return aggregated counts by severity and source."""
        with self._lock:
            by_severity: dict[str, int] = {}
            by_source: dict[str, int] = {}
            for r in self._records:
                by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
                by_source[r.source] = by_source.get(r.source, 0) + 1
            return FailureSummary(
                total=len(self._records),
                by_severity=by_severity,
                by_source=by_source,
                has_critical=any(
                    r.severity == FailureSeverity.CRITICAL for r in self._records
                ),
            )

    # ── Internals ──

    def _persist(self, rec: FailureRecord) -> None:
        """Append a single record to the JSON-lines file.

        Called inside the lock — must not re-acquire.
        """
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(rec.model_dump_json() + "\n")
        except OSError as exc:
            # File write failures must not crash the caller, but we log them
            logger.error("Failed to persist failure record: %s", exc)


# ── Module-level singleton ──

_singleton_lock = threading.Lock()
_singleton: FailureLog | None = None


def default_log() -> FailureLog:
    """Return the module-level singleton FailureLog.

    Creates it on first call.  Thread-safe.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = FailureLog()
    return _singleton


def capture_failure(
    source: str,
    severity: str,
    message: str,
    *,
    ticker: str | None = None,
    details: dict[str, Any] | None = None,
    category: str = "",
) -> FailureRecord:
    """Convenience — record a failure on the default singleton log.

    Same signature as :meth:`FailureLog.record`.
    """
    return default_log().record(
        source=source,
        severity=severity,
        message=message,
        ticker=ticker,
        details=details,
        category=category,
    )
