"""Cross-market correlation and lead-lag analysis.

US closes at 4:00 PM ET (= 1:30 AM IST next day). India opens at 9:15 AM IST.
There is a natural 7.75-hour gap where US closing behavior predicts India's
opening. This module computes correlation, lead-lag signals, and cross-market
regime synchronization.

All functions are pure computation -- accept OHLCV DataFrames, return analysis.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

import numpy as np
import pandas as pd
from pydantic import BaseModel


class MarketSyncStatus(StrEnum):
    """How synchronized two markets are."""

    SYNCHRONIZED = "synchronized"  # Same regime, same direction
    DIVERGENT = "divergent"  # Different regimes
    LEADING = "leading"  # Market A leading Market B
    LAGGING = "lagging"  # Market A lagging Market B


class CrossMarketSignal(BaseModel):
    """A signal from one market about what to expect in another."""

    source_market: str  # "US"
    target_market: str  # "INDIA"
    signal_type: str  # "gap_prediction", "regime_sync", "correlation"
    direction: str  # "bullish", "bearish", "neutral"
    strength: float  # 0.0-1.0
    description: str


class CrossMarketAnalysis(BaseModel):
    """Complete cross-market analysis between two markets."""

    source_market: str
    target_market: str
    as_of_date: date

    # Correlation
    correlation_20d: float  # Rolling 20-day return correlation
    correlation_60d: float  # Rolling 60-day return correlation

    # Lead-lag
    us_close_return_pct: float  # US last close return %
    predicted_india_gap_pct: float  # Expected India open gap %
    prediction_confidence: float  # How reliable the prediction is (R-squared)

    # Regime sync
    source_regime: int  # US regime (R1-R4)
    target_regime: int  # India regime (R1-R4)
    sync_status: MarketSyncStatus

    # Signals
    signals: list[CrossMarketSignal]

    # Summary
    summary: str
    commentary: list[str] = []


def compute_cross_market_correlation(
    source_ohlcv: pd.DataFrame,  # US OHLCV (e.g., SPY)
    target_ohlcv: pd.DataFrame,  # India OHLCV (e.g., NIFTY)
    window_short: int = 20,
    window_long: int = 60,
) -> tuple[float, float]:
    """Compute rolling return correlation between two markets.

    Returns (short_term_corr, long_term_corr).
    """
    # Daily returns
    src_returns = source_ohlcv["Close"].pct_change().dropna()
    tgt_returns = target_ohlcv["Close"].pct_change().dropna()

    # Align dates (may have different trading calendars)
    aligned = pd.concat([src_returns, tgt_returns], axis=1, join="inner")
    aligned.columns = ["source", "target"]
    aligned = aligned.dropna()

    if len(aligned) < window_short:
        return 0.0, 0.0

    # Short-term correlation
    short_corr = float(
        aligned["source"]
        .tail(window_short)
        .corr(aligned["target"].tail(window_short))
    )

    # Long-term correlation
    if len(aligned) >= window_long:
        long_corr = float(
            aligned["source"]
            .tail(window_long)
            .corr(aligned["target"].tail(window_long))
        )
    else:
        long_corr = short_corr

    return round(short_corr, 4), round(long_corr, 4)


def predict_gap(
    source_ohlcv: pd.DataFrame,
    target_ohlcv: pd.DataFrame,
    lookback: int = 60,
) -> tuple[float, float]:
    """Predict target market's next-day gap from source market's close.

    Uses linear regression of: target_next_open_return ~ source_close_return

    Returns (predicted_gap_pct, r_squared).
    """
    src_returns = source_ohlcv["Close"].pct_change().dropna()

    # Target: next-day open return = (open_t+1 - close_t) / close_t
    tgt_gap = (target_ohlcv["Open"].shift(-1) - target_ohlcv["Close"]) / target_ohlcv[
        "Close"
    ]
    tgt_gap = tgt_gap.dropna()

    # Align
    aligned = pd.concat([src_returns, tgt_gap], axis=1, join="inner")
    aligned.columns = ["source", "gap"]
    aligned = aligned.dropna().tail(lookback)

    if len(aligned) < 20:
        return 0.0, 0.0

    # Simple linear regression
    x = aligned["source"].values
    y = aligned["gap"].values

    x_mean = np.mean(x)
    y_mean = np.mean(y)

    ss_xy = float(np.sum((x - x_mean) * (y - y_mean)))
    ss_xx = float(np.sum((x - x_mean) ** 2))

    if ss_xx == 0:
        return 0.0, 0.0

    beta = ss_xy / ss_xx
    alpha = y_mean - beta * x_mean

    # Predicted gap from latest source return
    latest_src_return = float(src_returns.iloc[-1])
    predicted_gap = alpha + beta * latest_src_return

    # R-squared
    y_pred = alpha + beta * x
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y_mean) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    return round(float(predicted_gap) * 100, 3), round(max(0.0, float(r_squared)), 4)


def analyze_cross_market(
    source_ticker: str,
    target_ticker: str,
    source_ohlcv: pd.DataFrame,
    target_ohlcv: pd.DataFrame,
    source_regime_id: int,
    target_regime_id: int,
    source_market: str = "US",
    target_market: str = "INDIA",
) -> CrossMarketAnalysis:
    """Complete cross-market analysis between two markets."""
    today = date.today()

    # Correlation
    corr_20, corr_60 = compute_cross_market_correlation(source_ohlcv, target_ohlcv)

    # Lead-lag prediction
    predicted_gap, r_squared = predict_gap(source_ohlcv, target_ohlcv)

    # US last close return
    src_returns = source_ohlcv["Close"].pct_change()
    us_close_return = (
        float(src_returns.iloc[-1]) * 100 if len(src_returns) > 0 else 0.0
    )

    # Regime synchronization
    same_vol = (source_regime_id in (1, 3) and target_regime_id in (1, 3)) or (
        source_regime_id in (2, 4) and target_regime_id in (2, 4)
    )
    same_trend = (source_regime_id in (1, 2) and target_regime_id in (1, 2)) or (
        source_regime_id in (3, 4) and target_regime_id in (3, 4)
    )

    if same_vol and same_trend:
        sync = MarketSyncStatus.SYNCHRONIZED
    elif source_regime_id in (3, 4) and target_regime_id in (1, 2):
        sync = MarketSyncStatus.LEADING  # US trending, India hasn't caught up
    elif source_regime_id in (1, 2) and target_regime_id in (3, 4):
        sync = MarketSyncStatus.LAGGING  # US calm, India still trending
    else:
        sync = MarketSyncStatus.DIVERGENT

    # Build signals
    signals: list[CrossMarketSignal] = []

    # Gap prediction signal
    if abs(predicted_gap) > 0.3 and r_squared > 0.1:
        direction = "bullish" if predicted_gap > 0 else "bearish"
        signals.append(
            CrossMarketSignal(
                source_market=source_market,
                target_market=target_market,
                signal_type="gap_prediction",
                direction=direction,
                strength=min(abs(predicted_gap) / 2.0, 1.0),
                description=(
                    f"{target_market} expected to gap {predicted_gap:+.2f}% "
                    f"based on {source_market} close ({us_close_return:+.1f}%)"
                ),
            )
        )

    # Correlation strength signal
    if abs(corr_20) > 0.7:
        signals.append(
            CrossMarketSignal(
                source_market=source_market,
                target_market=target_market,
                signal_type="high_correlation",
                direction="neutral",
                strength=abs(corr_20),
                description=(
                    f"Strong 20-day correlation ({corr_20:.2f}) "
                    f"-- {target_market} moves with {source_market}"
                ),
            )
        )

    # Regime sync signal
    if sync == MarketSyncStatus.SYNCHRONIZED and source_regime_id in (3, 4):
        signals.append(
            CrossMarketSignal(
                source_market=source_market,
                target_market=target_market,
                signal_type="regime_sync_risk",
                direction="bearish",
                strength=0.8,
                description=(
                    f"Both markets in R{source_regime_id} "
                    f"-- correlated risk amplified"
                ),
            )
        )
    elif sync == MarketSyncStatus.LEADING:
        signals.append(
            CrossMarketSignal(
                source_market=source_market,
                target_market=target_market,
                signal_type="regime_lead",
                direction="bearish" if source_regime_id == 4 else "cautious",
                strength=0.6,
                description=(
                    f"{source_market} R{source_regime_id} leading "
                    f"-- {target_market} R{target_regime_id} may follow"
                ),
            )
        )

    # US crash -> India warning
    if us_close_return < -2.0:
        signals.append(
            CrossMarketSignal(
                source_market=source_market,
                target_market=target_market,
                signal_type="crash_warning",
                direction="bearish",
                strength=min(abs(us_close_return) / 5.0, 1.0),
                description=(
                    f"{source_market} closed {us_close_return:+.1f}% "
                    f"-- {target_market} likely gap-down at open"
                ),
            )
        )
    elif us_close_return > 2.0:
        signals.append(
            CrossMarketSignal(
                source_market=source_market,
                target_market=target_market,
                signal_type="rally_signal",
                direction="bullish",
                strength=min(abs(us_close_return) / 5.0, 1.0),
                description=(
                    f"{source_market} closed {us_close_return:+.1f}% "
                    f"-- {target_market} likely gap-up"
                ),
            )
        )

    # Summary
    parts = [
        f"Corr: {corr_20:.2f} (20d), {corr_60:.2f} (60d)",
        f"{source_market} close: {us_close_return:+.1f}%",
        f"Predicted {target_market} gap: {predicted_gap:+.2f}%",
        f"Regime sync: {sync.value} "
        f"({source_market}=R{source_regime_id}, "
        f"{target_market}=R{target_regime_id})",
    ]

    commentary = [
        f"Cross-market analysis: {source_ticker} ({source_market}) "
        f"-> {target_ticker} ({target_market})",
        f"Return correlation: {corr_20:.2f} (20d), {corr_60:.2f} (60d)",
        f"{source_market} last close: {us_close_return:+.2f}%",
        f"Linear model predicts {target_market} gap of "
        f"{predicted_gap:+.2f}% (R^2={r_squared:.2f})",
        f"Regime: {source_market}=R{source_regime_id}, "
        f"{target_market}=R{target_regime_id} -> {sync.value}",
    ]
    if signals:
        commentary.append(
            f"Signals: {', '.join(s.signal_type for s in signals)}"
        )

    return CrossMarketAnalysis(
        source_market=source_market,
        target_market=target_market,
        as_of_date=today,
        correlation_20d=corr_20,
        correlation_60d=corr_60,
        us_close_return_pct=round(us_close_return, 3),
        predicted_india_gap_pct=predicted_gap,
        prediction_confidence=r_squared,
        source_regime=source_regime_id,
        target_regime=target_regime_id,
        sync_status=sync,
        signals=signals,
        summary=" | ".join(parts),
        commentary=commentary,
    )
