"""Tests for candlestick pattern detection."""
from __future__ import annotations

from datetime import date

import pytest

from income_desk.models.technicals import (
    CandlePattern,
    CandlePatternSummary,
    CandlePatternType,
    SignalDirection,
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
