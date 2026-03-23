"""Regression validation for eTrading market snapshots.

Exports:
    validate_snapshot — validate a snapshot file, return RegressionFeedback
    RegressionFeedback — the full feedback model
    poll_and_validate — scan a directory for new snapshots and validate them
"""
from income_desk.regression.models import RegressionFeedback
from income_desk.regression.validator import validate_snapshot
from income_desk.regression.poller import poll_and_validate

__all__ = ["validate_snapshot", "RegressionFeedback", "poll_and_validate"]
