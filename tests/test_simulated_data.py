"""Tests for simulated market data layer.

Verifies that SimulatedMarketData generates realistic-looking option chains
and integrates correctly with the full MA pipeline.

Trust: UNRELIABLE — this layer is for testing/development only.
"""
from __future__ import annotations

import datetime
import pytest
from datetime import date

from market_analyzer.adapters.simulated import (
    SimulatedMarketData,
    SimulatedMetrics,
    SimulatedAccount,
    create_calm_market,
    create_volatile_market,
    create_crash_scenario,
    create_india_market,
    _generate_option_quote,
    _get_strike_step,
)
from market_analyzer.models.opportunity import LegAction, LegSpec


class TestSimulatedMarketData:
    def test_underlying_price(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        assert sim.get_underlying_price("SPY") == 580.0
        assert sim.get_underlying_price("FAKE") is None

    def test_underlying_price_case_insensitive(self):
        sim = SimulatedMarketData({"spy": {"price": 580.0, "iv": 0.18}})
        assert sim.get_underlying_price("SPY") == 580.0
        assert sim.get_underlying_price("spy") == 580.0

    def test_provider_name(self):
        sim = SimulatedMarketData({})
        assert sim.provider_name == "simulated"

    def test_option_chain_generated(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        chain = sim.get_option_chain("SPY")
        # 4 expirations × 2 types × N strikes — expect at least 20
        assert len(chain) > 20

    def test_chain_quote_structure(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        chain = sim.get_option_chain("SPY")
        for q in chain[:5]:
            assert q.ticker == "SPY"
            assert q.bid > 0
            assert q.ask >= q.bid
            assert q.mid == pytest.approx((q.bid + q.ask) / 2, abs=0.02)

    def test_unknown_ticker_returns_empty_chain(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        assert sim.get_option_chain("UNKNOWN") == []

    def test_chain_has_both_types(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        chain = sim.get_option_chain("SPY")
        calls = [q for q in chain if q.option_type == "call"]
        puts = [q for q in chain if q.option_type == "put"]
        assert len(calls) > 0
        assert len(puts) > 0

    def test_chain_has_four_expirations(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        chain = sim.get_option_chain("SPY")
        expirations = {q.expiration for q in chain}
        assert len(expirations) == 4

    def test_expiration_filter(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        target_exp = date.today() + datetime.timedelta(days=35)
        chain = sim.get_option_chain("SPY", expiration=target_exp)
        assert all(q.expiration == target_exp for q in chain)
        assert len(chain) > 0

    def test_atm_options_have_highest_time_value(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        chain = sim.get_option_chain("SPY")
        calls_35 = [
            q for q in chain
            if q.option_type == "call"
            and q.expiration == date.today() + datetime.timedelta(days=35)
        ]
        if calls_35:
            atm = min(calls_35, key=lambda q: abs(q.strike - 580))
            deep_otm = [q for q in calls_35 if q.strike > 610]
            if deep_otm:
                assert atm.mid > deep_otm[0].mid

    def test_greeks_present_and_non_none(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        chain = sim.get_option_chain("SPY")
        for q in chain[:5]:
            assert q.delta is not None
            assert q.gamma is not None
            assert q.theta is not None
            assert q.vega is not None

    def test_put_delta_negative(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        chain = sim.get_option_chain("SPY")
        puts = [q for q in chain if q.option_type == "put"]
        for p in puts:
            assert p.delta < 0, f"Put delta should be negative, got {p.delta}"

    def test_call_delta_positive(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        chain = sim.get_option_chain("SPY")
        calls = [q for q in chain if q.option_type == "call"]
        for c in calls:
            assert c.delta > 0, f"Call delta should be positive, got {c.delta}"

    def test_theta_negative(self):
        """Theta must be negative (time decay costs the holder)."""
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        chain = sim.get_option_chain("SPY")
        for q in chain[:10]:
            assert q.theta is not None
            assert q.theta <= 0, f"Theta should be <= 0, got {q.theta}"

    def test_vega_positive(self):
        """Vega (sensitivity to IV increase) must be positive."""
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        chain = sim.get_option_chain("SPY")
        for q in chain[:10]:
            assert q.vega is not None
            assert q.vega >= 0, f"Vega should be >= 0, got {q.vega}"

    def test_simulate_move(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        sim.simulate_move("SPY", -0.05)  # −5 %
        assert sim.get_underlying_price("SPY") == pytest.approx(551.0, abs=0.1)

    def test_simulate_move_positive(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        sim.simulate_move("SPY", 0.10)  # +10 %
        assert sim.get_underlying_price("SPY") == pytest.approx(638.0, abs=0.1)

    def test_update_price(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        sim.update_price("SPY", 600.0)
        assert sim.get_underlying_price("SPY") == 600.0

    def test_simulate_move_unknown_ticker_no_error(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0}})
        sim.simulate_move("FAKE", -0.10)  # Should not raise

    def test_get_quotes_for_legs(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        exp = date.today() + datetime.timedelta(days=35)
        legs = [
            LegSpec(
                role="short_put",
                action=LegAction.SELL_TO_OPEN,
                option_type="put",
                strike=570.0,
                strike_label="test",
                expiration=exp,
                days_to_expiry=35,
                atm_iv_at_expiry=0.18,
            ),
        ]
        quotes = sim.get_quotes(legs, ticker="SPY")
        assert len(quotes) == 1
        assert quotes[0] is not None
        assert quotes[0].strike == 570.0
        assert quotes[0].bid > 0

    def test_get_greeks_returns_dict(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        exp = date.today() + datetime.timedelta(days=35)
        legs = [
            LegSpec(
                role="short_put",
                action=LegAction.SELL_TO_OPEN,
                option_type="put",
                strike=570.0,
                strike_label="test",
                expiration=exp,
                days_to_expiry=35,
                atm_iv_at_expiry=0.18,
            ),
        ]
        greeks = sim.get_greeks(legs)
        assert "570.0P" in greeks or "570P" in greeks or any("570" in k for k in greeks)

    def test_put_skew_present(self):
        """OTM puts should carry higher IV than ATM puts (volatility skew)."""
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        chain = sim.get_option_chain("SPY")
        atm_put = min(
            [q for q in chain if q.option_type == "put"],
            key=lambda q: abs(q.strike - 580),
        )
        otm_puts = [q for q in chain if q.option_type == "put" and q.strike < 560]
        if otm_puts:
            far_otm = min(otm_puts, key=lambda q: abs(q.strike - 550))
            assert far_otm.implied_volatility >= atm_put.implied_volatility

    def test_volume_open_interest_positive(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18}})
        chain = sim.get_option_chain("SPY")
        # ATM options should have positive volume and OI
        atm = min(chain, key=lambda q: abs(q.strike - 580))
        assert atm.volume >= 0
        assert atm.open_interest >= 0


class TestSimulatedMetrics:
    def test_returns_iv_rank(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18, "iv_rank": 43}})
        metrics = SimulatedMetrics(sim)
        result = metrics.get_metrics(["SPY"])
        assert "SPY" in result
        assert result["SPY"].iv_rank == 43

    def test_returns_iv_30_day(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18, "iv_rank": 43}})
        metrics = SimulatedMetrics(sim)
        result = metrics.get_metrics(["SPY"])
        assert result["SPY"].iv_30_day == pytest.approx(0.18)

    def test_unknown_ticker_absent_from_result(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18, "iv_rank": 43}})
        metrics = SimulatedMetrics(sim)
        result = metrics.get_metrics(["FAKE"])
        assert "FAKE" not in result

    def test_multiple_tickers(self):
        sim = SimulatedMarketData({
            "SPY": {"price": 580.0, "iv": 0.18, "iv_rank": 43},
            "QQQ": {"price": 490.0, "iv": 0.25, "iv_rank": 55},
        })
        metrics = SimulatedMetrics(sim)
        result = metrics.get_metrics(["SPY", "QQQ"])
        assert "SPY" in result
        assert "QQQ" in result
        assert result["QQQ"].iv_rank == 55

    def test_iv_percentile_derived_from_rank(self):
        sim = SimulatedMarketData({"SPY": {"price": 580.0, "iv": 0.18, "iv_rank": 50}})
        metrics = SimulatedMetrics(sim)
        result = metrics.get_metrics(["SPY"])
        # iv_percentile = iv_rank * 1.1
        assert result["SPY"].iv_percentile == pytest.approx(55.0, abs=0.2)


class TestSimulatedAccount:
    def test_balance_default(self):
        acct = SimulatedAccount()
        bal = acct.get_balance()
        assert bal.net_liquidating_value == 100_000
        assert bal.source == "simulated"
        assert bal.account_number == "SIM-001"

    def test_balance_custom(self):
        acct = SimulatedAccount(nlv=200_000, cash=160_000, bp=150_000)
        bal = acct.get_balance()
        assert bal.net_liquidating_value == 200_000
        assert bal.derivative_buying_power == 150_000
        assert bal.maintenance_requirement == pytest.approx(50_000)

    def test_currency(self):
        acct = SimulatedAccount()
        bal = acct.get_balance()
        assert bal.currency == "USD"


class TestPresetScenarios:
    def test_calm_market_prices(self):
        sim = create_calm_market()
        assert sim.get_underlying_price("SPY") == 580.0
        assert sim.get_underlying_price("QQQ") == 500.0

    def test_calm_market_chain(self):
        sim = create_calm_market()
        chain = sim.get_option_chain("SPY")
        assert len(chain) > 0

    def test_volatile_market_prices(self):
        sim = create_volatile_market()
        assert sim.get_underlying_price("SPY") == 550.0

    def test_crash_scenario_prices(self):
        sim = create_crash_scenario()
        assert sim.get_underlying_price("SPY") == 480.0

    def test_crash_iv_is_very_high(self):
        """Crash scenario IV should exceed 0.30 (extreme stress)."""
        sim = create_crash_scenario()
        chain = sim.get_option_chain("SPY")
        atm = min(chain, key=lambda q: abs(q.strike - 480))
        assert atm.implied_volatility is not None
        assert atm.implied_volatility > 0.30

    def test_india_market_prices(self):
        sim = create_india_market()
        assert sim.get_underlying_price("NIFTY") == 26_000.0
        assert sim.get_underlying_price("BANKNIFTY") == 50_000.0

    def test_india_market_chain(self):
        sim = create_india_market()
        chain = sim.get_option_chain("NIFTY")
        assert len(chain) > 0

    def test_volatile_has_higher_iv_than_calm(self):
        calm = create_calm_market()
        volatile = create_volatile_market()
        calm_info = calm._tickers["SPY"]
        vol_info = volatile._tickers["SPY"]
        assert vol_info["iv"] > calm_info["iv"]

    def test_crash_has_higher_iv_rank_than_volatile(self):
        volatile = create_volatile_market()
        crash = create_crash_scenario()
        assert crash._tickers["SPY"]["iv_rank"] > volatile._tickers["SPY"]["iv_rank"]


class TestIntegrationWithMA:
    def test_full_pipeline_with_simulated_data(self):
        """Simulated data should wire through the entire MA service layer."""
        from market_analyzer import MarketAnalyzer, DataService

        sim = create_calm_market()
        ma = MarketAnalyzer(
            data_service=DataService(),
            market_data=sim,
            market_metrics=SimulatedMetrics(sim),
        )

        assert ma.quotes.has_broker is True
        assert ma.quotes.source == "simulated"

    def test_get_chain_via_quote_service(self):
        from market_analyzer import MarketAnalyzer, DataService

        sim = create_calm_market()
        ma = MarketAnalyzer(
            data_service=DataService(),
            market_data=sim,
            market_metrics=SimulatedMetrics(sim),
        )

        snapshot = ma.quotes.get_chain("SPY")
        assert snapshot is not None
        assert len(snapshot.quotes) > 20

    def test_regime_plus_simulated_quotes(self):
        """Regime detection (yfinance) + simulated quotes should coexist."""
        from market_analyzer import MarketAnalyzer, DataService

        sim = create_calm_market()
        ma = MarketAnalyzer(
            data_service=DataService(),
            market_data=sim,
            market_metrics=SimulatedMetrics(sim),
        )

        regime = ma.regime.detect("SPY")
        assert regime.regime.value in (1, 2, 3, 4)


class TestStrikeStep:
    def test_low_price_1_dollar_steps(self):
        assert _get_strike_step(30.0) == 1.0

    def test_mid_price_2_5_steps(self):
        assert _get_strike_step(150.0) == 2.5

    def test_high_price_5_steps(self):
        assert _get_strike_step(400.0) == 5.0

    def test_very_high_price_10_steps(self):
        assert _get_strike_step(600.0) == 10.0

    def test_boundary_50_uses_2_5(self):
        # price == 50 → second branch (< 200)
        assert _get_strike_step(50.0) == 2.5

    def test_boundary_200_uses_5(self):
        # price == 200 → third branch (< 500)
        assert _get_strike_step(200.0) == 5.0

    def test_boundary_500_uses_10(self):
        # price == 500 → final branch
        assert _get_strike_step(500.0) == 10.0


class TestGenerateOptionQuote:
    def test_call_bid_ask_spread_positive(self):
        exp = date.today() + datetime.timedelta(days=35)
        q = _generate_option_quote("SPY", 580.0, "call", exp, 35, 580.0, 0.18)
        assert q.ask > q.bid

    def test_put_bid_ask_spread_positive(self):
        exp = date.today() + datetime.timedelta(days=35)
        q = _generate_option_quote("SPY", 580.0, "put", exp, 35, 580.0, 0.18)
        assert q.ask > q.bid

    def test_itm_call_has_intrinsic_value(self):
        exp = date.today() + datetime.timedelta(days=35)
        # Deep ITM call: strike = 550, underlying = 580 → intrinsic = 30
        q = _generate_option_quote("SPY", 550.0, "call", exp, 35, 580.0, 0.18)
        assert q.mid >= 30.0

    def test_deep_otm_put_cheap(self):
        exp = date.today() + datetime.timedelta(days=35)
        # Very OTM put: strike = 450, underlying = 580 → close to zero value
        q = _generate_option_quote("SPY", 450.0, "put", exp, 35, 580.0, 0.18)
        assert q.mid < 1.0

    def test_dte_1_gives_minimal_time_value(self):
        exp = date.today() + datetime.timedelta(days=1)
        q_1 = _generate_option_quote("SPY", 580.0, "call", exp, 1, 580.0, 0.18)
        exp60 = date.today() + datetime.timedelta(days=60)
        q_60 = _generate_option_quote("SPY", 580.0, "call", exp60, 60, 580.0, 0.18)
        assert q_60.mid > q_1.mid


class TestRefreshAndSnapshot:
    def test_refresh_saves_to_disk(self, tmp_path, monkeypatch):
        """refresh_simulation_data saves JSON to disk."""
        monkeypatch.setattr(
            "market_analyzer.adapters.simulated.SIM_SNAPSHOT_FILE",
            tmp_path / "snapshot.json",
        )

        # Create a minimal mock MA
        class MockQuotes:
            source = "test"

            def get_metrics(self, t):
                return None

        class MockTech:
            current_price = 580.0
            atr_pct = 1.2

            class rsi:
                value = 52.0

        class MockVol:
            front_iv = 0.18

        class MockRegime:
            class regime:
                value = 1

            confidence = 0.95

        class MockMA:
            quotes = MockQuotes()

            class technicals:
                @staticmethod
                def snapshot(t):
                    return MockTech()

            class vol_surface:
                @staticmethod
                def surface(t):
                    return MockVol()

            class regime:
                @staticmethod
                def detect(t):
                    return MockRegime()

        from market_analyzer.adapters.simulated import refresh_simulation_data

        result = refresh_simulation_data(MockMA(), ["SPY"])
        assert "SPY" in result["tickers"]
        assert result["tickers"]["SPY"]["price"] == 580.0
        assert (tmp_path / "snapshot.json").exists()

    def test_create_from_snapshot(self, tmp_path, monkeypatch):
        """create_from_snapshot loads saved data."""
        import json

        snapshot_file = tmp_path / "snapshot.json"
        monkeypatch.setattr(
            "market_analyzer.adapters.simulated.SIM_SNAPSHOT_FILE", snapshot_file
        )

        snapshot_file.write_text(
            json.dumps(
                {
                    "captured_at": "2026-03-21T10:00:00",
                    "source": "test",
                    "tickers": {
                        "SPY": {"price": 580.0, "iv": 0.18, "iv_rank": 43, "atr_pct": 1.2},
                        "GLD": {"price": 420.0, "iv": 0.25, "iv_rank": 68, "atr_pct": 2.5},
                    },
                }
            )
        )

        from market_analyzer.adapters.simulated import create_from_snapshot

        sim = create_from_snapshot()
        assert sim is not None
        assert sim.get_underlying_price("SPY") == 580.0
        assert sim.get_underlying_price("GLD") == 420.0

        chain = sim.get_option_chain("SPY")
        assert len(chain) > 0

    def test_no_snapshot_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "market_analyzer.adapters.simulated.SIM_SNAPSHOT_FILE",
            tmp_path / "nonexistent.json",
        )

        from market_analyzer.adapters.simulated import create_from_snapshot

        assert create_from_snapshot() is None

    def test_snapshot_info(self, tmp_path, monkeypatch):
        import json
        from datetime import datetime

        snapshot_file = tmp_path / "snapshot.json"
        monkeypatch.setattr(
            "market_analyzer.adapters.simulated.SIM_SNAPSHOT_FILE", snapshot_file
        )

        snapshot_file.write_text(
            json.dumps(
                {
                    "captured_at": datetime.now().isoformat(),
                    "source": "tastytrade",
                    "tickers": {
                        "SPY": {"price": 580.0},
                        "QQQ": {"price": 490.0},
                    },
                }
            )
        )

        from market_analyzer.adapters.simulated import get_snapshot_info

        info = get_snapshot_info()
        assert info is not None
        assert info["ticker_count"] == 2
        assert info["source"] == "tastytrade"
        assert info["age_hours"] is not None

    def test_snapshot_skips_error_tickers(self, tmp_path, monkeypatch):
        import json

        snapshot_file = tmp_path / "snapshot.json"
        monkeypatch.setattr(
            "market_analyzer.adapters.simulated.SIM_SNAPSHOT_FILE", snapshot_file
        )

        snapshot_file.write_text(
            json.dumps(
                {
                    "captured_at": "2026-03-21T10:00:00",
                    "source": "test",
                    "tickers": {
                        "SPY": {"price": 580.0, "iv": 0.18},
                        "BAD": {"error": "fetch failed"},
                    },
                }
            )
        )

        from market_analyzer.adapters.simulated import create_from_snapshot

        sim = create_from_snapshot()
        assert sim is not None
        assert sim.get_underlying_price("SPY") == 580.0
        assert sim.get_underlying_price("BAD") is None
