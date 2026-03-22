"""All Pydantic models for the hedging domain package."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from income_desk.models.opportunity import TradeSpec


class HedgeTier(StrEnum):
    """Which hedging approach to use, ordered by preference."""

    DIRECT = "direct"                     # Tier 1: liquid same-ticker options
    FUTURES_SYNTHETIC = "futures_synthetic"  # Tier 2: futures + optional call/put
    PROXY_INDEX = "proxy_index"           # Tier 3: correlated index hedge
    NONE = "none"                         # No hedge available or needed


class HedgeGoal(StrEnum):
    """What the hedge is protecting against."""

    DOWNSIDE = "downside"        # Protect long equity from drop
    UPSIDE = "upside"            # Protect short equity from rally
    VOLATILITY = "volatility"    # Protect from vol expansion
    TAIL_RISK = "tail_risk"      # Black swan protection (cheap OTM)
    DELTA_NEUTRAL = "delta_neutral"  # Flatten directional exposure


class HedgeApproach(BaseModel):
    """Resolved hedge strategy — what approach and why.

    This is the OUTPUT of resolve_hedge_strategy().
    It tells the caller WHICH tier to use and WHY,
    but does NOT contain the actual TradeSpec yet.
    """

    ticker: str
    market: str                          # "US" or "INDIA"
    recommended_tier: HedgeTier
    goal: HedgeGoal
    rationale: str                       # Why this tier was chosen
    alternatives: list[HedgeAlternative]  # Other tiers considered, ranked
    # Cost context
    estimated_cost_pct: float | None     # Estimated hedge cost as % of position value
    basis_risk: str                      # "none", "low", "medium", "high"
    # Registry data used in decision
    has_liquid_options: bool
    has_futures: bool
    lot_size: int
    lot_size_affordable: bool            # Can the account afford at least 1 lot?


class HedgeAlternative(BaseModel):
    """An alternative hedge approach that was considered but not recommended."""

    tier: HedgeTier
    reason_not_chosen: str
    estimated_cost_pct: float | None


class HedgeResult(BaseModel):
    """A concrete hedge recommendation with TradeSpec.

    Every tier-specific builder returns this.
    """

    ticker: str
    market: str
    tier: HedgeTier
    hedge_type: str                      # "protective_put", "collar", "futures_short", etc.
    trade_spec: TradeSpec                # Concrete legs, ready for execution
    cost_estimate: float | None          # Net premium paid (positive = debit)
    cost_pct: float | None               # Cost as % of position value
    delta_reduction: float               # How much delta the hedge removes (0 to 1)
    protection_level: str                # "Put at 2600" or "Futures short 1 lot"
    max_loss_after_hedge: float | None   # Max loss with hedge in place
    rationale: str
    regime_context: str                  # Why this hedge suits the current regime
    commentary: list[str]                # Debug-mode trace of decisions


class CollarResult(BaseModel):
    """Collar-specific result with both put and call details."""

    ticker: str
    market: str
    put_strike: float
    call_strike: float
    net_cost: float                      # Negative = credit (call premium > put cost)
    downside_protection_pct: float       # How far below current price the put is
    upside_cap_pct: float                # How far above current price the call is
    trade_spec: TradeSpec
    rationale: str


class SyntheticOptionResult(BaseModel):
    """Result of building a synthetic option from futures.

    Synthetic put  = short futures + long call
    Synthetic call = long futures + long put
    """

    ticker: str
    market: str
    synthetic_type: str                  # "synthetic_put" or "synthetic_call"
    futures_direction: str               # "short" or "long"
    futures_lots: int
    option_strike: float
    option_type: str                     # "call" or "put"
    option_lots: int
    net_cost_estimate: float | None      # Basis cost + option premium
    trade_spec: TradeSpec
    rationale: str


class PositionHedge(BaseModel):
    """Per-position hedge detail within a portfolio analysis."""

    ticker: str
    position_value: float
    shares: int
    tier: HedgeTier
    hedge_type: str | None               # None if tier is NONE
    trade_spec: TradeSpec | None
    cost_estimate: float | None
    delta_before: float
    delta_after: float
    rationale: str


class PortfolioHedgeAnalysis(BaseModel):
    """Aggregate portfolio hedge analysis — the master output."""

    market: str
    account_nlv: float
    total_positions: int
    total_position_value: float

    # Tier breakdown
    tier_counts: dict[str, int]          # {"direct": 5, "futures_synthetic": 2, "proxy_index": 1, "none": 2}
    tier_values: dict[str, float]        # Value of positions in each tier

    # Per-position details
    position_hedges: list[PositionHedge]

    # Aggregate metrics
    total_hedge_cost: float
    hedge_cost_pct: float                # Total cost as % of portfolio value
    portfolio_delta_before: float
    portfolio_delta_after: float
    portfolio_beta_before: float | None
    portfolio_beta_after: float | None

    # All TradeSpecs ready for execution
    trade_specs: list[TradeSpec]

    # Summary
    coverage_pct: float                  # % of portfolio value that is hedged
    target_hedge_pct: float              # What was requested
    summary: str
    alerts: list[str]                    # Warnings (e.g., "3 positions have no hedge available")


class HedgeComparisonEntry(BaseModel):
    """One method in a hedge comparison."""

    tier: HedgeTier
    hedge_type: str
    trade_spec: TradeSpec | None         # None if method is unavailable
    cost_estimate: float | None
    cost_pct: float | None
    delta_reduction: float
    basis_risk: str                      # "none", "low", "medium", "high"
    pros: list[str]
    cons: list[str]
    available: bool
    unavailable_reason: str | None


class HedgeComparison(BaseModel):
    """Ranked comparison of all available hedge methods for a single ticker."""

    ticker: str
    market: str
    current_price: float
    position_value: float
    shares: int
    regime_id: int

    methods: list[HedgeComparisonEntry]  # Sorted best → worst
    recommended: HedgeComparisonEntry
    recommendation_rationale: str


class HedgeMonitorEntry(BaseModel):
    """Status of one active hedge."""

    ticker: str
    hedge_type: str
    dte_remaining: int
    is_expiring_soon: bool               # DTE <= 5
    is_expired: bool
    current_delta_coverage: float        # How much delta the hedge still covers
    action: str                          # "hold", "roll", "close", "replace"
    roll_spec: TradeSpec | None          # If action is "roll", the roll TradeSpec
    rationale: str


class HedgeMonitorResult(BaseModel):
    """Monitoring result for all active hedges."""

    hedges: list[HedgeMonitorEntry]
    expiring_count: int
    expired_count: int
    total_roll_cost: float | None
    roll_specs: list[TradeSpec]          # All roll TradeSpecs aggregated
    alerts: list[str]
    summary: str


class HedgeEffectiveness(BaseModel):
    """How much did hedges save in a given market move scenario."""

    market_move_pct: float               # Simulated move (e.g., -0.05 = -5%)
    portfolio_loss_unhedged: float
    portfolio_loss_hedged: float
    hedge_savings: float                 # unhedged - hedged
    hedge_savings_pct: float             # savings / unhedged
    cost_of_hedges: float
    net_benefit: float                   # savings - cost
    roi_on_hedge: float                  # net_benefit / cost (if cost > 0)
    commentary: str


class FnOCoverage(BaseModel):
    """F&O universe coverage for a set of tickers."""

    market: str
    total_tickers: int
    direct_hedge_count: int              # Tier 1 — liquid options
    futures_hedge_count: int             # Tier 2 — futures available
    proxy_only_count: int                # Tier 3 — index proxy only
    no_hedge_count: int                  # No viable hedge
    coverage_pct: float                  # (direct + futures) / total
    tier_breakdown: dict[str, list[str]]  # {"direct": ["RELIANCE", ...], ...}
    commentary: str


# Resolve forward reference in HedgeApproach
HedgeApproach.model_rebuild()
