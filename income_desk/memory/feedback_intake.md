# Feedback Intake

> Type: INTAKE | Last reviewed: 2026-03-29 | Staleness: FRESH

## Active Items

| Key | Item | Added | Last Actioned | Status | Assignee | Next Action | Blockers | Delivered To |
|-----|------|-------|---------------|--------|----------|-------------|----------|--------------|
| FB-001 | Stock recommendations given without broker connection — user discovered later | 2026-03-29 | 2026-03-29 | OPEN | Claude | Add mandatory broker connection check before ANY trading workflow output. If not connected, HALT with clear message, never show recommendations | — | — |
| FB-002 | Data trust factor not shown prominently — user can't tell if data is real or simulated | 2026-03-29 | 2026-03-29 | OPEN | Claude | Every workflow output must show data source + trust level at the top. "SIMULATED" or "LIVE (TastyTrade)" — impossible to miss | — | — |
| FB-003 | "Ready to go live" claimed 10+ times but basic issues keep appearing | 2026-03-29 | 2026-03-29 | OPEN | Claude | Create go-live checklist: broker connected, all 15 workflows pass with LIVE data, data trust > 90%, no simulated values in output, zero STALE intake items. Never claim ready without running this checklist | — | — |
| FB-004 | No convergence tracking on product readiness — user can't see if quality is improving | 2026-03-29 | 2026-03-29 | OPEN | Claude | Add readiness score to project_status.py: track % of go-live checklist passing over time. Show trend: "Readiness: 72% (up from 65% last week)" | — | — |

## Archive
(Previous feedback captured in user_info.md and decisions_info.md during consolidation)
