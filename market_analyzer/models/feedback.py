"""Models for trade outcome tracking and performance feedback.

eTrading stores TradeOutcome records. market_analyzer provides pure functions
that accept outcomes and return performance analysis + calibrated weights.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel

from market_analyzer.models.ranking import StrategyType


class TradeExitReason(StrEnum):
    """Why a trade was closed. Recorded by eTrading, analyzed by MA."""

    PROFIT_TARGET = "profit_target"
    STOP_LOSS = "stop_loss"
    DTE_EXIT = "dte_exit"
    REGIME_CHANGE = "regime_change"
    MANUAL = "manual"
    EXPIRED = "expired"


class TradeOutcome(BaseModel):
    """Record of a completed trade. eTrading stores these, MA analyzes them."""

    trade_id: str
    ticker: str
    strategy_type: StrategyType
    regime_at_entry: int  # R1-R4
    regime_at_exit: int
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    pnl_dollars: float
    pnl_pct: float  # As decimal (0.15 = 15%)
    holding_days: int
    exit_reason: TradeExitReason
    composite_score_at_entry: float  # What MA ranked it at
    contracts: int = 1

    # Fields requested by eTrading (CR-3) — all optional for backward compat
    structure_type: str | None = None  # iron_condor, credit_spread, etc.
    order_side: str | None = None  # credit, debit
    iv_rank_at_entry: float | None = None  # 0-100
    dte_at_entry: int | None = None
    dte_at_exit: int | None = None
    max_favorable_excursion: float | None = None  # Best P&L during hold
    max_adverse_excursion: float | None = None  # Worst P&L during hold


class StrategyPerformance(BaseModel):
    """Performance stats for a strategy type, optionally filtered by regime."""

    strategy_type: StrategyType
    regime_id: int | None  # None = all regimes combined
    total_trades: int
    wins: int
    losses: int
    win_rate: float  # 0.0-1.0
    avg_pnl_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    total_pnl_dollars: float
    avg_holding_days: float
    profit_factor: float  # gross_profit / gross_loss (inf if no losses)
    best_trade_pnl_pct: float
    worst_trade_pnl_pct: float
    avg_score_at_entry: float  # Were high-scored trades actually better?
    avg_dte_at_entry: float | None = None  # Average DTE when entered
    avg_iv_rank_at_entry: float | None = None  # Average IV rank when entered


class PerformanceReport(BaseModel):
    """Complete performance analysis across all strategies and regimes."""

    total_trades: int
    total_pnl_dollars: float
    overall_win_rate: float
    by_strategy: list[StrategyPerformance]
    by_regime: dict[int, list[StrategyPerformance]]  # regime_id -> per-strategy
    score_correlation: float | None  # Correlation between entry score and PnL
    summary: str
    pop_accuracy: dict[int, float] | None = None  # regime_id → actual_win_rate


class WeightAdjustment(BaseModel):
    """Suggested adjustment to regime-strategy alignment weight."""

    regime_id: int
    strategy_type: StrategyType
    current_weight: float
    suggested_weight: float
    reason: str


class CalibrationResult(BaseModel):
    """Result of calibrating strategy weights from performance data."""

    adjustments: list[WeightAdjustment]
    summary: str


class SharpeResult(BaseModel):
    """Risk-adjusted return metrics."""

    sharpe_ratio: float
    sortino_ratio: float
    annualized_return_pct: float
    annualized_volatility_pct: float
    risk_free_rate: float
    total_trades: int


class DrawdownResult(BaseModel):
    """Maximum drawdown analysis."""

    max_drawdown_pct: float
    max_drawdown_dollars: float
    max_drawdown_duration_days: int
    current_drawdown_pct: float
    current_drawdown_dollars: float
    recovery_trades: int  # Trades since max drawdown


class RegimePerformance(BaseModel):
    """Performance breakdown for a single regime."""

    regime_id: int
    regime_name: str
    total_trades: int
    win_rate: float
    avg_pnl_pct: float
    total_pnl_dollars: float
    best_strategy: str | None
    worst_strategy: str | None
