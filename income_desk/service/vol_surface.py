"""VolSurfaceService: volatility surface analysis via DataService or broker."""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

from income_desk.features.vol_surface import compute_vol_surface
from income_desk.models.vol_surface import (
    SkewSlice,
    TermStructurePoint,
    VolatilitySurface,
)

if TYPE_CHECKING:
    from income_desk.adapters.base import MarketDataProvider
    from income_desk.data.service import DataService

logger = logging.getLogger(__name__)


class VolSurfaceService:
    """Compute volatility surfaces from options chain data.

    Tries ``market_data`` (broker, e.g. Dhan) first — this gives real IV
    and Greeks.  Falls back to ``data_service`` (yfinance) which only has
    chain structure.
    """

    def __init__(
        self,
        data_service: DataService | None = None,
        market_data: MarketDataProvider | None = None,
    ) -> None:
        self.data_service = data_service
        self.market_data = market_data
        # Session-level cache: one chain fetch per ticker per session.
        # Prevents Dhan rate-limit errors when ranking calls vol_surface
        # for the same ticker across multiple assessors.
        self._surface_cache: dict[str, VolatilitySurface] = {}
        self._last_broker_call: float = 0.0

    def surface(self, ticker: str, as_of: date | None = None) -> VolatilitySurface:
        """Fetch options chain + OHLCV, compute vol surface."""

        # Check session cache first
        if ticker in self._surface_cache:
            return self._surface_cache[ticker]

        # --- Try broker (Dhan / TastyTrade) first ---
        if self.market_data is not None:
            try:
                chain_df = self._chain_from_broker(ticker)
                if chain_df is not None and not chain_df.empty:
                    underlying_price = self._underlying_from_broker(ticker, chain_df)
                    result = compute_vol_surface(chain_df, underlying_price, ticker, as_of=as_of)
                    self._surface_cache[ticker] = result
                    return result
            except Exception as exc:
                logger.debug("Broker vol surface failed for %s: %s", ticker, exc)

        # --- Fall back to DataService (yfinance) ---
        if self.data_service is None:
            raise ValueError(
                "VolSurfaceService requires either market_data (broker) or "
                "data_service to fetch options chain data"
            )

        chain_df = self.data_service.get_options_chain(ticker)
        ohlcv = self.data_service.get_ohlcv(ticker)
        if ohlcv is None or ohlcv.empty:
            raise ValueError(f"No OHLCV data for {ticker} — cannot compute vol surface")
        underlying_price = float(ohlcv["Close"].iloc[-1])

        return compute_vol_surface(chain_df, underlying_price, ticker, as_of=as_of)

    # --- Broker helpers ------------------------------------------------

    def _chain_from_broker(self, ticker: str) -> pd.DataFrame | None:
        """Convert broker option chain to the DataFrame format compute_vol_surface expects.

        Note: This is only called as a fallback when no ChainBundle is available.
        In the normal pipeline, ChainFetcher provides the vol_surface directly
        via the bundle, so this method is never reached.
        """

        raw = self.market_data.get_option_chain(ticker)  # type: ignore[union-attr]
        if raw is None or len(raw) == 0:
            return None

        # Broker returns list[OptionQuote] — convert to DataFrame
        rows: list[dict] = []
        for q in raw:
            row = q.model_dump() if hasattr(q, "model_dump") else vars(q)
            rows.append(row)

        df = pd.DataFrame(rows)

        # Normalise column names to what compute_vol_surface expects
        rename = {}
        if "implied_volatility" not in df.columns and "iv" in df.columns:
            rename["iv"] = "implied_volatility"
        if rename:
            df = df.rename(columns=rename)

        # Keep rows that have either bid/ask activity OR IV data.
        # Pre-market / post-market: bid/ask may be 0 but IV is still valid.
        has_bid_ask = "bid" in df.columns and "ask" in df.columns
        has_iv = "implied_volatility" in df.columns
        if has_bid_ask and has_iv:
            df = df[
                (df["bid"] > 0) | (df["ask"] > 0) |
                (df["implied_volatility"].notna() & (df["implied_volatility"] > 0))
            ]
        elif has_bid_ask:
            df = df[(df["bid"] > 0) | (df["ask"] > 0)]

        return df

    def _underlying_from_broker(self, ticker: str, chain_df: pd.DataFrame) -> float:
        """Get underlying price from broker, falling back to OHLCV."""
        try:
            price = self.market_data.get_underlying_price(ticker)  # type: ignore[union-attr]
            if price and price > 0:
                return price
        except Exception:
            pass

        # Fall back to OHLCV
        if self.data_service is not None:
            try:
                ohlcv = self.data_service.get_ohlcv(ticker)
                return float(ohlcv["Close"].iloc[-1])
            except Exception:
                pass

        # Last resort: mid of ATM strikes from chain
        if not chain_df.empty and "strike" in chain_df.columns:
            return float(chain_df["strike"].median())
        return 0.0

    # --- Convenience methods -------------------------------------------

    def term_structure(self, ticker: str) -> list[TermStructurePoint]:
        """Convenience: just the term structure."""
        surf = self.surface(ticker)
        return surf.term_structure

    def skew(self, ticker: str, expiration: date | None = None) -> SkewSlice | None:
        """Convenience: skew for nearest (or specified) expiration."""
        surf = self.surface(ticker)
        if not surf.skew_by_expiry:
            return None
        if expiration is None:
            return surf.skew_by_expiry[0]
        for s in surf.skew_by_expiry:
            if s.expiration == expiration:
                return s
        return None

    def calendar_edge(self, ticker: str) -> float:
        """Convenience: calendar edge score (0-1)."""
        surf = self.surface(ticker)
        return surf.calendar_edge_score
