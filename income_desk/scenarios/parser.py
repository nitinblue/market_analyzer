"""Parse .scenario.md files into ScenarioDef objects.

Markdown scenario files use YAML frontmatter for metadata and markdown
tables for factor shocks and IV regime shifts. Human-readable sections
(Trigger Conditions, Correlations, etc.) are ignored.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from income_desk.scenarios.definitions import ScenarioDef


def _parse_pct(value: str) -> float:
    """Convert a percentage string to a decimal float.

    Handles: "+30%", "-10%", "30%", "-0.10", "+0.35", "0.10".
    """
    s = value.strip().replace("\u2212", "-")  # unicode minus → ASCII minus
    if s.endswith("%"):
        return float(s[:-1]) / 100.0
    return float(s)


def _extract_section(text: str, heading: str) -> str | None:
    """Extract content between a ## heading and the next ## heading (or EOF)."""
    pattern = rf"^##\s+{re.escape(heading)}\s*$"
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        return None
    start = match.end()
    next_heading = re.search(r"^##\s+", text[start:], re.MULTILINE)
    if next_heading:
        return text[start : start + next_heading.start()].strip()
    return text[start:].strip()


def _parse_table_rows(section: str) -> list[list[str]]:
    """Parse markdown table rows, skipping header separator lines."""
    rows: list[list[str]] = []
    lines = section.strip().splitlines()
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        # Skip separator rows (| --- | --- |)
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.match(r"^[-:]+$", c) for c in cells):
            continue
        rows.append(cells)
    return rows


def _parse_factor_shocks(text: str) -> dict[str, float]:
    """Extract factor shocks from the ## Factor Shocks table."""
    section = _extract_section(text, "Factor Shocks")
    if not section:
        return {}

    rows = _parse_table_rows(section)
    shocks: dict[str, float] = {}
    # Skip header row (first row with column names)
    for row in rows[1:]:
        if len(row) < 2:
            continue
        factor = row[0].strip().lower()
        shock = _parse_pct(row[1])
        shocks[factor] = shock
    return shocks


def _parse_iv_shift(text: str) -> float:
    """Extract iv_shift value from ## IV Regime Shift table."""
    section = _extract_section(text, "IV Regime Shift")
    if not section:
        return 0.0

    rows = _parse_table_rows(section)
    for row in rows[1:]:  # skip header
        if len(row) < 2:
            continue
        metric = row[0].strip().lower()
        if metric == "iv_shift":
            return _parse_pct(row[1])
    return 0.0


def _parse_narrative(text: str) -> str:
    """Extract description from ## Narrative section."""
    section = _extract_section(text, "Narrative")
    if not section:
        return ""
    return section


def parse_scenario_md(text: str) -> ScenarioDef:
    """Parse a .scenario.md markdown string into a ScenarioDef.

    Args:
        text: Full markdown content with YAML frontmatter.

    Returns:
        ScenarioDef populated from frontmatter + parsed sections.

    Raises:
        ValueError: If no YAML frontmatter delimiters found.
    """
    # Split frontmatter
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("No YAML frontmatter found (missing --- delimiters)")

    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2]

    # Parse structured sections
    factor_shocks = _parse_factor_shocks(body)
    iv_shift = _parse_iv_shift(body)
    description = _parse_narrative(body) or fm.get("description", "")

    return ScenarioDef(
        name=fm.get("name", ""),
        description=description,
        category=fm.get("category", "custom"),
        factor_shocks=factor_shocks,
        iv_regime_shift=iv_shift,
        monte_carlo_paths=fm.get("monte_carlo_paths", 1000),
        severity=fm.get("severity", "moderate"),
        historical_analog=fm.get("historical_analog", ""),
        expected_duration_days=fm.get("expected_duration_days", 5),
    )


def load_scenario_file(path: Path) -> tuple[str, ScenarioDef]:
    """Load a single .scenario.md file.

    Args:
        path: Path to the .scenario.md file.

    Returns:
        Tuple of (key, ScenarioDef). Key comes from frontmatter ``key``
        field, falling back to the filename stem (minus .scenario suffix).
    """
    text = path.read_text(encoding="utf-8")
    scenario = parse_scenario_md(text)

    # Extract key from frontmatter
    parts = text.split("---", 2)
    fm = yaml.safe_load(parts[1]) or {} if len(parts) >= 3 else {}
    key = fm.get("key", "")
    if not key:
        # Fallback: filename stem without .scenario
        stem = path.stem
        if stem.endswith(".scenario"):
            stem = stem[: -len(".scenario")]
        key = stem

    return key, scenario


def load_scenario_dir(directory: Path) -> dict[str, ScenarioDef]:
    """Load all .scenario.md files from a directory.

    Args:
        directory: Directory to scan for .scenario.md files.

    Returns:
        Dict mapping scenario key to ScenarioDef.
    """
    scenarios: dict[str, ScenarioDef] = {}
    if not directory.is_dir():
        return scenarios

    for path in sorted(directory.glob("*.scenario.md")):
        key, scenario = load_scenario_file(path)
        scenarios[key] = scenario

    return scenarios
