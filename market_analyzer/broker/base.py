"""Abstract broker interfaces — implement for each broker.

Three ABCs because not all brokers provide all capabilities:
- BrokerSession: authentication and connection lifecycle
- MarketDataProvider: option chains, quotes, Greeks
- MarketMetricsProvider: IV rank, beta, liquidity (TastyTrade-specific today)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from market_analyzer.models.opportunity import LegSpec
    from market_analyzer.models.quotes import AccountBalance, MarketMetrics, OptionQuote


class TokenExpiredError(Exception):
    """Broker session token has expired. Re-authenticate."""

    pass


class BrokerSession(ABC):
    """Abstract broker connection. Implement for each broker."""

    @abstractmethod
    def connect(self) -> bool:
        """Authenticate and establish session. Returns True on success."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Clean up session resources."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Human-readable name: 'tastytrade', 'schwab', 'ibkr', etc."""
        ...

    def is_token_valid(self) -> bool:
        """Check if the session token is still valid."""
        return True


class MarketDataProvider(ABC):
    """Abstract market data provider for real-time quotes and Greeks."""

    @abstractmethod
    def get_option_chain(
        self, ticker: str, expiration: date | None = None,
    ) -> list[OptionQuote]:
        """Fetch full option chain with bid/ask/IV for a ticker.

        If expiration is None, returns all available expirations.
        """
        ...

    @abstractmethod
    def get_quotes(
        self,
        legs: list[LegSpec],
        *,
        ticker: str = "",
        include_greeks: bool = True,
    ) -> list[OptionQuote]:
        """Fetch quotes for specific option legs (strike + exp + type).

        Args:
            legs: Option legs to fetch.
            ticker: Underlying ticker (required for DXLink streamer symbols).
            include_greeks: If False, skip Greeks (faster — bid/ask only).
        """
        ...

    @abstractmethod
    def get_greeks(self, legs: list[LegSpec]) -> dict[str, dict]:
        """Fetch Greeks for specific option legs.

        Returns ``{leg_key: {delta, gamma, theta, vega}}``.
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """'tastytrade', 'schwab', 'ibkr', etc."""
        ...

    # -- SaaS support --

    def is_token_valid(self) -> bool:
        """Check if the broker session token is still valid. Default: always True."""
        return True

    @property
    def rate_limit_per_second(self) -> int:
        """Max requests per second for this provider. Default: 10."""
        return 10

    @property
    def supports_batch(self) -> bool:
        """Can this provider batch multiple tickers in one call? Default: False."""
        return False

    # -- Market properties (override per-broker / per-market) --

    @property
    def currency(self) -> str:
        """Currency code for this market: 'USD', 'INR', etc."""
        return "USD"

    @property
    def timezone(self) -> str:
        """Timezone for this market's trading hours."""
        return "US/Eastern"

    @property
    def market_hours(self) -> tuple:
        """Market open and close times as (open, close) time objects."""
        from datetime import time
        return (time(9, 30), time(16, 0))

    @property
    def lot_size_default(self) -> int:
        """Default contract multiplier for this market (100 for US equities)."""
        return 100

    # -- Optional intraday / underlying price (default no-ops) --

    def get_intraday_candles(
        self, ticker: str, interval: str = "5m",
    ) -> pd.DataFrame:
        """Today's intraday OHLCV candles. Empty DataFrame if not supported."""
        return pd.DataFrame()

    def get_underlying_price(self, ticker: str) -> float | None:
        """Real-time underlying price (mid of bid/ask). None if unavailable."""
        return None

    def get_quotes_batch(
        self,
        ticker_legs: list[tuple[str, list]],
        *,
        include_greeks: bool = False,
    ) -> dict[str, list[OptionQuote]]:
        """Fetch quotes for legs across multiple tickers in one connection.

        Default implementation calls get_quotes() per ticker (subclasses can
        override for single-connection batching).
        """
        result: dict[str, list[OptionQuote]] = {}
        for ticker, legs in ticker_legs:
            try:
                result[ticker] = self.get_quotes(
                    legs, ticker=ticker, include_greeks=include_greeks,
                )
            except Exception:
                result[ticker] = []
        return result


class WatchlistProvider(ABC):
    """Abstract provider for broker-managed watchlists."""

    @abstractmethod
    def get_watchlist(self, name: str) -> list[str]:
        """Fetch ticker symbols from a named watchlist.

        Args:
            name: Watchlist name (e.g., 'MA-Income', 'MA-Sectors').

        Returns:
            List of ticker symbols. Empty list if watchlist not found.
        """
        ...

    @abstractmethod
    def list_watchlists(self) -> list[str]:
        """List all available watchlist names (private + public)."""
        ...

    def create_watchlist(self, name: str, tickers: list[str]) -> bool:
        """Create or update a watchlist with the given tickers.

        Returns True on success. Default: not supported.
        """
        return False

    def get_all_equities(
        self,
        is_etf: bool | None = None,
        is_index: bool | None = None,
    ) -> list[dict]:
        """Fetch all tradeable equities/ETFs from broker.

        Returns list of dicts with at least: {symbol, is_etf, is_index, description}.
        Default: empty (not all brokers support this).
        """
        return []


class AccountProvider(ABC):
    """Abstract provider for account balance and positions."""

    @abstractmethod
    def get_balance(self) -> AccountBalance:
        """Fetch current account balance (buying power, NLV, margin)."""
        ...


class MarketMetricsProvider(ABC):
    """Abstract provider for market-level metrics (IV rank, etc.)."""

    @abstractmethod
    def get_metrics(self, tickers: list[str]) -> dict[str, MarketMetrics]:
        """Fetch IV rank, IV percentile, beta, etc. for tickers."""
        ...
