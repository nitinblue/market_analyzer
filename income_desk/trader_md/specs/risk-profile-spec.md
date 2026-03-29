# Risk Profile Specification

**Version:** 1.0
**Status:** Draft
**File extension:** `.risk.md`

## Overview

A risk profile file defines position sizing limits, trade quality filters, regime permissions, and exit rules. Workflows reference a risk profile via the `risk_profile:` frontmatter field. At runtime, individual risk fields are accessible through `$risk.<field>` bindings in step inputs and gate expressions.

## File Structure

```
---
name: <identifier>
description: <summary>
max_risk_per_trade_pct: <float>
max_portfolio_risk_pct: <float>
max_positions: <integer>
min_pop: <float>
min_dte: <integer>
max_dte: <integer>
min_iv_rank: <float>
max_spread_pct: <float>
profit_target_pct: <float>
stop_loss_pct: <float>
exit_dte: <integer>
r1_allowed: <boolean>
r2_allowed: <boolean>
r3_allowed: <boolean>
r4_allowed: <boolean>
---

# Title (ignored by parser)

<body text ignored by parser>
```

## Frontmatter Fields

### Identity

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| name | string | no | file stem | Unique identifier for the risk profile |
| description | string | no | — | Human-readable description (not parsed into model) |

### Position Limits

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| max_risk_per_trade_pct | float | no | `3.0` | Maximum risk per trade as percentage of capital |
| max_portfolio_risk_pct | float | no | `30.0` | Maximum total portfolio risk as percentage of capital |
| max_positions | integer | no | `8` | Maximum number of concurrent positions |

### Trade Filters

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| min_pop | float | no | `0.50` | Minimum probability of profit (0.0 to 1.0) |
| min_dte | integer | no | `7` | Minimum days to expiration for new trades |
| max_dte | integer | no | `45` | Maximum days to expiration for new trades |
| min_iv_rank | float | no | `20.0` | Minimum IV rank (0-100 scale) to consider selling premium |
| max_spread_pct | float | no | `0.05` | Maximum bid-ask spread as fraction of mid price |

### Exit Rules

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| profit_target_pct | float | no | `0.50` | Take profit when position reaches this fraction of max profit |
| stop_loss_pct | float | no | `2.0` | Stop loss as multiple of credit received |
| exit_dte | integer | no | `5` | Close positions when DTE falls below this threshold |

### Regime Rules

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| r1_allowed | boolean | no | `true` | Allow trading in R1 (Low-Vol Mean Reverting) |
| r2_allowed | boolean | no | `true` | Allow trading in R2 (High-Vol Mean Reverting) |
| r3_allowed | boolean | no | `false` | Allow trading in R3 (Low-Vol Trending) |
| r4_allowed | boolean | no | `false` | Allow trading in R4 (High-Vol Trending) |

The `r1_allowed` through `r4_allowed` fields are converted to a `regime_rules` dict:

```python
{"r1": True, "r2": True, "r3": False, "r4": False}
```

If none of the `rN_allowed` keys are present in frontmatter, the default regime rules apply: R1 and R2 allowed, R3 and R4 disallowed.

## Body Sections

The body text is ignored by the parser. It is used for human-readable documentation of the profile's intent and trading philosophy.

## Examples

### Minimal Example

```markdown
---
name: default
---
```

This produces a risk profile with all default values.

### Full Example

```markdown
---
name: moderate
description: Moderate risk profile - balanced income and protection
max_risk_per_trade_pct: 3.0
max_portfolio_risk_pct: 30.0
max_positions: 8
min_pop: 0.50
min_dte: 7
max_dte: 45
min_iv_rank: 20
max_spread_pct: 0.05
profit_target_pct: 0.50
stop_loss_pct: 2.0
exit_dte: 5
r1_allowed: true
r2_allowed: true
r3_allowed: false
r4_allowed: false
---

# Moderate Risk Profile

Trade in R1 (full income) and R2 (selective, wider wings).
Avoid directional regimes (R3, R4). Standard income trader profile.
```

## Parser Behavior

- All numeric fields are coerced via `float()` or `int()` at parse time. If a value cannot be converted, a `ValueError` is raised
- Boolean fields use Python's `bool()` coercion. YAML `true`/`false` are parsed as Python `True`/`False` by `yaml.safe_load`
- The `description` field from frontmatter is not stored in the `RiskProfile` model -- it exists only in the file for documentation
- If a field is absent from frontmatter, the dataclass default is used
- The regime rules dict only contains keys for `rN_allowed` fields that are explicitly present in the frontmatter. If zero regime fields are present, the full default dict is used instead
