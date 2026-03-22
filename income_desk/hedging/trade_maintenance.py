"""Trade maintenance — the primary 'hedge' for small accounts.

For income accounts under ~$200K, Greek-level hedging instruments (buying puts,
collars, futures) are impractical: the lot sizes eat too much capital and the
cost is high relative to position size.

The REAL hedge for these accounts is disciplined trade adjustment:
  - Profitable, regime stable   → hold (structure is working)
  - Tested, regime stable       → roll the tested side
  - Tested, regime changed      → convert to diagonal (add directionality)
  - Losing, time running out    → widen wings or close
  - Approaching max loss        → close (the stop IS the hedge)

This module is regime-aware: the same market price can trigger different
actions depending on whether the underlying regime has shifted.

All functions are pure — no I/O, no network, no randomness.
"""

from __future__ import annotations

from income_desk.hedging.models import TradeMaintenanceResult
from income_desk.models.opportunity import TradeSpec

# Threshold below which trade-adjustment is the primary hedge strategy
SMALL_ACCOUNT_THRESHOLD = 200_000

# % of max profit at which we consider a position "profitable enough to hold"
_PROFIT_HOLD_PCT = 0.25   # at 25%+ profit → hold unless regime has changed

# P&L % losses that define tested / breached / near-max-loss zones
_TESTED_LOSS_PCT = -0.15     # more than 15% loss → tested
_NEAR_MAX_LOSS_PCT = -0.60   # more than 60% loss → close

# DTE thresholds
_URGENT_DTE = 10             # ≤10 DTE with significant loss → act now
_EXPIRING_DTE = 5            # ≤5 DTE → close regardless of P&L


def recommend_trade_maintenance(
    trade_spec: TradeSpec,
    current_price: float,
    entry_price: float,
    regime_id: int,
    entry_regime_id: int | None = None,
    dte_remaining: int = 30,
    current_pnl_pct: float = 0.0,
    account_nlv: float = 100_000,
) -> TradeMaintenanceResult:
    """Recommend the appropriate trade adjustment as the primary hedging action.

    For small accounts with option positions (ICs, credit spreads, calendars),
    this function replaces a traditional hedging analysis.  The structure
    already limits max loss — the job is to manage it intelligently.

    Args:
        trade_spec:       The active position's TradeSpec.
        current_price:    Current underlying price.
        entry_price:      Premium received (credit) or paid (debit) at entry.
                          Positive for credits.
        regime_id:        Current regime (1–4).
        entry_regime_id:  Regime when the trade was entered (None = unknown).
        dte_remaining:    Days until expiration.
        current_pnl_pct:  Current P&L as a fraction of max profit.
                          0.50 = 50% profit; -0.30 = 30% loss of max-loss.
        account_nlv:      Account net liquidating value (for sizing notes).

    Returns:
        TradeMaintenanceResult with a concrete action, urgency, and rationale.
    """
    ticker = trade_spec.ticker
    account_size_note = _build_account_note(account_nlv)
    regime_context = _regime_context(regime_id, entry_regime_id)
    regime_changed = entry_regime_id is not None and regime_id != entry_regime_id

    # ------------------------------------------------------------------
    # Priority 1 — Near expiry: close any significant loser
    # ------------------------------------------------------------------
    if dte_remaining <= _EXPIRING_DTE and current_pnl_pct < _TESTED_LOSS_PCT:
        return TradeMaintenanceResult(
            ticker=ticker,
            action="close",
            urgency="immediate",
            rationale=(
                f"≤{_EXPIRING_DTE} DTE with {current_pnl_pct:.0%} P&L — "
                "position is expiring with an unrealised loss. "
                "Close to prevent pin risk and assignment."
            ),
            trade_spec=None,  # eTrading builds the close order from existing legs
            regime_context=regime_context,
            account_size_note=account_size_note,
        )

    # ------------------------------------------------------------------
    # Priority 2 — Near max loss: close immediately
    # ------------------------------------------------------------------
    if current_pnl_pct <= _NEAR_MAX_LOSS_PCT:
        return TradeMaintenanceResult(
            ticker=ticker,
            action="close",
            urgency="immediate",
            rationale=(
                f"Position at {current_pnl_pct:.0%} P&L — approaching max loss. "
                "The defined risk IS the hedge; honor it. Close now."
            ),
            trade_spec=None,
            regime_context=regime_context,
            account_size_note=account_size_note,
        )

    # ------------------------------------------------------------------
    # Priority 3 — Regime changed: convert to diagonal
    # ------------------------------------------------------------------
    if regime_changed:
        from_r = f"R{entry_regime_id}"
        to_r = f"R{regime_id}"
        if current_pnl_pct <= _TESTED_LOSS_PCT:
            # Losing AND regime shifted — convert to add directionality
            return TradeMaintenanceResult(
                ticker=ticker,
                action="convert_to_diagonal",
                urgency="soon",
                rationale=(
                    f"Regime changed {from_r} → {to_r} and position is "
                    f"at {current_pnl_pct:.0%} P&L. "
                    "Converting to diagonal adds directional bias aligned with "
                    "new regime while preserving theta income."
                ),
                trade_spec=None,  # Caller uses AdjustmentService for full TradeSpec
                regime_context=regime_context,
                account_size_note=account_size_note,
            )
        else:
            # Profitable but regime shifted — monitor closely, consider early close
            return TradeMaintenanceResult(
                ticker=ticker,
                action="hold",
                urgency="monitor",
                rationale=(
                    f"Regime changed {from_r} → {to_r} but position is "
                    f"at {current_pnl_pct:.0%} profit. "
                    "Hold and monitor — take profit early if structure reaches 40%+ max profit "
                    "rather than waiting for target."
                ),
                trade_spec=None,
                regime_context=regime_context,
                account_size_note=account_size_note,
            )

    # ------------------------------------------------------------------
    # Priority 4 — Tested / losing, regime stable
    # ------------------------------------------------------------------
    if current_pnl_pct <= _TESTED_LOSS_PCT:
        if dte_remaining <= _URGENT_DTE:
            # Running out of time with a loss — close
            return TradeMaintenanceResult(
                ticker=ticker,
                action="close",
                urgency="soon",
                rationale=(
                    f"≤{_URGENT_DTE} DTE with {current_pnl_pct:.0%} P&L and "
                    f"regime {_regime_name(regime_id)}. "
                    "Insufficient time for adjustment to work. Close and redeploy."
                ),
                trade_spec=None,
                regime_context=regime_context,
                account_size_note=account_size_note,
            )

        # Enough time remaining — roll or widen based on regime
        if regime_id in (1, 2):
            # Mean-reverting regime: roll tested side, give it room to snap back
            action = "roll"
            rationale = (
                f"Position tested at {current_pnl_pct:.0%} P&L in {_regime_name(regime_id)}. "
                "Mean-reverting regime favors rolling the tested side further OTM "
                "to collect more credit and reduce directional exposure."
            )
        else:
            # Trending regime: widening wings reduces gamma risk of a continued move
            action = "widen"
            rationale = (
                f"Position tested at {current_pnl_pct:.0%} P&L in {_regime_name(regime_id)}. "
                "Trending regime — widening the wings (or rolling the untested side in) "
                "reduces further damage if the trend continues."
            )

        return TradeMaintenanceResult(
            ticker=ticker,
            action=action,
            urgency="soon",
            rationale=rationale,
            trade_spec=None,  # AdjustmentService produces the concrete TradeSpec
            regime_context=regime_context,
            account_size_note=account_size_note,
        )

    # ------------------------------------------------------------------
    # Priority 5 — Profitable, regime stable → hold
    # ------------------------------------------------------------------
    if current_pnl_pct >= _PROFIT_HOLD_PCT:
        return TradeMaintenanceResult(
            ticker=ticker,
            action="hold",
            urgency="none",
            rationale=(
                f"Position at {current_pnl_pct:.0%} profit in stable "
                f"{_regime_name(regime_id)}. Structure is working — hold to target."
            ),
            trade_spec=None,
            regime_context=regime_context,
            account_size_note=account_size_note,
        )

    # ------------------------------------------------------------------
    # Default — early in trade, modest P&L, regime stable → monitor
    # ------------------------------------------------------------------
    return TradeMaintenanceResult(
        ticker=ticker,
        action="hold",
        urgency="monitor",
        rationale=(
            f"Position at {current_pnl_pct:.0%} P&L with {dte_remaining} DTE in "
            f"stable {_regime_name(regime_id)}. No action needed — continue monitoring."
        ),
        trade_spec=None,
        regime_context=regime_context,
        account_size_note=account_size_note,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _regime_name(regime_id: int) -> str:
    return {
        1: "R1 (low-vol MR)",
        2: "R2 (high-vol MR)",
        3: "R3 (low-vol trending)",
        4: "R4 (high-vol trending)",
    }.get(regime_id, f"R{regime_id}")


def _regime_context(regime_id: int, entry_regime_id: int | None) -> str:
    name = _regime_name(regime_id)
    if entry_regime_id is None or entry_regime_id == regime_id:
        return f"Current: {name} (regime unchanged)"
    return f"Current: {name} — shifted from {_regime_name(entry_regime_id)}"


def _build_account_note(account_nlv: float) -> str:
    if account_nlv < SMALL_ACCOUNT_THRESHOLD:
        return (
            f"Small account (${account_nlv:,.0f}) — trade adjustment is the primary "
            f"hedge. Separate hedging instruments are impractical at this account size."
        )
    return (
        f"Account (${account_nlv:,.0f}) — trade adjustment preferred for option "
        f"positions; structural hedges available if needed."
    )
