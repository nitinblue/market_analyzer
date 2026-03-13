"""Shared broker connection helper for all CLI entry points.

Encapsulates TastyTrade session creation so every CLI uses
identical connection logic.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_analyzer.broker.base import (
        AccountProvider, MarketDataProvider, MarketMetricsProvider, WatchlistProvider,
    )


def _styled(text: str, style: str = "") -> str:
    """Basic ANSI styling."""
    codes = {
        "bold": "\033[1m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "cyan": "\033[36m",
        "dim": "\033[2m",
        "reset": "\033[0m",
    }
    if not sys.stdout.isatty():
        return text
    code = codes.get(style, "")
    return f"{code}{text}{codes['reset']}" if code else text


def connect_broker(
    is_paper: bool = False,
) -> tuple[
    MarketDataProvider | None,
    MarketMetricsProvider | None,
    AccountProvider | None,
    WatchlistProvider | None,
]:
    """Connect to TastyTrade broker. Returns (market_data, market_metrics, account, watchlist).

    Returns (None, None, None, None) on any failure — caller continues without broker.
    """
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        # Load eTrading .env first (has TASTYTRADE_* credentials)
        etrading_env = Path.home() / "PythonProjects" / "eTrading" / ".env"
        if etrading_env.exists():
            load_dotenv(etrading_env)
        load_dotenv()  # Also load local .env if present
    except ImportError:
        pass

    try:
        from market_analyzer.broker.tastytrade.session import TastyTradeBrokerSession
        from market_analyzer.broker.tastytrade.market_data import TastyTradeMarketData
        from market_analyzer.broker.tastytrade.metrics import TastyTradeMetrics
        from market_analyzer.broker.tastytrade.account import TastyTradeAccount
        from market_analyzer.broker.tastytrade.watchlist import TastyTradeWatchlist

        session = TastyTradeBrokerSession(is_paper=is_paper)
        if session.connect():
            market_data = TastyTradeMarketData(session)
            market_metrics = TastyTradeMetrics(session)
            account = TastyTradeAccount(session)
            watchlist = TastyTradeWatchlist(session)
            print(_styled(
                f"Broker connected: {session.account.account_number}", "green",
            ))
            return market_data, market_metrics, account, watchlist
        else:
            print(_styled("Broker connection failed — running without broker", "yellow"))
            return None, None, None, None

    except ImportError:
        print(_styled("tastytrade SDK not installed — running without broker", "yellow"))
        return None, None, None, None
    except Exception as e:
        print(_styled(f"Broker unavailable: {e}", "yellow"))
        return None, None, None, None


def add_broker_args(parser) -> None:
    """Add standard --broker flag to an argparse parser."""
    parser.add_argument(
        "--broker",
        action="store_true",
        help="Connect to TastyTrade broker for live quotes/Greeks",
    )
    parser.add_argument(
        "--paper",
        action="store_true",
        help="Use paper trading account (with --broker)",
    )
