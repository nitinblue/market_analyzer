# Change Request: trader_md Engine Migration to CoTrader

> Date: 2026-04-04 | Priority: CRITICAL | Status: DONE

## What Changed

The `trader_md` orchestration engine (parser, runner, gate evaluator, binding resolver) has been migrated from income-desk to CoTrader (eTrading).

### Moved to ET (trading_cotrader/trader_md/)
- `runner.py` — TradingRunner, ExecutionContext, ExecutionReport, StepResult
- `parser.py` — parse_workflow, parse_broker, parse_universe, parse_risk, resolve_references
- `models.py` — Gate, Step, Phase, WorkflowPlan, BrokerProfile, UniverseSpec, RiskProfile
- `__main__.py` — CLI entry point
- All MD content: workflows/, broker_profiles/, risk_profiles/, universes/, scenarios/
- All tests: test_trader_md_full.py, test_trader_md_parser.py, test_trader_md_runner.py

### Kept in ID (income_desk/trader_md/)
- `__init__.py` — stub explaining the move
- `specs/` — reference documentation for MD file formats (workflow-spec, binding-spec, gate-spec, etc.)

### Why
- trader_md is the commercial orchestration layer — it's how CoTrader manufactures and sells trading workflows
- income-desk remains the open-source engine (pure functions, MIT)
- The orchestration IP (how functions are chained, gated, and reported) is CoTrader's product

## Impact on ID

- `income_desk.trader_md.runner` no longer importable from ID
- `income_desk.trader_md.parser` no longer importable from ID
- `income_desk.trader_md.models` no longer importable from ID
- `python -m income_desk.trader_md` no longer works from ID
- `test_benchmarking_workflow.py` — one test patched to skip (was importing trader_md.parser)
- Spec files remain for documentation reference

## No Impact On

- All 90+ pure functions — unchanged
- All 15 workflow API signatures — unchanged
- `python -m income_desk.trader` harness — unchanged (this is the demo, stays in ID)
- All broker adapters, simulated data, scenarios engine — unchanged
- PyPI package — trader_md was never part of the published distribution (it was a development module)

## Requests from ET

### R1: api_ops_reports.py Pydantic Models — Optional[float]

The following models need `Optional[float]` instead of strict `float` for null-over-fake compliance:
- `ShadowRecord.score` → `Optional[float] = None`
- `BookedRecord.score` → `Optional[float] = None`
- `ClosedTradeRecord.total_pnl` → `Optional[float] = None`

This allows ET to pass `None` for missing data instead of `0.0`.

### R2: Boundary Fixes (Future)

These ET containers currently calculate values that ID should provide:
- `position_container.py` computes PnL: `(current - entry) * qty * multiplier` → should use `compute_trade_pnl()`
- `trade_container.py` aggregates Greeks → should use `aggregate_portfolio_greeks()`

ET will file separate requests when ready to migrate these.
