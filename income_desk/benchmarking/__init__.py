"""Benchmarking — prediction accuracy tracking and calibration.

Pure computation functions for measuring how well income_desk predictions
match actual trade outcomes. eTrading captures predictions and outcomes,
passes them in as lists, income_desk returns calibration analysis.

No I/O, no state, no side effects.

Usage::

    from income_desk.benchmarking import (
        PredictionRecord,
        OutcomeRecord,
        CalibrationReport,
        calibrate_pop,
        regime_accuracy,
        score_vs_outcome,
        generate_calibration_report,
        format_calibration_report,
    )
"""

from income_desk.benchmarking.calibration import (
    calibrate_pop,
    generate_calibration_report,
    regime_accuracy,
    score_vs_outcome,
)
from income_desk.benchmarking.models import (
    CalibrationReport,
    OutcomeRecord,
    PopBucket,
    PredictionRecord,
    RegimeAccuracy,
)
from income_desk.benchmarking.report import format_calibration_report

__all__ = [
    "CalibrationReport",
    "OutcomeRecord",
    "PopBucket",
    "PredictionRecord",
    "RegimeAccuracy",
    "calibrate_pop",
    "format_calibration_report",
    "generate_calibration_report",
    "regime_accuracy",
    "score_vs_outcome",
]
