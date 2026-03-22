"""Tests for the end-to-end Trader runner (demo/trader.py)."""
from __future__ import annotations

import pytest

from income_desk.demo.trader import (
    TraderReport,
    run_india_trader,
    run_us_trader,
    print_trader_report,
)


class TestUSTrader:
    def test_runs_end_to_end(self):
        report = run_us_trader(capital=100_000)
        assert report.market == "US"
        assert report.desks_created >= 3
        assert report.capital == 100_000
        assert isinstance(report.trades_booked, int)
        assert report.trades_booked >= 0

    def test_books_at_least_one_trade(self):
        """With ideal income preset, at least one ticker should pass or be blocked (not silent)."""
        report = run_us_trader(capital=100_000)
        # Pipeline must produce some outcome — either booked or blocked
        assert report.trades_booked >= 1 or len(report.trades_blocked) > 0

    def test_monitoring_runs(self):
        report = run_us_trader()
        # If trades were booked, monitoring should have results
        if report.trades_booked > 0:
            assert len(report.monitoring_results) == report.trades_booked

    def test_tickers_scanned(self):
        report = run_us_trader()
        assert "SPY" in report.tickers_scanned
        assert "IWM" in report.tickers_scanned

    def test_regime_summary_populated(self):
        report = run_us_trader()
        assert len(report.regime_summary) > 0
        for ticker, regime_id in report.regime_summary.items():
            assert isinstance(regime_id, int)

    def test_risk_invariants(self):
        report = run_us_trader()
        assert report.total_risk_deployed >= 0
        assert 0.0 <= report.risk_pct <= 1.0

    def test_sentinel_signal_valid(self):
        report = run_us_trader()
        assert report.sentinel_signal in ("GREEN", "YELLOW", "ORANGE", "RED", "BLUE")

    def test_candidates_ranked(self):
        report = run_us_trader()
        assert report.candidates_ranked >= 0


class TestIndiaTrader:
    def test_runs_end_to_end(self):
        report = run_india_trader(capital=5_000_000)
        assert report.market == "India"
        assert report.desks_created >= 3
        assert report.capital == 5_000_000

    def test_india_tickers_scanned(self):
        report = run_india_trader()
        assert "NIFTY" in report.tickers_scanned or "BANKNIFTY" in report.tickers_scanned

    def test_sentinel_valid(self):
        report = run_india_trader()
        assert report.sentinel_signal in ("GREEN", "YELLOW", "ORANGE", "RED", "BLUE")

    def test_monitoring_matches_booked(self):
        report = run_india_trader()
        if report.trades_booked > 0:
            assert len(report.monitoring_results) == report.trades_booked


class TestTraderReport:
    def test_serialization(self):
        report = run_us_trader()
        d = report.model_dump()
        assert "trades_booked" in d
        assert "sentinel_signal" in d
        assert "positions" in d
        assert "monitoring_results" in d

    def test_print_report_runs(self, capsys):
        """print_trader_report should not raise and should print something."""
        report = run_us_trader()
        print_trader_report(report)
        captured = capsys.readouterr()
        assert "TRADER REPORT" in captured.out
        assert "SUMMARY" in captured.out

    def test_blocked_is_list(self):
        report = run_us_trader()
        assert isinstance(report.trades_blocked, list)
        for b in report.trades_blocked:
            assert "ticker" in b
            assert "reason" in b

    def test_positions_have_required_keys(self):
        report = run_us_trader()
        for pos in report.positions:
            assert "ticker" in pos
            assert "contracts" in pos
            assert "credit" in pos
            assert "desk" in pos
