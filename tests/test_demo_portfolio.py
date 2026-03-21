"""Tests for demo portfolio module."""
from __future__ import annotations
import pytest
from datetime import date

from market_analyzer.demo.portfolio import (
    create_demo_portfolio,
    load_demo_portfolio,
    save_demo_portfolio,
    add_demo_position,
    close_demo_position,
    get_demo_summary,
)


class TestDemoPortfolio:
    def test_create_demo_portfolio(self, tmp_path, monkeypatch):
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_DIR", tmp_path)
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_FILE", tmp_path / "demo.json")
        port = create_demo_portfolio(100000, "moderate")
        assert port.total_capital == 100000
        assert len(port.desks) >= 3
        assert port.cash_balance == 100000
        assert (tmp_path / "demo.json").exists()

    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_DIR", tmp_path)
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_FILE", tmp_path / "demo.json")
        port = create_demo_portfolio(50000, "conservative")
        loaded = load_demo_portfolio()
        assert loaded is not None
        assert loaded.total_capital == 50000

    def test_add_position_reduces_cash(self, tmp_path, monkeypatch):
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_DIR", tmp_path)
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_FILE", tmp_path / "demo.json")
        port = create_demo_portfolio(100000)

        from market_analyzer.models.opportunity import TradeSpec, LegSpec, LegAction
        ts = TradeSpec(
            ticker="SPY", underlying_price=580.0, target_dte=30,
            target_expiration=date(2026, 4, 24), spec_rationale="test",
            structure_type="iron_condor", order_side="credit",
            wing_width_points=5.0, legs=[
                LegSpec(role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
                        strike=570.0, strike_label="test", expiration=date(2026, 4, 24),
                        days_to_expiry=30, atm_iv_at_expiry=0.22),
            ],
        )
        pos = add_demo_position(port, "SPY", "desk_income_defined", ts, 1.50, 1, 1)
        assert pos.ticker == "SPY"
        assert port.cash_balance < 100000
        assert len(port.positions) == 1

    def test_close_position_records_pnl(self, tmp_path, monkeypatch):
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_DIR", tmp_path)
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_FILE", tmp_path / "demo.json")
        port = create_demo_portfolio(100000)

        from market_analyzer.models.opportunity import TradeSpec, LegSpec, LegAction
        ts = TradeSpec(
            ticker="SPY", underlying_price=580.0, target_dte=30,
            target_expiration=date(2026, 4, 24), spec_rationale="test",
            structure_type="iron_condor", order_side="credit",
            wing_width_points=5.0, legs=[
                LegSpec(role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
                        strike=570.0, strike_label="test", expiration=date(2026, 4, 24),
                        days_to_expiry=30, atm_iv_at_expiry=0.22),
            ],
        )
        pos = add_demo_position(port, "SPY", "desk_income_defined", ts, 1.50, 1, 1)

        closed = close_demo_position(port, pos.position_id, 0.75, "profit_target")
        assert closed is not None
        assert closed.pnl is not None
        assert closed.pnl > 0  # Entered at 1.50, closed at 0.75 (credit trade = profit)
        assert closed.status == "closed"
        assert len(port.positions) == 0
        assert len(port.closed_positions) == 1

    def test_summary(self, tmp_path, monkeypatch):
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_DIR", tmp_path)
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_FILE", tmp_path / "demo.json")
        port = create_demo_portfolio(100000)
        summary = get_demo_summary(port)
        assert summary["capital"] == 100000
        assert summary["open_positions"] == 0
        assert summary["drawdown_pct"] == 0

    def test_no_portfolio_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_FILE", tmp_path / "nonexistent.json")
        assert load_demo_portfolio() is None

    def test_create_aggressive_portfolio(self, tmp_path, monkeypatch):
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_DIR", tmp_path)
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_FILE", tmp_path / "demo.json")
        port = create_demo_portfolio(200000, "aggressive")
        assert port.total_capital == 200000
        assert port.risk_tolerance == "aggressive"
        assert port.current_nlv == 200000
        assert port.peak_nlv == 200000

    def test_portfolio_has_created_timestamp(self, tmp_path, monkeypatch):
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_DIR", tmp_path)
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_FILE", tmp_path / "demo.json")
        port = create_demo_portfolio()
        assert port.created  # Non-empty ISO datetime string
        assert "T" in port.created  # ISO format with time component

    def test_position_structure_type_stored(self, tmp_path, monkeypatch):
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_DIR", tmp_path)
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_FILE", tmp_path / "demo.json")
        port = create_demo_portfolio(100000)

        from market_analyzer.models.opportunity import TradeSpec, LegSpec, LegAction
        ts = TradeSpec(
            ticker="GLD", underlying_price=200.0, target_dte=45,
            target_expiration=date(2026, 5, 15), spec_rationale="test",
            structure_type="credit_spread", order_side="credit",
            wing_width_points=3.0, legs=[
                LegSpec(role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
                        strike=195.0, strike_label="test", expiration=date(2026, 5, 15),
                        days_to_expiry=45, atm_iv_at_expiry=0.18),
            ],
        )
        pos = add_demo_position(port, "GLD", "desk_income_defined", ts, 0.80, 2, 1)
        assert pos.structure_type == "credit_spread"
        assert pos.contracts == 2
        assert pos.entry_price == 0.80

    def test_close_nonexistent_position_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_DIR", tmp_path)
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_FILE", tmp_path / "demo.json")
        port = create_demo_portfolio(100000)
        result = close_demo_position(port, "nonexistent_id", 0.0, "test")
        assert result is None

    def test_summary_win_rate_with_trades(self, tmp_path, monkeypatch):
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_DIR", tmp_path)
        monkeypatch.setattr("market_analyzer.demo.portfolio.DEMO_FILE", tmp_path / "demo.json")
        port = create_demo_portfolio(100000)

        from market_analyzer.models.opportunity import TradeSpec, LegSpec, LegAction

        def _make_ts(ticker: str) -> TradeSpec:
            return TradeSpec(
                ticker=ticker, underlying_price=580.0, target_dte=30,
                target_expiration=date(2026, 4, 24), spec_rationale="test",
                structure_type="iron_condor", order_side="credit",
                wing_width_points=5.0, legs=[
                    LegSpec(role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
                            strike=570.0, strike_label="test", expiration=date(2026, 4, 24),
                            days_to_expiry=30, atm_iv_at_expiry=0.22),
                ],
            )

        # Add and close a winning trade (credit at 1.50, close at 0.50)
        pos1 = add_demo_position(port, "SPY", "desk_income_defined", _make_ts("SPY"), 1.50, 1, 1)
        close_demo_position(port, pos1.position_id, 0.50, "profit_target")

        # Add and close a losing trade (credit at 0.50, close at 1.50)
        pos2 = add_demo_position(port, "QQQ", "desk_income_defined", _make_ts("QQQ"), 0.50, 1, 1)
        close_demo_position(port, pos2.position_id, 1.50, "stop_loss")

        summary = get_demo_summary(port)
        assert summary["closed_trades"] == 2
        assert summary["win_rate"] == 0.5  # 1 winner out of 2
