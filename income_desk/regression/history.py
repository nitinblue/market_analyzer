"""Historical regression tracking — trend analysis over feedback files.

Scans ``*_ID_feedback.json`` files and computes pass-rate trends,
recurring failures, and domain-level improvements/degradation.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Models ──


class HistoryEntry(BaseModel):
    """Summary of a single feedback file."""

    snapshot_id: str
    date: str
    market: str
    pass_rate: float
    verdict: str
    domain_scores: dict[str, float] = Field(default_factory=dict)


class TrendReport(BaseModel):
    """Aggregated trend analysis across multiple feedback files."""

    entries: list[HistoryEntry] = Field(default_factory=list)
    avg_pass_rate: float = 0.0
    trend_direction: str = "stable"  # "improving", "stable", "degrading"
    recurring_failures: list[str] = Field(default_factory=list)
    best_domain: str = ""
    worst_domain: str = ""


# ── Public API ──


def load_history(report_dir: Path) -> list[HistoryEntry]:
    """Scan all ``*_ID_feedback.json`` files and extract summary data.

    Args:
        report_dir: Directory containing feedback JSON files.

    Returns:
        List of HistoryEntry sorted by date (oldest first).
    """
    report_dir = Path(report_dir)
    if not report_dir.is_dir():
        logger.warning("Report directory does not exist: %s", report_dir)
        return []

    entries: list[HistoryEntry] = []

    for feedback_path in sorted(report_dir.glob("*_ID_feedback.json")):
        try:
            raw = json.loads(feedback_path.read_text(encoding="utf-8"))
            entry = _parse_feedback(raw, feedback_path)
            if entry is not None:
                entries.append(entry)
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", feedback_path.name, exc)

    # Sort by date string (ISO format sorts correctly)
    entries.sort(key=lambda e: e.date)
    return entries


def compute_trend(history: list[HistoryEntry]) -> TrendReport:
    """Compute pass rate trend, recurring failures, domain rankings.

    Args:
        history: List of HistoryEntry (from load_history).

    Returns:
        TrendReport with aggregated metrics.
    """
    if not history:
        return TrendReport()

    avg_rate = sum(e.pass_rate for e in history) / len(history)

    # Trend direction: compare first half vs second half
    trend_direction = "stable"
    if len(history) >= 2:
        mid = len(history) // 2
        first_half_avg = sum(e.pass_rate for e in history[:mid]) / mid
        second_half_avg = sum(e.pass_rate for e in history[mid:]) / (len(history) - mid)
        diff = second_half_avg - first_half_avg
        if diff > 3.0:
            trend_direction = "improving"
        elif diff < -3.0:
            trend_direction = "degrading"

    # Recurring failures: collect all failure check names across entries
    # A failure is "recurring" if it appears in more than half the entries
    failure_counts: dict[str, int] = {}
    for entry in history:
        # We don't have individual failure names in HistoryEntry,
        # but we can identify domains that consistently score < 100%
        for domain, score in entry.domain_scores.items():
            if score < 100.0:
                failure_counts[domain] = failure_counts.get(domain, 0) + 1

    threshold = max(1, len(history) // 2)
    recurring = [
        name for name, count in sorted(failure_counts.items(), key=lambda x: -x[1])
        if count >= threshold
    ]

    # Best/worst domain by average score
    domain_avgs: dict[str, list[float]] = {}
    for entry in history:
        for domain, score in entry.domain_scores.items():
            domain_avgs.setdefault(domain, []).append(score)

    domain_means = {
        d: sum(scores) / len(scores) for d, scores in domain_avgs.items()
    }

    best_domain = max(domain_means, key=domain_means.get) if domain_means else ""  # type: ignore[arg-type]
    worst_domain = min(domain_means, key=domain_means.get) if domain_means else ""  # type: ignore[arg-type]

    return TrendReport(
        entries=history,
        avg_pass_rate=round(avg_rate, 1),
        trend_direction=trend_direction,
        recurring_failures=recurring,
        best_domain=best_domain,
        worst_domain=worst_domain,
    )


# ── Internal helpers ──


def _parse_feedback(raw: dict, path: Path) -> HistoryEntry | None:
    """Extract a HistoryEntry from a feedback JSON dict."""
    snapshot_id = raw.get("snapshot_id", "")
    if not snapshot_id:
        return None

    overall = raw.get("overall", {})
    pass_rate = overall.get("pass_rate", 0.0)
    verdict = overall.get("verdict", "unknown")

    # Extract date from snapshot_id or validated_at
    date = ""
    validated_at = raw.get("validated_at", "")
    if validated_at:
        date = validated_at[:10]  # YYYY-MM-DD

    # Infer market from filename (snapshot_US_... -> US)
    market = "US"
    name = path.stem
    if "_US_" in name:
        market = "US"
    elif "_EU_" in name:
        market = "EU"
    elif "_ASIA_" in name:
        market = "ASIA"

    # Domain scores: compute pass rate per domain
    domain_scores: dict[str, float] = {}
    domains = raw.get("domains", {})
    for domain_name, domain_data in domains.items():
        total = domain_data.get("total", 0)
        passed = domain_data.get("passed", 0)
        if total > 0:
            domain_scores[domain_name] = round(passed / total * 100, 1)
        else:
            domain_scores[domain_name] = 100.0  # No checks = no failures

    return HistoryEntry(
        snapshot_id=snapshot_id,
        date=date,
        market=market,
        pass_rate=pass_rate,
        verdict=verdict,
        domain_scores=domain_scores,
    )
