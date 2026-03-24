"""Unit tests for income_desk.trade_analytics — 6 functions, 13 tests."""

from __future__ import annotations

from datetime import date

import pytest

from income_desk.models.opportunity import LegSpec
from income_desk.trade_analytics import (
    LegPnLInput,
    PositionSnapshot,
    compute_pnl_attribution,
    compute_portfolio_analytics,
    compute_structure_risk,
    compute_trade_pnl,
    evaluate_circuit_breakers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _leg(
    strike: float,
    option_type: str,
    action: str,
    expiration: str = "2026-04-18",
    quantity: int = 1,
) -> LegSpec:
    """Create a LegSpec with required fields filled in for testing."""
    is_short = action in ("STO", "STC")
    role_prefix = "short" if is_short else "long"
    return LegSpec(
        role=f"{role_prefix}_{option_type}",
        action=action,
        quantity=quantity,
        option_type=option_type,
        strike=strike,
        strike_label=f"{strike} {option_type}",
        expiration=date.fromisoformat(expiration),
        days_to_expiry=30,
        atm_iv_at_expiry=0.25,
    )


# =========================================================================
# 1. compute_pnl_attribution — basic
# =========================================================================

def test_pnl_attribution_basic():
    result = compute_pnl_attribution(
        entry_delta=0.35,
        entry_gamma=0.005,
        entry_theta=-0.8,
        entry_vega=12.0,
        underlying_change=5.20,
        iv_change=-0.03,
        days_elapsed=33,
        actual_pnl=-1366.0,
        multiplier=100,
        quantity=1,
    )
    assert result.delta_pnl == pytest.approx(182.0)
    assert result.gamma_pnl == pytest.approx(6.76)
    assert result.theta_pnl == pytest.approx(-2640.0)
    assert result.vega_pnl == pytest.approx(-36.0)
    assert result.model_pnl == pytest.approx(-2487.24)
    assert result.unexplained_pnl == pytest.approx(1121.24)
    assert result.actual_pnl == pytest.approx(-1366.0)


# =========================================================================
# 2. compute_pnl_attribution — zero change
# =========================================================================

def test_pnl_attribution_zero_change():
    result = compute_pnl_attribution(
        entry_delta=0.35,
        entry_gamma=0.005,
        entry_theta=-0.8,
        entry_vega=12.0,
        underlying_change=0.0,
        iv_change=0.0,
        days_elapsed=0,
        actual_pnl=-50.0,
        multiplier=100,
        quantity=1,
    )
    assert result.delta_pnl == 0.0
    assert result.gamma_pnl == 0.0
    assert result.theta_pnl == 0.0
    assert result.vega_pnl == 0.0
    assert result.model_pnl == 0.0
    assert result.actual_pnl == pytest.approx(-50.0)
    assert result.unexplained_pnl == pytest.approx(-50.0)


# =========================================================================
# 3. compute_trade_pnl — basic
# =========================================================================

def test_trade_pnl_basic():
    result = compute_trade_pnl([
        LegPnLInput(quantity=1, entry_price=18.5, current_price=59.225, open_price=57.0, multiplier=100),
        LegPnLInput(quantity=-1, entry_price=10.0, current_price=45.65, open_price=43.0, multiplier=100),
    ])
    # Leg 1 inception: (59.225 - 18.5) * 1 * 100 = 4072.5
    # Leg 2 inception: (45.65 - 10.0) * (-1) * 100 = -3565.0
    assert result.pnl_inception == pytest.approx(507.5)
    # Leg 1 today: (59.225 - 57.0) * 1 * 100 = 222.5
    # Leg 2 today: (45.65 - 43.0) * (-1) * 100 = -265.0
    assert result.pnl_today == pytest.approx(-42.5)
    # entry_cost = |18.5*1*100| + |10.0*1*100| = 2850.0
    assert result.entry_cost == pytest.approx(2850.0)
    # inception_pct = 507.5 / 2850.0
    assert result.pnl_inception_pct == pytest.approx(507.5 / 2850.0, abs=1e-4)


# =========================================================================
# 4. compute_trade_pnl — empty legs
# =========================================================================

def test_trade_pnl_empty_legs():
    result = compute_trade_pnl([])
    assert result.pnl_inception == 0.0
    assert result.pnl_today == 0.0
    assert result.entry_cost == 0.0
    assert result.pnl_inception_pct == 0.0
    assert result.pnl_today_pct == 0.0
    assert result.legs == []


# =========================================================================
# 5. compute_structure_risk — iron condor
# =========================================================================

def test_structure_risk_iron_condor():
    legs = [
        _leg(540, "put", "STO"),
        _leg(535, "put", "BTO"),
        _leg(560, "call", "STO"),
        _leg(565, "call", "BTO"),
    ]
    result = compute_structure_risk(
        "iron_condor", legs, net_credit_debit=2.0, multiplier=100, contracts=1,
    )
    assert result.wing_width == pytest.approx(5.0)
    assert result.max_profit == pytest.approx(200.0)
    assert result.max_loss == pytest.approx(300.0)
    assert result.risk_reward_ratio == pytest.approx(200.0 / 300.0, abs=1e-4)
    assert result.breakeven_low == pytest.approx(538.0)
    assert result.breakeven_high == pytest.approx(562.0)
    assert result.risk_profile == "defined"


# =========================================================================
# 6. compute_structure_risk — debit spread (NVDA case)
# =========================================================================

def test_structure_risk_debit_spread():
    legs = [
        _leg(130, "call", "BTO", expiration="2027-01-15"),
        _leg(150, "call", "STO", expiration="2027-01-15"),
    ]
    result = compute_structure_risk(
        "debit_spread", legs, net_credit_debit=-8.5, multiplier=100, contracts=1,
    )
    assert result.max_loss == pytest.approx(850.0)
    assert result.wing_width == pytest.approx(20.0)
    assert result.max_profit == pytest.approx(1150.0)
    assert result.risk_reward_ratio == pytest.approx(1150.0 / 850.0, abs=1e-4)
    assert result.breakeven_low == pytest.approx(138.5)
    assert result.risk_profile == "defined"


# =========================================================================
# 7. compute_structure_risk — long call
# =========================================================================

def test_structure_risk_long_call():
    legs = [_leg(100, "call", "BTO")]
    result = compute_structure_risk("long_option", legs, net_credit_debit=-5.0)
    assert result.max_loss == pytest.approx(500.0)
    assert result.max_profit is None  # unlimited
    assert result.breakeven_low == pytest.approx(105.0)


# =========================================================================
# 8. compute_structure_risk — credit spread (bull put)
# =========================================================================

def test_structure_risk_credit_spread_bull_put():
    legs = [
        _leg(550, "put", "STO"),
        _leg(545, "put", "BTO"),
    ]
    result = compute_structure_risk("credit_spread", legs, net_credit_debit=1.5)
    assert result.max_profit == pytest.approx(150.0)
    assert result.max_loss == pytest.approx(350.0)
    assert result.wing_width == pytest.approx(5.0)
    assert result.breakeven_low == pytest.approx(548.5)


# =========================================================================
# 9. compute_portfolio_analytics — basic
# =========================================================================

def test_portfolio_analytics_basic():
    positions = [
        PositionSnapshot(
            ticker="SPY", entry_price=2.0, current_price=1.5, open_price=1.8,
            quantity=1, delta=0.3, gamma=0.01, theta=-0.05, vega=0.1,
            underlying_price=550.0, max_loss=500.0,
        ),
        PositionSnapshot(
            ticker="SPY", entry_price=3.0, current_price=2.5, open_price=2.8,
            quantity=-1, delta=-0.4, gamma=0.02, theta=0.08, vega=-0.15,
            underlying_price=550.0, max_loss=300.0,
        ),
    ]
    result = compute_portfolio_analytics(positions, account_nlv=50000.0)
    # net_delta = 0.3*1 + (-0.4)*(-1) = 0.7
    assert result.net_delta == pytest.approx(0.7)
    # total_margin_at_risk = 500 + 300 = 800
    assert result.total_margin_at_risk == pytest.approx(800.0)
    # by_underlying has SPY with position_count = 2
    assert "SPY" in result.by_underlying
    assert result.by_underlying["SPY"].position_count == 2


# =========================================================================
# 10. evaluate_circuit_breakers — all clear
# =========================================================================

def test_circuit_breakers_all_clear():
    result = evaluate_circuit_breakers(daily_pnl_pct=-0.5, weekly_pnl_pct=-1.0, vix=18.0)
    assert result.is_halted is False
    assert result.is_paused is False
    assert result.can_open_new is True
    assert len(result.breakers_tripped) == 0


# =========================================================================
# 11. evaluate_circuit_breakers — daily loss halt
# =========================================================================

def test_circuit_breakers_daily_loss_halt():
    result = evaluate_circuit_breakers(daily_pnl_pct=-3.0, weekly_pnl_pct=-1.0)
    assert result.is_halted is True
    assert result.can_open_new is False
    assert len(result.breakers_tripped) == 1
    assert result.breakers_tripped[0].name == "daily_loss"
    assert result.breakers_tripped[0].severity == "halt"


# =========================================================================
# 12. evaluate_circuit_breakers — consecutive pause
# =========================================================================

def test_circuit_breakers_consecutive_pause():
    result = evaluate_circuit_breakers(
        daily_pnl_pct=-0.5, weekly_pnl_pct=-1.0, consecutive_losses=3,
    )
    assert result.is_paused is True
    assert result.is_halted is False
    assert result.can_open_new is False


# =========================================================================
# 13. evaluate_circuit_breakers — VIX halt
# =========================================================================

def test_circuit_breakers_vix_halt():
    result = evaluate_circuit_breakers(daily_pnl_pct=0.0, weekly_pnl_pct=0.0, vix=40.0)
    assert result.is_halted is True
    breaker_names = [b.name for b in result.breakers_tripped]
    assert "vix_halt" in breaker_names
