"""Dict-based quote provider — pass quotes as Python dicts.

Usage::

    from market_analyzer.adapters.dict_quotes import DictQuoteProvider
    from market_analyzer import MarketAnalyzer, DataService

    quotes = {
        ("SPY", 580.0, "put",  "2026-04-24"): {"bid": 1.20, "ask": 1.35, "iv": 0.22},
        ("SPY", 575.0, "put",  "2026-04-24"): {"bid": 0.85, "ask": 0.95, "iv": 0.24},
        ("SPY", 590.0, "call", "2026-04-24"): {"bid": 1.10, "ask": 1.25, "iv": 0.20},
        ("SPY", 595.0, "call", "2026-04-24"): {"bid": 0.70, "ask": 0.80, "iv": 0.21},
    }

    provider = DictQuoteProvider(quotes, underlying_prices={"SPY": 582.50})
    ma = MarketAnalyzer(data_service=DataService(), market_data=provider)

    # Now ma.quotes.get_leg_quotes() uses your dict data
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from market_analyzer.broker.base import MarketDataProvider, MarketMetricsProvider
from market_analyzer.models.quotes import MarketMetrics, OptionQuote

if TYPE_CHECKING:
    from market_analyzer.models.opportunity import LegSpec

# Key type for the quotes dict: (ticker, strike, "put"|"call", "YYYY-MM-DD")
QuoteKey = tuple[str, float, str, str]


class DictQuoteProvider(MarketDataProvider):
    """Provide option quotes from a Python dictionary.

    Useful for:

    - Testing with known values
    - Wrapping any API that returns dicts
    - Manual quote entry from another terminal
    - Paper trading with snapshot data

    Quote dict format::

        {
            (ticker, strike, "put"|"call", "YYYY-MM-DD"): {
                "bid":   float,
                "ask":   float,
                "iv":    float | None,   # implied volatility (0-1 scale)
                "delta": float | None,
                "gamma": float | None,
                "theta": float | None,
                "vega":  float | None,
                "volume": int,
                "oi":    int,            # open interest
            },
            ...
        }
    """

    def __init__(
        self,
        quotes: dict[QuoteKey, dict],
        underlying_prices: dict[str, float] | None = None,
    ) -> None:
        self._quotes = quotes
        self._prices = underlying_prices or {}

    @property
    def provider_name(self) -> str:
        return "dict"

    # ------------------------------------------------------------------
    # MarketDataProvider interface
    # ------------------------------------------------------------------

    def get_option_chain(
        self, ticker: str, expiration: date | None = None
    ) -> list[OptionQuote]:
        """Return all quotes for *ticker*, optionally filtered by expiration."""
        results: list[OptionQuote] = []
        for (t, strike, opt_type, exp_str), data in self._quotes.items():
            if t != ticker:
                continue
            if expiration and str(expiration) != exp_str:
                continue
            results.append(self._build_quote(t, strike, opt_type, exp_str, data))
        return results

    def get_quotes(
        self,
        legs: list[LegSpec],
        *,
        ticker: str = "",
        include_greeks: bool = True,
    ) -> list[OptionQuote]:
        """Return quotes for specific option legs (matched by strike + type)."""
        results: list[OptionQuote] = []
        for leg in legs:
            match: OptionQuote | None = None
            for (t, strike, opt_type, exp_str), data in self._quotes.items():
                if strike == leg.strike and opt_type == leg.option_type:
                    # Also match expiration when available on the leg
                    leg_exp = getattr(leg, "expiration", None)
                    if leg_exp and str(leg_exp) != exp_str:
                        continue
                    match = self._build_quote(t, strike, opt_type, exp_str, data)
                    break
            results.append(match)  # type: ignore[arg-type]  # None allowed by base
        return results

    def get_greeks(self, legs: list[LegSpec]) -> dict[str, dict]:
        """Return greeks keyed by ``"{strike}{type[0]}"`` (e.g. ``"570p"``)."""
        result: dict[str, dict] = {}
        for leg in legs:
            for (t, strike, opt_type, exp_str), data in self._quotes.items():
                if strike == leg.strike and opt_type == leg.option_type:
                    key = f"{strike}{opt_type[0]}"
                    result[key] = {
                        k: data[k]
                        for k in ("delta", "gamma", "theta", "vega")
                        if k in data
                    }
                    break
        return result

    def get_underlying_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_quote(
        ticker: str,
        strike: float,
        opt_type: str,
        exp_str: str,
        data: dict,
    ) -> OptionQuote:
        bid = float(data.get("bid", 0))
        ask = float(data.get("ask", 0))
        return OptionQuote(
            ticker=ticker,
            strike=strike,
            option_type=opt_type,
            expiration=date.fromisoformat(exp_str),
            bid=bid,
            ask=ask,
            mid=(bid + ask) / 2,
            implied_volatility=data.get("iv"),
            delta=data.get("delta"),
            gamma=data.get("gamma"),
            theta=data.get("theta"),
            vega=data.get("vega"),
            volume=int(data.get("volume", 0)),
            open_interest=int(data.get("oi", 0)),
        )


class DictMetricsProvider(MarketMetricsProvider):
    """Provide IV rank and market metrics from a dictionary.

    Usage::

        metrics = {
            "SPY": {"iv_rank": 43.0, "iv_percentile": 91.0, "beta": 1.0},
            "GLD": {"iv_rank": 28.0, "iv_percentile": 62.0},
        }
        provider = DictMetricsProvider(metrics)
        ma = MarketAnalyzer(data_service=DataService(), market_metrics=provider)
    """

    def __init__(self, metrics: dict[str, dict]) -> None:
        self._metrics = metrics

    def get_metrics(self, tickers: list[str]) -> dict[str, MarketMetrics]:
        result: dict[str, MarketMetrics] = {}
        for t in tickers:
            if t in self._metrics:
                result[t] = MarketMetrics(ticker=t, **self._metrics[t])
        return result
