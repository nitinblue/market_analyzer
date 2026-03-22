"""Tests for assignment/exercise event handling."""
from __future__ import annotations

import pytest

from income_desk.features.assignment_handler import handle_assignment
from income_desk.models.assignment import AssignmentAction, AssignmentType


class TestPutAssignment:
    """PUT_ASSIGNED: short put exercised → you bought 100 shares per contract."""

    def test_large_position_sells_immediately(self):
        """100 shares of SPY at $650 = $65K on $50K account → SELL_IMMEDIATELY."""
        result = handle_assignment(
            ticker="SPY",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=650.0,
            contracts=1,
            current_price=640.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=8.0,
            atr_pct=1.2,
            account_nlv=50000,
            available_bp=30000,
        )
        assert result.recommended_action == AssignmentAction.SELL_IMMEDIATELY
        assert result.response_trade_spec is not None
        assert result.urgency == "immediate"
        assert result.capital_pct_of_nlv > 0.50

    def test_large_position_sell_spec_has_shares(self):
        """Sell TradeSpec should have correct share quantity."""
        result = handle_assignment(
            ticker="SPY",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=650.0,
            contracts=1,
            current_price=640.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=8.0,
            atr_pct=1.2,
            account_nlv=50000,
            available_bp=30000,
        )
        leg = result.response_trade_spec.legs[0]
        assert leg.quantity == 100
        assert leg.option_type == "equity"
        assert result.response_trade_spec.structure_type == "equity_sell"

    def test_manageable_r1_etf_wheels(self):
        """100 shares of IWM at $240 = $24K on $80K account → HOLD_AND_WHEEL."""
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=240.0,
            contracts=1,
            current_price=238.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=5.0,
            atr_pct=2.0,
            account_nlv=80000,
            available_bp=50000,
            is_etf=True,
            iv_rank=45.0,
        )
        assert result.recommended_action == AssignmentAction.HOLD_AND_WHEEL
        assert result.wheel_trade_spec is not None
        # Covered call should be above current price
        call_leg = result.wheel_trade_spec.legs[0]
        assert call_leg.option_type == "call"
        assert call_leg.strike > 238.0

    def test_r1_etf_wheel_spec_structure(self):
        """Wheel TradeSpec should be a covered_call structure on the credit side."""
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=240.0,
            contracts=1,
            current_price=238.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=5.0,
            atr_pct=2.0,
            account_nlv=80000,
            available_bp=50000,
            is_etf=True,
            iv_rank=45.0,
        )
        wts = result.wheel_trade_spec
        assert wts is not None
        assert wts.structure_type == "covered_call"
        assert wts.order_side == "credit"
        assert wts.profit_target_pct == pytest.approx(0.50)
        assert wts.exit_dte == 7

    def test_r2_etf_wheels(self):
        """R2 mean-reverting also supports wheel on ETF."""
        result = handle_assignment(
            ticker="QQQ",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=480.0,
            contracts=1,
            current_price=475.0,
            regime_id=2,
            regime_confidence=0.80,
            atr=12.0,
            atr_pct=2.5,
            account_nlv=200000,
            available_bp=120000,
            is_etf=True,
            iv_rank=55.0,
        )
        assert result.recommended_action == AssignmentAction.HOLD_AND_WHEEL
        assert result.wheel_trade_spec is not None

    def test_r4_always_sells(self):
        """R4 regime → sell regardless of position size."""
        result = handle_assignment(
            ticker="GLD",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=400.0,
            contracts=1,
            current_price=395.0,
            regime_id=4,
            regime_confidence=0.95,
            atr=12.0,
            atr_pct=3.0,
            account_nlv=100000,
            available_bp=70000,
        )
        assert result.recommended_action == AssignmentAction.SELL_IMMEDIATELY
        assert "R4" in result.reasons[0]

    def test_r4_urgency_is_immediate(self):
        """R4 sell should be immediate."""
        result = handle_assignment(
            ticker="GLD",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=400.0,
            contracts=1,
            current_price=395.0,
            regime_id=4,
            regime_confidence=0.95,
            atr=12.0,
            atr_pct=3.0,
            account_nlv=100000,
            available_bp=70000,
        )
        assert result.urgency == "immediate"

    def test_r3_trending_sells(self):
        """R3 trending regime → sell assigned shares (use large account so regime check fires)."""
        result = handle_assignment(
            ticker="SPY",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=640.0,
            contracts=1,
            current_price=630.0,
            regime_id=3,
            regime_confidence=0.85,
            atr=10.0,
            atr_pct=1.5,
            account_nlv=200000,  # 64K/200K = 32% — below 50% concentration
            available_bp=120000,
        )
        assert result.recommended_action == AssignmentAction.SELL_IMMEDIATELY

    def test_r3_urgency_is_today(self):
        """R3 sell should be today (not immediate, not this_week).

        Use a large account so position is < 50% NLV and regime check fires.
        """
        result = handle_assignment(
            ticker="SPY",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=640.0,
            contracts=1,
            current_price=630.0,
            regime_id=3,
            regime_confidence=0.85,
            atr=10.0,
            atr_pct=1.5,
            account_nlv=200000,  # 64K/200K = 32% — passes concentration but regime fires
            available_bp=120000,
        )
        assert result.urgency == "today"

    def test_margin_pressure_sells(self):
        """Low buying power → sell even in R1.

        Use account NLV large enough that concentration check passes,
        but BP is below 50% of capital tied up.
        IWM 240 × 100 = $24K; account NLV = $100K (24% — fine);
        but BP = $5K < $12K (50% of capital) → margin rule fires.
        """
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=240.0,
            contracts=1,
            current_price=238.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=5.0,
            atr_pct=2.0,
            account_nlv=100000,
            available_bp=5000,  # Very low BP — 5K < 12K threshold
        )
        assert result.recommended_action == AssignmentAction.SELL_IMMEDIATELY
        reason_lower = result.reasons[0].lower()
        assert "margin" in reason_lower or "buying power" in reason_lower

    def test_margin_pressure_urgency_immediate(self):
        """Margin call risk → urgency = immediate."""
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=240.0,
            contracts=1,
            current_price=238.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=5.0,
            atr_pct=2.0,
            account_nlv=100000,
            available_bp=5000,  # BP < 50% of $24K capital
        )
        assert result.urgency == "immediate"

    def test_unrealized_pnl_computed_loss(self):
        """Assigned at 240, current 235 → unrealized loss of -$500."""
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=240.0,
            contracts=1,
            current_price=235.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=5.0,
            atr_pct=2.0,
            account_nlv=80000,
            available_bp=50000,
        )
        # (235 - 240) * 100 = -500
        assert result.unrealized_pnl == pytest.approx(-500.0, abs=1)

    def test_unrealized_pnl_computed_gain(self):
        """Assigned at 240, current 245 → unrealized gain of +$500."""
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=240.0,
            contracts=1,
            current_price=245.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=5.0,
            atr_pct=2.0,
            account_nlv=80000,
            available_bp=50000,
            is_etf=True,
        )
        assert result.unrealized_pnl == pytest.approx(500.0, abs=1)

    def test_partial_sell_for_30_50_pct_position(self):
        """Position at 35% of NLV → PARTIAL_SELL."""
        # IWM 240 × 200 shares = $48K on $130K account → 36.9%
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=240.0,
            contracts=2,
            current_price=238.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=5.0,
            atr_pct=2.0,
            account_nlv=130000,
            available_bp=80000,
            is_etf=True,
        )
        assert result.recommended_action == AssignmentAction.PARTIAL_SELL
        assert result.urgency == "today"
        assert result.response_trade_spec is not None

    def test_individual_stock_low_iv_sells(self):
        """Individual stock with low IV in R1 → sell (not enough wheel premium)."""
        result = handle_assignment(
            ticker="AAPL",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=200.0,
            contracts=1,
            current_price=195.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=4.0,
            atr_pct=2.0,
            account_nlv=80000,
            available_bp=50000,
            is_etf=False,
            iv_rank=20.0,  # Low IV
        )
        assert result.recommended_action == AssignmentAction.SELL_IMMEDIATELY

    def test_individual_stock_high_iv_wheels(self):
        """Individual stock with high IV in R1 → HOLD_AND_WHEEL."""
        result = handle_assignment(
            ticker="AAPL",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=200.0,
            contracts=1,
            current_price=195.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=4.0,
            atr_pct=2.0,
            account_nlv=80000,
            available_bp=50000,
            is_etf=False,
            iv_rank=45.0,  # Elevated IV
        )
        assert result.recommended_action == AssignmentAction.HOLD_AND_WHEEL
        assert result.wheel_trade_spec is not None

    def test_individual_stock_no_iv_sells(self):
        """Individual stock with no IV data in R1 → sell (can't verify wheel yield)."""
        result = handle_assignment(
            ticker="AAPL",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=200.0,
            contracts=1,
            current_price=195.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=4.0,
            atr_pct=2.0,
            account_nlv=80000,
            available_bp=50000,
            is_etf=False,
            iv_rank=None,  # No IV data
        )
        assert result.recommended_action == AssignmentAction.SELL_IMMEDIATELY

    def test_capital_tied_up_correct(self):
        """Capital tied up = strike × shares."""
        result = handle_assignment(
            ticker="SPY",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=500.0,
            contracts=1,
            current_price=495.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=8.0,
            atr_pct=1.6,
            account_nlv=200000,
            available_bp=120000,
            is_etf=True,
        )
        assert result.capital_tied_up == pytest.approx(500.0 * 100, abs=1)

    def test_two_contracts_doubles_shares(self):
        """2 contracts = 200 shares."""
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=200.0,
            contracts=2,
            current_price=198.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=4.0,
            atr_pct=2.0,
            account_nlv=200000,
            available_bp=100000,
            is_etf=True,
            iv_rank=40.0,
        )
        assert result.shares == 200

    def test_response_trade_spec_ticker_matches(self):
        """TradeSpec ticker matches input ticker."""
        result = handle_assignment(
            ticker="GLD",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=400.0,
            contracts=1,
            current_price=395.0,
            regime_id=4,
            regime_confidence=0.95,
            atr=12.0,
            atr_pct=3.0,
            account_nlv=100000,
            available_bp=70000,
        )
        assert result.response_trade_spec.ticker == "GLD"

    def test_regime_id_propagated(self):
        """Regime ID is stored in the analysis."""
        result = handle_assignment(
            ticker="SPY",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=640.0,
            contracts=1,
            current_price=630.0,
            regime_id=2,
            regime_confidence=0.75,
            atr=10.0,
            atr_pct=1.5,
            account_nlv=100000,
            available_bp=60000,
            is_etf=True,
        )
        assert result.regime_id == 2

    def test_wheel_call_strike_above_current_price(self):
        """Covered call strike must be strictly above current price."""
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=240.0,
            contracts=1,
            current_price=238.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=5.0,
            atr_pct=2.0,
            account_nlv=80000,
            available_bp=50000,
            is_etf=True,
            iv_rank=45.0,
        )
        call_strike = result.wheel_trade_spec.legs[0].strike
        assert call_strike > 238.0


class TestCallAssignment:
    """CALL_ASSIGNED: short call exercised."""

    def test_covered_call_assigned_no_response_needed(self):
        """Shares called away — you owned them. No further action needed."""
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.CALL_ASSIGNED,
            strike_price=250.0,
            contracts=1,
            current_price=255.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=5.0,
            atr_pct=2.0,
            account_nlv=80000,
            available_bp=50000,
            existing_shares=100,  # You owned the shares
        )
        # Shares were called away at profit — no further action needed
        assert result.recommended_action != AssignmentAction.COVER_SHORT
        assert result.response_trade_spec is None

    def test_covered_call_assigned_shares_message(self):
        """Covered call assignment reason should mention shares delivered."""
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.CALL_ASSIGNED,
            strike_price=250.0,
            contracts=1,
            current_price=255.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=5.0,
            atr_pct=2.0,
            account_nlv=80000,
            available_bp=50000,
            existing_shares=100,
        )
        assert any("called away" in r.lower() or "delivered" in r.lower() or "premium" in r.lower()
                   for r in result.reasons)

    def test_naked_short_covers_immediately(self):
        """Short call assigned without owning shares → short stock → COVER_SHORT."""
        result = handle_assignment(
            ticker="SPY",
            assignment_type=AssignmentType.CALL_ASSIGNED,
            strike_price=660.0,
            contracts=1,
            current_price=665.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=8.0,
            atr_pct=1.2,
            account_nlv=50000,
            available_bp=30000,
            existing_shares=0,  # You DON'T own shares
        )
        assert result.recommended_action == AssignmentAction.COVER_SHORT
        assert result.urgency == "immediate"
        assert result.response_trade_spec is not None

    def test_naked_short_spec_is_buy_to_close(self):
        """Cover short TradeSpec should use BUY_TO_CLOSE action."""
        result = handle_assignment(
            ticker="SPY",
            assignment_type=AssignmentType.CALL_ASSIGNED,
            strike_price=660.0,
            contracts=1,
            current_price=665.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=8.0,
            atr_pct=1.2,
            account_nlv=50000,
            available_bp=30000,
            existing_shares=0,
        )
        leg = result.response_trade_spec.legs[0]
        assert leg.action.value == "BTC"  # BUY_TO_CLOSE
        assert result.response_trade_spec.structure_type == "equity_buy"
        assert result.response_trade_spec.order_side == "debit"

    def test_partial_share_coverage_triggers_cover(self):
        """Owning fewer shares than assigned → still triggers COVER_SHORT for the short portion."""
        result = handle_assignment(
            ticker="SPY",
            assignment_type=AssignmentType.CALL_ASSIGNED,
            strike_price=660.0,
            contracts=2,  # 200 shares assigned
            current_price=665.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=8.0,
            atr_pct=1.2,
            account_nlv=100000,
            available_bp=60000,
            existing_shares=50,  # Only own 50 shares → short 150 shares
        )
        assert result.recommended_action == AssignmentAction.COVER_SHORT


class TestAssignmentModels:
    """Model and serialization tests."""

    def test_serialization_sell(self):
        """AssignmentAnalysis serializes correctly for sell scenario."""
        result = handle_assignment(
            ticker="SPY",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=650.0,
            contracts=1,
            current_price=640.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=8.0,
            atr_pct=1.2,
            account_nlv=50000,
            available_bp=30000,
        )
        d = result.model_dump()
        assert "recommended_action" in d
        assert "response_trade_spec" in d
        assert "reasons" in d
        assert isinstance(d["reasons"], list)
        assert len(d["reasons"]) >= 1

    def test_serialization_wheel(self):
        """AssignmentAnalysis with wheel TradeSpec serializes correctly."""
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=240.0,
            contracts=1,
            current_price=238.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=5.0,
            atr_pct=2.0,
            account_nlv=80000,
            available_bp=50000,
            is_etf=True,
            iv_rank=45.0,
        )
        d = result.model_dump()
        assert d["wheel_trade_spec"] is not None
        wts = d["wheel_trade_spec"]
        assert "legs" in wts
        assert len(wts["legs"]) == 1

    def test_assignment_type_stored(self):
        """Assignment type is stored correctly on the model."""
        result = handle_assignment(
            ticker="SPY",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=640.0,
            contracts=1,
            current_price=630.0,
            regime_id=4,
            regime_confidence=0.95,
            atr=10.0,
            atr_pct=1.5,
            account_nlv=100000,
            available_bp=60000,
        )
        assert result.assignment_type == AssignmentType.PUT_ASSIGNED

    def test_all_fields_present(self):
        """All expected fields exist on AssignmentAnalysis."""
        result = handle_assignment(
            ticker="SPY",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=640.0,
            contracts=1,
            current_price=630.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=10.0,
            atr_pct=1.5,
            account_nlv=100000,
            available_bp=60000,
            is_etf=True,
        )
        assert hasattr(result, "ticker")
        assert hasattr(result, "assignment_type")
        assert hasattr(result, "shares")
        assert hasattr(result, "assignment_price")
        assert hasattr(result, "current_price")
        assert hasattr(result, "unrealized_pnl")
        assert hasattr(result, "unrealized_pnl_pct")
        assert hasattr(result, "capital_tied_up")
        assert hasattr(result, "capital_pct_of_nlv")
        assert hasattr(result, "margin_impact")
        assert hasattr(result, "recommended_action")
        assert hasattr(result, "urgency")
        assert hasattr(result, "reasons")
        assert hasattr(result, "response_trade_spec")
        assert hasattr(result, "wheel_trade_spec")
        assert hasattr(result, "wheel_rationale")
        assert hasattr(result, "regime_id")
        assert hasattr(result, "regime_rationale")

    def test_margin_impact_within_limits_when_bp_sufficient(self):
        """margin_impact = within_limits when BP is healthy."""
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=240.0,
            contracts=1,
            current_price=238.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=5.0,
            atr_pct=2.0,
            account_nlv=80000,
            available_bp=50000,
            is_etf=True,
        )
        assert result.margin_impact == "within_limits"

    def test_margin_impact_warning_when_bp_low(self):
        """margin_impact = margin_warning when BP is low."""
        result = handle_assignment(
            ticker="IWM",
            assignment_type=AssignmentType.PUT_ASSIGNED,
            strike_price=240.0,
            contracts=1,
            current_price=238.0,
            regime_id=1,
            regime_confidence=0.90,
            atr=5.0,
            atr_pct=2.0,
            account_nlv=35000,
            available_bp=8000,  # Low but not critical (< 50% of 24K but > 25%)
        )
        assert result.margin_impact in ("margin_warning", "margin_call")
