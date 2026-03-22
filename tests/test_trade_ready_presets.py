"""Integration tests for trade-ready simulation presets.

Verifies that create_ideal_income(), create_post_crash_recovery(),
create_wheel_opportunity(), and create_india_trading() produce option
chains with sufficient credits to pass the daily validation gates.

These tests run against purely simulated data — no network calls, no broker.
"""
from __future__ import annotations

import pytest
from datetime import date, timedelta

from income_desk.adapters.simulated import (
    SimulatedMarketData,
    SimulatedMetrics,
    create_ideal_income,
    create_post_crash_recovery,
    create_wheel_opportunity,
    create_india_trading,
    _generate_option_quote,
    _get_strike_step,
    _round_to_step,
)
from income_desk.models.opportunity import (
    LegAction,
    LegSpec,
    StructureType,
    OrderSide,
    TradeSpec,
)


# ── Shared helpers ────────────────────────────────────────────────────────────


def _make_ic_legs(ticker: str, price: float, wing_steps: int = 1) -> list[LegSpec]:
    """Build a simple iron condor centred on *price*.

    Short strikes at ~5% OTM, long strikes ``wing_steps`` strike-steps further out.
    Uses 1 step by default — for SPY at $560 this is a 10-point wing, which gives
    realistic ROC relative to wing width.
    """
    step = _get_strike_step(price)
    put_short = _round_to_step(price * 0.95, step)
    put_long = put_short - wing_steps * step
    call_short = _round_to_step(price * 1.05, step)
    call_long = call_short + wing_steps * step
    exp = date.today() + timedelta(days=35)

    return [
        LegSpec(
            role="long_put", action=LegAction.BUY_TO_OPEN, option_type="put",
            strike=put_long, strike_label=f"BTO {put_long:.0f}P",
            expiration=exp, days_to_expiry=35, atm_iv_at_expiry=0.0,
        ),
        LegSpec(
            role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
            strike=put_short, strike_label=f"STO {put_short:.0f}P",
            expiration=exp, days_to_expiry=35, atm_iv_at_expiry=0.0,
        ),
        LegSpec(
            role="short_call", action=LegAction.SELL_TO_OPEN, option_type="call",
            strike=call_short, strike_label=f"STO {call_short:.0f}C",
            expiration=exp, days_to_expiry=35, atm_iv_at_expiry=0.0,
        ),
        LegSpec(
            role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call",
            strike=call_long, strike_label=f"BTO {call_long:.0f}C",
            expiration=exp, days_to_expiry=35, atm_iv_at_expiry=0.0,
        ),
    ]


def _build_ic_trade_spec(ticker: str, price: float, wing_steps: int = 1) -> TradeSpec:
    """Build a minimal IC TradeSpec for validation testing."""
    step = _get_strike_step(price)
    wing = wing_steps * step
    legs = _make_ic_legs(ticker, price, wing_steps)
    exp = date.today() + timedelta(days=35)
    return TradeSpec(
        ticker=ticker,
        legs=legs,
        underlying_price=price,
        target_dte=35,
        target_expiration=exp,
        wing_width_points=wing,
        structure_type=StructureType.IRON_CONDOR,
        order_side=OrderSide.CREDIT,
        profit_target_pct=0.50,
        stop_loss_pct=2.0,
        exit_dte=21,
        spec_rationale="Test IC for validation gate testing",
    )


def _compute_ic_credit(sim: SimulatedMarketData, ticker: str) -> float:
    """Return the net credit (per share) for a test IC on *ticker*."""
    price = sim.get_underlying_price(ticker)
    assert price is not None and price > 0, f"No price for {ticker}"
    legs = _make_ic_legs(ticker, price)
    quotes = sim.get_quotes(legs, ticker=ticker)

    credit = 0.0
    for leg, q in zip(legs, quotes):
        if q is None:
            continue
        if leg.action == LegAction.SELL_TO_OPEN:
            credit += q.mid
        else:
            credit -= q.mid
    return round(credit, 2)


# ── IV-boost formula unit tests ───────────────────────────────────────────────


class TestIVBoostFormula:
    """The iv_boost multiplier in _generate_option_quote scales time value with IV."""

    def test_higher_iv_produces_higher_mid_price(self):
        exp = date.today() + timedelta(days=35)
        low_iv = _generate_option_quote(
            ticker="SPY", strike=560.0, option_type="call",
            expiration=exp, dte=35, underlying_price=560.0, iv=0.20,
        )
        high_iv = _generate_option_quote(
            ticker="SPY", strike=560.0, option_type="call",
            expiration=exp, dte=35, underlying_price=560.0, iv=0.30,
        )
        assert high_iv.mid > low_iv.mid, (
            f"Higher IV should produce higher ATM premium: {high_iv.mid} vs {low_iv.mid}"
        )

    def test_30pct_iv_materially_richer_than_20pct(self):
        """IV=30% should produce at least 30% more ATM premium than IV=20%."""
        exp = date.today() + timedelta(days=35)
        q20 = _generate_option_quote(
            ticker="SPY", strike=560.0, option_type="call",
            expiration=exp, dte=35, underlying_price=560.0, iv=0.20,
        )
        q30 = _generate_option_quote(
            ticker="SPY", strike=560.0, option_type="call",
            expiration=exp, dte=35, underlying_price=560.0, iv=0.30,
        )
        # iv_boost at 30%: 1 + (0.30-0.20)*2 = 1.20; plus the direct IV ratio 0.30/0.20 = 1.5x
        # Combined: 1.5 * 1.2 = 1.8x → well above 1.3x threshold
        assert q30.mid / q20.mid > 1.3, (
            f"30% IV option should be materially richer than 20% IV: {q30.mid:.2f} vs {q20.mid:.2f}"
        )

    def test_atm_put_at_26pct_iv_above_2_dollars(self):
        """At IV=26% (income preset level), ATM 35-DTE time value should be > $2."""
        exp = date.today() + timedelta(days=35)
        q = _generate_option_quote(
            ticker="SPY", strike=560.0, option_type="put",
            expiration=exp, dte=35, underlying_price=560.0, iv=0.26,
        )
        assert q.mid >= 2.00, f"ATM put should be >= $2 at IV=26%: {q.mid:.2f}"

    def test_iv_at_20pct_baseline_unchanged(self):
        """IV=20% is the baseline — iv_boost factor is 1.0 (no change)."""
        exp = date.today() + timedelta(days=35)
        # Verify bid > 0 and chain is still generated properly
        q = _generate_option_quote(
            ticker="SPY", strike=560.0, option_type="put",
            expiration=exp, dte=35, underlying_price=560.0, iv=0.20,
        )
        assert q.bid > 0 and q.ask > q.bid and q.mid > 0


# ── New preset structure tests ─────────────────────────────────────────────────


class TestNewPresetStructure:
    """Smoke tests — verify all four new presets instantiate and produce chains."""

    @pytest.mark.parametrize("factory,expected_tickers", [
        (create_ideal_income, ["SPY", "QQQ", "IWM", "GLD", "TLT"]),
        (create_post_crash_recovery, ["SPY", "QQQ", "IWM", "GLD", "TLT"]),
        (create_wheel_opportunity, ["SPY", "AAPL", "MSFT", "AMD", "IWM"]),
        (create_india_trading, ["NIFTY", "BANKNIFTY", "FINNIFTY", "RELIANCE", "TCS"]),
    ])
    def test_all_tickers_have_prices(self, factory, expected_tickers):
        sim = factory()
        for t in expected_tickers:
            price = sim.get_underlying_price(t)
            assert price is not None and price > 0, (
                f"{t} missing price in {factory.__name__}"
            )

    @pytest.mark.parametrize("factory,ticker", [
        (create_ideal_income, "SPY"),
        (create_post_crash_recovery, "SPY"),
        (create_wheel_opportunity, "SPY"),
        (create_india_trading, "NIFTY"),
        (create_india_trading, "BANKNIFTY"),
    ])
    def test_chains_are_non_empty(self, factory, ticker):
        sim = factory()
        chain = sim.get_option_chain(ticker)
        assert len(chain) > 0, f"{factory.__name__}/{ticker} produced empty chain"

    def test_recovery_has_higher_iv_than_income(self):
        income = create_ideal_income()
        recovery = create_post_crash_recovery()
        assert recovery._tickers["SPY"]["iv"] > income._tickers["SPY"]["iv"]

    def test_income_iv_rank_in_range(self):
        income = create_ideal_income()
        assert 45 <= income._tickers["SPY"]["iv_rank"] <= 70

    def test_recovery_iv_rank_above_70(self):
        recovery = create_post_crash_recovery()
        assert recovery._tickers["SPY"]["iv_rank"] >= 70

    def test_wheel_stocks_have_elevated_iv(self):
        wheel = create_wheel_opportunity()
        assert wheel._tickers["AMD"]["iv"] >= 0.40
        assert wheel._tickers["AAPL"]["iv"] >= 0.28

    def test_simulated_metrics_for_income_preset(self):
        sim = create_ideal_income()
        metrics_provider = SimulatedMetrics(sim)
        metrics = metrics_provider.get_metrics(["SPY", "QQQ"])
        assert "SPY" in metrics
        assert metrics["SPY"].iv_rank == 55
        assert metrics["QQQ"].iv_rank == 60

    def test_all_presets_produce_chains(self):
        """Every new preset produces non-empty option chains for the first two tickers."""
        for name, factory in [
            ("income", create_ideal_income),
            ("recovery", create_post_crash_recovery),
            ("wheel", create_wheel_opportunity),
            ("india_trading", create_india_trading),
        ]:
            sim = factory()
            tickers = list(sim._tickers.keys())[:2]
            for ticker in tickers:
                chain = sim.get_option_chain(ticker)
                assert len(chain) > 0, f"{name}/{ticker} produced empty chain"


# ── Credit levels ──────────────────────────────────────────────────────────────


class TestPresetCreditLevels:
    """Verify IC credits are above the $0.50 minimum gate for income presets."""

    def test_ideal_income_spy_credit_above_minimum(self):
        sim = create_ideal_income()
        credit = _compute_ic_credit(sim, "SPY")
        assert credit >= 0.50, (
            f"create_ideal_income() SPY IC credit too low: ${credit:.2f} "
            f"(need >= $0.50 for minimum_credit gate)"
        )

    def test_ideal_income_qqq_credit_above_minimum(self):
        sim = create_ideal_income()
        credit = _compute_ic_credit(sim, "QQQ")
        assert credit >= 0.50, f"QQQ credit too low: ${credit:.2f}"

    def test_recovery_spy_credit_above_1_dollar(self):
        """Post-crash recovery should produce very rich credits (>= $1.00)."""
        sim = create_post_crash_recovery()
        credit = _compute_ic_credit(sim, "SPY")
        assert credit >= 1.00, (
            f"create_post_crash_recovery() SPY credit should be rich: ${credit:.2f}"
        )

    def test_wheel_spy_credit_above_minimum(self):
        sim = create_wheel_opportunity()
        credit = _compute_ic_credit(sim, "SPY")
        assert credit >= 0.50, f"Wheel SPY credit too low: ${credit:.2f}"

    def test_income_higher_credits_than_calm(self):
        """Elevated-IV income preset should produce richer credits than low-IV calm."""
        from income_desk.adapters.simulated import create_calm_market
        calm = create_calm_market()
        income = create_ideal_income()

        calm_credit = _compute_ic_credit(calm, "SPY")
        income_credit = _compute_ic_credit(income, "SPY")
        assert income_credit > calm_credit, (
            f"Income preset (${income_credit:.2f}) should produce higher credits "
            f"than calm preset (${calm_credit:.2f})"
        )

    def test_recovery_higher_credits_than_income(self):
        """Post-crash recovery (IV 35-42%) should beat income preset (IV 26-30%)."""
        income = create_ideal_income()
        recovery = create_post_crash_recovery()

        income_credit = _compute_ic_credit(income, "SPY")
        recovery_credit = _compute_ic_credit(recovery, "SPY")
        assert recovery_credit > income_credit, (
            f"Recovery preset (${recovery_credit:.2f}) should produce higher credits "
            f"than income preset (${income_credit:.2f})"
        )


# ── Validation gate integration ────────────────────────────────────────────────


class TestValidationGates:
    """Verify trades built from income presets pass run_daily_checks().

    Uses pure-simulated data — no network calls.
    """

    def test_ideal_income_minimum_credit_gate_passes(self):
        """The minimum_credit pre-check must pass for income preset."""
        from income_desk.validation.daily_readiness import run_daily_checks
        from income_desk.validation.models import Severity

        sim = create_ideal_income()
        price = sim.get_underlying_price("SPY")
        trade_spec = _build_ic_trade_spec("SPY", price)
        credit = _compute_ic_credit(sim, "SPY")

        assert credit >= 0.50, (
            f"Preset credit ${credit:.2f} below $0.50 — preset IV needs adjustment"
        )

        rpt = run_daily_checks(
            ticker="SPY",
            trade_spec=trade_spec,
            entry_credit=credit,
            regime_id=1,  # R1 — ideal for income
            atr_pct=1.1,
            current_price=price,
            avg_bid_ask_spread_pct=0.5,
            dte=35,
            rsi=50.0,
            iv_rank=55,
            ticker_type="etf",
        )

        hard_fails = [c for c in rpt.checks if c.severity == Severity.FAIL]
        assert not hard_fails, (
            f"Income preset validation FAILED on: "
            f"{[(c.name, c.message) for c in hard_fails]}. "
            f"Adjust IV levels in create_ideal_income() until gates pass."
        )

    def test_recovery_minimum_credit_gate_passes(self):
        """Post-crash recovery should also pass the minimum credit gate."""
        from income_desk.validation.daily_readiness import run_daily_checks
        from income_desk.validation.models import Severity

        sim = create_post_crash_recovery()
        price = sim.get_underlying_price("SPY")
        trade_spec = _build_ic_trade_spec("SPY", price)
        credit = _compute_ic_credit(sim, "SPY")

        assert credit >= 0.50, (
            f"Recovery preset credit ${credit:.2f} below $0.50"
        )

        rpt = run_daily_checks(
            ticker="SPY",
            trade_spec=trade_spec,
            entry_credit=credit,
            regime_id=2,  # R2 — post-crash, MR with elevated vol
            atr_pct=1.8,
            current_price=price,
            avg_bid_ask_spread_pct=0.8,
            dte=35,
            rsi=45.0,
            iv_rank=82,
            ticker_type="etf",
        )

        hard_fails = [c for c in rpt.checks if c.severity == Severity.FAIL]
        assert not hard_fails, (
            f"Recovery preset validation FAILED on: "
            f"{[(c.name, c.message) for c in hard_fails]}"
        )

    def test_pop_computable_for_income_preset(self):
        """POP estimate must be computable (not None) for income preset."""
        from income_desk.trade_lifecycle import estimate_pop

        sim = create_ideal_income()
        price = sim.get_underlying_price("SPY")
        trade_spec = _build_ic_trade_spec("SPY", price)
        credit = _compute_ic_credit(sim, "SPY")

        if credit < 0.50:
            pytest.skip(f"Credit ${credit:.2f} too low to test POP — preset IV needs adjustment")

        pop = estimate_pop(
            trade_spec=trade_spec,
            entry_price=credit,
            regime_id=1,
            atr_pct=1.1,
            current_price=price,
            iv_rank=55,
        )
        assert pop is not None, "POP should be computable for IC with income preset"
        assert 0.0 < pop.pop_pct <= 1.0

    def test_pop_improves_regime_r1_vs_r4(self):
        """R1 regime should produce higher POP than R4 for same IC structure."""
        from income_desk.trade_lifecycle import estimate_pop

        price = 560.0
        trade_spec = _build_ic_trade_spec("SPY", price)
        credit = 1.50

        pop_r1 = estimate_pop(
            trade_spec=trade_spec, entry_price=credit,
            regime_id=1, atr_pct=1.1, current_price=price, iv_rank=55,
        )
        pop_r4 = estimate_pop(
            trade_spec=trade_spec, entry_price=credit,
            regime_id=4, atr_pct=1.1, current_price=price, iv_rank=55,
        )
        assert pop_r1 is not None and pop_r4 is not None
        # R1 (mean-reverting, compressed vol) should produce higher POP than R4 (trending)
        assert pop_r1.pop_pct > pop_r4.pop_pct, (
            f"R1 POP ({pop_r1.pop_pct:.1%}) should exceed R4 ({pop_r4.pop_pct:.1%})"
        )

    def test_wheel_preset_spy_credit_viable(self):
        """Wheel preset SPY credit must be viable for IC/CSP analysis."""
        sim = create_wheel_opportunity()
        price = sim.get_underlying_price("SPY")
        credit = _compute_ic_credit(sim, "SPY")
        assert credit >= 0.50, f"Wheel SPY IC credit too low: ${credit:.2f}"

    def test_india_trading_chains_non_empty(self):
        """India trading preset should produce usable chains for all indices."""
        sim = create_india_trading()
        for ticker in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
            chain = sim.get_option_chain(ticker)
            assert len(chain) > 0, f"India trading {ticker} chain is empty"
