"""Tests for trade commentary models and generation."""
import pytest

from income_desk.retrospection.models import (
    DecisionCommentary,
    DimensionFinding,
    TradeCommentary,
    LegRecord,
    PositionSize,
    TradeClosed,
    TradeOpened,
    TradeSnapshot,
    EntryAnalytics,
    DecisionRecord,
)
from income_desk.retrospection.commentary import (
    analyze_regime_alignment,
    analyze_strike_placement,
    analyze_entry_pricing,
    analyze_position_sizing,
    analyze_exit_quality,
    analyze_hindsight,
    compose_trade_commentary,
    generate_decision_commentary,
)


# ── Model Tests ────────────────────────────────────────────────────────


class TestCommentaryModels:
    def test_dimension_finding_defaults(self):
        f = DimensionFinding(
            dimension="regime_alignment", grade="A", score=92,
            narrative="Iron condor in R1 — textbook theta setup.",
        )
        assert f.dimension == "regime_alignment"
        assert f.grade == "A"
        assert f.score == 92
        assert f.details == {}

    def test_trade_commentary_defaults(self):
        tc = TradeCommentary(
            trade_id="abc-123", ticker="SPY", strategy="iron_condor",
            market="US", overall_narrative="Good trade.", dimensions=[],
        )
        assert tc.should_have_avoided is False
        assert tc.avoidance_reason is None
        assert tc.key_lesson is None

    def test_decision_commentary_defaults(self):
        dc = DecisionCommentary(narrative="433 decisions reviewed.")
        assert dc.near_misses == []
        assert dc.missed_opportunities == []
        assert dc.rejection_summary == {}


# ── Regime Alignment ───────────────────────────────────────────────────


class TestRegimeAlignment:
    def test_r1_iron_condor_is_grade_a(self):
        f = analyze_regime_alignment("iron_condor", "R1", 0.65)
        assert f.grade == "A"
        assert f.score >= 85
        assert "R1" in f.narrative

    def test_r4_iron_condor_is_grade_d_or_f(self):
        f = analyze_regime_alignment("iron_condor", "R4", 0.70)
        assert f.grade in ("D", "F")
        assert f.score <= 40

    def test_r3_diagonal_is_grade_a(self):
        f = analyze_regime_alignment("diagonal", "R3", 0.60)
        assert f.grade in ("A", "B+")

    def test_missing_regime_is_grade_c(self):
        f = analyze_regime_alignment("iron_condor", None, None)
        assert f.grade == "C"
        assert f.score == 50

    def test_low_confidence_regime(self):
        f = analyze_regime_alignment("iron_condor", "R1", 0.35)
        assert f.score < 85

    def test_neutral_strategy(self):
        f = analyze_regime_alignment("some_unknown", "R1", 0.60)
        assert f.grade == "B-"


# ── Strike Placement ───────────────────────────────────────────────────


class TestStrikePlacement:
    def _make_ic_legs(self, sp_delta, sc_delta, underlying=560.0, wing=5.0):
        return [
            LegRecord(action="STO", strike=underlying - 20, option_type="put",
                      entry_delta=sp_delta, quantity=-1),
            LegRecord(action="BTO", strike=underlying - 20 - wing, option_type="put",
                      entry_delta=sp_delta * 0.6, quantity=1),
            LegRecord(action="STO", strike=underlying + 20, option_type="call",
                      entry_delta=sc_delta, quantity=-1),
            LegRecord(action="BTO", strike=underlying + 20 + wing, option_type="call",
                      entry_delta=sc_delta * 0.6, quantity=1),
        ]

    def test_ideal_deltas_grade_a(self):
        legs = self._make_ic_legs(-0.20, 0.20)
        f = analyze_strike_placement(legs, "iron_condor", 560.0)
        assert f.grade == "A"
        assert f.score >= 85

    def test_aggressive_deltas_grade_c(self):
        legs = self._make_ic_legs(-0.35, 0.38)
        f = analyze_strike_placement(legs, "iron_condor", 560.0)
        assert f.grade in ("C", "C+")

    def test_very_aggressive_grade_d(self):
        legs = self._make_ic_legs(-0.45, 0.45)
        f = analyze_strike_placement(legs, "iron_condor", 560.0)
        assert f.grade in ("D", "F")

    def test_no_legs_grade_c(self):
        f = analyze_strike_placement([], "iron_condor", 560.0)
        assert f.grade == "C"

    def test_equity_skips_strike_analysis(self):
        legs = [LegRecord(action="BTO", option_type=None, quantity=100, entry_price=54.5)]
        f = analyze_strike_placement(legs, "equity_long", 54.5)
        assert f.grade == "B"

    def test_conservative_deltas(self):
        legs = self._make_ic_legs(-0.12, 0.12)
        f = analyze_strike_placement(legs, "iron_condor", 560.0)
        assert f.grade in ("A-", "A")


# ── Entry Pricing ──────────────────────────────────────────────────────


class TestEntryPricing:
    def test_excellent_credit_width_ratio(self):
        f = analyze_entry_pricing(3.20, [], "iron_condor", wing_width=5.0)
        assert f.grade == "A"

    def test_good_credit_ratio(self):
        f = analyze_entry_pricing(2.00, [], "iron_condor", wing_width=5.0)
        assert f.grade in ("B", "B+")

    def test_thin_credit_ratio(self):
        f = analyze_entry_pricing(1.20, [], "iron_condor", wing_width=5.0)
        assert f.grade in ("C", "D")

    def test_india_market_inr(self):
        f = analyze_entry_pricing(32.25, [], "iron_condor",
                                  wing_width=50.0, lot_size=25, currency="INR")
        assert f.grade == "A"
        assert f.details.get("currency") == "INR"

    def test_no_wing_width(self):
        f = analyze_entry_pricing(2.50, [], "credit_spread", wing_width=None)
        assert f.grade in ("B", "C")

    def test_no_entry_price(self):
        f = analyze_entry_pricing(0.0, [], "iron_condor", wing_width=5.0)
        assert f.grade == "C"


# ── Position Sizing ────────────────────────────────────────────────────


class TestPositionSizing:
    def test_small_position_grade_a(self):
        f = analyze_position_sizing(PositionSize(capital_at_risk_pct=1.5, contracts=1))
        assert f.grade == "A"

    def test_medium_position_grade_b(self):
        f = analyze_position_sizing(PositionSize(capital_at_risk_pct=2.5, contracts=2))
        assert f.grade in ("B", "B+", "C+")

    def test_oversized_grade_d(self):
        f = analyze_position_sizing(PositionSize(capital_at_risk_pct=7.0, contracts=5))
        assert f.grade in ("D", "F")

    def test_no_sizing_data(self):
        f = analyze_position_sizing(None)
        assert f.grade == "C"


# ── Exit Quality ───────────────────────────────────────────────────────


class TestExitQuality:
    def test_profit_target_hit(self):
        t = TradeClosed(
            trade_id="x", ticker="SPY", strategy_type="iron_condor",
            exit_reason="profit_target", total_pnl=150.0,
            max_pnl_during_hold=180.0, holding_days=12,
        )
        f = analyze_exit_quality(t)
        assert f.grade in ("A", "A-", "B")  # score=85 -> B (>=83)

    def test_was_profitable_closed_at_loss(self):
        t = TradeClosed(
            trade_id="x", ticker="SPY", strategy_type="iron_condor",
            exit_reason="stop_loss", total_pnl=-200.0,
            max_pnl_during_hold=120.0, min_pnl_during_hold=-250.0,
            holding_days=18,
        )
        f = analyze_exit_quality(t)
        assert f.score < 60

    def test_held_too_long_theta(self):
        t = TradeClosed(
            trade_id="x", ticker="QQQ", strategy_type="iron_condor",
            exit_reason="expiration", total_pnl=50.0, holding_days=35,
        )
        f = analyze_exit_quality(t)
        assert f.score < 80

    def test_regime_changed(self):
        t = TradeClosed(
            trade_id="x", ticker="GLD", strategy_type="calendar",
            exit_reason="profit_target", total_pnl=80.0,
            entry_regime="R1", exit_regime="R3", holding_days=14,
        )
        f = analyze_exit_quality(t)
        assert "regime" in f.narrative.lower()


# ── Hindsight ──────────────────────────────────────────────────────────


class TestHindsight:
    def test_position_doing_well(self):
        snap = TradeSnapshot(
            trade_id="x", ticker="SPY", strategy_type="iron_condor",
            current_pnl=80.0, current_pnl_pct=40.0, dte_remaining=15,
            underlying_price_at_entry=560.0, underlying_price_now=558.0,
        )
        f = analyze_hindsight(snap)
        assert f.score >= 75

    def test_underwater_low_dte(self):
        snap = TradeSnapshot(
            trade_id="x", ticker="QQQ", strategy_type="iron_condor",
            current_pnl=-100.0, current_pnl_pct=-50.0, dte_remaining=3,
        )
        f = analyze_hindsight(snap)
        assert f.score < 50

    def test_profitable_nearing_target(self):
        snap = TradeSnapshot(
            trade_id="x", ticker="GLD", strategy_type="credit_spread",
            current_pnl=120.0, current_pnl_pct=60.0, dte_remaining=8,
        )
        f = analyze_hindsight(snap)
        assert f.score >= 80


# ── Composer ───────────────────────────────────────────────────────────


class TestComposer:
    def test_compose_opened_trade(self):
        trade = TradeOpened(
            trade_id="abc", ticker="SPY", strategy_type="iron_condor",
            market="US", entry_price=3.20, entry_underlying_price=560.0,
            entry_analytics=EntryAnalytics(regime_at_entry="R1"),
            position_size=PositionSize(capital_at_risk_pct=2.0, contracts=1),
            legs=[
                LegRecord(action="STO", strike=540, option_type="put", entry_delta=-0.20, quantity=-1),
                LegRecord(action="BTO", strike=535, option_type="put", entry_delta=-0.12, quantity=1),
                LegRecord(action="STO", strike=580, option_type="call", entry_delta=0.20, quantity=-1),
                LegRecord(action="BTO", strike=585, option_type="call", entry_delta=0.12, quantity=1),
            ],
        )
        tc = compose_trade_commentary(trade, trade_type="opened")
        assert tc.ticker == "SPY"
        assert len(tc.dimensions) >= 4
        assert tc.overall_narrative
        assert not tc.should_have_avoided

    def test_compose_closed_trade(self):
        trade = TradeClosed(
            trade_id="xyz", ticker="QQQ", strategy_type="iron_condor",
            exit_reason="profit_target", total_pnl=150.0,
            max_pnl_during_hold=180.0, holding_days=14,
        )
        tc = compose_trade_commentary(trade, trade_type="closed")
        assert len(tc.dimensions) >= 2
        assert any(d.dimension == "exit_quality" for d in tc.dimensions)

    def test_compose_snapshot(self):
        snap = TradeSnapshot(
            trade_id="s1", ticker="GLD", strategy_type="credit_spread",
            current_pnl=50.0, current_pnl_pct=30.0, dte_remaining=12,
            underlying_price_at_entry=400.0, underlying_price_now=402.0,
        )
        tc = compose_trade_commentary(snap, trade_type="snapshot")
        assert any(d.dimension == "hindsight" for d in tc.dimensions)

    def test_avoid_detection(self):
        trade = TradeOpened(
            trade_id="bad", ticker="TSLA", strategy_type="iron_condor",
            market="US", entry_price=2.0, entry_underlying_price=250.0,
            entry_analytics=EntryAnalytics(regime_at_entry="R4"),
        )
        tc = compose_trade_commentary(trade, trade_type="opened")
        assert tc.should_have_avoided is True
        assert tc.avoidance_reason is not None


# ── Decision Commentary ────────────────────────────────────────────────


class TestDecisionCommentary:
    def test_groups_rejections(self):
        decisions = [
            DecisionRecord(id="1", ticker="SPY", strategy="iron_condor",
                           score=0.72, gate_result="PASS", response="approved"),
            DecisionRecord(id="2", ticker="TSLA", strategy="iron_condor",
                           score=0.15, gate_result="Score 0.15 < 0.35", response="rejected"),
            DecisionRecord(id="3", ticker="AAPL", strategy="calendar",
                           score=0.45, gate_result="NO_GO verdict", response="rejected"),
            DecisionRecord(id="4", ticker="GLD", strategy="diagonal",
                           score=0.55, gate_result="Score cap applied", response="rejected"),
        ]
        dc = generate_decision_commentary(decisions)
        assert dc.narrative
        assert len(dc.near_misses) >= 1  # AAPL at 0.45
        assert len(dc.missed_opportunities) >= 1  # GLD at 0.55

    def test_all_approved(self):
        decisions = [
            DecisionRecord(id="1", ticker="SPY", strategy="iron_condor",
                           score=0.72, gate_result="PASS", response="approved"),
        ]
        dc = generate_decision_commentary(decisions)
        assert dc.near_misses == []
        assert dc.missed_opportunities == []
        assert "1 approved" in dc.narrative
