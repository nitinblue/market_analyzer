# Go-Live Scoring Algorithm

> Scientific, measurable criteria. No gut feelings.

## Formula

```
Go-Live % = (passed_checks / total_checks) * 100
```

Each check has a **weight** based on trading impact. A check is PASS only with **evidence** (test output, not "I think it works").

## Weighted Checklist (India Market)

| # | Check | Weight | Evidence Required | India Status |
|---|-------|--------|-------------------|--------------|
| 1 | Broker connects without error | 5% | Zero HTTP errors in harness output | PASS |
| 2 | All workflows execute (no crashes) | 5% | 16/16 OK in harness summary | PASS |
| 3 | Underlying prices match broker | 5% | price_trade underlying matches Dhan quote within 0.5% | PASS |
| 4 | IV from broker, not estimated | 5% | IV column shows 15-80%, not 0.5% or None | PASS (after display fix) |
| 5 | IVR populated from broker | 3% | IVR column shows values, not N/A | PASS |
| 6 | Chain-repriced credits (not estimated) | 10% | ranking shows "chain_repriced=True", credit >1 INR | PARTIAL (some tickers) |
| 7 | POP realistic (30-80% for income) | 10% | POP column shows 30-80%, not 1% or 99% | FAIL (DTE bug) |
| 8 | Strikes from real chain (not fallback) | 8% | All 4 IC strikes exist in chain with OI>0 | PARTIAL |
| 9 | Wing width market-appropriate | 5% | India: 20-200pts based on ATR. US: 2-10pts | FAIL (agent fixing) |
| 10 | Gates reject bad data | 5% | price=0 → FAIL. credit<0.10 → FAIL | PASS |
| 11 | Gate detail explains decision | 3% | Every gate row has non-empty Detail | PASS |
| 12 | Account NLV from broker | 5% | Banner shows real INR balance, not 0 | NEEDS VERIFY |
| 13 | Position sizing produces 1+ contracts | 5% | Cts column shows >=1 for viable trades | FAIL (depends on POP) |
| 14 | Stress test PnL% reasonable | 3% | -30% to +10% range, not -1260% | PASS (after BUG-010 fix) |
| 15 | Breach detection fires correctly | 2% | -35% scenario shows breach=yes | PASS |
| 16 | No simulated data in output | 5% | No "DEMO-", no "simulated", no FRED errors | PARTIAL |
| 17 | Instrument key in leg quotes | 2% | Shows "SBIN 2026-03-30 1020 CE" format | PASS |
| 18 | Expiry date on ranked trades | 2% | Expiry column populated | PASS |
| 19 | Pricing regression 100% pass | 7% | 25/25 trades PASS in pricing_regression.py | PASS |
| 20 | 3 consecutive clean daily runs | 5% | daily_test.py green 3 days in a row | NOT STARTED |

## Current Score Calculation

| Check | Weight | Status | Score |
|-------|--------|--------|-------|
| 1 | 5% | PASS | 5% |
| 2 | 5% | PASS | 5% |
| 3 | 5% | PASS | 5% |
| 4 | 5% | PASS | 5% |
| 5 | 3% | PASS | 3% |
| 6 | 10% | PARTIAL (50%) | 5% |
| 7 | 10% | FAIL | 0% |
| 8 | 8% | PARTIAL (50%) | 4% |
| 9 | 5% | FAIL | 0% |
| 10 | 5% | PASS | 5% |
| 11 | 3% | PASS | 3% |
| 12 | 5% | UNVERIFIED | 0% |
| 13 | 5% | FAIL | 0% |
| 14 | 3% | PASS | 3% |
| 15 | 2% | PASS | 2% |
| 16 | 5% | PARTIAL (60%) | 3% |
| 17 | 2% | PASS | 2% |
| 18 | 2% | PASS | 2% |
| 19 | 7% | PASS | 7% |
| 20 | 5% | NOT STARTED | 0% |
| **TOTAL** | **100%** | | **59%** |

## What Moves the Score

| Fix | Checks Affected | Score Impact |
|-----|----------------|--------------|
| POP DTE bug | 7, 13 | +15% |
| Wing width fix | 9 | +5% |
| Chain repricing all tickers | 6, 8 | +9% |
| Account NLV verify | 12 | +5% |
| 3 clean daily runs | 20 | +5% |
| Remove all demo data | 16 | +2% |

## Rules

1. A check is PASS only with **dated evidence** (harness output file, test run)
2. PARTIAL scores at 50% weight unless specific % can be justified
3. Score recalculated after every fix, with evidence file reference
4. Going backwards (PASS → FAIL) is a regression — investigate immediately
5. Go-live requires **>85%** with no P0 checks failing (checks 6, 7, 8, 13)
