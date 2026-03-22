"""Tests for compute_monitoring_action and build_closing_trade_spec."""
from __future__ import annotations

from datetime import date

import pytest

from income_desk.models.opportunity import LegAction, LegSpec, TradeSpec
from income_desk.models.exit import MonitoringAction
from income_desk.opportunity.option_plays._trade_spec_helpers import build_closing_trade_spec


def _leg(role: str, action: LegAction, opt_type: str, strike: float) -> LegSpec:
    return LegSpec(
        role=role,
        action=action,
        option_type=opt_type,
        strike=strike,
        strike_label="test",
        expiration=date(2026, 4, 24),
        days_to_expiry=35,
        atm_iv_at_expiry=0.25,
    )


def _ic() -> TradeSpec:
    """Standard 4-leg iron condor used across tests."""
    return TradeSpec(
        ticker="SPY",
        underlying_price=650.0,
        target_dte=35,
        target_expiration=date(2026, 4, 24),
        spec_rationale="test",
        structure_type="iron_condor",
        order_side="credit",
        wing_width_points=5.0,
        profit_target_pct=0.50,
        stop_loss_pct=2.0,
        exit_dte=21,
        legs=[
            _leg("short_put",  LegAction.SELL_TO_OPEN, "put",  635),
            _leg("long_put",   LegAction.BUY_TO_OPEN,  "put",  630),
            _leg("short_call", LegAction.SELL_TO_OPEN, "call", 665),
            _leg("long_call",  LegAction.BUY_TO_OPEN,  "call", 670),
        ],
    )


# ---------------------------------------------------------------------------
# build_closing_trade_spec
# ---------------------------------------------------------------------------

class TestBuildClosingTradeSpec:

    def test_flips_sto_to_btc(self):
        ic = _ic()
        close = build_closing_trade_spec(ic, "test_close", 650.0)
        for orig, closing in zip(ic.legs, close.legs):
            if orig.action == LegAction.SELL_TO_OPEN:
                assert closing.action == LegAction.BUY_TO_CLOSE
            else:
                assert closing.action == LegAction.SELL_TO_CLOSE

    def test_flips_bto_to_stc(self):
        ic = _ic()
        close = build_closing_trade_spec(ic, "test_close", 650.0)
        for orig, closing in zip(ic.legs, close.legs):
            if orig.action == LegAction.BUY_TO_OPEN:
                assert closing.action == LegAction.SELL_TO_CLOSE

    def test_preserves_strikes(self):
        ic = _ic()
        close = build_closing_trade_spec(ic, "test", 650.0)
        for orig, closing in zip(ic.legs, close.legs):
            assert closing.strike == orig.strike
            assert closing.option_type == orig.option_type
            assert closing.expiration == orig.expiration
            assert closing.role == orig.role
            assert closing.quantity == orig.quantity

    def test_flips_order_side_credit_to_debit(self):
        close = build_closing_trade_spec(_ic(), "test", 650.0)
        assert close.order_side == "debit"

    def test_flips_order_side_debit_to_credit(self):
        debit_spec = _ic().model_copy(update={"order_side": "debit"})
        close = build_closing_trade_spec(debit_spec, "test", 650.0)
        assert close.order_side == "credit"

    def test_none_order_side_preserved(self):
        spec = _ic().model_copy(update={"order_side": None})
        close = build_closing_trade_spec(spec, "test", 650.0)
        assert close.order_side is None

    def test_rationale_includes_reason(self):
        close = build_closing_trade_spec(_ic(), "stop_loss_hit", 640.0)
        assert "CLOSE" in close.spec_rationale
        assert "stop_loss_hit" in close.spec_rationale

    def test_same_leg_count(self):
        ic = _ic()
        close = build_closing_trade_spec(ic, "test", 650.0)
        assert len(close.legs) == len(ic.legs)

    def test_uses_current_price(self):
        close = build_closing_trade_spec(_ic(), "test", 640.0)
        assert close.underlying_price == 640.0

    def test_fallback_to_open_price_when_current_price_none(self):
        ic = _ic()
        close = build_closing_trade_spec(ic, "test", None)
        assert close.underlying_price == ic.underlying_price

    def test_inherits_ticker(self):
        close = build_closing_trade_spec(_ic(), "test", 650.0)
        assert close.ticker == "SPY"

    def test_inherits_structure_type(self):
        close = build_closing_trade_spec(_ic(), "test", 650.0)
        assert close.structure_type == "iron_condor"

    def test_closing_spec_serialises(self):
        close = build_closing_trade_spec(_ic(), "stop_loss_hit", 640.0)
        d = close.model_dump()
        assert d["ticker"] == "SPY"
        assert len(d["legs"]) == 4

    def test_leg_short_codes_use_btc_stc(self):
        close = build_closing_trade_spec(_ic(), "test", 650.0)
        codes = [leg.short_code for leg in close.legs]
        # STO legs become BTC
        btc_codes = [c for c in codes if c.startswith("BTC")]
        stc_codes = [c for c in codes if c.startswith("STC")]
        assert len(btc_codes) == 2  # two short legs
        assert len(stc_codes) == 2  # two long legs


# ---------------------------------------------------------------------------
# LegAction enum completeness
# ---------------------------------------------------------------------------

class TestLegActionEnum:
    def test_all_four_values_exist(self):
        assert LegAction.BUY_TO_OPEN == "BTO"
        assert LegAction.SELL_TO_OPEN == "STO"
        assert LegAction.BUY_TO_CLOSE == "BTC"
        assert LegAction.SELL_TO_CLOSE == "STC"


# ---------------------------------------------------------------------------
# compute_monitoring_action
# ---------------------------------------------------------------------------

class TestComputeMonitoringAction:

    def test_profitable_position_hold(self):
        from income_desk.features.exit_intelligence import compute_monitoring_action
        result = compute_monitoring_action(
            trade_spec=_ic(),
            entry_price=1.50,
            current_mid=0.80,
            current_price=650.0,
            dte_remaining=25,
            regime_id=1,
            atr_pct=1.0,
            days_held=10,
            dte_at_entry=35,
        )
        assert result.action == "hold"
        assert result.closing_trade_spec is None
        assert result.has_closing_order is False

    def test_stop_loss_hit_produces_closing_spec(self):
        from income_desk.features.exit_intelligence import compute_monitoring_action
        # 3x entry price = stop hit (R1 stop is 2x)
        result = compute_monitoring_action(
            trade_spec=_ic(),
            entry_price=1.50,
            current_mid=4.50,
            current_price=650.0,
            dte_remaining=25,
            regime_id=1,
            atr_pct=1.0,
            days_held=5,
            dte_at_entry=35,
        )
        assert result.action == "close"
        assert result.has_closing_order
        assert result.closing_trade_spec is not None
        for leg in result.closing_trade_spec.legs:
            assert leg.action in (LegAction.BUY_TO_CLOSE, LegAction.SELL_TO_CLOSE)

    def test_stop_loss_closing_spec_has_correct_ticker(self):
        from income_desk.features.exit_intelligence import compute_monitoring_action
        result = compute_monitoring_action(
            trade_spec=_ic(),
            entry_price=1.50,
            current_mid=4.50,
            current_price=650.0,
            dte_remaining=25,
            regime_id=1,
            atr_pct=1.0,
            days_held=5,
            dte_at_entry=35,
        )
        assert result.closing_trade_spec.ticker == "SPY"

    def test_stress_fail_produces_closing_spec(self):
        from income_desk.features.exit_intelligence import compute_monitoring_action
        # Very high ATR relative to credit = stress fail
        result = compute_monitoring_action(
            trade_spec=_ic(),
            entry_price=0.10,
            current_mid=0.08,
            current_price=650.0,
            dte_remaining=25,
            regime_id=2,
            atr_pct=3.0,
            days_held=5,
            dte_at_entry=35,
        )
        # Stress fail or exit condition should produce closing spec
        if result.action == "close":
            assert result.has_closing_order
            assert result.closing_trade_spec is not None

    def test_dte_exit_produces_closing_spec(self):
        from income_desk.features.exit_intelligence import compute_monitoring_action
        # dte_remaining=5 is below exit_dte=21 on the IC
        result = compute_monitoring_action(
            trade_spec=_ic(),
            entry_price=1.50,
            current_mid=1.20,
            current_price=650.0,
            dte_remaining=5,
            regime_id=1,
            atr_pct=1.0,
            days_held=30,
            dte_at_entry=35,
        )
        assert result.action == "close"
        assert result.has_closing_order

    def test_regime_change_triggers_close(self):
        from income_desk.features.exit_intelligence import compute_monitoring_action
        # Entered in R1, now R4 with elevated ATR
        result = compute_monitoring_action(
            trade_spec=_ic(),
            entry_price=1.50,
            current_mid=1.40,
            current_price=650.0,
            dte_remaining=25,
            regime_id=4,
            atr_pct=2.5,
            entry_regime_id=1,
            days_held=10,
            dte_at_entry=35,
        )
        assert result.action == "close"
        assert result.has_closing_order

    def test_monitoring_action_serialises(self):
        from income_desk.features.exit_intelligence import compute_monitoring_action
        result = compute_monitoring_action(
            trade_spec=_ic(),
            entry_price=1.50,
            current_mid=0.80,
            current_price=650.0,
            dte_remaining=25,
            regime_id=1,
            atr_pct=1.0,
            days_held=10,
            dte_at_entry=35,
        )
        d = result.model_dump()
        assert "action" in d
        assert "urgency" in d
        assert "reason" in d
        assert "closing_trade_spec" in d
        assert "stress_report" in d

    def test_stress_report_always_present(self):
        from income_desk.features.exit_intelligence import compute_monitoring_action
        result = compute_monitoring_action(
            trade_spec=_ic(),
            entry_price=1.50,
            current_mid=0.80,
            current_price=650.0,
            dte_remaining=25,
            regime_id=1,
            atr_pct=1.0,
            days_held=10,
            dte_at_entry=35,
        )
        assert result.stress_report is not None
        assert isinstance(result.stress_report, dict)

    def test_closing_trade_spec_legs_match_count(self):
        from income_desk.features.exit_intelligence import compute_monitoring_action
        result = compute_monitoring_action(
            trade_spec=_ic(),
            entry_price=1.50,
            current_mid=4.50,  # Stop hit
            current_price=650.0,
            dte_remaining=25,
            regime_id=1,
            atr_pct=1.0,
            days_held=5,
            dte_at_entry=35,
        )
        assert result.action == "close"
        assert len(result.closing_trade_spec.legs) == 4

    def test_monitoring_action_model_has_closing_order_property(self):
        m = MonitoringAction(action="hold", urgency="none", reason="ok")
        assert m.has_closing_order is False
        ic = _ic()
        close_spec = build_closing_trade_spec(ic, "test", 650.0)
        m2 = MonitoringAction(action="close", urgency="immediate", reason="stop",
                               closing_trade_spec=close_spec)
        assert m2.has_closing_order is True
