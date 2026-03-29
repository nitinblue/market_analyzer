# Workflow Specification

**Version:** 1.0
**Status:** Draft
**File extension:** `.workflow.md`

## Overview

A workflow file defines a multi-phase trading plan that the TradingRunner executes sequentially. Each workflow references a broker profile, a universe of tickers, and a risk profile, then describes an ordered series of phases containing steps. Steps map to workflow API functions in `income_desk.workflow`, with typed inputs, captured outputs, and optional gate conditions that control execution flow.

Workflows are the primary orchestration mechanism for systematic trading. A single workflow file encodes an entire trading session -- from market assessment through scanning, entry, monitoring, and reporting.

## File Structure

```
---
name: <identifier>
description: <human-readable summary>
broker: <broker_profile_name>
universe: <universe_name>
risk_profile: <risk_profile_name>
---

# Title (ignored by parser)

## Phase 1: <Phase Name>

<optional phase-level attributes>

### Step: <Step Name>
workflow: <workflow_function_name>
inputs:
  <key>: <binding_expression>
outputs:
  <key>: <binding_expression>
gate:
  - <gate_expression>
  - <gate_expression>
on_fail: <ACTION> "<message>"
requires: <requirement>
on_simulated: <message>

## Phase 2: <Phase Name>
...
```

## Frontmatter Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| name | string | no | file stem | Unique identifier for the workflow |
| description | string | no | `""` | Human-readable description |
| broker | string | no | `"simulated"` | Name of broker profile file (without `.broker.md` extension). Resolved from `broker_profiles/` directory |
| universe | string | no | `""` | Name of universe file (without `.universe.md` extension). Resolved from `universes/` directory |
| risk_profile | string | no | `"moderate"` | Name of risk profile file (without `.risk.md` extension). Resolved from `risk_profiles/` directory |

## Body Sections

### Phase Headers

Format: `## Phase N: <Name>`

- `N` is a positive integer (1-based)
- `<Name>` is a human-readable label (trailing whitespace stripped)
- Phases execute in document order
- Each phase creates a namespace `phaseN` for output references

### Phase-Level Attributes

Appear between the phase header and the first step header.

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| requires_positions | `true` or `false` | `false` | Indicates this phase operates on existing positions. Case-insensitive boolean |

### Step Headers

Format: `### Step: <Name>`

- `<Name>` is a human-readable label (trailing whitespace stripped)
- Steps execute in document order within their phase

### Step Properties

All properties appear as `key: value` lines under a step header. The parser recognizes these property names:

| Property | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| workflow | string | yes | `""` | Name of the workflow function to call (must exist in `income_desk.workflow`) |
| requires | string | no | `None` | Prerequisite. Currently only `"live_broker"` is supported |
| on_simulated | string | no | `None` | Message to display when `requires: live_broker` but broker is simulated. Step is skipped with WARNED status |

### Block Properties

These properties introduce multi-line blocks. Content lines follow the block header with indented `key: value` pairs or list items.

#### `inputs:`

Key-value pairs where each key is a workflow request field name and each value is a binding expression (see binding-spec.md).

```
inputs:
  tickers: $universe
  capital: $capital
  market: India
```

#### `outputs:`

Key-value pairs where each key is an output name (stored in the phase namespace) and each value is a binding expression that resolves against `$result`.

```
outputs:
  pulse: $result.sentinel_signal
  proposals: $result.trades
```

#### `gate:`

A list of gate expressions (prefixed with `- `). Each expression becomes a Gate object with default `on_fail: HALT`. See gate-spec.md for expression syntax.

```
gate:
  - pulse != "RED"
  - safe == True
```

#### `on_fail:`

Format: `on_fail: ACTION "message"`

Applies retroactively to all gates defined in the current step. The action word and quoted message are extracted via regex: `^on_fail:\s*(\w+)\s*"(.*)"`.

```
on_fail: HALT "Market pulse {pulse} -- trading halted"
```

The message supports `{field_name}` interpolation from the step result object.

## Examples

### Minimal Example

```markdown
---
name: minimal
---

## Phase 1: Run

### Step: Snapshot
workflow: snapshot_market
inputs:
  tickers: $universe
```

### Full Example

```markdown
---
name: daily_us_income
description: Daily income trading workflow for US market
broker: tastytrade_live
universe: us_large_cap
risk_profile: moderate
---

# Daily US Income Trading

## Phase 1: Market Assessment

### Step: Market Pulse
workflow: check_portfolio_health
inputs:
  tickers: $universe
  capital: $capital
outputs:
  pulse: $result.sentinel_signal
  safe: $result.is_safe_to_trade
gate:
  - pulse != "RED"
  - safe == True
on_fail: HALT "Market pulse {pulse} -- trading halted"

## Phase 2: Scanning

### Step: Rank Opportunities
workflow: rank_opportunities
inputs:
  tickers: $universe
  capital: $capital
  iv_rank_map: $phase1.iv_rank_map
  min_pop: $risk.min_pop
  max_trades: $risk.max_positions
outputs:
  proposals: $result.trades
gate:
  - len(proposals) > 0
on_fail: SKIP "No tradeable opportunities found"

## Phase 3: Monitoring

requires_positions: true

### Step: Monitor Positions
workflow: monitor_positions
inputs:
  positions: $positions
gate:
  - critical_count == 0
on_fail: ALERT "Critical: {critical_count} positions need action"
```

## Parser Behavior

- The `# Title` line (H1 heading) is ignored; only `##` and `###` headings are parsed
- Any line that does not match a recognized pattern is silently ignored
- Frontmatter is parsed with `yaml.safe_load`; if no `---` delimiters are found, frontmatter is empty and the entire file is treated as body
- Phase and step numbering is derived from document order, not from any explicit numbering in step headers
- If `on_fail` appears before any `gate:` block, it has no effect (there are no gates to apply it to)
- If `on_fail` is absent, all gates default to `on_fail: HALT` with an empty message
- Block parsing (`inputs:`, `outputs:`, `gate:`) ends when a new block starter, step header, phase header, or non-matching line is encountered
- Input/output key-value lines match the pattern `^(\w+):\s*(.+)` -- keys must be word characters only
- The `workflow` field value must correspond to a function name in `income_desk.workflow`. The runner maps this to a module via `_MODULE_MAP` and looks for a `*Request` class in that module
