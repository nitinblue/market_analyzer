"""Tests for adversarial stress scenario checks."""
from datetime import date, timedelta

import pytest

from market_analyzer.trade_spec_factory import build_iron_condor
from market_analyzer.validation.models import Severity
from market_analyzer.validation.stress_scenarios import (
    check_breakeven_spread,
    check_gamma_stress,
    check_vega_shock,
)


def _ic_spec(wing_width: float = 5.0):
    exp = date.today() + timedelta(days=30)
    mid = 580.0
    return build_iron_condor(
        ticker="SPY", underlying_price=mid,
        short_put=mid - 10,  long_put=mid - 10 - wing_width,
        short_call=mid + 10, long_call=mid + 10 + wing_width,
        expiration=exp.isoformat(),
    )


class TestGammaStress:
    def test_defined_risk_ic_passes_gamma_stress(self) -> None:
        """Iron condor with wing: max loss is bounded regardless of gamma."""
        result = check_gamma_stress(_ic_spec(), entry_credit=1.50, atr_pct=1.0)
        assert result.severity == Severity.PASS
        assert result.name == "gamma_stress"

    def test_high_gamma_warns(self) -> None:
        """Very wide ATR (3%) + narrow wings → gamma exposure warning."""
        result = check_gamma_stress(_ic_spec(wing_width=1.0), entry_credit=0.30, atr_pct=3.0)
        assert result.severity in (Severity.WARN, Severity.FAIL)

    def test_result_includes_loss_estimate(self) -> None:
        result = check_gamma_stress(_ic_spec(), entry_credit=1.50, atr_pct=1.0)
        assert result.value is not None


class TestVegaShock:
    def test_ic_warns_on_iv_spike(self) -> None:
        """IC is short vega — +30% IV spike hurts the position."""
        result = check_vega_shock(_ic_spec(), entry_credit=1.50, iv_spike_pct=0.30)
        # IC is short vega so IV spike should be WARN or FAIL
        assert result.severity in (Severity.WARN, Severity.FAIL)
        assert result.name == "vega_shock"

    def test_result_message_describes_exposure(self) -> None:
        result = check_vega_shock(_ic_spec(), entry_credit=1.50, iv_spike_pct=0.30)
        assert len(result.message) > 0


class TestBreakevenSpread:
    def test_healthy_trade_passes_at_low_spread(self) -> None:
        """At 0.5% spread, a $1.50-credit IC should still be viable."""
        result = check_breakeven_spread(_ic_spec(), entry_credit=1.50, atr_pct=1.0)
        assert result.severity == Severity.PASS
        assert result.name == "breakeven_spread"

    def test_thin_credit_warns_at_high_spread(self) -> None:
        """$0.40 credit IC — edge disappears quickly as spread widens."""
        result = check_breakeven_spread(_ic_spec(), entry_credit=0.40, atr_pct=1.0)
        assert result.severity in (Severity.WARN, Severity.FAIL)

    def test_result_includes_break_even_spread_pct(self) -> None:
        """Value field should be the break-even spread %."""
        result = check_breakeven_spread(_ic_spec(), entry_credit=1.50, atr_pct=1.0)
        assert result.value is not None
        assert result.value > 0  # break-even spread pct
