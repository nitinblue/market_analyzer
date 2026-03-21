"""Dhan market data provider — option chains with Greeks for India NSE/NFO.

DhanHQ option_chain() returns ALL strikes for ALL expirations in a single call,
including bid/ask, LTP, OI, volume, IV, and full Greeks (delta/gamma/theta/vega).
This is a significant advantage over Zerodha (which has no native Greeks).

Rate limits:
- Option chain: 1 unique request per 3 seconds (conservative)
- Market quote: 20K requests / day total

Segments: NSE_FNO for F&O, NSE_EQ for equity.
All India index options are European exercise.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import TYPE_CHECKING

import pandas as pd

from market_analyzer.broker.base import MarketDataProvider

if TYPE_CHECKING:
    from market_analyzer.models.opportunity import LegSpec
    from market_analyzer.models.quotes import OptionQuote

logger = logging.getLogger(__name__)

# DhanHQ under_scrip_code for common underlyings (from Dhan's security master)
_SCRIP_CODES: dict[str, int] = {
    "NIFTY": 13,
    "BANKNIFTY": 25,
    "FINNIFTY": 27,
    "SENSEX": 51,
    "MIDCPNIFTY": 442,
}

# NSE lot sizes (contracts per lot) for index options
_LOT_SIZES: dict[str, int] = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "SENSEX": 10,
    "MIDCPNIFTY": 75,
}

# Dhan exchange segment constants
_SEGMENT_NSE_FNO = "NSE_FNO"
_SEGMENT_NSE_EQ = "NSE_EQ"
_SEGMENT_BSE_EQ = "BSE_EQ"

# Index underlying price segment (indices trade on NSE_EQ or IDX_I)
_INDEX_SEGMENT = "IDX_I"


def _safe_float(val, default: float = 0.0) -> float:
    """Convert value to float, returning default on None / empty string."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default: int = 0) -> int:
    """Convert value to int, returning default on None / empty string."""
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _parse_expiry(exp_str: str | None) -> date | None:
    """Parse Dhan expiry date string (YYYY-MM-DD) to date object."""
    if not exp_str:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(exp_str, fmt).date()
        except ValueError:
            continue
    return None


class DhanMarketData(MarketDataProvider):
    """Dhan MarketDataProvider for India NSE/NFO via DhanHQ SDK.

    Key differences from Zerodha:
    - option_chain() returns Greeks natively (no estimation needed)
    - IV is returned as percentage (e.g. 25.5 = 25.5%) → converted to decimal
    - Single API call returns all strikes + all expirations
    - Rate limit: 1 unique request per 3 seconds for option chain
    """

    def __init__(
        self,
        client: object = None,
        *,
        api_key: str = "",
        access_token: str = "",
    ) -> None:
        """Args:
            client: Pre-authenticated ``dhanhq`` instance (preferred).
            api_key: Unused legacy parameter (kept for backward compat).
            access_token: Unused legacy parameter (kept for backward compat).

        Note: ``client`` is optional so that property-only tests can
        instantiate without a live SDK connection. Calling any data-fetching
        method without a real client will raise AttributeError or return [].
        """
        self._client = client

    @property
    def provider_name(self) -> str:
        return "dhan"

    @property
    def rate_limit_per_second(self) -> int:
        # General Dhan API: ~25 req/s for market_quote and other REST calls.
        # option_chain specifically: 1 unique request per 3 seconds.
        # Callers should throttle option_chain calls independently.
        return 25

    @property
    def supports_batch(self) -> bool:
        # option_chain() already returns all strikes in one call
        return False

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
        """NIFTY default lot size (25 contracts per lot)."""
        return 25

    def _resolve_scrip_code(self, ticker: str) -> int | None:
        """Resolve ticker to DhanHQ under_scrip_code.

        For known index options, use the lookup table.
        For individual stocks, the caller must provide the numeric security ID.
        """
        upper = ticker.upper()
        if upper in _SCRIP_CODES:
            return _SCRIP_CODES[upper]
        # Allow numeric ticker as raw scrip code (for individual stocks)
        try:
            return int(ticker)
        except ValueError:
            logger.warning(
                "Unknown Dhan ticker %r — not in _SCRIP_CODES and not numeric. "
                "Add to _SCRIP_CODES or pass numeric security ID.",
                ticker,
            )
            return None

    def get_option_chain(
        self,
        ticker: str,
        expiration: date | None = None,
    ) -> list[OptionQuote]:
        """Fetch full option chain from DhanHQ.

        DhanHQ returns ALL strikes for ALL expirations in one call.
        If ``expiration`` is provided, filters to that date only.
        If ``expiration`` is None, returns nearest expiry chain.

        Greeks (delta/gamma/theta/vega) and IV are included in response.
        IV is converted from Dhan's percentage format to decimal (÷100).

        Args:
            ticker: Underlying ticker, e.g. "NIFTY", "BANKNIFTY".
            expiration: Filter to this expiry date, or None for nearest.

        Returns:
            List of OptionQuote objects with real Greeks from Dhan.
        """
        from market_analyzer.models.quotes import OptionQuote

        scrip_code = self._resolve_scrip_code(ticker)
        if scrip_code is None:
            return []

        try:
            response = self._client.option_chain(
                under_scrip_code=scrip_code,
                under_exchange_segment=_SEGMENT_NSE_FNO,
            )
        except Exception as e:
            logger.warning("Dhan option_chain failed for %s: %s", ticker, e)
            return []

        if not response:
            return []

        # Dhan may return the data under "data" key or at top level
        entries = response.get("data", response) if isinstance(response, dict) else response
        if not isinstance(entries, list):
            logger.warning("Unexpected Dhan option_chain response structure for %s", ticker)
            return []

        lot_size = _LOT_SIZES.get(ticker.upper(), 1)
        ticker_upper = ticker.upper()

        # Collect all expirations if filtering to nearest
        all_expiries: list[date] = []
        if expiration is None:
            today = date.today()
            for entry in entries:
                exp_date = _parse_expiry(entry.get("expiryDate") or entry.get("expiry_date"))
                if exp_date and exp_date >= today:
                    all_expiries.append(exp_date)
            if all_expiries:
                expiration = min(all_expiries)

        results: list[OptionQuote] = []

        for entry in entries:
            strike = _safe_float(entry.get("strikePrice") or entry.get("strike_price"))
            exp_date = _parse_expiry(entry.get("expiryDate") or entry.get("expiry_date"))

            if exp_date is None:
                continue
            if expiration is not None and exp_date != expiration:
                continue

            for side_key, opt_type in (("ce", "call"), ("pe", "put")):
                side_data = entry.get(side_key, {})
                if not side_data or not isinstance(side_data, dict):
                    continue

                bid = _safe_float(side_data.get("bid_price") or side_data.get("bidPrice"))
                ask = _safe_float(side_data.get("ask_price") or side_data.get("askPrice"))
                ltp = _safe_float(side_data.get("ltp") or side_data.get("last_price"))

                # Mid: prefer bid/ask midpoint, fall back to LTP
                if bid > 0 and ask > 0:
                    mid = (bid + ask) / 2
                else:
                    mid = ltp

                # Dhan returns IV as percentage (e.g. 25.5 means 25.5%)
                # MA convention: decimal (0.255)
                raw_iv = _safe_float(side_data.get("iv") or side_data.get("impliedVolatility"))
                implied_volatility = raw_iv / 100.0 if raw_iv > 0 else None

                results.append(OptionQuote(
                    ticker=ticker_upper,
                    strike=strike,
                    option_type=opt_type,
                    expiration=exp_date,
                    bid=bid,
                    ask=ask,
                    mid=round(mid, 2),
                    last=ltp if ltp > 0 else None,
                    implied_volatility=implied_volatility,
                    delta=_safe_float(side_data.get("delta")) or None,
                    gamma=_safe_float(side_data.get("gamma")) or None,
                    theta=_safe_float(side_data.get("theta")) or None,
                    vega=_safe_float(side_data.get("vega")) or None,
                    volume=_safe_int(side_data.get("volume")),
                    open_interest=_safe_int(side_data.get("oi") or side_data.get("openInterest")),
                    lot_size=lot_size,
                ))

        return results

    def get_quotes(
        self,
        legs: list[LegSpec],
        *,
        ticker: str = "",
        include_greeks: bool = True,
    ) -> list[OptionQuote]:
        """Fetch quotes for specific option legs by filtering the full chain.

        DhanHQ does not support per-leg quote queries — the option_chain()
        call returns all strikes, so we fetch the chain and filter.

        Args:
            legs: Option legs to match (strike + expiry + type).
            ticker: Underlying ticker (required).
            include_greeks: Included always (Dhan provides them natively).

        Returns:
            List of OptionQuote (same order as legs). None-equivalent entries
            are omitted — caller must handle missing quotes.
        """
        if not legs:
            return []

        # Determine unique expirations to minimize chain calls
        expirations = list({leg.expiration for leg in legs if leg.expiration})
        chain: list[OptionQuote] = []

        if len(expirations) == 1:
            chain = self.get_option_chain(ticker, expiration=expirations[0])
        else:
            # Multiple expirations — fetch full chain and filter
            chain = self.get_option_chain(ticker)

        results: list[OptionQuote] = []
        for leg in legs:
            match = None
            for q in chain:
                if (
                    q.strike == leg.strike
                    and q.option_type == leg.option_type
                    and q.expiration == leg.expiration
                ):
                    match = q
                    break
            results.append(match)  # type: ignore[arg-type]

        return results

    def get_greeks(self, legs: list[LegSpec]) -> dict[str, dict]:
        """Greeks are included natively in Dhan option chain response.

        Returns a dict keyed by ``"{strike}{C|P}"`` (e.g. ``"26000C"``).
        """
        if not legs:
            return {}

        # Get ticker from first leg if possible — legs don't carry ticker
        # Return empty if no ticker context; caller should use get_quotes()
        return {}

    def get_underlying_price(self, ticker: str) -> float | None:
        """Get current price of underlying (index or equity) via market_quote.

        Uses NSE_FNO segment for index futures as proxy, falls back to IDX_I.
        """
        scrip_code = self._resolve_scrip_code(ticker)
        if scrip_code is None:
            return None

        # Try NSE_FNO first (works for index options underlyings)
        for segment in (_SEGMENT_NSE_FNO, _INDEX_SEGMENT, _SEGMENT_NSE_EQ):
            try:
                response = self._client.market_quote(
                    security_id=str(scrip_code),
                    exchange_segment=segment,
                )
                if not response:
                    continue
                data = response.get("data", response) if isinstance(response, dict) else None
                if data:
                    ltp = _safe_float(
                        data.get("ltp")
                        or data.get("last_price")
                        or data.get("lastTradedPrice")
                    )
                    if ltp > 0:
                        return ltp
            except Exception as e:
                logger.debug("Dhan market_quote failed for %s on %s: %s", ticker, segment, e)
                continue

        return None

    def get_intraday_candles(
        self, ticker: str, interval: str = "5m",
    ) -> pd.DataFrame:
        """Get today's intraday candles via Dhan historical candle API.

        Dhan uses: dhan.intraday_daily_minute_charts(security_id, exchange_segment)
        Interval mapping: "5m" → "1MIN", "1m" → "1MIN" (smallest available).

        Returns empty DataFrame if not available or not connected.
        """
        scrip_code = self._resolve_scrip_code(ticker)
        if scrip_code is None:
            return pd.DataFrame()

        try:
            response = self._client.intraday_daily_minute_charts(
                security_id=str(scrip_code),
                exchange_segment=_SEGMENT_NSE_EQ,
            )
        except AttributeError:
            # Older SDK versions may not have this method
            logger.debug("Dhan SDK does not support intraday_daily_minute_charts")
            return pd.DataFrame()
        except Exception as e:
            logger.warning("Dhan intraday_candles failed for %s: %s", ticker, e)
            return pd.DataFrame()

        if not response:
            return pd.DataFrame()

        candles = response.get("data", response) if isinstance(response, dict) else response
        if not isinstance(candles, list) or not candles:
            return pd.DataFrame()

        try:
            df = pd.DataFrame(candles)
            # Dhan columns: timestamp, open, high, low, close, volume
            col_map = {
                "timestamp": "Datetime",
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            if "Datetime" in df.columns:
                df.index = pd.to_datetime(df["Datetime"])
            keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
            return df[keep] if keep else df
        except Exception as e:
            logger.warning("Dhan candle parsing failed for %s: %s", ticker, e)
            return pd.DataFrame()
