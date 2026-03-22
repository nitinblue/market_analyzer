"""Models for adaptive learning — drift detection, bandits, threshold optimization."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel

from income_desk.models.ranking import StrategyType


class DriftSeverity(StrEnum):
    OK = "ok"
    WARNING = "warning"       # >15% drop from baseline
    CRITICAL = "critical"     # >25% drop from baseline


class DriftAlert(BaseModel):
    """Alert when a strategy cell's performance drifts from historical."""

    regime_id: int
    strategy_type: StrategyType
    historical_win_rate: float
    recent_win_rate: float
    recent_trades: int
    drop_pct: float            # How much win rate dropped (e.g., 0.20 = 20pp)
    severity: DriftSeverity
    recommendation: str


class StrategyBandit(BaseModel):
    """Thompson Sampling bandit for one (regime, strategy) cell.

    Beta(alpha, beta) distribution. alpha = prior + wins, beta = prior + losses.
    eTrading stores these per cell and passes them to MA for selection.
    """

    regime_id: int
    strategy_type: StrategyType
    alpha: float = 1.0  # Prior + wins
    beta_param: float = 1.0  # Prior + losses (named beta_param to avoid shadowing)
    total_trades: int = 0
    last_updated: date | None = None

    @property
    def expected_win_rate(self) -> float:
        """Mean of Beta distribution."""
        return self.alpha / (self.alpha + self.beta_param)

    @property
    def uncertainty(self) -> float:
        """Higher = less data = more exploration needed."""
        return 1.0 / (self.alpha + self.beta_param)

    @property
    def key(self) -> str:
        """Unique key for storage: 'R1_iron_condor'."""
        return f"R{self.regime_id}_{self.strategy_type}"


class ThresholdConfig(BaseModel):
    """Optimized threshold values learned from trade outcomes.

    eTrading stores this and can pass it to MA services as config override.
    All values start at defaults and are adjusted based on actual trade performance.
    """

    ic_iv_rank_min: float = 15.0
    ifly_iv_rank_min: float = 20.0
    earnings_iv_rank_min: float = 25.0
    leap_iv_rank_max: float = 70.0
    pop_min: float = 0.50
    score_min: float = 0.60
    credit_width_min: float = 0.10
    adx_trend_max: float = 35.0
    adx_notrend_min: float = 15.0

    # Metadata
    trades_analyzed: int = 0
    last_optimized: date | None = None
