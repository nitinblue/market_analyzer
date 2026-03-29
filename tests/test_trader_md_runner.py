"""Tests for trader_md runner — validate, dry_run, binding resolution."""
from __future__ import annotations

import textwrap

import pytest

from income_desk.trader_md.runner import ExecutionContext, TradingRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_minimal_workflow(tmp_path, broker="simulated", universe="test_uni", risk="test_risk"):
    """Create a minimal workflow + supporting MD files for testing."""
    # Workflow
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    wf_file = wf_dir / "test.workflow.md"
    wf_file.write_text(textwrap.dedent(f"""\
        ---
        name: test_workflow
        description: Test workflow
        broker: {broker}
        universe: {universe}
        risk_profile: {risk}
        ---

        # Test Workflow

        ## Phase 1: Assessment

        ### Step: Health Check
        workflow: check_portfolio_health
        inputs:
          tickers: $universe
          capital: $capital
    """), encoding="utf-8")

    # Broker
    bp_dir = tmp_path / "broker_profiles"
    bp_dir.mkdir()
    (bp_dir / "simulated.broker.md").write_text(textwrap.dedent("""\
        ---
        name: simulated
        broker_type: simulated
        mode: simulated
        market: US
        currency: USD
        credentials: none
        fallback: none
        ---
    """), encoding="utf-8")

    # Universe
    uni_dir = tmp_path / "universes"
    uni_dir.mkdir()
    (uni_dir / "test_uni.universe.md").write_text(textwrap.dedent("""\
        ---
        name: test_universe
        market: US
        ---
        - SPY
        - QQQ
    """), encoding="utf-8")

    # Risk
    risk_dir = tmp_path / "risk_profiles"
    risk_dir.mkdir()
    (risk_dir / "test_risk.risk.md").write_text(textwrap.dedent("""\
        ---
        name: test_moderate
        max_positions: 8
        min_pop: 0.55
        max_risk_per_trade_pct: 3.0
        ---
    """), encoding="utf-8")

    return wf_file


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


def test_runner_validate_good(tmp_path):
    """Valid workflow with all references should validate clean."""
    wf_file = _write_minimal_workflow(tmp_path)
    runner = TradingRunner(str(wf_file))
    issues = runner.validate()
    assert issues == []


def test_runner_validate_missing_broker(tmp_path):
    """Missing broker ref should report issue."""
    wf_file = _write_minimal_workflow(tmp_path, broker="nonexistent")
    runner = TradingRunner(str(wf_file))
    issues = runner.validate()
    assert any("nonexistent" in i for i in issues)


def test_runner_validate_missing_universe(tmp_path):
    """Missing universe ref should report issue."""
    wf_file = _write_minimal_workflow(tmp_path, universe="nonexistent")
    runner = TradingRunner(str(wf_file))
    issues = runner.validate()
    assert any("nonexistent" in i for i in issues)


def test_runner_validate_missing_risk(tmp_path):
    """Missing risk profile ref should report issue."""
    wf_file = _write_minimal_workflow(tmp_path, risk="nonexistent")
    runner = TradingRunner(str(wf_file))
    issues = runner.validate()
    assert any("nonexistent" in i for i in issues)


# ---------------------------------------------------------------------------
# Dry run tests
# ---------------------------------------------------------------------------


def test_runner_dry_run(tmp_path):
    """Dry run should show phases and steps without executing."""
    wf_file = _write_minimal_workflow(tmp_path)
    runner = TradingRunner(str(wf_file))
    output = runner.dry_run()
    assert "DRY RUN: test_workflow" in output
    assert "Phase 1: Assessment" in output
    assert "Health Check" in output
    assert "check_portfolio_health" in output
    assert "2 tickers" in output


# ---------------------------------------------------------------------------
# Binding resolution tests
# ---------------------------------------------------------------------------


def test_resolve_binding_literal():
    """Non-$ strings pass through as literals."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {}
    ctx = ExecutionContext(universe=["SPY"])
    assert runner._resolve_binding("hello", ctx) == "hello"
    assert runner._resolve_binding("42", ctx) == 42
    assert runner._resolve_binding("true", ctx) is True


def test_resolve_binding_universe():
    """$universe resolves to ticker list."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {}
    ctx = ExecutionContext(universe=["SPY", "QQQ", "IWM"])
    result = runner._resolve_binding("$universe", ctx)
    assert result == ["SPY", "QQQ", "IWM"]


def test_resolve_binding_capital():
    """$capital resolves to capital value."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {}
    ctx = ExecutionContext(capital=100_000.0)
    assert runner._resolve_binding("$capital", ctx) == 100_000.0


def test_resolve_binding_risk():
    """$risk.min_pop resolves to risk profile field."""
    from income_desk.trader_md.models import RiskProfile

    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {}
    risk = RiskProfile(name="test", min_pop=0.65, max_positions=5)
    ctx = ExecutionContext(risk=risk)
    assert runner._resolve_binding("$risk.min_pop", ctx) == 0.65
    assert runner._resolve_binding("$risk.max_positions", ctx) == 5


def test_resolve_binding_risk_missing():
    """$risk.field with no risk profile returns None."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {}
    ctx = ExecutionContext(risk=None)
    assert runner._resolve_binding("$risk.min_pop", ctx) is None


def test_resolve_binding_phase_output():
    """$phase1.iv_rank_map resolves to phase output."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {}
    ctx = ExecutionContext()
    ctx.phases["phase1"] = {"iv_rank_map": {"SPY": 45.0, "QQQ": 32.0}}
    result = runner._resolve_binding("$phase1.iv_rank_map", ctx)
    assert result == {"SPY": 45.0, "QQQ": 32.0}


def test_resolve_binding_indexed():
    """$phase2.proposals[0].ticker resolves through list index."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {}

    class FakeProposal:
        ticker = "SPY"
        entry_credit = 2.80

    ctx = ExecutionContext()
    ctx.phases["phase2"] = {"proposals": [FakeProposal()]}
    assert runner._resolve_binding("$phase2.proposals[0].ticker", ctx) == "SPY"
    assert runner._resolve_binding("$phase2.proposals[0].entry_credit", ctx) == 2.80


def test_resolve_binding_positions():
    """$positions resolves to position list."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {}
    ctx = ExecutionContext(positions=["pos1", "pos2"])
    assert runner._resolve_binding("$positions", ctx) == ["pos1", "pos2"]


# ---------------------------------------------------------------------------
# --set override tests
# ---------------------------------------------------------------------------


def test_set_override_capital():
    """--set capital=100000 overrides $capital binding."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {"capital": "100000"}
    ctx = ExecutionContext(capital=50_000.0)
    result = runner._resolve_binding("$capital", ctx)
    assert result == 100000
    assert isinstance(result, int)


def test_set_override_float():
    """--set min_pop=0.70 parses as float."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {"min_pop": "0.70"}
    ctx = ExecutionContext()
    result = runner._resolve_binding("$min_pop", ctx)
    assert result == 0.70
    assert isinstance(result, float)


def test_set_override_string():
    """--set predictions_path=data/my.json passes through as string."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {"predictions_path": "data/my_predictions.json"}
    ctx = ExecutionContext()
    result = runner._resolve_binding("$predictions_path", ctx)
    assert result == "data/my_predictions.json"


def test_set_override_boolean():
    """--set skip_intraday=true parses as bool."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {"skip_intraday": "true"}
    ctx = ExecutionContext()
    assert runner._resolve_binding("$skip_intraday", ctx) is True


def test_set_override_literal_key():
    """Override a non-$ literal key."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {"period": "2026-Q1"}
    ctx = ExecutionContext()
    result = runner._resolve_binding("period", ctx)
    assert result == "2026-Q1"


def test_set_override_takes_priority():
    """Override takes priority over context value."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {"capital": "200000"}
    ctx = ExecutionContext(capital=50_000.0)
    assert runner._resolve_binding("$capital", ctx) == 200000


def test_no_override_falls_through():
    """Without override, $capital resolves normally from context."""
    runner = TradingRunner.__new__(TradingRunner)
    runner.overrides = {}
    ctx = ExecutionContext(capital=75_000.0)
    assert runner._resolve_binding("$capital", ctx) == 75_000.0


# ---------------------------------------------------------------------------
# parse_literal tests
# ---------------------------------------------------------------------------


def test_parse_literal_types():
    """_parse_literal handles int, float, bool, None, list, string."""
    assert TradingRunner._parse_literal("42") == 42
    assert TradingRunner._parse_literal("3.14") == 3.14
    assert TradingRunner._parse_literal("true") is True
    assert TradingRunner._parse_literal("False") is False
    assert TradingRunner._parse_literal("null") is None
    assert TradingRunner._parse_literal("[]") == []
    assert TradingRunner._parse_literal("hello") == "hello"


# ---------------------------------------------------------------------------
# export_report tests
# ---------------------------------------------------------------------------


def test_export_report(tmp_path):
    """export_report saves a markdown file with summary table."""
    from datetime import datetime

    from income_desk.trader_md.runner import ExecutionReport, StepResult

    runner = TradingRunner.__new__(TradingRunner)
    runner.plan = None
    runner.report = ExecutionReport(
        plan_name="test_plan",
        market="US",
        broker="simulated",
        data_source="Simulated (preset)",
        started_at=datetime(2026, 3, 28, 10, 0),
        step_results=[
            StepResult(step_name="Health Check", workflow="check_portfolio_health",
                       status="OK", duration_ms=120),
            StepResult(step_name="Scan", workflow="scan_universe",
                       status="FAILED", message="timeout", duration_ms=5000),
        ],
    )

    report_path = tmp_path / "report.md"
    runner.export_report(str(report_path))

    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "# test_plan" in content
    assert "2026-03-28" in content
    assert "simulated" in content


def test_export_report_contains_status(tmp_path):
    """Report file contains OK/FAILED/SKIPPED statuses."""
    from datetime import datetime

    from income_desk.trader_md.runner import ExecutionReport, StepResult

    runner = TradingRunner.__new__(TradingRunner)
    runner.plan = None
    runner.report = ExecutionReport(
        plan_name="status_test",
        market="US",
        broker="simulated",
        data_source="Simulated",
        started_at=datetime(2026, 3, 28, 10, 0),
        step_results=[
            StepResult(step_name="Step A", workflow="wf_a", status="OK", duration_ms=50),
            StepResult(step_name="Step B", workflow="wf_b", status="FAILED",
                       message="broke", duration_ms=100),
            StepResult(step_name="Step C", workflow="wf_c", status="SKIPPED",
                       message="not needed", duration_ms=0),
        ],
    )

    report_path = tmp_path / "status_report.md"
    runner.export_report(str(report_path))

    content = report_path.read_text(encoding="utf-8")
    assert "OK" in content
    assert "FAILED" in content
    assert "SKIPPED" in content
    assert "**Total:** 3" in content
    assert "**OK:** 1" in content
    assert "**Failed:** 1" in content


def test_export_report_with_gates(tmp_path):
    """Report includes gate results when present."""
    from datetime import datetime

    from income_desk.trader_md.runner import ExecutionReport, StepResult

    runner = TradingRunner.__new__(TradingRunner)
    runner.plan = None
    runner.report = ExecutionReport(
        plan_name="gate_test",
        market="US",
        broker="simulated",
        data_source="Simulated",
        started_at=datetime(2026, 3, 28, 10, 0),
        step_results=[
            StepResult(step_name="Gated Step", workflow="wf_g", status="OK",
                       duration_ms=50,
                       gate_results=[("health_ok == True", True), ("score > 0.5", False)]),
        ],
    )

    report_path = tmp_path / "gate_report.md"
    runner.export_report(str(report_path))

    content = report_path.read_text(encoding="utf-8")
    assert "## Gate Results" in content
    assert "[PASS]" in content
    assert "[FAIL]" in content


def test_export_report_halted(tmp_path):
    """Report shows HALTED status when workflow was halted."""
    from datetime import datetime

    from income_desk.trader_md.runner import ExecutionReport

    runner = TradingRunner.__new__(TradingRunner)
    runner.plan = None
    runner.report = ExecutionReport(
        plan_name="halted_test",
        market="US",
        broker="simulated",
        data_source="Simulated",
        started_at=datetime(2026, 3, 28, 10, 0),
        halted=True,
        halt_reason="Critical gate failed",
    )

    report_path = tmp_path / "halted_report.md"
    runner.export_report(str(report_path))

    content = report_path.read_text(encoding="utf-8")
    assert "**HALTED:**" in content
    assert "Critical gate failed" in content
