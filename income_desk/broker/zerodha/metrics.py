"""Zerodha market metrics — IV rank computed from option chain data.

Kite Connect doesn't provide IV rank/percentile natively.
We compute from the option chain: ATM IV as current, 1-year historical for rank.
"""

from __future__ import annotations

import logging
import math
from datetime import date

from income_desk.broker.base import MarketMetricsProvider, TokenExpiredError
from income_desk.models.quotes import MarketMetrics

logger = logging.getLogger(__name__)


class ZerodhaMetrics(MarketMetricsProvider):
    """Compute market metrics for India instruments from Kite option chain data.

    IV rank is computed by comparing current ATM IV against the chain's IV range.
    This is an approximation — not historical IV rank (which needs 1yr IV data).
    """

    def __init__(
        self,
        api_key: str = "",
        access_token: str = "",
        session: object = None,
        market_data: object = None,  # ZerodhaMarketData for chain access
    ) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._session = session
        self._market_data = market_data

    def get_metrics(self, tickers: list[str]) -> dict[str, MarketMetrics]:
        """Compute metrics from option chain for each ticker.

        Returns IV rank approximation from the chain's IV spread.
        """
        results: dict[str, MarketMetrics] = {}

        if self._market_data is None:
            return results

        for ticker in tickers:
            try:
                chain = self._market_data.get_option_chain(ticker)
                if not chain:
                    continue

                # Get underlying price
                price = self._market_data.get_underlying_price(ticker)
                if price is None or price <= 0:
                    continue

                # Find ATM options (nearest to underlying price)
                calls = [q for q in chain if q.option_type == "call" and q.mid > 0]
                puts = [q for q in chain if q.option_type == "put" and q.mid > 0]

                if not calls or not puts:
                    continue

                # ATM: nearest strike to price
                atm_call = min(calls, key=lambda q: abs(q.strike - price))
                atm_put = min(puts, key=lambda q: abs(q.strike - price))

                # Estimate IV from ATM straddle price (rough approximation)
                # Straddle price ≈ 0.8 × σ × √T × S (Brenner-Subrahmanyam approximation)
                dte = (atm_call.expiration - date.today()).days if atm_call.expiration else 30
                dte = max(dte, 1)
                straddle = atm_call.mid + atm_put.mid
                t = dte / 365
                estimated_iv = straddle / (0.8 * price * math.sqrt(t)) if t > 0 else 0

                # IV rank approximation from chain IV range
                all_ivs = []
                for q in chain:
                    if q.mid > 0 and q.strike > 0:
                        # Very rough IV per option
                        intrinsic = max(0, price - q.strike) if q.option_type == "call" else max(0, q.strike - price)
                        time_value = max(0, q.mid - intrinsic)
                        if time_value > 0:
                            est = time_value / (0.4 * price * math.sqrt(t))
                            if 0.01 < est < 2.0:  # Reasonable IV range
                                all_ivs.append(est)

                iv_rank = None
                iv_percentile = None
                if all_ivs and len(all_ivs) > 5:
                    sorted_ivs = sorted(all_ivs)
                    iv_min = sorted_ivs[int(len(sorted_ivs) * 0.1)]  # 10th percentile
                    iv_max = sorted_ivs[int(len(sorted_ivs) * 0.9)]  # 90th percentile
                    if iv_max > iv_min:
                        iv_rank = (estimated_iv - iv_min) / (iv_max - iv_min) * 100
                        iv_rank = max(0, min(100, iv_rank))
                    iv_percentile = iv_rank  # Same approximation

                # Total OI and volume
                total_oi = sum(q.open_interest or 0 for q in chain)
                total_volume = sum(q.volume or 0 for q in chain)

                # Liquidity rating (1-5 based on total OI)
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

                results[ticker] = MarketMetrics(
                    ticker=ticker,
                    iv_rank=round(iv_rank, 1) if iv_rank is not None else None,
                    iv_percentile=round(iv_percentile, 1) if iv_percentile is not None else None,
                    beta=None,  # Would need index correlation data
                    liquidity_rating=liquidity,
                    source="zerodha (computed)",
                )

            except Exception as e:
                if "TokenException" in type(e).__name__:
                    raise TokenExpiredError(f"Zerodha token expired: {e}")
                logger.warning("Metrics computation failed for %s: %s", ticker, e)

        return results
