"""Tests for DTE optimizer."""

from datetime import date, timedelta

import pytest

from market_analyzer.features.dte_optimizer import DTERecommendation, select_optimal_dte
from market_analyzer.models.vol_surface import (
    SkewSlice,
    TermStructurePoint,
    VolatilitySurface,
)


def _make_vol_surface(
    term_points: list[tuple[int, float]],  # (dte, atm_iv)
) -> VolatilitySurface:
    """Build a minimal vol surface from (dte, atm_iv) tuples."""
    today = date(2026, 3, 20)
    exps = [today + timedelta(days=dte) for dte, _ in term_points]
    ts = [
        TermStructurePoint(
            expiration=today + timedelta(days=dte),
            days_to_expiry=dte,
            atm_iv=iv,
            atm_strike=580.0,
        )
        for dte, iv in term_points
    ]
    front_iv = term_points[0][1]
    back_iv = term_points[-1][1]
    slope = (back_iv - front_iv) / front_iv if front_iv > 0 else 0

    skew = SkewSlice(
        expiration=exps[0], days_to_expiry=term_points[0][0], atm_iv=front_iv,
        otm_put_iv=front_iv + 0.04, otm_call_iv=front_iv + 0.02,
        put_skew=0.04, call_skew=0.02, skew_ratio=2.0,
    )

    return VolatilitySurface(
        ticker="SPY", as_of_date=today, underlying_price=580.0,
        expirations=exps, term_structure=ts,
        front_iv=front_iv, back_iv=back_iv, term_slope=slope,
        is_contango=back_iv > front_iv, is_backwardation=front_iv > back_iv,
        skew_by_expiry=[skew],
        calendar_edge_score=0.4,
        best_calendar_expiries=(exps[0], exps[-1]) if len(exps) >= 2 else None,
        iv_differential_pct=(front_iv - back_iv) / back_iv * 100 if back_iv > 0 else 0,
        total_contracts=500, avg_bid_ask_spread_pct=0.8,
        data_quality="good", summary="test",
    )


class TestSelectOptimalDTE:
    def test_picks_highest_theta_proxy(self) -> None:
        """Higher IV at shorter DTE -> higher theta proxy -> selected."""
        vs = _make_vol_surface([(21, 0.28), (30, 0.22), (45, 0.20)])
        result = select_optimal_dte(vs, regime_id=1)
        assert result is not None
        assert isinstance(result, DTERecommendation)
        # 21 DTE: 0.28 * sqrt(1/21) = 0.0611
        # 30 DTE: 0.22 * sqrt(1/30) = 0.0402
        # 45 DTE: 0.20 * sqrt(1/45) = 0.0298
        # With R1 preference (30-45), 30 and 45 DTE get 10% bonus
        # 30 DTE adjusted: 0.0402 * 1.1 = 0.0442
        # 21 DTE raw: 0.0611 — still highest
        assert result.recommended_dte == 21

    def test_regime_preference_as_tiebreaker(self) -> None:
        """When theta proxies are close, regime preference decides."""
        vs = _make_vol_surface([(25, 0.22), (35, 0.22)])
        result = select_optimal_dte(vs, regime_id=1)
        assert result is not None
        # 25 DTE: 0.22 * sqrt(1/25) = 0.044
        # 35 DTE: 0.22 * sqrt(1/35) = 0.0372
        # With R1 pref (30-45): 35 DTE gets 10% bonus = 0.0409
        # 25 DTE raw: 0.044 — still higher
        # Actually 25 still wins. Let's make them closer:
        vs2 = _make_vol_surface([(28, 0.215), (35, 0.22)])
        result2 = select_optimal_dte(vs2, regime_id=1)
        assert result2 is not None
        # 28 DTE: 0.215 * sqrt(1/28) = 0.0406
        # 35 DTE: 0.22 * sqrt(1/35) = 0.0372 * 1.1 = 0.0409
        # Very close — regime preference gives 35 DTE the edge
        assert result2.recommended_dte == 35

    def test_r2_prefers_shorter_dte(self) -> None:
        """R2 prefers 21-30 DTE range."""
        vs = _make_vol_surface([(21, 0.30), (30, 0.28), (45, 0.25)])
        result = select_optimal_dte(vs, regime_id=2)
        assert result is not None
        assert result.recommended_dte <= 30

    def test_r4_prefers_shortest_dte(self) -> None:
        """R4 prefers 14-21 DTE range."""
        vs = _make_vol_surface([(14, 0.35), (21, 0.32), (30, 0.28)])
        result = select_optimal_dte(vs, regime_id=4)
        assert result is not None
        assert result.recommended_dte <= 21

    def test_min_max_dte_filter(self) -> None:
        """Only consider DTEs within min/max range."""
        vs = _make_vol_surface([(7, 0.40), (14, 0.35), (30, 0.22), (60, 0.18)])
        result = select_optimal_dte(vs, min_dte=14, max_dte=45)
        assert result is not None
        assert 14 <= result.recommended_dte <= 45

    def test_no_valid_candidates_returns_none(self) -> None:
        """No expirations in range -> None."""
        vs = _make_vol_surface([(7, 0.40)])
        result = select_optimal_dte(vs, min_dte=14, max_dte=45)
        assert result is None

    def test_all_candidates_populated(self) -> None:
        """all_candidates list contains all evaluated DTEs."""
        vs = _make_vol_surface([(21, 0.28), (30, 0.22), (45, 0.20)])
        result = select_optimal_dte(vs)
        assert result is not None
        assert len(result.all_candidates) == 3

    def test_rationale_contains_dte(self) -> None:
        vs = _make_vol_surface([(30, 0.22)])
        result = select_optimal_dte(vs)
        assert result is not None
        assert "30" in result.rationale

    def test_regime_preference_string(self) -> None:
        vs = _make_vol_surface([(30, 0.22)])
        result = select_optimal_dte(vs, regime_id=2)
        assert result is not None
        assert "21-30" in result.regime_preference

    def test_serialization(self) -> None:
        vs = _make_vol_surface([(30, 0.22)])
        result = select_optimal_dte(vs)
        assert result is not None
        d = result.model_dump()
        assert "recommended_dte" in d
        assert "all_candidates" in d

    def test_backwardation_surface(self) -> None:
        """Higher front IV in backwardation -> shorter DTE strongly preferred."""
        vs = _make_vol_surface([(21, 0.35), (30, 0.28), (45, 0.22)])
        result = select_optimal_dte(vs, regime_id=2)
        assert result is not None
        assert result.recommended_dte == 21
        assert result.iv_at_expiration == 0.35
