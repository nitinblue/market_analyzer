# FEEDBACK: P0 Whitelist Fix Consumed

**From:** eTrading (session 48)
**Date:** 2026-03-24
**Status:** DONE

---

## What eTrading Did

Wired `ALL_OPTION_STRUCTURES` into `Maverick._get_allowed_structures()` as the fallback
when desk config has no explicit structure list. All 15 option structures now pass by default.

```python
from income_desk import ALL_OPTION_STRUCTURES
# Fallback: [s.value for s in ALL_OPTION_STRUCTURES]
```

## Result

- 6 shadow trades from today (QQQ diagonal 0.715, XLF calendar 0.684, etc.) would now pass
- 332 tests passing, zero regressions
- Option trading is unblocked for next market session

## Open: Desk-Specific Restrictions

For theta-only desks (desk_medium, desk_0dte), we may want to use `INCOME_STRUCTURES`
instead of `ALL_OPTION_STRUCTURES`. Currently all desks get the full list.

**Question for ID:** Should desk-level structure restrictions be configured in risk_config.yaml
or should ID provide a `recommend_structures_for_desk(desk_type, dte_range)` function?
