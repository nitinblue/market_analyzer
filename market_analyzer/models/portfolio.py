"""Models for portfolio desk management and capital allocation."""
from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel


class RiskTolerance(StrEnum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class PortfolioAssetClass(StrEnum):
    OPTIONS = "options"
    STOCKS = "stocks"
    METALS = "metals"
    FUTURES = "futures"
    CASH = "cash"


class PortfolioRiskType(StrEnum):
    DEFINED = "defined"        # Max loss is known (spreads, ICs)
    UNDEFINED = "undefined"    # Max loss is NOT capped (naked, directional)


class DeskHealth(StrEnum):
    EXCELLENT = "excellent"
    GOOD = "good"
    CAUTION = "caution"
    POOR = "poor"
    CRITICAL = "critical"


class DeskSpec(BaseModel):
    desk_key: str               # "desk_0dte", "desk_income", "desk_core"
    name: str                   # "0DTE Income", "Medium-Term Income", "Core Holdings"
    capital_allocation: float
    capital_pct: float
    dte_min: int
    dte_max: int
    preferred_underlyings: list[str]
    strategy_types: list[str]   # ["iron_condor", "credit_spread", ...]
    max_positions: int
    risk_limits: dict           # max_single_position_pct, circuit_breaker_pct, etc.
    instrument_type: str        # "options" | "equities" | "mixed"
    allow_undefined_risk: bool  # Ratio spreads, naked puts etc.
    rationale: str


class DeskRecommendation(BaseModel):
    desks: list[DeskSpec]
    total_capital: float
    unallocated_cash: float
    cash_reserve_pct: float
    rationale: str
    regime_context: str


class DeskAdjustment(BaseModel):
    desk_key: str
    current_capital: float
    recommended_capital: float
    change: float               # positive = add, negative = reduce
    reason: str


class RebalanceRecommendation(BaseModel):
    needs_rebalance: bool
    adjustments: list[DeskAdjustment]
    trigger: str                # "regime_change" | "drawdown" | "performance_drift" | "periodic"
    rationale: str


class DeskHealthReport(BaseModel):
    desk_key: str
    health: DeskHealth
    score: float                # 0-1
    win_rate: float | None
    profit_factor: float | None
    avg_days_held: float | None
    capital_efficiency: float   # P&L / capital deployed
    issues: list[str]
    suggestions: list[str]
    regime_fit: str             # "well_suited" | "neutral" | "poor_fit"


class DeskRiskLimits(BaseModel):
    desk_key: str
    max_positions: int
    max_single_position_pct: float
    max_portfolio_delta: float
    max_daily_loss_pct: float
    circuit_breaker_pct: float
    max_correlated_positions: int
    position_size_factor: float     # 1.0 normal, 0.5 in R4
    rationale: str


class InstrumentRisk(BaseModel):
    ticker: str
    instrument_type: str        # "option_spread" | "equity_long" | "futures" | "naked_option"
    max_loss: float
    expected_loss_1d: float
    margin_required: float
    risk_category: str          # "defined" | "undefined" | "equity"
    risk_method: str            # "max_loss" | "atr_based" | "margin_based"
    regime_factor: float
    rationale: str


class PortfolioAssetAllocation(BaseModel):
    """Capital allocation for one asset class."""
    asset_class: PortfolioAssetClass
    allocation_pct: float           # % of total capital
    allocation_dollars: float
    defined_risk_pct: float         # % within this asset class that is defined risk
    undefined_risk_pct: float       # % within this asset class that is undefined risk
    defined_risk_dollars: float
    undefined_risk_dollars: float
    rationale: str


class PortfolioAllocation(BaseModel):
    """Complete portfolio allocation across asset classes."""
    total_capital: float
    risk_tolerance: str
    cash_reserve_pct: float
    cash_reserve_dollars: float
    allocations: list[PortfolioAssetAllocation]
    desks: list[DeskSpec]            # Concrete desks derived from allocations
    regime_adjustments: list[str]    # What changed due to regime
    rationale: str

    @property
    def unallocated_cash(self) -> float:
        """Alias for cash_reserve_dollars (backward compatibility)."""
        return self.cash_reserve_dollars

    @property
    def regime_context(self) -> str:
        """Backward-compat: join regime_adjustments into a single string."""
        if not self.regime_adjustments:
            return "No regime data — using base allocations."
        return " ".join(self.regime_adjustments)
