"""Ready-made data adapters for common sources.

Users can either:
1. Use these adapters directly (CSV, DataFrame, dict, simulated)
2. Copy and modify for their broker/data source
3. Implement the ABCs from scratch (broker/base.py, data/providers/base.py)
"""
from market_analyzer.adapters.csv_provider import CSVProvider
from market_analyzer.adapters.dict_quotes import DictQuoteProvider, DictMetricsProvider
from market_analyzer.adapters.simulated import (
    SimulatedMarketData,
    SimulatedMetrics,
    SimulatedAccount,
    create_calm_market,
    create_volatile_market,
    create_crash_scenario,
    create_india_market,
)

__all__ = [
    "CSVProvider",
    "DictQuoteProvider",
    "DictMetricsProvider",
    "SimulatedMarketData",
    "SimulatedMetrics",
    "SimulatedAccount",
    "create_calm_market",
    "create_volatile_market",
    "create_crash_scenario",
    "create_india_market",
]
