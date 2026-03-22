"""Dhan watchlist provider — registry-based fallback.

Dhan does not expose a watchlist management API (as of SDK 2.1.0).
We implement the WatchlistProvider interface using the market registry
presets (india_fno, india_index, nifty50, etc.) as named watchlists.

If a requested name matches a registry preset, we return those tickers.
Otherwise we return an empty list and log a warning.
"""

from __future__ import annotations

import logging

from income_desk.broker.base import WatchlistProvider

logger = logging.getLogger(__name__)

# Well-known registry preset names for India market
_REGISTRY_PRESETS = [
    "india_fno",
    "india_index",
    "nifty50",
    "nifty_bank",
    "income",
    "directional",
    "broad",
]


class DhanWatchlist(WatchlistProvider):
    """Dhan WatchlistProvider using market registry presets as named watchlists.

    Dhan has no watchlist API. Supported 'watchlist' names:
    - Any MarketRegistry preset (india_fno, india_index, nifty50, etc.)
    - "positions" → returns the standard India F&O universe as a proxy

    For real position-based watchlists, eTrading should maintain its own
    position tracking and pass tickers directly.
    """

    def __init__(self, client: object | None = None) -> None:
        """Args:
            client: Unused — kept for API consistency with other providers.
        """
        self._client = client

    def get_watchlist(self, name: str) -> list[str]:
        """Get tickers from a named watchlist source.

        Dhan has no native watchlist API. This resolves:
        - Registry presets: india_fno, india_index, nifty50, etc.
        - "default" or "positions" → india_fno preset

        Args:
            name: Watchlist name or registry preset identifier.

        Returns:
            List of tickers, or empty list if name not recognized.
        """
        name_lower = name.lower().strip()

        # Aliases
        if name_lower in ("default", "positions", "holdings"):
            name_lower = "india_fno"

        try:
            from income_desk.registry import MarketRegistry
            tickers = MarketRegistry().get_universe(preset=name_lower, market="INDIA")
            if tickers:
                return tickers
        except Exception as e:
            logger.debug("Registry lookup for %r failed: %s", name, e)

        logger.warning(
            "Dhan watchlist %r not found. "
            "Dhan has no watchlist API — use registry presets: %s",
            name,
            ", ".join(_REGISTRY_PRESETS),
        )
        return []

    def list_watchlists(self) -> list[str]:
        """List available named sources (registry presets only).

        Returns:
            List of preset names available via the market registry.
        """
        available = []
        try:
            from income_desk.registry import MarketRegistry
            reg = MarketRegistry()
            for preset in _REGISTRY_PRESETS:
                try:
                    tickers = reg.get_universe(preset=preset, market="INDIA")
                    if tickers:
                        available.append(f"{preset} ({len(tickers)} tickers)")
                except Exception:
                    pass
        except Exception:
            pass

        if not available:
            available = [f"[preset] {p}" for p in _REGISTRY_PRESETS]

        return available

    def create_watchlist(self, name: str, tickers: list[str]) -> bool:
        """Not supported — Dhan has no watchlist API.

        Returns False. eTrading should store watchlists in its own DB.
        """
        logger.warning(
            "Dhan does not support watchlist creation via API. "
            "Store watchlists in eTrading's database instead."
        )
        return False

    def get_all_equities(
        self,
        is_etf: bool | None = None,
        is_index: bool | None = None,
    ) -> list[dict]:
        """Get all NSE F&O eligible equities from market registry.

        Dhan does not provide a bulk instrument listing API.
        Returns registry preset entries with basic metadata.

        Args:
            is_etf: If True, filter to ETFs only (not supported — returns all).
            is_index: If True, return index underlyings only.

        Returns:
            List of dicts with ticker, name, exchange fields.
        """
        from income_desk.broker.dhan.market_data import _SCRIP_CODES, _LOT_SIZES

        if is_index:
            # Return known index underlyings
            return [
                {
                    "ticker": ticker,
                    "name": ticker,
                    "exchange": "NSE_FNO",
                    "scrip_code": code,
                    "lot_size": _LOT_SIZES.get(ticker, 1),
                    "instrument_type": "INDEX",
                }
                for ticker, code in _SCRIP_CODES.items()
            ]

        # Try registry
        try:
            from income_desk.registry import MarketRegistry
            tickers = MarketRegistry().get_universe(preset="india_fno", market="INDIA")
            return [
                {
                    "ticker": t,
                    "name": t,
                    "exchange": "NSE_FNO",
                    "instrument_type": "EQ",
                }
                for t in tickers
            ]
        except Exception:
            pass

        return []
