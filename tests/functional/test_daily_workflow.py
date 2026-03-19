"""Functional tests: full daily trading pipeline.

Tests the scan → assess → gate workflow end-to-end.
All checks use synthetic data (no broker required).
"""
import pytest
from datetime import date

from market_analyzer.models.opportunity import Verdict
from market_analyzer.opportunity.option_plays.iron_condor import assess_iron_condor
from market_analyzer.validation import run_daily_checks
from market_analyzer.validation.models import Severity


def _technicals_for_workflow(rsi: float = 50.0, atr_pct: float = 1.0, price: float = 580.0):
    """Build a TechnicalSnapshot inline — avoids cross-test-module imports."""
    from market_analyzer.models.technicals import (
        BollingerBands, MACDData, MovingAverages, RSIData,
        StochasticData, SupportResistance, TechnicalSnapshot,
        MarketPhase, PhaseIndicator,
    )
    return TechnicalSnapshot(
        ticker="SPY", as_of_date=date(2026, 3, 18), current_price=price,
        atr=price * atr_pct / 100, atr_pct=atr_pct, vwma_20=price,
        moving_averages=MovingAverages(
            sma_20=price, sma_50=price * 0.98, sma_200=price * 0.95,
            ema_9=price, ema_21=price,
            price_vs_sma_20_pct=0.0, price_vs_sma_50_pct=2.0, price_vs_sma_200_pct=5.0,
        ),
        rsi=RSIData(value=rsi, is_overbought=rsi > 70, is_oversold=rsi < 30),
        bollinger=BollingerBands(upper=price + 10, middle=price, lower=price - 10, bandwidth=0.04, percent_b=0.5),
        macd=MACDData(macd_line=0.5, signal_line=0.3, histogram=0.2, is_bullish_crossover=False, is_bearish_crossover=False),
        stochastic=StochasticData(k=50.0, d=50.0, is_overbought=False, is_oversold=False),
        support_resistance=SupportResistance(support=570.0, resistance=590.0, price_vs_support_pct=1.7, price_vs_resistance_pct=-1.7),
        phase=PhaseIndicator(phase=MarketPhase.ACCUMULATION, confidence=0.5, description="Test",
                             higher_highs=False, higher_lows=True, lower_highs=False, lower_lows=False,
                             range_compression=0.3, volume_trend="declining", price_vs_sma_50_pct=2.0),
        signals=[],
    )


class TestAssessorVerdicts:
    @pytest.mark.daily
    def test_r1_ic_ideal_conditions_is_go(self, r1_regime, normal_vol_surface) -> None:
        """R1 + IV 22% + good spread → GO verdict from assessor."""
        result = assess_iron_condor("SPY", r1_regime, _technicals_for_workflow(rsi=50), normal_vol_surface)
        assert result.verdict == Verdict.GO

    @pytest.mark.daily
    def test_r4_ic_always_no_go(self, r4_regime, normal_vol_surface) -> None:
        """R4 is always a hard stop for iron condors."""
        result = assess_iron_condor("SPY", r4_regime, _technicals_for_workflow(rsi=50), normal_vol_surface)
        assert result.verdict == Verdict.NO_GO
        assert any("R4" in s.name for s in result.hard_stops)

    @pytest.mark.daily
    def test_go_assessor_produces_trade_spec(self, r1_regime, normal_vol_surface) -> None:
        """GO verdict must include a TradeSpec — needed for full pipeline."""
        result = assess_iron_condor("SPY", r1_regime, _technicals_for_workflow(rsi=50), normal_vol_surface)
        if result.verdict == Verdict.GO:
            assert result.trade_spec is not None
            assert len(result.trade_spec.legs) == 4

    @pytest.mark.daily
    def test_go_trade_spec_has_exit_rules(self, r1_regime, normal_vol_surface) -> None:
        """GO trade spec must include profit target, stop loss, and exit DTE."""
        result = assess_iron_condor("SPY", r1_regime, _technicals_for_workflow(), normal_vol_surface)
        if result.verdict == Verdict.GO and result.trade_spec:
            spec = result.trade_spec
            assert spec.profit_target_pct is not None, "Missing profit_target_pct"
            assert spec.stop_loss_pct is not None, "Missing stop_loss_pct"
            assert spec.exit_dte is not None, "Missing exit_dte"

    @pytest.mark.daily
    def test_validation_of_go_trade_is_ready(self, r1_regime, normal_vol_surface, standard_ic_spec) -> None:
        """A GO trade under ideal conditions should pass daily validation."""
        report = run_daily_checks(
            ticker="SPY",
            trade_spec=standard_ic_spec,
            entry_credit=3.00,
            regime_id=1,
            atr_pct=1.0,
            current_price=580.0,
            avg_bid_ask_spread_pct=0.8,
            dte=30,
            rsi=50.0,
            iv_rank=45.0,
        )
        assert report.is_ready is True, f"Expected READY. Failures: {[c for c in report.checks if c.severity == Severity.FAIL]}"

    def test_no_go_trade_should_not_reach_validation(self, r4_regime, normal_vol_surface) -> None:
        """R4 hard stops in the assessor — validation should never be called."""
        result = assess_iron_condor("SPY", r4_regime, _technicals_for_workflow(), normal_vol_surface)
        assert result.verdict == Verdict.NO_GO
        assert len(result.hard_stops) > 0
