"""Tests for scenario markdown parser."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from income_desk.scenarios.parser import (
    load_scenario_dir,
    load_scenario_file,
    parse_scenario_md,
)

FULL_SCENARIO = textwrap.dedent("""\
    ---
    key: black_monday
    name: Black Monday (-30% Flash Crash)
    category: crash
    severity: extreme
    historical_analog: 1987 Black Monday, 2020 March 16
    expected_duration_days: 1
    monte_carlo_paths: 10000
    ---

    # Black Monday (-30% Flash Crash)

    ## Narrative

    Extreme 1-day crash. Circuit breakers hit.

    ## Trigger Conditions

    - Single-day equity drop exceeds -7%
    - VIX spikes above 60

    ## Factor Shocks

    | Factor     | Shock   | Rationale                    |
    |------------|---------|------------------------------|
    | equity     | -30%    | Broad market crash           |
    | tech       | -15%    | High-beta tech leads down    |
    | rates      | +15%    | Flight to treasuries         |
    | volatility | +200%   | VIX triples                  |
    | commodity  | -10%    | Demand destruction           |
    | currency   | +10%    | USD safe haven               |

    ## IV Regime Shift

    | Metric          | Value | Rationale                    |
    |-----------------|-------|------------------------------|
    | iv_shift        | +35%  | Absolute IV increase         |
    | skew_steepening | +20%  | OTM puts expensive           |

    ## Cross-Asset Correlations

    All correlations go to 1.

    ## Trading Response

    Close all short premium.
""")


class TestParseFrontmatter:
    def test_parse_frontmatter(self):
        sd = parse_scenario_md(FULL_SCENARIO)
        assert sd.name == "Black Monday (-30% Flash Crash)"
        assert sd.category == "crash"
        assert sd.severity == "extreme"
        assert sd.historical_analog == "1987 Black Monday, 2020 March 16"
        assert sd.expected_duration_days == 1
        assert sd.monte_carlo_paths == 10000


class TestParseFactorShocks:
    def test_parse_factor_shocks(self):
        sd = parse_scenario_md(FULL_SCENARIO)
        assert sd.factor_shocks["equity"] == pytest.approx(-0.30)
        assert sd.factor_shocks["tech"] == pytest.approx(-0.15)
        assert sd.factor_shocks["rates"] == pytest.approx(0.15)
        assert sd.factor_shocks["volatility"] == pytest.approx(2.00)
        assert sd.factor_shocks["commodity"] == pytest.approx(-0.10)
        assert sd.factor_shocks["currency"] == pytest.approx(0.10)

    def test_parse_negative_shocks(self):
        md = textwrap.dedent("""\
            ---
            name: Test
            category: crash
            ---

            ## Factor Shocks

            | Factor | Shock | Note |
            |--------|-------|------|
            | equity | -10%  | down |
            | rates  | -0.05 | raw  |
        """)
        sd = parse_scenario_md(md)
        assert sd.factor_shocks["equity"] == pytest.approx(-0.10)
        assert sd.factor_shocks["rates"] == pytest.approx(-0.05)


class TestParseIVShift:
    def test_parse_iv_shift(self):
        sd = parse_scenario_md(FULL_SCENARIO)
        assert sd.iv_regime_shift == pytest.approx(0.35)

    def test_parse_missing_iv_section(self):
        md = textwrap.dedent("""\
            ---
            name: No IV
            category: crash
            ---

            ## Factor Shocks

            | Factor | Shock |
            |--------|-------|
            | equity | -5%   |
        """)
        sd = parse_scenario_md(md)
        assert sd.iv_regime_shift == 0.0


class TestParseNarrative:
    def test_parse_narrative(self):
        sd = parse_scenario_md(FULL_SCENARIO)
        assert sd.description == "Extreme 1-day crash. Circuit breakers hit."


class TestParseMissingSections:
    def test_parse_missing_factor_table(self):
        md = textwrap.dedent("""\
            ---
            name: Minimal
            category: custom
            ---

            ## Narrative

            Just a description, no shocks.
        """)
        sd = parse_scenario_md(md)
        assert sd.factor_shocks == {}

    def test_no_frontmatter_raises(self):
        with pytest.raises(ValueError, match="No YAML frontmatter"):
            parse_scenario_md("# No frontmatter here\n\nJust text.")


class TestLoadScenarioFile:
    def test_load_scenario_file(self, tmp_path: Path):
        f = tmp_path / "black_monday.scenario.md"
        f.write_text(FULL_SCENARIO, encoding="utf-8")
        key, sd = load_scenario_file(f)
        assert key == "black_monday"
        assert sd.name == "Black Monday (-30% Flash Crash)"
        assert sd.factor_shocks["equity"] == pytest.approx(-0.30)

    def test_load_scenario_file_key_from_filename(self, tmp_path: Path):
        md = textwrap.dedent("""\
            ---
            name: Test Scenario
            category: custom
            ---

            ## Narrative

            A test.
        """)
        f = tmp_path / "my_test.scenario.md"
        f.write_text(md, encoding="utf-8")
        key, sd = load_scenario_file(f)
        assert key == "my_test"


class TestLoadScenarioDir:
    def test_load_scenario_dir(self, tmp_path: Path):
        for name, cat in [("alpha", "crash"), ("beta", "rally")]:
            md = textwrap.dedent(f"""\
                ---
                key: {name}
                name: Scenario {name}
                category: {cat}
                ---

                ## Narrative

                Description for {name}.
            """)
            (tmp_path / f"{name}.scenario.md").write_text(md, encoding="utf-8")

        result = load_scenario_dir(tmp_path)
        assert len(result) == 2
        assert "alpha" in result
        assert "beta" in result
        assert result["alpha"].category == "crash"
        assert result["beta"].category == "rally"

    def test_load_empty_dir(self, tmp_path: Path):
        result = load_scenario_dir(tmp_path)
        assert result == {}
