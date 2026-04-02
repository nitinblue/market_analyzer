"""Pydantic models for the trade validator.

Structure-aware validation rules, configurable thresholds, and result types
for the validation layer between trade generation and output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ValidationConfig(BaseModel):
    """All validation thresholds — configurable, with sensible defaults."""

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
    zero_contracts_action: Literal[
        "exclude", "show_fractional", "show_min_1"
    ] = "show_fractional"

    # DTE tolerance
    dte_tolerance_days: int = 7

    # Concentration (portfolio-level, not per-trade)
    max_per_structure: int = 2
    correlation_penalty_threshold: float = 0.7
    correlation_penalty_pct: float = 0.30

    @classmethod
    def default(cls) -> ValidationConfig:
        """Return a config with all defaults."""
        return cls()

    @classmethod
    def from_yaml(cls, path: str | Path) -> ValidationConfig:
        """Load config from a YAML file.

        Only keys present in the YAML override the defaults.
        Raises ``FileNotFoundError`` if *path* does not exist and
        ``ImportError`` if PyYAML is not installed.
        """
        import yaml  # noqa: WPS433 — optional dep, lazy import

        path = Path(path)
        with path.open("r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}
        return cls(**raw)


# ---------------------------------------------------------------------------
# Structure knowledge base
# ---------------------------------------------------------------------------


class StructureRule(BaseModel):
    """Declares what is structurally valid for a given trade type."""

    required_legs: int
    leg_roles: set[str] | None = None  # None = any combination accepted
    wing_width: Literal["required", "not_applicable"]
    max_loss: Literal["computed", "approximate", "unlimited"]
    max_profit: Literal["computed", "unbounded", "varies"]
    entry_type: Literal["credit", "debit"]
    max_loss_formula: str | None = None
    max_profit_formula: str | None = None
    notes: str = ""


STRUCTURE_RULES: dict[str, StructureRule] = {
    "iron_condor": StructureRule(
        required_legs=4,
        leg_roles={"short_put", "long_put", "short_call", "long_call"},
        wing_width="required",
        max_loss="computed",
        max_profit="computed",
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
        max_loss="approximate",
        max_profit="unbounded",
        entry_type="debit",
        notes="Same strike, different expiry. Max loss ~ debit paid.",
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
    "double_calendar": StructureRule(
        required_legs=4,
        wing_width="not_applicable",
        max_loss="approximate",
        max_profit="unbounded",
        entry_type="debit",
        notes="Two calendars at different strikes. Max loss ~ debit paid.",
    ),
}


# ---------------------------------------------------------------------------
# Validation result types
# ---------------------------------------------------------------------------


class ValidationFlag(BaseModel):
    """A warning that does not block the trade but should be surfaced."""

    field: str
    value: Any
    threshold: Any
    message: str


class ValidationRejection(BaseModel):
    """A hard block — the trade cannot proceed."""

    field: str
    value: Any
    rule: str
    root_cause: str
    suggestion: str


class ValidatedEconomics(BaseModel):
    """Guaranteed non-null economics for valid/flagged trades."""

    entry_credit: float = Field(
        description="Positive for credit trades, negative for debit trades.",
    )
    max_profit: float = Field(ge=0, description="Always >= 0.")
    max_loss: float | None = Field(
        default=None,
        description="None only for unlimited-risk structures.",
    )
    wing_width: float | None = Field(
        default=None,
        description="None only when not_applicable per structure rules.",
    )
    pop_pct: float = Field(ge=0.0, le=1.0)
    expected_value: float
    contracts: float = Field(
        description="May be fractional if position is unfundable at 1 contract.",
    )
    lot_size: int


class ValidationResult(BaseModel):
    """Outcome of running a trade through the validator."""

    status: Literal["valid", "flagged", "rejected"]
    flags: list[ValidationFlag] = Field(default_factory=list)
    rejections: list[ValidationRejection] = Field(default_factory=list)
    economics: ValidatedEconomics | None = Field(
        default=None,
        description="None only when status is 'rejected'.",
    )
