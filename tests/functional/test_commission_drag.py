"""Functional tests: commission drag at realistic account sizes."""
import pytest
from datetime import date, timedelta

from market_analyzer.trade_spec_factory import build_iron_condor
from market_analyzer.validation.models import Severity
from market_analyzer.validation.profitability_audit import check_commission_drag


def _ic(wing_width=5.0):
    exp = date.today() + timedelta(days=30)
    mid = 580.0
    return build_iron_condor(
        ticker="SPY", underlying_price=mid,
        short_put=mid - 10, long_put=mid - 10 - wing_width,
        short_call=mid + 10, long_call=mid + 10 + wing_width,
        expiration=exp.isoformat(),
    )


class TestCommissionDragFunctional:
    @pytest.mark.daily
    def test_minimum_viable_credit_for_4leg_ic(self) -> None:
        """4-leg IC round trip = $5.20 fees. Minimum viable credit to pass: >$0.52/share (i.e., fees < 10%)."""
        min_viable = check_commission_drag(_ic(), entry_credit=0.53)
        too_thin = check_commission_drag(_ic(), entry_credit=0.51)
        assert min_viable.severity == Severity.PASS
        assert too_thin.severity in (Severity.WARN, Severity.FAIL)

    @pytest.mark.daily
    def test_typical_ic_credit_1_50_passes(self) -> None:
        """$1.50 credit = $150/contract. $5.20 fees = 3.5% drag. Well under 10% threshold."""
        result = check_commission_drag(_ic(), entry_credit=1.50)
        assert result.severity == Severity.PASS

    @pytest.mark.daily
    def test_scalping_5_cent_move_is_impossible(self) -> None:
        """$0.05 credit = $5/contract. $5.20 fees exceed credit — mathematically impossible."""
        result = check_commission_drag(_ic(), entry_credit=0.05)
        assert result.severity == Severity.FAIL

    def test_wider_wings_same_credit_still_viable(self) -> None:
        """10-wide IC with $1.50 credit: same commissions, more premium room."""
        result = check_commission_drag(_ic(wing_width=10.0), entry_credit=1.50)
        assert result.severity == Severity.PASS

    def test_net_credit_after_fees_is_positive(self) -> None:
        result = check_commission_drag(_ic(), entry_credit=1.50)
        assert result.value is not None
        assert result.value > 0, "Net credit after fees must be positive for a PASS"
