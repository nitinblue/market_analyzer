---
name: project-management
description: Use at session start for ANY project with intake docs or objectives. Run project_status.py, report KPIs (Skin in the Game, Convergence, Going in Circles), close blockers before features. MANDATORY before any work.
---

# Project Management System

## File Types
Every managed document uses one of three suffixes:
- `*_info.md` — Static reference. Stable facts, rules, decisions. No action tracking.
- `*_intake.md` — Action inbox. Items flow through: OPEN -> IN_PROGRESS -> CLOSED -> archived.
- `*_living.md` — Content-freshness tracked documents in docs/. Refresh after major changes.

## Where Files Live

**ALL memory files live IN THE REPO** — not in ~/.claude/projects/. This ensures:
- Other contributors can see objectives, blockers, learnings
- Git tracks changes to intake items
- No duplication between ~/.claude/ and repo

```
<project_root>/
  <package_name>/memory/       <- 11 memory files + MEMORY.md
  docs/                        <- project docs (roadmap, architecture, etc.)
  scripts/project_status.py    <- dashboard script
```

In `~/.claude/projects/.../memory/`, keep ONLY a pointer:
```markdown
# Memory files are in the repo
All memory files live at `<package>/memory/` in the project repo.
Read from there, not from this directory.
```

**user_info.md** lives at `~/.claude/user_info.md` (user-level, shared across all projects, never in repo).

## First Session Setup

If `<package>/memory/MEMORY.md` does not exist, Claude MUST create the full structure:
1. Create `<package>/memory/` directory
2. Create all 10 memory files (empty templates with headers)
3. Create `MEMORY.md` registry
4. Copy `scripts/project_status.py` from the skill template or income_desk reference
5. Ask user for business objectives to populate `objectives_info.md`

This happens automatically — user does not create files manually.

## Universal Template: 10 Memory Files (+ user_info at user level)

### Info Documents (4 in repo + 1 at user level)
| File | Location | Purpose |
|------|----------|---------|
| `user_info.md` | `~/.claude/` (user-level) | Profile, working style, team |
| `references_info.md` | Technical references (APIs, commands, versions) |
| `decisions_info.md` | Key architectural and naming decisions |
| `dependencies_info.md` | External systems depended upon |
| `learnings_info.md` | Retrospection, failures, self-correction protocol |

### Intake Documents (6)
| File | Purpose |
|------|---------|
| `feedback_intake.md` | User feedback and corrections |
| `bugs_intake.md` | Known bugs |
| `features_intake.md` | Requested features |
| `gaps_intake.md` | Known gaps and incomplete work |
| `risks_intake.md` | Security, scalability, vulnerabilities |
| `platform_intake.md` | SDLC, non-functional, Claude-owned |

## Intake Document Format

```markdown
# {Title} Intake

> Type: INTAKE | Last reviewed: {YYYY-MM-DD} | Staleness: {FRESH|AGING|STALE|DRAINED}

## Active Items

| Key | Item | Added | Last Actioned | Status | Assignee | Next Action | Blockers | Delivered To |
|-----|------|-------|---------------|--------|----------|-------------|----------|--------------|
| {PREFIX}-001 | Description | 2026-03-29 | 2026-03-29 | OPEN | Claude | What to do next | — | — |

## Archive
| Key | Item | Delivered | Resolution |
|-----|------|-----------|------------|
```

### Key Prefixes
- `BUG-` bugs, `FEAT-` features, `GAP-` gaps, `RISK-` risks, `PLAT-` platform, `FB-` feedback
- Keys are permanent — never reused after archival

### Item Statuses
- OPEN — captured, not yet started
- IN_PROGRESS — actively being worked on
- BLOCKED — can't proceed (blocker in Blockers column)
- CLOSED — done, will be archived

### Health (computed from Last Actioned date, not set manually)
- FRESH: last actioned within 3 days
- AGING: 4-7 days since last action
- STALE: 8+ days since last action

## Business Objectives

Every project should have `objectives_info.md` with:
- Business objectives table (ID, objective, success criteria, priority)
- Go-live/deployment checklist with per-check status
- Blockers mapped to objectives (which blocker prevents which objective)

## Project Docs (in repo docs/)

| File | Type | Purpose |
|------|------|---------|
| `docs/project_roadmap.md` | Delivery tracker | Intake items flow here |
| `docs/project_architecture_living.md` | Living | System design — refresh after major changes |
| `docs/project_integration_living.md` | Living | APIs, contracts — refresh when APIs change |
| `docs/project_vision_info.md` | Info | Mission, philosophy — stable |
| `README.md` | The manual | Update when features ship |

## Standing Instructions

### Session Start (MANDATORY)
1. Read `<package>/memory/MEMORY.md` — know objectives, readiness %, blockers.
2. Run `python scripts/project_status.py` — get KPIs.
3. Report: readiness %, top blocker, aging items, recommended focus.
4. Start working on the highest-priority blocker. Don't ask what to do.

### Drain Intake Documents
1. Every action item must flow to project_roadmap.md or session tasks.
2. Keep scrubbing until all items are CLOSED or BLOCKED.
3. When feedback/errors/requirements arrive: capture -> intake -> ROADMAP -> deliver.
4. Never let intake docs rot. STALE = Claude's failure.

### Self-Correction (when going in circles)
1. Stop building features — fix blockers instead.
2. Pick the blocker that unblocks the most objectives.
3. Prove it works with LIVE data, not simulated.
4. Close items before opening new ones.
5. Report convergence: "Readiness was X%, now Y%."

## Project Status Script

Copy `scripts/project_status.py` to any project. Update `MEMORY_DIR` path at top.

```bash
python scripts/project_status.py              # KPIs + focus + aging
python scripts/project_status.py --blockers   # All blockers with next actions
python scripts/project_status.py --objectives # Go-live checklist detail
python scripts/project_status.py --pipeline   # Items by category
python scripts/project_status.py --items      # All active items
python scripts/project_status.py --stale      # Only stale/aging
python scripts/project_status.py --docs       # Document inventory
python scripts/project_status.py --focus      # Just recommended focus
python scripts/project_status.py --all        # Everything
```

KPIs shown first: Skin in the Game score, Go-Live readiness %, Convergence %, Going in Circles detector.
