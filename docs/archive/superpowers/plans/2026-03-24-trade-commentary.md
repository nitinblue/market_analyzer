# Trade Commentary Retrospection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-trade narrative commentary to the retrospection engine — 6 dimensions per trade, structured for eTrading, readable for humans.

**Architecture:** New models (`DimensionFinding`, `TradeCommentary`, `DecisionCommentary`) added to `retrospection/models.py`. New commentary generation logic in `retrospection/commentary.py` (separate from engine.py to keep files focused). Engine calls commentary generator from `_analyze()`. All rule-based, no data fetching, no LLM calls.

**Tech Stack:** Pydantic models, pure Python logic, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `income_desk/retrospection/models.py` | Modify | Add `DimensionFinding`, `TradeCommentary`, `DecisionCommentary` models; add fields to `RetrospectionFeedback` |
| `income_desk/retrospection/commentary.py` | Create | Commentary generation: 6 dimension analyzers + decision commentary + overall narrative composer |
| `income_desk/retrospection/engine.py` | Modify | Call commentary generator from `_analyze()` |
| `income_desk/retrospection/__init__.py` | Modify | Export new models |
| `tests/test_retrospection_commentary.py` | Create | All commentary tests |

---

### Task 1: Add Commentary Data Models

**Files:**
- Modify: `income_desk/retrospection/models.py:280-364`
- Test: `tests/test_retrospection_commentary.py`

- [ ] **Step 1: Write model validation tests**

```python
"""Tests for trade commentary models and generation."""
import pytest
from income_desk.retrospection.models import (
    DimensionFinding, TradeCommentary, DecisionCommentary,
)


class TestCommentaryModels:
    def test_dimension_finding_defaults(self):
        f = DimensionFinding(
            dimension="regime_alignment",
            grade="A",
            score=92,
            narrative="Iron condor in R1 — textbook theta setup.",
        )
        assert f.dimension == "regime_alignment"
        assert f.grade == "A"
        assert f.score == 92
        assert f.details == {}

    def test_trade_commentary_defaults(self):
        tc = TradeCommentary(
            trade_id="abc-123",
            ticker="SPY",
            strategy="iron_condor",
            market="US",
            overall_narrative="Good trade.",
            dimensions=[],
        )
        assert tc.should_have_avoided is False
        assert tc.avoidance_reason is None
        assert tc.key_lesson is None

    def test_decision_commentary_defaults(self):
        dc = DecisionCommentary(narrative="433 decisions reviewed.")
        assert dc.near_misses == []
        assert dc.missed_opportunities == []
        assert dc.rejection_summary == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv_312/Scripts/python -m pytest tests/test_retrospection_commentary.py -v`
Expected: FAIL — `DimensionFinding` not defined

- [ ] **Step 3: Add models to models.py**

Add after `TradeAuditResult` (line ~297):

```python
class DimensionFinding(BaseModel):
    """Single dimension of trade commentary — grade + narrative."""
    dimension: str          # "regime_alignment", "strike_placement", etc.
    grade: str              # A/B/C/D/F
    score: int              # 0-100
    narrative: str          # Human-readable sentence
    details: dict[str, Any] = {}  # Structured data for eTrading rendering


class TradeCommentary(BaseModel):
    """Per-trade narrative commentary — structured for eTrading, readable for humans."""
    trade_id: str
    ticker: str
    strategy: str
    market: str = "US"
    overall_narrative: str              # 2-3 sentence summary
    dimensions: list[DimensionFinding] = []
    should_have_avoided: bool = False
    avoidance_reason: str | None = None
    key_lesson: str | None = None       # One actionable takeaway


class DecisionCommentary(BaseModel):
    """Commentary on the day's decision quality — approval/rejection patterns."""
    near_misses: list[dict[str, Any]] = []        # Score 0.35-0.50, gate rejected
    missed_opportunities: list[dict[str, Any]] = []  # Score >= 0.50, gate rejected
    rejection_summary: dict[str, int] = {}        # Counts by rejection reason
    narrative: str = ""                            # Human-readable summary
```

Add to `RetrospectionFeedback` after `trade_audit`:

```python
    trade_commentaries: list[TradeCommentary] = []
    decision_commentary: DecisionCommentary | None = None
```

- [ ] **Step 4: Update `__init__.py` exports**

Add `DimensionFinding`, `TradeCommentary`, `DecisionCommentary` to exports.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv_312/Scripts/python -m pytest tests/test_retrospection_commentary.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add income_desk/retrospection/models.py income_desk/retrospection/__init__.py tests/test_retrospection_commentary.py
git commit -m "feat(retrospection): add commentary data models"
```

---

### Task 2: Regime Alignment Dimension

**Files:**
- Create: `income_desk/retrospection/commentary.py`
- Test: `tests/test_retrospection_commentary.py`

- [ ] **Step 1: Write failing tests**

```python
from income_desk.retrospection.commentary import analyze_regime_alignment
from income_desk.retrospection.models import LegRecord, TradeOpened, EntryAnalytics


class TestRegimeAlignment:
    def test_r1_iron_condor_is_grade_a(self):
        """R1 + iron_condor = textbook theta setup."""
        f = analyze_regime_alignment("iron_condor", "R1", 0.65)
        assert f.grade == "A"
        assert f.score >= 85
        assert "R1" in f.narrative

    def test_r4_iron_condor_is_grade_f(self):
        """R4 trending + theta strategy = avoid."""
        f = analyze_regime_alignment("iron_condor", "R4", 0.70)
        assert f.grade in ("D", "F")
        assert f.score <= 40
        assert "trending" in f.narrative.lower() or "avoid" in f.narrative.lower()

    def test_r3_diagonal_is_grade_a(self):
        """R3 trending + directional strategy = good fit."""
        f = analyze_regime_alignment("diagonal", "R3", 0.60)
        assert f.grade in ("A", "B+")

    def test_missing_regime_is_grade_c(self):
        """No regime data = cannot validate, penalize."""
        f = analyze_regime_alignment("iron_condor", None, None)
        assert f.grade == "C"
        assert "no regime" in f.narrative.lower() or "missing" in f.narrative.lower()

    def test_low_confidence_regime(self):
        """Regime present but <50% confidence — uncertain."""
        f = analyze_regime_alignment("iron_condor", "R1", 0.35)
        assert f.score < 85  # penalized for low confidence
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv_312/Scripts/python -m pytest tests/test_retrospection_commentary.py::TestRegimeAlignment -v`
Expected: FAIL — `commentary` module not found

- [ ] **Step 3: Create `commentary.py` with regime alignment analyzer**

```python
"""Trade commentary generation — 6-dimension per-trade narrative analysis.

Each dimension analyzer is a pure function:
    (trade data) -> DimensionFinding

The composer combines dimensions into TradeCommentary.
"""
from __future__ import annotations

from income_desk.retrospection.models import DimensionFinding

# Regime-strategy compatibility (from CLAUDE.md)
_REGIME_RECOMMENDED: dict[str, set[str]] = {
    "R1": {"iron_condor", "strangle", "straddle", "ratio_spread", "calendar", "iron_butterfly", "credit_spread", "double_calendar", "pmcc"},
    "R2": {"iron_condor", "iron_butterfly", "calendar", "ratio_spread", "credit_spread"},
    "R3": {"diagonal", "leap", "momentum", "breakout", "debit_spread"},
    "R4": {"breakout", "momentum", "debit_spread"},
}

_REGIME_AVOID: dict[str, set[str]] = {
    "R1": {"breakout", "momentum", "debit_spread"},
    "R2": {"breakout", "momentum", "debit_spread"},
    "R3": {"iron_condor", "strangle", "straddle", "iron_butterfly"},
    "R4": {"iron_condor", "strangle", "straddle", "iron_butterfly", "calendar", "ratio_spread", "credit_spread"},
}

_REGIME_NAMES = {"R1": "Low-Vol Mean Reverting", "R2": "High-Vol Mean Reverting", "R3": "Low-Vol Trending", "R4": "High-Vol Trending"}


def analyze_regime_alignment(
    strategy: str,
    regime: str | None,
    confidence: float | None,
) -> DimensionFinding:
    """Evaluate whether the strategy fits the regime state."""
    if regime is None:
        return DimensionFinding(
            dimension="regime_alignment",
            grade="C",
            score=50,
            narrative="No regime data at entry — cannot confirm strategy suitability.",
            details={"regime": None, "strategy": strategy, "reason": "missing_regime"},
        )

    regime_upper = regime.upper() if isinstance(regime, str) else regime
    # Normalize "3" -> "R3", etc.
    if isinstance(regime_upper, str) and not regime_upper.startswith("R"):
        regime_upper = f"R{regime_upper}"

    regime_name = _REGIME_NAMES.get(regime_upper, regime_upper)
    recommended = _REGIME_RECOMMENDED.get(regime_upper, set())
    avoid = _REGIME_AVOID.get(regime_upper, set())

    conf = confidence or 0.0
    conf_str = f"{conf:.0%}" if conf > 0 else "unknown"

    if strategy in avoid:
        score = 25
        if conf >= 0.60:
            score = 15  # high confidence makes it worse
        return DimensionFinding(
            dimension="regime_alignment",
            grade="F" if score <= 20 else "D",
            score=score,
            narrative=f"{strategy} in {regime_upper} ({regime_name}) at {conf_str} confidence — this strategy should be avoided in trending/volatile regimes.",
            details={"regime": regime_upper, "strategy": strategy, "confidence": conf, "alignment": "avoid"},
        )

    if strategy in recommended:
        score = 92
        if conf < 0.50:
            score = 70  # right strategy but uncertain regime
            return DimensionFinding(
                dimension="regime_alignment",
                grade="B",
                score=score,
                narrative=f"{strategy} fits {regime_upper} ({regime_name}), but confidence is only {conf_str} — regime uncertain.",
                details={"regime": regime_upper, "strategy": strategy, "confidence": conf, "alignment": "recommended_low_conf"},
            )
        return DimensionFinding(
            dimension="regime_alignment",
            grade="A",
            score=score,
            narrative=f"{strategy} in {regime_upper} ({regime_name}) at {conf_str} confidence — good strategy-regime fit.",
            details={"regime": regime_upper, "strategy": strategy, "confidence": conf, "alignment": "recommended"},
        )

    # Neutral — not recommended, not avoided
    return DimensionFinding(
        dimension="regime_alignment",
        grade="B-",
        score=65,
        narrative=f"{strategy} is not in the recommended set for {regime_upper} ({regime_name}), but not explicitly avoided either.",
        details={"regime": regime_upper, "strategy": strategy, "confidence": conf, "alignment": "neutral"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv_312/Scripts/python -m pytest tests/test_retrospection_commentary.py::TestRegimeAlignment -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add income_desk/retrospection/commentary.py tests/test_retrospection_commentary.py
git commit -m "feat(retrospection): regime alignment commentary dimension"
```

---

### Task 3: Strike Placement Dimension

**Files:**
- Modify: `income_desk/retrospection/commentary.py`
- Test: `tests/test_retrospection_commentary.py`

- [ ] **Step 1: Write failing tests**

```python
from income_desk.retrospection.commentary import analyze_strike_placement
from income_desk.retrospection.models import LegRecord


class TestStrikePlacement:
    def _make_ic_legs(self, sp_delta, sc_delta, wing_width=5.0, underlying=560.0):
        """Helper: build 4-leg iron condor."""
        return [
            LegRecord(action="STO", strike=underlying - 20, option_type="put", entry_delta=sp_delta, quantity=-1),
            LegRecord(action="BTO", strike=underlying - 20 - wing_width, option_type="put", entry_delta=sp_delta * 0.6, quantity=1),
            LegRecord(action="STO", strike=underlying + 20, option_type="call", entry_delta=sc_delta, quantity=-1),
            LegRecord(action="BTO", strike=underlying + 20 + wing_width, option_type="call", entry_delta=sc_delta * 0.6, quantity=1),
        ]

    def test_ideal_deltas_grade_a(self):
        """Short deltas 0.16-0.25 = grade A."""
        legs = self._make_ic_legs(-0.20, 0.20)
        f = analyze_strike_placement(legs, "iron_condor", 560.0)
        assert f.grade == "A"
        assert f.score >= 85

    def test_aggressive_deltas_grade_c(self):
        """Short deltas 0.30-0.40 = grade C."""
        legs = self._make_ic_legs(-0.35, 0.38)
        f = analyze_strike_placement(legs, "iron_condor", 560.0)
        assert f.grade in ("C", "C+")
        assert "aggressive" in f.narrative.lower()

    def test_very_aggressive_grade_d(self):
        """Short deltas > 0.40 = grade D/F."""
        legs = self._make_ic_legs(-0.45, 0.45)
        f = analyze_strike_placement(legs, "iron_condor", 560.0)
        assert f.grade in ("D", "F")

    def test_no_legs_grade_c(self):
        """No leg data = can't evaluate."""
        f = analyze_strike_placement([], "iron_condor", 560.0)
        assert f.grade == "C"
        assert "no leg" in f.narrative.lower() or "missing" in f.narrative.lower()

    def test_equity_skips_strike_analysis(self):
        """Equity trades have no strikes to analyze."""
        legs = [LegRecord(action="BTO", option_type=None, quantity=100, entry_price=54.5)]
        f = analyze_strike_placement(legs, "equity_long", 54.5)
        assert f.grade == "B"  # neutral — not applicable
        assert "equity" in f.narrative.lower() or "not applicable" in f.narrative.lower()

    def test_conservative_deltas_grade_a_minus(self):
        """Short deltas 0.10-0.16 = A- (safe but less premium)."""
        legs = self._make_ic_legs(-0.12, 0.12)
        f = analyze_strike_placement(legs, "iron_condor", 560.0)
        assert f.grade in ("A-", "A")
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement `analyze_strike_placement`**

Add to `commentary.py`:

```python
def analyze_strike_placement(
    legs: list[LegRecord],
    strategy: str,
    underlying_price: float,
) -> DimensionFinding:
    """Evaluate strike selection quality based on deltas and distance."""
    # Non-option strategies
    _EQUITY_STRATEGIES = {"equity_long", "equity_short", "equity_sell", "equity_buy"}
    if strategy in _EQUITY_STRATEGIES or not legs:
        if not legs:
            return DimensionFinding(
                dimension="strike_placement", grade="C", score=50,
                narrative="No leg data — cannot evaluate strike placement.",
                details={"reason": "no_legs"},
            )
        return DimensionFinding(
            dimension="strike_placement", grade="B", score=70,
            narrative="Equity position — strike placement not applicable.",
            details={"reason": "equity"},
        )

    # Find short legs (STO) and extract deltas
    short_legs = [l for l in legs if l.action == "STO" and l.entry_delta is not None]
    if not short_legs:
        return DimensionFinding(
            dimension="strike_placement", grade="C", score=50,
            narrative="No short leg delta data — cannot grade strike placement.",
            details={"reason": "no_short_deltas"},
        )

    short_deltas = [abs(l.entry_delta) for l in short_legs if l.entry_delta is not None]
    avg_delta = sum(short_deltas) / len(short_deltas)
    max_delta = max(short_deltas)

    # Grade based on average short delta
    if avg_delta <= 0.16:
        grade, score = "A-", 88
        desc = f"Conservative short deltas (avg {avg_delta:.2f}) — safe but may collect less premium."
    elif avg_delta <= 0.25:
        grade, score = "A", 92
        desc = f"Short deltas avg {avg_delta:.2f} — ideal range for income strategies."
    elif avg_delta <= 0.30:
        grade, score = "B", 75
        desc = f"Short deltas avg {avg_delta:.2f} — slightly wide of ideal 0.16-0.25 range."
    elif avg_delta <= 0.40:
        grade, score = "C", 55
        desc = f"Short deltas avg {avg_delta:.2f} — aggressive for income. Standard target is 0.16-0.30."
        if max_delta > 0.35:
            grade, score = "C+", 60  # acknowledge at least one is tighter
            desc = f"Short deltas avg {avg_delta:.2f} (max {max_delta:.2f}) — aggressive. Tighten to 0.20-0.25."
    else:
        grade, score = "D", 35
        desc = f"Short deltas avg {avg_delta:.2f} — too aggressive. High probability of breach."

    # Wing width analysis (if we can determine it from strikes)
    short_strikes = [(l.strike, l.option_type) for l in short_legs if l.strike]
    long_legs = [l for l in legs if l.action == "BTO" and l.strike]
    wing_info = {}
    if short_strikes and long_legs:
        # Find wing width from short-long strike pairs
        for sl in short_legs:
            for ll in long_legs:
                if sl.option_type == ll.option_type and sl.strike and ll.strike:
                    wing_info[sl.option_type] = abs(sl.strike - ll.strike)

    details = {
        "avg_short_delta": round(avg_delta, 4),
        "max_short_delta": round(max_delta, 4),
        "short_deltas": [round(d, 4) for d in short_deltas],
        "underlying_price": underlying_price,
    }
    if wing_info:
        details["wing_widths"] = wing_info

    return DimensionFinding(
        dimension="strike_placement", grade=grade, score=score,
        narrative=desc, details=details,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add income_desk/retrospection/commentary.py tests/test_retrospection_commentary.py
git commit -m "feat(retrospection): strike placement commentary dimension"
```

---

### Task 4: Entry Pricing Dimension

**Files:**
- Modify: `income_desk/retrospection/commentary.py`
- Test: `tests/test_retrospection_commentary.py`

- [ ] **Step 1: Write failing tests**

```python
from income_desk.retrospection.commentary import analyze_entry_pricing
from income_desk.retrospection.models import LegRecord


class TestEntryPricing:
    def test_excellent_credit_width_ratio(self):
        """Credit > 50% of wing width = grade A."""
        f = analyze_entry_pricing(
            entry_price=3.20, legs=[], strategy="iron_condor",
            wing_width=5.0, lot_size=100, currency="USD",
        )
        assert f.grade == "A"
        assert "64" in f.narrative or "%" in f.narrative  # 3.20/5.0 = 64%

    def test_good_credit_ratio(self):
        """Credit 33-50% = grade B."""
        f = analyze_entry_pricing(
            entry_price=2.00, legs=[], strategy="iron_condor",
            wing_width=5.0, lot_size=100, currency="USD",
        )
        assert f.grade in ("B", "B+")

    def test_thin_credit_ratio(self):
        """Credit < 33% = grade C/D."""
        f = analyze_entry_pricing(
            entry_price=1.20, legs=[], strategy="iron_condor",
            wing_width=5.0, lot_size=100, currency="USD",
        )
        assert f.grade in ("C", "D")

    def test_india_market_inr(self):
        """INR currency handled correctly."""
        f = analyze_entry_pricing(
            entry_price=32.25, legs=[], strategy="iron_condor",
            wing_width=50.0, lot_size=25, currency="INR",
        )
        assert f.grade == "A"  # 32.25/50 = 64.5%
        assert f.details.get("currency") == "INR"

    def test_no_wing_width(self):
        """No wing width = limited analysis."""
        f = analyze_entry_pricing(
            entry_price=2.50, legs=[], strategy="credit_spread",
            wing_width=None, lot_size=100, currency="USD",
        )
        assert f.grade in ("B", "C")  # can't fully evaluate
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement `analyze_entry_pricing`**

Add to `commentary.py`:

```python
def analyze_entry_pricing(
    entry_price: float,
    legs: list[LegRecord],
    strategy: str,
    wing_width: float | None = None,
    lot_size: int = 100,
    currency: str = "USD",
) -> DimensionFinding:
    """Evaluate entry pricing quality — credit/width ratio, premium collected."""
    curr_sym = "Rs." if currency == "INR" else "$"

    if not entry_price or entry_price <= 0:
        return DimensionFinding(
            dimension="entry_pricing", grade="C", score=50,
            narrative="No entry price data — cannot evaluate premium quality.",
            details={"reason": "no_entry_price"},
        )

    if wing_width and wing_width > 0:
        ratio = entry_price / wing_width
        ratio_pct = ratio * 100

        if ratio >= 0.50:
            grade, score = "A", 92
            desc = f"Collected {curr_sym}{entry_price:.2f} on {wing_width:.0f}-wide wings — {ratio_pct:.1f}% of max width. Excellent premium."
        elif ratio >= 0.33:
            grade, score = "B", 75
            desc = f"Collected {curr_sym}{entry_price:.2f} on {wing_width:.0f}-wide wings — {ratio_pct:.1f}% of width. Good premium."
        elif ratio >= 0.20:
            grade, score = "C", 55
            desc = f"Collected {curr_sym}{entry_price:.2f} on {wing_width:.0f}-wide wings — {ratio_pct:.1f}% of width. Thin premium for the risk."
        else:
            grade, score = "D", 35
            desc = f"Collected {curr_sym}{entry_price:.2f} on {wing_width:.0f}-wide wings — only {ratio_pct:.1f}%. Risk/reward unfavorable."

        details = {
            "entry_price": entry_price,
            "wing_width": wing_width,
            "credit_pct": round(ratio_pct, 1),
            "lot_size": lot_size,
            "currency": currency,
            "total_credit": round(entry_price * lot_size, 2),
        }
    else:
        # No wing width — just report the raw credit
        grade, score = "B", 70
        desc = f"Entry at {curr_sym}{entry_price:.2f} per contract ({curr_sym}{entry_price * lot_size:.0f} total). Cannot evaluate credit/width ratio without wing width."
        details = {
            "entry_price": entry_price,
            "lot_size": lot_size,
            "currency": currency,
            "total_credit": round(entry_price * lot_size, 2),
        }

    return DimensionFinding(
        dimension="entry_pricing", grade=grade, score=score,
        narrative=desc, details=details,
    )
```

- [ ] **Step 4: Run tests, verify pass**

- [ ] **Step 5: Commit**

```bash
git add income_desk/retrospection/commentary.py tests/test_retrospection_commentary.py
git commit -m "feat(retrospection): entry pricing commentary dimension"
```

---

### Task 5: Position Sizing Dimension

**Files:**
- Modify: `income_desk/retrospection/commentary.py`
- Test: `tests/test_retrospection_commentary.py`

- [ ] **Step 1: Write failing tests**

```python
from income_desk.retrospection.commentary import analyze_position_sizing
from income_desk.retrospection.models import PositionSize


class TestPositionSizing:
    def test_small_position_grade_a(self):
        f = analyze_position_sizing(PositionSize(capital_at_risk_pct=1.5, contracts=1))
        assert f.grade == "A"

    def test_medium_position_grade_b(self):
        f = analyze_position_sizing(PositionSize(capital_at_risk_pct=2.5, contracts=2))
        assert f.grade in ("B", "B+")

    def test_large_position_grade_c(self):
        f = analyze_position_sizing(PositionSize(capital_at_risk_pct=4.0, contracts=3))
        assert f.grade in ("C", "C+")

    def test_oversized_grade_d(self):
        f = analyze_position_sizing(PositionSize(capital_at_risk_pct=7.0, contracts=5))
        assert f.grade in ("D", "F")
        assert "oversized" in f.narrative.lower() or "too large" in f.narrative.lower()

    def test_no_sizing_data(self):
        f = analyze_position_sizing(None)
        assert f.grade == "C"
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement `analyze_position_sizing`**

```python
def analyze_position_sizing(
    position_size: PositionSize | None,
) -> DimensionFinding:
    """Evaluate position sizing vs account risk guidelines."""
    if position_size is None:
        return DimensionFinding(
            dimension="position_sizing", grade="C", score=50,
            narrative="No position sizing data — cannot evaluate risk allocation.",
            details={"reason": "no_data"},
        )

    pct = position_size.capital_at_risk_pct
    contracts = position_size.contracts

    if pct <= 2.0:
        grade, score = "A", 92
        desc = f"{pct:.1f}% of NLV at risk ({contracts} contracts) — well within 2% guideline."
    elif pct <= 3.0:
        grade, score = "B", 78
        desc = f"{pct:.1f}% of NLV at risk ({contracts} contracts) — acceptable, near 3% soft limit."
    elif pct <= 5.0:
        grade, score = "C", 55
        desc = f"{pct:.1f}% of NLV at risk ({contracts} contracts) — elevated. Target <=3%."
    else:
        grade, score = "D", 30
        desc = f"{pct:.1f}% of NLV at risk ({contracts} contracts) — oversized. Max recommended is 3-5%."

    return DimensionFinding(
        dimension="position_sizing", grade=grade, score=score,
        narrative=desc,
        details={"capital_at_risk_pct": pct, "contracts": contracts},
    )
```

- [ ] **Step 4: Run tests, verify pass**

- [ ] **Step 5: Commit**

```bash
git add income_desk/retrospection/commentary.py tests/test_retrospection_commentary.py
git commit -m "feat(retrospection): position sizing commentary dimension"
```

---

### Task 6: Exit Quality Dimension (Closed Trades)

**Files:**
- Modify: `income_desk/retrospection/commentary.py`
- Test: `tests/test_retrospection_commentary.py`

- [ ] **Step 1: Write failing tests**

```python
from income_desk.retrospection.commentary import analyze_exit_quality
from income_desk.retrospection.models import TradeClosed, PnLPoint


class TestExitQuality:
    def test_profit_target_hit(self):
        t = TradeClosed(
            trade_id="x", ticker="SPY", strategy_type="iron_condor",
            exit_reason="profit_target", total_pnl=150.0,
            max_pnl_during_hold=180.0, holding_days=12,
        )
        f = analyze_exit_quality(t)
        assert f.grade in ("A", "A-")
        assert "profit target" in f.narrative.lower()

    def test_was_profitable_closed_at_loss(self):
        t = TradeClosed(
            trade_id="x", ticker="SPY", strategy_type="iron_condor",
            exit_reason="stop_loss", total_pnl=-200.0,
            max_pnl_during_hold=120.0, min_pnl_during_hold=-250.0,
            holding_days=18,
        )
        f = analyze_exit_quality(t)
        assert f.score < 60
        assert "profitable" in f.narrative.lower() or "was" in f.narrative.lower()

    def test_held_too_long_theta(self):
        t = TradeClosed(
            trade_id="x", ticker="QQQ", strategy_type="iron_condor",
            exit_reason="expiration", total_pnl=50.0,
            holding_days=35,
        )
        f = analyze_exit_quality(t)
        assert f.score < 80  # penalized for holding too long

    def test_regime_changed_during_hold(self):
        t = TradeClosed(
            trade_id="x", ticker="GLD", strategy_type="calendar",
            exit_reason="profit_target", total_pnl=80.0,
            entry_regime="R1", exit_regime="R3",
            holding_days=14,
        )
        f = analyze_exit_quality(t)
        assert "regime" in f.narrative.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement `analyze_exit_quality`**

```python
_THETA_STRATEGIES = {"iron_condor", "iron_butterfly", "strangle", "straddle", "ratio_spread", "calendar", "credit_spread", "double_calendar"}

def analyze_exit_quality(trade: TradeClosed) -> DimensionFinding:
    """Evaluate exit timing and decision quality for closed trades."""
    score = 70
    observations: list[str] = []

    # Exit reason
    if trade.exit_reason == "profit_target":
        score += 15
        observations.append("Exited at profit target — good discipline.")
    elif trade.exit_reason == "stop_loss":
        score -= 5
        observations.append("Stop loss triggered — loss is expected sometimes.")
    elif trade.exit_reason == "expiration":
        score -= 5
        observations.append("Held to expiration — consider earlier exit for capital efficiency.")

    # Was profitable but closed at loss?
    if (trade.max_pnl_during_hold is not None
            and trade.max_pnl_during_hold > 0
            and trade.total_pnl < 0):
        score -= 15
        observations.append(
            f"Was profitable (max ${trade.max_pnl_during_hold:.0f}) but closed at "
            f"${trade.total_pnl:.0f}. Review exit timing — tighter profit target or "
            f"trail stop could have captured the gain."
        )

    # Profit left on table
    if (trade.max_pnl_during_hold is not None
            and trade.total_pnl > 0
            and trade.max_pnl_during_hold > trade.total_pnl * 1.5):
        left = trade.max_pnl_during_hold - trade.total_pnl
        observations.append(
            f"Left ~${left:.0f} on table (max was ${trade.max_pnl_during_hold:.0f}, "
            f"captured ${trade.total_pnl:.0f})."
        )

    # Holding period for theta strategies
    if trade.strategy_type in _THETA_STRATEGIES and trade.holding_days > 28:
        score -= 10
        observations.append(
            f"Held {trade.holding_days} days for theta strategy — target 21-28 DTE exit."
        )

    # Regime change during hold
    if (trade.entry_regime and trade.exit_regime
            and trade.entry_regime != trade.exit_regime):
        score -= 5
        observations.append(
            f"Regime changed {trade.entry_regime} -> {trade.exit_regime} during hold. "
            f"Consider adding regime-change exit rule."
        )

    score = max(0, min(100, score))
    narrative = " ".join(observations) if observations else "Standard exit — no notable issues."

    return DimensionFinding(
        dimension="exit_quality", grade=_score_to_grade(score), score=score,
        narrative=narrative,
        details={
            "exit_reason": trade.exit_reason,
            "total_pnl": trade.total_pnl,
            "max_pnl": trade.max_pnl_during_hold,
            "holding_days": trade.holding_days,
            "entry_regime": trade.entry_regime,
            "exit_regime": trade.exit_regime,
        },
    )
```

Note: import `_score_to_grade` from engine or duplicate it in commentary.py (prefer duplicating — it's 10 lines and keeps files independent).

- [ ] **Step 4: Run tests, verify pass**

- [ ] **Step 5: Commit**

```bash
git add income_desk/retrospection/commentary.py tests/test_retrospection_commentary.py
git commit -m "feat(retrospection): exit quality commentary dimension"
```

---

### Task 7: Hindsight Dimension (Open Trades)

**Files:**
- Modify: `income_desk/retrospection/commentary.py`
- Test: `tests/test_retrospection_commentary.py`

- [ ] **Step 1: Write failing tests**

```python
from income_desk.retrospection.commentary import analyze_hindsight
from income_desk.retrospection.models import TradeSnapshot, LegRecord


class TestHindsight:
    def test_position_doing_well(self):
        snap = TradeSnapshot(
            trade_id="x", ticker="SPY", strategy_type="iron_condor",
            current_pnl=80.0, current_pnl_pct=40.0,
            dte_remaining=15, current_delta=-0.05,
            underlying_price_at_entry=560.0, underlying_price_now=558.0,
        )
        f = analyze_hindsight(snap)
        assert f.score >= 75

    def test_underlying_moved_toward_short_strike(self):
        snap = TradeSnapshot(
            trade_id="x", ticker="SPY", strategy_type="iron_condor",
            current_pnl=-50.0, current_pnl_pct=-25.0,
            dte_remaining=10, current_delta=-0.30,
            underlying_price_at_entry=560.0, underlying_price_now=575.0,
        )
        f = analyze_hindsight(snap)
        assert f.score < 60
        assert "moved" in f.narrative.lower() or "delta" in f.narrative.lower()

    def test_profitable_nearing_target(self):
        snap = TradeSnapshot(
            trade_id="x", ticker="GLD", strategy_type="credit_spread",
            current_pnl=120.0, current_pnl_pct=60.0,
            dte_remaining=8,
        )
        f = analyze_hindsight(snap)
        assert f.score >= 80
        assert "profit" in f.narrative.lower() or "target" in f.narrative.lower()

    def test_low_dte_with_loss(self):
        snap = TradeSnapshot(
            trade_id="x", ticker="QQQ", strategy_type="iron_condor",
            current_pnl=-100.0, current_pnl_pct=-50.0,
            dte_remaining=3,
        )
        f = analyze_hindsight(snap)
        assert f.score < 50
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement `analyze_hindsight`**

```python
def analyze_hindsight(snap: TradeSnapshot) -> DimensionFinding:
    """Evaluate current position state with hindsight — how's it doing now?"""
    score = 70
    observations: list[str] = []

    pnl_pct = snap.current_pnl_pct or 0
    dte = snap.dte_remaining

    # PnL trajectory
    if pnl_pct >= 50:
        score += 15
        observations.append(f"Position at {pnl_pct:.0f}% profit — approaching target.")
    elif pnl_pct >= 20:
        score += 5
        observations.append(f"Position at {pnl_pct:.0f}% profit — on track.")
    elif pnl_pct <= -50:
        score -= 20
        observations.append(f"Position at {pnl_pct:.0f}% — significant loss. Consider management.")
    elif pnl_pct < 0:
        score -= 10
        observations.append(f"Position at {pnl_pct:.0f}% — underwater but manageable.")

    # DTE urgency
    if dte is not None:
        if dte <= 3 and pnl_pct < 0:
            score -= 15
            observations.append(f"Only {dte} DTE remaining with a loss — gamma risk elevated.")
        elif dte <= 7 and pnl_pct < -25:
            score -= 10
            observations.append(f"{dte} DTE with {pnl_pct:.0f}% loss — consider closing to avoid further decay risk.")
        elif dte <= 5 and pnl_pct > 0:
            observations.append(f"{dte} DTE, profitable — consider closing to lock in gains.")

    # Underlying movement
    if snap.underlying_price_at_entry and snap.underlying_price_now:
        move_pct = (snap.underlying_price_now - snap.underlying_price_at_entry) / snap.underlying_price_at_entry * 100
        if abs(move_pct) > 3:
            direction = "up" if move_pct > 0 else "down"
            observations.append(f"Underlying moved {move_pct:+.1f}% {direction} since entry.")
            if pnl_pct < 0:
                score -= 5

    # Delta exposure
    if snap.current_delta is not None and abs(snap.current_delta) > 0.30:
        observations.append(f"Net delta at {snap.current_delta:.2f} — directional exposure building.")
        score -= 5

    score = max(0, min(100, score))
    narrative = " ".join(observations) if observations else "Position within expected parameters."

    return DimensionFinding(
        dimension="hindsight", grade=_score_to_grade(score), score=score,
        narrative=narrative,
        details={
            "current_pnl_pct": pnl_pct,
            "dte_remaining": dte,
            "current_delta": snap.current_delta,
            "underlying_move_pct": round(
                (snap.underlying_price_now - snap.underlying_price_at_entry) / snap.underlying_price_at_entry * 100, 2
            ) if snap.underlying_price_at_entry and snap.underlying_price_now else None,
        },
    )
```

- [ ] **Step 4: Run tests, verify pass**

- [ ] **Step 5: Commit**

```bash
git add income_desk/retrospection/commentary.py tests/test_retrospection_commentary.py
git commit -m "feat(retrospection): hindsight commentary dimension"
```

---

### Task 8: Trade Commentary Composer + Decision Commentary

**Files:**
- Modify: `income_desk/retrospection/commentary.py`
- Test: `tests/test_retrospection_commentary.py`

- [ ] **Step 1: Write failing tests**

```python
from income_desk.retrospection.commentary import (
    compose_trade_commentary,
    generate_decision_commentary,
)
from income_desk.retrospection.models import (
    TradeOpened, TradeClosed, TradeSnapshot, DecisionRecord,
    LegRecord, EntryAnalytics, PositionSize,
)


class TestComposer:
    def test_compose_opened_trade(self):
        trade = TradeOpened(
            trade_id="abc", ticker="SPY", strategy_type="iron_condor",
            market="US", entry_price=3.20,
            entry_underlying_price=560.0,
            entry_analytics=EntryAnalytics(regime_at_entry="R1", pop_at_entry=0.72),
            position_size=PositionSize(capital_at_risk_pct=2.0, contracts=1),
            legs=[
                LegRecord(action="STO", strike=540, option_type="put", entry_delta=-0.20, quantity=-1),
                LegRecord(action="BTO", strike=535, option_type="put", entry_delta=-0.12, quantity=1),
                LegRecord(action="STO", strike=580, option_type="call", entry_delta=0.20, quantity=-1),
                LegRecord(action="BTO", strike=585, option_type="call", entry_delta=0.12, quantity=1),
            ],
        )
        tc = compose_trade_commentary(trade, trade_type="opened")
        assert tc.ticker == "SPY"
        assert len(tc.dimensions) >= 4  # regime, strike, pricing, sizing
        assert tc.overall_narrative  # not empty
        assert tc.key_lesson is not None

    def test_compose_closed_trade(self):
        trade = TradeClosed(
            trade_id="xyz", ticker="QQQ", strategy_type="iron_condor",
            exit_reason="profit_target", total_pnl=150.0,
            max_pnl_during_hold=180.0, holding_days=14,
        )
        tc = compose_trade_commentary(trade, trade_type="closed")
        assert len(tc.dimensions) >= 2  # at least exit_quality + regime
        assert "QQQ" in tc.overall_narrative or "iron_condor" in tc.overall_narrative


class TestDecisionCommentary:
    def test_groups_rejections(self):
        decisions = [
            DecisionRecord(id="1", ticker="SPY", strategy="iron_condor", score=0.72, gate_result="PASS", response="approved"),
            DecisionRecord(id="2", ticker="TSLA", strategy="iron_condor", score=0.15, gate_result="Score 0.15 < 0.35", response="rejected"),
            DecisionRecord(id="3", ticker="AAPL", strategy="calendar", score=0.45, gate_result="NO_GO verdict", response="rejected"),
            DecisionRecord(id="4", ticker="GLD", strategy="diagonal", score=0.55, gate_result="Score cap applied", response="rejected"),
        ]
        dc = generate_decision_commentary(decisions)
        assert dc.narrative  # not empty
        assert len(dc.near_misses) >= 1  # AAPL at 0.45
        assert len(dc.missed_opportunities) >= 1  # GLD at 0.55

    def test_all_approved(self):
        decisions = [
            DecisionRecord(id="1", ticker="SPY", strategy="iron_condor", score=0.72, gate_result="PASS", response="approved"),
        ]
        dc = generate_decision_commentary(decisions)
        assert dc.near_misses == []
        assert dc.missed_opportunities == []
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement composer and decision commentary**

Add to `commentary.py`:

```python
from income_desk.retrospection.models import (
    DecisionCommentary,
    DecisionRecord,
    DimensionFinding,
    LegRecord,
    PositionSize,
    TradeCommentary,
    TradeClosed,
    TradeOpened,
    TradeSnapshot,
)


def compose_trade_commentary(
    trade: TradeOpened | TradeClosed | TradeSnapshot,
    trade_type: str = "opened",  # "opened", "closed", "snapshot"
) -> TradeCommentary:
    """Compose full commentary for a single trade across all applicable dimensions."""
    dims: list[DimensionFinding] = []

    ticker = trade.ticker
    strategy = trade.strategy_type
    market = getattr(trade, "market", "US")

    # 1. Regime alignment
    regime = None
    confidence = None
    if isinstance(trade, TradeOpened) and trade.entry_analytics:
        regime = trade.entry_analytics.regime_at_entry
    elif isinstance(trade, TradeClosed):
        regime = trade.entry_regime
    dims.append(analyze_regime_alignment(strategy, regime, confidence))

    # 2. Strike placement
    legs = getattr(trade, "legs", [])
    underlying = 0.0
    if isinstance(trade, TradeOpened):
        underlying = trade.entry_underlying_price
    elif isinstance(trade, TradeSnapshot):
        underlying = trade.underlying_price_at_entry or 0.0
    dims.append(analyze_strike_placement(legs, strategy, underlying))

    # 3. Entry pricing
    entry_price = getattr(trade, "entry_price", 0.0)
    # Derive wing width from legs
    wing_width = _derive_wing_width(legs)
    lot_size = 100 if market == "US" else 25  # simplified
    currency = "INR" if market == "India" else "USD"
    dims.append(analyze_entry_pricing(entry_price, legs, strategy, wing_width, lot_size, currency))

    # 4. Position sizing
    pos_size = getattr(trade, "position_size", None)
    dims.append(analyze_position_sizing(pos_size))

    # 5. Exit quality (closed only)
    if isinstance(trade, TradeClosed):
        dims.append(analyze_exit_quality(trade))

    # 6. Hindsight (snapshot only)
    if isinstance(trade, TradeSnapshot):
        dims.append(analyze_hindsight(trade))

    # Compose overall narrative from top findings
    key_points = [d.narrative for d in dims if d.score <= 60 or d.score >= 85]
    if not key_points:
        key_points = [d.narrative for d in dims[:2]]
    overall = f"{ticker} {strategy}: " + " ".join(key_points[:3])

    # Should have avoided?
    avoid = any(d.dimension == "regime_alignment" and d.grade in ("D", "F") for d in dims)
    avoid_reason = next(
        (d.narrative for d in dims if d.dimension == "regime_alignment" and d.grade in ("D", "F")),
        None,
    )

    # Key lesson — pick the lowest-scoring dimension
    worst = min(dims, key=lambda d: d.score)
    lesson = worst.narrative if worst.score < 70 else None

    return TradeCommentary(
        trade_id=getattr(trade, "trade_id", ""),
        ticker=ticker,
        strategy=strategy,
        market=market,
        overall_narrative=overall,
        dimensions=dims,
        should_have_avoided=avoid,
        avoidance_reason=avoid_reason,
        key_lesson=lesson,
    )


def _derive_wing_width(legs: list[LegRecord]) -> float | None:
    """Derive wing width from leg strikes (short - long on same side)."""
    shorts = {l.option_type: l.strike for l in legs if l.action == "STO" and l.strike}
    longs = {l.option_type: l.strike for l in legs if l.action == "BTO" and l.strike}
    widths = []
    for ot in ("put", "call"):
        if ot in shorts and ot in longs:
            widths.append(abs(shorts[ot] - longs[ot]))
    return widths[0] if widths else None


def generate_decision_commentary(decisions: list[DecisionRecord]) -> DecisionCommentary:
    """Analyze the day's approval/rejection patterns."""
    approved = [d for d in decisions if d.response == "approved"]
    rejected = [d for d in decisions if d.response != "approved"]

    # Group rejections by reason
    reason_counts: dict[str, int] = {}
    near_misses = []
    missed_opps = []

    for d in rejected:
        reason = d.gate_result or "unknown"
        # Bucket the reason
        if "score" in reason.lower() and "<" in reason:
            bucket = "low_score"
        elif "no_go" in reason.lower():
            bucket = "no_go_verdict"
        elif "structure" in reason.lower():
            bucket = "structure_blocked"
        else:
            bucket = reason[:30]
        reason_counts[bucket] = reason_counts.get(bucket, 0) + 1

        # Near misses: score 0.35-0.50
        if 0.35 <= d.score < 0.50:
            near_misses.append({
                "ticker": d.ticker, "strategy": d.strategy,
                "score": d.score, "gate_result": d.gate_result,
            })

        # Missed opportunities: score >= 0.50 but rejected
        if d.score >= 0.50:
            missed_opps.append({
                "ticker": d.ticker, "strategy": d.strategy,
                "score": d.score, "gate_result": d.gate_result,
            })

    narrative = (
        f"{len(decisions)} decisions: {len(approved)} approved, {len(rejected)} rejected. "
    )
    if near_misses:
        narrative += f"{len(near_misses)} near-misses (score 0.35-0.50). "
    if missed_opps:
        narrative += f"{len(missed_opps)} potential missed opportunities (score >= 0.50 but rejected). "

    return DecisionCommentary(
        near_misses=near_misses,
        missed_opportunities=missed_opps,
        rejection_summary=reason_counts,
        narrative=narrative,
    )
```

- [ ] **Step 4: Run tests, verify pass**

- [ ] **Step 5: Commit**

```bash
git add income_desk/retrospection/commentary.py tests/test_retrospection_commentary.py
git commit -m "feat(retrospection): trade commentary composer + decision commentary"
```

---

### Task 9: Wire Into Engine + Integration Test

**Files:**
- Modify: `income_desk/retrospection/engine.py:150-232`
- Modify: `income_desk/retrospection/__init__.py`
- Test: `tests/test_retrospection_commentary.py`

- [ ] **Step 1: Write integration test**

```python
import json
from pathlib import Path
from income_desk.retrospection import RetrospectionEngine


class TestCommentaryIntegration:
    def test_engine_produces_commentary(self):
        """Run engine on the real eTrading input and verify commentary is generated."""
        input_path = Path.home() / ".income_desk" / "retrospection" / "etrading_retrospection_input.json"
        if not input_path.exists():
            pytest.skip("No eTrading input file available")

        engine = RetrospectionEngine()
        result = engine.analyze_file(input_path)

        assert result is not None
        fb = result.feedback
        # Should have trade commentaries for opened trades
        assert len(fb.trade_commentaries) > 0

        # Each commentary has dimensions
        for tc in fb.trade_commentaries:
            assert tc.ticker
            assert tc.strategy
            assert len(tc.dimensions) >= 2
            assert tc.overall_narrative

            for dim in tc.dimensions:
                assert dim.dimension
                assert dim.grade
                assert 0 <= dim.score <= 100
                assert dim.narrative

        # Decision commentary should exist
        assert fb.decision_commentary is not None
        assert fb.decision_commentary.narrative
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Wire commentary into engine `_analyze()`**

In `engine.py`, add import and call after existing audits:

```python
# At top of file, add import:
from income_desk.retrospection.commentary import (
    compose_trade_commentary,
    generate_decision_commentary,
)

# In _analyze(), after line ~183 (learning recommendations), add:

        # Trade commentary (per-trade narrative)
        trade_commentaries = []
        for t in inp.trades_opened:
            trade_commentaries.append(compose_trade_commentary(t, trade_type="opened"))
        for t in inp.trades_closed:
            trade_commentaries.append(compose_trade_commentary(t, trade_type="closed"))
        for t in inp.trades_open_snapshot:
            trade_commentaries.append(compose_trade_commentary(t, trade_type="snapshot"))

        # Decision commentary
        decision_commentary = generate_decision_commentary(inp.decisions)
```

Pass both to the `RetrospectionFeedback` constructor:

```python
        feedback = RetrospectionFeedback(
            # ... existing fields ...
            trade_commentaries=trade_commentaries,
            decision_commentary=decision_commentary,
        )
```

- [ ] **Step 4: Update `__init__.py` exports**

Add `TradeCommentary`, `DecisionCommentary`, `DimensionFinding` to `__all__` and imports.

- [ ] **Step 5: Run ALL tests**

Run: `.venv_312/Scripts/python -m pytest tests/test_retrospection_commentary.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run engine on real data to verify output**

```bash
.venv_312/Scripts/python -c "
from income_desk.retrospection import RetrospectionEngine
engine = RetrospectionEngine()
result = engine.analyze_file(engine.input_path)
for tc in result.feedback.trade_commentaries[:3]:
    print(f'--- {tc.ticker} {tc.strategy} ---')
    print(tc.overall_narrative)
    for d in tc.dimensions:
        print(f'  [{d.grade}] {d.dimension}: {d.narrative}')
    if tc.key_lesson:
        print(f'  LESSON: {tc.key_lesson}')
    print()
dc = result.feedback.decision_commentary
print(dc.narrative)
print(f'Near misses: {len(dc.near_misses)}, Missed opps: {len(dc.missed_opportunities)}')
"
```

- [ ] **Step 7: Commit**

```bash
git add income_desk/retrospection/engine.py income_desk/retrospection/commentary.py income_desk/retrospection/__init__.py tests/test_retrospection_commentary.py
git commit -m "feat(retrospection): wire trade commentary into engine"
```

---

### Task 10: Write eTrading Change Notification

**Files:**
- Write to: `C:/Users/nitin/.income_desk/retrospection/id_retrospection_request.json`

- [ ] **Step 1: Write change notification to shared file**

Write a request to eTrading informing them of the new fields in `id_retrospection_feedback.json`:

```python
{
    "version": "1.0",
    "requested_at": "<now>",
    "requests": [
        {
            "request_id": "change-001",
            "type": "schema_change",
            "fields_needed": [],
            "reason": "New fields added to retrospection feedback",
            "message": "id_retrospection_feedback.json now includes: trade_commentaries (list[TradeCommentary]) and decision_commentary (DecisionCommentary). Each TradeCommentary has 6 dimensions with grade/score/narrative. Additive change — existing fields unchanged. See docs/superpowers/specs/2026-03-24-trade-commentary-design.md for full schema."
        }
    ]
}
```

- [ ] **Step 2: Commit everything**

```bash
git add docs/superpowers/specs/2026-03-24-trade-commentary-design.md docs/superpowers/plans/2026-03-24-trade-commentary.md
git commit -m "docs: trade commentary design spec and implementation plan"
```
