"""Regression validation for eTrading market snapshots.

Exports:
    validate_snapshot — validate a snapshot file, return RegressionFeedback
    RegressionFeedback — the full feedback model
    poll_and_validate — scan a directory for new snapshots and validate them
    create_calm_market — synthetic R1 snapshot
    create_volatile_market — synthetic R2 snapshot
    create_crash_scenario — synthetic R4 snapshot
    create_from_snapshot — clone a snapshot with overrides
    load_history — scan feedback files into HistoryEntry list
    compute_trend — compute trend report from history
    HistoryEntry — single feedback summary
    TrendReport — aggregated trend analysis
    FailureRecord — a single captured failure
    FailureLog — append-only failure log (in-memory + JSON-lines)
    FailureSummary — aggregated failure counts
    capture_failure — convenience: record on the default singleton log
    default_log — return the module-level singleton FailureLog
    FeedbackItem — a single feedback item in the channel
    FeedbackChannel — shared feedback channel between eTrading and income_desk
"""
from income_desk.regression.models import RegressionFeedback
from income_desk.regression.validator import validate_snapshot
from income_desk.regression.poller import poll_and_validate
from income_desk.regression.simulation import (
    create_calm_market,
    create_volatile_market,
    create_crash_scenario,
    create_from_snapshot,
)
from income_desk.regression.history import (
    load_history,
    compute_trend,
    HistoryEntry,
    TrendReport,
)
from income_desk.regression.failure_log import (
    FailureRecord,
    FailureLog,
    FailureSummary,
    capture_failure,
    default_log,
)
from income_desk.regression.feedback import (
    FeedbackItem,
    FeedbackChannel,
)
from income_desk.regression.pipeline_validation import (
    SanityIssue,
    HealthCheck,
    PipelineHealthReport,
    PipelineTestResult,
    validate_trade_data_sanity,
    validate_pipeline_health,
    validate_full_pipeline,
)

__all__ = [
    "validate_snapshot",
    "RegressionFeedback",
    "poll_and_validate",
    "create_calm_market",
    "create_volatile_market",
    "create_crash_scenario",
    "create_from_snapshot",
    "load_history",
    "compute_trend",
    "HistoryEntry",
    "TrendReport",
    "FailureRecord",
    "FailureLog",
    "FailureSummary",
    "capture_failure",
    "default_log",
    "FeedbackItem",
    "FeedbackChannel",
    "SanityIssue",
    "HealthCheck",
    "PipelineHealthReport",
    "PipelineTestResult",
    "validate_trade_data_sanity",
    "validate_pipeline_health",
    "validate_full_pipeline",
]
