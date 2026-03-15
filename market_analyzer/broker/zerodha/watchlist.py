"""Zerodha watchlist provider — uses holdings + positions as proxy.

Kite Connect doesn't have a native watchlist API.
We use portfolio holdings and F&O positions as "watchlist" sources.
For curated universes, use MarketRegistry.get_universe() instead.
"""

from __future__ import annotations

import logging

from market_analyzer.broker.base import WatchlistProvider, TokenExpiredError

logger = logging.getLogger(__name__)


class ZerodhaWatchlist(WatchlistProvider):
    """Zerodha WatchlistProvider using holdings/positions as proxy.

    Kite doesn't have a native watchlist API. Instead:
    - "holdings" → equity portfolio tickers
    - "positions" → currently open F&O positions
    - For scanning universes, use MarketRegistry.get_universe()
    """

    def __init__(
        self,
        api_key: str = "",
        access_token: str = "",
        session: object = None,
    ) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._session = session
        self._kite = None

    def _get_kite(self):
        if self._kite is not None:
            return self._kite

        from kiteconnect import KiteConnect

        if self._session is not None and isinstance(self._session, KiteConnect):
            self._kite = self._session
        else:
            self._kite = KiteConnect(api_key=self._api_key)
            if self._access_token:
                self._kite.set_access_token(self._access_token)

        return self._kite

    def get_watchlist(self, name: str) -> list[str]:
        """Get tickers from a named source.

        Supported names:
        - "holdings" → equity portfolio tickers
        - "positions" → open F&O position tickers
        - Any registry preset → delegates to MarketRegistry.get_universe()
        """
        name_lower = name.lower()

        if name_lower == "holdings":
            return self._get_holdings_tickers()
        elif name_lower == "positions":
            return self._get_position_tickers()
        else:
            # Try registry preset
            try:
                from market_analyzer.registry import MarketRegistry
                tickers = MarketRegistry().get_universe(preset=name_lower, market="INDIA")
                if tickers:
                    return tickers
            except Exception:
                pass
            logger.warning("Watchlist '%s' not found. Try: holdings, positions, or a registry preset.", name)
            return []

    def list_watchlists(self) -> list[str]:
        """List available watchlist sources."""
        available = ["holdings", "positions"]
        # Add registry presets
        try:
            from market_analyzer.registry import MarketRegistry
            for preset in ["india_fno", "india_index", "nifty50", "income", "directional"]:
                tickers = MarketRegistry().get_universe(preset=preset, market="INDIA")
                if tickers:
                    available.append(f"[preset] {preset} ({len(tickers)} tickers)")
        except Exception:
            pass
        return available

    def create_watchlist(self, name: str, tickers: list[str]) -> bool:
        """Not supported by Kite — use GTT orders or external storage."""
        logger.warning("Zerodha doesn't support watchlist creation via API.")
        return False

    def get_all_equities(
        self,
        is_etf: bool | None = None,
        is_index: bool | None = None,
    ) -> list[dict]:
        """Get all NSE equities from instruments master."""
        kite = self._get_kite()

        try:
            instruments = kite.instruments(exchange="NSE")
            results = []
            for inst in instruments:
                itype = inst.get("instrument_type", "")
                # Filter by segment
                if is_index and itype != "INDEX":
                    continue
                if is_etf is not None:
                    # Kite doesn't tag ETFs directly — skip this filter
                    pass
                if itype == "EQ" or (is_index and itype == "INDEX"):
                    results.append({
                        "ticker": inst.get("tradingsymbol", ""),
                        "name": inst.get("name", ""),
                        "instrument_token": inst.get("instrument_token"),
                        "lot_size": inst.get("lot_size", 1),
                        "exchange": "NSE",
                    })
            return results
        except Exception as e:
            if "TokenException" in type(e).__name__:
                raise TokenExpiredError(f"Zerodha token expired: {e}")
            logger.warning("Failed to get NSE equities: %s", e)
            return []

    def _get_holdings_tickers(self) -> list[str]:
        """Get tickers from equity holdings."""
        kite = self._get_kite()
        try:
            holdings = kite.holdings()
            return list(set(h.get("tradingsymbol", "") for h in holdings if h.get("quantity", 0) > 0))
        except Exception as e:
            if "TokenException" in type(e).__name__:
                raise TokenExpiredError(f"Zerodha token expired: {e}")
            logger.warning("Failed to get holdings: %s", e)
            return []

    def _get_position_tickers(self) -> list[str]:
        """Get underlying tickers from F&O positions."""
        kite = self._get_kite()
        try:
            positions = kite.positions()
            net = positions.get("net", [])
            # Extract underlying from tradingsymbol (e.g., "NIFTY26MAR22500CE" → "NIFTY")
            tickers = set()
            for p in net:
                sym = p.get("tradingsymbol", "")
                # F&O symbols start with underlying name
                for known in ["NIFTY", "BANKNIFTY", "FINNIFTY", "RELIANCE", "TCS",
                              "INFY", "HDFCBANK", "ICICIBANK", "SBIN"]:
                    if sym.startswith(known):
                        tickers.add(known)
                        break
            return list(tickers)
        except Exception as e:
            if "TokenException" in type(e).__name__:
                raise TokenExpiredError(f"Zerodha token expired: {e}")
            logger.warning("Failed to get positions: %s", e)
            return []
