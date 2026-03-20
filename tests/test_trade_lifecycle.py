"""Tests for trade_lifecycle APIs — all gaps resolved."""

import pytest
from datetime import date

from market_analyzer.trade_spec_factory import build_iron_condor, build_credit_spread, build_debit_spread
from market_analyzer.trade_lifecycle import (
    AggregatedGreeks,
    AlignedStrikes,
    Breakevens,
    ExitMonitorResult,
    FilteredTrades,
    IncomeEntryCheck,
    IncomeYield,
    POPEstimate,
    TradeHealthCheck,
    aggregate_greeks,
    check_income_entry,
    check_trade_health,
    compute_breakevens,
    compute_income_yield,
    estimate_pop,
    filter_trades_by_account,
    monitor_exit_conditions,
)
from market_analyzer.models.quotes import OptionQuote


def _ic_spec():
    return build_iron_condor(
        ticker="GLD", underlying_price=221.0,
        short_put=218.0, long_put=213.0,
        short_call=225.0, long_call=230.0,
        expiration="2026-04-17", entry_price=0.72,
    )


def _cs_spec():
    return build_credit_spread(
        ticker="SPY", underlying_price=600.0,
        short_strike=585.0, long_strike=580.0,
        option_type="put", expiration="2026-04-17",
        entry_price=0.45,
    )


def _ds_spec():
    return build_debit_spread(
        ticker="AAPL", underlying_price=210.0,
        long_strike=210.0, short_strike=215.0,
        option_type="call", expiration="2026-04-17",
        entry_price=1.80,
    )


# ── F5: Income Yield ──


class TestIncomeYield:
    def test_iron_condor_yield(self):
        y = compute_income_yield(_ic_spec(), entry_credit=0.72, contracts=1)
        assert y is not None
        assert y.credit_per_spread == 0.72
        assert y.wing_width == 5.0
        assert y.max_profit == 72.0
        assert y.max_loss == 428.0
        assert y.credit_to_width_pct == pytest.approx(0.144)
        assert y.return_on_capital_pct > 0
        assert y.annualized_roc_pct > y.return_on_capital_pct

    def test_credit_spread_yield(self):
        y = compute_income_yield(_cs_spec(), entry_credit=0.45, contracts=2)
        assert y is not None
        assert y.contracts == 2
        assert y.max_profit == 90.0  # 0.45 * 100 * 2

    def test_debit_trade_returns_none(self):
        y = compute_income_yield(_ds_spec(), entry_credit=1.80)
        assert y is None

    def test_breakevens_on_ic(self):
        y = compute_income_yield(_ic_spec(), entry_credit=0.72)
        assert y.breakeven_low == pytest.approx(217.28)
        assert y.breakeven_high == pytest.approx(225.72)


# ── F8: Breakevens ──


class TestBreakevens:
    def test_ic_breakevens(self):
        b = compute_breakevens(_ic_spec(), entry_price=0.72)
        assert b.low == pytest.approx(217.28)
        assert b.high == pytest.approx(225.72)

    def test_credit_spread_breakeven(self):
        b = compute_breakevens(_cs_spec(), entry_price=0.45)
        assert b.low == pytest.approx(584.55)  # 585 - 0.45
        assert b.high is None

    def test_debit_spread_breakeven(self):
        b = compute_breakevens(_ds_spec(), entry_price=1.80)
        assert b.low == pytest.approx(211.80)  # 210 + 1.80
        assert b.high is None


# ── F9: Greeks Aggregation ──


class TestAggregateGreeks:
    def test_ic_greeks(self):
        spec = _ic_spec()
        quotes = [
            OptionQuote(ticker="GLD", expiration=date(2026, 4, 17), strike=218,
                        option_type="put", bid=0, ask=0, mid=0,
                        delta=-0.25, gamma=0.02, theta=-0.05, vega=0.10),
            OptionQuote(ticker="GLD", expiration=date(2026, 4, 17), strike=213,
                        option_type="put", bid=0, ask=0, mid=0,
                        delta=-0.10, gamma=0.01, theta=-0.02, vega=0.05),
            OptionQuote(ticker="GLD", expiration=date(2026, 4, 17), strike=225,
                        option_type="call", bid=0, ask=0, mid=0,
                        delta=0.20, gamma=0.02, theta=-0.04, vega=0.08),
            OptionQuote(ticker="GLD", expiration=date(2026, 4, 17), strike=230,
                        option_type="call", bid=0, ask=0, mid=0,
                        delta=0.08, gamma=0.01, theta=-0.01, vega=0.03),
        ]
        g = aggregate_greeks(spec, quotes, contracts=2)
        assert g is not None
        # STO put: +0.25 delta, BTO put: -(-0.10)=+0.10, STO call: -0.20, BTO call: +0.08
        # Net delta = 0.25 + (-0.10) + (-0.20) + 0.08 = 0.03
        assert g.net_delta == pytest.approx(0.03, abs=0.01)
        assert g.net_theta > 0  # Income trade: positive theta
        assert g.daily_theta_dollars > 0
        assert g.contracts == 2

    def test_missing_greeks_returns_none(self):
        spec = _ic_spec()
        quotes = [
            OptionQuote(ticker="GLD", expiration=date(2026, 4, 17), strike=218,
                        option_type="put", bid=0, ask=0, mid=0),
        ] * 4
        g = aggregate_greeks(spec, quotes)
        assert g is None  # No delta data

    def test_wrong_count_returns_none(self):
        spec = _ic_spec()
        g = aggregate_greeks(spec, [])
        assert g is None


# ── F7: POP Estimate ──


class TestPOPEstimate:
    def test_ic_pop_r1(self):
        pop = estimate_pop(
            _ic_spec(), entry_price=0.72, regime_id=1,
            atr_pct=1.2, current_price=221.0,
        )
        assert pop is not None
        assert 0.3 < pop.pop_pct < 0.99  # Reasonable range for IC
        assert pop.method == "regime_historical"
        assert pop.regime_id == 1

    def test_ic_pop_lower_in_r4(self):
        pop_r1 = estimate_pop(
            _ic_spec(), entry_price=0.72, regime_id=1,
            atr_pct=1.2, current_price=221.0,
        )
        pop_r4 = estimate_pop(
            _ic_spec(), entry_price=0.72, regime_id=4,
            atr_pct=1.2, current_price=221.0,
        )
        assert pop_r1 is not None and pop_r4 is not None
        assert pop_r4.pop_pct < pop_r1.pop_pct  # R4 = worse for IC

    def test_debit_spread_pop(self):
        pop = estimate_pop(
            _ds_spec(), entry_price=1.80, regime_id=3,
            atr_pct=2.0, current_price=210.0,
        )
        assert pop is not None
        assert 0.0 < pop.pop_pct < 1.0

    def test_expected_value(self):
        pop = estimate_pop(
            _ic_spec(), entry_price=0.72, regime_id=1,
            atr_pct=1.2, current_price=221.0,
        )
        assert pop is not None
        # EV should reflect POP × profit - (1-POP) × loss
        assert isinstance(pop.expected_value, float)

    def test_max_loss_is_positive_for_valid_ic(self):
        """Regression: max_loss must be positive for a 5-wide IC with credit < wing width."""
        pop = estimate_pop(
            _ic_spec(), entry_price=0.72, regime_id=1,
            atr_pct=1.2, current_price=221.0,
        )
        assert pop is not None
        assert pop.max_loss > 0, f"max_loss should be positive, got {pop.max_loss}"
        # For 5-wide IC with $0.72 credit: max_loss = (5.0 - 0.72) * 100 = $428
        assert abs(pop.max_loss - 428.0) < 1.0, f"Expected ~$428, got {pop.max_loss}"

    def test_max_loss_zero_when_credit_exceeds_wing_returns_degraded_result(self):
        """Regression: when credit estimate exceeds wing width, return degraded POPEstimate
        with max_loss=0 and a data_gap — do NOT silently use negative max_loss."""
        # 5-wide IC but entry_price=6.10 (overestimated without broker)
        pop = estimate_pop(
            _ic_spec(), entry_price=6.10, regime_id=1,
            atr_pct=1.2, current_price=221.0,
        )
        assert pop is not None, "Should return degraded result, not None"
        assert pop.max_loss == 0.0, f"max_loss should be 0.0 (degraded), got {pop.max_loss}"
        assert pop.expected_value == 0.0
        assert len(pop.data_gaps) > 0, "Should have a data_gap explaining why EV is unavailable"
        assert pop.trade_quality == "poor"

    def test_max_profit_correct_for_5_wide_ic(self):
        """Regression: max_profit = credit × lot_size = 0.72 × 100 = $72."""
        pop = estimate_pop(
            _ic_spec(), entry_price=0.72, regime_id=1,
            atr_pct=1.2, current_price=221.0,
        )
        assert pop is not None
        assert abs(pop.max_profit - 72.0) < 1.0, f"Expected max_profit ~$72, got {pop.max_profit}"


# ── F10: Income Entry Check ──


class TestIncomeEntry:
    def test_ideal_conditions(self):
        check = check_income_entry(
            iv_rank=45.0, iv_percentile=50.0, dte=35,
            rsi=50.0, atr_pct=1.2, regime_id=1,
        )
        assert check.confirmed
        assert check.score > 0.8

    def test_r4_blocks_entry(self):
        check = check_income_entry(
            iv_rank=45.0, iv_percentile=50.0, dte=35,
            rsi=50.0, atr_pct=1.2, regime_id=4,
        )
        assert not check.confirmed

    def test_earnings_warning(self):
        check = check_income_entry(
            iv_rank=45.0, iv_percentile=50.0, dte=35,
            rsi=50.0, atr_pct=1.2, regime_id=1,
            has_earnings_within_dte=True,
        )
        failed = [c for c in check.conditions if not c["passed"]]
        assert any("earnings" in c["name"] for c in failed)

    def test_no_iv_data_doesnt_block(self):
        check = check_income_entry(
            iv_rank=None, iv_percentile=None, dte=35,
            rsi=50.0, atr_pct=1.2, regime_id=1,
        )
        assert check.confirmed  # Should still pass without IV data


# ── F12: Exit Monitoring ──


class TestExitMonitor:
    def test_profit_target_triggered(self):
        result = monitor_exit_conditions(
            trade_id="GLD-IC-001", ticker="GLD",
            structure_type="iron_condor", order_side="credit",
            entry_price=0.72, current_mid_price=0.30,  # 58% profit
            contracts=2, dte_remaining=25, regime_id=1,
            profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
        )
        assert result.should_close
        assert any(s.rule == "profit_target" and s.triggered for s in result.signals)

    def test_stop_loss_triggered(self):
        result = monitor_exit_conditions(
            trade_id="GLD-IC-001", ticker="GLD",
            structure_type="iron_condor", order_side="credit",
            entry_price=0.72, current_mid_price=2.20,  # 2.06× credit loss
            contracts=1, dte_remaining=30, regime_id=1,
            profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
        )
        assert result.should_close
        assert any(s.rule == "stop_loss" and s.triggered for s in result.signals)

    def test_dte_exit_triggered(self):
        result = monitor_exit_conditions(
            trade_id="GLD-IC-001", ticker="GLD",
            structure_type="iron_condor", order_side="credit",
            entry_price=0.72, current_mid_price=0.50,
            contracts=1, dte_remaining=18, regime_id=1,
            profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
        )
        assert result.should_close
        assert any(s.rule == "dte_exit" and s.triggered for s in result.signals)

    def test_regime_change_severe(self):
        result = monitor_exit_conditions(
            trade_id="GLD-IC-001", ticker="GLD",
            structure_type="iron_condor", order_side="credit",
            entry_price=0.72, current_mid_price=0.60,
            contracts=1, dte_remaining=30, regime_id=4,
            entry_regime_id=1,
            profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
        )
        assert result.should_close
        assert any(s.rule == "regime_change" and s.triggered for s in result.signals)

    def test_hold_when_healthy(self):
        result = monitor_exit_conditions(
            trade_id="GLD-IC-001", ticker="GLD",
            structure_type="iron_condor", order_side="credit",
            entry_price=0.72, current_mid_price=0.55,  # 24% profit (below 50%)
            contracts=1, dte_remaining=30, regime_id=1,
            profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
        )
        assert not result.should_close
        assert "HOLD" in result.summary

    def test_debit_trade_monitoring(self):
        result = monitor_exit_conditions(
            trade_id="AAPL-DS-001", ticker="AAPL",
            structure_type="debit_spread", order_side="debit",
            entry_price=1.80, current_mid_price=2.70,  # 50% profit
            contracts=1, dte_remaining=20, regime_id=3,
            profit_target_pct=0.50, stop_loss_pct=0.50, exit_dte=14,
        )
        assert result.should_close
        assert any(s.rule == "profit_target" and s.triggered for s in result.signals)


# ── Trade Health Check (combined monitoring + adjustment) ──


class TestTradeHealthCheck:
    def test_healthy_trade(self):
        from market_analyzer.models.regime import RegimeID, RegimeResult
        from market_analyzer.models.technicals import (
            BollingerBands, MACDData, MovingAverages, PhaseIndicator,
            RSIData, StochasticData, SupportResistance, TechnicalSnapshot,
        )

        spec = _ic_spec()
        regime = RegimeResult(
            ticker="GLD", regime=RegimeID.R1_LOW_VOL_MR,
            confidence=0.85, regime_probabilities={},
            as_of_date=date.today(), model_version="test",
        )
        price = 221.0
        technicals = TechnicalSnapshot(
            ticker="GLD", as_of_date=date.today(),
            current_price=price, atr=2.5, atr_pct=1.13, vwma_20=price,
            moving_averages=MovingAverages(
                sma_20=price, sma_50=price, sma_200=price,
                ema_9=price, ema_21=price,
                price_vs_sma_20_pct=0.0, price_vs_sma_50_pct=0.0, price_vs_sma_200_pct=0.0,
            ),
            rsi=RSIData(value=50.0, is_overbought=False, is_oversold=False),
            bollinger=BollingerBands(
                upper=price + 5, middle=price, lower=price - 5,
                bandwidth=4.5, percent_b=0.5,
            ),
            macd=MACDData(
                macd_line=0.0, signal_line=0.0, histogram=0.0,
                is_bullish_crossover=False, is_bearish_crossover=False,
            ),
            stochastic=StochasticData(k=50.0, d=50.0, is_overbought=False, is_oversold=False),
            support_resistance=SupportResistance(
                support=price - 10, resistance=price + 10,
                price_vs_support_pct=4.5, price_vs_resistance_pct=4.5,
            ),
            phase=PhaseIndicator(
                phase="accumulation", confidence=0.6, description="",
                higher_highs=True, higher_lows=True, lower_highs=False, lower_lows=False,
                range_compression=0.0, volume_trend="stable", price_vs_sma_50_pct=0.0,
            ),
            signals=[],
        )

        health = check_trade_health(
            trade_id="GLD-IC-001",
            trade_spec=spec,
            entry_price=0.72,
            contracts=1,
            current_mid_price=0.55,
            dte_remaining=30,
            regime=regime,
            technicals=technicals,
        )
        assert health.status == "healthy"
        assert health.overall_action == "hold"
        assert not health.exit_result.should_close
