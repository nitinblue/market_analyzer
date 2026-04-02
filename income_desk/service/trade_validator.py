"""TradeValidator: structure-aware configurable trade validation.

Every trade passes through validate() after generation.
Rules are driven by the structure knowledge base + user config.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from income_desk.models.validation import (
    STRUCTURE_RULES,
    ValidatedEconomics,
    ValidationConfig,
    ValidationFlag,
    ValidationRejection,
    ValidationResult,
)

if TYPE_CHECKING:
    from income_desk.models.opportunity import TradeSpec
    from income_desk.workflow.pricing_service import RepricedTrade

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WING_PAIRS: list[tuple[str, str]] = [
    ("short_put", "long_put"),
    ("short_call", "long_call"),
]
"""Pairs of leg roles that define a wing spread."""


def _strikes_by_role(trade_spec: TradeSpec) -> dict[str, float]:
    """Map leg role -> strike for all legs in a trade spec."""
    return {leg.role: leg.strike for leg in trade_spec.legs}


def _compute_wing_width(strikes: dict[str, float]) -> float | None:
    """Compute the wing width from short/long strike pairs.

    Returns the narrowest wing (for iron condors with asymmetric widths),
    or None if no wing pairs are present.
    """
    widths: list[float] = []
    for short_role, long_role in _WING_PAIRS:
        if short_role in strikes and long_role in strikes:
            width = abs(strikes[short_role] - strikes[long_role])
            widths.append(width)
    return min(widths) if widths else None


# ---------------------------------------------------------------------------
# PopEstimate protocol — we accept anything with a .pop_pct attribute
# ---------------------------------------------------------------------------

class _PopLike:
    """Structural type for POP estimates (duck typing)."""
    pop_pct: float


# ---------------------------------------------------------------------------
# TradeValidator
# ---------------------------------------------------------------------------


class TradeValidator:
    """Structure-aware configurable trade validation.

    Every trade passes through ``validate()`` after generation.
    Rules are driven by the structure knowledge base + user config.
    The validator is **stateless** — all config is injected at construction.
    """

    def __init__(self, config: ValidationConfig | None = None) -> None:
        self.config = config or ValidationConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        trade_spec: TradeSpec,
        repriced_trade: RepricedTrade | None = None,
        pop_estimate: _PopLike | None = None,
    ) -> ValidationResult:
        """Validate a single trade.

        Returns a :class:`ValidationResult` with status ``valid``,
        ``flagged``, or ``rejected`` — plus detailed flags, rejections,
        and validated economics.
        """
        flags: list[ValidationFlag] = []
        rejections: list[ValidationRejection] = []

        # ── Step 1: Structure match ──────────────────────────────────
        structure_type = trade_spec.structure_type or ""
        rule = STRUCTURE_RULES.get(structure_type)

        if rule is None:
            rejections.append(ValidationRejection(
                field="structure_type",
                value=structure_type,
                rule="structure_known",
                root_cause=f"Unknown structure type '{structure_type}'",
                suggestion=(
                    "Use one of the known structure types: "
                    + ", ".join(sorted(STRUCTURE_RULES.keys()))
                ),
            ))
            logger.warning("Rejected trade: unknown structure '%s'", structure_type)
            return ValidationResult(
                status="rejected", rejections=rejections, flags=flags,
            )

        actual_legs = len(trade_spec.legs)
        if actual_legs != rule.required_legs:
            rejections.append(ValidationRejection(
                field="legs",
                value=actual_legs,
                rule="leg_count",
                root_cause=(
                    f"Expected {rule.required_legs} legs for {structure_type}, "
                    f"got {actual_legs}"
                ),
                suggestion=(
                    f"Rebuild the trade spec with exactly "
                    f"{rule.required_legs} legs for a {structure_type}."
                ),
            ))
            logger.warning(
                "Rejected %s: expected %d legs, got %d",
                structure_type, rule.required_legs, actual_legs,
            )
            return ValidationResult(
                status="rejected", rejections=rejections, flags=flags,
            )

        # ── Step 2: Strike validation (wing structures only) ─────────
        strikes = _strikes_by_role(trade_spec)
        wing_width: float | None = None

        if rule.wing_width == "required":
            for short_role, long_role in _WING_PAIRS:
                if short_role in strikes and long_role in strikes:
                    if strikes[short_role] == strikes[long_role]:
                        rejections.append(ValidationRejection(
                            field=f"{short_role}_vs_{long_role}",
                            value=strikes[short_role],
                            rule="wing_width_nonzero",
                            root_cause=(
                                f"short_strike ({strikes[short_role]}) == "
                                f"long_strike ({strikes[long_role]}), wing_width=0"
                            ),
                            suggestion=(
                                "Widen the wing — move the long strike at least "
                                "1 strike away from the short strike."
                            ),
                        ))

            if rejections:
                logger.warning(
                    "Rejected %s %s: zero wing width",
                    trade_spec.ticker, structure_type,
                )
                return ValidationResult(
                    status="rejected", rejections=rejections, flags=flags,
                )

            wing_width = _compute_wing_width(strikes)
            if wing_width is not None and wing_width < self.config.min_wing_width_strikes:
                flags.append(ValidationFlag(
                    field="wing_width",
                    value=wing_width,
                    threshold=self.config.min_wing_width_strikes,
                    message=(
                        f"Wing width {wing_width} is below minimum "
                        f"{self.config.min_wing_width_strikes}"
                    ),
                ))

        # ── Step 3: Economics computation ─────────────────────────────
        # Determine entry credit/debit
        entry_credit: float
        if repriced_trade is not None:
            entry_credit = repriced_trade.entry_credit
        elif trade_spec.limit_price is not None:
            entry_credit = trade_spec.limit_price
        elif trade_spec.max_entry_price is not None:
            entry_credit = trade_spec.max_entry_price
        else:
            entry_credit = 0.0

        lot_size = trade_spec.lot_size

        # Compute max_profit and max_loss based on structure formulas
        max_profit: float = 0.0
        max_loss: float | None = None

        if rule.max_profit == "computed" and rule.max_profit_formula:
            max_profit = self._eval_profit_formula(
                rule.max_profit_formula, entry_credit, wing_width, lot_size,
            )
        elif rule.max_profit == "unbounded":
            # Calendar/diagonal — profit is theoretically unbounded;
            # approximate as a multiple of debit paid
            max_profit = abs(entry_credit) * lot_size * 2.0
        elif rule.max_profit == "varies":
            max_profit = abs(entry_credit) * lot_size

        if rule.max_loss == "computed" and rule.max_loss_formula:
            max_loss = self._eval_loss_formula(
                rule.max_loss_formula, entry_credit, wing_width, lot_size,
            )
            if max_loss is not None and max_loss <= 0:
                rejections.append(ValidationRejection(
                    field="max_loss",
                    value=max_loss,
                    rule="max_loss_positive",
                    root_cause=(
                        f"Computed max_loss={max_loss:.2f} is <= 0 "
                        f"(formula: {rule.max_loss_formula}, "
                        f"entry_credit={entry_credit}, wing_width={wing_width})"
                    ),
                    suggestion=(
                        "Entry credit exceeds wing width — the structure is "
                        "mispriced or misconfigured. Verify strikes and pricing."
                    ),
                ))
                logger.warning(
                    "Rejected %s %s: max_loss=%.2f <= 0",
                    trade_spec.ticker, structure_type, max_loss,
                )
                return ValidationResult(
                    status="rejected", rejections=rejections, flags=flags,
                )
        elif rule.max_loss == "approximate":
            max_loss = abs(entry_credit) * lot_size
        elif rule.max_loss == "unlimited":
            max_loss = None

        # Flag low credit on credit structures
        if rule.entry_type == "credit" and entry_credit < self.config.min_credit_per_spread:
            flags.append(ValidationFlag(
                field="entry_credit",
                value=entry_credit,
                threshold=self.config.min_credit_per_spread,
                message=(
                    f"Entry credit ${entry_credit:.2f} is below minimum "
                    f"${self.config.min_credit_per_spread:.2f} per spread"
                ),
            ))

        # ── Step 4: POP validation ────────────────────────────────────
        pop_pct: float = 0.0
        if pop_estimate is not None:
            pop_pct = pop_estimate.pop_pct
            if pop_pct < self.config.pop_suspicious_low:
                flags.append(ValidationFlag(
                    field="pop_pct",
                    value=pop_pct,
                    threshold=self.config.pop_suspicious_low,
                    message=(
                        f"POP {pop_pct:.1%} is suspiciously low "
                        f"(below {self.config.pop_suspicious_low:.0%})"
                    ),
                ))
            elif pop_pct > self.config.pop_suspicious_high:
                flags.append(ValidationFlag(
                    field="pop_pct",
                    value=pop_pct,
                    threshold=self.config.pop_suspicious_high,
                    message=(
                        f"POP {pop_pct:.1%} is suspiciously high "
                        f"(above {self.config.pop_suspicious_high:.0%})"
                    ),
                ))

        # Guard: negative max_profit means trade costs more than max payout
        if max_profit < 0:
            rejections.append(ValidationRejection(
                field="max_profit",
                value=max_profit,
                rule="max_profit_positive",
                root_cause=(
                    f"Computed max_profit={max_profit:.2f} is negative — "
                    f"entry cost exceeds maximum payout"
                ),
                suggestion="Widen the spread or find a cheaper entry.",
            ))
            logger.warning(
                "Rejected %s %s: max_profit=%.2f <= 0",
                trade_spec.ticker, structure_type, max_profit,
            )
            return ValidationResult(
                status="rejected", rejections=rejections, flags=flags,
            )

        # ── Step 5: DTE validation ────────────────────────────────────
        if trade_spec.legs:
            actual_dte = trade_spec.legs[0].days_to_expiry
            target_dte = trade_spec.target_dte
            dte_diff = abs(actual_dte - target_dte)
            if dte_diff > self.config.dte_tolerance_days:
                flags.append(ValidationFlag(
                    field="dte",
                    value=actual_dte,
                    threshold=f"target={target_dte} ± {self.config.dte_tolerance_days}",
                    message=(
                        f"Actual DTE ({actual_dte}) differs from target "
                        f"({target_dte}) by {dte_diff} days "
                        f"(tolerance: {self.config.dte_tolerance_days})"
                    ),
                ))

        # ── Step 6: Build ValidatedEconomics ──────────────────────────
        expected_value = self._compute_ev(pop_pct, max_profit, max_loss)
        contracts = self._compute_contracts(trade_spec, max_loss, lot_size)

        economics = ValidatedEconomics(
            entry_credit=entry_credit,
            max_profit=max_profit,
            max_loss=max_loss,
            wing_width=wing_width,
            pop_pct=pop_pct,
            expected_value=expected_value,
            contracts=contracts,
            lot_size=lot_size,
        )

        status = "flagged" if flags else "valid"
        if flags:
            for f in flags:
                logger.info("Flag on %s %s: %s", trade_spec.ticker, structure_type, f.message)

        return ValidationResult(
            status=status,
            flags=flags,
            rejections=rejections,
            economics=economics,
        )

    def validate_batch(self, trades: list[dict]) -> list[ValidationResult]:
        """Validate a batch of trades and apply concentration rules.

        Args:
            trades: Each dict is kwargs to ``validate()`` — must contain
                ``trade_spec`` and optionally ``repriced_trade`` and
                ``pop_estimate``.

        Returns:
            List of :class:`ValidationResult` in the same order as input.
        """
        results = [self.validate(**t) for t in trades]
        self._apply_concentration(results, trades)
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _eval_profit_formula(
        formula: str,
        entry_credit: float,
        wing_width: float | None,
        lot_size: int,
    ) -> float:
        """Evaluate a max_profit formula from StructureRule.

        Known formulas:
          - ``"entry_credit * lot_size"``
          - ``"(wing_width - entry_debit) * lot_size"``
        """
        if "entry_credit" in formula:
            return abs(entry_credit) * lot_size
        if "entry_debit" in formula and wing_width is not None:
            return (wing_width - abs(entry_credit)) * lot_size
        return abs(entry_credit) * lot_size

    @staticmethod
    def _eval_loss_formula(
        formula: str,
        entry_credit: float,
        wing_width: float | None,
        lot_size: int,
    ) -> float | None:
        """Evaluate a max_loss formula from StructureRule.

        Known formulas:
          - ``"(wing_width - entry_credit) * lot_size"``
          - ``"entry_debit * lot_size"``
        """
        if "wing_width" in formula and wing_width is not None:
            return (wing_width - abs(entry_credit)) * lot_size
        if "entry_debit" in formula:
            return abs(entry_credit) * lot_size
        return None

    @staticmethod
    def _compute_ev(
        pop_pct: float, max_profit: float, max_loss: float | None,
    ) -> float:
        """Expected value = POP * profit - (1-POP) * loss.

        For unlimited-risk structures (max_loss=None), EV is set to 0
        since we cannot compute it without a risk estimate.
        """
        if max_loss is None or max_loss == 0:
            return 0.0
        return pop_pct * max_profit - (1.0 - pop_pct) * max_loss

    @staticmethod
    def _compute_contracts(
        trade_spec: TradeSpec, max_loss: float | None, lot_size: int,
    ) -> float:
        """Delegate to TradeSpec.position_size if possible, else return 1.

        Returns float to support fractional sizing (show_fractional mode).
        """
        # If the trade_spec itself can compute sizing, use it
        try:
            return float(trade_spec.position_size(capital=50_000, risk_pct=0.02))
        except Exception:  # noqa: BLE001
            return 1.0

    def _apply_concentration(
        self,
        results: list[ValidationResult],
        trades: list[dict],
    ) -> None:
        """Flag excess trades per structure type (concentration limit).

        Keeps the best N (by composite_score from trade_spec context) and
        flags the rest. Modifies results in place.
        """
        # Group indices by structure type
        structure_groups: dict[str, list[int]] = {}
        for idx, trade_kwargs in enumerate(trades):
            ts = trade_kwargs.get("trade_spec")
            if ts is None:
                continue
            st = ts.structure_type or ""
            structure_groups.setdefault(st, []).append(idx)

        for st, indices in structure_groups.items():
            if len(indices) <= self.config.max_per_structure:
                continue

            # Sort by trade quality — use composite_score from the
            # RankedEntry context if available, otherwise by entry_credit
            def _score_key(idx: int) -> float:
                r = results[idx]
                if r.economics is not None:
                    return r.economics.expected_value
                return 0.0

            sorted_indices = sorted(indices, key=_score_key, reverse=True)
            excess = sorted_indices[self.config.max_per_structure:]

            for idx in excess:
                r = results[idx]
                if r.status == "rejected":
                    continue  # Already rejected, don't double-flag
                r.flags.append(ValidationFlag(
                    field="concentration",
                    value=len(indices),
                    threshold=self.config.max_per_structure,
                    message=(
                        f"Concentration limit: {len(indices)} {st} trades "
                        f"exceeds max {self.config.max_per_structure} — "
                        f"this trade is outside the top {self.config.max_per_structure}"
                    ),
                ))
                if r.status == "valid":
                    r.status = "flagged"
