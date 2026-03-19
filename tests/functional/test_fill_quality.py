"""Functional tests: fill quality (bid-ask spread survival)."""
import pytest
from market_analyzer.validation.models import Severity
from market_analyzer.validation.profitability_audit import check_fill_quality


class TestFillQualityFunctional:
    @pytest.mark.daily
    def test_spy_etf_typical_spread_passes(self) -> None:
        """SPY options typically have 0.3-1% spread — well within threshold."""
        result = check_fill_quality(avg_bid_ask_spread_pct=0.5)
        assert result.severity == Severity.PASS

    @pytest.mark.daily
    def test_illiquid_name_wide_spread_fails(self) -> None:
        """Low-volume ticker with 4% spread — hard to get filled at mid."""
        result = check_fill_quality(avg_bid_ask_spread_pct=4.5)
        assert result.severity == Severity.FAIL

    @pytest.mark.daily
    def test_elevated_spread_warns(self) -> None:
        """2% spread — viable but risky at natural fill."""
        result = check_fill_quality(avg_bid_ask_spread_pct=2.0)
        assert result.severity == Severity.WARN

    def test_exact_fail_boundary(self) -> None:
        """3.0% is still WARN, 3.1% is FAIL."""
        assert check_fill_quality(3.0).severity == Severity.WARN
        assert check_fill_quality(3.1).severity == Severity.FAIL
