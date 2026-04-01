# Trade Validator — Structure-Aware Configurable Rules Engine

**Date:** 2026-04-01  
**Status:** Design  
**Author:** Claude + Nitin

## Problem

Trades reach output with `max_loss=0`, `credit=0`, same-strike legs, and suspicious POP values. No systematic validation exists between trade generation and output. Each bug is patched individually — no framework.

## Solution

A configurable validation layer that every trade passes through after generation, before output. Rules are driven by:
1. **Structure knowledge base** — what's valid per trade type (IC vs calendar vs strangle)
2. **User config** — thresholds, actions, preferences (YAML, overridable)
3. **Portfolio context** — concentration limits, correlation penalties

## Architecture

```
Assessor generates TradeSpec
       ↓
TradeValidator.validate(trade_spec, repriced, config)
       ↓
ValidationResult:
  - status: "valid" | "flagged" | "rejected"
  - flags: list[ValidationFlag]  # warnings
  - rejections: list[ValidationRejection]  # hard blocks with root cause
  - economics: ValidatedEconomics  # guaranteed non-null if valid
       ↓
Only "valid" and "flagged" trades reach output
```

## Models

### ValidationConfig (Pydantic, from YAML)

```python
class ValidationConfig(BaseModel):
    # Strike validation
    same_strike_action: Literal["reject", "widen_then_reject"] = "widen_then_reject"
    min_wing_width_strikes: int = 1

    # POP bounds
    pop_suspicious_high: float = 0.95
    pop_suspicious_low: float = 0.05
    pop_action: Literal["flag", "reject", "clamp"] = "flag"

    # Credit thresholds
    min_credit_per_spread: float = 0.10
    zero_credit_action: Literal["reject", "investigate", "flag"] = "investigate"

    # Sizing
    zero_contracts_action: Literal["exclude", "show_fractional", "show_min_1"] = "show_fractional"

    # DTE tolerance
    dte_tolerance_days: int = 7

    # Concentration (applied at portfolio level, not per-trade)
    max_per_structure: int = 2
    correlation_penalty_threshold: float = 0.7
    correlation_penalty_pct: float = 0.30
```

### StructureRules (Knowledge Base)

```python
STRUCTURE_RULES: dict[str, StructureRule] = {
    "iron_condor": StructureRule(
        required_legs=4,
        leg_roles={"short_put", "long_put", "short_call", "long_call"},
        wing_width="required",      # must be > 0
        max_loss="computed",         # (wing - credit) × lot
        max_profit="computed",       # credit × lot
        entry_type="credit",
        max_loss_formula="(wing_width - entry_credit) * lot_size",
        max_profit_formula="entry_credit * lot_size",
    ),
    "iron_butterfly": StructureRule(
        required_legs=4,
        leg_roles={"short_put", "long_put", "short_call", "long_call"},
        wing_width="required",
        max_loss="computed",
        max_profit="computed",
        entry_type="credit",
        max_loss_formula="(wing_width - entry_credit) * lot_size",
        max_profit_formula="entry_credit * lot_size",
        notes="short_put strike == short_call strike (ATM center)",
    ),
    "credit_spread": StructureRule(
        required_legs=2,
        wing_width="required",
        max_loss="computed",
        max_profit="computed",
        entry_type="credit",
        max_loss_formula="(wing_width - entry_credit) * lot_size",
        max_profit_formula="entry_credit * lot_size",
    ),
    "debit_spread": StructureRule(
        required_legs=2,
        wing_width="required",
        max_loss="computed",
        max_profit="computed",
        entry_type="debit",
        max_loss_formula="entry_debit * lot_size",
        max_profit_formula="(wing_width - entry_debit) * lot_size",
    ),
    "calendar": StructureRule(
        required_legs=2,
        wing_width="not_applicable",
        max_loss="approximate",      # debit paid
        max_profit="unbounded",
        entry_type="debit",
        notes="Same strike, different expiry. Max loss ≈ debit paid.",
    ),
    "diagonal": StructureRule(
        required_legs=2,
        wing_width="not_applicable",
        max_loss="approximate",
        max_profit="varies",
        entry_type="debit",
        notes="Different strike, different expiry.",
    ),
    "strangle": StructureRule(
        required_legs=2,
        leg_roles={"short_put", "short_call"},
        wing_width="not_applicable",
        max_loss="unlimited",
        max_profit="computed",
        entry_type="credit",
        max_profit_formula="entry_credit * lot_size",
    ),
    "straddle": StructureRule(
        required_legs=2,
        wing_width="not_applicable",
        max_loss="unlimited",
        max_profit="computed",
        entry_type="credit",
        max_profit_formula="entry_credit * lot_size",
        notes="Both legs at same ATM strike.",
    ),
    "ratio_spread": StructureRule(
        required_legs=3,
        wing_width="not_applicable",
        max_loss="unlimited",
        max_profit="computed",
        entry_type="credit",
        notes="Undefined risk on naked side.",
    ),
}
```

### ValidationResult

```python
class ValidationFlag(BaseModel):
    field: str           # "pop_pct", "entry_credit", etc.
    value: Any           # actual value
    threshold: Any       # what it was checked against
    message: str         # human-readable

class ValidationRejection(BaseModel):
    field: str
    value: Any
    rule: str            # "same_strike", "zero_max_loss", "missing_legs"
    root_cause: str      # "Wing width < strike interval" or "No bid/ask on long put"
    suggestion: str      # "Try wider strikes or different ticker"

class ValidatedEconomics(BaseModel):
    """Guaranteed non-null economics for valid/flagged trades."""
    entry_credit: float      # positive for credit, negative for debit
    max_profit: float        # always >= 0
    max_loss: float | None   # None only for unlimited risk structures
    wing_width: float | None # None only when not_applicable per structure rules
    pop_pct: float           # 0-1
    expected_value: float
    contracts: float         # fractional if unfundable
    lot_size: int

class ValidationResult(BaseModel):
    status: Literal["valid", "flagged", "rejected"]
    flags: list[ValidationFlag] = []
    rejections: list[ValidationRejection] = []
    economics: ValidatedEconomics | None = None  # None only if rejected
```

## Validation Steps (in order)

### Step 1: Structure Match
- Look up structure in STRUCTURE_RULES
- Verify leg count matches
- Verify leg roles match (if specified)
- REJECT if unknown structure or wrong leg count

### Step 2: Strike Validation
- For structures with `wing_width="required"`:
  - Extract short/long strikes from legs
  - If same strike: attempt widen to next available (if config allows)
  - If still same or widen fails: REJECT with root_cause
- For calendars: verify same strike, different expiry
- For straddles: verify same strike (valid)

### Step 3: Economics Computation
- Compute entry_credit from repriced trade (sell@bid - buy@ask)
- Compute max_profit and max_loss per structure formula
- For "unlimited" max_loss: set to None (not 0)
- For "approximate" max_loss (calendars): set to debit paid
- REJECT if max_loss computes to <= 0 on required structures
- FLAG if entry_credit < min_credit_per_spread

### Step 4: POP Validation
- Check pop_pct bounds
- FLAG if outside [pop_suspicious_low, pop_suspicious_high]
- If pop_action = "clamp": force to bounds
- If pop_action = "reject": REJECT

### Step 5: DTE Validation
- Compare actual expiry DTE to target_dte
- FLAG if |actual - target| > dte_tolerance_days

### Step 6: Sizing
- Compute contracts from capital / max_loss
- If contracts < 1: show as fractional (e.g., 0.3 contracts)
- FLAG as "unfundable — requires $X minimum"

### Step 7: Concentration (portfolio-level, after all trades validated)
- Count trades per structure type
- If > max_per_structure: keep best N by score, move rest to "alternatives"
- Apply correlation penalty to score

## Files

| File | Purpose |
|------|---------|
| `income_desk/models/validation.py` | NEW: ValidationConfig, StructureRule, ValidationResult, ValidatedEconomics |
| `income_desk/service/trade_validator.py` | NEW: TradeValidator class with validate() and validate_batch() |
| `income_desk/config/validation_defaults.yaml` | NEW: Default config (user overrides) |
| `income_desk/workflow/rank_opportunities.py` | MODIFY: Call validator after batch_reprice |

## Testing

- Unit test each structure type with known-good and known-bad inputs
- Edge case: BAC $0.50 strikes with small ATR → same-strike → widen → verify
- Edge case: Calendar same-strike → valid, not rejected
- Edge case: POP = 0.97 → flagged, not rejected
- Edge case: max_loss = 0 on IC → rejected with root cause
- Integration: run full pipeline, verify 0 trades with $0 max_loss in output
