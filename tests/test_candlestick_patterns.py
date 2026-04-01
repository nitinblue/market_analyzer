"""Tests for candlestick pattern detection."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from income_desk.models.technicals import (
    CandlePattern,
    CandlePatternSummary,
    CandlePatternType,
    SignalDirection,
)
from income_desk.features.patterns.candles import detect_candlestick_patterns


class TestCandleModels:
    def test_candle_pattern_type_has_all_19(self) -> None:
        assert len(CandlePatternType) == 19

    def test_candle_pattern_creation(self) -> None:
        p = CandlePattern(
            pattern=CandlePatternType.HAMMER,
            direction=SignalDirection.BULLISH,
            bar_index=5,
            bar_date=date(2026, 3, 31),
            bars_involved=1,
        )
        assert p.conviction == 0
        assert p.context == ""

    def test_candle_pattern_summary_defaults(self) -> None:
        s = CandlePatternSummary()
        assert s.patterns == []
        assert s.bullish_count == 0
        assert s.strongest is None


# ---------------------------------------------------------------------------
# Helpers for detection tests
# ---------------------------------------------------------------------------


def _make_ohlcv(
    bars: list[tuple[float, float, float, float, int]],
) -> pd.DataFrame:
    """Build OHLCV DataFrame from (open, high, low, close, volume) tuples."""
    df = pd.DataFrame(bars, columns=["Open", "High", "Low", "Close", "Volume"])
    df.index = pd.date_range("2026-03-20", periods=len(bars), freq="B")
    return df


def _downtrend_prefix(n: int = 6) -> list[tuple[float, float, float, float, int]]:
    """Generate N bars of a clear downtrend."""
    bars = []
    price = 110.0
    for i in range(n):
        o = price
        h = price + 0.5
        l = price - 2.5
        c = price - 2.0
        bars.append((o, h, l, c, 100000))
        price = c
    return bars


def _uptrend_prefix(n: int = 6) -> list[tuple[float, float, float, float, int]]:
    """Generate N bars of a clear uptrend."""
    bars = []
    price = 90.0
    for i in range(n):
        o = price
        h = price + 2.5
        l = price - 0.5
        c = price + 2.0
        bars.append((o, h, l, c, 100000))
        price = c
    return bars


def _flat_prefix(n: int = 6) -> list[tuple[float, float, float, float, int]]:
    """Generate N bars of flat/sideways movement."""
    bars = []
    price = 100.0
    for i in range(n):
        o = price
        h = price + 0.3
        l = price - 0.3
        c = price + 0.1 * ((-1) ** i)
        bars.append((o, h, l, c, 100000))
    return bars


class TestSingleBarDetection:
    def test_hammer(self) -> None:
        bars = _downtrend_prefix() + [
            (98.0, 98.5, 92.0, 98.2, 120000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.HAMMER in names

    def test_inverted_hammer(self) -> None:
        bars = _downtrend_prefix() + [
            (92.0, 98.0, 91.5, 92.3, 120000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.INVERTED_HAMMER in names

    def test_hanging_man(self) -> None:
        bars = _uptrend_prefix() + [
            (102.0, 102.5, 96.0, 102.2, 120000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.HANGING_MAN in names

    def test_shooting_star(self) -> None:
        bars = _uptrend_prefix() + [
            (102.0, 108.0, 101.5, 102.3, 120000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.SHOOTING_STAR in names

    def test_doji(self) -> None:
        bars = _flat_prefix() + [
            (100.0, 101.5, 98.5, 100.1, 100000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.DOJI in names

    def test_dragonfly_doji(self) -> None:
        bars = _flat_prefix() + [
            (100.0, 100.1, 95.0, 100.05, 100000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.DRAGONFLY_DOJI in names

    def test_spinning_top(self) -> None:
        bars = _flat_prefix() + [
            (100.0, 102.0, 98.0, 100.8, 100000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.SPINNING_TOP in names
