# Developer Onboarding — Working with Claude

This project uses a structured project management system powered by Claude Code. Follow these steps to set up your environment.

## Prerequisites

- Claude Code CLI installed ([claude.ai/code](https://claude.ai/code))
- Git access to this repo
- Python 3.12+

## Step 1: Install the Global Skill (one-time, per machine)

Create this file at `~/.claude/skills/project-management.md`:

```bash
# Mac/Linux
mkdir -p ~/.claude/skills
curl -o ~/.claude/skills/project-management.md https://raw.githubusercontent.com/nitinblue/income-desk/main/.claude/skills/project-management.md
```

```powershell
# Windows
mkdir %USERPROFILE%\.claude\skills
curl -o %USERPROFILE%\.claude\skills\project-management.md https://raw.githubusercontent.com/nitinblue/income-desk/main/.claude/skills/project-management.md
```

Or simply copy `~/.claude/skills/project-management.md` from Nitin's machine.

This skill teaches Claude the project management system. It works across ALL projects, not just this one.

## Step 2: Create Your User Profile (one-time, per machine)

Create `~/.claude/user_info.md` with your details:

```markdown
# User Profile

> Type: INFO | Last updated: YYYY-MM-DD

## Team

| Name | Role | Focus |
|------|------|-------|
| Your Name | Your role | Your focus areas |

## Working Style
- Your preferences for how Claude should work with you
```

This file is personal — it stays on your machine, never committed to any repo.

## Step 3: Clone and Run

```bash
git clone https://github.com/nitinblue/income-desk.git
cd income-desk
pip install -e ".[dev]"

# See where the project stands
python scripts/project_status.py
```

The project status shows: readiness %, blockers, aging items, and recommended focus.

## Step 4: Start a Claude Session

```bash
claude
```

Claude will:
1. Read `income_desk/memory/MEMORY.md` — knows objectives, blockers, readiness
2. Run `python scripts/project_status.py` — gets current KPIs
3. Report status and recommend what to work on
4. Start working — no open-ended questions

You don't need to explain the project. Claude has full context from the memory files.

## How the System Works

### Memory Files (in repo at `income_desk/memory/`)

These files track everything about the project:

| File | What's inside |
|------|--------------|
| `MEMORY.md` | Registry — index of all files with staleness |
| `objectives_info.md` | Business objectives, go-live checklist, blockers |
| `decisions_info.md` | Key decisions made (architecture, naming, strategy) |
| `references_info.md` | Technical references (APIs, broker details, versions) |
| `dependencies_info.md` | External systems we depend on |
| `learnings_info.md` | Retrospection — what failed, how to fix, self-correction |
| `feedback_intake.md` | User feedback flowing through pipeline |
| `bugs_intake.md` | Known bugs |
| `features_intake.md` | Feature requests |
| `gaps_intake.md` | Technical gaps and incomplete work |
| `risks_intake.md` | Security, scalability concerns |
| `platform_intake.md` | CI/CD, non-functional requirements |

### File Types

- `*_info.md` — Stable reference. Read anytime.
- `*_intake.md` — Action pipeline. Items flow: OPEN -> IN_PROGRESS -> CLOSED.

### Intake Item Format

Every intake item has:

| Column | Purpose |
|--------|---------|
| Key | Unique ID (BUG-001, FEAT-002, etc.) — permanent, never reused |
| Item | What it is |
| Added | When it was captured |
| Last Actioned | When someone last worked on it |
| Status | OPEN, IN_PROGRESS, BLOCKED, CLOSED |
| Assignee | Who owns it (Nitin, Priyanka, Claude) |
| Next Action | What to do next |
| Blockers | What's preventing progress |
| Delivered To | Which roadmap phase this feeds |

### Health/Staleness (computed automatically)

- **FRESH**: Actioned within 3 days
- **AGING**: 4-7 days without action
- **STALE**: 8+ days — someone dropped the ball

## Project Status Dashboard

```bash
python scripts/project_status.py              # KPIs + focus + aging items
python scripts/project_status.py --blockers   # All blockers mapped to objectives
python scripts/project_status.py --objectives # Go-live checklist detail
python scripts/project_status.py --pipeline   # Items by intake category
python scripts/project_status.py --items      # All active items
python scripts/project_status.py --stale      # Only stale/aging
python scripts/project_status.py --docs       # Document inventory
python scripts/project_status.py --focus      # Just the recommended focus
python scripts/project_status.py --all        # Everything
```

### KPIs (shown first, every time)

| KPI | What it measures |
|-----|-----------------|
| Skin in the Game | Is Claude driving toward objectives or doing busywork? (0-100) |
| Go-Live Readiness | % of go-live checklist passing with live broker data |
| Convergence | Closed items / total items — are we finishing things? |
| Going in Circles? | Technical churn without business progress |

## How to Contribute

### Adding a bug
Edit `income_desk/memory/bugs_intake.md`, add a row:
```
| BUG-NNN | Description | YYYY-MM-DD | YYYY-MM-DD | OPEN | Your Name | What to do | — | — |
```

### Adding a feature request
Edit `income_desk/memory/features_intake.md`, same format with `FEAT-NNN` key.

### Closing an item
Change status to `CLOSED`, move the row to the Archive section at the bottom.

### Starting a Claude session to work on something
Just open Claude in the project directory. Claude reads the memory files and knows what needs doing. Say what you want to focus on, or let Claude pick based on priority.

## Project Docs

| Doc | Purpose |
|-----|---------|
| `README.md` | The manual — how to use income_desk |
| `CLAUDE.md` | Standing instructions for Claude |
| `docs/project_roadmap.md` | Delivery tracker — phases, objectives |
| `docs/project_architecture_living.md` | System design |
| `docs/project_integration_living.md` | APIs, contracts, boundaries |
| `docs/project_vision_info.md` | Mission, philosophy |

## Setting Up Other Projects (Cleaning Up Existing MD Mess)

If you have a project with scattered .md files and no structure, open Claude in that project directory and say:

```
Read ~/.claude/skills/project-management.md.
This project has scattered MD files that need consolidation.
Set up the standard memory structure, migrate everything
relevant into the 10 intake/info files, archive the rest.
Run project_status.py when done.
```

### What Claude will do automatically:

1. Read the global skill (knows the full system)
2. Scan ALL existing .md files in the project
3. For each file, categorize: decision? bug? feature? learning? reference? gap? risk?
4. Create `<package>/memory/` with the 10 standard files
5. Migrate content from scattered files into the right intake/info file
6. Archive originals to `docs/archive/`
7. Create `MEMORY.md` registry
8. Copy `scripts/project_status.py` (auto-discovers memory dir)
9. Ask for business objectives — populate `objectives_info.md` with go-live checklist
10. Run `python scripts/project_status.py` to show the clean state
11. Identify all action items discovered during migration — add to intake files with keys
12. Map blockers to objectives
13. Report: "Found X bugs, Y features, Z gaps. Skin in the Game: N/100."

### What YOU do:

Nothing. One prompt. Claude does the cleanup. The skill is the instruction manual.

### For Priyanka's machine setup:

```bash
# 1. Install the skill (one-time)
mkdir -p ~/.claude/skills
# Copy project-management.md from Nitin's machine or download from repo

# 2. Create user profile (one-time)
# Create ~/.claude/user_info.md with your details

# 3. Clone any project — memory files are already in the repo
git clone <repo>
cd <project>
python scripts/project_status.py   # see where things stand

# 4. Start Claude — it knows what to do
claude
```

## Team

| Name | Role |
|------|------|
| Nitin | Founder, architect, trader |
| Priyanka Jain | Co-founder, strategy, India market |
| Claude (Opus 4.6) | AI engineering partner |
