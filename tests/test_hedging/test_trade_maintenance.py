"""Tests for recommend_trade_maintenance() — trade-adjustment-as-hedge."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from income_desk.hedging.trade_maintenance import (
    SMALL_ACCOUNT_THRESHOLD,
    recommend_trade_maintenance,
)
from income_desk.models.opportunity import LegAction, LegSpec, TradeSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_leg(action: LegAction, opt_type: str, strike: float, expiry: date) -> LegSpec:
    return LegSpec(
        action=action,
        option_type=opt_type,
        strike=strike,
        expiration=expiry,
        dte=30,
        days_to_expiry=30,
        quantity=1,
        role=f"{'long' if action == LegAction.BUY_TO_OPEN else 'short'}_{opt_type}",
        ticker="SPY",
        strike_label=f"{strike} {opt_type}",
        atm_iv_at_expiry=0.20,
    )


def _ic_spec(ticker: str = "SPY", underlying: float = 580.0) -> TradeSpec:
    """A minimal iron-condor TradeSpec for tests."""
    exp = date.today() + timedelta(days=30)
    return TradeSpec(
        ticker=ticker,
        legs=[
            _make_leg(LegAction.SELL_TO_OPEN, "put", 555.0, exp),
            _make_leg(LegAction.BUY_TO_OPEN, "put", 545.0, exp),
            _make_leg(LegAction.SELL_TO_OPEN, "call", 605.0, exp),
            _make_leg(LegAction.BUY_TO_OPEN, "call", 615.0, exp),
        ],
        underlying_price=underlying,
        target_dte=30,
        target_expiration=exp,
        spec_rationale="test IC",
        structure_type="iron_condor",
        order_side="credit",
    )


# ---------------------------------------------------------------------------
# Hold scenarios
# ---------------------------------------------------------------------------

class TestHoldScenarios:
    def test_profitable_position_hold(self):
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=580.0,
            entry_price=1.50,
            regime_id=1,
            dte_remaining=25,
            current_pnl_pct=0.30,
        )
        assert result.action == "hold"
        assert result.urgency == "none"
        assert "profit" in result.rationale.lower()

    def test_early_trade_small_pnl_monitor(self):
        """Early in trade with negligible P&L — monitor, not urgent."""
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=580.0,
            entry_price=1.50,
            regime_id=1,
            dte_remaining=28,
            current_pnl_pct=0.05,
        )
        assert result.action == "hold"
        assert result.urgency == "monitor"

    def test_regime_changed_profitable_holds_with_monitor(self):
        """Regime changed but position is profitable — hold/monitor (don't force close)."""
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=580.0,
            entry_price=1.50,
            regime_id=3,
            entry_regime_id=1,
            dte_remaining=20,
            current_pnl_pct=0.35,
        )
        assert result.action == "hold"
        assert result.urgency == "monitor"


# ---------------------------------------------------------------------------
# Roll / widen scenarios
# ---------------------------------------------------------------------------

class TestRollWidenScenarios:
    def test_tested_position_mr_regime_rolls(self):
        """Tested in mean-reverting regime → roll."""
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=572.0,
            entry_price=1.50,
            regime_id=1,       # R1 = MR
            dte_remaining=20,
            current_pnl_pct=-0.20,
        )
        assert result.action == "roll"
        assert result.urgency == "soon"

    def test_tested_position_trending_regime_widens(self):
        """Tested in trending regime → widen (don't fight the trend with a roll)."""
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=565.0,
            entry_price=1.50,
            regime_id=3,       # R3 = trending
            dte_remaining=20,
            current_pnl_pct=-0.25,
        )
        assert result.action == "widen"

    def test_tested_r2_also_rolls(self):
        """R2 is still mean-reverting (high-vol MR) → roll."""
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=570.0,
            entry_price=1.50,
            regime_id=2,
            dte_remaining=18,
            current_pnl_pct=-0.18,
        )
        assert result.action == "roll"


# ---------------------------------------------------------------------------
# Convert-to-diagonal scenario
# ---------------------------------------------------------------------------

class TestConvertToDiagonal:
    def test_regime_change_with_loss_converts(self):
        """Regime changed AND losing → convert_to_diagonal."""
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=575.0,
            entry_price=1.50,
            regime_id=3,           # Now trending
            entry_regime_id=1,     # Was MR
            dte_remaining=20,
            current_pnl_pct=-0.20,
        )
        assert result.action == "convert_to_diagonal"
        assert result.urgency == "soon"
        assert "R1" in result.rationale or "R3" in result.rationale

    def test_r4_change_with_loss_converts(self):
        """Regime shifted to R4 (high-vol trending) → convert_to_diagonal."""
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=560.0,
            entry_price=1.50,
            regime_id=4,
            entry_regime_id=1,
            dte_remaining=15,
            current_pnl_pct=-0.30,
        )
        assert result.action == "convert_to_diagonal"


# ---------------------------------------------------------------------------
# Close scenarios
# ---------------------------------------------------------------------------

class TestCloseScenarios:
    def test_near_max_loss_close_immediately(self):
        """Position at 60%+ loss → close immediately."""
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=545.0,  # Below put short strike
            entry_price=1.50,
            regime_id=2,
            dte_remaining=15,
            current_pnl_pct=-0.65,
        )
        assert result.action == "close"
        assert result.urgency == "immediate"

    def test_expiring_with_loss_close(self):
        """≤5 DTE with significant loss → close."""
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=570.0,
            entry_price=1.50,
            regime_id=1,
            dte_remaining=4,
            current_pnl_pct=-0.20,
        )
        assert result.action == "close"
        assert result.urgency == "immediate"

    def test_urgent_dte_with_loss_close(self):
        """≤10 DTE with tested position → close (not enough time to roll)."""
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=570.0,
            entry_price=1.50,
            regime_id=1,
            dte_remaining=8,
            current_pnl_pct=-0.20,
        )
        assert result.action == "close"
        assert result.urgency == "soon"


# ---------------------------------------------------------------------------
# Account size note
# ---------------------------------------------------------------------------

class TestAccountSizeNote:
    def test_small_account_note_present(self):
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=580.0,
            entry_price=1.50,
            regime_id=1,
            account_nlv=50_000,
        )
        assert "small account" in result.account_size_note.lower()
        assert "50,000" in result.account_size_note

    def test_large_account_note_different(self):
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=580.0,
            entry_price=1.50,
            regime_id=1,
            account_nlv=300_000,
        )
        # Large account note should NOT say "small account"
        assert "small account" not in result.account_size_note.lower()

    def test_boundary_account_exactly_200k(self):
        """At exactly SMALL_ACCOUNT_THRESHOLD — still considered small (< not <=)."""
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=580.0,
            entry_price=1.50,
            regime_id=1,
            account_nlv=SMALL_ACCOUNT_THRESHOLD,
        )
        # Equal to threshold → NOT small (< condition)
        assert "small account" not in result.account_size_note.lower()


# ---------------------------------------------------------------------------
# Regime context
# ---------------------------------------------------------------------------

class TestRegimeContext:
    def test_stable_regime_context(self):
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=580.0,
            entry_price=1.50,
            regime_id=2,
            entry_regime_id=2,
            dte_remaining=20,
        )
        assert "unchanged" in result.regime_context.lower()

    def test_changed_regime_context(self):
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=580.0,
            entry_price=1.50,
            regime_id=3,
            entry_regime_id=1,
            dte_remaining=20,
            current_pnl_pct=0.40,  # Profitable — just monitor
        )
        assert "shifted" in result.regime_context.lower() or "R1" in result.regime_context

    def test_no_entry_regime_context(self):
        """When entry_regime_id is None, context just shows current."""
        result = recommend_trade_maintenance(
            trade_spec=_ic_spec(),
            current_price=580.0,
            entry_price=1.50,
            regime_id=1,
        )
        assert "R1" in result.regime_context
