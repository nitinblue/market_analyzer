# Gate Specification

**Version:** 1.0
**Status:** Draft
**File extension:** n/a (used within `.workflow.md` files)

## Overview

Gates are conditional checks that run after a workflow step completes. Each gate contains a Python expression that is evaluated against the step's result object. If a gate expression evaluates to `False`, the associated `on_fail` action determines how execution proceeds. Gates enable workflow files to encode trading rules declaratively -- halting on red market signals, skipping when no opportunities exist, or alerting when positions need attention.

## Syntax

### Gate Declaration

Gates are declared in a `gate:` block within a step, as a bullet list:

```
gate:
  - <expression>
  - <expression>
```

Each `- <expression>` line creates a `Gate` object with `on_fail: "HALT"` and `message: ""` as defaults.

### on_fail Declaration

The `on_fail:` line applies to **all gates** in the current step (retroactively):

```
on_fail: ACTION "message with {interpolation}"
```

Format: `on_fail:\s*(\w+)\s*"(.*)"` -- an action word followed by a quoted message string.

## Gate Expressions

Gate expressions are Python expressions evaluated in a restricted namespace. The namespace contains:

1. **Step result fields** -- all non-private attributes of the workflow response object
2. **Phase outputs** -- all named outputs from previously executed phases
3. **Built-in functions** -- only `len()` is available
4. **Boolean/None constants** -- `True`, `False`, `None`

### Supported Operators

| Operator | Example | Description |
|----------|---------|-------------|
| `==` | `safe == True` | Equality |
| `!=` | `pulse != "RED"` | Inequality |
| `<` | `risk_pct_of_capital < 3.0` | Less than |
| `>` | `len(proposals) > 0` | Greater than |
| `<=` | `dte <= 45` | Less than or equal |
| `>=` | `score >= 0.5` | Greater than or equal |

### Functions

| Function | Example | Description |
|----------|---------|-------------|
| `len()` | `len(proposals) > 0` | Length of a list or collection |

### Value Types in Expressions

| Type | Example | Notes |
|------|---------|-------|
| String | `pulse != "RED"` | Must be quoted with double quotes |
| Boolean | `safe == True`, `is_ready == True` | Use Python `True`/`False` |
| Integer | `critical_count == 0` | Numeric comparison |
| Float | `risk_pct_of_capital < 3.0` | Decimal comparison |

### $risk References in Expressions

Gate expressions can reference risk profile fields using `$risk.<field>` syntax. Before evaluation, these references are resolved and replaced with their literal values:

```
gate:
  - risk_pct_of_capital < $risk.max_risk_per_trade_pct
```

At evaluation time, `$risk.max_risk_per_trade_pct` is replaced with `3.0` (or whatever the resolved value is), so the expression becomes `risk_pct_of_capital < 3.0`.

## on_fail Actions

| Action | Behavior | Description |
|--------|----------|-------------|
| `HALT` | Stop entire workflow | Critical failure -- no further phases or steps execute. The execution report is marked as halted with the gate message as the reason |
| `SKIP` | Skip remaining steps in current phase | Non-critical -- the current step is recorded as SKIPPED and execution continues to the next phase |
| `BLOCK` | Block the current step | The step is recorded as BLOCKED. Execution continues to the next step in the same phase |
| `ALERT` | Record alert, continue | The step is recorded as ALERT. Execution continues normally. Used for monitoring steps where action is needed but the workflow should not stop |
| `WARN` | Record warning, continue | The step is recorded as WARNED. Execution continues normally. Informational only |

### Default Action

If no `on_fail:` line is present, all gates default to `on_fail: HALT` with an empty message.

## Message Interpolation

The message string supports `{field_name}` interpolation using Python's `str.format()`. Field names are resolved from the step result object's attributes.

```
on_fail: HALT "Market pulse {pulse} -- trading halted"
on_fail: ALERT "Critical: {critical_count} positions need action"
on_fail: BLOCK "Risk {risk_pct_of_capital}% exceeds limit"
on_fail: SKIP "Validation failed: {failed_gates}"
```

If a referenced field does not exist on the result object, the interpolation falls back to the raw gate expression as the message.

## Examples

### Single Gate with HALT

```
gate:
  - pulse != "RED"
on_fail: HALT "Market pulse {pulse} -- trading halted"
```

### Multiple Gates with HALT

Both gates share the same on_fail action and message:

```
gate:
  - pulse != "RED"
  - safe == True
on_fail: HALT "Market pulse {pulse} -- trading halted"
```

### Gate with len()

```
gate:
  - len(proposals) > 0
on_fail: SKIP "No tradeable opportunities found"
```

### Gate with $risk Reference

```
gate:
  - risk_pct_of_capital < $risk.max_risk_per_trade_pct
on_fail: BLOCK "Risk {risk_pct_of_capital}% exceeds limit"
```

### Gate without on_fail (defaults to HALT)

```
gate:
  - is_ready == True
```

## Parser Behavior

- Gate expressions are stored as raw strings; no validation occurs at parse time
- `on_fail` is parsed after all gates in the step are collected; it applies to every gate in that step
- If `on_fail` appears before `gate:`, it has no effect (there are no gates to retroactively update)
- Multiple `on_fail` lines in the same step will each overwrite all gates' action and message

## Evaluation Behavior

- Expressions are evaluated using Python `eval()` with a restricted `__builtins__` namespace containing only `len`, `True`, `False`, and `None`
- The evaluation namespace includes all non-private attributes from the step result object, plus all phase output values
- `$risk.<field>` references are resolved and substituted as `repr()` literals before `eval()` runs
- If `eval()` raises any exception (NameError, TypeError, etc.), the gate is treated as **passed** (returns `True`). This is a safety default -- unknown conditions do not block execution
- When a gate fails, only the first failing gate's action is applied; subsequent gates in the same step are not evaluated
