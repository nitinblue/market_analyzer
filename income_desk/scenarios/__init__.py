"""Scenario Engine — stress-test portfolios against macro scenarios.

Takes real market data as baseline, applies factor-based shocks with
statistical correlations, produces stressed SimulatedMarketData for
all 15 workflows.

Usage::

    from income_desk.scenarios import apply_scenario, SCENARIOS
    from income_desk.adapters.simulated import create_india_trading

    baseline = create_india_trading()
    stressed = apply_scenario(baseline, "sp500_down_10")

    # Use with any workflow
    ma = MarketAnalyzer(data_service=DataService(), market_data=stressed, ...)
"""

from income_desk.scenarios.engine import apply_scenario, ScenarioEngine
from income_desk.scenarios.definitions import SCENARIOS, ScenarioDef
from income_desk.scenarios.factors import FactorModel

__all__ = [
    "apply_scenario",
    "ScenarioEngine",
    "SCENARIOS",
    "ScenarioDef",
    "FactorModel",
]
