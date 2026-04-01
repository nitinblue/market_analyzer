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
from income_desk.models.dxlink_result import GreeksResult, QuoteResult
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
        self,
        ticker: str,
        expiration: date | None = None,
        *,
        strikes_each_side: int = 15,
        num_expiries: int = 6,
    ) -> list[OptionQuote]:
        """Fetch option chain via REST API + DXLink for near-ATM quotes/Greeks.

        Starts from ATM and selects the N closest strikes on each side (puts
        below, calls above), across the M nearest expiries. Only these
        near-ATM strikes get live DXLink quotes and Greeks — far-OTM strikes
        are included in the result with bid=0/ask=0 for chain structure only.

        Args:
            ticker: Underlying symbol.
            expiration: Optional: fetch only this expiry.
            strikes_each_side: Number of strikes above and below ATM to fetch
                live quotes for (default 30 → 60 strikes per expiry).
            num_expiries: Number of nearest future expiries to stream
                (default 2 — supports calendar spreads).
        """
        symbol_info = run_sync(
            fetch_option_chain_rest(
                self._session.sdk_session, ticker, expiration,
            ),
        )

        if not symbol_info:
            return []

        # Get current underlying price as the center point
        underlying_price = self.get_underlying_price(ticker)

        if underlying_price and underlying_price > 0:
            # Select N nearest expiries
            all_expiries = sorted(set(s["expiration"] for s in symbol_info))
            from datetime import date as _date
            future_exp = [e for e in all_expiries if e >= _date.today()]
            target_exps = set(future_exp[:num_expiries]) if future_exp else (
                set(all_expiries[:num_expiries]) if all_expiries else set()
            )

            # For each target expiry, pick strikes_each_side closest to ATM
            near_atm = _select_near_atm(
                symbol_info, underlying_price, target_exps, strikes_each_side,
            )
            far_otm = [s for s in symbol_info if s not in near_atm]

            logger.info(
                "Chain %s: %d near-ATM (%d each side × %d expiries) of %d total, "
                "ATM=$%.0f, skipping %d far-OTM",
                ticker, len(near_atm), strikes_each_side, len(target_exps),
                len(symbol_info), underlying_price, len(far_otm),
            )
        else:
            logger.warning(
                "No underlying price for %s — cannot center strikes, "
                "streaming first %d symbols",
                ticker, min(200, len(symbol_info)),
            )
            near_atm = symbol_info[:200]
            far_otm = symbol_info[200:]

        # Fetch live quotes and Greeks only for near-ATM strikes
        quotes_map: dict[str, dict] = {}
        greeks_map: dict[str, dict] = {}

        if near_atm:
            near_symbols = [s["sym"] for s in near_atm]
            total_timeout = max(3.0, min(15.0, len(near_symbols) * 0.3))
            quote_result: QuoteResult = run_sync(
                fetch_quotes(
                    self._session.data_session, near_symbols,
                    total_timeout=total_timeout,
                ),
            )
            greeks_result: GreeksResult = run_sync(
                fetch_greeks(self._session.data_session, near_symbols),
            )
            quotes_map = quote_result.data
            greeks_map = greeks_result.data

            logger.info(
                "%s: %d/%d quotes, %d/%d greeks",
                ticker, quote_result.received_count, len(near_symbols),
                greeks_result.received_count, len(near_symbols),
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
        ).data

        greeks_map: dict[str, dict] = {}
        if include_greeks:
            greeks_map = run_sync(
                fetch_greeks(self._session.data_session, symbols),
            ).data

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
        ).data

        greeks_map: dict[str, dict] = {}
        if include_greeks:
            greeks_map = run_sync(
                fetch_greeks(self._session.data_session, all_symbols),
            ).data

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
        ).data

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


def _select_near_atm(
    symbol_info: list[dict],
    underlying_price: float,
    target_exps: set,
    strikes_each_side: int,
) -> list[dict]:
    """Select the N closest strikes above and below ATM for each target expiry.

    Starts from ATM and expands outward — never fetches more than needed.
    Returns a flat list of symbol dicts that should get DXLink quotes.
    """
    near_atm: list[dict] = []

    for exp in target_exps:
        # Get unique strikes for this expiry, sorted by distance from ATM
        exp_symbols = [s for s in symbol_info if s["expiration"] == exp]
        strikes = sorted(set(s["strike"] for s in exp_symbols))

        if not strikes:
            continue

        # Find ATM index
        atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - underlying_price))

        # Select N below + N above (clamped to available range)
        low_idx = max(0, atm_idx - strikes_each_side)
        high_idx = min(len(strikes), atm_idx + strikes_each_side + 1)
        selected_strikes = set(strikes[low_idx:high_idx])

        # Collect both puts and calls for selected strikes
        for s in exp_symbols:
            if s["strike"] in selected_strikes:
                near_atm.append(s)

    return near_atm


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
