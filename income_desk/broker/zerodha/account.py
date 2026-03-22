"""Zerodha account provider — balance and buying power via Kite Connect."""

from __future__ import annotations

import logging

from income_desk.broker.base import AccountProvider, TokenExpiredError
from income_desk.models.quotes import AccountBalance

logger = logging.getLogger(__name__)


class ZerodhaAccount(AccountProvider):
    """Zerodha AccountProvider via Kite Connect margins API."""

    def __init__(
        self,
        api_key: str = "",
        access_token: str = "",
        session: object = None,
    ) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._session = session
        self._kite = None

    def _get_kite(self):
        if self._kite is not None:
            return self._kite

        from kiteconnect import KiteConnect

        if self._session is not None and isinstance(self._session, KiteConnect):
            self._kite = self._session
        else:
            self._kite = KiteConnect(api_key=self._api_key)
            if self._access_token:
                self._kite.set_access_token(self._access_token)

        return self._kite

    def get_balance(self) -> AccountBalance:
        """Get account balance from Zerodha margins API."""
        kite = self._get_kite()

        try:
            margins = kite.margins()
            equity = margins.get("equity", {})

            net = float(equity.get("net", 0))
            available = equity.get("available", {})
            available_cash = float(available.get("cash", 0))
            available_margin = float(available.get("live_balance", 0))
            used = equity.get("utilised", {})
            used_margin = float(used.get("debits", 0))

            return AccountBalance(
                account_number="zerodha",
                net_liquidating_value=net,
                cash_balance=available_cash,
                derivative_buying_power=available_margin,
                equity_buying_power=available_cash,
                maintenance_requirement=used_margin,
                pending_cash=0.0,
                source="zerodha",
                currency="INR",
                timezone="Asia/Kolkata",
            )
        except Exception as e:
            if "TokenException" in type(e).__name__:
                raise TokenExpiredError(f"Zerodha token expired: {e}")
            logger.warning("Failed to get Zerodha balance: %s", e)
            return AccountBalance(
                account_number="zerodha",
                net_liquidating_value=0,
                cash_balance=0,
                derivative_buying_power=0,
                equity_buying_power=0,
                maintenance_requirement=0,
                pending_cash=0,
                source="zerodha (error)",
                currency="INR",
                timezone="Asia/Kolkata",
            )
