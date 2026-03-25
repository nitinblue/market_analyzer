"""Dhan broker integration for India NSE/NFO markets.

Provides live option quotes with Greeks, account balance, and metrics
for all NSE F&O instruments via DhanHQ REST API.

Credentials: client_id + access_token (from https://dhanhq.co/).
- Standalone: args, env vars (DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN),
  or ~/.income_desk/broker.yaml
- SaaS: pass pre-authenticated dhanhq client instance

Usage::

    from income_desk.broker.dhan import connect_dhan
    md, mm, acct, wl = connect_dhan()  # reads env / yaml
    ma = MarketAnalyzer(data_service=DataService(), market="India",
                        market_data=md, market_metrics=mm,
                        account_provider=acct)
"""

from __future__ import annotations

from income_desk.broker.dhan.account import DhanAccount
from income_desk.broker.dhan.market_data import DhanMarketData
from income_desk.broker.dhan.metrics import DhanMetrics
from income_desk.broker.dhan.watchlist import DhanWatchlist


def connect_dhan(
    client_id: str | None = None,
    access_token: str | None = None,
    *,
    api_key: str | None = None,  # Backward-compat alias for client_id
    exclude_account: bool = False,
) -> tuple:
    """Connect to Dhan broker and return provider 4-tuple.

    Credential resolution order:
    1. ``client_id`` / ``access_token`` arguments
    2. Env vars: ``DHAN_CLIENT_ID`` / ``DHAN_ACCESS_TOKEN``
    3. ``~/.income_desk/broker.yaml`` → ``dhan.client_id`` / ``dhan.access_token``

    Args:
        client_id: Dhan client ID (from https://dhanhq.co/).
        access_token: Dhan access token.

    Returns:
        4-tuple: (MarketDataProvider, MarketMetricsProvider, AccountProvider, None)
        Watchlist is None — Dhan does not expose a watchlist API.

    Raises:
        ImportError: If dhanhq SDK is not installed.
        ValueError: If credentials are missing from all sources.
    """
    try:
        from dhanhq import dhanhq  # type: ignore[import]
    except ImportError:
        raise ImportError(
            "Dhan SDK not installed. Run: pip install dhanhq\n"
            "Get credentials at: https://dhanhq.co/"
        )

    import os

    # api_key is a backward-compat alias for client_id
    cid = client_id or api_key or os.environ.get("DHAN_CLIENT_ID", "")
    token = access_token or os.environ.get("DHAN_ACCESS_TOKEN", "") or os.environ.get("DHAN_TOKEN", "")

    # Try to extract client_id from JWT if not provided
    if not cid and token:
        try:
            import base64
            import json
            payload = token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            jwt_data = json.loads(base64.b64decode(payload))
            cid = str(jwt_data.get("dhanClientId", ""))
        except Exception:
            pass

    if not cid or not token:
        # Try broker.yaml
        from pathlib import Path

        yaml_path = Path.home() / ".income_desk" / "broker.yaml"
        if yaml_path.exists():
            try:
                import yaml

                with open(yaml_path) as f:
                    cfg = yaml.safe_load(f) or {}
                dhan_cfg = cfg.get("dhan", {})
                cid = cid or str(dhan_cfg.get("client_id", ""))
                token = token or str(dhan_cfg.get("access_token", ""))
            except Exception:
                pass

    if not cid or not token:
        raise ValueError(
            "Dhan credentials required. Set DHAN_CLIENT_ID + DHAN_TOKEN "
            "or add to ~/.income_desk/broker.yaml under 'dhan:' key."
        )

    client = dhanhq(cid, token)

    md = DhanMarketData(client)
    mm = DhanMetrics(client)

    if exclude_account:
        return (md, mm, None)  # 3-tuple: data only (watchlist is None for Dhan)

    return (md, mm, DhanAccount(client), None)  # 4-tuple: backwards compat


def connect_dhan_from_session(
    session: object,
    *,
    exclude_account: bool = False,
) -> tuple:
    """Create Dhan providers from a pre-authenticated dhanhq client.

    For SaaS/eTrading: the platform handles authentication and passes
    the authenticated dhanhq instance. MA never sees credentials.

    Args:
        session: Pre-authenticated ``dhanhq`` client instance.

    Returns:
        4-tuple: (MarketData, Metrics, Account, None)
    """
    md = DhanMarketData(session)
    mm = DhanMetrics(session)

    if exclude_account:
        return (md, mm, None)  # 3-tuple: data only

    return (md, mm, DhanAccount(session), None)  # 4-tuple: backwards compat


__all__ = [
    "DhanMarketData",
    "DhanMetrics",
    "DhanAccount",
    "DhanWatchlist",
    "connect_dhan",
    "connect_dhan_from_session",
]
