"""Tests for desk management pure functions."""
from __future__ import annotations

import pytest

from income_desk.features.desk_management import (
    compute_desk_risk_limits,
    compute_instrument_risk,
    evaluate_desk_health,
    rebalance_desks,
    recommend_desk_structure,
    suggest_desk_for_trade,
)
from income_desk.models.portfolio import (
    DeskHealth,
    PortfolioAllocation,
    PortfolioAssetAllocation,
    PortfolioAssetClass,
    RiskTolerance,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_trades(n_wins: int, n_losses: int, win_pnl: float = 200.0, loss_pnl: float = -100.0, days: float = 15.0):
    trades = []
    for _ in range(n_wins):
        trades.append({"pnl": win_pnl, "won": True, "days_held": days})
    for _ in range(n_losses):
        trades.append({"pnl": loss_pnl, "won": False, "days_held": days})
    return trades


def _moderate_desks_raw(total: float = 100_000.0):
    """Helper: call recommend_desk_structure and return raw desk list."""
    rec = recommend_desk_structure(total, "moderate", "US")
    return [d.model_dump() for d in rec.desks]


# ---------------------------------------------------------------------------
# 1. recommend_desk_structure
# ---------------------------------------------------------------------------

class TestRecommendDeskStructure:

    def test_moderate_100k_us_has_3_or_more_desks(self):
        rec = recommend_desk_structure(100_000, "moderate", "US")
        assert len(rec.desks) >= 3

    def test_moderate_100k_capital_sums_to_total(self):
        rec = recommend_desk_structure(100_000, "moderate", "US")
        total = sum(d.capital_allocation for d in rec.desks) + rec.unallocated_cash
        assert total == pytest.approx(100_000, rel=1e-4)

    def test_conservative_100k_capital_sums_to_total(self):
        rec = recommend_desk_structure(100_000, "conservative", "US")
        total = sum(d.capital_allocation for d in rec.desks) + rec.unallocated_cash
        assert total == pytest.approx(100_000, rel=1e-4)

    def test_aggressive_100k_capital_sums_to_total(self):
        rec = recommend_desk_structure(100_000, "aggressive", "US")
        total = sum(d.capital_allocation for d in rec.desks) + rec.unallocated_cash
        assert total == pytest.approx(100_000, rel=1e-4)

    def test_50k_capital_sums_to_total(self):
        rec = recommend_desk_structure(50_000, "moderate")
        total = sum(d.capital_allocation for d in rec.desks) + rec.unallocated_cash
        assert total == pytest.approx(50_000, rel=1e-4)

    def test_unallocated_cash_is_positive(self):
        rec = recommend_desk_structure(100_000, "moderate", "US")
        assert rec.unallocated_cash > 0

    def test_conservative_has_larger_cash_reserve_than_moderate(self):
        con = recommend_desk_structure(100_000, "conservative", "US")
        mod = recommend_desk_structure(100_000, "moderate", "US")
        assert con.cash_reserve_pct >= mod.cash_reserve_pct

    def test_moderate_has_larger_cash_reserve_than_aggressive(self):
        mod = recommend_desk_structure(100_000, "moderate", "US")
        agg = recommend_desk_structure(100_000, "aggressive", "US")
        assert mod.cash_reserve_pct >= agg.cash_reserve_pct

    def test_conservative_smaller_0dte_than_moderate(self):
        con = recommend_desk_structure(100_000, "conservative", "US")
        mod = recommend_desk_structure(100_000, "moderate", "US")
        con_0dte = next((d for d in con.desks if "0dte" in d.desk_key), None)
        mod_0dte = next((d for d in mod.desks if "0dte" in d.desk_key), None)
        if con_0dte and mod_0dte:
            assert con_0dte.capital_pct <= mod_0dte.capital_pct

    def test_r4_increases_cash_reserve(self):
        r1 = recommend_desk_structure(100_000, "moderate", regime={"SPY": 1})
        r4 = recommend_desk_structure(100_000, "moderate", regime={"SPY": 4})
        assert r4.cash_reserve_pct > r1.cash_reserve_pct

    def test_r4_reduces_0dte_allocation(self):
        r1 = recommend_desk_structure(100_000, "moderate", regime={"SPY": 1, "QQQ": 1})
        r4 = recommend_desk_structure(100_000, "moderate", regime={"SPY": 4, "QQQ": 4})
        r1_0dte = next((d for d in r1.desks if "0dte" in d.desk_key), None)
        r4_0dte = next((d for d in r4.desks if "0dte" in d.desk_key), None)
        if r1_0dte and r4_0dte:
            assert r4_0dte.capital_allocation < r1_0dte.capital_allocation

    def test_india_market_has_expiry_desk(self):
        rec = recommend_desk_structure(500_000, "moderate", "India")
        desk_keys = [d.desk_key for d in rec.desks]
        assert any("expiry" in k for k in desk_keys)

    def test_india_expiry_desk_has_nifty_underlyings(self):
        rec = recommend_desk_structure(500_000, "moderate", "India")
        expiry_desk = next((d for d in rec.desks if "expiry" in d.desk_key), None)
        assert expiry_desk is not None
        assert any("NIFTY" in u for u in expiry_desk.preferred_underlyings)

    def test_aggressive_allows_undefined_risk(self):
        rec = recommend_desk_structure(100_000, "aggressive", "US")
        has_undefined = any(d.allow_undefined_risk for d in rec.desks)
        assert has_undefined

    def test_conservative_no_undefined_risk(self):
        rec = recommend_desk_structure(100_000, "conservative", "US")
        all_defined = all(not d.allow_undefined_risk for d in rec.desks)
        assert all_defined

    def test_desk_keys_are_unique(self):
        rec = recommend_desk_structure(100_000, "moderate", "US")
        keys = [d.desk_key for d in rec.desks]
        assert len(keys) == len(set(keys))

    def test_all_desks_have_positive_allocation(self):
        rec = recommend_desk_structure(100_000, "moderate", "US")
        assert all(d.capital_allocation > 0 for d in rec.desks)

    def test_all_desks_have_strategy_types(self):
        rec = recommend_desk_structure(100_000, "moderate", "US")
        assert all(len(d.strategy_types) > 0 for d in rec.desks)

    def test_regime_context_populated(self):
        rec = recommend_desk_structure(100_000, "moderate", regime={"SPY": 2, "QQQ": 2, "IWM": 2})
        assert len(rec.regime_context) > 0

    def test_r2_majority_reduces_0dte(self):
        baseline = recommend_desk_structure(100_000, "moderate", regime={"SPY": 1})
        r2_maj = recommend_desk_structure(100_000, "moderate", regime={"SPY": 2, "QQQ": 2, "IWM": 2})
        base_0dte = next((d for d in baseline.desks if "0dte" in d.desk_key), None)
        r2_0dte = next((d for d in r2_maj.desks if "0dte" in d.desk_key), None)
        if base_0dte and r2_0dte:
            assert r2_0dte.capital_allocation <= base_0dte.capital_allocation

    def test_total_capital_preserved_in_recommendation(self):
        rec = recommend_desk_structure(200_000, "moderate", "US")
        assert rec.total_capital == 200_000.0

    def test_income_desk_present_in_all_tolerances(self):
        for tol in ["conservative", "moderate", "aggressive"]:
            rec = recommend_desk_structure(100_000, tol, "US")
            has_income = any("income" in d.desk_key for d in rec.desks)
            assert has_income, f"Missing income desk for {tol}"


# ---------------------------------------------------------------------------
# 2. rebalance_desks
# ---------------------------------------------------------------------------

class TestRebalanceDesks:

    def _make_current(self):
        return [
            {"desk_key": "desk_0dte", "current_capital": 15_000},
            {"desk_key": "desk_income", "current_capital": 35_000},
            {"desk_key": "desk_core", "current_capital": 30_000},
        ]

    def _make_target(self):
        return [
            {"desk_key": "desk_0dte", "target_capital": 15_000},
            {"desk_key": "desk_income", "target_capital": 35_000},
            {"desk_key": "desk_core", "target_capital": 30_000},
        ]

    def test_no_rebalance_when_all_at_target(self):
        result = rebalance_desks(self._make_current(), self._make_target())
        assert result.needs_rebalance is False
        assert result.trigger == "none"

    def test_regime_change_triggers_rebalance(self):
        result = rebalance_desks(
            self._make_current(),
            self._make_target(),
            regime_changed=True,
        )
        assert result.needs_rebalance is True
        assert result.trigger == "regime_change"

    def test_regime_change_produces_adjustments(self):
        # Current and target differ
        current = [
            {"desk_key": "desk_0dte", "current_capital": 20_000},
            {"desk_key": "desk_income", "current_capital": 30_000},
        ]
        target = [
            {"desk_key": "desk_0dte", "target_capital": 10_000},
            {"desk_key": "desk_income", "target_capital": 40_000},
        ]
        result = rebalance_desks(current, target, regime_changed=True)
        assert result.needs_rebalance is True
        assert len(result.adjustments) > 0

    def test_drawdown_over_5pct_triggers_rebalance(self):
        result = rebalance_desks(
            self._make_current(),
            self._make_target(),
            account_drawdown_pct=0.07,
        )
        assert result.needs_rebalance is True
        assert result.trigger == "drawdown"

    def test_drawdown_reduces_all_desks(self):
        result = rebalance_desks(
            self._make_current(),
            self._make_target(),
            account_drawdown_pct=0.07,
        )
        for adj in result.adjustments:
            assert adj.change < 0, f"Expected reduction for {adj.desk_key}"

    def test_5pct_drawdown_no_trigger(self):
        # Exactly 5% shouldn't trigger (> not >=)
        result = rebalance_desks(
            self._make_current(),
            self._make_target(),
            account_drawdown_pct=0.05,
        )
        assert result.trigger != "drawdown"

    def test_drift_over_20pct_triggers_rebalance(self):
        current = [{"desk_key": "desk_income", "current_capital": 50_000}]
        target = [{"desk_key": "desk_income", "target_capital": 35_000}]
        result = rebalance_desks(current, target)
        # 50k vs 35k = 43% drift
        assert result.needs_rebalance is True
        assert result.trigger == "performance_drift"

    def test_small_drift_no_trigger(self):
        current = [{"desk_key": "desk_income", "current_capital": 36_000}]
        target = [{"desk_key": "desk_income", "target_capital": 35_000}]
        result = rebalance_desks(current, target)
        # 2.8% drift — below 20% threshold
        assert result.trigger != "performance_drift"

    def test_periodic_30_days_triggers_rebalance(self):
        result = rebalance_desks(
            self._make_current(),
            self._make_target(),
            days_since_last_rebalance=31,
        )
        assert result.needs_rebalance is True
        assert result.trigger == "periodic"

    def test_29_days_no_periodic_trigger(self):
        result = rebalance_desks(
            self._make_current(),
            self._make_target(),
            days_since_last_rebalance=29,
        )
        assert result.trigger != "periodic"

    def test_adjustment_change_sign_correct(self):
        current = [{"desk_key": "desk_0dte", "current_capital": 5_000}]
        target = [{"desk_key": "desk_0dte", "target_capital": 15_000}]
        result = rebalance_desks(current, target, regime_changed=True)
        adj = next(a for a in result.adjustments if a.desk_key == "desk_0dte")
        assert adj.change > 0  # needs more capital

    def test_rationale_is_non_empty(self):
        result = rebalance_desks(
            self._make_current(),
            self._make_target(),
            regime_changed=True,
        )
        assert len(result.rationale) > 0


# ---------------------------------------------------------------------------
# 3. evaluate_desk_health
# ---------------------------------------------------------------------------

class TestEvaluateDeskHealth:

    def test_no_trades_returns_caution(self):
        result = evaluate_desk_health("desk_income", [], capital_deployed=50_000)
        assert result.desk_key == "desk_income"
        assert result.win_rate is None
        assert len(result.issues) > 0

    def test_high_win_rate_excellent(self):
        trades = _make_trades(n_wins=18, n_losses=2, win_pnl=150, loss_pnl=-100)
        result = evaluate_desk_health("desk_income", trades, capital_deployed=50_000)
        assert result.health in (DeskHealth.EXCELLENT, DeskHealth.GOOD)
        assert result.win_rate == pytest.approx(0.90)

    def test_low_win_rate_flagged(self):
        trades = _make_trades(n_wins=4, n_losses=10, win_pnl=150, loss_pnl=-100)
        result = evaluate_desk_health("desk_income", trades, capital_deployed=50_000)
        assert result.win_rate == pytest.approx(4 / 14, rel=1e-3)
        assert any("win rate" in i.lower() for i in result.issues)

    def test_losing_desk_poor_or_critical(self):
        trades = _make_trades(n_wins=3, n_losses=7, win_pnl=50, loss_pnl=-300)
        result = evaluate_desk_health("desk_income", trades, capital_deployed=50_000)
        assert result.health in (DeskHealth.POOR, DeskHealth.CRITICAL)

    def test_profit_factor_below_1_flagged(self):
        trades = _make_trades(n_wins=6, n_losses=4, win_pnl=50, loss_pnl=-200)
        result = evaluate_desk_health("desk_income", trades, capital_deployed=50_000)
        assert result.profit_factor is not None
        assert result.profit_factor < 1.0
        assert any("profit factor" in i.lower() for i in result.issues)

    def test_regime_mismatch_flagged_r4_income(self):
        trades = _make_trades(n_wins=5, n_losses=5)
        result = evaluate_desk_health(
            "desk_income", trades, capital_deployed=50_000,
            current_regime=4,
            desk_strategy_types=["iron_condor", "credit_spread"],
        )
        assert result.regime_fit == "poor_fit"
        assert any("R4" in i for i in result.issues)

    def test_regime_well_suited_r1_income(self):
        trades = _make_trades(n_wins=8, n_losses=2)
        result = evaluate_desk_health(
            "desk_income", trades, capital_deployed=50_000,
            current_regime=1,
            desk_strategy_types=["iron_condor", "credit_spread"],
        )
        assert result.regime_fit == "well_suited"

    def test_regime_well_suited_r3_directional(self):
        trades = _make_trades(n_wins=7, n_losses=3)
        result = evaluate_desk_health(
            "desk_directional", trades, capital_deployed=30_000,
            current_regime=3,
            desk_strategy_types=["debit_spread", "diagonal"],
        )
        assert result.regime_fit == "well_suited"

    def test_score_between_0_and_1(self):
        trades = _make_trades(n_wins=5, n_losses=5)
        result = evaluate_desk_health("desk_income", trades, capital_deployed=50_000)
        assert 0.0 <= result.score <= 1.0

    def test_avg_days_held_computed(self):
        trades = [
            {"pnl": 100, "won": True, "days_held": 20},
            {"pnl": -50, "won": False, "days_held": 10},
        ]
        result = evaluate_desk_health("desk_income", trades, capital_deployed=50_000)
        assert result.avg_days_held == pytest.approx(15.0)

    def test_suggestions_non_empty_for_problems(self):
        trades = _make_trades(n_wins=2, n_losses=8, win_pnl=50, loss_pnl=-300)
        result = evaluate_desk_health("desk_income", trades, capital_deployed=50_000)
        assert len(result.suggestions) > 0


# ---------------------------------------------------------------------------
# 4. suggest_desk_for_trade
# ---------------------------------------------------------------------------

class TestSuggestDeskForTrade:

    def _make_desks(self):
        return [
            {
                "desk_key": "desk_0dte",
                "dte_min": 0, "dte_max": 0,
                "strategy_types": ["iron_condor", "credit_spread"],
                "max_positions": 3,
                "capital_allocation": 15_000,
            },
            {
                "desk_key": "desk_income",
                "dte_min": 21, "dte_max": 60,
                "strategy_types": ["iron_condor", "credit_spread", "calendar"],
                "max_positions": 8,
                "capital_allocation": 35_000,
            },
            {
                "desk_key": "desk_growth",
                "dte_min": 14, "dte_max": 45,
                "strategy_types": ["debit_spread", "diagonal"],
                "max_positions": 4,
                "capital_allocation": 12_000,
            },
        ]

    def test_0dte_routes_to_0dte_desk(self):
        result = suggest_desk_for_trade(
            self._make_desks(), trade_dte=0, strategy_type="iron_condor"
        )
        assert result["desk_key"] == "desk_0dte"

    def test_45dte_ic_routes_to_income_desk(self):
        result = suggest_desk_for_trade(
            self._make_desks(), trade_dte=45, strategy_type="iron_condor"
        )
        assert result["desk_key"] == "desk_income"

    def test_21dte_debit_routes_to_growth_desk(self):
        result = suggest_desk_for_trade(
            self._make_desks(), trade_dte=21, strategy_type="debit_spread"
        )
        assert result["desk_key"] == "desk_growth"

    def test_full_desk_routes_elsewhere(self):
        existing = {"desk_0dte": ["SPY", "QQQ", "IWM"]}  # 3/3 = at capacity
        result = suggest_desk_for_trade(
            self._make_desks(),
            trade_dte=0,
            strategy_type="iron_condor",
            existing_positions_by_desk=existing,
        )
        # desk_0dte is full, should route elsewhere
        assert result["desk_key"] != "desk_0dte" or result["score"] == 0.0

    def test_result_has_required_keys(self):
        result = suggest_desk_for_trade(
            self._make_desks(), trade_dte=30, strategy_type="calendar"
        )
        assert "desk_key" in result
        assert "reason" in result
        assert "score" in result
        assert "alternatives" in result

    def test_score_between_0_and_1(self):
        result = suggest_desk_for_trade(
            self._make_desks(), trade_dte=45, strategy_type="iron_condor"
        )
        assert 0.0 <= result["score"] <= 1.0

    def test_empty_desks_returns_none_desk_key(self):
        result = suggest_desk_for_trade([], trade_dte=30, strategy_type="iron_condor")
        assert result["desk_key"] is None

    def test_ticker_correlation_penalizes_same_desk(self):
        existing = {"desk_income": ["SPY"]}
        result_no_ticker = suggest_desk_for_trade(
            self._make_desks(), trade_dte=45, strategy_type="iron_condor",
            ticker="SPY",
            existing_positions_by_desk=existing,
        )
        result_no_conflict = suggest_desk_for_trade(
            self._make_desks(), trade_dte=45, strategy_type="iron_condor",
            ticker="GLD",  # not in desk_income
            existing_positions_by_desk=existing,
        )
        # SPY already in desk_income → lower score vs GLD
        assert result_no_conflict["score"] >= result_no_ticker["score"]

    def test_alternatives_list_populated(self):
        result = suggest_desk_for_trade(
            self._make_desks(), trade_dte=45, strategy_type="iron_condor"
        )
        assert isinstance(result["alternatives"], list)


# ---------------------------------------------------------------------------
# 5. compute_desk_risk_limits
# ---------------------------------------------------------------------------

class TestComputeDeskRiskLimits:

    def test_r1_full_limits(self):
        result = compute_desk_risk_limits(
            desk_key="desk_income",
            base_max_positions=10,
            base_max_single_position_pct=0.12,
            base_circuit_breaker_pct=0.07,
            regime_id=1,
        )
        assert result.max_positions == 10
        assert result.max_single_position_pct == pytest.approx(0.12)
        assert result.position_size_factor == pytest.approx(1.0)

    def test_r2_80pct_limits(self):
        result = compute_desk_risk_limits(
            desk_key="desk_income",
            base_max_positions=10,
            base_max_single_position_pct=0.12,
            base_circuit_breaker_pct=0.07,
            regime_id=2,
        )
        assert result.max_positions == 8  # 10 * 0.80
        assert result.max_single_position_pct == pytest.approx(0.096)  # 0.12 * 0.80
        assert result.position_size_factor == pytest.approx(0.80)

    def test_r4_halved_limits(self):
        result = compute_desk_risk_limits(
            desk_key="desk_income",
            base_max_positions=10,
            base_max_single_position_pct=0.12,
            base_circuit_breaker_pct=0.07,
            regime_id=4,
        )
        assert result.max_positions == 5  # 10 * 0.50
        assert result.max_single_position_pct == pytest.approx(0.06)  # 0.12 * 0.50
        assert result.position_size_factor == pytest.approx(0.50)

    def test_r3_income_desk_70pct(self):
        result = compute_desk_risk_limits(
            desk_key="desk_income",
            base_max_positions=10,
            base_max_single_position_pct=0.12,
            base_circuit_breaker_pct=0.07,
            regime_id=3,
        )
        assert result.max_positions == 7  # 10 * 0.70
        assert result.position_size_factor == pytest.approx(0.70)

    def test_r3_directional_desk_full_limits(self):
        result = compute_desk_risk_limits(
            desk_key="desk_directional",
            base_max_positions=6,
            base_max_single_position_pct=0.12,
            base_circuit_breaker_pct=0.05,
            regime_id=3,
        )
        assert result.max_positions == 6  # full limits for directional in R3
        assert result.position_size_factor == pytest.approx(1.0)

    def test_drawdown_overlay_halves_limits(self):
        baseline = compute_desk_risk_limits(
            desk_key="desk_income",
            base_max_positions=10,
            base_max_single_position_pct=0.12,
            base_circuit_breaker_pct=0.07,
            regime_id=1,
            account_drawdown_pct=0.0,
        )
        with_drawdown = compute_desk_risk_limits(
            desk_key="desk_income",
            base_max_positions=10,
            base_max_single_position_pct=0.12,
            base_circuit_breaker_pct=0.07,
            regime_id=1,
            account_drawdown_pct=0.07,  # 7% drawdown
        )
        assert with_drawdown.max_positions < baseline.max_positions
        assert with_drawdown.position_size_factor < baseline.position_size_factor

    def test_circuit_breaker_not_scaled(self):
        # Circuit breaker is a hard stop — should not be reduced
        r1 = compute_desk_risk_limits(
            desk_key="desk_income",
            base_max_positions=10,
            base_max_single_position_pct=0.12,
            base_circuit_breaker_pct=0.07,
            regime_id=1,
        )
        r4 = compute_desk_risk_limits(
            desk_key="desk_income",
            base_max_positions=10,
            base_max_single_position_pct=0.12,
            base_circuit_breaker_pct=0.07,
            regime_id=4,
        )
        assert r1.circuit_breaker_pct == r4.circuit_breaker_pct

    def test_max_positions_minimum_1(self):
        result = compute_desk_risk_limits(
            desk_key="desk_income",
            base_max_positions=1,
            base_max_single_position_pct=0.12,
            base_circuit_breaker_pct=0.07,
            regime_id=4,
            account_drawdown_pct=0.10,
        )
        assert result.max_positions >= 1

    def test_rationale_populated(self):
        result = compute_desk_risk_limits(
            desk_key="desk_income",
            base_max_positions=10,
            base_max_single_position_pct=0.12,
            base_circuit_breaker_pct=0.07,
        )
        assert len(result.rationale) > 0

    def test_desk_key_preserved(self):
        result = compute_desk_risk_limits(
            desk_key="desk_0dte",
            base_max_positions=3,
            base_max_single_position_pct=0.08,
            base_circuit_breaker_pct=0.04,
        )
        assert result.desk_key == "desk_0dte"


# ---------------------------------------------------------------------------
# 6. compute_instrument_risk
# ---------------------------------------------------------------------------

class TestComputeInstrumentRisk:

    def test_option_spread_defined_risk(self):
        result = compute_instrument_risk(
            ticker="SPY",
            instrument_type="option_spread",
            position_value=150.0,
            regime_id=1,
            wing_width=5.0,
            lot_size=100,
        )
        assert result.risk_category == "defined"
        assert result.max_loss == pytest.approx(500.0)  # 5 * 100
        assert result.risk_method == "max_loss"

    def test_option_spread_without_wing_width_uses_position_value(self):
        result = compute_instrument_risk(
            ticker="SPY",
            instrument_type="option_spread",
            position_value=200.0,
            regime_id=1,
        )
        assert result.max_loss == pytest.approx(200.0)
        assert result.risk_category == "defined"

    def test_equity_long_atr_based(self):
        result = compute_instrument_risk(
            ticker="AAPL",
            instrument_type="equity_long",
            position_value=10_000.0,
            regime_id=1,
            atr_pct=0.015,
        )
        assert result.risk_category == "equity"
        assert result.risk_method == "atr_based"
        # R1 factor = 0.40, expected_loss = 10000 * 0.015 * 0.40 = 60
        assert result.expected_loss_1d == pytest.approx(60.0)

    def test_equity_long_fallback_2pct_without_atr(self):
        result = compute_instrument_risk(
            ticker="AAPL",
            instrument_type="equity_long",
            position_value=10_000.0,
            regime_id=1,
        )
        # 2% * 10000 * 0.40 = 80
        assert result.expected_loss_1d == pytest.approx(80.0)

    def test_futures_margin_based(self):
        result = compute_instrument_risk(
            ticker="ES",
            instrument_type="futures",
            position_value=250_000.0,
            regime_id=1,
            contract_value=250_000.0,
            margin_pct=0.10,
        )
        assert result.risk_method == "margin_based"
        # margin = 250000 * 0.10 * 0.40 = 10000
        assert result.margin_required == pytest.approx(10_000.0)

    def test_naked_option_undefined_risk(self):
        result = compute_instrument_risk(
            ticker="SPY",
            instrument_type="naked_option",
            position_value=500.0,
            regime_id=1,
            underlying_price=450.0,
            lot_size=100,
        )
        assert result.risk_category == "undefined"
        assert result.max_loss == pytest.approx(45_000.0)  # 450 * 100
        assert "UNDEFINED RISK" in result.rationale

    def test_naked_option_without_price_uses_proxy(self):
        result = compute_instrument_risk(
            ticker="SPY",
            instrument_type="naked_option",
            position_value=500.0,
            regime_id=1,
        )
        assert result.max_loss == pytest.approx(5_000.0)  # 500 * 10
        assert result.risk_category == "undefined"

    def test_r4_increases_expected_loss(self):
        r1 = compute_instrument_risk("SPY", "equity_long", 10_000, regime_id=1, atr_pct=0.015)
        r4 = compute_instrument_risk("SPY", "equity_long", 10_000, regime_id=4, atr_pct=0.015)
        assert r4.expected_loss_1d > r1.expected_loss_1d

    def test_india_lot_size_option_spread(self):
        # NIFTY lot size = 75
        result = compute_instrument_risk(
            ticker="NIFTY",
            instrument_type="option_spread",
            position_value=3_000.0,
            regime_id=1,
            wing_width=100.0,  # 100 point wide spread
            lot_size=75,
        )
        assert result.max_loss == pytest.approx(7_500.0)  # 100 * 75

    def test_regime_factor_stored(self):
        result = compute_instrument_risk("SPY", "equity_long", 10_000, regime_id=2, atr_pct=0.015)
        assert result.regime_factor == pytest.approx(0.70)

    def test_rationale_non_empty(self):
        result = compute_instrument_risk("SPY", "option_spread", 200.0, wing_width=5.0)
        assert len(result.rationale) > 0

    def test_ticker_preserved(self):
        result = compute_instrument_risk("GLD", "equity_long", 5_000.0, atr_pct=0.01)
        assert result.ticker == "GLD"

    def test_unknown_instrument_type_returns_conservative(self):
        result = compute_instrument_risk("XYZ", "exotic_swap", 10_000.0)
        assert result.max_loss > 0
        assert result.risk_category == "undefined"


# ---------------------------------------------------------------------------
# 7. TestAssetAllocation — new asset class → risk type → desk framework
# ---------------------------------------------------------------------------

class TestAssetAllocation:

    def test_returns_portfolio_allocation(self):
        rec = recommend_desk_structure(100_000, "moderate")
        assert isinstance(rec, PortfolioAllocation)

    def test_allocations_sum_to_100pct(self):
        rec = recommend_desk_structure(100_000, "moderate")
        total_pct = rec.cash_reserve_pct + sum(a.allocation_pct for a in rec.allocations)
        assert total_pct == pytest.approx(1.0, abs=0.01)

    def test_conservative_no_undefined_options(self):
        rec = recommend_desk_structure(100_000, "conservative")
        options = next((a for a in rec.allocations if a.asset_class == PortfolioAssetClass.OPTIONS), None)
        assert options is not None
        assert options.undefined_risk_pct == pytest.approx(0.0)

    def test_aggressive_has_undefined_options(self):
        rec = recommend_desk_structure(100_000, "aggressive")
        options = next((a for a in rec.allocations if a.asset_class == PortfolioAssetClass.OPTIONS), None)
        assert options is not None
        assert options.undefined_risk_pct > 0.0

    def test_r4_increases_cash(self):
        r1 = recommend_desk_structure(100_000, "moderate", regime={"SPY": 1})
        r4 = recommend_desk_structure(100_000, "moderate", regime={"SPY": 4})
        assert r4.cash_reserve_pct > r1.cash_reserve_pct

    def test_defined_plus_undefined_equals_allocation(self):
        rec = recommend_desk_structure(100_000, "moderate")
        for a in rec.allocations:
            assert a.defined_risk_dollars + a.undefined_risk_dollars == pytest.approx(
                a.allocation_dollars, abs=1
            )

    def test_india_no_futures_allocation(self):
        rec = recommend_desk_structure(500_000, "moderate", market="India")
        futures = [a for a in rec.allocations if a.asset_class == PortfolioAssetClass.FUTURES]
        if futures:
            assert futures[0].allocation_dollars == pytest.approx(0.0, abs=1)

    def test_desks_derived_from_allocations(self):
        rec = recommend_desk_structure(100_000, "moderate")
        desk_capital = sum(d.capital_allocation for d in rec.desks)
        alloc_capital = sum(a.allocation_dollars for a in rec.allocations)
        assert desk_capital == pytest.approx(alloc_capital, abs=100)

    def test_each_asset_class_present(self):
        rec = recommend_desk_structure(100_000, "moderate")
        classes = {a.asset_class for a in rec.allocations}
        assert PortfolioAssetClass.OPTIONS in classes
        assert PortfolioAssetClass.STOCKS in classes

    def test_allocation_dollars_match_pct(self):
        rec = recommend_desk_structure(100_000, "moderate")
        for a in rec.allocations:
            expected = 100_000 * a.allocation_pct
            assert a.allocation_dollars == pytest.approx(expected, abs=1)

    def test_cash_reserve_dollars_matches_pct(self):
        rec = recommend_desk_structure(100_000, "moderate")
        expected = 100_000 * rec.cash_reserve_pct
        assert rec.cash_reserve_dollars == pytest.approx(expected, abs=1)

    def test_regime_adjustments_populated(self):
        rec = recommend_desk_structure(100_000, "moderate", regime={"SPY": 2, "QQQ": 2, "IWM": 2})
        assert len(rec.regime_adjustments) > 0
        assert len(rec.regime_context) > 0  # backward-compat property

    def test_r4_forces_undefined_options_to_zero(self):
        rec = recommend_desk_structure(100_000, "moderate", regime={"SPY": 4, "QQQ": 4})
        options = next((a for a in rec.allocations if a.asset_class == PortfolioAssetClass.OPTIONS), None)
        if options is not None:
            assert options.undefined_risk_pct == pytest.approx(0.0)

    def test_r4_forces_undefined_stocks_to_zero(self):
        rec = recommend_desk_structure(100_000, "moderate", regime={"SPY": 4, "QQQ": 4})
        stocks = next((a for a in rec.allocations if a.asset_class == PortfolioAssetClass.STOCKS), None)
        if stocks is not None:
            assert stocks.undefined_risk_pct == pytest.approx(0.0)

    def test_total_capital_preserved_with_new_model(self):
        rec = recommend_desk_structure(200_000, "moderate")
        total = rec.cash_reserve_dollars + sum(a.allocation_dollars for a in rec.allocations)
        assert total == pytest.approx(200_000, rel=1e-4)

    def test_moderate_has_metals_desk(self):
        rec = recommend_desk_structure(100_000, "moderate")
        desk_keys = {d.desk_key for d in rec.desks}
        assert "desk_metals_options" in desk_keys

    def test_moderate_has_wheel_desk(self):
        rec = recommend_desk_structure(100_000, "moderate")
        desk_keys = {d.desk_key for d in rec.desks}
        assert "desk_wheel" in desk_keys

    def test_moderate_has_income_defined_desk(self):
        rec = recommend_desk_structure(100_000, "moderate")
        desk_keys = {d.desk_key for d in rec.desks}
        assert "desk_income_defined" in desk_keys

    def test_asset_allocation_rationale_non_empty(self):
        rec = recommend_desk_structure(100_000, "moderate")
        for a in rec.allocations:
            assert len(a.rationale) > 0

    def test_conservative_only_defined_risk_desks(self):
        rec = recommend_desk_structure(100_000, "conservative")
        all_defined = all(not d.allow_undefined_risk for d in rec.desks)
        assert all_defined

    def test_portfolio_allocation_type_annotations(self):
        rec = recommend_desk_structure(100_000, "moderate")
        assert isinstance(rec.allocations, list)
        assert all(isinstance(a, PortfolioAssetAllocation) for a in rec.allocations)

    def test_india_has_expiry_desk_via_new_framework(self):
        rec = recommend_desk_structure(500_000, "moderate", market="India")
        desk_keys = [d.desk_key for d in rec.desks]
        assert any("expiry" in k for k in desk_keys)
