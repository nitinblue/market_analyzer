"""Alpaca market data provider.

Implements MarketDataProvider using alpaca-py SDK.

Free tier provides delayed stock/option snapshots.
Paid tier adds real-time quotes and Level 2 data.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from market_analyzer.broker.base import MarketDataProvider

if TYPE_CHECKING:
    from market_analyzer.models.opportunity import LegSpec
    from market_analyzer.models.quotes import OptionQuote

logger = logging.getLogger(__name__)

# OCC symbol pattern: TICKER(1-6) + YYMMDD + C/P + 8-digit strike*1000
# e.g. SPY   260424C00580000
_OCC_RE = re.compile(
    r"^([A-Z]{1,6})\s*(\d{6})([CP])(\d{8})$"
)


def _parse_occ(symbol: str) -> tuple[str, date, str, float] | None:
    """Parse an OCC option symbol into (ticker, expiration, option_type, strike).

    Returns None if the symbol cannot be parsed.
    """
    m = _OCC_RE.match(symbol.strip())
    if not m:
        return None
    ticker = m.group(1).strip()
    yymmdd = m.group(2)
    cp = m.group(3)
    strike_raw = int(m.group(4))
    try:
        exp = datetime.strptime(yymmdd, "%y%m%d").date()
    except ValueError:
        return None
    option_type = "call" if cp == "C" else "put"
    strike = strike_raw / 1000.0
    return ticker, exp, option_type, strike


def _build_occ(ticker: str, leg: LegSpec) -> str:
    """Build an OCC option symbol from a LegSpec.

    OCC format: ``SPY   260424C00580000``
    (6-char padded ticker, YYMMDD, C/P, 8-digit strike * 1000)
    """
    padded = ticker.ljust(6)
    yymmdd = leg.expiration.strftime("%y%m%d")
    cp = "C" if leg.option_type == "call" else "P"
    strike_int = int(leg.strike * 1000)
    return f"{padded}{yymmdd}{cp}{strike_int:08d}"


class AlpacaMarketData(MarketDataProvider):
    """Alpaca market data — works with free tier.

    Free tier provides:
    - Delayed stock quotes (15 min)
    - Options snapshots (delayed)
    - Historical bars

    Paid tier adds:
    - Real-time quotes
    - Level 2 data
    """

    def __init__(self, stock_client, option_client) -> None:
        """
        Args:
            stock_client: ``alpaca.data.historical.StockHistoricalDataClient``
            option_client: ``alpaca.data.historical.option.OptionHistoricalDataClient``
        """
        self._stock = stock_client
        self._option = option_client

    @property
    def provider_name(self) -> str:
        return "alpaca"

    @property
    def currency(self) -> str:
        return "USD"

    @property
    def timezone(self) -> str:
        return "US/Eastern"

    # ------------------------------------------------------------------
    # MarketDataProvider interface
    # ------------------------------------------------------------------

    def get_option_chain(
        self, ticker: str, expiration: date | None = None
    ) -> list[OptionQuote]:
        """Fetch option chain snapshots from Alpaca.

        Alpaca returns options for the full chain of an underlying.
        If ``expiration`` is provided, filters to that date only.
        """
        from market_analyzer.models.quotes import OptionQuote

        try:
            from alpaca.data.requests import OptionSnapshotRequest
        except ImportError as exc:
            raise ImportError(
                "alpaca-py is not installed. Run: pip install 'market-analyzer[alpaca]'"
            ) from exc

        try:
            request = OptionSnapshotRequest(underlying_symbol=[ticker])
            snapshots = self._option.get_option_snapshot(request)
        except Exception as exc:
            logger.warning("Alpaca option chain fetch failed for %s: %s", ticker, exc)
            return []

        results: list[OptionQuote] = []
        for symbol, snap in snapshots.items():
            parsed = _parse_occ(symbol)
            if parsed is None:
                continue
            _, exp, option_type, strike = parsed

            if expiration is not None and exp != expiration:
                continue

            bid = 0.0
            ask = 0.0
            if snap.latest_quote is not None:
                bid = float(snap.latest_quote.bid_price or 0)
                ask = float(snap.latest_quote.ask_price or 0)
            mid = (bid + ask) / 2

            iv = None
            delta = gamma = theta = vega = None
            if snap.greeks is not None:
                iv = _safe_float(snap.greeks.implied_volatility)
                delta = _safe_float(snap.greeks.delta)
                gamma = _safe_float(snap.greeks.gamma)
                theta = _safe_float(snap.greeks.theta)
                vega = _safe_float(snap.greeks.vega)
            elif hasattr(snap, "implied_volatility"):
                iv = _safe_float(snap.implied_volatility)

            volume = 0
            if snap.daily_bar is not None:
                volume = int(snap.daily_bar.volume or 0)

            oi = int(snap.open_interest or 0) if hasattr(snap, "open_interest") else 0

            results.append(OptionQuote(
                ticker=ticker,
                expiration=exp,
                strike=strike,
                option_type=option_type,
                bid=bid,
                ask=ask,
                mid=mid,
                implied_volatility=iv,
                volume=volume,
                open_interest=oi,
                delta=delta,
                gamma=gamma,
                theta=theta,
                vega=vega,
            ))

        return results

    def get_quotes(
        self,
        legs: list[LegSpec],
        *,
        ticker: str = "",
        include_greeks: bool = True,
    ) -> list[OptionQuote | None]:
        """Fetch quotes for specific option legs via Alpaca snapshots."""
        from market_analyzer.models.quotes import OptionQuote

        if not legs:
            return []

        try:
            from alpaca.data.requests import OptionSnapshotRequest
        except ImportError as exc:
            raise ImportError(
                "alpaca-py is not installed. Run: pip install 'market-analyzer[alpaca]'"
            ) from exc

        # Build OCC symbols for all legs
        occ_symbols = [_build_occ(ticker, leg) for leg in legs]

        try:
            request = OptionSnapshotRequest(symbol_or_symbols=occ_symbols)
            snapshots = self._option.get_option_snapshot(request)
        except Exception as exc:
            logger.warning("Alpaca quote fetch failed for %s: %s", ticker, exc)
            return [None] * len(legs)

        results: list[OptionQuote | None] = []
        for leg, occ in zip(legs, occ_symbols):
            snap = snapshots.get(occ.strip())
            if snap is None:
                results.append(None)
                continue

            bid = 0.0
            ask = 0.0
            if snap.latest_quote is not None:
                bid = float(snap.latest_quote.bid_price or 0)
                ask = float(snap.latest_quote.ask_price or 0)
            mid = (bid + ask) / 2

            iv = delta = gamma = theta = vega = None
            if include_greeks and snap.greeks is not None:
                iv = _safe_float(snap.greeks.implied_volatility)
                delta = _safe_float(snap.greeks.delta)
                gamma = _safe_float(snap.greeks.gamma)
                theta = _safe_float(snap.greeks.theta)
                vega = _safe_float(snap.greeks.vega)
            elif hasattr(snap, "implied_volatility"):
                iv = _safe_float(snap.implied_volatility)

            results.append(OptionQuote(
                ticker=ticker,
                expiration=leg.expiration,
                strike=leg.strike,
                option_type=leg.option_type,
                bid=bid,
                ask=ask,
                mid=mid,
                implied_volatility=iv,
                delta=delta,
                gamma=gamma,
                theta=theta,
                vega=vega,
            ))

        return results

    def get_greeks(self, legs: list[LegSpec]) -> dict[str, dict]:
        """Fetch Greeks for specific option legs.

        Returns ``{leg_key: {delta, gamma, theta, vega}}``.
        Greeks are included in Alpaca option snapshots.
        """
        quotes = self.get_quotes(legs, include_greeks=True)
        result: dict[str, dict] = {}
        for leg, quote in zip(legs, quotes):
            if quote is None:
                continue
            key = f"{leg.strike}{leg.option_type[0].lower()}"
            result[key] = {
                "delta": quote.delta,
                "gamma": quote.gamma,
                "theta": quote.theta,
                "vega": quote.vega,
                "iv": quote.implied_volatility,
            }
        return result

    def get_underlying_price(self, ticker: str) -> float | None:
        """Real-time/delayed underlying mid price from Alpaca."""
        try:
            from alpaca.data.requests import StockLatestQuoteRequest
            request = StockLatestQuoteRequest(symbol_or_symbols=ticker)
            quotes = self._stock.get_stock_latest_quote(request)
            if ticker in quotes:
                q = quotes[ticker]
                bid = float(q.bid_price or 0)
                ask = float(q.ask_price or 0)
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
        except ImportError as exc:
            raise ImportError(
                "alpaca-py is not installed. Run: pip install 'market-analyzer[alpaca]'"
            ) from exc
        except Exception as exc:
            logger.warning("Alpaca underlying price fetch failed for %s: %s", ticker, exc)
        return None


def _safe_float(val) -> float | None:
    """Convert value to float, returning None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
