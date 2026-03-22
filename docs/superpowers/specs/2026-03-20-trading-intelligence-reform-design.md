# Trading Intelligence Reform — Design Spec

> Transforms income_desk from "signal generator" to "complete trading intelligence system" by closing 10 gaps across exit discipline, position sizing, trade construction, and signal quality.

**Date:** 2026-03-20
**Status:** Approved for implementation
**Scope:** 10 features across 4 sub-systems, ~10 tasks, ~250 new tests

## Motivation

Current state ratings:
- What to buy: 8/10
- When to buy (entry levels): 7.5/10
- How much to buy (sizing): 7.5/10 (Kelly added but unwired)
- When to exit: 7.5/10

Target after reform:
- What to buy: 8.5/10 (+0.5 from strategy switching + IV rank quality)
- When to buy: 8/10 (+0.5 from DTE optimization + IV rank threshold)
- How much to buy: 9/10 (+1.5 from correlated sizing + margin-regime + Kelly wiring)
- When to exit: 9/10 (+1.5 from regime stops + trailing targets + theta decay)

## Sub-system A: Exit Intelligence

### New file: `income_desk/features/exit_intelligence.py`
### New file: `income_desk/models/exit.py`

#### Feature 1: Regime-Contingent Stops

**Problem:** Fixed 2× stop for all regimes. In R2 (high-vol MR), a 2× breach often mean-reverts — premature stop. In R4 (explosive), 2× is too slow — should cut at 1.5×.

**Solution:** `compute_regime_stop(regime_id, structure_type) -> RegimeStop`

| Regime | Stop Multiplier | Rationale |
|--------|----------------|-----------|
| R1 (calm MR) | 2.0× | Standard — breaches are unusual, respect the stop |
| R2 (high-vol MR) | 3.0× | Wider swings are normal — let mean-reversion work |
| R3 (trending) | 1.5× | Trends persist — cut losses fast |
| R4 (explosive) | 1.5× | Maximum risk — tightest stop |

**Model:**
```python
class RegimeStop(BaseModel):
    regime_id: int
    base_multiplier: float
    structure_type: str
    rationale: str
```

**Integration:** `monitor_exit_conditions()` gets optional `regime_stop_multiplier: float | None` parameter. When provided, overrides `stop_loss_pct`. Backward compatible — None means use existing stop_loss_pct.

#### Feature 2: Trailing Profit Targets (Time-Based Acceleration)

**Problem:** Fixed 50% profit target for all holding periods. If you're at 40% profit in 5 days on a 30 DTE trade, the remaining 10% takes 25 more days of risk. Close early and redeploy.

**Solution:** `compute_time_adjusted_target(days_held, dte_at_entry, current_profit_pct, original_target_pct) -> TimeAdjustedTarget`

**Logic:**
```
time_elapsed_pct = days_held / dte_at_entry
profit_velocity = current_profit_pct / max(time_elapsed_pct, 0.01)

If profit_velocity > 2.0 and current_profit_pct >= 0.25:
    # Earning profit 2× faster than expected — close early
    adjusted = max(0.25, original_target - 0.15)
    reason = "Capital velocity: {profit_velocity:.1f}× expected pace"

If time_elapsed_pct > 0.60 and current_profit_pct < 0.15:
    # 60% of time gone, only 15% profit — theta exhausted
    adjusted = max(current_profit_pct, 0.10)
    reason = "Theta exhausted: {time_elapsed_pct:.0%} of time, only {current_profit_pct:.0%} profit"

Else:
    adjusted = original_target  # No adjustment
```

**Model:**
```python
class TimeAdjustedTarget(BaseModel):
    original_target_pct: float
    adjusted_target_pct: float
    days_held: int
    dte_at_entry: int
    time_elapsed_pct: float
    profit_velocity: float
    acceleration_reason: str | None  # None if no adjustment
```

**Integration:** `monitor_exit_conditions()` gets optional `days_held: int | None` and `dte_at_entry: int | None`. When provided, compute time-adjusted target and use it instead of static `profit_target_pct`.

#### Feature 3: Theta Decay Curve Comparison

**Problem:** At 15 DTE with 30% profit, remaining theta is minimal — close and redeploy. At 15 DTE with 10% profit, theta is still working — hold. The decision should be "profit / remaining_theta."

**Solution:** `compute_remaining_theta_value(dte_remaining, dte_at_entry, current_profit_pct) -> ThetaDecayResult`

**Logic:** Theta decay is non-linear — approximated by 1/√DTE:
```
remaining_theta_pct = √(dte_remaining) / √(dte_at_entry)
profit_to_theta_ratio = current_profit_pct / max(remaining_theta_pct, 0.01)

If profit_to_theta_ratio > 3.0: "close_and_redeploy"
    # Captured most available theta — diminishing returns to hold
If profit_to_theta_ratio > 1.5: "approaching_decay_cliff"
    # Monitor closely — theta accelerating
Else: "hold"
    # Theta still working for you
```

**Model:**
```python
class ThetaDecayResult(BaseModel):
    dte_remaining: int
    dte_at_entry: int
    remaining_theta_pct: float      # 0-1, how much theta is left
    current_profit_pct: float
    profit_to_theta_ratio: float
    recommendation: str             # "hold" / "close_and_redeploy" / "approaching_decay_cliff"
    rationale: str
```

**Integration:** `check_trade_health()` calls this and includes recommendation in commentary. Not a hard exit signal — advisory.

---

## Sub-system B: Sizing Intelligence

### Extend: `income_desk/features/position_sizing.py`

#### Feature 4: Pairwise Correlation from OHLCV

**Problem:** `check_correlation_risk()` requires caller-provided correlation data. Kelly sizing ignores correlation between positions.

**Solution:** `compute_pairwise_correlation(returns_a, returns_b, lookback) -> float`

```python
def compute_pairwise_correlation(
    returns_a: list[float],  # Daily log returns
    returns_b: list[float],
    lookback: int = 60,
) -> float:
    # Pearson correlation on last `lookback` returns
    # Returns -1.0 to 1.0
    # Uses only data MA already has (OHLCV cached by DataService)
```

No pandas dependency — pure Python with math module.

#### Feature 5: Correlation-Adjusted Kelly

**Problem:** 3 short-vol ICs on SPY/QQQ/IWM should be sized as ~1.5 positions (high correlation), not 3. Current Kelly treats each independently.

**Solution:** `adjust_kelly_for_correlation(kelly_result, new_ticker, open_tickers, correlation_fn) -> CorrelationAdjustment`

**Logic:**
```
For each open position ticker:
    corr = correlation_fn(new_ticker_returns, existing_ticker_returns)
    if corr > 0.70: count as partial duplicate

max_corr = max correlation with any existing position
penalty = max_corr * 0.5 if max_corr > 0.70 else 0.0
adjusted_kelly = kelly × (1 - penalty)
```

**Model:**
```python
class CorrelationAdjustment(BaseModel):
    original_kelly_fraction: float
    correlation_penalty: float
    adjusted_kelly_fraction: float
    correlated_pairs: list[tuple[str, str, float]]  # (ticker_a, ticker_b, corr)
    effective_position_count: float
    rationale: str
```

#### Feature 6: Regime-Adjusted Margin Estimation

**Problem:** `TradeSpec.position_size()` assumes BP = wing_width × lot_size. In R2, broker margin typically expands 30%+. A 50K account that holds 5 ICs in R1 can only hold 3-4 in R2.

**Solution:** `compute_regime_adjusted_bp(wing_width, regime_id, lot_size) -> RegimeMarginEstimate`

| Regime | Margin Multiplier | Rationale |
|--------|------------------|-----------|
| R1 | 1.0× | Standard margin |
| R2 | 1.3× | Broker raises margin in high vol |
| R3 | 1.1× | Slight increase for trending |
| R4 | 1.5× | Maximum margin expansion |

**Model:**
```python
class RegimeMarginEstimate(BaseModel):
    base_bp_per_contract: float
    regime_id: int
    regime_multiplier: float
    adjusted_bp_per_contract: float
    max_contracts_by_margin: int
    rationale: str
```

#### Feature 7: Unified Position Sizing (Wire Kelly End-to-End)

**Problem:** `compute_kelly_position_size()` exists but nobody calls it. `TradeSpec.position_size()` uses fixed 2%. No unified API.

**Solution:** `compute_position_size(trade_spec, pop_estimate, capital, exposure, regime_id, correlation_fn) -> KellyResult`

This is the "master" sizing function that chains:
1. `compute_kelly_fraction()` — raw Kelly from POP/R:R
2. `compute_kelly_position_size()` — apply safety factor + portfolio exposure
3. `adjust_kelly_for_correlation()` — reduce for correlated positions
4. `compute_regime_adjusted_bp()` — cap by regime-aware margin
5. Return final `KellyResult` with all adjustments shown

---

## Sub-system C: Trade Construction Intelligence

### New file: `income_desk/features/dte_optimizer.py`

#### Feature 8: DTE Optimization from Vol Surface

**Problem:** Assessors default to 30-45 DTE. But if 21 DTE IV is 28% and 45 DTE IV is 22%, the 21 DTE trade has more theta per day.

**Solution:** `select_optimal_dte(vol_surface, regime_id, strategy, min_dte, max_dte) -> DTERecommendation`

**Logic:**
```
For each expiration in vol_surface.term_structure:
    if min_dte <= days_to_expiry <= max_dte:
        theta_proxy = atm_iv * √(1 / days_to_expiry)
        # Higher theta_proxy = more daily theta per unit of IV

Pick expiration with highest theta_proxy.

Regime adjustment:
    R1: prefer 30-45 DTE (standard theta harvesting window)
    R2: prefer 21-30 DTE (shorter exposure to vol swings)
    R3: prefer 21 DTE (minimize time in adverse trend)
    R4: prefer 14-21 DTE (defined risk, minimum exposure)
```

**Model:**
```python
class DTERecommendation(BaseModel):
    recommended_dte: int
    recommended_expiration: date
    theta_proxy: float
    iv_at_expiration: float
    all_candidates: list[dict]  # All evaluated DTEs with scores
    regime_preference: str       # "30-45 DTE (R1 standard)"
    rationale: str
```

### Extend: `income_desk/service/adjustment.py`

#### Feature 9: Strategy Switching on Regime Change

**Problem:** When regime shifts R1→R3 mid-trade, the adjustment service says "roll or close." The quant-optimal move is "convert to diagonal" — rotate the structure to match the new regime.

**Solution:** Add `CONVERT_TO_DIAGONAL` and `CONVERT_TO_CALENDAR` to `AdjustmentType`. Modify `recommend_action()` decision tree.

**New adjustment types:**
```python
# Add to AdjustmentType enum:
CONVERT_TO_DIAGONAL = "convert_to_diagonal"
CONVERT_TO_CALENDAR = "convert_to_calendar"
```

**New decision logic:**
```
If TESTED + regime changed R1/R2 → R3:
    If bullish trend: CONVERT_TO_DIAGONAL (bull call diagonal)
    If bearish trend: CONVERT_TO_DIAGONAL (bear put diagonal)
    # Close tested side, open diagonal in trend direction

If one side of IC profitable (short call at 80%+ profit) + other side neutral:
    CONVERT_TO_CALENDAR on the profitable side
    # Close profitable side, open calendar for additional theta
```

**Integration:** `recommend_action()` gets `entry_regime_id: int | None` parameter to detect regime change. Backward compatible — None means no switching logic.

---

## Sub-system D: Signal Quality

### Extend: `income_desk/features/entry_levels.py`

#### Feature 10: IV Rank Entry Threshold by Ticker Type

**Problem:** "SPY IV rank 42" and "AAPL IV rank 42" look the same but aren't. ETF IV is structurally lower — IV rank 30+ is already elevated. Individual equities need IV rank 45+ for the same signal quality.

**Solution:** `compute_iv_rank_quality(current_iv_rank, ticker_type) -> IVRankQuality`

| Ticker Type | "Good" IV Rank | "Wait" | "Avoid" |
|---|---|---|---|
| ETF (SPY, QQQ, GLD) | ≥ 30 | 20-30 | < 20 |
| Equity (AAPL, MSFT) | ≥ 45 | 30-45 | < 30 |
| Index (SPX, NDX) | ≥ 25 | 15-25 | < 15 |

**Model:**
```python
class IVRankQuality(BaseModel):
    current_iv_rank: float
    ticker_type: str
    threshold_good: float
    threshold_wait: float
    quality: str  # "good" / "wait" / "avoid"
    rationale: str
```

### Extend: `income_desk/models/adjustment.py`

#### Feature 11: Adjustment P&L Tracking

**Problem:** No tracking of whether past adjustments helped. The system adjusts positions but never learns which adjustments work.

**Solution:** New model `AdjustmentOutcome` + analysis function `analyze_adjustment_effectiveness(outcomes)`

**Model:**
```python
class AdjustmentOutcome(BaseModel):
    trade_id: str
    adjustment_type: str  # AdjustmentType value
    adjustment_date: date
    cost: float  # What the adjustment cost (negative = credit received)
    subsequent_pnl: float  # P&L from adjustment date to close
    was_profitable: bool  # cost + subsequent_pnl > 0
    regime_at_adjustment: int
    position_status_at_adjustment: str

class AdjustmentEffectiveness(BaseModel):
    by_type: dict[str, dict]  # Per adjustment type: win_rate, avg_cost, avg_subsequent_pnl
    by_regime: dict[int, dict]  # Per regime: which adjustments work best
    recommendations: list[str]  # "ROLL_AWAY wins 62% in R2, skip in R4"
    total_outcomes: int
```

---

## File Structure

```
NEW files (create):
  income_desk/models/exit.py                    # RegimeStop, TimeAdjustedTarget, ThetaDecayResult
  income_desk/features/exit_intelligence.py     # 3 exit functions
  income_desk/features/dte_optimizer.py         # DTE selection from vol surface
  tests/test_exit_intelligence.py                   # Exit function tests
  tests/test_dte_optimizer.py                       # DTE optimizer tests
  tests/functional/test_reform.py                   # End-to-end reform tests

EXTEND files (modify):
  income_desk/features/position_sizing.py       # +correlation, +margin-regime, +unified sizing
  income_desk/features/entry_levels.py          # +IV rank quality
  income_desk/models/adjustment.py              # +AdjustmentOutcome, +CONVERT types
  income_desk/service/adjustment.py             # +strategy switching logic
  income_desk/trade_lifecycle.py                # Wire regime stops + trailing targets
  income_desk/validation/daily_readiness.py     # Wire IV rank quality check (#10)
  income_desk/__init__.py                       # Wire all new exports
  income_desk/cli/interactive.py                # CLI commands
  tests/test_position_sizing.py                     # +correlation, +margin tests
  tests/test_entry_levels.py                        # +IV rank quality tests
```

## Validation Changes

Daily validation suite grows from 9 to 10 checks:
- Check #10: `iv_rank_quality` — PASS if IV rank meets ticker-type threshold, WARN if marginal, FAIL if "avoid"

## CLI Commands (new)

| Command | What it does |
|---|---|
| `optimal_dte TICKER` | Shows theta/IV comparison across expirations, recommends best DTE |
| `exit_intelligence TICKER` | Shows regime stop, time-adjusted target, theta decay for a hypothetical position |

## Backward Compatibility

Every modification uses optional parameters with None defaults:
- `monitor_exit_conditions(..., regime_stop_multiplier=None, days_held=None, dte_at_entry=None)`
- `recommend_action(..., entry_regime_id=None)`
- `run_daily_checks(..., iv_rank=None, ticker_type=None)`
- All existing callers continue to work unchanged

## Implementation Order

Tasks ordered by dependency (earlier tasks feed later ones):

1. Exit models (models/exit.py)
2. Exit intelligence functions (3 functions)
3. Wire exit intelligence into trade_lifecycle.py
4. Correlation + margin-regime sizing functions
5. Unified position sizing (chains Kelly + correlation + margin)
6. DTE optimizer
7. Strategy switching in adjustment service
8. IV rank quality + validation check #10
9. Adjustment outcome tracking models + analysis
10. CLI commands + exports + functional tests
