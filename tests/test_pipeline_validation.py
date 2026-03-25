"""Tests for pipeline validation functions."""

from datetime import datetime, timedelta, timezone

import pytest

from income_desk.regression.pipeline_validation import (
    SanityIssue,
    HealthCheck,
    PipelineHealthReport,
    PipelineTestResult,
    validate_trade_data_sanity,
    validate_pipeline_health,
    validate_full_pipeline,
)


# ── Helpers ──


def _make_trade(**overrides) -> dict:
    """Build a minimal trade dict with sensible defaults."""
    base = {
        "ticker": "SPY",
        "entry_price": 1.50,
        "current_price": 1.20,
        "structure_type": "iron_condor",
        "total_pnl": 30.0,
        "opened_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
        "legs": [
            {"asset_type": "option", "strike": 550.0, "option_type": "put", "action": "buy"},
            {"asset_type": "option", "strike": 555.0, "option_type": "put", "action": "sell"},
            {"asset_type": "option", "strike": 575.0, "option_type": "call", "action": "sell"},
            {"asset_type": "option", "strike": 580.0, "option_type": "call", "action": "buy"},
        ],
    }
    base.update(overrides)
    return base


def _make_equity_trade(**overrides) -> dict:
    """Build a minimal equity trade dict."""
    base = {
        "ticker": "AAPL",
        "entry_price": 180.0,
        "current_price": 185.0,
        "structure_type": "equity_long",
        "total_pnl": 500.0,
        "lot_size": 1,
        "opened_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
        "legs": [
            {"asset_type": "equity", "quantity": 100},
        ],
    }
    base.update(overrides)
    return base


def _make_decision(**overrides) -> dict:
    """Build a minimal decision dict."""
    base = {
        "strategy_type": "iron_condor",
        "ticker": "SPY",
        "approved": True,
        "score": 0.75,
    }
    base.update(overrides)
    return base


# ── Test: validate_trade_data_sanity ──


class TestSanityValidation:

    def test_sanity_catches_zero_entry_price(self):
        trade = _make_trade(entry_price=0)
        issues = validate_trade_data_sanity(trade)
        critical = [i for i in issues if i.severity == "critical" and i.field == "entry_price"]
        assert len(critical) >= 1
        assert "entry_price" in critical[0].message

    def test_sanity_catches_negative_entry_price(self):
        trade = _make_trade(entry_price=-1.5)
        issues = validate_trade_data_sanity(trade)
        critical = [i for i in issues if i.severity == "critical"]
        # Should catch both entry_price <= 0 and negative price checks
        assert any("entry_price" in i.field for i in critical)

    def test_sanity_catches_equity_lot_100(self):
        trade = _make_equity_trade(lot_size=100)
        issues = validate_trade_data_sanity(trade)
        critical = [i for i in issues if i.severity == "critical" and i.field == "lot_size"]
        assert len(critical) == 1
        assert "100" in critical[0].message
        assert "equity" in critical[0].message.lower()

    def test_sanity_catches_equity_multiplier_100(self):
        trade = _make_equity_trade(lot_size=None, multiplier=100)
        issues = validate_trade_data_sanity(trade)
        critical = [i for i in issues if i.severity == "critical" and i.field == "lot_size"]
        assert len(critical) == 1

    def test_sanity_catches_quantity_doubling(self):
        trade = _make_equity_trade(entry_price=180.0, current_price=400.0)
        issues = validate_trade_data_sanity(trade)
        critical = [i for i in issues if i.severity == "critical" and "doubling" in i.message]
        assert len(critical) == 1

    def test_sanity_catches_stale_mark(self):
        trade = _make_trade(
            entry_price=1.50,
            current_price=1.50,
            opened_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        )
        issues = validate_trade_data_sanity(trade)
        warnings = [i for i in issues if i.severity == "warning" and "stale" in i.message]
        assert len(warnings) == 1

    def test_sanity_catches_zero_pnl_with_price_diff(self):
        trade = _make_trade(
            entry_price=1.50,
            current_price=1.20,
            total_pnl=0,
            opened_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        )
        issues = validate_trade_data_sanity(trade)
        warnings = [i for i in issues if i.severity == "warning" and "total_pnl" in i.field]
        assert len(warnings) == 1

    def test_sanity_catches_option_without_strike(self):
        trade = _make_trade(legs=[
            {"asset_type": "option", "strike": None, "option_type": "put"},
            {"asset_type": "option", "strike": 555.0, "option_type": "put"},
        ])
        issues = validate_trade_data_sanity(trade)
        critical = [i for i in issues if i.severity == "critical" and "strike" in i.field]
        assert len(critical) == 1

    def test_sanity_catches_multi_leg_with_single_leg(self):
        trade = _make_trade(
            structure_type="iron_condor",
            legs=[
                {"asset_type": "option", "strike": 550.0, "option_type": "put"},
            ],
        )
        issues = validate_trade_data_sanity(trade)
        critical = [i for i in issues if i.severity == "critical" and i.field == "legs"]
        assert len(critical) == 1
        assert "iron_condor" in critical[0].message

    def test_sanity_clean_trade_has_no_issues(self):
        trade = _make_trade()
        issues = validate_trade_data_sanity(trade)
        # A well-formed trade should have no critical issues
        critical = [i for i in issues if i.severity == "critical"]
        assert len(critical) == 0


# ── Test: validate_pipeline_health ──


class TestPipelineHealth:

    def test_pipeline_health_red_when_no_options(self):
        trades = [_make_equity_trade()]
        decisions = [_make_decision()]
        report = validate_pipeline_health(trades, decisions, min_option_trades=1)
        assert report.overall_health == "RED"
        assert len(report.blocking_issues) > 0
        assert any("option" in b.lower() for b in report.blocking_issues)

    def test_pipeline_health_green_with_options(self):
        trades = [_make_trade()]
        decisions = [
            _make_decision(approved=True),
            _make_decision(approved=False, strategy_type="iron_condor"),
            _make_decision(approved=False, strategy_type="credit_spread"),
            _make_decision(approved=False, strategy_type="iron_butterfly"),
            _make_decision(approved=False, strategy_type="equity_long"),
        ]
        report = validate_pipeline_health(trades, decisions, min_option_trades=1)
        # Should be GREEN or YELLOW (not RED)
        assert report.overall_health != "RED"
        # option_trades_exist should pass
        option_check = next(
            (c for c in report.checks if c.name == "option_trades_exist"), None
        )
        assert option_check is not None
        assert option_check.passed is True

    def test_pipeline_health_catches_quantity_doubling(self):
        trades = [
            _make_equity_trade(entry_price=180.0, current_price=400.0),
        ]
        decisions = [_make_decision()]
        report = validate_pipeline_health(trades, decisions, min_option_trades=0)
        doubling_check = next(
            (c for c in report.checks if c.name == "no_quantity_doubling"), None
        )
        assert doubling_check is not None
        assert doubling_check.passed is False

    def test_pipeline_health_checks_approval_rate(self):
        # 100% approval rate should warn
        decisions = [_make_decision(approved=True) for _ in range(10)]
        trades = [_make_trade()]
        report = validate_pipeline_health(trades, decisions, min_option_trades=1)
        rate_check = next(
            (c for c in report.checks if c.name == "approval_rate_sane"), None
        )
        assert rate_check is not None
        assert rate_check.passed is False

    def test_pipeline_health_empty_decisions_ok(self):
        trades = [_make_trade()]
        report = validate_pipeline_health(trades, [], min_option_trades=1)
        # No decisions -> approval rate check should pass (nothing to evaluate)
        rate_check = next(
            (c for c in report.checks if c.name == "approval_rate_sane"), None
        )
        assert rate_check is not None
        assert rate_check.passed is True


# ── Test: validate_full_pipeline ──


class TestFullPipeline:

    @pytest.mark.slow
    def test_full_pipeline_passes_with_simulation(self):
        result = validate_full_pipeline(simulation="ideal_income")
        # At minimum, simulation creation and MA init should pass
        assert "create_simulation" in result.stages_passed
        assert "init_market_analyzer" in result.stages_passed
        assert "rank_trades" in result.stages_passed

        # The overall test should pass (all stages)
        if not result.passed:
            failed_names = [name for name, _ in result.stages_failed]
            pytest.fail(
                f"Pipeline failed at stages: {failed_names}. "
                f"Details: {result.stages_failed}"
            )

        assert result.sample_trade is not None
        assert result.sample_trade.get("ticker") is not None

    @pytest.mark.slow
    def test_full_pipeline_india_simulation(self):
        result = validate_full_pipeline(simulation="india")
        assert "create_simulation" in result.stages_passed
        assert "init_market_analyzer" in result.stages_passed
