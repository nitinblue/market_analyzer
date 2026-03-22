"""Tests for entry-level intelligence models and functions."""

import pytest
from income_desk.models.entry import (
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

from income_desk.models.levels import (
    LevelRole, LevelSource, LevelsAnalysis, PriceLevel, TradeDirection,
)
from income_desk.models.opportunity import LegAction, LegSpec, TradeSpec
from income_desk.features.entry_levels import compute_strike_support_proximity


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


from income_desk.models.vol_surface import SkewSlice
from income_desk.features.entry_levels import select_skew_optimal_strike


def _make_skew(
    atm_iv: float = 0.22, put_skew: float = 0.05,
    call_skew: float = 0.02, skew_ratio: float = 2.5,
) -> SkewSlice:
    return SkewSlice(
        expiration=date(2026, 4, 17), days_to_expiry=30,
        atm_iv=atm_iv, otm_put_iv=atm_iv + put_skew,
        otm_call_iv=atm_iv + call_skew,
        put_skew=put_skew, call_skew=call_skew, skew_ratio=skew_ratio,
    )


class TestSkewOptimalStrike:
    def test_put_side_shifts_toward_skew(self) -> None:
        skew = _make_skew(atm_iv=0.22, put_skew=0.08)
        result = select_skew_optimal_strike(580.0, 5.0, 1, skew, "put")
        assert result.optimal_strike <= result.baseline_strike
        assert result.iv_advantage_pct > 0
        assert result.optimal_iv > result.baseline_iv

    def test_flat_skew_no_shift(self) -> None:
        skew = _make_skew(atm_iv=0.22, put_skew=0.005, call_skew=0.003)
        result = select_skew_optimal_strike(580.0, 5.0, 1, skew, "put")
        assert result.optimal_strike == result.baseline_strike
        assert result.iv_advantage_pct < 5.0

    def test_call_side_shifts_toward_call_skew(self) -> None:
        skew = _make_skew(atm_iv=0.22, call_skew=0.06)
        result = select_skew_optimal_strike(580.0, 5.0, 1, skew, "call")
        assert result.optimal_strike >= result.baseline_strike
        assert result.iv_advantage_pct > 0

    def test_r2_wider_baseline(self) -> None:
        skew = _make_skew(atm_iv=0.30, put_skew=0.06)
        r1 = select_skew_optimal_strike(580.0, 5.0, 1, skew, "put")
        r2 = select_skew_optimal_strike(580.0, 5.0, 2, skew, "put")
        assert r2.baseline_strike < r1.baseline_strike

    def test_stays_within_atr_bounds(self) -> None:
        skew = _make_skew(atm_iv=0.22, put_skew=0.15)
        result = select_skew_optimal_strike(580.0, 5.0, 1, skew, "put")
        distance = abs(580.0 - result.optimal_strike)
        assert distance >= 0.8 * 5.0 - 0.01
        assert distance <= 2.0 * 5.0 + 0.01


# ---------------------------------------------------------------------------
# Task 4: score_entry_level
# ---------------------------------------------------------------------------

from income_desk.models.technicals import (
    BollingerBands, MACDData, MovingAverages, RSIData,
    StochasticData, SupportResistance, TechnicalSnapshot,
    MarketPhase, PhaseIndicator,
)
from income_desk.features.entry_levels import score_entry_level


def _make_technicals(
    price: float = 580.0, rsi: float = 50.0, percent_b: float = 0.5,
    atr_pct: float = 0.86, sma_20: float | None = None, vwap: float | None = None,
) -> TechnicalSnapshot:
    atr = price * atr_pct / 100
    _sma_20 = sma_20 if sma_20 is not None else price
    _vwap = vwap if vwap is not None else price
    pct_sma_20 = (price - _sma_20) / _sma_20 * 100 if _sma_20 else 0.0
    return TechnicalSnapshot(
        ticker="SPY", as_of_date=date(2026, 3, 19), current_price=price,
        atr=atr, atr_pct=atr_pct, vwma_20=_vwap,
        moving_averages=MovingAverages(
            sma_20=_sma_20, sma_50=price * 0.98, sma_200=price * 0.95,
            ema_9=price, ema_21=price,
            price_vs_sma_20_pct=pct_sma_20, price_vs_sma_50_pct=2.0, price_vs_sma_200_pct=5.0,
        ),
        rsi=RSIData(value=rsi, is_overbought=rsi > 70, is_oversold=rsi < 30),
        bollinger=BollingerBands(upper=price + 10, middle=price, lower=price - 10,
                                 bandwidth=0.04, percent_b=percent_b),
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


class TestEntryLevelScore:
    def test_extreme_oversold_at_support_enter_now(self) -> None:
        """RSI 25 + %B 0.05 + extended from mean + near support → enter_now."""
        tech = _make_technicals(price=572.0, rsi=25.0, percent_b=0.05,
                                sma_20=580.0, vwap=580.0)
        levels = _make_levels(
            supports=[(570.0, 0.90, ["sma_200", "swing_support"])],
            resistances=[],
        )
        result = score_entry_level(tech, levels, direction="bullish")
        assert result.action == "enter_now"
        assert result.overall_score >= 0.70
        assert result.components["rsi_extremity"] > 0.7

    def test_neutral_rsi_mid_bollinger_wait(self) -> None:
        tech = _make_technicals(price=580.0, rsi=50.0, percent_b=0.5)
        levels = _make_levels(supports=[], resistances=[])
        result = score_entry_level(tech, levels, direction="bullish")
        assert result.action in ("wait", "not_yet")
        assert result.overall_score < 0.70

    def test_overbought_at_resistance_bearish_enter(self) -> None:
        tech = _make_technicals(price=589.0, rsi=78.0, percent_b=0.95,
                                sma_20=580.0, vwap=580.0)
        levels = _make_levels(supports=[], resistances=[(590.0, 0.85, ["swing_resistance", "pivot_r1"])])
        result = score_entry_level(tech, levels, direction="bearish")
        assert result.action == "enter_now"
        assert result.overall_score >= 0.70

    def test_moderate_signal_caution(self) -> None:
        tech = _make_technicals(price=582.0, rsi=62.0, percent_b=0.70)
        levels = _make_levels(supports=[(578.0, 0.60, ["sma_20"])], resistances=[])
        result = score_entry_level(tech, levels, direction="bearish")
        assert result.action == "wait"
        assert 0.40 <= result.overall_score <= 0.75

    def test_components_all_present(self) -> None:
        tech = _make_technicals()
        levels = _make_levels(supports=[], resistances=[])
        result = score_entry_level(tech, levels, direction="neutral")
        expected_keys = {"rsi_extremity", "bollinger_extremity", "vwap_deviation",
                         "atr_extension", "level_proximity"}
        assert expected_keys == set(result.components.keys())

    def test_neutral_direction_uses_absolute_extremity(self) -> None:
        tech = _make_technicals(rsi=28.0, percent_b=0.10)
        levels = _make_levels(supports=[(575.0, 0.70, ["sma_50"])], resistances=[])
        result = score_entry_level(tech, levels, direction="neutral")
        assert result.components["rsi_extremity"] > 0.6


# ---------------------------------------------------------------------------
# Task 5: compute_limit_entry_price
# ---------------------------------------------------------------------------

from income_desk.features.entry_levels import compute_limit_entry_price


class TestLimitEntryPrice:
    def test_patient_debit_entry_below_mid(self) -> None:
        result = compute_limit_entry_price(current_mid=3.50, bid_ask_spread=0.40, urgency="patient", is_credit=False)
        assert result.entry_mode == "limit"
        assert result.limit_price < result.current_mid
        assert result.limit_price == pytest.approx(3.50 - 0.40 * 0.30, abs=0.01)
        assert result.improvement_pct > 0

    def test_normal_debit_entry_slight_improvement(self) -> None:
        result = compute_limit_entry_price(current_mid=3.50, bid_ask_spread=0.40, urgency="normal", is_credit=False)
        assert result.limit_price == pytest.approx(3.50 - 0.40 * 0.10, abs=0.01)
        assert result.limit_price < result.current_mid

    def test_aggressive_entry_at_mid(self) -> None:
        result = compute_limit_entry_price(current_mid=1.85, bid_ask_spread=0.30, urgency="aggressive")
        assert result.limit_price == result.current_mid
        assert result.improvement_pct == 0.0

    def test_narrow_spread_minimal_improvement(self) -> None:
        result = compute_limit_entry_price(current_mid=1.85, bid_ask_spread=0.05, urgency="patient")
        improvement = abs(result.current_mid - result.limit_price)
        assert improvement < 0.02

    def test_patient_credit_holds_at_mid(self) -> None:
        result = compute_limit_entry_price(current_mid=1.85, bid_ask_spread=0.30, urgency="patient", is_credit=True)
        assert result.limit_price == result.current_mid
        assert result.entry_mode == "limit"

    def test_normal_credit_small_concession(self) -> None:
        result = compute_limit_entry_price(current_mid=1.85, bid_ask_spread=0.30, urgency="normal", is_credit=True)
        assert result.limit_price == pytest.approx(1.85 - 0.30 * 0.10, abs=0.01)
        assert result.limit_price < result.current_mid

    def test_aggressive_credit_big_concession(self) -> None:
        result = compute_limit_entry_price(current_mid=1.85, bid_ask_spread=0.30, urgency="aggressive", is_credit=True)
        assert result.limit_price == pytest.approx(1.85 - 0.30 * 0.30, abs=0.01)

    def test_rationale_includes_urgency(self) -> None:
        result = compute_limit_entry_price(1.85, 0.30, "patient")
        assert "patient" in result.rationale.lower() or "R1" in result.rationale


# ---------------------------------------------------------------------------
# Task 6: compute_pullback_levels
# ---------------------------------------------------------------------------

from income_desk.features.entry_levels import compute_pullback_levels


class TestPullbackLevels:
    def test_support_pullback_improves_put_side(self) -> None:
        levels = _make_levels(
            supports=[(576.0, 0.70, ["sma_20"]), (570.0, 0.85, ["sma_200"])],
            resistances=[],
        )
        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        assert len(alerts) >= 1
        assert alerts[0].alert_price < 580.0
        assert alerts[0].roc_improvement_pct > 0

    def test_no_nearby_levels_no_alerts(self) -> None:
        levels = _make_levels(supports=[], resistances=[])
        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        assert len(alerts) == 0

    def test_only_levels_below_current_price(self) -> None:
        levels = _make_levels(supports=[(576.0, 0.70, ["sma_20"])], resistances=[(585.0, 0.70, ["sma_50"])])
        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        for alert in alerts:
            assert alert.alert_price < 580.0

    def test_weak_levels_excluded(self) -> None:
        levels = _make_levels(supports=[(577.0, 0.25, ["ema_9"])], resistances=[])
        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        assert len(alerts) == 0

    def test_max_pullback_distance_2atr(self) -> None:
        levels = _make_levels(supports=[(560.0, 0.90, ["sma_200"])], resistances=[])
        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        assert len(alerts) == 0

    def test_alerts_sorted_nearest_first(self) -> None:
        levels = _make_levels(supports=[(576.0, 0.70, ["sma_20"]), (573.0, 0.80, ["sma_50"])], resistances=[])
        alerts = compute_pullback_levels(580.0, levels, atr=5.0)
        assert len(alerts) == 2
        assert alerts[0].alert_price > alerts[1].alert_price


# ---------------------------------------------------------------------------
# Task 7: Wire Skew into build_iron_condor_legs + TradeSpec entry fields
# ---------------------------------------------------------------------------

from income_desk.opportunity.option_plays._trade_spec_helpers import build_iron_condor_legs


class TestSkewWiredIntoIC:
    def test_no_skew_preserves_original_behavior(self) -> None:
        legs_no_skew, wing = build_iron_condor_legs(
            price=580.0, atr=5.0, regime_id=1,
            expiration=date(2026, 4, 17), dte=30, atm_iv=0.22,
        )
        assert len(legs_no_skew) == 4
        short_put = [l for l in legs_no_skew if l.role == "short_put"][0]
        assert short_put.strike == 575.0

    def test_with_steep_skew_shifts_strikes(self) -> None:
        skew = _make_skew(atm_iv=0.22, put_skew=0.08, call_skew=0.03)
        legs_with_skew, wing = build_iron_condor_legs(
            price=580.0, atr=5.0, regime_id=1,
            expiration=date(2026, 4, 17), dte=30, atm_iv=0.22,
            skew=skew,
        )
        legs_no_skew, _ = build_iron_condor_legs(
            price=580.0, atr=5.0, regime_id=1,
            expiration=date(2026, 4, 17), dte=30, atm_iv=0.22,
        )
        short_put_skewed = [l for l in legs_with_skew if l.role == "short_put"][0]
        short_put_no_skew = [l for l in legs_no_skew if l.role == "short_put"][0]
        assert short_put_skewed.strike <= short_put_no_skew.strike

    def test_flat_skew_no_change(self) -> None:
        skew = _make_skew(atm_iv=0.22, put_skew=0.005, call_skew=0.003)
        legs_flat, _ = build_iron_condor_legs(
            price=580.0, atr=5.0, regime_id=1,
            expiration=date(2026, 4, 17), dte=30, atm_iv=0.22, skew=skew,
        )
        legs_none, _ = build_iron_condor_legs(
            price=580.0, atr=5.0, regime_id=1,
            expiration=date(2026, 4, 17), dte=30, atm_iv=0.22,
        )
        sp_flat = [l for l in legs_flat if l.role == "short_put"][0]
        sp_none = [l for l in legs_none if l.role == "short_put"][0]
        assert sp_flat.strike == sp_none.strike


class TestTradeSpecEntryFields:
    def test_new_fields_default_none(self) -> None:
        ts = TradeSpec(
            ticker="SPY",
            legs=[_make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0)],
            underlying_price=580.0, target_dte=30,
            target_expiration=date(2026, 4, 17), spec_rationale="test",
        )
        assert ts.entry_mode is None
        assert ts.limit_price is None
        assert ts.pullback_levels is None
        assert ts.strike_proximity_score is None


# ---------------------------------------------------------------------------
# Task 8: Wire proximity check into daily validation
# ---------------------------------------------------------------------------

from income_desk.validation.daily_readiness import run_daily_checks
from income_desk.validation.models import Severity


class TestStrikeProximityInDailyChecks:
    def _run_daily_with_levels(self, supports, resistances):
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
            _make_leg("short_call", LegAction.SELL_TO_OPEN, "call", 590.0),
            _make_leg("long_call", LegAction.BUY_TO_OPEN, "call", 595.0),
        ]
        ts = _make_trade_spec(legs)
        levels = _make_levels(supports, resistances)
        return run_daily_checks(
            ticker="SPY", trade_spec=ts, entry_credit=3.00,
            regime_id=1, atr_pct=0.86, current_price=580.0,
            avg_bid_ask_spread_pct=1.0, dte=30, rsi=50.0,
            levels=levels,
        )

    def test_backed_strikes_pass(self) -> None:
        report = self._run_daily_with_levels(
            supports=[(571.0, 0.85, ["sma_200", "swing_support"])],
            resistances=[(592.0, 0.80, ["swing_resistance"])],
        )
        prox = [c for c in report.checks if c.name == "strike_proximity"]
        assert len(prox) == 1
        assert prox[0].severity == Severity.PASS

    def test_unbacked_strikes_warn(self) -> None:
        report = self._run_daily_with_levels(supports=[], resistances=[])
        prox = [c for c in report.checks if c.name == "strike_proximity"]
        assert len(prox) == 1
        assert prox[0].severity == Severity.WARN

    def test_no_levels_data_warn(self) -> None:
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
        ]
        ts = _make_trade_spec(legs)
        report = run_daily_checks(
            ticker="SPY", trade_spec=ts, entry_credit=3.00,
            regime_id=1, atr_pct=0.86, current_price=580.0,
            avg_bid_ask_spread_pct=1.0, dte=30, rsi=50.0,
            levels=None,
        )
        prox = [c for c in report.checks if c.name == "strike_proximity"]
        assert len(prox) == 1
        assert prox[0].severity == Severity.WARN

    def test_total_checks_now_10_with_levels(self) -> None:
        report = self._run_daily_with_levels(
            supports=[(571.0, 0.85, ["sma_200"])],
            resistances=[(592.0, 0.80, ["swing_resistance"])],
        )
        assert len(report.checks) == 10


class TestCLIEntryAnalysis:
    def test_do_entry_analysis_import(self) -> None:
        from income_desk import (
            compute_strike_support_proximity,
            select_skew_optimal_strike,
            score_entry_level,
            compute_limit_entry_price,
            compute_pullback_levels,
            StrikeProximityResult,
            SkewOptimalStrike,
            EntryLevelScore,
            ConditionalEntry,
            PullbackAlert,
        )
        assert callable(compute_strike_support_proximity)
        assert callable(select_skew_optimal_strike)
        assert callable(score_entry_level)
        assert callable(compute_limit_entry_price)
        assert callable(compute_pullback_levels)


# ---------------------------------------------------------------------------
# Check #9: Earnings blackout gate in daily validation
# ---------------------------------------------------------------------------


class TestEarningsBlackoutInDailyChecks:
    def _run_daily_with_earnings(self, days_to_earnings: int | None, dte: int = 30):
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
        ]
        ts = _make_trade_spec(legs)
        return run_daily_checks(
            ticker="SPY", trade_spec=ts, entry_credit=3.00,
            regime_id=1, atr_pct=0.86, current_price=580.0,
            avg_bid_ask_spread_pct=1.0, dte=dte, rsi=50.0,
            days_to_earnings=days_to_earnings,
        )

    def test_earnings_within_dte_fails(self) -> None:
        """Earnings in 15 days with 30 DTE trade -> FAIL."""
        report = self._run_daily_with_earnings(days_to_earnings=15, dte=30)
        eb = [c for c in report.checks if c.name == "earnings_blackout"]
        assert len(eb) == 1
        assert eb[0].severity == Severity.FAIL
        assert not report.is_ready  # FAIL blocks the trade

    def test_earnings_just_outside_dte_warns(self) -> None:
        """Earnings in 33 days with 30 DTE trade -> WARN (close but OK)."""
        report = self._run_daily_with_earnings(days_to_earnings=33, dte=30)
        eb = [c for c in report.checks if c.name == "earnings_blackout"]
        assert len(eb) == 1
        assert eb[0].severity == Severity.WARN

    def test_earnings_far_away_passes(self) -> None:
        """Earnings in 60 days with 30 DTE trade -> PASS."""
        report = self._run_daily_with_earnings(days_to_earnings=60, dte=30)
        eb = [c for c in report.checks if c.name == "earnings_blackout"]
        assert len(eb) == 1
        assert eb[0].severity == Severity.PASS

    def test_no_earnings_data_passes(self) -> None:
        """No earnings data (ETF) -> PASS."""
        report = self._run_daily_with_earnings(days_to_earnings=None)
        eb = [c for c in report.checks if c.name == "earnings_blackout"]
        assert len(eb) == 1
        assert eb[0].severity == Severity.PASS

    def test_earnings_on_expiry_day_fails(self) -> None:
        """Earnings exactly on DTE -> FAIL."""
        report = self._run_daily_with_earnings(days_to_earnings=30, dte=30)
        eb = [c for c in report.checks if c.name == "earnings_blackout"]
        assert eb[0].severity == Severity.FAIL

    def test_total_checks_now_10(self) -> None:
        """Daily suite now has 10 checks."""
        report = self._run_daily_with_earnings(days_to_earnings=60)
        assert len(report.checks) == 10


# ---------------------------------------------------------------------------
# Task 8: IVRankQuality model + compute_iv_rank_quality()
# ---------------------------------------------------------------------------


from income_desk.models.entry import IVRankQuality  # noqa: E402
from income_desk.features.entry_levels import compute_iv_rank_quality  # noqa: E402


class TestIVRankQuality:
    def test_etf_good(self) -> None:
        result = compute_iv_rank_quality(35.0, "etf")
        assert result.quality == "good"
        assert result.threshold_good == 30.0

    def test_etf_wait(self) -> None:
        result = compute_iv_rank_quality(25.0, "etf")
        assert result.quality == "wait"

    def test_etf_avoid(self) -> None:
        result = compute_iv_rank_quality(15.0, "etf")
        assert result.quality == "avoid"

    def test_equity_good(self) -> None:
        result = compute_iv_rank_quality(50.0, "equity")
        assert result.quality == "good"
        assert result.threshold_good == 45.0

    def test_equity_wait(self) -> None:
        result = compute_iv_rank_quality(35.0, "equity")
        assert result.quality == "wait"

    def test_equity_avoid(self) -> None:
        result = compute_iv_rank_quality(25.0, "equity")
        assert result.quality == "avoid"

    def test_index_good(self) -> None:
        result = compute_iv_rank_quality(30.0, "index")
        assert result.quality == "good"
        assert result.threshold_good == 25.0

    def test_index_wait(self) -> None:
        result = compute_iv_rank_quality(20.0, "index")
        assert result.quality == "wait"

    def test_index_avoid(self) -> None:
        result = compute_iv_rank_quality(10.0, "index")
        assert result.quality == "avoid"

    def test_boundary_exactly_at_good(self) -> None:
        result = compute_iv_rank_quality(30.0, "etf")
        assert result.quality == "good"

    def test_boundary_exactly_at_wait(self) -> None:
        result = compute_iv_rank_quality(20.0, "etf")
        assert result.quality == "wait"

    def test_unknown_type_uses_etf_defaults(self) -> None:
        result = compute_iv_rank_quality(35.0, "unknown")
        assert result.quality == "good"  # Uses default (30, 20)

    def test_case_insensitive(self) -> None:
        result = compute_iv_rank_quality(35.0, "ETF")
        assert result.quality == "good"

    def test_serialization(self) -> None:
        result = compute_iv_rank_quality(40.0, "etf")
        d = result.model_dump()
        assert "quality" in d
        assert "ticker_type" in d
        assert "threshold_good" in d

    def test_rationale_contains_rank(self) -> None:
        result = compute_iv_rank_quality(42.0, "etf")
        assert "42" in result.rationale


# ---------------------------------------------------------------------------
# Fix 2: Momentum override (MACD histogram extremity caps entry score)
# ---------------------------------------------------------------------------


def _make_technicals_with_macd(
    price: float = 580.0,
    rsi: float = 25.0,
    percent_b: float = 0.05,
    macd_histogram: float = 0.2,
    atr_pct: float = 0.86,
) -> TechnicalSnapshot:
    """Build a TechnicalSnapshot with a specific MACD histogram value."""
    atr = price * atr_pct / 100
    return TechnicalSnapshot(
        ticker="SPY", as_of_date=date(2026, 3, 19), current_price=price,
        atr=atr, atr_pct=atr_pct, vwma_20=price,
        moving_averages=MovingAverages(
            sma_20=price, sma_50=price * 0.98, sma_200=price * 0.95,
            ema_9=price, ema_21=price,
            price_vs_sma_20_pct=0.0, price_vs_sma_50_pct=2.0, price_vs_sma_200_pct=5.0,
        ),
        rsi=RSIData(value=rsi, is_overbought=rsi > 70, is_oversold=rsi < 30),
        bollinger=BollingerBands(upper=price + 10, middle=price, lower=price - 10,
                                 bandwidth=0.04, percent_b=percent_b),
        macd=MACDData(macd_line=-3.0, signal_line=-2.0, histogram=macd_histogram,
                      is_bullish_crossover=False, is_bearish_crossover=False),
        stochastic=StochasticData(k=20.0, d=25.0, is_overbought=False, is_oversold=True),
        support_resistance=SupportResistance(support=570.0, resistance=590.0,
                                              price_vs_support_pct=1.7, price_vs_resistance_pct=-1.7),
        phase=PhaseIndicator(phase=MarketPhase.ACCUMULATION, confidence=0.5, description="Test",
                             higher_highs=False, higher_lows=True, lower_highs=False, lower_lows=False,
                             range_compression=0.3, volume_trend="declining", price_vs_sma_50_pct=2.0),
        signals=[],
    )


class TestMomentumOverride:
    """Tests for Fix 2: MACD momentum override in score_entry_level."""

    def test_no_override_when_macd_aligned_bullish(self) -> None:
        """MACD positive (bullish momentum) for bullish direction → no cap applied.

        The no-override case: with positive MACD the momentum_cap stays at 1.0
        so the score should NOT be artificially capped. We verify by comparing
        the uncapped result equals the raw weighted sum (RSI+BB extremity only,
        since price==sma_20==vwap → atr_score and vwap_score are 0).
        """
        tech = _make_technicals_with_macd(rsi=25.0, percent_b=0.05, macd_histogram=+5.0)
        levels = _make_levels(supports=[(570.0, 0.80, ["sma_200"])], resistances=[])
        result = score_entry_level(tech, levels, direction="bullish")
        # No cap was applied (score matches raw weighted sum without override)
        assert "override" not in result.rationale.lower()
        # RSI=25 → rsi_score=1.25 capped at 1.0; %B=0.05 → bb_score=1.5 capped at 1.0
        # weighted: 1.0*0.35 + 1.0*0.30 = 0.65 (no vwap/atr contribution with price==sma_20)
        assert result.overall_score == pytest.approx(0.65, abs=0.01)

    def test_override_applied_strong_bearish_macd_for_bullish_entry(self) -> None:
        """MACD histogram deeply negative (strong selling) for bullish entry → capped at 0.65."""
        # price=572 (oversold: RSI=25, %B=0.05) but MACD selling is accelerating
        # ATR at 0.86% of 572 ≈ 4.9 points; histogram=-10.0 → momentum_z ≈ 2.0 > 1.0
        tech = _make_technicals_with_macd(
            price=572.0, rsi=25.0, percent_b=0.05, macd_histogram=-10.0, atr_pct=0.86
        )
        levels = _make_levels(supports=[(570.0, 0.90, ["sma_200"])], resistances=[])
        result = score_entry_level(tech, levels, direction="bullish")
        # Score must be capped at 0.65 even though RSI/BB look very oversold
        assert result.overall_score <= 0.65
        assert result.action in ("wait", "enter_now")  # 0.65 is right at enter_now boundary
        assert "override" in result.rationale.lower() or "momentum" in result.rationale.lower()

    def test_override_applied_strong_bullish_macd_for_bearish_entry(self) -> None:
        """MACD histogram strongly positive (buying momentum) for bearish entry → capped at 0.65."""
        # Overbought conditions (RSI=78, %B=0.95) but buying momentum accelerating
        tech = _make_technicals_with_macd(
            price=589.0, rsi=78.0, percent_b=0.95, macd_histogram=+10.0, atr_pct=0.86
        )
        levels = _make_levels(supports=[], resistances=[(590.0, 0.85, ["swing_resistance"])])
        result = score_entry_level(tech, levels, direction="bearish")
        assert result.overall_score <= 0.65
        assert "override" in result.rationale.lower() or "momentum" in result.rationale.lower()

    def test_override_threshold_exactly_one_atr(self) -> None:
        """Momentum z-score exactly at 1.0 (boundary) → no cap applied (must be > 1.0)."""
        # ATR at 0.86% of 580 ≈ 4.99 points; histogram = -4.99 → momentum_z ≈ 1.0 (not > 1.0)
        price = 580.0
        atr_pct = 0.86
        atr = price * atr_pct / 100  # ≈ 4.988
        macd_hist = -1.0 * atr  # exactly 1.0x ATR
        tech = _make_technicals_with_macd(
            price=price, rsi=25.0, percent_b=0.05, macd_histogram=macd_hist, atr_pct=atr_pct
        )
        levels = _make_levels(supports=[(575.0, 0.80, ["sma_200"])], resistances=[])
        result_at_boundary = score_entry_level(tech, levels, direction="bullish")
        # At exactly 1.0 ATR, momentum_z is not > 1.0 → no cap
        assert "override" not in result_at_boundary.rationale.lower()

    def test_override_not_applied_neutral_direction(self) -> None:
        """Neutral direction ignores MACD override (doesn't penalise either way)."""
        tech = _make_technicals_with_macd(
            price=572.0, rsi=25.0, percent_b=0.05, macd_histogram=-10.0, atr_pct=0.86
        )
        levels = _make_levels(supports=[(570.0, 0.80, ["sma_200"])], resistances=[])
        result = score_entry_level(tech, levels, direction="neutral")
        # Override only applies to directional entries, not neutral
        assert "override" not in result.rationale.lower()

    def test_override_note_prepended_to_rationale(self) -> None:
        """When override fires, the momentum note is the first item in rationale."""
        tech = _make_technicals_with_macd(
            price=572.0, rsi=25.0, percent_b=0.05, macd_histogram=-10.0, atr_pct=0.86
        )
        levels = _make_levels(supports=[], resistances=[])
        result = score_entry_level(tech, levels, direction="bullish")
        assert result.rationale.startswith("Momentum override")


# ---------------------------------------------------------------------------
# Fix 1: Minimum credit pre-filter in run_daily_checks
# ---------------------------------------------------------------------------


class TestMinimumCreditFilter:
    """Tests for Fix 1: minimum $0.50 credit pre-filter in run_daily_checks."""

    def _make_simple_trade_spec(self) -> "TradeSpec":
        legs = [
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 570.0),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", 565.0),
            _make_leg("short_call", LegAction.SELL_TO_OPEN, "call", 590.0),
            _make_leg("long_call", LegAction.BUY_TO_OPEN, "call", 595.0),
        ]
        return _make_trade_spec(legs)

    def test_credit_above_minimum_proceeds_normally(self) -> None:
        """Credit $1.50 → normal 10-check suite runs."""
        ts = self._make_simple_trade_spec()
        report = run_daily_checks(
            ticker="SPY", trade_spec=ts, entry_credit=1.50,
            regime_id=1, atr_pct=0.86, current_price=580.0,
            avg_bid_ask_spread_pct=1.0, dte=30, rsi=50.0,
        )
        assert len(report.checks) == 10

    def test_credit_at_minimum_proceeds_normally(self) -> None:
        """Credit exactly $0.50 → normal suite runs (boundary: >= 0.50 is allowed)."""
        ts = self._make_simple_trade_spec()
        report = run_daily_checks(
            ticker="SPY", trade_spec=ts, entry_credit=0.50,
            regime_id=1, atr_pct=0.86, current_price=580.0,
            avg_bid_ask_spread_pct=1.0, dte=30, rsi=50.0,
        )
        assert len(report.checks) == 10

    def test_credit_below_minimum_early_fail(self) -> None:
        """Credit $0.05 → immediate FAIL with single check, not full suite."""
        ts = self._make_simple_trade_spec()
        report = run_daily_checks(
            ticker="SPY", trade_spec=ts, entry_credit=0.05,
            regime_id=1, atr_pct=0.86, current_price=580.0,
            avg_bid_ask_spread_pct=1.0, dte=30, rsi=50.0,
        )
        assert len(report.checks) == 1
        assert report.checks[0].name == "minimum_credit"
        assert report.checks[0].severity == Severity.FAIL
        assert not report.is_ready

    def test_credit_zero_early_fail(self) -> None:
        """Credit $0.00 → immediate FAIL."""
        ts = self._make_simple_trade_spec()
        report = run_daily_checks(
            ticker="SPY", trade_spec=ts, entry_credit=0.00,
            regime_id=1, atr_pct=0.86, current_price=580.0,
            avg_bid_ask_spread_pct=1.0, dte=30, rsi=50.0,
        )
        assert report.checks[0].name == "minimum_credit"
        assert report.checks[0].severity == Severity.FAIL

    def test_credit_negative_early_fail(self) -> None:
        """Negative credit (debit trade passed by mistake) → immediate FAIL."""
        ts = self._make_simple_trade_spec()
        report = run_daily_checks(
            ticker="SPY", trade_spec=ts, entry_credit=-0.10,
            regime_id=1, atr_pct=0.86, current_price=580.0,
            avg_bid_ask_spread_pct=1.0, dte=30, rsi=50.0,
        )
        assert report.checks[0].name == "minimum_credit"
        assert report.checks[0].severity == Severity.FAIL

    def test_credit_just_below_minimum_early_fail(self) -> None:
        """Credit $0.49 → immediate FAIL (just below the $0.50 threshold)."""
        ts = self._make_simple_trade_spec()
        report = run_daily_checks(
            ticker="SPY", trade_spec=ts, entry_credit=0.49,
            regime_id=1, atr_pct=0.86, current_price=580.0,
            avg_bid_ask_spread_pct=1.0, dte=30, rsi=50.0,
        )
        assert report.checks[0].name == "minimum_credit"
        assert report.checks[0].severity == Severity.FAIL

    def test_fail_message_shows_credit_amount(self) -> None:
        """Fail message includes the actual credit amount."""
        ts = self._make_simple_trade_spec()
        report = run_daily_checks(
            ticker="SPY", trade_spec=ts, entry_credit=0.12,
            regime_id=1, atr_pct=0.86, current_price=580.0,
            avg_bid_ask_spread_pct=1.0, dte=30, rsi=50.0,
        )
        assert "0.12" in report.checks[0].message
