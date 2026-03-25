"""TastyTrade broker integration — optional sub-package.

Requires ``tastytrade`` SDK: ``pip install tastytrade-sdk``

Usage::

    from income_desk.broker.tastytrade import connect_tastytrade

    market_data, metrics, account = connect_tastytrade()
    ma = MarketAnalyzer(data_service=DataService(),
                        market_data=market_data, market_metrics=metrics,
                        account_provider=account)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from income_desk.broker.tastytrade.account import TastyTradeAccount
    from income_desk.broker.tastytrade.market_data import TastyTradeMarketData
    from income_desk.broker.tastytrade.metrics import TastyTradeMetrics
    from income_desk.broker.tastytrade.watchlist import TastyTradeWatchlist

logger = logging.getLogger(__name__)


def connect_tastytrade(
    config_path: str = "tastytrade_broker.yaml",
    is_paper: bool = False,
    *,
    exclude_account: bool = False,
) -> tuple:
    """Convenience: authenticate and return MarketData + Metrics + Account + Watchlist.

    Loads credentials from YAML + env vars.  For standalone / local usage.
    For SaaS (caller owns credentials), use ``connect_from_sessions()`` instead.

    Raises on auth failure.
    """
    from income_desk.broker.tastytrade.account import TastyTradeAccount
    from income_desk.broker.tastytrade.market_data import TastyTradeMarketData
    from income_desk.broker.tastytrade.metrics import TastyTradeMetrics
    from income_desk.broker.tastytrade.session import TastyTradeBrokerSession
    from income_desk.broker.tastytrade.watchlist import TastyTradeWatchlist

    session = TastyTradeBrokerSession(config_path=config_path, is_paper=is_paper)
    if not session.connect():
        raise ConnectionError("Failed to authenticate with TastyTrade")

    md = TastyTradeMarketData(session)
    mm = TastyTradeMetrics(session)
    wl = TastyTradeWatchlist(session)

    if exclude_account:
        return (md, mm, wl)  # 3-tuple: data only

    return (md, mm, TastyTradeAccount(session), wl)  # 4-tuple: backwards compat


def connect_from_sessions(
    sdk_session,
    data_session=None,
    *,
    exclude_account: bool = False,
) -> tuple:
    """Create providers from pre-authenticated tastytrade SDK sessions.

    SaaS pattern: the caller (eTrading) owns authentication and passes
    already-connected sessions.  market_analyzer never touches credentials.

    Args:
        sdk_session: An authenticated ``tastytrade.Session`` (for REST API calls).
        data_session: An authenticated ``tastytrade.Session`` for DXLink streaming.
                      Defaults to *sdk_session* if not provided.
    """
    from income_desk.broker.tastytrade.account import TastyTradeAccount
    from income_desk.broker.tastytrade.market_data import TastyTradeMarketData
    from income_desk.broker.tastytrade.metrics import TastyTradeMetrics
    from income_desk.broker.tastytrade.session import ExternalBrokerSession
    from income_desk.broker.tastytrade.watchlist import TastyTradeWatchlist

    wrapper = ExternalBrokerSession(sdk_session, data_session or sdk_session)

    md = TastyTradeMarketData(wrapper)
    mm = TastyTradeMetrics(wrapper)
    wl = TastyTradeWatchlist(wrapper)

    if exclude_account:
        return (md, mm, wl)  # 3-tuple: data only

    return (md, mm, TastyTradeAccount(wrapper), wl)  # 4-tuple: backwards compat
