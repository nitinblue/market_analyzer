"""Tests for assess_assignment_risk() — BEFORE-assignment early warning."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from market_analyzer.features.assignment_handler import assess_assignment_risk
from market_analyzer.models.assignment import AssignmentRisk
from market_analyzer.models.opportunity import LegAction, LegSpec, OrderSide, StructureType, TradeSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ic(
    ticker: str = "SPY",
    short_put: float = 570.0,
    short_call: float = 590.0,
    wing: float = 5.0,
    dte: int = 30,
    price: float = 580.0,
) -> TradeSpec:
    """Build a representative Iron Condor TradeSpec."""
    exp = date.today() + timedelta(days=dte)
    legs = [
        LegSpec(role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
                strike=short_put, strike_label=f"STO {short_put:.0f}P",
                expiration=exp, days_to_expiry=dte, atm_iv_at_expiry=0.0),
        LegSpec(role="long_put", action=LegAction.BUY_TO_OPEN, option_type="put",
                strike=short_put - wing, strike_label=f"BTO {short_put - wing:.0f}P",
                expiration=exp, days_to_expiry=dte, atm_iv_at_expiry=0.0),
        LegSpec(role="short_call", action=LegAction.SELL_TO_OPEN, option_type="call",
                strike=short_call, strike_label=f"STO {short_call:.0f}C",
                expiration=exp, days_to_expiry=dte, atm_iv_at_expiry=0.0),
        LegSpec(role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call",
                strike=short_call + wing, strike_label=f"BTO {short_call + wing:.0f}C",
                expiration=exp, days_to_expiry=dte, atm_iv_at_expiry=0.0),
    ]
    return TradeSpec(
        ticker=ticker,
        legs=legs,
        underlying_price=price,
        target_dte=dte,
        target_expiration=exp,
        wing_width_points=wing,
        structure_type=StructureType.IRON_CONDOR,
        order_side=OrderSide.CREDIT,
        spec_rationale="Test IC",
    )


def _make_single_short_put(
    ticker: str = "SPY",
    strike: float = 570.0,
    dte: int = 30,
    price: float = 580.0,
) -> TradeSpec:
    """Build a single-leg short put TradeSpec."""
    exp = date.today() + timedelta(days=dte)
    legs = [
        LegSpec(role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
                strike=strike, strike_label=f"STO {strike:.0f}P",
                expiration=exp, days_to_expiry=dte, atm_iv_at_expiry=0.0),
    ]
    return TradeSpec(
        ticker=ticker,
        legs=legs,
        underlying_price=price,
        target_dte=dte,
        target_expiration=exp,
        structure_type=StructureType.CREDIT_SPREAD,
        order_side=OrderSide.CREDIT,
        spec_rationale="Test short put",
    )


def _make_single_short_call(
    ticker: str = "SPY",
    strike: float = 590.0,
    dte: int = 30,
    price: float = 580.0,
) -> TradeSpec:
    """Build a single-leg short call TradeSpec."""
    exp = date.today() + timedelta(days=dte)
    legs = [
        LegSpec(role="short_call", action=LegAction.SELL_TO_OPEN, option_type="call",
                strike=strike, strike_label=f"STO {strike:.0f}C",
                expiration=exp, days_to_expiry=dte, atm_iv_at_expiry=0.0),
    ]
    return TradeSpec(
        ticker=ticker,
        legs=legs,
        underlying_price=price,
        target_dte=dte,
        target_expiration=exp,
        structure_type=StructureType.CREDIT_SPREAD,
        order_side=OrderSide.CREDIT,
        spec_rationale="Test short call",
    )


# ---------------------------------------------------------------------------
# OTM — no risk
# ---------------------------------------------------------------------------

class TestOTMNoRisk:
    def test_ic_both_otm_no_risk(self):
        """IC with both short strikes OTM → NONE risk."""
        ts = _make_ic(short_put=570, short_call=590, price=580)
        result = assess_assignment_risk(ts, current_price=580, dte_remaining=30)
        assert result.risk_level == AssignmentRisk.NONE

    def test_short_put_otm_no_risk(self):
        """Short put OTM → NONE."""
        ts = _make_single_short_put(strike=570, price=580)
        result = assess_assignment_risk(ts, current_price=580, dte_remaining=20)
        assert result.risk_level == AssignmentRisk.NONE

    def test_short_call_otm_no_risk(self):
        """Short call OTM → NONE."""
        ts = _make_single_short_call(strike=590, price=580)
        result = assess_assignment_risk(ts, current_price=580, dte_remaining=20)
        assert result.risk_level == AssignmentRisk.NONE

    def test_no_sto_legs_no_risk(self):
        """Trade with no STO legs (debit only) → NONE."""
        exp = date.today() + timedelta(days=30)
        ts = TradeSpec(
            ticker="SPY",
            legs=[LegSpec(role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call",
                          strike=590, strike_label="BTO 590C", expiration=exp, days_to_expiry=30,
                          atm_iv_at_expiry=0.0)],
            underlying_price=580,
            target_dte=30,
            target_expiration=exp,
            structure_type=StructureType.DEBIT_SPREAD,
            order_side=OrderSide.DEBIT,
            spec_rationale="Test debit-only",
        )
        result = assess_assignment_risk(ts, current_price=580, dte_remaining=30)
        assert result.risk_level == AssignmentRisk.NONE

    def test_result_has_ticker(self):
        """Result should carry the ticker symbol."""
        ts = _make_single_short_put(ticker="GLD", strike=180, price=200)
        result = assess_assignment_risk(ts, current_price=200, dte_remaining=10)
        assert result.ticker == "GLD"


# ---------------------------------------------------------------------------
# Slightly ITM — LOW
# ---------------------------------------------------------------------------

class TestSlightlyITMLow:
    def test_slightly_itm_put_american_low_risk(self):
        """Short put 0.5% ITM (580 strike, 577 price) → LOW risk (not deep enough)."""
        # 580 - 577 = 3; itm_pct = 3/577 ≈ 0.52% which is < 1%
        ts = _make_single_short_put(strike=580, price=577)
        result = assess_assignment_risk(ts, current_price=577, dte_remaining=20)
        assert result.risk_level == AssignmentRisk.LOW

    def test_low_risk_urgency_none(self):
        """LOW risk → urgency 'none' (not enough to act)."""
        ts = _make_single_short_put(strike=580, price=577)
        result = assess_assignment_risk(ts, current_price=577, dte_remaining=20)
        assert result.urgency == "none"

    def test_low_risk_action_hold(self):
        """LOW risk → recommended_action 'hold'."""
        ts = _make_single_short_put(strike=580, price=577)
        result = assess_assignment_risk(ts, current_price=577, dte_remaining=20)
        assert result.recommended_action == "hold"

    def test_low_risk_no_response_spec(self):
        """LOW risk → no response TradeSpec needed."""
        ts = _make_single_short_put(strike=580, price=577)
        result = assess_assignment_risk(ts, current_price=577, dte_remaining=20)
        assert result.response_trade_spec is None


# ---------------------------------------------------------------------------
# Moderate risk
# ---------------------------------------------------------------------------

class TestModerateRisk:
    def test_1_5pct_itm_american_moderate(self):
        """Short put 1.5% ITM with 20 DTE → MODERATE."""
        # 580 strike, 580 * 0.985 = ~571 price; itm = 9, itm_pct ≈ 1.57%
        price = 571.0
        strike = 580.0
        ts = _make_single_short_put(strike=strike, price=price)
        result = assess_assignment_risk(ts, current_price=price, dte_remaining=20)
        assert result.risk_level == AssignmentRisk.MODERATE

    def test_moderate_urgency_monitor(self):
        """MODERATE → urgency 'monitor'."""
        price = 571.0
        ts = _make_single_short_put(strike=580, price=price)
        result = assess_assignment_risk(ts, current_price=price, dte_remaining=20)
        assert result.urgency == "monitor"

    def test_moderate_action_monitor(self):
        """MODERATE → recommended_action 'monitor'."""
        price = 571.0
        ts = _make_single_short_put(strike=580, price=price)
        result = assess_assignment_risk(ts, current_price=price, dte_remaining=20)
        assert result.recommended_action == "monitor"


# ---------------------------------------------------------------------------
# HIGH risk (deep ITM or near expiry)
# ---------------------------------------------------------------------------

class TestHighRisk:
    def test_deep_itm_american_high_risk(self):
        """Short put >3% ITM → HIGH (deep ITM)."""
        # 580 strike, price 560 → ITM = 20, itm_pct = 20/560 ≈ 3.57%
        ts = _make_single_short_put(strike=580, price=560)
        result = assess_assignment_risk(ts, current_price=560, dte_remaining=20)
        assert result.risk_level == AssignmentRisk.HIGH

    def test_near_expiry_itm_american_high(self):
        """Short put 1.5% ITM with 4 DTE → HIGH (near expiry + ITM)."""
        # 580 strike, price 571 → itm_pct ≈ 1.57%, 4 DTE
        ts = _make_single_short_put(strike=580, price=571)
        result = assess_assignment_risk(ts, current_price=571, dte_remaining=4)
        assert result.risk_level == AssignmentRisk.HIGH

    def test_high_risk_urgency_prepare(self):
        """HIGH risk with >5 DTE → urgency 'prepare'."""
        ts = _make_single_short_put(strike=580, price=560)
        result = assess_assignment_risk(ts, current_price=560, dte_remaining=20)
        assert result.urgency == "prepare"

    def test_high_risk_dte5_urgency_prepare(self):
        """HIGH risk with 4 DTE → urgency 'prepare', action 'close_itm_leg'."""
        ts = _make_single_short_put(strike=580, price=571)
        result = assess_assignment_risk(ts, current_price=571, dte_remaining=4)
        assert result.urgency == "prepare"
        assert result.recommended_action == "close_itm_leg"

    def test_high_risk_produces_response_spec(self):
        """HIGH risk → response_trade_spec is not None (closing action)."""
        ts = _make_single_short_put(strike=580, price=560)
        result = assess_assignment_risk(ts, current_price=560, dte_remaining=20)
        assert result.response_trade_spec is not None

    def test_high_risk_response_spec_is_btc(self):
        """HIGH risk response spec should be a BUY_TO_CLOSE."""
        ts = _make_single_short_put(strike=580, price=560)
        result = assess_assignment_risk(ts, current_price=560, dte_remaining=20)
        spec = result.response_trade_spec
        assert spec is not None
        assert spec.legs[0].action == LegAction.BUY_TO_CLOSE


# ---------------------------------------------------------------------------
# IMMINENT risk
# ---------------------------------------------------------------------------

class TestImminentRisk:
    def test_1dte_itm_put_imminent(self):
        """Short put ITM with 1 DTE → IMMINENT."""
        ts = _make_single_short_put(strike=580, price=575)
        result = assess_assignment_risk(ts, current_price=575, dte_remaining=1)
        assert result.risk_level == AssignmentRisk.IMMINENT

    def test_2dte_itm_put_imminent(self):
        """Short put 1% ITM with 2 DTE → IMMINENT."""
        # 580 strike, price 574 → itm_pct ≈ 1.05%
        ts = _make_single_short_put(strike=580, price=574)
        result = assess_assignment_risk(ts, current_price=574, dte_remaining=2)
        assert result.risk_level == AssignmentRisk.IMMINENT

    def test_imminent_urgency_act_now(self):
        """IMMINENT → urgency 'act_now'."""
        ts = _make_single_short_put(strike=580, price=575)
        result = assess_assignment_risk(ts, current_price=575, dte_remaining=1)
        assert result.urgency == "act_now"

    def test_imminent_action_close(self):
        """IMMINENT → recommended_action 'close_itm_leg'."""
        ts = _make_single_short_put(strike=580, price=575)
        result = assess_assignment_risk(ts, current_price=575, dte_remaining=1)
        assert result.recommended_action == "close_itm_leg"

    def test_imminent_produces_response_spec(self):
        """IMMINENT → response_trade_spec is BTC."""
        ts = _make_single_short_put(strike=580, price=575)
        result = assess_assignment_risk(ts, current_price=575, dte_remaining=1)
        assert result.response_trade_spec is not None

    def test_0dte_itm_imminent(self):
        """Short put ITM with 0 DTE → IMMINENT (assign tonight)."""
        ts = _make_single_short_put(strike=580, price=575)
        result = assess_assignment_risk(ts, current_price=575, dte_remaining=0)
        assert result.risk_level == AssignmentRisk.IMMINENT


# ---------------------------------------------------------------------------
# European style — no early assignment
# ---------------------------------------------------------------------------

class TestEuropeanStyle:
    def test_european_itm_not_at_expiry_no_risk(self):
        """European + ITM + 10 DTE → NONE (no early assignment)."""
        ts = _make_single_short_put(strike=580, price=560)
        result = assess_assignment_risk(
            ts, current_price=560, dte_remaining=10, exercise_style="european",
        )
        assert result.risk_level == AssignmentRisk.NONE

    def test_european_has_note(self):
        """European style result should include european_note."""
        ts = _make_single_short_put(strike=580, price=560)
        result = assess_assignment_risk(
            ts, current_price=560, dte_remaining=10, exercise_style="european",
        )
        assert result.european_note is not None
        assert "European" in result.european_note

    def test_european_expiry_day_itm_high(self):
        """European + 0 DTE + 1% ITM → HIGH (expiry-day assignment risk)."""
        ts = _make_single_short_put(strike=580, price=574)
        result = assess_assignment_risk(
            ts, current_price=574, dte_remaining=0, exercise_style="european",
        )
        assert result.risk_level == AssignmentRisk.HIGH

    def test_european_1dte_itm_still_none(self):
        """European + 1 DTE + ITM → NONE (1 day buffer, not expiry)."""
        ts = _make_single_short_put(strike=580, price=560)
        result = assess_assignment_risk(
            ts, current_price=560, dte_remaining=1, exercise_style="european",
        )
        assert result.risk_level == AssignmentRisk.NONE

    def test_american_default_style(self):
        """Default exercise_style is 'american'."""
        ts = _make_single_short_put(strike=580, price=575)
        result = assess_assignment_risk(ts, current_price=575, dte_remaining=1)
        assert result.exercise_style == "american"


# ---------------------------------------------------------------------------
# Dividend early assignment risk (calls)
# ---------------------------------------------------------------------------

class TestDividendCallRisk:
    def test_itm_call_dividend_pending_high_risk(self):
        """ITM call + dividend pending → HIGH (early assignment risk)."""
        ts = _make_single_short_call(strike=575, price=580)
        result = assess_assignment_risk(
            ts, current_price=580, dte_remaining=20,
            is_dividend_pending=True, ex_dividend_days=3,
        )
        assert result.risk_level == AssignmentRisk.HIGH

    def test_dividend_reason_mentions_ex_dividend(self):
        """Dividend risk reason should mention ex-dividend."""
        ts = _make_single_short_call(strike=575, price=580)
        result = assess_assignment_risk(
            ts, current_price=580, dte_remaining=20,
            is_dividend_pending=True, ex_dividend_days=3,
        )
        reasons_text = " ".join(result.reasons)
        assert "dividend" in reasons_text.lower() or "ex-dividend" in reasons_text.lower()

    def test_otm_call_dividend_no_risk(self):
        """OTM call + dividend → NONE (OTM overrides dividend check)."""
        ts = _make_single_short_call(strike=590, price=580)
        result = assess_assignment_risk(
            ts, current_price=580, dte_remaining=20,
            is_dividend_pending=True, ex_dividend_days=3,
        )
        assert result.risk_level == AssignmentRisk.NONE

    def test_put_dividend_no_early_assignment_risk(self):
        """Short put + dividend pending → dividend does NOT affect put assignment risk."""
        # Put is ITM but only slightly (LOW risk territory) — dividend doesn't change it
        ts = _make_single_short_put(strike=580, price=577)
        result = assess_assignment_risk(
            ts, current_price=577, dte_remaining=20,
            is_dividend_pending=True, ex_dividend_days=3,
        )
        # Puts are not affected by dividend early assignment
        assert result.risk_level in (AssignmentRisk.NONE, AssignmentRisk.LOW)


# ---------------------------------------------------------------------------
# IC — multiple legs
# ---------------------------------------------------------------------------

class TestICMultipleLegs:
    def test_ic_one_side_itm_reports_worst(self):
        """IC with put side ITM should report the worst-case risk."""
        # short_put=580, price=560 → put is 3.5% ITM
        ts = _make_ic(short_put=580, short_call=600, price=560)
        result = assess_assignment_risk(ts, current_price=560, dte_remaining=20)
        assert result.risk_level == AssignmentRisk.HIGH

    def test_ic_at_risk_legs_populated(self):
        """at_risk_legs list should contain all STO legs (even OTM ones)."""
        ts = _make_ic(short_put=570, short_call=590, price=580)
        result = assess_assignment_risk(ts, current_price=580, dte_remaining=30)
        # Should have 2 STO legs: short_put and short_call
        assert len(result.at_risk_legs) == 2

    def test_ic_at_risk_legs_include_itm_pct(self):
        """Each at_risk leg should have itm_pct field."""
        ts = _make_ic(short_put=580, short_call=600, price=560)
        result = assess_assignment_risk(ts, current_price=560, dte_remaining=20)
        for leg in result.at_risk_legs:
            assert "itm_pct" in leg
            assert "itm_amount" in leg

    def test_both_sides_otm_returns_otm_legs(self):
        """OTM IC returns 2 legs in at_risk_legs but both with NONE risk."""
        ts = _make_ic(short_put=560, short_call=600, price=580)
        result = assess_assignment_risk(ts, current_price=580, dte_remaining=30)
        assert result.risk_level == AssignmentRisk.NONE
        for leg in result.at_risk_legs:
            assert leg["risk_level"] == AssignmentRisk.NONE


# ---------------------------------------------------------------------------
# Result structure validation
# ---------------------------------------------------------------------------

class TestResultStructure:
    def test_result_has_exercise_style(self):
        ts = _make_single_short_put(strike=570, price=580)
        result = assess_assignment_risk(ts, current_price=580, dte_remaining=20)
        assert result.exercise_style in ("american", "european")

    def test_result_has_reasons(self):
        ts = _make_single_short_put(strike=570, price=580)
        result = assess_assignment_risk(ts, current_price=580, dte_remaining=20)
        assert isinstance(result.reasons, list)
        assert len(result.reasons) > 0

    def test_high_risk_response_spec_ticker_matches(self):
        """Response TradeSpec ticker should match the original trade ticker."""
        ts = _make_single_short_put(ticker="GLD", strike=200, price=190)
        result = assess_assignment_risk(ts, current_price=190, dte_remaining=20)
        if result.response_trade_spec:
            assert result.response_trade_spec.ticker == "GLD"
