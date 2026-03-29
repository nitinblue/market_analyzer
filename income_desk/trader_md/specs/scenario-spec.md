# Scenario Specification

**Version:** 1.0
**Status:** Draft
**File extension:** `.scenario.md`

## Overview

A scenario file defines a macro-economic stress scenario for portfolio risk analysis. Each file describes a set of factor shocks (equity, rates, volatility, etc.), an IV regime shift, and narrative context. The parser extracts structured data from YAML frontmatter and specific markdown tables, while ignoring human-readable sections like Trigger Conditions, Correlations, and Trading Response.

Scenario files are consumed by the stress testing engine (`stress_test_portfolio` workflow) to evaluate portfolio impact under hypothetical market conditions.

## File Structure

```
---
key: <scenario_key>
name: <display_name>
category: <category>
severity: <severity_level>
historical_analog: <reference_event>
expected_duration_days: <integer>
monte_carlo_paths: <integer>
---

# Title (ignored by parser)

## Narrative

<description text -- becomes the scenario description>

## Trigger Conditions

<human-readable, ignored by parser>

## Factor Shocks

| Factor     | Shock    | Rationale                    |
|------------|----------|------------------------------|
| equity     | -10%     | Broad market sell-off        |
| rates      | +5%      | Flight to safety             |
| volatility | +60%     | Vol expansion                |

## IV Regime Shift

| Metric          | Value  | Rationale                    |
|-----------------|--------|------------------------------|
| iv_shift        | +10%   | Significant vol expansion    |
| skew_steepening | +8%    | OTM put skew richens         |

## Cross-Asset Correlations

<human-readable, ignored by parser>

## Impact by Asset Class

<human-readable, ignored by parser>

## Trading Response

<human-readable, ignored by parser>

## Historical Data Points

<human-readable, ignored by parser>
```

## Frontmatter Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| key | string | no | file stem (minus `.scenario`) | Unique identifier used as the scenario lookup key |
| name | string | no | `""` | Human-readable scenario name |
| category | string | no | `"custom"` | One of: `"crash"`, `"rally"`, `"rotation"`, `"macro"`, `"custom"` |
| severity | string | no | `"moderate"` | One of: `"mild"`, `"moderate"`, `"severe"`, `"extreme"` |
| historical_analog | string | no | `""` | Reference to historical event(s) |
| expected_duration_days | integer | no | `5` | How many days the scenario plays out |
| monte_carlo_paths | integer | no | `1000` | Number of Monte Carlo simulation paths |

## Body Sections

### Section: Narrative (parsed)

Content between `## Narrative` and the next `##` heading becomes the scenario's `description` field. If no Narrative section exists, the `description` frontmatter field is used as fallback.

### Section: Factor Shocks (parsed)

A markdown table with at least two columns: `Factor` and `Shock`. The parser:

1. Finds the `## Factor Shocks` heading
2. Extracts all table rows (lines starting with `|`)
3. Skips the header row (first data row) and separator rows (`| --- | --- |`)
4. For each remaining row: column 0 is the factor name (lowercased), column 1 is the shock value
5. Shock values are parsed as percentages: `"+10%"` becomes `0.10`, `"-5%"` becomes `-0.05`
6. Plain decimals are also accepted: `"0.10"`, `"-0.05"`
7. Unicode minus signs are normalized to ASCII

Common factor names: `equity`, `rates`, `volatility`, `commodity`, `tech`, `currency`, `credit`.

### Section: IV Regime Shift (parsed)

A markdown table with at least two columns: `Metric` and `Value`. The parser:

1. Finds the `## IV Regime Shift` heading
2. Extracts table rows, skipping header and separator rows
3. Looks for a row where column 0 (lowercased) equals `"iv_shift"`
4. Parses column 1 as a percentage (same rules as Factor Shocks)
5. Returns `0.0` if no `iv_shift` row is found

Other rows in this table (e.g., `skew_steepening`) are ignored by the parser.

### Ignored Sections

These sections are for human consumption and are not parsed:

- `## Trigger Conditions`
- `## Cross-Asset Correlations`
- `## Impact by Asset Class`
- `## Trading Response`
- `## Historical Data Points`

Any other `##` sections are also ignored.

## Examples

### Minimal Example

```markdown
---
key: custom_test
name: "Custom Test Scenario"
category: custom
severity: mild
---

## Factor Shocks

| Factor | Shock | Rationale |
|--------|-------|-----------|
| equity | -5%   | Test      |
```

### Full Example

```markdown
---
key: sp500_down_10
name: "S&P 500 -10% Correction"
category: crash
severity: moderate
historical_analog: "2022 Q1 correction, 2018 Q4 sell-off"
expected_duration_days: 15
monte_carlo_paths: 1000
---

# S&P 500 -10% Correction

## Narrative

A sharp 10% correction that shakes out weak hands and triggers systematic selling.
Flight to safety is pronounced. The correction unfolds over 2-3 weeks.

## Trigger Conditions

- SPX drops 3%+ on two consecutive sessions
- VIX breaks above 30

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| equity     | -10%     | Broad market sell-off                  |
| rates      | +5%      | Strong flight to safety into treasuries|
| volatility | +60%     | Vol doubles from baseline              |
| commodity  | +5%      | Gold/safe-haven bid                    |
| tech       | -5%      | Growth underperforms on higher vol     |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +10%   | Significant vol expansion              |
| skew_steepening | +8%    | OTM put skew richens sharply           |

## Trading Response

- Immediate: Close or roll any short puts that are breached.
- Day 5-10: Begin selling elevated premium with wider wings.
```

## Parser Behavior

- Frontmatter is split by the first two `---` delimiters. If fewer than 3 parts result, a `ValueError` is raised
- The `key` field falls back to the filename stem with `.scenario` suffix removed (e.g., `sp500_down_10.scenario.md` yields key `sp500_down_10`)
- Section extraction uses `## <Heading>` matching (case-sensitive) and captures text until the next `## ` heading or end of file
- Table parsing treats any line starting with `|` as a potential row. Separator rows (cells matching `^[-:]+$`) are skipped. The first non-separator row is treated as the header and skipped
- Percentage parsing: strips whitespace, normalizes unicode minus, removes trailing `%` and divides by 100. Falls back to `float()` for plain decimal values
- If `## Factor Shocks` is absent, `factor_shocks` is an empty dict
- If `## IV Regime Shift` is absent or contains no `iv_shift` row, `iv_regime_shift` is `0.0`
- If `## Narrative` is absent and no `description` in frontmatter, `description` is `""`
- The `load_scenario_dir()` function loads all `*.scenario.md` files from a directory, sorted by filename
