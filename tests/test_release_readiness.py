"""Tests for release readiness validation system.

Tests every stage runner, the report generator, the manifest writer,
parallel execution, and end-to-end readiness flow.
"""

import json
import tempfile
from pathlib import Path

import pytest

from income_desk.regression.release_readiness import (
    APICall,
    ReadinessReport,
    StageResult,
    StageVerdict,
    _build_credit_spread,
    _build_india_ic,
    _build_iron_condor,
    _check,
    _run_api,
    _run_stage_1_scan,
    _run_stage_2_rank,
    _run_stage_3_gate,
    _run_stage_4_size,
    _run_stage_5_enter,
    _run_stage_6_monitor,
    _run_stage_7_adjust,
    _run_stage_8_analytics,
    _serialize,
    run_release_readiness,
)
from income_desk.regression.readiness_report import (
    generate_html,
    write_html,
    write_manifest,
)


# ── Fixture helpers ──────────────────────────────────────────────────────────


def _sim_us():
    from income_desk.adapters.simulated import create_ideal_income
    return create_ideal_income()


def _sim_india():
    from income_desk.adapters.simulated import create_india_trading
    return create_india_trading()


# ── Unit tests: Utility functions ────────────────────────────────────────────


class TestSerialize:
    def test_none(self):
        assert _serialize(None) is None

    def test_primitives(self):
        assert _serialize(42) == 42
        assert _serialize("hello") == "hello"
        assert _serialize(3.14) == 3.14

    def test_dict(self):
        result = _serialize({"a": 1, "b": [2, 3]})
        assert result == {"a": 1, "b": [2, 3]}

    def test_pydantic_model(self):
        call = APICall(api="test", module="test.module")
        result = _serialize(call)
        assert isinstance(result, dict)
        assert result["api"] == "test"

    def test_date(self):
        from datetime import date
        result = _serialize(date(2026, 3, 26))
        assert result == "2026-03-26"

    def test_enum(self):
        result = _serialize(StageVerdict.PASS)
        assert result == "PASS"

    def test_nested_list(self):
        result = _serialize([1, [2, 3], {"a": 4}])
        assert result == [1, [2, 3], {"a": 4}]


class TestCheckInvariant:
    def test_passing_check(self):
        call = APICall(api="test", module="test")
        _check(call, "value is positive", True)
        assert call.invariants_checked == ["value is positive"]
        assert call.invariants_passed == [True]

    def test_failing_check(self):
        call = APICall(api="test", module="test")
        _check(call, "value is positive", False)
        assert call.invariants_passed == [False]

    def test_multiple_checks(self):
        call = APICall(api="test", module="test")
        _check(call, "check1", True)
        _check(call, "check2", False)
        _check(call, "check3", True)
        assert call.invariants_passed == [True, False, True]


class TestRunApi:
    def test_success(self):
        call = _run_api(
            "add", "math",
            lambda: 2 + 3,
            {"a": 2, "b": 3},
        )
        assert call.outputs == 5
        assert call.error is None
        assert call.duration_ms >= 0

    def test_error(self):
        call = _run_api(
            "fail", "test",
            lambda: 1 / 0,
            {},
        )
        assert call.error is not None
        assert "ZeroDivision" in call.error

    def test_with_invariants(self):
        call = _run_api(
            "add", "math",
            lambda: 5,
            {},
            lambda c, r: (
                _check(c, "result is 5", r == 5),
                _check(c, "result > 0", r > 0),
            ),
        )
        assert len(call.invariants_checked) == 2
        assert all(call.invariants_passed)


# ── Unit tests: Trade spec builders ──────────────────────────────────────────


class TestTradeSpecBuilders:
    def test_iron_condor(self):
        ic = _build_iron_condor()
        assert ic.ticker == "SPY"
        assert ic.structure_type == "iron_condor"
        assert len(ic.legs) == 4
        assert ic.wing_width_points == 5.0

    def test_credit_spread(self):
        cs = _build_credit_spread()
        assert cs.ticker == "GLD"
        assert cs.structure_type == "credit_spread"
        assert len(cs.legs) == 2

    def test_india_ic(self):
        ic = _build_india_ic()
        assert ic.ticker == "NIFTY"
        assert ic.structure_type == "iron_condor"
        assert len(ic.legs) == 4


# ── Stage-level tests ────────────────────────────────────────────────────────


class TestStage1Scan:
    def test_scan_completes(self):
        stage = _run_stage_1_scan(_sim_us(), _sim_india())
        assert stage.stage == "SCAN"
        assert stage.stage_number == 1
        assert len(stage.api_calls) > 0
        assert stage.duration_ms > 0

    def test_scan_has_regime_calls(self):
        stage = _run_stage_1_scan(_sim_us(), _sim_india())
        regime_calls = [c for c in stage.api_calls if c.api == "regime.detect"]
        assert len(regime_calls) >= 5  # 5 US tickers

    def test_scan_has_context_call(self):
        stage = _run_stage_1_scan(_sim_us(), _sim_india())
        context_calls = [c for c in stage.api_calls if c.api == "context.assess"]
        assert len(context_calls) >= 1

    def test_scan_verdict_not_fail_on_valid_sim(self):
        stage = _run_stage_1_scan(_sim_us(), _sim_india())
        # May be PASS or WARN depending on sim data, but shouldn't error
        assert stage.verdict != StageVerdict.FAIL or stage.error is not None


class TestStage2Rank:
    def test_rank_completes(self):
        stage = _run_stage_2_rank(_sim_us())
        assert stage.stage == "RANK"
        assert len(stage.api_calls) >= 1
        assert stage.duration_ms > 0

    def test_rank_produces_results(self):
        stage = _run_stage_2_rank(_sim_us())
        call = stage.api_calls[0]
        assert call.outputs is not None or call.error is not None


class TestStage3Gate:
    def test_gate_completes(self):
        stage = _run_stage_3_gate()
        assert stage.stage == "GATE"
        assert len(stage.api_calls) == 2  # filter_by_account + filter_with_portfolio

    def test_gate_invariants_pass(self):
        stage = _run_stage_3_gate()
        for call in stage.api_calls:
            assert call.error is None, f"{call.api} errored: {call.error}"
            assert all(call.invariants_passed), f"{call.api} has failed invariants"


class TestStage4Size:
    def test_size_completes(self):
        stage = _run_stage_4_size()
        assert stage.stage == "SIZE"
        assert len(stage.api_calls) == 3  # kelly fraction, full size, negative EV

    def test_kelly_invariants(self):
        stage = _run_stage_4_size()
        for call in stage.api_calls:
            assert call.error is None, f"{call.api} errored: {call.error}"

    def test_negative_ev_kelly(self):
        stage = _run_stage_4_size()
        neg_ev_call = [c for c in stage.api_calls if c.inputs.get("_note") == "negative_EV_trade"]
        assert len(neg_ev_call) == 1
        assert neg_ev_call[0].outputs <= 0  # Kelly should be <= 0


class TestStage5Enter:
    def test_enter_completes(self):
        stage = _run_stage_5_enter()
        assert stage.stage == "ENTER"
        assert len(stage.api_calls) >= 6  # yield, breakeven, pop, entry check (x2), greeks

    def test_income_yield_numbers(self):
        stage = _run_stage_5_enter()
        yield_call = [c for c in stage.api_calls if c.api == "compute_income_yield"][0]
        assert yield_call.error is None
        assert yield_call.outputs["max_profit"] == 160.0  # 1.60 * 100

    def test_breakeven_numbers(self):
        stage = _run_stage_5_enter()
        be_call = [c for c in stage.api_calls if c.api == "compute_breakevens"][0]
        assert be_call.error is None
        assert be_call.outputs["low"] == 568.40
        assert be_call.outputs["high"] == 591.60

    def test_entry_check_confirmed(self):
        stage = _run_stage_5_enter()
        entry_calls = [c for c in stage.api_calls if c.api == "check_income_entry"]
        good = [c for c in entry_calls if c.inputs.get("_note") != "bad_conditions"][0]
        assert good.outputs["confirmed"] is True

    def test_entry_check_rejected(self):
        stage = _run_stage_5_enter()
        bad = [c for c in stage.api_calls if c.inputs.get("_note") == "bad_conditions"][0]
        assert bad.outputs["confirmed"] is False


class TestStage6Monitor:
    def test_monitor_completes(self):
        stage = _run_stage_6_monitor()
        assert stage.stage == "MONITOR"
        assert len(stage.api_calls) == 3  # profit hit, stop loss, healthy

    def test_profit_target_triggers_close(self):
        stage = _run_stage_6_monitor()
        profit_call = [c for c in stage.api_calls if c.inputs.get("_note") == "profit_target_hit"][0]
        assert profit_call.outputs["should_close"] is True
        assert profit_call.outputs["pnl_dollars"] > 0

    def test_stop_loss_triggers_close(self):
        stage = _run_stage_6_monitor()
        stop_call = [c for c in stage.api_calls if c.inputs.get("_note") == "stop_loss_hit_with_regime_change"][0]
        assert stop_call.outputs["should_close"] is True
        assert stop_call.outputs["pnl_dollars"] < 0

    def test_healthy_trade_holds(self):
        stage = _run_stage_6_monitor()
        hold_call = [c for c in stage.api_calls if c.inputs.get("_note") == "healthy_trade_hold"][0]
        assert hold_call.outputs["should_close"] is False


class TestStage7Adjust:
    def test_adjust_completes(self):
        stage = _run_stage_7_adjust()
        assert stage.stage == "ADJUST"
        assert len(stage.api_calls) >= 1

    def test_assignment_risk(self):
        stage = _run_stage_7_adjust()
        call = stage.api_calls[0]
        assert call.error is None


class TestStage8Analytics:
    def test_analytics_completes(self):
        stage = _run_stage_8_analytics()
        assert stage.stage == "ANALYTICS"
        assert len(stage.api_calls) >= 5  # pnl_attribution, trade_pnl, structure_risk, portfolio, circuit_breakers x2

    def test_pnl_attribution_sums(self):
        stage = _run_stage_8_analytics()
        pnl_call = [c for c in stage.api_calls if c.api == "compute_pnl_attribution"][0]
        assert pnl_call.error is None
        o = pnl_call.outputs
        model = o["delta_pnl"] + o["gamma_pnl"] + o["theta_pnl"] + o["vega_pnl"]
        assert abs(model - o["model_pnl"]) < 0.01

    def test_structure_risk_ic(self):
        stage = _run_stage_8_analytics()
        risk_call = [c for c in stage.api_calls if c.api == "compute_structure_risk"][0]
        assert risk_call.error is None
        assert risk_call.outputs["max_profit"] == 160.0
        assert risk_call.outputs["max_loss"] == 340.0
        assert risk_call.outputs["risk_profile"] == "defined"

    def test_circuit_breakers_no_trip(self):
        stage = _run_stage_8_analytics()
        normal = [c for c in stage.api_calls
                  if c.api == "evaluate_circuit_breakers" and c.inputs.get("_note") != "breaker_tripped"][0]
        assert normal.outputs["can_open_new"] is True

    def test_circuit_breakers_tripped(self):
        stage = _run_stage_8_analytics()
        tripped = [c for c in stage.api_calls if c.inputs.get("_note") == "breaker_tripped"][0]
        assert tripped.outputs["can_open_new"] is False


# ── ReadinessReport model tests ──────────────────────────────────────────────


class TestReadinessReport:
    def test_compute_verdict_all_pass(self):
        report = ReadinessReport()
        s = StageResult(stage="TEST", stage_number=1, description="test")
        call = APICall(api="test", module="test")
        _check(call, "ok", True)
        s.api_calls.append(call)
        report.stages.append(s)
        report.compute_verdict()
        assert report.overall_verdict == "GO"

    def test_compute_verdict_some_fail(self):
        report = ReadinessReport()
        s = StageResult(stage="TEST", stage_number=1, description="test", verdict=StageVerdict.FAIL)
        report.stages.append(s)
        report.compute_verdict()
        assert report.overall_verdict == "NO-GO"

    def test_stage_invariant_counts(self):
        s = StageResult(stage="TEST", stage_number=1, description="test")
        call = APICall(api="test", module="test")
        _check(call, "a", True)
        _check(call, "b", False)
        _check(call, "c", True)
        s.api_calls.append(call)
        assert s.total_invariants == 3
        assert s.passed_invariants == 2
        assert s.failed_invariants == 1


# ── Report generation tests ─────────────────────────────────────────────────


class TestReportGeneration:
    def _quick_report(self) -> ReadinessReport:
        report = ReadinessReport(version="1.0.0", markets_tested=["US"])
        s = StageResult(stage="TEST", stage_number=1, description="test stage")
        call = APICall(api="test_api", module="test.module",
                       inputs={"x": 1}, outputs={"y": 2}, output_type="dict")
        _check(call, "y is 2", True)
        s.api_calls.append(call)
        report.stages.append(s)
        report.compute_verdict()
        return report

    def test_generate_html(self):
        html = generate_html(self._quick_report())
        assert "<!DOCTYPE html>" in html
        assert "income_desk Release Readiness" in html
        assert "test_api" in html
        assert "test.module" in html

    def test_write_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_html(self._quick_report(), Path(tmpdir) / "test.html")
            assert path.exists()
            content = path.read_text()
            assert "income_desk" in content

    def test_write_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_manifest(self._quick_report(), Path(tmpdir) / "manifest.json")
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["version"] == "1.0.0"
            assert len(data["stages"]) == 1
            assert data["stages"][0]["api_calls"][0]["api"] == "test_api"

    def test_manifest_has_inputs_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_manifest(self._quick_report(), Path(tmpdir) / "manifest.json")
            data = json.loads(path.read_text())
            call = data["stages"][0]["api_calls"][0]
            assert call["inputs"] == {"x": 1}
            assert call["outputs"] == {"y": 2}
            assert call["invariants_checked"] == ["y is 2"]
            assert call["invariants_passed"] == [True]


# ── End-to-end integration test ─────────────────────────────────────────────


class TestEndToEnd:
    def test_full_run_sequential(self):
        report = run_release_readiness(parallel=False, include_india=False)
        assert report.version
        assert report.total_apis_tested > 0
        assert report.total_invariants > 0
        assert report.overall_verdict in ("GO", "CONDITIONAL-GO", "NO-GO")
        assert len(report.stages) == 8

    def test_full_run_parallel(self):
        report = run_release_readiness(parallel=True, include_india=False)
        assert len(report.stages) == 8
        assert report.total_apis_tested > 0

    def test_full_run_with_india(self):
        report = run_release_readiness(parallel=True, include_india=True)
        assert "India" in report.markets_tested
        # India regime calls should be present in stage 1
        scan_stage = report.stages[0]
        india_calls = [c for c in scan_stage.api_calls
                       if c.inputs.get("market") == "India"]
        assert len(india_calls) >= 1

    def test_html_report_end_to_end(self):
        report = run_release_readiness(parallel=False, include_india=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = write_html(report, Path(tmpdir) / "readiness.html")
            manifest_path = write_manifest(report, Path(tmpdir) / "manifest.json")
            assert html_path.exists()
            assert manifest_path.exists()

            html = html_path.read_text()
            assert report.overall_verdict in html

            manifest = json.loads(manifest_path.read_text())
            assert manifest["total_apis"] == report.total_apis_tested

    def test_all_stages_present(self):
        report = run_release_readiness(parallel=False, include_india=False)
        stage_names = [s.stage for s in report.stages]
        expected = ["SCAN", "RANK", "GATE", "SIZE", "ENTER", "MONITOR", "ADJUST", "ANALYTICS"]
        assert stage_names == expected

    def test_every_stage_has_api_calls(self):
        report = run_release_readiness(parallel=False, include_india=False)
        for stage in report.stages:
            assert len(stage.api_calls) > 0, f"Stage {stage.stage} has no API calls"

    def test_every_api_call_has_invariants(self):
        report = run_release_readiness(parallel=False, include_india=False)
        for stage in report.stages:
            for call in stage.api_calls:
                if call.error is None:
                    assert len(call.invariants_checked) > 0, \
                        f"{call.api} in {stage.stage} has no invariants"

    def test_manifest_replay_completeness(self):
        report = run_release_readiness(parallel=False, include_india=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_manifest(report, Path(tmpdir) / "m.json")
            data = json.loads(path.read_text())
            for stage in data["stages"]:
                for call in stage["api_calls"]:
                    # Every successful call has inputs + outputs
                    if call["error"] is None:
                        assert call["inputs"] is not None, f"{call['api']} missing inputs"
                        assert call["outputs"] is not None, f"{call['api']} missing outputs"
