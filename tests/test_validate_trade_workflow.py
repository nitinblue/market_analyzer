"""Tests for BUG-005: validate_trade workflow data quality checks."""
import pytest

from income_desk.workflow.validate_trade import ValidateRequest, validate_trade


class TestBUG005ZeroPrice:
    """current_price=0 must fail the entry_quality gate, not pass all gates."""

    def test_zero_price_fails(self) -> None:
        req = ValidateRequest(
            ticker="SPY",
            entry_credit=1.50,
            regime_id=1,
            atr_pct=1.0,
            current_price=0,
        )
        resp = validate_trade(req)
        assert resp.is_ready is False
        assert "entry_quality" in resp.failed_gates
        # The detail must explain the failure reason
        gate = resp.gates[0]
        assert gate.passed is False
        assert "current_price" in gate.detail

    def test_negative_price_fails(self) -> None:
        req = ValidateRequest(
            ticker="SPY",
            entry_credit=1.50,
            regime_id=1,
            atr_pct=1.0,
            current_price=-10.0,
        )
        resp = validate_trade(req)
        assert resp.is_ready is False
        assert "entry_quality" in resp.failed_gates

    def test_valid_price_does_not_fail_data_quality(self) -> None:
        req = ValidateRequest(
            ticker="SPY",
            entry_credit=1.50,
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
        )
        resp = validate_trade(req)
        # Should not have a data_quality failure — may or may not be ready
        # depending on other gates, but entry_quality should not fail on price
        gate_names = [g.name for g in resp.gates]
        data_q = [g for g in resp.gates if g.name == "entry_quality" and "current_price" in g.detail and "no market data" in g.detail]
        assert len(data_q) == 0, "entry_quality should not fail on valid price"
