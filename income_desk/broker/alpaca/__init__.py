"""Alpaca broker integration — optional sub-package.

Requires ``alpaca-py`` SDK: ``pip install 'market-analyzer[alpaca]'``

Works with free tier (no funding required).
Get free API keys at: https://app.alpaca.markets/signup

Usage::

    from income_desk.broker.alpaca import connect_alpaca

    market_data, metrics, account, _ = connect_alpaca()
    ma = MarketAnalyzer(data_service=DataService(),
                        market_data=market_data, market_metrics=metrics,
                        account_provider=account)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from income_desk.broker.alpaca.account import AlpacaAccount
    from income_desk.broker.alpaca.market_data import AlpacaMarketData
    from income_desk.broker.alpaca.metrics import AlpacaMetrics

logger = logging.getLogger(__name__)


def connect_alpaca(
    api_key: str | None = None,
    api_secret: str | None = None,
    paper: bool = True,
) -> tuple[AlpacaMarketData | None, AlpacaMetrics | None, AlpacaAccount | None, None]:
    """Connect to Alpaca. Works with free tier (no funding needed).

    Credentials resolved in order:
    1. Explicit ``api_key`` / ``api_secret`` arguments
    2. Environment variables ``ALPACA_API_KEY`` / ``ALPACA_API_SECRET``
    3. ``~/.income_desk/broker.yaml`` under the ``alpaca`` key

    Args:
        api_key: Alpaca API key ID. If None, reads from env / config.
        api_secret: Alpaca API secret. If None, reads from env / config.
        paper: Use paper trading endpoint (default True).

    Returns:
        4-tuple ``(MarketDataProvider, MarketMetricsProvider, AccountProvider, None)``.
        The fourth element is always None — Alpaca has no watchlist concept.

    Raises:
        ImportError: If ``alpaca-py`` is not installed.
        ValueError: If credentials are missing.
    """
    try:
        from alpaca.trading.client import TradingClient  # noqa: F401
        from alpaca.data.historical import StockHistoricalDataClient  # noqa: F401
        from alpaca.data.historical.option import OptionHistoricalDataClient  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "alpaca-py is not installed. Run: pip install 'market-analyzer[alpaca]'"
        ) from exc

    from alpaca.trading.client import TradingClient
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.historical.option import OptionHistoricalDataClient
    from income_desk.broker.alpaca.account import AlpacaAccount
    from income_desk.broker.alpaca.market_data import AlpacaMarketData
    from income_desk.broker.alpaca.metrics import AlpacaMetrics

    key, secret = _resolve_credentials(api_key, api_secret)

    if not key or not secret:
        raise ValueError(
            "Alpaca API key and secret required. "
            "Get free keys at https://app.alpaca.markets/signup\n"
            "Then set ALPACA_API_KEY and ALPACA_API_SECRET environment variables."
        )

    trading = TradingClient(key, secret, paper=paper)
    stock_data = StockHistoricalDataClient(key, secret)
    option_data = OptionHistoricalDataClient(key, secret)

    return (
        AlpacaMarketData(stock_data, option_data),
        AlpacaMetrics(stock_data),
        AlpacaAccount(trading),
        None,  # No watchlist provider for Alpaca
    )


def _resolve_credentials(
    api_key: str | None,
    api_secret: str | None,
) -> tuple[str, str]:
    """Resolve Alpaca credentials from args, env vars, or config file."""
    key = api_key or os.environ.get("ALPACA_API_KEY", "")
    secret = api_secret or os.environ.get("ALPACA_API_SECRET", "")

    if key and secret:
        return key, secret

    # Try broker.yaml
    config_path = Path.home() / ".income_desk" / "broker.yaml"
    if config_path.exists():
        try:
            import yaml
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            alpaca_cfg = cfg.get("alpaca", {})
            key = key or alpaca_cfg.get("api_key", "")
            secret = secret or alpaca_cfg.get("api_secret", "")
        except Exception:
            pass

    return key, secret
