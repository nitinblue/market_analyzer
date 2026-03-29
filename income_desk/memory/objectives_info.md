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

| # | Check | US Status | India Status |
|---|-------|-----------|-------------|
| 1 | Broker connected (not simulated) | UNTESTED | UNTESTED |
| 2 | All 15 workflows execute without error | PASS (simulated) | PASS (simulated) |
| 3 | Data trust > 90% on all outputs | UNTESTED | UNTESTED |
| 4 | No $0.00 prices in price_trade | UNTESTED | UNTESTED |
| 5 | IV rank populated from broker (not None) | UNTESTED | UNTESTED |
| 6 | Ranked trades have real strikes from chain | UNTESTED | UNTESTED |
| 7 | Stress test uses live portfolio positions | UNTESTED | UNTESTED |
| 8 | No simulated data flagged anywhere in output | UNTESTED | UNTESTED |
| 9 | Gate scorecard passes with real data | UNTESTED | UNTESTED |
| 10 | Position sizing uses real account NLV/BP | PASS (TT connected) | UNTESTED |

## Blockers to Objectives

| Blocker | Blocks | Intake Key | Status |
|---------|--------|-----------|--------|
| Broker not connected during testing | OBJ-1, OBJ-2 | FB-001 | OPEN |
| Data trust not displayed | OBJ-1, OBJ-2 | FB-002 | OPEN |
| Dhan rate limiting | OBJ-2 | GAP-001 | OPEN |
| Dhan token expiry | OBJ-2 | GAP-002 | OPEN |
| No go-live checklist enforcement | OBJ-1, OBJ-2 | FB-003 | OPEN |
| Claude Skill not built | OBJ-4 | FEAT-001 | OPEN |
| MCP server not built | OBJ-5 | FEAT-002 | OPEN |
