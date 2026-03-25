"""Dhan market metrics provider — IV and liquidity metrics for India instruments.

DhanHQ provides IV natively in the option chain (as percentage).
We extract ATM IV as iv_30_day proxy and compute a rough IV rank from the
chain's IV spread (same approximation as Zerodha, but with real IV data).

IV rank (true historical) is NOT available from Dhan — would need a separate
historical IV data source.
"""

from __future__ import annotations

import logging
from datetime import date

from income_desk.broker.base import MarketMetricsProvider
from income_desk.models.quotes import MarketMetrics

logger = logging.getLogger(__name__)


class DhanMetrics(MarketMetricsProvider):
    """Compute market metrics for India instruments from Dhan option chain.

    - ``iv_30_day``: ATM IV from the nearest-expiry option chain (real Dhan data)
    - ``iv_rank``: Approximated from the chain's IV spread (not true 1-year rank)
    - ``iv_percentile``: Same approximation as iv_rank
    - ``beta``, ``corr_spy``: Not available from Dhan
    - ``liquidity_rating``: Derived from total chain OI (1–5 scale)

    Gap: True IV rank / IV percentile require historical IV data that Dhan does
    not provide directly. eTrading should store IV history and compute externally.
    """

    def __init__(self, client: object) -> None:
        """Args:
            client: Pre-authenticated ``dhanhq`` instance.
        """
        self._client = client

    def get_metrics(self, tickers: list[str]) -> dict[str, MarketMetrics]:
        """Compute metrics from option chain data for each ticker.

        Args:
            tickers: List of underlying tickers (e.g. ["NIFTY", "BANKNIFTY"]).

        Returns:
            Dict of ticker → MarketMetrics. Missing tickers are omitted.
        """
        results: dict[str, MarketMetrics] = {}

        for ticker in tickers:
            try:
                metrics = self._compute_metrics(ticker)
                if metrics is not None:
                    results[ticker] = metrics
            except Exception as e:
                logger.warning("Dhan metrics failed for %s: %s", ticker, e)

        return results

    def _compute_metrics(self, ticker: str) -> MarketMetrics | None:
        """Compute metrics for a single ticker from option chain."""
        from income_desk.broker.dhan.market_data import (
            DhanMarketData, _safe_float, _SCRIP_CODES, _SEGMENT_NSE_FNO,
        )

        scrip_code = _SCRIP_CODES.get(ticker.upper())
        if scrip_code is None:
            try:
                scrip_code = int(ticker)
            except ValueError:
                return None

        # Fetch expiry list first (required by new SDK)
        try:
            exp_response = self._client.expiry_list(
                under_security_id=scrip_code,  # int
                under_exchange_segment=_SEGMENT_NSE_FNO,
            )
            exp_outer = exp_response.get("data", {}) if isinstance(exp_response, dict) else {}
            exp_data = exp_outer.get("data", exp_outer) if isinstance(exp_outer, dict) else exp_outer
            if not isinstance(exp_data, list) or not exp_data:
                return None
            today = date.today()
            future_exp = sorted(e for e in exp_data if e >= today.strftime("%Y-%m-%d"))
            nearest_exp = future_exp[0] if future_exp else exp_data[-1]
        except Exception as e:
            logger.debug("Dhan expiry_list for metrics failed on %s: %s", ticker, e)
            return None

        try:
            response = self._client.option_chain(
                under_security_id=scrip_code,  # int
                under_exchange_segment=_SEGMENT_NSE_FNO,
                expiry=nearest_exp,
            )
        except Exception as e:
            logger.debug("Dhan option_chain for metrics failed on %s: %s", ticker, e)
            return None

        if not response or response.get("status") != "success":
            return None

        # Response: {data: {data: {last_price: X, oc: {strike: {ce: {}, pe: {}}}}}}
        outer = response.get("data", {})
        inner = outer.get("data", outer) if isinstance(outer, dict) else {}
        if not isinstance(inner, dict):
            return None

        oc_data = inner.get("oc", {})
        if not isinstance(oc_data, dict) or not oc_data:
            return None

        # Convert oc dict format to flat entries for existing metrics logic
        chain_entries = []
        for strike_str, entry in oc_data.items():
            chain_entries.append({
                "strikePrice": float(strike_str),
                "ce": entry.get("ce", {}),
                "pe": entry.get("pe", {}),
            })

        # Get ATM underlying price — prefer ticker_data for indices (chain last_price
        # can return wrong scale for NIFTY/BANKNIFTY)
        chain_price = _safe_float(inner.get("last_price"))
        md = DhanMarketData(self._client)
        ticker_price = md.get_underlying_price(ticker) or 0

        if ticker_price > 0 and chain_price > 0:
            # If they diverge by >50%, trust ticker_data (the authoritative source)
            ratio = max(ticker_price, chain_price) / min(ticker_price, chain_price)
            if ratio > 1.5:
                logger.warning(
                    "%s: chain last_price=%.2f vs ticker_data=%.2f (ratio %.1fx) — using ticker_data",
                    ticker, chain_price, ticker_price, ratio,
                )
            underlying_price = ticker_price
        elif ticker_price > 0:
            underlying_price = ticker_price
        else:
            underlying_price = chain_price

        # Collect all IVs (Dhan returns as %) and find ATM
        all_ivs: list[float] = []
        atm_iv = None
        min_dist = float("inf")

        for entry in chain_entries:
            strike = _safe_float(entry.get("strikePrice") or entry.get("strike_price"))
            dist = abs(strike - underlying_price) if underlying_price > 0 else float("inf")

            for side_key in ("ce", "pe"):
                side = entry.get(side_key, {})
                if not side or not isinstance(side, dict):
                    continue
                raw_iv = _safe_float(side.get("implied_volatility") or side.get("iv"))
                if raw_iv > 0:
                    iv_decimal = raw_iv / 100.0
                    all_ivs.append(iv_decimal)

                    if dist < min_dist:
                        min_dist = dist
                        atm_iv = iv_decimal

        # IV rank approximation: where does atm_iv sit in the chain's IV distribution?
        iv_rank: float | None = None
        iv_percentile: float | None = None

        if all_ivs and len(all_ivs) > 5 and atm_iv is not None:
            sorted_ivs = sorted(all_ivs)
            iv_min = sorted_ivs[max(0, int(len(sorted_ivs) * 0.1))]
            iv_max = sorted_ivs[min(len(sorted_ivs) - 1, int(len(sorted_ivs) * 0.9))]
            if iv_max > iv_min:
                raw_rank = (atm_iv - iv_min) / (iv_max - iv_min) * 100
                iv_rank = round(max(0.0, min(100.0, raw_rank)), 1)
                iv_percentile = iv_rank  # Same approximation

        # Liquidity rating from total chain OI
        total_oi: int = 0
        for entry in chain_entries:
            for side_key in ("ce", "pe"):
                side = entry.get(side_key, {})
                if side and isinstance(side, dict):
                    total_oi += int(_safe_float(
                        side.get("oi") or side.get("openInterest") or 0
                    ))

        if total_oi > 10_000_000:
            liquidity = 5
        elif total_oi > 1_000_000:
            liquidity = 4
        elif total_oi > 100_000:
            liquidity = 3
        elif total_oi > 10_000:
            liquidity = 2
        else:
            liquidity = 1

        return MarketMetrics(
            ticker=ticker,
            iv_rank=iv_rank,          # Approximation from chain IV spread, not historical
            iv_percentile=iv_percentile,
            iv_30_day=round(atm_iv, 4) if atm_iv else None,  # Real ATM IV from Dhan
            beta=None,                # Not available from Dhan
            liquidity_rating=float(liquidity),
        )
