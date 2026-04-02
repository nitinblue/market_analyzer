# Gaps Intake

> Type: INTAKE | Last reviewed: 2026-04-01 | Staleness: FRESH

## Active Items

| Key | Item | Added | Last Actioned | Status | Assignee | Next Action | Blockers | Delivered To |
|-----|------|-------|---------------|--------|----------|-------------|----------|--------------|
| GAP-001 | Dhan rate limiting — 805 errors at scale | 2026-03-24 | 2026-03-24 | OPEN | Claude | Add throttle (1 req/3s) in option_chain loop | — | — |
| GAP-002 | Dhan token expires — no auto-refresh | 2026-03-24 | 2026-03-24 | OPEN | Nitin | Build token refresh flow or alert when expired | Needs Dhan API docs for refresh endpoint | — |
| GAP-003 | FINNIFTY yfinance symbol — verify ^NSEFI | 2026-03-24 | 2026-03-24 | OPEN | Claude | Use existing ticker symbol utility (already built) to verify — check income_desk/models/universe.py or market_registry | — | — |
| GAP-004 | Zero income trades for India in some conditions | 2026-03-26 | 2026-04-01 | CLOSED | Claude | Fixed: chain-first pipeline + POP fix + iv_30_day wiring. India trades now generate with real chain strikes and correct POP. Commits 8070e7d, d18a63b, 7295609 | — | chain pipeline |
| GAP-005 | regime_id not on TradeProposal | 2026-03-29 | 2026-04-01 | CLOSED | Claude | Already added: TradeProposal has regime_id field since chain-first refactor | — | _types.py |
| GAP-006 | README needs trader_md CLI commands | 2026-03-29 | 2026-03-29 | OPEN | Claude | Add trader_md section to README | — | ROADMAP Phase 1 |

## Archive
