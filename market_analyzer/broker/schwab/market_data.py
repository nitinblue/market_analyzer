"""Schwab market data provider via schwab-py.

Maps Schwab's option chain response (callExpDateMap / putExpDateMap)
to the broker-agnostic OptionQuote model.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

from market_analyzer.broker.base import MarketDataProvider

if TYPE_CHECKING:
    from market_analyzer.models.opportunity import LegSpec
    from market_analyzer.models.quotes import OptionQuote

logger = logging.getLogger(__name__)


class SchwabMarketData(MarketDataProvider):
    """Charles Schwab market data via schwab-py.

    Fetches option chains and individual option quotes from Schwab's
    Market Data API. Requires valid OAuth2 credentials.
    """

    def __init__(self, client) -> None:
        """
        Args:
            client: Authenticated ``schwab.client.Client`` instance.
        """
        self._client = client

    @property
    def provider_name(self) -> str:
        return "schwab"

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
        """Fetch full option chain from Schwab.

        Schwab's API returns callExpDateMap and putExpDateMap, each keyed
        by ``"YYYY-MM-DD:DTE"`` with nested strike maps.
        """
        from market_analyzer.models.quotes import OptionQuote

        try:
            import schwab  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "schwab-py is not installed. Run: pip install 'market-analyzer[schwab]'"
            ) from exc

        try:
            kwargs: dict = {}
            if expiration is not None:
                kwargs["from_date"] = expiration
                kwargs["to_date"] = expiration
            resp = self._client.get_option_chain(ticker, **kwargs)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("Schwab option chain fetch failed for %s: %s", ticker, exc)
            return []

        results: list[OptionQuote] = []
        for option_type, exp_date_map_key in (
            ("call", "callExpDateMap"),
            ("put", "putExpDateMap"),
        ):
            exp_date_map = data.get(exp_date_map_key, {})
            for exp_key, strikes in exp_date_map.items():
                # exp_key format: "2026-04-24:35"
                exp_date_str = exp_key.split(":")[0]
                try:
                    exp = datetime.strptime(exp_date_str, "%Y-%m-%d").date()
                except ValueError:
                    continue

                if expiration is not None and exp != expiration:
                    continue

                for strike_str, contracts in strikes.items():
                    strike = _safe_float(strike_str)
                    if strike is None:
                        continue
                    for contract in contracts:
                        quote = _parse_schwab_contract(
                            contract, ticker, exp, strike, option_type
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
        """Fetch quotes for specific option legs from Schwab.

        Builds OCC symbols and calls the Schwab quotes endpoint.
        """
        from market_analyzer.models.quotes import OptionQuote

        if not legs:
            return []

        try:
            import schwab  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "schwab-py is not installed. Run: pip install 'market-analyzer[schwab]'"
            ) from exc

        occ_symbols = [_to_occ(ticker, leg) for leg in legs]

        try:
            resp = self._client.get_quotes(occ_symbols)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("Schwab quotes fetch failed for %s: %s", ticker, exc)
            return [None] * len(legs)

        results: list[OptionQuote | None] = []
        for leg, occ in zip(legs, occ_symbols):
            contract = data.get(occ.strip())
            if contract is None:
                results.append(None)
                continue
            # Schwab quote response has a nested structure
            quote_data = contract.get("quote", contract)
            option_type = leg.option_type

            bid = _safe_float(quote_data.get("bidPrice", 0)) or 0.0
            ask = _safe_float(quote_data.get("askPrice", 0)) or 0.0
            mid = _safe_float(quote_data.get("mark")) or (bid + ask) / 2

            iv = _safe_float(quote_data.get("volatility"))
            delta = _safe_float(quote_data.get("delta")) if include_greeks else None
            gamma = _safe_float(quote_data.get("gamma")) if include_greeks else None
            theta = _safe_float(quote_data.get("theta")) if include_greeks else None
            vega = _safe_float(quote_data.get("vega")) if include_greeks else None
            oi = int(quote_data.get("openInterest", 0) or 0)
            volume = int(quote_data.get("totalVolume", 0) or 0)

            results.append(OptionQuote(
                ticker=ticker,
                expiration=leg.expiration,
                strike=leg.strike,
                option_type=option_type,
                bid=bid,
                ask=ask,
                mid=mid,
                implied_volatility=iv,
                volume=volume,
                open_interest=oi,
                delta=delta,
                gamma=gamma,
                theta=theta,
                vega=vega,
            ))

        return results

    def get_greeks(self, legs: list[LegSpec]) -> dict[str, dict]:
        """Fetch Greeks for specific option legs.

        Schwab returns delta/gamma/theta/vega directly in quote objects.
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
        """Real-time underlying price from Schwab."""
        try:
            resp = self._client.get_quote(ticker)
            resp.raise_for_status()
            data = resp.json()
            quote = data.get(ticker, {}).get("quote", {})
            mark = _safe_float(quote.get("mark"))
            if mark:
                return mark
            bid = _safe_float(quote.get("bidPrice", 0)) or 0.0
            ask = _safe_float(quote.get("askPrice", 0)) or 0.0
            if bid > 0 and ask > 0:
                return (bid + ask) / 2
        except Exception as exc:
            logger.warning("Schwab underlying price fetch failed for %s: %s", ticker, exc)
        return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_schwab_contract(
    contract: dict,
    ticker: str,
    exp: date,
    strike: float,
    option_type: str,
) -> OptionQuote | None:
    """Parse a Schwab contract dict into an OptionQuote."""
    from market_analyzer.models.quotes import OptionQuote

    try:
        bid = _safe_float(contract.get("bid", 0)) or 0.0
        ask = _safe_float(contract.get("ask", 0)) or 0.0
        mid = _safe_float(contract.get("mark")) or (bid + ask) / 2

        return OptionQuote(
            ticker=ticker,
            expiration=exp,
            strike=strike,
            option_type=option_type,
            bid=bid,
            ask=ask,
            mid=mid,
            implied_volatility=_safe_float(contract.get("volatility")),
            volume=int(contract.get("totalVolume", 0) or 0),
            open_interest=int(contract.get("openInterest", 0) or 0),
            delta=_safe_float(contract.get("delta")),
            gamma=_safe_float(contract.get("gamma")),
            theta=_safe_float(contract.get("theta")),
            vega=_safe_float(contract.get("vega")),
        )
    except Exception as exc:
        logger.debug("Failed to parse Schwab contract: %s", exc)
        return None


def _to_occ(ticker: str, leg: LegSpec) -> str:
    """Convert a LegSpec to an OCC option symbol for Schwab API.

    OCC format: ``SPY   260424C00580000``
    (6-char padded ticker, YYMMDD, C/P, 8-digit strike * 1000)
    """
    padded = ticker.ljust(6)
    yymmdd = leg.expiration.strftime("%y%m%d")
    cp = "C" if leg.option_type == "call" else "P"
    strike_int = int(leg.strike * 1000)
    return f"{padded}{yymmdd}{cp}{strike_int:08d}"


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
