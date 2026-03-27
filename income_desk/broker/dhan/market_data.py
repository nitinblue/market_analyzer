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

from income_desk.broker.base import MarketDataProvider

if TYPE_CHECKING:
    from income_desk.models.opportunity import LegSpec
    from income_desk.models.quotes import OptionQuote

logger = logging.getLogger(__name__)

# DhanHQ under_scrip_code for common underlyings (from Dhan's security master)
_SCRIP_CODES: dict[str, int] = {
    # Indices
    "NIFTY": 13,
    "BANKNIFTY": 25,
    "FINNIFTY": 27,
    "SENSEX": 51,
    "MIDCPNIFTY": 442,
    # F&O Stocks — NSE equity security IDs (from Dhan security master)
    "RELIANCE": 2885,
    "TCS": 11536,
    "INFY": 1594,
    "HDFCBANK": 1333,
    "ICICIBANK": 4963,
    "SBIN": 3045,
    "WIPRO": 3787,
    "BAJFINANCE": 317,
    "AXISBANK": 5900,
    "KOTAKBANK": 1922,
    "LT": 11483,
    "HCLTECH": 7229,
    "TATAMOTORS": 3456,
    "MARUTI": 10999,
    "SUNPHARMA": 3351,
    "ITC": 1660,
    "HINDUNILVR": 1394,
    "BHARTIARTL": 10604,
    "TITAN": 3506,
    "ASIANPAINT": 236,
    "ULTRACEMCO": 11532,
    "POWERGRID": 14977,
    "NTPC": 11630,
    "ONGC": 2475,
    "COALINDIA": 20374,
    "JSWSTEEL": 11723,
    "TATASTEEL": 3499,
    "M_M": 2031,
    "INDUSINDBK": 5258,
    "DIVISLAB": 10940,
    "DRREDDY": 881,
    "CIPLA": 694,
    "APOLLOHOSP": 157,
    "TECHM": 13538,
    "BAJAJFINSV": 16669,
    "EICHERMOT": 910,
    "NESTLEIND": 17963,
    "HEROMOTOCO": 1348,
    "BPCL": 526,
    "GRASIM": 1232,
    "BRITANNIA": 547,
    "TATACONSUM": 3432,
    "HDFCLIFE": 467,
    "HINDALCO": 1361,
    "ADANIPORTS": 15083,
}

# NSE lot sizes (contracts per lot) for index + stock options
# Stock lot sizes sourced from registry.py — must stay in sync.
_LOT_SIZES: dict[str, int] = {
    # Indices
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "SENSEX": 10,
    "MIDCPNIFTY": 75,
    # F&O Stocks
    "RELIANCE": 250,
    "TCS": 150,
    "INFY": 300,
    "HDFCBANK": 550,
    "ICICIBANK": 700,
    "SBIN": 1500,
    "WIPRO": 1500,
    "BAJFINANCE": 125,
    "AXISBANK": 600,
    "KOTAKBANK": 400,
    "LT": 150,
    "HCLTECH": 350,
    "TATAMOTORS": 1125,
    "MARUTI": 100,
    "SUNPHARMA": 350,
    "ITC": 1600,
    "HINDUNILVR": 300,
    "BHARTIARTL": 475,
    "TITAN": 175,
    "ASIANPAINT": 300,
    "ULTRACEMCO": 100,
    "POWERGRID": 2700,
    "NTPC": 2800,
    "ONGC": 3850,
    "COALINDIA": 2100,
    "JSWSTEEL": 675,
    "TATASTEEL": 1100,
    "M_M": 350,
    "INDUSINDBK": 500,
    "DIVISLAB": 150,
    "DRREDDY": 125,
    "CIPLA": 650,
    "APOLLOHOSP": 125,
    "TECHM": 600,
    "BAJAJFINSV": 500,
    "EICHERMOT": 175,
    "NESTLEIND": 50,
    "HEROMOTOCO": 150,
    "BPCL": 900,
    "GRASIM": 350,
    "BRITANNIA": 200,
    "TATACONSUM": 550,
    "HDFCLIFE": 1100,
    "HINDALCO": 1300,
    "ADANIPORTS": 1000,
}

# Dhan exchange segment constants
_SEGMENT_NSE_FNO = "NSE_FNO"
_SEGMENT_NSE_EQ = "NSE_EQ"
_SEGMENT_BSE_EQ = "BSE_EQ"
_SEGMENT_IDX_I = "IDX_I"

# Tickers that are indices (not equities) — determines segment for API calls.
# Index option chains use IDX_I segment; stock option chains use NSE_FNO.
# Index underlying prices use IDX_I; stock prices use NSE_EQ.
_INDEX_TICKERS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"}


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
        from income_desk.models.quotes import OptionQuote

        scrip_code = self._resolve_scrip_code(ticker)
        if scrip_code is None:
            return []

        # Index option chains use IDX_I segment; stock options use NSE_FNO.
        # Using NSE_FNO for indices returns a different instrument (wrong strikes).
        is_index = ticker.upper() in _INDEX_TICKERS
        chain_segment = _SEGMENT_IDX_I if is_index else _SEGMENT_NSE_FNO

        # Dhan requires expiry — fetch expiry list first if not provided
        target_expiry_str: str | None = None
        if expiration:
            target_expiry_str = expiration.strftime("%Y-%m-%d")
        else:
            try:
                exp_response = self._client.expiry_list(
                    under_security_id=scrip_code,  # int, not str
                    under_exchange_segment=chain_segment,
                )
                # Response: {data: {data: ["2026-03-27", ...], status: "success"}}
                exp_outer = exp_response.get("data", {}) if isinstance(exp_response, dict) else {}
                exp_list = exp_outer.get("data", exp_outer) if isinstance(exp_outer, dict) else exp_outer
                if isinstance(exp_list, list) and exp_list:
                    today = date.today()
                    future_exp = sorted(e for e in exp_list if e >= today.strftime("%Y-%m-%d"))
                    if future_exp:
                        target_expiry_str = future_exp[0]
                    else:
                        target_expiry_str = exp_list[-1]
            except Exception as e:
                logger.warning("Dhan expiry_list failed for %s: %s", ticker, e)
                return []

        if not target_expiry_str:
            logger.warning("No expiry available for %s", ticker)
            return []

        expiration = _parse_expiry(target_expiry_str) or expiration

        try:
            response = self._client.option_chain(
                under_security_id=scrip_code,  # int, not str
                under_exchange_segment=chain_segment,
                expiry=target_expiry_str,
            )
        except Exception as e:
            logger.warning("Dhan option_chain failed for %s: %s", ticker, e)
            return []

        if not response or response.get("status") != "success":
            logger.warning("Dhan option_chain returned non-success for %s", ticker)
            return []

        # Response structure: {data: {data: {last_price: X, oc: {strike: {ce: {}, pe: {}}}}}}
        outer = response.get("data", {})
        inner = outer.get("data", outer) if isinstance(outer, dict) else {}
        if not isinstance(inner, dict):
            logger.warning("Unexpected Dhan option_chain response structure for %s", ticker)
            return []

        # Extract underlying price — cross-validate chain vs ticker_data for indices
        chain_ltp = _safe_float(inner.get("last_price"))
        ticker_ltp = self.get_underlying_price(ticker) or 0
        if chain_ltp > 0 and ticker_ltp > 0:
            ratio = max(chain_ltp, ticker_ltp) / min(chain_ltp, ticker_ltp)
            if ratio > 1.5:
                logger.warning(
                    "%s option chain last_price=%.2f vs ticker_data=%.2f (%.1fx divergence)",
                    ticker, chain_ltp, ticker_ltp, ratio,
                )
        oc_data = inner.get("oc", {})
        if not isinstance(oc_data, dict):
            logger.warning("No 'oc' dict in Dhan option_chain for %s", ticker)
            return []

        lot_size = _LOT_SIZES.get(ticker.upper(), 1)
        ticker_upper = ticker.upper()

        results: list[OptionQuote] = []

        for strike_str, entry in oc_data.items():
            strike = _safe_float(strike_str)
            if strike <= 0:
                continue

            for side_key, opt_type in (("ce", "call"), ("pe", "put")):
                side_data = entry.get(side_key, {})
                if not side_data or not isinstance(side_data, dict):
                    continue

                bid = _safe_float(side_data.get("top_bid_price"))
                ask = _safe_float(side_data.get("top_ask_price"))
                ltp = _safe_float(side_data.get("last_price"))

                # Mid: prefer bid/ask midpoint, fall back to LTP
                if bid > 0 and ask > 0:
                    mid = (bid + ask) / 2
                else:
                    mid = ltp

                # Dhan returns IV as percentage (e.g. 25.5 means 25.5%)
                # MA convention: decimal (0.255)
                raw_iv = _safe_float(side_data.get("implied_volatility"))
                implied_volatility = raw_iv / 100.0 if raw_iv > 0 else None

                # Greeks are nested under "greeks" key
                greeks = side_data.get("greeks", {})

                results.append(OptionQuote(
                    ticker=ticker_upper,
                    strike=strike,
                    option_type=opt_type,
                    expiration=expiration,
                    bid=bid,
                    ask=ask,
                    mid=round(mid, 2),
                    last=ltp if ltp > 0 else None,
                    implied_volatility=implied_volatility,
                    delta=_safe_float(greeks.get("delta")) or None,
                    gamma=_safe_float(greeks.get("gamma")) or None,
                    theta=_safe_float(greeks.get("theta")) or None,
                    vega=_safe_float(greeks.get("vega")) or None,
                    volume=_safe_int(side_data.get("volume")),
                    open_interest=_safe_int(side_data.get("oi")),
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

    def get_greeks(
        self, legs_or_ticker: "list[LegSpec] | str" = "", ticker: str = "",
    ) -> dict[str, dict]:
        """Get Greeks from Dhan option chain.

        Accepts either:
        - A ticker string: returns ATM Greeks for nearest expiry
        - A list of LegSpec: returns Greeks for each leg

        Returns dict keyed by ``"{strike}{C|P}"`` (e.g. ``"23000C"``),
        with values ``{"delta": .., "gamma": .., "theta": .., "vega": .., "iv": ..}``.
        """
        # Resolve ticker
        if isinstance(legs_or_ticker, str) and legs_or_ticker:
            ticker = legs_or_ticker
        elif isinstance(legs_or_ticker, list) and legs_or_ticker:
            # LegSpec list — try to extract ticker from chain call
            ticker = ticker or ""
        if not ticker:
            return {}

        chain = self.get_option_chain(ticker)
        if not chain:
            return {}

        result: dict[str, dict] = {}
        if isinstance(legs_or_ticker, list) and legs_or_ticker:
            # Match specific legs
            for leg in legs_or_ticker:
                opt_type_char = "C" if leg.option_type == "call" else "P"
                key = f"{leg.strike:.0f}{opt_type_char}"
                for q in chain:
                    if (q.strike == leg.strike and q.option_type == leg.option_type
                            and q.delta is not None):
                        result[key] = {
                            "delta": q.delta, "gamma": q.gamma,
                            "theta": q.theta, "vega": q.vega,
                            "iv": q.implied_volatility,
                        }
                        break
        else:
            # Return all Greeks from chain where available
            for q in chain:
                if q.delta is not None:
                    opt_type_char = "C" if q.option_type == "call" else "P"
                    key = f"{q.strike:.0f}{opt_type_char}"
                    result[key] = {
                        "delta": q.delta, "gamma": q.gamma,
                        "theta": q.theta, "vega": q.vega,
                        "iv": q.implied_volatility,
                    }

        return result

    # Session-level price cache: avoids hammering Dhan for the same ticker
    # within a short window. Entries are (price, timestamp).
    _price_cache: dict[str, tuple[float, float]] = {}
    _PRICE_CACHE_TTL = 5.0  # seconds

    def get_underlying_price(self, ticker: str) -> float | None:
        """Get current price of underlying (index or equity) via ticker_data.

        Uses NSE_EQ for equities, IDX_I for indices.
        Includes retry with backoff to handle Dhan rate limiting.
        Caches results for 5 seconds to reduce API calls.
        """
        import time as _time

        upper = ticker.upper()

        # Check cache first
        if upper in self._price_cache:
            cached_price, cached_at = self._price_cache[upper]
            if (_time.monotonic() - cached_at) < self._PRICE_CACHE_TTL:
                return cached_price

        scrip_code = self._resolve_scrip_code(ticker)
        if scrip_code is None:
            return None

        is_index = upper in _INDEX_TICKERS
        segment = _SEGMENT_IDX_I if is_index else _SEGMENT_NSE_EQ

        # Retry with backoff: Dhan rate-limits ticker_data under burst
        for attempt in range(3):
            try:
                if attempt > 0:
                    _time.sleep(1.5 * attempt)

                response = self._client.ticker_data(
                    {segment: [scrip_code]}
                )
                if not isinstance(response, dict) or response.get("status") != "success":
                    continue

                outer = response.get("data", {})
                inner = outer.get("data", outer) if isinstance(outer, dict) else {}
                if isinstance(inner, dict):
                    seg_data = inner.get(segment, {})
                    if isinstance(seg_data, dict):
                        item = seg_data.get(str(scrip_code), seg_data.get(scrip_code, {}))
                        if isinstance(item, dict):
                            ltp = _safe_float(item.get("last_price"))
                            if ltp > 0:
                                self._price_cache[upper] = (ltp, _time.monotonic())
                                return ltp
            except Exception as e:
                logger.debug("Dhan ticker_data attempt %d failed for %s: %s", attempt + 1, ticker, e)

        return None

    def get_prices_batch(self, tickers: list[str]) -> dict[str, float]:
        """Fetch prices for multiple tickers in minimal API calls.

        Groups tickers by segment (IDX_I vs NSE_EQ) and makes ONE
        Dhan ticker_data call per segment — maximum 2 API calls total.
        Returns dict of ticker → price. Missing tickers omitted.
        """
        import time as _time

        if not tickers:
            return {}

        # Group by segment
        idx_codes: dict[str, int] = {}  # ticker → scrip_code
        eq_codes: dict[str, int] = {}
        for ticker in tickers:
            upper = ticker.upper()
            # Check cache first
            if upper in self._price_cache:
                cached_price, cached_at = self._price_cache[upper]
                if (_time.monotonic() - cached_at) < self._PRICE_CACHE_TTL:
                    continue  # will add from cache below

            scrip_code = self._resolve_scrip_code(ticker)
            if scrip_code is None:
                continue
            if upper in _INDEX_TICKERS:
                idx_codes[upper] = scrip_code
            else:
                eq_codes[upper] = scrip_code

        result: dict[str, float] = {}

        # Add cached prices
        now = _time.monotonic()
        for ticker in tickers:
            upper = ticker.upper()
            if upper in self._price_cache:
                cached_price, cached_at = self._price_cache[upper]
                if (now - cached_at) < self._PRICE_CACHE_TTL:
                    result[upper] = cached_price

        # Batch fetch indices (1 API call)
        if idx_codes:
            try:
                response = self._client.ticker_data(
                    {_SEGMENT_IDX_I: list(idx_codes.values())}
                )
                if isinstance(response, dict) and response.get("status") == "success":
                    outer = response.get("data", {})
                    inner = outer.get("data", outer) if isinstance(outer, dict) else {}
                    if isinstance(inner, dict):
                        seg_data = inner.get(_SEGMENT_IDX_I, {})
                        if isinstance(seg_data, dict):
                            for ticker_upper, scrip_code in idx_codes.items():
                                item = seg_data.get(str(scrip_code), seg_data.get(scrip_code, {}))
                                if isinstance(item, dict):
                                    ltp = _safe_float(item.get("last_price"))
                                    if ltp > 0:
                                        result[ticker_upper] = ltp
                                        self._price_cache[ticker_upper] = (ltp, _time.monotonic())
            except Exception as e:
                logger.debug("Batch index price fetch failed: %s", e)

        # Batch fetch equities (1 API call)
        if eq_codes:
            try:
                _time.sleep(1.5)  # small delay between segment calls
                response = self._client.ticker_data(
                    {_SEGMENT_NSE_EQ: list(eq_codes.values())}
                )
                if isinstance(response, dict) and response.get("status") == "success":
                    outer = response.get("data", {})
                    inner = outer.get("data", outer) if isinstance(outer, dict) else {}
                    if isinstance(inner, dict):
                        seg_data = inner.get(_SEGMENT_NSE_EQ, {})
                        if isinstance(seg_data, dict):
                            for ticker_upper, scrip_code in eq_codes.items():
                                item = seg_data.get(str(scrip_code), seg_data.get(scrip_code, {}))
                                if isinstance(item, dict):
                                    ltp = _safe_float(item.get("last_price"))
                                    if ltp > 0:
                                        result[ticker_upper] = ltp
                                        self._price_cache[ticker_upper] = (ltp, _time.monotonic())
            except Exception as e:
                logger.debug("Batch equity price fetch failed: %s", e)

        return result

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

        is_index = ticker.upper() in _INDEX_TICKERS
        if is_index:
            # Dhan intraday_minute_data does not support index candles.
            # Index intraday data requires a different endpoint (not available
            # in dhanhq SDK as of 2026-03). Return empty gracefully.
            return pd.DataFrame()
        segment = _SEGMENT_NSE_EQ
        inst_type = "EQUITY"

        today = date.today()
        try:
            # Use intraday_minute_data with today's date range
            response = self._client.intraday_minute_data(
                security_id=str(scrip_code),
                exchange_segment=segment,
                instrument_type=inst_type,
                from_date=today.strftime("%Y-%m-%d"),
                to_date=today.strftime("%Y-%m-%d"),
            )
        except AttributeError:
            # Older SDK versions may not have this method
            logger.debug("Dhan SDK does not support intraday_minute_data")
            return pd.DataFrame()
        except Exception as e:
            logger.warning("Dhan intraday_candles failed for %s: %s", ticker, e)
            return pd.DataFrame()

        # Guard against DataFrame or None response
        if response is None:
            return pd.DataFrame()
        if isinstance(response, pd.DataFrame):
            return response if not response.empty else pd.DataFrame()

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
