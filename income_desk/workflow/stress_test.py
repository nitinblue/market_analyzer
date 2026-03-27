"""Stress Test Portfolio — run all scenarios against live positions.

The core risk management workflow. Takes your actual portfolio positions,
runs every macro scenario, reports:
- Which scenarios blow your risk budget
- Per-scenario P&L impact on every position
- Worst-case portfolio loss across all scenarios
- Which positions are most vulnerable

Usage::

    from income_desk.workflow import stress_test_portfolio, StressTestRequest

    result = stress_test_portfolio(
        StressTestRequest(
            positions=my_open_positions,
            capital=5_000_000,
            market="India",
            scenarios=["sp500_down_10", "nifty_down_10", "black_monday"],  # or None for all
        ),
        ma,
    )

    # result.worst_scenario = "black_monday"
    # result.worst_portfolio_pnl = -485000
    # result.scenarios_breaching_limit = ["black_monday", "correlation_1"]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from income_desk.workflow._types import OpenPosition, WorkflowMeta

if TYPE_CHECKING:
    from income_desk.service.analyzer import MarketAnalyzer

logger = logging.getLogger(__name__)


class StressTestRequest(BaseModel):
    """Request to stress-test a portfolio."""
    positions: list[OpenPosition]
    capital: float = 5_000_000
    market: str = "India"
    risk_limit_pct: float = 0.30       # max acceptable loss as % of capital
    scenarios: list[str] | None = None  # None = run all 18 scenarios


class PositionScenarioImpact(BaseModel):
    """How one position is affected by one scenario."""
    trade_id: str
    ticker: str
    structure: str
    base_value: float              # current P&L or position value
    stressed_value: float          # value under scenario
    scenario_pnl: float            # change from base
    scenario_pnl_pct: float        # as % of entry
    price_move_pct: float          # underlying price change
    iv_move: float                 # IV change (absolute)


class ScenarioPortfolioImpact(BaseModel):
    """Portfolio-level impact from one scenario."""
    scenario_key: str
    scenario_name: str
    severity: str
    portfolio_pnl: float           # total P&L across all positions
    portfolio_pnl_pct: float       # as % of capital
    breaches_limit: bool           # loss > risk_limit_pct
    position_impacts: list[PositionScenarioImpact]
    worst_position: str            # ticker with largest loss
    worst_position_pnl: float


class StressTestResponse(BaseModel):
    """Complete stress test results."""
    meta: WorkflowMeta
    capital: float
    risk_limit_pct: float
    total_positions: int
    scenarios_run: int

    # Per-scenario results (sorted worst to best)
    scenario_results: list[ScenarioPortfolioImpact]

    # Summary
    worst_scenario: str
    worst_scenario_pnl: float
    worst_scenario_pnl_pct: float
    best_scenario: str
    best_scenario_pnl: float
    scenarios_breaching_limit: list[str]
    portfolio_at_risk: float       # worst-case loss amount
    risk_score: str                # "safe", "caution", "danger", "critical"

    # Most vulnerable positions across all scenarios
    most_vulnerable_positions: list[dict]  # [{ticker, avg_loss, worst_scenario, worst_loss}]


def stress_test_portfolio(
    request: StressTestRequest,
    ma: MarketAnalyzer,
) -> StressTestResponse:
    """Run macro scenarios against portfolio positions.

    For each scenario:
    1. Compute stressed price per ticker using factor model
    2. Re-value each position under stressed prices/IV
    3. Aggregate portfolio P&L
    4. Flag scenarios that breach risk limits
    """
    from income_desk.scenarios import apply_scenario, SCENARIOS
    from income_desk.scenarios.definitions import list_scenarios
    from income_desk.adapters.simulated import SimulatedMarketData, SimulatedMetrics

    timestamp = datetime.now()
    warnings: list[str] = []

    # Build baseline from current market data
    baseline = None
    if isinstance(ma.market_data, SimulatedMarketData):
        baseline = ma.market_data
    else:
        # Build from latest prices if available
        from income_desk.adapters.simulated import create_india_trading, create_ideal_income
        baseline = create_india_trading() if request.market == "India" else create_ideal_income()

        # Override with live prices where available
        if ma.market_data is not None:
            for pos in request.positions:
                try:
                    live_price = ma.market_data.get_underlying_price(pos.ticker)
                    if live_price and live_price > 0 and pos.ticker.upper() in baseline._tickers:
                        baseline._tickers[pos.ticker.upper()]["price"] = live_price
                except Exception:
                    pass

    # Determine which scenarios to run
    scenario_keys = request.scenarios or list(SCENARIOS.keys())
    scenario_keys = [k for k in scenario_keys if k in SCENARIOS]

    if not scenario_keys:
        return StressTestResponse(
            meta=WorkflowMeta(as_of=timestamp, market=request.market, data_source="scenario_engine", warnings=["No valid scenarios"]),
            capital=request.capital, risk_limit_pct=request.risk_limit_pct,
            total_positions=len(request.positions), scenarios_run=0,
            scenario_results=[], worst_scenario="none", worst_scenario_pnl=0,
            worst_scenario_pnl_pct=0, best_scenario="none", best_scenario_pnl=0,
            scenarios_breaching_limit=[], portfolio_at_risk=0,
            risk_score="safe", most_vulnerable_positions=[],
        )

    # --- Run each scenario ---
    all_results: list[ScenarioPortfolioImpact] = []
    position_losses: dict[str, list[float]] = {pos.ticker: [] for pos in request.positions}

    for scenario_key in scenario_keys:
        try:
            stressed_sim, scenario_result = apply_scenario(baseline, scenario_key, run_monte_carlo=False)
        except Exception as e:
            warnings.append(f"Scenario {scenario_key} failed: {e}")
            continue

        scenario_def = SCENARIOS[scenario_key]
        position_impacts: list[PositionScenarioImpact] = []
        total_pnl = 0.0

        for pos in request.positions:
            ticker = pos.ticker.upper()
            impact = scenario_result.ticker_impacts.get(ticker)

            if impact is None:
                # Ticker not in factor model — assume market beta
                price_move = scenario_def.factor_shocks.get("equity", 0.0)
                iv_move = scenario_def.iv_regime_shift
            else:
                price_move = impact.return_pct / 100.0
                iv_move = impact.iv_change

            # Re-value position under stress
            # For credit trades: profit when price stays in range, lose when it moves
            # Simplified P&L model: delta * price_move + vega * iv_move + theta
            lot_size = pos.lot_size
            contracts = pos.contracts
            multiplier = lot_size * contracts

            # Credit spread P&L under stress:
            # If underlying moves toward short strike, position loses
            entry = pos.entry_price
            current = pos.current_mid_price or entry * 0.7

            # Approximate stressed mid-price
            # Iron condor: loses ~delta*move per point, gains from theta
            # Simplified: position P&L ≈ current_pnl + (delta_effect + vega_effect) * multiplier
            base_pnl = (entry - current) * multiplier if pos.order_side == "credit" else (current - entry) * multiplier

            # Delta effect: how much the position loses from price move
            # For credit spreads: short delta ≈ 0.15-0.30, so adverse move costs
            assumed_delta = 0.20  # typical short IC delta
            delta_pnl = -abs(price_move) * pos.entry_price * multiplier * assumed_delta * 3

            # Vega effect: IV spike hurts short vol positions
            # For credit trades: short vega, so IV spike = loss
            vega_pnl = 0.0
            if pos.order_side == "credit":
                vega_pnl = -abs(iv_move) * multiplier * 2.0  # rough vega sensitivity

            scenario_pnl = delta_pnl + vega_pnl
            stressed_value = base_pnl + scenario_pnl

            position_impacts.append(PositionScenarioImpact(
                trade_id=pos.trade_id,
                ticker=pos.ticker,
                structure=pos.structure_type,
                base_value=round(base_pnl, 2),
                stressed_value=round(stressed_value, 2),
                scenario_pnl=round(scenario_pnl, 2),
                scenario_pnl_pct=round(scenario_pnl / max(abs(entry * multiplier), 1) * 100, 1),
                price_move_pct=round(price_move * 100, 1),
                iv_move=round(iv_move, 4),
            ))

            total_pnl += scenario_pnl
            position_losses.setdefault(pos.ticker, []).append(scenario_pnl)

        # Find worst position in this scenario
        worst_pos = min(position_impacts, key=lambda p: p.scenario_pnl) if position_impacts else None

        portfolio_pnl_pct = total_pnl / request.capital * 100 if request.capital > 0 else 0
        breaches = abs(total_pnl) > request.capital * request.risk_limit_pct

        all_results.append(ScenarioPortfolioImpact(
            scenario_key=scenario_key,
            scenario_name=scenario_def.name,
            severity=scenario_def.severity,
            portfolio_pnl=round(total_pnl, 2),
            portfolio_pnl_pct=round(portfolio_pnl_pct, 1),
            breaches_limit=breaches,
            position_impacts=position_impacts,
            worst_position=worst_pos.ticker if worst_pos else "none",
            worst_position_pnl=worst_pos.scenario_pnl if worst_pos else 0,
        ))

    # Sort by P&L (worst first)
    all_results.sort(key=lambda r: r.portfolio_pnl)

    worst = all_results[0] if all_results else None
    best = all_results[-1] if all_results else None
    breaching = [r.scenario_key for r in all_results if r.breaches_limit]

    # Most vulnerable positions (across all scenarios)
    vulnerable: list[dict] = []
    for ticker, losses in position_losses.items():
        if losses:
            avg_loss = sum(losses) / len(losses)
            worst_loss = min(losses)
            worst_idx = losses.index(worst_loss)
            worst_scen = scenario_keys[worst_idx] if worst_idx < len(scenario_keys) else "unknown"
            vulnerable.append({
                "ticker": ticker,
                "avg_scenario_loss": round(avg_loss, 2),
                "worst_scenario": worst_scen,
                "worst_loss": round(worst_loss, 2),
            })
    vulnerable.sort(key=lambda v: v["avg_scenario_loss"])

    # Risk score
    worst_pct = abs(worst.portfolio_pnl_pct) if worst else 0
    if worst_pct > 25:
        risk_score = "critical"
    elif worst_pct > 15:
        risk_score = "danger"
    elif worst_pct > 8:
        risk_score = "caution"
    else:
        risk_score = "safe"

    return StressTestResponse(
        meta=WorkflowMeta(
            as_of=timestamp, market=request.market, data_source="scenario_engine",
            warnings=warnings,
        ),
        capital=request.capital,
        risk_limit_pct=request.risk_limit_pct,
        total_positions=len(request.positions),
        scenarios_run=len(all_results),
        scenario_results=all_results,
        worst_scenario=worst.scenario_key if worst else "none",
        worst_scenario_pnl=worst.portfolio_pnl if worst else 0,
        worst_scenario_pnl_pct=worst.portfolio_pnl_pct if worst else 0,
        best_scenario=best.scenario_key if best else "none",
        best_scenario_pnl=best.portfolio_pnl if best else 0,
        scenarios_breaching_limit=breaching,
        portfolio_at_risk=abs(worst.portfolio_pnl) if worst else 0,
        risk_score=risk_score,
        most_vulnerable_positions=vulnerable[:5],
    )
