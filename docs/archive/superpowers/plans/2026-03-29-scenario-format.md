# Scenario MD Format Standardization Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert 18 macro scenarios from Python dataclass to standardized `.scenario.md` files with a parser that loads them back into `ScenarioDef` objects.

**Architecture:** Each scenario becomes a markdown file with YAML frontmatter (machine fields) + structured sections (human context). A parser reads frontmatter + Factor Shocks table to produce `ScenarioDef`. Existing `definitions.py` becomes a thin loader that calls the parser. Backward compatible — all existing code that imports `SCENARIOS` keeps working.

**Tech Stack:** Python 3.12, PyYAML, existing `ScenarioDef` dataclass, `tabulate` for report formatting

---

## File Structure

| File | Responsibility |
|------|---------------|
| `income_desk/scenarios/formats/` | Directory for all `.scenario.md` files (18 files) |
| `income_desk/scenarios/parser.py` | Parse `.scenario.md` → `ScenarioDef`, load directory |
| `income_desk/scenarios/definitions.py` | Modified: loads from `.scenario.md` files, keeps `SCENARIOS` dict |
| `tests/test_scenario_parser.py` | Parser tests |

---

### Task 1: Parser — read `.scenario.md` into `ScenarioDef`

**Files:**
- Create: `income_desk/scenarios/parser.py`
- Create: `tests/test_scenario_parser.py`

- [ ] **Step 1: Write test for parsing YAML frontmatter**

```python
# tests/test_scenario_parser.py
from income_desk.scenarios.parser import parse_scenario_md

SAMPLE_MD = '''---
key: test_crash
name: Test Crash Scenario
category: crash
severity: moderate
historical_analog: 2020 COVID crash
expected_duration_days: 15
monte_carlo_paths: 1000
---

# Test Crash Scenario

## Narrative

A test crash scenario for parser validation.

## Factor Shocks

| Factor     | Shock   | Rationale              |
|------------|---------|------------------------|
| equity     | -10%    | Broad market sell-off  |
| rates      | +5%     | Flight to treasuries   |
| volatility | +60%    | VIX doubles            |

## IV Regime Shift

| Metric   | Value | Rationale          |
|----------|-------|--------------------|
| iv_shift | +10%  | Vol regime change  |
'''

def test_parse_frontmatter():
    sd = parse_scenario_md(SAMPLE_MD)
    assert sd.name == "Test Crash Scenario"
    assert sd.category == "crash"
    assert sd.severity == "moderate"
    assert sd.expected_duration_days == 15
    assert sd.monte_carlo_paths == 1000
    assert sd.historical_analog == "2020 COVID crash"

def test_parse_factor_shocks():
    sd = parse_scenario_md(SAMPLE_MD)
    assert sd.factor_shocks["equity"] == -0.10
    assert sd.factor_shocks["rates"] == 0.05
    assert sd.factor_shocks["volatility"] == 0.60

def test_parse_iv_shift():
    sd = parse_scenario_md(SAMPLE_MD)
    assert sd.iv_regime_shift == 0.10
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `.venv_312/Scripts/python -m pytest tests/test_scenario_parser.py -v`
Expected: FAIL (parser doesn't exist)

- [ ] **Step 3: Implement parser**

```python
# income_desk/scenarios/parser.py
"""Parse .scenario.md files into ScenarioDef objects."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from income_desk.scenarios.definitions import ScenarioDef


def parse_scenario_md(text: str) -> ScenarioDef:
    """Parse a .scenario.md string into a ScenarioDef."""
    frontmatter, body = _split_frontmatter(text)
    meta = yaml.safe_load(frontmatter)

    factor_shocks = _parse_factor_table(body)
    iv_shift = _parse_iv_shift(body)

    return ScenarioDef(
        name=meta.get("name", ""),
        description=_parse_narrative(body),
        category=meta.get("category", "custom"),
        factor_shocks=factor_shocks,
        iv_regime_shift=iv_shift,
        monte_carlo_paths=meta.get("monte_carlo_paths", 1000),
        severity=meta.get("severity", "moderate"),
        historical_analog=meta.get("historical_analog", ""),
        expected_duration_days=meta.get("expected_duration_days", 5),
    )


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split YAML frontmatter from markdown body."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        raise ValueError("No YAML frontmatter found (expected --- delimiters)")
    return match.group(1), match.group(2)


def _parse_factor_table(body: str) -> dict[str, float]:
    """Extract Factor Shocks table → {factor: decimal_shock}."""
    factors = {}
    in_table = False
    for line in body.splitlines():
        if "## Factor Shocks" in line:
            in_table = True
            continue
        if in_table and line.startswith("##"):
            break
        if in_table and "|" in line and "---" not in line and "Factor" not in line:
            cols = [c.strip() for c in line.split("|") if c.strip()]
            if len(cols) >= 2:
                factor = cols[0].lower()
                shock_str = cols[1].replace("%", "").replace("+", "").strip()
                try:
                    factors[factor] = float(shock_str) / 100.0
                except ValueError:
                    pass
    return factors


def _parse_iv_shift(body: str) -> float:
    """Extract iv_shift from IV Regime Shift table."""
    in_table = False
    for line in body.splitlines():
        if "## IV Regime Shift" in line:
            in_table = True
            continue
        if in_table and line.startswith("##"):
            break
        if in_table and "|" in line and "iv_shift" in line.lower():
            cols = [c.strip() for c in line.split("|") if c.strip()]
            if len(cols) >= 2:
                val_str = cols[1].replace("%", "").replace("+", "").strip()
                try:
                    return float(val_str) / 100.0
                except ValueError:
                    pass
    return 0.0


def _parse_narrative(body: str) -> str:
    """Extract text under ## Narrative section."""
    lines = []
    in_narrative = False
    for line in body.splitlines():
        if "## Narrative" in line:
            in_narrative = True
            continue
        if in_narrative and line.startswith("##"):
            break
        if in_narrative and line.strip():
            lines.append(line.strip())
    return " ".join(lines)


def load_scenario_file(path: Path) -> tuple[str, ScenarioDef]:
    """Load a single .scenario.md file. Returns (key, ScenarioDef)."""
    text = path.read_text(encoding="utf-8")
    fm, _ = _split_frontmatter(text)
    meta = yaml.safe_load(fm)
    key = meta.get("key", path.stem.replace(".scenario", ""))
    return key, parse_scenario_md(text)


def load_scenario_dir(directory: Path) -> dict[str, ScenarioDef]:
    """Load all .scenario.md files from a directory."""
    scenarios = {}
    if not directory.exists():
        return scenarios
    for path in sorted(directory.glob("*.scenario.md")):
        try:
            key, sd = load_scenario_file(path)
            scenarios[key] = sd
        except Exception:
            pass
    return scenarios
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `.venv_312/Scripts/python -m pytest tests/test_scenario_parser.py -v`
Expected: PASS

- [ ] **Step 5: Add tests for file/directory loading**

```python
def test_load_scenario_file(tmp_path):
    p = tmp_path / "test.scenario.md"
    p.write_text(SAMPLE_MD)
    key, sd = load_scenario_file(p)
    assert key == "test_crash"
    assert sd.name == "Test Crash Scenario"

def test_load_scenario_dir(tmp_path):
    p1 = tmp_path / "crash1.scenario.md"
    p1.write_text(SAMPLE_MD)
    p2 = tmp_path / "crash2.scenario.md"
    p2.write_text(SAMPLE_MD.replace("test_crash", "test_crash2").replace("Test Crash", "Another Crash"))
    result = load_scenario_dir(tmp_path)
    assert len(result) == 2

def test_load_empty_dir(tmp_path):
    result = load_scenario_dir(tmp_path)
    assert result == {}
```

- [ ] **Step 6: Run all tests — verify pass**
- [ ] **Step 7: Commit**

```bash
git add income_desk/scenarios/parser.py tests/test_scenario_parser.py
git commit -m "feat: scenario markdown parser — .scenario.md to ScenarioDef"
```

---

### Task 2: Convert all 18 scenarios to `.scenario.md` files

**Files:**
- Create: `income_desk/scenarios/formats/` (directory)
- Create: 18 `.scenario.md` files inside it

Each file follows the standardized format. The key fields come from `definitions.py`, enriched with Narrative, Trigger Conditions, Cross-Asset Correlations, Impact by Asset Class, Trading Response, and Historical Data Points.

- [ ] **Step 1: Create the formats directory**

```bash
mkdir -p income_desk/scenarios/formats
```

- [ ] **Step 2: Write a conversion script to generate all 18 files**

Create a temporary script that reads `SCENARIOS` from `definitions.py` and writes `.scenario.md` files. For each scenario:
- YAML frontmatter from dataclass fields
- Factor Shocks table from `factor_shocks` dict
- IV Regime Shift table from `iv_regime_shift`
- Narrative from `description`
- Add empty sections for: Trigger Conditions, Cross-Asset Correlations, Impact by Asset Class, Trading Response, Historical Data Points

The conversion script is disposable — run it once, verify files, delete script.

- [ ] **Step 3: Run the conversion**
- [ ] **Step 4: Verify all 18 files are valid — parser round-trips**

```python
# Quick verification
from income_desk.scenarios.parser import load_scenario_dir
from pathlib import Path
scenarios = load_scenario_dir(Path("income_desk/scenarios/formats"))
assert len(scenarios) == 18
for key, sd in scenarios.items():
    assert sd.name, f"{key} missing name"
    assert sd.factor_shocks, f"{key} missing factor_shocks"
    print(f"  {key}: {sd.name} — {len(sd.factor_shocks)} factors")
```

- [ ] **Step 5: Commit all scenario files**

```bash
git add income_desk/scenarios/formats/
git commit -m "feat: 18 macro scenarios in standardized .scenario.md format"
```

---

### Task 3: Wire definitions.py to load from `.scenario.md` files

**Files:**
- Modify: `income_desk/scenarios/definitions.py`

- [ ] **Step 1: Add loader that merges MD files with existing SCENARIOS**

Keep existing `SCENARIOS` dict as fallback. Add `load_all_scenarios()` that loads from MD files first, then fills gaps from the Python dict.

```python
# At bottom of definitions.py, replace or augment SCENARIOS loading:

def load_all_scenarios() -> dict[str, ScenarioDef]:
    """Load scenarios from .scenario.md files, fall back to Python definitions."""
    from pathlib import Path
    from income_desk.scenarios.parser import load_scenario_dir

    formats_dir = Path(__file__).parent / "formats"
    md_scenarios = load_scenario_dir(formats_dir)

    # Merge: MD files take precedence, Python dict fills gaps
    merged = dict(SCENARIOS)
    merged.update(md_scenarios)
    return merged
```

- [ ] **Step 2: Verify backward compatibility**

Run: `.venv_312/Scripts/python -c "from income_desk.scenarios.definitions import SCENARIOS, load_all_scenarios; s = load_all_scenarios(); print(f'{len(s)} scenarios loaded'); assert len(s) >= 18"`

- [ ] **Step 3: Run existing scenario tests**

Run: `.venv_312/Scripts/python -m pytest tests/ -k scenario -v`
Expected: All existing tests still pass

- [ ] **Step 4: Commit**

```bash
git add income_desk/scenarios/definitions.py
git commit -m "feat: definitions.py loads from .scenario.md files with Python fallback"
```

---

### Task 4: Enrich scenario files with human context

**Files:**
- Modify: All 18 `.scenario.md` files in `income_desk/scenarios/formats/`

Task 2 creates skeleton files with Factor Shocks and Narrative. This task enriches them with the full human-readable sections that make scenarios useful as documentation and playbooks.

For each scenario, add:
- **Trigger Conditions**: When would this scenario activate? (2-3 bullet points)
- **Cross-Asset Correlations**: Normal vs scenario correlation table (3-4 key pairs)
- **Impact by Asset Class**: What happens to index options, single-stock, bonds, gold, cash
- **Trading Response**: Immediate + follow-up actions with position sizing guidance
- **Historical Data Points**: 2-4 real dates with SPY/NIFTY move, VIX peak, recovery days

- [ ] **Step 1: Enrich crash scenarios (4 files)**

`sp500_down_5.scenario.md`, `sp500_down_10.scenario.md`, `sp500_down_20.scenario.md`, `black_monday.scenario.md`

- [ ] **Step 2: Enrich India scenarios (3 files)**

`nifty_down_10.scenario.md`, `rbi_rate_hike.scenario.md`, `fii_selloff.scenario.md`

- [ ] **Step 3: Enrich commodity + rate + inflation scenarios (6 files)**

`gold_crash_10.scenario.md`, `commodity_meltup.scenario.md`, `rates_shock_up.scenario.md`, `rates_collapse.scenario.md`, `inflation_surge.scenario.md`, `deflation_scare.scenario.md`

- [ ] **Step 4: Enrich rotation + rally + tail risk scenarios (5 files)**

`tech_rotation.scenario.md`, `risk_on_rally.scenario.md`, `india_budget_rally.scenario.md`, `correlation_1.scenario.md`, `geopolitical_shock.scenario.md`

- [ ] **Step 5: Verify parser still loads all enriched files**

Run: `.venv_312/Scripts/python -c "from income_desk.scenarios.parser import load_scenario_dir; from pathlib import Path; s = load_scenario_dir(Path('income_desk/scenarios/formats')); print(f'{len(s)} loaded'); assert len(s) == 18"`

- [ ] **Step 6: Commit**

```bash
git add income_desk/scenarios/formats/
git commit -m "docs: enriched 18 scenarios with correlations, impacts, trading playbooks"
```

---

### Task 5: Final verification

- [ ] **Step 1: Run full test suite**

Run: `.venv_312/Scripts/python -m pytest tests/ -x -q -m "not integration"`
Expected: All tests pass, no regressions

- [ ] **Step 2: Run harness to verify stress test still works**

Run: `.venv_312/Scripts/python -m challenge.harness --phase=5 --market=US 2>&1 | tail -30`
Expected: Phase 5 stress test runs with all scenarios

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: scenario format standardization complete — 18 .scenario.md files + parser"
```
