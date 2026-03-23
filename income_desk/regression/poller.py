"""Simple poller that scans for new snapshots and validates them.

Usage::

    from income_desk.regression.poller import poll_and_validate
    from pathlib import Path

    results = poll_and_validate(Path("path/to/reports/regression/"))
"""
from __future__ import annotations

import logging
from pathlib import Path

from income_desk.regression.models import RegressionFeedback
from income_desk.regression.validator import validate_snapshot

logger = logging.getLogger(__name__)


def poll_and_validate(report_dir: Path) -> list[RegressionFeedback]:
    """Scan for snapshot files and validate any that lack feedback.

    Args:
        report_dir: Directory containing ``snapshot_*.json`` files.

    Returns:
        List of RegressionFeedback for newly validated snapshots.
    """
    report_dir = Path(report_dir)
    if not report_dir.is_dir():
        logger.warning("Report directory does not exist: %s", report_dir)
        return []

    results: list[RegressionFeedback] = []

    for snapshot_path in sorted(report_dir.glob("snapshot_*.json")):
        # Skip feedback files that also match the glob
        if "_ID_feedback" in snapshot_path.name:
            continue
        # Skip if feedback already exists
        feedback_name = f"{snapshot_path.stem}_ID_feedback.json"
        feedback_path = report_dir / feedback_name
        if feedback_path.exists():
            logger.debug("Skipping %s — feedback already exists", snapshot_path.name)
            continue

        logger.info("Validating new snapshot: %s", snapshot_path.name)
        try:
            feedback = validate_snapshot(snapshot_path)
            results.append(feedback)

            # Write feedback file so we skip this snapshot on next poll
            feedback_path.write_text(
                feedback.model_dump_json(indent=2), encoding="utf-8"
            )

            logger.info(
                "Validated %s — %s (%d/%d passed)",
                snapshot_path.name,
                feedback.overall.verdict,
                feedback.overall.passed,
                feedback.overall.total_checks,
            )
        except Exception as exc:
            logger.error("Failed to validate %s: %s", snapshot_path.name, exc)

    return results
