"""Instrument snapshot models — pre-market chain structure for trading.

These models capture the full option chain topology (strikes, expiries,
OI, tradeability) for one or more instruments at a point in time.
Used by the instrument snapshot service to build the data layer that
assessors and ranking consume.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Standalone helpers
# ---------------------------------------------------------------------------

BucketName = Literal["0dte", "weekly", "two_week", "monthly", "leap"]


def classify_expiry(exp_date: date, today: date) -> BucketName:
    """Classify an expiration date into a DTE bucket."""
    dte = (exp_date - today).days
    if dte == 0:
        return "0dte"
    if dte <= 7:
        return "weekly"
    if dte <= 14:
        return "two_week"
    if dte <= 60:
        return "monthly"
    return "leap"


def select_expiry_buckets(
    expiries: list[date],
    today: date,
    per_bucket: int = 3,
) -> list[date]:
    """Select up to *per_bucket* expiries from each bucket.

    Within each bucket the nearest expiries are preferred.
    Returns a flat, date-sorted list.
    """
    buckets: dict[str, list[date]] = defaultdict(list)
    for exp in sorted(expiries):
        buckets[classify_expiry(exp, today)].append(exp)

    selected: list[date] = []
    for dates in buckets.values():
        # dates already sorted (nearest first) because we sorted expiries above
        selected.extend(dates[:per_bucket])

    return sorted(selected)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class StrikeInfo(BaseModel):
    """One strike in the option chain."""

    strike: float
    option_type: Literal["put", "call"]
    streamer_symbol: str = Field(
        ..., description="DXLink symbol for live streaming"
    )
    open_interest: int = Field(
        0, description="Open interest from DXLink Summary event"
    )
    is_tradeable: bool = Field(
        False,
        description=(
            "True when OI >= threshold AND bid/ask existed at snapshot time"
        ),
    )


class ExpiryInfo(BaseModel):
    """One expiration date with its associated strikes."""

    expiration: date
    dte: int = Field(..., ge=0, description="Days to expiry")
    settlement_type: Literal["AM", "PM"] = "PM"
    bucket: BucketName
    strikes: list[StrikeInfo] = Field(default_factory=list)

    # -- helpers --

    def tradeable_puts(self) -> list[StrikeInfo]:
        """Tradeable put strikes sorted by strike ascending."""
        return sorted(
            [s for s in self.strikes if s.option_type == "put" and s.is_tradeable],
            key=lambda s: s.strike,
        )

    def tradeable_calls(self) -> list[StrikeInfo]:
        """Tradeable call strikes sorted by strike ascending."""
        return sorted(
            [s for s in self.strikes if s.option_type == "call" and s.is_tradeable],
            key=lambda s: s.strike,
        )

    def nearest_put(self, target: float) -> StrikeInfo | None:
        """Closest tradeable put to *target* strike."""
        puts = self.tradeable_puts()
        if not puts:
            return None
        return min(puts, key=lambda s: abs(s.strike - target))

    def nearest_call(self, target: float) -> StrikeInfo | None:
        """Closest tradeable call to *target* strike."""
        calls = self.tradeable_calls()
        if not calls:
            return None
        return min(calls, key=lambda s: abs(s.strike - target))


class InstrumentSnapshot(BaseModel):
    """Full option-chain snapshot for a single ticker.

    Price anchors for P&L calculations:
    - prev_close: previous session close (for overnight P&L)
    - open_price: today's open (for intraday P&L)
    - underlying_price: price at snapshot time (reference point)
    During trading, current price comes live from DXLink — not stored here.
    """

    ticker: str
    underlying_price: float
    prev_close: float | None = Field(None, description="Previous session close price")
    open_price: float | None = Field(None, description="Today's opening price")
    lot_size: int = 1
    expiries: list[ExpiryInfo] = Field(default_factory=list)
    snapshot_time: datetime
    provider: Literal["tastytrade", "dhan"]

    # -- helpers --

    def tradeable_strikes(
        self,
        expiration: date,
        side: Literal["put", "call"],
    ) -> list[StrikeInfo]:
        """All tradeable strikes for a given expiry and side, sorted ascending."""
        for exp in self.expiries:
            if exp.expiration == expiration:
                if side == "put":
                    return exp.tradeable_puts()
                return exp.tradeable_calls()
        return []

    def nearest_expiry(self, bucket: BucketName) -> ExpiryInfo | None:
        """Nearest expiry in the requested bucket (lowest DTE first)."""
        matches = self.expiries_in_bucket(bucket)
        if not matches:
            return None
        return min(matches, key=lambda e: e.dte)

    def expiries_in_bucket(self, bucket: BucketName) -> list[ExpiryInfo]:
        """All expiries matching *bucket*, sorted by DTE ascending."""
        return sorted(
            [e for e in self.expiries if e.bucket == bucket],
            key=lambda e: e.dte,
        )

    def all_streamer_symbols(self) -> list[str]:
        """Flat list of every streamer symbol across all expiries/strikes."""
        return [
            s.streamer_symbol
            for exp in self.expiries
            for s in exp.strikes
        ]


class MarketSnapshot(BaseModel):
    """Full pre-market snapshot covering multiple instruments."""

    instruments: dict[str, InstrumentSnapshot] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    market: Literal["US", "India"]
    provider: str

    # -- helpers --

    def tickers(self) -> list[str]:
        """List of ticker strings in the snapshot."""
        return list(self.instruments.keys())

    def is_stale(self, max_age_hours: float = 12) -> bool:
        """True if the snapshot is older than *max_age_hours*."""
        now = datetime.now(timezone.utc)
        created = self.created_at
        # Ensure timezone-aware comparison
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_hours = (now - created).total_seconds() / 3600
        return age_hours > max_age_hours
