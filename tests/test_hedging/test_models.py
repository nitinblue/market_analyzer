"""Tests for hedging domain models."""

import pytest

from income_desk.hedging.models import (
    CollarResult,
    FnOCoverage,
    HedgeAlternative,
    HedgeApproach,
    HedgeComparison,
    HedgeComparisonEntry,
    HedgeEffectiveness,
    HedgeGoal,
    HedgeMonitorEntry,
    HedgeMonitorResult,
    HedgeResult,
    HedgeTier,
    PositionHedge,
    PortfolioHedgeAnalysis,
    SyntheticOptionResult,
)
from income_desk.models.opportunity import (
    LegAction,
    LegSpec,
    OrderSide,
    StructureType,
    TradeSpec,
)


def _make_trade_spec(ticker: str = "RELIANCE", structure: StructureType = StructureType.LONG_OPTION) -> TradeSpec:
    """Helper to build a minimal TradeSpec for testing."""
    return TradeSpec(
        ticker=ticker,
        structure_type=structure,
        order_side=OrderSide.DEBIT,
        underlying_price=2680.0,
        target_dte=30,
        target_expiration="2026-04-24",
        spec_rationale="Test hedge spec",
        legs=[
            LegSpec(
                role="long_put",
                action=LegAction.BUY_TO_OPEN,
                strike=2600.0,
                strike_label="2600P",
                expiration="2026-04-24",
                days_to_expiry=30,
                option_type="put",
                atm_iv_at_expiry=0.20,
                quantity=1,
            ),
        ],
        max_profit_desc="Unlimited downside protection",
        max_loss_desc="Premium paid",
    )


class TestHedgeTier:
    def test_values(self):
        assert HedgeTier.DIRECT == "direct"
        assert HedgeTier.FUTURES_SYNTHETIC == "futures_synthetic"
        assert HedgeTier.PROXY_INDEX == "proxy_index"
        assert HedgeTier.NONE == "none"

    def test_ordering_preference(self):
        tiers = [HedgeTier.DIRECT, HedgeTier.FUTURES_SYNTHETIC, HedgeTier.PROXY_INDEX]
        assert len(tiers) == 3  # Three viable tiers


class TestHedgeApproach:
    def test_direct_approach(self):
        approach = HedgeApproach(
            ticker="RELIANCE",
            market="INDIA",
            recommended_tier=HedgeTier.DIRECT,
            goal=HedgeGoal.DOWNSIDE,
            rationale="RELIANCE has medium options liquidity — direct put available",
            alternatives=[
                HedgeAlternative(
                    tier=HedgeTier.FUTURES_SYNTHETIC,
                    reason_not_chosen="Direct options available and cheaper",
                    estimated_cost_pct=0.8,
                ),
            ],
            estimated_cost_pct=1.2,
            basis_risk="none",
            has_liquid_options=True,
            has_futures=True,
            lot_size=250,
            lot_size_affordable=True,
        )
        assert approach.recommended_tier == HedgeTier.DIRECT
        assert approach.lot_size == 250

    def test_proxy_approach_dmart(self):
        """DMart (Avenue Supermarts) — no F&O, proxy only."""
        approach = HedgeApproach(
            ticker="DMART",
            market="INDIA",
            recommended_tier=HedgeTier.PROXY_INDEX,
            goal=HedgeGoal.DOWNSIDE,
            rationale="DMART not in F&O — use NIFTY proxy (consumer discretionary sector)",
            alternatives=[],
            estimated_cost_pct=1.5,
            basis_risk="high",
            has_liquid_options=False,
            has_futures=False,
            lot_size=0,
            lot_size_affordable=False,
        )
        assert approach.recommended_tier == HedgeTier.PROXY_INDEX
        assert approach.basis_risk == "high"


class TestHedgeResult:
    def test_protective_put_result(self):
        result = HedgeResult(
            ticker="RELIANCE",
            market="INDIA",
            tier=HedgeTier.DIRECT,
            hedge_type="protective_put",
            trade_spec=_make_trade_spec("RELIANCE"),
            cost_estimate=15000.0,
            cost_pct=1.2,
            delta_reduction=0.85,
            protection_level="Put at 2600 (1 ATR OTM)",
            max_loss_after_hedge=50000.0,
            rationale="R2 high-vol MR — protective put with high IV partially offset by collar potential",
            regime_context="R2: elevated vol makes puts expensive but protection critical",
            commentary=["ATR=80, put at 2600 (1 ATR below 2680)", "Lot size 250, 1 lot covers position"],
        )
        assert result.delta_reduction == 0.85
        assert result.trade_spec.ticker == "RELIANCE"


class TestCollarResult:
    def test_zero_cost_collar(self):
        collar = CollarResult(
            ticker="SPY",
            market="US",
            put_strike=560.0,
            call_strike=590.0,
            net_cost=-0.15,  # Slight credit
            downside_protection_pct=3.4,
            upside_cap_pct=1.7,
            trade_spec=_make_trade_spec("SPY"),
            rationale="R2 high IV makes zero-cost collar achievable",
        )
        assert collar.net_cost < 0  # Credit


class TestSyntheticOptionResult:
    def test_synthetic_put(self):
        synthetic = SyntheticOptionResult(
            ticker="TATASTEEL",
            market="INDIA",
            synthetic_type="synthetic_put",
            futures_direction="short",
            futures_lots=1,
            option_strike=130.0,
            option_type="call",
            option_lots=1,
            net_cost_estimate=2500.0,
            trade_spec=_make_trade_spec("TATASTEEL", StructureType.FUTURES_SHORT),
            rationale="TATASTEEL options illiquid — synthetic put via short futures + long call",
        )
        assert synthetic.futures_direction == "short"
        assert synthetic.option_type == "call"  # Synthetic put = short futures + long call


class TestPortfolioHedgeAnalysis:
    def test_mixed_tier_portfolio(self):
        analysis = PortfolioHedgeAnalysis(
            market="INDIA",
            account_nlv=5000000.0,
            total_positions=3,
            total_position_value=3000000.0,
            tier_counts={"direct": 1, "futures_synthetic": 1, "proxy_index": 1},
            tier_values={"direct": 1500000, "futures_synthetic": 1000000, "proxy_index": 500000},
            position_hedges=[],
            total_hedge_cost=45000.0,
            hedge_cost_pct=1.5,
            portfolio_delta_before=-2.5,
            portfolio_delta_after=-0.3,
            portfolio_beta_before=1.1,
            portfolio_beta_after=0.4,
            trade_specs=[],
            coverage_pct=83.3,
            target_hedge_pct=80.0,
            summary="3 positions hedged across 3 tiers, 83% coverage achieved",
            alerts=["DMART hedge has high basis risk (proxy only)"],
        )
        assert analysis.coverage_pct > analysis.target_hedge_pct


class TestHedgeEffectiveness:
    def test_five_pct_drop(self):
        eff = HedgeEffectiveness(
            market_move_pct=-0.05,
            portfolio_loss_unhedged=250000.0,
            portfolio_loss_hedged=80000.0,
            hedge_savings=170000.0,
            hedge_savings_pct=68.0,
            cost_of_hedges=45000.0,
            net_benefit=125000.0,
            roi_on_hedge=2.78,
            commentary="Hedges saved 68% of potential loss in a 5% drawdown; 2.8x ROI on hedge cost",
        )
        assert eff.net_benefit > 0
        assert eff.roi_on_hedge > 1.0


class TestFnOCoverage:
    def test_india_portfolio_coverage(self):
        coverage = FnOCoverage(
            market="INDIA",
            total_tickers=10,
            direct_hedge_count=3,
            futures_hedge_count=4,
            proxy_only_count=2,
            no_hedge_count=1,
            coverage_pct=70.0,
            tier_breakdown={
                "direct": ["NIFTY", "BANKNIFTY", "RELIANCE"],
                "futures_synthetic": ["TATASTEEL", "SBIN", "ITC", "INFY"],
                "proxy_index": ["DMART", "PIDILITIND"],
                "none": ["SMALLCAP_X"],
            },
            commentary="70% hedgeable via direct or futures; 2 require NIFTY proxy; 1 has no viable hedge",
        )
        assert coverage.direct_hedge_count + coverage.futures_hedge_count == 7
