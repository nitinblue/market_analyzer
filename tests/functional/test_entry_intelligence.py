"""Functional tests for entry-level intelligence pipeline."""

from datetime import date

import pytest

from market_analyzer.features.entry_levels import (
    compute_limit_entry_price,
    compute_pullback_levels,
    compute_strike_support_proximity,
    score_entry_level,
    select_skew_optimal_strike,
)
from market_analyzer.models.entry import (
    ConditionalEntry,
    EntryLevelScore,
    PullbackAlert,
    SkewOptimalStrike,
    StrikeProximityResult,
)
from market_analyzer.models.levels import (
    LevelRole,
    LevelSource,
    LevelsAnalysis,
    PriceLevel,
    TradeDirection,
)
from market_analyzer.models.opportunity import Verdict
from market_analyzer.opportunity.option_plays.iron_condor import assess_iron_condor
from market_analyzer.validation.daily_readiness import run_daily_checks
from market_analyzer.validation.models import Severity


class TestFullEntryPipeline:
    def test_r1_ic_with_strong_levels_passes_all(self, r1_regime, normal_vol_surface) -> None:
        from market_analyzer.models.technicals import (
            BollingerBands, MACDData, MovingAverages, RSIData,
            StochasticData, SupportResistance, TechnicalSnapshot,
            MarketPhase, PhaseIndicator,
        )

        tech = TechnicalSnapshot(
            ticker="SPY", as_of_date=date(2026, 3, 19), current_price=580.0,
            atr=5.0, atr_pct=0.86, vwma_20=580.0,
            moving_averages=MovingAverages(
                sma_20=580.0, sma_50=568.0, sma_200=551.0,
                ema_9=580.0, ema_21=579.0,
                price_vs_sma_20_pct=0.0, price_vs_sma_50_pct=2.1, price_vs_sma_200_pct=5.3,
            ),
            rsi=RSIData(value=52.0, is_overbought=False, is_oversold=False),
            bollinger=BollingerBands(upper=590.0, middle=580.0, lower=570.0,
                                     bandwidth=0.035, percent_b=0.50),
            macd=MACDData(macd_line=0.5, signal_line=0.3, histogram=0.2,
                          is_bullish_crossover=False, is_bearish_crossover=False),
            stochastic=StochasticData(k=50.0, d=50.0, is_overbought=False, is_oversold=False),
            support_resistance=SupportResistance(support=570.0, resistance=590.0,
                                                  price_vs_support_pct=1.7, price_vs_resistance_pct=-1.7),
            phase=PhaseIndicator(phase=MarketPhase.ACCUMULATION, confidence=0.5, description="Test",
                                 higher_highs=False, higher_lows=True, lower_highs=False, lower_lows=False,
                                 range_compression=0.3, volume_trend="declining", price_vs_sma_50_pct=2.0),
            signals=[],
        )

        ic = assess_iron_condor("SPY", r1_regime, tech, normal_vol_surface)
        if ic.trade_spec is None:
            pytest.skip("IC assessment returned no trade spec")

        short_put = [l for l in ic.trade_spec.legs if l.role == "short_put"][0]
        short_call = [l for l in ic.trade_spec.legs if l.role == "short_call"][0]

        levels = LevelsAnalysis(
            ticker="SPY", as_of_date=date(2026, 3, 19), entry_price=580.0,
            direction=TradeDirection.LONG, direction_auto_detected=True,
            current_price=580.0, atr=5.0, atr_pct=0.86,
            support_levels=[
                PriceLevel(price=short_put.strike + 1.0, role=LevelRole.SUPPORT,
                           sources=[LevelSource.SMA_200, LevelSource.SWING_SUPPORT],
                           confluence_score=2, strength=0.90,
                           distance_pct=abs(580 - short_put.strike - 1) / 580 * 100,
                           description="SMA-200 + swing support"),
            ],
            resistance_levels=[
                PriceLevel(price=short_call.strike + 1.0, role=LevelRole.RESISTANCE,
                           sources=[LevelSource.SWING_RESISTANCE],
                           confluence_score=1, strength=0.75,
                           distance_pct=abs(short_call.strike + 1 - 580) / 580 * 100,
                           description="Swing resistance"),
            ],
            stop_loss=None, targets=[], best_target=None, summary="test",
        )

        prox = compute_strike_support_proximity(ic.trade_spec, levels, atr=5.0)
        assert isinstance(prox, StrikeProximityResult)

        entry_score = score_entry_level(tech, levels, direction="neutral")
        assert isinstance(entry_score, EntryLevelScore)

        limit = compute_limit_entry_price(1.80, 0.30, urgency="patient")
        assert isinstance(limit, ConditionalEntry)

        pullbacks = compute_pullback_levels(580.0, levels, atr=5.0)
        assert isinstance(pullbacks, list)


class TestSkewOptimalWithRealVolSurface:
    def test_normal_vol_surface_has_skew(self, normal_vol_surface) -> None:
        assert len(normal_vol_surface.skew_by_expiry) >= 1
        skew = normal_vol_surface.skew_by_expiry[0]
        result = select_skew_optimal_strike(580.0, 5.0, 1, skew, "put")
        assert isinstance(result, SkewOptimalStrike)

    def test_high_vol_surface_steeper_skew(self, normal_vol_surface, high_vol_surface) -> None:
        normal_skew = normal_vol_surface.skew_by_expiry[0]
        high_skew = high_vol_surface.skew_by_expiry[0]
        r_normal = select_skew_optimal_strike(580.0, 5.0, 1, normal_skew, "put")
        r_high = select_skew_optimal_strike(580.0, 8.0, 2, high_skew, "put")
        assert r_high.iv_advantage_pct >= r_normal.iv_advantage_pct


class TestEntryScoreWithExtremes:
    def test_oversold_bounce_entry(self) -> None:
        from market_analyzer.models.technicals import (
            BollingerBands, MACDData, MovingAverages, RSIData,
            StochasticData, SupportResistance, TechnicalSnapshot,
            MarketPhase, PhaseIndicator,
        )

        tech = TechnicalSnapshot(
            ticker="SPY", as_of_date=date(2026, 3, 19), current_price=565.0,
            atr=6.0, atr_pct=1.06, vwma_20=575.0,
            moving_averages=MovingAverages(
                sma_20=575.0, sma_50=578.0, sma_200=560.0,
                ema_9=568.0, ema_21=572.0,
                price_vs_sma_20_pct=-1.7, price_vs_sma_50_pct=-2.2, price_vs_sma_200_pct=0.9,
            ),
            rsi=RSIData(value=22.0, is_overbought=False, is_oversold=True),
            bollinger=BollingerBands(upper=590.0, middle=575.0, lower=560.0,
                                     bandwidth=0.05, percent_b=-0.10),
            macd=MACDData(macd_line=-1.5, signal_line=-0.8, histogram=-0.7,
                          is_bullish_crossover=False, is_bearish_crossover=True),
            stochastic=StochasticData(k=15.0, d=18.0, is_overbought=False, is_oversold=True),
            support_resistance=SupportResistance(support=560.0, resistance=575.0,
                                                  price_vs_support_pct=0.9, price_vs_resistance_pct=-1.7),
            phase=PhaseIndicator(phase=MarketPhase.ACCUMULATION, confidence=0.7, description="Test",
                                 higher_highs=False, higher_lows=False, lower_highs=True, lower_lows=True,
                                 range_compression=0.1, volume_trend="rising", price_vs_sma_50_pct=-2.2),
            signals=[],
        )

        levels = LevelsAnalysis(
            ticker="SPY", as_of_date=date(2026, 3, 19), entry_price=565.0,
            direction=TradeDirection.LONG, direction_auto_detected=True,
            current_price=565.0, atr=6.0, atr_pct=1.06,
            support_levels=[
                PriceLevel(price=560.0, role=LevelRole.SUPPORT,
                           sources=[LevelSource.SMA_200, LevelSource.SWING_SUPPORT],
                           confluence_score=2, strength=0.90, distance_pct=0.88,
                           description="SMA-200 + swing"),
            ],
            resistance_levels=[], stop_loss=None, targets=[], best_target=None, summary="test",
        )

        result = score_entry_level(tech, levels, direction="bullish")
        assert result.action == "enter_now"
        assert result.overall_score >= 0.70
        assert result.components["rsi_extremity"] > 0.80


class TestPullbackWithRealisticLevels:
    def test_multiple_support_levels_multiple_alerts(self) -> None:
        levels = LevelsAnalysis(
            ticker="SPY", as_of_date=date(2026, 3, 19), entry_price=580.0,
            direction=TradeDirection.LONG, direction_auto_detected=True,
            current_price=580.0, atr=5.0, atr_pct=0.86,
            support_levels=[
                PriceLevel(price=577.0, role=LevelRole.SUPPORT,
                           sources=[LevelSource.SMA_20], confluence_score=1, strength=0.55,
                           distance_pct=0.52, description="SMA-20"),
                PriceLevel(price=574.0, role=LevelRole.SUPPORT,
                           sources=[LevelSource.SMA_50, LevelSource.EMA_21], confluence_score=2, strength=0.75,
                           distance_pct=1.03, description="SMA-50 + EMA-21"),
                PriceLevel(price=570.0, role=LevelRole.SUPPORT,
                           sources=[LevelSource.SMA_200, LevelSource.SWING_SUPPORT, LevelSource.ORDER_BLOCK_LOW],
                           confluence_score=3, strength=0.92, distance_pct=1.72, description="SMA-200 + swing + OB"),
            ],
            resistance_levels=[], stop_loss=None, targets=[], best_target=None, summary="test",
        )

        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        assert len(alerts) >= 2
        assert alerts[0].alert_price > alerts[-1].alert_price
        for alert in alerts:
            assert alert.roc_improvement_pct > 0
