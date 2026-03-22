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

# Models
from income_desk.hedging.models import (
    HedgeTier,
    HedgeGoal,
    HedgeApproach,
    HedgeAlternative,
    HedgeResult,
    CollarResult,
    SyntheticOptionResult,
    PositionHedge,
    PortfolioHedgeAnalysis,
    HedgeComparisonEntry,
    HedgeComparison,
    HedgeMonitorEntry,
    HedgeMonitorResult,
    HedgeEffectiveness,
    FnOCoverage,
)

# Universe
from income_desk.hedging.universe import (
    classify_hedge_tier,
    get_fno_coverage,
    get_sector_beta,
    get_proxy_instrument,
)

# Resolver
from income_desk.hedging.resolver import resolve_hedge_strategy

# Direct (Tier 1)
from income_desk.hedging.direct import (
    build_protective_put,
    build_collar,
    build_put_spread_hedge,
)

# Futures (Tier 2)
from income_desk.hedging.futures_hedge import (
    build_futures_hedge,
    build_synthetic_put,
    build_synthetic_collar,
    compute_hedge_ratio,
)

# Proxy (Tier 3)
from income_desk.hedging.proxy import (
    build_index_hedge,
    compute_portfolio_beta,
    recommend_proxy,
)

# Comparison
from income_desk.hedging.comparison import compare_hedge_methods

# Portfolio
from income_desk.hedging.portfolio import analyze_portfolio_hedge

# Monitoring
from income_desk.hedging.monitoring import (
    monitor_hedge_status,
    compute_hedge_effectiveness,
)

__all__ = [
    # Backward-compat legacy
    "HedgeType",
    "HedgeUrgency",
    "HedgeRecommendation",
    "assess_hedge",
    # Models
    "HedgeTier",
    "HedgeGoal",
    "HedgeApproach",
    "HedgeAlternative",
    "HedgeResult",
    "CollarResult",
    "SyntheticOptionResult",
    "PositionHedge",
    "PortfolioHedgeAnalysis",
    "HedgeComparisonEntry",
    "HedgeComparison",
    "HedgeMonitorEntry",
    "HedgeMonitorResult",
    "HedgeEffectiveness",
    "FnOCoverage",
    # Universe
    "classify_hedge_tier",
    "get_fno_coverage",
    "get_sector_beta",
    "get_proxy_instrument",
    # Resolver
    "resolve_hedge_strategy",
    # Direct (Tier 1)
    "build_protective_put",
    "build_collar",
    "build_put_spread_hedge",
    # Futures (Tier 2)
    "build_futures_hedge",
    "build_synthetic_put",
    "build_synthetic_collar",
    "compute_hedge_ratio",
    # Proxy (Tier 3)
    "build_index_hedge",
    "compute_portfolio_beta",
    "recommend_proxy",
    # Comparison
    "compare_hedge_methods",
    # Portfolio
    "analyze_portfolio_hedge",
    # Monitoring
    "monitor_hedge_status",
    "compute_hedge_effectiveness",
]
