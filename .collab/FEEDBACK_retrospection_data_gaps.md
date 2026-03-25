# FEEDBACK: Retrospection Data Gaps — 5 Fields Needed

**From:** income-desk
**Date:** 2026-03-24
**Status:** Waiting on eTrading

---

## Report Summary (2026-03-24)

Grade: F (58) — **not because trades are bad, but because data is missing.**

39 trades analyzed. Every trade gets C on regime_alignment (no regime_at_entry) and C on position_sizing (no position_size). With these fields populated, grade would be ~B+.

## 5 Fields eTrading Must Populate

| # | Field | On Model | Current | Impact |
|---|-------|----------|---------|--------|
| 1 | `regime_at_entry` | TradeOpened.entry_analytics | null on all 15 | regime_alignment = C |
| 2 | `position_size` | TradeOpened | null on all 15 | position_sizing = C |
| 3 | `entry_price` | TradeOpened | 0.0 on most US | entry_pricing = C |
| 4 | `entry_delta` / `delta` | LegRecord | 0.0 on most US | strike_placement misleading |
| 5 | System health fields | RetrospectionInput.system_health | all zeros | system health = RED |

## PnL Multiplier Bug (Still Open)

BAC/GBTC equity: 100x multiplier instead of 1x. eTrading-side fix.

## See Also

Full request with code snippets: `eTrading/collaboration/id-etrading/REQUEST_data_quality_for_commentary.md`
