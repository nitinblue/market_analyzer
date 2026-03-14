"""Dhan watchlist provider — stub.

Actual API integration pending Dhan SDK access.
"""

from __future__ import annotations

from market_analyzer.broker.base import WatchlistProvider


class DhanWatchlist(WatchlistProvider):
    """Dhan WatchlistProvider for India NSE/BSE.

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

    def get_watchlist(self, name: str) -> list[str]:
        raise NotImplementedError("Dhan watchlist not yet implemented")

    def list_watchlists(self) -> list[str]:
        raise NotImplementedError("Dhan watchlist listing not yet implemented")

    def create_watchlist(self, name: str, tickers: list[str]) -> bool:
        raise NotImplementedError("Dhan watchlist creation not yet implemented")

    def get_all_equities(
        self,
        is_etf: bool | None = None,
        is_index: bool | None = None,
    ) -> list[dict]:
        raise NotImplementedError("Dhan equity listing not yet implemented")
