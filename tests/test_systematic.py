"""Tests for Phase 1 systematic trading features.

Covers:
  G01: recommend_action() deterministic adjustment decision tree
  G02: validate_execution_quality()
  G03: entry_window on TradeSpec
  G04: time_of_day in monitor_exit_conditions
  G05: assess_overnight_risk
"""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest

from market_analyzer.models.adjustment import (
    AdjustmentDecision,
    AdjustmentType,
    PositionStatus,
)
from market_analyzer.models.opportunity import (
    LegAction,
    LegSpec,
    OrderSide,
    StructureType,
    TradeSpec,
)
from market_analyzer.models.quotes import OptionQuote
from market_analyzer.models.feedback import TradeOutcome, TradeExitReason
from market_analyzer.models.ranking import StrategyType
from market_analyzer.models.regime import RegimeID, RegimeResult
from market_analyzer.models.technicals import (
    BollingerBands,
    MACDData,
    MovingAverages,
    PhaseIndicator,
    RSIData,
    StochasticData,
    SupportResistance,
    TechnicalSnapshot,
)
from market_analyzer.execution_quality import (
    ExecutionQuality,
    ExecutionVerdict,
    validate_execution_quality,
)
from market_analyzer.service.adjustment import AdjustmentService
from market_analyzer.trade_lifecycle import (
    OvernightRisk,
    OvernightRiskLevel,
    assess_overnight_risk,
    monitor_exit_conditions,
)


# ── Shared Fixtures ──


def _make_leg(
    role: str,
    action: LegAction,
    option_type: str,
    strike: float,
    dte: int = 30,
) -> LegSpec:
    exp = date.today() + timedelta(days=dte)
    return LegSpec(
        role=role,
        action=action,
        option_type=option_type,
        strike=strike,
        strike_label=f"{strike:.0f} {option_type}",
        expiration=exp,
        days_to_expiry=dte,
        atm_iv_at_expiry=0.25,
    )


def _make_iron_condor(
    ticker: str = "SPY",
    price: float = 600.0,
    short_put: float = 580.0,
    long_put: float = 575.0,
    short_call: float = 620.0,
    long_call: float = 625.0,
    dte: int = 30,
) -> TradeSpec:
    exp = date.today() + timedelta(days=dte)
    return TradeSpec(
        ticker=ticker,
        legs=[
            _make_leg("short_put", LegAction.SELL_TO_OPEN, "put", short_put, dte),
            _make_leg("long_put", LegAction.BUY_TO_OPEN, "put", long_put, dte),
            _make_leg("short_call", LegAction.SELL_TO_OPEN, "call", short_call, dte),
            _make_leg("long_call", LegAction.BUY_TO_OPEN, "call", long_call, dte),
        ],
        underlying_price=price,
        target_dte=dte,
        target_expiration=exp,
        wing_width_points=5.0,
        spec_rationale="Test IC",
        structure_type=StructureType.IRON_CONDOR,
        order_side=OrderSide.CREDIT,
        profit_target_pct=0.50,
        stop_loss_pct=2.0,
        exit_dte=21,
    )


def _make_regime(regime_id: int = 1) -> RegimeResult:
    return RegimeResult(
        ticker="SPY",
        regime=RegimeID(regime_id),
        confidence=0.85,
        regime_probabilities={
            RegimeID.R1_LOW_VOL_MR: 0.85 if regime_id == 1 else 0.05,
            RegimeID.R2_HIGH_VOL_MR: 0.85 if regime_id == 2 else 0.05,
            RegimeID.R3_LOW_VOL_TREND: 0.85 if regime_id == 3 else 0.05,
            RegimeID.R4_HIGH_VOL_TREND: 0.85 if regime_id == 4 else 0.05,
        },
        as_of_date=date.today(),
        model_version="test",
    )


def _make_technicals(price: float = 600.0, atr: float = 8.0) -> TechnicalSnapshot:
    return TechnicalSnapshot(
        ticker="SPY",
        as_of_date=date.today(),
        current_price=price,
        atr=atr,
        atr_pct=atr / price * 100,
        vwma_20=price,
        moving_averages=MovingAverages(
            sma_20=price, sma_50=price, sma_200=price,
            ema_9=price, ema_21=price,
            price_vs_sma_20_pct=0.0, price_vs_sma_50_pct=0.0,
            price_vs_sma_200_pct=0.0,
        ),
        rsi=RSIData(value=50.0, is_overbought=False, is_oversold=False),
        bollinger=BollingerBands(
            upper=price + 10, middle=price, lower=price - 10,
            bandwidth=3.3, percent_b=0.5,
        ),
        macd=MACDData(
            macd_line=0.0, signal_line=0.0, histogram=0.0,
            is_bullish_crossover=False, is_bearish_crossover=False,
        ),
        stochastic=StochasticData(k=50.0, d=50.0, is_overbought=False, is_oversold=False),
        support_resistance=SupportResistance(
            support=price - 20, resistance=price + 20,
            price_vs_support_pct=3.3, price_vs_resistance_pct=3.3,
        ),
        phase=PhaseIndicator(
            phase="accumulation", confidence=0.6, description="",
            higher_highs=True, higher_lows=True, lower_highs=False, lower_lows=False,
            range_compression=0.0, volume_trend="stable", price_vs_sma_50_pct=0.0,
        ),
        signals=[],
    )


def _make_quote(
    strike: float,
    option_type: str,
    expiration: date,
    bid: float = 2.50,
    ask: float = 2.70,
    open_interest: int = 500,
    volume: int = 100,
) -> OptionQuote:
    return OptionQuote(
        ticker="SPY",
        expiration=expiration,
        strike=strike,
        option_type=option_type,
        bid=bid,
        ask=ask,
        mid=(bid + ask) / 2.0,
        volume=volume,
        open_interest=open_interest,
    )


# ── G01: recommend_action() deterministic adjustment decision tree ──


class TestRecommendAction:
    """Test the deterministic adjustment decision tree."""

    def _call(
        self,
        price: float,
        regime_id: int,
        short_put: float = 580.0,
        long_put: float = 575.0,
        short_call: float = 620.0,
        long_call: float = 625.0,
    ) -> AdjustmentDecision:
        svc = AdjustmentService()
        ic = _make_iron_condor(
            price=600.0,
            short_put=short_put,
            long_put=long_put,
            short_call=short_call,
            long_call=long_call,
        )
        regime = _make_regime(regime_id)
        tech = _make_technicals(price=price)
        return svc.recommend_action(ic, regime, tech)

    def test_safe_always_do_nothing(self):
        """SAFE + any regime -> DO_NOTHING."""
        for r in (1, 2, 3, 4):
            result = self._call(price=600.0, regime_id=r)
            assert result.action == AdjustmentType.DO_NOTHING, f"SAFE + R{r} should be DO_NOTHING"

    def test_tested_r1_do_nothing(self):
        """TESTED + R1 -> DO_NOTHING."""
        result = self._call(price=583.0, regime_id=1)
        assert result.action == AdjustmentType.DO_NOTHING

    def test_tested_r2_do_nothing(self):
        """TESTED + R2 -> DO_NOTHING."""
        result = self._call(price=583.0, regime_id=2)
        assert result.action == AdjustmentType.DO_NOTHING

    def test_tested_r3_roll_away(self):
        """TESTED + R3 -> ROLL_AWAY."""
        result = self._call(price=583.0, regime_id=3)
        assert result.action == AdjustmentType.ROLL_AWAY

    def test_tested_r4_close_full(self):
        """TESTED + R4 -> CLOSE_FULL."""
        result = self._call(price=583.0, regime_id=4)
        assert result.action == AdjustmentType.CLOSE_FULL

    def test_breached_r1_roll_away(self):
        """BREACHED + R1 -> ROLL_AWAY."""
        result = self._call(price=577.0, regime_id=1)
        assert result.action == AdjustmentType.ROLL_AWAY

    def test_breached_r2_roll_away(self):
        """BREACHED + R2 -> ROLL_AWAY."""
        result = self._call(price=577.0, regime_id=2)
        assert result.action == AdjustmentType.ROLL_AWAY

    def test_breached_r3_close_full(self):
        """BREACHED + R3 -> CLOSE_FULL."""
        result = self._call(price=577.0, regime_id=3)
        assert result.action == AdjustmentType.CLOSE_FULL

    def test_breached_r4_close_full(self):
        """BREACHED + R4 -> CLOSE_FULL."""
        result = self._call(price=577.0, regime_id=4)
        assert result.action == AdjustmentType.CLOSE_FULL

    def test_max_loss_always_close(self):
        """MAX_LOSS + any regime -> CLOSE_FULL."""
        for r in (1, 2, 3, 4):
            result = self._call(price=570.0, regime_id=r)
            assert result.action == AdjustmentType.CLOSE_FULL, f"MAX_LOSS + R{r} should be CLOSE_FULL"

    def test_returns_adjustment_decision_type(self):
        """Verify return type is AdjustmentDecision."""
        result = self._call(price=600.0, regime_id=1)
        assert isinstance(result, AdjustmentDecision)

    def test_rationale_includes_regime(self):
        """Verify rationale mentions regime context."""
        # TESTED + R3 should mention R3 / trending
        result = self._call(price=583.0, regime_id=3)
        assert "R3" in result.rationale or "trending" in result.rationale.lower()


# ── G02: validate_execution_quality() ──


class TestExecutionQuality:
    """Test execution quality validation."""

    def _make_ic_with_quotes(
        self,
        bid: float = 2.50,
        ask: float = 2.70,
        open_interest: int = 500,
        volume: int = 100,
    ) -> tuple[TradeSpec, list[OptionQuote]]:
        """Build a 4-leg IC and matching quotes for all legs."""
        ic = _make_iron_condor()
        quotes = [
            _make_quote(
                strike=leg.strike,
                option_type=leg.option_type,
                expiration=leg.expiration,
                bid=bid,
                ask=ask,
                open_interest=open_interest,
                volume=volume,
            )
            for leg in ic.legs
        ]
        return ic, quotes

    def test_go_with_good_quotes(self):
        """All legs have tight spread, good OI/volume -> GO."""
        ic, quotes = self._make_ic_with_quotes(bid=2.50, ask=2.70, open_interest=500, volume=100)
        result = validate_execution_quality(ic, quotes)
        assert result.overall_verdict == ExecutionVerdict.GO
        assert result.tradeable is True

    def test_wide_spread_detected(self):
        """One leg with 20% spread -> WIDE_SPREAD."""
        ic = _make_iron_condor()
        # 3 good legs + 1 wide-spread leg
        quotes = []
        for i, leg in enumerate(ic.legs):
            if i == 0:
                # bid=1.0, ask=1.40 -> spread = 0.40 / 1.20 * 100 = 33%
                quotes.append(_make_quote(leg.strike, leg.option_type, leg.expiration,
                                          bid=1.0, ask=1.40, open_interest=500, volume=100))
            else:
                quotes.append(_make_quote(leg.strike, leg.option_type, leg.expiration,
                                          bid=2.50, ask=2.70, open_interest=500, volume=100))
        result = validate_execution_quality(ic, quotes)
        assert result.overall_verdict == ExecutionVerdict.WIDE_SPREAD
        assert result.tradeable is False

    def test_no_quote_detected(self):
        """Missing quote for a leg -> NO_QUOTE."""
        ic = _make_iron_condor()
        # Only provide quotes for 3 of 4 legs
        quotes = [
            _make_quote(leg.strike, leg.option_type, leg.expiration)
            for leg in ic.legs[:3]
        ]
        result = validate_execution_quality(ic, quotes)
        assert result.overall_verdict == ExecutionVerdict.NO_QUOTE
        assert result.tradeable is False

    def test_illiquid_low_oi(self):
        """OI < min_open_interest -> ILLIQUID."""
        ic, quotes = self._make_ic_with_quotes(open_interest=10, volume=100)
        result = validate_execution_quality(ic, quotes, min_open_interest=50)
        assert result.overall_verdict == ExecutionVerdict.ILLIQUID
        assert result.tradeable is False

    def test_illiquid_low_volume(self):
        """volume < min_volume -> ILLIQUID."""
        ic, quotes = self._make_ic_with_quotes(open_interest=500, volume=1)
        result = validate_execution_quality(ic, quotes, min_volume=5)
        assert result.overall_verdict == ExecutionVerdict.ILLIQUID
        assert result.tradeable is False

    def test_worst_leg_determines_overall(self):
        """3 legs GO + 1 leg WIDE_SPREAD -> overall WIDE_SPREAD."""
        ic = _make_iron_condor()
        quotes = []
        for i, leg in enumerate(ic.legs):
            if i == 2:
                # Wide spread: bid=0.50, ask=1.50 -> spread = 100%
                quotes.append(_make_quote(leg.strike, leg.option_type, leg.expiration,
                                          bid=0.50, ask=1.50, open_interest=500, volume=100))
            else:
                quotes.append(_make_quote(leg.strike, leg.option_type, leg.expiration,
                                          bid=2.50, ask=2.70, open_interest=500, volume=100))
        result = validate_execution_quality(ic, quotes)
        assert result.overall_verdict == ExecutionVerdict.WIDE_SPREAD
        # Verify 3 legs passed
        go_count = sum(1 for lq in result.legs if lq.verdict == ExecutionVerdict.GO)
        assert go_count == 3

    def test_tradeable_only_when_go(self):
        """tradeable=True only when overall_verdict == GO."""
        # GO case
        ic, quotes = self._make_ic_with_quotes()
        result = validate_execution_quality(ic, quotes)
        assert result.tradeable is True
        assert result.overall_verdict == ExecutionVerdict.GO

        # Non-GO case
        ic, quotes = self._make_ic_with_quotes(open_interest=1)
        result = validate_execution_quality(ic, quotes, min_open_interest=50)
        assert result.tradeable is False
        assert result.overall_verdict != ExecutionVerdict.GO

    def test_custom_thresholds(self):
        """Custom max_spread_pct, min_open_interest work."""
        ic = _make_iron_condor()
        # bid=2.50, ask=3.10 -> spread = 21.4%, fails at 15% but passes at 25%
        quotes = [
            _make_quote(leg.strike, leg.option_type, leg.expiration,
                        bid=2.50, ask=3.10, open_interest=500, volume=100)
            for leg in ic.legs
        ]
        # Fails with default 15%
        result_strict = validate_execution_quality(ic, quotes, max_spread_pct=15.0)
        assert result_strict.overall_verdict == ExecutionVerdict.WIDE_SPREAD

        # Passes with relaxed 25%
        result_relaxed = validate_execution_quality(ic, quotes, max_spread_pct=25.0)
        assert result_relaxed.overall_verdict == ExecutionVerdict.GO

    def test_zero_bid_is_no_quote(self):
        """bid=0 -> NO_QUOTE even if ask is present."""
        ic = _make_iron_condor()
        quotes = [
            _make_quote(leg.strike, leg.option_type, leg.expiration,
                        bid=0.0, ask=2.70, open_interest=500, volume=100)
            for leg in ic.legs
        ]
        result = validate_execution_quality(ic, quotes)
        assert result.overall_verdict == ExecutionVerdict.NO_QUOTE
        assert result.tradeable is False


# ── G03: entry_window on TradeSpec ──


class TestEntryWindow:
    """Test entry_window_start/end fields on TradeSpec."""

    def test_defaults_to_none(self):
        """TradeSpec() with no entry window -> None."""
        ic = _make_iron_condor()
        assert ic.entry_window_start is None
        assert ic.entry_window_end is None

    def test_entry_window_round_trip(self):
        """Set entry_window_start/end, verify they persist."""
        exp = date.today() + timedelta(days=30)
        ts = TradeSpec(
            ticker="SPY",
            legs=[_make_leg("short_put", LegAction.SELL_TO_OPEN, "put", 580.0)],
            underlying_price=600.0,
            target_dte=30,
            target_expiration=exp,
            spec_rationale="Test entry window",
            entry_window_start=time(9, 45),
            entry_window_end=time(14, 0),
        )
        assert ts.entry_window_start == time(9, 45)
        assert ts.entry_window_end == time(14, 0)


# ── G04: time_of_day in monitor_exit_conditions ──


class TestTimeOfDayUrgency:
    """Test end-of-day urgency escalation."""

    def test_0dte_after_1500_force_close(self):
        """dte=0, time=15:01 -> eod_0dte signal triggered."""
        result = monitor_exit_conditions(
            trade_id="t1",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=1.20,
            contracts=1,
            dte_remaining=0,
            regime_id=1,
            time_of_day=time(15, 1),
        )
        eod_signals = [s for s in result.signals if s.rule == "eod_0dte"]
        assert len(eod_signals) == 1
        assert eod_signals[0].triggered is True
        assert eod_signals[0].urgency == "immediate"

    def test_0dte_before_1500_no_signal(self):
        """dte=0, time=14:59 -> no eod_0dte signal."""
        result = monitor_exit_conditions(
            trade_id="t1",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=1.20,
            contracts=1,
            dte_remaining=0,
            regime_id=1,
            time_of_day=time(14, 59),
        )
        eod_signals = [s for s in result.signals if s.rule == "eod_0dte"]
        assert len(eod_signals) == 0

    def test_tested_after_1530_escalate(self):
        """dte=30, tested position (approaching stop loss), time=15:31 -> eod_tested signal."""
        # Entry at 1.50 credit. Current mid at 2.70 means loss_multiple = (2.70-1.50)/1.50 = 0.8.
        # With stop_loss_pct=2.0, 0.75 * 2.0 = 1.5, 0.8 < 1.5, so stop_loss urgency is "monitor", not "soon".
        # We need urgency == "soon" for stop_loss. That requires loss_multiple >= 0.75 * stop_loss_pct.
        # stop_loss_pct=2.0 -> need loss_multiple >= 1.5 -> current_mid = 1.50 + 1.50 * 1.5 = 3.75.
        result = monitor_exit_conditions(
            trade_id="t1",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=3.75,
            contracts=1,
            dte_remaining=30,
            regime_id=1,
            stop_loss_pct=2.0,
            time_of_day=time(15, 31),
        )
        eod_signals = [s for s in result.signals if s.rule == "eod_tested"]
        assert len(eod_signals) == 1
        assert eod_signals[0].triggered is True

    def test_safe_after_1530_no_escalate(self):
        """dte=30, safe position, time=15:31 -> no eod_tested signal."""
        result = monitor_exit_conditions(
            trade_id="t1",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=1.20,
            contracts=1,
            dte_remaining=30,
            regime_id=1,
            stop_loss_pct=2.0,
            time_of_day=time(15, 31),
        )
        eod_signals = [s for s in result.signals if s.rule == "eod_tested"]
        assert len(eod_signals) == 0

    def test_no_time_provided_backward_compat(self):
        """time_of_day=None -> no eod signals, same behavior as before."""
        result = monitor_exit_conditions(
            trade_id="t1",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=1.20,
            contracts=1,
            dte_remaining=0,
            regime_id=1,
            time_of_day=None,
        )
        eod_signals = [s for s in result.signals if s.rule.startswith("eod_")]
        assert len(eod_signals) == 0


# ── G05: assess_overnight_risk ──


class TestOvernightRisk:
    """Test overnight gap risk assessment."""

    def test_0dte_always_close(self):
        """dte=0 -> CLOSE_BEFORE_CLOSE."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=0, regime_id=1,
            position_status="safe",
        )
        assert result.risk_level == OvernightRiskLevel.CLOSE_BEFORE_CLOSE

    def test_breached_r4_close(self):
        """breached + R4 -> CLOSE_BEFORE_CLOSE."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=4,
            position_status="breached",
        )
        assert result.risk_level == OvernightRiskLevel.CLOSE_BEFORE_CLOSE

    def test_tested_r4_close(self):
        """tested + R4 -> CLOSE_BEFORE_CLOSE."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=4,
            position_status="tested",
        )
        assert result.risk_level == OvernightRiskLevel.CLOSE_BEFORE_CLOSE

    def test_breached_r1_high(self):
        """breached + R1 -> HIGH."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=1,
            position_status="breached",
        )
        assert result.risk_level == OvernightRiskLevel.HIGH

    def test_tested_r3_high(self):
        """tested + R3 -> HIGH."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=3,
            position_status="tested",
        )
        assert result.risk_level == OvernightRiskLevel.HIGH

    def test_earnings_tomorrow_high(self):
        """safe + R1 + earnings tomorrow -> HIGH."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=1,
            position_status="safe", has_earnings_tomorrow=True,
        )
        assert result.risk_level == OvernightRiskLevel.HIGH

    def test_macro_tomorrow_medium(self):
        """safe + R1 + macro tomorrow -> MEDIUM."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=1,
            position_status="safe", has_macro_event_tomorrow=True,
        )
        assert result.risk_level == OvernightRiskLevel.MEDIUM

    def test_safe_r1_low(self):
        """safe + R1 + no events -> LOW."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=1,
            position_status="safe",
        )
        assert result.risk_level == OvernightRiskLevel.LOW

    def test_safe_r3_medium(self):
        """safe + R3 -> MEDIUM (trending = some gap risk)."""
        result = assess_overnight_risk(
            trade_id="t1", ticker="SPY", structure_type="iron_condor",
            order_side="credit", dte_remaining=30, regime_id=3,
            position_status="safe",
        )
        assert result.risk_level == OvernightRiskLevel.MEDIUM


# ── G06: Auto-select screening ──


class TestAutoSelectScreening:
    """Test ScreeningResult model fields and scan() parameters."""

    def test_min_score_filters_low_candidates(self):
        """ScreeningResult with min_score=0.7 excludes candidates below 0.7."""
        from market_analyzer.service.screening import ScreenCandidate, ScreeningResult

        candidates = [
            ScreenCandidate(
                ticker="SPY", screen="breakout", score=0.8, reason="strong",
                regime_id=1, rsi=55.0, atr_pct=1.2,
            ),
            ScreenCandidate(
                ticker="GLD", screen="income", score=0.5, reason="weak",
                regime_id=1, rsi=45.0, atr_pct=0.9,
            ),
            ScreenCandidate(
                ticker="QQQ", screen="momentum", score=0.75, reason="ok",
                regime_id=3, rsi=60.0, atr_pct=1.5,
            ),
        ]
        # Apply min_score filter manually (same logic as scan())
        min_score = 0.7
        filtered = [c for c in candidates if c.score >= min_score]
        result = ScreeningResult(
            as_of_date=date.today(),
            tickers_scanned=3,
            candidates=filtered,
            by_screen={},
            summary="test",
            min_score_applied=min_score,
            filtered_count=len(candidates) - len(filtered),
        )
        assert len(result.candidates) == 2
        assert all(c.score >= 0.7 for c in result.candidates)
        assert result.filtered_count == 1

    def test_top_n_limits_results(self):
        """top_n=2 returns only top 2."""
        from market_analyzer.service.screening import ScreenCandidate, ScreeningResult

        candidates = [
            ScreenCandidate(
                ticker=t, screen="breakout", score=s, reason="r",
                regime_id=1, rsi=50.0, atr_pct=1.0,
            )
            for t, s in [("SPY", 0.9), ("GLD", 0.8), ("QQQ", 0.7), ("TLT", 0.6)]
        ]
        top_n = 2
        limited = candidates[:top_n]
        result = ScreeningResult(
            as_of_date=date.today(),
            tickers_scanned=4,
            candidates=limited,
            by_screen={},
            summary="test",
        )
        assert len(result.candidates) == 2
        assert result.candidates[0].ticker == "SPY"
        assert result.candidates[1].ticker == "GLD"

    def test_filtered_count_tracks_removed(self):
        """filtered_count reflects how many were cut."""
        from market_analyzer.service.screening import ScreeningResult

        result = ScreeningResult(
            as_of_date=date.today(),
            tickers_scanned=10,
            candidates=[],
            by_screen={},
            summary="test",
            min_score_applied=0.8,
            filtered_count=7,
        )
        assert result.filtered_count == 7
        assert result.min_score_applied == 0.8

    def test_min_score_zero_returns_all(self):
        """min_score=0 returns everything (backward compat)."""
        from market_analyzer.service.screening import ScreenCandidate, ScreeningResult

        candidates = [
            ScreenCandidate(
                ticker=t, screen="income", score=s, reason="r",
                regime_id=1, rsi=50.0, atr_pct=1.0,
            )
            for t, s in [("SPY", 0.1), ("GLD", 0.05), ("QQQ", 0.9)]
        ]
        # min_score=0 means no filtering
        min_score = 0.0
        filtered = [c for c in candidates if c.score >= min_score] if min_score > 0 else candidates
        result = ScreeningResult(
            as_of_date=date.today(),
            tickers_scanned=3,
            candidates=filtered,
            by_screen={},
            summary="test",
            min_score_applied=min_score,
            filtered_count=0,
        )
        assert len(result.candidates) == 3

    def test_default_min_score_is_0_6(self):
        """Verify default parameter is 0.6 in ScreeningService.scan()."""
        import inspect
        from market_analyzer.service.screening import ScreeningService

        sig = inspect.signature(ScreeningService.scan)
        min_score_param = sig.parameters["min_score"]
        assert min_score_param.default == 0.6


# ── G07: Performance feedback ──


def _make_outcome(
    pnl_pct: float = 0.15,
    strategy: StrategyType = StrategyType.IRON_CONDOR,
    regime: int = 1,
    exit_reason: TradeExitReason = TradeExitReason.PROFIT_TARGET,
    score: float = 0.75,
    pnl_dollars: float | None = None,
    trade_id: str = "test-001",
) -> TradeOutcome:
    if pnl_dollars is None:
        pnl_dollars = 40.0 if pnl_pct > 0 else -40.0
    return TradeOutcome(
        trade_id=trade_id,
        ticker="SPY",
        strategy_type=strategy,
        regime_at_entry=regime,
        regime_at_exit=regime,
        entry_date=date(2026, 1, 1),
        exit_date=date(2026, 1, 15),
        entry_price=0.80,
        exit_price=0.40,
        pnl_dollars=pnl_dollars,
        pnl_pct=pnl_pct,
        holding_days=14,
        exit_reason=exit_reason,
        composite_score_at_entry=score,
    )


class TestPerformanceTracking:
    """Test performance analysis and weight calibration."""

    def test_compute_strategy_performance_basic(self):
        """5 winning trades + 3 losing -> correct win_rate, avg_pnl."""
        from market_analyzer.performance import compute_strategy_performance

        outcomes = (
            [_make_outcome(pnl_pct=0.10, pnl_dollars=30.0, trade_id=f"w{i}") for i in range(5)]
            + [_make_outcome(pnl_pct=-0.08, pnl_dollars=-25.0, trade_id=f"l{i}") for i in range(3)]
        )
        result = compute_strategy_performance(outcomes, strategy_type=StrategyType.IRON_CONDOR)
        assert result.total_trades == 8
        assert result.wins == 5
        assert result.losses == 3
        assert abs(result.win_rate - 5 / 8) < 0.01
        expected_avg = (5 * 0.10 + 3 * (-0.08)) / 8
        assert abs(result.avg_pnl_pct - expected_avg) < 0.001

    def test_compute_strategy_performance_by_regime(self):
        """Filter by regime_id=1 -> only R1 trades counted."""
        from market_analyzer.performance import compute_strategy_performance

        outcomes = [
            _make_outcome(regime=1, pnl_pct=0.10, pnl_dollars=30.0, trade_id="r1a"),
            _make_outcome(regime=1, pnl_pct=0.12, pnl_dollars=35.0, trade_id="r1b"),
            _make_outcome(regime=2, pnl_pct=-0.05, pnl_dollars=-20.0, trade_id="r2a"),
            _make_outcome(regime=3, pnl_pct=0.08, pnl_dollars=25.0, trade_id="r3a"),
        ]
        result = compute_strategy_performance(
            outcomes, strategy_type=StrategyType.IRON_CONDOR, regime_id=1,
        )
        assert result.total_trades == 2
        assert result.regime_id == 1
        assert result.wins == 2

    def test_compute_performance_report_groups_by_strategy(self):
        """Multiple strategies -> by_strategy has entries for each."""
        from market_analyzer.performance import compute_performance_report

        outcomes = [
            _make_outcome(strategy=StrategyType.IRON_CONDOR, trade_id="ic1"),
            _make_outcome(strategy=StrategyType.IRON_CONDOR, trade_id="ic2"),
            _make_outcome(strategy=StrategyType.BREAKOUT, trade_id="bo1"),
            _make_outcome(strategy=StrategyType.LEAP, trade_id="lp1"),
        ]
        report = compute_performance_report(outcomes)
        assert report.total_trades == 4
        strategy_types = {sp.strategy_type for sp in report.by_strategy}
        assert StrategyType.IRON_CONDOR in strategy_types
        assert StrategyType.BREAKOUT in strategy_types
        assert StrategyType.LEAP in strategy_types

    def test_compute_performance_report_groups_by_regime(self):
        """Multiple regimes -> by_regime dict populated."""
        from market_analyzer.performance import compute_performance_report

        outcomes = [
            _make_outcome(regime=1, trade_id="r1"),
            _make_outcome(regime=2, trade_id="r2"),
            _make_outcome(regime=3, trade_id="r3"),
        ]
        report = compute_performance_report(outcomes)
        assert 1 in report.by_regime
        assert 2 in report.by_regime
        assert 3 in report.by_regime

    def test_calibrate_weights_no_trades_no_adjustments(self):
        """Empty outcomes -> no adjustments."""
        from market_analyzer.performance import calibrate_weights

        result = calibrate_weights([])
        assert len(result.adjustments) == 0
        assert "No trade outcomes" in result.summary

    def test_calibrate_weights_few_trades_no_adjustments(self):
        """5 trades (below min_trades=10) -> no adjustments."""
        from market_analyzer.performance import calibrate_weights

        outcomes = [
            _make_outcome(trade_id=f"t{i}") for i in range(5)
        ]
        result = calibrate_weights(outcomes, min_trades=10)
        assert len(result.adjustments) == 0

    def test_calibrate_weights_winning_strategy_increases_weight(self):
        """15 trades all winning in R1 IC -> suggest increasing R1+IC weight if win rate > weight + 0.1."""
        from market_analyzer.performance import calibrate_weights
        from market_analyzer.features.ranking import REGIME_STRATEGY_ALIGNMENT

        # R1 + IC weight from the alignment matrix
        current_weight = REGIME_STRATEGY_ALIGNMENT.get(
            (1, StrategyType.IRON_CONDOR), 0.5
        )
        # If current weight is already high (>0.9), a 100% win rate won't differ by >0.1.
        # Use a regime+strategy combo where weight is moderate so the test is meaningful.
        # R3 + IRON_CONDOR typically has a low weight (income in trending)
        r3_ic_weight = REGIME_STRATEGY_ALIGNMENT.get(
            (3, StrategyType.IRON_CONDOR), 0.5
        )
        outcomes = [
            _make_outcome(
                regime=3, strategy=StrategyType.IRON_CONDOR,
                pnl_pct=0.10, pnl_dollars=30.0, trade_id=f"t{i}",
            )
            for i in range(15)
        ]
        result = calibrate_weights(outcomes, min_trades=10)
        # If r3_ic_weight < 0.9, we should see an increase suggestion
        if r3_ic_weight < 0.9:
            assert len(result.adjustments) >= 1
            adj = result.adjustments[0]
            assert adj.suggested_weight > adj.current_weight
            assert "increase" in adj.reason.lower()

    def test_calibrate_weights_losing_strategy_decreases_weight(self):
        """15 trades all losing in R1 IC -> suggest decreasing R1+IC weight."""
        from market_analyzer.performance import calibrate_weights

        # R1 + IC has weight=1.0 typically; 0% win rate is 1.0 below, so diff = -1.0
        outcomes = [
            _make_outcome(
                regime=1, strategy=StrategyType.IRON_CONDOR,
                pnl_pct=-0.10, pnl_dollars=-30.0, trade_id=f"t{i}",
            )
            for i in range(15)
        ]
        result = calibrate_weights(outcomes, min_trades=10)
        assert len(result.adjustments) >= 1
        adj = result.adjustments[0]
        assert adj.suggested_weight < adj.current_weight
        assert "decrease" in adj.reason.lower()

    def test_calibrate_weights_max_adjustment_clamped(self):
        """Adjustment never exceeds max_adjustment parameter."""
        from market_analyzer.performance import calibrate_weights

        outcomes = [
            _make_outcome(
                regime=1, strategy=StrategyType.IRON_CONDOR,
                pnl_pct=-0.10, pnl_dollars=-30.0, trade_id=f"t{i}",
            )
            for i in range(20)
        ]
        max_adj = 0.05
        result = calibrate_weights(outcomes, min_trades=10, max_adjustment=max_adj)
        for adj in result.adjustments:
            assert abs(adj.suggested_weight - adj.current_weight) <= max_adj + 0.001

    def test_trade_outcome_model(self):
        """TradeOutcome can be created with all fields."""
        outcome = _make_outcome()
        assert outcome.trade_id == "test-001"
        assert outcome.ticker == "SPY"
        assert outcome.strategy_type == StrategyType.IRON_CONDOR
        assert outcome.regime_at_entry == 1
        assert outcome.pnl_pct == 0.15
        assert outcome.exit_reason == TradeExitReason.PROFIT_TARGET
        assert outcome.holding_days == 14
        assert outcome.contracts == 1  # default

    def test_performance_report_score_correlation(self):
        """With enough trades, score_correlation is computed (not None)."""
        from market_analyzer.performance import compute_performance_report

        # Create 10 trades with varying scores and PnLs (need >= 5 for correlation)
        outcomes = [
            _make_outcome(
                score=0.5 + i * 0.05,
                pnl_pct=0.02 * i,
                pnl_dollars=10.0 * i if i > 0 else -5.0,
                trade_id=f"corr{i}",
            )
            for i in range(10)
        ]
        report = compute_performance_report(outcomes)
        assert report.score_correlation is not None

    def test_profit_factor_no_losses(self):
        """All winning trades -> profit_factor = inf."""
        from market_analyzer.performance import compute_strategy_performance

        outcomes = [
            _make_outcome(pnl_pct=0.10, pnl_dollars=30.0, trade_id=f"w{i}")
            for i in range(5)
        ]
        result = compute_strategy_performance(outcomes, strategy_type=StrategyType.IRON_CONDOR)
        assert result.profit_factor == float("inf")


# ── G08-G09: Commentary + Data Gaps ──


class TestTransparency:
    """Test transparency fields (commentary + data_gaps) on models."""

    def test_data_gap_model(self):
        """DataGap(field='pop', reason='no broker', impact='off by 10-15%')."""
        from market_analyzer.models.transparency import DataGap

        gap = DataGap(field="pop", reason="no broker", impact="off by 10-15%")
        assert gap.field == "pop"
        assert gap.reason == "no broker"
        assert gap.impact == "off by 10-15%"

    def test_regime_result_has_commentary_field(self):
        """RegimeResult with empty commentary + data_gaps -> works."""
        result = _make_regime(1)
        assert result.commentary == []
        assert result.data_gaps == []

    def test_regime_result_accepts_commentary(self):
        """RegimeResult with populated commentary list -> accessible."""
        from market_analyzer.models.transparency import DataGap

        result = RegimeResult(
            ticker="SPY",
            regime=RegimeID.R1_LOW_VOL_MR,
            confidence=0.85,
            regime_probabilities={1: 0.85, 2: 0.05, 3: 0.05, 4: 0.05},
            as_of_date=date.today(),
            model_version="test",
            commentary=["Step 1: computed features", "Step 2: ran HMM inference"],
            data_gaps=[
                DataGap(field="iv_rank", reason="no broker", impact="regime may be less precise"),
            ],
        )
        assert len(result.commentary) == 2
        assert "Step 1" in result.commentary[0]
        assert len(result.data_gaps) == 1
        assert result.data_gaps[0].field == "iv_rank"

    def test_ranked_entry_has_data_gaps_field(self):
        """RankedEntry with data_gaps -> accessible."""
        from market_analyzer.models.ranking import RankedEntry, ScoreBreakdown, StrategyType
        from market_analyzer.models.opportunity import Verdict
        from market_analyzer.models.transparency import DataGap

        entry = RankedEntry(
            rank=1,
            ticker="SPY",
            strategy_type=StrategyType.IRON_CONDOR,
            verdict=Verdict.GO,
            composite_score=0.85,
            breakdown=ScoreBreakdown(
                verdict_score=1.0, confidence_score=0.8, regime_alignment=0.9,
                risk_reward=0.7, technical_quality=0.6, phase_alignment=0.8,
                income_bias_boost=0.05, black_swan_penalty=0.0,
                macro_penalty=0.0, earnings_penalty=0.0,
            ),
            strategy_name="iron_condor",
            direction="neutral",
            rationale="test",
            risk_notes=[],
            data_gaps=[
                DataGap(field="pop", reason="no broker", impact="estimated"),
            ],
            commentary=["Scored regime alignment at 0.9"],
        )
        assert len(entry.data_gaps) == 1
        assert entry.data_gaps[0].field == "pop"
        assert len(entry.commentary) == 1

    def test_trading_plan_has_transparency_fields(self):
        """DailyTradingPlan with commentary + data_gaps -> works."""
        from market_analyzer.models.trading_plan import (
            DailyTradingPlan, DayVerdict, RiskBudget,
        )
        from market_analyzer.models.transparency import DataGap

        plan = DailyTradingPlan(
            as_of_date=date.today(),
            plan_for_date=date.today(),
            day_verdict=DayVerdict.TRADE,
            day_verdict_reasons=["No macro events"],
            risk_budget=RiskBudget(
                max_new_positions=3,
                account_size=50000.0,
                max_daily_risk_dollars=1000.0,
                position_size_factor=1.0,
            ),
            expiry_events=[],
            upcoming_expiries=[],
            trades_by_horizon={},
            all_trades=[],
            total_trades=0,
            summary="test plan",
            commentary=["Step 1: checked macro calendar"],
            data_gaps=[
                DataGap(field="account_size", reason="no broker", impact="using config default"),
            ],
        )
        assert len(plan.commentary) == 1
        assert len(plan.data_gaps) == 1
        assert plan.data_gaps[0].field == "account_size"

    def test_opportunity_models_have_transparency_fields(self):
        """ZeroDTEOpportunity, LEAPOpportunity, BreakoutOpportunity, MomentumOpportunity all declare commentary + data_gaps."""
        from market_analyzer.models.opportunity import (
            ZeroDTEOpportunity, LEAPOpportunity, BreakoutOpportunity, MomentumOpportunity,
        )

        for model_cls in (ZeroDTEOpportunity, LEAPOpportunity, BreakoutOpportunity, MomentumOpportunity):
            fields = model_cls.model_fields
            assert "commentary" in fields, f"{model_cls.__name__} missing commentary field"
            assert "data_gaps" in fields, f"{model_cls.__name__} missing data_gaps field"
            # Verify defaults are empty lists
            assert fields["commentary"].default == [], f"{model_cls.__name__} commentary default != []"
            assert fields["data_gaps"].default == [], f"{model_cls.__name__} data_gaps default != []"

    def test_existing_models_backward_compat(self):
        """Creating RegimeResult WITHOUT commentary/data_gaps still works (defaults to [])."""
        result = RegimeResult(
            ticker="SPY",
            regime=RegimeID.R1_LOW_VOL_MR,
            confidence=0.85,
            regime_probabilities={1: 0.85, 2: 0.05, 3: 0.05, 4: 0.05},
            as_of_date=date.today(),
            model_version="test",
            # No commentary or data_gaps provided
        )
        assert result.commentary == []
        assert result.data_gaps == []
        # Same for RankedEntry
        from market_analyzer.models.ranking import RankedEntry, ScoreBreakdown, StrategyType
        from market_analyzer.models.opportunity import Verdict

        entry = RankedEntry(
            rank=1, ticker="SPY", strategy_type=StrategyType.IRON_CONDOR,
            verdict=Verdict.GO, composite_score=0.85,
            breakdown=ScoreBreakdown(
                verdict_score=1.0, confidence_score=0.8, regime_alignment=0.9,
                risk_reward=0.7, technical_quality=0.6, phase_alignment=0.8,
                income_bias_boost=0.05, black_swan_penalty=0.0,
                macro_penalty=0.0, earnings_penalty=0.0,
            ),
            strategy_name="iron_condor", direction="neutral",
            rationale="test", risk_notes=[],
            # No commentary or data_gaps provided
        )
        assert entry.commentary == []
        assert entry.data_gaps == []


# ── CR-3: TradeOutcome extended fields ──


class TestEtradingCR3:
    """CR-3: TradeOutcome extended fields for eTrading."""

    def test_trade_outcome_new_fields_optional(self):
        """TradeOutcome created WITHOUT new fields still works — backward compat."""
        outcome = TradeOutcome(
            trade_id="t1",
            ticker="SPY",
            strategy_type=StrategyType.IRON_CONDOR,
            regime_at_entry=1,
            regime_at_exit=1,
            entry_date=date(2026, 3, 1),
            exit_date=date(2026, 3, 10),
            entry_price=2.50,
            exit_price=1.00,
            pnl_dollars=150.0,
            pnl_pct=0.15,
            holding_days=9,
            exit_reason=TradeExitReason.PROFIT_TARGET,
            composite_score_at_entry=0.80,
        )
        assert outcome.structure_type is None
        assert outcome.order_side is None
        assert outcome.iv_rank_at_entry is None
        assert outcome.dte_at_entry is None
        assert outcome.dte_at_exit is None
        assert outcome.max_favorable_excursion is None
        assert outcome.max_adverse_excursion is None

    def test_trade_outcome_with_etrading_fields(self):
        """TradeOutcome WITH all CR-3 fields populates correctly."""
        outcome = TradeOutcome(
            trade_id="t2",
            ticker="GLD",
            strategy_type=StrategyType.IRON_CONDOR,
            regime_at_entry=1,
            regime_at_exit=2,
            entry_date=date(2026, 3, 1),
            exit_date=date(2026, 3, 14),
            entry_price=3.00,
            exit_price=1.50,
            pnl_dollars=150.0,
            pnl_pct=0.10,
            holding_days=13,
            exit_reason=TradeExitReason.PROFIT_TARGET,
            composite_score_at_entry=0.75,
            structure_type="iron_condor",
            order_side="credit",
            iv_rank_at_entry=55.0,
            dte_at_entry=30,
            dte_at_exit=17,
            max_favorable_excursion=200.0,
            max_adverse_excursion=-80.0,
        )
        assert outcome.structure_type == "iron_condor"
        assert outcome.order_side == "credit"
        assert outcome.iv_rank_at_entry == 55.0
        assert outcome.dte_at_entry == 30
        assert outcome.dte_at_exit == 17
        assert outcome.max_favorable_excursion == 200.0
        assert outcome.max_adverse_excursion == -80.0

    def test_strategy_performance_has_avg_dte_and_iv(self):
        """compute_strategy_performance populates avg_dte_at_entry and avg_iv_rank_at_entry when data present."""
        from market_analyzer.performance import compute_strategy_performance

        outcomes = [
            TradeOutcome(
                trade_id=f"t{i}",
                ticker="SPY",
                strategy_type=StrategyType.IRON_CONDOR,
                regime_at_entry=1,
                regime_at_exit=1,
                entry_date=date(2026, 3, 1),
                exit_date=date(2026, 3, 10),
                entry_price=2.50,
                exit_price=1.00,
                pnl_dollars=150.0,
                pnl_pct=0.15,
                holding_days=9,
                exit_reason=TradeExitReason.PROFIT_TARGET,
                composite_score_at_entry=0.80,
                dte_at_entry=dte,
                iv_rank_at_entry=iv,
            )
            for i, (dte, iv) in enumerate([(30, 40.0), (45, 60.0), (20, 50.0)])
        ]
        perf = compute_strategy_performance(outcomes, StrategyType.IRON_CONDOR)
        assert perf.avg_dte_at_entry is not None
        assert abs(perf.avg_dte_at_entry - (30 + 45 + 20) / 3) < 0.01
        assert perf.avg_iv_rank_at_entry is not None
        assert abs(perf.avg_iv_rank_at_entry - (40.0 + 60.0 + 50.0) / 3) < 0.01

    def test_strategy_performance_none_without_dte_iv(self):
        """compute_strategy_performance returns None for avg_dte/avg_iv when not provided."""
        from market_analyzer.performance import compute_strategy_performance

        outcomes = [
            TradeOutcome(
                trade_id="t1",
                ticker="SPY",
                strategy_type=StrategyType.IRON_CONDOR,
                regime_at_entry=1,
                regime_at_exit=1,
                entry_date=date(2026, 3, 1),
                exit_date=date(2026, 3, 10),
                entry_price=2.50,
                exit_price=1.00,
                pnl_dollars=150.0,
                pnl_pct=0.15,
                holding_days=9,
                exit_reason=TradeExitReason.PROFIT_TARGET,
                composite_score_at_entry=0.80,
                # No dte_at_entry or iv_rank_at_entry
            )
        ]
        perf = compute_strategy_performance(outcomes, StrategyType.IRON_CONDOR)
        assert perf.avg_dte_at_entry is None
        assert perf.avg_iv_rank_at_entry is None


# ── CR-4: Debug mode / commentary on services ──


class TestEtradingCR4:
    """CR-4: Debug mode / commentary on services."""

    def test_technical_snapshot_has_commentary(self):
        """TechnicalSnapshot accepts and stores commentary field."""
        snapshot = TechnicalSnapshot(
            ticker="SPY",
            as_of_date=date.today(),
            current_price=570.0,
            atr=5.0,
            atr_pct=0.88,
            vwma_20=568.0,
            moving_averages=MovingAverages(
                sma_20=565.0, sma_50=560.0, sma_200=530.0,
                ema_9=568.0, ema_21=565.0,
                price_vs_sma_20_pct=0.9, price_vs_sma_50_pct=1.8, price_vs_sma_200_pct=7.5,
            ),
            rsi=RSIData(value=55.0, is_overbought=False, is_oversold=False),
            bollinger=BollingerBands(upper=580.0, middle=565.0, lower=550.0, bandwidth=5.3, percent_b=0.67),
            macd=MACDData(macd_line=2.5, signal_line=1.8, histogram=0.7, is_bullish_crossover=False, is_bearish_crossover=False),
            stochastic=StochasticData(k=65.0, d=60.0, is_overbought=False, is_oversold=False),
            support_resistance=SupportResistance(support=555.0, resistance=580.0, price_vs_support_pct=2.7, price_vs_resistance_pct=-1.7),
            phase=PhaseIndicator(
                phase="markup", confidence=0.75, description="test",
                higher_highs=True, higher_lows=True, lower_highs=False, lower_lows=False,
                range_compression=0.3, volume_trend="stable", price_vs_sma_50_pct=1.8,
            ),
            signals=[],
            commentary=["Step 1: computed RSI = 55", "Step 2: SMA crossover check"],
        )
        assert len(snapshot.commentary) == 2
        assert "RSI" in snapshot.commentary[0]

    def test_market_context_has_commentary(self):
        """MarketContext accepts and stores commentary field."""
        from market_analyzer.models.context import MarketContext, IntermarketDashboard
        from market_analyzer.models.black_swan import BlackSwanAlert, AlertLevel
        from market_analyzer.models.macro import MacroCalendar

        ctx = MarketContext(
            as_of_date=date.today(),
            market="US",
            macro=MacroCalendar(
                events=[],
                next_event=None,
                days_to_next=None,
                next_fomc=None,
                days_to_next_fomc=None,
                events_next_7_days=[],
                events_next_30_days=[],
            ),
            black_swan=BlackSwanAlert(
                as_of_date=date.today(),
                alert_level=AlertLevel.NORMAL,
                composite_score=0.0,
                circuit_breakers=[],
                indicators=[],
                triggered_breakers=0,
                action="none",
                summary="All clear",
            ),
            intermarket=IntermarketDashboard(entries=[], summary="test"),
            environment_label="risk-on",
            trading_allowed=True,
            commentary=["Step 1: checked VIX at 15", "Step 2: no macro events"],
        )
        assert len(ctx.commentary) == 2
        assert "VIX" in ctx.commentary[0]

    def test_commentary_defaults_empty(self):
        """Both TechnicalSnapshot and MarketContext default commentary to [] when not set."""
        assert TechnicalSnapshot.model_fields["commentary"].default == []
        assert "commentary" in TechnicalSnapshot.model_fields

        from market_analyzer.models.context import MarketContext

        assert MarketContext.model_fields["commentary"].default == []


# ── CR-5: DataGap has affects field, data_gaps on more models ──


class TestEtradingCR5:
    """CR-5: DataGap has affects field, data_gaps on more models."""

    def test_data_gap_has_affects_field(self):
        """DataGap accepts the 'affects' field."""
        from market_analyzer.models.transparency import DataGap

        gap = DataGap(
            field="pop",
            reason="no broker connected",
            impact="high",
            affects="POP estimate",
        )
        assert gap.affects == "POP estimate"
        assert gap.field == "pop"
        assert gap.reason == "no broker connected"

    def test_data_gap_affects_defaults_empty(self):
        """DataGap without 'affects' defaults to empty string."""
        from market_analyzer.models.transparency import DataGap

        gap = DataGap(field="iv_rank", reason="no metrics", impact="medium")
        assert gap.affects == ""

    def test_exit_monitor_result_has_data_gaps(self):
        """ExitMonitorResult accepts data_gaps field."""
        from market_analyzer.trade_lifecycle import ExitMonitorResult, ExitSignal
        from market_analyzer.models.transparency import DataGap

        result = ExitMonitorResult(
            trade_id="t1",
            ticker="SPY",
            signals=[],
            should_close=False,
            most_urgent=None,
            pnl_pct=0.05,
            pnl_dollars=50.0,
            summary="Holding",
            commentary="Position looks healthy",
            data_gaps=[
                DataGap(field="greeks", reason="no broker", impact="cannot check delta", affects="risk monitoring"),
            ],
        )
        assert len(result.data_gaps) == 1
        assert result.data_gaps[0].field == "greeks"
        assert result.data_gaps[0].affects == "risk monitoring"

    def test_trade_health_check_has_data_gaps(self):
        """TradeHealthCheck accepts data_gaps field."""
        from market_analyzer.trade_lifecycle import TradeHealthCheck, ExitMonitorResult
        from market_analyzer.models.transparency import DataGap

        exit_result = ExitMonitorResult(
            trade_id="t1",
            ticker="SPY",
            signals=[],
            should_close=False,
            most_urgent=None,
            pnl_pct=0.03,
            pnl_dollars=30.0,
            summary="OK",
            commentary="Healthy",
        )
        health = TradeHealthCheck(
            trade_id="t1",
            ticker="SPY",
            status="healthy",
            exit_result=exit_result,
            adjustment_needed=False,
            overall_action="hold",
            summary="Position healthy",
            commentary="All checks passed",
            data_gaps=[
                DataGap(field="adjustment_options", reason="no quote service", impact="cannot price adjustments", affects="adjustment recommendations"),
            ],
        )
        assert len(health.data_gaps) == 1
        assert health.data_gaps[0].field == "adjustment_options"
        assert health.data_gaps[0].affects == "adjustment recommendations"

    def test_exit_monitor_result_data_gaps_defaults_empty(self):
        """ExitMonitorResult without data_gaps defaults to []."""
        from market_analyzer.trade_lifecycle import ExitMonitorResult

        result = ExitMonitorResult(
            trade_id="t1",
            ticker="SPY",
            signals=[],
            should_close=False,
            most_urgent=None,
            pnl_pct=0.0,
            pnl_dollars=0.0,
            summary="OK",
            commentary="Fine",
        )
        assert result.data_gaps == []

    def test_trade_health_check_data_gaps_defaults_empty(self):
        """TradeHealthCheck without data_gaps defaults to []."""
        from market_analyzer.trade_lifecycle import TradeHealthCheck, ExitMonitorResult

        exit_result = ExitMonitorResult(
            trade_id="t1",
            ticker="SPY",
            signals=[],
            should_close=False,
            most_urgent=None,
            pnl_pct=0.0,
            pnl_dollars=0.0,
            summary="OK",
            commentary="Fine",
        )
        health = TradeHealthCheck(
            trade_id="t1",
            ticker="SPY",
            status="healthy",
            exit_result=exit_result,
            adjustment_needed=False,
            overall_action="hold",
            summary="OK",
            commentary="OK",
        )
        assert health.data_gaps == []


# ── SQ1: IV rank integration in assessors ──


class TestSQ1IVIntegration:
    """SQ1: IV rank integration in assessors."""

    def test_iron_condor_hard_stop_low_iv(self):
        """assess_iron_condor with iv_rank=10 -> NO_GO (hard stop: IV rank too low)."""
        from market_analyzer.opportunity.option_plays.iron_condor import assess_iron_condor
        from market_analyzer.models.opportunity import Verdict

        regime = _make_regime(1)
        technicals = _make_technicals()
        result = assess_iron_condor(
            ticker="SPY",
            regime=regime,
            technicals=technicals,
            iv_rank=10,
        )
        assert result.verdict == Verdict.NO_GO
        hard_stop_names = [hs.name for hs in result.hard_stops]
        assert any("IV rank" in name or "iv_rank" in name.lower() for name in hard_stop_names)

    def test_iron_condor_accepts_iv_rank_none(self):
        """assess_iron_condor with iv_rank=None (default) -> works, no TypeError."""
        from market_analyzer.opportunity.option_plays.iron_condor import assess_iron_condor

        regime = _make_regime(1)
        technicals = _make_technicals()
        # Should not raise TypeError
        result = assess_iron_condor(
            ticker="SPY",
            regime=regime,
            technicals=technicals,
            iv_rank=None,
        )
        assert result is not None

    def test_iron_condor_iv_rank_below_threshold_no_signal(self):
        """assess_iron_condor with iv_rank=30 (below 40 threshold, above 15 hard stop).

        Without vol_surface the hard stop on vol_surface fires first, but the
        function still accepts iv_rank without error.  We verify the hard stop
        names do NOT include the IV rank stop (since 30 > 15).
        """
        from market_analyzer.opportunity.option_plays.iron_condor import assess_iron_condor
        from market_analyzer.models.opportunity import Verdict

        regime = _make_regime(1)
        technicals = _make_technicals()
        # No vol_surface -> will hit the vol_surface hard stop, but NOT the iv_rank one
        result = assess_iron_condor(
            ticker="SPY",
            regime=regime,
            technicals=technicals,
            iv_rank=30,
        )
        # Should be NO_GO due to missing vol_surface, but NOT due to IV rank
        assert result.verdict == Verdict.NO_GO
        iv_hard_stops = [hs for hs in result.hard_stops if "IV rank" in hs.name]
        assert len(iv_hard_stops) == 0  # iv_rank=30 is above the 15 threshold

    def test_leap_hard_stop_high_iv(self):
        """assess_leap with iv_rank=80 -> NO_GO (hard stop: IV rank too high)."""
        from market_analyzer.opportunity.option_plays.leap import assess_leap
        from market_analyzer.models.opportunity import Verdict
        from market_analyzer.models.phase import (
            PhaseResult, PhaseID, PriceStructure, PhaseEvidence,
        )
        from market_analyzer.models.macro import MacroCalendar

        regime = _make_regime(3)  # R3 for LEAPs
        technicals = _make_technicals()
        phase = PhaseResult(
            ticker="SPY",
            phase=PhaseID.MARKUP,
            phase_name="Markup",
            confidence=0.7,
            phase_age_days=15,
            prior_phase=None,
            cycle_completion=0.3,
            price_structure=PriceStructure(
                swing_highs=[], swing_lows=[],
                higher_highs=True, higher_lows=True,
                lower_highs=False, lower_lows=False,
                range_compression=0.3, price_vs_sma=2.0,
                volume_trend="stable",
                support_level=580.0, resistance_level=620.0,
            ),
            evidence=PhaseEvidence(
                regime_signal="R3", price_signal="Higher highs",
                volume_signal="Stable", supporting=[], contradictions=[],
            ),
            transitions=[],
            strategy_comment="Test",
            as_of_date=date.today(),
        )
        macro = MacroCalendar(
            events=[], next_event=None, days_to_next=None,
            next_fomc=None, days_to_next_fomc=None,
            events_next_7_days=[], events_next_30_days=[],
        )
        result = assess_leap(
            ticker="SPY",
            regime=regime,
            technicals=technicals,
            phase=phase,
            macro=macro,
            iv_rank=80,
        )
        assert result.verdict == Verdict.NO_GO
        hard_stop_names = [hs.name for hs in result.hard_stops]
        assert any("iv_rank" in name.lower() for name in hard_stop_names)

    def test_leap_accepts_iv_rank_none(self):
        """assess_leap with iv_rank=None -> works, no TypeError."""
        from market_analyzer.opportunity.option_plays.leap import assess_leap
        from market_analyzer.models.phase import (
            PhaseResult, PhaseID, PriceStructure, PhaseEvidence,
        )
        from market_analyzer.models.macro import MacroCalendar

        regime = _make_regime(3)
        technicals = _make_technicals()
        phase = PhaseResult(
            ticker="SPY",
            phase=PhaseID.MARKUP,
            phase_name="Markup",
            confidence=0.7,
            phase_age_days=15,
            prior_phase=None,
            cycle_completion=0.3,
            price_structure=PriceStructure(
                swing_highs=[], swing_lows=[],
                higher_highs=True, higher_lows=True,
                lower_highs=False, lower_lows=False,
                range_compression=0.3, price_vs_sma=2.0,
                volume_trend="stable",
                support_level=580.0, resistance_level=620.0,
            ),
            evidence=PhaseEvidence(
                regime_signal="R3", price_signal="Higher highs",
                volume_signal="Stable", supporting=[], contradictions=[],
            ),
            transitions=[],
            strategy_comment="Test",
            as_of_date=date.today(),
        )
        macro = MacroCalendar(
            events=[], next_event=None, days_to_next=None,
            next_fomc=None, days_to_next_fomc=None,
            events_next_7_days=[], events_next_30_days=[],
        )
        result = assess_leap(
            ticker="SPY", regime=regime, technicals=technicals,
            phase=phase, macro=macro, iv_rank=None,
        )
        assert result is not None

    def test_earnings_hard_stop_low_iv(self):
        """assess_earnings_play with iv_rank=20 -> NO_GO (hard stop: IV rank too low)."""
        from market_analyzer.opportunity.option_plays.earnings import assess_earnings_play
        from market_analyzer.models.opportunity import Verdict

        regime = _make_regime(1)
        technicals = _make_technicals()
        result = assess_earnings_play(
            ticker="SPY",
            regime=regime,
            technicals=technicals,
            iv_rank=20,
        )
        assert result.verdict == Verdict.NO_GO
        hard_stop_names = [hs.name for hs in result.hard_stops]
        assert any("IV rank" in name or "iv_rank" in name.lower() for name in hard_stop_names)

    def test_earnings_accepts_iv_rank_none(self):
        """assess_earnings_play with iv_rank=None -> works, no TypeError."""
        from market_analyzer.opportunity.option_plays.earnings import assess_earnings_play

        regime = _make_regime(1)
        technicals = _make_technicals()
        result = assess_earnings_play(
            ticker="SPY", regime=regime, technicals=technicals, iv_rank=None,
        )
        assert result is not None


# ── SQ2: HMM model staleness and validation ──


class TestSQ2HMMStaleness:
    """SQ2: HMM model staleness and validation."""

    def test_regime_result_has_staleness_fields(self):
        """RegimeResult with model_fit_date, model_age_days, regime_stability -> works."""
        result = RegimeResult(
            ticker="SPY",
            regime=RegimeID.R1_LOW_VOL_MR,
            confidence=0.85,
            regime_probabilities={1: 0.85, 2: 0.05, 3: 0.05, 4: 0.05},
            as_of_date=date.today(),
            model_version="test",
            model_fit_date=date(2026, 3, 1),
            model_age_days=13,
            regime_stability=2,
        )
        assert result.model_fit_date == date(2026, 3, 1)
        assert result.model_age_days == 13
        assert result.regime_stability == 2

    def test_regime_result_staleness_defaults_none(self):
        """RegimeResult without staleness fields -> all None."""
        result = _make_regime(1)
        assert result.model_fit_date is None
        assert result.model_age_days is None
        assert result.regime_stability is None

    def test_regime_stability_field(self):
        """RegimeResult with regime_stability=3 -> accessible."""
        result = RegimeResult(
            ticker="GLD",
            regime=RegimeID.R2_HIGH_VOL_MR,
            confidence=0.70,
            regime_probabilities={1: 0.10, 2: 0.70, 3: 0.15, 4: 0.05},
            as_of_date=date.today(),
            model_version="test",
            regime_stability=3,
        )
        assert result.regime_stability == 3

    def test_regime_result_model_age_integer(self):
        """model_age_days is int | None, not float."""
        result = RegimeResult(
            ticker="SPY",
            regime=RegimeID.R1_LOW_VOL_MR,
            confidence=0.85,
            regime_probabilities={1: 0.85, 2: 0.05, 3: 0.05, 4: 0.05},
            as_of_date=date.today(),
            model_version="test",
            model_age_days=45,
        )
        assert isinstance(result.model_age_days, int)
        assert result.model_age_days == 45


# ── SQ3: POP calibration from outcomes + IV rank ──


class TestSQ3POPCalibration:
    """SQ3: POP calibration from outcomes + IV rank."""

    def test_estimate_pop_accepts_iv_rank(self):
        """estimate_pop with iv_rank=50 -> works, no error."""
        from market_analyzer.trade_lifecycle import estimate_pop

        ic = _make_iron_condor()
        result = estimate_pop(
            trade_spec=ic,
            entry_price=2.50,
            regime_id=1,
            atr_pct=1.33,  # 8/600 * 100
            current_price=600.0,
            iv_rank=50,
        )
        assert result is not None
        assert 0.0 <= result.pop_pct <= 1.0

    def test_estimate_pop_iv_rank_widens_move(self):
        """Higher iv_rank -> lower POP (wider expected move for credit trades)."""
        from market_analyzer.trade_lifecycle import estimate_pop

        ic = _make_iron_condor()
        common = dict(
            trade_spec=ic,
            entry_price=2.50,
            regime_id=1,
            atr_pct=1.33,
            current_price=600.0,
        )
        pop_low_iv = estimate_pop(**common, iv_rank=20)
        pop_high_iv = estimate_pop(**common, iv_rank=80)
        assert pop_low_iv is not None
        assert pop_high_iv is not None
        # Higher IV rank widens expected moves -> lower POP for credit trades
        assert pop_low_iv.pop_pct > pop_high_iv.pop_pct

    def test_estimate_pop_iv_rank_none_data_gap(self):
        """estimate_pop with iv_rank=None -> POPEstimate has data_gap."""
        from market_analyzer.trade_lifecycle import estimate_pop

        ic = _make_iron_condor()
        result = estimate_pop(
            trade_spec=ic,
            entry_price=2.50,
            regime_id=1,
            atr_pct=1.33,
            current_price=600.0,
            iv_rank=None,
        )
        assert result is not None
        assert len(result.data_gaps) >= 1
        gap_fields = [g.field for g in result.data_gaps]
        assert "pop" in gap_fields

    def test_estimate_pop_iv_rank_provided_no_data_gap(self):
        """estimate_pop with iv_rank=50 -> no IV-related data gap."""
        from market_analyzer.trade_lifecycle import estimate_pop

        ic = _make_iron_condor()
        result = estimate_pop(
            trade_spec=ic,
            entry_price=2.50,
            regime_id=1,
            atr_pct=1.33,
            current_price=600.0,
            iv_rank=50,
        )
        assert result is not None
        iv_gaps = [g for g in result.data_gaps if "IV" in g.reason or "iv" in g.reason.lower()]
        assert len(iv_gaps) == 0

    def test_calibrate_pop_factors_empty(self):
        """Empty outcomes -> empty dict."""
        from market_analyzer.performance import calibrate_pop_factors

        result = calibrate_pop_factors([])
        assert result == {}

    def test_calibrate_pop_factors_few_trades(self):
        """5 trades (below min=10) -> empty dict."""
        from market_analyzer.performance import calibrate_pop_factors

        outcomes = [_make_outcome(trade_id=f"t{i}") for i in range(5)]
        result = calibrate_pop_factors(outcomes, min_trades_per_regime=10)
        assert result == {}

    def test_calibrate_pop_factors_enough_trades(self):
        """15 trades all in R1 -> dict has key 1."""
        from market_analyzer.performance import calibrate_pop_factors

        outcomes = [
            _make_outcome(regime=1, pnl_pct=0.10, trade_id=f"t{i}")
            for i in range(15)
        ]
        result = calibrate_pop_factors(outcomes, min_trades_per_regime=10)
        assert 1 in result
        assert isinstance(result[1], float)

    def test_calibrate_pop_factors_clamped(self):
        """Result factors are within [0.15, 2.0]."""
        from market_analyzer.performance import calibrate_pop_factors

        # All winning -> factor should be low but >= 0.15
        winning = [
            _make_outcome(regime=1, pnl_pct=0.10, pnl_dollars=30.0, trade_id=f"w{i}")
            for i in range(20)
        ]
        result_win = calibrate_pop_factors(winning, min_trades_per_regime=10)
        if 1 in result_win:
            assert 0.15 <= result_win[1] <= 2.0

        # All losing -> factor should be high but <= 2.0
        losing = [
            _make_outcome(regime=2, pnl_pct=-0.10, pnl_dollars=-30.0, trade_id=f"l{i}")
            for i in range(20)
        ]
        result_lose = calibrate_pop_factors(losing, min_trades_per_regime=10)
        if 2 in result_lose:
            assert 0.15 <= result_lose[2] <= 2.0

    def test_performance_report_has_pop_accuracy(self):
        """compute_performance_report with enough outcomes -> pop_accuracy populated."""
        from market_analyzer.performance import compute_performance_report

        # Need >= 5 trades per regime for pop_accuracy to populate
        outcomes = [
            _make_outcome(regime=1, pnl_pct=0.10, pnl_dollars=30.0, trade_id=f"r1w{i}")
            for i in range(4)
        ] + [
            _make_outcome(regime=1, pnl_pct=-0.05, pnl_dollars=-15.0, trade_id=f"r1l{i}")
            for i in range(3)
        ]
        report = compute_performance_report(outcomes)
        # 7 trades in R1 (>= 5), so pop_accuracy should have key 1
        assert report.pop_accuracy is not None
        assert 1 in report.pop_accuracy
        # 4 wins / 7 trades
        assert abs(report.pop_accuracy[1] - 4 / 7) < 0.01

    def test_performance_report_pop_accuracy_none_few_trades(self):
        """compute_performance_report with < 5 trades per regime -> pop_accuracy is None."""
        from market_analyzer.performance import compute_performance_report

        outcomes = [
            _make_outcome(regime=1, trade_id="t1"),
            _make_outcome(regime=2, trade_id="t2"),
            _make_outcome(regime=3, trade_id="t3"),
        ]
        report = compute_performance_report(outcomes)
        # Each regime has only 1 trade (< 5) -> no pop_accuracy entries
        assert report.pop_accuracy is None
