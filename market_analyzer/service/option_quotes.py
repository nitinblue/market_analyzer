"""Option quote service — works with any broker, yfinance fallback.

Includes a session-scoped TTL cache to avoid redundant DXLink connections,
and a circuit breaker that stops retrying after DXLink failures.

Usage::

    # With TastyTrade
    qs = OptionQuoteService(market_data=tt_market_data, metrics=tt_metrics)

    # Without broker (yfinance only)
    qs = OptionQuoteService(data_service=DataService())

    # Both (broker preferred, yfinance as fallback)
    qs = OptionQuoteService(market_data=tt_md, data_service=DataService())
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import TYPE_CHECKING

from market_analyzer.models.quotes import MarketMetrics, OptionQuote, QuoteSnapshot

if TYPE_CHECKING:
    from market_analyzer.broker.base import MarketDataProvider, MarketMetricsProvider
    from market_analyzer.data.service import DataService
    from market_analyzer.models.opportunity import LegSpec

logger = logging.getLogger(__name__)

# Default cache TTL: 60 seconds. DXLink quotes are snapshots, not streams —
# within one plan generation run (~30-60s) the same bid/ask is reusable.
_DEFAULT_CACHE_TTL = 60.0

# After this many consecutive DXLink failures, stop trying temporarily.
_CIRCUIT_BREAKER_THRESHOLD = 3

# Auto-reset circuit breaker after this many seconds (allows retry later in session).
_CIRCUIT_BREAKER_COOLDOWN = 60.0


class _CachedQuote:
    """Quote with timestamp for TTL expiry."""

    __slots__ = ("quote", "cached_at")

    def __init__(self, quote: OptionQuote) -> None:
        self.quote = quote
        self.cached_at = time.monotonic()

    def is_fresh(self, ttl: float) -> bool:
        return (time.monotonic() - self.cached_at) < ttl


class OptionQuoteService:
    """Fetches option quotes via broker, with yfinance fallback.

    Features:
    - **TTL cache**: Quotes cached for 60s by default. Prevents redundant DXLink
      calls when multiple trades reference the same legs.
    - **Circuit breaker**: After 2 consecutive DXLink failures, stops retrying
      for the rest of the session. Prevents the cascade of GLD×4, IWM×3 failures.
    - **include_greeks**: Plan only needs bid/ask — skips expensive Greeks fetch.
    - **Batch prefetch**: `prefetch_leg_quotes()` fetches all unique legs in one call.
    """

    def __init__(
        self,
        market_data: MarketDataProvider | None = None,
        metrics: MarketMetricsProvider | None = None,
        data_service: DataService | None = None,
        cache_ttl: float = _DEFAULT_CACHE_TTL,
    ) -> None:
        self._market_data = market_data
        self._metrics = metrics
        self._data_service = data_service
        self._cache_ttl = cache_ttl

        # TTL-aware quote cache: key → _CachedQuote
        self._quote_cache: dict[str, _CachedQuote] = {}

        # Circuit breaker: consecutive DXLink failures
        self._consecutive_failures = 0
        self._circuit_open = False
        self._circuit_opened_at: float = 0.0

    def clear_cache(self) -> None:
        """Clear quote cache and reset circuit breaker."""
        self._quote_cache.clear()
        self._consecutive_failures = 0
        self._circuit_open = False

    @staticmethod
    def _leg_cache_key(leg: LegSpec, ticker: str = "") -> str:
        """Unique key for a leg: ticker|strike|type|expiration."""
        return f"{ticker}|{leg.strike:.2f}|{leg.option_type}|{leg.expiration}"

    def _get_cached(self, key: str) -> OptionQuote | None:
        """Get a cached quote if it exists and is still fresh."""
        entry = self._quote_cache.get(key)
        if entry and entry.is_fresh(self._cache_ttl):
            return entry.quote
        # Expired — remove
        if entry:
            del self._quote_cache[key]
        return None

    def _put_cached(self, key: str, quote: OptionQuote) -> None:
        """Store a quote in the TTL cache."""
        self._quote_cache[key] = _CachedQuote(quote)

    def _record_success(self) -> None:
        """Reset circuit breaker on successful fetch."""
        self._consecutive_failures = 0
        self._circuit_open = False

    def _record_failure(self) -> None:
        """Increment failure counter, open circuit if threshold reached."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
            if not self._circuit_open:
                logger.warning(
                    "DXLink circuit breaker OPEN after %d failures — "
                    "will auto-reset after %.0fs cooldown",
                    self._consecutive_failures,
                    _CIRCUIT_BREAKER_COOLDOWN,
                )
            self._circuit_open = True
            self._circuit_opened_at = time.monotonic()

    def _check_circuit(self) -> bool:
        """Check if circuit breaker is open. Auto-resets after cooldown."""
        if not self._circuit_open:
            return False
        elapsed = time.monotonic() - self._circuit_opened_at
        if elapsed >= _CIRCUIT_BREAKER_COOLDOWN:
            logger.info(
                "DXLink circuit breaker auto-reset after %.0fs cooldown", elapsed,
            )
            self._circuit_open = False
            self._consecutive_failures = 0
            return False
        return True

    @property
    def source(self) -> str:
        """Broker name if connected, 'yfinance' otherwise."""
        if self._market_data:
            return self._market_data.provider_name
        return "yfinance"

    @property
    def has_broker(self) -> bool:
        return self._market_data is not None

    @property
    def cache_stats(self) -> dict:
        """Cache diagnostics for debugging."""
        now = time.monotonic()
        fresh = sum(1 for e in self._quote_cache.values() if e.is_fresh(self._cache_ttl))
        return {
            "total_entries": len(self._quote_cache),
            "fresh_entries": fresh,
            "circuit_open": self._circuit_open,
            "consecutive_failures": self._consecutive_failures,
        }

    def get_chain(
        self, ticker: str, expiration: date | None = None,
    ) -> QuoteSnapshot:
        """Full chain with bid/ask/Greeks.

        Tries broker first, falls back to yfinance OPTIONS_CHAIN.
        """
        if self._market_data:
            try:
                quotes = self._market_data.get_option_chain(ticker, expiration)
                underlying = self._infer_underlying_price(quotes, ticker)
                return QuoteSnapshot(
                    ticker=ticker,
                    as_of=datetime.now(),
                    underlying_price=underlying,
                    quotes=quotes,
                    source=self._market_data.provider_name,
                )
            except Exception as e:
                logger.warning("Broker chain failed for %s, falling back to yfinance: %s", ticker, e)

        return self._yfinance_chain(ticker, expiration)

    def get_leg_quotes(
        self,
        legs: list[LegSpec],
        ticker: str = "",
        *,
        include_greeks: bool = True,
    ) -> list[OptionQuote]:
        """Quotes for specific legs (used by adjustment and plan services).

        Returns broker quotes only. Returns empty list if no broker connected.
        Does NOT fall back to Black-Scholes estimates.
        Uses TTL cache + circuit breaker to avoid redundant/failed DXLink calls.

        Args:
            legs: Option legs to fetch.
            ticker: Underlying ticker (e.g. "SPY"). Required for DXLink symbols.
            include_greeks: If False, skip Greeks fetch (faster for plan pricing).
        """
        if not self._market_data:
            return []

        # Circuit breaker: don't retry if DXLink is down
        if self._check_circuit():
            return []

        # Check which legs are already cached
        cached: dict[int, OptionQuote] = {}
        uncached_legs: list[LegSpec] = []
        uncached_indices: list[int] = []

        for i, leg in enumerate(legs):
            key = self._leg_cache_key(leg, ticker)
            quote = self._get_cached(key)
            if quote is not None:
                cached[i] = quote
            else:
                uncached_legs.append(leg)
                uncached_indices.append(i)

        if cached and not uncached_legs:
            logger.debug("All %d legs served from cache for %s", len(legs), ticker)

        # Fetch only uncached legs
        fetched: list[OptionQuote] = []
        if uncached_legs:
            try:
                fetched = self._market_data.get_quotes(
                    uncached_legs, ticker=ticker, include_greeks=include_greeks,
                )
                self._record_success()
            except Exception as e:
                logger.warning("Broker leg quotes failed for %s: %s", ticker, e)
                self._record_failure()
                fetched = []

            # Cache the results
            for leg, quote in zip(uncached_legs, fetched):
                key = self._leg_cache_key(leg, ticker)
                self._put_cached(key, quote)

        # Reassemble in original order
        result: list[OptionQuote] = []
        fetch_idx = 0
        for i in range(len(legs)):
            if i in cached:
                result.append(cached[i])
            elif fetch_idx < len(fetched):
                result.append(fetched[fetch_idx])
                fetch_idx += 1

        return result

    def prefetch_leg_quotes(
        self,
        ticker_legs: list[tuple[str, list[LegSpec]]],
        *,
        include_greeks: bool = True,
    ) -> None:
        """Batch-fetch quotes for all tickers in ONE DXLink connection.

        Uses ``get_quotes_batch()`` when available (e.g. TastyTrade) to open a
        single WebSocket for all symbols across all tickers. Falls back to
        per-ticker fetching if batch isn't supported.

        Includes a single retry on failure — transient DXLink WebSocket errors
        are common but usually succeed on second attempt.

        Args:
            ticker_legs: List of (ticker, legs) tuples.
            include_greeks: If False, skip Greeks (faster for plan pricing).
        """
        if not self._market_data or not ticker_legs:
            return

        if self._check_circuit():
            logger.info("Circuit breaker open — skipping prefetch")
            return

        # Collect uncached legs per ticker
        uncached_ticker_legs: list[tuple[str, list[LegSpec]]] = []
        total_legs = 0

        for ticker, legs in ticker_legs:
            unique_legs: list[LegSpec] = []
            seen: set[str] = set()
            for leg in legs:
                key = self._leg_cache_key(leg, ticker)
                if self._get_cached(key) is None and key not in seen:
                    unique_legs.append(leg)
                    seen.add(key)
            if unique_legs:
                uncached_ticker_legs.append((ticker, unique_legs))
                total_legs += len(unique_legs)

        if not uncached_ticker_legs:
            return

        logger.info(
            "Prefetching %d legs across %d tickers (greeks=%s)",
            total_legs, len(uncached_ticker_legs), include_greeks,
        )

        # Try batch fetch (single DXLink connection for all tickers)
        has_batch = hasattr(self._market_data, "get_quotes_batch")
        fetched = False

        for attempt in range(2):  # One retry on failure
            try:
                if has_batch:
                    batch_result = self._market_data.get_quotes_batch(
                        uncached_ticker_legs, include_greeks=include_greeks,
                    )
                    for ticker, legs in uncached_ticker_legs:
                        quotes = batch_result.get(ticker, [])
                        for leg, quote in zip(legs, quotes):
                            key = self._leg_cache_key(leg, ticker)
                            self._put_cached(key, quote)
                else:
                    # Fallback: per-ticker fetching
                    for ticker, legs in uncached_ticker_legs:
                        quotes = self._market_data.get_quotes(
                            legs, ticker=ticker, include_greeks=include_greeks,
                        )
                        for leg, quote in zip(legs, quotes):
                            key = self._leg_cache_key(leg, ticker)
                            self._put_cached(key, quote)

                self._record_success()
                fetched = True
                break

            except Exception as e:
                if attempt == 0:
                    logger.warning("Prefetch attempt 1 failed, retrying: %s", e)
                else:
                    logger.warning("Prefetch attempt 2 failed: %s", e)
                    self._record_failure()

        cached_count = sum(1 for e in self._quote_cache.values() if e.is_fresh(self._cache_ttl))
        logger.info(
            "Prefetch %s: %d cached quotes from %d total legs",
            "complete" if fetched else "FAILED", cached_count, total_legs,
        )

    def get_metrics(self, ticker: str) -> MarketMetrics | None:
        """IV rank, percentile, beta. None if no metrics provider."""
        if not self._metrics:
            return None
        try:
            result = self._metrics.get_metrics([ticker])
            return result.get(ticker)
        except Exception as e:
            logger.warning("Metrics fetch failed for %s: %s", ticker, e)
            return None

    # -- yfinance fallback --

    def _yfinance_chain(
        self, ticker: str, expiration: date | None,
    ) -> QuoteSnapshot:
        """Build QuoteSnapshot from yfinance OPTIONS_CHAIN data."""
        if not self._data_service:
            return QuoteSnapshot(
                ticker=ticker,
                as_of=datetime.now(),
                underlying_price=0.0,
                quotes=[],
                source="none",
            )

        from market_analyzer.models.data import DataRequest, DataType

        try:
            df, result = self._data_service.get(DataRequest(
                ticker=ticker, data_type=DataType.OPTIONS_CHAIN,
            ))
        except Exception as e:
            logger.warning("yfinance chain fetch failed for %s: %s", ticker, e)
            return QuoteSnapshot(
                ticker=ticker,
                as_of=datetime.now(),
                underlying_price=0.0,
                quotes=[],
                source="yfinance",
            )

        # Get underlying price from OHLCV cache
        underlying = 0.0
        try:
            ohlcv = self._data_service.get_ohlcv(ticker)
            if not ohlcv.empty:
                underlying = float(ohlcv["Close"].iloc[-1])
        except Exception:
            pass

        quotes: list[OptionQuote] = []
        for _, row in df.iterrows():
            bid = float(row.get("bid", 0) or 0)
            ask = float(row.get("ask", 0) or 0)
            mid = round((bid + ask) / 2, 4) if (bid + ask) > 0 else float(row.get("lastPrice", 0) or 0)

            exp_val = row.get("expiration")
            if exp_val is None:
                continue
            if hasattr(exp_val, "date"):
                exp_date = exp_val.date() if callable(exp_val.date) else exp_val
            else:
                exp_date = exp_val

            if expiration and exp_date != expiration:
                continue

            quotes.append(OptionQuote(
                ticker=ticker,
                expiration=exp_date,
                strike=float(row.get("strike", 0)),
                option_type=str(row.get("option_type", "call")).lower(),
                bid=bid,
                ask=ask,
                mid=mid,
                last=float(row.get("lastPrice", 0) or 0),
                volume=int(row.get("volume", 0) or 0),
                open_interest=int(row.get("openInterest", 0) or 0),
                implied_volatility=float(row.get("impliedVolatility", 0) or 0),
            ))

        return QuoteSnapshot(
            ticker=ticker,
            as_of=datetime.now(),
            underlying_price=underlying,
            quotes=quotes,
            source="yfinance",
        )

    def _infer_underlying_price(
        self, quotes: list[OptionQuote], ticker: str,
    ) -> float:
        """Infer underlying price — try broker direct quote first, then put-call parity."""
        # Try direct broker underlying price (DXLink equity quote)
        if self._market_data is not None:
            try:
                price = self._market_data.get_underlying_price(ticker)
                if price and price > 0:
                    return price
            except Exception:
                pass

        if not quotes:
            return 0.0

        # Find the strike where call and put mid are closest
        calls = {q.strike: q for q in quotes if q.option_type == "call"}
        puts = {q.strike: q for q in quotes if q.option_type == "put"}
        common = set(calls) & set(puts)

        if common:
            best = min(common, key=lambda s: abs(calls[s].mid - puts[s].mid))
            return round(best + calls[best].mid - puts[best].mid, 2)

        strikes = sorted({q.strike for q in quotes})
        if strikes:
            return strikes[len(strikes) // 2]
        return 0.0
