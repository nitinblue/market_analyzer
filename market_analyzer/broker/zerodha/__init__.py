"""Zerodha (Kite) broker integration for India NSE/BSE markets.

Stub implementation — actual API integration pending Kite Connect SDK access.
"""

from market_analyzer.broker.zerodha.account import ZerodhaAccount
from market_analyzer.broker.zerodha.market_data import ZerodhaMarketData
from market_analyzer.broker.zerodha.metrics import ZerodhaMetrics
from market_analyzer.broker.zerodha.watchlist import ZerodhaWatchlist


def connect_zerodha(api_key: str, access_token: str) -> tuple[
    ZerodhaMarketData, ZerodhaMetrics, ZerodhaAccount, ZerodhaWatchlist
]:
    """Create Zerodha providers from Kite Connect credentials."""
    md = ZerodhaMarketData(api_key=api_key, access_token=access_token)
    mm = ZerodhaMetrics(api_key=api_key, access_token=access_token)
    acct = ZerodhaAccount(api_key=api_key, access_token=access_token)
    wl = ZerodhaWatchlist(api_key=api_key, access_token=access_token)
    return md, mm, acct, wl


def connect_zerodha_from_session(session: object) -> tuple[
    ZerodhaMarketData, ZerodhaMetrics, ZerodhaAccount, ZerodhaWatchlist
]:
    """Create Zerodha providers from pre-authenticated session (SaaS pattern)."""
    md = ZerodhaMarketData(session=session)
    mm = ZerodhaMetrics(session=session)
    acct = ZerodhaAccount(session=session)
    wl = ZerodhaWatchlist(session=session)
    return md, mm, acct, wl


__all__ = [
    "ZerodhaMarketData",
    "ZerodhaMetrics",
    "ZerodhaAccount",
    "ZerodhaWatchlist",
    "connect_zerodha",
    "connect_zerodha_from_session",
]
