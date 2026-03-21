"""Tests for interest rate risk assessment."""
from __future__ import annotations

import pytest

from market_analyzer.features.rate_risk import (
    RateRiskLevel,
    RateRiskAssessment,
    PortfolioRateRisk,
    assess_rate_risk,
    assess_portfolio_rate_risk,
)


# ---------------------------------------------------------------------------
# Single ticker rate risk
# ---------------------------------------------------------------------------

class TestTLTHighSensitivity:
    def test_tlt_has_high_sensitivity(self):
        """TLT is classified as high rate sensitivity."""
        result = assess_rate_risk("TLT")
        assert result.rate_sensitivity == "high"

    def test_tlt_has_nonzero_duration(self):
        """TLT has ~17 year duration."""
        result = assess_rate_risk("TLT")
        assert result.estimated_duration > 10.0

    def test_tlt_negative_yield_correlation(self):
        """TLT prices fall when yields rise → negative correlation."""
        result = assess_rate_risk("TLT")
        assert result.yield_correlation < -0.5

    def test_tlt_elevated_risk_stable_yields(self):
        """TLT has at least ELEVATED risk even in stable yield environment."""
        result = assess_rate_risk("TLT", current_yield_change_bps=0)
        assert result.rate_risk_level in (RateRiskLevel.ELEVATED, RateRiskLevel.HIGH)

    def test_tlt_high_risk_rising_yields(self):
        """TLT is HIGH risk when yields are rising sharply."""
        result = assess_rate_risk("TLT", current_yield_change_bps=30)
        assert result.rate_risk_level == RateRiskLevel.HIGH

    def test_tlt_100bp_impact_negative(self):
        """TLT price falls when yields rise → impact_per_100bp should be negative."""
        result = assess_rate_risk("TLT")
        assert result.impact_per_100bp < 0

    def test_tlt_100bp_impact_significant(self):
        """TLT ~17y duration → ~17% price drop per 100bp (≈ -0.17)."""
        result = assess_rate_risk("TLT")
        assert result.impact_per_100bp < -0.10  # At least 10% impact per 100bp

    def test_tlt_recommendation_avoid_long_duration(self):
        """In high-risk condition, recommendation = avoid_long_duration."""
        result = assess_rate_risk("TLT", current_yield_change_bps=25)
        assert result.recommendation == "avoid_long_duration"


class TestSPYLowSensitivity:
    def test_spy_has_low_sensitivity(self):
        """SPY has low rate sensitivity."""
        result = assess_rate_risk("SPY")
        assert result.rate_sensitivity == "low"

    def test_spy_zero_duration(self):
        """SPY (equity) has 0 bond duration."""
        result = assess_rate_risk("SPY")
        assert result.estimated_duration == 0.0

    def test_spy_low_risk(self):
        """SPY has LOW rate risk in normal environment."""
        result = assess_rate_risk("SPY", current_yield_change_bps=5)
        assert result.rate_risk_level == RateRiskLevel.LOW

    def test_spy_no_action_recommendation(self):
        """SPY with low rate risk → no_action recommendation."""
        result = assess_rate_risk("SPY", current_yield_change_bps=5)
        assert result.recommendation == "no_action"

    def test_spy_impact_small(self):
        """SPY 100bp impact should be small (< 5% in magnitude)."""
        result = assess_rate_risk("SPY")
        assert abs(result.impact_per_100bp) < 0.05


class TestUtilitiesModerate:
    def test_xlu_moderate_sensitivity(self):
        """Utilities are moderately rate sensitive."""
        result = assess_rate_risk("XLU")
        assert result.rate_sensitivity == "moderate"

    def test_xlu_negative_yield_correlation(self):
        """Utilities have negative yield correlation (compete with bonds)."""
        result = assess_rate_risk("XLU")
        assert result.yield_correlation < 0

    def test_xlu_elevated_in_volatile_yields(self):
        """XLU in volatile rate environment should be ELEVATED."""
        result = assess_rate_risk("XLU", current_yield_change_bps=20)
        assert result.rate_risk_level in (RateRiskLevel.ELEVATED, RateRiskLevel.HIGH)


class TestFinancialsPositiveCorr:
    def test_xlf_positive_yield_correlation(self):
        """Banks benefit from rising rates → positive yield correlation."""
        result = assess_rate_risk("XLF")
        assert result.yield_correlation > 0

    def test_xlf_low_risk_rising_yields(self):
        """XLF should have low-to-moderate risk in rising rate environment (it benefits)."""
        result = assess_rate_risk("XLF", current_yield_change_bps=20)
        assert result.rate_risk_level in (RateRiskLevel.LOW, RateRiskLevel.MODERATE)


class TestUnknownTicker:
    def test_unknown_ticker_defaults_to_low(self):
        """Unknown tickers should default to low sensitivity."""
        result = assess_rate_risk("UNKNOWN_TICKER_XYZ")
        assert result.rate_sensitivity == "low"
        assert result.rate_risk_level == RateRiskLevel.LOW

    def test_unknown_ticker_no_duration(self):
        """Unknown ticker should have 0 duration."""
        result = assess_rate_risk("UNKNOWN_TICKER_XYZ")
        assert result.estimated_duration == 0.0


class TestYieldTrends:
    def test_stable_yields_no_rising(self):
        """0 bps → stable trend."""
        result = assess_rate_risk("TLT", current_yield_change_bps=0)
        assert result.current_yield_trend == "stable"

    def test_rising_yields_label(self):
        """+10 bps → rising trend (below volatile threshold of 15bp)."""
        result = assess_rate_risk("SPY", current_yield_change_bps=10)
        assert result.current_yield_trend == "rising"

    def test_falling_yields_label(self):
        """-10 bps → falling trend (below volatile threshold of 15bp)."""
        result = assess_rate_risk("SPY", current_yield_change_bps=-10)
        assert result.current_yield_trend == "falling"

    def test_volatile_threshold_15bp(self):
        """>15 bps absolute → volatile."""
        result = assess_rate_risk("SPY", current_yield_change_bps=20)
        assert result.current_yield_trend == "volatile"

    def test_volatile_negative_also(self):
        """-20 bps → volatile (absolute > 15)."""
        result = assess_rate_risk("TLT", current_yield_change_bps=-20)
        assert result.current_yield_trend == "volatile"


class TestRateRiskResultFields:
    def test_has_all_required_fields(self):
        """RateRiskAssessment should have all required fields."""
        result = assess_rate_risk("SPY")
        assert hasattr(result, "ticker")
        assert hasattr(result, "rate_sensitivity")
        assert hasattr(result, "estimated_duration")
        assert hasattr(result, "yield_correlation")
        assert hasattr(result, "rate_risk_level")
        assert hasattr(result, "impact_per_25bp")
        assert hasattr(result, "impact_per_100bp")
        assert hasattr(result, "current_yield_trend")
        assert hasattr(result, "reasons")
        assert hasattr(result, "recommendation")
        assert hasattr(result, "summary")

    def test_25bp_impact_is_quarter_of_100bp(self):
        """For bond-like instruments, 25bp impact ≈ 25% of 100bp impact."""
        result = assess_rate_risk("TLT")
        assert result.impact_per_25bp == pytest.approx(result.impact_per_100bp / 4, rel=0.05)

    def test_reasons_list_nonempty(self):
        """Reasons should always be populated."""
        result = assess_rate_risk("GLD")
        assert len(result.reasons) > 0

    def test_summary_contains_ticker(self):
        """Summary should mention the ticker."""
        result = assess_rate_risk("QQQ")
        assert "QQQ" in result.summary


# ---------------------------------------------------------------------------
# Portfolio rate risk
# ---------------------------------------------------------------------------

class TestPortfolioRateRisk:
    def test_portfolio_with_tlt_has_high_duration(self):
        """Portfolio with TLT should have significant duration."""
        result = assess_portfolio_rate_risk(["TLT", "SPY", "QQQ"])
        assert result.portfolio_duration > 0

    def test_all_equities_low_duration(self):
        """All-equity portfolio should have near-zero duration."""
        result = assess_portfolio_rate_risk(["SPY", "QQQ", "IWM", "GLD"])
        assert result.portfolio_duration == pytest.approx(0.0, abs=0.01)

    def test_tlt_in_high_risk_tickers(self):
        """TLT in rising rate environment should appear in high_risk_tickers."""
        result = assess_portfolio_rate_risk(
            ["TLT", "SPY", "QQQ"],
            current_yield_change_bps=30,
        )
        assert "TLT" in result.high_risk_tickers

    def test_spy_not_in_high_risk(self):
        """SPY should not be in high_risk_tickers in normal environment."""
        result = assess_portfolio_rate_risk(["SPY", "QQQ", "IWM"])
        assert "SPY" not in result.high_risk_tickers

    def test_portfolio_impact_weighted(self):
        """Portfolio impact should be weighted average of individual impacts."""
        result = assess_portfolio_rate_risk(["TLT", "SPY"], weights={"TLT": 0.5, "SPY": 0.5})
        tlt = assess_rate_risk("TLT")
        spy = assess_rate_risk("SPY")
        expected = 0.5 * tlt.impact_per_100bp + 0.5 * spy.impact_per_100bp
        assert result.estimated_portfolio_impact_100bp == pytest.approx(expected, rel=0.05)

    def test_equal_weights_when_none(self):
        """When no weights provided, should use equal weights."""
        result = assess_portfolio_rate_risk(["SPY", "QQQ"])
        # Should not raise; just check fields
        assert result.portfolio_duration == pytest.approx(0.0, abs=0.01)
        assert result.estimated_portfolio_impact_100bp is not None

    def test_empty_tickers_returns_no_action(self):
        """Empty ticker list → no_action."""
        result = assess_portfolio_rate_risk([])
        assert result.recommendation == "no_action"

    def test_ticker_risks_length_matches_input(self):
        """ticker_risks list length should match number of input tickers."""
        tickers = ["SPY", "TLT", "GLD"]
        result = assess_portfolio_rate_risk(tickers)
        assert len(result.ticker_risks) == len(tickers)

    def test_bond_heavy_portfolio_high_sensitivity(self):
        """Portfolio >30% in high-sensitivity bonds → portfolio_rate_sensitivity='high'."""
        # TLT, IEF, LQD are all "high" sensitivity
        result = assess_portfolio_rate_risk(["TLT", "TLT", "TLT", "SPY"])
        # 3/4 = 75% high sensitivity
        assert result.portfolio_rate_sensitivity == "high"

    def test_recommendation_reduce_with_high_risk(self):
        """Bond-heavy portfolio in rising rates → recommendation involves reducing exposure."""
        result = assess_portfolio_rate_risk(
            ["TLT", "LQD", "SPY"],
            current_yield_change_bps=30,
        )
        assert result.recommendation != "no_action"

    def test_summary_is_nonempty_string(self):
        """Portfolio summary should be a non-empty string."""
        result = assess_portfolio_rate_risk(["SPY", "TLT"])
        assert isinstance(result.summary, str)
        assert len(result.summary) > 0
