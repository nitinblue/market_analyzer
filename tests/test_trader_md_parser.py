import pytest
from pathlib import Path
from income_desk.trader_md.models import (
    Gate, Step, Phase, WorkflowPlan,
    BrokerProfile, UniverseSpec, RiskProfile,
)
from income_desk.trader_md.parser import (
    parse_workflow, parse_broker, parse_universe, parse_risk, resolve_references,
)


# --- Model tests ---

def test_gate_creation():
    g = Gate(expression='pulse != "RED"', on_fail="HALT", message="halted")
    assert g.on_fail == "HALT"

def test_step_defaults():
    s = Step(name="Health", workflow="check_portfolio_health")
    assert s.inputs == {}
    assert s.gates == []
    assert s.requires is None

def test_phase_with_steps():
    p = Phase(name="Pre-Market", number=1, steps=[
        Step(name="Health", workflow="check_portfolio_health"),
    ])
    assert len(p.steps) == 1
    assert not p.requires_positions

def test_risk_profile_defaults():
    rp = RiskProfile(name="moderate")
    assert rp.min_pop == 0.50
    assert rp.regime_rules["r1"] is True
    assert rp.regime_rules["r4"] is False


# --- Parser tests ---

SAMPLE_WORKFLOW = '''---
name: test_workflow
description: A test workflow
broker: simulated
universe: us_test
risk_profile: moderate
---

# Test Workflow

## Phase 1: Assessment

### Step: Market Pulse
workflow: check_portfolio_health
inputs:
  tickers: $universe
  capital: $capital
outputs:
  pulse: $result.sentinel_signal
  safe: $result.is_safe_to_trade
gate:
  - pulse != "RED"
  - safe == True
on_fail: HALT "Market pulse {pulse}"

### Step: Snapshot
workflow: snapshot_market
inputs:
  tickers: $universe
outputs:
  iv_rank_map: $result.tickers

## Phase 2: Scanning

### Step: Rank
workflow: rank_opportunities
inputs:
  tickers: $universe
  capital: $capital
  iv_rank_map: $phase1.iv_rank_map
gate:
  - len(proposals) > 0
on_fail: SKIP "No opportunities"

## Phase 3: Monitoring

requires_positions: true

### Step: Monitor
workflow: monitor_positions
inputs:
  positions: $positions
'''

SAMPLE_BROKER = '''---
name: test_broker
broker_type: tastytrade
mode: live
market: US
currency: USD
credentials: .env.trading
fallback: simulated
---
'''

SAMPLE_UNIVERSE = '''---
name: us_test
market: US
description: Test universe
---

## Core
- SPY
- QQQ
- IWM

## Commodities
- GLD    # Gold
'''

SAMPLE_RISK = '''---
name: moderate
max_risk_per_trade_pct: 3.0
max_portfolio_risk_pct: 30.0
max_positions: 8
min_pop: 0.50
min_dte: 7
max_dte: 45
min_iv_rank: 20.0
max_spread_pct: 0.05
profit_target_pct: 0.50
stop_loss_pct: 2.0
exit_dte: 5
r1_allowed: true
r2_allowed: true
r3_allowed: false
r4_allowed: false
---
'''


def test_parse_workflow_metadata():
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.workflow.md', delete=False) as f:
        f.write(SAMPLE_WORKFLOW)
        f.flush()
        plan = parse_workflow(Path(f.name))
    assert plan.name == "test_workflow"
    assert plan.broker_ref == "simulated"
    assert plan.universe_ref == "us_test"
    assert plan.risk_ref == "moderate"

def test_parse_workflow_phases():
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.workflow.md', delete=False) as f:
        f.write(SAMPLE_WORKFLOW)
        f.flush()
        plan = parse_workflow(Path(f.name))
    assert len(plan.phases) == 3
    assert plan.phases[0].name == "Assessment"
    assert plan.phases[0].number == 1
    assert plan.phases[2].requires_positions is True

def test_parse_workflow_steps():
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.workflow.md', delete=False) as f:
        f.write(SAMPLE_WORKFLOW)
        f.flush()
        plan = parse_workflow(Path(f.name))
    phase1 = plan.phases[0]
    assert len(phase1.steps) == 2
    assert phase1.steps[0].workflow == "check_portfolio_health"
    assert phase1.steps[0].inputs["tickers"] == "$universe"
    assert phase1.steps[0].outputs["pulse"] == "$result.sentinel_signal"

def test_parse_workflow_gates():
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.workflow.md', delete=False) as f:
        f.write(SAMPLE_WORKFLOW)
        f.flush()
        plan = parse_workflow(Path(f.name))
    step = plan.phases[0].steps[0]
    assert len(step.gates) == 2
    assert step.gates[0].expression == 'pulse != "RED"'
    assert step.gates[0].on_fail == "HALT"
    assert "pulse" in step.gates[0].message

def test_parse_broker(tmp_path):
    p = tmp_path / "test.broker.md"
    p.write_text(SAMPLE_BROKER)
    bp = parse_broker(p)
    assert bp.name == "test_broker"
    assert bp.broker_type == "tastytrade"
    assert bp.mode == "live"
    assert bp.credentials_source == ".env.trading"
    assert bp.fallback == "simulated"

def test_parse_universe(tmp_path):
    p = tmp_path / "test.universe.md"
    p.write_text(SAMPLE_UNIVERSE)
    u = parse_universe(p)
    assert u.name == "us_test"
    assert u.market == "US"
    assert set(u.tickers) == {"SPY", "QQQ", "IWM", "GLD"}

def test_parse_risk(tmp_path):
    p = tmp_path / "test.risk.md"
    p.write_text(SAMPLE_RISK)
    r = parse_risk(p)
    assert r.name == "moderate"
    assert r.min_pop == 0.50
    assert r.max_positions == 8
    assert r.regime_rules["r1"] is True
    assert r.regime_rules["r4"] is False

def test_resolve_references(tmp_path):
    # Create workflow
    wf = tmp_path / "workflows"
    wf.mkdir()
    (wf / "test.workflow.md").write_text(SAMPLE_WORKFLOW)

    # Create broker
    bp = tmp_path / "broker_profiles"
    bp.mkdir()
    (bp / "simulated.broker.md").write_text(SAMPLE_BROKER.replace("test_broker", "simulated").replace("tastytrade", "simulated"))

    # Create universe
    up = tmp_path / "universes"
    up.mkdir()
    (up / "us_test.universe.md").write_text(SAMPLE_UNIVERSE)

    # Create risk
    rp = tmp_path / "risk_profiles"
    rp.mkdir()
    (rp / "moderate.risk.md").write_text(SAMPLE_RISK)

    plan = parse_workflow(wf / "test.workflow.md")
    plan = resolve_references(plan, tmp_path)

    assert plan.broker is not None
    assert plan.universe is not None
    assert plan.risk is not None
    assert len(plan.universe.tickers) == 4

def test_resolve_missing_reference(tmp_path):
    wf = tmp_path / "test.workflow.md"
    wf.write_text(SAMPLE_WORKFLOW)
    plan = parse_workflow(wf)
    plan = resolve_references(plan, tmp_path)  # no broker/universe/risk files exist
    assert plan.broker is None
    assert plan.universe is None
    assert plan.risk is None
