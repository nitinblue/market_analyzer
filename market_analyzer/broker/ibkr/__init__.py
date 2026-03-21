"""Interactive Brokers integration — optional sub-package.

Requires ``ib_insync`` SDK and TWS/IB Gateway running locally:
``pip install 'market-analyzer[ibkr]'``

Requires:
- TWS or IB Gateway running (default: localhost:7497 for paper)
- API access enabled in TWS settings

Common ports:
- TWS paper trading: 7497
- TWS live trading:  7496
- IB Gateway paper:  4002
- IB Gateway live:   4001

Usage::

    from market_analyzer.broker.ibkr import connect_ibkr

    market_data, _, account, _ = connect_ibkr(host="127.0.0.1", port=7497)
    ma = MarketAnalyzer(data_service=DataService(), market_data=market_data)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_analyzer.broker.ibkr.account import IBKRAccount
    from market_analyzer.broker.ibkr.market_data import IBKRMarketData

logger = logging.getLogger(__name__)


def connect_ibkr(
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 1,
) -> tuple[IBKRMarketData | None, None, IBKRAccount | None, None]:
    """Connect to Interactive Brokers via ib_insync.

    Requires TWS or IB Gateway running at the specified host:port.

    Args:
        host: TWS/Gateway host. Default: 127.0.0.1
        port: TWS/Gateway API port. Default: 7497 (TWS paper).
              Use 7496 for live TWS, 4002 for Gateway paper, 4001 for Gateway live.
        client_id: Unique client ID for this connection (1-32).

    Returns:
        4-tuple ``(MarketDataProvider, None, AccountProvider, None)``.
        MarketMetricsProvider is None — IBKR metrics come through market data.

    Raises:
        ImportError: If ``ib_insync`` is not installed.
        ConnectionError: If TWS/Gateway is not reachable.
    """
    try:
        from ib_insync import IB  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "ib_insync is not installed. Run: pip install 'market-analyzer[ibkr]'"
        ) from exc

    from market_analyzer.broker.ibkr.account import IBKRAccount
    from market_analyzer.broker.ibkr.market_data import IBKRMarketData

    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id)
    except Exception as exc:
        raise ConnectionError(
            f"IBKR connection failed ({host}:{port}). "
            "Ensure TWS or IB Gateway is running with API access enabled.\n"
            f"Error: {exc}"
        ) from exc

    return (
        IBKRMarketData(ib),
        None,  # IBKR metrics come via market data (modelGreeks)
        IBKRAccount(ib),
        None,  # No watchlist provider
    )
