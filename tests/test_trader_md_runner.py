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
    ctx = ExecutionContext(universe=["SPY"])
    assert runner._resolve_binding("hello", ctx) == "hello"
    assert runner._resolve_binding("42", ctx) == "42"
    assert runner._resolve_binding("true", ctx) == "true"


def test_resolve_binding_universe():
    """$universe resolves to ticker list."""
    runner = TradingRunner.__new__(TradingRunner)
    ctx = ExecutionContext(universe=["SPY", "QQQ", "IWM"])
    result = runner._resolve_binding("$universe", ctx)
    assert result == ["SPY", "QQQ", "IWM"]


def test_resolve_binding_capital():
    """$capital resolves to capital value."""
    runner = TradingRunner.__new__(TradingRunner)
    ctx = ExecutionContext(capital=100_000.0)
    assert runner._resolve_binding("$capital", ctx) == 100_000.0


def test_resolve_binding_risk():
    """$risk.min_pop resolves to risk profile field."""
    from income_desk.trader_md.models import RiskProfile

    runner = TradingRunner.__new__(TradingRunner)
    risk = RiskProfile(name="test", min_pop=0.65, max_positions=5)
    ctx = ExecutionContext(risk=risk)
    assert runner._resolve_binding("$risk.min_pop", ctx) == 0.65
    assert runner._resolve_binding("$risk.max_positions", ctx) == 5


def test_resolve_binding_risk_missing():
    """$risk.field with no risk profile returns None."""
    runner = TradingRunner.__new__(TradingRunner)
    ctx = ExecutionContext(risk=None)
    assert runner._resolve_binding("$risk.min_pop", ctx) is None


def test_resolve_binding_phase_output():
    """$phase1.iv_rank_map resolves to phase output."""
    runner = TradingRunner.__new__(TradingRunner)
    ctx = ExecutionContext()
    ctx.phases["phase1"] = {"iv_rank_map": {"SPY": 45.0, "QQQ": 32.0}}
    result = runner._resolve_binding("$phase1.iv_rank_map", ctx)
    assert result == {"SPY": 45.0, "QQQ": 32.0}


def test_resolve_binding_indexed():
    """$phase2.proposals[0].ticker resolves through list index."""
    runner = TradingRunner.__new__(TradingRunner)

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
    ctx = ExecutionContext(positions=["pos1", "pos2"])
    assert runner._resolve_binding("$positions", ctx) == ["pos1", "pos2"]
