"""Zerodha (Kite Connect) broker integration for India NSE/BSE markets.

Provides live option quotes, chain data, account balance, and instrument
lookup for all NSE F&O instruments via Kite Connect REST API.

Credentials: API key + daily access token (OAuth2 flow).
- Standalone: load from zerodha_credentials.yaml
- SaaS: eTrading passes pre-authenticated KiteConnect session

Usage::

    from market_analyzer.broker.zerodha import connect_zerodha
    md, mm, acct, wl = connect_zerodha(api_key="xxx", access_token="yyy")
    ma = MarketAnalyzer(data_service=DataService(), market="India",
                        market_data=md, market_metrics=mm,
                        account_provider=acct, watchlist_provider=wl)
"""

from market_analyzer.broker.zerodha.account import ZerodhaAccount
from market_analyzer.broker.zerodha.market_data import ZerodhaMarketData
from market_analyzer.broker.zerodha.metrics import ZerodhaMetrics
from market_analyzer.broker.zerodha.watchlist import ZerodhaWatchlist


def connect_zerodha(api_key: str, access_token: str) -> tuple[
    ZerodhaMarketData, ZerodhaMetrics, ZerodhaAccount, ZerodhaWatchlist
]:
    """Create Zerodha providers from Kite Connect credentials.

    Args:
        api_key: Kite Connect API key (from https://developers.kite.trade)
        access_token: Daily access token (from OAuth2 login flow)

    Returns:
        4-tuple: (MarketData, Metrics, Account, Watchlist) providers
    """
    md = ZerodhaMarketData(api_key=api_key, access_token=access_token)
    mm = ZerodhaMetrics(api_key=api_key, access_token=access_token, market_data=md)
    acct = ZerodhaAccount(api_key=api_key, access_token=access_token)
    wl = ZerodhaWatchlist(api_key=api_key, access_token=access_token)
    return md, mm, acct, wl


def connect_zerodha_from_session(session: object) -> tuple[
    ZerodhaMarketData, ZerodhaMetrics, ZerodhaAccount, ZerodhaWatchlist
]:
    """Create Zerodha providers from pre-authenticated KiteConnect session.

    For SaaS/eTrading: the platform handles OAuth login and passes
    the authenticated KiteConnect instance. MA never sees credentials.

    Args:
        session: Pre-authenticated KiteConnect instance

    Returns:
        4-tuple: (MarketData, Metrics, Account, Watchlist) providers
    """
    md = ZerodhaMarketData(session=session)
    mm = ZerodhaMetrics(session=session, market_data=md)
    acct = ZerodhaAccount(session=session)
    wl = ZerodhaWatchlist(session=session)
    return md, mm, acct, wl


def load_credentials(path: str = "zerodha_credentials.yaml") -> dict:
    """Load credentials from YAML file (standalone/CLI usage only).

    In SaaS mode, use connect_zerodha_from_session() instead.
    """
    from pathlib import Path
    import yaml

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Zerodha credentials not found at {p}. "
            f"Copy zerodha_credentials.yaml.template and fill in your values."
        )

    with open(p) as f:
        creds = yaml.safe_load(f)

    return {
        "api_key": creds.get("api_key", ""),
        "api_secret": creds.get("api_secret", ""),
        "access_token": creds.get("access_token", ""),
    }


__all__ = [
    "ZerodhaMarketData",
    "ZerodhaMetrics",
    "ZerodhaAccount",
    "ZerodhaWatchlist",
    "connect_zerodha",
    "connect_zerodha_from_session",
    "load_credentials",
]
