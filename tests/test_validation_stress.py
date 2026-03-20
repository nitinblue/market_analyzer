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
        """Extreme risk/reward (> 5:1) → gamma exposure warning."""
        # 10-point wing, $0.20 credit → max_loss $980, max_profit $20 → R:R 49:1 (FAIL)
        result = check_gamma_stress(_ic_spec(wing_width=10.0), entry_credit=0.20, atr_pct=3.0)
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


# ── Regression: graceful degradation when credit estimate exceeds wing width ──


class TestGammaStressGracefulDegradation:
    """Bug fix: stress checks must WARN (not FAIL) when parameters are invalid.

    Previously both checks returned Severity.FAIL with "max loss is zero or negative"
    when entry_credit >= wing_width. FAIL means "trade is dangerous", but the real
    issue is insufficient data — so WARN is correct.
    """

    def test_gamma_stress_warns_not_fails_when_credit_exceeds_wing(self) -> None:
        """Regression: credit > wing_width should return WARN, not FAIL."""
        # 5-wide IC but credit = 6.10 (overestimated without broker)
        result = check_gamma_stress(_ic_spec(wing_width=5.0), entry_credit=6.10, atr_pct=1.0)
        assert result.severity == Severity.WARN, (
            f"Expected WARN (insufficient data), got {result.severity}: {result.message}"
        )
        assert "broker" in result.message.lower() or "cannot" in result.message.lower()

    def test_gamma_stress_warns_when_credit_equals_wing(self) -> None:
        """Edge case: credit exactly equals wing width → max_loss = 0 → WARN."""
        result = check_gamma_stress(_ic_spec(wing_width=5.0), entry_credit=5.0, atr_pct=1.0)
        assert result.severity == Severity.WARN

    def test_breakeven_spread_warns_not_fails_when_credit_exceeds_wing(self) -> None:
        """Regression: invalid params should return WARN, not FAIL."""
        result = check_breakeven_spread(_ic_spec(wing_width=5.0), entry_credit=6.10, atr_pct=1.0)
        assert result.severity == Severity.WARN, (
            f"Expected WARN (insufficient data), got {result.severity}: {result.message}"
        )

    def test_breakeven_spread_warns_when_credit_is_zero(self) -> None:
        """Edge case: zero credit → no edge to measure → WARN."""
        result = check_breakeven_spread(_ic_spec(), entry_credit=0.0, atr_pct=1.0)
        assert result.severity == Severity.WARN
