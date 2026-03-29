"""Benchmarking workflow wrappers -- make calibration callable from trader_md runner."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from income_desk.workflow._types import WorkflowMeta


class BenchmarkRequest(BaseModel):
    predictions_source: str = "file"
    predictions_path: str = ""
    outcomes_source: str = "file"
    outcomes_path: str = ""
    period: str = ""


class BenchmarkResponse(BaseModel):
    meta: WorkflowMeta
    total_trades: int = 0
    win_rate: float | None = None
    pop_rmse: float | None = None
    regime_persistence_rate: float | None = None
    score_correlation: float | None = None
    summary: str = ""
    report_text: str = ""


def run_benchmark(request: BenchmarkRequest, ma: object | None = None) -> BenchmarkResponse:
    """Run full benchmarking pipeline: load data, calibrate, report."""
    from income_desk.benchmarking.calibration import generate_calibration_report
    from income_desk.benchmarking.loader import load_outcomes, load_predictions
    from income_desk.benchmarking.report import format_calibration_report

    timestamp = datetime.now()
    warnings: list[str] = []

    predictions = load_predictions(request.predictions_source, request.predictions_path)
    outcomes = load_outcomes(request.outcomes_source, request.outcomes_path)

    if not predictions or not outcomes:
        return BenchmarkResponse(
            meta=WorkflowMeta(
                as_of=timestamp, market="", data_source="file", warnings=["No data loaded"]
            ),
            summary="No prediction/outcome data available for benchmarking.",
        )

    report = generate_calibration_report(predictions, outcomes, period=request.period)
    report_text = format_calibration_report(report)

    return BenchmarkResponse(
        meta=WorkflowMeta(
            as_of=timestamp, market="", data_source="file", warnings=warnings
        ),
        total_trades=report.total_trades,
        win_rate=report.win_rate,
        pop_rmse=report.pop_rmse,
        regime_persistence_rate=report.regime_persistence_rate,
        score_correlation=report.score_win_correlation,
        summary=report.summary,
        report_text=report_text,
    )
