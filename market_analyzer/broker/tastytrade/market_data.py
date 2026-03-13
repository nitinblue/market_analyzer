"""TastyTrade market data — DXLink streaming for quotes and Greeks.

Adapted from eTrading tastytrade_adapter.py.
Uses DXLinkStreamer exactly as implemented in cotrader.

DXLink streaming patterns, timeouts, and symbol formats are copied
from the proven eTrading adapter to ensure consistency.

All DXLink logic lives in ``dxlink.py`` (fetch utilities) and
``symbols.py`` (symbol conversion). This module is a thin orchestrator
that implements the ``MarketDataProvider`` ABC.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

from market_analyzer.broker.base import MarketDataProvider
from market_analyzer.broker.tastytrade._async import run_sync
from market_analyzer.broker.tastytrade.dxlink import (
    fetch_candles,
    fetch_greeks,
    fetch_option_chain_symbols,
    fetch_quotes,
    fetch_underlying_price,
)
from market_analyzer.broker.tastytrade.symbols import (
    build_streamer_symbol,
    leg_to_streamer_symbol_from_label,
)
from market_analyzer.models.quotes import OptionQuote

if TYPE_CHECKING:
    from market_analyzer.broker.tastytrade.session import TastyTradeBrokerSession
    from market_analyzer.models.opportunity import LegSpec

logger = logging.getLogger(__name__)


class TastyTradeMarketData(MarketDataProvider):
    """DXLink streaming quotes and Greeks — same pattern as cotrader adapter."""

    def __init__(self, session: TastyTradeBrokerSession) -> None:
        self._session = session

    @property
    def provider_name(self) -> str:
        return "tastytrade"

    # -- MarketDataProvider ABC --

    def get_option_chain(
        self, ticker: str, expiration: date | None = None,
    ) -> list[OptionQuote]:
        """Fetch option chain via NestedOptionChain + DXLink quotes/Greeks.

        Uses NestedOptionChain.get() (SDK v12) to get strikes and streamer
        symbols, then DXLink for live bid/ask and Greeks.
        """
        symbol_info = run_sync(
            fetch_option_chain_symbols(
                self._session.sdk_session, ticker, expiration,
            ),
        )

        if not symbol_info:
            return []

        all_symbols = [s["sym"] for s in symbol_info]

        # Fetch quotes and Greeks via DXLink
        quotes_map = run_sync(
            fetch_quotes(self._session.data_session, all_symbols),
        )
        greeks_map = run_sync(
            fetch_greeks(self._session.data_session, all_symbols),
        )

        return _build_option_quotes(ticker, symbol_info, quotes_map, greeks_map)

    def get_quotes(
        self,
        legs: list[LegSpec],
        *,
        ticker: str = "",
        include_greeks: bool = True,
    ) -> list[OptionQuote]:
        """Fetch quotes for specific legs via DXLink streaming.

        Args:
            legs: Option legs to fetch.
            ticker: Underlying ticker (e.g. "SPY"). Required for building
                correct DXLink streamer symbols.
            include_greeks: If False, skip Greeks fetch (faster — bid/ask only).
                Plan generation only needs bid/ask for pricing.
        """
        if not ticker:
            logger.warning("get_quotes called without ticker — symbols will be wrong")

        symbols = [
            build_streamer_symbol(ticker, leg.expiration, leg.option_type, leg.strike)
            if ticker
            else self._leg_to_streamer_symbol(leg)
            for leg in legs
        ]
        symbols = [s for s in symbols if s]

        if not symbols:
            return []

        quotes_map = run_sync(
            fetch_quotes(self._session.data_session, symbols),
        )

        greeks_map: dict[str, dict] = {}
        if include_greeks:
            greeks_map = run_sync(
                fetch_greeks(self._session.data_session, symbols),
            )

        result: list[OptionQuote] = []
        for leg, sym in zip(legs, symbols):
            if not sym:
                continue
            q = quotes_map.get(sym, {})
            g = greeks_map.get(sym, {})

            bid = q.get("bid", 0.0)
            ask = q.get("ask", 0.0)

            result.append(OptionQuote(
                ticker=ticker,
                expiration=leg.expiration,
                strike=leg.strike,
                option_type=leg.option_type,
                bid=bid,
                ask=ask,
                mid=round((bid + ask) / 2, 4),
                implied_volatility=g.get("iv"),
                delta=g.get("delta"),
                gamma=g.get("gamma"),
                theta=g.get("theta"),
                vega=g.get("vega"),
            ))

        return result

    def get_greeks(self, legs: list[LegSpec]) -> dict[str, dict]:
        """Fetch Greeks for specific legs via DXLink."""
        symbols = [self._leg_to_streamer_symbol(leg) for leg in legs]
        symbol_keys = [f"{leg.strike:.0f}{leg.option_type[0].upper()}" for leg in legs]
        symbols_clean = [s for s in symbols if s]

        greeks_map = run_sync(
            fetch_greeks(self._session.data_session, symbols_clean),
        )

        result: dict[str, dict] = {}
        for key, sym in zip(symbol_keys, symbols):
            if sym and sym in greeks_map:
                result[key] = greeks_map[sym]

        return result

    # -- Intraday candles + underlying price --

    def get_intraday_candles(
        self, ticker: str, interval: str = "5m",
    ) -> pd.DataFrame:
        """Today's intraday OHLCV candles via DXLink Candle subscription."""
        coro = fetch_candles(self._session.data_session, ticker, interval)
        try:
            rows = run_sync(coro, timeout=15)
        except Exception as e:
            coro.close()
            logger.warning("Intraday candle fetch failed for %s: %s", ticker, e)
            return pd.DataFrame()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(list(rows.values()))
        df.index = pd.to_datetime(df.pop("time"), unit="ms", utc=True)
        df.index = df.index.tz_convert("US/Eastern").tz_localize(None)
        return df.sort_index()

    def get_underlying_price(self, ticker: str) -> float | None:
        """Real-time underlying mid price via DXLink equity Quote."""
        coro = fetch_underlying_price(self._session.data_session, ticker)
        try:
            return run_sync(coro)
        except Exception as e:
            coro.close()
            logger.warning("Underlying price fetch failed for %s: %s", ticker, e)
            return None

    # -- Symbol conversion --

    def _leg_to_streamer_symbol(self, leg: LegSpec) -> str | None:
        """Convert LegSpec to DXLink streamer symbol.

        Format: ``.{TICKER}{YYMMDD}{C|P}{STRIKE}``
        Example: ``.SPY260320P580``
        """
        return leg_to_streamer_symbol_from_label(leg)

    def leg_to_streamer_symbol_with_ticker(
        self, ticker: str, leg: LegSpec,
    ) -> str:
        """Convert LegSpec + known ticker to DXLink streamer symbol."""
        return build_streamer_symbol(
            ticker=ticker,
            expiration=leg.expiration,
            option_type=leg.option_type,
            strike=leg.strike,
        )


def _build_option_quotes(
    ticker: str,
    symbol_info: list[dict],
    quotes_map: dict[str, dict],
    greeks_map: dict[str, dict],
) -> list[OptionQuote]:
    """Build OptionQuote list from symbol info + DXLink data maps."""
    result: list[OptionQuote] = []
    for info in symbol_info:
        sym = info["sym"]
        q = quotes_map.get(sym, {})
        g = greeks_map.get(sym, {})

        bid = q.get("bid", 0.0)
        ask = q.get("ask", 0.0)

        result.append(OptionQuote(
            ticker=ticker,
            expiration=info["expiration"],
            strike=info["strike"],
            option_type=info["option_type"],
            bid=bid,
            ask=ask,
            mid=round((bid + ask) / 2, 4),
            implied_volatility=g.get("iv"),
            delta=g.get("delta"),
            gamma=g.get("gamma"),
            theta=g.get("theta"),
            vega=g.get("vega"),
        ))

    return result
