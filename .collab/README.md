# .collab — eTrading ↔ income-desk Collaboration

Cross-repo communication channel between eTrading (orchestrator) and income-desk (library).

## Protocol

1. **Requests** (`eT → ID`): eTrading writes `REQUEST_<topic>.md` with function specs, models, integration pattern
2. **Feedback** (`ID → eT`): ID writes `FEEDBACK_<topic>.md` with API changes, breaking changes, recommendations
3. **Contracts** (`shared`): `CONTRACT_<topic>.md` — agreed interfaces that both repos depend on

## File Naming

| Direction | Pattern | Example |
|-----------|---------|---------|
| eT → ID | `REQUEST_<topic>.md` | `REQUEST_ops_reporting.md` |
| ID → eT | `FEEDBACK_<topic>.md` | `FEEDBACK_structure_whitelist.md` |
| Shared | `CONTRACT_<topic>.md` | `CONTRACT_trade_analytics.md` |

## Active Items

- `REQUEST_ops_reporting.md` — Business operations reporting functions (2026-03-24)
