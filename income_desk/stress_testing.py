"""Portfolio stress testing — scenario-based impact analysis.

Answers: "What happens to my portfolio if market drops 3%?"
Pure computation from position data + scenario parameters.
eTrading provides positions, MA computes impact per position and portfolio-level.

Three types of stress tests:
1. Market shock: underlying price moves +/-X%
2. Volatility shock: IV expands/contracts by X points
3. Combined: price + vol + time (most realistic)
"""

from __future__ import annotations

import math
from datetime import date
from enum import StrEnum

from pydantic import BaseModel

from income_desk.risk import PortfolioPosition


# ── Enums ────────────────────────────────────────────────────────────────────


class ScenarioType(StrEnum):
    MARKET_SHOCK = "market_shock"       # Price moves +/-X%
    VOL_SHOCK = "vol_shock"             # IV changes +/-X points
    COMBINED = "combined"                # Price + vol + time
    HISTORICAL = "historical"            # Replay a historical event
    CUSTOM = "custom"                    # User-defined


class PredefinedScenario(StrEnum):
    """Named scenarios traders can run quickly."""
    MARKET_DOWN_1 = "market_down_1pct"
    MARKET_DOWN_3 = "market_down_3pct"
    MARKET_DOWN_5 = "market_down_5pct"
    MARKET_DOWN_10 = "market_down_10pct"
    MARKET_UP_3 = "market_up_3pct"
    VIX_SPIKE_50 = "vix_spike_50pct"     # VIX jumps 50% (from 20 to 30)
    VIX_SPIKE_100 = "vix_spike_100pct"   # VIX doubles (from 20 to 40)
    RATE_SHOCK = "rate_shock"            # 10Y yield +50bp
    FLASH_CRASH = "flash_crash"          # -7% in 1 day, VIX triples
    BLACK_MONDAY = "black_monday"        # -20%, VIX to 80
    COVID_MARCH = "covid_march_2020"     # -12% week, VIX to 65
    INDIA_CRASH = "india_crash"          # NIFTY -5%, India VIX doubles
    FED_SURPRISE = "fed_surprise"        # -2%, yields +30bp, dollar +2%


# ── Models ───────────────────────────────────────────────────────────────────


class ScenarioParams(BaseModel):
    """Parameters for a stress test scenario."""
    name: str
    scenario_type: ScenarioType
    price_shock_pct: float = 0.0        # -5.0 = market drops 5%
    vol_shock_pct: float = 0.0          # +50.0 = IV increases 50% (relative)
    vol_shock_points: float = 0.0       # +10.0 = IV increases 10 points (absolute)
    time_decay_days: int = 0            # Days of theta decay to apply
    rate_shock_bp: float = 0.0          # Yield change in basis points
    dollar_shock_pct: float = 0.0       # USD strength change %
    description: str = ""


class PositionImpact(BaseModel):
    """Impact of a scenario on a single position."""
    ticker: str
    structure_type: str
    current_value: float            # Current P&L or mark
    stressed_value: float           # P&L under scenario
    impact_dollars: float           # Change in P&L
    impact_pct: float               # Change as % of position value
    new_status: str                 # "safe", "tested", "breached", "max_loss"
    action_needed: str              # "hold", "close", "hedge"
    commentary: str


class StressTestResult(BaseModel):
    """Complete stress test result for the portfolio."""
    scenario: ScenarioParams
    as_of_date: date
    # Portfolio impact
    total_impact_dollars: float     # Sum of all position impacts
    total_impact_pct: float         # As % of NLV
    worst_position: str             # Ticker with worst impact
    worst_impact_dollars: float
    # Position details
    position_impacts: list[PositionImpact]
    # Margin impact
    estimated_margin_increase_pct: float  # Margin typically increases with vol
    margin_call_risk: bool          # True if stressed margin > available BP
    # Action
    portfolio_survives: bool        # True if total loss < drawdown threshold
    recommended_action: str         # "no action", "reduce size", "hedge", "close all"
    commentary: list[str]


class StressTestSuite(BaseModel):
    """Multiple scenarios run against the same portfolio."""
    as_of_date: date
    account_nlv: float
    positions_count: int
    results: list[StressTestResult]
    worst_scenario: str             # Name of worst scenario
    worst_impact_pct: float
    survives_all: bool              # True if portfolio survives ALL scenarios
    summary: str


# ── Predefined Scenarios ─────────────────────────────────────────────────────


_PREDEFINED_SCENARIOS: dict[str, ScenarioParams] = {
    "market_down_1pct": ScenarioParams(
        name="Market -1%", scenario_type=ScenarioType.COMBINED,
        price_shock_pct=-1.0, vol_shock_pct=10.0,
        description="Mild selloff — market drops 1%, VIX rises 10%",
    ),
    "market_down_3pct": ScenarioParams(
        name="Market -3%", scenario_type=ScenarioType.COMBINED,
        price_shock_pct=-3.0, vol_shock_pct=30.0,
        description="Significant selloff — market drops 3%, VIX jumps 30%",
    ),
    "market_down_5pct": ScenarioParams(
        name="Market -5%", scenario_type=ScenarioType.COMBINED,
        price_shock_pct=-5.0, vol_shock_pct=60.0, time_decay_days=1,
        description="Sharp selloff — market drops 5%, VIX spikes 60%",
    ),
    "market_down_10pct": ScenarioParams(
        name="Market -10%", scenario_type=ScenarioType.COMBINED,
        price_shock_pct=-10.0, vol_shock_pct=150.0, time_decay_days=3,
        description="Crash — market drops 10% over 3 days, VIX more than doubles",
    ),
    "market_up_3pct": ScenarioParams(
        name="Market +3%", scenario_type=ScenarioType.COMBINED,
        price_shock_pct=3.0, vol_shock_pct=-20.0,
        description="Strong rally — market up 3%, VIX contracts 20%",
    ),
    "vix_spike_50pct": ScenarioParams(
        name="VIX Spike 50%", scenario_type=ScenarioType.VOL_SHOCK,
        vol_shock_pct=50.0,
        description="Volatility spike — VIX jumps 50% (e.g., 20 to 30)",
    ),
    "vix_spike_100pct": ScenarioParams(
        name="VIX Doubles", scenario_type=ScenarioType.VOL_SHOCK,
        vol_shock_pct=100.0,
        description="Volatility explosion — VIX doubles (e.g., 20 to 40)",
    ),
    "rate_shock": ScenarioParams(
        name="Rate Shock +50bp", scenario_type=ScenarioType.COMBINED,
        price_shock_pct=-2.0, rate_shock_bp=50.0, vol_shock_pct=15.0,
        description="Fed surprise — yields +50bp, stocks -2%",
    ),
    "flash_crash": ScenarioParams(
        name="Flash Crash", scenario_type=ScenarioType.COMBINED,
        price_shock_pct=-7.0, vol_shock_pct=200.0, time_decay_days=1,
        description="Flash crash — market -7% in 1 day, VIX triples",
    ),
    "black_monday": ScenarioParams(
        name="Black Monday", scenario_type=ScenarioType.COMBINED,
        price_shock_pct=-20.0, vol_shock_pct=300.0, time_decay_days=5,
        description="Black Monday scenario — market -20%, VIX to 80+",
    ),
    "covid_march_2020": ScenarioParams(
        name="COVID March 2020", scenario_type=ScenarioType.COMBINED,
        price_shock_pct=-12.0, vol_shock_pct=200.0, time_decay_days=5,
        description="COVID crash — -12% in a week, VIX to 65",
    ),
    "india_crash": ScenarioParams(
        name="India Market Crash", scenario_type=ScenarioType.COMBINED,
        price_shock_pct=-5.0, vol_shock_pct=80.0, dollar_shock_pct=2.0,
        description="India selloff — NIFTY -5%, India VIX doubles, INR weakens 2%",
    ),
    "fed_surprise": ScenarioParams(
        name="Fed Hawkish Surprise", scenario_type=ScenarioType.COMBINED,
        price_shock_pct=-2.0, rate_shock_bp=30.0, vol_shock_pct=20.0,
        description="Unexpected rate hike signal — stocks -2%, yields +30bp",
    ),
}


def get_predefined_scenario(name: PredefinedScenario | str) -> ScenarioParams:
    """Get a predefined scenario by name."""
    key = str(name).lower()
    if key in _PREDEFINED_SCENARIOS:
        return _PREDEFINED_SCENARIOS[key]
    raise KeyError(f"Unknown scenario: {name}. Available: {list(_PREDEFINED_SCENARIOS.keys())}")


# ── Position Impact Computation ──────────────────────────────────────────────


def _compute_position_impact(
    pos: PortfolioPosition,
    scenario: ScenarioParams,
) -> PositionImpact:
    """Compute impact of a scenario on a single position."""

    structure = pos.structure_type.lower()
    price_move = scenario.price_shock_pct / 100  # Convert to decimal

    # Current value (from current P&L)
    current_value = pos.current_pnl_pct * pos.max_loss if pos.max_loss > 0 else 0

    # --- Impact by structure type ---

    if structure in ("iron_condor", "iron_butterfly", "iron_man"):
        # Defined risk: max loss is capped
        # Price shock: if price moves toward short strike, loss increases
        # For IC: loses money proportional to price move / wing width
        # Rough: if price moves 1 ATR toward short, loses ~50% of width
        loss_from_price = abs(price_move) * pos.max_loss * 2  # 1% move ~ 2% of max loss
        loss_from_price = min(loss_from_price, pos.max_loss)  # Can't lose more than max

        # Vol shock: short options lose money when vol rises (short vega)
        # Vega impact: vega x vol_change x lot_size
        vega_impact = abs(pos.vega) * (scenario.vol_shock_pct / 100) * 100  # Rough

        # Theta benefit (if time passes)
        theta_benefit = pos.theta * scenario.time_decay_days * 100 if pos.theta > 0 else 0

        stressed_impact = -(loss_from_price + vega_impact) + theta_benefit
        stressed_value = current_value + stressed_impact

        # Clamp to max loss
        if abs(stressed_value) > pos.max_loss:
            stressed_value = -pos.max_loss

    elif structure in ("credit_spread",):
        # Directional defined risk
        if pos.direction == "bullish":
            # Bull put spread: loses on down move
            impact = price_move * pos.max_loss * 3  # Leveraged loss
        else:
            # Bear call spread: loses on up move
            impact = -price_move * pos.max_loss * 3
        impact = max(-pos.max_loss, min(pos.max_loss, impact))
        stressed_value = current_value + impact
        stressed_impact = impact

    elif structure in ("equity_long", "futures_long"):
        # Full directional exposure
        notional = pos.notional_value if pos.notional_value > 0 else pos.max_loss * 10
        impact = notional * price_move
        stressed_value = current_value + impact
        stressed_impact = impact

    elif structure in ("equity_short", "futures_short"):
        notional = pos.notional_value if pos.notional_value > 0 else pos.max_loss * 10
        impact = -notional * price_move
        stressed_value = current_value + impact
        stressed_impact = impact

    elif structure in ("straddle", "strangle"):
        # Short vol: loses on big moves AND vol expansion
        base_notional = pos.notional_value if pos.notional_value > 0 else pos.max_loss
        price_loss = abs(price_move) * base_notional * 1.5
        vol_loss = abs(pos.vega) * (scenario.vol_shock_pct / 100) * 100
        stressed_impact = -(price_loss + vol_loss)
        stressed_value = current_value + stressed_impact

    else:
        # Generic: proportional to price move
        stressed_impact = price_move * pos.max_loss * 2
        stressed_value = current_value + stressed_impact

    # Determine new status
    if pos.max_loss > 0 and abs(stressed_value) >= pos.max_loss * 0.9:
        new_status = "max_loss"
        action = "close"
    elif pos.max_loss > 0 and abs(stressed_value) >= pos.max_loss * 0.5:
        new_status = "breached"
        action = "hedge" if structure in ("equity_long", "straddle") else "close"
    elif pos.max_loss > 0 and abs(stressed_impact) > pos.max_loss * 0.2:
        new_status = "tested"
        action = "monitor"
    else:
        new_status = "safe"
        action = "hold"

    impact_pct = stressed_impact / pos.max_loss * 100 if pos.max_loss > 0 else 0

    commentary = (
        f"{pos.ticker} {structure}: "
        f"{stressed_impact:+,.0f} ({impact_pct:+.0f}% of max loss)"
    )
    if new_status in ("max_loss", "breached"):
        commentary += f" — {action.upper()}"

    return PositionImpact(
        ticker=pos.ticker,
        structure_type=structure,
        current_value=round(current_value, 2),
        stressed_value=round(stressed_value, 2),
        impact_dollars=round(stressed_impact, 2),
        impact_pct=round(impact_pct, 2),
        new_status=new_status,
        action_needed=action,
        commentary=commentary,
    )


# ── Run Stress Tests ─────────────────────────────────────────────────────────


def run_stress_test(
    positions: list[PortfolioPosition],
    scenario: ScenarioParams,
    account_nlv: float,
    drawdown_threshold: float = 0.10,
) -> StressTestResult:
    """Run a single stress test scenario against the portfolio.

    Args:
        positions: Current portfolio positions from eTrading.
        scenario: Scenario parameters defining the shock.
        account_nlv: Net liquidating value of the account.
        drawdown_threshold: Max acceptable loss as fraction of NLV (default 10%).

    Returns:
        StressTestResult with per-position and portfolio-level impact.
    """
    today = date.today()
    impacts = [_compute_position_impact(pos, scenario) for pos in positions]

    total_impact = sum(i.impact_dollars for i in impacts)
    total_pct = total_impact / account_nlv * 100 if account_nlv > 0 else 0

    worst = min(impacts, key=lambda i: i.impact_dollars) if impacts else None

    # Margin increase estimate (vol spike increases margin)
    margin_increase = max(0, scenario.vol_shock_pct * 0.5)

    # Survival check
    survives = abs(total_pct / 100) < drawdown_threshold

    # Action
    if not survives:
        action = (
            "EMERGENCY: portfolio loss exceeds drawdown threshold. "
            "Close positions immediately."
        )
    elif total_pct < -5:
        action = (
            "CRITICAL: significant loss expected. "
            "Reduce exposure, hedge remaining positions."
        )
    elif total_pct < -2:
        action = (
            "WARNING: notable loss. "
            "Tighten stops, consider hedging largest positions."
        )
    elif total_pct < -1:
        action = "CAUTION: moderate impact. Monitor positions closely."
    else:
        action = "OK: portfolio withstands this scenario."

    commentary = [
        f"Scenario: {scenario.name} — {scenario.description}",
        f"Portfolio impact: {total_impact:+,.0f} ({total_pct:+.1f}% of NLV)",
    ]
    if worst:
        commentary.append(f"Worst hit: {worst.ticker} ({worst.impact_dollars:+,.0f})")

    positions_at_risk = [
        i for i in impacts if i.new_status in ("breached", "max_loss")
    ]
    if positions_at_risk:
        commentary.append(
            f"{len(positions_at_risk)} position(s) at risk of max loss"
        )

    commentary.append(action)

    return StressTestResult(
        scenario=scenario,
        as_of_date=today,
        total_impact_dollars=round(total_impact, 2),
        total_impact_pct=round(total_pct, 2),
        worst_position=worst.ticker if worst else "",
        worst_impact_dollars=round(worst.impact_dollars, 2) if worst else 0,
        position_impacts=impacts,
        estimated_margin_increase_pct=round(margin_increase, 1),
        margin_call_risk=margin_increase > 30,
        portfolio_survives=survives,
        recommended_action=action,
        commentary=commentary,
    )


def run_stress_suite(
    positions: list[PortfolioPosition],
    account_nlv: float,
    scenarios: list[str | PredefinedScenario] | None = None,
    drawdown_threshold: float = 0.10,
) -> StressTestSuite:
    """Run multiple predefined scenarios against the portfolio.

    If scenarios is None, runs: -1%, -3%, -5%, +3%, VIX+50%, flash crash,
    fed surprise.

    Args:
        positions: Current portfolio positions from eTrading.
        account_nlv: Net liquidating value.
        scenarios: List of scenario names to run. None = default suite.
        drawdown_threshold: Max acceptable loss as fraction of NLV.

    Returns:
        StressTestSuite with all results and worst-case summary.
    """
    if scenarios is None:
        scenarios = [
            "market_down_1pct",
            "market_down_3pct",
            "market_down_5pct",
            "market_up_3pct",
            "vix_spike_50pct",
            "flash_crash",
            "fed_surprise",
        ]

    results: list[StressTestResult] = []
    for name in scenarios:
        try:
            params = get_predefined_scenario(name)
            result = run_stress_test(
                positions, params, account_nlv, drawdown_threshold,
            )
            results.append(result)
        except KeyError:
            continue

    worst = min(results, key=lambda r: r.total_impact_pct) if results else None
    survives_all = all(r.portfolio_survives for r in results)

    summary_parts = [
        f"Stress tested {len(results)} scenarios against {len(positions)} positions",
    ]
    if worst:
        summary_parts.append(
            f"Worst: {worst.scenario.name} ({worst.total_impact_pct:+.1f}%)"
        )
    summary_parts.append(f"Survives all: {'YES' if survives_all else 'NO'}")

    return StressTestSuite(
        as_of_date=date.today(),
        account_nlv=account_nlv,
        positions_count=len(positions),
        results=results,
        worst_scenario=worst.scenario.name if worst else "",
        worst_impact_pct=round(worst.total_impact_pct, 2) if worst else 0,
        survives_all=survives_all,
        summary=" | ".join(summary_parts),
    )
