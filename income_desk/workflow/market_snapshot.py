"""Market Snapshot — batch data fetching with rate-limit management.

eTrading sends all portfolio tickers at once. ID fetches prices, option
chains, IV, Greeks, and regime in a single coordinated operation with
proper Dhan rate limiting and timestamp consistency.
"""
from __future__ import annotations

import logging
import time as _time
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from income_desk.workflow._types import TickerSnapshot, TickerRegime, WorkflowMeta

if TYPE_CHECKING:
    from income_desk.service.analyzer import MarketAnalyzer

logger = logging.getLogger(__name__)


class SnapshotRequest(BaseModel):
    """Request for batch market data."""
    tickers: list[str]
    include_chains: bool = False  # option chains are slow (3.5s each)
    include_regime: bool = True
    market: str = "India"


class MarketSnapshot(BaseModel):
    """Complete market data for all requested tickers."""
    meta: WorkflowMeta
    tickers: dict[str, TickerSnapshot]
    regimes: dict[str, TickerRegime]
    timestamp: datetime  # single consistent timestamp


def snapshot_market(
    request: SnapshotRequest,
    ma: MarketAnalyzer,
) -> MarketSnapshot:
    """Fetch batch market data with rate-limit management.

    - Prices: batch call via Dhan ticker_data (all tickers in 1 API call)
    - Chains: sequential with 3.5s throttle (only if include_chains=True)
    - Regime: from cached OHLCV (no broker call)
    - Technicals: from cached OHLCV
    """
    timestamp = datetime.now()
    warnings: list[str] = []
    snapshots: dict[str, TickerSnapshot] = {}
    regimes: dict[str, TickerRegime] = {}
    data_source = "unknown"

    # Determine data source
    if ma.market_data is not None:
        data_source = getattr(ma.market_data, 'provider_name', 'broker')
    else:
        data_source = "yfinance"

    # --- Batch price fetch (2 API calls for ALL tickers) ---
    batch_prices: dict[str, float] = {}
    if ma.market_data is not None and hasattr(ma.market_data, "get_prices_batch"):
        try:
            batch_prices = ma.market_data.get_prices_batch(request.tickers)
        except Exception as e:
            warnings.append(f"Batch price fetch failed: {e}")

    for ticker in request.tickers:
        snap = TickerSnapshot(ticker=ticker)

        # Price from batch result (or fallback to individual)
        upper = ticker.upper()
        if upper in batch_prices:
            snap.price = batch_prices[upper]
        elif ma.market_data is not None:
            try:
                price = ma.market_data.get_underlying_price(ticker)
                if price and price > 0:
                    snap.price = price
            except Exception as e:
                warnings.append(f"{ticker}: price fetch failed: {e}")

        # Technicals (from OHLCV cache — no broker call)
        try:
            tech = ma.technicals.snapshot(ticker)
            if tech:
                snap.atr_pct = tech.atr_pct
                snap.rsi = getattr(tech.rsi, 'value', tech.rsi) if tech.rsi else None
                if snap.price is None and tech.current_price:
                    snap.price = tech.current_price
        except Exception as e:
            warnings.append(f"{ticker}: technicals failed: {e}")

        snapshots[ticker] = snap

    # --- Regime detection (from OHLCV — no broker call) ---
    if request.include_regime:
        regime_labels = {1: "R1 Low-Vol MR", 2: "R2 High-Vol MR", 3: "R3 Low-Vol Trend", 4: "R4 High-Vol Trend"}
        for ticker in request.tickers:
            try:
                r = ma.regime.detect(ticker)
                rid = r.regime if isinstance(r.regime, int) else r.regime.value
                regimes[ticker] = TickerRegime(
                    ticker=ticker,
                    regime_id=rid,
                    regime_label=regime_labels.get(rid, f"R{rid}"),
                    confidence=r.confidence,
                    tradeable=rid in (1, 2, 3),
                )
                snapshots[ticker].regime_id = rid
                snapshots[ticker].regime_label = regime_labels.get(rid, f"R{rid}")
                snapshots[ticker].regime_confidence = r.confidence
            except Exception as e:
                warnings.append(f"{ticker}: regime detection failed: {e}")

    # --- Option chains (slow — only if requested) ---
    if request.include_chains and ma.market_data is not None:
        for ticker in request.tickers:
            try:
                _time.sleep(3.5)  # Dhan rate limit
                chain = ma.market_data.get_option_chain(ticker)
                if chain:
                    snap = snapshots[ticker]
                    snap.chain_strikes = len(chain)
                    snap.chain_liquid = sum(1 for q in chain if (getattr(q, 'bid', 0) or 0) > 0)
                    snap.has_greeks = any(getattr(q, 'delta', None) is not None for q in chain)
                    snap.has_iv = any(getattr(q, 'implied_volatility', None) is not None for q in chain)

                    # Extract ATM IV
                    if snap.price and snap.price > 0:
                        atm = [q for q in chain if getattr(q, 'implied_volatility', None) and abs(q.strike - snap.price) / snap.price < 0.02]
                        if atm:
                            snap.iv_30d = sum(q.implied_volatility for q in atm) / len(atm)
            except Exception as e:
                warnings.append(f"{ticker}: chain fetch failed: {e}")

    # --- Metrics (IV rank) ---
    if ma.market_metrics is not None:
        try:
            metrics = ma.market_metrics.get_metrics(request.tickers)
            for ticker, m in metrics.items():
                if ticker in snapshots:
                    snapshots[ticker].iv_rank = m.iv_rank
                    if m.iv_30_day and snapshots[ticker].iv_30d is None:
                        snapshots[ticker].iv_30d = m.iv_30_day
        except Exception as e:
            warnings.append(f"Metrics fetch failed: {e}")

    return MarketSnapshot(
        meta=WorkflowMeta(
            as_of=timestamp,
            market=request.market,
            data_source=data_source,
            warnings=warnings,
        ),
        tickers=snapshots,
        regimes=regimes,
        timestamp=timestamp,
    )
