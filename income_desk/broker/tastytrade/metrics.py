"""TastyTrade market metrics — IV rank, IV percentile, beta, liquidity.

Adapted from eTrading tastytrade_adapter.py get_market_metrics().
"""

from __future__ import annotations

import asyncio
import logging
import math
from decimal import Decimal
from typing import TYPE_CHECKING

from income_desk.broker.base import MarketMetricsProvider
from income_desk.models.quotes import MarketMetrics

if TYPE_CHECKING:
    from income_desk.broker.tastytrade.session import TastyTradeBrokerSession

logger = logging.getLogger(__name__)


def _safe_float(val) -> float | None:
    """Convert Decimal/str to float, returning None for NaN/empty/None."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _to_pct(val) -> float | None:
    """Convert 0-1 decimal to 0-100 percentage. Returns None for None/NaN.

    TastyTrade returns IV rank/percentile as 0-1 decimal (e.g. 0.43 = 43%).
    Can exceed 1.0 when current IV is above the 52-week high (e.g. 1.14 = 114%).
    Always multiply by 100 to normalize to 0-100 scale.
    """
    f = _safe_float(val)
    if f is None:
        return None
    return round(f * 100, 2)


class TastyTradeMetrics(MarketMetricsProvider):
    """IV rank, IV percentile, beta, liquidity from TastyTrade API."""

    def __init__(self, session: TastyTradeBrokerSession) -> None:
        self._session = session

    def get_metrics(self, tickers: list[str]) -> dict[str, MarketMetrics]:
        """Fetch market metrics for tickers via TastyTrade API.

        Handles SDK validation errors (e.g. unexpected settlement-type)
        by splitting failed batches into smaller sub-batches.
        """
        raw_items = self._fetch_raw(tickers)
        return self._convert(raw_items)

    def _fetch_raw(self, tickers: list[str]) -> list:
        """Fetch raw MarketMetricInfo objects, retrying failed batches individually."""
        from tastytrade.metrics import get_market_metrics
        from income_desk.broker.tastytrade._async import run_sync

        try:
            raw = get_market_metrics(self._session.sdk_session, tickers)
            if asyncio.iscoroutine(raw):
                raw = run_sync(raw)
            return list(raw)
        except Exception as e:
            if len(tickers) <= 1:
                logger.debug("Metrics failed for %s: %s", tickers, e)
                return []

            # Split and retry — binary split to find the bad ticker(s)
            mid = len(tickers) // 2
            logger.debug("Metrics batch failed (%d tickers), splitting: %s", len(tickers), e)
            left = self._fetch_raw(tickers[:mid])
            right = self._fetch_raw(tickers[mid:])
            return left + right

    @staticmethod
    def _convert(raw_items: list) -> dict[str, MarketMetrics]:
        """Convert raw SDK objects to MarketMetrics models."""
        result: dict[str, MarketMetrics] = {}
        for m in raw_items:
            try:
                earnings_date = None
                if m.earnings and hasattr(m.earnings, "expected_report_date"):
                    earnings_date = m.earnings.expected_report_date

                result[m.symbol] = MarketMetrics(
                    ticker=m.symbol,
                    iv_rank=_to_pct(m.implied_volatility_index_rank),
                    iv_percentile=_to_pct(m.implied_volatility_percentile),
                    iv_index=_safe_float(m.implied_volatility_index),
                    iv_30_day=_safe_float(m.implied_volatility_30_day),
                    hv_30_day=_safe_float(m.historical_volatility_30_day),
                    hv_60_day=_safe_float(m.historical_volatility_60_day),
                    beta=_safe_float(m.beta),
                    corr_spy=_safe_float(m.corr_spy_3month),
                    liquidity_rating=_safe_float(m.liquidity_rating),
                    earnings_date=earnings_date,
                )
            except Exception as exc:
                sym = getattr(m, "symbol", "?")
                logger.debug("Failed to convert metrics for %s: %s", sym, exc)

        return result
