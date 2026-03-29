"""Pydantic models for the $30K Trading Challenge portfolio tracker.

Designed for trading platform consumption — all inputs come via API,
YAML files are just the backing store.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TradeStatus(StrEnum):
    """Lifecycle status of a trade."""

    OPEN = "open"
    CLOSED = "closed"
    EXPIRED = "expired"
    ADJUSTED = "adjusted"  # Original trade modified, new trade_id created


class TradeRecord(BaseModel):
    """A single trade in the journal — booked from a TradeSpec.

    The trading platform calls `book_trade()` with a TradeSpec + fill data,
    producing one of these records.  On close, it updates exit fields.
    """

    trade_id: str  # Unique: "GLD-IC-20260312-001"
    status: TradeStatus = TradeStatus.OPEN

    # From TradeSpec
    ticker: str
    structure_type: str  # StructureType value
    order_side: str  # "credit" or "debit"
    legs: list[dict[str, Any]]  # Serialized LegSpec dicts
    target_expiration: str  # ISO date
    wing_width: float | None = None  # Points between short and long strike

    # Entry
    entry_date: str  # ISO date
    entry_price: float  # Net credit received or debit paid (per spread)
    contracts: int = 1
    buying_power_used: float = 0.0  # Margin/BP blocked by this trade

    # Exit (filled on close)
    exit_date: str | None = None
    exit_price: float | None = None  # Net debit to close (credit) or credit received (debit)
    realized_pnl: float | None = None  # Total P&L in dollars
    exit_reason: str | None = None  # "profit_target", "stop_loss", "expiration", "manual", "adjustment"

    # Risk/exit rules (from TradeSpec)
    profit_target_pct: float | None = None
    stop_loss_pct: float | None = None
    exit_dte: int | None = None
    max_entry_price: float | None = None

    # Tracking
    notes: str = ""
    tags: list[str] = []  # ["income", "hedge", "earnings_play"]
    adjusted_from: str | None = None  # trade_id of original trade if this is an adjustment

    @property
    def is_open(self) -> bool:
        return self.status == TradeStatus.OPEN

    @property
    def max_profit(self) -> float | None:
        """Max profit in dollars for the trade."""
        if self.order_side == "credit":
            return self.entry_price * 100 * self.contracts
        if self.order_side == "debit" and self.wing_width is not None:
            return (self.wing_width - self.entry_price) * 100 * self.contracts
        return None

    @property
    def max_loss(self) -> float | None:
        """Max loss in dollars (defined-risk trades)."""
        if self.order_side == "credit" and self.wing_width is not None:
            return (self.wing_width - self.entry_price) * 100 * self.contracts
        if self.order_side == "debit":
            return self.entry_price * 100 * self.contracts
        return None

    @property
    def risk_reward_ratio(self) -> float | None:
        """Risk:Reward as a ratio (e.g., 5.0 means risking $5 for $1)."""
        mp = self.max_profit
        ml = self.max_loss
        if mp and ml and mp > 0:
            return round(ml / mp, 2)
        return None


class RiskLimits(BaseModel):
    """Account-level risk limits — loaded from config YAML."""

    account_size: float = 30_000.0
    max_positions: int = 5
    max_per_ticker: int = 2
    max_daily_risk_pct: float = 0.02  # 2% = $600/day on 30K
    max_single_trade_risk_pct: float = 0.05  # 5% = $1500 per trade
    max_sector_concentration_pct: float = 0.40  # 40% in one sector
    max_portfolio_risk_pct: float = 0.25  # 25% of account in total risk
    min_buying_power_reserve_pct: float = 0.20  # Keep 20% BP in cash

    # Strategy-level limits
    max_undefined_risk_positions: int = 0  # No naked for small accounts
    allowed_structures: list[str] = [
        "iron_condor", "iron_butterfly", "credit_spread",
        "debit_spread", "calendar", "diagonal", "long_option",
        "double_calendar", "pmcc",
    ]

    # Sector mapping (ticker → sector)
    ticker_sectors: dict[str, str] = {
        "SPX": "index", "SPY": "index", "QQQ": "tech",
        "IWM": "small_cap", "GLD": "commodity", "SLV": "commodity",
        "TLT": "bonds", "AAPL": "tech", "MSFT": "tech",
        "AMZN": "tech", "META": "tech", "GOOGL": "tech",
        "NVDA": "tech", "AMD": "tech", "TSLA": "auto",
    }


class RiskCheckResult(BaseModel):
    """Result of a pre-trade risk check."""

    allowed: bool
    violations: list[str] = []  # What rules would be broken
    warnings: list[str] = []  # Caution but not blocking
    available_capital: float = 0.0
    buying_power_after: float = 0.0
    portfolio_risk_after_pct: float = 0.0
    position_count_after: int = 0
    ticker_count_after: int = 0


class PortfolioStatus(BaseModel):
    """Current portfolio snapshot — returned by get_status()."""

    account_size: float
    total_risk_deployed: float  # Sum of max_loss on open trades
    buying_power_used: float
    buying_power_available: float
    cash_reserve: float  # account_size * min_buying_power_reserve_pct

    open_positions: int
    max_positions: int
    portfolio_risk_pct: float  # total_risk_deployed / account_size

    # P&L summary
    total_realized_pnl: float  # All closed trades
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float  # winning / total (0 if no closed trades)
    avg_winner: float  # Average $ on winners
    avg_loser: float  # Average $ on losers
    largest_winner: float
    largest_loser: float

    # Concentration
    tickers_deployed: dict[str, int]  # ticker → count of open positions
    sectors_deployed: dict[str, float]  # sector → total risk $
    sector_concentration_pct: dict[str, float]  # sector → % of account

    # Heat map
    portfolio_heat: str  # "cool" (<50%), "warm" (50-75%), "hot" (>75%)
    heat_pct: float  # buying_power_used / account_size
