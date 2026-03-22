"""Tests for profitability audit checks."""
from datetime import date, timedelta
import pytest

from income_desk.trade_spec_factory import build_iron_condor
from income_desk.validation.models import Severity
from income_desk.validation.profitability_audit import (
    check_commission_drag,
    check_fill_quality,
    check_margin_efficiency,
)
from income_desk.trade_lifecycle import compute_income_yield


def _ic_spec():
    exp = date.today() + timedelta(days=30)
    return build_iron_condor(
        ticker="SPY", underlying_price=580.0,
        short_put=570.0, long_put=565.0,
        short_call=590.0, long_call=595.0,
        expiration=exp.isoformat(),
    )


class TestCommissionDrag:
    def test_healthy_credit_passes(self) -> None:
        """$1.50 credit on 4-leg IC — fees are ~3.5% of credit."""
        result = check_commission_drag(_ic_spec(), entry_credit=1.50)
        assert result.severity == Severity.PASS
        assert result.name == "commission_drag"

    def test_thin_credit_warns(self) -> None:
        """$0.40 credit on 4-leg IC — fees eat ~13% of credit (10–25% → WARN)."""
        result = check_commission_drag(_ic_spec(), entry_credit=0.40)
        assert result.severity == Severity.WARN

    def test_microscopic_credit_fails(self) -> None:
        """$0.20 credit on 4-leg IC — fees exceed credit entirely."""
        result = check_commission_drag(_ic_spec(), entry_credit=0.20)
        assert result.severity == Severity.FAIL

    def test_result_includes_values(self) -> None:
        result = check_commission_drag(_ic_spec(), entry_credit=1.50)
        assert result.value is not None   # net credit after fees
        assert result.threshold is not None  # commission drag amount


class TestFillQuality:
    def test_tight_spread_passes(self) -> None:
        result = check_fill_quality(avg_bid_ask_spread_pct=0.8)
        assert result.severity == Severity.PASS

    def test_moderate_spread_warns(self) -> None:
        result = check_fill_quality(avg_bid_ask_spread_pct=2.0)
        assert result.severity == Severity.WARN

    def test_wide_spread_fails(self) -> None:
        result = check_fill_quality(avg_bid_ask_spread_pct=4.0)
        assert result.severity == Severity.FAIL

    def test_boundary_at_3pct(self) -> None:
        at_boundary = check_fill_quality(avg_bid_ask_spread_pct=3.0)
        above_boundary = check_fill_quality(avg_bid_ask_spread_pct=3.1)
        assert at_boundary.severity == Severity.WARN
        assert above_boundary.severity == Severity.FAIL


class TestMarginEfficiency:
    def test_good_roc_passes(self) -> None:
        # $3.00 credit on a 5-wide IC → ~18% annualized ROC → PASS (≥15%)
        spec = _ic_spec()
        income = compute_income_yield(spec, entry_credit=3.00, contracts=1)
        assert income is not None, "compute_income_yield returned None for standard IC"
        result = check_margin_efficiency(income)
        assert result.severity == Severity.PASS

    def test_marginal_roc_warns(self) -> None:
        # $2.50 credit on a 5-wide IC → ~12% annualized ROC → WARN (10–15%)
        spec = _ic_spec()
        income = compute_income_yield(spec, entry_credit=2.50, contracts=1)
        assert income is not None, "compute_income_yield returned None for standard IC"
        result = check_margin_efficiency(income)
        assert result.severity == Severity.WARN

    def test_result_shows_annualized_roc(self) -> None:
        spec = _ic_spec()
        income = compute_income_yield(spec, entry_credit=3.00)
        assert income is not None, "compute_income_yield returned None for standard IC"
        result = check_margin_efficiency(income)
        assert result.value is not None   # annualized ROC %
        assert "%" in result.message
