"""Pre-built scenario definitions — macro events that stress-test portfolios.

Each scenario defines factor shocks and metadata. The engine applies these
to baseline market data using the factor model.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScenarioDef:
    """A macro scenario with factor shocks."""
    name: str
    description: str
    category: str                         # "crash", "rally", "rotation", "macro", "custom"
    factor_shocks: dict[str, float]       # factor_name -> shock_pct (decimal)
    iv_regime_shift: float = 0.0          # additional IV shift (decimal, e.g. 0.10 = +10% absolute)
    monte_carlo_paths: int = 1000         # for confidence intervals
    severity: str = "moderate"            # "mild", "moderate", "severe", "extreme"
    historical_analog: str = ""           # reference event
    expected_duration_days: int = 5       # how long this plays out


# ── Pre-built scenarios ─────────────────────────────────────────────────

SCENARIOS: dict[str, ScenarioDef] = {

    # === EQUITY CRASHES ===

    "sp500_down_5": ScenarioDef(
        name="S&P 500 -5% Correction",
        description="Standard market pullback. Tech leads down, bonds rally, vol spikes.",
        category="crash",
        factor_shocks={"equity": -0.05, "rates": 0.02, "volatility": 0.30, "tech": -0.03},
        iv_regime_shift=0.05,
        severity="mild",
        historical_analog="Typical quarterly pullback",
        expected_duration_days=5,
    ),

    "sp500_down_10": ScenarioDef(
        name="S&P 500 -10% Correction",
        description="Sharp correction. Flight to safety — bonds and gold up, vol doubles.",
        category="crash",
        factor_shocks={"equity": -0.10, "rates": 0.05, "volatility": 0.60, "commodity": 0.05, "tech": -0.05},
        iv_regime_shift=0.10,
        severity="moderate",
        historical_analog="2022 Q1 correction, 2018 Q4 sell-off",
        expected_duration_days=15,
    ),

    "sp500_down_20": ScenarioDef(
        name="S&P 500 -20% Bear Market",
        description="Bear market. Everything sells except treasuries. VIX > 40.",
        category="crash",
        factor_shocks={"equity": -0.20, "rates": 0.10, "volatility": 1.00, "commodity": -0.05, "tech": -0.10, "currency": 0.05},
        iv_regime_shift=0.20,
        severity="severe",
        historical_analog="2020 COVID crash, 2022 bear market",
        expected_duration_days=30,
        monte_carlo_paths=5000,
    ),

    "black_monday": ScenarioDef(
        name="Black Monday (-30% Flash Crash)",
        description="Extreme 1-day crash. Circuit breakers hit. All correlations go to 1.",
        category="crash",
        factor_shocks={"equity": -0.30, "rates": 0.15, "volatility": 2.00, "commodity": -0.10, "tech": -0.15, "currency": 0.10},
        iv_regime_shift=0.35,
        severity="extreme",
        historical_analog="1987 Black Monday, 2020 March 16",
        expected_duration_days=1,
        monte_carlo_paths=10000,
    ),

    # === INDIA-SPECIFIC ===

    "nifty_down_10": ScenarioDef(
        name="NIFTY -10% + INR Depreciation",
        description="India correction with FII outflows. Rupee weakens, banks lead down.",
        category="crash",
        factor_shocks={"equity": -0.10, "rates": 0.03, "volatility": 0.50, "currency": -0.05},
        iv_regime_shift=0.08,
        severity="moderate",
        historical_analog="2024 election volatility, 2022 FII sell-off",
        expected_duration_days=10,
    ),

    "rbi_rate_hike": ScenarioDef(
        name="RBI Surprise Rate Hike",
        description="Unexpected 50bp rate hike. Banks rally, rate-sensitive sectors fall.",
        category="macro",
        factor_shocks={"equity": -0.03, "rates": 0.15, "volatility": 0.20, "currency": 0.03},
        iv_regime_shift=0.03,
        severity="mild",
        historical_analog="2022 surprise rate hike cycle",
        expected_duration_days=3,
    ),

    "fii_selloff": ScenarioDef(
        name="FII Mass Selling",
        description="Foreign institutional investors dump India. Broad weakness, INR falls.",
        category="crash",
        factor_shocks={"equity": -0.08, "rates": 0.02, "volatility": 0.40, "currency": -0.08, "tech": -0.05},
        iv_regime_shift=0.06,
        severity="moderate",
        historical_analog="2024 Q4 FII outflows",
        expected_duration_days=20,
    ),

    # === COMMODITY SCENARIOS ===

    "gold_crash_10": ScenarioDef(
        name="Gold -10% Crash",
        description="Gold dumps on rate fears. Commodity sector weak, USD rallies.",
        category="crash",
        factor_shocks={"commodity": -0.15, "rates": -0.05, "equity": 0.02, "currency": 0.05},
        severity="moderate",
        historical_analog="2013 gold crash, 2022 rate hike gold sell-off",
        expected_duration_days=10,
    ),

    "commodity_meltup": ScenarioDef(
        name="Commodity Super-Cycle Meltup",
        description="Oil, gold, metals all surge. Inflationary boom, energy leads.",
        category="rally",
        factor_shocks={"commodity": 0.20, "equity": 0.03, "rates": -0.05, "volatility": 0.15, "currency": -0.03},
        iv_regime_shift=0.03,
        severity="moderate",
        historical_analog="2021-2022 commodity rally",
        expected_duration_days=30,
    ),

    # === RATE SCENARIOS ===

    "rates_shock_up": ScenarioDef(
        name="10Y Yield +100bp Spike",
        description="Bond crash. Rates surge, growth stocks hammered, banks rally.",
        category="macro",
        factor_shocks={"rates": -0.15, "equity": -0.05, "tech": -0.10, "volatility": 0.25},
        iv_regime_shift=0.05,
        severity="moderate",
        historical_analog="2022 rate shock, 2023 Q3 long-end sell-off",
        expected_duration_days=15,
    ),

    "rates_collapse": ScenarioDef(
        name="Rate Collapse / Flight to Safety",
        description="Recession fears crash rates. Bonds rally, equities sell, gold up.",
        category="macro",
        factor_shocks={"rates": 0.20, "equity": -0.08, "volatility": 0.40, "commodity": 0.10, "tech": -0.03},
        iv_regime_shift=0.08,
        severity="moderate",
        historical_analog="2019 rate inversion, 2020 March",
        expected_duration_days=20,
    ),

    # === INFLATION / DEFLATION ===

    "inflation_surge": ScenarioDef(
        name="Inflation Surge (CPI +2%)",
        description="Surprise inflation. Rates spike, growth hammered, commodities rally.",
        category="macro",
        factor_shocks={"rates": -0.10, "equity": -0.05, "commodity": 0.15, "tech": -0.08, "volatility": 0.20},
        iv_regime_shift=0.05,
        severity="moderate",
        historical_analog="2022 June CPI shock",
        expected_duration_days=10,
    ),

    "deflation_scare": ScenarioDef(
        name="Deflation Scare",
        description="Demand collapse. Commodities crash, bonds rally, equities mixed.",
        category="macro",
        factor_shocks={"commodity": -0.15, "rates": 0.15, "equity": -0.03, "volatility": 0.15, "tech": 0.05},
        iv_regime_shift=0.03,
        severity="mild",
        historical_analog="2015 China devaluation scare",
        expected_duration_days=10,
    ),

    # === ROTATION / RALLY ===

    "tech_rotation": ScenarioDef(
        name="Tech-to-Value Rotation",
        description="Money flows from tech to value/cyclicals. QQQ down, IWM up.",
        category="rotation",
        factor_shocks={"tech": -0.12, "equity": 0.02, "rates": -0.03, "commodity": 0.05},
        severity="moderate",
        historical_analog="2021 Q1 rotation, 2022 value outperformance",
        expected_duration_days=20,
    ),

    "risk_on_rally": ScenarioDef(
        name="Risk-On Rally (+8%)",
        description="Broad market rally. Vol compresses, bonds sell, everything up.",
        category="rally",
        factor_shocks={"equity": 0.08, "rates": -0.03, "volatility": -0.30, "tech": 0.05, "commodity": 0.03},
        iv_regime_shift=-0.05,
        severity="moderate",
        historical_analog="2023 Q4 Santa rally, 2024 AI boom",
        expected_duration_days=20,
    ),

    "india_budget_rally": ScenarioDef(
        name="India Budget Rally",
        description="Pro-growth budget. Banks, infra rally. FII inflows resume.",
        category="rally",
        factor_shocks={"equity": 0.05, "rates": -0.02, "volatility": -0.20, "currency": 0.03},
        iv_regime_shift=-0.03,
        severity="mild",
        historical_analog="2024 interim budget rally",
        expected_duration_days=10,
    ),

    # === TAIL RISKS ===

    "correlation_1": ScenarioDef(
        name="Correlation Spike (All Assets Down)",
        description="Liquidity crisis. Everything sells — stocks, bonds, gold, crypto. Cash is king.",
        category="crash",
        factor_shocks={"equity": -0.15, "rates": -0.05, "volatility": 1.50, "commodity": -0.10, "tech": -0.10, "currency": 0.10},
        iv_regime_shift=0.25,
        severity="extreme",
        historical_analog="2020 March liquidity crisis, 2008 Lehman",
        expected_duration_days=5,
        monte_carlo_paths=10000,
    ),

    "geopolitical_shock": ScenarioDef(
        name="Geopolitical Shock",
        description="War escalation. Oil spikes, equities sell, gold and bonds bid.",
        category="macro",
        factor_shocks={"equity": -0.07, "commodity": 0.25, "rates": 0.05, "volatility": 0.50, "currency": -0.03},
        iv_regime_shift=0.08,
        severity="severe",
        historical_analog="2022 Russia-Ukraine, 2024 Middle East",
        expected_duration_days=10,
    ),
}


def list_scenarios(category: str | None = None) -> list[dict]:
    """List available scenarios with metadata.

    Args:
        category: Filter by category (crash, rally, rotation, macro). None = all.

    Returns:
        List of dicts with name, description, severity, category.
    """
    results = []
    for key, s in sorted(SCENARIOS.items()):
        if category and s.category != category:
            continue
        results.append({
            "key": key,
            "name": s.name,
            "description": s.description,
            "category": s.category,
            "severity": s.severity,
            "factors": {k: f"{v:+.0%}" for k, v in s.factor_shocks.items()},
            "historical_analog": s.historical_analog,
        })
    return results
