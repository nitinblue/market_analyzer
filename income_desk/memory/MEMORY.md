# Document Registry

> Last scanned: 2026-03-29

## File Types
- `*_info.md` — Static reference. Stable facts, rules, decisions.
- `*_intake.md` — Action inbox. Items flow through: NEW → IN_PROGRESS → DELIVERED → archived.

## Intake Documents (Claude drains these into ROADMAP)

| File | Staleness | Active Items | Last Reviewed |
|------|-----------|--------------|---------------|
| feedback_intake.md | FRESH | 4 | 2026-03-29 |
| bugs_intake.md | AGING | 1 | 2026-03-29 |
| features_intake.md | FRESH | 8 | 2026-03-29 |
| gaps_intake.md | AGING | 6 | 2026-03-29 |
| risks_intake.md | FRESH | 3 | 2026-03-29 |
| platform_intake.md | FRESH | 5 | 2026-03-29 |

## Info Documents (Stable reference)

| File | Last Updated |
|------|-------------|
| user_info.md | 2026-03-29 |
| references_info.md | 2026-03-29 |
| decisions_info.md | 2026-03-29 |
| dependencies_info.md | 2026-03-29 |
| learnings_info.md | 2026-03-29 |

## Project Docs (in repo)

| Doc | Type | Purpose |
|-----|------|---------|
| `README.md` | Living | The manual — update when features ship |
| `docs/project_roadmap.md` | Intake | THE delivery tracker — intake items flow here |
| `docs/project_architecture_living.md` | Living | System design — refresh after major changes |
| `docs/project_integration_living.md` | Living | APIs, contracts — refresh when APIs change |
| `docs/project_vision_info.md` | Info | Mission, philosophy — stable |

## Stats
- Memory files: 12 (6 info, 6 intake)
- Active intake items: 28
- Go-live readiness: US 20%, India 10%
- Key blockers to go-live: 5 (FB-001, FB-002, FB-003, GAP-001, GAP-002)

## HARD RULES (from user_info.md)
- NEVER show recommendations without verified broker connection
- ALWAYS show data trust factor on every output
- NEVER claim "ready" without go-live checklist with LIVE data
- Track convergence every session — readiness % must improve
