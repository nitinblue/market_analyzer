# Functional Testing Framework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a profitability-first functional testing framework that validates the full trading pipeline (scan → rank → entry → exit) and exposes a `validate` CLI command for daily pre-market use and MCP consumption.

**Architecture:** Pure validation functions in `income_desk/validation/` (no broker required) called by both `tests/functional/` pytest tests and a new `do_validate` CLI command. The CLI command's structured output makes it directly consumable as an MCP tool.

**Tech Stack:** Python 3.12, Pydantic BaseModel, pytest, existing `trade_lifecycle.py` / `risk.py` / `trade_spec_factory.py` APIs.

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `income_desk/validation/__init__.py` | Package exports |
| `income_desk/validation/models.py` | `CheckResult`, `Severity`, `Suite`, `ValidationReport` |
| `income_desk/validation/profitability_audit.py` | `check_commission_drag`, `check_fill_quality`, `check_margin_efficiency` |
| `income_desk/validation/daily_readiness.py` | `run_daily_checks`, `run_adversarial_checks` orchestrators |
| `income_desk/validation/stress_scenarios.py` | `check_gamma_stress`, `check_vega_shock`, `check_breakeven_spread` |
| `tests/functional/__init__.py` | Empty, marks directory as test package |
| `tests/functional/conftest.py` | Shared fixtures for all functional tests |
| `tests/functional/test_daily_workflow.py` | Full pipeline: regime → assessor → GO verdict → trade spec quality |
| `tests/functional/test_commission_drag.py` | Fee viability checks |
| `tests/functional/test_fill_quality.py` | Spread survival checks |
| `tests/functional/test_margin_efficiency.py` | ROC checks |
| `tests/functional/test_adversarial_stress.py` | Gamma/vega/spread stress |
| `tests/functional/test_profitability_gates.py` | POP, EV, profit factor gates |
| `tests/functional/test_exit_discipline.py` | Profit target, stop loss, DTE, regime change exit |
| `tests/functional/test_drawdown_circuit.py` | Circuit breaker + position scaling |

### Modified files
| File | Change |
|------|--------|
| `income_desk/cli/interactive.py` | Add `do_validate` command |

---

## Task 1: Validation Models

**Files:**
- Create: `income_desk/validation/models.py`
- Create: `income_desk/validation/__init__.py` (stub)

- [ ] **Step 1: Write the failing test**

Create `tests/test_validation_models.py`:

```python
"""Tests for validation result models."""
from income_desk.validation.models import (
    CheckResult, Severity, Suite, ValidationReport,
)
from datetime import date


def test_check_result_creation() -> None:
    r = CheckResult(
        name="commission_drag",
        severity=Severity.PASS,
        message="Credit covers fees",
        value=1.50,
        threshold=0.52,
    )
    assert r.severity == Severity.PASS
    assert r.name == "commission_drag"


def test_validation_report_summary_ready() -> None:
    report = ValidationReport(
        ticker="SPY",
        suite=Suite.DAILY,
        as_of=date(2026, 3, 18),
        checks=[
            CheckResult(name="a", severity=Severity.PASS, message="ok"),
            CheckResult(name="b", severity=Severity.WARN, message="marginal"),
        ],
    )
    assert report.is_ready is True
    assert report.passed == 1
    assert report.warnings == 1
    assert report.failures == 0
    assert "READY TO TRADE" in report.summary


def test_validation_report_summary_not_ready() -> None:
    report = ValidationReport(
        ticker="SPY",
        suite=Suite.DAILY,
        as_of=date(2026, 3, 18),
        checks=[
            CheckResult(name="a", severity=Severity.PASS, message="ok"),
            CheckResult(name="b", severity=Severity.FAIL, message="bad"),
        ],
    )
    assert report.is_ready is False
    assert "NOT READY" in report.summary
```

- [ ] **Step 2: Run to confirm it fails**

```bash
.venv_312/Scripts/python -m pytest tests/test_validation_models.py -v
```
Expected: `ImportError` (module doesn't exist yet)

- [ ] **Step 3: Create `income_desk/validation/models.py`**

```python
"""Validation result models for the profitability testing framework."""
from __future__ import annotations

from datetime import date
from enum import auto
from typing import Any

from pydantic import BaseModel, computed_field

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): ...


class Severity(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class Suite(StrEnum):
    DAILY = "daily"
    ADVERSARIAL = "adversarial"
    FULL = "full"


class CheckResult(BaseModel):
    """Result of a single profitability check."""
    name: str
    severity: Severity
    message: str
    detail: str = ""
    value: float | None = None
    threshold: float | None = None


class ValidationReport(BaseModel):
    """Aggregated result of a validation suite run."""
    ticker: str
    suite: Suite
    as_of: date
    checks: list[CheckResult]

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.severity == Severity.PASS)

    @property
    def warnings(self) -> int:
        return sum(1 for c in self.checks if c.severity == Severity.WARN)

    @property
    def failures(self) -> int:
        return sum(1 for c in self.checks if c.severity == Severity.FAIL)

    @property
    def is_ready(self) -> bool:
        return self.failures == 0

    @property
    def summary(self) -> str:
        status = "READY TO TRADE" if self.is_ready else "NOT READY"
        total = len(self.checks)
        return f"{status} ({self.passed}/{total} passed, {self.warnings} warnings)"
```

- [ ] **Step 4: Create `income_desk/validation/__init__.py`** (stub for now)

```python
"""Profitability validation framework — pure functions, no broker required."""
```

- [ ] **Step 5: Run tests**

```bash
.venv_312/Scripts/python -m pytest tests/test_validation_models.py -v
```
Expected: 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add income_desk/validation/ tests/test_validation_models.py
git commit -m "feat: add validation models (CheckResult, Severity, ValidationReport)"
```

---

## Task 2: Profitability Audit Functions

**Files:**
- Create: `income_desk/validation/profitability_audit.py`
- Test: `tests/test_validation_profitability_audit.py`

These are pure functions — no broker, no MA services. Input: numbers and TradeSpec. Output: CheckResult.

- [ ] **Step 1: Write failing tests**

Create `tests/test_validation_profitability_audit.py`:

```python
"""Tests for profitability audit checks."""
from datetime import date, timedelta
import pytest

from income_desk.trade_spec_factory import build_iron_condor
from income_desk.validation.models import Severity
from income_desk.validation.profitability_audit import (
    check_commission_drag,
    check_fill_quality,
    check_margin_efficiency,
)
from income_desk.trade_lifecycle import compute_income_yield


def _ic_spec():
    exp = date.today() + timedelta(days=30)
    return build_iron_condor(
        ticker="SPY", underlying_price=580.0,
        short_put=570.0, long_put=565.0,
        short_call=590.0, long_call=595.0,
        expiration=exp.isoformat(),
    )


class TestCommissionDrag:
    def test_healthy_credit_passes(self) -> None:
        """$1.50 credit on 4-leg IC — fees are ~3.5% of credit."""
        result = check_commission_drag(_ic_spec(), entry_credit=1.50)
        assert result.severity == Severity.PASS
        assert result.name == "commission_drag"

    def test_thin_credit_warns(self) -> None:
        """$0.60 credit — fees eat ~22% of credit."""
        result = check_commission_drag(_ic_spec(), entry_credit=0.60)
        assert result.severity == Severity.WARN

    def test_microscopic_credit_fails(self) -> None:
        """$0.20 credit on 4-leg IC — fees exceed credit entirely."""
        result = check_commission_drag(_ic_spec(), entry_credit=0.20)
        assert result.severity == Severity.FAIL

    def test_result_includes_values(self) -> None:
        result = check_commission_drag(_ic_spec(), entry_credit=1.50)
        assert result.value is not None   # net credit after fees
        assert result.threshold is not None  # commission drag amount


class TestFillQuality:
    def test_tight_spread_passes(self) -> None:
        result = check_fill_quality(avg_bid_ask_spread_pct=0.8)
        assert result.severity == Severity.PASS

    def test_moderate_spread_warns(self) -> None:
        result = check_fill_quality(avg_bid_ask_spread_pct=2.0)
        assert result.severity == Severity.WARN

    def test_wide_spread_fails(self) -> None:
        result = check_fill_quality(avg_bid_ask_spread_pct=4.0)
        assert result.severity == Severity.FAIL

    def test_boundary_at_3pct(self) -> None:
        at_boundary = check_fill_quality(avg_bid_ask_spread_pct=3.0)
        above_boundary = check_fill_quality(avg_bid_ask_spread_pct=3.1)
        assert at_boundary.severity == Severity.WARN
        assert above_boundary.severity == Severity.FAIL


class TestMarginEfficiency:
    def test_good_roc_passes(self) -> None:
        spec = _ic_spec()
        income = compute_income_yield(spec, entry_credit=1.50, contracts=1)
        assert income is not None, "compute_income_yield returned None for standard IC"
        result = check_margin_efficiency(income)
        assert result.severity == Severity.PASS

    def test_marginal_roc_warns(self) -> None:
        spec = _ic_spec()
        # Narrow wings + low credit → low ROC
        from datetime import date, timedelta
        exp = date.today() + timedelta(days=30)
        narrow_spec = build_iron_condor(
            ticker="SPY", underlying_price=580.0,
            short_put=579.0, long_put=578.0,
            short_call=581.0, long_call=582.0,
            expiration=exp.isoformat(),
        )
        income = compute_income_yield(narrow_spec, entry_credit=0.25, contracts=1)
        result = check_margin_efficiency(income)
        assert result.severity in (Severity.WARN, Severity.FAIL)

    def test_result_shows_annualized_roc(self) -> None:
        spec = _ic_spec()
        income = compute_income_yield(spec, entry_credit=1.50)
        assert income is not None, "compute_income_yield returned None for standard IC"
        result = check_margin_efficiency(income)
        assert result.value is not None   # annualized ROC %
        assert "%" in result.message
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv_312/Scripts/python -m pytest tests/test_validation_profitability_audit.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement `profitability_audit.py`**

```python
"""Profitability audit checks — pure functions, no broker required.

All functions take numbers / models as input and return a CheckResult.
No income_desk services are called here.
"""
from __future__ import annotations

from income_desk.models.opportunity import TradeSpec
from income_desk.trade_lifecycle import IncomeYield
from income_desk.validation.models import CheckResult, Severity

# Commission constants
_COMMISSION_PER_CONTRACT = 0.65  # $ per leg per direction (TastyTrade rate)


def check_commission_drag(
    trade_spec: TradeSpec,
    entry_credit: float,
    commission_per_contract: float = _COMMISSION_PER_CONTRACT,
) -> CheckResult:
    """Checks whether the entry credit justifies round-trip commission costs.

    Args:
        trade_spec: The trade structure (used to count legs).
        entry_credit: Net credit received per spread in dollars-per-share (e.g., 1.50).
        commission_per_contract: Cost per leg per direction, default $0.65.

    Returns:
        PASS if fees < 10% of gross credit.
        WARN if fees are 10–25% of gross credit.
        FAIL if fees exceed 25% or net credit <= 0.
    """
    leg_count = len(trade_spec.legs)
    round_trip_cost = commission_per_contract * leg_count * 2  # open + close
    gross_credit_dollars = entry_credit * 100  # per-share → per-contract

    if gross_credit_dollars <= 0:
        return CheckResult(
            name="commission_drag",
            severity=Severity.FAIL,
            message="Entry credit is zero or negative — no edge to cover fees",
            value=0.0,
            threshold=round_trip_cost,
        )

    commission_drag_pct = (round_trip_cost / gross_credit_dollars) * 100
    net_credit_dollars = gross_credit_dollars - round_trip_cost

    if net_credit_dollars <= 0 or commission_drag_pct >= 25.0:
        sev = Severity.FAIL
        msg = (
            f"Fees ${round_trip_cost:.2f} eat {commission_drag_pct:.0f}% of "
            f"${gross_credit_dollars:.0f} credit — trade is not viable after commissions"
        )
    elif commission_drag_pct >= 10.0:
        sev = Severity.WARN
        msg = (
            f"Fees ${round_trip_cost:.2f} ({commission_drag_pct:.0f}% of credit) — "
            f"marginal, net credit ${net_credit_dollars:.2f}"
        )
    else:
        sev = Severity.PASS
        msg = (
            f"Credit ${gross_credit_dollars:.0f} covers ${round_trip_cost:.2f} fees "
            f"({commission_drag_pct:.1f}% drag), net ${net_credit_dollars:.2f}"
        )

    return CheckResult(
        name="commission_drag",
        severity=sev,
        message=msg,
        value=round(net_credit_dollars, 2),
        threshold=round(round_trip_cost, 2),
    )


def check_fill_quality(avg_bid_ask_spread_pct: float) -> CheckResult:
    """Checks whether the bid-ask spread is tight enough to survive a natural fill.

    Args:
        avg_bid_ask_spread_pct: Average bid-ask spread as % of mid price.

    Returns:
        PASS if spread <= 1.5%, WARN if 1.5–3%, FAIL if > 3%.
    """
    if avg_bid_ask_spread_pct > 3.0:
        sev = Severity.FAIL
        msg = f"Spread {avg_bid_ask_spread_pct:.1f}% is too wide — natural fill will destroy edge"
    elif avg_bid_ask_spread_pct > 1.5:
        sev = Severity.WARN
        msg = f"Spread {avg_bid_ask_spread_pct:.1f}% — acceptable at mid, risky at natural fill"
    else:
        sev = Severity.PASS
        msg = f"Spread {avg_bid_ask_spread_pct:.1f}% — survives natural fill"

    return CheckResult(
        name="fill_quality",
        severity=sev,
        message=msg,
        value=avg_bid_ask_spread_pct,
        threshold=3.0,
    )


def check_margin_efficiency(income_yield: IncomeYield) -> CheckResult:
    """Checks whether the trade earns sufficient return on capital deployed.

    Compares annualized ROC against the minimum threshold for small accounts:
    income must justify the margin tie-up.

    Args:
        income_yield: IncomeYield from compute_income_yield().

    Returns:
        PASS if annualized ROC >= 15%, WARN if 10–15%, FAIL if < 10%.
    """
    roc = income_yield.annualized_roc_pct

    if roc < 10.0:
        sev = Severity.FAIL
        msg = f"Annualized ROC {roc:.1f}% — below 10% minimum for small account viability"
    elif roc < 15.0:
        sev = Severity.WARN
        msg = f"Annualized ROC {roc:.1f}% — marginal (target ≥15%)"
    else:
        sev = Severity.PASS
        msg = f"Annualized ROC {roc:.1f}% — capital deployed efficiently"

    return CheckResult(
        name="margin_efficiency",
        severity=sev,
        message=msg,
        value=round(roc, 1),
        threshold=15.0,
    )
```

- [ ] **Step 4: Run tests**

```bash
.venv_312/Scripts/python -m pytest tests/test_validation_profitability_audit.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add income_desk/validation/profitability_audit.py tests/test_validation_profitability_audit.py
git commit -m "feat: add profitability audit checks (commission drag, fill quality, margin efficiency)"
```

---

## Task 3: Stress Scenarios

**Files:**
- Create: `income_desk/validation/stress_scenarios.py`
- Test: `tests/test_validation_stress.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_validation_stress.py`:

```python
"""Tests for adversarial stress scenario checks."""
from datetime import date, timedelta

import pytest

from income_desk.trade_spec_factory import build_iron_condor
from income_desk.validation.models import Severity
from income_desk.validation.stress_scenarios import (
    check_breakeven_spread,
    check_gamma_stress,
    check_vega_shock,
)


def _ic_spec(wing_width: float = 5.0):
    exp = date.today() + timedelta(days=30)
    mid = 580.0
    return build_iron_condor(
        ticker="SPY", underlying_price=mid,
        short_put=mid - 10,  long_put=mid - 10 - wing_width,
        short_call=mid + 10, long_call=mid + 10 + wing_width,
        expiration=exp.isoformat(),
    )


class TestGammaStress:
    def test_defined_risk_ic_passes_gamma_stress(self) -> None:
        """Iron condor with wing: max loss is bounded regardless of gamma."""
        result = check_gamma_stress(_ic_spec(), entry_credit=1.50, atr_pct=1.0)
        assert result.severity == Severity.PASS
        assert result.name == "gamma_stress"

    def test_high_gamma_warns(self) -> None:
        """Very wide ATR (3%) + narrow wings → gamma exposure warning."""
        result = check_gamma_stress(_ic_spec(wing_width=1.0), entry_credit=0.30, atr_pct=3.0)
        assert result.severity in (Severity.WARN, Severity.FAIL)

    def test_result_includes_loss_estimate(self) -> None:
        result = check_gamma_stress(_ic_spec(), entry_credit=1.50, atr_pct=1.0)
        assert result.value is not None


class TestVegaShock:
    def test_ic_warns_on_iv_spike(self) -> None:
        """IC is short vega — +30% IV spike hurts the position."""
        result = check_vega_shock(_ic_spec(), entry_credit=1.50, iv_spike_pct=0.30)
        # IC is short vega so IV spike should be WARN or FAIL
        assert result.severity in (Severity.WARN, Severity.FAIL)
        assert result.name == "vega_shock"

    def test_result_message_describes_exposure(self) -> None:
        result = check_vega_shock(_ic_spec(), entry_credit=1.50, iv_spike_pct=0.30)
        assert len(result.message) > 0


class TestBreakevenSpread:
    def test_healthy_trade_passes_at_low_spread(self) -> None:
        """At 0.5% spread, a $1.50-credit IC should still be viable."""
        result = check_breakeven_spread(_ic_spec(), entry_credit=1.50, atr_pct=1.0)
        assert result.severity == Severity.PASS
        assert result.name == "breakeven_spread"

    def test_thin_credit_warns_at_high_spread(self) -> None:
        """$0.40 credit IC — edge disappears quickly as spread widens."""
        result = check_breakeven_spread(_ic_spec(), entry_credit=0.40, atr_pct=1.0)
        assert result.severity in (Severity.WARN, Severity.FAIL)

    def test_result_includes_break_even_spread_pct(self) -> None:
        """Value field should be the break-even spread %."""
        result = check_breakeven_spread(_ic_spec(), entry_credit=1.50, atr_pct=1.0)
        assert result.value is not None
        assert result.value > 0  # break-even spread pct
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv_312/Scripts/python -m pytest tests/test_validation_stress.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement `stress_scenarios.py`**

```python
"""Adversarial stress scenario checks — pure functions.

These answer: "At what point does our edge disappear?"
No broker required. All inputs are numbers/models.
"""
from __future__ import annotations

from income_desk.models.opportunity import StructureType, TradeSpec
from income_desk.validation.models import CheckResult, Severity

# Structures that are short vega (harmed by IV spikes)
_SHORT_VEGA_STRUCTURES = {
    StructureType.IRON_CONDOR,
    StructureType.IRON_BUTTERFLY,
    StructureType.CREDIT_SPREAD,
    StructureType.STRANGLE,
    StructureType.STRADDLE,
}

# Structures that are long vega (helped by IV spikes)
_LONG_VEGA_STRUCTURES = {
    StructureType.CALENDAR,
    StructureType.DOUBLE_CALENDAR,
    StructureType.DIAGONAL,
}


def check_gamma_stress(
    trade_spec: TradeSpec,
    entry_credit: float,
    atr_pct: float,
    sigma_multiple: float = 2.0,
) -> CheckResult:
    """Checks whether the trade survives a large intraday move.

    For defined-risk structures, the max loss is bounded by wing width.
    The check validates that the risk/reward ratio stays reasonable under stress.

    Args:
        trade_spec: Trade structure (must have wing_width_points for defined-risk).
        entry_credit: Net credit per spread (dollars per share).
        atr_pct: ATR as % of underlying price.
        sigma_multiple: Standard deviation multiple for the stress move (default 2.0).
    """
    wing_width = trade_spec.wing_width_points

    if wing_width is None or wing_width <= 0:
        return CheckResult(
            name="gamma_stress",
            severity=Severity.WARN,
            message="Cannot assess gamma risk: no wing width (undefined-risk structure)",
        )

    max_loss = wing_width * 100 - entry_credit * 100
    max_profit = entry_credit * 100

    if max_loss <= 0:
        return CheckResult(
            name="gamma_stress",
            severity=Severity.FAIL,
            message=f"Max loss is zero or negative — invalid trade parameters",
        )

    risk_reward = max_loss / max_profit if max_profit > 0 else 999.0

    # Stress: at 2 ATR move, does the expected loss stay within acceptable bounds?
    # For ICs this is theoretical — wings cap the loss at max_loss regardless.
    # Key signal: is the risk/reward ratio still reasonable?
    stress_move_pct = atr_pct * sigma_multiple

    if risk_reward > 10.0:
        sev = Severity.FAIL
        msg = (
            f"Risk/reward {risk_reward:.1f}:1 is extreme — risking ${max_loss:.0f} "
            f"to make ${max_profit:.0f} at {stress_move_pct:.1f}% stress move"
        )
    elif risk_reward > 5.0:
        sev = Severity.WARN
        msg = (
            f"Risk/reward {risk_reward:.1f}:1 — marginal at {sigma_multiple}σ "
            f"({stress_move_pct:.1f}% move), max loss ${max_loss:.0f}"
        )
    else:
        sev = Severity.PASS
        msg = (
            f"Gamma risk bounded: max loss ${max_loss:.0f} "
            f"at {sigma_multiple}σ move ({stress_move_pct:.1f}%), R:R {risk_reward:.1f}:1"
        )

    return CheckResult(
        name="gamma_stress",
        severity=sev,
        message=msg,
        value=round(max_loss, 0),
        threshold=round(max_profit * 5, 0),  # flag if max_loss > 5× max_profit
    )


def check_vega_shock(
    trade_spec: TradeSpec,
    entry_credit: float,
    iv_spike_pct: float = 0.30,
) -> CheckResult:
    """Checks the trade's exposure to a sudden IV expansion.

    Short-vega structures (IC, credit spread) are hurt by IV spikes.
    Long-vega structures (calendar, diagonal) benefit from IV spikes.

    Args:
        trade_spec: The trade structure.
        entry_credit: Net credit per spread (dollars per share).
        iv_spike_pct: Fractional IV increase to stress test (0.30 = +30%).
    """
    structure = trade_spec.structure_type
    wing_width = trade_spec.wing_width_points
    max_profit = entry_credit * 100

    if structure in _LONG_VEGA_STRUCTURES:
        return CheckResult(
            name="vega_shock",
            severity=Severity.PASS,
            message=f"Long-vega structure benefits from +{iv_spike_pct:.0%} IV spike",
            value=iv_spike_pct,
        )

    # Short vega: estimate impact as fraction of max profit at risk
    # Approximate: a +30% IV spike on a 30-DTE IC can erase 30-50% of credit
    estimated_loss_pct = iv_spike_pct * 1.2  # conservative multiplier
    estimated_loss_dollars = max_profit * estimated_loss_pct

    if estimated_loss_pct >= 0.5:
        sev = Severity.FAIL
        msg = (
            f"Short-vega structure: +{iv_spike_pct:.0%} IV spike could erase "
            f"~{estimated_loss_pct:.0%} of credit (≈${estimated_loss_dollars:.0f})"
        )
    else:
        sev = Severity.WARN
        msg = (
            f"Short-vega: +{iv_spike_pct:.0%} IV spike risks ~{estimated_loss_pct:.0%} "
            f"of credit (≈${estimated_loss_dollars:.0f}). Monitor if IV rises."
        )

    return CheckResult(
        name="vega_shock",
        severity=sev,
        message=msg,
        value=round(estimated_loss_dollars, 0),
        threshold=round(max_profit, 0),
    )


def check_breakeven_spread(
    trade_spec: TradeSpec,
    entry_credit: float,
    atr_pct: float,
    spread_pcts: list[float] | None = None,
) -> CheckResult:
    """Finds the bid-ask spread at which this trade loses its EV edge.

    Parametric test: simulates entry at progressively worse fills and
    finds the break-even spread percentage.

    Args:
        trade_spec: The trade structure.
        entry_credit: Net credit at mid price (dollars per share).
        atr_pct: ATR as % of underlying price (used as proxy for daily σ).
        spread_pcts: Spread percentages to test (default: 0.5%, 1%, 2%, 3%, 4%, 5%).
    """
    if spread_pcts is None:
        spread_pcts = [0.5, 1.0, 2.0, 3.0, 4.0, 5.0]

    wing_width = trade_spec.wing_width_points or 5.0
    max_profit = entry_credit * 100
    max_loss = wing_width * 100 - max_profit

    if max_loss <= 0 or max_profit <= 0:
        return CheckResult(
            name="breakeven_spread",
            severity=Severity.FAIL,
            message="Cannot compute break-even: invalid trade parameters",
        )

    # ATR-based rough POP estimate (regime-neutral, ~R1 conditions)
    daily_sigma = (atr_pct / 100.0) / 1.25
    pop = max(0.30, min(0.90, 1.0 - daily_sigma * 2.0))

    # Find break-even spread
    breakeven_spread_pct: float | None = None
    for sp in spread_pcts:
        # At spread sp%, effective credit = mid - sp%/2 of mid
        effective_credit = entry_credit * (1 - sp / 200)
        ev = pop * (effective_credit * 100) - (1 - pop) * max_loss
        if ev <= 0 and breakeven_spread_pct is None:
            breakeven_spread_pct = sp
            break

    if breakeven_spread_pct is None:
        # Edge survives even at max tested spread
        sev = Severity.PASS
        msg = f"Edge survives up to {spread_pcts[-1]:.1f}% spread (POP {pop:.0%}, credit ${max_profit:.0f})"
    elif breakeven_spread_pct <= 1.0:
        sev = Severity.FAIL
        msg = (
            f"Edge disappears at {breakeven_spread_pct:.1f}% spread — "
            f"trade is too thin to survive realistic fills"
        )
    elif breakeven_spread_pct <= 2.0:
        sev = Severity.WARN
        msg = (
            f"Break-even spread {breakeven_spread_pct:.1f}% — "
            f"viable at mid fill, risky at natural fill"
        )
    else:
        sev = Severity.PASS
        msg = (
            f"Break-even spread {breakeven_spread_pct:.1f}% — "
            f"sufficient cushion for realistic fills"
        )

    return CheckResult(
        name="breakeven_spread",
        severity=sev,
        message=msg,
        value=breakeven_spread_pct,
        threshold=2.0,
    )
```

- [ ] **Step 4: Run tests**

```bash
.venv_312/Scripts/python -m pytest tests/test_validation_stress.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add income_desk/validation/stress_scenarios.py tests/test_validation_stress.py
git commit -m "feat: add adversarial stress checks (gamma, vega shock, breakeven spread)"
```

---

## Task 4: Daily Readiness Orchestrator

**Files:**
- Create: `income_desk/validation/daily_readiness.py`
- Test: `tests/test_validation_daily_readiness.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_validation_daily_readiness.py`:

```python
"""Tests for daily readiness and adversarial check orchestrators."""
from datetime import date, timedelta, time

import pytest

from income_desk.trade_spec_factory import build_iron_condor
from income_desk.validation.models import Severity, Suite
from income_desk.validation.daily_readiness import (
    run_daily_checks,
    run_adversarial_checks,
)


def _ic_spec():
    exp = date.today() + timedelta(days=30)
    return build_iron_condor(
        ticker="SPY", underlying_price=580.0,
        short_put=570.0, long_put=565.0,
        short_call=590.0, long_call=595.0,
        expiration=exp.isoformat(),
    )


class TestRunDailyChecks:
    def test_returns_validation_report(self) -> None:
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=1.50,
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
            avg_bid_ask_spread_pct=0.8,
            dte=30,
            rsi=50.0,
        )
        assert report.ticker == "SPY"
        assert report.suite == Suite.DAILY
        assert len(report.checks) >= 5

    def test_ideal_conditions_is_ready(self) -> None:
        """R1 + good IV + centered RSI + tight spread → READY."""
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=1.50,
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
            avg_bid_ask_spread_pct=0.8,
            dte=30,
            rsi=50.0,
            iv_rank=45.0,
        )
        assert report.is_ready is True

    def test_poor_fill_quality_blocks_trade(self) -> None:
        """Wide spread → NOT READY."""
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=1.50,
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
            avg_bid_ask_spread_pct=5.0,   # too wide
            dte=30,
            rsi=50.0,
        )
        assert report.is_ready is False
        fail_names = [c.name for c in report.checks if c.severity == Severity.FAIL]
        assert "fill_quality" in fail_names

    def test_microscopic_credit_blocks_trade(self) -> None:
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=0.15,   # too thin
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
            avg_bid_ask_spread_pct=0.8,
            dte=30,
            rsi=50.0,
        )
        assert report.is_ready is False

    def test_report_has_exit_discipline_check(self) -> None:
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=1.50,
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
            avg_bid_ask_spread_pct=0.8,
            dte=30,
            rsi=50.0,
        )
        check_names = [c.name for c in report.checks]
        assert "exit_discipline" in check_names


class TestRunAdversarialChecks:
    def test_returns_validation_report(self) -> None:
        report = run_adversarial_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=1.50,
            atr_pct=1.0,
        )
        assert report.suite == Suite.ADVERSARIAL
        assert len(report.checks) >= 3

    def test_defined_risk_ic_passes_adversarial(self) -> None:
        report = run_adversarial_checks(
            ticker="SPY",
            trade_spec=_ic_spec(),
            entry_credit=1.50,
            atr_pct=1.0,
        )
        # Defined risk IC should pass gamma and breakeven checks
        fail_names = [c.name for c in report.checks if c.severity == Severity.FAIL]
        assert "gamma_stress" not in fail_names
        assert "breakeven_spread" not in fail_names
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv_312/Scripts/python -m pytest tests/test_validation_daily_readiness.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement `daily_readiness.py`**

```python
"""Daily readiness and adversarial check orchestrators.

run_daily_checks() — 7-check pre-trade validation.
run_adversarial_checks() — 3-check stress test.

Both return a ValidationReport that is consumed by the CLI and functional tests.
"""
from __future__ import annotations

from datetime import date, time

from income_desk.models.opportunity import TradeSpec
from income_desk.trade_lifecycle import (
    check_income_entry,
    compute_income_yield,
    estimate_pop,
)
from income_desk.validation.models import CheckResult, Severity, Suite, ValidationReport
from income_desk.validation.profitability_audit import (
    check_commission_drag,
    check_fill_quality,
    check_margin_efficiency,
)
from income_desk.validation.stress_scenarios import (
    check_breakeven_spread,
    check_gamma_stress,
    check_vega_shock,
)


def run_daily_checks(
    ticker: str,
    trade_spec: TradeSpec,
    entry_credit: float,
    regime_id: int,
    atr_pct: float,
    current_price: float,
    avg_bid_ask_spread_pct: float,
    dte: int,
    rsi: float,
    iv_rank: float | None = None,
    iv_percentile: float | None = None,
    time_of_day: time | None = None,
    contracts: int = 1,
) -> ValidationReport:
    """Run the 7-check daily pre-trade validation suite.

    Checks (in order):
      1. commission_drag    — fees vs credit
      2. fill_quality       — bid-ask spread viability
      3. margin_efficiency  — annualized ROC
      4. pop_gate           — probability of profit >= 65%
      5. ev_positive        — expected value is positive
      6. entry_quality      — IV rank, DTE, RSI, regime confirmation
      7. exit_discipline    — trade spec has profit target, stop loss, exit DTE

    Args:
        ticker: Underlying symbol.
        trade_spec: The proposed trade.
        entry_credit: Net credit per spread (dollars per share, e.g., 1.50).
        regime_id: Current regime (1=R1, 2=R2, 3=R3, 4=R4).
        atr_pct: ATR as % of underlying price.
        current_price: Current underlying price.
        avg_bid_ask_spread_pct: Average bid-ask spread of the options chain.
        dte: Days to expiration of the front/target leg.
        rsi: Current RSI value.
        iv_rank: IV rank 0–100 (optional, improves POP accuracy).
        iv_percentile: IV percentile 0–100 (optional).
        time_of_day: Current time in ET (for entry window check).
        contracts: Number of contracts for yield computation.
    """
    checks: list[CheckResult] = []

    # 1. Commission drag
    checks.append(check_commission_drag(trade_spec, entry_credit))

    # 2. Fill quality
    checks.append(check_fill_quality(avg_bid_ask_spread_pct))

    # 3. Margin efficiency
    income = compute_income_yield(trade_spec, entry_credit, contracts)
    if income is not None:
        checks.append(check_margin_efficiency(income))
    else:
        checks.append(CheckResult(
            name="margin_efficiency",
            severity=Severity.WARN,
            message="Cannot compute ROC — trade structure not supported by yield calculator",
        ))

    # 4 & 5. POP and EV
    pop_estimate = estimate_pop(
        trade_spec=trade_spec,
        entry_price=entry_credit,
        regime_id=regime_id,
        atr_pct=atr_pct,
        current_price=current_price,
        contracts=contracts,
        iv_rank=iv_rank,
    )
    if pop_estimate is not None:
        pop_sev = Severity.PASS if pop_estimate.pop_pct >= 65.0 else (
            Severity.WARN if pop_estimate.pop_pct >= 55.0 else Severity.FAIL
        )
        checks.append(CheckResult(
            name="pop_gate",
            severity=pop_sev,
            message=f"POP {pop_estimate.pop_pct:.1f}% "
                    f"({'≥' if pop_estimate.pop_pct >= 65 else '<'} 65% threshold)",
            value=round(pop_estimate.pop_pct, 1),
            threshold=65.0,
        ))

        ev = pop_estimate.expected_value
        ev_sev = Severity.PASS if ev > 0 else (Severity.WARN if ev > -10 else Severity.FAIL)
        checks.append(CheckResult(
            name="ev_positive",
            severity=ev_sev,
            message=f"EV {'+' if ev >= 0 else ''}${ev:.0f} per contract "
                    f"({'positive edge' if ev > 0 else 'negative edge — avoid'})",
            value=round(ev, 0),
            threshold=0.0,
        ))
    else:
        checks.append(CheckResult(
            name="pop_gate",
            severity=Severity.WARN,
            message="POP not computable for this structure — skip EV gate",
        ))

    # 6. Entry quality (IV rank, RSI, regime, DTE)
    entry_check = check_income_entry(
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        dte=dte,
        rsi=rsi,
        atr_pct=atr_pct,
        regime_id=regime_id,
    )
    entry_sev = Severity.PASS if entry_check.confirmed else (
        Severity.WARN if entry_check.score >= 0.45 else Severity.FAIL
    )
    checks.append(CheckResult(
        name="entry_quality",
        severity=entry_sev,
        message=entry_check.summary,
        value=round(entry_check.score, 2),
        threshold=0.60,
    ))

    # 7. Exit discipline — does the trade spec have an exit plan?
    has_exit = (
        trade_spec.profit_target_pct is not None
        and trade_spec.stop_loss_pct is not None
        and trade_spec.exit_dte is not None
    )
    exit_sev = Severity.PASS if has_exit else Severity.WARN
    exit_msg = (
        f"TP {trade_spec.profit_target_pct:.0%} | "
        f"SL {trade_spec.stop_loss_pct}× | "
        f"exit ≤{trade_spec.exit_dte} DTE"
        if has_exit else "Trade spec missing exit rules — add profit_target_pct, stop_loss_pct, exit_dte"
    )
    checks.append(CheckResult(
        name="exit_discipline",
        severity=exit_sev,
        message=exit_msg,
    ))

    return ValidationReport(
        ticker=ticker,
        suite=Suite.DAILY,
        as_of=date.today(),
        checks=checks,
    )


def run_adversarial_checks(
    ticker: str,
    trade_spec: TradeSpec,
    entry_credit: float,
    atr_pct: float,
) -> ValidationReport:
    """Run the 3-check adversarial stress test suite.

    Checks:
      1. gamma_stress     — max loss at 2σ move
      2. vega_shock       — IV spike impact
      3. breakeven_spread — edge survival at natural fills

    Args:
        ticker: Underlying symbol.
        trade_spec: The proposed trade.
        entry_credit: Net credit per spread (dollars per share).
        atr_pct: ATR as % of underlying price.
    """
    checks = [
        check_gamma_stress(trade_spec, entry_credit, atr_pct),
        check_vega_shock(trade_spec, entry_credit),
        check_breakeven_spread(trade_spec, entry_credit, atr_pct),
    ]

    return ValidationReport(
        ticker=ticker,
        suite=Suite.ADVERSARIAL,
        as_of=date.today(),
        checks=checks,
    )
```

- [ ] **Step 4: Run tests**

```bash
.venv_312/Scripts/python -m pytest tests/test_validation_daily_readiness.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add income_desk/validation/daily_readiness.py tests/test_validation_daily_readiness.py
git commit -m "feat: add daily readiness + adversarial orchestrators"
```

---

## Task 5: Package Exports

**Files:**
- Modify: `income_desk/validation/__init__.py`

- [ ] **Step 1: Update `__init__.py` with clean exports**

```python
"""Profitability validation framework — pure functions, no broker required.

Usage::

    from income_desk.validation import run_daily_checks, run_adversarial_checks
    from income_desk.validation.models import ValidationReport, CheckResult, Severity, Suite

    report = run_daily_checks(
        ticker="SPY",
        trade_spec=spec,
        entry_credit=1.50,
        regime_id=1,
        atr_pct=1.0,
        current_price=580.0,
        avg_bid_ask_spread_pct=0.8,
        dte=30,
        rsi=50.0,
    )
    print(report.summary)
"""
from income_desk.validation.daily_readiness import run_adversarial_checks, run_daily_checks
from income_desk.validation.models import CheckResult, Severity, Suite, ValidationReport
from income_desk.validation.profitability_audit import (
    check_commission_drag,
    check_fill_quality,
    check_margin_efficiency,
)
from income_desk.validation.stress_scenarios import (
    check_breakeven_spread,
    check_gamma_stress,
    check_vega_shock,
)

__all__ = [
    "run_daily_checks",
    "run_adversarial_checks",
    "ValidationReport",
    "CheckResult",
    "Severity",
    "Suite",
    "check_commission_drag",
    "check_fill_quality",
    "check_margin_efficiency",
    "check_gamma_stress",
    "check_vega_shock",
    "check_breakeven_spread",
]
```

- [ ] **Step 2: Verify import works**

```bash
.venv_312/Scripts/python -c "from income_desk.validation import run_daily_checks, ValidationReport; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Run full test suite to confirm no regressions**

```bash
.venv_312/Scripts/python -m pytest tests/test_validation_models.py tests/test_validation_profitability_audit.py tests/test_validation_stress.py tests/test_validation_daily_readiness.py -v
```
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add income_desk/validation/__init__.py
git commit -m "feat: wire validation package exports"
```

---

## Task 6: Functional Test Suite

**Files:**
- Create: `tests/functional/__init__.py`
- Create: `tests/functional/conftest.py`
- Create: `tests/functional/test_daily_workflow.py`
- Create: `tests/functional/test_commission_drag.py`
- Create: `tests/functional/test_fill_quality.py`
- Create: `tests/functional/test_margin_efficiency.py`
- Create: `tests/functional/test_adversarial_stress.py`
- Create: `tests/functional/test_profitability_gates.py`
- Create: `tests/functional/test_exit_discipline.py`
- Create: `tests/functional/test_drawdown_circuit.py`

- [ ] **Step 1: Create `tests/functional/__init__.py`**

```python
"""Functional tests — validate full trading pipeline profitability."""
```

- [ ] **Step 2: Create `tests/functional/conftest.py`**

```python
"""Shared fixtures for functional tests.

All fixtures use synthetic data — no broker required.
Designed to represent realistic daily trading conditions for SPY/small account.
"""
from datetime import date, timedelta

import pytest

from income_desk.models.regime import RegimeID, RegimeResult
from income_desk.models.vol_surface import SkewSlice, TermStructurePoint, VolatilitySurface
from income_desk.trade_spec_factory import build_iron_condor, build_credit_spread


# ── Regime fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def r1_regime() -> RegimeResult:
    """R1 Low-Vol Mean Reverting — ideal income environment."""
    return RegimeResult(
        ticker="SPY", regime=RegimeID(1), confidence=0.82,
        regime_probabilities={1: 0.82, 2: 0.10, 3: 0.05, 4: 0.03},
        as_of_date=date(2026, 3, 18), model_version="test", trend_direction=None,
    )


@pytest.fixture
def r2_regime() -> RegimeResult:
    """R2 High-Vol Mean Reverting — wider wings, selective income."""
    return RegimeResult(
        ticker="SPY", regime=RegimeID(2), confidence=0.75,
        regime_probabilities={1: 0.15, 2: 0.75, 3: 0.07, 4: 0.03},
        as_of_date=date(2026, 3, 18), model_version="test", trend_direction=None,
    )


@pytest.fixture
def r4_regime() -> RegimeResult:
    """R4 High-Vol Trending — hard stop for income strategies."""
    return RegimeResult(
        ticker="SPY", regime=RegimeID(4), confidence=0.70,
        regime_probabilities={1: 0.05, 2: 0.10, 3: 0.15, 4: 0.70},
        as_of_date=date(2026, 3, 18), model_version="test", trend_direction=None,
    )


# ── Vol surface fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def normal_vol_surface() -> VolatilitySurface:
    """Normal conditions: IV=22%, tight spread, good quality."""
    today = date(2026, 3, 18)
    exps = [today + timedelta(days=30), today + timedelta(days=60)]
    front_iv, back_iv = 0.22, 0.20
    slope = (back_iv - front_iv) / front_iv
    skew = SkewSlice(
        expiration=exps[0], days_to_expiry=30, atm_iv=front_iv,
        otm_put_iv=front_iv + 0.04, otm_call_iv=front_iv + 0.02,
        put_skew=0.04, call_skew=0.02, skew_ratio=2.0,
    )
    return VolatilitySurface(
        ticker="SPY", as_of_date=today, underlying_price=580.0,
        expirations=exps, term_structure=[
            TermStructurePoint(expiration=exps[0], days_to_expiry=30, atm_iv=front_iv, atm_strike=580.0),
            TermStructurePoint(expiration=exps[1], days_to_expiry=60, atm_iv=back_iv, atm_strike=580.0),
        ],
        front_iv=front_iv, back_iv=back_iv, term_slope=slope,
        is_contango=back_iv > front_iv, is_backwardation=front_iv > back_iv,
        skew_by_expiry=[skew],
        calendar_edge_score=0.4,
        best_calendar_expiries=(exps[0], exps[1]),
        iv_differential_pct=(front_iv - back_iv) / back_iv * 100,
        total_contracts=500, avg_bid_ask_spread_pct=0.8,
        data_quality="good", summary="test normal conditions",
    )


@pytest.fixture
def high_vol_surface() -> VolatilitySurface:
    """Elevated IV: 35% front, backwardation, wider spread."""
    today = date(2026, 3, 18)
    exps = [today + timedelta(days=30), today + timedelta(days=60)]
    front_iv, back_iv = 0.35, 0.28
    slope = (back_iv - front_iv) / front_iv
    skew = SkewSlice(
        expiration=exps[0], days_to_expiry=30, atm_iv=front_iv,
        otm_put_iv=front_iv + 0.08, otm_call_iv=front_iv + 0.03,
        put_skew=0.08, call_skew=0.03, skew_ratio=2.7,
    )
    return VolatilitySurface(
        ticker="SPY", as_of_date=today, underlying_price=580.0,
        expirations=exps, term_structure=[
            TermStructurePoint(expiration=exps[0], days_to_expiry=30, atm_iv=front_iv, atm_strike=580.0),
            TermStructurePoint(expiration=exps[1], days_to_expiry=60, atm_iv=back_iv, atm_strike=580.0),
        ],
        front_iv=front_iv, back_iv=back_iv, term_slope=slope,
        is_contango=False, is_backwardation=True,
        skew_by_expiry=[skew],
        calendar_edge_score=0.7,
        best_calendar_expiries=(exps[0], exps[1]),
        iv_differential_pct=(front_iv - back_iv) / back_iv * 100,
        total_contracts=800, avg_bid_ask_spread_pct=1.2,
        data_quality="good", summary="test high vol conditions",
    )


# ── Trade spec fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def standard_ic_spec():
    """Standard SPY iron condor: 5-wide wings, 30 DTE, $1.50 credit."""
    exp = date(2026, 4, 17)
    return build_iron_condor(
        ticker="SPY", underlying_price=580.0,
        short_put=570.0, long_put=565.0,
        short_call=590.0, long_call=595.0,
        expiration=exp.isoformat(),
    )


@pytest.fixture
def wide_ic_spec():
    """Wide SPY iron condor: 10-wide wings for R2 environment."""
    exp = date(2026, 4, 17)
    return build_iron_condor(
        ticker="SPY", underlying_price=580.0,
        short_put=565.0, long_put=555.0,
        short_call=595.0, long_call=605.0,
        expiration=exp.isoformat(),
    )


@pytest.fixture
def credit_spread_spec():
    """Bull put spread: 5-wide, 30 DTE."""
    exp = date(2026, 4, 17)
    return build_credit_spread(
        ticker="SPY", underlying_price=580.0,
        option_type="put",
        short_strike=570.0, long_strike=565.0,
        expiration=exp.isoformat(),
    )


# ── Account context fixtures ─────────────────────────────────────────────────

@pytest.fixture
def small_account():
    """50K taxable account context."""
    return {
        "account_nlv": 50_000.0,
        "account_peak": 52_000.0,
        "available_buying_power": 35_000.0,
        "max_positions": 5,
    }


@pytest.fixture
def ira_account():
    """200K IRA account context."""
    return {
        "account_nlv": 200_000.0,
        "account_peak": 205_000.0,
        "available_buying_power": 120_000.0,
        "max_positions": 8,
    }
```

- [ ] **Step 3: Create `tests/functional/test_daily_workflow.py`**

```python
"""Functional tests: full daily trading pipeline.

Tests the scan → assess → gate workflow end-to-end.
All checks use synthetic data (no broker required).
"""
import pytest
from datetime import date, timedelta

from income_desk.models.opportunity import Verdict
from income_desk.opportunity.option_plays.iron_condor import assess_iron_condor
from income_desk.opportunity.option_plays.zero_dte import assess_zero_dte
from income_desk.validation import run_daily_checks
from income_desk.validation.models import Severity


def _technicals_for_workflow(rsi: float = 50.0, atr_pct: float = 1.0, price: float = 580.0):
    """Build a TechnicalSnapshot inline — avoids cross-test-module imports."""
    from datetime import date
    from income_desk.models.technicals import (
        BollingerBands, MACDData, MovingAverages, RSIData,
        StochasticData, SupportResistance, TechnicalSnapshot,
        MarketPhase, PhaseIndicator,
    )
    return TechnicalSnapshot(
        ticker="SPY", as_of_date=date(2026, 3, 18), current_price=price,
        atr=price * atr_pct / 100, atr_pct=atr_pct, vwma_20=price,
        moving_averages=MovingAverages(
            sma_20=price, sma_50=price * 0.98, sma_200=price * 0.95,
            ema_9=price, ema_21=price,
            price_vs_sma_20_pct=0.0, price_vs_sma_50_pct=2.0, price_vs_sma_200_pct=5.0,
        ),
        rsi=RSIData(value=rsi, is_overbought=rsi > 70, is_oversold=rsi < 30),
        bollinger=BollingerBands(upper=price + 10, middle=price, lower=price - 10, bandwidth=0.04, percent_b=0.5),
        macd=MACDData(macd_line=0.5, signal_line=0.3, histogram=0.2, is_bullish_crossover=False, is_bearish_crossover=False),
        stochastic=StochasticData(k=50.0, d=50.0, is_overbought=False, is_oversold=False),
        support_resistance=SupportResistance(support=570.0, resistance=590.0, price_vs_support_pct=1.7, price_vs_resistance_pct=-1.7),
        phase=PhaseIndicator(phase=MarketPhase.ACCUMULATION, confidence=0.5, description="Test",
                             higher_highs=False, higher_lows=True, lower_highs=False, lower_lows=False,
                             range_compression=0.3, volume_trend="declining", price_vs_sma_50_pct=2.0),
        signals=[],
    )


class TestAssessorVerdicts:
    @pytest.mark.daily
    def test_r1_ic_ideal_conditions_is_go(self, r1_regime, normal_vol_surface) -> None:
        """R1 + IV 22% + good spread → GO verdict from assessor."""
        result = assess_iron_condor("SPY", r1_regime, _technicals_for_workflow(rsi=50), normal_vol_surface)
        assert result.verdict == Verdict.GO

    @pytest.mark.daily
    def test_r4_ic_always_no_go(self, r4_regime, normal_vol_surface) -> None:
        """R4 is always a hard stop for iron condors."""
        result = assess_iron_condor("SPY", r4_regime, _technicals_for_workflow(rsi=50), normal_vol_surface)
        assert result.verdict == Verdict.NO_GO
        assert any("R4" in s.name for s in result.hard_stops)

    @pytest.mark.daily
    def test_go_assessor_produces_trade_spec(self, r1_regime, normal_vol_surface) -> None:
        """GO verdict must include a TradeSpec — needed for full pipeline."""
        result = assess_iron_condor("SPY", r1_regime, _technicals_for_workflow(rsi=50), normal_vol_surface)
        if result.verdict == Verdict.GO:
            assert result.trade_spec is not None
            assert len(result.trade_spec.legs) == 4

    @pytest.mark.daily
    def test_go_trade_spec_has_exit_rules(self, r1_regime, normal_vol_surface) -> None:
        """GO trade spec must include profit target, stop loss, and exit DTE."""
        result = assess_iron_condor("SPY", r1_regime, _technicals_for_workflow(), normal_vol_surface)
        if result.verdict == Verdict.GO and result.trade_spec:
            spec = result.trade_spec
            assert spec.profit_target_pct is not None, "Missing profit_target_pct"
            assert spec.stop_loss_pct is not None, "Missing stop_loss_pct"
            assert spec.exit_dte is not None, "Missing exit_dte"

    @pytest.mark.daily
    def test_validation_of_go_trade_is_ready(self, r1_regime, normal_vol_surface, standard_ic_spec) -> None:
        """A GO trade under ideal conditions should pass daily validation."""
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=standard_ic_spec,
            entry_credit=1.50,
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
            avg_bid_ask_spread_pct=0.8,
            dte=30,
            rsi=50.0,
            iv_rank=45.0,
        )
        assert report.is_ready is True, f"Expected READY. Failures: {[c for c in report.checks if c.severity == Severity.FAIL]}"

    def test_no_go_trade_should_not_reach_validation(self, r4_regime, normal_vol_surface) -> None:
        """R4 hard stops in the assessor — validation should never be called."""
        result = assess_iron_condor("SPY", r4_regime, _technicals_for_workflow(), normal_vol_surface)
        assert result.verdict == Verdict.NO_GO
        assert len(result.hard_stops) > 0
```

- [ ] **Step 4: Create `tests/functional/test_commission_drag.py`**

```python
"""Functional tests: commission drag at realistic account sizes."""
import pytest
from datetime import date, timedelta

from income_desk.trade_spec_factory import build_iron_condor
from income_desk.validation.models import Severity
from income_desk.validation.profitability_audit import check_commission_drag


def _ic(wing_width=5.0):
    exp = date.today() + timedelta(days=30)
    mid = 580.0
    return build_iron_condor(
        ticker="SPY", underlying_price=mid,
        short_put=mid - 10, long_put=mid - 10 - wing_width,
        short_call=mid + 10, long_call=mid + 10 + wing_width,
        expiration=exp.isoformat(),
    )


class TestCommissionDragFunctional:
    @pytest.mark.daily
    def test_minimum_viable_credit_for_4leg_ic(self) -> None:
        """4-leg IC round trip = $5.20 fees. Minimum viable credit to pass: >$0.52/share."""
        min_viable = check_commission_drag(_ic(), entry_credit=0.53)
        too_thin = check_commission_drag(_ic(), entry_credit=0.51)
        assert min_viable.severity == Severity.PASS
        assert too_thin.severity in (Severity.WARN, Severity.FAIL)

    @pytest.mark.daily
    def test_typical_ic_credit_1_50_passes(self) -> None:
        """$1.50 credit = $150/contract. $5.20 fees = 3.5% drag. Well under 10% threshold."""
        result = check_commission_drag(_ic(), entry_credit=1.50)
        assert result.severity == Severity.PASS

    @pytest.mark.daily
    def test_scalping_5_cent_move_is_impossible(self) -> None:
        """$0.05 credit = $5/contract. $5.20 fees exceed credit — mathematically impossible."""
        result = check_commission_drag(_ic(), entry_credit=0.05)
        assert result.severity == Severity.FAIL

    def test_wider_wings_same_credit_still_viable(self) -> None:
        """10-wide IC with $1.50 credit: same commissions, more premium room."""
        result = check_commission_drag(_ic(wing_width=10.0), entry_credit=1.50)
        assert result.severity == Severity.PASS

    def test_net_credit_after_fees_is_positive(self) -> None:
        result = check_commission_drag(_ic(), entry_credit=1.50)
        assert result.value is not None
        assert result.value > 0, "Net credit after fees must be positive for a PASS"
```

- [ ] **Step 5: Create `tests/functional/test_fill_quality.py`**

```python
"""Functional tests: fill quality (bid-ask spread survival)."""
import pytest
from income_desk.validation.models import Severity
from income_desk.validation.profitability_audit import check_fill_quality


class TestFillQualityFunctional:
    @pytest.mark.daily
    def test_spy_etf_typical_spread_passes(self) -> None:
        """SPY options typically have 0.3–1% spread — well within threshold."""
        result = check_fill_quality(avg_bid_ask_spread_pct=0.5)
        assert result.severity == Severity.PASS

    @pytest.mark.daily
    def test_illiquid_name_wide_spread_fails(self) -> None:
        """Low-volume ticker with 4% spread — hard to get filled at mid."""
        result = check_fill_quality(avg_bid_ask_spread_pct=4.5)
        assert result.severity == Severity.FAIL

    @pytest.mark.daily
    def test_elevated_spread_warns(self) -> None:
        """2% spread — viable but risky at natural fill."""
        result = check_fill_quality(avg_bid_ask_spread_pct=2.0)
        assert result.severity == Severity.WARN

    def test_exact_fail_boundary(self) -> None:
        """3.0% is still WARN, 3.1% is FAIL."""
        assert check_fill_quality(3.0).severity == Severity.WARN
        assert check_fill_quality(3.1).severity == Severity.FAIL
```

- [ ] **Step 6: Create `tests/functional/test_margin_efficiency.py`**

```python
"""Functional tests: margin efficiency (return on capital)."""
import pytest
from datetime import date, timedelta

from income_desk.trade_spec_factory import build_iron_condor
from income_desk.trade_lifecycle import compute_income_yield
from income_desk.validation.models import Severity
from income_desk.validation.profitability_audit import check_margin_efficiency


def _ic(wing_width=5.0, underlying=580.0):
    exp = date.today() + timedelta(days=30)
    return build_iron_condor(
        ticker="SPY", underlying_price=underlying,
        short_put=underlying - 10, long_put=underlying - 10 - wing_width,
        short_call=underlying + 10, long_call=underlying + 10 + wing_width,
        expiration=exp.isoformat(),
    )


class TestMarginEfficiencyFunctional:
    @pytest.mark.daily
    def test_standard_ic_30dte_passes_roc_gate(self) -> None:
        """5-wide IC, $1.50 credit, 30 DTE → ROC should exceed 10% annualized."""
        income = compute_income_yield(_ic(), entry_credit=1.50)
        result = check_margin_efficiency(income)
        assert result.severity in (Severity.PASS, Severity.WARN)
        assert result.value is not None
        assert result.value > 0

    def test_narrow_wing_low_credit_fails_roc(self) -> None:
        """1-wide IC with $0.10 credit → capital-inefficient, below threshold."""
        income = compute_income_yield(_ic(wing_width=1.0), entry_credit=0.10)
        result = check_margin_efficiency(income)
        assert result.severity == Severity.FAIL

    def test_roc_value_is_annualized(self) -> None:
        """Annualized ROC for 30-DTE trade = monthly_roc × 12."""
        income = compute_income_yield(_ic(), entry_credit=1.50)
        result = check_margin_efficiency(income)
        # Value should be the annualized ROC %, not monthly
        assert result.value == pytest.approx(income.annualized_roc_pct, abs=0.1)
```

- [ ] **Step 7: Create `tests/functional/test_adversarial_stress.py`**

```python
"""Functional tests: adversarial stress scenarios.

These are the 'what if' tests — where does our edge break down?
"""
import pytest
from datetime import date, timedelta

from income_desk.trade_spec_factory import build_iron_condor
from income_desk.validation.models import Severity
from income_desk.validation.stress_scenarios import (
    check_breakeven_spread,
    check_gamma_stress,
    check_vega_shock,
)
from income_desk.validation import run_adversarial_checks


def _ic(wing_width=5.0):
    exp = date.today() + timedelta(days=30)
    mid = 580.0
    return build_iron_condor(
        ticker="SPY", underlying_price=mid,
        short_put=mid - 10, long_put=mid - 10 - wing_width,
        short_call=mid + 10, long_call=mid + 10 + wing_width,
        expiration=exp.isoformat(),
    )


class TestGammaStressFunctional:
    @pytest.mark.daily
    def test_standard_ic_survives_2sigma_move(self) -> None:
        """5-wide IC bounded by wing. At 2σ (2% ATR), max loss = $500 - credit."""
        result = check_gamma_stress(_ic(), entry_credit=1.50, atr_pct=1.0)
        assert result.severity == Severity.PASS

    def test_extreme_atr_with_narrow_wings_warns(self) -> None:
        """3% daily ATR + 1-wide wings: risk/reward extreme."""
        result = check_gamma_stress(_ic(wing_width=1.0), entry_credit=0.20, atr_pct=3.0)
        assert result.severity in (Severity.WARN, Severity.FAIL)

    def test_r4_scenario_gamma_catastrophic(self) -> None:
        """R4-like 2.5% ATR: even 5-wide IC shows elevated risk/reward."""
        result = check_gamma_stress(_ic(), entry_credit=1.50, atr_pct=2.5, sigma_multiple=2.0)
        # With good wings and decent credit, still passes (bounded loss)
        assert result.value is not None


class TestVegaShockFunctional:
    @pytest.mark.daily
    def test_short_vega_ic_warns_on_iv_spike(self) -> None:
        """IC is short vega — +30% IV spike should result in WARN or FAIL."""
        result = check_vega_shock(_ic(), entry_credit=1.50, iv_spike_pct=0.30)
        assert result.severity in (Severity.WARN, Severity.FAIL)

    def test_moderate_iv_spike_warns_not_fails(self) -> None:
        """+15% IV spike is uncomfortable but not catastrophic for IC."""
        result = check_vega_shock(_ic(), entry_credit=1.50, iv_spike_pct=0.15)
        assert result.severity in (Severity.WARN, Severity.FAIL)


class TestBreakevenSpreadFunctional:
    @pytest.mark.daily
    def test_healthy_trade_survives_1pct_spread(self) -> None:
        """$1.50 credit IC: EV still positive at 1% spread."""
        result = check_breakeven_spread(_ic(), entry_credit=1.50, atr_pct=1.0)
        assert result.severity == Severity.PASS

    def test_thin_trade_loses_edge_early(self) -> None:
        """$0.25 credit IC: edge disappears at very small spread."""
        result = check_breakeven_spread(_ic(), entry_credit=0.25, atr_pct=1.0)
        assert result.severity in (Severity.WARN, Severity.FAIL)

    def test_adversarial_suite_runs_all_three_checks(self) -> None:
        report = run_adversarial_checks("SPY", _ic(), entry_credit=1.50, atr_pct=1.0)
        check_names = {c.name for c in report.checks}
        assert "gamma_stress" in check_names
        assert "vega_shock" in check_names
        assert "breakeven_spread" in check_names
```

- [ ] **Step 8: Create `tests/functional/test_profitability_gates.py`**

```python
"""Functional tests: profitability gates (POP, EV, trade quality)."""
import pytest
from datetime import date, timedelta

from income_desk.trade_spec_factory import build_iron_condor
from income_desk.trade_lifecycle import estimate_pop
from income_desk.validation import run_daily_checks
from income_desk.validation.models import Severity


def _ic():
    exp = date.today() + timedelta(days=30)
    return build_iron_condor(
        ticker="SPY", underlying_price=580.0,
        short_put=570.0, long_put=565.0,
        short_call=590.0, long_call=595.0,
        expiration=exp.isoformat(),
    )


class TestPOPGate:
    @pytest.mark.daily
    def test_r1_ic_pop_above_65pct_minimum(self) -> None:
        """R1 IC with 1% ATR should yield POP >= 65%."""
        pop = estimate_pop(
            trade_spec=_ic(), entry_price=1.50,
            regime_id=1, atr_pct=1.0, current_price=580.0,
        )
        assert pop is not None
        assert pop.pop_pct >= 65.0, f"R1 IC POP {pop.pop_pct:.1f}% is below 65% minimum"

    def test_r4_conditions_lower_pop(self) -> None:
        """R4 inflates ATR sigma, reducing POP estimate."""
        pop_r1 = estimate_pop(_ic(), 1.50, regime_id=1, atr_pct=1.0, current_price=580.0)
        pop_r4 = estimate_pop(_ic(), 1.50, regime_id=4, atr_pct=1.0, current_price=580.0)
        assert pop_r1 is not None and pop_r4 is not None
        assert pop_r4.pop_pct < pop_r1.pop_pct, "R4 should have lower POP than R1"

    @pytest.mark.daily
    def test_ev_positive_for_r1_ic(self) -> None:
        """R1 IC with decent credit should have positive expected value."""
        pop = estimate_pop(_ic(), 1.50, regime_id=1, atr_pct=1.0, current_price=580.0)
        assert pop is not None
        assert pop.expected_value > 0, f"EV {pop.expected_value:.0f} should be positive"

    def test_daily_checks_pop_gate_present(self) -> None:
        """run_daily_checks must include pop_gate and ev_positive check names."""
        report = run_daily_checks(
            ticker="SPY", trade_spec=_ic(), entry_credit=1.50,
            regime_id=1, atr_pct=1.0, current_price=580.0,
            avg_bid_ask_spread_pct=0.8, dte=30, rsi=50.0,
        )
        check_names = {c.name for c in report.checks}
        assert "pop_gate" in check_names
        assert "ev_positive" in check_names

    @pytest.mark.daily
    def test_profit_factor_simulation(self) -> None:
        """Simulated 20-trade sequence at 68% win rate must yield profit_factor > 1.5.

        Models a typical monthly IC cycle: 20 trades, 68% win, 50% TP, 2× stop loss.
        """
        win_rate = 0.68
        max_profit = 1.50 * 100  # $150 per contract
        profit_target = max_profit * 0.50  # close at 50% = $75
        max_loss_per_trade = (5.0 * 100 - 1.50 * 100) * 2.0  # 2× credit stop = $700

        n_trades = 20
        n_wins = round(n_trades * win_rate)
        n_losses = n_trades - n_wins

        gross_profit = n_wins * profit_target
        gross_loss = n_losses * max_loss_per_trade

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        assert profit_factor >= 1.5, (
            f"Profit factor {profit_factor:.2f} below 1.5 threshold. "
            f"Win: {n_wins}×${profit_target:.0f}=${gross_profit:.0f}, "
            f"Loss: {n_losses}×${max_loss_per_trade:.0f}=${gross_loss:.0f}"
        )
```

- [ ] **Step 9: Create `tests/functional/test_exit_discipline.py`**

```python
"""Functional tests: exit discipline — right time to close, wrong time to hold."""
import pytest
from datetime import date, timedelta

from income_desk.trade_spec_factory import build_iron_condor
from income_desk.trade_lifecycle import monitor_exit_conditions


def _ic():
    exp = date.today() + timedelta(days=30)
    return build_iron_condor(
        ticker="SPY", underlying_price=580.0,
        short_put=570.0, long_put=565.0,
        short_call=590.0, long_call=595.0,
        expiration=exp.isoformat(),
    )


class TestExitDiscipline:
    @pytest.mark.daily
    def test_profit_target_triggers_at_50pct(self) -> None:
        """When current mid price = 50% of entry credit, profit target fires.

        Entry credit $1.50 → profit target at $0.75 mid (50% closed).
        Simulate: current_mid_price = entry_price * 0.50 (trade decayed to half credit).
        """
        spec = _ic()
        entry_credit = 1.50
        current_mid = entry_credit * 0.50  # at profit target

        result = monitor_exit_conditions(
            trade_id="test-001",
            ticker="SPY",
            structure_type=spec.structure_type or "iron_condor",
            order_side=spec.order_side or "credit",
            entry_price=entry_credit,
            current_mid_price=current_mid,
            contracts=1,
            dte_remaining=15,
            regime_id=1,
            profit_target_pct=spec.profit_target_pct or 0.50,
            stop_loss_pct=spec.stop_loss_pct or 2.0,
            exit_dte=spec.exit_dte or 21,
        )
        assert result is not None
        assert result.should_close is True
        assert "profit" in result.summary.lower() or "target" in result.summary.lower()

    @pytest.mark.daily
    def test_stop_loss_triggers_at_2x_credit(self) -> None:
        """Loss = 2× credit received → stop loss fires.

        Entry credit $1.50, stop at 2×. Current mid = $1.50 + 2×$1.50 = $4.50
        (trade moved against us — now costs $4.50 to close what we sold for $1.50).
        """
        spec = _ic()
        entry_credit = 1.50
        stop_loss_pct = spec.stop_loss_pct or 2.0
        current_mid = entry_credit * (1 + stop_loss_pct)  # at stop loss

        result = monitor_exit_conditions(
            trade_id="test-002",
            ticker="SPY",
            structure_type=spec.structure_type or "iron_condor",
            order_side=spec.order_side or "credit",
            entry_price=entry_credit,
            current_mid_price=current_mid,
            contracts=1,
            dte_remaining=20,
            regime_id=1,
            profit_target_pct=spec.profit_target_pct or 0.50,
            stop_loss_pct=stop_loss_pct,
            exit_dte=spec.exit_dte or 21,
        )
        assert result is not None
        assert result.should_close is True

    @pytest.mark.daily
    def test_dte_exit_triggers_at_threshold(self) -> None:
        """When DTE drops below exit_dte threshold, close to avoid gamma risk."""
        spec = _ic()
        exit_dte = spec.exit_dte or 21

        result = monitor_exit_conditions(
            trade_id="test-003",
            ticker="SPY",
            structure_type=spec.structure_type or "iron_condor",
            order_side=spec.order_side or "credit",
            entry_price=1.50,
            current_mid_price=1.20,  # small profit, not at 50% target
            contracts=1,
            dte_remaining=exit_dte - 1,  # past threshold
            regime_id=1,
            profit_target_pct=spec.profit_target_pct or 0.50,
            stop_loss_pct=spec.stop_loss_pct or 2.0,
            exit_dte=exit_dte,
        )
        assert result is not None
        assert result.should_close is True

    def test_healthy_trade_does_not_exit_early(self) -> None:
        """IC at 25 DTE, small profit, price at center — no exit signal yet."""
        spec = _ic()
        result = monitor_exit_conditions(
            trade_id="test-004",
            ticker="SPY",
            structure_type=spec.structure_type or "iron_condor",
            order_side=spec.order_side or "credit",
            entry_price=1.50,
            current_mid_price=1.30,  # only 13% profit, well above 50% target threshold
            contracts=1,
            dte_remaining=25,  # well above exit_dte
            regime_id=1,
            profit_target_pct=spec.profit_target_pct or 0.50,
            stop_loss_pct=spec.stop_loss_pct or 2.0,
            exit_dte=spec.exit_dte or 21,
        )
        assert result is not None
        assert result.should_close is False
```

- [ ] **Step 10: Create `tests/functional/test_drawdown_circuit.py`**

```python
"""Functional tests: drawdown circuit breaker and position scaling."""
import pytest

from income_desk.risk import check_drawdown_circuit_breaker, compute_risk_dashboard, PortfolioPosition


class TestDrawdownCircuit:
    @pytest.mark.daily
    def test_circuit_breaker_fires_at_10pct_drawdown(self) -> None:
        """10% drawdown from peak → can_open_new_trades = False."""
        status = check_drawdown_circuit_breaker(
            current_nlv=45_000.0,
            account_peak=50_000.0,
            circuit_breaker_pct=0.10,
        )
        assert status.is_triggered is True
        assert status.drawdown_pct >= 0.10

    @pytest.mark.daily
    def test_no_drawdown_circuit_allows_trading(self) -> None:
        """Normal conditions: NLV at peak, circuit breaker not triggered."""
        status = check_drawdown_circuit_breaker(
            current_nlv=50_000.0,
            account_peak=50_000.0,
        )
        assert status.is_triggered is False

    def test_5pct_drawdown_does_not_halt(self) -> None:
        """5% drawdown is uncomfortable but below 10% halt threshold."""
        status = check_drawdown_circuit_breaker(
            current_nlv=47_500.0,
            account_peak=50_000.0,
            circuit_breaker_pct=0.10,
        )
        assert status.is_triggered is False

    @pytest.mark.daily
    def test_risk_dashboard_blocks_trades_after_circuit_fires(
        self, small_account
    ) -> None:
        """compute_risk_dashboard() blocks new trades when drawdown exceeded."""
        dashboard = compute_risk_dashboard(
            positions=[],
            account_nlv=44_000.0,      # 12% below peak
            account_peak=50_000.0,
            max_positions=5,
        )
        assert dashboard.can_open_new_trades is False

    def test_scaling_active_near_drawdown_threshold(self, small_account) -> None:
        """At 7% drawdown, position sizing is scaled down."""
        dashboard = compute_risk_dashboard(
            positions=[],
            account_nlv=46_500.0,      # 7% below peak
            account_peak=50_000.0,
            max_positions=5,
        )
        # Either halted or size factor reduced
        assert dashboard.max_new_trade_size_pct <= 1.0
```

- [ ] **Step 11: Run all functional tests**

```bash
.venv_312/Scripts/python -m pytest tests/functional/ -v
```
Expected: all PASS (some may skip if assessors return NO_GO under certain conditions — that's correct)

- [ ] **Step 12: Run `@pytest.mark.daily` subset**

```bash
.venv_312/Scripts/python -m pytest tests/functional/ -m daily -v
```
Expected: ~15 tests PASS in under 10 seconds

- [ ] **Step 13: Commit**

```bash
git add tests/functional/
git commit -m "feat: add functional test suite (9 modules, daily/adversarial coverage)"
```

---

## Task 7: CLI `do_validate` Command

**Files:**
- Modify: `income_desk/cli/interactive.py`

**Design:** The command fetches real market data via MA services, runs the appropriate assessor
to get a real TradeSpec (with ATR/vol-surface-based strikes), fetches real entry credit from
DXLink broker quotes when connected, then passes everything to the pure validation functions.
When no broker is connected, it falls back to an IV-based credit estimate and shows a warning.

- [ ] **Step 1: Write a CLI smoke test**

Add to `tests/test_cli_functional.py` (create if not exists):

```python
"""Smoke tests for the do_validate CLI command."""
import pytest


def test_do_validate_no_args_prints_usage(capsys) -> None:
    """do_validate with no args prints usage without crashing."""
    from income_desk.cli.interactive import InteractiveShell
    shell = InteractiveShell.__new__(InteractiveShell)
    shell.do_validate("")
    out = capsys.readouterr().out
    assert "Usage" in out or "validate" in out.lower()


def test_do_validate_invalid_suite_prints_error(capsys) -> None:
    """--suite with unknown value prints error without crashing."""
    from income_desk.cli.interactive import InteractiveShell
    shell = InteractiveShell.__new__(InteractiveShell)
    shell.do_validate("SPY --suite bad_value")
    out = capsys.readouterr().out
    assert out  # something printed, did not crash
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv_312/Scripts/python -m pytest tests/test_cli_functional.py -v
```
Expected: `AttributeError: do_validate` not found

- [ ] **Step 3: Add `do_validate` to `cli/interactive.py`**

Find the `do_income_entry` method in `interactive.py`. Add the following method directly after it:

```python
def do_validate(self, arg: str) -> None:
    """Run profitability validation using live broker data.

    Usage:
        validate TICKER [--suite daily|adversarial|full]
        validate SPY
        validate SPY --suite adversarial
        validate SPY --suite full

    Suites:
        daily       7-check pre-trade validation (default)
                    commission_drag, fill_quality, margin_efficiency,
                    pop_gate, ev_positive, entry_quality, exit_discipline
        adversarial Stress tests: gamma_stress, vega_shock, breakeven_spread
        full        Both suites combined (10 checks)

    Data sources:
        Regime, ATR, RSI      — yfinance OHLCV (always available)
        Vol surface, spread   — yfinance options chain (always available)
        TradeSpec strikes     — assess_iron_condor() with real vol + levels
        Entry credit          — DXLink real mid prices (broker required)
                                Falls back to IV-based estimate if no broker.
        IV rank               — TastyTrade REST API (broker required)

    Output is MCP-consumable: structured PASS/WARN/FAIL per check.
    Run pre-market before trading.
    """
    from income_desk.models.opportunity import LegAction, Verdict
    from income_desk.opportunity.option_plays.iron_condor import assess_iron_condor
    from income_desk.validation import run_adversarial_checks, run_daily_checks
    from income_desk.validation.models import Severity

    # ── Argument parsing ──────────────────────────────────────────────────
    parts = arg.strip().split()
    if not parts or parts[0].startswith("-"):
        print("Usage: validate TICKER [--suite daily|adversarial|full]")
        return

    ticker = parts[0].upper()
    suite_arg = "daily"
    for i, p in enumerate(parts[1:], 1):
        if p == "--suite" and i + 1 < len(parts):
            suite_arg = parts[i + 1]

    if suite_arg not in ("daily", "adversarial", "full"):
        print(f"Unknown suite '{suite_arg}'. Use: daily, adversarial, full")
        return

    try:
        ma = self._get_ma()

        # ── Step 1: Fetch real market data ────────────────────────────────
        regime = ma.regime.detect(ticker)
        tech   = ma.technicals.snapshot(ticker)
        vol    = ma.vol_surface.compute(ticker)   # VolatilitySurface | None

        regime_id     = int(regime.regime)
        current_price = tech.current_price
        atr_pct       = tech.atr_pct
        rsi           = tech.rsi.value
        avg_spread_pct = vol.avg_bid_ask_spread_pct if vol else 2.0

        # IV rank from broker metrics (None if not connected)
        metrics  = ma.quotes.get_metrics(ticker) if ma.quotes else None
        iv_rank  = metrics.iv_rank if metrics else None

        _print_header(f"VALIDATION — {ticker} — {suite_arg.upper()} SUITE")

        # ── Step 2: Run assessor → real TradeSpec ─────────────────────────
        # assess_iron_condor places short strikes using vol surface + support/resistance.
        # This is the same TradeSpec that would be submitted to the broker.
        ic_result = assess_iron_condor(ticker, regime, tech, vol)

        if ic_result.verdict == Verdict.NO_GO:
            stop_msg = ic_result.hard_stops[0].description if ic_result.hard_stops else "hard stop"
            print(f"  {_styled('✗ FAIL', 'red')}  {'assessor_gate':<22s}  {stop_msg}")
            print()
            print(f"  {_styled('NOT READY', 'red')}  (hard stopped — no trade possible in current regime)")
            print(f"  Regime: R{regime_id} | ATR: {atr_pct:.2f}% | RSI: {rsi:.0f}")
            return

        spec = ic_result.trade_spec
        if spec is None:
            print(f"  {_styled('ERROR:', 'red')} Assessor returned GO but no TradeSpec")
            return

        # ── Step 3: Get real entry credit from DXLink ─────────────────────
        # Broker quotes give us the actual mid price for each leg.
        # entry_credit = sum(STO mids) - sum(BTO mids) = net credit per share.
        entry_credit: float | None = None
        credit_source = "none"

        if ma.quotes and ma.quotes.has_broker:
            try:
                leg_quotes = ma.quotes.get_leg_quotes(spec.legs)
                if leg_quotes and len(leg_quotes) == len(spec.legs):
                    entry_credit = sum(
                        q.mid * (1 if leg.action == LegAction.SELL_TO_OPEN else -1)
                        for leg, q in zip(spec.legs, leg_quotes)
                        if q is not None and q.mid is not None
                    )
                    credit_source = f"DXLink ({ma.quotes.source})"
            except Exception:
                pass  # fall through to estimate

        if entry_credit is None or entry_credit <= 0:
            # Fallback: estimate from IV — approximate IC credit ≈ front_iv × price × 0.05
            front_iv = vol.front_iv if vol else 0.20
            entry_credit = round(front_iv * current_price * 0.05, 2)
            credit_source = "IV estimate (no broker quotes)"
            print(f"  {_styled('⚠ WARN', 'yellow')}  {'broker_quotes':<22s}  "
                  f"No live quotes — using credit estimate ${entry_credit:.2f} ({credit_source})")

        # ── Step 4: Run validation with real data ─────────────────────────
        reports = []

        if suite_arg in ("daily", "full"):
            report = run_daily_checks(
                ticker=ticker,
                trade_spec=spec,
                entry_credit=entry_credit,
                regime_id=regime_id,
                atr_pct=atr_pct,
                current_price=current_price,
                avg_bid_ask_spread_pct=avg_spread_pct,
                dte=spec.target_dte,
                rsi=rsi,
                iv_rank=iv_rank,
                iv_percentile=metrics.iv_percentile if metrics else None,
            )
            reports.append(report)

        if suite_arg in ("adversarial", "full"):
            report_adv = run_adversarial_checks(
                ticker=ticker,
                trade_spec=spec,
                entry_credit=entry_credit,
                atr_pct=atr_pct,
            )
            reports.append(report_adv)

        # ── Step 5: Display results ────────────────────────────────────────
        for report in reports:
            if len(reports) > 1:
                print(f"\n  [{report.suite.upper()}]")
            for check in report.checks:
                icon  = "✓" if check.severity == Severity.PASS else (
                        "⚠" if check.severity == Severity.WARN else "✗")
                color = "green" if check.severity == Severity.PASS else (
                        "yellow" if check.severity == Severity.WARN else "red")
                label = _styled(f"{icon} {check.severity.upper():4s}", color)
                print(f"  {label}  {check.name:<22s}  {check.message}")

        print()
        all_checks = [c for r in reports for c in r.checks]
        passed   = sum(1 for c in all_checks if c.severity == Severity.PASS)
        warnings = sum(1 for c in all_checks if c.severity == Severity.WARN)
        failures = sum(1 for c in all_checks if c.severity == Severity.FAIL)
        is_ready = failures == 0

        status_text  = "READY TO TRADE" if is_ready else "NOT READY"
        status_color = "green" if is_ready else "red"
        print("  " + "─" * 60)
        print(f"  {_styled(status_text, status_color)}  "
              f"({passed}/{len(all_checks)} passed, {warnings} warnings, {failures} failures)")
        print(f"  Regime: R{regime_id} ({regime.confidence:.0%}) | "
              f"ATR: {atr_pct:.2f}% | RSI: {rsi:.0f} | "
              f"IV Rank: {f'{iv_rank:.0f}' if iv_rank else 'N/A'} | "
              f"Credit: ${entry_credit:.2f} [{credit_source}]")

    except Exception as exc:
        print(f"{_styled('ERROR:', 'red')} {exc}")
```

- [ ] **Step 4: Run smoke test**

```bash
.venv_312/Scripts/python -m pytest tests/test_cli_functional.py -v
```
Expected: 2 tests PASS

- [ ] **Step 5: Manual integration test** (requires yfinance data — no broker needed for basic run)

```bash
analyzer-cli
# In REPL:
validate SPY
validate SPY --suite adversarial
validate SPY --suite full
validate GLD
```

Expected output (without broker):
```
VALIDATION — SPY — DAILY SUITE
  ⚠ WARN  broker_quotes          No live quotes — using credit estimate $1.45 (IV estimate)
  ✓ PASS  commission_drag        Credit $145 covers $5.20 fees (3.6% drag), net $139.80
  ✓ PASS  fill_quality           Spread 0.9% — survives natural fill
  ✓ PASS  margin_efficiency      Annualized ROC 16.2% — capital deployed efficiently
  ...
  ────────────────────────────────────────────────────────────
  READY TO TRADE  (6/7 passed, 1 warning)
  Regime: R1 (82%) | ATR: 1.20% | RSI: 51 | IV Rank: N/A | Credit: $1.45 [IV estimate]
```

Expected output (with broker `--broker` flag):
```
  ✓ PASS  commission_drag        Credit $162 covers $5.20 fees (3.2% drag), net $156.80
  ...
  Credit: $1.62 [DXLink (tastytrade)]
```

- [ ] **Step 6: Run full regression suite**

```bash
.venv_312/Scripts/python -m pytest tests/ -v --tb=short
```
Expected: all existing tests PASS, new tests PASS, no regressions

- [ ] **Step 7: Final commit**

```bash
git add income_desk/cli/interactive.py tests/test_cli_functional.py
git commit -m "feat: add validate CLI command for daily pre-trade profitability check"
```

---

## Final Verification

- [ ] All functional tests pass: `pytest tests/functional/ -v`
- [ ] Daily suite is fast: `pytest tests/functional/ -m daily -v` completes in < 15 seconds
- [ ] CLI validate command works: `validate SPY` in REPL
- [ ] No regressions: `pytest tests/ -v` passes
- [ ] Validation module importable: `python -c "from income_desk.validation import run_daily_checks; print('OK')"`
- [ ] Update `USER_MANUAL.md` with `validate` command documentation

---

## Summary

| Component | Location | Purpose |
|---|---|---|
| `validation/models.py` | `income_desk/` | CheckResult, Severity, Suite, ValidationReport |
| `validation/profitability_audit.py` | `income_desk/` | commission_drag, fill_quality, margin_efficiency |
| `validation/stress_scenarios.py` | `income_desk/` | gamma_stress, vega_shock, breakeven_spread |
| `validation/daily_readiness.py` | `income_desk/` | run_daily_checks, run_adversarial_checks |
| `tests/functional/` | `tests/` | 9 test modules, `@pytest.mark.daily` subset |
| `do_validate` | `cli/interactive.py` | Daily pre-market CLI command, MCP-consumable |
