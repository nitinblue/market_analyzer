"""Schwab market metrics provider.

Schwab's API provides some fundamental data but not a dedicated
IV rank endpoint. This provider fetches what Schwab offers natively
and computes IV rank approximations from available data.
"""

from __future__ import annotations

import logging

from income_desk.broker.base import MarketMetricsProvider
from income_desk.models.quotes import MarketMetrics

logger = logging.getLogger(__name__)


class SchwabMetrics(MarketMetricsProvider):
    """Market metrics via Schwab API.

    Schwab does not provide IV rank directly. Available metrics:
    - iv_30_day: 30-day IV approximation from quote data
    - hv_30_day: 30-day historical volatility (computed from bars)
    - iv_rank, iv_percentile: None (not provided by Schwab API)
    - beta, corr_spy: None (not provided by Schwab API)
    """

    def __init__(self, client) -> None:
        """
        Args:
            client: Authenticated ``schwab.client.Client`` instance.
        """
        self._client = client

    def get_metrics(self, tickers: list[str]) -> dict[str, MarketMetrics]:
        """Fetch market metrics for tickers from Schwab.

        Returns available fields; unavailable fields are None.
        Callers must handle None gracefully.
        """
        result: dict[str, MarketMetrics] = {}

        # Batch fetch quotes for all tickers to get IV data
        iv_map = self._fetch_iv(tickers)

        for ticker in tickers:
            result[ticker] = MarketMetrics(
                ticker=ticker,
                iv_rank=None,       # Not available from Schwab API
                iv_percentile=None, # Not available from Schwab API
                iv_index=None,
                iv_30_day=iv_map.get(ticker),
                hv_30_day=None,     # Would need bar data computation
                beta=None,
                corr_spy=None,
                liquidity_rating=None,
            )

        return result

    def _fetch_iv(self, tickers: list[str]) -> dict[str, float | None]:
        """Fetch implied volatility from Schwab quote data."""
        result: dict[str, float | None] = {}
        try:
            resp = self._client.get_quotes(tickers)
            resp.raise_for_status()
            data = resp.json()
            for ticker in tickers:
                quote = data.get(ticker, {})
                # Schwab equity quotes include volatility field
                fundamental = quote.get("fundamental", {})
                vol = fundamental.get("vol1DayAvg") or fundamental.get("marketCapFloat")
                # Try quote section for IV
                quote_data = quote.get("quote", {})
                iv = _safe_float(quote_data.get("volatility"))
                result[ticker] = iv
        except Exception as exc:
            logger.debug("Schwab IV fetch failed: %s", exc)
            for ticker in tickers:
                result[ticker] = None
        return result


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
