"""Comprehensive test suite for trader_md -- the MD-driven trading platform."""
from __future__ import annotations

import pytest
from pathlib import Path
from types import SimpleNamespace

from income_desk.trader_md.models import (
    Gate, Step, Phase, WorkflowPlan,
    BrokerProfile, UniverseSpec, RiskProfile,
)
from income_desk.trader_md.parser import (
    parse_workflow, parse_broker, parse_universe, parse_risk, resolve_references,
)
from income_desk.trader_md.runner import TradingRunner, ExecutionContext, StepResult

# Path to real MD files
TRADER_MD_DIR = Path("income_desk/trader_md")


# -----------------------------------------------------------------------
# Section 1: Real File Parsing
# -----------------------------------------------------------------------


class TestRealFileParsing:
    """Parse the actual committed MD files -- catches format drift."""

    def test_parse_us_workflow(self):
        plan = parse_workflow(TRADER_MD_DIR / "workflows/daily_us.workflow.md")
        assert plan.name == "daily_us_income"
        assert plan.broker_ref == "tastytrade_live"
        assert plan.universe_ref == "us_large_cap"
        assert plan.risk_ref == "moderate"
        assert len(plan.phases) == 5

    def test_parse_us_workflow_phases_have_steps(self):
        plan = parse_workflow(TRADER_MD_DIR / "workflows/daily_us.workflow.md")
        # Phase 1: Market Assessment (3 steps)
        assert plan.phases[0].name == "Market Assessment"
        assert len(plan.phases[0].steps) == 3
        # Phase 2: Scanning (2 steps)
        assert plan.phases[1].name == "Scanning"
        assert len(plan.phases[1].steps) == 2

    def test_parse_india_workflow(self):
        plan = parse_workflow(TRADER_MD_DIR / "workflows/daily_india.workflow.md")
        assert plan.name == "daily_india_income"
        assert plan.broker_ref == "dhan_live"
        assert plan.universe_ref == "india_fno"
        assert len(plan.phases) >= 4

    def test_parse_india_workflow_market_input(self):
        plan = parse_workflow(TRADER_MD_DIR / "workflows/daily_india.workflow.md")
        # India workflow steps should have market: India in inputs
        pulse_step = plan.phases[0].steps[0]
        assert pulse_step.inputs.get("market") == "India"

    def test_parse_us_universe(self):
        u = parse_universe(TRADER_MD_DIR / "universes/us_large_cap.universe.md")
        assert u.name == "us_large_cap"
        assert u.market == "US"
        assert "SPY" in u.tickers
        assert "QQQ" in u.tickers
        assert "IWM" in u.tickers
        assert "GLD" in u.tickers
        assert "AAPL" in u.tickers
        assert len(u.tickers) >= 10

    def test_parse_india_universe(self):
        u = parse_universe(TRADER_MD_DIR / "universes/india_fno.universe.md")
        assert u.name == "india_fno"
        assert u.market == "India"
        assert "NIFTY" in u.tickers
        assert "BANKNIFTY" in u.tickers
        assert "HDFCBANK" in u.tickers

    def test_parse_moderate_risk(self):
        r = parse_risk(TRADER_MD_DIR / "risk_profiles/moderate.risk.md")
        assert r.name == "moderate"
        assert r.min_pop == 0.50
        assert r.max_positions == 8
        assert r.regime_rules["r1"] is True
        assert r.regime_rules["r2"] is True
        assert r.regime_rules["r3"] is False
        assert r.regime_rules["r4"] is False

    def test_parse_conservative_risk(self):
        r = parse_risk(TRADER_MD_DIR / "risk_profiles/conservative.risk.md")
        assert r.name == "conservative"
        assert r.min_pop == 0.65  # stricter than moderate
        assert r.max_positions == 5  # fewer positions
        assert r.regime_rules["r1"] is True
        assert r.regime_rules["r2"] is False  # only R1

    def test_parse_aggressive_risk(self):
        r = parse_risk(TRADER_MD_DIR / "risk_profiles/aggressive.risk.md")
        assert r.name == "aggressive"
        assert r.min_pop == 0.40  # looser than moderate
        assert r.max_positions == 12  # more positions
        assert r.regime_rules["r3"] is True  # includes directional

    def test_parse_all_brokers(self):
        for name in ["tastytrade_live", "dhan_live", "simulated"]:
            bp = parse_broker(TRADER_MD_DIR / f"broker_profiles/{name}.broker.md")
            assert bp.name == name

    def test_tastytrade_broker_details(self):
        bp = parse_broker(TRADER_MD_DIR / "broker_profiles/tastytrade_live.broker.md")
        assert bp.broker_type == "tastytrade"
        assert bp.mode == "live"
        assert bp.market == "US"
        assert bp.currency == "USD"
        assert bp.fallback == "simulated"

    def test_dhan_broker_details(self):
        bp = parse_broker(TRADER_MD_DIR / "broker_profiles/dhan_live.broker.md")
        assert bp.broker_type == "dhan"
        assert bp.market == "India"
        assert bp.currency == "INR"

    def test_simulated_broker_details(self):
        bp = parse_broker(TRADER_MD_DIR / "broker_profiles/simulated.broker.md")
        assert bp.broker_type == "simulated"
        assert bp.mode == "simulated"

    def test_resolve_us_references(self):
        plan = parse_workflow(TRADER_MD_DIR / "workflows/daily_us.workflow.md")
        plan = resolve_references(plan, TRADER_MD_DIR)
        assert plan.broker is not None
        assert plan.broker.broker_type == "tastytrade"
        assert plan.universe is not None
        assert "SPY" in plan.universe.tickers
        assert plan.risk is not None
        assert plan.risk.min_pop == 0.50

    def test_resolve_india_references(self):
        plan = parse_workflow(TRADER_MD_DIR / "workflows/daily_india.workflow.md")
        plan = resolve_references(plan, TRADER_MD_DIR)
        assert plan.broker is not None
        assert plan.broker.broker_type == "dhan"
        assert plan.universe is not None
        assert "NIFTY" in plan.universe.tickers
        assert plan.risk is not None


# -----------------------------------------------------------------------
# Section 2: Binding Resolution
# -----------------------------------------------------------------------


class TestBindingResolution:
    """Test $variable resolution in the runner."""

    def setup_method(self):
        self.runner = TradingRunner.__new__(TradingRunner)
        self.runner.plan = None
        self.runner.ma = None
        self.ctx = ExecutionContext(
            universe=["SPY", "QQQ", "IWM"],
            capital=50000.0,
            market="US",
            currency="USD",
        )

    def test_literal_string(self):
        assert self.runner._resolve_binding("hello", self.ctx) == "hello"

    def test_literal_empty_list(self):
        assert self.runner._resolve_binding("[]", self.ctx) == []

    def test_literal_true(self):
        assert self.runner._resolve_binding("true", self.ctx) is True
        assert self.runner._resolve_binding("True", self.ctx) is True

    def test_literal_false(self):
        assert self.runner._resolve_binding("false", self.ctx) is False
        assert self.runner._resolve_binding("False", self.ctx) is False

    def test_literal_none(self):
        assert self.runner._resolve_binding("None", self.ctx) is None
        assert self.runner._resolve_binding("null", self.ctx) is None

    def test_literal_int(self):
        assert self.runner._resolve_binding("42", self.ctx) == 42

    def test_literal_float(self):
        assert self.runner._resolve_binding("1.5", self.ctx) == 1.5

    def test_literal_zero(self):
        assert self.runner._resolve_binding("0", self.ctx) == 0

    def test_universe(self):
        result = self.runner._resolve_binding("$universe", self.ctx)
        assert result == ["SPY", "QQQ", "IWM"]

    def test_capital(self):
        result = self.runner._resolve_binding("$capital", self.ctx)
        assert result == 50000.0

    def test_risk_field(self):
        self.ctx.risk = RiskProfile(name="moderate", min_pop=0.50)
        result = self.runner._resolve_binding("$risk.min_pop", self.ctx)
        assert result == 0.50

    def test_risk_field_max_positions(self):
        self.ctx.risk = RiskProfile(name="moderate", max_positions=8)
        result = self.runner._resolve_binding("$risk.max_positions", self.ctx)
        assert result == 8

    def test_risk_field_missing(self):
        self.ctx.risk = None
        result = self.runner._resolve_binding("$risk.min_pop", self.ctx)
        assert result is None

    def test_phase_output(self):
        self.ctx.phases["phase1"] = {"iv_rank_map": {"SPY": 55.0}}
        result = self.runner._resolve_binding("$phase1.iv_rank_map", self.ctx)
        assert result == {"SPY": 55.0}

    def test_phase_output_missing(self):
        result = self.runner._resolve_binding("$phase1.iv_rank_map", self.ctx)
        assert result is None

    def test_phase_output_indexed(self):
        self.ctx.phases["phase2"] = {
            "proposals": [
                SimpleNamespace(ticker="SPY", pop_pct=0.72),
                SimpleNamespace(ticker="QQQ", pop_pct=0.68),
            ]
        }
        result = self.runner._resolve_binding("$phase2.proposals[0].ticker", self.ctx)
        assert result == "SPY"

    def test_positions(self):
        from income_desk.workflow._types import OpenPosition
        pos = OpenPosition(
            trade_id="T1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", entry_price=2.80,
        )
        self.ctx.positions = [pos]
        result = self.runner._resolve_binding("$positions", self.ctx)
        assert len(result) == 1

    def test_positions_indexed(self):
        from income_desk.workflow._types import OpenPosition
        pos = OpenPosition(
            trade_id="T1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", entry_price=2.80,
        )
        self.ctx.positions = [pos]
        result = self.runner._resolve_binding("$positions[0].ticker", self.ctx)
        assert result == "SPY"

    def test_positions_indexed_trade_id(self):
        from income_desk.workflow._types import OpenPosition
        pos = OpenPosition(
            trade_id="T1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", entry_price=2.80,
        )
        self.ctx.positions = [pos]
        result = self.runner._resolve_binding("$positions[0].trade_id", self.ctx)
        assert result == "T1"

    def test_positions_indexed_out_of_range(self):
        self.ctx.positions = []
        result = self.runner._resolve_binding("$positions[0].ticker", self.ctx)
        assert result is None

    def test_non_string_passthrough(self):
        # Non-string inputs should pass through unchanged
        assert self.runner._resolve_binding(42, self.ctx) == 42
        assert self.runner._resolve_binding(None, self.ctx) is None
        assert self.runner._resolve_binding([1, 2], self.ctx) == [1, 2]


# -----------------------------------------------------------------------
# Section 3: Gate Evaluation
# -----------------------------------------------------------------------


class TestGateEvaluation:
    """Test gate expression evaluation."""

    def setup_method(self):
        self.runner = TradingRunner.__new__(TradingRunner)
        self.runner.plan = None
        self.runner.ma = None
        self.ctx = ExecutionContext()

    def test_string_not_equal_pass(self):
        result = SimpleNamespace(sentinel_signal="GREEN")
        gate = Gate(expression='sentinel_signal != "RED"', on_fail="HALT")
        assert self.runner._evaluate_gate(gate, result, self.ctx) is True

    def test_string_not_equal_fail(self):
        result = SimpleNamespace(sentinel_signal="RED")
        gate = Gate(expression='sentinel_signal != "RED"', on_fail="HALT")
        assert self.runner._evaluate_gate(gate, result, self.ctx) is False

    def test_boolean_true(self):
        result = SimpleNamespace(is_safe_to_trade=True)
        gate = Gate(expression="is_safe_to_trade == True", on_fail="HALT")
        assert self.runner._evaluate_gate(gate, result, self.ctx) is True

    def test_boolean_false(self):
        result = SimpleNamespace(is_safe_to_trade=False)
        gate = Gate(expression="is_safe_to_trade == True", on_fail="HALT")
        assert self.runner._evaluate_gate(gate, result, self.ctx) is False

    def test_len_check(self):
        result = SimpleNamespace(proposals=[1, 2, 3])
        gate = Gate(expression="len(proposals) > 0", on_fail="SKIP")
        assert self.runner._evaluate_gate(gate, result, self.ctx) is True

    def test_len_check_empty(self):
        result = SimpleNamespace(proposals=[])
        gate = Gate(expression="len(proposals) > 0", on_fail="SKIP")
        assert self.runner._evaluate_gate(gate, result, self.ctx) is False

    def test_numeric_comparison(self):
        result = SimpleNamespace(risk_pct_of_capital=2.5)
        gate = Gate(expression="risk_pct_of_capital < 5.0", on_fail="BLOCK")
        assert self.runner._evaluate_gate(gate, result, self.ctx) is True

    def test_numeric_comparison_fail(self):
        result = SimpleNamespace(risk_pct_of_capital=7.0)
        gate = Gate(expression="risk_pct_of_capital < 5.0", on_fail="BLOCK")
        assert self.runner._evaluate_gate(gate, result, self.ctx) is False

    def test_equality_check(self):
        result = SimpleNamespace(risk_score="low")
        gate = Gate(expression='risk_score != "critical"', on_fail="ALERT")
        assert self.runner._evaluate_gate(gate, result, self.ctx) is True

    def test_equality_check_fail(self):
        result = SimpleNamespace(risk_score="critical")
        gate = Gate(expression='risk_score != "critical"', on_fail="ALERT")
        assert self.runner._evaluate_gate(gate, result, self.ctx) is False

    def test_zero_count_check(self):
        result = SimpleNamespace(critical_count=0)
        gate = Gate(expression="critical_count == 0", on_fail="ALERT")
        assert self.runner._evaluate_gate(gate, result, self.ctx) is True

    def test_nonzero_count_check(self):
        result = SimpleNamespace(critical_count=2)
        gate = Gate(expression="critical_count == 0", on_fail="ALERT")
        assert self.runner._evaluate_gate(gate, result, self.ctx) is False

    def test_unparseable_gate_passes(self):
        """Gates that can't be evaluated should pass (don't block on syntax issues)."""
        gate = Gate(expression="some_weird_expression!!", on_fail="HALT")
        assert self.runner._evaluate_gate(gate, None, self.ctx) is True

    def test_none_result_passes(self):
        """Gate with None result should pass (can't evaluate)."""
        gate = Gate(expression="missing_field == True", on_fail="HALT")
        assert self.runner._evaluate_gate(gate, None, self.ctx) is True

    def test_gate_with_risk_reference(self):
        """Gate referencing $risk.field should resolve correctly."""
        self.ctx.risk = RiskProfile(name="moderate", max_risk_per_trade_pct=3.0)
        result = SimpleNamespace(risk_pct_of_capital=2.0)
        gate = Gate(expression="risk_pct_of_capital < $risk.max_risk_per_trade_pct", on_fail="BLOCK")
        assert self.runner._evaluate_gate(gate, result, self.ctx) is True


# -----------------------------------------------------------------------
# Section 4: Validate & Dry-Run
# -----------------------------------------------------------------------


class TestValidateAndDryRun:
    """Test validate and dry-run commands against real files."""

    def test_validate_us_workflow(self):
        runner = TradingRunner(str(TRADER_MD_DIR / "workflows/daily_us.workflow.md"))
        issues = runner.validate()
        workflow_issues = [i for i in issues if "Unknown workflow" in i]
        assert len(workflow_issues) == 0, f"Unknown workflows: {workflow_issues}"

    def test_validate_india_workflow(self):
        runner = TradingRunner(str(TRADER_MD_DIR / "workflows/daily_india.workflow.md"))
        issues = runner.validate()
        workflow_issues = [i for i in issues if "Unknown workflow" in i]
        assert len(workflow_issues) == 0

    def test_validate_us_has_no_missing_refs(self):
        runner = TradingRunner(str(TRADER_MD_DIR / "workflows/daily_us.workflow.md"))
        issues = runner.validate()
        ref_issues = [i for i in issues if "not found" in i]
        assert len(ref_issues) == 0, f"Missing references: {ref_issues}"

    def test_validate_india_has_no_missing_refs(self):
        runner = TradingRunner(str(TRADER_MD_DIR / "workflows/daily_india.workflow.md"))
        issues = runner.validate()
        ref_issues = [i for i in issues if "not found" in i]
        assert len(ref_issues) == 0, f"Missing references: {ref_issues}"

    def test_validate_bad_broker(self, tmp_path):
        wf = tmp_path / "bad.workflow.md"
        wf.write_text(
            '---\nname: bad\nbroker: nonexistent\nuniverse: us_large_cap\n'
            'risk_profile: moderate\n---\n\n## Phase 1: Test\n\n'
            '### Step: Health\nworkflow: check_portfolio_health\n'
        )
        runner = TradingRunner(str(wf))
        issues = runner.validate()
        assert any("broker" in i.lower() or "nonexistent" in i.lower() for i in issues)

    def test_validate_bad_universe(self, tmp_path):
        wf = tmp_path / "bad.workflow.md"
        wf.write_text(
            '---\nname: bad\nbroker: simulated\nuniverse: nonexistent\n'
            'risk_profile: moderate\n---\n\n## Phase 1: Test\n\n'
            '### Step: Health\nworkflow: check_portfolio_health\n'
        )
        runner = TradingRunner(str(wf))
        issues = runner.validate()
        assert any("universe" in i.lower() or "nonexistent" in i.lower() for i in issues)

    def test_validate_unknown_workflow_name(self, tmp_path):
        wf = tmp_path / "bad.workflow.md"
        wf.write_text(
            '---\nname: bad\nbroker: simulated\n---\n\n## Phase 1: Test\n\n'
            '### Step: BadStep\nworkflow: totally_fake_workflow\n'
        )
        runner = TradingRunner(str(wf))
        issues = runner.validate()
        assert any("Unknown workflow" in i for i in issues)

    def test_dry_run_us(self):
        runner = TradingRunner(str(TRADER_MD_DIR / "workflows/daily_us.workflow.md"))
        output = runner.dry_run()
        assert "daily_us_income" in output
        assert "Phase 1" in output
        assert "check_portfolio_health" in output
        assert "rank_opportunities" in output
        assert "tastytrade_live" in output

    def test_dry_run_india(self):
        runner = TradingRunner(str(TRADER_MD_DIR / "workflows/daily_india.workflow.md"))
        output = runner.dry_run()
        assert "daily_india_income" in output
        assert "dhan" in output.lower()
        assert "Phase 1" in output

    def test_dry_run_shows_step_inputs(self):
        runner = TradingRunner(str(TRADER_MD_DIR / "workflows/daily_us.workflow.md"))
        output = runner.dry_run()
        # Should show input bindings
        assert "$universe" in output
        assert "$capital" in output

    def test_dry_run_shows_gates(self):
        runner = TradingRunner(str(TRADER_MD_DIR / "workflows/daily_us.workflow.md"))
        output = runner.dry_run()
        # Steps with gates should show gate count
        assert "gates" in output.lower()


# -----------------------------------------------------------------------
# Section 5: Full Execution (against simulated data)
# -----------------------------------------------------------------------


class TestFullExecution:
    """Full end-to-end execution against simulated data."""

    @pytest.mark.slow
    def test_run_us_workflow(self):
        """Full US workflow execution -- should complete with no FAILED steps."""
        runner = TradingRunner(str(TRADER_MD_DIR / "workflows/daily_us.workflow.md"))
        report = runner.run()
        failed = [r for r in report.step_results if r.status == "FAILED"]
        assert len(failed) == 0, f"Failed steps: {[(f.step_name, f.message) for f in failed]}"
        assert len(report.step_results) >= 10  # at least 10 steps should execute

    @pytest.mark.slow
    def test_run_india_workflow(self):
        """Full India workflow execution."""
        runner = TradingRunner(str(TRADER_MD_DIR / "workflows/daily_india.workflow.md"))
        report = runner.run()
        failed = [r for r in report.step_results if r.status == "FAILED"]
        assert len(failed) == 0, f"Failed steps: {[(f.step_name, f.message) for f in failed]}"

    @pytest.mark.slow
    def test_run_report_has_plan_name(self):
        """Report should contain plan metadata."""
        runner = TradingRunner(str(TRADER_MD_DIR / "workflows/daily_us.workflow.md"))
        report = runner.run()
        assert report.plan_name == "daily_us_income"
        assert report.market == "US"

    @pytest.mark.slow
    def test_run_with_simulated_broker(self, tmp_path):
        """Workflow with simulated broker should work without credentials."""
        import shutil
        wf_content = '''---
name: test_simulated
broker: simulated
universe: us_large_cap
risk_profile: moderate
---

## Phase 1: Test

### Step: Health
workflow: check_portfolio_health
inputs:
  tickers: $universe
  capital: $capital
'''
        wf = tmp_path / "test.workflow.md"
        wf.write_text(wf_content)

        # Copy supporting files
        for subdir in ["broker_profiles", "universes", "risk_profiles"]:
            src = TRADER_MD_DIR / subdir
            dst = tmp_path / subdir
            if src.exists():
                shutil.copytree(src, dst)

        runner = TradingRunner(str(wf))
        report = runner.run()
        assert len(report.step_results) >= 1
        assert report.step_results[0].status == "OK"


# -----------------------------------------------------------------------
# Section 6: Behavior Change Tests
# -----------------------------------------------------------------------


class TestBehaviorChanges:
    """Verify that editing MD files changes workflow behavior."""

    def test_smaller_universe(self, tmp_path):
        """Smaller universe should produce fewer tickers in resolved plan."""
        import shutil
        shutil.copytree(TRADER_MD_DIR, tmp_path / "trader_md")

        # Create tiny universe
        tiny = tmp_path / "trader_md/universes/tiny.universe.md"
        tiny.write_text('---\nname: tiny\nmarket: US\n---\n\n- SPY\n- QQQ\n')

        # Create workflow using tiny universe
        wf = tmp_path / "trader_md/workflows/tiny_test.workflow.md"
        wf_content = (tmp_path / "trader_md/workflows/daily_us.workflow.md").read_text()
        wf_content = wf_content.replace("universe: us_large_cap", "universe: tiny")
        wf_content = wf_content.replace("name: daily_us_income", "name: tiny_test")
        wf.write_text(wf_content)

        plan = parse_workflow(Path(str(wf)))
        plan = resolve_references(plan, tmp_path / "trader_md")
        assert plan.universe is not None
        assert len(plan.universe.tickers) == 2
        assert set(plan.universe.tickers) == {"SPY", "QQQ"}

    def test_different_risk_profile(self, tmp_path):
        """Switching risk profile should change resolved risk values."""
        import shutil
        shutil.copytree(TRADER_MD_DIR, tmp_path / "trader_md")

        # Create workflow using aggressive risk
        wf = tmp_path / "trader_md/workflows/agg_test.workflow.md"
        wf_content = (tmp_path / "trader_md/workflows/daily_us.workflow.md").read_text()
        wf_content = wf_content.replace("risk_profile: moderate", "risk_profile: aggressive")
        wf_content = wf_content.replace("name: daily_us_income", "name: agg_test")
        wf.write_text(wf_content)

        plan = parse_workflow(Path(str(wf)))
        plan = resolve_references(plan, tmp_path / "trader_md")
        assert plan.risk is not None
        assert plan.risk.name == "aggressive"
        assert plan.risk.min_pop == 0.40
        assert plan.risk.max_positions == 12

    def test_different_broker(self, tmp_path):
        """Switching broker should change resolved broker type."""
        import shutil
        shutil.copytree(TRADER_MD_DIR, tmp_path / "trader_md")

        wf = tmp_path / "trader_md/workflows/sim_test.workflow.md"
        wf_content = (tmp_path / "trader_md/workflows/daily_us.workflow.md").read_text()
        wf_content = wf_content.replace("broker: tastytrade_live", "broker: simulated")
        wf_content = wf_content.replace("name: daily_us_income", "name: sim_test")
        wf.write_text(wf_content)

        plan = parse_workflow(Path(str(wf)))
        plan = resolve_references(plan, tmp_path / "trader_md")
        assert plan.broker is not None
        assert plan.broker.broker_type == "simulated"

    def test_custom_risk_profile(self, tmp_path):
        """Custom risk profile with extreme values should parse correctly."""
        import shutil
        shutil.copytree(TRADER_MD_DIR, tmp_path / "trader_md")

        strict_risk = tmp_path / "trader_md/risk_profiles/strict.risk.md"
        strict_risk.write_text(
            '---\nname: strict\nmax_risk_per_trade_pct: 1.0\n'
            'max_portfolio_risk_pct: 10.0\nmax_positions: 2\nmin_pop: 0.99\n'
            'min_dte: 30\nmax_dte: 45\nmin_iv_rank: 80\nmax_spread_pct: 0.01\n'
            'profit_target_pct: 0.50\nstop_loss_pct: 1.0\nexit_dte: 10\n'
            'r1_allowed: true\nr2_allowed: false\nr3_allowed: false\nr4_allowed: false\n---\n'
        )

        r = parse_risk(strict_risk)
        assert r.name == "strict"
        assert r.min_pop == 0.99
        assert r.max_positions == 2
        assert r.regime_rules["r1"] is True
        assert r.regime_rules["r2"] is False


# -----------------------------------------------------------------------
# Section 7: Error Handling
# -----------------------------------------------------------------------


class TestErrorHandling:
    """Verify graceful error handling."""

    def test_missing_workflow_file(self):
        runner = TradingRunner("nonexistent.workflow.md")
        issues = runner.validate()
        # Should return parse error (file not found)
        assert len(issues) > 0
        assert any("error" in i.lower() or "parse" in i.lower() for i in issues)

    def test_malformed_workflow(self, tmp_path):
        wf = tmp_path / "bad.workflow.md"
        wf.write_text("This is not a valid workflow file\nNo frontmatter here")
        runner = TradingRunner(str(wf))
        issues = runner.validate()
        # Should not crash -- will parse with defaults and likely have missing refs
        assert isinstance(issues, list)

    def test_empty_workflow(self, tmp_path):
        wf = tmp_path / "empty.workflow.md"
        wf.write_text('---\nname: empty\nbroker: simulated\n---\n')
        runner = TradingRunner(str(wf))
        issues = runner.validate()
        # Should parse OK even if empty (no phases)
        # validate may warn about missing universe/risk but shouldn't crash
        assert isinstance(issues, list)

    def test_workflow_no_phases(self, tmp_path):
        wf = tmp_path / "nophase.workflow.md"
        wf.write_text('---\nname: nophase\nbroker: simulated\n---\n\nSome text but no phases.\n')
        plan = parse_workflow(wf)
        assert plan.name == "nophase"
        assert len(plan.phases) == 0

    def test_workflow_phase_no_steps(self, tmp_path):
        wf = tmp_path / "nosteps.workflow.md"
        wf.write_text(
            '---\nname: nosteps\nbroker: simulated\n---\n\n'
            '## Phase 1: Empty Phase\n\nSome description.\n'
        )
        plan = parse_workflow(wf)
        assert len(plan.phases) == 1
        assert len(plan.phases[0].steps) == 0

    def test_resolve_missing_all_references(self, tmp_path):
        wf = tmp_path / "missing.workflow.md"
        wf.write_text(
            '---\nname: missing\nbroker: fake_broker\n'
            'universe: fake_universe\nrisk_profile: fake_risk\n---\n'
        )
        plan = parse_workflow(wf)
        plan = resolve_references(plan, tmp_path)
        assert plan.broker is None
        assert plan.universe is None
        assert plan.risk is None

    def test_universe_no_tickers(self, tmp_path):
        u_file = tmp_path / "empty.universe.md"
        u_file.write_text('---\nname: empty\nmarket: US\n---\n\nNo tickers listed.\n')
        u = parse_universe(u_file)
        assert u.name == "empty"
        assert len(u.tickers) == 0

    def test_risk_defaults_when_minimal(self, tmp_path):
        r_file = tmp_path / "minimal.risk.md"
        r_file.write_text('---\nname: minimal\n---\n')
        r = parse_risk(r_file)
        assert r.name == "minimal"
        # Should get default values
        assert r.min_pop == 0.50
        assert r.max_positions == 8
        assert r.regime_rules == {"r1": True, "r2": True, "r3": False, "r4": False}

    def test_broker_defaults_when_minimal(self, tmp_path):
        b_file = tmp_path / "minimal.broker.md"
        b_file.write_text('---\nname: minimal\n---\n')
        bp = parse_broker(b_file)
        assert bp.name == "minimal"
        assert bp.broker_type == "simulated"
        assert bp.fallback == "simulated"


# -----------------------------------------------------------------------
# Section 8: StepResult & ExecutionReport
# -----------------------------------------------------------------------


class TestRunnerDataModels:
    """Test runner data model construction."""

    def test_step_result_defaults(self):
        sr = StepResult(step_name="Health", workflow="check_portfolio_health", status="OK")
        assert sr.duration_ms == 0
        assert sr.gate_results == []
        assert sr.message == ""

    def test_step_result_with_gates(self):
        sr = StepResult(
            step_name="Rank",
            workflow="rank_opportunities",
            status="SKIPPED",
            message="No opportunities",
            gate_results=[("len(proposals) > 0", False)],
        )
        assert sr.status == "SKIPPED"
        assert len(sr.gate_results) == 1
        assert sr.gate_results[0][1] is False

    def test_execution_context_defaults(self):
        ctx = ExecutionContext()
        assert ctx.universe == []
        assert ctx.capital == 50_000.0
        assert ctx.market == "US"
        assert ctx.phases == {}
        assert ctx.positions == []

    def test_execution_context_custom(self):
        ctx = ExecutionContext(
            universe=["NIFTY", "BANKNIFTY"],
            capital=5_000_000,
            market="India",
            currency="INR",
        )
        assert ctx.market == "India"
        assert ctx.capital == 5_000_000
        assert len(ctx.universe) == 2
