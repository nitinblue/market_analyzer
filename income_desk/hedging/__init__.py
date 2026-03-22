"""Hedging domain package — market-generic hedge intelligence.

Resolver pattern:
    resolve_hedge_strategy() → HedgeApproach (decides tier)
    Tier 1 (direct.py)       → protective puts, collars, put spreads
    Tier 2 (futures_hedge.py) → futures short, synthetic puts, synthetic collars
    Tier 3 (proxy.py)        → beta-adjusted index hedges
    portfolio.py             → orchestrate across all positions
    comparison.py            → rank all available methods
    monitoring.py            → expiry tracking, rolling, effectiveness

Backward-compat re-exports from original hedging.py:
    HedgeType, HedgeUrgency, HedgeRecommendation, assess_hedge
"""

# Re-export original hedging.py API for backward compatibility
from income_desk.hedging._legacy import (
    HedgeType,
    HedgeUrgency,
    HedgeRecommendation,
    assess_hedge,
)

__all__ = [
    "HedgeType",
    "HedgeUrgency",
    "HedgeRecommendation",
    "assess_hedge",
]
