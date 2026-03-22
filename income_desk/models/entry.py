"""Pydantic models for entry confirmation."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel

from income_desk.models.technicals import TechnicalSignal


class EntryTriggerType(StrEnum):
    """Types of entry triggers to confirm."""

    BREAKOUT_CONFIRMED = "breakout_confirmed"
    PULLBACK_TO_SUPPORT = "pullback_to_support"
    MOMENTUM_CONTINUATION = "momentum_continuation"
    MEAN_REVERSION_EXTREME = "mean_reversion_extreme"
    ORB_BREAKOUT = "orb_breakout"


class EntryCondition(BaseModel):
    """A single pass/fail condition for entry confirmation."""

    name: str
    met: bool
    weight: float
    description: str


class EntryConfirmation(BaseModel):
    """Result of entry signal confirmation."""

    ticker: str
    as_of_date: date
    trigger_type: EntryTriggerType
    confirmed: bool
    confidence: float               # 0.0–1.0
    conditions: list[EntryCondition]
    conditions_met: int
    conditions_total: int
    signals: list[TechnicalSignal]
    suggested_entry_price: float | None = None
    suggested_stop_price: float | None = None
    risk_per_share: float | None = None
    summary: str = ""


class StrikeProximityLeg(BaseModel):
    """Proximity analysis for one short leg."""

    role: str  # "short_put", "short_call"
    strike: float
    nearest_level_price: float
    nearest_level_strength: float  # 0-1 from PriceLevel.strength
    nearest_level_sources: list[str]  # LevelSource values
    distance_points: float  # abs(strike - level_price)
    distance_atr: float  # distance_points / atr
    backed_by_level: bool  # True if distance_atr <= 1.0 AND strength >= 0.5


class StrikeProximityResult(BaseModel):
    """Result of checking short strike proximity to S/R levels."""

    legs: list[StrikeProximityLeg]
    overall_score: float  # 0-1, average of leg scores
    all_backed: bool  # True if every short leg is backed
    summary: str


class SkewOptimalStrike(BaseModel):
    """Result of skew-informed strike selection."""

    option_type: str  # "put" or "call"
    baseline_strike: float  # Where ATR-only logic would place it
    optimal_strike: float  # Where skew says the richest premium is
    baseline_iv: float  # IV at baseline strike
    optimal_iv: float  # IV at optimal strike
    iv_advantage_pct: float  # (optimal_iv - baseline_iv) / baseline_iv * 100
    distance_atr: float  # How far optimal strike is from spot (in ATR units)
    rationale: str


class EntryLevelScore(BaseModel):
    """Multi-factor score: enter now vs wait for better level."""

    overall_score: float  # 0-1
    action: str  # "enter_now" (>=0.70), "wait" (0.50-0.70), "not_yet" (<0.50)
    components: dict[str, float]  # name → 0-1 score
    rationale: str


class ConditionalEntry(BaseModel):
    """Limit order entry price computation."""

    entry_mode: str  # "limit" or "market"
    limit_price: float  # Target fill price
    current_mid: float  # Current mid price
    improvement_pct: float  # How much better limit is vs market
    urgency: str  # "patient", "normal", "aggressive"
    rationale: str


class PullbackAlert(BaseModel):
    """Price level where the trade improves materially."""

    alert_price: float  # Price to watch for
    current_price: float
    level_source: str  # What S/R level is at that price
    level_strength: float  # 0-1
    improvement_description: str  # What changes at that price
    roc_improvement_pct: float  # Estimated ROC improvement


class IVRankQuality(BaseModel):
    """IV rank quality assessment by ticker type."""

    current_iv_rank: float
    ticker_type: str  # "etf", "equity", "index"
    threshold_good: float
    threshold_wait: float
    quality: str  # "good", "wait", "avoid"
    rationale: str
