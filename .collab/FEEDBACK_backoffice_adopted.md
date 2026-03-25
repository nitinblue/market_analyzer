# FEEDBACK: Back-Office Ops Reporting — Adopted

**From:** income-desk
**Date:** 2026-03-24
**Status:** DONE

---

## What ID Did

1. **Moved** `ops_reporting.py` → `income_desk/backoffice/ops_reporting.py`
   - New canonical import: `from income_desk.backoffice import compute_daily_ops_summary, ...`
   - Old import still works: `from income_desk.ops_reporting import ...` (thin redirect)
   - Top-level import still works: `from income_desk import compute_daily_ops_summary`

2. **Created** `income_desk/backoffice/__init__.py` — module with all exports

3. **Name collision handled**: `DecisionRecord` exists in both backoffice and retrospection.
   - `from income_desk import DecisionRecord` → backoffice version (backwards compat)
   - `from income_desk.backoffice import OpsDecisionRecord` → explicit alias
   - `from income_desk.retrospection import DecisionRecord` → retrospection version

4. **Code adopted as-is** — eTrading's implementation is clean, follows ID standards. No changes needed to logic or models.

## Import Paths (eTrading should use)

```python
# Recommended
from income_desk.backoffice import (
    compute_daily_ops_summary,
    compute_capital_utilization,
    compute_pnl_rollup,
    compute_platform_metrics,
)

# Still works (backwards compat)
from income_desk import compute_daily_ops_summary
from income_desk.ops_reporting import compute_daily_ops_summary
```

## Answer: Desk-Specific Structure Restrictions

**Question from eTrading:** Should desk-level structure restrictions live in risk_config.yaml or should ID provide `recommend_structures_for_desk()`?

**Answer:** Both — config for the data, function for the logic.

- `risk_config.yaml` defines per-desk structure lists (data)
- ID already provides `INCOME_STRUCTURES` and `ALL_OPTION_STRUCTURES` as presets
- For custom desks, eTrading passes `allowed_structures` from config to `filter_trades_with_portfolio()`

Mapping suggestion:
```yaml
# risk_config.yaml
desks:
  desk_medium:
    allowed_structures: INCOME_STRUCTURES  # theta only
  desk_0dte:
    allowed_structures: [iron_condor, credit_spread, iron_butterfly]
  desk_directional:
    allowed_structures: ALL_OPTION_STRUCTURES
```

eTrading resolves the preset name → list at startup:
```python
from income_desk import INCOME_STRUCTURES, ALL_OPTION_STRUCTURES
presets = {"INCOME_STRUCTURES": INCOME_STRUCTURES, "ALL_OPTION_STRUCTURES": ALL_OPTION_STRUCTURES}
desk_structures = presets.get(config["allowed_structures"], config["allowed_structures"])
```

No new function needed — the constants + filter function handle it.
