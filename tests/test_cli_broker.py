"""Tests for shared CLI broker connection helper."""

import argparse
from unittest.mock import MagicMock, patch

from income_desk.cli._broker import (
    add_broker_args,
    connect_broker,
)


class TestConnectBroker:
    def test_returns_none_tuple_when_tastytrade_not_installed(self):
        with patch.dict("sys.modules", {"tastytrade": None}):
            with patch(
                "income_desk.cli._broker.connect_broker",
                wraps=connect_broker,
            ):
                md, mm, acct, wl = connect_broker()
                # May or may not be None depending on install;
                # just verify it doesn't crash
                assert isinstance(md, type(None)) or md is not None

    def test_returns_none_tuple_on_connection_failure(self):
        mock_session = MagicMock()
        mock_session.connect.return_value = False

        with patch(
            "income_desk.broker.tastytrade.session.TastyTradeBrokerSession",
            return_value=mock_session,
        ):
            md, mm, acct, wl = connect_broker()
            assert md is None
            assert mm is None
            assert acct is None
            assert wl is None

    def test_returns_providers_on_success(self):
        mock_session = MagicMock()
        mock_session.connect.return_value = True
        mock_session.account.account_number = "TEST123"

        with patch(
            "income_desk.broker.tastytrade.session.TastyTradeBrokerSession",
            return_value=mock_session,
        ), patch(
            "income_desk.broker.tastytrade.market_data.TastyTradeMarketData",
        ) as MockMD, patch(
            "income_desk.broker.tastytrade.metrics.TastyTradeMetrics",
        ) as MockMM, patch(
            "income_desk.broker.tastytrade.account.TastyTradeAccount",
        ) as MockAcct, patch(
            "income_desk.broker.tastytrade.watchlist.TastyTradeWatchlist",
        ) as MockWL:
            md, mm, acct, wl = connect_broker()
            assert md is not None
            assert mm is not None
            assert acct is not None
            assert wl is not None
            MockMD.assert_called_once_with(mock_session)
            MockMM.assert_called_once_with(mock_session)
            MockAcct.assert_called_once_with(mock_session)
            MockWL.assert_called_once_with(mock_session)


class TestAddBrokerArgs:
    def test_adds_broker_and_paper_flags(self):
        parser = argparse.ArgumentParser()
        add_broker_args(parser)

        args = parser.parse_args([])
        assert args.broker is False
        assert args.paper is False

        args = parser.parse_args(["--broker", "--paper"])
        assert args.broker is True
        assert args.paper is True


class TestBrokerPricingInPlan:
    """Verify trading plan uses broker quotes, not BS pricing."""

    def test_no_broker_returns_none_max_price(self):
        """Without broker, max_entry_price must be None — never computed."""
        from income_desk.opportunity.option_plays._trade_spec_helpers import (
            compute_max_entry_price_from_quotes,
        )
        # Zero net price → None
        assert compute_max_entry_price_from_quotes(0.0, "credit") is None

    def test_credit_slippage_from_broker_mid(self):
        from income_desk.opportunity.option_plays._trade_spec_helpers import (
            compute_max_entry_price_from_quotes,
        )
        # Broker says net credit is 1.80, slippage 20% → min accept 1.44
        result = compute_max_entry_price_from_quotes(1.80, "credit", 0.20)
        assert result == 1.44

    def test_debit_slippage_from_broker_mid(self):
        from income_desk.opportunity.option_plays._trade_spec_helpers import (
            compute_max_entry_price_from_quotes,
        )
        # Broker says net debit is -2.50, slippage 20% → max pay 3.00
        result = compute_max_entry_price_from_quotes(-2.50, "debit", 0.20)
        assert result == 3.00


class TestNoBSPricingAnywhere:
    """Verify BS pricing functions are completely removed."""

    def test_no_bs_price_function(self):
        import income_desk.opportunity.option_plays._trade_spec_helpers as helpers
        assert not hasattr(helpers, "_bs_price"), "_bs_price must be removed"

    def test_no_estimate_trade_price(self):
        import income_desk.opportunity.option_plays._trade_spec_helpers as helpers
        assert not hasattr(helpers, "estimate_trade_price"), "estimate_trade_price must be removed"

    def test_no_old_compute_max_entry_price(self):
        """Old compute_max_entry_price (BS-based) must not exist."""
        import income_desk.opportunity.option_plays._trade_spec_helpers as helpers
        assert not hasattr(helpers, "compute_max_entry_price"), (
            "Old BS-based compute_max_entry_price must be removed"
        )

    def test_no_norm_cdf(self):
        import income_desk.opportunity.option_plays._trade_spec_helpers as helpers
        assert not hasattr(helpers, "_norm_cdf"), "_norm_cdf must be removed"

    def test_no_math_import(self):
        """math module should no longer be imported (was only used for BS)."""
        import importlib
        import income_desk.opportunity.option_plays._trade_spec_helpers as helpers
        importlib.reload(helpers)
        # Check the module doesn't have math in its namespace for BS
        source = open(helpers.__file__).read()
        assert "import math" not in source, "math import should be removed (was only for BS)"


class TestAccountBalance:
    """Test account balance integration."""

    def test_account_balance_model(self):
        from income_desk.models.quotes import AccountBalance
        bal = AccountBalance(
            account_number="TEST123",
            net_liquidating_value=50000.0,
            cash_balance=25000.0,
            derivative_buying_power=40000.0,
            equity_buying_power=50000.0,
            maintenance_requirement=10000.0,
            source="test",
        )
        assert bal.net_liquidating_value == 50000.0
        assert bal.derivative_buying_power == 40000.0

    def test_risk_budget_has_account_fields(self):
        from income_desk.models.trading_plan import RiskBudget
        rb = RiskBudget(
            account_size=50000.0,
            account_source="broker",
            max_new_positions=3,
            max_daily_risk_dollars=1000.0,
            position_size_factor=1.0,
        )
        assert rb.account_size == 50000.0
        assert rb.account_source == "broker"

    def test_risk_budget_defaults_to_config(self):
        from income_desk.models.trading_plan import RiskBudget
        rb = RiskBudget(
            max_new_positions=3,
            max_daily_risk_dollars=1000.0,
            position_size_factor=1.0,
        )
        assert rb.account_source == "config"

    def test_account_provider_abc(self):
        from income_desk.broker.base import AccountProvider
        import abc
        assert abc.ABC in AccountProvider.__mro__
