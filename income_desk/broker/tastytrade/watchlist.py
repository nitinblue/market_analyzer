"""TastyTrade watchlist provider — pull tickers from broker watchlists.

Uses the tastytrade SDK's PrivateWatchlist and PublicWatchlist classes
to fetch user-curated ticker lists for screening.

Also supports creating/updating watchlists via API and fetching
the full equity universe for filtering.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from income_desk.broker.base import WatchlistProvider

if TYPE_CHECKING:
    from income_desk.broker.tastytrade.session import TastyTradeBrokerSession

logger = logging.getLogger(__name__)


class TastyTradeWatchlist(WatchlistProvider):
    """Fetch watchlists from TastyTrade (private and public)."""

    def __init__(self, session: TastyTradeBrokerSession) -> None:
        self._session = session

    def get_watchlist(self, name: str) -> list[str]:
        """Fetch ticker symbols from a named watchlist.

        Tries private watchlists first, then public. Returns equity/ETF
        symbols only (filters out futures, crypto, etc.).
        """
        try:
            from tastytrade.watchlists import PrivateWatchlist, PublicWatchlist
            from income_desk.broker.tastytrade._async import run_sync
        except ImportError:
            logger.error("tastytrade SDK not installed")
            return []

        sdk = self._session.sdk_session
        tickers: list[str] = []

        # Try private first
        try:
            result = PrivateWatchlist.get(sdk, name)
            if hasattr(result, '__await__') or str(type(result)).find('coroutine') >= 0:
                result = run_sync(result)
            if result is not None:
                tickers = self._extract_tickers(result)
                if tickers:
                    logger.info("Loaded %d tickers from private watchlist '%s'", len(tickers), name)
                    return tickers
        except Exception as e:
            logger.debug("Private watchlist '%s' not found: %s", name, e)

        # Try public
        try:
            result = PublicWatchlist.get(sdk, name)
            if hasattr(result, '__await__') or str(type(result)).find('coroutine') >= 0:
                result = run_sync(result)
            if result is not None:
                tickers = self._extract_tickers(result)
                if tickers:
                    logger.info("Loaded %d tickers from public watchlist '%s'", len(tickers), name)
                    return tickers
        except Exception as e:
            logger.debug("Public watchlist '%s' not found: %s", name, e)

        logger.warning("Watchlist '%s' not found (private or public)", name)
        return []

    def list_watchlists(self) -> list[str]:
        """List all available watchlist names (private + public)."""
        try:
            from tastytrade.watchlists import PrivateWatchlist, PublicWatchlist
            from income_desk.broker.tastytrade._async import run_sync
        except ImportError:
            return []

        sdk = self._session.sdk_session
        names: list[str] = []

        try:
            result = PrivateWatchlist.get(sdk)
            if hasattr(result, '__await__') or str(type(result)).find('coroutine') >= 0:
                result = run_sync(result)
            if result:
                for wl in result:
                    names.append(f"[private] {wl.name}")
        except Exception as e:
            logger.debug("Failed to list private watchlists: %s", e)

        try:
            result = PublicWatchlist.get(sdk, counts_only=True)
            if hasattr(result, '__await__') or str(type(result)).find('coroutine') >= 0:
                result = run_sync(result)
            if result:
                for wl in result:
                    names.append(f"[public] {wl.name}")
        except Exception as e:
            logger.debug("Failed to list public watchlists: %s", e)

        return names

    def get_multiple_watchlists(self, names: list[str]) -> list[str]:
        """Fetch and merge tickers from multiple watchlists, deduped."""
        seen: set[str] = set()
        tickers: list[str] = []
        for name in names:
            for t in self.get_watchlist(name):
                if t not in seen:
                    seen.add(t)
                    tickers.append(t)
        return tickers

    def create_watchlist(self, name: str, tickers: list[str]) -> bool:
        """Create or update a private watchlist with the given tickers.

        If a watchlist with this name exists, it is replaced.
        """
        try:
            from tastytrade.watchlists import PrivateWatchlist
            from income_desk.broker.tastytrade._async import run_sync
        except ImportError:
            logger.error("tastytrade SDK not installed")
            return False

        sdk = self._session.sdk_session

        entries = [
            {"symbol": t, "instrument-type": "Equity"}
            for t in tickers
        ]

        try:
            # Try to delete existing first (ignore errors if not found)
            try:
                result = PrivateWatchlist.remove(sdk, name)
                if hasattr(result, '__await__') or str(type(result)).find('coroutine') >= 0:
                    run_sync(result)
            except Exception:
                pass

            wl = PrivateWatchlist(
                name=name,
                watchlist_entries=entries,
                group_name="market_analyzer",
                order_index=100,
            )
            result = wl.upload(sdk)
            if hasattr(result, '__await__') or str(type(result)).find('coroutine') >= 0:
                run_sync(result)

            logger.info("Created watchlist '%s' with %d tickers", name, len(tickers))
            return True
        except Exception as e:
            logger.error("Failed to create watchlist '%s': %s", name, e)
            return False

    def get_all_equities(
        self,
        is_etf: bool | None = None,
        is_index: bool | None = None,
    ) -> list[dict]:
        """Fetch all tradeable equities/ETFs from TastyTrade.

        Returns list of dicts: {symbol, is_etf, is_index, description, is_illiquid}.
        Paginates through all results automatically.
        """
        try:
            from tastytrade.instruments import Equity
            from income_desk.broker.tastytrade._async import run_sync
        except ImportError:
            logger.error("tastytrade SDK not installed")
            return []

        sdk = self._session.sdk_session

        try:
            # get_active_equities only accepts per_page/page_offset/lendability
            # is_etf/is_index filtering must be done locally
            result = Equity.get_active_equities(sdk, per_page=1000, page_offset=None)
            if hasattr(result, '__await__') or str(type(result)).find('coroutine') >= 0:
                result = run_sync(result, timeout=60)

            equities = []
            for eq in result:
                # Skip closing-only and halted
                if eq.is_closing_only or eq.is_options_closing_only:
                    continue

                # Apply local is_etf/is_index filters
                if is_etf is not None and eq.is_etf != is_etf:
                    continue
                if is_index is not None and eq.is_index != is_index:
                    continue

                equities.append({
                    "symbol": eq.symbol,
                    "is_etf": eq.is_etf,
                    "is_index": eq.is_index,
                    "description": eq.description,
                    "is_illiquid": eq.is_illiquid,
                    "listed_market": getattr(eq, "listed_market", None),
                })

            logger.info("Fetched %d active equities from TastyTrade", len(equities))
            return equities

        except Exception as e:
            logger.error("Failed to fetch equities: %s", e)
            return []

    @staticmethod
    def _extract_tickers(watchlist) -> list[str]:
        """Extract equity/ETF ticker symbols from a watchlist object."""
        tickers: list[str] = []
        if not hasattr(watchlist, 'watchlist_entries') or not watchlist.watchlist_entries:
            return tickers

        for entry in watchlist.watchlist_entries:
            # SDK returns dicts with 'symbol' and 'instrument-type'
            if isinstance(entry, dict):
                sym = entry.get("symbol", "")
                itype = entry.get("instrument-type", "Equity")
                if itype in ("Equity", "ETF", "Index") and sym:
                    tickers.append(sym)
            elif hasattr(entry, "symbol"):
                tickers.append(entry.symbol)

        return tickers
