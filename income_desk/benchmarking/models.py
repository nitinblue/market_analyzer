"""Benchmarking models — Pydantic schemas for prediction tracking and calibration."""

from __future__ import annotations

from pydantic import BaseModel


class PredictionRecord(BaseModel):
    """What income_desk predicted at trade entry. eTrading captures and stores this."""

    trade_id: str
    ticker: str
    timestamp: str  # ISO datetime of fill
    regime_id: int  # 1-4
    regime_confidence: float  # 0-1
    pop_pct: float | None = None  # probability of profit, 0-100
    composite_score: float | None = None
    iv_rank: float | None = None  # 0-100
    entry_credit: float | None = None
    structure: str = ""  # "iron_condor", "credit_spread", etc.
    market: str = "US"


class OutcomeRecord(BaseModel):
    """Actual trade outcome. eTrading records this at exit."""

    trade_id: str
    ticker: str
    entry_timestamp: str
    exit_timestamp: str
    pnl: float
    is_win: bool
    holding_days: int
    regime_at_exit: int | None = None
    regime_persisted: bool | None = None  # same regime entry->exit?
    exit_reason: str = ""  # "profit_target", "stop_loss", "expiry", "manual"


class PopBucket(BaseModel):
    """One bucket in POP calibration analysis."""

    predicted_low: float  # e.g. 60
    predicted_high: float  # e.g. 70
    predicted_mid: float  # e.g. 65
    actual_win_rate: float  # actual % that won
    count: int  # trades in this bucket
    error: float  # actual - predicted_mid


class RegimeAccuracy(BaseModel):
    """Accuracy for one regime ID."""

    regime_id: int
    count: int
    persisted_count: int
    persistence_rate: float


class CalibrationReport(BaseModel):
    """Output of calibration analysis."""

    period: str  # "2026-03" or "2026-Q1"
    total_trades: int
    # POP calibration
    pop_buckets: list[PopBucket] = []
    pop_rmse: float | None = None
    # Regime accuracy
    regime_persistence_rate: float | None = None
    regime_accuracy: list[RegimeAccuracy] = []
    # Score correlation
    score_win_correlation: float | None = None
    avg_score_winners: float | None = None
    avg_score_losers: float | None = None
    # Overall
    win_rate: float | None = None
    avg_pnl: float | None = None
    summary: str = ""
