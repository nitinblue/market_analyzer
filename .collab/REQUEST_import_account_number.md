# REQUEST: Add account_number to ImportResult/ImportedPosition

**From:** eTrading
**To:** income-desk
**Date:** 2026-03-31
**Priority:** HIGH — blocks broker onboarding via CSV

---

## Problem

`ImportedPosition` doesn't include `account_number`. When a user imports positions via CSV, eTrading needs to know which account they belong to, so each account gets its own portfolio. Without this, we can't distinguish between:

- Fidelity IRA (259510977) and Fidelity Personal (Z71212342)
- Multiple TastyTrade accounts

## What We Need

### Option A: Add `account_number` to `ImportResult`

```python
class ImportResult:
    positions: list[ImportedPosition]
    total_imported: int
    skipped: int
    errors: list[str]
    broker_detected: str
    file_path: str
    account_number: str | None  # ← NEW: extracted from CSV content or filename
```

### Option B: Add `account_number` to each `ImportedPosition`

```python
class ImportedPosition:
    ticker: str
    ...
    account_number: str | None  # ← NEW
```

**Option A is simpler** since a CSV file typically represents one account.

## Where Account Numbers Live

| Broker | Where account_number is |
|--------|------------------------|
| Fidelity | Filename: `Portfolio_Positions_259-510977.csv`, or first row "Account Number" |
| Schwab | CSV header row includes account number |
| TastyTrade | "Account Number" column in CSV |
| IBKR | "Account" column in Flex report |
| Webull | Filename or "Account" column |

## Fallback

If extraction fails, return `account_number=None`. eTrading will prompt the user to identify the account.

---

**Status:** WAITING
