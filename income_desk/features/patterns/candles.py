"""Candlestick pattern detection and context scoring.

Two-layer design:
  - Layer 1: detect_candlestick_patterns() — pure geometric detection
  - Layer 2: score_candlestick_patterns() — context-based conviction scoring
  - Convenience: compute_candlestick_patterns() — detect + score + summarize
  - Signal bridge: generate_candlestick_signals() — for TechnicalSnapshot.signals

All functions accept OHLCV DataFrames with columns: Open, High, Low, Close, Volume.
Timeframe-agnostic — works on any bar size.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from income_desk.config import TechnicalsSettings, get_settings
from income_desk.models.technicals import (
    CandlePattern,
    CandlePatternSummary,
    CandlePatternType,
    SignalDirection,
    SignalStrength,
    TechnicalSignal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _body(o: float, c: float) -> float:
    return abs(c - o)


def _range(h: float, l: float) -> float:
    return h - l


def _upper_wick(o: float, h: float, c: float) -> float:
    return h - max(o, c)


def _lower_wick(o: float, l: float, c: float) -> float:
    return min(o, c) - l


def _is_bullish(o: float, c: float) -> bool:
    return c > o


def _is_bearish(o: float, c: float) -> bool:
    return c < o


def _body_pct(o: float, h: float, l: float, c: float) -> float:
    """Body as fraction of total range. Returns 0.0 if range is zero."""
    r = _range(h, l)
    if r == 0:
        return 0.0
    return _body(o, c) / r


def _detect_trend(closes: pd.Series) -> SignalDirection:
    """Simple trend detection from a series of close prices."""
    n = len(closes)
    if n < 3:
        return SignalDirection.NEUTRAL
    mid = n // 2
    first_avg = closes.iloc[:mid].mean()
    second_avg = closes.iloc[mid:].mean()
    diff_pct = (second_avg - first_avg) / first_avg if first_avg != 0 else 0
    if diff_pct > 0.005:
        return SignalDirection.BULLISH
    elif diff_pct < -0.005:
        return SignalDirection.BEARISH
    return SignalDirection.NEUTRAL


# ---------------------------------------------------------------------------
# Layer 1: Detection
# ---------------------------------------------------------------------------

def detect_candlestick_patterns(
    ohlcv: pd.DataFrame,
    *,
    lookback_bars: int = 10,
    settings: TechnicalsSettings | None = None,
) -> list[CandlePattern]:
    """Detect raw candlestick patterns in the last N bars.

    Args:
        ohlcv: DataFrame with columns: Open, High, Low, Close, Volume.
        lookback_bars: How many recent bars to scan.
        settings: Override default thresholds.

    Returns:
        List of CandlePattern with conviction=0 (unscored).
    """
    if settings is None:
        settings = get_settings().technicals

    if len(ohlcv) < 2:
        return []

    doji_pct = settings.candle_body_doji_pct
    small_pct = settings.candle_body_small_pct
    wick_mult = settings.candle_wick_multiplier
    trend_lb = settings.candle_trend_lookback
    tweezer_tol = settings.candle_tweezer_tolerance_pct

    patterns: list[CandlePattern] = []
    start = max(0, len(ohlcv) - lookback_bars)

    for i in range(start, len(ohlcv)):
        row = ohlcv.iloc[i]
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        r = _range(h, l)
        if r == 0:
            continue

        bp = _body_pct(o, h, l, c)
        bd = _body(o, c)
        uw = _upper_wick(o, h, c)
        lw = _lower_wick(o, l, c)

        bar_date = ohlcv.index[i]
        bar_date_val = bar_date.date() if hasattr(bar_date, "date") else bar_date

        # Prior trend
        trend_start = max(0, i - trend_lb)
        trend = _detect_trend(ohlcv["Close"].iloc[trend_start:i])

        # --- Single-bar patterns ---
        patterns.extend(
            _detect_single(i, bar_date_val, o, h, l, c, r, bp, bd, uw, lw, trend, doji_pct, small_pct, wick_mult)
        )

        # --- Double-bar patterns ---
        if i >= 1:
            prev = ohlcv.iloc[i - 1]
            patterns.extend(
                _detect_double(i, bar_date_val, o, h, l, c, prev, trend, tweezer_tol)
            )

        # --- Triple-bar patterns ---
        if i >= 2:
            bar1 = ohlcv.iloc[i - 2]
            bar2 = ohlcv.iloc[i - 1]
            patterns.extend(
                _detect_triple(i, bar_date_val, o, h, l, c, bar1, bar2, trend, doji_pct, small_pct)
            )

        # --- Five-bar patterns ---
        if i >= 4:
            five = [ohlcv.iloc[i - j] for j in range(4, -1, -1)]
            patterns.extend(
                _detect_five(i, bar_date_val, five, small_pct)
            )

    return patterns


def _detect_single(
    idx: int, bar_date, o: float, h: float, l: float, c: float,
    r: float, bp: float, bd: float, uw: float, lw: float,
    trend: SignalDirection,
    doji_pct: float, small_pct: float, wick_mult: float,
) -> list[CandlePattern]:
    """Detect single-bar patterns."""
    results: list[CandlePattern] = []
    bd_safe = max(bd, 1e-10)

    is_doji = bp < doji_pct
    is_small_body = bp < small_pct
    has_long_lower = lw >= r * 0.6
    has_long_upper = uw >= r * 0.6

    # Hammer shape: small body at top, long lower wick, short upper wick
    is_hammer_shape = is_small_body and has_long_lower and uw < r * 0.15

    # Inverted hammer shape: small body at bottom, long upper wick, short lower wick
    is_inv_hammer_shape = is_small_body and has_long_upper and lw < r * 0.15

    if is_hammer_shape:
        if trend == SignalDirection.BEARISH:
            results.append(CandlePattern(
                pattern=CandlePatternType.HAMMER,
                direction=SignalDirection.BULLISH,
                bar_index=idx, bar_date=bar_date, bars_involved=1,
            ))
        elif trend == SignalDirection.BULLISH:
            results.append(CandlePattern(
                pattern=CandlePatternType.HANGING_MAN,
                direction=SignalDirection.BEARISH,
                bar_index=idx, bar_date=bar_date, bars_involved=1,
            ))

    if is_inv_hammer_shape:
        if trend == SignalDirection.BEARISH:
            results.append(CandlePattern(
                pattern=CandlePatternType.INVERTED_HAMMER,
                direction=SignalDirection.BULLISH,
                bar_index=idx, bar_date=bar_date, bars_involved=1,
            ))
        elif trend == SignalDirection.BULLISH:
            results.append(CandlePattern(
                pattern=CandlePatternType.SHOOTING_STAR,
                direction=SignalDirection.BEARISH,
                bar_index=idx, bar_date=bar_date, bars_involved=1,
            ))

    # Dragonfly Doji: doji with negligible upper wick, long lower wick
    if is_doji and uw < r * 0.1 and lw > r * 0.6:
        results.append(CandlePattern(
            pattern=CandlePatternType.DRAGONFLY_DOJI,
            direction=SignalDirection.BULLISH,
            bar_index=idx, bar_date=bar_date, bars_involved=1,
        ))
    elif is_doji:
        results.append(CandlePattern(
            pattern=CandlePatternType.DOJI,
            direction=SignalDirection.NEUTRAL,
            bar_index=idx, bar_date=bar_date, bars_involved=1,
        ))

    # Spinning Top: body 10-33% of range, wicks on both sides
    if not is_doji and small_pct >= bp > doji_pct and uw > r * 0.15 and lw > r * 0.15:
        results.append(CandlePattern(
            pattern=CandlePatternType.SPINNING_TOP,
            direction=SignalDirection.NEUTRAL,
            bar_index=idx, bar_date=bar_date, bars_involved=1,
        ))

    return results


def _detect_double(
    idx: int, bar_date, o: float, h: float, l: float, c: float,
    prev: pd.Series, trend: SignalDirection, tweezer_tol: float,
) -> list[CandlePattern]:
    """Detect double-bar patterns."""
    results: list[CandlePattern] = []
    po, ph, pl, pc = float(prev["Open"]), float(prev["High"]), float(prev["Low"]), float(prev["Close"])

    curr_body_lo = min(o, c)
    curr_body_hi = max(o, c)
    prev_body_lo = min(po, pc)
    prev_body_hi = max(po, pc)

    # Bullish Engulfing
    if _is_bearish(po, pc) and _is_bullish(o, c):
        if curr_body_lo <= prev_body_lo and curr_body_hi >= prev_body_hi:
            results.append(CandlePattern(
                pattern=CandlePatternType.BULLISH_ENGULFING,
                direction=SignalDirection.BULLISH,
                bar_index=idx, bar_date=bar_date, bars_involved=2,
            ))

    # Bearish Engulfing
    if _is_bullish(po, pc) and _is_bearish(o, c):
        if curr_body_lo <= prev_body_lo and curr_body_hi >= prev_body_hi:
            results.append(CandlePattern(
                pattern=CandlePatternType.BEARISH_ENGULFING,
                direction=SignalDirection.BEARISH,
                bar_index=idx, bar_date=bar_date, bars_involved=2,
            ))

    # Tweezer Bottom
    if trend == SignalDirection.BEARISH:
        avg_price = (l + pl) / 2
        if avg_price > 0 and abs(l - pl) / avg_price <= tweezer_tol:
            results.append(CandlePattern(
                pattern=CandlePatternType.TWEEZER_BOTTOM,
                direction=SignalDirection.BULLISH,
                bar_index=idx, bar_date=bar_date, bars_involved=2,
            ))

    # Tweezer Top
    if trend == SignalDirection.BULLISH:
        avg_price = (h + ph) / 2
        if avg_price > 0 and abs(h - ph) / avg_price <= tweezer_tol:
            results.append(CandlePattern(
                pattern=CandlePatternType.TWEEZER_TOP,
                direction=SignalDirection.BEARISH,
                bar_index=idx, bar_date=bar_date, bars_involved=2,
            ))

    return results


def _detect_triple(
    idx: int, bar_date,
    o3: float, h3: float, l3: float, c3: float,
    bar1: pd.Series, bar2: pd.Series,
    trend: SignalDirection,
    doji_pct: float, small_pct: float,
) -> list[CandlePattern]:
    """Detect triple-bar patterns."""
    results: list[CandlePattern] = []
    o1, h1, l1, c1 = float(bar1["Open"]), float(bar1["High"]), float(bar1["Low"]), float(bar1["Close"])
    o2, h2, l2, c2 = float(bar2["Open"]), float(bar2["High"]), float(bar2["Low"]), float(bar2["Close"])

    r2 = _range(h2, l2)
    bp2 = _body_pct(o2, h2, l2, c2) if r2 > 0 else 0

    mid1 = (o1 + c1) / 2

    is_doji2 = bp2 < doji_pct
    is_small2 = bp2 < small_pct

    # Morning Star / Morning Doji Star
    if _is_bearish(o1, c1) and is_small2 and _is_bullish(o3, c3) and c3 > mid1:
        if is_doji2:
            results.append(CandlePattern(
                pattern=CandlePatternType.MORNING_DOJI_STAR,
                direction=SignalDirection.BULLISH,
                bar_index=idx, bar_date=bar_date, bars_involved=3,
            ))
        else:
            results.append(CandlePattern(
                pattern=CandlePatternType.MORNING_STAR,
                direction=SignalDirection.BULLISH,
                bar_index=idx, bar_date=bar_date, bars_involved=3,
            ))

    # Evening Star / Evening Doji Star
    if _is_bullish(o1, c1) and is_small2 and _is_bearish(o3, c3) and c3 < mid1:
        if is_doji2:
            results.append(CandlePattern(
                pattern=CandlePatternType.EVENING_DOJI_STAR,
                direction=SignalDirection.BEARISH,
                bar_index=idx, bar_date=bar_date, bars_involved=3,
            ))
        else:
            results.append(CandlePattern(
                pattern=CandlePatternType.EVENING_STAR,
                direction=SignalDirection.BEARISH,
                bar_index=idx, bar_date=bar_date, bars_involved=3,
            ))

    # Three White Soldiers
    if (
        _is_bullish(o1, c1) and _is_bullish(o2, c2) and _is_bullish(o3, c3)
        and c2 > c1 and c3 > c2
        and o2 > o1 and o3 > o2
    ):
        uw1 = _upper_wick(o1, h1, c1)
        uw2 = _upper_wick(o2, h2, c2)
        uw3 = _upper_wick(o3, h3, c3)
        b1, b2, b3 = _body(o1, c1), _body(o2, c2), _body(o3, c3)
        if b1 > 0 and b2 > 0 and b3 > 0:
            if uw1 < b1 * 0.5 and uw2 < b2 * 0.5 and uw3 < b3 * 0.5:
                results.append(CandlePattern(
                    pattern=CandlePatternType.THREE_WHITE_SOLDIERS,
                    direction=SignalDirection.BULLISH,
                    bar_index=idx, bar_date=bar_date, bars_involved=3,
                ))

    # Three Black Crows
    if (
        _is_bearish(o1, c1) and _is_bearish(o2, c2) and _is_bearish(o3, c3)
        and c2 < c1 and c3 < c2
        and o2 < o1 and o3 < o2
    ):
        lw1 = _lower_wick(o1, l1, c1)
        lw2 = _lower_wick(o2, l2, c2)
        lw3 = _lower_wick(o3, l3, c3)
        b1, b2, b3 = _body(o1, c1), _body(o2, c2), _body(o3, c3)
        if b1 > 0 and b2 > 0 and b3 > 0:
            if lw1 < b1 * 0.5 and lw2 < b2 * 0.5 and lw3 < b3 * 0.5:
                results.append(CandlePattern(
                    pattern=CandlePatternType.THREE_BLACK_CROWS,
                    direction=SignalDirection.BEARISH,
                    bar_index=idx, bar_date=bar_date, bars_involved=3,
                ))

    return results


def _detect_five(
    idx: int, bar_date,
    bars: list[pd.Series], small_pct: float,
) -> list[CandlePattern]:
    """Detect five-bar patterns (Rising Three, Falling Three)."""
    results: list[CandlePattern] = []

    b0, b4 = bars[0], bars[4]
    o0, h0, l0, c0 = float(b0["Open"]), float(b0["High"]), float(b0["Low"]), float(b0["Close"])
    o4, h4, l4, c4 = float(b4["Open"]), float(b4["High"]), float(b4["Low"]), float(b4["Close"])

    # Rising Three
    if _is_bullish(o0, c0) and _is_bullish(o4, c4) and _body_pct(o0, h0, l0, c0) > 0.5:
        middle_ok = True
        for j in range(1, 4):
            bj = bars[j]
            oj, hj, lj, cj = float(bj["Open"]), float(bj["High"]), float(bj["Low"]), float(bj["Close"])
            rj = _range(hj, lj)
            bpj = _body_pct(oj, hj, lj, cj) if rj > 0 else 0
            if bpj > small_pct or hj > h0 or lj < l0:
                middle_ok = False
                break
        if middle_ok and c4 > c0:
            results.append(CandlePattern(
                pattern=CandlePatternType.RISING_THREE,
                direction=SignalDirection.BULLISH,
                bar_index=idx, bar_date=bar_date, bars_involved=5,
            ))

    # Falling Three
    if _is_bearish(o0, c0) and _is_bearish(o4, c4) and _body_pct(o0, h0, l0, c0) > 0.5:
        middle_ok = True
        for j in range(1, 4):
            bj = bars[j]
            oj, hj, lj, cj = float(bj["Open"]), float(bj["High"]), float(bj["Low"]), float(bj["Close"])
            rj = _range(hj, lj)
            bpj = _body_pct(oj, hj, lj, cj) if rj > 0 else 0
            if bpj > small_pct or hj > h0 or lj < l0:
                middle_ok = False
                break
        if middle_ok and c4 < c0:
            results.append(CandlePattern(
                pattern=CandlePatternType.FALLING_THREE,
                direction=SignalDirection.BEARISH,
                bar_index=idx, bar_date=bar_date, bars_involved=5,
            ))

    return results
