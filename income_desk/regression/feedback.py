"""Structured feedback channel between eTrading and income_desk.

Provides a shared JSON file where either system can report issues,
acknowledge them, and mark them resolved.  This is the formal
communication path for bugs, data mismatches, and integration problems.

Usage::

    from income_desk.regression.feedback import FeedbackChannel

    ch = FeedbackChannel()

    # eTrading reports an issue
    item = ch.report_issue(
        from_system="etrading",
        category="pnl_mismatch",
        severity="error",
        title="Greek PnL doesn't sum to total",
        description="delta_pnl + theta_pnl != total_pnl for trade xyz",
        affected_tickers=["SPY"],
    )

    # income_desk acknowledges
    ch.acknowledge(item.id)

    # income_desk resolves
    ch.resolve(item.id, resolution="Fixed rounding in Greek decomposition")
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Enums ──


class FeedbackSystem(StrEnum):
    ETRADING = "etrading"
    INCOME_DESK = "income_desk"


class FeedbackCategory(StrEnum):
    BUG = "bug"
    FEATURE = "feature"
    DATA_ISSUE = "data_issue"
    PNL_MISMATCH = "pnl_mismatch"
    INTEGRATION = "integration"


class FeedbackStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


# ── Models ──


class FeedbackItem(BaseModel):
    """A single feedback item in the channel."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    from_system: str  # FeedbackSystem value
    category: str  # FeedbackCategory value
    severity: str  # info/warning/error/critical
    title: str
    description: str = ""
    affected_tickers: list[str] = Field(default_factory=list)
    status: str = FeedbackStatus.OPEN
    resolution: str = ""
    resolved_at: str | None = None
    acknowledged_at: str | None = None


# ── Default path ──

_DEFAULT_FEEDBACK_DIR = Path.home() / ".income_desk" / "regression"
_DEFAULT_FEEDBACK_PATH = _DEFAULT_FEEDBACK_DIR / "feedback.json"


# ── FeedbackChannel ──


class FeedbackChannel:
    """Read/write feedback items to a shared JSON file.

    Thread-safe: a lock guards all reads and writes.

    Args:
        path: Path to the feedback JSON file.  Created on first write.
    """

    def __init__(self, path: Path | None = _DEFAULT_FEEDBACK_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()

    # ── Public API ──

    def report_issue(
        self,
        from_system: str,
        category: str,
        severity: str,
        title: str,
        description: str = "",
        affected_tickers: list[str] | None = None,
    ) -> FeedbackItem:
        """Report a new issue.

        Args:
            from_system: Which system is reporting (etrading/income_desk).
            category: bug/feature/data_issue/pnl_mismatch/integration.
            severity: info/warning/error/critical.
            title: Short summary.
            description: Full details.
            affected_tickers: Relevant ticker symbols.

        Returns:
            The created FeedbackItem (with generated id).
        """
        item = FeedbackItem(
            from_system=from_system,
            category=category,
            severity=severity,
            title=title,
            description=description,
            affected_tickers=affected_tickers or [],
        )
        with self._lock:
            items = self._load()
            items.append(item)
            self._save(items)

        logger.info(
            "Feedback reported [%s]: %s — %s",
            item.id,
            item.category,
            item.title,
        )
        return item

    def acknowledge(self, item_id: str) -> FeedbackItem | None:
        """Mark an item as acknowledged.

        Args:
            item_id: The id of the feedback item.

        Returns:
            The updated item, or None if not found.
        """
        with self._lock:
            items = self._load()
            for item in items:
                if item.id == item_id:
                    item.status = FeedbackStatus.ACKNOWLEDGED
                    item.acknowledged_at = datetime.now().isoformat()
                    self._save(items)
                    logger.info("Feedback acknowledged: %s", item_id)
                    return item
        logger.warning("Feedback item not found for acknowledge: %s", item_id)
        return None

    def resolve(self, item_id: str, resolution: str = "") -> FeedbackItem | None:
        """Mark an item as resolved.

        Args:
            item_id: The id of the feedback item.
            resolution: Notes on how the issue was resolved.

        Returns:
            The updated item, or None if not found.
        """
        with self._lock:
            items = self._load()
            for item in items:
                if item.id == item_id:
                    item.status = FeedbackStatus.RESOLVED
                    item.resolution = resolution
                    item.resolved_at = datetime.now().isoformat()
                    self._save(items)
                    logger.info("Feedback resolved: %s — %s", item_id, resolution)
                    return item
        logger.warning("Feedback item not found for resolve: %s", item_id)
        return None

    def get_open(self) -> list[FeedbackItem]:
        """Return all items that are not resolved."""
        with self._lock:
            items = self._load()
        return [i for i in items if i.status != FeedbackStatus.RESOLVED]

    def get_all(self) -> list[FeedbackItem]:
        """Return all feedback items."""
        with self._lock:
            return self._load()

    # ── Internals ──

    def _load(self) -> list[FeedbackItem]:
        """Load items from the JSON file.  Returns empty list if missing."""
        if self._path is None or not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [FeedbackItem.model_validate(r) for r in raw]
        except Exception as exc:
            logger.error("Failed to load feedback file %s: %s", self._path, exc)
            return []

    def _save(self, items: list[FeedbackItem]) -> None:
        """Write all items to the JSON file (full rewrite)."""
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = [item.model_dump() for item in items]
            self._path.write_text(
                json.dumps(payload, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            logger.error("Failed to save feedback file: %s", exc)
