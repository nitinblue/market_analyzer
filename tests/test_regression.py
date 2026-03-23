"""Tests for the income_desk.regression module."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from income_desk.regression import (
    RegressionFeedback,
    validate_snapshot,
    poll_and_validate,
    create_calm_market,
    create_volatile_market,
    create_crash_scenario,
    create_from_snapshot,
    load_history,
    compute_trend,
    HistoryEntry,
    TrendReport,
)
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


# ── Simulation snapshot tests ──


class TestSimulationSnapshots:
    """Each simulation function produces a valid snapshot that passes validation."""

    def _validate_simulation(self, snapshot: dict, tmp_path: Path) -> RegressionFeedback:
        """Helper: write snapshot to disk and validate it."""
        snapshot_file = tmp_path / f"snapshot_{snapshot['snapshot_id']}.json"
        snapshot_file.write_text(json.dumps(snapshot), encoding="utf-8")
        return validate_snapshot(snapshot_file)

    def test_calm_market_structure(self):
        snap = create_calm_market()
        assert snap["broker_connected"] is True
        assert snap["regime"]["regime_id"] == 1
        assert len(snap["open_trades"]) == 3
        assert len(snap["portfolios"]) >= 1
        assert len(snap["desks"]) >= 1
        assert "decision_log" in snap
        assert "closed_today" in snap

    def test_calm_market_validates(self, tmp_path: Path):
        snap = create_calm_market()
        fb = self._validate_simulation(snap, tmp_path)
        assert fb.overall.verdict in ("GREEN", "AMBER")
        assert fb.overall.total_checks > 0
        # Data trust should be all green (broker connected, regime, capital)
        dt = fb.domains["data_trust"]
        assert dt.failed == 0

    def test_volatile_market_structure(self):
        snap = create_volatile_market()
        assert snap["regime"]["regime_id"] == 2
        assert len(snap["open_trades"]) == 2
        # Trades should have tested health
        for trade in snap["open_trades"]:
            assert trade["health_status"] in ("tested", "safe")

    def test_volatile_market_validates(self, tmp_path: Path):
        snap = create_volatile_market()
        fb = self._validate_simulation(snap, tmp_path)
        assert fb.overall.total_checks > 0
        assert fb.overall.verdict in ("GREEN", "AMBER", "RED")

    def test_crash_scenario_structure(self):
        snap = create_crash_scenario()
        assert snap["regime"]["regime_id"] == 4
        assert len(snap["open_trades"]) == 3
        assert len(snap["closed_today"]) >= 1
        # Trades should have breached/max_loss health
        health_statuses = {t["health_status"] for t in snap["open_trades"]}
        assert health_statuses & {"breached", "max_loss"}

    def test_crash_scenario_validates(self, tmp_path: Path):
        snap = create_crash_scenario()
        fb = self._validate_simulation(snap, tmp_path)
        assert fb.overall.total_checks > 0

    def test_create_from_snapshot_override(self):
        base = create_calm_market()
        modified = create_from_snapshot(base, broker_connected=False)
        assert modified["broker_connected"] is False
        # Original unchanged
        assert base["broker_connected"] is True

    def test_create_from_snapshot_nested_override(self):
        base = create_calm_market()
        modified = create_from_snapshot(base, regime__confidence=0.50)
        assert modified["regime"]["confidence"] == 0.50
        assert base["regime"]["confidence"] == 0.82  # original unchanged

    def test_create_from_snapshot_validates(self, tmp_path: Path):
        """Modified snapshot still validates."""
        base = create_calm_market()
        modified = create_from_snapshot(
            base,
            snapshot_id="sim-override-test",
            broker_connected=False,
        )
        fb = self._validate_simulation(modified, tmp_path)
        assert fb.overall.total_checks > 0
        # Should have broker_connected failure
        dt = fb.domains["data_trust"]
        assert dt.failed >= 1

    def test_all_trades_have_required_fields(self):
        """Every trade in every simulation has id, ticker, legs, decision_lineage."""
        for factory in (create_calm_market, create_volatile_market, create_crash_scenario):
            snap = factory()
            for trade in snap["open_trades"]:
                assert "id" in trade
                assert "ticker" in trade
                assert "legs" in trade
                assert len(trade["legs"]) >= 2
                assert "decision_lineage" in trade
                assert "health_status" in trade

    def test_all_legs_have_dxlink_symbols(self):
        """Every option leg has a dxlink_symbol and action."""
        for factory in (create_calm_market, create_volatile_market, create_crash_scenario):
            snap = factory()
            for trade in snap["open_trades"]:
                for leg in trade["legs"]:
                    if leg.get("asset_type") == "option":
                        assert leg.get("dxlink_symbol"), f"Missing dxlink_symbol in {trade['id']}"
                        assert leg.get("action"), f"Missing action in {trade['id']}"


# ── History tracking tests ──


class TestHistoryTracking:
    """Test load_history and compute_trend with synthetic feedback files."""

    def _write_feedback(
        self,
        tmp_path: Path,
        snapshot_id: str,
        date: str,
        pass_rate: float,
        verdict: str,
        domains: dict[str, dict],
    ) -> Path:
        """Write a synthetic feedback JSON file."""
        feedback = {
            "snapshot_id": snapshot_id,
            "validated_at": f"{date}T16:00:00",
            "domains": domains,
            "overall": {
                "total_checks": 10,
                "passed": int(pass_rate / 10),
                "failed": 10 - int(pass_rate / 10),
                "pass_rate": pass_rate,
                "verdict": verdict,
            },
            "recommendations": [],
        }
        path = tmp_path / f"snapshot_US_{date.replace('-', '')}_ID_feedback.json"
        path.write_text(json.dumps(feedback), encoding="utf-8")
        return path

    def test_load_history_empty_dir(self, tmp_path: Path):
        entries = load_history(tmp_path)
        assert entries == []

    def test_load_history_nonexistent_dir(self, tmp_path: Path):
        entries = load_history(tmp_path / "nonexistent")
        assert entries == []

    def test_load_history_with_files(self, tmp_path: Path):
        self._write_feedback(
            tmp_path,
            snapshot_id="snap-001",
            date="2026-03-20",
            pass_rate=90.0,
            verdict="GREEN",
            domains={
                "trade_integrity": {"passed": 5, "failed": 0, "total": 5, "failures": []},
                "pnl_validation": {"passed": 4, "failed": 1, "total": 5, "failures": []},
            },
        )
        self._write_feedback(
            tmp_path,
            snapshot_id="snap-002",
            date="2026-03-21",
            pass_rate=80.0,
            verdict="AMBER",
            domains={
                "trade_integrity": {"passed": 4, "failed": 1, "total": 5, "failures": []},
                "pnl_validation": {"passed": 3, "failed": 2, "total": 5, "failures": []},
            },
        )

        entries = load_history(tmp_path)
        assert len(entries) == 2
        assert entries[0].date == "2026-03-20"
        assert entries[1].date == "2026-03-21"
        assert entries[0].pass_rate == 90.0
        assert entries[1].pass_rate == 80.0
        assert all(isinstance(e, HistoryEntry) for e in entries)

    def test_load_history_sorted_by_date(self, tmp_path: Path):
        # Write in reverse order
        self._write_feedback(
            tmp_path, "snap-b", "2026-03-22", 85.0, "AMBER",
            {"d1": {"passed": 8, "failed": 2, "total": 10, "failures": []}},
        )
        self._write_feedback(
            tmp_path, "snap-a", "2026-03-20", 95.0, "GREEN",
            {"d1": {"passed": 9, "failed": 1, "total": 10, "failures": []}},
        )
        entries = load_history(tmp_path)
        assert entries[0].date <= entries[1].date

    def test_compute_trend_empty(self):
        report = compute_trend([])
        assert isinstance(report, TrendReport)
        assert report.avg_pass_rate == 0.0
        assert report.trend_direction == "stable"

    def test_compute_trend_improving(self, tmp_path: Path):
        self._write_feedback(
            tmp_path, "snap-1", "2026-03-18", 70.0, "RED",
            {"d1": {"passed": 7, "failed": 3, "total": 10, "failures": []}},
        )
        self._write_feedback(
            tmp_path, "snap-2", "2026-03-19", 72.0, "RED",
            {"d1": {"passed": 7, "failed": 3, "total": 10, "failures": []}},
        )
        self._write_feedback(
            tmp_path, "snap-3", "2026-03-20", 90.0, "GREEN",
            {"d1": {"passed": 9, "failed": 1, "total": 10, "failures": []}},
        )
        self._write_feedback(
            tmp_path, "snap-4", "2026-03-21", 95.0, "GREEN",
            {"d1": {"passed": 10, "failed": 0, "total": 10, "failures": []}},
        )

        entries = load_history(tmp_path)
        report = compute_trend(entries)
        assert report.trend_direction == "improving"
        assert report.avg_pass_rate > 0

    def test_compute_trend_degrading(self, tmp_path: Path):
        self._write_feedback(
            tmp_path, "snap-1", "2026-03-18", 95.0, "GREEN",
            {"d1": {"passed": 10, "failed": 0, "total": 10, "failures": []}},
        )
        self._write_feedback(
            tmp_path, "snap-2", "2026-03-19", 92.0, "GREEN",
            {"d1": {"passed": 9, "failed": 1, "total": 10, "failures": []}},
        )
        self._write_feedback(
            tmp_path, "snap-3", "2026-03-20", 70.0, "RED",
            {"d1": {"passed": 7, "failed": 3, "total": 10, "failures": []}},
        )
        self._write_feedback(
            tmp_path, "snap-4", "2026-03-21", 65.0, "RED",
            {"d1": {"passed": 6, "failed": 4, "total": 10, "failures": []}},
        )

        entries = load_history(tmp_path)
        report = compute_trend(entries)
        assert report.trend_direction == "degrading"

    def test_compute_trend_best_worst_domain(self, tmp_path: Path):
        self._write_feedback(
            tmp_path, "snap-1", "2026-03-20", 85.0, "AMBER",
            {
                "trade_integrity": {"passed": 10, "failed": 0, "total": 10, "failures": []},
                "pnl_validation": {"passed": 5, "failed": 5, "total": 10, "failures": []},
            },
        )
        self._write_feedback(
            tmp_path, "snap-2", "2026-03-21", 85.0, "AMBER",
            {
                "trade_integrity": {"passed": 9, "failed": 1, "total": 10, "failures": []},
                "pnl_validation": {"passed": 6, "failed": 4, "total": 10, "failures": []},
            },
        )

        entries = load_history(tmp_path)
        report = compute_trend(entries)
        assert report.best_domain == "trade_integrity"
        assert report.worst_domain == "pnl_validation"

    def test_compute_trend_recurring_failures(self, tmp_path: Path):
        # pnl_validation fails in all 3 entries -> recurring
        for i, date in enumerate(["2026-03-19", "2026-03-20", "2026-03-21"]):
            self._write_feedback(
                tmp_path, f"snap-{i}", date, 80.0, "AMBER",
                {
                    "trade_integrity": {"passed": 10, "failed": 0, "total": 10, "failures": []},
                    "pnl_validation": {"passed": 6, "failed": 4, "total": 10, "failures": []},
                },
            )

        entries = load_history(tmp_path)
        report = compute_trend(entries)
        assert "pnl_validation" in report.recurring_failures
        assert "trade_integrity" not in report.recurring_failures

    def test_history_entry_model(self):
        entry = HistoryEntry(
            snapshot_id="test",
            date="2026-03-20",
            market="US",
            pass_rate=85.0,
            verdict="AMBER",
            domain_scores={"d1": 90.0, "d2": 80.0},
        )
        assert entry.snapshot_id == "test"
        data = entry.model_dump()
        assert "domain_scores" in data

    def test_trend_report_model(self):
        report = TrendReport(
            entries=[],
            avg_pass_rate=85.0,
            trend_direction="stable",
            recurring_failures=["pnl"],
            best_domain="integrity",
            worst_domain="pnl",
        )
        assert report.trend_direction == "stable"
        data = report.model_dump()
        assert "recurring_failures" in data
