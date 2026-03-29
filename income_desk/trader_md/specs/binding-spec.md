# Binding Specification

**Version:** 1.0
**Status:** Draft
**File extension:** n/a (used within `.workflow.md` files)

## Overview

Bindings are expressions that appear as values in workflow step `inputs:` and `outputs:` blocks. They define how data flows between the execution context, step results, risk profile, and literal values. The TradingRunner resolves bindings at runtime by pattern-matching the expression string and extracting the corresponding value from the execution context.

Binding expressions start with `$` to reference runtime values, or are literal values (strings, numbers, booleans, empty lists).

## Binding Types

### Context Variables

| Expression | Resolves To | Description |
|------------|-------------|-------------|
| `$universe` | `list[str]` | Ticker list from the resolved universe file |
| `$capital` | `float` | Account net liquidating value (NLV) |
| `$positions` | `list` | Current open positions |

### Indexed Position Access

| Expression | Resolves To | Description |
|------------|-------------|-------------|
| `$positions[N]` | object | The Nth position (0-indexed) |
| `$positions[N].field` | any | A field on the Nth position |

Example: `$positions[0].ticker`, `$positions[0].entry_price`

If index `N` is out of range, resolves to `None`.

### Risk Profile Fields

| Expression | Resolves To | Description |
|------------|-------------|-------------|
| `$risk.<field>` | any | Field from the resolved RiskProfile |

Example: `$risk.min_pop`, `$risk.max_positions`, `$risk.max_risk_per_trade_pct`

If the risk profile is not resolved or the field does not exist, resolves to `None`.

### Step Result Fields

| Expression | Resolves To | Description |
|------------|-------------|-------------|
| `$result.<field>` | any | Field from the current step's return value |
| `$result.<field>.<subfield>` | any | Nested field access via dot notation |

Used primarily in `outputs:` blocks to capture specific fields from a workflow response.

Example: `$result.sentinel_signal`, `$result.trades`, `$result.is_safe_to_trade`

### Cross-Phase References

| Expression | Resolves To | Description |
|------------|-------------|-------------|
| `$phaseN.<output>` | any | Named output from phase N |
| `$phaseN.<output>[I]` | any | Item at index I from a list output |
| `$phaseN.<output>[I].<field>` | any | Field on an indexed item |

Examples:
- `$phase1.iv_rank_map` -- the `iv_rank_map` output saved during phase 1
- `$phase2.proposals[0].ticker` -- the `ticker` field of the first item in the `proposals` output from phase 2
- `$phase2.proposals[0].entry_credit` -- a numeric field on the first proposal

If the phase key does not exist, the output name is not found, or the index is out of range, resolves to `None`.

### Literal Values

Non-`$` expressions are parsed as literal values in this order:

| Literal | Resolves To | Type |
|---------|-------------|------|
| `[]` | `[]` | empty list |
| `true` or `True` | `True` | bool |
| `false` or `False` | `False` | bool |
| `null` or `None` | `None` | NoneType |
| Integer string (e.g., `1`, `42`) | `1`, `42` | int |
| Float string (e.g., `1.0`, `0.3`) | `1.0`, `0.3` | float |
| Anything else | the string itself | str |

Examples in workflow files:
```
inputs:
  regime_id: 1              # int literal
  atr_pct: 1.0              # float literal
  include_regime: true       # bool literal
  trades_today: []           # empty list literal
  market: India              # string literal
  current_price: 0           # int literal
```

## Resolution Order

1. If the value does not start with `$`, parse as literal
2. If `$universe`, return context universe list
3. If `$capital`, return context capital float
4. If `$positions`, return context positions list
5. If `$positions[N]...`, index into positions list
6. If `$risk.<field>`, look up field on RiskProfile
7. If `$result.<field>`, navigate dotted path on current step result
8. If `$phaseN.<path>`, look up in phase outputs dict with optional indexing
9. If none of the above patterns match, return the expression string unchanged

## Null Handling

- Out-of-range index access returns `None`
- Missing fields on objects return `None`
- Missing phase outputs return `None`
- `None` inputs are filtered out before building the workflow request (the runner excludes `None` values from the request constructor)
- If a required request field resolves to `None`, the request construction will raise an error

## Examples

### Input Bindings

```
inputs:
  tickers: $universe                         # context variable
  capital: $capital                           # context variable
  iv_rank_map: $phase1.iv_rank_map           # cross-phase reference
  min_pop: $risk.min_pop                     # risk profile field
  ticker: $phase2.proposals[0].ticker        # indexed cross-phase
  regime_id: 1                               # int literal
  market: India                              # string literal
  trades_today: []                           # empty list literal
```

### Output Bindings

```
outputs:
  pulse: $result.sentinel_signal             # step result field
  proposals: $result.trades                  # step result field
  snapshots: $result.tickers                 # step result field
```
