"""Zerodha (Kite) market metrics provider — stub.

Actual API integration pending Kite Connect SDK access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from market_analyzer.broker.base import MarketMetricsProvider

if TYPE_CHECKING:
    from market_analyzer.models.quotes import MarketMetrics


class ZerodhaMetrics(MarketMetricsProvider):
    """Zerodha MarketMetricsProvider for India NSE/BSE.

    Stub — all methods raise NotImplementedError until Kite Connect SDK is integrated.
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

    def get_metrics(self, tickers: list[str]) -> dict[str, MarketMetrics]:
        raise NotImplementedError("Zerodha metrics not yet implemented")
