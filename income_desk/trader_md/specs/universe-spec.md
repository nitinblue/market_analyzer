# Universe Specification

**Version:** 1.0
**Status:** Draft
**File extension:** `.universe.md`

## Overview

A universe file defines a list of ticker symbols that a workflow operates on. Tickers can appear in the YAML frontmatter, in the markdown body as bullet points, or both. The parser deduplicates the combined list while preserving insertion order. Universe files are referenced by workflow files via the `universe:` frontmatter field.

## File Structure

```
---
name: <identifier>
market: <market_code>
description: <summary>
tickers:
  - TICKER1
  - TICKER2
---

# Title (ignored by parser)

## Section Heading (ignored by parser)
- TICKER3    # optional comment
- TICKER4    # optional comment
```

## Frontmatter Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| name | string | no | file stem | Unique identifier for the universe |
| market | string | no | `"US"` | Market code: `"US"` or `"India"` |
| description | string | no | `""` | Human-readable description |
| tickers | list of strings | no | `[]` | Tickers defined in frontmatter (processed before body tickers) |

## Body Sections

### Ticker Bullet Points

Tickers in the body are extracted from lines matching the pattern:

```
^\s*-\s+([A-Z][A-Z0-9.]*)
```

Rules:
- The ticker must start with an uppercase letter (`A-Z`)
- Remaining characters can be uppercase letters, digits, or dots (e.g., `BRK.B`)
- Everything after the ticker symbol on the same line is ignored (comments, lot sizes, etc.)
- Section headings (`##`) are ignored by the parser; they serve only as human-readable organization
- Lines that do not match the bullet pattern are ignored

### Deduplication

Tickers from frontmatter are processed first, then body tickers. Duplicates are removed while preserving the order of first appearance. For example, if `SPY` appears in both frontmatter and body, only the frontmatter occurrence is kept.

## Examples

### Minimal Example

```markdown
---
name: test
---

- SPY
- QQQ
```

### Full Example

```markdown
---
name: us_large_cap
market: US
description: US large cap stocks and major ETFs for income trading
---

# US Large Cap Universe

## Index ETFs
- SPY    # S&P 500
- QQQ    # Nasdaq 100
- IWM    # Russell 2000
- DIA    # Dow 30

## Bonds & Commodities
- TLT    # 20Y Treasury
- GLD    # Gold

## Mega Cap Tech
- AAPL   # Apple
- MSFT   # Microsoft
- NVDA   # NVIDIA
```

## Parser Behavior

- Frontmatter `tickers` field accepts a YAML list; each element is converted to a string and stripped
- If `tickers` is not a list (e.g., a scalar string), it is not iterated and no frontmatter tickers are added
- Body ticker regex requires at least one uppercase letter followed by zero or more uppercase letters, digits, or dots. Lowercase tickers will not be matched
- The parser does not validate whether ticker symbols are real or tradeable
- An empty universe (no tickers in frontmatter or body) is valid and results in an empty `tickers` list
