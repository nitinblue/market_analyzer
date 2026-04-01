"""Snapshot service — build, save, and load instrument snapshots.

Pre-market: builds a complete snapshot with OI for all tradeable tickers.
Trading day: loads snapshot from disk — zero network calls for instrument data.

Usage::

    from income_desk.service.snapshot import SnapshotService

    svc = SnapshotService(market_data=md, registry=registry)
    snap = svc.build(["SPY", "QQQ", "GLD"], market="US")
    path = svc.save(snap)

    # Later (during trading):
    snap = SnapshotService.load(market="US")
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from income_desk.models.instrument_snapshot import (
    ExpiryInfo,
    InstrumentSnapshot,
    MarketSnapshot,
    StrikeInfo,
    classify_expiry,
    select_expiry_buckets,
)

if TYPE_CHECKING:
    from income_desk.broker.tastytrade.market_data import TastyTradeMarketData
    from income_desk.broker.tastytrade.session import TastyTradeBrokerSession
    from income_desk.registry import MarketRegistry

logger = logging.getLogger(__name__)


class SnapshotService:
    """Build, save, and load instrument snapshots.

    Pre-market: builds a complete snapshot with OI for all tradeable tickers.
    Trading day: loads snapshot from disk — zero network calls for instrument data.
    """

    SNAPSHOT_DIR = Path.home() / ".income_desk" / "snapshots"
    MIN_OI = 10  # minimum OI to consider a strike tradeable
    STRIKES_EACH_SIDE = 20  # configurable

    def __init__(
        self,
        market_data: TastyTradeMarketData | None = None,
        registry: MarketRegistry | None = None,
    ) -> None:
        self._market_data = market_data
        self._registry = registry
        self._session: TastyTradeBrokerSession | None = None

        if market_data is not None:
            # Store broker session for REST + DXLink calls
            self._session = market_data._session

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, tickers: list[str], market: str = "US") -> MarketSnapshot:
        """Build a full snapshot for all tickers. Pre-market only.

        For each ticker:
        1. REST: fetch all strikes/expiries via fetch_option_chain_rest
        2. Select expiry buckets (2-3 per bucket: 0dte, weekly, two_week, monthly, leap)
        3. For selected expiries, pick STRIKES_EACH_SIDE strikes each side of ATM
        4. DXLink Summary: fetch OI for those strikes
        5. Mark strikes as tradeable (OI >= MIN_OI or OI not available)
        6. Build InstrumentSnapshot
        """
        if self._session is None:
            raise RuntimeError(
                "SnapshotService.build() requires a broker connection. "
                "Pass market_data with an active TastyTrade session."
            )

        instruments: dict[str, InstrumentSnapshot] = {}
        for ticker in tickers:
            try:
                snap = self._build_single(ticker, market)
                instruments[ticker] = snap
            except Exception:
                logger.exception("Failed to build snapshot for %s — skipping", ticker)

        result = MarketSnapshot(
            instruments=instruments,
            market=market,  # type: ignore[arg-type]
            provider="tastytrade",
        )
        logger.info(
            "Snapshot complete: %d/%d tickers, market=%s",
            len(instruments), len(tickers), market,
        )
        return result

    def _build_single(self, ticker: str, market: str = "US") -> InstrumentSnapshot:
        """Build snapshot for one ticker."""
        from income_desk.broker.tastytrade._async import run_sync
        from income_desk.broker.tastytrade.dxlink import (
            fetch_option_chain_rest,
            fetch_summary,
        )

        assert self._session is not None  # enforced by build()

        # 1. REST: fetch full chain structure
        all_options = run_sync(
            fetch_option_chain_rest(self._session.sdk_session, ticker),
            timeout=30,
        )
        if not all_options:
            raise ValueError(f"No option chain data for {ticker}")

        # 2. Get underlying price for ATM centering
        underlying_price = self._market_data.get_underlying_price(ticker)  # type: ignore[union-attr]
        if not underlying_price or underlying_price <= 0:
            raise ValueError(
                f"Cannot get underlying price for {ticker} — "
                "needed for ATM centering"
            )

        # 3. Select expiry buckets
        today = date.today()
        all_expiries = sorted(
            {opt["expiration"] for opt in all_options if opt["expiration"] >= today}
        )
        selected_expiries = select_expiry_buckets(all_expiries, today, per_bucket=3)

        if not selected_expiries:
            raise ValueError(f"No future expiries found for {ticker}")

        # 4. For each selected expiry, pick STRIKES_EACH_SIDE strikes each side of ATM
        #    and collect streamer symbols for OI fetch
        expiry_strike_map: dict[date, list[dict]] = {}
        all_oi_symbols: list[str] = []

        for exp_date in selected_expiries:
            exp_options = [
                opt for opt in all_options if opt["expiration"] == exp_date
            ]
            if not exp_options:
                continue

            # Get unique strikes, sorted
            strikes = sorted({opt["strike"] for opt in exp_options})

            # Find ATM index
            atm_idx = min(
                range(len(strikes)),
                key=lambda i: abs(strikes[i] - underlying_price),
            )
            low_idx = max(0, atm_idx - self.STRIKES_EACH_SIDE)
            high_idx = min(len(strikes), atm_idx + self.STRIKES_EACH_SIDE + 1)
            selected_strikes = set(strikes[low_idx:high_idx])

            # Collect options for selected strikes
            selected_options = [
                opt for opt in exp_options if opt["strike"] in selected_strikes
            ]
            expiry_strike_map[exp_date] = selected_options
            all_oi_symbols.extend(opt["sym"] for opt in selected_options)

        # 5. DXLink Summary: fetch OI for all selected strikes
        oi_map: dict[str, int] = {}
        if all_oi_symbols:
            try:
                oi_map = run_sync(
                    fetch_summary(
                        self._session.data_session,
                        all_oi_symbols,
                        total_timeout=max(15.0, len(all_oi_symbols) * 0.1),
                    ),
                    timeout=60,
                )
                logger.info(
                    "%s: OI fetched for %d/%d symbols",
                    ticker, len(oi_map), len(all_oi_symbols),
                )
            except Exception:
                logger.exception(
                    "%s: OI fetch failed — marking all strikes as tradeable", ticker,
                )

        # 6. Build ExpiryInfo list
        expiries: list[ExpiryInfo] = []
        total_tradeable = 0

        for exp_date in selected_expiries:
            options = expiry_strike_map.get(exp_date, [])
            if not options:
                continue

            dte = (exp_date - today).days
            bucket = classify_expiry(exp_date, today)

            strikes_list: list[StrikeInfo] = []
            for opt in options:
                oi = oi_map.get(opt["sym"], -1)  # -1 means OI not available
                # Tradeable if OI >= threshold, or if OI data was unavailable
                is_tradeable = oi >= self.MIN_OI if oi >= 0 else True

                strikes_list.append(StrikeInfo(
                    strike=opt["strike"],
                    option_type=opt["option_type"],
                    streamer_symbol=opt["sym"],
                    open_interest=max(oi, 0),
                    is_tradeable=is_tradeable,
                ))
                if is_tradeable:
                    total_tradeable += 1

            expiries.append(ExpiryInfo(
                expiration=exp_date,
                dte=dte,
                bucket=bucket,
                strikes=strikes_list,
            ))

        # Lot size: registry first, then market default
        lot_size = self._resolve_lot_size(ticker, market)

        print(
            f"  {ticker}: ${underlying_price:.2f}, "
            f"{len(expiries)} expiries, "
            f"{total_tradeable} tradeable strikes"
        )

        return InstrumentSnapshot(
            ticker=ticker,
            underlying_price=underlying_price,
            lot_size=lot_size,
            expiries=expiries,
            snapshot_time=datetime.now(timezone.utc),
            provider="tastytrade",
        )

    # ------------------------------------------------------------------
    # Save / Load
    # ------------------------------------------------------------------

    def save(self, snapshot: MarketSnapshot) -> Path:
        """Save to ~/.income_desk/snapshots/{market}_{date}.json"""
        self.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

        today_str = date.today().isoformat()
        filename = f"{snapshot.market}_{today_str}.json"
        path = self.SNAPSHOT_DIR / filename

        path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Snapshot saved: %s (%d tickers)", path, len(snapshot.instruments))
        return path

    @classmethod
    def load(cls, market: str = "US", target_date: date | None = None) -> MarketSnapshot | None:
        """Load snapshot for a specific date. Returns None if not found or stale.

        Args:
            market: Market identifier ("US" or "India").
            target_date: Date to load (default: today).
        """
        if target_date is None:
            target_date = date.today()

        path = cls.SNAPSHOT_DIR / f"{market}_{target_date.isoformat()}.json"
        if not path.exists():
            logger.info("No snapshot file for %s on %s", market, target_date)
            return None

        try:
            raw = path.read_text(encoding="utf-8")
            snapshot = MarketSnapshot.model_validate_json(raw)
        except Exception:
            logger.exception("Failed to load snapshot from %s", path)
            return None

        if snapshot.is_stale():
            logger.warning(
                "Snapshot %s is stale (created %s) — returning None",
                path.name, snapshot.created_at,
            )
            return None

        logger.info(
            "Loaded snapshot: %s (%d tickers)",
            path.name, len(snapshot.instruments),
        )
        return snapshot

    @classmethod
    def load_latest(cls, market: str = "US") -> MarketSnapshot | None:
        """Load the most recent snapshot file regardless of date.

        Scans all files matching {market}_*.json, picks the most recent by
        filename (date-sorted), loads and returns it. Does NOT check staleness
        — caller decides whether to use a stale snapshot.
        """
        if not cls.SNAPSHOT_DIR.exists():
            return None

        files = sorted(
            cls.SNAPSHOT_DIR.glob(f"{market}_*.json"),
            reverse=True,
        )
        if not files:
            logger.info("No snapshot files found for market=%s", market)
            return None

        path = files[0]
        try:
            raw = path.read_text(encoding="utf-8")
            snapshot = MarketSnapshot.model_validate_json(raw)
        except Exception:
            logger.exception("Failed to load latest snapshot from %s", path)
            return None

        logger.info(
            "Loaded latest snapshot: %s (%d tickers, created %s)",
            path.name, len(snapshot.instruments), snapshot.created_at,
        )
        return snapshot

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_lot_size(self, ticker: str, market: str) -> int:
        """Resolve lot size: registry first, then market default."""
        if self._registry is not None:
            try:
                return self._registry.get_instrument(ticker).lot_size
            except KeyError:
                pass

        # Market defaults
        if market.upper() == "US":
            return 100
        return 1  # India default (caller should use registry for correct lot)
