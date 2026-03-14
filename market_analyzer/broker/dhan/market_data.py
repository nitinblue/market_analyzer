"""Dhan market data provider — stub.

Actual API integration pending Dhan SDK access.
Dhan provides REST + WebSocket APIs for NSE/BSE market data.
"""

from __future__ import annotations

from datetime import date, time
from typing import TYPE_CHECKING

import pandas as pd

from market_analyzer.broker.base import MarketDataProvider

if TYPE_CHECKING:
    from market_analyzer.models.opportunity import LegSpec
    from market_analyzer.models.quotes import OptionQuote


class DhanMarketData(MarketDataProvider):
    """Dhan MarketDataProvider for India NSE/BSE.

    Stub — all methods raise NotImplementedError until Dhan SDK is integrated.
    """

    def __init__(
        self,
        api_key: str = "",
        access_token: str = "",
        session: object = None,
    ) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._session = session

    @property
    def provider_name(self) -> str:
        return "dhan"

    @property
    def currency(self) -> str:
        return "INR"

    @property
    def timezone(self) -> str:
        return "Asia/Kolkata"

    @property
    def market_hours(self) -> tuple[time, time]:
        return (time(9, 15), time(15, 30))

    @property
    def lot_size_default(self) -> int:
        """NIFTY default lot size."""
        return 25

    def get_option_chain(
        self, ticker: str, expiration: date | None = None,
    ) -> list[OptionQuote]:
        raise NotImplementedError("Dhan option chain not yet implemented")

    def get_quotes(
        self,
        legs: list[LegSpec],
        *,
        ticker: str = "",
        include_greeks: bool = True,
    ) -> list[OptionQuote]:
        raise NotImplementedError("Dhan quotes not yet implemented")

    def get_greeks(self, legs: list[LegSpec]) -> dict[str, dict]:
        raise NotImplementedError("Dhan Greeks not yet implemented")

    def get_intraday_candles(
        self, ticker: str, interval: str = "5m",
    ) -> pd.DataFrame:
        raise NotImplementedError("Dhan intraday candles not yet implemented")

    def get_underlying_price(self, ticker: str) -> float | None:
        raise NotImplementedError("Dhan underlying price not yet implemented")
