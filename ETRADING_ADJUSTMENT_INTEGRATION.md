# eTrading: Trade Adjustment Integration Checklist

All adjustment logic operates at **strategy level**, not leg level.
MA tells eTrading: "close these legs, open these legs." eTrading executes the orders.

---

## APIs to Integrate

### 1. `AdjustmentService.analyze()` — Full ranked menu (for human review UI)

```python
from market_analyzer.service.adjustment import AdjustmentService

analysis: AdjustmentAnalysis = ma.adjustment.analyze(
    trade_spec=trade_spec,   # TradeSpec — the original trade as entered
    regime=regime_result,    # RegimeResult from ma.regime.detect(ticker)
    technicals=tech,         # TechnicalSnapshot from ma.technicals.analyze(ticker)
    vol_surface=None,        # Optional VolatilitySurface
)
```

**Returns:** `AdjustmentAnalysis` — ranked list of adjustment options, best first.

**Use for:** "Show me my options" UI screen — human picks from the ranked list.

---

### 2. `AdjustmentService.recommend_action()` — Single deterministic action (for automation)

```python
decision: AdjustmentDecision = ma.adjustment.recommend_action(
    trade_spec=trade_spec,
    regime=regime_result,
    technicals=tech,
)
```

**Returns:** `AdjustmentDecision` — exactly ONE action with rationale.

**Decision tree (hardcoded, no overrides):**

| Position Status | Regime | Action |
|----------------|--------|--------|
| MAX_LOSS | any | CLOSE_FULL (immediate) |
| BREACHED | R3 or R4 | CLOSE_FULL (immediate) |
| BREACHED | R1 or R2 | ROLL_AWAY (soon) |
| TESTED | R4 | CLOSE_FULL (immediate) |
| TESTED | R3 | ROLL_AWAY (soon) |
| TESTED | R1 or R2 | DO_NOTHING |
| SAFE | any | DO_NOTHING |

**Use for:** Systematic/automated trading — no human in the loop.

---

### 3. `get_adjustment_recommendation()` — Wrapper in trade_lifecycle.py

```python
from market_analyzer.trade_lifecycle import get_adjustment_recommendation

decision: AdjustmentDecision = get_adjustment_recommendation(
    trade_spec=trade_spec,
    regime=regime_result,
    technicals=tech,
    adjustment_service=ma.adjustment,
)
```

Same as `recommend_action()` but accessible from the trade lifecycle module.

---

## What MA Returns — Key Fields to Use

### `AdjustmentAnalysis` (from `analyze()`)

| Field | Type | Use |
|-------|------|-----|
| `position_status` | `PositionStatus` | SAFE / TESTED / BREACHED / MAX_LOSS |
| `tested_side` | `TestedSide` | NONE / PUT / CALL / BOTH |
| `distance_to_short_put_pct` | `float \| None` | % distance from price to short put |
| `distance_to_short_call_pct` | `float \| None` | % distance from price to short call |
| `pnl_estimate` | `float \| None` | Current mark P&L (None without broker) |
| `remaining_dte` | `int` | Days left on trade |
| `adjustments` | `list[AdjustmentOption]` | Ranked list, best first |
| `recommendation` | `str` | One-line top recommendation |

### `AdjustmentOption` (each item in `adjustments`)

| Field | Type | Use |
|-------|------|-----|
| `adjustment_type` | `AdjustmentType` | DO_NOTHING / CLOSE_FULL / ROLL_AWAY / etc. |
| `close_legs` | `list[LegSpec]` | **Legs to close** — build close orders from these |
| `new_legs` | `list[LegSpec]` | **Legs to open** — build open orders from these |
| `estimated_cost` | `float \| None` | Net cost (negative = credit received). None without broker |
| `risk_change` | `float` | Dollar risk removed (negative = good) |
| `urgency` | `str` | "none" / "monitor" / "soon" / "immediate" |
| `rationale` | `str` | Human-readable explanation |

### `AdjustmentDecision` (from `recommend_action()`)

| Field | Type | Use |
|-------|------|-----|
| `action` | `AdjustmentType` | The single chosen action |
| `urgency` | `str` | How fast to act |
| `rationale` | `str` | Why this action was chosen |
| `detail` | `AdjustmentOption \| None` | Full adjustment spec if action != DO_NOTHING |
| `position_status` | `PositionStatus` | Status that triggered this decision |

---

## How to Execute an Adjustment

MA returns `close_legs` and `new_legs` — eTrading must translate these to broker orders.

```python
option = analysis.adjustments[0]  # or decision.detail

# Step 1: Close legs (BTC/STC)
for leg in option.close_legs:
    # leg.action is the ORIGINAL action (STO/BTO)
    # To close: flip it — STO → BTC, BTO → STC
    close_action = "BTC" if leg.action == LegAction.SELL_TO_OPEN else "STC"
    submit_order(
        ticker=trade_spec.ticker,
        option_type=leg.option_type,
        strike=leg.strike,
        expiration=leg.expiration,
        action=close_action,
        quantity=leg.quantity,
    )

# Step 2: Open new legs (if any)
for leg in option.new_legs:
    submit_order(
        ticker=trade_spec.ticker,
        option_type=leg.option_type,
        strike=leg.strike,
        expiration=leg.expiration,
        action=leg.action,   # STO or BTO as-is
        quantity=leg.quantity,
    )
```

**Important:** Submit close legs and open legs as a single multi-leg order where possible (reduces slippage and partial-fill risk).

---

## Position Status Thresholds

MA computes status using ATR:

| Status | Condition |
|--------|-----------|
| SAFE | Price > 1 ATR from short strike |
| TESTED | Price within 0–1 ATR of short strike |
| BREACHED | Price past short strike |
| MAX_LOSS | Price past protective wing |

These are re-computed every time `analyze()` or `recommend_action()` is called. eTrading should call these on a schedule (e.g., every 5 minutes during market hours) and act on the urgency level.

---

## Structure Types Supported

| `StructureType` | Adjustments Available |
|----------------|----------------------|
| `IRON_CONDOR` | ROLL_AWAY (put/call), NARROW_UNTESTED, CONVERT (to butterfly), ROLL_OUT |
| `IRON_MAN` | Same as IRON_CONDOR |
| `IRON_BUTTERFLY` | Same as IRON_CONDOR |
| `CREDIT_SPREAD` | ROLL_AWAY, ROLL_OUT |
| `CALENDAR` / `DOUBLE_CALENDAR` | ROLL_OUT (front leg) |
| `RATIO_SPREAD` | ADD_WING (to cap naked risk) |
| `DEBIT_SPREAD` | CLOSE_FULL at profit target |
| `STRADDLE` / `STRANGLE` | ADD_WING (define risk), CLOSE_FULL (tested side) |

All structures also get DO_NOTHING and CLOSE_FULL as baseline options.

---

## Integration Checklist

### Broker Connection
- [ ] Pass `market_data` and `market_metrics` when constructing `MarketAnalyzer` — this wires `OptionQuoteService` and enables real `estimated_cost` values from DXLink quotes
- [ ] If `estimated_cost` is `None` despite broker being connected, that is a **data error** — DXLink failed to price that leg. Log it, alert, and do not execute the adjustment blindly

### Calling the APIs
- [ ] Call `analyze()` for any UI that shows adjustment options to a human
- [ ] Call `recommend_action()` for any automated/systematic path (no menus, single action)
- [ ] Pass `RegimeResult` from `ma.regime.detect(ticker)` — not a hardcoded regime
- [ ] Pass `TechnicalSnapshot` from `ma.technicals.analyze(ticker)` — current price and ATR matter

### Executing Orders
- [ ] Use `close_legs` to build close orders — **flip the action** (STO→BTC, BTO→STC)
- [ ] Use `new_legs` to build open orders — use `leg.action` as-is
- [ ] Send as a single multi-leg order where broker supports it
- [ ] Validate `estimated_cost` before executing — negative = net credit (good), positive = net debit (you pay)

### Urgency Handling
- [ ] `"immediate"` → execute within current bar, alert user if manual
- [ ] `"soon"` → execute within current session
- [ ] `"monitor"` → check again next bar, no action needed now
- [ ] `"none"` → position healthy, no action

### DO_NOTHING Handling
- [ ] `DO_NOTHING` always appears first in `analysis.adjustments` — it is the baseline, not a bug
- [ ] For `recommend_action()` returning DO_NOTHING: take no order action, just log

### Data Gaps
- [ ] `pnl_estimate = None` → DXLink failed to price one or more legs — log and alert, do not show $0
- [ ] `estimated_cost = None` → DXLink pricing failed for this adjustment — do not execute, investigate quote fetch
- [ ] Do not skip adjustments with `None` cost — they are still valid actions, but require manual cost verification before executing

---

## Monitoring Frequency Recommendation

| Urgency Needed | Check Interval |
|---------------|----------------|
| 0DTE positions | Every bar (5 min) |
| Weekly income trades | Every 30 min |
| Monthly income trades | Hourly |
| After regime change | Immediately re-check all open trades |
