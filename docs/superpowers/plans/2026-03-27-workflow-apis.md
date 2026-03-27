# Workflow APIs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build 14 workflow APIs that give eTrading single-function-call access to every trading operation, with internal rate limiting and batch data fetching.

**Architecture:** Each workflow is a pure function taking a Pydantic request + MarketAnalyzer, returning a Pydantic response. Workflows compose existing services — no new business logic. Shared types in `_types.py`.

**Tech Stack:** Pydantic models, existing income_desk services, no new dependencies.

---

### Task 1: Shared types and package scaffold

**Files:**
- Create: `income_desk/workflow/__init__.py`
- Create: `income_desk/workflow/_types.py`

- [ ] Create `_types.py` with `WorkflowResponse` base, `TickerRegime`, `TradeProposal`, `PositionStatus`, `BlockedTrade` shared models
- [ ] Create `__init__.py` that will export all workflow functions
- [ ] Verify import: `from income_desk.workflow import *`

### Task 2: market_snapshot — batch data fetching

**Files:**
- Create: `income_desk/workflow/market_snapshot.py`
- Test: `tests/test_workflow_snapshot.py`

- [ ] Define `SnapshotRequest(tickers, include_chains, include_regime)` and `MarketSnapshot` response
- [ ] Implement `snapshot_market()`: batch prices via single ticker_data call, sequential chains with throttle, regime detect
- [ ] Test with simulated data
- [ ] Test with live Dhan

### Task 3: scan_universe

**Files:**
- Create: `income_desk/workflow/scan_universe.py`

- [ ] Define `ScanRequest(tickers, market, min_score)` and `ScanResponse`
- [ ] Implement: calls `ma.screening.scan()` + regime filter, returns candidates with regime labels

### Task 4: rank_opportunities

**Files:**
- Create: `income_desk/workflow/rank_opportunities.py`

- [ ] Define `RankRequest(tickers, capital, market, risk_tolerance, iv_rank_map, skip_intraday)` and `RankResponse`
- [ ] Implement: regime filter R4, call `ma.ranking.rank()`, attach POP + sizing to each trade, return sorted proposals + blocked

### Task 5: validate_trade

**Files:**
- Create: `income_desk/workflow/validate_trade.py`

- [ ] Define `ValidateRequest(trade_spec, regime_id, capital, ...)` and `ValidateResponse`
- [ ] Implement: calls `run_daily_checks()`, returns gate results + is_ready

### Task 6: size_position

**Files:**
- Create: `income_desk/workflow/size_position.py`

- [ ] Define `SizeRequest(trade_spec, capital, regime_id, pop_pct)` and `SizeResponse`
- [ ] Implement: calls `compute_position_size()`, returns contracts + risk metrics

### Task 7: price_trade

**Files:**
- Create: `income_desk/workflow/price_trade.py`

- [ ] Define `PriceRequest(trade_spec, ticker)` and `PriceResponse`
- [ ] Implement: calls `ma.market_data.get_quotes()`, computes net credit/debit, max entry price, spread quality

### Task 8: monitor_positions

**Files:**
- Create: `income_desk/workflow/monitor_positions.py`

- [ ] Define `MonitorRequest(positions: list[OpenPosition])` and `MonitorResponse`
- [ ] Implement: for each position call `monitor_exit_conditions()`, `compute_regime_stop()`, `compute_remaining_theta_value()`

### Task 9: adjust_position

**Files:**
- Create: `income_desk/workflow/adjust_position.py`

- [ ] Define `AdjustRequest(position, regime_id, technicals)` and `AdjustResponse`
- [ ] Implement: calls `ma.adjustment.recommend_action()`

### Task 10: overnight_risk

**Files:**
- Create: `income_desk/workflow/overnight_risk.py`

- [ ] Define `OvernightRiskRequest(positions)` and `OvernightRiskResponse`
- [ ] Implement: calls `assess_overnight_risk()` per position, aggregates

### Task 11: expiry_day

**Files:**
- Create: `income_desk/workflow/expiry_day.py`

- [ ] Define `ExpiryDayRequest(positions, market)` and `ExpiryDayResponse`
- [ ] Implement: identifies expiry-day positions, urgency escalation, close-before-close flags

### Task 12: portfolio_health

**Files:**
- Create: `income_desk/workflow/portfolio_health.py`

- [ ] Define `HealthRequest(tickers, positions, capital)` and `HealthResponse`
- [ ] Implement: crash sentinel, regime distribution, risk budget, data trust

### Task 13: profitability_check

**Files:**
- Create: `income_desk/workflow/profitability_check.py`

- [ ] Define `ProfitabilityRequest(tickers, capital, market)` and `ProfitabilityResponse`
- [ ] Implement: extract logic from `scripts/daily_profitability_test.py` into callable workflow

### Task 14: daily_plan (orchestrator)

**Files:**
- Create: `income_desk/workflow/daily_plan.py`

- [ ] Define `DailyPlanRequest(tickers, capital, market, risk_tolerance)` and `DailyPlanResponse`
- [ ] Implement: composes scan → rank → validate → size into single call

### Task 15: daily_report

**Files:**
- Create: `income_desk/workflow/daily_report.py`

- [ ] Define `ReportRequest(trades_today, positions, regime_summary)` and `ReportResponse`
- [ ] Implement: summary stats, P&L rollup, blocked trade reasons

### Task 16: Wire exports and publish to collab

**Files:**
- Modify: `income_desk/workflow/__init__.py`
- Modify: `income_desk/__init__.py`
- Create: `.collab/FEEDBACK_workflow_apis.md`

- [ ] Export all 14 workflow functions from `__init__.py`
- [ ] Add workflow imports to top-level `income_desk/__init__.py`
- [ ] Write collab FEEDBACK with usage examples for eTrading
- [ ] Run full test suite to verify no regressions

### Task 17: Integration test

**Files:**
- Create: `tests/test_workflow_integration.py`

- [ ] Test full daily_plan workflow with simulated data
- [ ] Test market_snapshot with live Dhan
- [ ] Test rank_opportunities produces income trades (not equity)
- [ ] Verify all 14 workflows importable and callable
