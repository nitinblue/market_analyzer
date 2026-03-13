"""Universe scanner — dynamic ticker selection via broker filters.

Two-phase scanning:
  Phase 1: Pull equity listings from broker, apply basic filters (asset type, price)
  Phase 2: Batch-fetch market metrics, apply IV/liquidity/beta filters
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

from market_analyzer.models.universe import (
    PRESETS,
    AssetType,
    SortField,
    UniverseCandidate,
    UniverseFilter,
    UniverseScanResult,
)

if TYPE_CHECKING:
    from market_analyzer.broker.base import MarketMetricsProvider, WatchlistProvider

logger = logging.getLogger(__name__)

# Batch size for market metrics API calls
_METRICS_BATCH_SIZE = 50


class UniverseService:
    """Scan broker universe and filter by criteria."""

    def __init__(
        self,
        watchlist_provider: WatchlistProvider | None = None,
        metrics_provider: MarketMetricsProvider | None = None,
    ) -> None:
        self._watchlist = watchlist_provider
        self._metrics = metrics_provider

    @property
    def has_broker(self) -> bool:
        return self._watchlist is not None and self._metrics is not None

    def scan(
        self,
        filter_config: UniverseFilter | None = None,
        preset: str | None = None,
        save_watchlist: str | None = None,
    ) -> UniverseScanResult:
        """Scan the broker universe and return filtered candidates.

        Args:
            filter_config: Custom filter. Mutually exclusive with preset.
            preset: Named preset ("income", "directional", "high_vol", "broad").
            save_watchlist: If set, save results as a TastyTrade watchlist with this name.

        Returns:
            UniverseScanResult with filtered candidates and metadata.
        """
        if not self.has_broker:
            return UniverseScanResult(
                filter_used=preset or "custom",
                total_scanned=0,
                total_passed=0,
                candidates=[],
            )

        # Resolve filter
        if preset and preset in PRESETS:
            filt = PRESETS[preset]
            filter_name = preset
        elif filter_config:
            filt = filter_config
            filter_name = "custom"
        else:
            filt = UniverseFilter()
            filter_name = "default"

        # Phase 1: Get equity universe from broker
        logger.info("Phase 1: Fetching equity universe...")
        candidates = self._phase1_listings(filt)
        total_scanned = len(candidates)
        logger.info("Phase 1 complete: %d symbols after basic filters", total_scanned)

        if candidates:
            logger.info("Phase 2: Fetching market metrics in batches of %d...", _METRICS_BATCH_SIZE)
            candidates = self._phase2_metrics(candidates, filt)
            logger.info("Phase 2 complete: %d symbols passed all filters", len(candidates))

        # Add forced include tickers (bypass filters)
        forced: list[str] = []
        existing = {c.ticker for c in candidates}
        for t in filt.include_tickers:
            if t not in existing:
                candidates.append(UniverseCandidate(
                    ticker=t,
                    asset_type="forced",
                    filter_reason="include_tickers (forced)",
                ))
                forced.append(t)

        # Sort
        candidates = self._sort(candidates, filt.sort_by, filt.sort_descending)

        # Cap
        candidates = candidates[:filt.max_symbols]

        # Save watchlist if requested
        wl_name: str | None = None
        if save_watchlist and self._watchlist:
            tickers = [c.ticker for c in candidates]
            if self._watchlist.create_watchlist(save_watchlist, tickers):
                wl_name = save_watchlist
                logger.info("Saved watchlist '%s' with %d tickers", save_watchlist, len(tickers))

        return UniverseScanResult(
            filter_used=filter_name,
            total_scanned=total_scanned,
            total_passed=len(candidates),
            candidates=candidates,
            include_forced=forced,
            watchlist_saved=wl_name,
        )

    def _phase1_listings(self, filt: UniverseFilter) -> list[UniverseCandidate]:
        """Phase 1: Pull equity listings and apply basic filters."""
        assert self._watchlist is not None

        candidates: list[UniverseCandidate] = []
        exclude = set(filt.exclude_tickers)

        # Determine which asset types to fetch
        want_etf = AssetType.ETF in filt.asset_types
        want_equity = AssetType.EQUITY in filt.asset_types
        want_index = AssetType.INDEX in filt.asset_types

        if want_etf and not want_equity:
            # ETF-only: faster query
            raw = self._watchlist.get_all_equities(is_etf=True)
        elif want_index and not want_equity and not want_etf:
            raw = self._watchlist.get_all_equities(is_index=True)
        else:
            # Fetch all, filter locally
            raw = self._watchlist.get_all_equities()

        for eq in raw:
            sym = eq["symbol"]
            if sym in exclude:
                continue

            # Asset type filter
            is_etf = eq.get("is_etf", False)
            is_idx = eq.get("is_index", False)
            if is_etf:
                atype = AssetType.ETF
            elif is_idx:
                atype = AssetType.INDEX
            else:
                atype = AssetType.EQUITY

            if atype not in filt.asset_types:
                continue

            # Skip illiquid instruments
            if eq.get("is_illiquid", False):
                continue

            candidates.append(UniverseCandidate(
                ticker=sym,
                asset_type=atype.value,
            ))

        return candidates

    def _phase2_metrics(
        self,
        candidates: list[UniverseCandidate],
        filt: UniverseFilter,
    ) -> list[UniverseCandidate]:
        """Phase 2: Batch-fetch metrics, apply IV/liquidity/beta filters."""
        assert self._metrics is not None

        # Batch fetch
        symbols = [c.ticker for c in candidates]
        all_metrics: dict = {}

        for i in range(0, len(symbols), _METRICS_BATCH_SIZE):
            batch = symbols[i : i + _METRICS_BATCH_SIZE]
            try:
                batch_metrics = self._metrics.get_metrics(batch)
                all_metrics.update(batch_metrics)
            except Exception as e:
                logger.warning("Metrics batch failed (symbols %d-%d): %s", i, i + len(batch), e)

        # Apply filters
        passed: list[UniverseCandidate] = []
        today = date.today()

        for c in candidates:
            m = all_metrics.get(c.ticker)
            if m is None:
                continue  # No metrics = skip

            # Liquidity filter — reject if None when filter is active
            if filt.min_liquidity_rating:
                if m.liquidity_rating is None or m.liquidity_rating < filt.min_liquidity_rating:
                    continue

            # IV rank filters — reject if None when filter is active
            if filt.iv_rank_min is not None:
                if m.iv_rank is None or m.iv_rank < filt.iv_rank_min:
                    continue
            if filt.iv_rank_max is not None:
                if m.iv_rank is None or m.iv_rank > filt.iv_rank_max:
                    continue

            # IV percentile filters
            if filt.iv_percentile_min is not None:
                if m.iv_percentile is None or m.iv_percentile < filt.iv_percentile_min:
                    continue
            if filt.iv_percentile_max is not None:
                if m.iv_percentile is None or m.iv_percentile > filt.iv_percentile_max:
                    continue

            # Historical vol filters
            if filt.hv_30_day_min is not None:
                if m.hv_30_day is None or m.hv_30_day < filt.hv_30_day_min:
                    continue
            if filt.hv_30_day_max is not None:
                if m.hv_30_day is None or m.hv_30_day > filt.hv_30_day_max:
                    continue

            # IV-HV spread
            iv_hv_spread: float | None = None
            if m.iv_30_day is not None and m.hv_30_day is not None:
                iv_hv_spread = m.iv_30_day - m.hv_30_day
                if filt.iv_hv_spread_min is not None and iv_hv_spread < filt.iv_hv_spread_min:
                    continue

            # Beta filters
            if filt.beta_min is not None:
                if m.beta is None or m.beta < filt.beta_min:
                    continue
            if filt.beta_max is not None:
                if m.beta is None or m.beta > filt.beta_max:
                    continue

            # Earnings proximity filter
            if filt.exclude_earnings_within_days is not None and m.earnings_date is not None:
                days_to_earnings = (m.earnings_date - today).days
                if 0 <= days_to_earnings <= filt.exclude_earnings_within_days:
                    continue

            # Enrich candidate with metrics
            c.iv_rank = m.iv_rank
            c.iv_percentile = m.iv_percentile
            c.iv_index = m.iv_index
            c.hv_30_day = m.hv_30_day
            c.iv_hv_spread = iv_hv_spread
            c.beta = m.beta
            c.liquidity_rating = m.liquidity_rating
            c.earnings_date = str(m.earnings_date) if m.earnings_date else None

            passed.append(c)

        return passed

    @staticmethod
    def _sort(
        candidates: list[UniverseCandidate],
        sort_by: SortField,
        descending: bool,
    ) -> list[UniverseCandidate]:
        """Sort candidates by the specified field."""
        key_map = {
            SortField.IV_RANK: lambda c: c.iv_rank if c.iv_rank is not None else -1,
            SortField.LIQUIDITY: lambda c: c.liquidity_rating if c.liquidity_rating is not None else -1,
            SortField.BETA: lambda c: c.beta if c.beta is not None else -1,
            SortField.IV_HV_SPREAD: lambda c: c.iv_hv_spread if c.iv_hv_spread is not None else -1,
            SortField.MARKET_CAP: lambda c: c.market_cap if c.market_cap is not None else -1,
            SortField.VOLUME: lambda c: c.liquidity_rating if c.liquidity_rating is not None else -1,
        }
        key_fn = key_map.get(sort_by, key_map[SortField.IV_RANK])
        return sorted(candidates, key=key_fn, reverse=descending)
