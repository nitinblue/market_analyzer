"""Tests for benchmarking workflow: loader, workflow wrapper, and MD validation."""
from __future__ import annotations

import json

import pytest

from income_desk.benchmarking.loader import load_outcomes, load_predictions
from income_desk.benchmarking.models import OutcomeRecord, PredictionRecord
from income_desk.workflow.benchmarking import BenchmarkRequest, run_benchmark


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------

SAMPLE_PREDICTIONS = [
    {
        "trade_id": "T-001",
        "ticker": "SPY",
        "timestamp": "2026-03-01T10:00:00",
        "regime_id": 1,
        "regime_confidence": 0.85,
        "pop_pct": 70.0,
        "composite_score": 82.3,
        "iv_rank": 43.0,
        "entry_credit": 1.45,
        "structure": "iron_condor",
        "market": "US",
    },
    {
        "trade_id": "T-002",
        "ticker": "QQQ",
        "timestamp": "2026-03-02T10:15:00",
        "regime_id": 1,
        "regime_confidence": 0.78,
        "pop_pct": 72.0,
        "composite_score": 79.1,
        "iv_rank": 38.0,
        "entry_credit": 1.20,
        "structure": "iron_condor",
        "market": "US",
    },
    {
        "trade_id": "T-003",
        "ticker": "GLD",
        "timestamp": "2026-03-03T10:30:00",
        "regime_id": 2,
        "regime_confidence": 0.65,
        "pop_pct": 65.0,
        "composite_score": 74.5,
        "iv_rank": 55.0,
        "entry_credit": 0.95,
        "structure": "credit_spread",
        "market": "US",
    },
]

SAMPLE_OUTCOMES = [
    {
        "trade_id": "T-001",
        "ticker": "SPY",
        "entry_timestamp": "2026-03-01T10:00:00",
        "exit_timestamp": "2026-03-15T14:00:00",
        "pnl": 95.0,
        "is_win": True,
        "holding_days": 14,
        "regime_at_exit": 1,
        "regime_persisted": True,
        "exit_reason": "profit_target",
    },
    {
        "trade_id": "T-002",
        "ticker": "QQQ",
        "entry_timestamp": "2026-03-02T10:15:00",
        "exit_timestamp": "2026-03-16T11:00:00",
        "pnl": 78.0,
        "is_win": True,
        "holding_days": 14,
        "regime_at_exit": 1,
        "regime_persisted": True,
        "exit_reason": "profit_target",
    },
    {
        "trade_id": "T-003",
        "ticker": "GLD",
        "entry_timestamp": "2026-03-03T10:30:00",
        "exit_timestamp": "2026-03-10T15:00:00",
        "pnl": -120.0,
        "is_win": False,
        "holding_days": 7,
        "regime_at_exit": 3,
        "regime_persisted": False,
        "exit_reason": "stop_loss",
    },
]


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


def test_load_predictions_json(tmp_path):
    """Load predictions from a JSON file."""
    path = tmp_path / "preds.json"
    path.write_text(json.dumps(SAMPLE_PREDICTIONS))

    records = load_predictions("file", str(path))
    assert len(records) == 3
    assert all(isinstance(r, PredictionRecord) for r in records)
    assert records[0].trade_id == "T-001"
    assert records[0].ticker == "SPY"
    assert records[0].regime_id == 1
    assert records[0].pop_pct == 70.0


def test_load_predictions_csv(tmp_path):
    """Load predictions from a CSV file."""
    path = tmp_path / "preds.csv"
    header = "trade_id,ticker,timestamp,regime_id,regime_confidence,pop_pct,composite_score,iv_rank,entry_credit,structure,market\n"
    row1 = "T-001,SPY,2026-03-01T10:00:00,1,0.85,70.0,82.3,43.0,1.45,iron_condor,US\n"
    row2 = "T-002,QQQ,2026-03-02T10:15:00,1,0.78,72.0,79.1,38.0,1.20,iron_condor,US\n"
    path.write_text(header + row1 + row2)

    records = load_predictions("file", str(path))
    assert len(records) == 2
    assert records[0].trade_id == "T-001"
    assert records[0].regime_id == 1
    assert records[1].pop_pct == 72.0


def test_load_outcomes_json(tmp_path):
    """Load outcomes from a JSON file."""
    path = tmp_path / "outcomes.json"
    path.write_text(json.dumps(SAMPLE_OUTCOMES))

    records = load_outcomes("file", str(path))
    assert len(records) == 3
    assert all(isinstance(r, OutcomeRecord) for r in records)
    assert records[0].trade_id == "T-001"
    assert records[0].pnl == 95.0
    assert records[0].is_win is True
    assert records[2].is_win is False
    assert records[2].regime_persisted is False


def test_load_empty_file(tmp_path):
    """Missing file returns empty list."""
    result_p = load_predictions("file", str(tmp_path / "nonexistent.json"))
    result_o = load_outcomes("file", str(tmp_path / "nonexistent.json"))
    assert result_p == []
    assert result_o == []


def test_load_unsupported_extension(tmp_path):
    """Unsupported file extension returns empty list."""
    path = tmp_path / "data.xml"
    path.write_text("<data/>")
    assert load_predictions("file", str(path)) == []
    assert load_outcomes("file", str(path)) == []


# ---------------------------------------------------------------------------
# Workflow wrapper tests
# ---------------------------------------------------------------------------


def test_run_benchmark_with_data(tmp_path):
    """Full benchmark run with prediction + outcome files."""
    pred_path = tmp_path / "predictions.json"
    out_path = tmp_path / "outcomes.json"
    pred_path.write_text(json.dumps(SAMPLE_PREDICTIONS))
    out_path.write_text(json.dumps(SAMPLE_OUTCOMES))

    request = BenchmarkRequest(
        predictions_source="file",
        predictions_path=str(pred_path),
        outcomes_source="file",
        outcomes_path=str(out_path),
        period="2026-Q1",
    )

    response = run_benchmark(request)

    assert response.total_trades == 3
    assert response.win_rate is not None
    assert response.win_rate == pytest.approx(2 / 3, abs=0.01)
    assert response.summary != ""
    assert response.report_text != ""
    assert response.meta.data_source == "file"
    assert len(response.meta.warnings) == 0


def test_run_benchmark_no_data():
    """No files produces 'No data' response."""
    request = BenchmarkRequest(
        predictions_path="/nonexistent/predictions.json",
        outcomes_path="/nonexistent/outcomes.json",
    )

    response = run_benchmark(request)

    assert response.total_trades == 0
    assert "No" in response.summary
    assert "No data loaded" in response.meta.warnings


# ---------------------------------------------------------------------------
# Workflow MD validation
# ---------------------------------------------------------------------------

