"""Chain context — available strikes, expiries, lot size from broker.

Also contains ChainBundle (single-fetch result) and FetchMetadata
for explicit data quality reporting throughout the pipeline.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict


class AvailableStrike(BaseModel):
    """A strike that exists in the broker chain with real quotes."""
    strike: float
    option_type: str  # "put" or "call"
    bid: float
    ask: float
    mid: float
    iv: float | None = None
    delta: float | None = None
    open_interest: int = 0
    volume: int = 0


class ChainContext(BaseModel):
    """Everything the assessor needs to pick strikes from what actually exists."""
    ticker: str
    expiration: date
    lot_size: int
    underlying_price: float
    put_strikes: list[AvailableStrike]   # sorted by strike ascending, bid > 0
    call_strikes: list[AvailableStrike]  # sorted by strike ascending, bid > 0

    def nearest_put(self, target: float) -> AvailableStrike | None:
        if not self.put_strikes:
            return None
        return min(self.put_strikes, key=lambda s: abs(s.strike - target))

    def nearest_call(self, target: float) -> AvailableStrike | None:
        if not self.call_strikes:
            return None
        return min(self.call_strikes, key=lambda s: abs(s.strike - target))

    def puts_between(self, low: float, high: float) -> list[AvailableStrike]:
        return [s for s in self.put_strikes if low <= s.strike <= high]

    def calls_between(self, low: float, high: float) -> list[AvailableStrike]:
        return [s for s in self.call_strikes if low <= s.strike <= high]

    def put_below(self, target: float, n: int = 1) -> list[AvailableStrike]:
        """Return n put strikes below target, sorted descending (nearest first)."""
        below = [s for s in self.put_strikes if s.strike < target]
        return sorted(below, key=lambda s: s.strike, reverse=True)[:n]

    def call_above(self, target: float, n: int = 1) -> list[AvailableStrike]:
        """Return n call strikes above target, sorted ascending (nearest first)."""
        above = [s for s in self.call_strikes if s.strike > target]
        return sorted(above, key=lambda s: s.strike)[:n]


# ---------------------------------------------------------------------------
# Fetch metadata & bundle — single-fetch, pass-everywhere pattern
# ---------------------------------------------------------------------------


class FetchMetadata(BaseModel):
    """Quality report for a chain fetch operation."""
    timestamp: datetime
    provider: str  # "tastytrade" | "dhan" | "yfinance"
    fetch_duration_s: float = 0.0
    requested_symbols: int = 0
    received_symbols: int = 0
    missing_symbols: list[str] = []
    is_partial: bool = False
    error: str | None = None


class ChainBundle(BaseModel):
    """Everything fetched for one ticker — created once, used everywhere.

    This is the unit of work in the trading pipeline. Chain is fetched once
    by ChainFetcher, then passed to ranking, assessors, pricing, and
    monitoring without any re-fetching.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ticker: str
    underlying_price: float
    raw_chain: list = []  # list[OptionQuote] — use list to avoid circular import
    chain_df: Any = None  # pd.DataFrame — use Any for Pydantic compat
    vol_surface: Any = None  # VolatilitySurface | None
    chain_context: ChainContext | None = None
    fetch_meta: FetchMetadata

    @property
    def is_usable(self) -> bool:
        """True if we have enough data to assess trades."""
        return len(self.raw_chain) > 0 and self.underlying_price > 0

    @property
    def has_chain_df(self) -> bool:
        """True if chain_df is a non-empty DataFrame."""
        return self.chain_df is not None and hasattr(self.chain_df, 'empty') and not self.chain_df.empty

    @property
    def missing_count(self) -> int:
        return len(self.fetch_meta.missing_symbols)

    @property
    def quality_pct(self) -> float:
        """Percentage of requested symbols successfully received."""
        if self.fetch_meta.requested_symbols == 0:
            return 0.0
        return self.fetch_meta.received_symbols / self.fetch_meta.requested_symbols * 100
