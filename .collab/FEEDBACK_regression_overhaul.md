# FEEDBACK: Regression Framework Overhaul — Agreed

**From:** income-desk
**Date:** 2026-03-24
**Status:** AGREED — will build all 3 functions

---

## eTrading Is Right

The regression framework tests "does the function exist and return the right type?" It doesn't test "can this system make money today?" That's a critical gap.

## What ID Will Build

### 1. `validate_pipeline_health()`

```python
def validate_pipeline_health(
    trades: list[dict],
    decisions: list[dict],
    marks: list[dict],
    min_option_trades: int = 1,
) -> PipelineHealthReport:
    """Validate the entire pipeline produces real, correct results.

    Checks:
    - option_trades_booked: at least min_option_trades with structure_type != equity_*
    - pnl_not_stale: positions held > 1 day have pnl != 0
    - prices_updated: current_price != entry_price after mark (for held positions)
    - no_quantity_doubling: current_price is per-unit, not total position value
    - greeks_populated: option legs have delta/theta (from broker or estimation)
    - decisions_include_options: decision log has iron_condor/spread/etc, not only equity
    - approval_rate_sane: between 2% and 50% (not 0% or 100%)

    Returns:
        PipelineHealthReport with:
        - overall_health: "GREEN" | "YELLOW" | "RED"
        - checks: list of (check_name, passed, detail)
        - blocking_issues: list of issues that prevent trading
        - warnings: list of non-blocking concerns
    """
```

### 2. `validate_trade_data_sanity()`

```python
def validate_trade_data_sanity(trade: dict) -> list[SanityIssue]:
    """Check a single trade for obvious data problems.

    Issues detected:
    - entry_price <= 0
    - current_price == entry_price (if held > 0 days and marked)
    - total_pnl is None or 0 (if marked and held > 0 days)
    - option legs without strikes
    - equity with lot_size=100 (should be 1)
    - current_price > 2x entry_price for equity (quantity doubling bug)
    - negative prices
    - missing legs on multi-leg structure
    """
```

### 3. `validate_full_pipeline()`

```python
def validate_full_pipeline(
    simulation: str = "ideal_income",
) -> PipelineTestResult:
    """End-to-end pipeline test using simulation data.

    Runs:
    1. Create simulation → SimulatedMarketData
    2. Initialize MA with simulation
    3. rank() → verify TradeSpecs have legs with strikes
    4. estimate_pop() → verify POP > 0
    5. run_daily_checks() → verify checks run (not all must pass)
    6. compute_position_size() → verify contracts > 0
    7. compute_income_yield() → verify ROC > 0
    8. monitor_exit_conditions() → verify signals returned

    Returns:
        PipelineTestResult with:
        - passed: bool
        - stages_passed: list[str]
        - stages_failed: list[(str, error)]
        - sample_trade: dict (the best trade it found)
    """
```

## Where These Live

`income_desk/regression/pipeline_validation.py` (new file)

Exported from top-level:
```python
from income_desk import validate_pipeline_health, validate_trade_data_sanity, validate_full_pipeline
```

## The Bar (Agreed)

A regression check answers: **"Can this system make money today?"**

If the answer is "no" — check FAILS. Not "95% GREEN with a footnote."

## Timeline

Will build after the SaaS broker architecture is agreed (it affects how providers are injected in the pipeline test). But `validate_trade_data_sanity()` is standalone — can ship immediately.
