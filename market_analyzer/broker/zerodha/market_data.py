"""Zerodha (Kite Connect) market data provider.

Provides live option quotes, chains, Greeks (computed), and intraday data
for NSE/BSE markets via Kite Connect REST API.

Credentials: API key + daily access token.
- Standalone: load from zerodha_credentials.yaml
- SaaS: eTrading passes pre-authenticated KiteConnect session

Rate limit: 3 requests/second (Kite Connect policy).
Access token expires daily — must re-auth each morning.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from market_analyzer.broker.base import MarketDataProvider, TokenExpiredError

if TYPE_CHECKING:
    from market_analyzer.models.opportunity import LegSpec
    from market_analyzer.models.quotes import OptionQuote

logger = logging.getLogger(__name__)

# NSE exchange codes for Kite
_EXCHANGE_NSE = "NSE"
_EXCHANGE_NFO = "NFO"  # NSE Futures & Options


def _build_nfo_symbol(ticker: str, expiry: date, option_type: str, strike: float) -> str:
    """Build NFO tradingsymbol: NIFTY26MAR22500CE

    Format: {UNDERLYING}{YY}{MON}{STRIKE}{CE|PE}
    """
    yy = expiry.strftime("%y")
    mon = expiry.strftime("%b").upper()
    strike_str = str(int(strike)) if strike == int(strike) else f"{strike:.1f}"
    ot = "CE" if option_type.lower() in ("call", "ce") else "PE"
    return f"{ticker}{yy}{mon}{strike_str}{ot}"


def _parse_nfo_instrument(inst: dict) -> dict:
    """Parse a Kite instrument dict into structured fields."""
    return {
        "instrument_token": inst.get("instrument_token"),
        "tradingsymbol": inst.get("tradingsymbol", ""),
        "exchange": inst.get("exchange", ""),
        "strike": float(inst.get("strike", 0)),
        "lot_size": int(inst.get("lot_size", 1)),
        "instrument_type": inst.get("instrument_type", ""),  # CE, PE, FUT
        "expiry": inst.get("expiry"),  # date object
        "name": inst.get("name", ""),  # Underlying name
    }


class ZerodhaMarketData(MarketDataProvider):
    """Zerodha MarketDataProvider for India NSE/BSE via Kite Connect.

    Provides live option quotes with bid/ask, OI, volume.
    Greeks are estimated (Kite doesn't provide Greeks natively).
    """

    def __init__(
        self,
        api_key: str = "",
        access_token: str = "",
        session: object = None,
    ) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._session = session
        self._kite = None
        self._instruments_cache: dict[str, list[dict]] = {}  # underlying -> instruments
        self._instruments_loaded = False

    def _get_kite(self):
        """Lazy-init KiteConnect client."""
        if self._kite is not None:
            return self._kite

        from kiteconnect import KiteConnect

        if self._session is not None and isinstance(self._session, KiteConnect):
            self._kite = self._session
        else:
            self._kite = KiteConnect(api_key=self._api_key)
            if self._access_token:
                self._kite.set_access_token(self._access_token)

        return self._kite

    def _ensure_instruments(self, underlying: str) -> list[dict]:
        """Load NFO instruments for an underlying (cached per session)."""
        underlying = underlying.upper()
        if underlying in self._instruments_cache:
            return self._instruments_cache[underlying]

        try:
            kite = self._get_kite()
            all_nfo = kite.instruments(exchange=_EXCHANGE_NFO)
            # Filter for this underlying's options
            filtered = [
                _parse_nfo_instrument(i) for i in all_nfo
                if i.get("name", "").upper() == underlying
                and i.get("instrument_type") in ("CE", "PE")
            ]
            self._instruments_cache[underlying] = filtered
            logger.info("Loaded %d NFO instruments for %s", len(filtered), underlying)
            return filtered
        except Exception as e:
            if "TokenException" in type(e).__name__ or "403" in str(e):
                raise TokenExpiredError(f"Zerodha access token expired: {e}")
            logger.warning("Failed to load instruments for %s: %s", underlying, e)
            return []

    @property
    def provider_name(self) -> str:
        return "zerodha"

    @property
    def rate_limit_per_second(self) -> int:
        return 3

    @property
    def supports_batch(self) -> bool:
        return True  # kite.quote() accepts multiple instruments

    @property
    def currency(self) -> str:
        return "INR"

    @property
    def timezone(self) -> str:
        return "Asia/Kolkata"

    @property
    def market_hours(self) -> tuple[time, time]:
        return (time(9, 15), time(15, 30))

    @property
    def lot_size_default(self) -> int:
        return 25

    def is_token_valid(self) -> bool:
        """Check if access token is still valid."""
        try:
            kite = self._get_kite()
            kite.profile()
            return True
        except Exception:
            return False

    def get_option_chain(
        self, ticker: str, expiration: date | None = None,
    ) -> list[OptionQuote]:
        """Get full option chain for a ticker.

        If expiration is None, returns nearest expiry chain.
        """
        from market_analyzer.models.quotes import OptionQuote

        instruments = self._ensure_instruments(ticker)
        if not instruments:
            return []

        # Filter by expiration
        if expiration:
            instruments = [i for i in instruments if i["expiry"] == expiration]
        else:
            # Find nearest expiry
            today = date.today()
            expiries = sorted(set(i["expiry"] for i in instruments if i["expiry"] and i["expiry"] >= today))
            if not expiries:
                return []
            nearest = expiries[0]
            instruments = [i for i in instruments if i["expiry"] == nearest]

        if not instruments:
            return []

        # Fetch live quotes (batch — up to 500 per call)
        kite = self._get_kite()
        quotes = []

        # Build instrument keys: "NFO:NIFTY26MAR22500CE"
        batch_size = 200  # Kite limit per quote call
        for i in range(0, len(instruments), batch_size):
            batch = instruments[i:i + batch_size]
            keys = [f"{_EXCHANGE_NFO}:{inst['tradingsymbol']}" for inst in batch]

            try:
                quote_data = kite.quote(*keys)
            except Exception as e:
                if "TokenException" in type(e).__name__:
                    raise TokenExpiredError(f"Zerodha token expired: {e}")
                logger.warning("Quote fetch failed for batch: %s", e)
                continue

            for inst in batch:
                key = f"{_EXCHANGE_NFO}:{inst['tradingsymbol']}"
                q = quote_data.get(key)
                if q is None:
                    continue

                depth = q.get("depth", {})
                buy_depth = depth.get("buy", [{}])
                sell_depth = depth.get("sell", [{}])
                bid = buy_depth[0].get("price", 0) if buy_depth else 0
                ask = sell_depth[0].get("price", 0) if sell_depth else 0
                mid = (bid + ask) / 2 if bid > 0 and ask > 0 else q.get("last_price", 0)

                opt_type = "call" if inst["instrument_type"] == "CE" else "put"

                quotes.append(OptionQuote(
                    ticker=ticker,
                    strike=inst["strike"],
                    option_type=opt_type,
                    expiration=inst["expiry"],
                    bid=bid,
                    ask=ask,
                    mid=round(mid, 2),
                    last_price=q.get("last_price", 0),
                    volume=q.get("volume", 0),
                    open_interest=q.get("oi", 0),
                    lot_size=inst["lot_size"],
                    # Greeks: estimated (Kite doesn't provide)
                    delta=None,
                    gamma=None,
                    theta=None,
                    vega=None,
                    iv=None,
                    source="zerodha",
                ))

        return quotes

    def get_quotes(
        self,
        legs: list[LegSpec],
        *,
        ticker: str = "",
        include_greeks: bool = True,
    ) -> list[OptionQuote]:
        """Get quotes for specific option legs."""
        from market_analyzer.models.quotes import OptionQuote

        if not legs:
            return []

        kite = self._get_kite()
        results: list[OptionQuote] = []

        # Build NFO symbols for each leg
        keys = []
        leg_map: dict[str, LegSpec] = {}
        for leg in legs:
            sym = _build_nfo_symbol(ticker, leg.expiration, leg.option_type, leg.strike)
            key = f"{_EXCHANGE_NFO}:{sym}"
            keys.append(key)
            leg_map[key] = leg

        if not keys:
            return []

        try:
            quote_data = kite.quote(*keys)
        except Exception as e:
            if "TokenException" in type(e).__name__:
                raise TokenExpiredError(f"Zerodha token expired: {e}")
            logger.warning("Leg quote fetch failed: %s", e)
            return []

        for key, leg in leg_map.items():
            q = quote_data.get(key)
            if q is None:
                continue

            depth = q.get("depth", {})
            buy_depth = depth.get("buy", [{}])
            sell_depth = depth.get("sell", [{}])
            bid = buy_depth[0].get("price", 0) if buy_depth else 0
            ask = sell_depth[0].get("price", 0) if sell_depth else 0
            mid = (bid + ask) / 2 if bid > 0 and ask > 0 else q.get("last_price", 0)

            # Get lot size from instruments cache
            lot_size = 25  # Default NIFTY
            instruments = self._instruments_cache.get(ticker.upper(), [])
            for inst in instruments:
                if inst["strike"] == leg.strike and inst["expiry"] == leg.expiration:
                    lot_size = inst["lot_size"]
                    break

            results.append(OptionQuote(
                ticker=ticker,
                strike=leg.strike,
                option_type=leg.option_type,
                expiration=leg.expiration,
                bid=bid,
                ask=ask,
                mid=round(mid, 2),
                last_price=q.get("last_price", 0),
                volume=q.get("volume", 0),
                open_interest=q.get("oi", 0),
                lot_size=lot_size,
                delta=None,
                gamma=None,
                theta=None,
                vega=None,
                iv=None,
                source="zerodha",
            ))

        return results

    def get_greeks(self, legs: list[LegSpec]) -> dict[str, dict]:
        """Greeks are NOT available from Zerodha Kite Connect.

        Returns empty dict. Use ZerodhaMetrics for IV approximation.
        For Greeks, a third-party service or local computation would be needed.
        """
        return {}

    def get_underlying_price(self, ticker: str) -> float | None:
        """Get current price of underlying (index or equity)."""
        kite = self._get_kite()

        # Map to Kite exchange symbol
        index_map = {
            "NIFTY": "NSE:NIFTY 50",
            "BANKNIFTY": "NSE:NIFTY BANK",
            "FINNIFTY": "NSE:NIFTY FIN SERVICE",
        }

        key = index_map.get(ticker.upper(), f"NSE:{ticker.upper()}")

        try:
            data = kite.ltp(key)
            if key in data:
                return float(data[key].get("last_price", 0))
        except Exception as e:
            if "TokenException" in type(e).__name__:
                raise TokenExpiredError(f"Zerodha token expired: {e}")
            logger.warning("Failed to get price for %s: %s", ticker, e)

        return None

    def get_intraday_candles(
        self, ticker: str, interval: str = "5minute",
    ) -> pd.DataFrame:
        """Get intraday candles via Kite historical data API."""
        kite = self._get_kite()

        # Need instrument token — get from instruments cache or NSE
        token = self._get_instrument_token(ticker)
        if token is None:
            return pd.DataFrame()

        today = date.today()
        try:
            data = kite.historical_data(
                instrument_token=token,
                from_date=datetime.combine(today, time(9, 15)),
                to_date=datetime.combine(today, time(15, 30)),
                interval=interval,
            )
        except Exception as e:
            if "TokenException" in type(e).__name__:
                raise TokenExpiredError(f"Zerodha token expired: {e}")
            logger.warning("Intraday candle fetch failed for %s: %s", ticker, e)
            return pd.DataFrame()

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        if "date" in df.columns:
            df.index = pd.to_datetime(df["date"])
            df = df.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
            df = df[["Open", "High", "Low", "Close", "Volume"]]

        return df

    def _get_instrument_token(self, ticker: str) -> int | None:
        """Get NSE instrument token for an equity/index."""
        kite = self._get_kite()

        index_map = {
            "NIFTY": "NSE:NIFTY 50",
            "BANKNIFTY": "NSE:NIFTY BANK",
            "FINNIFTY": "NSE:NIFTY FIN SERVICE",
        }

        key = index_map.get(ticker.upper(), f"NSE:{ticker.upper()}")

        try:
            data = kite.ltp(key)
            if key in data:
                return data[key].get("instrument_token")
        except Exception:
            pass

        return None
