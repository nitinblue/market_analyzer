# Project Retrospection & Learnings

> Type: INFO | Last updated: 2026-03-29

## Critical Failures & Lessons

### F1: Recommending trades without broker connection
**What happened:** During trading hours, showed recommendations from simulated data. User discovered later.
**Root cause:** No mandatory broker check. Simulated data indistinguishable from real.
**Mitigation:** FB-001, FB-002 — HALT if no broker, always show data trust.
**Go-to-green:** Every output: "LIVE (TastyTrade)" or "SIMULATED — not tradeable". No recommendations if simulated.
**Status:** OPEN

### F2: Claiming "ready to go live" 10+ times without evidence
**What happened:** Each time basic issues found — $0 prices, missing IV, wrong fields, Unicode crashes.
**Root cause:** No objective checklist. "Ready" based on code inspection, not live proof.
**Mitigation:** FB-003 — 10-check go-live checklist run with LIVE broker.
**Go-to-green:** Readiness must reach 100% on both markets. Currently US 20%, India 10%.
**Status:** OPEN

### F3: Going in circles — technical churn, no business progress
**What happened:** 28 items created, 0 closed. Features built but readiness only 20%/10%.
**Root cause:** Building features (fun) instead of fixing blockers (hard). No convergence tracking.
**Mitigation:** Skin in the Game score + convergence % + going-in-circles detector.
**Go-to-green:** Close blockers first. Readiness must improve each session.
**Status:** Score is 32/100 (WEAK). Detector live.

### F4-F6: Technical bugs (RESOLVED)
- **F4:** FRED EQUITPC 404 — fallback to PCRATIOPCE. DONE.
- **F5:** DXLink warnings flooding — suppressed during setup. DONE.
- **F6:** Windows Unicode crashes — ASCII fallback. DONE.

## Patterns to Watch For

| Pattern | Signal | Response |
|---------|--------|----------|
| Simulated data shown as real | No "SIMULATED" banner | HALT — never show without source |
| Claiming ready without checklist | Readiness < 100% | Run checklist, show score |
| Features before blockers | Convergence stagnant | Stop features, fix blockers |
| New items > closed items | Going in circles | Prioritize closing over opening |
| Field name mismatch | Test against real Pydantic models | Verify field names before using |
| Hardcoded series/URLs | Single point of failure | Always add fallback chain |
| Untested with live broker | False confidence | Never claim working without live test |

## Go-to-Green Plan

| # | Action | Blocks | Status | Target |
|---|--------|--------|--------|--------|
| 1 | FB-001: Mandatory broker check before output | OBJ-1, OBJ-2 | OPEN | HALT if not connected |
| 2 | FB-002: Data trust on every output | OBJ-1, OBJ-2 | OPEN | Source always visible |
| 3 | FB-003: Go-live checklist enforcement | OBJ-1, OBJ-2 | OPEN | 10/10 with LIVE data |
| 4 | GAP-001: Dhan rate throttle | OBJ-2 | OPEN | 1 req/3s in option_chain |
| 5 | GAP-002: Dhan token refresh | OBJ-2 | OPEN | Auto-detect expired |
| 6 | Run checklist with TastyTrade LIVE | OBJ-1 | 20% | 100% |
| 7 | Run checklist with Dhan LIVE | OBJ-2 | 10% | 100% |

## Self-Correction Protocol (when going in circles)

When `project_status.py` shows "Going in Circles: YES" or Skin in the Game < 50:

### Step 1: Stop building features
Features are the easy, fun work. Blockers are the hard, unglamorous work that moves readiness %.
If readiness hasn't improved, STOP all feature work. Every commit must resolve a blocker or close an item.

### Step 2: Pick the blocker that unblocks the most
FB-001 (broker check) blocks BOTH OBJ-1 and OBJ-2. Fix that before GAP-001 (only blocks OBJ-2).
Sort blockers by: how many objectives they block, then by age.

### Step 3: Prove it works with LIVE data
Don't mark a blocker resolved until tested with the real broker during market hours.
"It works with simulated data" is not evidence. That's exactly how F1 and F2 happened.

### Step 4: Close items, don't open more
If open items > 20 and closed items = 0, the system is accumulating debt.
Every session must close at least 1 item. If nothing can be closed, ask: why not?

### Step 5: Update readiness checklist honestly
After fixing a blocker, re-run the go-live checklist. If the check now passes with LIVE data, update objectives_info.md.
If it doesn't actually pass, don't mark it. Honesty > progress.

### Step 6: Report convergence
Start of next session: "Last session readiness was 20%/10%. This session: 30%/20%. Converging."
If not converging: "Readiness unchanged at 20%/10%. Going in circles. Switching to blocker-only mode."

## Technical Learnings

- FRED EQUITPC discontinued — always try fallback series
- Windows cp1252 can't handle Unicode — use ASCII
- DXLink probes warn when market closed — suppress during setup
- .env must be loaded explicitly (dotenv.load_dotenv())
- GitHub Actions OIDC needs PyPI-side config — use twine + API token
- Scheduled agents can't access local .env — simulated data only
- Gmail MCP not available for trigger connectors (2026-03-29)
- TradeProposal doesn't carry regime_id — hardcode default
