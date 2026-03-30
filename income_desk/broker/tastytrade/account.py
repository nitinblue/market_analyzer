"""TastyTrade account balance and positions — real data from broker."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import TYPE_CHECKING

from income_desk.broker.base import AccountProvider
from income_desk.models.quotes import AccountBalance, BrokerPosition

if TYPE_CHECKING:
    from income_desk.broker.tastytrade.session import TastyTradeBrokerSession

logger = logging.getLogger(__name__)


class TastyTradeAccount(AccountProvider):
    """Account balance and positions from TastyTrade API."""

    def __init__(self, session: TastyTradeBrokerSession) -> None:
        self._session = session

    def get_balance(self) -> AccountBalance:
        """Fetch current account balance via TastyTrade API."""
        account = self._session.account
        from income_desk.broker.tastytrade._async import run_sync

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

    def get_positions(self) -> list[BrokerPosition]:
        """Fetch current open positions from TastyTrade."""
        account = self._session.account
        from income_desk.broker.tastytrade._async import run_sync

        result = account.get_positions(self._session.sdk_session)
        if asyncio.iscoroutine(result):
            result = run_sync(result)

        positions: list[BrokerPosition] = []
        for p in result:
            qty = int(p.quantity)
            if p.quantity_direction == "Short":
                qty = -abs(qty)

            ticker, opt_type, strike, exp = _parse_tt_symbol(
                p.symbol, p.underlying_symbol, str(p.instrument_type),
            )

            positions.append(BrokerPosition(
                ticker=ticker,
                symbol=p.symbol,
                instrument_type=str(p.instrument_type),
                quantity=qty,
                average_open_price=float(p.average_open_price),
                close_price=float(p.close_price) if p.close_price is not None else None,
                multiplier=int(p.multiplier),
                expiration=exp,
                strike=strike,
                option_type=opt_type,
                source="tastytrade",
            ))

        return positions


def _parse_tt_symbol(
    symbol: str, underlying: str, instrument_type: str,
) -> tuple[str, str | None, float | None, date | None]:
    """Extract ticker, option_type, strike, expiration from TastyTrade position.

    For equities returns (ticker, None, None, None).
    For options parses OCC-style symbols.
    """
    ticker = underlying or symbol

    if "Option" not in instrument_type:
        return ticker, None, None, None

    # OCC format: SPY   260417P00570000  (ticker padded to 6, YYMMDD, C/P, strike*1000)
    clean = symbol.replace(" ", "")
    match = re.match(r"([A-Z]+)(\d{6})([CP])(\d+)", clean)
    if match:
        exp_str = match.group(2)
        opt_type = "call" if match.group(3) == "C" else "put"
        strike = int(match.group(4)) / 1000
        try:
            exp = date(
                2000 + int(exp_str[:2]), int(exp_str[2:4]), int(exp_str[4:6]),
            )
        except ValueError:
            exp = None
        return ticker, opt_type, strike, exp

    return ticker, None, None, None
