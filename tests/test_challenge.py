"""Tests for the $30K Trading Challenge portfolio tracker."""

import pytest
import tempfile
from datetime import date
from pathlib import Path

from income_desk.trade_spec_factory import (
    create_trade_spec,
    build_iron_condor,
    build_credit_spread,
    build_debit_spread,
    build_calendar,
    from_dxlink_symbols,
    to_dxlink_symbols,
    parse_dxlink_symbol,
)
from income_desk.models.opportunity import TradeSpec, LegAction, StructureType, OrderSide
from challenge.portfolio import Portfolio
from challenge.models import TradeStatus, RiskLimits, PortfolioStatus


# ── TradeSpec Factory Tests ──


class TestCreateTradeSpec:
    def test_iron_condor_from_raw(self):
        spec = create_trade_spec(
            ticker="GLD",
            structure_type="iron_condor",
            legs=[
                {"action": "STO", "option_type": "put", "strike": 218.0, "expiration": "2026-04-17"},
                {"action": "BTO", "option_type": "put", "strike": 213.0, "expiration": "2026-04-17"},
                {"action": "STO", "option_type": "call", "strike": 225.0, "expiration": "2026-04-17"},
                {"action": "BTO", "option_type": "call", "strike": 230.0, "expiration": "2026-04-17"},
            ],
            underlying_price=221.50,
            entry_price=0.72,
        )
        assert spec.ticker == "GLD"
        assert spec.structure_type == "iron_condor"
        assert spec.order_side == "credit"
        assert len(spec.legs) == 4
        assert spec.wing_width_points == 5.0
        assert spec.max_entry_price == 0.72
        assert spec.target_expiration == date(2026, 4, 17)

    def test_legs_have_correct_actions(self):
        spec = create_trade_spec(
            ticker="SPY",
            structure_type="credit_spread",
            legs=[
                {"action": "STO", "option_type": "put", "strike": 580.0, "expiration": "2026-04-17"},
                {"action": "BTO", "option_type": "put", "strike": 575.0, "expiration": "2026-04-17"},
            ],
            underlying_price=590.0,
        )
        assert spec.legs[0].action == LegAction.SELL_TO_OPEN
        assert spec.legs[1].action == LegAction.BUY_TO_OPEN

    def test_auto_detects_credit_order_side(self):
        spec = create_trade_spec(
            ticker="SPY",
            structure_type="iron_condor",
            legs=[
                {"action": "STO", "option_type": "put", "strike": 580.0, "expiration": "2026-04-17"},
                {"action": "BTO", "option_type": "put", "strike": 575.0, "expiration": "2026-04-17"},
                {"action": "STO", "option_type": "call", "strike": 615.0, "expiration": "2026-04-17"},
                {"action": "BTO", "option_type": "call", "strike": 620.0, "expiration": "2026-04-17"},
            ],
            underlying_price=600.0,
        )
        assert spec.order_side == "credit"

    def test_auto_detects_debit_order_side(self):
        spec = create_trade_spec(
            ticker="SPY",
            structure_type="debit_spread",
            legs=[
                {"action": "BTO", "option_type": "call", "strike": 600.0, "expiration": "2026-04-17"},
                {"action": "STO", "option_type": "call", "strike": 605.0, "expiration": "2026-04-17"},
            ],
            underlying_price=600.0,
        )
        assert spec.order_side == "debit"

    def test_wing_width_computed_for_spread(self):
        spec = create_trade_spec(
            ticker="SPY",
            structure_type="credit_spread",
            legs=[
                {"action": "STO", "option_type": "put", "strike": 580.0, "expiration": "2026-04-17"},
                {"action": "BTO", "option_type": "put", "strike": 575.0, "expiration": "2026-04-17"},
            ],
            underlying_price=590.0,
        )
        assert spec.wing_width_points == 5.0

    def test_default_exit_rules_applied(self):
        spec = create_trade_spec(
            ticker="SPY",
            structure_type="iron_condor",
            legs=[
                {"action": "STO", "option_type": "put", "strike": 580.0, "expiration": "2026-04-17"},
                {"action": "BTO", "option_type": "put", "strike": 575.0, "expiration": "2026-04-17"},
                {"action": "STO", "option_type": "call", "strike": 615.0, "expiration": "2026-04-17"},
                {"action": "BTO", "option_type": "call", "strike": 620.0, "expiration": "2026-04-17"},
            ],
            underlying_price=600.0,
        )
        assert spec.profit_target_pct == 0.50
        assert spec.stop_loss_pct == 2.0
        assert spec.exit_dte == 21

    def test_custom_exit_rules_override_defaults(self):
        spec = create_trade_spec(
            ticker="SPY",
            structure_type="iron_condor",
            legs=[
                {"action": "STO", "option_type": "put", "strike": 580.0, "expiration": "2026-04-17"},
                {"action": "BTO", "option_type": "put", "strike": 575.0, "expiration": "2026-04-17"},
                {"action": "STO", "option_type": "call", "strike": 615.0, "expiration": "2026-04-17"},
                {"action": "BTO", "option_type": "call", "strike": 620.0, "expiration": "2026-04-17"},
            ],
            underlying_price=600.0,
            profit_target_pct=0.75,
            stop_loss_pct=3.0,
            exit_dte=14,
        )
        assert spec.profit_target_pct == 0.75
        assert spec.stop_loss_pct == 3.0
        assert spec.exit_dte == 14

    def test_date_object_and_string_both_work(self):
        spec1 = create_trade_spec(
            ticker="SPY", structure_type="credit_spread",
            legs=[
                {"action": "STO", "option_type": "put", "strike": 580.0, "expiration": "2026-04-17"},
                {"action": "BTO", "option_type": "put", "strike": 575.0, "expiration": "2026-04-17"},
            ],
            underlying_price=590.0,
        )
        spec2 = create_trade_spec(
            ticker="SPY", structure_type="credit_spread",
            legs=[
                {"action": "STO", "option_type": "put", "strike": 580.0, "expiration": date(2026, 4, 17)},
                {"action": "BTO", "option_type": "put", "strike": 575.0, "expiration": date(2026, 4, 17)},
            ],
            underlying_price=590.0,
        )
        assert spec1.target_expiration == spec2.target_expiration

    def test_invalid_action_raises(self):
        with pytest.raises(ValueError, match="Invalid action"):
            create_trade_spec(
                ticker="SPY", structure_type="credit_spread",
                legs=[
                    {"action": "INVALID", "option_type": "put", "strike": 580.0, "expiration": "2026-04-17"},
                ],
                underlying_price=590.0,
            )

    def test_tradespec_has_cotrader_fields(self):
        """Verify TradeSpec from factory has all fields eTrading needs."""
        spec = build_iron_condor(
            ticker="GLD", underlying_price=221.0,
            short_put=218.0, long_put=213.0,
            short_call=225.0, long_call=230.0,
            expiration="2026-04-17", entry_price=0.72,
        )
        # eTrading contract fields
        assert spec.structure_type is not None
        assert spec.order_side is not None
        assert spec.leg_codes  # parseable leg codes
        assert spec.order_data  # machine-readable dicts
        assert spec.dxlink_symbols  # DXLink streaming symbols
        assert spec.exit_summary  # one-line exit guidance
        assert spec.position_size(30_000) >= 1  # sizing works


class TestBuilders:
    def test_build_iron_condor(self):
        spec = build_iron_condor(
            ticker="GLD", underlying_price=221.0,
            short_put=218.0, long_put=213.0,
            short_call=225.0, long_call=230.0,
            expiration="2026-04-17", entry_price=0.72,
        )
        assert spec.ticker == "GLD"
        assert spec.structure_type == "iron_condor"
        assert spec.order_side == "credit"
        assert len(spec.legs) == 4
        assert spec.wing_width_points == 5.0

    def test_build_credit_spread(self):
        spec = build_credit_spread(
            ticker="SPY", underlying_price=600.0,
            short_strike=585.0, long_strike=580.0,
            option_type="put", expiration="2026-04-17",
            entry_price=0.45,
        )
        assert spec.structure_type == "credit_spread"
        assert len(spec.legs) == 2
        assert spec.wing_width_points == 5.0

    def test_build_debit_spread(self):
        spec = build_debit_spread(
            ticker="AAPL", underlying_price=210.0,
            long_strike=210.0, short_strike=215.0,
            option_type="call", expiration="2026-04-17",
            entry_price=1.80,
        )
        assert spec.structure_type == "debit_spread"
        assert spec.order_side == "debit"
        assert spec.profit_target_pct == 0.50
        assert spec.stop_loss_pct == 0.50

    def test_build_calendar(self):
        spec = build_calendar(
            ticker="SPY", underlying_price=600.0, strike=600.0,
            option_type="call",
            front_expiration="2026-04-03", back_expiration="2026-05-15",
            entry_price=2.50,
        )
        assert spec.structure_type == "calendar"
        assert spec.order_side == "debit"
        assert len(spec.legs) == 2


# ── Portfolio Tracker Tests ──


class TestPortfolioLifecycle:
    @pytest.fixture
    def tmp_dir(self, tmp_path):
        return tmp_path

    @pytest.fixture
    def portfolio(self, tmp_dir):
        return Portfolio(data_dir=tmp_dir)

    @pytest.fixture
    def sample_spec(self):
        return build_iron_condor(
            ticker="GLD", underlying_price=221.0,
            short_put=218.0, long_put=213.0,
            short_call=225.0, long_call=230.0,
            expiration="2026-04-17", entry_price=0.72,
        )

    def test_initial_status(self, portfolio):
        status = portfolio.get_status()
        assert status.account_size == 30_000.0
        assert status.open_positions == 0
        assert status.buying_power_available == 30_000.0
        assert status.portfolio_heat == "cool"

    def test_book_trade(self, portfolio, sample_spec):
        record = portfolio.book_trade(sample_spec, entry_price=0.72, contracts=1)
        assert record.trade_id.startswith("GLD-")
        assert record.status == TradeStatus.OPEN
        assert record.entry_price == 0.72
        assert record.contracts == 1
        assert record.buying_power_used == 500.0  # 5-wide × 100

    def test_book_updates_portfolio(self, portfolio, sample_spec):
        portfolio.book_trade(sample_spec, entry_price=0.72, contracts=1)
        status = portfolio.get_status()
        assert status.open_positions == 1
        assert status.buying_power_used == 500.0
        assert status.buying_power_available == 29_500.0

    def test_close_trade_credit(self, portfolio, sample_spec):
        record = portfolio.book_trade(sample_spec, entry_price=0.72, contracts=1)
        closed = portfolio.close_trade(record.trade_id, exit_price=0.35, reason="profit_target")
        assert closed.status == TradeStatus.CLOSED
        assert closed.realized_pnl == pytest.approx(37.0)  # (0.72 - 0.35) * 100

    def test_close_trade_loss(self, portfolio, sample_spec):
        record = portfolio.book_trade(sample_spec, entry_price=0.72, contracts=2)
        closed = portfolio.close_trade(record.trade_id, exit_price=1.50, reason="stop_loss")
        assert closed.realized_pnl == pytest.approx(-156.0)  # (0.72 - 1.50) * 100 * 2

    def test_expire_trade_credit(self, portfolio, sample_spec):
        record = portfolio.book_trade(sample_spec, entry_price=0.72, contracts=1)
        expired = portfolio.expire_trade(record.trade_id)
        assert expired.status == TradeStatus.EXPIRED
        assert expired.realized_pnl == pytest.approx(72.0)  # Full credit kept

    def test_pnl_tracking(self, portfolio, sample_spec):
        r1 = portfolio.book_trade(sample_spec, entry_price=0.72, contracts=1)
        portfolio.close_trade(r1.trade_id, exit_price=0.35, reason="profit_target")

        spec2 = build_credit_spread(
            ticker="SPY", underlying_price=600.0,
            short_strike=585.0, long_strike=580.0,
            option_type="put", expiration="2026-04-17",
            entry_price=0.45,
        )
        r2 = portfolio.book_trade(spec2, entry_price=0.45, contracts=1)
        portfolio.close_trade(r2.trade_id, exit_price=0.80, reason="stop_loss")

        status = portfolio.get_status()
        assert status.total_trades == 2
        assert status.winning_trades == 1
        assert status.losing_trades == 1
        assert status.win_rate == 0.5
        assert status.total_realized_pnl == pytest.approx(2.0)  # 37 + (-35)

    def test_list_trades_by_status(self, portfolio, sample_spec):
        r1 = portfolio.book_trade(sample_spec, entry_price=0.72, contracts=1)
        portfolio.close_trade(r1.trade_id, exit_price=0.35)

        spec2 = build_credit_spread(
            ticker="SPY", underlying_price=600.0,
            short_strike=585.0, long_strike=580.0,
            option_type="put", expiration="2026-04-17",
            entry_price=0.45,
        )
        portfolio.book_trade(spec2, entry_price=0.45, contracts=1)

        open_trades = portfolio.list_trades(status="open")
        closed_trades = portfolio.list_trades(status="closed")
        assert len(open_trades) == 1
        assert len(closed_trades) == 1

    def test_yaml_persistence(self, tmp_dir, sample_spec):
        """Trades persist across Portfolio instances."""
        p1 = Portfolio(data_dir=tmp_dir)
        p1.book_trade(sample_spec, entry_price=0.72, contracts=1)

        p2 = Portfolio(data_dir=tmp_dir)
        assert len(p2.list_trades(status="open")) == 1

    def test_config_persistence(self, tmp_dir):
        """Config persists across Portfolio instances."""
        p1 = Portfolio(data_dir=tmp_dir)
        p1.update_config(account_size=50_000, max_positions=8)

        p2 = Portfolio(data_dir=tmp_dir)
        assert p2.limits.account_size == 50_000
        assert p2.limits.max_positions == 8


class TestRiskChecks:
    @pytest.fixture
    def portfolio(self, tmp_path):
        return Portfolio(data_dir=tmp_path)

    @pytest.fixture
    def sample_spec(self):
        return build_iron_condor(
            ticker="GLD", underlying_price=221.0,
            short_put=218.0, long_put=213.0,
            short_call=225.0, long_call=230.0,
            expiration="2026-04-17", entry_price=0.72,
        )

    def test_risk_check_passes(self, portfolio, sample_spec):
        check = portfolio.check_risk(sample_spec, contracts=1, entry_price=0.72)
        assert check.allowed
        assert len(check.violations) == 0

    def test_max_positions_violated(self, portfolio):
        # Book 5 trades (max_positions=5)
        for i in range(5):
            ticker = f"T{i}"
            spec = build_credit_spread(
                ticker=ticker, underlying_price=100.0,
                short_strike=95.0, long_strike=90.0,
                option_type="put", expiration="2026-04-17",
                entry_price=0.30,
            )
            portfolio.book_trade(spec, entry_price=0.30)

        # 6th should fail
        spec = build_credit_spread(
            ticker="T5", underlying_price=100.0,
            short_strike=95.0, long_strike=90.0,
            option_type="put", expiration="2026-04-17",
            entry_price=0.30,
        )
        check = portfolio.check_risk(spec, contracts=1, entry_price=0.30)
        assert not check.allowed
        assert any("Max positions" in v for v in check.violations)

    def test_max_per_ticker_violated(self, portfolio):
        spec = build_iron_condor(
            ticker="GLD", underlying_price=221.0,
            short_put=218.0, long_put=213.0,
            short_call=225.0, long_call=230.0,
            expiration="2026-04-17", entry_price=0.72,
        )
        # Book 2 GLD trades (max_per_ticker=2)
        portfolio.book_trade(spec, entry_price=0.72)
        portfolio.book_trade(spec, entry_price=0.65)

        check = portfolio.check_risk(spec, contracts=1, entry_price=0.70)
        assert not check.allowed
        assert any("GLD" in v for v in check.violations)

    def test_single_trade_risk_limit(self, portfolio):
        # max_single_trade_risk_pct=0.05 → $1500 on 30K
        # 5-wide IC × 4 contracts = $2000 risk → should fail
        spec = build_iron_condor(
            ticker="GLD", underlying_price=221.0,
            short_put=218.0, long_put=213.0,
            short_call=225.0, long_call=230.0,
            expiration="2026-04-17", entry_price=0.72,
        )
        check = portfolio.check_risk(spec, contracts=4, entry_price=0.72)
        assert not check.allowed
        assert any("single-trade limit" in v for v in check.violations)

    def test_buying_power_reserve(self, portfolio):
        """Can't use more than 80% of account (20% reserve)."""
        # max BP = 30K * 0.80 = $24K. Try to use $25K
        spec = build_iron_condor(
            ticker="GLD", underlying_price=221.0,
            short_put=218.0, long_put=213.0,
            short_call=225.0, long_call=230.0,
            expiration="2026-04-17", entry_price=0.72,
        )
        # 50 contracts × $500 BP = $25,000
        check = portfolio.check_risk(spec, contracts=50, entry_price=0.72)
        assert not check.allowed

    def test_book_trade_blocked_by_risk(self, portfolio):
        """book_trade raises ValueError when risk check fails."""
        # Fill up to max positions
        for i in range(5):
            spec = build_credit_spread(
                ticker=f"T{i}", underlying_price=100.0,
                short_strike=95.0, long_strike=90.0,
                option_type="put", expiration="2026-04-17",
                entry_price=0.30,
            )
            portfolio.book_trade(spec, entry_price=0.30)

        with pytest.raises(ValueError, match="risk limits"):
            spec = build_credit_spread(
                ticker="T5", underlying_price=100.0,
                short_strike=95.0, long_strike=90.0,
                option_type="put", expiration="2026-04-17",
                entry_price=0.30,
            )
            portfolio.book_trade(spec, entry_price=0.30)


class TestTradeRecordProperties:
    def test_max_profit_credit(self):
        from challenge.models import TradeRecord
        r = TradeRecord(
            trade_id="T1", ticker="GLD", structure_type="iron_condor",
            order_side="credit", legs=[], target_expiration="2026-04-17",
            entry_date="2026-03-12", entry_price=0.72, contracts=2,
            wing_width=5.0,
        )
        assert r.max_profit == 144.0  # 0.72 * 100 * 2
        assert r.max_loss == 856.0  # (5 - 0.72) * 100 * 2
        assert r.risk_reward_ratio == pytest.approx(5.94, rel=0.01)

    def test_max_profit_debit(self):
        from challenge.models import TradeRecord
        r = TradeRecord(
            trade_id="T1", ticker="SPY", structure_type="debit_spread",
            order_side="debit", legs=[], target_expiration="2026-04-17",
            entry_date="2026-03-12", entry_price=1.80, contracts=1,
            wing_width=5.0,
        )
        assert r.max_profit == 320.0  # (5 - 1.80) * 100
        assert r.max_loss == 180.0  # 1.80 * 100


class TestPortfolioHeat:
    def test_cool_heat(self, tmp_path):
        p = Portfolio(data_dir=tmp_path)
        assert p.get_status().portfolio_heat == "cool"

    def test_warm_heat(self, tmp_path):
        p = Portfolio(data_dir=tmp_path)
        # Raise limits to allow larger trades for this test
        p.update_config(
            max_single_trade_risk_pct=0.25, max_portfolio_risk_pct=0.80,
            max_sector_concentration_pct=0.80,
        )
        # Book enough to use ~60% BP: 3 × $6000 = $18K / $30K = 60%
        for i in range(3):
            spec = build_iron_condor(
                ticker=f"T{i}", underlying_price=500.0,
                short_put=480.0, long_put=420.0,
                short_call=520.0, long_call=580.0,
                expiration="2026-04-17", entry_price=3.0,
            )
            p.book_trade(spec, entry_price=3.0, contracts=1)
        status = p.get_status()
        assert status.portfolio_heat == "warm"


# -- DXLink Symbol Conversion Tests --


class TestDXLinkConversion:
    def test_parse_dxlink_symbol(self):
        p = parse_dxlink_symbol(".GLD260417P455")
        assert p["ticker"] == "GLD"
        assert p["expiration"] == date(2026, 4, 17)
        assert p["option_type"] == "put"
        assert p["strike"] == 455.0

    def test_parse_without_dot(self):
        p = parse_dxlink_symbol("SPY260327C600")
        assert p["ticker"] == "SPY"
        assert p["option_type"] == "call"
        assert p["strike"] == 600.0

    def test_parse_fractional_strike(self):
        p = parse_dxlink_symbol(".AAPL260417C212.5")
        assert p["strike"] == 212.5

    def test_parse_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_dxlink_symbol("INVALID")

    def test_roundtrip_iron_condor(self):
        """DXLink -> TradeSpec -> DXLink is lossless."""
        symbols = [".GLD260417P455", ".GLD260417P450",
                   ".GLD260417C480", ".GLD260417C485"]
        actions = ["STO", "BTO", "STO", "BTO"]

        spec = from_dxlink_symbols(symbols, actions, underlying_price=466.88)

        assert spec.structure_type == "iron_condor"
        assert spec.order_side == "credit"
        assert spec.wing_width_points == 5.0
        assert spec.strategy_symbol == "IC"
        assert to_dxlink_symbols(spec) == symbols

    def test_roundtrip_credit_spread(self):
        symbols = [".SPY260417P585", ".SPY260417P580"]
        spec = from_dxlink_symbols(
            symbols, ["STO", "BTO"],
            underlying_price=600.0, entry_price=0.45,
        )
        assert spec.structure_type == "credit_spread"
        assert spec.order_side == "credit"
        assert spec.wing_width_points == 5.0
        assert to_dxlink_symbols(spec) == symbols

    def test_auto_detect_calendar(self):
        symbols = [".GLD260402C465", ".GLD260515C465"]
        spec = from_dxlink_symbols(symbols, ["STO", "BTO"], underlying_price=466.0)
        assert spec.structure_type == "calendar"

    def test_auto_detect_iron_butterfly(self):
        symbols = [".TLT260417P87", ".TLT260417C87",
                   ".TLT260417P86", ".TLT260417C88"]
        spec = from_dxlink_symbols(
            symbols, ["STO", "STO", "BTO", "BTO"],
            underlying_price=87.0,
        )
        assert spec.structure_type == "iron_butterfly"

    def test_with_explicit_structure(self):
        """Override auto-detection."""
        symbols = [".SPY260417P585", ".SPY260417P580"]
        spec = from_dxlink_symbols(
            symbols, ["STO", "BTO"],
            underlying_price=600.0,
            structure_type="credit_spread",
        )
        assert spec.structure_type == "credit_spread"

    def test_strategy_badge(self):
        spec = build_iron_condor(
            "GLD", 221.0, 218, 213, 225, 230, "2026-04-17",
        )
        assert spec.strategy_badge == "IC neutral · defined"

        spec2 = build_credit_spread(
            "SPY", 600.0, 585, 580, "put", "2026-04-17",
        )
        assert spec2.strategy_badge == "CS directional · defined"

        spec3 = build_debit_spread(
            "AAPL", 210.0, 210, 215, "call", "2026-04-17",
        )
        assert spec3.strategy_badge == "DS directional · defined"
