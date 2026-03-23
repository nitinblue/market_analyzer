"""Tests for the income_desk.regression module."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from income_desk.regression import RegressionFeedback, validate_snapshot, poll_and_validate
from income_desk.regression.models import (
    CheckFailure,
    DomainResult,
    OverallResult,
    SnapshotLeg,
    SnapshotTrade,
)


# ── Path to real snapshot ──

REAL_SNAPSHOT = Path(
    "C:/Users/nitin/PythonProjects/eTrading/trading_cotrader/reports/regression/"
    "snapshot_US_2026-03-23_152922.json"
)


# ── Model unit tests ──


class TestModels:
    def test_domain_result_pass(self):
        d = DomainResult()
        d.record_pass()
        assert d.passed == 1
        assert d.failed == 0
        assert d.total == 1

    def test_domain_result_fail(self):
        d = DomainResult()
        d.record_fail(CheckFailure(check="test", message="bad"))
        assert d.passed == 0
        assert d.failed == 1
        assert d.total == 1
        assert len(d.failures) == 1

    def test_regression_feedback_compute_overall(self):
        fb = RegressionFeedback(snapshot_id="test-123")
        d1 = DomainResult(passed=8, failed=2, total=10)
        d2 = DomainResult(passed=5, failed=0, total=5)
        fb.domains["domain_a"] = d1
        fb.domains["domain_b"] = d2
        fb.compute_overall()
        assert fb.overall.total_checks == 15
        assert fb.overall.passed == 13
        assert fb.overall.failed == 2
        assert fb.overall.pass_rate == 86.7
        assert fb.overall.verdict == "AMBER"

    def test_feedback_green_verdict(self):
        fb = RegressionFeedback(snapshot_id="ok")
        fb.domains["d1"] = DomainResult(passed=10, failed=0, total=10)
        fb.compute_overall()
        assert fb.overall.verdict == "GREEN"

    def test_feedback_red_verdict(self):
        fb = RegressionFeedback(snapshot_id="bad")
        fb.domains["d1"] = DomainResult(passed=2, failed=8, total=10)
        fb.compute_overall()
        assert fb.overall.verdict == "RED"

    def test_snapshot_trade_properties(self):
        trade = SnapshotTrade(
            id="t1",
            ticker="SPY",
            trade_type="shadow",
            entry_price=0.0,
            legs=[
                SnapshotLeg(asset_type="option", option_type="call"),
            ],
        )
        assert trade.is_shadow is True
        assert trade.is_equity is False
        assert trade.has_option_legs is True
        assert trade.has_entry is False

    def test_snapshot_trade_equity(self):
        trade = SnapshotTrade(
            id="t2",
            ticker="BAC",
            trade_type="real",
            entry_price=54.5,
            legs=[
                SnapshotLeg(asset_type="equity", quantity=100),
            ],
        )
        assert trade.is_equity is True
        assert trade.has_option_legs is False
        assert trade.has_entry is True


# ── Synthetic snapshot test ──


def _build_minimal_snapshot() -> dict:
    """Build a minimal synthetic snapshot for testing."""
    return {
        "snapshot_id": "test-synthetic-001",
        "market": "US",
        "captured_at": "2026-03-23T10:00:00",
        "date": "2026-03-23",
        "broker_connected": True,
        "regime": {"regime_id": 2, "confidence": 0.75},
        "portfolios": [
            {"id": "p1", "name": "Test Portfolio", "capital": 50000.0},
        ],
        "desks": [
            {
                "desk_key": "desk_test",
                "capital": 10000.0,
                "risk_limits": {
                    "max_positions": 5,
                    "max_single_position_pct": 20,
                },
            },
        ],
        "open_trades": [
            {
                "id": "trade-ic-001",
                "ticker": "SPY",
                "trade_type": "real",
                "strategy_type": "iron_condor",
                "entry_price": 1.50,
                "current_price": 0.75,
                "total_pnl": 75.0,  # (0.75 - 1.50) * -1 * 100 per leg... simplified
                "health_status": "safe",
                "decision_lineage": {
                    "score": 0.65,
                    "gates": [{"name": "score", "passed": True}],
                },
                "legs": [
                    {
                        "id": "l1",
                        "symbol_ticker": "SPY",
                        "asset_type": "option",
                        "option_type": "put",
                        "strike": 560.0,
                        "expiration": "2026-04-17",
                        "quantity": -1,
                        "entry_price": 3.00,
                        "current_price": 2.00,
                        "dxlink_symbol": ".SPY260417P560",
                        "action": "STO",
                    },
                    {
                        "id": "l2",
                        "symbol_ticker": "SPY",
                        "asset_type": "option",
                        "option_type": "put",
                        "strike": 555.0,
                        "expiration": "2026-04-17",
                        "quantity": 1,
                        "entry_price": 2.50,
                        "current_price": 1.50,
                        "dxlink_symbol": ".SPY260417P555",
                        "action": "BTO",
                    },
                    {
                        "id": "l3",
                        "symbol_ticker": "SPY",
                        "asset_type": "option",
                        "option_type": "call",
                        "strike": 600.0,
                        "expiration": "2026-04-17",
                        "quantity": -1,
                        "entry_price": 3.50,
                        "current_price": 2.75,
                        "dxlink_symbol": ".SPY260417C600",
                        "action": "STO",
                    },
                    {
                        "id": "l4",
                        "symbol_ticker": "SPY",
                        "asset_type": "option",
                        "option_type": "call",
                        "strike": 605.0,
                        "expiration": "2026-04-17",
                        "quantity": 1,
                        "entry_price": 3.00,
                        "current_price": 2.25,
                        "dxlink_symbol": ".SPY260417C605",
                        "action": "BTO",
                    },
                ],
            },
        ],
        "decision_log": [],
        "closed_today": [],
        "stats": {},
    }


class TestSyntheticSnapshot:
    def test_validate_synthetic(self, tmp_path: Path):
        """Validate a minimal synthetic snapshot."""
        snapshot = _build_minimal_snapshot()
        snapshot_file = tmp_path / "snapshot_US_2026-03-23_100000.json"
        snapshot_file.write_text(json.dumps(snapshot), encoding="utf-8")

        fb = validate_snapshot(snapshot_file)

        assert isinstance(fb, RegressionFeedback)
        assert fb.snapshot_id == "test-synthetic-001"
        assert "trade_integrity" in fb.domains
        assert "pnl_validation" in fb.domains
        assert "risk_validation" in fb.domains
        assert "data_trust" in fb.domains
        assert "execution_quality" in fb.domains
        assert "health_lifecycle" in fb.domains
        assert "decision_audit" in fb.domains

        assert fb.overall.total_checks > 0
        assert fb.overall.verdict in ("GREEN", "AMBER", "RED")

        # Feedback file should be written
        feedback_file = tmp_path / "snapshot_US_2026-03-23_100000_ID_feedback.json"
        assert feedback_file.exists()

        # Parse feedback file and check structure
        feedback_data = json.loads(feedback_file.read_text(encoding="utf-8"))
        assert "snapshot_id" in feedback_data
        assert "domains" in feedback_data
        assert "overall" in feedback_data

    def test_data_trust_all_green(self, tmp_path: Path):
        """With broker connected and regime data, data_trust should pass."""
        snapshot = _build_minimal_snapshot()
        snapshot_file = tmp_path / "snapshot_test.json"
        snapshot_file.write_text(json.dumps(snapshot), encoding="utf-8")

        fb = validate_snapshot(snapshot_file)
        dt = fb.domains["data_trust"]
        assert dt.failed == 0
        assert dt.passed == 3  # broker, regime, capital

    def test_data_trust_broker_disconnected(self, tmp_path: Path):
        snapshot = _build_minimal_snapshot()
        snapshot["broker_connected"] = False
        snapshot_file = tmp_path / "snapshot_test.json"
        snapshot_file.write_text(json.dumps(snapshot), encoding="utf-8")

        fb = validate_snapshot(snapshot_file)
        dt = fb.domains["data_trust"]
        assert dt.failed >= 1
        fails = {f.check for f in dt.failures}
        assert "broker_connected" in fails

    def test_risk_no_limits(self, tmp_path: Path):
        snapshot = _build_minimal_snapshot()
        snapshot["desks"][0]["risk_limits"] = None
        snapshot_file = tmp_path / "snapshot_test.json"
        snapshot_file.write_text(json.dumps(snapshot), encoding="utf-8")

        fb = validate_snapshot(snapshot_file)
        rv = fb.domains["risk_validation"]
        fails = {f.check for f in rv.failures}
        assert "desk_has_risk_limits" in fails

    def test_health_unquoted(self, tmp_path: Path):
        snapshot = _build_minimal_snapshot()
        snapshot["open_trades"][0]["health_status"] = "unquoted"
        snapshot_file = tmp_path / "snapshot_test.json"
        snapshot_file.write_text(json.dumps(snapshot), encoding="utf-8")

        fb = validate_snapshot(snapshot_file)
        hl = fb.domains["health_lifecycle"]
        fails = {f.check for f in hl.failures}
        assert "health_status_quoted" in fails

    def test_pnl_mismatch_detected(self, tmp_path: Path):
        snapshot = _build_minimal_snapshot()
        # Set a wildly wrong total_pnl
        snapshot["open_trades"][0]["total_pnl"] = 99999.0
        snapshot_file = tmp_path / "snapshot_test.json"
        snapshot_file.write_text(json.dumps(snapshot), encoding="utf-8")

        fb = validate_snapshot(snapshot_file)
        pnl = fb.domains["pnl_validation"]
        assert pnl.failed >= 1

    def test_empty_snapshot(self, tmp_path: Path):
        """Empty snapshot should not crash."""
        snapshot = {
            "snapshot_id": "empty-001",
            "market": "US",
            "captured_at": "2026-03-23T10:00:00",
            "broker_connected": False,
            "regime": {},
            "portfolios": [],
            "desks": [],
            "open_trades": [],
            "decision_log": [],
            "closed_today": [],
        }
        snapshot_file = tmp_path / "snapshot_empty.json"
        snapshot_file.write_text(json.dumps(snapshot), encoding="utf-8")

        fb = validate_snapshot(snapshot_file)
        assert isinstance(fb, RegressionFeedback)
        assert fb.overall.total_checks >= 0

    def test_feedback_json_structure(self, tmp_path: Path):
        """Verify feedback JSON matches expected schema."""
        snapshot = _build_minimal_snapshot()
        snapshot_file = tmp_path / "snapshot_test.json"
        snapshot_file.write_text(json.dumps(snapshot), encoding="utf-8")

        fb = validate_snapshot(snapshot_file)
        data = json.loads(fb.model_dump_json())

        # Required top-level keys
        assert "snapshot_id" in data
        assert "validated_at" in data
        assert "domains" in data
        assert "overall" in data
        assert "recommendations" in data

        # Overall structure
        assert "total_checks" in data["overall"]
        assert "passed" in data["overall"]
        assert "failed" in data["overall"]
        assert "pass_rate" in data["overall"]
        assert "verdict" in data["overall"]

        # Domain structure
        for domain_name, domain in data["domains"].items():
            assert "passed" in domain
            assert "failed" in domain
            assert "total" in domain
            assert "failures" in domain


class TestPoller:
    def test_poll_skips_existing_feedback(self, tmp_path: Path):
        snapshot = _build_minimal_snapshot()
        snapshot_file = tmp_path / "snapshot_US_2026-03-23_100000.json"
        snapshot_file.write_text(json.dumps(snapshot), encoding="utf-8")

        # First run — should validate
        results = poll_and_validate(tmp_path)
        assert len(results) == 1

        # Second run — feedback exists, should skip
        results2 = poll_and_validate(tmp_path)
        assert len(results2) == 0

    def test_poll_nonexistent_dir(self, tmp_path: Path):
        results = poll_and_validate(tmp_path / "nonexistent")
        assert results == []


# ── Real snapshot test ──


@pytest.mark.skipif(
    not REAL_SNAPSHOT.exists(),
    reason="Real snapshot not available",
)
class TestRealSnapshot:
    def test_validate_real_snapshot(self, tmp_path: Path):
        """Validate the actual eTrading snapshot.

        We copy to tmp_path so feedback file doesn't pollute the source dir.
        """
        import shutil

        snapshot_copy = tmp_path / REAL_SNAPSHOT.name
        shutil.copy2(REAL_SNAPSHOT, snapshot_copy)

        fb = validate_snapshot(snapshot_copy)

        assert isinstance(fb, RegressionFeedback)
        assert fb.snapshot_id != "unknown"
        assert fb.overall.total_checks > 0

        # Print summary for debugging
        print(f"\n{'='*60}")
        print(f"Real Snapshot Validation: {fb.overall.verdict}")
        print(f"  Pass rate: {fb.overall.pass_rate}%")
        print(f"  Checks: {fb.overall.passed}/{fb.overall.total_checks} passed")
        for domain, dr in fb.domains.items():
            status = "PASS" if dr.failed == 0 else f"FAIL({dr.failed})"
            print(f"  {domain}: {status} ({dr.passed}/{dr.total})")
            for f in dr.failures:
                print(f"    - {f.check}: {f.message}")
        if fb.recommendations:
            print("  Recommendations:")
            for r in fb.recommendations:
                print(f"    - {r}")
        print(f"{'='*60}")

    def test_real_snapshot_has_trades(self):
        """Sanity: real snapshot should have open trades."""
        raw = json.loads(REAL_SNAPSHOT.read_text(encoding="utf-8"))
        assert len(raw.get("open_trades", [])) > 0
