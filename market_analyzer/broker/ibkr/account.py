"""IBKR account provider via ib_insync."""

from __future__ import annotations

import logging

from market_analyzer.broker.base import AccountProvider
from market_analyzer.models.quotes import AccountBalance

logger = logging.getLogger(__name__)


class IBKRAccount(AccountProvider):
    """Account balance and buying power via IBKR ib_insync.

    Reads from ``accountValues`` — the standard IBKR account summary.
    """

    def __init__(self, ib) -> None:
        """
        Args:
            ib: Connected ``ib_insync.IB`` instance.
        """
        self._ib = ib

    def get_balance(self) -> AccountBalance:
        """Fetch current account balance from IBKR.

        Uses ``reqAccountSummary`` to get key financial metrics.
        Falls back to ``accountValues()`` if summary is unavailable.
        """
        try:
            # Prefer account summary (works for all account types)
            summary = {
                item.tag: item.value
                for item in self._ib.accountSummary()
            }

            # Use first managed account if multiple
            acct_num = (
                self._ib.managedAccounts()[0]
                if self._ib.managedAccounts()
                else "unknown"
            )

            nlv = _safe_float(summary.get("NetLiquidation", 0))
            cash = _safe_float(summary.get("TotalCashValue", 0))
            # OptionBuyingPower for derivatives; AvailableFunds as fallback
            deriv_bp = _safe_float(
                summary.get("OptionBuyingPower")
                or summary.get("AvailableFunds", 0)
            )
            equity_bp = _safe_float(
                summary.get("EquityWithLoanValue")
                or summary.get("AvailableFunds", 0)
            )
            maint = _safe_float(summary.get("MaintMarginReq", 0))

            return AccountBalance(
                account_number=acct_num,
                net_liquidating_value=nlv or 0.0,
                cash_balance=cash or 0.0,
                derivative_buying_power=deriv_bp or 0.0,
                equity_buying_power=equity_bp or 0.0,
                maintenance_requirement=maint or 0.0,
                source="ibkr",
                currency="USD",
            )
        except Exception as exc:
            raise ConnectionError(f"IBKR account balance fetch failed: {exc}") from exc


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
