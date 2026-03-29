"""Tests for the benchmarking calibration framework."""

from __future__ import annotations

import pytest

from income_desk.benchmarking import (
    CalibrationReport,
    OutcomeRecord,
    PopBucket,
    PredictionRecord,
    RegimeAccuracy,
    calibrate_pop,
    format_calibration_report,
    generate_calibration_report,
    regime_accuracy,
    score_vs_outcome,
)


def _pred(trade_id: str, **kwargs) -> PredictionRecord:
    """Helper to build a PredictionRecord with defaults."""
    defaults = {
        "trade_id": trade_id,
        "ticker": "SPY",
        "timestamp": "2026-03-01T10:00:00",
        "regime_id": 1,
        "regime_confidence": 0.8,
    }
    defaults.update(kwargs)
    return PredictionRecord(**defaults)


def _outcome(trade_id: str, *, is_win: bool, pnl: float = 50.0, **kwargs) -> OutcomeRecord:
    """Helper to build an OutcomeRecord with defaults."""
    defaults = {
        "trade_id": trade_id,
        "ticker": "SPY",
        "entry_timestamp": "2026-03-01T10:00:00",
        "exit_timestamp": "2026-03-05T15:00:00",
        "pnl": pnl,
        "is_win": is_win,
        "holding_days": 4,
    }
    defaults.update(kwargs)
    return OutcomeRecord(**defaults)


class TestPopCalibration:
    def test_pop_calibration_basic(self):
        """100 trades with 70% POP, 70 winners -> bucket should show ~70% actual."""
        preds = [_pred(f"t{i}", pop_pct=70.0) for i in range(100)]
        outcomes = [
            _outcome(f"t{i}", is_win=(i < 70)) for i in range(100)
        ]

        buckets = calibrate_pop(preds, outcomes)

        assert len(buckets) == 1
        bucket = buckets[0]
        assert bucket.predicted_low == 70.0
        assert bucket.predicted_high == 80.0
        assert bucket.actual_win_rate == 70.0
        assert bucket.count == 100
        assert bucket.error == pytest.approx(-5.0)  # 70 - 75 (mid)

    def test_pop_calibration_empty(self):
        """No trades with POP -> empty buckets."""
        preds = [_pred(f"t{i}") for i in range(10)]  # no pop_pct
        outcomes = [_outcome(f"t{i}", is_win=True) for i in range(10)]

        buckets = calibrate_pop(preds, outcomes)
        assert buckets == []

    def test_pop_calibration_multiple_buckets(self):
        """Trades across multiple POP ranges."""
        preds = [
            _pred("t1", pop_pct=55.0),
            _pred("t2", pop_pct=55.0),
            _pred("t3", pop_pct=75.0),
            _pred("t4", pop_pct=75.0),
        ]
        outcomes = [
            _outcome("t1", is_win=True),
            _outcome("t2", is_win=False),
            _outcome("t3", is_win=True),
            _outcome("t4", is_win=True),
        ]

        buckets = calibrate_pop(preds, outcomes)
        assert len(buckets) == 2

        # 50-60 bucket
        b50 = buckets[0]
        assert b50.predicted_low == 50.0
        assert b50.actual_win_rate == 50.0
        assert b50.count == 2

        # 70-80 bucket
        b70 = buckets[1]
        assert b70.predicted_low == 70.0
        assert b70.actual_win_rate == 100.0
        assert b70.count == 2

    def test_pop_calibration_no_matching_outcomes(self):
        """Predictions without matching outcomes are ignored."""
        preds = [_pred("t1", pop_pct=70.0)]
        outcomes = [_outcome("t999", is_win=True)]  # different trade_id

        buckets = calibrate_pop(preds, outcomes)
        assert buckets == []


class TestRegimeAccuracy:
    def test_regime_accuracy_all_persist(self):
        """All trades same regime at exit -> 100% persistence."""
        preds = [_pred(f"t{i}", regime_id=2) for i in range(20)]
        outcomes = [
            _outcome(f"t{i}", is_win=True, regime_at_exit=2, regime_persisted=True)
            for i in range(20)
        ]

        results = regime_accuracy(preds, outcomes)
        assert len(results) == 1
        assert results[0].regime_id == 2
        assert results[0].count == 20
        assert results[0].persisted_count == 20
        assert results[0].persistence_rate == 1.0

    def test_regime_accuracy_mixed(self):
        """Mix of persisted and not."""
        preds = [_pred(f"t{i}", regime_id=1) for i in range(10)]
        outcomes = [
            _outcome(f"t{i}", is_win=True, regime_persisted=(i < 6))
            for i in range(10)
        ]

        results = regime_accuracy(preds, outcomes)
        assert len(results) == 1
        r = results[0]
        assert r.regime_id == 1
        assert r.count == 10
        assert r.persisted_count == 6
        assert r.persistence_rate == pytest.approx(0.6)

    def test_regime_accuracy_multiple_regimes(self):
        """Trades across different regimes."""
        preds = [
            _pred("t1", regime_id=1),
            _pred("t2", regime_id=1),
            _pred("t3", regime_id=3),
        ]
        outcomes = [
            _outcome("t1", is_win=True, regime_persisted=True),
            _outcome("t2", is_win=False, regime_persisted=False),
            _outcome("t3", is_win=True, regime_persisted=True),
        ]

        results = regime_accuracy(preds, outcomes)
        assert len(results) == 2
        assert results[0].regime_id == 1
        assert results[0].persistence_rate == 0.5
        assert results[1].regime_id == 3
        assert results[1].persistence_rate == 1.0

    def test_regime_accuracy_none_persisted_skipped(self):
        """Outcomes with regime_persisted=None are ignored."""
        preds = [_pred("t1", regime_id=1)]
        outcomes = [_outcome("t1", is_win=True)]  # regime_persisted defaults to None

        results = regime_accuracy(preds, outcomes)
        assert results == []


class TestScoreCorrelation:
    def test_score_correlation_positive(self):
        """Higher scores = more wins -> positive correlation."""
        preds = [
            _pred(f"t{i}", composite_score=80.0 + i) for i in range(20)
        ] + [
            _pred(f"l{i}", composite_score=30.0 + i) for i in range(20)
        ]
        outcomes = [
            _outcome(f"t{i}", is_win=True, pnl=100.0) for i in range(20)
        ] + [
            _outcome(f"l{i}", is_win=False, pnl=-50.0) for i in range(20)
        ]

        result = score_vs_outcome(preds, outcomes)
        assert result["correlation"] is not None
        assert result["correlation"] > 0.5
        assert result["avg_score_winners"] is not None
        assert result["avg_score_losers"] is not None
        assert result["avg_score_winners"] > result["avg_score_losers"]

    def test_score_correlation_no_scores(self):
        """No composite scores -> all None."""
        preds = [_pred("t1")]  # no composite_score
        outcomes = [_outcome("t1", is_win=True)]

        result = score_vs_outcome(preds, outcomes)
        assert result["correlation"] is None
        assert result["avg_score_winners"] is None
        assert result["avg_score_losers"] is None

    def test_score_correlation_single_trade(self):
        """Single trade can't compute correlation but can compute averages."""
        preds = [_pred("t1", composite_score=75.0)]
        outcomes = [_outcome("t1", is_win=True)]

        result = score_vs_outcome(preds, outcomes)
        assert result["correlation"] is None  # need >= 2
        assert result["avg_score_winners"] == 75.0


class TestGenerateReport:
    def test_generate_report(self):
        """Full report with all fields populated."""
        preds = [
            _pred(f"t{i}", pop_pct=70.0, composite_score=60.0 + i, regime_id=1)
            for i in range(30)
        ]
        outcomes = [
            _outcome(
                f"t{i}",
                is_win=(i < 21),  # 70% win rate
                pnl=100.0 if i < 21 else -150.0,
                regime_persisted=(i < 25),
            )
            for i in range(30)
        ]

        report = generate_calibration_report(preds, outcomes, period="2026-03")

        assert report.period == "2026-03"
        assert report.total_trades == 30
        assert report.win_rate == pytest.approx(0.7)
        assert report.pop_buckets  # non-empty
        assert report.pop_rmse is not None
        assert report.regime_accuracy  # non-empty
        assert report.regime_persistence_rate is not None
        assert report.score_win_correlation is not None
        assert report.avg_score_winners is not None
        assert report.avg_score_losers is not None
        assert report.avg_pnl is not None
        assert report.summary  # non-empty string

    def test_generate_report_empty(self):
        """Empty inputs produce a valid but empty report."""
        report = generate_calibration_report([], [])
        assert report.total_trades == 0
        assert report.pop_buckets == []
        assert report.regime_accuracy == []
        assert report.win_rate is None


class TestFormatReport:
    def test_format_report(self):
        """format_calibration_report returns non-empty string with expected sections."""
        report = CalibrationReport(
            period="2026-03",
            total_trades=50,
            pop_buckets=[
                PopBucket(
                    predicted_low=60.0,
                    predicted_high=70.0,
                    predicted_mid=65.0,
                    actual_win_rate=68.0,
                    count=25,
                    error=3.0,
                ),
            ],
            pop_rmse=3.0,
            regime_persistence_rate=0.8,
            regime_accuracy=[
                RegimeAccuracy(regime_id=1, count=30, persisted_count=24, persistence_rate=0.8),
            ],
            score_win_correlation=0.45,
            avg_score_winners=72.0,
            avg_score_losers=55.0,
            win_rate=0.68,
            avg_pnl=45.50,
            summary="50 trades analyzed, win rate 68%, POP RMSE 3.0pp",
        )

        text = format_calibration_report(report)
        assert len(text) > 0
        assert "Calibration Report" in text
        assert "2026-03" in text
        assert "POP Calibration" in text
        assert "Regime Persistence" in text
        assert "Score vs Outcome" in text
        assert "68" in text

    def test_format_report_empty(self):
        """Minimal report still formats without error."""
        report = CalibrationReport(period="", total_trades=0)
        text = format_calibration_report(report)
        assert "Calibration Report" in text
        assert "Total trades: 0" in text
