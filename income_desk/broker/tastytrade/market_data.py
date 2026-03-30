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

from income_desk.broker.base import MarketDataProvider
from income_desk.broker.tastytrade._async import run_sync
from income_desk.broker.tastytrade.dxlink import (
    fetch_candles,
    fetch_greeks,
    fetch_option_chain_rest,
    fetch_option_chain_symbols,
    fetch_quotes,
    fetch_underlying_price,
)
from income_desk.broker.tastytrade.symbols import (
    build_streamer_symbol,
    leg_to_streamer_symbol_from_label,
)
from income_desk.models.quotes import OptionQuote

if TYPE_CHECKING:
    from income_desk.broker.tastytrade.session import TastyTradeBrokerSession
    from income_desk.models.opportunity import LegSpec

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
        """Fetch option chain via REST API + DXLink for near-ATM quotes/Greeks.

        BUG-012 fix: uses ``Option.get_option_chain()`` REST API for the full
        chain structure (one HTTP call, ~1-2s), then streams live quotes and
        Greeks via DXLink only for strikes within ±15% of the current price.
        Far-OTM strikes get bid=0, ask=0, no Greeks.

        Previous approach subscribed to ALL 1000+ strikes via DXLink WebSocket,
        taking 3+ minutes per ticker.
        """
        symbol_info = run_sync(
            fetch_option_chain_rest(
                self._session.sdk_session, ticker, expiration,
            ),
        )

        if not symbol_info:
            return []

        # Get current underlying price for ATM filtering
        underlying_price = self.get_underlying_price(ticker)

        if underlying_price and underlying_price > 0:
            # Filter to nearest expiry + ±5% of ATM to keep DXLink subscription small
            # SPY has $1 strikes — ±15% = 190 strikes × 2 (C+P) = 380 subscriptions
            # ±5% = 64 strikes × 2 = 128 subscriptions (manageable)
            atm_low = underlying_price * 0.95
            atm_high = underlying_price * 1.05

            # Find nearest future expiry
            all_expiries = sorted(set(s["expiration"] for s in symbol_info))
            from datetime import date as _date
            future_exp = [e for e in all_expiries if e >= _date.today()]
            target_exp = future_exp[0] if future_exp else (all_expiries[0] if all_expiries else None)

            # Filter: nearest expiry + near-ATM strikes only for DXLink
            near_atm = [
                s for s in symbol_info
                if atm_low <= s["strike"] <= atm_high and s["expiration"] == target_exp
            ]
            far_otm = [
                s for s in symbol_info
                if not (atm_low <= s["strike"] <= atm_high and s["expiration"] == target_exp)
            ]
            logger.info(
                "Chain %s: %d total strikes, %d near-ATM (±15%% of $%.0f), "
                "%d far-OTM (skipping DXLink)",
                ticker, len(symbol_info), len(near_atm),
                underlying_price, len(far_otm),
            )
        else:
            # No underlying price — fall back to streaming all (bounded)
            logger.warning(
                "No underlying price for %s — streaming all %d strikes",
                ticker, len(symbol_info),
            )
            near_atm = symbol_info
            far_otm = []

        # Fetch live quotes and Greeks only for near-ATM strikes
        quotes_map: dict[str, dict] = {}
        greeks_map: dict[str, dict] = {}

        if near_atm:
            near_symbols = [s["sym"] for s in near_atm]
            # Scale timeout with symbol count (0.3s per symbol, 3-15s range)
            total_timeout = max(3.0, min(15.0, len(near_symbols) * 0.3))
            quotes_map = run_sync(
                fetch_quotes(
                    self._session.data_session, near_symbols,
                    total_timeout=total_timeout,
                ),
            )
            greeks_map = run_sync(
                fetch_greeks(self._session.data_session, near_symbols),
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

        return self._assemble_quotes(legs, symbols, quotes_map, greeks_map, ticker)

    def get_quotes_batch(
        self,
        ticker_legs: list[tuple[str, list[LegSpec]]],
        *,
        include_greeks: bool = False,
    ) -> dict[str, list[OptionQuote]]:
        """Fetch quotes for legs across MULTIPLE tickers in ONE DXLink connection.

        Instead of opening a separate WebSocket per ticker, this collects all
        streamer symbols and fetches them in a single connection. Much more
        reliable for plan generation with 10+ tickers.

        Args:
            ticker_legs: List of (ticker, legs) tuples.
            include_greeks: If False, skip Greeks (default for plan pricing).

        Returns:
            ``{ticker: [OptionQuote, ...]}``
        """
        # Build all symbols, tracking which ticker each belongs to
        all_symbols: list[str] = []
        symbol_to_ticker: dict[str, str] = {}
        ticker_sym_legs: dict[str, list[tuple[LegSpec, str]]] = {}

        for ticker, legs in ticker_legs:
            sym_legs: list[tuple[LegSpec, str]] = []
            for leg in legs:
                sym = build_streamer_symbol(ticker, leg.expiration, leg.option_type, leg.strike)
                if sym:
                    all_symbols.append(sym)
                    symbol_to_ticker[sym] = ticker
                    sym_legs.append((leg, sym))
            ticker_sym_legs[ticker] = sym_legs

        if not all_symbols:
            return {}

        # Single DXLink connection for ALL symbols (with longer timeout for large batches)
        total_timeout = max(5.0, min(15.0, len(all_symbols) * 0.3))
        quotes_map = run_sync(
            fetch_quotes(
                self._session.data_session, all_symbols,
                total_timeout=total_timeout,
            ),
        )

        greeks_map: dict[str, dict] = {}
        if include_greeks:
            greeks_map = run_sync(
                fetch_greeks(self._session.data_session, all_symbols),
            )

        # Distribute results back to per-ticker lists
        result: dict[str, list[OptionQuote]] = {}
        for ticker, sym_legs in ticker_sym_legs.items():
            legs_list = [sl[0] for sl in sym_legs]
            syms_list = [sl[1] for sl in sym_legs]
            result[ticker] = self._assemble_quotes(
                legs_list, syms_list, quotes_map, greeks_map, ticker,
            )

        return result

    def _assemble_quotes(
        self,
        legs: list[LegSpec],
        symbols: list[str],
        quotes_map: dict[str, dict],
        greeks_map: dict[str, dict],
        ticker: str,
    ) -> list[OptionQuote]:
        """Build OptionQuote list from DXLink quote/greeks maps."""
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
