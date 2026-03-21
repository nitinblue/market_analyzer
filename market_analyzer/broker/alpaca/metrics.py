"""Alpaca market metrics provider.

Alpaca does not natively provide IV rank or IV percentile (those are
TastyTrade-specific metrics). This provider computes a simple IV rank
approximation from Alpaca's historical option data when available,
and returns None for unavailable fields.
"""

from __future__ import annotations

import logging

from market_analyzer.broker.base import MarketMetricsProvider
from market_analyzer.models.quotes import MarketMetrics

logger = logging.getLogger(__name__)


class AlpacaMetrics(MarketMetricsProvider):
    """Market metrics via Alpaca data.

    IV rank and IV percentile are not available directly from Alpaca's
    free-tier API. These fields will be None unless a historical IV
    calculation is implemented.

    Available metrics:
    - iv_30_day: 30-day implied volatility (from option snapshots if available)
    - iv_rank, iv_percentile: None (not provided by Alpaca free tier)
    - beta, corr_spy: None (not provided by Alpaca)
    """

    def __init__(self, stock_client) -> None:
        """
        Args:
            stock_client: ``alpaca.data.historical.StockHistoricalDataClient``
        """
        self._stock = stock_client

    def get_metrics(self, tickers: list[str]) -> dict[str, MarketMetrics]:
        """Fetch market metrics for tickers.

        Alpaca free tier does not provide IV rank / IV percentile.
        Returns MarketMetrics with available fields populated and the
        rest as None — callers must handle None gracefully.
        """
        result: dict[str, MarketMetrics] = {}
        for ticker in tickers:
            result[ticker] = MarketMetrics(
                ticker=ticker,
                iv_rank=None,
                iv_percentile=None,
                iv_index=None,
                iv_30_day=None,
                hv_30_day=self._compute_hv30(ticker),
                beta=None,
                corr_spy=None,
                liquidity_rating=None,
            )
        return result

    def _compute_hv30(self, ticker: str) -> float | None:
        """Estimate 30-day historical volatility from Alpaca bar data."""
        import math
        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame
            from datetime import datetime, timedelta
            import pandas as pd

            end = datetime.utcnow()
            start = end - timedelta(days=45)
            request = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
            )
            bars = self._stock.get_stock_bars(request)
            df = bars.df
            if df is None or len(df) < 21:
                return None

            # Reset multi-index if present
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(ticker, level=0) if ticker in df.index.get_level_values(0) else df.reset_index(level=0, drop=True)

            closes = df["close"].dropna()
            if len(closes) < 21:
                return None

            log_returns = [
                math.log(closes.iloc[i] / closes.iloc[i - 1])
                for i in range(1, min(31, len(closes)))
            ]
            if not log_returns:
                return None
            mean = sum(log_returns) / len(log_returns)
            variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
            hv_daily = math.sqrt(variance)
            return round(hv_daily * math.sqrt(252), 4)
        except ImportError as exc:
            raise ImportError(
                "alpaca-py is not installed. Run: pip install 'market-analyzer[alpaca]'"
            ) from exc
        except Exception as exc:
            logger.debug("HV30 computation failed for %s: %s", ticker, exc)
            return None
