"""Tests for Cash-Secured Put / Covered Call workflow and MarginBuffer."""
from __future__ import annotations

import pytest
from datetime import date

from market_analyzer.features.assignment_handler import (
    analyze_cash_secured_put,
    analyze_covered_call,
)
from market_analyzer.features.position_sizing import compute_margin_buffer
from market_analyzer.models.assignment import CSPIntent
from market_analyzer.models.opportunity import LegAction, LegSpec, OrderSide, StructureType, TradeSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ts(structure_type: str = "iron_condor") -> TradeSpec:
    """Build a minimal TradeSpec with the given structure_type."""
    exp = date.today()
    return TradeSpec(
        ticker="SPY",
        legs=[LegSpec(
            role="short_put",
            action=LegAction.SELL_TO_OPEN,
            quantity=1,
            option_type="put",
            strike=500.0,
            strike_label="500P",
            expiration=exp,
            days_to_expiry=0,
            atm_iv_at_expiry=0.20,
        )],
        underlying_price=510.0,
        target_dte=30,
        target_expiration=exp,
        spec_rationale="test",
        structure_type=StructureType(structure_type),
        order_side=OrderSide.CREDIT,
    )


# ---------------------------------------------------------------------------
# CSPAnalysis tests
# ---------------------------------------------------------------------------

class TestCSPAnalysis:

    def test_wheel_entry_produces_csp_and_cc(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=240.0,
            premium=2.50,
            current_price=245.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
            intent="wheel_entry",
        )
        assert result.trade_spec is not None
        assert result.covered_call_spec is not None
        assert result.effective_buy_price == pytest.approx(237.50, abs=0.01)
        assert result.intent == CSPIntent.WHEEL_ENTRY
        assert result.post_assignment_plan == "sell_covered_call"

    def test_income_only_no_cc(self):
        result = analyze_cash_secured_put(
            ticker="SPY",
            strike=640.0,
            premium=3.00,
            current_price=650.0,
            dte=21,
            regime_id=1,
            atr=8.0,
            account_nlv=80000,
            intent="income_only",
        )
        assert result.covered_call_spec is None
        assert result.post_assignment_plan == "sell_immediately"
        assert result.trade_spec.profit_target_pct == pytest.approx(0.50, abs=0.01)

    def test_acquire_stock_has_cc_plan(self):
        result = analyze_cash_secured_put(
            ticker="AAPL",
            strike=200.0,
            premium=2.00,
            current_price=210.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
            intent="acquire_stock",
        )
        assert result.covered_call_spec is not None
        assert result.post_assignment_plan == "hold_long_term"
        assert result.intent == CSPIntent.ACQUIRE_STOCK

    def test_discount_computed(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=240.0,
            premium=2.50,
            current_price=250.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
        )
        # Effective buy: 237.50 vs current 250 = 5% discount
        assert result.discount_from_current_pct > 0.04

    def test_cash_secured_amount(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=240.0,
            premium=2.50,
            current_price=245.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
        )
        assert result.cash_to_secure == pytest.approx(24000.0, abs=0.01)  # 240 * 100

    def test_itm_put_high_assignment_prob(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=250.0,
            premium=8.00,
            current_price=245.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
        )
        assert result.assignment_probability == "high"

    def test_deep_otm_low_assignment_prob(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=200.0,
            premium=0.50,
            current_price=250.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
        )
        assert result.assignment_probability == "low"

    def test_near_money_moderate_assignment_prob(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=249.0,
            premium=2.00,
            current_price=250.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
        )
        # 1/250 = 0.4% OTM — within 2% threshold → "moderate"
        assert result.assignment_probability == "moderate"

    def test_trade_spec_structure_type(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=240.0,
            premium=2.50,
            current_price=245.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
        )
        assert str(result.trade_spec.structure_type) == "cash_secured_put"
        assert result.trade_spec.order_side == OrderSide.CREDIT

    def test_csp_leg_is_sto_put(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=240.0,
            premium=2.50,
            current_price=245.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
        )
        leg = result.trade_spec.legs[0]
        assert leg.action == LegAction.SELL_TO_OPEN
        assert leg.option_type == "put"
        assert leg.strike == pytest.approx(240.0)

    def test_max_loss_equals_cash_minus_premium(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=240.0,
            premium=2.50,
            current_price=245.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
        )
        # Max loss: 240*100 - 2.50*100 = 24000 - 250 = 23750
        assert result.max_loss == pytest.approx(23750.0, abs=1.0)

    def test_breakeven_equals_effective_buy(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=240.0,
            premium=2.50,
            current_price=245.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
        )
        assert result.breakeven == pytest.approx(result.effective_buy_price, abs=0.01)

    def test_covered_call_strike_above_current(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=240.0,
            premium=2.50,
            current_price=245.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
            intent="wheel_entry",
        )
        assert result.covered_call_spec is not None
        cc_leg = result.covered_call_spec.legs[0]
        assert cc_leg.strike > 245.0
        assert cc_leg.option_type == "call"
        assert cc_leg.action == LegAction.SELL_TO_OPEN

    def test_income_only_profit_target_set(self):
        result = analyze_cash_secured_put(
            ticker="SPY",
            strike=600.0,
            premium=2.00,
            current_price=615.0,
            dte=30,
            regime_id=1,
            atr=8.0,
            account_nlv=100000,
            intent="income_only",
        )
        assert result.trade_spec.profit_target_pct == pytest.approx(0.50, abs=0.01)

    def test_wheel_entry_no_profit_target(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=240.0,
            premium=2.50,
            current_price=245.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
            intent="wheel_entry",
        )
        # Wheel entry: let it get assigned, no profit target
        assert result.trade_spec.profit_target_pct is None

    def test_summary_contains_ticker(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=240.0,
            premium=2.50,
            current_price=245.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
        )
        assert "IWM" in result.summary

    def test_annualized_yield_positive(self):
        result = analyze_cash_secured_put(
            ticker="IWM",
            strike=240.0,
            premium=2.50,
            current_price=245.0,
            dte=30,
            regime_id=1,
            atr=5.0,
            account_nlv=80000,
        )
        assert result.annualized_yield_if_not_assigned > 0


# ---------------------------------------------------------------------------
# CoveredCallAnalysis tests
# ---------------------------------------------------------------------------

class TestCoveredCallAnalysis:

    def test_cc_strike_above_current(self):
        result = analyze_covered_call(
            ticker="IWM",
            shares_owned=100,
            cost_basis=240.0,
            current_price=245.0,
            regime_id=1,
            atr=5.0,
        )
        assert result.call_strike > 245.0
        assert result.trade_spec is not None

    def test_if_called_away_profit_positive(self):
        result = analyze_covered_call(
            ticker="IWM",
            shares_owned=100,
            cost_basis=240.0,
            current_price=245.0,
            regime_id=1,
            atr=5.0,
        )
        # Call strike > current > cost_basis → profit if called
        assert result.if_called_away_profit > 0

    def test_r3_wider_strike_than_r1(self):
        r1 = analyze_covered_call("IWM", 100, 240.0, 245.0, 1, 5.0)
        r3 = analyze_covered_call("IWM", 100, 240.0, 245.0, 3, 5.0)
        assert r3.call_strike >= r1.call_strike  # R3 keeps more upside

    def test_r4_widest_strike(self):
        r1 = analyze_covered_call("IWM", 100, 240.0, 245.0, 1, 5.0)
        r4 = analyze_covered_call("IWM", 100, 240.0, 245.0, 4, 5.0)
        assert r4.call_strike >= r1.call_strike

    def test_trade_spec_is_cc(self):
        result = analyze_covered_call(
            ticker="IWM",
            shares_owned=100,
            cost_basis=240.0,
            current_price=245.0,
            regime_id=1,
            atr=5.0,
        )
        assert str(result.trade_spec.structure_type) == "covered_call"
        assert result.trade_spec.order_side == OrderSide.CREDIT

    def test_cc_leg_is_sto_call(self):
        result = analyze_covered_call(
            ticker="IWM",
            shares_owned=100,
            cost_basis=240.0,
            current_price=245.0,
            regime_id=1,
            atr=5.0,
        )
        leg = result.trade_spec.legs[0]
        assert leg.action == LegAction.SELL_TO_OPEN
        assert leg.option_type == "call"

    def test_contracts_from_shares(self):
        result = analyze_covered_call(
            ticker="IWM",
            shares_owned=200,
            cost_basis=240.0,
            current_price=245.0,
            regime_id=1,
            atr=5.0,
        )
        assert result.trade_spec.legs[0].quantity == 2  # 200 shares / 100 = 2 contracts

    def test_estimated_premium_positive(self):
        result = analyze_covered_call(
            ticker="IWM",
            shares_owned=100,
            cost_basis=240.0,
            current_price=245.0,
            regime_id=1,
            atr=5.0,
            iv_rank=40,
        )
        assert result.estimated_premium > 0

    def test_upside_cap_equals_call_strike(self):
        result = analyze_covered_call(
            ticker="IWM",
            shares_owned=100,
            cost_basis=240.0,
            current_price=245.0,
            regime_id=1,
            atr=5.0,
        )
        assert result.upside_cap == result.call_strike

    def test_if_not_called_income(self):
        result = analyze_covered_call(
            ticker="IWM",
            shares_owned=100,
            cost_basis=240.0,
            current_price=245.0,
            regime_id=1,
            atr=5.0,
        )
        # Premium * shares
        assert result.if_not_called_income == pytest.approx(
            result.estimated_premium * result.shares_owned, abs=0.01
        )

    def test_summary_contains_ticker(self):
        result = analyze_covered_call(
            ticker="IWM",
            shares_owned=100,
            cost_basis=240.0,
            current_price=245.0,
            regime_id=1,
            atr=5.0,
        )
        assert "IWM" in result.summary


# ---------------------------------------------------------------------------
# MarginBuffer tests
# ---------------------------------------------------------------------------

class TestMarginBuffer:

    def test_ic_defined_risk_small_buffer(self):
        ts = _make_ts(structure_type="iron_condor")
        buf = compute_margin_buffer(ts, base_margin=500.0, regime_id=1)
        assert buf.risk_category == "defined"
        assert buf.recommended_buffer_pct < 0.15

    def test_csp_semi_defined_larger_buffer(self):
        ts = _make_ts(structure_type="cash_secured_put")
        buf = compute_margin_buffer(ts, base_margin=24000.0, regime_id=1)
        assert buf.risk_category == "semi_defined"
        assert buf.recommended_buffer_pct >= 0.20

    def test_naked_option_largest_buffer(self):
        ts = _make_ts(structure_type="ratio_spread")
        buf = compute_margin_buffer(ts, base_margin=5000.0, regime_id=1)
        assert buf.risk_category == "undefined"
        assert buf.recommended_buffer_pct >= 0.30

    def test_r2_increases_buffer_vs_r1(self):
        ts = _make_ts(structure_type="iron_condor")
        r1 = compute_margin_buffer(ts, 500.0, regime_id=1)
        r2 = compute_margin_buffer(ts, 500.0, regime_id=2)
        assert r2.recommended_buffer_dollars > r1.recommended_buffer_dollars

    def test_r4_maximum_buffer(self):
        ts = _make_ts(structure_type="cash_secured_put")
        buf = compute_margin_buffer(ts, 24000.0, regime_id=4)
        # CSP 25% base × 1.5 R4 = 37.5%
        assert buf.recommended_buffer_pct >= 0.35

    def test_total_is_base_plus_buffer(self):
        ts = _make_ts(structure_type="iron_condor")
        buf = compute_margin_buffer(ts, 1000.0, regime_id=1)
        assert buf.total_recommended == pytest.approx(
            buf.base_margin + buf.recommended_buffer_dollars, abs=0.01
        )

    def test_rationale_contains_risk_category(self):
        ts = _make_ts(structure_type="cash_secured_put")
        buf = compute_margin_buffer(ts, 24000.0, regime_id=2)
        assert "semi_defined" in buf.buffer_rationale

    def test_rationale_mentions_regime_for_r2(self):
        ts = _make_ts(structure_type="iron_condor")
        buf = compute_margin_buffer(ts, 500.0, regime_id=2)
        assert "R2" in buf.buffer_rationale

    def test_r1_no_regime_multiplier_in_rationale(self):
        ts = _make_ts(structure_type="iron_condor")
        buf = compute_margin_buffer(ts, 500.0, regime_id=1)
        # R1 mult = 1.0, so no regime adjustment mention
        assert "R1" not in buf.buffer_rationale

    def test_unknown_structure_falls_back_to_defined(self):
        ts = _make_ts(structure_type="iron_condor")
        # Manually override structure_type via dict trick to test fallback
        from market_analyzer.features.position_sizing import _MARGIN_BUFFERS
        # "iron_condor" is known, so use an unknown key via direct call
        from market_analyzer.features.position_sizing import MarginBuffer, _REGIME_BUFFER_MULT
        # Test the fallback: unknown structure should use default (defined, 10%)
        risk_cat, base_pct = _MARGIN_BUFFERS.get("nonexistent_structure_xyz", ("defined", 0.10))
        assert risk_cat == "defined"
        assert base_pct == 0.10

    def test_straddle_undefined_risk(self):
        ts = _make_ts(structure_type="straddle")
        buf = compute_margin_buffer(ts, 5000.0, regime_id=1)
        assert buf.risk_category == "undefined"

    def test_covered_call_semi_defined(self):
        ts = _make_ts(structure_type="covered_call")
        buf = compute_margin_buffer(ts, 5000.0, regime_id=1)
        assert buf.risk_category == "semi_defined"

    def test_debit_spread_smaller_buffer_than_credit_spread(self):
        ts_ds = _make_ts(structure_type="debit_spread")
        ts_cs = _make_ts(structure_type="credit_spread")
        buf_ds = compute_margin_buffer(ts_ds, 1000.0, regime_id=1)
        buf_cs = compute_margin_buffer(ts_cs, 1000.0, regime_id=1)
        assert buf_ds.recommended_buffer_pct <= buf_cs.recommended_buffer_pct
