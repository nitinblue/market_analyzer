# Design: Candlestick Pattern Detection Module

**Date:** 2026-03-31
**Status:** Reviewed (v2 — addressed 5 review items)
**Author:** Claude (brainstormed with Nitin)

---

## Goal

Detect 19 classical candlestick patterns from raw OHLCV data, score them by context, and expose them as composable building blocks. Inspired by Ross Cameron's bar-reading approach: no indicators, just price action geometry in context.

Timeframe-agnostic. Works on daily bars today, intraday bars tomorrow.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Timeframe | Configurable via parameter | Day trading needs 1/5 min; swing needs daily. Same geometry. |
| Integration | Wired into TechnicalSnapshot | Additive — new optional field, zero impact on existing callers |
| Pattern scope | All 19 patterns in v1 | Complete reference chart coverage |
| Architecture | Two layers: detect + score | Raw detection for backtesting, scored for live decisions |
| Composability | Each function independently callable | Callers pick the level of abstraction they need |
| CLI | New `candles` command | Non-negotiable per CLAUDE.md |

## Architecture

```
models/technicals.py              ← CandlePatternType, CandlePattern, CandlePatternSummary
features/patterns/candles.py      ← detect, score, compute, generate_candlestick_signals
config/__init__.py                ← candle_* flat fields on TechnicalsSettings
features/technicals.py            ← Wire compute + generate_candlestick_signals into compute_technicals
cli/interactive.py                ← `candles` command
__init__.py                       ← Export public symbols
tests/test_candlestick_patterns.py ← Unit tests for all 19 patterns + scoring + signals
```

No new directories. No new dependencies. Slots into existing structure.

## Models

### CandlePatternType (StrEnum)

All 19 patterns:

**Single-bar (7):**
- `HAMMER` — small body top of range, lower wick >= 2x body, after downtrend
- `INVERTED_HAMMER` — small body bottom of range, upper wick >= 2x body, after downtrend
- `HANGING_MAN` — hammer shape but after uptrend (bearish)
- `SHOOTING_STAR` — inverted hammer shape but after uptrend (bearish)
- `DOJI` — body < 10% of total range (indecision)
- `DRAGONFLY_DOJI` — doji with negligible upper wick (bullish)
- `SPINNING_TOP` — body 10-33% of range, wicks on both sides (neutral)

**Double-bar (4):**
- `BULLISH_ENGULFING` — green body fully engulfs prior red body
- `BEARISH_ENGULFING` — red body fully engulfs prior green body
- `TWEEZER_BOTTOM` — two candles with lows within tolerance, after downtrend
- `TWEEZER_TOP` — two candles with highs within tolerance, after uptrend

**Triple-bar (6):**
- `MORNING_STAR` — red candle, small body, green candle closing above midpoint of first
- `EVENING_STAR` — green candle, small body, red candle closing below midpoint of first
- `MORNING_DOJI_STAR` — morning star where middle candle is a doji
- `EVENING_DOJI_STAR` — evening star where middle candle is a doji
- `THREE_WHITE_SOLDIERS` — three consecutive green candles, each closing higher, small upper wicks
- `THREE_BLACK_CROWS` — three consecutive red candles, each closing lower, small lower wicks

**Five-bar (2):**
- `RISING_THREE` — long green, 3 small bodies contained within range, long green continuation
- `FALLING_THREE` — long red, 3 small bodies contained within range, long red continuation

### CandlePattern (Pydantic BaseModel)

```python
class CandlePattern(BaseModel):
    pattern: CandlePatternType
    direction: SignalDirection        # bullish / bearish / neutral
    bar_index: int                    # DataFrame index where pattern completes
    bar_date: date
    conviction: int = 0              # 0-100, filled by scorer
    context: str = ""                # "hammer at 20-bar low with 1.5x avg volume"
    bars_involved: int               # 1, 2, 3, or 5
```

### CandlePatternSummary (Pydantic BaseModel)

```python
class CandlePatternSummary(BaseModel):
    patterns: list[CandlePattern] = []
    bullish_count: int = 0
    bearish_count: int = 0
    strongest: CandlePattern | None = None   # highest conviction
    timeframe: str = "daily"
```

### TechnicalSnapshot addition

```python
candlestick_patterns: CandlePatternSummary | None = None
```

Matches the established `| None = None` convention used by `vcp`, `smart_money`, `fibonacci`, etc.

## Settings

Flat fields on `TechnicalsSettings` with `candle_` prefix, matching the existing convention
used by VCP (`vcp_*`) and Smart Money (`ob_*`, `fvg_*`):

```python
# Added to TechnicalsSettings:
candle_enabled: bool = True
candle_lookback_bars: int = 10              # how many recent bars to scan
candle_body_doji_pct: float = 0.10          # body < 10% of range = doji
candle_body_small_pct: float = 0.33         # body < 33% = small body
candle_wick_multiplier: float = 2.0         # wick >= Nx body for hammer/star
candle_trend_lookback: int = 5              # bars to determine prior trend direction
candle_volume_avg_period: int = 20          # for volume confirmation scoring
candle_min_conviction: int = 30             # filter out noise below this in summary
candle_tweezer_tolerance_pct: float = 0.001 # highs/lows within 0.1% = tweezers
candle_timeframe: str = "daily"             # context hint for scoring
```

## Functions (composable API)

### Layer 1: Detection

```python
def detect_candlestick_patterns(
    ohlcv: pd.DataFrame,
    *,
    lookback_bars: int = 10,
    settings: TechnicalsSettings | None = None,
) -> list[CandlePattern]:
    """Detect raw candlestick patterns in the last N bars.

    Pure geometric detection. No conviction scoring.
    Returns all matches, including weak/ambiguous ones.

    Args:
        ohlcv: DataFrame with columns: Open, High, Low, Close, Volume.
               (Capitalized — matches project convention.)
               Index can be DatetimeIndex or RangeIndex.
        lookback_bars: How many recent bars to scan.
        settings: Override default thresholds.

    Returns:
        List of CandlePattern with conviction=0 (unscored).
    """
```

Internally delegates to private `_detect_*` functions:

```python
_detect_single_bar(row, prev_rows, settings) -> list[CandlePattern]
_detect_double_bar(row, prev_row, trend, settings) -> list[CandlePattern]
_detect_triple_bar(rows_3, trend, settings) -> list[CandlePattern]
_detect_five_bar(rows_5, settings) -> list[CandlePattern]
```

Trend detection helper:

```python
_detect_trend(ohlcv_slice: pd.DataFrame) -> SignalDirection
```

Simple: if closes trending up over N bars = BULLISH, down = BEARISH, else NEUTRAL.
Uses simple close-over-close comparison: if close[-1] > close[-N] and majority of bars are up = BULLISH, etc. No scipy/numpy linreg — keeps it simple with numpy operations already available in the project.

### Layer 2: Context Scoring

```python
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

    Returns new list with conviction and context fields populated.
    """
```

Scoring breakdown:

**Trend alignment (0-30):** Reversal pattern at end of a clear trend = 30. Same pattern mid-range = 5-10. Continuation pattern in the direction of the trend = 25-30.

**Body conviction (0-20):** For engulfing: how much larger is the engulfing body? For hammer: how long is the wick relative to body? Bigger = more decisive.

**Volume confirmation (0-20):** Signal bar volume vs 20-period average. 2x+ average = 20. 1.5x = 15. Below average = 5.

**Support/resistance proximity (0-20):** Pattern near a recent high/low (lookback 20 bars) = 20. Mid-range = 5.

**Pattern complexity (0-10):** Single-bar = 3. Double-bar = 5. Triple-bar = 8. Five-bar = 10. More bars = more conviction.

### Convenience Function

```python
def compute_candlestick_patterns(
    ohlcv: pd.DataFrame,
    settings: TechnicalsSettings | None = None,
) -> CandlePatternSummary:
    """Detect + score + summarize. The all-in-one call.

    This is what compute_technicals() calls internally.
    Applies min_conviction filter and produces the summary.
    """
```

### Signal Generation (for TechnicalSnapshot.signals integration)

```python
def generate_candlestick_signals(
    summary: CandlePatternSummary | None,
) -> list[TechnicalSignal]:
    """Convert top candlestick patterns into TechnicalSignal entries.

    Follows the same contract as generate_vcp_signals() and
    generate_smart_money_signals(). Wired into compute_technicals()
    so candlestick patterns appear in the unified signals list.

    Mapping:
      conviction >= 70 → SignalStrength.STRONG
      conviction >= 50 → SignalStrength.MODERATE
      conviction >= 30 → SignalStrength.WEAK
      conviction < 30  → not emitted

    Emits up to 3 signals (top patterns by conviction).
    """
```

## CLI Command

Added to `cli/interactive.py`:

```
candles <TICKER>                     # scan daily, show scored patterns above threshold
candles <TICKER> --timeframe 5min    # scan intraday bars
candles <TICKER> --raw               # no conviction filter, show all detections
candles <TICKER> --lookback 20       # scan last 20 bars
candles <TICKER> --debug             # show scoring breakdown per pattern
```

Output format:

```
CANDLESTICK PATTERNS: SPY (daily, last 10 bars)
──────────────────────────────────────────────────
  2026-03-28  BULLISH_ENGULFING  bullish  conviction: 78
              Green body engulfs prior red at 20-bar low, volume 1.8x avg

  2026-03-31  HAMMER             bullish  conviction: 62
              Long lower wick (3.1x body) near support, volume 1.2x avg

  Strongest: BULLISH_ENGULFING (78) — bullish
  Summary: 2 bullish, 0 bearish, 0 neutral
```

## Testing Strategy

`tests/test_candlestick_patterns.py`:

1. **Per-pattern detection tests (19 tests)** — craft synthetic OHLCV for each pattern, assert detection
2. **Negative tests** — bars that look similar but don't qualify (e.g., hammer without prior downtrend for hanging man distinction)
3. **Scoring tests** — verify conviction breakdown for known setups
4. **Edge cases** — insufficient data (< 5 bars), flat market (zero range), missing volume
5. **Integration test** — `compute_candlestick_patterns` returns `CandlePatternSummary` with correct counts
6. **TechnicalSnapshot test** — verify `candlestick_patterns` field populated after `compute_technicals()`

Synthetic OHLCV helper:

```python
def _make_ohlcv(bars: list[tuple[float, float, float, float, int]]) -> pd.DataFrame:
    """Build OHLCV DataFrame from (open, high, low, close, volume) tuples."""
```

## What This Does NOT Do

- No trade signals — detection and scoring only. Callers decide what to do.
- No multi-timeframe alignment — caller runs it per timeframe, composes externally.
- No indicator dependency — pure OHLCV + volume geometry.
- No regime coupling — works independently of R1-R4.
- No state — pure functions, no caching, no side effects.

## Files Changed

| File | Change |
|------|--------|
| `models/technicals.py` | Add CandlePatternType, CandlePattern, CandlePatternSummary; add field to TechnicalSnapshot |
| `features/patterns/candles.py` | New file — detect, score, compute, generate_candlestick_signals |
| `features/patterns/__init__.py` | Export new functions |
| `config/__init__.py` | Add `candle_*` flat fields to TechnicalsSettings |
| `features/technicals.py` | Wire compute_candlestick_patterns + generate_candlestick_signals into compute_technicals |
| `cli/interactive.py` | Add `candles` command |
| `__init__.py` | Export new public symbols |
| `tests/test_candlestick_patterns.py` | New file — comprehensive tests |
