"""TastyTrade account balance — real buying power from broker."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from market_analyzer.broker.base import AccountProvider
from market_analyzer.models.quotes import AccountBalance

if TYPE_CHECKING:
    from market_analyzer.broker.tastytrade.session import TastyTradeBrokerSession

logger = logging.getLogger(__name__)


class TastyTradeAccount(AccountProvider):
    """Account balance from TastyTrade API."""

    def __init__(self, session: TastyTradeBrokerSession) -> None:
        self._session = session

    def get_balance(self) -> AccountBalance:
        """Fetch current account balance via TastyTrade API."""
        account = self._session.account
        from market_analyzer.broker.tastytrade._async import run_sync

        result = account.get_balances(self._session.sdk_session)
        if asyncio.iscoroutine(result):
            result = run_sync(result)

        return AccountBalance(
            account_number=result.account_number,
            net_liquidating_value=float(result.net_liquidating_value),
            cash_balance=float(result.cash_balance),
            derivative_buying_power=float(result.derivative_buying_power),
            equity_buying_power=float(result.equity_buying_power),
            maintenance_requirement=float(result.maintenance_requirement),
            pending_cash=float(result.pending_cash),
            source="tastytrade",
        )
