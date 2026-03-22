"""Schwab account provider via schwab-py."""

from __future__ import annotations

import logging

from income_desk.broker.base import AccountProvider
from income_desk.models.quotes import AccountBalance

logger = logging.getLogger(__name__)


class SchwabAccount(AccountProvider):
    """Account balance and buying power via Schwab API."""

    def __init__(self, client) -> None:
        """
        Args:
            client: Authenticated ``schwab.client.Client`` instance.
        """
        self._client = client

    def get_balance(self) -> AccountBalance:
        """Fetch current account balance from Schwab.

        Maps Schwab account fields to AccountBalance.
        Schwab returns a list of accounts; uses the first one.
        """
        try:
            resp = self._client.get_accounts(fields=[self._client.Account.Fields.POSITIONS])
            resp.raise_for_status()
            accounts = resp.json()
        except AttributeError:
            # Older schwab-py versions use different enum access
            try:
                resp = self._client.get_accounts()
                resp.raise_for_status()
                accounts = resp.json()
            except Exception as exc:
                raise ConnectionError(f"Schwab account fetch failed: {exc}") from exc
        except Exception as exc:
            raise ConnectionError(f"Schwab account fetch failed: {exc}") from exc

        if not accounts:
            raise ConnectionError("No Schwab accounts found")

        # Use first account
        acct_data = accounts[0]
        acct = acct_data.get("securitiesAccount", acct_data)
        account_number = str(acct.get("accountNumber", "unknown"))

        # Current balances section
        current = acct.get("currentBalances", {})
        initial = acct.get("initialBalances", {})

        nlv = _safe_float(current.get("liquidationValue") or current.get("accountValue") or 0)
        cash = _safe_float(current.get("cashBalance", 0))
        # Options buying power (key for sizing)
        deriv_bp = _safe_float(
            current.get("optionBuyingPower")
            or current.get("buyingPower", 0)
        )
        equity_bp = _safe_float(current.get("buyingPower", 0))
        maint = _safe_float(current.get("maintenanceRequirement", 0))

        return AccountBalance(
            account_number=account_number,
            net_liquidating_value=nlv or 0.0,
            cash_balance=cash or 0.0,
            derivative_buying_power=deriv_bp or 0.0,
            equity_buying_power=equity_bp or 0.0,
            maintenance_requirement=maint or 0.0,
            source="schwab",
            currency="USD",
        )


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
