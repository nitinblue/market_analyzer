"""Pydantic models for intraday 0DTE signal monitoring."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class IntradaySignalType(StrEnum):
    """Types of intraday signals for 0DTE management."""

    PROFIT_TARGET = "profit_target"        # Position P&L hit target
    STOP_LOSS = "stop_loss"                # Position P&L hit stop
    GAMMA_RISK = "gamma_risk"              # Short gamma accelerating
    BREACH_SHORT_STRIKE = "breach_short"   # Underlying crossed short strike
    APPROACHING_STRIKE = "approaching"     # Within threshold of short strike
    MOMENTUM_SHIFT = "momentum_shift"      # Intraday trend reversal
    VOLUME_SPIKE = "volume_spike"          # Unusual volume surge
    VIX_SPIKE = "vix_spike"               # VIX jumped intraday
    TIME_DECAY_WINDOW = "theta_window"     # Optimal entry/exit window
    EXPIRY_APPROACHING = "expiry_close"    # Market close approaching, act now


class IntradayUrgency(StrEnum):
    """How urgently the signal should be acted on."""

    IMMEDIATE = "immediate"    # Act now — seconds matter
    SOON = "soon"              # Within 5-15 minutes
    MONITOR = "monitor"        # Watch, no action needed yet
    INFORMATIONAL = "info"     # Context only


class IntradaySignal(BaseModel):
    """A single intraday signal for a 0DTE position or opportunity."""

    signal_type: IntradaySignalType
    urgency: IntradayUrgency
    ticker: str
    timestamp: datetime
    message: str
    action: str                              # Recommended action
    current_price: float                     # Underlying price at signal time
    strike_distance_pct: float | None = None # How far from nearest short strike
    pnl_pct: float | None = None             # Current P&L as % of max
    data: dict = {}                          # Extra signal-specific data


class IntradaySnapshot(BaseModel):
    """Complete intraday state for 0DTE monitoring."""

    ticker: str
    timestamp: datetime
    price: float
    vwap: float | None = None
    day_range_low: float | None = None
    day_range_high: float | None = None
    volume: int | None = None
    avg_volume: int | None = None            # Typical volume for this time of day
    vix: float | None = None
    signals: list[IntradaySignal] = []

    # Market microstructure
    bid_ask_spread_pct: float | None = None  # Option bid-ask as % of mid
    minutes_to_close: int | None = None      # Minutes until 4:00 PM ET


class IntradayMonitorResult(BaseModel):
    """Result of monitoring all 0DTE positions."""

    as_of: datetime
    snapshots: list[IntradaySnapshot] = []
    signals: list[IntradaySignal] = []       # All signals across all tickers
    urgent_count: int = 0
    summary: str = ""
