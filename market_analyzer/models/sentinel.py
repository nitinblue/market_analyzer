"""Models for crash sentinel / market health monitoring."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class SentinelSignal(StrEnum):
    GREEN = "green"    # Normal operations
    YELLOW = "yellow"  # Elevated risk — tighten stops
    ORANGE = "orange"  # Pre-crash — close positions, raise cash
    RED = "red"        # Crash active — 100% cash
    BLUE = "blue"      # Post-crash opportunity — deploy per playbook


class SentinelTicker(BaseModel):
    ticker: str
    regime_id: int
    regime_confidence: float
    r4_probability: float
    iv_rank: float | None


class SentinelReport(BaseModel):
    signal: SentinelSignal
    as_of: datetime
    reasons: list[str]
    actions: list[str]
    tickers: list[SentinelTicker]
    r4_count: int
    r2_count: int
    r1_count: int
    avg_iv_rank: float
    max_r4_probability: float
    environment: str
    position_size_factor: float
    # Playbook phase guidance
    playbook_phase: str  # "normal", "pre_crash", "crash", "stabilization", "recovery", "elevated"
    sizing_params: dict  # Recommended PortfolioExposure overrides for this phase
