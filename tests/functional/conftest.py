"""Shared fixtures for functional tests.

All fixtures use synthetic data — no broker required.
Designed to represent realistic daily trading conditions for SPY/small account.
"""
from datetime import date, timedelta

import pytest

from income_desk.models.regime import RegimeID, RegimeResult
from income_desk.models.vol_surface import SkewSlice, TermStructurePoint, VolatilitySurface
from income_desk.trade_spec_factory import build_iron_condor, build_credit_spread


# ── Regime fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def r1_regime() -> RegimeResult:
    """R1 Low-Vol Mean Reverting — ideal income environment."""
    return RegimeResult(
        ticker="SPY", regime=RegimeID(1), confidence=0.82,
        regime_probabilities={1: 0.82, 2: 0.10, 3: 0.05, 4: 0.03},
        as_of_date=date(2026, 3, 18), model_version="test", trend_direction=None,
    )


@pytest.fixture
def r2_regime() -> RegimeResult:
    """R2 High-Vol Mean Reverting — wider wings, selective income."""
    return RegimeResult(
        ticker="SPY", regime=RegimeID(2), confidence=0.75,
        regime_probabilities={1: 0.15, 2: 0.75, 3: 0.07, 4: 0.03},
        as_of_date=date(2026, 3, 18), model_version="test", trend_direction=None,
    )


@pytest.fixture
def r4_regime() -> RegimeResult:
    """R4 High-Vol Trending — hard stop for income strategies."""
    return RegimeResult(
        ticker="SPY", regime=RegimeID(4), confidence=0.70,
        regime_probabilities={1: 0.05, 2: 0.10, 3: 0.15, 4: 0.70},
        as_of_date=date(2026, 3, 18), model_version="test", trend_direction=None,
    )


# ── Vol surface fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def normal_vol_surface() -> VolatilitySurface:
    """Normal conditions: IV=22%, tight spread, good quality."""
    today = date(2026, 3, 18)
    exps = [today + timedelta(days=30), today + timedelta(days=60)]
    front_iv, back_iv = 0.22, 0.20
    slope = (back_iv - front_iv) / front_iv
    skew = SkewSlice(
        expiration=exps[0], days_to_expiry=30, atm_iv=front_iv,
        otm_put_iv=front_iv + 0.04, otm_call_iv=front_iv + 0.02,
        put_skew=0.04, call_skew=0.02, skew_ratio=2.0,
    )
    return VolatilitySurface(
        ticker="SPY", as_of_date=today, underlying_price=580.0,
        expirations=exps, term_structure=[
            TermStructurePoint(expiration=exps[0], days_to_expiry=30, atm_iv=front_iv, atm_strike=580.0),
            TermStructurePoint(expiration=exps[1], days_to_expiry=60, atm_iv=back_iv, atm_strike=580.0),
        ],
        front_iv=front_iv, back_iv=back_iv, term_slope=slope,
        is_contango=back_iv > front_iv, is_backwardation=front_iv > back_iv,
        skew_by_expiry=[skew],
        calendar_edge_score=0.4,
        best_calendar_expiries=(exps[0], exps[1]),
        iv_differential_pct=(front_iv - back_iv) / back_iv * 100,
        total_contracts=500, avg_bid_ask_spread_pct=0.8,
        data_quality="good", summary="test normal conditions",
    )


@pytest.fixture
def high_vol_surface() -> VolatilitySurface:
    """Elevated IV: 35% front, backwardation, wider spread."""
    today = date(2026, 3, 18)
    exps = [today + timedelta(days=30), today + timedelta(days=60)]
    front_iv, back_iv = 0.35, 0.28
    slope = (back_iv - front_iv) / front_iv
    skew = SkewSlice(
        expiration=exps[0], days_to_expiry=30, atm_iv=front_iv,
        otm_put_iv=front_iv + 0.08, otm_call_iv=front_iv + 0.03,
        put_skew=0.08, call_skew=0.03, skew_ratio=2.7,
    )
    return VolatilitySurface(
        ticker="SPY", as_of_date=today, underlying_price=580.0,
        expirations=exps, term_structure=[
            TermStructurePoint(expiration=exps[0], days_to_expiry=30, atm_iv=front_iv, atm_strike=580.0),
            TermStructurePoint(expiration=exps[1], days_to_expiry=60, atm_iv=back_iv, atm_strike=580.0),
        ],
        front_iv=front_iv, back_iv=back_iv, term_slope=slope,
        is_contango=False, is_backwardation=True,
        skew_by_expiry=[skew],
        calendar_edge_score=0.7,
        best_calendar_expiries=(exps[0], exps[1]),
        iv_differential_pct=(front_iv - back_iv) / back_iv * 100,
        total_contracts=800, avg_bid_ask_spread_pct=1.2,
        data_quality="good", summary="test high vol conditions",
    )


# ── Trade spec fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def standard_ic_spec():
    """Standard SPY iron condor: 5-wide wings, 20 OTM, 30 DTE."""
    exp = date(2026, 4, 17)
    return build_iron_condor(
        ticker="SPY", underlying_price=580.0,
        short_put=560.0, long_put=555.0,
        short_call=600.0, long_call=605.0,
        expiration=exp.isoformat(),
    )


@pytest.fixture
def wide_ic_spec():
    """Wide SPY iron condor: 10-wide wings for R2 environment."""
    exp = date(2026, 4, 17)
    return build_iron_condor(
        ticker="SPY", underlying_price=580.0,
        short_put=565.0, long_put=555.0,
        short_call=595.0, long_call=605.0,
        expiration=exp.isoformat(),
    )


@pytest.fixture
def credit_spread_spec():
    """Bull put spread: 5-wide, 30 DTE."""
    exp = date(2026, 4, 17)
    return build_credit_spread(
        ticker="SPY", underlying_price=580.0,
        option_type="put",
        short_strike=570.0, long_strike=565.0,
        expiration=exp.isoformat(),
    )


# ── Account context fixtures ─────────────────────────────────────────────────

@pytest.fixture
def small_account():
    """50K taxable account context."""
    return {
        "account_nlv": 50_000.0,
        "account_peak": 52_000.0,
        "available_buying_power": 35_000.0,
        "max_positions": 5,
    }


@pytest.fixture
def ira_account():
    """200K IRA account context."""
    return {
        "account_nlv": 200_000.0,
        "account_peak": 205_000.0,
        "available_buying_power": 120_000.0,
        "max_positions": 8,
    }
