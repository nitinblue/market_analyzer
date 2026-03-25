# Trade Commentary Retrospection — Design Spec

**Date:** 2026-03-24
**Status:** Approved
**Goal:** Per-trade narrative commentary in retrospection engine — structured for eTrading integration, readable for human review.

---

## Problem

The retrospection engine produces mechanical checks (PnL verification, gate consistency, risk audit) but no trade-by-trade reasoning. Nitin and eTrading need commentary that explains *why* each trade was good/bad, what could improve, and what lessons to carry forward.

## Design

### 6 Commentary Dimensions

Every opened/closed/snapshot trade is analyzed across 6 dimensions. Each produces a grade, score, narrative sentence, and structured details.

| # | Dimension | Applies To | What It Evaluates |
|---|-----------|-----------|-------------------|
| 1 | `regime_alignment` | All | Strategy vs regime state (R1-R4 compatibility) |
| 2 | `strike_placement` | Options | Short strike deltas, wing width, distance from underlying |
| 3 | `entry_pricing` | All | Credit/debit vs wing width, ROC, premium quality |
| 4 | `position_sizing` | All | Capital at risk %, portfolio fit, contract count |
| 5 | `exit_quality` | Closed only | Exit timing, profit left on table, holding period |
| 6 | `hindsight` | All | Current state vs entry — what do we know now? |

### Decision Commentary (Rejected Trades)

433 decisions per day, most correctly rejected. Commentary focuses on:
- **Near-misses** (score 0.35-0.50, rejected by gates) — were they right to reject?
- **High-score rejects** (score >= 0.50, gate failed) — missed opportunities?
- **Mass rejects** (score < 0.20) — summarized as a group, not individually

### Data Models

```python
class DimensionFinding(BaseModel):
    dimension: str          # "regime_alignment", "strike_placement", etc.
    grade: str              # A/B/C/D/F
    score: int              # 0-100
    narrative: str          # Human-readable sentence
    details: dict = {}      # Structured data for eTrading rendering

class TradeCommentary(BaseModel):
    trade_id: str
    ticker: str
    strategy: str
    market: str
    overall_narrative: str              # 2-3 sentence summary
    dimensions: list[DimensionFinding]
    should_have_avoided: bool
    avoidance_reason: str | None = None
    key_lesson: str | None = None       # One actionable takeaway

class DecisionCommentary(BaseModel):
    near_misses: list[dict]             # Score 0.35-0.50, gate rejected
    missed_opportunities: list[dict]    # Score >= 0.50, gate rejected
    rejection_summary: dict             # Counts by rejection reason
    narrative: str                      # "433 decisions: 30 approved..."
```

### Integration Points

**RetrospectionFeedback** gains two new fields:
```python
trade_commentaries: list[TradeCommentary] = []
decision_commentary: DecisionCommentary | None = None
```

**Engine method:** `_generate_commentary(inp, trade_audits) -> list[TradeCommentary]`
**Engine method:** `_generate_decision_commentary(decisions) -> DecisionCommentary`

Both called from `_analyze()` after existing domain audits.

### Dimension Logic

**1. Regime Alignment**
- Input: `regime_at_entry` (or `entry_analytics.regime_at_entry`), `strategy_type`
- Rules: Match against `_REGIME_STRATEGIES` table from CLAUDE.md
- Grade A: Strategy in recommended set for regime
- Grade D: Strategy explicitly in "avoid" set for regime
- Grade C: No regime data available (penalize missing data)

**2. Strike Placement**
- Input: `legs[]` with strike, delta, option_type; `entry_underlying_price`
- Rules:
  - Short delta target: 0.16-0.30 for income (iron condors, credit spreads)
  - Wing width: adequate for the strategy (50-wide standard for US, lot-adjusted for India)
  - Distance from underlying: short strikes should be outside 1 SD
- Grade A: Short deltas 0.16-0.25, adequate wings
- Grade C: Short deltas 0.30-0.40 (aggressive)
- Grade F: Short deltas > 0.40 or strikes too close

**3. Entry Pricing**
- Input: `entry_price`, leg prices, wing width from strikes
- Rules:
  - Credit/width ratio: >50% excellent, 33-50% good, <33% thin
  - ROC if available from `entry_analytics`
- Accounts for market (INR vs USD, lot sizes)

**4. Position Sizing**
- Input: `position_size` (capital_at_risk_pct), account context from risk snapshots
- Rules:
  - <=2% of NLV: A
  - 2-3%: B
  - 3-5%: C
  - >5%: D/F

**5. Exit Quality** (closed trades only)
- Input: `exit_reason`, `total_pnl`, `max_pnl_during_hold`, `holding_days`, `pnl_journey`
- Rules:
  - Profit target hit: bonus
  - Had max profit but closed at loss: penalty, "was profitable, review exit timing"
  - Held past 21 DTE for theta: penalty
  - Regime changed during hold without exit: penalty

**6. Hindsight**
- Input: Open snapshot `underlying_price_now` vs `underlying_price_at_entry`, current PnL, current delta
- Rules:
  - Underlying moved toward short strike: warn
  - Delta expanded beyond entry: warn
  - PnL trending negative after being positive: "consider management"

### Constraints

- **No data fetching** — pure computation from eTrading input
- **No LLM calls** — all rule-based, deterministic, testable
- **Handles missing data** — null regime, null analytics → grade C with "insufficient data" narrative
- **Market-aware** — INR/USD, lot sizes, settlement differences

### File Changes

| File | Change |
|------|--------|
| `retrospection/models.py` | Add `DimensionFinding`, `TradeCommentary`, `DecisionCommentary` models |
| `retrospection/models.py` | Add fields to `RetrospectionFeedback` |
| `retrospection/engine.py` | Add `_generate_commentary()`, `_generate_decision_commentary()` |
| `retrospection/engine.py` | Call from `_analyze()` |
| `tests/test_retrospection.py` | Commentary tests with real-shaped data |

### Example Output (JSON)

```json
{
  "trade_id": "e71aec02-...",
  "ticker": "NIFTY",
  "strategy": "iron_condor",
  "market": "India",
  "overall_narrative": "NIFTY iron condor opened without regime data — cannot validate strategy fit. Short put at 0.35 delta is aggressive for income; standard target is 0.16-0.30. Credit of 32.25 on 50-wide wings (64.5% of width) is excellent premium collection.",
  "dimensions": [
    {
      "dimension": "regime_alignment",
      "grade": "C",
      "score": 50,
      "narrative": "No regime data at entry — cannot confirm R1/R2 suitability for iron condor.",
      "details": {"regime": null, "strategy": "iron_condor", "reason": "missing_regime"}
    },
    {
      "dimension": "strike_placement",
      "grade": "C+",
      "score": 68,
      "narrative": "Short put at 0.35 delta is aggressive — standard income targets 0.16-0.30. Short call at 0.39 delta also wide. Consider tighter deltas.",
      "details": {"short_put_delta": -0.35, "short_call_delta": 0.39, "target_range": [0.16, 0.30]}
    },
    {
      "dimension": "entry_pricing",
      "grade": "A",
      "score": 92,
      "narrative": "Collected 32.25 on 50-wide wings — 64.5% of max width. Excellent premium for an iron condor.",
      "details": {"credit": 32.25, "wing_width": 50, "credit_pct": 64.5}
    }
  ],
  "should_have_avoided": false,
  "key_lesson": "Good premium but aggressive deltas — tighten short strikes to 0.20-0.25 range for better probability."
}
```
