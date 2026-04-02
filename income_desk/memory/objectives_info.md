# Business Objectives

> Type: INFO | Last updated: 2026-04-01

## Objectives

| ID | Objective | Success Criteria | Priority |
|----|-----------|-----------------|----------|
| OBJ-1 | Go live US trading | All 15 workflows pass with LIVE TastyTrade data, data trust > 90%, zero simulated values in output | P0 |
| OBJ-2 | Go live India trading | All 15 workflows pass with LIVE Dhan data, lot sizes correct, zero simulated values | P0 |
| OBJ-3 | trader_md for external users | pip install + .workflow.md + .env.trading = working platform, no Python knowledge needed | P1 |
| OBJ-4 | Claude Skill distribution | Skill manifest published, NL-to-workflow working, onboarding < 5 minutes | P1 |
| OBJ-5 | 100K PyPI downloads | MCP server, REST API, community workflows, documentation site | P2 |

## Go-Live Checklist (OBJ-1 and OBJ-2)

| # | Check | US Status | India Status | Notes (2026-04-01) |
|---|-------|-----------|--------------|---------------------|
| 1 | Broker connected (not simulated) | UNTESTED | PASS | Dhan connected, 0 HTTP errors |
| 2 | All 16 workflows execute without error | PASS (simulated) | PASS | 16/16 OK, real data flowing |
| 3 | Data trust > 90% on all outputs | UNTESTED | PASS | POP fixed (was 0%, now 53-70%), iv_30_day wired, chain-first credits |
| 4 | No $0.00 prices in price_trade | UNTESTED | PASS | current_price from Dhan, gates reject price=0 |
| 5 | IV rank populated from broker (not None) | UNTESTED | PASS | IVR from Dhan live, iv_30_day flows to POP |
| 6 | Ranked trades have real strikes from chain | UNTESTED | PASS | ChainBundle architecture, degenerate guards |
| 7 | Stress test uses live portfolio positions | UNTESTED | FAIL | No Dhan positions open — needs real trades first |
| 8 | No simulated data flagged anywhere in output | UNTESTED | PARTIAL | Phases 1-3 real, phases 4-7 still demo |
| 9 | Gate scorecard passes with real data | UNTESTED | PASS | TradeValidator with structure-aware rules |
| 10 | Position sizing uses real account NLV/BP | UNTESTED | PARTIAL | Capital warning added, Dhan NLV fix delivered, needs live retest |

### Go-Live Confidence: India 60% (was 45%), US needs live test

**April 1 fixes:** POP 0%→53-70% (d18a63b), iv_30_day wired (7295609), ratio 3 legs (10b44f9), degenerate guards (cba7788), capital warning (91fcf2d), eTrading exports (adc12af)

**Blocks to 100%:** Live broker verification (both markets), real trades for phases 4-7, POP calibration

## Blockers to Objectives

| Blocker | Blocks | Intake Key | Status |
|---------|--------|-----------|--------|
| Broker not connected during testing | OBJ-1, OBJ-2 | FB-001 | OPEN — top priority for April 2 |
| Data trust not displayed | OBJ-1, OBJ-2 | FB-002 | OPEN |
| Dhan rate limiting | OBJ-2 | GAP-001 | OPEN |
| Dhan token expiry | OBJ-2 | GAP-002 | OPEN (Nitin) |
| No go-live checklist enforcement | OBJ-1, OBJ-2 | FB-003 | OPEN |
| trader/ not tested end-to-end with LIVE broker | OBJ-1, OBJ-2 | PLAT-008 | OPEN — April 2 live test |
| POP broken for strangles | OBJ-1, OBJ-2 | BUG-003 | CLOSED (d18a63b) |
| Credits nonsensical | OBJ-1, OBJ-2 | BUG-004 | CLOSED (chain-first) |
| Gates rubber-stamp bad input | OBJ-1, OBJ-2 | BUG-005 | CLOSED (TradeValidator) |
| Ranking uses estimated strikes | OBJ-1, OBJ-2 | FB-013 | CLOSED (ChainBundle) |

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
