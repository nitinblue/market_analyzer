"""Dhan account provider — balance and buying power via DhanHQ fund limits API.

DhanHQ get_fund_limits() returns:
- availabelBalance (sic — Dhan API typo): available cash
- utilizedAmount: margin currently in use
- clientId: account identifier

All amounts in INR.
"""

from __future__ import annotations

import logging

from income_desk.broker.base import AccountProvider
from income_desk.models.quotes import AccountBalance

logger = logging.getLogger(__name__)


class DhanAccount(AccountProvider):
    """Dhan AccountProvider via DhanHQ fund limits REST API.

    Note on Dhan's typo: The API returns ``availabelBalance`` (with typo).
    We handle both ``availabelBalance`` and ``availableBalance`` for robustness.
    """

    def __init__(self, client: object) -> None:
        """Args:
            client: Pre-authenticated ``dhanhq`` instance.
        """
        self._client = client

    def get_balance(self) -> AccountBalance:
        """Fetch fund limits from Dhan and return AccountBalance.

        Returns:
            AccountBalance with INR amounts and 'dhan' source.

        Raises:
            ConnectionError: If Dhan API call fails or returns empty data.
        """
        try:
            response = self._client.get_fund_limits()
        except Exception as e:
            raise ConnectionError(f"Dhan get_fund_limits() failed: {e}") from e

        if not response:
            raise ConnectionError("Dhan returned empty fund limits response")

        # Response may be nested under 'data' or at top level
        data = response.get("data", response) if isinstance(response, dict) else {}
        if not data:
            raise ConnectionError("Dhan fund limits: empty data field")

        # Dhan API has a typo: "availabelBalance" — handle both spellings
        available = float(
            data.get("availabelBalance")
            or data.get("availableBalance")
            or data.get("availableAllBalance")
            or 0
        )
        utilized = float(
            data.get("utilizedAmount")
            or data.get("utilisedAmount")
            or 0
        )
        client_id = str(data.get("clientId") or data.get("dhanClientId") or "")

        # Net liquidating value: available + utilized (total funds on account)
        nlv = available + utilized

        return AccountBalance(
            account_number=client_id,
            net_liquidating_value=nlv,
            cash_balance=available,
            # Derivative buying power: what's available after current margin usage
            derivative_buying_power=max(0.0, available),
            equity_buying_power=available,
            maintenance_requirement=utilized,
            pending_cash=0.0,
            source="dhan",
            currency="INR",
            timezone="Asia/Kolkata",
        )
