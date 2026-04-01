"""DXLink streaming result models — explicit data quality reporting.

Every DXLink fetch returns a result model that tracks what was requested,
what was received, and what's missing. Callers can no longer silently
receive partial data without knowing.
"""
from __future__ import annotations

from pydantic import BaseModel


class QuoteResult(BaseModel):
    """Result of a DXLink quote fetch with explicit quality reporting."""
    data: dict[str, dict]  # {symbol: {"bid": float, "ask": float}}
    requested: list[str]
    missing_symbols: list[str] = []
    is_partial: bool = False
    fetch_duration_s: float = 0.0

    @property
    def received_count(self) -> int:
        return len(self.data)

    @property
    def quality_pct(self) -> float:
        if not self.requested:
            return 0.0
        return len(self.data) / len(self.requested) * 100


class GreeksResult(BaseModel):
    """Result of a DXLink Greeks fetch with explicit quality reporting."""
    data: dict[str, dict]  # {symbol: {"delta", "gamma", "theta", "vega", "iv"}}
    requested: list[str]
    missing_symbols: list[str] = []
    is_partial: bool = False
    fetch_duration_s: float = 0.0

    @property
    def received_count(self) -> int:
        return len(self.data)

    @property
    def quality_pct(self) -> float:
        if not self.requested:
            return 0.0
        return len(self.data) / len(self.requested) * 100
