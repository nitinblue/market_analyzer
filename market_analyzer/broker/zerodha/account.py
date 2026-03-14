"""Zerodha (Kite) account provider — stub.

Actual API integration pending Kite Connect SDK access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from market_analyzer.broker.base import AccountProvider

if TYPE_CHECKING:
    from market_analyzer.models.quotes import AccountBalance


class ZerodhaAccount(AccountProvider):
    """Zerodha AccountProvider for India NSE/BSE.

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

    def get_balance(self) -> AccountBalance:
        raise NotImplementedError("Zerodha account balance not yet implemented")
