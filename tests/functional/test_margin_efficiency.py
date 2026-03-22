"""Functional tests: margin efficiency (return on capital)."""
import pytest
from datetime import date, timedelta

from income_desk.trade_spec_factory import build_iron_condor
from income_desk.trade_lifecycle import compute_income_yield
from income_desk.validation.models import Severity
from income_desk.validation.profitability_audit import check_margin_efficiency


def _ic(wing_width=5.0, underlying=580.0):
    exp = date.today() + timedelta(days=30)
    return build_iron_condor(
        ticker="SPY", underlying_price=underlying,
        short_put=underlying - 10, long_put=underlying - 10 - wing_width,
        short_call=underlying + 10, long_call=underlying + 10 + wing_width,
        expiration=exp.isoformat(),
    )


class TestMarginEfficiencyFunctional:
    @pytest.mark.daily
    def test_standard_ic_30dte_passes_roc_gate(self) -> None:
        """5-wide IC, $3.00 credit, 30 DTE → ROC should exceed 15% annualized."""
        income = compute_income_yield(_ic(), entry_credit=3.00)
        result = check_margin_efficiency(income)
        assert result.severity == Severity.PASS
        assert result.value is not None
        assert result.value > 0

    def test_narrow_wing_low_credit_fails_roc(self) -> None:
        """1-wide IC with $0.10 credit → capital-inefficient, below threshold."""
        ic = build_iron_condor(
            ticker="SPY", underlying_price=580.0,
            short_put=579.0, long_put=578.0,
            short_call=581.0, long_call=582.0,
            expiration=(date.today() + timedelta(days=30)).isoformat(),
        )
        income = compute_income_yield(ic, entry_credit=0.10)
        result = check_margin_efficiency(income)
        assert result.severity == Severity.FAIL

    def test_roc_value_is_annualized(self) -> None:
        """Annualized ROC for 30-DTE trade = monthly_roc x 12."""
        income = compute_income_yield(_ic(), entry_credit=3.00)
        result = check_margin_efficiency(income)
        # Value should be the annualized ROC %, not monthly
        assert result.value == pytest.approx(income.annualized_roc_pct, abs=0.1)
