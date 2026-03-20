"""Tests for entry-level intelligence models and functions."""

import pytest
from market_analyzer.models.entry import (
    StrikeProximityLeg,
    StrikeProximityResult,
    SkewOptimalStrike,
    EntryLevelScore,
    ConditionalEntry,
    PullbackAlert,
)


class TestEntryModels:
    def test_strike_proximity_result_fields(self) -> None:
        leg = StrikeProximityLeg(
            role="short_put",
            strike=570.0,
            nearest_level_price=572.0,
            nearest_level_strength=0.85,
            nearest_level_sources=["sma_200", "swing_support"],
            distance_points=2.0,
            distance_atr=0.25,
            backed_by_level=True,
        )
        result = StrikeProximityResult(
            legs=[leg],
            overall_score=0.85,
            all_backed=True,
            summary="Short put at 570 backed by SMA-200 + swing support at 572 (0.25 ATR)",
        )
        assert result.overall_score == 0.85
        assert result.all_backed is True
        assert len(result.legs) == 1
        assert result.legs[0].backed_by_level is True

    def test_skew_optimal_strike_fields(self) -> None:
        result = SkewOptimalStrike(
            option_type="put",
            baseline_strike=570.0,
            optimal_strike=565.0,
            baseline_iv=0.22,
            optimal_iv=0.27,
            iv_advantage_pct=22.7,
            distance_atr=1.2,
            rationale="565 put IV 27% vs ATM 22% — 22.7% richer premium at 1.2 ATR OTM",
        )
        assert result.optimal_strike == 565.0
        assert result.iv_advantage_pct > 20

    def test_entry_level_score_fields(self) -> None:
        score = EntryLevelScore(
            overall_score=0.75,
            action="enter_now",
            components={
                "rsi_extremity": 0.80,
                "bollinger_extremity": 0.70,
                "vwap_deviation": 0.65,
                "atr_extension": 0.80,
                "level_proximity": 0.85,
            },
            rationale="RSI 28 oversold + price at lower Bollinger + near SMA-200 support",
        )
        assert score.action == "enter_now"
        assert score.overall_score >= 0.70

    def test_entry_level_score_wait(self) -> None:
        score = EntryLevelScore(
            overall_score=0.55,
            action="wait",
            components={"rsi_extremity": 0.40, "bollinger_extremity": 0.50,
                         "vwap_deviation": 0.30, "atr_extension": 0.45,
                         "level_proximity": 0.60},
            rationale="RSI 55 neutral — no extremity. Wait for pullback.",
        )
        assert score.action == "wait"

    def test_conditional_entry_fields(self) -> None:
        entry = ConditionalEntry(
            entry_mode="limit",
            limit_price=1.75,
            current_mid=1.85,
            improvement_pct=5.4,
            urgency="patient",
            rationale="R1 patient entry: limit at $1.75 (mid $1.85 - 30% of $0.33 spread)",
        )
        assert entry.entry_mode == "limit"
        assert entry.limit_price < entry.current_mid

    def test_pullback_alert_fields(self) -> None:
        alert = PullbackAlert(
            alert_price=576.0,
            current_price=580.0,
            level_source="sma_20",
            level_strength=0.65,
            improvement_description="Short put moves from 570 to 566 (further OTM by 0.5 ATR)",
            roc_improvement_pct=2.3,
        )
        assert alert.alert_price < alert.current_price
        assert alert.roc_improvement_pct > 0

    def test_serialization(self) -> None:
        """All models must serialize for MCP."""
        score = EntryLevelScore(
            overall_score=0.72, action="enter_now",
            components={"rsi_extremity": 0.8}, rationale="test",
        )
        d = score.model_dump()
        assert "overall_score" in d
        assert "components" in d
