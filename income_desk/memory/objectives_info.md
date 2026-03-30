# Business Objectives

> Type: INFO | Last updated: 2026-03-29

## Objectives

| ID | Objective | Success Criteria | Priority |
|----|-----------|-----------------|----------|
| OBJ-1 | Go live US trading | All 15 workflows pass with LIVE TastyTrade data, data trust > 90%, zero simulated values in output | P0 |
| OBJ-2 | Go live India trading | All 15 workflows pass with LIVE Dhan data, lot sizes correct, zero simulated values | P0 |
| OBJ-3 | trader_md for external users | pip install + .workflow.md + .env.trading = working platform, no Python knowledge needed | P1 |
| OBJ-4 | Claude Skill distribution | Skill manifest published, NL-to-workflow working, onboarding < 5 minutes | P1 |
| OBJ-5 | 100K PyPI downloads | MCP server, REST API, community workflows, documentation site | P2 |

## Go-Live Checklist (OBJ-1 and OBJ-2)

| # | Check | US Status | India 2026-03-29 | India 2026-03-30 |
|---|-------|-----------|-------------------|-------------------|
| 1 | Broker connected (not simulated) | UNTESTED | PASS | PASS — Dhan connected, 0 errors |
| 2 | All 16 workflows execute without error | PASS (simulated) | PASS (garbage output) | PASS — 16/16 OK, no crashes |
| 3 | Data trust > 90% on all outputs | UNTESTED | FAIL — POP 1%, credits 0.15 | NEEDS RETEST — BUG-002 fixed, yfinance data flowing |
| 4 | No $0.00 prices in price_trade | UNTESTED | FAIL — current_price=0 | NEEDS RETEST — BUG-005 fix in progress |
| 5 | IV rank populated from broker (not None) | UNTESTED | PASS — IVR 21-62 | PASS — IVR from Dhan live |
| 6 | Ranked trades have real strikes from chain | UNTESTED | FAIL — estimation | PARTIAL — pricing regression 25/25 from chain, but harness workflow still uses estimation |
| 7 | Stress test uses live portfolio positions | UNTESTED | FAIL — DEMO | FAIL — still DEMO (no Dhan positions open) |
| 8 | No simulated data flagged anywhere in output | UNTESTED | FAIL — FRED, demo | IMPROVED — FRED suppressed, but demo positions still used in phases 4-7 |
| 9 | Gate scorecard passes with real data | UNTESTED | FAIL — rubber-stamp | NEEDS RETEST — BUG-005 fix in progress |
| 10 | Position sizing uses real account NLV/BP | PASS (TT connected) | FAIL — NLV=0 | NEEDS RETEST — BUG-011 fix delivered |

### India Go-Live Confidence Score: 35% (up from 20% on 2026-03-29)

**What improved (20% → 35%):**
- Broker connection clean, zero HTTP errors (was 22+ per run)
- yfinance .NS suffix fixed — India stock data now flows
- FRED noise eliminated for India market
- Phase ordering correct (context → snapshot → health → plan)
- Scan → rank pipeline wired correctly
- Pricing regression: 25/25 valid trades from real chain data
- Dhan NLV calculation fixed (needs live verification)
- Labels de-jargoned

**What blocks 35% → 70%:**
- BUG-003/004: POP and credits need retest with BUG-002 fix (likely fixed, needs confirmation)
- BUG-005: Gates must reject bad data (fix in progress)
- BUG-007: Harness still uses $5 wing width for India (pricing regression uses chain-based)
- Phases 4-7 use demo positions (no real positions to test with)
- Account NLV fix needs live verification

**What blocks 70% → 100%:**
- Real trades executed and monitored through full lifecycle
- POP calibration against actual outcomes
- Overnight risk tested with real overnight positions
- Stress test with realistic PnL% (BUG-010 fix in progress)
- 7 consecutive clean daily test runs

## Blockers to Objectives

| Blocker | Blocks | Intake Key | Status |
|---------|--------|-----------|--------|
| Broker not connected during testing | OBJ-1, OBJ-2 | FB-001 | OPEN |
| Data trust not displayed | OBJ-1, OBJ-2 | FB-002 | OPEN |
| Dhan rate limiting | OBJ-2 | GAP-001 | OPEN |
| Dhan token expiry | OBJ-2 | GAP-002 | OPEN |
| No go-live checklist enforcement | OBJ-1, OBJ-2 | FB-003 | OPEN |
| trader_md not tested end-to-end with LIVE broker | OBJ-1, OBJ-2, OBJ-3 | PLAT-007 | OPEN |
| trader/ not tested end-to-end with LIVE broker | OBJ-1, OBJ-2 | PLAT-008 | OPEN |
| Full pytest suite not verified for v2.0 | OBJ-3 | PLAT-009 | OPEN |
| Claude Skill not built | OBJ-4 | FEAT-001 | OPEN |
| MCP server not built | OBJ-5 | FEAT-002 | OPEN |

## v2.0 Release Checklist (must ALL pass before PyPI publish)

### trader_md (PLAT-007)

| # | Test | Status | How to run |
|---|------|--------|-----------|
| 1 | validate US workflow | UNTESTED | python -m income_desk.trader_md validate workflows/daily_us.workflow.md |
| 2 | validate India workflow | UNTESTED | python -m income_desk.trader_md validate workflows/daily_india.workflow.md |
| 3 | dry-run US workflow | UNTESTED | python -m income_desk.trader_md dry-run workflows/daily_us.workflow.md |
| 4 | dry-run India workflow | UNTESTED | python -m income_desk.trader_md dry-run workflows/daily_india.workflow.md |
| 5 | run US workflow (simulated) | UNTESTED | python -m income_desk.trader_md run workflows/daily_us.workflow.md |
| 6 | run India workflow (simulated) | UNTESTED | python -m income_desk.trader_md run workflows/daily_india.workflow.md |
| 7 | run US workflow (LIVE TastyTrade, market open) | UNTESTED | python -m income_desk.trader_md run workflows/daily_us.workflow.md (during market hours) |
| 8 | run India workflow (LIVE Dhan, market open) | UNTESTED | python -m income_desk.trader_md run workflows/daily_india.workflow.md (during market hours) |
| 9 | --set override changes behavior | UNTESTED | python -m income_desk.trader_md run ... --set min_pop=0.90 |
| 10 | --report generates markdown file | UNTESTED | python -m income_desk.trader_md run ... --report /tmp/test.md |
| 11 | benchmarking workflow runs | UNTESTED | python -m income_desk.trader_md run workflows/benchmarking.workflow.md |
| 12 | 0 FAILED steps in summary | UNTESTED | Check execution summary |

### trader/ Python path (PLAT-008)

| # | Test | Status | How to run |
|---|------|--------|-----------|
| 1 | US all phases (simulated) | UNTESTED | python -m income_desk.trader --all --market=US |
| 2 | India all phases (simulated) | UNTESTED | python -m income_desk.trader --all --market=India |
| 3 | US all phases (LIVE TastyTrade, market open) | UNTESTED | python -m income_desk.trader --all --market=US (during market hours) |
| 4 | India all phases (LIVE Dhan, market open) | UNTESTED | python -m income_desk.trader --all --market=India (during market hours) |
| 5 | 15/15 workflows PASS | UNTESTED | Check harness summary |
| 6 | Data trust displayed on every output | UNTESTED | Visual inspection |
| 7 | No simulated data presented as real | UNTESTED | Visual inspection during LIVE run |

### Full test suite (PLAT-009)

| # | Test | Status | How to run |
|---|------|--------|-----------|
| 1 | All unit tests pass | UNTESTED | python -m pytest tests/ -x -q -m "not integration" |
| 2 | trader_md parser tests (13) | UNTESTED | python -m pytest tests/test_trader_md_parser.py -v |
| 3 | trader_md full tests (83) | UNTESTED | python -m pytest tests/test_trader_md_full.py -v -m "not slow" |
| 4 | trader_md runner tests (25) | UNTESTED | python -m pytest tests/test_trader_md_runner.py -v |
| 5 | benchmarking tests (23) | UNTESTED | python -m pytest tests/test_benchmarking.py tests/test_benchmarking_workflow.py -v |
| 6 | scenario parser tests (12) | UNTESTED | python -m pytest tests/test_scenario_parser.py -v |
| 7 | 0 failures total | UNTESTED | Full suite green |
