# Platform Intake

> Type: INTAKE | Last reviewed: 2026-03-29 | Staleness: FRESH

## Active Items

| Key | Item | Added | Last Actioned | Status | Assignee | Next Action | Blockers | Delivered To |
|-----|------|-------|---------------|--------|----------|-------------|----------|--------------|
| PLAT-001 | Update scheduled agent prompts to income_desk.trader | 2026-03-29 | 2026-03-29 | OPEN| Claude | Update both trigger prompts via RemoteTrigger API | — | — |
| PLAT-002 | Gmail MCP not available for triggers | 2026-03-29 | 2026-03-29 | BLOCKED | — | Monitor Anthropic connector updates | Gmail not in trigger connector list | — |
| PLAT-003 | Add pre-commit hooks (linting, type checking) | 2026-03-29 | 2026-03-29 | OPEN| Claude | Create .pre-commit-config.yaml with ruff + mypy | — | ROADMAP Phase 7 |
| PLAT-004 | Pin major dependency versions | 2026-03-29 | 2026-03-29 | OPEN| Claude | Review pyproject.toml deps, pin pandas/numpy/hmmlearn | — | ROADMAP Phase 7 |
| PLAT-005 | Integration tests with paper trading | 2026-03-29 | 2026-03-29 | OPEN| Claude | Create nightly CI job connecting to TT paper account | Needs paper account credentials in GitHub secrets | ROADMAP Phase 7 |
| PLAT-006 | Set up GitHub Project for issue tracking | 2026-03-29 | 2026-03-29 | OPEN | Nitin | Run: gh auth refresh -s read:project,project | Needs GitHub auth scope | — |
| PLAT-007 | v2.0 release testing: trader_md end-to-end with LIVE broker | 2026-03-29 | 2026-03-29 | OPEN | Claude | See v2.0 release checklist below | Must pass all checks before PyPI publish | — |
| PLAT-008 | v2.0 release testing: trader/ (Python path) with LIVE broker | 2026-03-29 | 2026-03-29 | OPEN | Claude | See v2.0 release checklist below | Must pass all checks before PyPI publish | — |
| PLAT-009 | v2.0 release testing: run full pytest suite, 0 failures | 2026-03-29 | 2026-03-29 | OPEN | Claude | .venv_312/Scripts/python -m pytest tests/ -x -q | — | — |
| PLAT-010 | v2.0 release: bump version to 2.0.0, create GitHub release | 2026-03-29 | 2026-03-29 | OPEN | Claude | Update pyproject.toml, gh release create v2.0.0 | PLAT-007,008,009 must pass first | — |

## Archive
