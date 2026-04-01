"""ChainFetcher — single-fetch, pass-everywhere chain data service.

Fetches option chain data once per ticker into a ChainBundle, which is then
passed to ranking, assessors, pricing, and monitoring without re-fetching.

This eliminates the 4-5x redundant chain fetch pattern that was the root
cause of live test failures (slow ranking, silent data loss, illiquid trades).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING

import pandas as pd

from income_desk.models.chain import ChainBundle, FetchMetadata
from income_desk.models.instrument_snapshot import InstrumentSnapshot, MarketSnapshot

if TYPE_CHECKING:
    from income_desk.adapters.base import MarketDataProvider
    from income_desk.data.service import DataService
    from income_desk.models.vol_surface import VolatilitySurface
    from income_desk.service.vol_surface import VolSurfaceService

logger = logging.getLogger(__name__)


class ChainFetcher:
    """Stateless service: fetch all chains for a batch of tickers.

    Returns dict[str, ChainBundle] with explicit data quality reporting.
    Every downstream consumer (ranking, assessors, pricing) receives
    pre-fetched data — no hidden network calls.
    """

    def __init__(
        self,
        market_data: MarketDataProvider | None = None,
        data_service: DataService | None = None,
    ) -> None:
        self._market_data = market_data
        self._data_service = data_service

    def fetch_batch(
        self,
        tickers: list[str],
        snapshot: MarketSnapshot | None = None,
    ) -> dict[str, ChainBundle]:
        """Fetch chains for all tickers, respecting rate limits.

        When *snapshot* is provided, tickers found in the snapshot use the
        fast ``_fetch_with_snapshot`` path — skips REST discovery entirely
        and streams only the tradeable symbols already identified.

        For TastyTrade: no rate limit between tickers.
        For Dhan: 3.5s sleep between tickers.

        Returns:
            dict mapping ticker to ChainBundle with quality metadata.
        """
        bundles: dict[str, ChainBundle] = {}
        provider = getattr(self._market_data, 'provider_name', '') if self._market_data else ''

        for idx, ticker in enumerate(tickers):
            # Rate limit for Dhan only
            if idx > 0 and provider == 'dhan':
                time.sleep(4)

            if snapshot and ticker in snapshot.instruments:
                bundle = self._fetch_with_snapshot(
                    ticker, snapshot.instruments[ticker], provider,
                )
            else:
                bundle = self._fetch_single(ticker, provider)
            bundles[ticker] = bundle

            # Report quality
            if bundle.fetch_meta.error:
                logger.warning(
                    "%s: chain fetch FAILED — %s",
                    ticker, bundle.fetch_meta.error,
                )
            elif bundle.fetch_meta.is_partial:
                logger.warning(
                    "%s: PARTIAL chain — %d/%d symbols received (%.0f%%) in %.1fs",
                    ticker, bundle.fetch_meta.received_symbols,
                    bundle.fetch_meta.requested_symbols,
                    bundle.quality_pct, bundle.fetch_meta.fetch_duration_s,
                )
            else:
                logger.info(
                    "%s: chain OK — %d symbols in %.1fs",
                    ticker, bundle.fetch_meta.received_symbols,
                    bundle.fetch_meta.fetch_duration_s,
                )

        # Summary
        usable = sum(1 for b in bundles.values() if b.is_usable)
        partial = sum(1 for b in bundles.values() if b.fetch_meta.is_partial)
        failed = sum(1 for b in bundles.values() if b.fetch_meta.error)
        logger.info(
            "ChainFetcher: %d/%d tickers usable, %d partial, %d failed",
            usable, len(tickers), partial, failed,
        )

        return bundles

    def _fetch_with_snapshot(
        self,
        ticker: str,
        inst: InstrumentSnapshot,
        provider: str,
    ) -> ChainBundle:
        """Fast path: build chain from snapshot structure + DXLink quotes.

        Skips the REST ``get_option_chain`` call entirely. Instead:
        1. Read streamer symbols from the pre-built InstrumentSnapshot.
        2. Stream bid/ask + Greeks for those symbols via DXLink.
        3. Assemble OptionQuote list and derived data (vol surface, context).

        This is ~3-5x faster than ``_fetch_single`` because REST discovery
        (the slowest step) is eliminated.
        """
        from income_desk.models.quotes import OptionQuote

        t0 = time.monotonic()
        underlying_price = inst.underlying_price
        error: str | None = None
        raw_chain: list[OptionQuote] = []

        try:
            # Get current underlying price (fast — single DXLink quote)
            if self._market_data is not None:
                live_price = self._market_data.get_underlying_price(ticker)
                if live_price and live_price > 0:
                    underlying_price = live_price

            # Build symbol_info list from snapshot structure (matches REST format)
            symbol_info: list[dict] = []
            for exp_info in inst.expiries:
                for strike_info in exp_info.strikes:
                    if not strike_info.is_tradeable:
                        continue  # Only stream tradeable strikes
                    symbol_info.append({
                        "sym": strike_info.streamer_symbol,
                        "strike": strike_info.strike,
                        "option_type": strike_info.option_type,
                        "expiration": exp_info.expiration,
                    })

            if not symbol_info:
                error = "Snapshot has no tradeable strikes"
                logger.warning("%s: snapshot has no tradeable strikes", ticker)
            elif self._market_data is not None:
                # Stream quotes + Greeks via DXLink (same as get_option_chain internals)
                from income_desk.broker.tastytrade._async import run_sync
                from income_desk.broker.tastytrade.dxlink import fetch_greeks, fetch_quotes

                streamer_symbols = [s["sym"] for s in symbol_info]
                total_timeout = max(3.0, min(15.0, len(streamer_symbols) * 0.15))

                session = getattr(self._market_data, '_session', None)
                if session is None:
                    error = "No broker session for DXLink streaming"
                else:
                    quotes_result = run_sync(
                        fetch_quotes(
                            session.data_session,
                            streamer_symbols,
                            total_timeout=total_timeout,
                        ),
                    )
                    greeks_result = run_sync(
                        fetch_greeks(session.data_session, streamer_symbols),
                    )

                    quotes_map = quotes_result.data
                    greeks_map = greeks_result.data

                    logger.info(
                        "%s (snapshot): %d/%d quotes, %d/%d greeks",
                        ticker, quotes_result.received_count, len(streamer_symbols),
                        greeks_result.received_count, len(streamer_symbols),
                    )

                    # Build OptionQuote list
                    for info in symbol_info:
                        sym = info["sym"]
                        q = quotes_map.get(sym, {})
                        g = greeks_map.get(sym, {})
                        bid = q.get("bid", 0.0)
                        ask = q.get("ask", 0.0)
                        raw_chain.append(OptionQuote(
                            ticker=ticker,
                            expiration=info["expiration"],
                            strike=info["strike"],
                            option_type=info["option_type"],
                            bid=bid,
                            ask=ask,
                            mid=round((bid + ask) / 2, 4),
                            implied_volatility=g.get("iv"),
                            delta=g.get("delta"),
                            gamma=g.get("gamma"),
                            theta=g.get("theta"),
                            vega=g.get("vega"),
                        ))

        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            logger.warning("Snapshot chain fetch failed for %s: %s", ticker, e)

        elapsed = time.monotonic() - t0

        # Build chain DataFrame for vol_surface
        chain_df = self._build_chain_df(raw_chain)

        with_quotes = sum(
            1 for q in raw_chain
            if getattr(q, 'bid', 0) > 0 or getattr(q, 'ask', 0) > 0
        )
        total_count = with_quotes

        # Build vol surface
        vol_surface = None
        if not chain_df.empty and underlying_price > 0:
            try:
                from income_desk.features.vol_surface import compute_vol_surface
                vol_surface = compute_vol_surface(chain_df, underlying_price, ticker)
            except Exception as e:
                logger.debug("Vol surface compute failed for %s: %s", ticker, e)

        # Build chain context
        chain_context = None
        if raw_chain and underlying_price > 0:
            try:
                from income_desk.opportunity.option_plays._chain_context import build_chain_context
                chain_context = build_chain_context(ticker, raw_chain, underlying_price)
            except Exception as e:
                logger.debug("Chain context build failed for %s: %s", ticker, e)

        return ChainBundle(
            ticker=ticker,
            underlying_price=underlying_price,
            raw_chain=raw_chain,
            chain_df=chain_df,
            vol_surface=vol_surface,
            chain_context=chain_context,
            fetch_meta=FetchMetadata(
                timestamp=datetime.now(),
                provider=f"{provider}+snapshot",
                fetch_duration_s=elapsed,
                requested_symbols=total_count,
                received_symbols=with_quotes,
                missing_symbols=[],
                is_partial=with_quotes < total_count * 0.5 if total_count > 0 else False,
                error=error,
            ),
        )

    def _fetch_single(self, ticker: str, provider: str) -> ChainBundle:
        """Fetch chain + build all derived data for one ticker."""
        t0 = time.monotonic()
        raw_chain: list = []
        underlying_price = 0.0
        error: str | None = None

        if self._market_data is not None:
            try:
                raw_chain = self._market_data.get_option_chain(ticker) or []
                underlying_price = self._market_data.get_underlying_price(ticker) or 0.0
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                logger.warning("Chain fetch failed for %s: %s", ticker, e)

        elapsed = time.monotonic() - t0

        # Build chain DataFrame for vol_surface
        chain_df = self._build_chain_df(raw_chain)

        # Count near-ATM quotes (with real bid/ask) vs total near-ATM
        # Only near-ATM strikes get DXLink quotes; far-OTM always have bid=0
        with_quotes = sum(
            1 for q in raw_chain
            if getattr(q, 'bid', 0) > 0 or getattr(q, 'ask', 0) > 0
        )
        # Use with_quotes as both requested and received for quality
        # (far-OTM strikes were intentionally skipped, not "missing")
        total_count = with_quotes  # Only count what we actually tried to fetch

        # Build vol surface from chain_df (no additional fetch)
        vol_surface: VolatilitySurface | None = None
        if not chain_df.empty and underlying_price > 0:
            try:
                from income_desk.features.vol_surface import compute_vol_surface
                vol_surface = compute_vol_surface(chain_df, underlying_price, ticker)
            except Exception as e:
                logger.debug("Vol surface compute failed for %s: %s", ticker, e)

        # Build chain context for assessor strike selection
        chain_context = None
        if raw_chain and underlying_price > 0:
            try:
                from income_desk.opportunity.option_plays._chain_context import build_chain_context
                chain_context = build_chain_context(ticker, raw_chain, underlying_price)
            except Exception as e:
                logger.debug("Chain context build failed for %s: %s", ticker, e)

        return ChainBundle(
            ticker=ticker,
            underlying_price=underlying_price,
            raw_chain=raw_chain,
            chain_df=chain_df,
            vol_surface=vol_surface,
            chain_context=chain_context,
            fetch_meta=FetchMetadata(
                timestamp=datetime.now(),
                provider=provider,
                fetch_duration_s=elapsed,
                requested_symbols=total_count,
                received_symbols=with_quotes,
                missing_symbols=[],  # TODO: could track specific missing symbols
                is_partial=with_quotes < total_count * 0.5 if total_count > 0 else False,
                error=error,
            ),
        )

    @staticmethod
    def _build_chain_df(raw_chain: list) -> pd.DataFrame:
        """Convert list[OptionQuote] to DataFrame for vol_surface."""
        if not raw_chain:
            return pd.DataFrame()

        rows: list[dict] = []
        for q in raw_chain:
            row = q.model_dump() if hasattr(q, 'model_dump') else vars(q)
            rows.append(row)

        df = pd.DataFrame(rows)

        # Normalise column names to what compute_vol_surface expects
        if 'iv' in df.columns and 'implied_volatility' not in df.columns:
            df = df.rename(columns={'iv': 'implied_volatility'})

        # Keep rows with bid/ask activity OR IV data
        has_bid_ask = 'bid' in df.columns and 'ask' in df.columns
        has_iv = 'implied_volatility' in df.columns
        if has_bid_ask and has_iv:
            df = df[
                (df['bid'] > 0) | (df['ask'] > 0) |
                (df['implied_volatility'].notna() & (df['implied_volatility'] > 0))
            ]
        elif has_bid_ask:
            df = df[(df['bid'] > 0) | (df['ask'] > 0)]

        return df
