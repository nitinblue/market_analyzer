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
    SignalStrength,
    TechnicalSignal,
)
from income_desk.features.patterns.candles import (
    compute_candlestick_patterns,
    detect_candlestick_patterns,
    generate_candlestick_signals,
    score_candlestick_patterns,
)


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


class TestDoubleBarDetection:
    def test_bullish_engulfing(self) -> None:
        bars = _downtrend_prefix() + [
            (97.0, 97.5, 96.0, 96.5, 100000),  # red bar
            (96.0, 98.0, 95.5, 98.0, 150000),   # green engulfs
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.BULLISH_ENGULFING in names

    def test_bearish_engulfing(self) -> None:
        bars = _uptrend_prefix() + [
            (103.0, 104.0, 102.5, 103.5, 100000),  # green bar
            (104.0, 104.5, 102.0, 102.0, 150000),   # red engulfs
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.BEARISH_ENGULFING in names

    def test_tweezer_bottom(self) -> None:
        bars = _downtrend_prefix() + [
            (97.0, 98.0, 95.00, 97.5, 100000),
            (97.5, 98.5, 95.00, 98.0, 120000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.TWEEZER_BOTTOM in names

    def test_tweezer_top(self) -> None:
        bars = _uptrend_prefix() + [
            (103.0, 105.00, 102.5, 104.5, 100000),
            (104.5, 105.00, 103.0, 103.5, 120000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.TWEEZER_TOP in names


class TestTripleBarDetection:
    def test_morning_star(self) -> None:
        bars = _downtrend_prefix() + [
            (97.0, 97.5, 95.0, 95.5, 100000),
            (95.5, 96.0, 95.0, 95.8, 80000),
            (96.0, 98.0, 95.5, 97.5, 130000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=4)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.MORNING_STAR in names

    def test_evening_star(self) -> None:
        bars = _uptrend_prefix() + [
            (103.0, 105.0, 102.5, 104.5, 100000),
            (104.5, 105.0, 104.0, 104.3, 80000),
            (104.0, 104.5, 102.0, 102.5, 130000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=4)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.EVENING_STAR in names

    def test_morning_doji_star(self) -> None:
        bars = _downtrend_prefix() + [
            (97.0, 97.5, 95.0, 95.5, 100000),
            (95.5, 96.0, 95.0, 95.52, 80000),
            (96.0, 98.0, 95.5, 97.5, 130000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=4)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.MORNING_DOJI_STAR in names

    def test_evening_doji_star(self) -> None:
        bars = _uptrend_prefix() + [
            (103.0, 105.0, 102.5, 104.5, 100000),
            (104.5, 105.0, 104.0, 104.52, 80000),
            (104.0, 104.5, 102.0, 102.5, 130000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=4)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.EVENING_DOJI_STAR in names

    def test_three_white_soldiers(self) -> None:
        bars = _flat_prefix() + [
            (100.0, 102.0, 99.8, 101.8, 100000),
            (101.0, 103.5, 100.8, 103.3, 110000),
            (102.0, 105.0, 101.8, 104.8, 120000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=4)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.THREE_WHITE_SOLDIERS in names

    def test_three_black_crows(self) -> None:
        bars = _flat_prefix() + [
            (102.0, 102.2, 100.0, 100.2, 100000),
            (101.0, 101.2, 99.0, 99.2, 110000),
            (100.0, 100.2, 98.0, 98.2, 120000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=4)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.THREE_BLACK_CROWS in names


class TestFiveBarDetection:
    def test_rising_three(self) -> None:
        # Bar0: strong bullish (body_pct ~0.78). Middle bars: small body (bp<0.33),
        # contained within bar0's range. Bar4: bullish close above bar0's close.
        bars = _flat_prefix() + [
            (100.0, 104.0, 99.5, 103.5, 150000),   # bar0: strong bull
            (103.0, 103.5, 101.0, 102.5, 80000),   # body=0.5, range=2.5, bp=0.20
            (102.5, 103.2, 100.5, 102.0, 70000),   # body=0.5, range=2.7, bp=0.19
            (102.0, 103.5, 100.0, 102.8, 75000),   # body=0.8, range=3.5, bp=0.23
            (103.0, 106.0, 102.5, 105.5, 160000),  # bar4: strong bull, c4 > c0
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=6)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.RISING_THREE in names

    def test_falling_three(self) -> None:
        # Bar0: strong bearish (body_pct ~0.78). Middle bars: small body (bp<0.33),
        # contained within bar0's range. Bar4: bearish close below bar0's close.
        bars = _flat_prefix() + [
            (104.0, 104.5, 100.0, 100.5, 150000),  # bar0: strong bear
            (101.0, 103.0, 100.5, 101.5, 80000),   # body=0.5, range=2.5, bp=0.20
            (101.5, 103.0, 100.5, 102.0, 70000),   # body=0.5, range=2.5, bp=0.20
            (102.0, 103.5, 100.5, 101.5, 75000),   # body=0.5, range=3.0, bp=0.17
            (101.0, 101.5, 98.0, 98.5, 160000),    # bar4: strong bear, c4 < c0
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=6)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.FALLING_THREE in names

    def test_rising_three_fails_if_middle_breaks_range(self) -> None:
        bars = _flat_prefix() + [
            (100.0, 104.0, 99.5, 103.5, 150000),
            (103.0, 105.0, 102.0, 102.5, 80000),  # breaks above h0=104
            (102.5, 103.0, 101.5, 102.0, 70000),
            (102.0, 103.3, 101.0, 102.8, 75000),
            (103.0, 106.0, 102.5, 105.5, 160000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=6)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.RISING_THREE not in names


class TestScoring:
    def test_scored_patterns_have_conviction(self) -> None:
        bars = _downtrend_prefix() + [
            (98.0, 98.5, 92.0, 98.2, 200000),
        ]
        df = _make_ohlcv(bars)
        raw = detect_candlestick_patterns(df, lookback_bars=3)
        scored = score_candlestick_patterns(df, raw)
        hammers = [p for p in scored if p.pattern == CandlePatternType.HAMMER]
        assert len(hammers) >= 1
        assert hammers[0].conviction > 0
        assert hammers[0].context != ""

    def test_high_volume_boosts_conviction(self) -> None:
        base = _downtrend_prefix()
        bars_low = base + [(98.0, 98.5, 92.0, 98.2, 50000)]
        bars_high = base + [(98.0, 98.5, 92.0, 98.2, 300000)]
        scored_low = score_candlestick_patterns(
            _make_ohlcv(bars_low),
            detect_candlestick_patterns(_make_ohlcv(bars_low), lookback_bars=3),
        )
        scored_high = score_candlestick_patterns(
            _make_ohlcv(bars_high),
            detect_candlestick_patterns(_make_ohlcv(bars_high), lookback_bars=3),
        )
        hammer_low = [p for p in scored_low if p.pattern == CandlePatternType.HAMMER]
        hammer_high = [p for p in scored_high if p.pattern == CandlePatternType.HAMMER]
        assert hammer_high[0].conviction > hammer_low[0].conviction


class TestConvenience:
    def test_compute_returns_summary(self) -> None:
        bars = _downtrend_prefix() + [
            (98.0, 98.5, 92.0, 98.2, 200000),
        ]
        df = _make_ohlcv(bars)
        summary = compute_candlestick_patterns(df)
        assert isinstance(summary, CandlePatternSummary)
        assert summary.bullish_count >= 1
        assert summary.strongest is not None

    def test_compute_filters_by_min_conviction(self) -> None:
        bars = _flat_prefix() + [
            (100.0, 100.5, 99.5, 100.2, 50000),
        ]
        df = _make_ohlcv(bars)
        summary = compute_candlestick_patterns(df)
        for p in summary.patterns:
            assert p.conviction >= 30


class TestSignalGeneration:
    def test_generates_signals(self) -> None:
        bars = _downtrend_prefix() + [
            (98.0, 98.5, 92.0, 98.2, 200000),
        ]
        df = _make_ohlcv(bars)
        summary = compute_candlestick_patterns(df)
        signals = generate_candlestick_signals(summary)
        assert isinstance(signals, list)
        if summary.patterns:
            assert len(signals) >= 1
            assert all(isinstance(s, TechnicalSignal) for s in signals)

    def test_none_summary_returns_empty(self) -> None:
        assert generate_candlestick_signals(None) == []

    def test_signal_strength_mapping(self) -> None:
        bars = _downtrend_prefix() + [
            (96.0, 98.0, 95.5, 98.0, 250000),
            (98.0, 98.5, 92.0, 98.2, 200000),
        ]
        df = _make_ohlcv(bars)
        summary = compute_candlestick_patterns(df)
        signals = generate_candlestick_signals(summary)
        for s in signals:
            assert s.strength in (SignalStrength.STRONG, SignalStrength.MODERATE, SignalStrength.WEAK)


class TestEdgeCases:
    def test_insufficient_data(self) -> None:
        df = _make_ohlcv([(100, 101, 99, 100, 1000)])
        patterns = detect_candlestick_patterns(df)
        assert isinstance(patterns, list)

    def test_empty_dataframe(self) -> None:
        df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        patterns = detect_candlestick_patterns(df)
        assert patterns == []

    def test_zero_range_bar_skipped(self) -> None:
        bars = _flat_prefix() + [(100.0, 100.0, 100.0, 100.0, 100000)]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=2)
        zero_bar_patterns = [p for p in patterns if p.bar_index == len(df) - 1]
        assert zero_bar_patterns == []

    def test_hammer_not_detected_without_downtrend(self) -> None:
        bars = _uptrend_prefix() + [
            (102.0, 102.5, 96.0, 102.2, 120000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.HAMMER not in names
        assert CandlePatternType.HANGING_MAN in names

    def test_compute_with_disabled_returns_empty(self) -> None:
        from income_desk.config import TechnicalsSettings
        settings = TechnicalsSettings(candle_enabled=False)
        bars = _downtrend_prefix() + [(98.0, 98.5, 92.0, 98.2, 200000)]
        df = _make_ohlcv(bars)
        summary = compute_candlestick_patterns(df, settings=settings)
        assert summary.patterns == []


class TestIntegration:
    def test_technical_snapshot_includes_candlestick(self) -> None:
        from income_desk.models.technicals import TechnicalSnapshot
        fields = TechnicalSnapshot.model_fields
        assert "candlestick_patterns" in fields

    def test_public_api_exports(self) -> None:
        from income_desk import CandlePattern, CandlePatternSummary, CandlePatternType
        assert CandlePatternType.HAMMER == "hammer"
