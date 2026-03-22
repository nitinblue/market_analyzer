"""IBKR market data provider via ib_insync.

Fetches option chains, quotes, and Greeks from Interactive Brokers
using the ib_insync library (which wraps the TWS/IB Gateway socket API).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

from income_desk.broker.base import MarketDataProvider

if TYPE_CHECKING:
    from income_desk.models.opportunity import LegSpec
    from income_desk.models.quotes import OptionQuote

logger = logging.getLogger(__name__)

# Timeout in seconds to wait for market data ticks from TWS
_TICK_WAIT_SECS = 2.0


class IBKRMarketData(MarketDataProvider):
    """Interactive Brokers market data via ib_insync.

    Fetches live quotes and Greeks from TWS or IB Gateway.
    Requires the gateway to be running and the contract to be subscribed.

    Note on performance:
    - Each ``reqMktData`` call waits up to ``_TICK_WAIT_SECS`` for data.
    - For large chains, this is slow. Use ``get_option_chain`` only for
      specific expirations to limit the number of round-trips.
    """

    def __init__(self, ib) -> None:
        """
        Args:
            ib: Connected ``ib_insync.IB`` instance.
        """
        self._ib = ib

    @property
    def provider_name(self) -> str:
        return "ibkr"

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
        """Fetch option chain from IBKR via reqSecDefOptParams.

        Warning: This fetches all strikes for all expirations (or one expiration)
        and requests market data for each contract individually. This can be slow
        for tickers with many strikes. Always pass ``expiration`` to limit scope.
        """
        from income_desk.models.quotes import OptionQuote

        try:
            from ib_insync import Stock, Option  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "ib_insync is not installed. Run: pip install 'market-analyzer[ibkr]'"
            ) from exc

        stock = Stock(ticker, "SMART", "USD")
        self._ib.qualifyContracts(stock)
        chains = self._ib.reqSecDefOptParams(
            stock.symbol, "", stock.secType, stock.conId
        )

        results: list[OptionQuote] = []
        for chain in chains:
            for exp_str in chain.expirations:
                exp_date = _parse_ibkr_date(exp_str)
                if exp_date is None:
                    continue
                if expiration is not None and exp_date != expiration:
                    continue

                for strike in chain.strikes:
                    for right in ("C", "P"):
                        opt = Option(ticker, exp_str, strike, right, "SMART")
                        quote = self._fetch_single_option(
                            opt, ticker, exp_date, strike, right
                        )
                        if quote is not None:
                            results.append(quote)

        return results

    def get_quotes(
        self,
        legs: list[LegSpec],
        *,
        ticker: str = "",
        include_greeks: bool = True,
    ) -> list[OptionQuote | None]:
        """Fetch quotes for specific option legs from IBKR."""
        from income_desk.models.quotes import OptionQuote

        try:
            from ib_insync import Option  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "ib_insync is not installed. Run: pip install 'market-analyzer[ibkr]'"
            ) from exc

        results: list[OptionQuote | None] = []
        for leg in legs:
            right = "C" if leg.option_type == "call" else "P"
            exp_str = leg.expiration.strftime("%Y%m%d")
            opt = Option(ticker, exp_str, leg.strike, right, "SMART")
            quote = self._fetch_single_option(
                opt, ticker, leg.expiration, leg.strike, right
            )
            results.append(quote)

        return results

    def get_greeks(self, legs: list[LegSpec]) -> dict[str, dict]:
        """Fetch Greeks for specific option legs.

        IBKR provides model Greeks via ``reqMktData`` with generic tick types.
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
        """Real-time underlying price from IBKR."""
        try:
            from ib_insync import Stock  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "ib_insync is not installed. Run: pip install 'market-analyzer[ibkr]'"
            ) from exc

        try:
            stock = Stock(ticker, "SMART", "USD")
            self._ib.qualifyContracts(stock)
            md = self._ib.reqMktData(stock, "", False, False)
            self._ib.sleep(_TICK_WAIT_SECS)
            self._ib.cancelMktData(stock)

            if md.bid and md.ask and md.bid > 0 and md.ask > 0:
                return (md.bid + md.ask) / 2
            if md.last and md.last > 0:
                return float(md.last)
        except Exception as exc:
            logger.warning("IBKR underlying price fetch failed for %s: %s", ticker, exc)

        return None

    def disconnect(self) -> None:
        """Disconnect from TWS/IB Gateway."""
        try:
            self._ib.disconnect()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_single_option(
        self,
        contract,
        ticker: str,
        exp: date,
        strike: float,
        right: str,
    ) -> OptionQuote | None:
        """Request market data for a single option contract and return an OptionQuote."""
        from income_desk.models.quotes import OptionQuote

        try:
            self._ib.qualifyContracts(contract)
            md = self._ib.reqMktData(contract, "106", False, False)
            self._ib.sleep(_TICK_WAIT_SECS)
            self._ib.cancelMktData(contract)

            bid = float(md.bid or 0)
            ask = float(md.ask or 0)
            mid = (bid + ask) / 2

            iv = delta = gamma = theta = vega = None
            if md.modelGreeks is not None:
                iv = _safe_float(md.modelGreeks.impliedVol)
                delta = _safe_float(md.modelGreeks.delta)
                gamma = _safe_float(md.modelGreeks.gamma)
                theta = _safe_float(md.modelGreeks.theta)
                vega = _safe_float(md.modelGreeks.vega)

            return OptionQuote(
                ticker=ticker,
                expiration=exp,
                strike=strike,
                option_type="call" if right == "C" else "put",
                bid=bid,
                ask=ask,
                mid=mid,
                implied_volatility=iv,
                delta=delta,
                gamma=gamma,
                theta=theta,
                vega=vega,
            )
        except Exception as exc:
            logger.debug(
                "IBKR quote fetch failed for %s %s %s %s: %s",
                ticker, exp, strike, right, exc,
            )
            return None


def _parse_ibkr_date(date_str: str) -> date | None:
    """Parse IBKR expiration date string (YYYYMMDD) to date."""
    try:
        return datetime.strptime(date_str, "%Y%m%d").date()
    except ValueError:
        return None


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        # IBKR uses 1.7976931348623157e+308 as sentinel for "not available"
        if abs(f) > 1e300:
            return None
        return f
    except (TypeError, ValueError):
        return None
