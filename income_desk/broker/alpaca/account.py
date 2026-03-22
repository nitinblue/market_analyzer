"""Alpaca account provider.

Reads account balance and buying power from Alpaca's trading API.
"""

from __future__ import annotations

import logging

from income_desk.broker.base import AccountProvider
from income_desk.models.quotes import AccountBalance

logger = logging.getLogger(__name__)


class AlpacaAccount(AccountProvider):
    """Account balance and buying power via Alpaca TradingClient."""

    def __init__(self, trading_client) -> None:
        """
        Args:
            trading_client: ``alpaca.trading.client.TradingClient``
        """
        self._client = trading_client

    def get_balance(self) -> AccountBalance:
        """Fetch current account balance from Alpaca.

        Maps Alpaca account fields to AccountBalance:
        - equity → net_liquidating_value
        - cash → cash_balance
        - options_buying_power → derivative_buying_power (if available)
        - buying_power → equity_buying_power
        - maintenance_margin → maintenance_requirement
        """
        try:
            acct = self._client.get_account()
        except Exception as exc:
            raise ConnectionError(f"Alpaca account fetch failed: {exc}") from exc

        # Alpaca may or may not expose options_buying_power depending on account type
        derivative_bp = _safe_float(
            getattr(acct, "options_buying_power", None)
            or getattr(acct, "regt_buying_power", None)
            or acct.buying_power
        ) or 0.0

        return AccountBalance(
            account_number=str(acct.account_number),
            net_liquidating_value=_safe_float(acct.equity) or 0.0,
            cash_balance=_safe_float(acct.cash) or 0.0,
            derivative_buying_power=derivative_bp,
            equity_buying_power=_safe_float(acct.buying_power) or 0.0,
            maintenance_requirement=_safe_float(
                getattr(acct, "maintenance_margin", None) or 0
            ) or 0.0,
            source="alpaca",
            currency="USD",
        )


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
