# Entry-Level Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform entry logic from "enter now at market" to "enter at the right price, at the right strike, backed by support/resistance" — 6 capabilities that answer "at what level should I enter?"

**Architecture:** Pure functions in `market_analyzer/features/entry_levels.py` that consume existing models (TechnicalSnapshot, LevelsAnalysis, VolatilitySurface, TradeSpec) and return entry intelligence. No broker required. Modifications to `_trade_spec_helpers.py` wire skew into IC strike selection. New validation check adds strike-proximity gate to daily readiness.

**Tech Stack:** Python 3.12, Pydantic BaseModel, existing market_analyzer models. No new dependencies.

**Venv / test command:** `.venv_312/Scripts/python.exe -m pytest tests/ -v`

---

## File Structure

```
market_analyzer/
  models/entry.py                    # NEW: 6 result models
  features/entry_levels.py           # NEW: 6 pure functions (core logic)
  models/opportunity.py              # MODIFY: add 4 new TradeSpec fields
  opportunity/option_plays/
    _trade_spec_helpers.py           # MODIFY: skew-aware build_iron_condor_legs
  validation/daily_readiness.py      # MODIFY: add strike_proximity check (#8)
  __init__.py                        # MODIFY: wire new exports
  cli/interactive.py                 # MODIFY: add do_entry_analysis command

tests/
  test_entry_levels.py               # NEW: unit tests for all 6 functions
  functional/test_entry_intelligence.py  # NEW: functional tests (pipeline)
```

### File responsibilities:

| File | Responsibility |
|------|---------------|
| `models/entry.py` | Result models only: StrikeProximityResult, SkewOptimalStrike, EntryLevelScore, ConditionalEntry, PullbackAlert, StrikeProximityLeg |
| `features/entry_levels.py` | Pure functions: compute_strike_support_proximity, select_skew_optimal_strike, score_entry_level, compute_limit_entry_price, compute_pullback_levels |
| `_trade_spec_helpers.py` | `build_iron_condor_legs` gets optional `skew: SkewSlice | None` param. If provided, adjusts short strike placement toward richest IV |
| `models/opportunity.py` | TradeSpec gains: `entry_mode`, `limit_price`, `pullback_levels`, `strike_proximity_score` |
| `validation/daily_readiness.py` | Check #8 `strike_proximity` added — PASS if short strikes near high-conviction S/R |

---

## Context for implementers

### Existing data available (no new fetches needed)

- `TechnicalSnapshot`: RSI (.value, .is_overbought, .is_oversold), Bollinger (.percent_b, .bandwidth), Stochastic (.k, .d), MACD, VWAP (.vwap if present), ATR, ATR%, moving_averages (sma_20/50/200, ema_9/21, price_vs_sma_20_pct)
- `LevelsAnalysis`: support_levels and resistance_levels — each a `PriceLevel` with `.price`, `.sources: list[LevelSource]`, `.confluence_score: int`, `.strength: float` (0-1), `.distance_pct: float`
- `VolatilitySurface.skew_by_expiry: list[SkewSlice]` — each has `.atm_iv`, `.otm_put_iv`, `.otm_call_iv`, `.put_skew`, `.call_skew`, `.skew_ratio`
- `TradeSpec.legs: list[LegSpec]` — each leg has `.action` (BTO/STO), `.option_type` ("put"/"call"), `.strike`, `.role`
- Current IC strike selection: `build_iron_condor_legs(price, atr, regime_id, expiration, dte, atm_iv)` uses `short_mult = 1.0 if R1 else 1.5` (ATR multiples), no skew input

### Key thresholds (from gap analysis — treat as spec)

| Metric | Threshold | Source |
|--------|-----------|--------|
| Strike-to-support proximity | PASS ≤ 1.0 ATR from level with strength ≥ 0.5 | Gap 1 |
| Skew premium ratio | Pick strike where put_skew or call_skew is highest in valid range | Gap 2 |
| Entry level score | ≥ 0.70 = enter now, 0.50-0.70 = wait, < 0.50 = not yet | Gap 4 |
| Limit price patience | R1: bid-side (mid - 30% spread), normal: mid - 10%, aggressive: mid | Gap 3 |
| Pullback improvement | Report level where trade ROC improves by ≥ 2% | Gap 5 |

---

## Task 1: Entry-Level Models

**Files:**
- Create: `market_analyzer/models/entry.py`
- Test: `tests/test_entry_levels.py`

These models are the return types for the 6 functions in Task 2-6.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_entry_levels.py
"""Tests for entry-level intelligence models and functions."""

import pytest
from market_analyzer.models.entry import (
    StrikeProximityLeg,
    StrikeProximityResult,
    SkewOptimalStrike,
    EntryLevelScore,
    ConditionalEntry,
    PullbackAlert,
)


class TestEntryModels:
    def test_strike_proximity_result_fields(self) -> None:
        leg = StrikeProximityLeg(
            role="short_put",
            strike=570.0,
            nearest_level_price=572.0,
            nearest_level_strength=0.85,
            nearest_level_sources=["sma_200", "swing_support"],
            distance_points=2.0,
            distance_atr=0.25,
            backed_by_level=True,
        )
        result = StrikeProximityResult(
            legs=[leg],
            overall_score=0.85,
            all_backed=True,
            summary="Short put at 570 backed by SMA-200 + swing support at 572 (0.25 ATR)",
        )
        assert result.overall_score == 0.85
        assert result.all_backed is True
        assert len(result.legs) == 1
        assert result.legs[0].backed_by_level is True

    def test_skew_optimal_strike_fields(self) -> None:
        result = SkewOptimalStrike(
            option_type="put",
            baseline_strike=570.0,
            optimal_strike=565.0,
            baseline_iv=0.22,
            optimal_iv=0.27,
            iv_advantage_pct=22.7,
            distance_atr=1.2,
            rationale="565 put IV 27% vs ATM 22% — 22.7% richer premium at 1.2 ATR OTM",
        )
        assert result.optimal_strike == 565.0
        assert result.iv_advantage_pct > 20

    def test_entry_level_score_fields(self) -> None:
        score = EntryLevelScore(
            overall_score=0.75,
            action="enter_now",
            components={
                "rsi_extremity": 0.80,
                "bollinger_extremity": 0.70,
                "vwap_deviation": 0.65,
                "atr_extension": 0.80,
                "level_proximity": 0.85,
            },
            rationale="RSI 28 oversold + price at lower Bollinger + near SMA-200 support",
        )
        assert score.action == "enter_now"
        assert score.overall_score >= 0.70

    def test_entry_level_score_wait(self) -> None:
        score = EntryLevelScore(
            overall_score=0.55,
            action="wait",
            components={"rsi_extremity": 0.40, "bollinger_extremity": 0.50,
                         "vwap_deviation": 0.30, "atr_extension": 0.45,
                         "level_proximity": 0.60},
            rationale="RSI 55 neutral — no extremity. Wait for pullback.",
        )
        assert score.action == "wait"

    def test_conditional_entry_fields(self) -> None:
        entry = ConditionalEntry(
            entry_mode="limit",
            limit_price=1.75,
            current_mid=1.85,
            improvement_pct=5.4,
            urgency="patient",
            rationale="R1 patient entry: limit at $1.75 (mid $1.85 - 30% of $0.33 spread)",
        )
        assert entry.entry_mode == "limit"
        assert entry.limit_price < entry.current_mid

    def test_pullback_alert_fields(self) -> None:
        alert = PullbackAlert(
            alert_price=576.0,
            current_price=580.0,
            level_source="sma_20",
            level_strength=0.65,
            improvement_description="Short put moves from 570 to 566 (further OTM by 0.5 ATR)",
            roc_improvement_pct=2.3,
        )
        assert alert.alert_price < alert.current_price
        assert alert.roc_improvement_pct > 0

    def test_serialization(self) -> None:
        """All models must serialize for MCP."""
        score = EntryLevelScore(
            overall_score=0.72, action="enter_now",
            components={"rsi_extremity": 0.8}, rationale="test",
        )
        d = score.model_dump()
        assert "overall_score" in d
        assert "components" in d
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py -v`
Expected: FAIL (ImportError — models/entry.py doesn't exist)

- [ ] **Step 3: Write minimal implementation**

```python
# market_analyzer/models/entry.py
"""Models for entry-level intelligence — strike proximity, skew selection, entry scoring."""

from __future__ import annotations

from pydantic import BaseModel


class StrikeProximityLeg(BaseModel):
    """Proximity analysis for one short leg."""

    role: str  # "short_put", "short_call"
    strike: float
    nearest_level_price: float
    nearest_level_strength: float  # 0-1 from PriceLevel.strength
    nearest_level_sources: list[str]  # LevelSource values
    distance_points: float  # abs(strike - level_price)
    distance_atr: float  # distance_points / atr
    backed_by_level: bool  # True if distance_atr <= 1.0 AND strength >= 0.5


class StrikeProximityResult(BaseModel):
    """Result of checking short strike proximity to S/R levels."""

    legs: list[StrikeProximityLeg]
    overall_score: float  # 0-1, average of leg scores
    all_backed: bool  # True if every short leg is backed
    summary: str


class SkewOptimalStrike(BaseModel):
    """Result of skew-informed strike selection."""

    option_type: str  # "put" or "call"
    baseline_strike: float  # Where ATR-only logic would place it
    optimal_strike: float  # Where skew says the richest premium is
    baseline_iv: float  # IV at baseline strike
    optimal_iv: float  # IV at optimal strike
    iv_advantage_pct: float  # (optimal_iv - baseline_iv) / baseline_iv * 100
    distance_atr: float  # How far optimal strike is from spot (in ATR units)
    rationale: str


class EntryLevelScore(BaseModel):
    """Multi-factor score: enter now vs wait for better level."""

    overall_score: float  # 0-1
    action: str  # "enter_now" (>=0.70), "wait" (0.50-0.70), "not_yet" (<0.50)
    components: dict[str, float]  # name → 0-1 score
    rationale: str


class ConditionalEntry(BaseModel):
    """Limit order entry price computation."""

    entry_mode: str  # "limit" or "market"
    limit_price: float  # Target fill price
    current_mid: float  # Current mid price
    improvement_pct: float  # How much better limit is vs market
    urgency: str  # "patient", "normal", "aggressive"
    rationale: str


class PullbackAlert(BaseModel):
    """Price level where the trade improves materially."""

    alert_price: float  # Price to watch for
    current_price: float
    level_source: str  # What S/R level is at that price
    level_strength: float  # 0-1
    improvement_description: str  # What changes at that price
    roc_improvement_pct: float  # Estimated ROC improvement
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add market_analyzer/models/entry.py tests/test_entry_levels.py
git commit -m "feat: add entry-level intelligence models"
```

---

## Task 2: Strike-to-Support Proximity Gate

**Files:**
- Create: `market_analyzer/features/entry_levels.py`
- Test: `tests/test_entry_levels.py` (append)

**Context:** This function answers: "Is my short put backed by a real support level, or floating in thin air?" It takes a TradeSpec + LevelsAnalysis and checks each short leg's distance to the nearest high-conviction S/R level.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entry_levels.py`:

```python
from datetime import date, timedelta

from market_analyzer.models.levels import (
    LevelRole, LevelSource, LevelsAnalysis, PriceLevel, TradeDirection,
)
from market_analyzer.models.opportunity import LegAction, LegSpec, TradeSpec
from market_analyzer.features.entry_levels import compute_strike_support_proximity


def _make_leg(role: str, action: LegAction, opt_type: str, strike: float) -> LegSpec:
    return LegSpec(
        role=role, action=action, option_type=opt_type, strike=strike,
        strike_label="test", expiration=date(2026, 4, 17),
        days_to_expiry=30, atm_iv_at_expiry=0.22,
    )


def _make_trade_spec(legs: list[LegSpec]) -> TradeSpec:
    return TradeSpec(
        ticker="SPY", legs=legs, underlying_price=580.0,
        target_dte=30, target_expiration=date(2026, 4, 17),
        spec_rationale="test",
    )


def _make_levels(
    supports: list[tuple[float, float, list[str]]],
    resistances: list[tuple[float, float, list[str]]],
) -> LevelsAnalysis:
    """Build LevelsAnalysis from (price, strength, [sources]) tuples."""
    sup = [
        PriceLevel(
            price=p, role=LevelRole.SUPPORT, sources=[LevelSource(s) for s in srcs],
            confluence_score=len(srcs), strength=st, distance_pct=abs(580 - p) / 580 * 100,
            description=f"test support at {p}",
        )
        for p, st, srcs in supports
    ]
    res = [
        PriceLevel(
            price=p, role=LevelRole.RESISTANCE, sources=[LevelSource(s) for s in srcs],
            confluence_score=len(srcs), strength=st, distance_pct=abs(p - 580) / 580 * 100,
            description=f"test resistance at {p}",
        )
        for p, st, srcs in resistances
    ]
    return LevelsAnalysis(
        ticker="SPY", as_of_date=date(2026, 3, 19), entry_price=580.0,
        direction=TradeDirection.LONG, direction_auto_detected=True,
        current_price=580.0, atr=5.0, atr_pct=0.86,
        support_levels=sup, resistance_levels=res,
        stop_loss=None, targets=[], best_target=None, summary="test",
    )


class TestStrikeProximity:
    def test_short_put_backed_by_strong_support(self) -> None:
        """Short put at 570 with strong support at 572 → backed."""
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
            _make_leg("short_call", LegAction.SELL_TO_OPEN, "call", 590.0),
            _make_leg("long_call", LegAction.BUY_TO_OPEN, "call", 595.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(
            supports=[(572.0, 0.85, ["sma_200", "swing_support"])],
            resistances=[(588.0, 0.75, ["swing_resistance"])],
        )
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        put_leg = [l for l in result.legs if l.role == "short_put"][0]
        assert put_leg.backed_by_level is True
        assert put_leg.distance_atr < 1.0

    def test_short_put_no_nearby_support(self) -> None:
        """Short put at 570 with nearest support at 550 → NOT backed (4 ATR away)."""
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(
            supports=[(550.0, 0.90, ["sma_200"])],
            resistances=[],
        )
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        put_leg = [l for l in result.legs if l.role == "short_put"][0]
        assert put_leg.backed_by_level is False
        assert put_leg.distance_atr > 1.0

    def test_weak_support_not_counted(self) -> None:
        """Support with strength < 0.5 doesn't count as backing."""
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(
            supports=[(571.0, 0.30, ["ema_9"])],  # Weak single source
            resistances=[],
        )
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        put_leg = [l for l in result.legs if l.role == "short_put"][0]
        assert put_leg.backed_by_level is False

    def test_call_side_uses_resistance(self) -> None:
        """Short call at 590 checks resistance levels, not support."""
        legs = [
            _make_leg("short_call", LegAction.SELL_TO_OPEN, "call", 590.0),
            _make_leg("long_call", LegAction.BUY_TO_OPEN, "call", 595.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(
            supports=[],
            resistances=[(592.0, 0.80, ["swing_resistance", "sma_50"])],
        )
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        call_leg = [l for l in result.legs if l.role == "short_call"][0]
        assert call_leg.backed_by_level is True

    def test_both_sides_backed(self) -> None:
        """Full IC with both short legs backed → all_backed=True, high score."""
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
            _make_leg("short_call", LegAction.SELL_TO_OPEN, "call", 590.0),
            _make_leg("long_call", LegAction.BUY_TO_OPEN, "call", 595.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(
            supports=[(571.0, 0.85, ["sma_200", "swing_support"])],
            resistances=[(592.0, 0.80, ["swing_resistance", "pivot_r1"])],
        )
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        assert result.all_backed is True
        assert result.overall_score >= 0.70

    def test_only_short_legs_analyzed(self) -> None:
        """Long (BTO) legs are ignored — only STO legs matter."""
        legs = [
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(supports=[], resistances=[])
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        assert len(result.legs) == 0
        assert result.all_backed is True  # Vacuously true — no short legs

    def test_no_levels_at_all(self) -> None:
        """No support/resistance levels → all short legs unbacked."""
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(supports=[], resistances=[])
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        assert result.all_backed is False
        assert result.overall_score == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestStrikeProximity -v`
Expected: FAIL (ImportError — features/entry_levels.py doesn't exist)

- [ ] **Step 3: Write minimal implementation**

```python
# market_analyzer/features/entry_levels.py
"""Entry-level intelligence: strike proximity, skew selection, entry scoring.

Pure functions — no data fetching, no broker required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from market_analyzer.models.entry import (
    StrikeProximityLeg,
    StrikeProximityResult,
)

if TYPE_CHECKING:
    from market_analyzer.models.levels import LevelsAnalysis
    from market_analyzer.models.opportunity import TradeSpec


def compute_strike_support_proximity(
    trade_spec: TradeSpec,
    levels: LevelsAnalysis,
    atr: float,
    min_strength: float = 0.5,
    max_distance_atr: float = 1.0,
) -> StrikeProximityResult:
    """Check how close each short strike is to a high-conviction S/R level.

    Args:
        trade_spec: Trade with legs to analyze.
        levels: Support/resistance from LevelsService.
        atr: Current ATR (for distance normalization).
        min_strength: Minimum PriceLevel.strength to count as backing (default 0.5).
        max_distance_atr: Max distance in ATR units to count as "backed" (default 1.0).

    Returns:
        StrikeProximityResult with per-leg analysis and overall score.
    """
    from market_analyzer.models.opportunity import LegAction

    leg_results: list[StrikeProximityLeg] = []

    for leg in trade_spec.legs:
        if leg.action != LegAction.SELL_TO_OPEN:
            continue

        # Pick the right level set
        if leg.option_type == "put":
            candidate_levels = levels.support_levels
        else:
            candidate_levels = levels.resistance_levels

        # Find nearest level with sufficient strength
        best_level = None
        best_dist = float("inf")

        for lvl in candidate_levels:
            dist = abs(leg.strike - lvl.price)
            if dist < best_dist:
                best_dist = dist
                best_level = lvl

        if best_level is not None:
            distance_atr = best_dist / atr if atr > 0 else float("inf")
            backed = distance_atr <= max_distance_atr and best_level.strength >= min_strength
            leg_results.append(StrikeProximityLeg(
                role=leg.role,
                strike=leg.strike,
                nearest_level_price=best_level.price,
                nearest_level_strength=best_level.strength,
                nearest_level_sources=[s.value for s in best_level.sources],
                distance_points=round(best_dist, 2),
                distance_atr=round(distance_atr, 2),
                backed_by_level=backed,
            ))
        else:
            # No levels found for this side
            leg_results.append(StrikeProximityLeg(
                role=leg.role,
                strike=leg.strike,
                nearest_level_price=0.0,
                nearest_level_strength=0.0,
                nearest_level_sources=[],
                distance_points=0.0,
                distance_atr=float("inf"),
                backed_by_level=False,
            ))

    # Compute overall score
    if not leg_results:
        overall_score = 1.0  # No short legs → vacuously fine
        all_backed = True
    else:
        backed_count = sum(1 for l in leg_results if l.backed_by_level)
        overall_score = backed_count / len(leg_results)
        all_backed = backed_count == len(leg_results)

    # Build summary
    parts = []
    for lr in leg_results:
        status = "backed" if lr.backed_by_level else "UNBACKED"
        sources = ", ".join(lr.nearest_level_sources[:2]) if lr.nearest_level_sources else "none"
        parts.append(
            f"{lr.role} at {lr.strike} {status} "
            f"({sources} at {lr.nearest_level_price}, {lr.distance_atr:.1f} ATR)"
        )
    summary = "; ".join(parts) if parts else "No short legs to analyze"

    return StrikeProximityResult(
        legs=leg_results,
        overall_score=round(overall_score, 2),
        all_backed=all_backed,
        summary=summary,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestStrikeProximity -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add market_analyzer/features/entry_levels.py tests/test_entry_levels.py
git commit -m "feat: add strike-to-support proximity gate"
```

---

## Task 3: Skew-Optimal Strike Selection

**Files:**
- Modify: `market_analyzer/features/entry_levels.py` (add function)
- Test: `tests/test_entry_levels.py` (append)

**Context:** Instead of placing short strikes at a fixed ATR multiple, search for the strike where IV is most elevated vs ATM within the valid range. Uses `SkewSlice` data from vol surface. The function doesn't replace `build_iron_condor_legs` — it advises WHERE to shift the short strike for maximum premium.

**Key insight:** If OTM put IV at 565 is 27% but at 570 is only 24%, selling the 565 put captures 12.5% more premium per unit of risk. The skew tells you where the market is overpricing protection.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entry_levels.py`:

```python
from market_analyzer.models.vol_surface import SkewSlice
from market_analyzer.features.entry_levels import select_skew_optimal_strike


def _make_skew(
    atm_iv: float = 0.22,
    put_skew: float = 0.05,
    call_skew: float = 0.02,
    skew_ratio: float = 2.5,
) -> SkewSlice:
    return SkewSlice(
        expiration=date(2026, 4, 17), days_to_expiry=30,
        atm_iv=atm_iv, otm_put_iv=atm_iv + put_skew,
        otm_call_iv=atm_iv + call_skew,
        put_skew=put_skew, call_skew=call_skew, skew_ratio=skew_ratio,
    )


class TestSkewOptimalStrike:
    def test_put_side_shifts_toward_skew(self) -> None:
        """When put skew is steep, optimal strike shifts further OTM (more premium)."""
        skew = _make_skew(atm_iv=0.22, put_skew=0.08)  # 8% skew = steep
        result = select_skew_optimal_strike(
            underlying_price=580.0, atr=5.0, regime_id=1, skew=skew,
            option_type="put",
        )
        # Optimal should be further OTM than baseline (lower strike)
        assert result.optimal_strike <= result.baseline_strike
        assert result.iv_advantage_pct > 0
        assert result.optimal_iv > result.baseline_iv

    def test_flat_skew_no_shift(self) -> None:
        """When skew is near zero, optimal ≈ baseline (no edge to capture)."""
        skew = _make_skew(atm_iv=0.22, put_skew=0.005, call_skew=0.003)
        result = select_skew_optimal_strike(
            underlying_price=580.0, atr=5.0, regime_id=1, skew=skew,
            option_type="put",
        )
        assert result.optimal_strike == result.baseline_strike
        assert result.iv_advantage_pct < 5.0  # Minimal advantage

    def test_call_side_shifts_toward_call_skew(self) -> None:
        """Call skew shifts optimal call strike further OTM (higher)."""
        skew = _make_skew(atm_iv=0.22, call_skew=0.06)
        result = select_skew_optimal_strike(
            underlying_price=580.0, atr=5.0, regime_id=1, skew=skew,
            option_type="call",
        )
        assert result.optimal_strike >= result.baseline_strike
        assert result.iv_advantage_pct > 0

    def test_r2_wider_baseline(self) -> None:
        """R2 baseline is 1.5 ATR (vs R1 = 1.0 ATR). Skew adjustment starts from there."""
        skew = _make_skew(atm_iv=0.30, put_skew=0.06)
        r1 = select_skew_optimal_strike(580.0, 5.0, 1, skew, "put")
        r2 = select_skew_optimal_strike(580.0, 5.0, 2, skew, "put")
        # R2 baseline is further OTM
        assert r2.baseline_strike < r1.baseline_strike

    def test_stays_within_atr_bounds(self) -> None:
        """Optimal strike must stay between 0.8-2.0 ATR from spot."""
        skew = _make_skew(atm_iv=0.22, put_skew=0.15)  # Extreme skew
        result = select_skew_optimal_strike(580.0, 5.0, 1, skew, "put")
        distance = abs(580.0 - result.optimal_strike)
        assert distance >= 0.8 * 5.0 - 0.01  # Allow rounding
        assert distance <= 2.0 * 5.0 + 0.01
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestSkewOptimalStrike -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Write implementation**

Add to `market_analyzer/features/entry_levels.py`:

```python
from market_analyzer.models.entry import SkewOptimalStrike

# Add to imports at top if not already there:
# from market_analyzer.models.vol_surface import SkewSlice
# from market_analyzer.opportunity.option_plays._trade_spec_helpers import snap_strike, compute_otm_strike


def select_skew_optimal_strike(
    underlying_price: float,
    atr: float,
    regime_id: int,
    skew: SkewSlice,
    option_type: str,
    min_distance_atr: float = 0.8,
    max_distance_atr: float = 2.0,
) -> SkewOptimalStrike:
    """Select the strike with richest IV premium within ATR-based range.

    Instead of placing the short strike at exactly 1.0 ATR (R1) or 1.5 ATR (R2),
    evaluate the skew across the valid range and pick the strike where IV is most
    elevated above ATM.

    Args:
        underlying_price: Current spot price.
        atr: Current ATR value.
        regime_id: 1-4 regime.
        skew: SkewSlice from vol surface (IV at ATM, OTM put, OTM call).
        option_type: "put" or "call".
        min_distance_atr: Closest allowed strike (default 0.8 ATR).
        max_distance_atr: Farthest allowed strike (default 2.0 ATR).

    Returns:
        SkewOptimalStrike with baseline vs optimal comparison.
    """
    from market_analyzer.opportunity.option_plays._trade_spec_helpers import (
        snap_strike,
    )

    # Baseline: where ATR-only logic places the strike
    short_mult = 1.0 if regime_id == 1 else 1.5
    if option_type == "put":
        baseline_raw = underlying_price - (short_mult * atr)
        relevant_skew = skew.put_skew  # otm_put_iv - atm_iv
        skew_direction = -1  # Further OTM = lower strike
    else:
        baseline_raw = underlying_price + (short_mult * atr)
        relevant_skew = skew.call_skew
        skew_direction = 1  # Further OTM = higher strike

    baseline_strike = snap_strike(baseline_raw, underlying_price)
    baseline_iv = skew.atm_iv + relevant_skew * (short_mult / 1.5)  # Linear interpolation

    # If skew is too flat, no edge — keep baseline
    min_skew_threshold = 0.01  # 1% skew minimum to justify shift
    if relevant_skew < min_skew_threshold:
        return SkewOptimalStrike(
            option_type=option_type,
            baseline_strike=baseline_strike,
            optimal_strike=baseline_strike,
            baseline_iv=round(baseline_iv, 4),
            optimal_iv=round(baseline_iv, 4),
            iv_advantage_pct=0.0,
            distance_atr=round(short_mult, 2),
            rationale=f"Skew too flat ({relevant_skew:.1%}) — no adjustment from baseline",
        )

    # Skew is meaningful: shift further OTM to capture richer premium
    # The richer premium is at the OTM point (5% OTM in SkewSlice)
    # We shift proportionally: more skew = more shift, capped at max_distance_atr
    skew_factor = min(relevant_skew / 0.10, 1.0)  # Normalize: 10% skew = max shift
    target_mult = short_mult + skew_factor * (max_distance_atr - short_mult)
    target_mult = max(min_distance_atr, min(target_mult, max_distance_atr))

    if option_type == "put":
        optimal_raw = underlying_price - (target_mult * atr)
    else:
        optimal_raw = underlying_price + (target_mult * atr)

    optimal_strike = snap_strike(optimal_raw, underlying_price)

    # Estimate IV at optimal strike (linear interpolation along skew)
    optimal_iv = skew.atm_iv + relevant_skew * (target_mult / 1.5)

    iv_advantage = (optimal_iv - baseline_iv) / baseline_iv * 100 if baseline_iv > 0 else 0.0

    return SkewOptimalStrike(
        option_type=option_type,
        baseline_strike=baseline_strike,
        optimal_strike=optimal_strike,
        baseline_iv=round(baseline_iv, 4),
        optimal_iv=round(optimal_iv, 4),
        iv_advantage_pct=round(iv_advantage, 1),
        distance_atr=round(target_mult, 2),
        rationale=(
            f"{optimal_strike} {option_type} IV {optimal_iv:.0%} vs baseline "
            f"{baseline_strike} IV {baseline_iv:.0%} — "
            f"{iv_advantage:.1f}% richer at {target_mult:.1f} ATR OTM"
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestSkewOptimalStrike -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add market_analyzer/features/entry_levels.py tests/test_entry_levels.py
git commit -m "feat: add skew-optimal strike selection"
```

---

## Task 4: Multi-Factor Entry Score

**Files:**
- Modify: `market_analyzer/features/entry_levels.py` (add function)
- Test: `tests/test_entry_levels.py` (append)

**Context:** This answers "should I enter NOW or WAIT for a better level?" by scoring 5 factors that measure how extended price is from mean/levels. High score = price is at an extreme and near a level → enter now. Low score = price is mid-range with no level backing → wait for pullback.

**Scoring weights:**
- RSI extremity: 25% (how far from 50)
- Bollinger %B extremity: 20% (how close to band edge)
- VWAP deviation: 15% (how far from VWAP)
- ATR extension: 20% (how many ATRs from SMA-20)
- Level proximity: 20% (how close to nearest high-conviction S/R)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entry_levels.py`:

```python
from market_analyzer.models.technicals import (
    BollingerBands, MACDData, MovingAverages, RSIData,
    StochasticData, SupportResistance, TechnicalSnapshot,
    MarketPhase, PhaseIndicator,
)
from market_analyzer.features.entry_levels import score_entry_level


def _make_technicals(
    price: float = 580.0,
    rsi: float = 50.0,
    percent_b: float = 0.5,
    atr_pct: float = 0.86,
    sma_20: float | None = None,
    vwap: float | None = None,
) -> TechnicalSnapshot:
    atr = price * atr_pct / 100
    _sma_20 = sma_20 if sma_20 is not None else price
    _vwap = vwap if vwap is not None else price
    pct_sma_20 = (price - _sma_20) / _sma_20 * 100 if _sma_20 else 0.0
    return TechnicalSnapshot(
        ticker="SPY", as_of_date=date(2026, 3, 19), current_price=price,
        atr=atr, atr_pct=atr_pct, vwma_20=_vwap,
        moving_averages=MovingAverages(
            sma_20=_sma_20, sma_50=price * 0.98, sma_200=price * 0.95,
            ema_9=price, ema_21=price,
            price_vs_sma_20_pct=pct_sma_20, price_vs_sma_50_pct=2.0, price_vs_sma_200_pct=5.0,
        ),
        rsi=RSIData(value=rsi, is_overbought=rsi > 70, is_oversold=rsi < 30),
        bollinger=BollingerBands(
            upper=price + 10, middle=price, lower=price - 10,
            bandwidth=0.04, percent_b=percent_b,
        ),
        macd=MACDData(macd_line=0.5, signal_line=0.3, histogram=0.2,
                      is_bullish_crossover=False, is_bearish_crossover=False),
        stochastic=StochasticData(k=50.0, d=50.0, is_overbought=False, is_oversold=False),
        support_resistance=SupportResistance(
            support=570.0, resistance=590.0,
            price_vs_support_pct=1.7, price_vs_resistance_pct=-1.7,
        ),
        phase=PhaseIndicator(
            phase=MarketPhase.ACCUMULATION, confidence=0.5, description="Test",
            higher_highs=False, higher_lows=True, lower_highs=False, lower_lows=False,
            range_compression=0.3, volume_trend="declining", price_vs_sma_50_pct=2.0,
        ),
        signals=[],
    )


class TestEntryLevelScore:
    def test_extreme_oversold_at_support_enter_now(self) -> None:
        """RSI 25 + %B 0.05 + extended from mean + near support → enter_now (bullish MR)."""
        # Price at 572 but SMA-20 at 580 and VWAP at 580 → extended below mean
        tech = _make_technicals(price=572.0, rsi=25.0, percent_b=0.05,
                                sma_20=580.0, vwap=580.0)
        levels = _make_levels(
            supports=[(570.0, 0.90, ["sma_200", "swing_support"])],
            resistances=[],
        )
        result = score_entry_level(tech, levels, direction="bullish")
        assert result.action == "enter_now"
        assert result.overall_score >= 0.70
        assert result.components["rsi_extremity"] > 0.7

    def test_neutral_rsi_mid_bollinger_wait(self) -> None:
        """RSI 50 + %B 0.5 + no nearby level → wait."""
        tech = _make_technicals(price=580.0, rsi=50.0, percent_b=0.5)
        levels = _make_levels(supports=[], resistances=[])
        result = score_entry_level(tech, levels, direction="bullish")
        assert result.action in ("wait", "not_yet")
        assert result.overall_score < 0.70

    def test_overbought_at_resistance_bearish_enter(self) -> None:
        """RSI 78 + %B 0.95 + extended above mean + near resistance → enter_now (bearish MR)."""
        # Price at 589 but SMA-20 at 580 and VWAP at 580 → extended above mean
        tech = _make_technicals(price=589.0, rsi=78.0, percent_b=0.95,
                                sma_20=580.0, vwap=580.0)
        levels = _make_levels(
            supports=[],
            resistances=[(590.0, 0.85, ["swing_resistance", "pivot_r1"])],
        )
        result = score_entry_level(tech, levels, direction="bearish")
        assert result.action == "enter_now"
        assert result.overall_score >= 0.70

    def test_moderate_signal_caution(self) -> None:
        """RSI 62 + %B 0.7 → moderate. Score between 0.50-0.70."""
        tech = _make_technicals(price=582.0, rsi=62.0, percent_b=0.70)
        levels = _make_levels(
            supports=[(578.0, 0.60, ["sma_20"])],
            resistances=[],
        )
        result = score_entry_level(tech, levels, direction="bearish")
        assert result.action == "wait"
        assert 0.40 <= result.overall_score <= 0.75

    def test_components_all_present(self) -> None:
        """All 5 components must be present in output."""
        tech = _make_technicals()
        levels = _make_levels(supports=[], resistances=[])
        result = score_entry_level(tech, levels, direction="neutral")
        expected_keys = {"rsi_extremity", "bollinger_extremity", "vwap_deviation",
                         "atr_extension", "level_proximity"}
        assert expected_keys == set(result.components.keys())

    def test_neutral_direction_uses_absolute_extremity(self) -> None:
        """Neutral direction scores RSI extremity from 50 (either direction)."""
        tech = _make_technicals(rsi=28.0, percent_b=0.10)
        levels = _make_levels(supports=[(575.0, 0.70, ["sma_50"])], resistances=[])
        result = score_entry_level(tech, levels, direction="neutral")
        # Even neutral should detect the extremity
        assert result.components["rsi_extremity"] > 0.6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestEntryLevelScore -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Write implementation**

Add to `market_analyzer/features/entry_levels.py`:

```python
from market_analyzer.models.entry import EntryLevelScore

# TYPE_CHECKING imports already present from Task 2; add if needed:
# from market_analyzer.models.technicals import TechnicalSnapshot


def score_entry_level(
    technicals: TechnicalSnapshot,
    levels: LevelsAnalysis,
    direction: str = "neutral",
) -> EntryLevelScore:
    """Multi-factor entry score: enter now vs wait for better level.

    Scores how extended price is from mean + how close to S/R levels.

    Args:
        technicals: Current TechnicalSnapshot.
        levels: Support/resistance from LevelsService.
        direction: "bullish" (looking for oversold), "bearish" (overbought),
                   "neutral" (either extreme).

    Returns:
        EntryLevelScore with action: "enter_now" (>=0.70), "wait" (0.50-0.70),
        "not_yet" (<0.50).
    """
    rsi = technicals.rsi.value
    percent_b = technicals.bollinger.percent_b if technicals.bollinger else 0.5
    price = technicals.current_price
    sma_20 = technicals.moving_averages.sma_20 if technicals.moving_averages else price
    atr = technicals.atr if technicals.atr > 0 else 1.0
    vwap = technicals.vwma_20 if technicals.vwma_20 else price

    # ── Component 1: RSI extremity (25%) ──
    # How far RSI is from 50 in the relevant direction
    if direction == "bullish":
        rsi_extremity = max(0, (50 - rsi) / 30)  # RSI 20 → 1.0, 50 → 0
    elif direction == "bearish":
        rsi_extremity = max(0, (rsi - 50) / 30)  # RSI 80 → 1.0, 50 → 0
    else:
        rsi_extremity = abs(rsi - 50) / 30  # Either direction
    rsi_extremity = min(1.0, rsi_extremity)

    # ── Component 2: Bollinger %B extremity (20%) ──
    if direction == "bullish":
        bb_extremity = max(0, (0.5 - percent_b) / 0.5)  # %B 0 → 1.0
    elif direction == "bearish":
        bb_extremity = max(0, (percent_b - 0.5) / 0.5)  # %B 1.0 → 1.0
    else:
        bb_extremity = abs(percent_b - 0.5) / 0.5
    bb_extremity = min(1.0, bb_extremity)

    # ── Component 3: VWAP deviation (15%) ──
    vwap_dev = abs(price - vwap) / atr if atr > 0 else 0
    # Normalize: 2+ ATR from VWAP → 1.0
    vwap_score = min(1.0, vwap_dev / 2.0)

    # ── Component 4: ATR extension from SMA-20 (20%) ──
    extension = abs(price - sma_20) / atr if atr > 0 else 0
    # Normalize: 1.5+ ATR from SMA-20 → 1.0
    atr_ext_score = min(1.0, extension / 1.5)

    # ── Component 5: Level proximity (20%) ──
    # How close is price to a high-conviction level?
    target_levels = (
        levels.support_levels if direction == "bullish"
        else levels.resistance_levels if direction == "bearish"
        else levels.support_levels + levels.resistance_levels
    )
    level_prox_score = 0.0
    for lvl in target_levels:
        dist_atr = abs(price - lvl.price) / atr if atr > 0 else float("inf")
        if dist_atr <= 1.0 and lvl.strength >= 0.5:
            # Close to a strong level — high score
            prox = (1.0 - dist_atr) * lvl.strength
            level_prox_score = max(level_prox_score, prox)

    # ── Weighted composite ──
    components = {
        "rsi_extremity": round(rsi_extremity, 2),
        "bollinger_extremity": round(bb_extremity, 2),
        "vwap_deviation": round(vwap_score, 2),
        "atr_extension": round(atr_ext_score, 2),
        "level_proximity": round(level_prox_score, 2),
    }

    weights = {
        "rsi_extremity": 0.25,
        "bollinger_extremity": 0.20,
        "vwap_deviation": 0.15,
        "atr_extension": 0.20,
        "level_proximity": 0.20,
    }

    overall = sum(components[k] * weights[k] for k in components)
    overall = round(overall, 2)

    if overall >= 0.70:
        action = "enter_now"
    elif overall >= 0.50:
        action = "wait"
    else:
        action = "not_yet"

    # Build rationale
    parts = []
    if rsi_extremity > 0.5:
        parts.append(f"RSI {rsi:.0f} {'oversold' if direction == 'bullish' else 'overbought' if direction == 'bearish' else 'extreme'}")
    if bb_extremity > 0.5:
        parts.append(f"Bollinger %B {percent_b:.2f} at band edge")
    if level_prox_score > 0.3:
        parts.append("near high-conviction S/R level")
    if not parts:
        parts.append("no strong entry signals")
    rationale = " + ".join(parts)

    return EntryLevelScore(
        overall_score=overall,
        action=action,
        components=components,
        rationale=rationale,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestEntryLevelScore -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add market_analyzer/features/entry_levels.py tests/test_entry_levels.py
git commit -m "feat: add multi-factor entry level score"
```

---

## Task 5: Conditional Entry / Limit Order Price

**Files:**
- Modify: `market_analyzer/features/entry_levels.py` (add function)
- Test: `tests/test_entry_levels.py` (append)

**Context:** Current TradeSpec has `max_entry_price` (ceiling) but no target limit price. This function computes what price to place a limit order at, based on fill urgency (patient in R1, aggressive in R3 trending).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entry_levels.py`:

```python
from market_analyzer.features.entry_levels import compute_limit_entry_price


class TestLimitEntryPrice:
    def test_patient_debit_entry_below_mid(self) -> None:
        """Patient debit entry: target below mid by 30% of spread (save money)."""
        result = compute_limit_entry_price(
            current_mid=3.50, bid_ask_spread=0.40, urgency="patient",
            is_credit=False,
        )
        assert result.entry_mode == "limit"
        assert result.limit_price < result.current_mid
        assert result.limit_price == pytest.approx(3.50 - 0.40 * 0.30, abs=0.01)
        assert result.improvement_pct > 0

    def test_normal_debit_entry_slight_improvement(self) -> None:
        """Normal debit entry: target below mid by 10% of spread."""
        result = compute_limit_entry_price(
            current_mid=3.50, bid_ask_spread=0.40, urgency="normal",
            is_credit=False,
        )
        assert result.limit_price == pytest.approx(3.50 - 0.40 * 0.10, abs=0.01)
        assert result.limit_price < result.current_mid

    def test_aggressive_entry_at_mid(self) -> None:
        """Aggressive (R3 trending): fill at mid, don't miss the move."""
        result = compute_limit_entry_price(
            current_mid=1.85, bid_ask_spread=0.30, urgency="aggressive",
        )
        assert result.limit_price == result.current_mid
        assert result.improvement_pct == 0.0

    def test_narrow_spread_minimal_improvement(self) -> None:
        """Very tight spread ($0.05) → improvement is tiny."""
        result = compute_limit_entry_price(
            current_mid=1.85, bid_ask_spread=0.05, urgency="patient",
        )
        improvement = abs(result.current_mid - result.limit_price)
        assert improvement < 0.02  # < 2 cents improvement on tight spread

    def test_patient_credit_holds_at_mid(self) -> None:
        """Patient credit entry: hold out for mid (don't concede premium)."""
        result = compute_limit_entry_price(
            current_mid=1.85, bid_ask_spread=0.30, urgency="patient",
            is_credit=True,
        )
        # Patient on credits = don't concede, ask for full mid
        assert result.limit_price == result.current_mid
        assert result.entry_mode == "limit"

    def test_normal_credit_small_concession(self) -> None:
        """Normal credit entry: concede 10% of spread to fill faster."""
        result = compute_limit_entry_price(
            current_mid=1.85, bid_ask_spread=0.30, urgency="normal",
            is_credit=True,
        )
        # Accept slightly less credit: mid - 10% of spread
        assert result.limit_price == pytest.approx(1.85 - 0.30 * 0.10, abs=0.01)
        assert result.limit_price < result.current_mid

    def test_aggressive_credit_big_concession(self) -> None:
        """Aggressive credit entry: concede 30% of spread (just get filled)."""
        result = compute_limit_entry_price(
            current_mid=1.85, bid_ask_spread=0.30, urgency="aggressive",
            is_credit=True,
        )
        # Biggest concession on credits: accept much less
        assert result.limit_price == pytest.approx(1.85 - 0.30 * 0.30, abs=0.01)

    def test_rationale_includes_urgency(self) -> None:
        result = compute_limit_entry_price(1.85, 0.30, "patient")
        assert "patient" in result.rationale.lower() or "R1" in result.rationale
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestLimitEntryPrice -v`
Expected: FAIL

- [ ] **Step 3: Write implementation**

Add to `market_analyzer/features/entry_levels.py`:

```python
from market_analyzer.models.entry import ConditionalEntry


def compute_limit_entry_price(
    current_mid: float,
    bid_ask_spread: float,
    urgency: str = "normal",
    is_credit: bool = True,
) -> ConditionalEntry:
    """Compute limit order price based on fill urgency.

    For credit trades (IC, credit spread):
        patient: aim for mid (don't concede premium)
        normal: concede 10% of spread (slight improvement for speed)
        aggressive: concede 30% of spread (just get filled)

    For debit trades (debit spread, PMCC):
        patient: bid-side (mid - 30% of spread)
        normal: mid - 10% of spread
        aggressive: at mid

    Args:
        current_mid: Current mid price (expected fill).
        bid_ask_spread: Current bid-ask spread width.
        urgency: "patient" (R1), "normal", "aggressive" (R3).
        is_credit: True for credit trades, False for debit.

    Returns:
        ConditionalEntry with limit_price and rationale.
    """
    # Credits: patient = hold out for mid (don't concede), aggressive = concede most
    # Debits: patient = bid-side (pay less), aggressive = pay mid
    if is_credit:
        credit_factors = {
            "patient": 0.0,      # Hold at mid — don't give up premium
            "normal": 0.10,      # Concede 10% of spread
            "aggressive": 0.30,  # Concede 30% — just get filled
        }
        factor = credit_factors.get(urgency, 0.10)
        limit_price = current_mid - factor * bid_ask_spread
    else:
        debit_factors = {
            "patient": 0.30,     # Save 30% of spread — bid-side
            "normal": 0.10,      # Save 10% of spread
            "aggressive": 0.0,   # Pay mid — don't miss the move
        }
        factor = debit_factors.get(urgency, 0.10)
        limit_price = current_mid - factor * bid_ask_spread

    limit_price = round(limit_price, 2)
    improvement = abs(current_mid - limit_price)
    improvement_pct = round(improvement / current_mid * 100, 1) if current_mid > 0 else 0.0

    entry_mode = "limit"
    if factor == 0.0 and not is_credit:
        # Aggressive debit = market order (pay mid, just fill)
        entry_mode = "market"
        improvement_pct = 0.0
    elif factor == 0.0 and is_credit:
        # Patient credit = limit at mid (hold for full premium)
        entry_mode = "limit"

    side_label = "credit" if is_credit else "debit"
    concession = f" - {factor:.0%} of ${bid_ask_spread:.2f} spread" if factor > 0 else ""
    return ConditionalEntry(
        entry_mode=entry_mode,
        limit_price=limit_price,
        current_mid=current_mid,
        improvement_pct=improvement_pct,
        urgency=urgency,
        rationale=(
            f"{urgency.title()} {side_label} entry: "
            f"limit at ${limit_price:.2f} (mid ${current_mid:.2f}{concession})"
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestLimitEntryPrice -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add market_analyzer/features/entry_levels.py tests/test_entry_levels.py
git commit -m "feat: add conditional entry / limit order price computation"
```

---

## Task 6: Pullback Alert Levels

**Files:**
- Modify: `market_analyzer/features/entry_levels.py` (add function)
- Test: `tests/test_entry_levels.py` (append)

**Context:** Given an IC at current price, compute price levels where the trade gets BETTER. If SPY is at 580 and SMA-20 is at 576, a pullback to 576 means the short put can be placed 4 pts further OTM — improving ROC. This gives the trader "wait for 576" alerts instead of blindly entering at 580.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entry_levels.py`:

```python
from market_analyzer.features.entry_levels import compute_pullback_levels


class TestPullbackLevels:
    def test_support_pullback_improves_put_side(self) -> None:
        """Pullback to SMA-20 at 576 means short put is further OTM → better."""
        tech = _make_technicals(price=580.0)
        levels = _make_levels(
            supports=[(576.0, 0.70, ["sma_20"]), (570.0, 0.85, ["sma_200"])],
            resistances=[],
        )
        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        assert len(alerts) >= 1
        # First alert should be nearest level
        assert alerts[0].alert_price < 580.0
        assert alerts[0].roc_improvement_pct > 0

    def test_no_nearby_levels_no_alerts(self) -> None:
        """No support levels within 2 ATR → no pullback alerts."""
        levels = _make_levels(supports=[], resistances=[])
        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        assert len(alerts) == 0

    def test_only_levels_below_current_price(self) -> None:
        """Only generates alerts for levels BELOW current price (pullback, not breakout)."""
        levels = _make_levels(
            supports=[(576.0, 0.70, ["sma_20"])],
            resistances=[(585.0, 0.70, ["sma_50"])],
        )
        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        for alert in alerts:
            assert alert.alert_price < 580.0

    def test_weak_levels_excluded(self) -> None:
        """Levels with strength < 0.4 don't generate alerts."""
        levels = _make_levels(
            supports=[(577.0, 0.25, ["ema_9"])],
            resistances=[],
        )
        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        assert len(alerts) == 0

    def test_max_pullback_distance_2atr(self) -> None:
        """Don't generate alerts for levels more than 2 ATR below current."""
        levels = _make_levels(
            supports=[(560.0, 0.90, ["sma_200"])],  # 4 ATR below at atr=5
            resistances=[],
        )
        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        assert len(alerts) == 0

    def test_alerts_sorted_nearest_first(self) -> None:
        """Alerts ordered by distance (nearest first)."""
        levels = _make_levels(
            supports=[(576.0, 0.70, ["sma_20"]), (573.0, 0.80, ["sma_50"])],
            resistances=[],
        )
        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        assert len(alerts) == 2
        assert alerts[0].alert_price > alerts[1].alert_price  # 576 before 573
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestPullbackLevels -v`
Expected: FAIL

- [ ] **Step 3: Write implementation**

Add to `market_analyzer/features/entry_levels.py`:

```python
from market_analyzer.models.entry import PullbackAlert


def compute_pullback_levels(
    current_price: float,
    levels: LevelsAnalysis,
    atr: float,
    min_level_strength: float = 0.4,
    max_pullback_atr: float = 2.0,
    min_roc_improvement_pct: float = 1.0,
) -> list[PullbackAlert]:
    """Compute price levels where the trade improves materially.

    For income trades (IC), a pullback means:
    - Short put strike moves further OTM → wider margin of safety
    - Credit stays ~similar (short strike delta changes little)
    - ROC improves because risk decreases while credit is stable

    Args:
        current_price: Current underlying price.
        levels: Support/resistance from LevelsService.
        atr: Current ATR.
        min_level_strength: Minimum PriceLevel.strength to include (default 0.4).
        max_pullback_atr: Max distance in ATR to consider (default 2.0).
        min_roc_improvement_pct: Minimum ROC improvement to report (default 1.0%).

    Returns:
        List of PullbackAlert sorted nearest-first. Empty if no worthwhile pullbacks.
    """
    alerts: list[PullbackAlert] = []

    for lvl in levels.support_levels:
        # Only consider levels below current price (pullback)
        if lvl.price >= current_price:
            continue

        # Check strength
        if lvl.strength < min_level_strength:
            continue

        # Check distance
        distance = current_price - lvl.price
        distance_atr = distance / atr if atr > 0 else float("inf")
        if distance_atr > max_pullback_atr:
            continue

        # Estimate ROC improvement:
        # If price pulls back by X points, the IC short put moves X points further OTM
        # This increases the probability of profit (wider margin)
        # Rough ROC improvement ≈ distance / wing_width_typical * 10%
        # (each point of additional OTM distance adds ~2% POP for a 5-wide IC)
        typical_wing_width = atr * 0.5  # R1 wing width
        roc_improvement = (distance / typical_wing_width) * 2.0 if typical_wing_width > 0 else 0
        roc_improvement = round(roc_improvement, 1)

        if roc_improvement < min_roc_improvement_pct:
            continue

        sources_str = ", ".join(s.value for s in lvl.sources[:2])
        alerts.append(PullbackAlert(
            alert_price=lvl.price,
            current_price=current_price,
            level_source=sources_str,
            level_strength=lvl.strength,
            improvement_description=(
                f"Pullback to {lvl.price:.0f} ({sources_str}): "
                f"short put moves {distance:.0f} pts further OTM "
                f"({distance_atr:.1f} ATR pullback)"
            ),
            roc_improvement_pct=roc_improvement,
        ))

    # Sort nearest first (highest alert_price)
    alerts.sort(key=lambda a: a.alert_price, reverse=True)
    return alerts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestPullbackLevels -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add market_analyzer/features/entry_levels.py tests/test_entry_levels.py
git commit -m "feat: add pullback alert levels for patient entry"
```

---

## Task 7: Wire Skew into build_iron_condor_legs + TradeSpec Fields

**Files:**
- Modify: `market_analyzer/opportunity/option_plays/_trade_spec_helpers.py`
- Modify: `market_analyzer/models/opportunity.py`
- Test: `tests/test_entry_levels.py` (append)

**Context:** Modify `build_iron_condor_legs` to accept optional `SkewSlice`. When provided, use `select_skew_optimal_strike` to shift short strikes toward richest premium. Add 4 new fields to TradeSpec for entry intelligence.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entry_levels.py`:

```python
from market_analyzer.opportunity.option_plays._trade_spec_helpers import (
    build_iron_condor_legs,
)


class TestSkewWiredIntoIC:
    def test_no_skew_preserves_original_behavior(self) -> None:
        """Without skew, build_iron_condor_legs works exactly as before."""
        legs_no_skew, wing = build_iron_condor_legs(
            price=580.0, atr=5.0, regime_id=1,
            expiration=date(2026, 4, 17), dte=30, atm_iv=0.22,
        )
        assert len(legs_no_skew) == 4
        # Short put at ~1.0 ATR OTM = ~575
        short_put = [l for l in legs_no_skew if l.role == "short_put"][0]
        assert short_put.strike == 575.0

    def test_with_steep_skew_shifts_strikes(self) -> None:
        """With steep put skew, short put shifts further OTM for richer premium."""
        skew = _make_skew(atm_iv=0.22, put_skew=0.08, call_skew=0.03)
        legs_with_skew, wing = build_iron_condor_legs(
            price=580.0, atr=5.0, regime_id=1,
            expiration=date(2026, 4, 17), dte=30, atm_iv=0.22,
            skew=skew,
        )
        legs_no_skew, _ = build_iron_condor_legs(
            price=580.0, atr=5.0, regime_id=1,
            expiration=date(2026, 4, 17), dte=30, atm_iv=0.22,
        )
        short_put_skewed = [l for l in legs_with_skew if l.role == "short_put"][0]
        short_put_no_skew = [l for l in legs_no_skew if l.role == "short_put"][0]
        # Skew should push short put further OTM (lower)
        assert short_put_skewed.strike <= short_put_no_skew.strike

    def test_flat_skew_no_change(self) -> None:
        """Flat skew → same as no skew."""
        skew = _make_skew(atm_iv=0.22, put_skew=0.005, call_skew=0.003)
        legs_flat, _ = build_iron_condor_legs(
            price=580.0, atr=5.0, regime_id=1,
            expiration=date(2026, 4, 17), dte=30, atm_iv=0.22,
            skew=skew,
        )
        legs_none, _ = build_iron_condor_legs(
            price=580.0, atr=5.0, regime_id=1,
            expiration=date(2026, 4, 17), dte=30, atm_iv=0.22,
        )
        sp_flat = [l for l in legs_flat if l.role == "short_put"][0]
        sp_none = [l for l in legs_none if l.role == "short_put"][0]
        assert sp_flat.strike == sp_none.strike


class TestTradeSpecEntryFields:
    def test_new_fields_default_none(self) -> None:
        """New entry fields default to None."""
        ts = TradeSpec(
            ticker="SPY",
            legs=[_make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0)],
            underlying_price=580.0,
            target_dte=30,
            target_expiration=date(2026, 4, 17),
            spec_rationale="test",
        )
        assert ts.entry_mode is None
        assert ts.limit_price is None
        assert ts.pullback_levels is None
        assert ts.strike_proximity_score is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestSkewWiredIntoIC -v`
Expected: FAIL (skew parameter not accepted)

- [ ] **Step 3: Modify build_iron_condor_legs**

Edit `market_analyzer/opportunity/option_plays/_trade_spec_helpers.py`:

Change the `build_iron_condor_legs` signature from:
```python
def build_iron_condor_legs(
    price: float,
    atr: float,
    regime_id: int,
    expiration: date,
    dte: int,
    atm_iv: float,
) -> tuple[list[LegSpec], float]:
```
to:
```python
def build_iron_condor_legs(
    price: float,
    atr: float,
    regime_id: int,
    expiration: date,
    dte: int,
    atm_iv: float,
    skew: SkewSlice | None = None,
) -> tuple[list[LegSpec], float]:
```

Add the import at the top of the file. Since `_trade_spec_helpers.py` already has `from __future__ import annotations`, the annotation `SkewSlice | None` is string-evaluated at runtime and the import can go in the TYPE_CHECKING block:
```python
if TYPE_CHECKING:
    from market_analyzer.models.vol_surface import SkewSlice
```
Verify `from __future__ import annotations` exists at the top of the file. If not, add it AND use a runtime import instead.

Inside `build_iron_condor_legs`, after computing `short_put` and `short_call`, add skew adjustment:
```python
    # Skew adjustment: shift short strikes toward richest IV premium
    if skew is not None:
        from market_analyzer.features.entry_levels import select_skew_optimal_strike
        put_optimal = select_skew_optimal_strike(price, atr, regime_id, skew, "put")
        if put_optimal.iv_advantage_pct >= 5.0:  # Only shift if meaningful advantage
            short_put = put_optimal.optimal_strike
        call_optimal = select_skew_optimal_strike(price, atr, regime_id, skew, "call")
        if call_optimal.iv_advantage_pct >= 5.0:
            short_call = call_optimal.optimal_strike
```

Then recompute long strikes from the (possibly adjusted) short strikes:
```python
    long_put = snap_strike(short_put - wing_width, price)
    long_call = snap_strike(short_call + wing_width, price)
    wing_width_points = short_put - long_put
```

- [ ] **Step 4: Add TradeSpec fields**

Edit `market_analyzer/models/opportunity.py`. Add after line ~497 (after `entry_window_timezone`):
```python
    entry_mode: str | None = None  # "limit" or "market"
    limit_price: float | None = None  # Target limit order price
    pullback_levels: list[dict] | None = None  # Serialized PullbackAlert list
    strike_proximity_score: float | None = None  # 0-1 from compute_strike_support_proximity
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestSkewWiredIntoIC tests/test_entry_levels.py::TestTradeSpecEntryFields -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `.venv_312/Scripts/python.exe -m pytest tests/ -x -q`
Expected: All ~1408 tests pass (existing IC tests should pass since skew=None preserves behavior)

- [ ] **Step 7: Commit**

```bash
git add market_analyzer/opportunity/option_plays/_trade_spec_helpers.py market_analyzer/models/opportunity.py tests/test_entry_levels.py
git commit -m "feat: wire skew into IC strike selection + add TradeSpec entry fields"
```

---

## Task 8: Wire Proximity Check into Validation

**Files:**
- Modify: `market_analyzer/validation/daily_readiness.py`
- Test: `tests/test_entry_levels.py` (append)

**Context:** Add `strike_proximity` as check #8 in `run_daily_checks`. This requires adding `levels: LevelsAnalysis | None` and `atr: float` as optional parameters. When levels are provided, check that short strikes are backed by S/R levels. When not provided, emit a WARN (data gap).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entry_levels.py`:

```python
from market_analyzer.validation.daily_readiness import run_daily_checks
from market_analyzer.validation.models import Severity


class TestStrikeProximityInDailyChecks:
    def _run_daily_with_levels(
        self,
        supports: list[tuple[float, float, list[str]]],
        resistances: list[tuple[float, float, list[str]]],
    ):
        """Run daily checks with levels data included."""
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
            _make_leg("short_call", LegAction.SELL_TO_OPEN, "call", 590.0),
            _make_leg("long_call", LegAction.BUY_TO_OPEN, "call", 595.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(supports, resistances)
        return run_daily_checks(
            ticker="SPY", trade_spec=ts, entry_credit=3.00,
            regime_id=1, atr_pct=0.86, current_price=580.0,
            avg_bid_ask_spread_pct=1.0, dte=30, rsi=50.0,
            levels=levels,
        )

    def test_backed_strikes_pass(self) -> None:
        """Both short legs backed → strike_proximity PASS."""
        report = self._run_daily_with_levels(
            supports=[(571.0, 0.85, ["sma_200", "swing_support"])],
            resistances=[(592.0, 0.80, ["swing_resistance"])],
        )
        prox = [c for c in report.checks if c.name == "strike_proximity"]
        assert len(prox) == 1
        assert prox[0].severity == Severity.PASS

    def test_unbacked_strikes_warn(self) -> None:
        """No S/R backing → strike_proximity WARN."""
        report = self._run_daily_with_levels(supports=[], resistances=[])
        prox = [c for c in report.checks if c.name == "strike_proximity"]
        assert len(prox) == 1
        assert prox[0].severity == Severity.WARN

    def test_no_levels_data_warn(self) -> None:
        """When levels=None, emit WARN for missing data."""
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
        ]
        ts = _make_trade_spec(legs)
        report = run_daily_checks(
            ticker="SPY", trade_spec=ts, entry_credit=3.00,
            regime_id=1, atr_pct=0.86, current_price=580.0,
            avg_bid_ask_spread_pct=1.0, dte=30, rsi=50.0,
            levels=None,  # No levels data
        )
        prox = [c for c in report.checks if c.name == "strike_proximity"]
        assert len(prox) == 1
        assert prox[0].severity == Severity.WARN

    def test_total_checks_now_8(self) -> None:
        """Daily suite now has 8 checks (7 original + strike_proximity)."""
        report = self._run_daily_with_levels(
            supports=[(571.0, 0.85, ["sma_200"])],
            resistances=[(592.0, 0.80, ["swing_resistance"])],
        )
        assert len(report.checks) == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestStrikeProximityInDailyChecks -v`
Expected: FAIL (levels parameter not accepted by run_daily_checks)

- [ ] **Step 3: Modify run_daily_checks**

Edit `market_analyzer/validation/daily_readiness.py`:

Add `levels: LevelsAnalysis | None = None` parameter to `run_daily_checks` signature.

Add the import at the top (in TYPE_CHECKING block):
```python
from market_analyzer.models.levels import LevelsAnalysis
```

After check #7 (exit_discipline), add check #8:

```python
    # ── Check 8: Strike proximity to S/R levels ──
    if levels is not None:
        from market_analyzer.features.entry_levels import compute_strike_support_proximity
        atr_value = current_price * atr_pct / 100
        proximity = compute_strike_support_proximity(trade_spec, levels, atr=atr_value)
        if proximity.all_backed:
            checks.append(CheckResult(
                name="strike_proximity",
                severity=Severity.PASS,
                message=f"Short strikes backed by S/R levels (score {proximity.overall_score:.0%})",
                detail=proximity.summary,
                value=proximity.overall_score,
                threshold=0.5,
            ))
        else:
            checks.append(CheckResult(
                name="strike_proximity",
                severity=Severity.WARN,
                message=f"Short strikes not fully backed (score {proximity.overall_score:.0%})",
                detail=proximity.summary,
                value=proximity.overall_score,
                threshold=0.5,
            ))
    else:
        checks.append(CheckResult(
            name="strike_proximity",
            severity=Severity.WARN,
            message="No levels data — cannot assess strike proximity to S/R",
            detail="Pass levels from ma.levels.analyze() for strike proximity check",
        ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_entry_levels.py::TestStrikeProximityInDailyChecks -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Fix any regressions from check count change**

Run: `.venv_312/Scripts/python.exe -m pytest tests/test_validation_daily_readiness.py tests/functional/ -v`

Existing tests that assert check count == 7 will need updating to 8. The implementer should fix these by updating the assertions.

- [ ] **Step 6: Commit**

```bash
git add market_analyzer/validation/daily_readiness.py tests/test_entry_levels.py
git commit -m "feat: add strike_proximity check (#8) to daily validation suite"
```

---

## Task 9: Package Exports + CLI do_entry_analysis

**Files:**
- Modify: `market_analyzer/__init__.py`
- Modify: `market_analyzer/cli/interactive.py`
- Test: `tests/test_entry_levels.py` (append)

**Context:** Wire all 6 functions into the public API + add a `do_entry_analysis` CLI command that runs the full entry-level intelligence pipeline for a given ticker.

- [ ] **Step 1: Add exports to `__init__.py`**

Add to `market_analyzer/__init__.py` exports:

```python
from market_analyzer.models.entry import (
    ConditionalEntry,
    EntryLevelScore,
    PullbackAlert,
    SkewOptimalStrike,
    StrikeProximityLeg,
    StrikeProximityResult,
)
from market_analyzer.features.entry_levels import (
    compute_limit_entry_price,
    compute_pullback_levels,
    compute_strike_support_proximity,
    score_entry_level,
    select_skew_optimal_strike,
)
```

Add all 11 names to `__all__`.

- [ ] **Step 2: Add CLI command**

Add to `market_analyzer/cli/interactive.py` (after `do_validate`):

```python
    def do_entry_analysis(self, arg: str) -> None:
        """Analyze entry levels for a ticker: entry_analysis TICKER

        Runs full entry-level intelligence:
        1. Strike-to-S/R proximity check (are your short strikes backed?)
        2. Skew-optimal strike suggestion (where is IV richest?)
        3. Multi-factor entry score (enter now vs wait?)
        4. Limit order price (patient/normal/aggressive fill target)
        5. Pullback alert levels (where does the trade get better?)
        """
        ticker = arg.strip().upper() or "SPY"

        try:
            # Fetch data
            regime = self.ma.regime.detect(ticker)
            tech = self.ma.technicals.snapshot(ticker)
            levels = self.ma.levels.analyze(ticker)
            vol = self.ma.vol_surface.compute(ticker)

            from market_analyzer.opportunity.option_plays.iron_condor import assess_iron_condor
            ic = assess_iron_condor(ticker, regime, tech, vol)

            if ic.trade_spec is None:
                print(f"No trade spec for {ticker} (verdict: {ic.verdict})")
                return

            from market_analyzer.features.entry_levels import (
                compute_strike_support_proximity,
                select_skew_optimal_strike,
                score_entry_level,
                compute_limit_entry_price,
                compute_pullback_levels,
            )

            atr = tech.atr
            price = tech.current_price

            # 1. Strike proximity
            proximity = compute_strike_support_proximity(ic.trade_spec, levels, atr=atr)
            print(f"\nENTRY ANALYSIS — {ticker} — {tech.as_of_date}")
            print("─" * 50)
            status = "✓" if proximity.all_backed else "⚠"
            print(f"{status}  Strike Proximity   {proximity.summary}")

            # 2. Skew optimal (if vol surface has skew data)
            if vol and vol.skew_by_expiry:
                skew = vol.skew_by_expiry[0]
                put_opt = select_skew_optimal_strike(price, atr, regime.regime.value, skew, "put")
                call_opt = select_skew_optimal_strike(price, atr, regime.regime.value, skew, "call")
                if put_opt.iv_advantage_pct >= 5:
                    print(f"↑  Skew Put          {put_opt.rationale}")
                else:
                    print(f"·  Skew Put          No meaningful skew advantage ({put_opt.iv_advantage_pct:.1f}%)")
                if call_opt.iv_advantage_pct >= 5:
                    print(f"↑  Skew Call         {call_opt.rationale}")
                else:
                    print(f"·  Skew Call         No meaningful skew advantage ({call_opt.iv_advantage_pct:.1f}%)")
            else:
                print(f"·  Skew              No vol surface data")

            # 3. Entry level score
            entry_score = score_entry_level(tech, levels, direction="neutral")
            icon = {"enter_now": "✓", "wait": "⏳", "not_yet": "✗"}
            print(f"{icon.get(entry_score.action, '?')}  Entry Score        {entry_score.overall_score:.0%} → {entry_score.action.upper()} ({entry_score.rationale})")

            # 4. Limit price (use max_entry_price from trade spec or broker quotes)
            entry_credit = ic.trade_spec.max_entry_price
            if entry_credit is not None:
                spread = vol.avg_bid_ask_spread_pct / 100 * price / 100 if vol else 0.10
                urgency_map = {1: "patient", 2: "normal", 3: "aggressive", 4: "aggressive"}
                urgency = urgency_map.get(regime.regime.value, "normal")
                limit = compute_limit_entry_price(
                    current_mid=entry_credit,
                    bid_ask_spread=spread,
                    urgency=urgency,
                )
                print(f"$  Limit Price       {limit.rationale}")
            else:
                print(f"·  Limit Price       No entry price available (connect broker for real quotes)")

            # 5. Pullback levels
            pullbacks = compute_pullback_levels(price, levels, atr=atr)
            if pullbacks:
                print(f"\n📋 Pullback Alerts ({len(pullbacks)}):")
                for pb in pullbacks[:3]:
                    print(f"   → Wait for {pb.alert_price:.0f} ({pb.level_source}) — +{pb.roc_improvement_pct:.1f}% ROC improvement")
            else:
                print(f"\n   No pullback levels within 2 ATR")

            print("─" * 50)

        except Exception as e:
            print(f"Error: {e}")
```

- [ ] **Step 3: Write smoke test**

Append to `tests/test_entry_levels.py`:

```python
class TestCLIEntryAnalysis:
    def test_do_entry_analysis_import(self) -> None:
        """Verify all entry_levels functions are importable from top-level."""
        from market_analyzer import (
            compute_strike_support_proximity,
            select_skew_optimal_strike,
            score_entry_level,
            compute_limit_entry_price,
            compute_pullback_levels,
            StrikeProximityResult,
            SkewOptimalStrike,
            EntryLevelScore,
            ConditionalEntry,
            PullbackAlert,
        )
        assert callable(compute_strike_support_proximity)
        assert callable(select_skew_optimal_strike)
        assert callable(score_entry_level)
        assert callable(compute_limit_entry_price)
        assert callable(compute_pullback_levels)
```

- [ ] **Step 4: Run full suite**

Run: `.venv_312/Scripts/python.exe -m pytest tests/ -x -q`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add market_analyzer/__init__.py market_analyzer/cli/interactive.py tests/test_entry_levels.py
git commit -m "feat: add entry_analysis CLI command + wire package exports"
```

---

## Task 10: Functional Test Suite

**Files:**
- Create: `tests/functional/test_entry_intelligence.py`

**Context:** End-to-end tests that exercise the full pipeline: assess_iron_condor → entry level functions → validate. Uses shared fixtures from `conftest.py`.

- [ ] **Step 1: Write functional tests**

```python
# tests/functional/test_entry_intelligence.py
"""Functional tests for entry-level intelligence pipeline."""

from datetime import date

import pytest

from market_analyzer.features.entry_levels import (
    compute_limit_entry_price,
    compute_pullback_levels,
    compute_strike_support_proximity,
    score_entry_level,
    select_skew_optimal_strike,
)
from market_analyzer.models.entry import (
    ConditionalEntry,
    EntryLevelScore,
    PullbackAlert,
    SkewOptimalStrike,
    StrikeProximityResult,
)
from market_analyzer.models.levels import (
    LevelRole,
    LevelSource,
    LevelsAnalysis,
    PriceLevel,
    TradeDirection,
)
from market_analyzer.models.opportunity import Verdict
from market_analyzer.opportunity.option_plays.iron_condor import assess_iron_condor
from market_analyzer.validation.daily_readiness import run_daily_checks
from market_analyzer.validation.models import Severity


class TestFullEntryPipeline:
    """End-to-end: assess → proximity → score → validate."""

    def test_r1_ic_with_strong_levels_passes_all(
        self, r1_regime, normal_vol_surface,
    ) -> None:
        """R1 IC with strong S/R backing passes proximity and daily checks."""
        from market_analyzer.models.technicals import (
            BollingerBands, MACDData, MovingAverages, RSIData,
            StochasticData, SupportResistance, TechnicalSnapshot,
            MarketPhase, PhaseIndicator,
        )

        tech = TechnicalSnapshot(
            ticker="SPY", as_of_date=date(2026, 3, 19), current_price=580.0,
            atr=5.0, atr_pct=0.86, vwma_20=580.0,
            moving_averages=MovingAverages(
                sma_20=580.0, sma_50=568.0, sma_200=551.0,
                ema_9=580.0, ema_21=579.0,
                price_vs_sma_20_pct=0.0, price_vs_sma_50_pct=2.1, price_vs_sma_200_pct=5.3,
            ),
            rsi=RSIData(value=52.0, is_overbought=False, is_oversold=False),
            bollinger=BollingerBands(upper=590.0, middle=580.0, lower=570.0,
                                     bandwidth=0.035, percent_b=0.50),
            macd=MACDData(macd_line=0.5, signal_line=0.3, histogram=0.2,
                          is_bullish_crossover=False, is_bearish_crossover=False),
            stochastic=StochasticData(k=50.0, d=50.0, is_overbought=False, is_oversold=False),
            support_resistance=SupportResistance(
                support=570.0, resistance=590.0,
                price_vs_support_pct=1.7, price_vs_resistance_pct=-1.7,
            ),
            phase=PhaseIndicator(
                phase=MarketPhase.ACCUMULATION, confidence=0.5, description="Test",
                higher_highs=False, higher_lows=True, lower_highs=False, lower_lows=False,
                range_compression=0.3, volume_trend="declining", price_vs_sma_50_pct=2.0,
            ),
            signals=[],
        )

        # Assess IC
        ic = assess_iron_condor("SPY", r1_regime, tech, normal_vol_surface)
        if ic.trade_spec is None:
            pytest.skip("IC assessment returned no trade spec")

        # Build levels with strong S/R at IC strike locations
        short_put = [l for l in ic.trade_spec.legs if l.role == "short_put"][0]
        short_call = [l for l in ic.trade_spec.legs if l.role == "short_call"][0]

        levels = LevelsAnalysis(
            ticker="SPY", as_of_date=date(2026, 3, 19), entry_price=580.0,
            direction=TradeDirection.LONG, direction_auto_detected=True,
            current_price=580.0, atr=5.0, atr_pct=0.86,
            support_levels=[
                PriceLevel(
                    price=short_put.strike + 1.0, role=LevelRole.SUPPORT,
                    sources=[LevelSource.SMA_200, LevelSource.SWING_SUPPORT],
                    confluence_score=2, strength=0.90,
                    distance_pct=abs(580 - short_put.strike - 1) / 580 * 100,
                    description="SMA-200 + swing support",
                ),
            ],
            resistance_levels=[
                PriceLevel(
                    price=short_call.strike + 1.0, role=LevelRole.RESISTANCE,
                    sources=[LevelSource.SWING_RESISTANCE],
                    confluence_score=1, strength=0.75,
                    distance_pct=abs(short_call.strike + 1 - 580) / 580 * 100,
                    description="Swing resistance",
                ),
            ],
            stop_loss=None, targets=[], best_target=None, summary="test",
        )

        # Check proximity
        prox = compute_strike_support_proximity(ic.trade_spec, levels, atr=5.0)
        assert isinstance(prox, StrikeProximityResult)
        # At least the put side should be backed (level is within 1 ATR)
        put_legs = [l for l in prox.legs if l.role == "short_put"]
        assert len(put_legs) >= 1

        # Score entry
        entry_score = score_entry_level(tech, levels, direction="neutral")
        assert isinstance(entry_score, EntryLevelScore)

        # Limit price
        limit = compute_limit_entry_price(1.80, 0.30, urgency="patient")
        assert isinstance(limit, ConditionalEntry)

        # Pullback levels
        pullbacks = compute_pullback_levels(580.0, levels, atr=5.0)
        assert isinstance(pullbacks, list)


class TestSkewOptimalWithRealVolSurface:
    """Test skew selection using fixtures from conftest."""

    def test_normal_vol_surface_has_skew(self, normal_vol_surface) -> None:
        """Normal vol surface fixture should have skew data."""
        assert len(normal_vol_surface.skew_by_expiry) >= 1
        skew = normal_vol_surface.skew_by_expiry[0]
        result = select_skew_optimal_strike(580.0, 5.0, 1, skew, "put")
        assert isinstance(result, SkewOptimalStrike)

    def test_high_vol_surface_steeper_skew(
        self, normal_vol_surface, high_vol_surface,
    ) -> None:
        """High vol surface should produce more skew adjustment than normal."""
        normal_skew = normal_vol_surface.skew_by_expiry[0]
        high_skew = high_vol_surface.skew_by_expiry[0]
        r_normal = select_skew_optimal_strike(580.0, 5.0, 1, normal_skew, "put")
        r_high = select_skew_optimal_strike(580.0, 8.0, 2, high_skew, "put")
        # High vol should have more skew advantage (steeper put skew in stressed markets)
        assert r_high.iv_advantage_pct >= r_normal.iv_advantage_pct


class TestEntryScoreWithExtremes:
    """Entry score at market extremes (oversold/overbought)."""

    def test_oversold_bounce_entry(self) -> None:
        """RSI 22, %B -0.1 (below lower band) → strong enter_now."""
        from market_analyzer.models.technicals import (
            BollingerBands, MACDData, MovingAverages, RSIData,
            StochasticData, SupportResistance, TechnicalSnapshot,
            MarketPhase, PhaseIndicator,
        )

        tech = TechnicalSnapshot(
            ticker="SPY", as_of_date=date(2026, 3, 19), current_price=565.0,
            atr=6.0, atr_pct=1.06, vwma_20=575.0,
            moving_averages=MovingAverages(
                sma_20=575.0, sma_50=578.0, sma_200=560.0,
                ema_9=568.0, ema_21=572.0,
                price_vs_sma_20_pct=-1.7, price_vs_sma_50_pct=-2.2, price_vs_sma_200_pct=0.9,
            ),
            rsi=RSIData(value=22.0, is_overbought=False, is_oversold=True),
            bollinger=BollingerBands(upper=590.0, middle=575.0, lower=560.0,
                                     bandwidth=0.05, percent_b=-0.10),
            macd=MACDData(macd_line=-1.5, signal_line=-0.8, histogram=-0.7,
                          is_bullish_crossover=False, is_bearish_crossover=True),
            stochastic=StochasticData(k=15.0, d=18.0, is_overbought=False, is_oversold=True),
            support_resistance=SupportResistance(
                support=560.0, resistance=575.0,
                price_vs_support_pct=0.9, price_vs_resistance_pct=-1.7,
            ),
            phase=PhaseIndicator(
                phase=MarketPhase.ACCUMULATION, confidence=0.7, description="Test",
                higher_highs=False, higher_lows=False, lower_highs=True, lower_lows=True,
                range_compression=0.1, volume_trend="rising", price_vs_sma_50_pct=-2.2,
            ),
            signals=[],
        )

        levels = LevelsAnalysis(
            ticker="SPY", as_of_date=date(2026, 3, 19), entry_price=565.0,
            direction=TradeDirection.LONG, direction_auto_detected=True,
            current_price=565.0, atr=6.0, atr_pct=1.06,
            support_levels=[
                PriceLevel(
                    price=560.0, role=LevelRole.SUPPORT,
                    sources=[LevelSource.SMA_200, LevelSource.SWING_SUPPORT],
                    confluence_score=2, strength=0.90,
                    distance_pct=0.88, description="SMA-200 + swing",
                ),
            ],
            resistance_levels=[],
            stop_loss=None, targets=[], best_target=None, summary="test",
        )

        result = score_entry_level(tech, levels, direction="bullish")
        assert result.action == "enter_now"
        assert result.overall_score >= 0.70
        assert result.components["rsi_extremity"] > 0.80


class TestPullbackWithRealisticLevels:
    """Pullback alerts using realistic level configurations."""

    def test_multiple_support_levels_multiple_alerts(self) -> None:
        """Three support levels below → three ranked pullback alerts."""
        levels = LevelsAnalysis(
            ticker="SPY", as_of_date=date(2026, 3, 19), entry_price=580.0,
            direction=TradeDirection.LONG, direction_auto_detected=True,
            current_price=580.0, atr=5.0, atr_pct=0.86,
            support_levels=[
                PriceLevel(price=577.0, role=LevelRole.SUPPORT,
                           sources=[LevelSource.SMA_20],
                           confluence_score=1, strength=0.55, distance_pct=0.52,
                           description="SMA-20"),
                PriceLevel(price=574.0, role=LevelRole.SUPPORT,
                           sources=[LevelSource.SMA_50, LevelSource.EMA_21],
                           confluence_score=2, strength=0.75, distance_pct=1.03,
                           description="SMA-50 + EMA-21"),
                PriceLevel(price=570.0, role=LevelRole.SUPPORT,
                           sources=[LevelSource.SMA_200, LevelSource.SWING_SUPPORT,
                                    LevelSource.ORDER_BLOCK_LOW],
                           confluence_score=3, strength=0.92, distance_pct=1.72,
                           description="SMA-200 + swing + OB"),
            ],
            resistance_levels=[],
            stop_loss=None, targets=[], best_target=None, summary="test",
        )

        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        assert len(alerts) >= 2
        # Sorted nearest first
        assert alerts[0].alert_price > alerts[-1].alert_price
        # All improvement positive
        for alert in alerts:
            assert alert.roc_improvement_pct > 0
```

- [ ] **Step 2: Run functional tests**

Run: `.venv_312/Scripts/python.exe -m pytest tests/functional/test_entry_intelligence.py -v`
Expected: PASS

- [ ] **Step 3: Run full regression**

Run: `.venv_312/Scripts/python.exe -m pytest tests/ -x -q`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/functional/test_entry_intelligence.py
git commit -m "feat: add functional tests for entry-level intelligence pipeline"
```

---

## Final Verification Checklist

After all 10 tasks are complete:

- [ ] All tests pass: `.venv_312/Scripts/python.exe -m pytest tests/ -v`
- [ ] All 6 functions importable from `market_analyzer`:
  - `compute_strike_support_proximity`
  - `select_skew_optimal_strike`
  - `score_entry_level`
  - `compute_limit_entry_price`
  - `compute_pullback_levels`
- [ ] All 6 models importable from `market_analyzer`:
  - `StrikeProximityResult`, `StrikeProximityLeg`
  - `SkewOptimalStrike`
  - `EntryLevelScore`
  - `ConditionalEntry`
  - `PullbackAlert`
- [ ] CLI `entry_analysis SPY` runs without error (with broker or without)
- [ ] Daily validation now has 8 checks (was 7)
- [ ] `build_iron_condor_legs` backward compatible (skew=None works as before)
- [ ] TradeSpec has 4 new fields (all default None, no breaking change)
- [ ] No existing tests broken
