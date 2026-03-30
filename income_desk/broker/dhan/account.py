"""Dhan account provider — balance and buying power via DhanHQ fund limits API.

DhanHQ get_fund_limits() returns (via dhanhq SDK wrapper)::

    {
        "status": "success",
        "data": {
            "dhanClientId": "...",
            "availabelBalance": 98440.0,   # available cash (note Dhan typo)
            "sodLimit": 113642.0,          # start-of-day total limit (best NLV proxy)
            "collateralAmount": 0.0,       # pledged stocks/MF collateral
            "receiveableAmount": 0.0,
            "utilizedAmount": 15202.0,     # margin currently in use
            "blockedPayoutAmount": 0.0,
            "withdrawableBalance": 98310.0,
        }
    }

All amounts in INR.
"""

from __future__ import annotations

import logging

from income_desk.broker.base import AccountProvider
from income_desk.models.quotes import AccountBalance

logger = logging.getLogger(__name__)


def _safe_float(data: dict, *keys: str) -> float:
    """Extract a float from *data* trying each key in order.

    Unlike an ``or``-chain, this correctly distinguishes a real ``0.0``
    value from a missing key.  Only ``None`` (key absent) triggers
    fallback to the next key.
    """
    for key in keys:
        val = data.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 0.0


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

        # dhanhq SDK wraps every response as {"status": ..., "data": ...}.
        # On success, data is the API JSON dict.  On failure, data is ''.
        if not isinstance(response, dict):
            raise ConnectionError("Dhan fund limits: unexpected response type")

        # Detect SDK-level failure before parsing
        if response.get("status") == "failure":
            remarks = response.get("remarks", "unknown error")
            raise ConnectionError(f"Dhan fund limits failed: {remarks}")

        # Extract the inner data dict from SDK wrapper
        inner = response.get("data")
        if isinstance(inner, dict) and inner:
            data = inner
        elif any(k in response for k in ("availabelBalance", "availableBalance", "dhanClientId")):
            # Raw API dict without SDK wrapper (e.g. in tests)
            data = response
        else:
            raise ConnectionError("Dhan fund limits: empty data field")

        # Use _safe_float to avoid the ``0.0 or fallback`` bug
        # (Python treats 0.0 as falsy, so an ``or``-chain skips valid zeros).
        available = _safe_float(data, "availabelBalance", "availableBalance")
        utilized = _safe_float(data, "utilizedAmount", "utilisedAmount")
        collateral = _safe_float(data, "collateralAmount")
        sod_limit = _safe_float(data, "sodLimit")
        receivable = _safe_float(data, "receiveableAmount", "receivableAmount")

        client_id = str(data.get("dhanClientId") or data.get("clientId") or "")

        # Net liquidating value — best representation of total account value.
        # sodLimit (start-of-day limit) is the most accurate NLV proxy from
        # Dhan because it includes cash + collateral + receivables.
        # Fall back to available + utilized + collateral if sodLimit is absent.
        if sod_limit > 0:
            nlv = sod_limit
        else:
            nlv = available + utilized + collateral

        # Buying power: available cash (what can be deployed for new trades)
        buying_power = max(0.0, available)

        return AccountBalance(
            account_number=client_id,
            net_liquidating_value=nlv,
            cash_balance=available,
            derivative_buying_power=buying_power,
            equity_buying_power=available,
            maintenance_requirement=utilized,
            pending_cash=receivable,
            source="dhan",
            currency="INR",
            timezone="Asia/Kolkata",
        )
