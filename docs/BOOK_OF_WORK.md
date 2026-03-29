# income_desk — Book of Work

**Last updated:** 2026-03-29

The complete roadmap from current state to production-ready MD-driven trading platform.

---

## What's Done

### Foundation (v1.1.1 — published to PyPI)

| Component | Status | Location |
|-----------|--------|----------|
| 15 workflow APIs | Done | `income_desk/workflow/` |
| MarketAnalyzer engine | Done | `income_desk/service/` |
| Broker integrations (TastyTrade, Dhan, 4 more) | Done | `income_desk/broker/` |
| Simulated data + 7 presets | Done | `income_desk/adapters/simulated.py` |
| Regime detection (HMM, 4-state) | Done | `income_desk/hmm/` |
| 18 scenario definitions (Python) | Done | `income_desk/scenarios/definitions.py` |
| Python trader (harness) | Done | `income_desk/trader/` |
| Benchmarking framework (calibration APIs) | Done | `income_desk/benchmarking/` |
| GitHub Actions CI + PyPI publish | Done | `.github/workflows/` |
| Scheduled daily harness (US + India) | Done | Remote triggers on claude.ai |

### MD Foundation (v2.0 in progress)

| Component | Status | Location |
|-----------|--------|----------|
| Scenario MD format (.scenario.md) | Done | `income_desk/trader_md/scenarios/` (18 files) |
| Scenario parser | Done | `income_desk/scenarios/parser.py` |
| Workflow MD format (.workflow.md) | Done | `income_desk/trader_md/workflows/` (2 files) |
| Universe MD format (.universe.md) | Done | `income_desk/trader_md/universes/` (2 files) |
| Risk profile MD format (.risk.md) | Done | `income_desk/trader_md/risk_profiles/` (3 files) |
| Broker profile MD format (.broker.md) | Done | `income_desk/trader_md/broker_profiles/` (3 files) |
| MD parser (all 5 types) | Done | `income_desk/trader_md/parser.py` |
| MD models (WorkflowPlan, Phase, Step, Gate) | Done | `income_desk/trader_md/models.py` |
| MD runner (TradingRunner) | Done | `income_desk/trader_md/runner.py` |
| MD CLI (run, validate, dry-run) | Done | `income_desk/trader_md/__main__.py` |
| README v2 section | Done | `README.md` |

---

## Phase 1: Testing & Hardening

### 1.1 Automated Test Suite for trader_md

| Test | What it validates | Priority |
|------|-------------------|----------|
| Parser: workflow parsing | Phases, steps, gates, bindings extracted correctly | P0 |
| Parser: broker/universe/risk parsing | All fields mapped, defaults applied | P0 |
| Parser: reference resolution | Broker/universe/risk files found and loaded | P0 |
| Parser: malformed files | Graceful errors on bad YAML, missing frontmatter | P0 |
| Runner: binding resolution | $universe, $capital, $risk.field, $phase1.output, indexed access | P0 |
| Runner: literal parsing | "[]" -> list, "true" -> bool, "42" -> int, "1.5" -> float | P0 |
| Runner: gate evaluation | Expressions evaluate correctly, on_fail actions work | P0 |
| Runner: full US workflow | All phases execute, 12+ OK, 0 FAILED | P0 |
| Runner: full India workflow | All phases execute against india_fno universe | P0 |
| Runner: validate command | Reports issues for missing refs, bad workflows | P1 |
| Runner: dry-run command | Shows correct plan without API calls | P1 |
| Runner: interactive mode | Pause/skip/quit between steps | P2 |

### 1.2 Behavior Change Tests

| Test | What it validates | Priority |
|------|-------------------|----------|
| Change risk min_pop → fewer proposals | MD edit changes workflow behavior | P0 |
| Change universe tickers → different scan results | Universe file drives ticker selection | P0 |
| Switch broker to simulated → no connection attempt | Broker profile controls connection | P0 |
| Add stricter gate → step gets skipped | Gate expressions control flow | P0 |
| Change risk regime_rules → different strategy filter | Regime rules propagate correctly | P1 |
| Change broker fallback → different fallback behavior | Fallback chain works per broker profile | P1 |

### 1.3 Parity Tests (Python vs MD)

| Test | What it validates | Priority |
|------|-------------------|----------|
| Same tickers → same regime detection | Engine produces identical results | P0 |
| Same tickers → same ranking order | Ranking is deterministic | P0 |
| Same scenario → same stress results | Stress test produces same P&L | P1 |
| Compare harness summary vs MD summary | Same workflows, comparable outputs | P1 |

### 1.4 Error Handling Tests

| Test | What it validates | Priority |
|------|-------------------|----------|
| Bad broker ref → graceful fallback | Runner doesn't crash | P0 |
| Bad universe ref → clear error | Reports which file is missing | P0 |
| Workflow step fails → continues to next | Error isolation per step | P0 |
| HALT gate → stops entire workflow | Halt propagates correctly | P0 |
| Missing .env.trading → falls back to simulated | Credential failure is not fatal | P0 |
| Network timeout in workflow call → error reported | Timeout handling per step | P1 |

---

## Phase 2: Benchmarking Workflow

### 2.1 Benchmarking as a Workflow Step

A single benchmarking flow callable from both eTrading (Python) and trader_md (MD):

```markdown
# benchmarking.workflow.md
---
name: benchmarking_report
description: Generate calibration report from trade prediction/outcome data
---

## Phase 1: Data Collection

### Step: Load Predictions
workflow: load_predictions
inputs:
  source: $data_source        # "file", "database", "api"
  path: $predictions_path     # CSV/JSON path or API endpoint
outputs:
  predictions: $result.predictions

### Step: Load Outcomes
workflow: load_outcomes
inputs:
  source: $data_source
  path: $outcomes_path
outputs:
  outcomes: $result.outcomes

## Phase 2: Calibration

### Step: POP Calibration
workflow: calibrate_pop
inputs:
  predictions: $phase1.predictions
  outcomes: $phase1.outcomes
outputs:
  pop_buckets: $result.buckets
  pop_rmse: $result.rmse
gate:
  - len(pop_buckets) > 0
on_fail: SKIP "Not enough trades for POP calibration"

### Step: Regime Accuracy
workflow: regime_accuracy
inputs:
  predictions: $phase1.predictions
  outcomes: $phase1.outcomes
outputs:
  regime_report: $result

### Step: Score Correlation
workflow: score_vs_outcome
inputs:
  predictions: $phase1.predictions
  outcomes: $phase1.outcomes
outputs:
  correlation: $result.correlation

## Phase 3: Report

### Step: Generate Report
workflow: generate_calibration_report
inputs:
  predictions: $phase1.predictions
  outcomes: $phase1.outcomes
  period: $period
outputs:
  report: $result

### Step: Format Report
workflow: format_calibration_report
inputs:
  report: $phase3.report
```

### 2.2 Benchmarking API Additions

| API | What it does | Location |
|-----|-------------|----------|
| `load_predictions(source, path)` | Load PredictionRecord list from file/API | `income_desk/benchmarking/` |
| `load_outcomes(source, path)` | Load OutcomeRecord list from file/API | `income_desk/benchmarking/` |
| Wire existing calibration functions as workflows | Make them callable from runner | `income_desk/workflow/` |

### 2.3 eTrading Integration

eTrading calls the same flow programmatically:

```python
from income_desk.benchmarking import generate_calibration_report
report = generate_calibration_report(predictions, outcomes, period="2026-03")
```

Or via MD:

```bash
python -m income_desk.trader_md run benchmarking.workflow.md \
  --set data_source=file \
  --set predictions_path=data/predictions.csv \
  --set outcomes_path=data/outcomes.csv
```

**Single flow, two access methods.** eTrading doesn't need to know about the MD format. MD users don't need to know Python.

---

## Phase 3: Format Specifications

Publish formal specs so others can build parsers/tools for these formats.

| Spec | What it documents | Priority |
|------|-------------------|----------|
| `workflow-spec.md` | .workflow.md format: frontmatter, phases, steps, gates, bindings | P0 |
| `scenario-spec.md` | .scenario.md format: frontmatter, factor shocks, IV shift, sections | P0 |
| `universe-spec.md` | .universe.md format: frontmatter, ticker lists | P1 |
| `risk-profile-spec.md` | .risk.md format: all fields, regime rules | P1 |
| `broker-profile-spec.md` | .broker.md format: connection config, credential sources | P1 |
| `binding-spec.md` | Variable binding language: $universe, $result.*, $phaseN.*, indexed access | P0 |
| `gate-spec.md` | Gate expression syntax, on_fail actions | P0 |

---

## Phase 4: Runner Enhancements

| Feature | What it enables | Priority |
|---------|----------------|----------|
| `--set key=value` CLI args | Override MD values from command line | P0 |
| Execution timing per step | Show how long each workflow call takes | Done |
| Report export (MD file) | Save execution results as markdown report | P1 |
| Scenario-triggered workflows | `trigger_scenario: black_monday` → auto-run crash playbook | P1 |
| Workflow composition | `import: shared/pre_market.workflow.md` → reuse phases across workflows | P2 |
| Conditional phases | `if: $phase1.pulse == "BLUE"` → skip/include phases based on state | P2 |
| Parallel step execution | Run independent steps concurrently | P3 |
| Formula definition language | Express mathematical relationships in scenarios | P3 |

---

## Phase 5: Distribution

### 5.1 Claude Skill

```markdown
# .claude/skills/income-desk-trader.md
---
name: income-desk-trader
description: Generate and execute trading strategies using markdown
---

When user describes a trading strategy:
1. Generate .workflow.md from description
2. Generate supporting .risk.md, .universe.md files
3. Validate: python -m income_desk.trader_md validate <workflow>
4. Dry-run: python -m income_desk.trader_md dry-run <workflow>
5. Execute: python -m income_desk.trader_md run <workflow>
```

### 5.2 Template Library

Starter templates that users copy and customize:

| Template | Description |
|----------|-------------|
| `templates/daily_income_us.workflow.md` | US theta harvesting (SPY, QQQ, IWM) |
| `templates/daily_income_india.workflow.md` | India F&O income (NIFTY, BANKNIFTY) |
| `templates/zero_dte.workflow.md` | 0DTE same-day plays |
| `templates/wheel.workflow.md` | Cash-secured puts → covered calls |
| `templates/crash_response.workflow.md` | Emergency playbook when sentinel is RED |
| `templates/earnings.workflow.md` | Pre/post earnings volatility plays |
| `templates/moderate.risk.md` | Standard income trader risk profile |
| `templates/us_large_cap.universe.md` | S&P 500 components + ETFs |

### 5.3 PyPI v2.0 Release

```bash
pip install income-desk==2.0.0
```

Includes: engine + trader + trader_md + scenarios + benchmarking + templates

---

## Phase 6: Advanced Features (Future)

| Feature | Description | Depends On |
|---------|-------------|-----------|
| Backtesting engine | Run workflow against historical dates + scenarios | Phase 4 (--set) |
| Performance dashboard | HTML report from benchmarking data | Phase 2 |
| Strategy comparison | Diff two workflows against same scenario | Phase 4 |
| Multi-desk orchestration | Run multiple workflows, aggregate risk | Phase 4 (composition) |
| Natural language → workflow | "I want iron condors on SPY" → .workflow.md | Phase 5 (skill) |
| Scenario authoring | Describe event in English → .scenario.md | Phase 5 (skill) |
| Integration with scenarios library | Import from `C:\Users\nitin\PythonProjects\scenarios` | External dependency |
| Real-time monitoring workflow | monitor.workflow.md runs every 5 minutes | Phase 4 (conditional) |
| Portfolio-aware workflows | Load real positions from broker for phases 4-5 | Runner enhancement |

---

## Implementation Priority

### Now (this session / next session)
- [ ] Phase 1: Automated test suite (P0 tests)
- [ ] Phase 2.2: Wire benchmarking as workflow-callable APIs

### Next sprint
- [ ] Phase 1: Behavior change tests + parity tests
- [ ] Phase 2.1: Benchmarking workflow MD file
- [ ] Phase 3: Core format specs (workflow, scenario, binding, gate)
- [ ] Phase 4: `--set` CLI args

### Before v2.0 release
- [ ] Phase 1: All P0 + P1 tests green
- [ ] Phase 3: All specs published
- [ ] Phase 4: Report export
- [ ] Phase 5.2: Template library
- [ ] Phase 5.3: PyPI v2.0

### Post-release
- [ ] Phase 5.1: Claude Skill
- [ ] Phase 4: Workflow composition, conditional phases
- [ ] Phase 6: Backtesting, performance dashboard, NL → workflow
