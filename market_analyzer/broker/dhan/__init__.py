"""Dhan broker integration for India NSE/BSE markets.

Stub implementation — actual API integration pending Dhan SDK access.
"""

from market_analyzer.broker.dhan.account import DhanAccount
from market_analyzer.broker.dhan.market_data import DhanMarketData
from market_analyzer.broker.dhan.metrics import DhanMetrics
from market_analyzer.broker.dhan.watchlist import DhanWatchlist


def connect_dhan(api_key: str, access_token: str) -> tuple[
    DhanMarketData, DhanMetrics, DhanAccount, DhanWatchlist
]:
    """Create Dhan providers from credentials."""
    md = DhanMarketData(api_key=api_key, access_token=access_token)
    mm = DhanMetrics(api_key=api_key, access_token=access_token)
    acct = DhanAccount(api_key=api_key, access_token=access_token)
    wl = DhanWatchlist(api_key=api_key, access_token=access_token)
    return md, mm, acct, wl


def connect_dhan_from_session(session: object) -> tuple[
    DhanMarketData, DhanMetrics, DhanAccount, DhanWatchlist
]:
    """Create Dhan providers from pre-authenticated session (SaaS pattern)."""
    md = DhanMarketData(session=session)
    mm = DhanMetrics(session=session)
    acct = DhanAccount(session=session)
    wl = DhanWatchlist(session=session)
    return md, mm, acct, wl


__all__ = [
    "DhanMarketData",
    "DhanMetrics",
    "DhanAccount",
    "DhanWatchlist",
    "connect_dhan",
    "connect_dhan_from_session",
]
