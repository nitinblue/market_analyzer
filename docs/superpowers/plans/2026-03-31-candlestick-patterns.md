# Candlestick Pattern Detection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect 19 classical candlestick patterns from OHLCV data, score by context, wire into TechnicalSnapshot.

**Architecture:** Two-layer design — Layer 1 detects raw geometric patterns, Layer 2 adds conviction scoring with context. Both layers are independently callable. Integrated into `compute_technicals()` via the same pattern as VCP/Smart Money.

**Tech Stack:** Python 3.12, pandas, numpy, pydantic. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-03-31-candlestick-patterns-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `income_desk/models/technicals.py` | Modify | Add `CandlePatternType`, `CandlePattern`, `CandlePatternSummary` models; add field to `TechnicalSnapshot` |
| `income_desk/config/__init__.py` | Modify | Add `candle_*` flat fields to `TechnicalsSettings` |
| `income_desk/features/patterns/candles.py` | Create | All detection, scoring, signal generation functions |
| `income_desk/features/patterns/__init__.py` | Modify | Export new functions |
| `income_desk/features/technicals.py` | Modify | Wire candlestick computation + signals into `compute_technicals()` |
| `income_desk/cli/interactive.py` | Modify | Add `do_candles` command |
| `income_desk/__init__.py` | Modify | Export new public symbols |
| `tests/test_candlestick_patterns.py` | Create | All tests |

---

### Task 1: Models — CandlePatternType, CandlePattern, CandlePatternSummary

**Files:**
- Modify: `income_desk/models/technicals.py:278-310`
- Test: `tests/test_candlestick_patterns.py` (new)

- [ ] **Step 1: Write failing test for model instantiation**

Create `tests/test_candlestick_patterns.py`:

```python
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
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `.venv_312/Scripts/python -m pytest tests/test_candlestick_patterns.py::TestCandleModels -v`
Expected: FAIL — `CandlePatternType` not found

- [ ] **Step 3: Add models to technicals.py**

In `income_desk/models/technicals.py`, insert before `class TechnicalSnapshot` (before line 285):

```python
class CandlePatternType(StrEnum):
    """Classical candlestick pattern types."""
    # Single-bar (7)
    HAMMER = "hammer"
    INVERTED_HAMMER = "inverted_hammer"
    HANGING_MAN = "hanging_man"
    SHOOTING_STAR = "shooting_star"
    DOJI = "doji"
    DRAGONFLY_DOJI = "dragonfly_doji"
    SPINNING_TOP = "spinning_top"
    # Double-bar (4)
    BULLISH_ENGULFING = "bullish_engulfing"
    BEARISH_ENGULFING = "bearish_engulfing"
    TWEEZER_BOTTOM = "tweezer_bottom"
    TWEEZER_TOP = "tweezer_top"
    # Triple-bar (6)
    MORNING_STAR = "morning_star"
    EVENING_STAR = "evening_star"
    MORNING_DOJI_STAR = "morning_doji_star"
    EVENING_DOJI_STAR = "evening_doji_star"
    THREE_WHITE_SOLDIERS = "three_white_soldiers"
    THREE_BLACK_CROWS = "three_black_crows"
    # Five-bar (2)
    RISING_THREE = "rising_three"
    FALLING_THREE = "falling_three"


class CandlePattern(BaseModel):
    """A single detected candlestick pattern."""
    pattern: CandlePatternType
    direction: SignalDirection          # bullish / bearish / neutral
    bar_index: int                      # DataFrame iloc where pattern completes
    bar_date: date
    conviction: int = 0                 # 0-100, filled by scorer
    context: str = ""                   # human-readable explanation
    bars_involved: int                  # 1, 2, 3, or 5


class CandlePatternSummary(BaseModel):
    """Aggregated candlestick pattern result for TechnicalSnapshot."""
    patterns: list[CandlePattern] = []
    bullish_count: int = 0
    bearish_count: int = 0
    strongest: CandlePattern | None = None
    timeframe: str = "daily"
```

Then add to `TechnicalSnapshot` (after `daily_vwap` field, before `signals`):

```python
    candlestick_patterns: CandlePatternSummary | None = None
```

- [ ] **Step 4: Run test — expect PASS**

Run: `.venv_312/Scripts/python -m pytest tests/test_candlestick_patterns.py::TestCandleModels -v`
Expected: 3 PASS

- [ ] **Step 5: Run full test suite to verify no regression**

Run: `.venv_312/Scripts/python -m pytest tests/ -x -q`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add income_desk/models/technicals.py tests/test_candlestick_patterns.py
git commit -m "feat: candlestick pattern models — CandlePatternType (19), CandlePattern, CandlePatternSummary"
```

---

### Task 2: Config — candle_* settings on TechnicalsSettings

**Files:**
- Modify: `income_desk/config/__init__.py:99-129`

- [ ] **Step 1: Add candle_* fields to TechnicalsSettings**

In `income_desk/config/__init__.py`, add after the last `fvg_*` field (after `fvg_max_gaps`):

```python
    # Candlestick pattern settings
    candle_enabled: bool = True
    candle_lookback_bars: int = 10
    candle_body_doji_pct: float = 0.10
    candle_body_small_pct: float = 0.33
    candle_wick_multiplier: float = 2.0
    candle_trend_lookback: int = 5
    candle_volume_avg_period: int = 20
    candle_min_conviction: int = 30
    candle_tweezer_tolerance_pct: float = 0.001
    candle_timeframe: str = "daily"
```

- [ ] **Step 2: Verify settings load**

Run: `.venv_312/Scripts/python -c "from income_desk.config import TechnicalsSettings; s = TechnicalsSettings(); print(f'candle_enabled={s.candle_enabled}, lookback={s.candle_lookback_bars}')"`
Expected: `candle_enabled=True, lookback=10`

- [ ] **Step 3: Run full test suite**

Run: `.venv_312/Scripts/python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add income_desk/config/__init__.py
git commit -m "feat: candle_* settings on TechnicalsSettings"
```

---

### Task 3: Detection — Single-bar patterns (7 patterns)

**Files:**
- Create: `income_desk/features/patterns/candles.py`
- Test: `tests/test_candlestick_patterns.py`

- [ ] **Step 1: Write failing tests for all 7 single-bar patterns**

Add to `tests/test_candlestick_patterns.py`:

```python
import numpy as np
import pandas as pd

from income_desk.features.patterns.candles import detect_candlestick_patterns


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
        # Downtrend, then hammer: small body at top, long lower wick
        bars = _downtrend_prefix() + [
            (98.0, 98.5, 92.0, 98.2, 120000),  # body ~0.2, range 6.5, lower wick 6.0
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.HAMMER in names

    def test_inverted_hammer(self) -> None:
        # Downtrend, then inverted hammer: small body at bottom, long upper wick
        bars = _downtrend_prefix() + [
            (92.0, 98.0, 91.5, 92.3, 120000),  # body ~0.3, upper wick 5.7
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.INVERTED_HAMMER in names

    def test_hanging_man(self) -> None:
        # Uptrend, then hammer shape = hanging man (bearish)
        bars = _uptrend_prefix() + [
            (102.0, 102.5, 96.0, 102.2, 120000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.HANGING_MAN in names

    def test_shooting_star(self) -> None:
        # Uptrend, then inverted hammer shape = shooting star (bearish)
        bars = _uptrend_prefix() + [
            (102.0, 108.0, 101.5, 102.3, 120000),
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.SHOOTING_STAR in names

    def test_doji(self) -> None:
        bars = _flat_prefix() + [
            (100.0, 101.5, 98.5, 100.1, 100000),  # body 0.1, range 3.0
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.DOJI in names

    def test_dragonfly_doji(self) -> None:
        bars = _flat_prefix() + [
            (100.0, 100.1, 95.0, 100.05, 100000),  # body ~0.05, upper wick ~0.1, lower 5.0
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.DRAGONFLY_DOJI in names

    def test_spinning_top(self) -> None:
        bars = _flat_prefix() + [
            (100.0, 102.0, 98.0, 100.8, 100000),  # body 0.8, range 4.0 = 20% body
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.SPINNING_TOP in names
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `.venv_312/Scripts/python -m pytest tests/test_candlestick_patterns.py::TestSingleBarDetection -v`
Expected: FAIL — `candles` module not found

- [ ] **Step 3: Implement candles.py with single-bar detection**

Create `income_desk/features/patterns/candles.py`:

```python
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
    """Simple trend detection from a series of close prices.

    Compares first half average to second half average.
    """
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

    Pure geometric detection. No conviction scoring.

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
        o, h, l, c, v = row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
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
            _detect_single(
                i, bar_date_val, o, h, l, c, r, bp, bd, uw, lw, trend,
                doji_pct, small_pct, wick_mult,
            )
        )

        # --- Double-bar patterns ---
        if i >= 1:
            prev = ohlcv.iloc[i - 1]
            patterns.extend(
                _detect_double(
                    i, bar_date_val, o, h, l, c, prev, trend, tweezer_tol,
                )
            )

        # --- Triple-bar patterns ---
        if i >= 2:
            bar1 = ohlcv.iloc[i - 2]
            bar2 = ohlcv.iloc[i - 1]
            patterns.extend(
                _detect_triple(
                    i, bar_date_val, o, h, l, c, bar1, bar2, row, trend,
                    doji_pct, small_pct,
                )
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
    bd_safe = max(bd, 1e-10)  # avoid division by zero

    is_doji = bp < doji_pct
    is_small_body = bp < small_pct
    has_long_lower = lw >= wick_mult * bd_safe
    has_long_upper = uw >= wick_mult * bd_safe

    # Hammer shape: small body at top, long lower wick
    is_hammer_shape = is_small_body and has_long_lower and uw < bd_safe * 0.5

    # Inverted hammer shape: small body at bottom, long upper wick
    is_inv_hammer_shape = is_small_body and has_long_upper and lw < bd_safe * 0.5

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
        # Generic doji (but not if already classified as dragonfly)
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
    po, ph, pl, pc = prev["Open"], prev["High"], prev["Low"], prev["Close"]

    curr_body_lo = min(o, c)
    curr_body_hi = max(o, c)
    prev_body_lo = min(po, pc)
    prev_body_hi = max(po, pc)

    # Bullish Engulfing: prior red, current green engulfs it
    if _is_bearish(po, pc) and _is_bullish(o, c):
        if curr_body_lo <= prev_body_lo and curr_body_hi >= prev_body_hi:
            results.append(CandlePattern(
                pattern=CandlePatternType.BULLISH_ENGULFING,
                direction=SignalDirection.BULLISH,
                bar_index=idx, bar_date=bar_date, bars_involved=2,
            ))

    # Bearish Engulfing: prior green, current red engulfs it
    if _is_bullish(po, pc) and _is_bearish(o, c):
        if curr_body_lo <= prev_body_lo and curr_body_hi >= prev_body_hi:
            results.append(CandlePattern(
                pattern=CandlePatternType.BEARISH_ENGULFING,
                direction=SignalDirection.BEARISH,
                bar_index=idx, bar_date=bar_date, bars_involved=2,
            ))

    # Tweezer Bottom: lows within tolerance, after downtrend
    if trend == SignalDirection.BEARISH:
        avg_price = (l + pl) / 2
        if avg_price > 0 and abs(l - pl) / avg_price <= tweezer_tol:
            results.append(CandlePattern(
                pattern=CandlePatternType.TWEEZER_BOTTOM,
                direction=SignalDirection.BULLISH,
                bar_index=idx, bar_date=bar_date, bars_involved=2,
            ))

    # Tweezer Top: highs within tolerance, after uptrend
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
    bar1: pd.Series, bar2: pd.Series, bar3: pd.Series,
    trend: SignalDirection,
    doji_pct: float, small_pct: float,
) -> list[CandlePattern]:
    """Detect triple-bar patterns."""
    results: list[CandlePattern] = []
    o1, h1, l1, c1 = bar1["Open"], bar1["High"], bar1["Low"], bar1["Close"]
    o2, h2, l2, c2 = bar2["Open"], bar2["High"], bar2["Low"], bar2["Close"]

    r2 = _range(h2, l2)
    bp2 = _body_pct(o2, h2, l2, c2) if r2 > 0 else 0

    mid1 = (o1 + c1) / 2  # midpoint of first bar's body

    is_doji2 = bp2 < doji_pct
    is_small2 = bp2 < small_pct

    # Morning Star: bar1 red, bar2 small, bar3 green closing above mid of bar1
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

    # Evening Star: bar1 green, bar2 small, bar3 red closing below mid of bar1
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

    # Three White Soldiers: 3 green candles, each closing higher, small upper wicks
    if (
        _is_bullish(o1, c1) and _is_bullish(o2, c2) and _is_bullish(o3, c3)
        and c2 > c1 and c3 > c2
        and o2 > o1 and o3 > o2
    ):
        # Check small upper wicks relative to body
        uw1 = _upper_wick(o1, h1, c1)
        uw2 = _upper_wick(o2, h2, c2)
        uw3 = _upper_wick(o3, h3, c3)
        b1 = _body(o1, c1)
        b2 = _body(o2, c2)
        b3 = _body(o3, c3)
        if b1 > 0 and b2 > 0 and b3 > 0:
            if uw1 < b1 * 0.5 and uw2 < b2 * 0.5 and uw3 < b3 * 0.5:
                results.append(CandlePattern(
                    pattern=CandlePatternType.THREE_WHITE_SOLDIERS,
                    direction=SignalDirection.BULLISH,
                    bar_index=idx, bar_date=bar_date, bars_involved=3,
                ))

    # Three Black Crows: 3 red candles, each closing lower, small lower wicks
    if (
        _is_bearish(o1, c1) and _is_bearish(o2, c2) and _is_bearish(o3, c3)
        and c2 < c1 and c3 < c2
        and o2 < o1 and o3 < o2
    ):
        lw1 = _lower_wick(o1, l1, c1)
        lw2 = _lower_wick(o2, l2, c2)
        lw3 = _lower_wick(o3, l3, c3)
        b1 = _body(o1, c1)
        b2 = _body(o2, c2)
        b3 = _body(o3, c3)
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

    b0 = bars[0]  # first bar
    b4 = bars[4]  # last bar
    o0, h0, l0, c0 = b0["Open"], b0["High"], b0["Low"], b0["Close"]
    o4, h4, l4, c4 = b4["Open"], b4["High"], b4["Low"], b4["Close"]

    r0 = _range(h0, l0)
    r4 = _range(h4, l4)

    # Rising Three: first bar green + large, 3 small bodies within range, last bar green continuation
    if _is_bullish(o0, c0) and _is_bullish(o4, c4) and _body_pct(o0, h0, l0, c0) > 0.5:
        middle_contained = True
        for j in range(1, 4):
            bj = bars[j]
            oj, hj, lj, cj = bj["Open"], bj["High"], bj["Low"], bj["Close"]
            rj = _range(hj, lj)
            bpj = _body_pct(oj, hj, lj, cj) if rj > 0 else 0
            # Must be small body AND contained within first bar's range
            if bpj > small_pct or hj > h0 or lj < l0:
                middle_contained = False
                break
        if middle_contained and c4 > c0:
            results.append(CandlePattern(
                pattern=CandlePatternType.RISING_THREE,
                direction=SignalDirection.BULLISH,
                bar_index=idx, bar_date=bar_date, bars_involved=5,
            ))

    # Falling Three: first bar red + large, 3 small bodies within range, last bar red continuation
    if _is_bearish(o0, c0) and _is_bearish(o4, c4) and _body_pct(o0, h0, l0, c0) > 0.5:
        middle_contained = True
        for j in range(1, 4):
            bj = bars[j]
            oj, hj, lj, cj = bj["Open"], bj["High"], bj["Low"], bj["Close"]
            rj = _range(hj, lj)
            bpj = _body_pct(oj, hj, lj, cj) if rj > 0 else 0
            if bpj > small_pct or hj > h0 or lj < l0:
                middle_contained = False
                break
        if middle_contained and c4 < c0:
            results.append(CandlePattern(
                pattern=CandlePatternType.FALLING_THREE,
                direction=SignalDirection.BEARISH,
                bar_index=idx, bar_date=bar_date, bars_involved=5,
            ))

    return results
```

- [ ] **Step 4: Run single-bar tests**

Run: `.venv_312/Scripts/python -m pytest tests/test_candlestick_patterns.py::TestSingleBarDetection -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add income_desk/features/patterns/candles.py tests/test_candlestick_patterns.py
git commit -m "feat: candlestick detection — 7 single-bar patterns + helpers"
```

---

### Task 4: Detection — Double-bar patterns (4 patterns)

**Files:**
- Test: `tests/test_candlestick_patterns.py`

- [ ] **Step 1: Write tests for all 4 double-bar patterns**

Add to `tests/test_candlestick_patterns.py`:

```python
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
            (97.5, 98.5, 95.00, 98.0, 120000),  # same low
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.TWEEZER_BOTTOM in names

    def test_tweezer_top(self) -> None:
        bars = _uptrend_prefix() + [
            (103.0, 105.00, 102.5, 104.5, 100000),
            (104.5, 105.00, 103.0, 103.5, 120000),  # same high
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=3)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.TWEEZER_TOP in names
```

- [ ] **Step 2: Run tests — expect PASS (detection code already in place)**

Run: `.venv_312/Scripts/python -m pytest tests/test_candlestick_patterns.py::TestDoubleBarDetection -v`
Expected: 4 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_candlestick_patterns.py
git commit -m "test: double-bar candlestick pattern detection (4 patterns)"
```

---

### Task 5: Detection — Triple-bar patterns (6 patterns)

**Files:**
- Test: `tests/test_candlestick_patterns.py`

- [ ] **Step 1: Write tests for all 6 triple-bar patterns**

Add to `tests/test_candlestick_patterns.py`:

```python
class TestTripleBarDetection:
    def test_morning_star(self) -> None:
        bars = _downtrend_prefix() + [
            (97.0, 97.5, 95.0, 95.5, 100000),    # red
            (95.5, 96.0, 95.0, 95.8, 80000),      # small body (not doji)
            (96.0, 98.0, 95.5, 97.5, 130000),     # green, closes above mid of bar1
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=4)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.MORNING_STAR in names

    def test_evening_star(self) -> None:
        bars = _uptrend_prefix() + [
            (103.0, 105.0, 102.5, 104.5, 100000),  # green
            (104.5, 105.0, 104.0, 104.3, 80000),   # small body
            (104.0, 104.5, 102.0, 102.5, 130000),  # red, closes below mid of bar1
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=4)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.EVENING_STAR in names

    def test_morning_doji_star(self) -> None:
        bars = _downtrend_prefix() + [
            (97.0, 97.5, 95.0, 95.5, 100000),    # red
            (95.5, 96.0, 95.0, 95.52, 80000),     # doji (body < 10% of range)
            (96.0, 98.0, 95.5, 97.5, 130000),     # green, above mid
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=4)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.MORNING_DOJI_STAR in names

    def test_evening_doji_star(self) -> None:
        bars = _uptrend_prefix() + [
            (103.0, 105.0, 102.5, 104.5, 100000),  # green
            (104.5, 105.0, 104.0, 104.52, 80000),  # doji
            (104.0, 104.5, 102.0, 102.5, 130000),  # red, below mid
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
```

- [ ] **Step 2: Run tests — expect PASS**

Run: `.venv_312/Scripts/python -m pytest tests/test_candlestick_patterns.py::TestTripleBarDetection -v`
Expected: 6 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_candlestick_patterns.py
git commit -m "test: triple-bar candlestick pattern detection (6 patterns)"
```

---

### Task 6: Detection — Five-bar patterns (2 patterns)

**Files:**
- Test: `tests/test_candlestick_patterns.py`

- [ ] **Step 1: Write tests for Rising Three and Falling Three**

Add to `tests/test_candlestick_patterns.py`:

```python
class TestFiveBarDetection:
    def test_rising_three(self) -> None:
        bars = _flat_prefix() + [
            (100.0, 104.0, 99.5, 103.5, 150000),  # big green (body > 50%)
            (103.0, 103.2, 102.0, 102.5, 80000),   # small, contained
            (102.5, 103.0, 101.5, 102.0, 70000),   # small, contained
            (102.0, 103.3, 101.0, 102.8, 75000),   # small, contained
            (103.0, 106.0, 102.5, 105.5, 160000),  # big green, closes > first close
        ]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=6)
        names = [p.pattern for p in patterns]
        assert CandlePatternType.RISING_THREE in names

    def test_falling_three(self) -> None:
        bars = _flat_prefix() + [
            (104.0, 104.5, 100.0, 100.5, 150000),  # big red (body > 50%)
            (101.0, 102.0, 100.5, 101.5, 80000),   # small, contained
            (101.5, 102.5, 101.0, 102.0, 70000),   # small, contained
            (102.0, 103.0, 101.0, 101.5, 75000),   # small, contained
            (101.0, 101.5, 98.0, 98.5, 160000),    # big red, closes < first close
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
```

- [ ] **Step 2: Run tests — expect PASS**

Run: `.venv_312/Scripts/python -m pytest tests/test_candlestick_patterns.py::TestFiveBarDetection -v`
Expected: 3 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_candlestick_patterns.py
git commit -m "test: five-bar candlestick pattern detection (Rising/Falling Three)"
```

---

### Task 7: Scoring + Convenience + Signal Generation

**Files:**
- Modify: `income_desk/features/patterns/candles.py`
- Test: `tests/test_candlestick_patterns.py`

- [ ] **Step 1: Write failing tests for scoring and convenience**

Add to `tests/test_candlestick_patterns.py`:

```python
from income_desk.features.patterns.candles import (
    compute_candlestick_patterns,
    generate_candlestick_signals,
    score_candlestick_patterns,
)


class TestScoring:
    def test_scored_patterns_have_conviction(self) -> None:
        bars = _downtrend_prefix() + [
            (98.0, 98.5, 92.0, 98.2, 200000),  # hammer with high volume
        ]
        df = _make_ohlcv(bars)
        raw = detect_candlestick_patterns(df, lookback_bars=3)
        scored = score_candlestick_patterns(df, raw)
        hammers = [p for p in scored if p.pattern == CandlePatternType.HAMMER]
        assert len(hammers) >= 1
        assert hammers[0].conviction > 0
        assert hammers[0].context != ""

    def test_high_volume_boosts_conviction(self) -> None:
        # Same pattern, low vol vs high vol
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
            (100.0, 100.5, 99.5, 100.2, 50000),  # doji — likely low conviction
        ]
        df = _make_ohlcv(bars)
        summary = compute_candlestick_patterns(df)
        # All returned patterns should be above min_conviction threshold
        for p in summary.patterns:
            assert p.conviction >= 30  # default candle_min_conviction


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
            (96.0, 98.0, 95.5, 98.0, 250000),   # green engulfs red at low
            (98.0, 98.5, 92.0, 98.2, 200000),   # hammer too
        ]
        df = _make_ohlcv(bars)
        summary = compute_candlestick_patterns(df)
        signals = generate_candlestick_signals(summary)
        for s in signals:
            assert s.strength in (SignalStrength.STRONG, SignalStrength.MODERATE, SignalStrength.WEAK)
```

- [ ] **Step 2: Run tests — expect ImportError/FAIL**

Run: `.venv_312/Scripts/python -m pytest tests/test_candlestick_patterns.py::TestScoring -v`
Expected: FAIL — `score_candlestick_patterns` not found

- [ ] **Step 3: Implement scoring, convenience, and signal generation**

Append to `income_desk/features/patterns/candles.py`:

```python
# ---------------------------------------------------------------------------
# Layer 2: Context Scoring
# ---------------------------------------------------------------------------

def score_candlestick_patterns(
    ohlcv: pd.DataFrame,
    patterns: list[CandlePattern],
    *,
    settings: TechnicalsSettings | None = None,
) -> list[CandlePattern]:
    """Add conviction scores and context commentary to detected patterns.

    Scoring components (0-100 total):
      - Trend alignment:          0-30 pts
      - Body conviction:          0-20 pts
      - Volume confirmation:      0-20 pts
      - Support/resistance prox:  0-20 pts
      - Pattern complexity:       0-10 pts
    """
    if settings is None:
        settings = get_settings().technicals

    vol_period = settings.candle_volume_avg_period
    trend_lb = settings.candle_trend_lookback
    scored: list[CandlePattern] = []

    for p in patterns:
        idx = p.bar_index
        parts: list[str] = []

        # --- Trend alignment (0-30) ---
        trend_start = max(0, idx - trend_lb)
        trend = _detect_trend(ohlcv["Close"].iloc[trend_start:idx])
        trend_score = _score_trend(p, trend)

        # --- Body conviction (0-20) ---
        row = ohlcv.iloc[idx]
        body_score = _score_body(p, row, ohlcv, idx)

        # --- Volume confirmation (0-20) ---
        vol_score, vol_ratio = _score_volume(ohlcv, idx, vol_period)
        if vol_ratio > 1.0:
            parts.append(f"volume {vol_ratio:.1f}x avg")

        # --- Support/resistance proximity (0-20) ---
        sr_score = _score_sr_proximity(ohlcv, idx)

        # --- Pattern complexity (0-10) ---
        complexity_map = {1: 3, 2: 5, 3: 8, 5: 10}
        complexity_score = complexity_map.get(p.bars_involved, 3)

        conviction = min(100, trend_score + body_score + vol_score + sr_score + complexity_score)

        # Build context string
        if trend != SignalDirection.NEUTRAL:
            parts.insert(0, f"after {trend.value} trend")
        if sr_score >= 15:
            parts.append("near key level")
        context = f"{p.pattern.value}: {', '.join(parts)}" if parts else p.pattern.value

        scored.append(p.model_copy(update={"conviction": conviction, "context": context}))

    return scored


def _score_trend(p: CandlePattern, trend: SignalDirection) -> int:
    """Score trend alignment."""
    # Reversal patterns at end of opposing trend = high score
    reversal_patterns = {
        CandlePatternType.HAMMER, CandlePatternType.INVERTED_HAMMER,
        CandlePatternType.BULLISH_ENGULFING, CandlePatternType.TWEEZER_BOTTOM,
        CandlePatternType.MORNING_STAR, CandlePatternType.MORNING_DOJI_STAR,
        CandlePatternType.HANGING_MAN, CandlePatternType.SHOOTING_STAR,
        CandlePatternType.BEARISH_ENGULFING, CandlePatternType.TWEEZER_TOP,
        CandlePatternType.EVENING_STAR, CandlePatternType.EVENING_DOJI_STAR,
    }
    continuation_patterns = {
        CandlePatternType.THREE_WHITE_SOLDIERS, CandlePatternType.THREE_BLACK_CROWS,
        CandlePatternType.RISING_THREE, CandlePatternType.FALLING_THREE,
    }

    if p.pattern in reversal_patterns:
        if (p.direction == SignalDirection.BULLISH and trend == SignalDirection.BEARISH) or \
           (p.direction == SignalDirection.BEARISH and trend == SignalDirection.BULLISH):
            return 30  # reversal at end of trend
        elif trend == SignalDirection.NEUTRAL:
            return 10
        return 5  # wrong direction
    elif p.pattern in continuation_patterns:
        if (p.direction == SignalDirection.BULLISH and trend == SignalDirection.BULLISH) or \
           (p.direction == SignalDirection.BEARISH and trend == SignalDirection.BEARISH):
            return 28
        elif trend == SignalDirection.NEUTRAL:
            return 15
        return 5
    return 10  # neutral patterns


def _score_body(
    p: CandlePattern, row: pd.Series, ohlcv: pd.DataFrame, idx: int,
) -> int:
    """Score body conviction."""
    o, h, l, c = row["Open"], row["High"], row["Low"], row["Close"]
    r = _range(h, l)
    if r == 0:
        return 5

    bd = _body(o, c)
    lw = _lower_wick(o, l, c)
    uw = _upper_wick(o, h, c)
    bd_safe = max(bd, 1e-10)

    # For hammer/shooting star: longer wick = more conviction
    if p.pattern in (CandlePatternType.HAMMER, CandlePatternType.HANGING_MAN):
        ratio = lw / bd_safe
        return min(20, int(ratio * 4))
    if p.pattern in (CandlePatternType.SHOOTING_STAR, CandlePatternType.INVERTED_HAMMER):
        ratio = uw / bd_safe
        return min(20, int(ratio * 4))

    # For engulfing: how much larger
    if p.pattern in (CandlePatternType.BULLISH_ENGULFING, CandlePatternType.BEARISH_ENGULFING):
        if idx >= 1:
            prev = ohlcv.iloc[idx - 1]
            prev_body = _body(prev["Open"], prev["Close"])
            if prev_body > 0:
                ratio = bd / prev_body
                return min(20, int(ratio * 7))
        return 10

    # Default: body percentage of range
    return min(20, int(bd / r * 20))


def _score_volume(ohlcv: pd.DataFrame, idx: int, period: int) -> tuple[int, float]:
    """Score volume confirmation. Returns (score, volume_ratio)."""
    if "Volume" not in ohlcv.columns:
        return 5, 1.0

    vol = ohlcv["Volume"].iloc[idx]
    start = max(0, idx - period)
    avg_vol = ohlcv["Volume"].iloc[start:idx].mean()

    if avg_vol == 0 or pd.isna(avg_vol):
        return 5, 1.0

    ratio = vol / avg_vol
    if ratio >= 2.0:
        return 20, ratio
    if ratio >= 1.5:
        return 15, ratio
    if ratio >= 1.0:
        return 10, ratio
    return 5, ratio


def _score_sr_proximity(ohlcv: pd.DataFrame, idx: int) -> int:
    """Score proximity to support/resistance (recent highs/lows)."""
    lookback = min(20, idx)
    if lookback < 3:
        return 5

    recent = ohlcv.iloc[idx - lookback:idx]
    high_20 = recent["High"].max()
    low_20 = recent["Low"].min()
    price = ohlcv["Close"].iloc[idx]

    rng = high_20 - low_20
    if rng == 0:
        return 5

    dist_to_high = abs(price - high_20) / rng
    dist_to_low = abs(price - low_20) / rng

    min_dist = min(dist_to_high, dist_to_low)
    if min_dist <= 0.05:
        return 20
    if min_dist <= 0.15:
        return 15
    if min_dist <= 0.30:
        return 10
    return 5


# ---------------------------------------------------------------------------
# Convenience: compute (detect + score + summarize)
# ---------------------------------------------------------------------------

def compute_candlestick_patterns(
    ohlcv: pd.DataFrame,
    settings: TechnicalsSettings | None = None,
) -> CandlePatternSummary:
    """Detect + score + summarize. The all-in-one call."""
    if settings is None:
        settings = get_settings().technicals

    if not settings.candle_enabled or len(ohlcv) < 2:
        return CandlePatternSummary(timeframe=settings.candle_timeframe)

    raw = detect_candlestick_patterns(
        ohlcv, lookback_bars=settings.candle_lookback_bars, settings=settings,
    )
    scored = score_candlestick_patterns(ohlcv, raw, settings=settings)

    # Filter by min conviction
    filtered = [p for p in scored if p.conviction >= settings.candle_min_conviction]

    bullish = [p for p in filtered if p.direction == SignalDirection.BULLISH]
    bearish = [p for p in filtered if p.direction == SignalDirection.BEARISH]
    strongest = max(filtered, key=lambda p: p.conviction) if filtered else None

    return CandlePatternSummary(
        patterns=filtered,
        bullish_count=len(bullish),
        bearish_count=len(bearish),
        strongest=strongest,
        timeframe=settings.candle_timeframe,
    )


# ---------------------------------------------------------------------------
# Signal bridge: for TechnicalSnapshot.signals
# ---------------------------------------------------------------------------

def generate_candlestick_signals(
    summary: CandlePatternSummary | None,
) -> list[TechnicalSignal]:
    """Convert top candlestick patterns into TechnicalSignal entries.

    Emits up to 3 signals (top patterns by conviction).
    """
    if summary is None or not summary.patterns:
        return []

    # Top 3 by conviction
    top = sorted(summary.patterns, key=lambda p: p.conviction, reverse=True)[:3]
    signals: list[TechnicalSignal] = []

    for p in top:
        if p.conviction >= 70:
            strength = SignalStrength.STRONG
        elif p.conviction >= 50:
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK

        signals.append(TechnicalSignal(
            name=f"Candle: {p.pattern.value.replace('_', ' ').title()}",
            direction=p.direction,
            strength=strength,
            description=p.context or p.pattern.value,
        ))

    return signals
```

- [ ] **Step 4: Run all scoring + signal tests**

Run: `.venv_312/Scripts/python -m pytest tests/test_candlestick_patterns.py::TestScoring tests/test_candlestick_patterns.py::TestConvenience tests/test_candlestick_patterns.py::TestSignalGeneration -v`
Expected: All PASS

- [ ] **Step 5: Run full test file**

Run: `.venv_312/Scripts/python -m pytest tests/test_candlestick_patterns.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add income_desk/features/patterns/candles.py tests/test_candlestick_patterns.py
git commit -m "feat: candlestick scoring, compute convenience, signal generation"
```

---

### Task 8: Edge cases + negative tests

**Files:**
- Test: `tests/test_candlestick_patterns.py`

- [ ] **Step 1: Write edge case and negative tests**

Add to `tests/test_candlestick_patterns.py`:

```python
class TestEdgeCases:
    def test_insufficient_data(self) -> None:
        df = _make_ohlcv([(100, 101, 99, 100, 1000)])
        patterns = detect_candlestick_patterns(df)
        # Should not crash, may return empty or single-bar only
        assert isinstance(patterns, list)

    def test_empty_dataframe(self) -> None:
        df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        patterns = detect_candlestick_patterns(df)
        assert patterns == []

    def test_zero_range_bar_skipped(self) -> None:
        bars = _flat_prefix() + [(100.0, 100.0, 100.0, 100.0, 100000)]
        df = _make_ohlcv(bars)
        patterns = detect_candlestick_patterns(df, lookback_bars=2)
        # Zero-range bar should produce no patterns
        zero_bar_patterns = [p for p in patterns if p.bar_index == len(df) - 1]
        assert zero_bar_patterns == []

    def test_hammer_not_detected_without_downtrend(self) -> None:
        # Hammer shape but after uptrend = hanging man, not hammer
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
```

- [ ] **Step 2: Run tests**

Run: `.venv_312/Scripts/python -m pytest tests/test_candlestick_patterns.py::TestEdgeCases -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_candlestick_patterns.py
git commit -m "test: candlestick edge cases and negative tests"
```

---

### Task 9: Wire into compute_technicals + patterns __init__

**Files:**
- Modify: `income_desk/features/technicals.py:1-18, 870-918`
- Modify: `income_desk/features/patterns/__init__.py`

- [ ] **Step 1: Add imports to technicals.py**

In `income_desk/features/technicals.py`, add import after the VCP import block (after line 18):

```python
from income_desk.features.patterns.candles import (  # noqa: F401
    compute_candlestick_patterns,
    generate_candlestick_signals as _generate_candlestick_signals,
)
```

- [ ] **Step 2: Wire computation into compute_technicals()**

In `income_desk/features/technicals.py`, after the smart_money block (after line 872), add:

```python
    # Candlestick patterns (from features.patterns.candles)
    candle_summary = compute_candlestick_patterns(ohlcv, settings)
    signals.extend(_generate_candlestick_signals(candle_summary))
```

Then in the `TechnicalSnapshot(...)` constructor (around line 910), add after `smart_money=smart_money,`:

```python
        candlestick_patterns=candle_summary,
```

- [ ] **Step 3: Update patterns __init__.py**

In `income_desk/features/patterns/__init__.py`, add:

```python
from income_desk.features.patterns.candles import (
    compute_candlestick_patterns,
    detect_candlestick_patterns,
    score_candlestick_patterns,
    generate_candlestick_signals,
)
```

And extend `__all__`:

```python
__all__ = [
    "compute_vcp",
    "compute_order_blocks",
    "compute_fair_value_gaps",
    "compute_smart_money",
    "compute_orb",
    "compute_candlestick_patterns",
    "detect_candlestick_patterns",
    "score_candlestick_patterns",
    "generate_candlestick_signals",
]
```

- [ ] **Step 4: Run full test suite**

Run: `.venv_312/Scripts/python -m pytest tests/ -x -q`
Expected: All pass (existing + new)

- [ ] **Step 5: Commit**

```bash
git add income_desk/features/technicals.py income_desk/features/patterns/__init__.py
git commit -m "feat: wire candlestick patterns into compute_technicals + pattern exports"
```

---

### Task 10: CLI — `candles` command

**Files:**
- Modify: `income_desk/cli/interactive.py` (after `do_technicals`, before `do_levels` ~line 922)

- [ ] **Step 1: Add do_candles command**

In `income_desk/cli/interactive.py`, after `do_technicals` (after line 921), add:

```python
    def do_candles(self, arg: str) -> None:
        """Show candlestick patterns.\nUsage: candles SPY [--lookback N] [--raw] [--debug]"""
        parts = arg.split()
        if not parts:
            print("Usage: candles TICKER [--lookback N] [--raw] [--debug]")
            return

        ticker = parts[0].upper()
        lookback = 10
        raw = False
        debug = False

        i = 1
        while i < len(parts):
            if parts[i] == "--lookback" and i + 1 < len(parts):
                lookback = int(parts[i + 1])
                i += 2
            elif parts[i] == "--raw":
                raw = True
                i += 1
            elif parts[i] == "--debug":
                debug = True
                i += 1
            else:
                i += 1

        try:
            ma = self._get_ma()
            ds = ma.data_service
            ohlcv = ds.get_daily(ticker)

            from income_desk.config import TechnicalsSettings, get_settings
            settings = get_settings().technicals

            if raw:
                from income_desk.features.patterns.candles import detect_candlestick_patterns
                patterns = detect_candlestick_patterns(
                    ohlcv, lookback_bars=lookback, settings=settings,
                )
                _print_header(f"{ticker} — Raw Candlestick Patterns (last {lookback} bars)")
                if not patterns:
                    print("  No patterns detected.")
                for p in patterns:
                    print(f"  {p.bar_date}  {p.pattern.value:<25} {p.direction.value}")
            else:
                from income_desk.features.patterns.candles import compute_candlestick_patterns
                settings_copy = settings.model_copy(update={"candle_lookback_bars": lookback})
                summary = compute_candlestick_patterns(ohlcv, settings=settings_copy)

                _print_header(
                    f"{ticker} — Candlestick Patterns "
                    f"({summary.timeframe}, last {lookback} bars)"
                )
                if not summary.patterns:
                    print("  No patterns above conviction threshold.")
                for p in summary.patterns:
                    print(
                        f"  {p.bar_date}  {p.pattern.value:<25} "
                        f"{p.direction.value:<8} conviction: {p.conviction}"
                    )
                    if p.context:
                        print(f"{'':30}{p.context}")

                if summary.strongest:
                    print(f"\n  Strongest: {summary.strongest.pattern.value} ({summary.strongest.conviction})"
                          f" — {summary.strongest.direction.value}")
                print(f"  Summary: {summary.bullish_count} bullish, "
                      f"{summary.bearish_count} bearish")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")
```

- [ ] **Step 2: Smoke test**

Run: `.venv_312/Scripts/python -c "from income_desk.cli.interactive import AnalyzerShell; print('CLI loads OK')"`
Expected: `CLI loads OK`

- [ ] **Step 3: Run full test suite**

Run: `.venv_312/Scripts/python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add income_desk/cli/interactive.py
git commit -m "feat: candles CLI command — scored + raw modes with lookback"
```

---

### Task 11: Public API exports + final integration test

**Files:**
- Modify: `income_desk/__init__.py`
- Test: `tests/test_candlestick_patterns.py`

- [ ] **Step 1: Add exports to __init__.py**

In `income_desk/__init__.py`, after `from income_desk.models.technicals import TechnicalSnapshot, TechnicalSignal` (line 44), add:

```python
from income_desk.models.technicals import (
    CandlePattern,
    CandlePatternSummary,
    CandlePatternType,
)
```

- [ ] **Step 2: Write integration test**

Add to `tests/test_candlestick_patterns.py`:

```python
class TestIntegration:
    def test_technical_snapshot_includes_candlestick(self) -> None:
        """Verify candlestick_patterns field exists on TechnicalSnapshot."""
        from income_desk.models.technicals import TechnicalSnapshot
        fields = TechnicalSnapshot.model_fields
        assert "candlestick_patterns" in fields

    def test_public_api_exports(self) -> None:
        from income_desk import CandlePattern, CandlePatternSummary, CandlePatternType
        assert CandlePatternType.HAMMER == "hammer"
```

- [ ] **Step 3: Run full test suite**

Run: `.venv_312/Scripts/python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 4: Final commit**

```bash
git add income_desk/__init__.py tests/test_candlestick_patterns.py
git commit -m "feat: candlestick patterns — public API exports + integration tests"
```
