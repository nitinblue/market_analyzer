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


from datetime import date, timedelta

from market_analyzer.models.levels import (
    LevelRole, LevelSource, LevelsAnalysis, PriceLevel, TradeDirection,
)
from market_analyzer.models.opportunity import LegAction, LegSpec, TradeSpec
from market_analyzer.features.entry_levels import compute_strike_support_proximity


def _make_leg(role: str, action: LegAction, opt_type: str, strike: float) -> LegSpec:
    return LegSpec(
        role=role, action=action, option_type=opt_type, strike=strike,
        strike_label="test", expiration=date(2026, 4, 17),
        days_to_expiry=30, atm_iv_at_expiry=0.22,
    )


def _make_trade_spec(legs: list[LegSpec]) -> TradeSpec:
    return TradeSpec(
        ticker="SPY", legs=legs, underlying_price=580.0,
        target_dte=30, target_expiration=date(2026, 4, 17),
        spec_rationale="test",
    )


def _make_levels(
    supports: list[tuple[float, float, list[str]]],
    resistances: list[tuple[float, float, list[str]]],
) -> LevelsAnalysis:
    """Build LevelsAnalysis from (price, strength, [sources]) tuples."""
    sup = [
        PriceLevel(
            price=p, role=LevelRole.SUPPORT, sources=[LevelSource(s) for s in srcs],
            confluence_score=len(srcs), strength=st, distance_pct=abs(580 - p) / 580 * 100,
            description=f"test support at {p}",
        )
        for p, st, srcs in supports
    ]
    res = [
        PriceLevel(
            price=p, role=LevelRole.RESISTANCE, sources=[LevelSource(s) for s in srcs],
            confluence_score=len(srcs), strength=st, distance_pct=abs(p - 580) / 580 * 100,
            description=f"test resistance at {p}",
        )
        for p, st, srcs in resistances
    ]
    return LevelsAnalysis(
        ticker="SPY", as_of_date=date(2026, 3, 19), entry_price=580.0,
        direction=TradeDirection.LONG, direction_auto_detected=True,
        current_price=580.0, atr=5.0, atr_pct=0.86,
        support_levels=sup, resistance_levels=res,
        stop_loss=None, targets=[], best_target=None, summary="test",
    )


class TestStrikeProximity:
    def test_short_put_backed_by_strong_support(self) -> None:
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
            _make_leg("short_call", LegAction.SELL_TO_OPEN, "call", 590.0),
            _make_leg("long_call", LegAction.BUY_TO_OPEN, "call", 595.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(
            supports=[(572.0, 0.85, ["sma_200", "swing_support"])],
            resistances=[(588.0, 0.75, ["swing_resistance"])],
        )
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        put_leg = [l for l in result.legs if l.role == "short_put"][0]
        assert put_leg.backed_by_level is True
        assert put_leg.distance_atr < 1.0

    def test_short_put_no_nearby_support(self) -> None:
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(supports=[(550.0, 0.90, ["sma_200"])], resistances=[])
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        put_leg = [l for l in result.legs if l.role == "short_put"][0]
        assert put_leg.backed_by_level is False
        assert put_leg.distance_atr > 1.0

    def test_weak_support_not_counted(self) -> None:
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(supports=[(571.0, 0.30, ["ema_9"])], resistances=[])
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        put_leg = [l for l in result.legs if l.role == "short_put"][0]
        assert put_leg.backed_by_level is False

    def test_call_side_uses_resistance(self) -> None:
        legs = [
            _make_leg("short_call", LegAction.SELL_TO_OPEN, "call", 590.0),
            _make_leg("long_call", LegAction.BUY_TO_OPEN, "call", 595.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(supports=[], resistances=[(592.0, 0.80, ["swing_resistance", "sma_50"])])
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        call_leg = [l for l in result.legs if l.role == "short_call"][0]
        assert call_leg.backed_by_level is True

    def test_both_sides_backed(self) -> None:
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
            _make_leg("short_call", LegAction.SELL_TO_OPEN, "call", 590.0),
            _make_leg("long_call", LegAction.BUY_TO_OPEN, "call", 595.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(
            supports=[(571.0, 0.85, ["sma_200", "swing_support"])],
            resistances=[(592.0, 0.80, ["swing_resistance", "pivot_r1"])],
        )
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        assert result.all_backed is True
        assert result.overall_score >= 0.70

    def test_only_short_legs_analyzed(self) -> None:
        legs = [_make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0)]
        ts = _make_trade_spec(legs)
        levels = _make_levels(supports=[], resistances=[])
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        assert len(result.legs) == 0
        assert result.all_backed is True

    def test_no_levels_at_all(self) -> None:
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(supports=[], resistances=[])
        result = compute_strike_support_proximity(ts, levels, atr=5.0)
        assert result.all_backed is False
        assert result.overall_score == 0.0
