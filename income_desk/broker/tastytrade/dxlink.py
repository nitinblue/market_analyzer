"""DXLink streaming utilities — extracted from market_data.py.

Low-level DXLink fetch functions that open a single streamer connection,
subscribe to events, collect results, and return clean dicts. Each function
handles its own timeout and error classification.

Timeouts match eTrading's proven tastytrade_adapter.py:
- Quotes: 3s total, 0.5s per event
- Greeks: 15s total, 2s per event
- Underlying price: 5s single event
- Intraday candles: 10s collection window

All functions are async. Callers use ``run_sync()`` from ``_async.py``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from enum import StrEnum

logger = logging.getLogger(__name__)


class DXLinkError(StrEnum):
    """Classification of DXLink failures for caller decision-making."""

    GRANT_REVOKED = "grant_revoked"        # Token expired/revoked
    TIMEOUT = "timeout"                     # No data within timeout
    CONNECTION_FAILED = "connection_failed"  # WebSocket/network error
    NO_DATA = "no_data"                     # Connected but no events received
    UNKNOWN = "unknown"


def classify_error(exc: Exception) -> DXLinkError:
    """Classify a DXLink exception into an actionable error type."""
    msg = str(exc).lower()
    if "invalid_grant" in msg or "grant revoked" in msg:
        return DXLinkError.GRANT_REVOKED
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return DXLinkError.TIMEOUT
    if "websocket" in msg or "connection" in msg or "refused" in msg:
        return DXLinkError.CONNECTION_FAILED
    return DXLinkError.UNKNOWN


async def fetch_quotes(
    data_session,
    streamer_symbols: list[str],
    *,
    total_timeout: float = 3.0,
    per_event_timeout: float = 0.5,
) -> dict[str, dict]:
    """Fetch bid/ask quotes via DXLink streaming.

    Opens a single DXLinkStreamer connection, subscribes to all symbols,
    and collects Quote events until all symbols are received or timeout.

    Args:
        data_session: Authenticated tastytrade Session for DXLink.
        streamer_symbols: List of DXLink streamer symbols.
        total_timeout: Max seconds to wait for all quotes (default 3s).
        per_event_timeout: Max seconds to wait for each event (default 0.5s).

    Returns:
        ``{symbol: {"bid": float, "ask": float}}``
    """
    from tastytrade.dxfeed import Quote as DXQuote
    from tastytrade.streamer import DXLinkStreamer

    quotes: dict[str, dict] = {}
    if not streamer_symbols:
        return quotes

    try:
        async with DXLinkStreamer(data_session) as streamer:
            await streamer.subscribe(DXQuote, streamer_symbols)

            end_time = asyncio.get_event_loop().time() + total_timeout

            while asyncio.get_event_loop().time() < end_time:
                try:
                    event = await asyncio.wait_for(
                        streamer.get_event(DXQuote), timeout=per_event_timeout,
                    )
                    if event:
                        quotes[event.event_symbol] = {
                            "bid": float(event.bid_price or 0),
                            "ask": float(event.ask_price or 0),
                        }
                        if len(quotes) >= len(streamer_symbols):
                            break
                except asyncio.TimeoutError:
                    continue

    except Exception as e:
        err = classify_error(e)
        logger.warning("DXLink quote fetch error (%s): %s", err, e)

    return quotes


async def fetch_greeks(
    data_session,
    streamer_symbols: list[str],
    *,
    total_timeout: float = 15.0,
    per_event_timeout: float = 2.0,
    chunk_size: int = 12,
) -> dict[str, dict]:
    """Fetch Greeks via DXLink streaming, chunked for large symbol lists.

    For <= chunk_size symbols, opens one connection. For larger lists, splits
    into chunks and fetches sequentially (each chunk gets its own connection
    and full timeout). This avoids the problem of 30+ symbols timing out in
    a single 15s window.

    Args:
        data_session: Authenticated tastytrade Session for DXLink.
        streamer_symbols: List of DXLink streamer symbols.
        total_timeout: Max seconds per chunk (default 15s).
        per_event_timeout: Max seconds to wait for each event (default 2s).
        chunk_size: Max symbols per DXLink connection (default 12).

    Returns:
        ``{symbol: {"delta": float, "gamma": float, "theta": float, "vega": float, "iv": float|None}}``
    """
    if not streamer_symbols:
        return {}

    # Chunk large lists to avoid single-connection timeout
    if len(streamer_symbols) > chunk_size:
        chunks = [
            streamer_symbols[i:i + chunk_size]
            for i in range(0, len(streamer_symbols), chunk_size)
        ]
        logger.info(
            "Chunking %d symbols into %d batches of ≤%d",
            len(streamer_symbols), len(chunks), chunk_size,
        )
        all_greeks: dict[str, dict] = {}
        for i, chunk in enumerate(chunks):
            logger.info("Greeks batch %d/%d (%d symbols)", i + 1, len(chunks), len(chunk))
            chunk_result = await _fetch_greeks_single(
                data_session, chunk,
                total_timeout=total_timeout,
                per_event_timeout=per_event_timeout,
            )
            all_greeks.update(chunk_result)
        return all_greeks

    return await _fetch_greeks_single(
        data_session, streamer_symbols,
        total_timeout=total_timeout,
        per_event_timeout=per_event_timeout,
    )


async def _fetch_greeks_single(
    data_session,
    streamer_symbols: list[str],
    *,
    total_timeout: float = 15.0,
    per_event_timeout: float = 2.0,
) -> dict[str, dict]:
    """Fetch Greeks for a single batch (≤12 symbols) via one DXLink connection."""
    from tastytrade.dxfeed import Greeks as DXGreeks
    from tastytrade.streamer import DXLinkStreamer

    greeks: dict[str, dict] = {}
    if not streamer_symbols:
        return greeks

    symbols_needed = set(streamer_symbols)

    try:
        async with DXLinkStreamer(data_session) as streamer:
            await streamer.subscribe(DXGreeks, streamer_symbols)

            start_time = asyncio.get_event_loop().time()

            while symbols_needed and (asyncio.get_event_loop().time() - start_time) < total_timeout:
                try:
                    event = await asyncio.wait_for(
                        streamer.get_event(DXGreeks), timeout=per_event_timeout,
                    )
                    sym = event.event_symbol
                    if sym in symbols_needed:
                        greeks[sym] = {
                            "delta": float(event.delta or 0),
                            "gamma": float(event.gamma or 0),
                            "theta": float(event.theta or 0),
                            "vega": float(event.vega or 0),
                            "iv": float(event.volatility or 0) if hasattr(event, "volatility") else None,
                        }
                        symbols_needed.remove(sym)

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.warning("Error getting Greeks event: %s", e)
                    continue

            if symbols_needed:
                logger.warning("Timeout: missing Greeks for %d/%d symbols", len(symbols_needed), len(streamer_symbols))

    except Exception as e:
        err = classify_error(e)
        logger.error("DXLink Greeks streaming error (%s): %s", err, e)

    return greeks


async def fetch_underlying_price(
    data_session,
    ticker: str,
    *,
    timeout: float = 5.0,
) -> float | None:
    """Fetch real-time underlying mid price via DXLink equity Quote.

    Args:
        data_session: Authenticated tastytrade Session.
        ticker: Equity ticker (e.g. "SPY").
        timeout: Max seconds to wait for quote.

    Returns:
        Mid price (bid+ask)/2, or None on failure.
    """
    from tastytrade.dxfeed import Quote as DXQuote
    from tastytrade.streamer import DXLinkStreamer

    try:
        async with DXLinkStreamer(data_session) as streamer:
            await streamer.subscribe(DXQuote, [ticker])
            try:
                event = await asyncio.wait_for(
                    streamer.get_event(DXQuote), timeout=timeout,
                )
                bid = float(event.bid_price or 0)
                ask = float(event.ask_price or 0)
                if bid > 0 and ask > 0:
                    return round((bid + ask) / 2, 2)
                return float(event.last_price or 0) or None
            except asyncio.TimeoutError:
                return None
    except Exception as e:
        err = classify_error(e)
        logger.warning("DXLink underlying quote error (%s): %s", err, e)
        return None


async def fetch_candles(
    data_session,
    ticker: str,
    interval: str = "5m",
    start_time: datetime | None = None,
    *,
    collection_window: float = 10.0,
    per_event_timeout: float = 2.0,
) -> dict[int, dict]:
    """Fetch intraday candles via DXLink Candle subscription.

    Args:
        data_session: Authenticated tastytrade Session.
        ticker: Equity ticker.
        interval: Candle interval (e.g. "5m", "1m").
        start_time: UTC datetime for subscription start (default: today 9:30 ET).
        collection_window: Max seconds to collect candles.
        per_event_timeout: Max seconds per event wait.

    Returns:
        ``{timestamp_ms: {"time": int, "Open": float, "High": float, "Low": float, "Close": float, "Volume": float}}``
    """
    from tastytrade.dxfeed import Candle
    from tastytrade.streamer import DXLinkStreamer

    rows: dict[int, dict] = {}

    if start_time is None:
        start_time = _today_market_open()

    try:
        async with DXLinkStreamer(data_session) as streamer:
            await streamer.subscribe_candle([ticker], interval, start_time)

            end = asyncio.get_event_loop().time() + collection_window
            while asyncio.get_event_loop().time() < end:
                try:
                    event = await asyncio.wait_for(
                        streamer.get_event(Candle), timeout=per_event_timeout,
                    )
                    ts = int(event.time) if event.time else 0
                    if ts > 0:
                        rows[ts] = {
                            "time": ts,
                            "Open": float(event.open),
                            "High": float(event.high),
                            "Low": float(event.low),
                            "Close": float(event.close),
                            "Volume": float(event.volume or 0),
                        }
                    if getattr(event, "snapshot_end", False):
                        break
                except asyncio.TimeoutError:
                    break

    except Exception as e:
        err = classify_error(e)
        logger.warning("DXLink candle fetch error (%s): %s", err, e)

    return rows


async def fetch_option_chain_symbols(
    sdk_session,
    ticker: str,
    expiration=None,
) -> list[dict]:
    """Get all option streamer symbols via NestedOptionChain (SDK v12).

    Returns a list of dicts with keys: sym, strike, option_type, expiration.
    These can be passed directly to ``fetch_quotes`` / ``fetch_greeks``.

    Args:
        sdk_session: Authenticated tastytrade Session (for REST calls).
        ticker: Underlying ticker.
        expiration: Optional date filter.

    Returns:
        List of ``{"sym": str, "strike": float, "option_type": str, "expiration": date}``
    """
    from tastytrade.instruments import NestedOptionChain

    chains = NestedOptionChain.get(sdk_session, ticker)
    if asyncio.iscoroutine(chains):
        chains = await chains

    if not chains:
        return []

    symbol_info: list[dict] = []
    for chain in chains:
        for exp in chain.expirations:
            exp_date = exp.expiration_date
            if expiration and exp_date != expiration:
                continue
            for strike_obj in exp.strikes:
                strike_price = float(strike_obj.strike_price)
                if strike_obj.call_streamer_symbol:
                    symbol_info.append({
                        "sym": strike_obj.call_streamer_symbol,
                        "strike": strike_price,
                        "option_type": "call",
                        "expiration": exp_date,
                    })
                if strike_obj.put_streamer_symbol:
                    symbol_info.append({
                        "sym": strike_obj.put_streamer_symbol,
                        "strike": strike_price,
                        "option_type": "put",
                        "expiration": exp_date,
                    })

    return symbol_info


async def fetch_option_chain_rest(
    sdk_session,
    ticker: str,
    expiration=None,
) -> list[dict]:
    """Get option chain via REST API (``Option.get_option_chain``).

    BUG-012 fix: replaces the old approach of streaming 1000+ strikes via
    DXLink WebSocket. This REST call returns the full chain in one HTTP
    request (~1-2 seconds vs 3+ minutes).

    Each returned dict contains chain structure data (strike, type, expiry,
    streamer_symbol). No live bid/ask — those come from DXLink for the
    near-ATM subset only.

    Args:
        sdk_session: Authenticated tastytrade Session (for REST calls).
        ticker: Underlying ticker.
        expiration: Optional date filter.

    Returns:
        List of ``{"sym": str, "strike": float, "option_type": str, "expiration": date}``
    """
    from tastytrade.instruments import get_option_chain as _tt_get_chain

    chain = await _tt_get_chain(sdk_session, ticker)

    if not chain:
        return []

    symbol_info: list[dict] = []
    for exp_date, options in chain.items():
        if expiration and exp_date != expiration:
            continue
        for opt in options:
            streamer_sym = getattr(opt, "streamer_symbol", None)
            if not streamer_sym:
                continue
            opt_type_raw = getattr(opt, "option_type", None)
            if opt_type_raw is not None:
                # OptionType enum: .value is "C" or "P"
                opt_val = getattr(opt_type_raw, "value", str(opt_type_raw)).lower()
                if opt_val in ("c", "call"):
                    opt_type = "call"
                elif opt_val in ("p", "put"):
                    opt_type = "put"
                else:
                    continue
            else:
                continue
            symbol_info.append({
                "sym": streamer_sym,
                "strike": float(opt.strike_price),
                "option_type": opt_type,
                "expiration": exp_date,
            })

    return symbol_info


def _today_market_open() -> datetime:
    """Return today at 9:30 ET as a timezone-aware datetime (UTC)."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

    et = ZoneInfo("US/Eastern")
    now_et = datetime.now(et)
    open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    return open_et.astimezone(timezone.utc)
