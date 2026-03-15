"""Trade Lifecycle APIs — the complete trading workflow for eTrading.

Pure computation functions covering every stage of a trade's lifecycle:

    1. PRE-TRADE:  filter_trades_by_account()   — account-aware trade filtering
                   compute_income_yield()        — ROC, annualized yield, credit/width
                   align_strikes_to_levels()     — snap strikes to S/R levels
                   estimate_pop()                — regime-based probability of profit
                   compute_breakevens()          — breakeven prices
                   check_income_entry()          — income-optimal entry confirmation

    2. AT ENTRY:   aggregate_greeks()            — net delta/gamma/theta/vega

    3. MONITORING: monitor_exit_conditions()     — profit target, stop loss, DTE, regime
                   check_trade_health()          — combined exit + adjustment health check
                   get_adjustment_recommendation() — wrapper for AdjustmentService

Every function takes inputs and returns results. No state, no broker calls,
no data fetching. eTrading provides the data, market_analyzer computes the answer.
"""

from __future__ import annotations

import math
from datetime import date, time as dt_time
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel

from market_analyzer.models.transparency import DataGap

if TYPE_CHECKING:
    from market_analyzer.models.adjustment import AdjustmentAnalysis, AdjustmentDecision
    from market_analyzer.models.levels import LevelsAnalysis
    from market_analyzer.models.opportunity import TradeSpec
    from market_analyzer.models.quotes import OptionQuote
    from market_analyzer.models.ranking import RankedEntry
    from market_analyzer.models.regime import RegimeResult
    from market_analyzer.models.technicals import TechnicalSnapshot
    from market_analyzer.models.vol_surface import VolatilitySurface


# ── F5: Income Yield Metrics ──


class IncomeYield(BaseModel):
    """Income yield metrics for a credit trade.

    eTrading calls ``compute_income_yield(trade_spec, entry_credit)``
    after getting a fill to assess capital efficiency.
    """

    credit_per_spread: float  # Net credit received per spread
    wing_width: float  # Distance between short and long strikes
    max_profit: float  # credit × 100 × contracts
    max_loss: float  # (wing - credit) × 100 × contracts
    credit_to_width_pct: float  # credit / wing_width (e.g., 0.16 = 16%)
    return_on_capital_pct: float  # max_profit / max_loss (ROC per trade)
    annualized_roc_pct: float  # ROC annualized by DTE
    breakeven_low: float | None  # Short put - credit (bull put / IC)
    breakeven_high: float | None  # Short call + credit (bear call / IC)
    contracts: int


def compute_income_yield(
    trade_spec: TradeSpec,
    entry_credit: float,
    contracts: int = 1,
) -> IncomeYield | None:
    """Compute income yield metrics for a credit trade.

    Args:
        trade_spec: The trade structure (needs wing_width_points, legs).
        entry_credit: Net credit received per spread.
        contracts: Number of contracts.

    Returns:
        IncomeYield with ROC, annualized yield, breakevens. None if not a credit trade.
    """
    if not trade_spec.order_side or trade_spec.order_side != "credit":
        return None
    wing = trade_spec.wing_width_points
    if not wing or wing <= 0:
        return None

    lot_size = trade_spec.lot_size
    max_profit = entry_credit * lot_size * contracts
    max_loss = (wing - entry_credit) * lot_size * contracts
    credit_to_width = entry_credit / wing
    roc = max_profit / max_loss if max_loss > 0 else 0.0

    dte = trade_spec.target_dte or 30
    annual_factor = 365.0 / max(dte, 1)
    annualized = roc * annual_factor

    # Breakevens from legs
    be_low, be_high = _compute_breakevens(trade_spec, entry_credit)

    return IncomeYield(
        credit_per_spread=entry_credit,
        wing_width=wing,
        max_profit=round(max_profit, 2),
        max_loss=round(max_loss, 2),
        credit_to_width_pct=round(credit_to_width, 4),
        return_on_capital_pct=round(roc, 4),
        annualized_roc_pct=round(annualized, 4),
        breakeven_low=be_low,
        breakeven_high=be_high,
        contracts=contracts,
    )


# ── F8: Breakeven Calculation ──


class Breakevens(BaseModel):
    """Breakeven prices for a trade structure."""

    low: float | None = None  # Price below which you lose money
    high: float | None = None  # Price above which you lose money
    structure_type: str


def compute_breakevens(
    trade_spec: TradeSpec,
    entry_price: float,
) -> Breakevens:
    """Compute breakeven prices for any structure.

    Args:
        trade_spec: The trade structure with legs.
        entry_price: Net credit or debit per spread.

    Returns:
        Breakevens with low and/or high price levels.
    """
    low, high = _compute_breakevens(trade_spec, entry_price)
    return Breakevens(
        low=low, high=high,
        structure_type=trade_spec.structure_type or "unknown",
    )


def _compute_breakevens(
    trade_spec: TradeSpec,
    entry_price: float,
) -> tuple[float | None, float | None]:
    """Internal: compute breakeven low/high from legs and fill price."""
    from market_analyzer.models.opportunity import LegAction

    st = trade_spec.structure_type or ""
    legs = trade_spec.legs

    if st in ("iron_condor", "iron_man"):
        short_puts = [l for l in legs if l.option_type == "put" and l.action == LegAction.SELL_TO_OPEN]
        short_calls = [l for l in legs if l.option_type == "call" and l.action == LegAction.SELL_TO_OPEN]
        be_low = round(short_puts[0].strike - entry_price, 2) if short_puts else None
        be_high = round(short_calls[0].strike + entry_price, 2) if short_calls else None
        return be_low, be_high

    if st == "iron_butterfly":
        # Short straddle at ATM
        short_strikes = [l for l in legs if l.action == LegAction.SELL_TO_OPEN]
        if short_strikes:
            atm = short_strikes[0].strike
            return round(atm - entry_price, 2), round(atm + entry_price, 2)
        return None, None

    if st == "credit_spread":
        short_legs = [l for l in legs if l.action == LegAction.SELL_TO_OPEN]
        if short_legs:
            s = short_legs[0]
            if s.option_type == "put":
                return round(s.strike - entry_price, 2), None
            else:
                return None, round(s.strike + entry_price, 2)
        return None, None

    if st == "debit_spread":
        long_legs = [l for l in legs if l.action == LegAction.BUY_TO_OPEN]
        if long_legs:
            l = long_legs[0]
            if l.option_type == "call":
                return round(l.strike + entry_price, 2), None
            else:
                return None, round(l.strike - entry_price, 2)
        return None, None

    if st in ("straddle", "strangle"):
        puts = [l for l in legs if l.option_type == "put"]
        calls = [l for l in legs if l.option_type == "call"]
        if puts and calls:
            if trade_spec.order_side == "credit":
                return round(puts[0].strike - entry_price, 2), round(calls[0].strike + entry_price, 2)
            else:
                return round(puts[0].strike - entry_price, 2), round(calls[0].strike + entry_price, 2)
        return None, None

    return None, None


# ── F9: Greeks Aggregation ──


class AggregatedGreeks(BaseModel):
    """Net portfolio Greeks for a multi-leg trade.

    eTrading calls ``aggregate_greeks(trade_spec, leg_quotes)``
    after fetching broker quotes with Greeks.
    """

    net_delta: float
    net_gamma: float
    net_theta: float  # Daily theta income (positive = collecting)
    net_vega: float
    daily_theta_dollars: float  # net_theta × 100 × contracts
    contracts: int


def aggregate_greeks(
    trade_spec: TradeSpec,
    leg_quotes: list[OptionQuote],
    contracts: int = 1,
) -> AggregatedGreeks | None:
    """Aggregate Greeks across all legs of a trade.

    Args:
        trade_spec: The trade structure with legs.
        leg_quotes: Broker quotes with Greeks (one per leg, same order).
        contracts: Number of contracts.

    Returns:
        AggregatedGreeks with net delta/gamma/theta/vega. None if Greeks unavailable.
    """
    from market_analyzer.models.opportunity import LegAction

    if len(leg_quotes) != len(trade_spec.legs):
        return None

    net_d = net_g = net_t = net_v = 0.0

    for leg, quote in zip(trade_spec.legs, leg_quotes):
        if quote.delta is None:
            return None  # Greeks not available

        sign = 1.0 if leg.action == LegAction.BUY_TO_OPEN else -1.0
        qty = leg.quantity

        net_d += sign * qty * (quote.delta or 0.0)
        net_g += sign * qty * (quote.gamma or 0.0)
        net_t += sign * qty * (quote.theta or 0.0)
        net_v += sign * qty * (quote.vega or 0.0)

    return AggregatedGreeks(
        net_delta=round(net_d, 4),
        net_gamma=round(net_g, 6),
        net_theta=round(net_t, 4),
        net_vega=round(net_v, 4),
        daily_theta_dollars=round(net_t * trade_spec.lot_size * contracts, 2),
        contracts=contracts,
    )


# ── F4: Account-Size Trade Filter ──


class FilteredTrades(BaseModel):
    """Result of filtering ranked trades by account constraints."""

    affordable: list[dict]  # Trades that fit within available BP
    filtered_out: list[dict]  # Trades removed (too expensive, wrong structure)
    total_input: int
    total_affordable: int
    available_buying_power: float


def filter_trades_by_account(
    ranked_entries: list[RankedEntry],
    available_buying_power: float,
    allowed_structures: list[str] | None = None,
    max_risk_per_trade: float | None = None,
) -> FilteredTrades:
    """Filter ranked trades by account size and structure constraints.

    Args:
        ranked_entries: Output from TradeRankingService.rank().top_trades.
        available_buying_power: Current available BP from portfolio/broker.
        allowed_structures: Only include these structure types.
        max_risk_per_trade: Max dollar risk per trade.

    Returns:
        FilteredTrades with affordable trades and reasons for filtering.
    """
    affordable = []
    filtered = []

    for entry in ranked_entries:
        ts = entry.trade_spec
        reason = None

        # Structure check
        if allowed_structures and ts and ts.structure_type:
            if ts.structure_type not in allowed_structures:
                reason = f"structure '{ts.structure_type}' not allowed"

        # BP check
        if ts and ts.wing_width_points and not reason:
            bp_needed = ts.wing_width_points * ts.lot_size
            if bp_needed > available_buying_power:
                reason = f"needs ${bp_needed:.0f} BP, have ${available_buying_power:.0f}"

        # Risk check
        if ts and max_risk_per_trade and not reason:
            risk = (ts.wing_width_points or 0) * ts.lot_size
            if ts.order_side == "debit" and ts.max_entry_price:
                risk = ts.max_entry_price * ts.lot_size
            if risk > max_risk_per_trade:
                reason = f"risk ${risk:.0f} exceeds limit ${max_risk_per_trade:.0f}"

        rec = {
            "rank": entry.rank,
            "ticker": entry.ticker,
            "strategy_type": str(entry.strategy_type),
            "composite_score": entry.composite_score,
            "verdict": str(entry.verdict),
            "direction": entry.direction,
            "structure_type": ts.structure_type if ts else None,
            "wing_width": ts.wing_width_points if ts else None,
            "max_entry_price": ts.max_entry_price if ts else None,
        }

        if reason:
            rec["filter_reason"] = reason
            filtered.append(rec)
        else:
            affordable.append(rec)

    return FilteredTrades(
        affordable=affordable,
        filtered_out=filtered,
        total_input=len(ranked_entries),
        total_affordable=len(affordable),
        available_buying_power=available_buying_power,
    )


class OpenPosition(BaseModel):
    """Snapshot of an open position — eTrading provides this from portfolio DB."""

    ticker: str
    structure_type: str  # "iron_condor", "credit_spread", "equity_long", etc.
    sector: str = ""     # "tech", "finance", "energy", etc.
    max_loss: float = 0  # Max loss in local currency
    buying_power_used: float = 0


class RiskLimits(BaseModel):
    """Risk limits for position-aware filtering — eTrading configures per desk."""

    max_positions: int = 5
    max_per_ticker: int = 2
    max_sector_concentration_pct: float = 0.40  # 40% of NLV in one sector
    max_portfolio_risk_pct: float = 0.25  # 25% total risk deployed
    min_trade_quality_score: float = 0.50  # From POPEstimate.trade_quality_score


class PortfolioFilterResult(BaseModel):
    """Result of position-aware trade filtering."""

    approved: list[dict]
    rejected: list[dict]  # Each has "reason" field
    total_input: int
    total_approved: int
    open_positions_count: int
    portfolio_risk_pct: float  # Current risk as % of NLV
    slots_remaining: int  # How many more positions can be opened
    summary: str


def filter_trades_with_portfolio(
    ranked_entries: list[RankedEntry],
    open_positions: list[OpenPosition],
    account_nlv: float,
    available_buying_power: float,
    risk_limits: RiskLimits = RiskLimits(),
    allowed_structures: list[str] | None = None,
    max_risk_per_trade: float | None = None,
) -> PortfolioFilterResult:
    """Position-aware trade filtering — the full risk gate.

    Combines account filtering with position limits, sector concentration,
    and portfolio risk budget. eTrading calls this INSTEAD of filter_trades_by_account()
    when position data is available.

    Args:
        ranked_entries: Ranked trades from MA
        open_positions: Current open positions from eTrading portfolio DB
        account_nlv: Net liquidating value of account
        available_buying_power: BP minus what's used by open positions
        risk_limits: Per-desk risk configuration
        allowed_structures: Structure whitelist
        max_risk_per_trade: Max dollar risk per trade

    Returns:
        PortfolioFilterResult with approved/rejected trades and portfolio stats
    """
    # Build concentration maps from open positions
    ticker_count: dict[str, int] = {}
    sector_risk: dict[str, float] = {}
    total_risk = 0.0

    for pos in open_positions:
        ticker_count[pos.ticker] = ticker_count.get(pos.ticker, 0) + 1
        sector_risk[pos.sector] = sector_risk.get(pos.sector, 0) + pos.max_loss
        total_risk += pos.max_loss

    approved = []
    rejected = []
    new_positions = 0

    for entry in ranked_entries:
        ts = entry.trade_spec
        reason = None

        # 1. Structure whitelist
        if allowed_structures and ts and ts.structure_type:
            if ts.structure_type not in allowed_structures:
                reason = f"structure '{ts.structure_type}' not allowed"

        # 2. Total position limit
        if not reason and len(open_positions) + new_positions >= risk_limits.max_positions:
            reason = f"portfolio full ({risk_limits.max_positions} positions)"

        # 3. Per-ticker limit
        if not reason and ts:
            current = ticker_count.get(ts.ticker, 0)
            if current >= risk_limits.max_per_ticker:
                reason = f"ticker {ts.ticker} at limit ({current}/{risk_limits.max_per_ticker})"

        # 4. BP check
        if not reason and ts and ts.wing_width_points:
            bp_needed = ts.wing_width_points * ts.lot_size
            if bp_needed > available_buying_power:
                reason = f"insufficient BP (need {bp_needed:.0f}, have {available_buying_power:.0f})"

        # 5. Single trade risk limit
        trade_risk = 0.0
        if ts:
            trade_risk = (ts.wing_width_points or 0) * ts.lot_size
            if ts.order_side == "debit" and ts.max_entry_price:
                trade_risk = ts.max_entry_price * ts.lot_size
        if not reason and max_risk_per_trade and trade_risk > max_risk_per_trade:
            reason = f"trade risk {trade_risk:.0f} exceeds limit {max_risk_per_trade:.0f}"

        # 6. Sector concentration
        if not reason and ts and account_nlv > 0:
            sector = ""
            try:
                from market_analyzer.registry import MarketRegistry
                inst = MarketRegistry().get_instrument(ts.ticker)
                sector = inst.sector
            except (KeyError, ImportError):
                pass
            if sector:
                new_sector_risk = sector_risk.get(sector, 0) + trade_risk
                if new_sector_risk / account_nlv > risk_limits.max_sector_concentration_pct:
                    reason = f"sector '{sector}' at {new_sector_risk / account_nlv:.0%} (limit {risk_limits.max_sector_concentration_pct:.0%})"

        # 7. Portfolio risk budget
        if not reason and account_nlv > 0:
            new_total_risk = total_risk + trade_risk
            if new_total_risk / account_nlv > risk_limits.max_portfolio_risk_pct:
                reason = f"portfolio risk {new_total_risk / account_nlv:.0%} exceeds {risk_limits.max_portfolio_risk_pct:.0%}"

        rec = {
            "rank": entry.rank,
            "ticker": entry.ticker,
            "strategy_type": str(entry.strategy_type),
            "composite_score": entry.composite_score,
            "verdict": str(entry.verdict),
            "structure_type": ts.structure_type if ts else None,
            "trade_risk": round(trade_risk, 2),
        }

        if reason:
            rec["reason"] = reason
            rejected.append(rec)
        else:
            approved.append(rec)
            new_positions += 1
            if ts:
                ticker_count[ts.ticker] = ticker_count.get(ts.ticker, 0) + 1
                total_risk += trade_risk
                available_buying_power -= (ts.wing_width_points or 0) * ts.lot_size

    portfolio_risk_pct = total_risk / account_nlv if account_nlv > 0 else 0
    slots = max(0, risk_limits.max_positions - len(open_positions) - new_positions)

    return PortfolioFilterResult(
        approved=approved,
        rejected=rejected,
        total_input=len(ranked_entries),
        total_approved=len(approved),
        open_positions_count=len(open_positions),
        portfolio_risk_pct=round(portfolio_risk_pct, 4),
        slots_remaining=slots,
        summary=f"{len(approved)} approved, {len(rejected)} rejected | "
                f"{len(open_positions)} open + {new_positions} new = {len(open_positions) + new_positions} total | "
                f"Risk: {portfolio_risk_pct:.0%} of NLV | {slots} slots remaining",
    )


# ── F6: Strike Alignment to Support/Resistance ──


class AlignedStrikes(BaseModel):
    """Strikes snapped to nearest support/resistance levels."""

    original_strike: float
    aligned_strike: float
    level_price: float
    level_source: str  # "support" or "resistance"
    distance_from_level: float  # How far aligned strike is from the level
    improved: bool  # True if aligned is different from original


def align_strikes_to_levels(
    trade_spec: TradeSpec,
    levels: LevelsAnalysis,
    max_snap_distance_pct: float = 0.02,
) -> list[AlignedStrikes]:
    """Snap short strikes to nearest support/resistance levels.

    Args:
        trade_spec: The trade with legs to align.
        levels: Support/resistance from LevelsService.analyze().
        max_snap_distance_pct: Max % distance to snap (default 2%).

    Returns:
        List of AlignedStrikes for each short leg that could be improved.
    """
    from market_analyzer.models.opportunity import LegAction
    from market_analyzer.opportunity.option_plays._trade_spec_helpers import snap_strike

    results = []
    price = levels.current_price

    for leg in trade_spec.legs:
        if leg.action != LegAction.SELL_TO_OPEN:
            continue

        # Find nearest level
        best_level = None
        best_dist = float("inf")
        best_source = ""

        if leg.option_type == "put":
            # Short puts: snap to support levels
            for lvl in levels.support_levels:
                dist = abs(leg.strike - lvl.price) / price
                if dist < best_dist and dist <= max_snap_distance_pct:
                    best_dist = dist
                    best_level = lvl
                    best_source = "support"
        else:
            # Short calls: snap to resistance levels
            for lvl in levels.resistance_levels:
                dist = abs(leg.strike - lvl.price) / price
                if dist < best_dist and dist <= max_snap_distance_pct:
                    best_dist = dist
                    best_level = lvl
                    best_source = "resistance"

        if best_level is not None:
            aligned = snap_strike(best_level.price, price)
            results.append(AlignedStrikes(
                original_strike=leg.strike,
                aligned_strike=aligned,
                level_price=best_level.price,
                level_source=best_source,
                distance_from_level=round(best_dist * 100, 2),
                improved=aligned != leg.strike,
            ))

    return results


# ── F7: Probability of Profit (POP) ──


class POPEstimate(BaseModel):
    """Regime-based probability of profit estimate with R:R and trade quality.

    Uses historical regime-specific return distributions, not Black-Scholes.
    Combines POP + Expected Value + Risk:Reward into a single trade quality score.
    """

    pop_pct: float               # Probability of profit (0-1)
    expected_value: float        # EV = POP × max_profit - (1-POP) × max_loss
    max_profit: float = 0.0     # Max profit in dollars
    max_loss: float = 0.0       # Max loss in dollars (positive number)
    risk_reward_ratio: float = 0.0  # max_loss / max_profit (lower = better)
    trade_quality: str = ""      # "excellent" / "good" / "marginal" / "poor"
    trade_quality_score: float = 0.0  # 0-1 composite of POP + EV + R:R
    method: str                  # "regime_historical" or "simple_distance"
    regime_id: int
    notes: str
    data_gaps: list[DataGap] = []


def _trade_quality(pop: float, ev: float, rr: float, max_profit: float) -> tuple[str, float]:
    """Compute trade quality from POP + EV + R:R combined.

    Scoring:
    - POP component (40%): higher POP = better
    - EV component (30%): positive EV = better, weighted by magnitude
    - R:R component (30%): lower R:R = better (less risk per unit reward)

    Returns (quality_label, quality_score 0-1).
    """
    # POP score: 0.5 POP = 0, 1.0 POP = 1.0
    pop_score = max(0, (pop - 0.3) / 0.7)  # 30% floor

    # EV score: positive = good, normalized by max_profit
    if max_profit > 0:
        ev_score = max(0, min(1, (ev / max_profit + 0.5)))  # -50% to +50% range
    else:
        ev_score = 0.5 if ev >= 0 else 0

    # R:R score: 1:1 = excellent, 5:1 = poor, 10:1+ = terrible
    if rr <= 1.0:
        rr_score = 1.0
    elif rr <= 3.0:
        rr_score = 1.0 - (rr - 1.0) / 4.0  # Linear decay from 1.0 to 0.5
    elif rr <= 10.0:
        rr_score = 0.5 - (rr - 3.0) / 14.0  # Linear decay from 0.5 to 0
    else:
        rr_score = 0.0

    # Weighted composite
    score = pop_score * 0.40 + ev_score * 0.30 + rr_score * 0.30
    score = max(0, min(1, score))

    # Quality label
    if score >= 0.70:
        label = "excellent"
    elif score >= 0.50:
        label = "good"
    elif score >= 0.30:
        label = "marginal"
    else:
        label = "poor"

    return label, score


def estimate_pop(
    trade_spec: TradeSpec,
    entry_price: float,
    regime_id: int,
    atr_pct: float,
    current_price: float,
    contracts: int = 1,
    iv_rank: float | None = None,
) -> POPEstimate | None:
    """Estimate probability of profit using regime-aware distance analysis.

    NOT Black-Scholes. Uses the regime's historical ATR behavior to estimate
    the probability that price stays within the profit range.

    Args:
        trade_spec: The trade structure.
        entry_price: Net credit or debit.
        regime_id: Current regime (1-4).
        atr_pct: Current ATR as % of price.
        current_price: Current underlying price.
        contracts: Number of contracts.
        iv_rank: IV rank (0-100). When provided, adjusts expected move
            based on IV environment. Higher IV rank widens expected moves.

    Returns:
        POPEstimate. None if structure not supported.
    """
    be_low, be_high = _compute_breakevens(trade_spec, entry_price)

    st = trade_spec.structure_type or ""
    dte = trade_spec.target_dte or 30

    if st in ("iron_condor", "iron_butterfly", "credit_spread", "strangle", "straddle"):
        # Credit trade: profit if price stays between breakevens
        # ATR% is daily. Convert to 1-sigma via ATR/1.25 (ATR ≈ 1.25σ for normal dist)
        daily_sigma = (atr_pct / 100.0) / 1.25
        # IV rank adjustment: elevated IV (rank > 50) widens expected moves,
        # compressed IV (rank < 50) narrows them
        if iv_rank is not None:
            iv_factor = 0.7 + (iv_rank / 100) * 0.6  # Range: 0.7 to 1.3
            daily_sigma = daily_sigma * iv_factor
        expected_move = daily_sigma * math.sqrt(dte) * current_price

        # Regime adjustments: MR regimes compress effective vol, trending expands it
        regime_factor = {1: 0.40, 2: 0.70, 3: 1.10, 4: 1.50}.get(regime_id, 1.0)
        adjusted_move = expected_move * regime_factor

        if adjusted_move <= 0:
            return None

        # Distance to breakevens in units of expected move
        if be_low and be_high:
            dist_low = (current_price - be_low) / adjusted_move
            dist_high = (be_high - current_price) / adjusted_move
            # Approximate POP: probability price stays within range
            # Using normal approximation: P(|Z| < d) ≈ erf(d/√2)
            pop_low = 0.5 * (1 + math.erf(dist_low / math.sqrt(2)))
            pop_high = 0.5 * (1 + math.erf(dist_high / math.sqrt(2)))
            pop = pop_low + pop_high - 1.0
        elif be_low:
            dist = (current_price - be_low) / adjusted_move
            pop = 0.5 * (1 + math.erf(dist / math.sqrt(2)))
        elif be_high:
            dist = (be_high - current_price) / adjusted_move
            pop = 0.5 * (1 + math.erf(dist / math.sqrt(2)))
        else:
            return None

        pop = max(0.0, min(1.0, pop))

        # Expected value
        wing = trade_spec.wing_width_points or 5.0
        lot_size = trade_spec.lot_size
        if trade_spec.order_side == "credit":
            max_profit = entry_price * lot_size * contracts
            max_loss = (wing - entry_price) * lot_size * contracts
        else:
            max_profit = (wing - entry_price) * lot_size * contracts
            max_loss = entry_price * lot_size * contracts

        ev = pop * max_profit - (1 - pop) * max_loss

        regime_names = {1: "R1 Low-Vol MR", 2: "R2 High-Vol MR", 3: "R3 Low-Vol Trend", 4: "R4 High-Vol Trend"}
        iv_note = f", IV rank {iv_rank:.0f}" if iv_rank is not None else ""
        notes = (
            f"Regime {regime_names.get(regime_id, f'R{regime_id}')}: "
            f"expected {dte}d move ±${adjusted_move:.1f} "
            f"(ATR {atr_pct:.1f}%, regime factor {regime_factor:.2f}{iv_note})"
        )

        gaps: list[DataGap] = []
        if iv_rank is None:
            gaps.append(DataGap(
                field="pop",
                reason="no IV rank — using ATR-only expected move",
                impact="medium",
                affects="POP estimate may be 10-15% off without IV calibration",
            ))

        rr = round(max_loss / max_profit, 2) if max_profit > 0 else 99.0
        quality, qscore = _trade_quality(pop, ev, rr, max_profit)

        return POPEstimate(
            pop_pct=round(pop, 4),
            expected_value=round(ev, 2),
            max_profit=round(max_profit, 2),
            max_loss=round(max_loss, 2),
            risk_reward_ratio=rr,
            trade_quality=quality,
            trade_quality_score=round(qscore, 3),
            method="regime_historical",
            regime_id=regime_id,
            notes=notes,
            data_gaps=gaps,
        )

    if st in ("debit_spread", "long_option"):
        # Debit trade: need price to move in the right direction
        from market_analyzer.models.opportunity import LegAction
        long_legs = [l for l in trade_spec.legs if l.action == LegAction.BUY_TO_OPEN]
        if not long_legs:
            return None

        daily_sigma = (atr_pct / 100.0) / 1.25
        # IV rank adjustment (same as credit branch)
        if iv_rank is not None:
            iv_factor = 0.7 + (iv_rank / 100) * 0.6  # Range: 0.7 to 1.3
            daily_sigma = daily_sigma * iv_factor
        expected_move = daily_sigma * math.sqrt(dte) * current_price
        regime_factor = {1: 0.40, 2: 0.70, 3: 1.10, 4: 1.50}.get(regime_id, 1.0)
        adjusted_move = expected_move * regime_factor

        if adjusted_move <= 0:
            return None

        l = long_legs[0]
        if l.option_type == "call":
            breakeven = l.strike + entry_price
            dist = (breakeven - current_price) / adjusted_move
            pop = 1.0 - 0.5 * (1 + math.erf(dist / math.sqrt(2)))
        else:
            breakeven = l.strike - entry_price
            dist = (current_price - breakeven) / adjusted_move
            pop = 1.0 - 0.5 * (1 + math.erf(dist / math.sqrt(2)))

        pop = max(0.0, min(1.0, pop))

        lot_size = trade_spec.lot_size
        max_profit = ((trade_spec.wing_width_points or entry_price) - entry_price) * lot_size * contracts
        max_loss = entry_price * lot_size * contracts
        ev = pop * max_profit - (1 - pop) * max_loss

        gaps: list[DataGap] = []
        if iv_rank is None:
            gaps.append(DataGap(
                field="pop",
                reason="no IV rank — using ATR-only expected move",
                impact="medium",
                affects="POP estimate may be 10-15% off without IV calibration",
            ))

        rr = round(max_loss / max_profit, 2) if max_profit > 0 else 99.0
        quality, qscore = _trade_quality(pop, ev, rr, max_profit)

        return POPEstimate(
            pop_pct=round(pop, 4),
            expected_value=round(ev, 2),
            max_profit=round(max_profit, 2),
            max_loss=round(max_loss, 2),
            risk_reward_ratio=rr,
            trade_quality=quality,
            trade_quality_score=round(qscore, 3),
            method="regime_historical",
            regime_id=regime_id,
            notes=f"Directional: needs ${adjusted_move:.1f} move to profit",
            data_gaps=gaps,
        )

    return None


# ── F10: Income-Specific Entry Check ──


class IncomeEntryCheck(BaseModel):
    """Income-optimal entry confirmation.

    Checks conditions specific to selling premium, not directional triggers.
    """

    confirmed: bool
    score: float  # 0-1 composite score
    conditions: list[dict]  # {name, passed, value, threshold, weight}
    summary: str


def check_income_entry(
    iv_rank: float | None,
    iv_percentile: float | None,
    dte: int,
    rsi: float,
    atr_pct: float,
    regime_id: int,
    has_earnings_within_dte: bool = False,
    has_macro_event_today: bool = False,
) -> IncomeEntryCheck:
    """Check if conditions are optimal for income (premium selling) entry.

    Args:
        iv_rank: IV rank (0-100). From broker metrics.
        iv_percentile: IV percentile (0-100). From broker metrics.
        dte: Days to expiration of the trade.
        rsi: Current RSI (14-period).
        atr_pct: ATR as % of price.
        regime_id: Current regime (1-4).
        has_earnings_within_dte: True if earnings before expiration.
        has_macro_event_today: True if FOMC/CPI/NFP today.

    Returns:
        IncomeEntryCheck with pass/fail and detailed conditions.
    """
    conditions = []
    total_score = 0.0
    total_weight = 0.0

    # 1. IV Rank sweet spot (25-75 ideal for selling; >50 better)
    w = 0.25
    if iv_rank is not None:
        passed = 25 <= iv_rank <= 80
        conditions.append({
            "name": "iv_rank_sweet_spot",
            "passed": passed,
            "value": iv_rank,
            "threshold": "25-80",
            "weight": w,
        })
        total_score += w * (1.0 if passed else 0.0)
    else:
        conditions.append({
            "name": "iv_rank_sweet_spot",
            "passed": True,  # No data, don't block
            "value": None,
            "threshold": "25-80 (no data)",
            "weight": 0,
        })
    total_weight += w

    # 2. DTE sweet spot (30-45 ideal for theta decay curve)
    w = 0.20
    passed = 25 <= dte <= 50
    conditions.append({
        "name": "dte_sweet_spot",
        "passed": passed,
        "value": dte,
        "threshold": "25-50",
        "weight": w,
    })
    total_score += w * (1.0 if passed else 0.0)
    total_weight += w

    # 3. RSI neutral (40-60: not trending, ideal for range-bound trades)
    w = 0.15
    passed = 35 <= rsi <= 65
    conditions.append({
        "name": "rsi_neutral",
        "passed": passed,
        "value": round(rsi, 1),
        "threshold": "35-65",
        "weight": w,
    })
    total_score += w * (1.0 if passed else 0.0)
    total_weight += w

    # 4. Regime is income-friendly (R1 ideal, R2 acceptable)
    w = 0.20
    passed = regime_id in (1, 2)
    conditions.append({
        "name": "regime_income_friendly",
        "passed": passed,
        "value": f"R{regime_id}",
        "threshold": "R1 or R2",
        "weight": w,
    })
    total_score += w * (1.0 if passed else 0.0)
    total_weight += w

    # 5. No earnings surprise risk
    w = 0.10
    passed = not has_earnings_within_dte
    conditions.append({
        "name": "no_earnings_risk",
        "passed": passed,
        "value": has_earnings_within_dte,
        "threshold": "no earnings within DTE",
        "weight": w,
    })
    total_score += w * (1.0 if passed else 0.0)
    total_weight += w

    # 6. No macro event today
    w = 0.10
    passed = not has_macro_event_today
    conditions.append({
        "name": "no_macro_event",
        "passed": passed,
        "value": has_macro_event_today,
        "threshold": "no FOMC/CPI/NFP today",
        "weight": w,
    })
    total_score += w * (1.0 if passed else 0.0)
    total_weight += w

    score = total_score / total_weight if total_weight > 0 else 0.0
    confirmed = score >= 0.60 and regime_id in (1, 2, 3)

    failed = [c["name"] for c in conditions if not c["passed"]]
    if confirmed:
        summary = f"Income entry CONFIRMED (score {score:.0%})"
    else:
        summary = f"Income entry NOT CONFIRMED (score {score:.0%}): {', '.join(failed)}"

    return IncomeEntryCheck(
        confirmed=confirmed,
        score=round(score, 4),
        conditions=conditions,
        summary=summary,
    )


# ── F12: Exit Condition Monitor ──


class ExitSignal(BaseModel):
    """A triggered or approaching exit condition."""

    rule: str  # "profit_target", "stop_loss", "dte_exit", "regime_change"
    triggered: bool
    current_value: float | str
    threshold: float | str
    urgency: str  # "immediate", "soon", "monitor"
    action: str  # What to do
    detail: str = ""  # Additional context for this signal


class ExitMonitorResult(BaseModel):
    """Result of checking exit conditions for an open trade.

    eTrading calls ``monitor_exit_conditions()`` with current market data
    for each open position to get actionable exit signals.
    """

    trade_id: str
    ticker: str
    signals: list[ExitSignal]
    should_close: bool  # True if any signal is triggered
    most_urgent: ExitSignal | None
    pnl_pct: float  # Current P&L as percentage
    pnl_dollars: float  # Current P&L in dollars
    summary: str
    commentary: str  # Human-readable justification for the decision
    data_gaps: list[DataGap] = []


def monitor_exit_conditions(
    trade_id: str,
    ticker: str,
    structure_type: str,
    order_side: str,
    entry_price: float,
    current_mid_price: float,
    contracts: int,
    dte_remaining: int,
    regime_id: int,
    entry_regime_id: int | None = None,
    profit_target_pct: float | None = None,
    stop_loss_pct: float | None = None,
    exit_dte: int | None = None,
    time_of_day: dt_time | None = None,
    lot_size: int = 100,
) -> ExitMonitorResult:
    """Check all exit conditions for an open trade.

    Args:
        trade_id: Trade identifier.
        ticker: Underlying symbol.
        structure_type: Trade structure type.
        order_side: "credit" or "debit".
        entry_price: Original fill price.
        current_mid_price: Current mid price to close.
        contracts: Number of contracts.
        dte_remaining: Days to expiration remaining.
        regime_id: Current regime.
        entry_regime_id: Regime when trade was opened (for regime change detection).
        profit_target_pct: Close at X% of max profit.
        stop_loss_pct: Credit: X× credit; Debit: X fraction loss.
        exit_dte: Close when DTE drops to this.
        time_of_day: Current time for end-of-day urgency escalation.

    Returns:
        ExitMonitorResult with all triggered signals.
    """
    signals: list[ExitSignal] = []
    regime_names = {1: "Low-Vol MR", 2: "High-Vol MR", 3: "Low-Vol Trend", 4: "High-Vol Trend"}

    if order_side == "credit":
        # Profit: entry_price - current_mid = profit per spread
        profit_per = entry_price - current_mid_price
        pnl_pct = profit_per / entry_price if entry_price > 0 else 0
        pnl_dollars = profit_per * lot_size * contracts

        # Profit target
        if profit_target_pct is not None:
            triggered = pnl_pct >= profit_target_pct
            approaching = pnl_pct >= profit_target_pct * 0.85
            signals.append(ExitSignal(
                rule="profit_target",
                triggered=triggered,
                current_value=f"{pnl_pct:.0%} ({pnl_dollars:+.0f}$)",
                threshold=f"{profit_target_pct:.0%}",
                urgency="immediate" if triggered else "soon" if approaching else "monitor",
                action=f"Close for ${pnl_dollars:.0f} profit" if triggered else "Approaching target",
                detail=f"Credit decayed {pnl_pct:.0%} of max ({profit_target_pct:.0%} target). "
                       f"Lock in ${pnl_dollars:.0f} gain." if triggered
                       else f"At {pnl_pct:.0%} of {profit_target_pct:.0%} target — approaching profit zone.",
            ))

        # Stop loss (credit: loss = current_mid - entry > X× entry)
        if stop_loss_pct is not None:
            loss_multiple = (current_mid_price - entry_price) / entry_price if entry_price > 0 else 0
            triggered = loss_multiple >= stop_loss_pct
            approaching = loss_multiple >= stop_loss_pct * 0.75
            loss_dollars = (current_mid_price - entry_price) * lot_size * contracts
            signals.append(ExitSignal(
                rule="stop_loss",
                triggered=triggered,
                current_value=f"{loss_multiple:.1f}× credit ({loss_dollars:+.0f}$)",
                threshold=f"{stop_loss_pct:.0f}× credit",
                urgency="immediate" if triggered else "soon" if approaching else "monitor",
                action=f"Close to limit loss at ${loss_dollars:.0f}" if triggered else "Monitoring loss",
                detail=f"Loss at {loss_multiple:.1f}× initial credit (${loss_dollars:+.0f}). "
                       f"Stop at {stop_loss_pct:.0f}×. Close to prevent further damage." if triggered
                       else f"Loss at {loss_multiple:.1f}× credit — within tolerance but elevated.",
            ))
    else:
        # Debit trade
        profit_per = current_mid_price - entry_price
        pnl_pct = profit_per / entry_price if entry_price > 0 else 0
        pnl_dollars = profit_per * lot_size * contracts

        if profit_target_pct is not None:
            triggered = pnl_pct >= profit_target_pct
            signals.append(ExitSignal(
                rule="profit_target",
                triggered=triggered,
                current_value=f"{pnl_pct:.0%} ({pnl_dollars:+.0f}$)",
                threshold=f"{profit_target_pct:.0%}",
                urgency="immediate" if triggered else "monitor",
                action=f"Close for ${pnl_dollars:.0f} profit" if triggered else "Monitoring",
                detail=f"Debit gained {pnl_pct:.0%} (target {profit_target_pct:.0%}). Take profit." if triggered
                       else f"Debit at {pnl_pct:.0%} — below {profit_target_pct:.0%} target.",
            ))

        if stop_loss_pct is not None:
            loss_frac = -pnl_pct if pnl_pct < 0 else 0
            triggered = loss_frac >= stop_loss_pct
            signals.append(ExitSignal(
                rule="stop_loss",
                triggered=triggered,
                current_value=f"{loss_frac:.0%} loss ({pnl_dollars:+.0f}$)",
                threshold=f"{stop_loss_pct:.0%}",
                urgency="immediate" if triggered else "monitor",
                action=f"Close to limit loss" if triggered else "Monitoring",
                detail=f"Down {loss_frac:.0%} from entry. Stop at {stop_loss_pct:.0%}." if triggered
                       else f"Position within loss tolerance ({loss_frac:.0%} vs {stop_loss_pct:.0%} max).",
            ))

    # DTE exit
    if exit_dte is not None:
        triggered = dte_remaining <= exit_dte
        approaching = dte_remaining <= exit_dte + 5
        signals.append(ExitSignal(
            rule="dte_exit",
            triggered=triggered,
            current_value=f"{dte_remaining} DTE",
            threshold=f"≤{exit_dte} DTE",
            urgency="immediate" if triggered else "soon" if approaching else "monitor",
            action=f"Close — {dte_remaining} DTE (gamma risk)" if triggered else f"{dte_remaining} DTE remaining",
            detail=f"Only {dte_remaining} DTE left (close at {exit_dte}). "
                   f"Gamma acceleration makes holding risky — close regardless of P&L." if triggered
                   else f"{dte_remaining} DTE — {'approaching close window, prepare exit order' if approaching else 'well within holding window'}.",
        ))

    # Regime change
    if entry_regime_id is not None and regime_id != entry_regime_id:
        severe = (entry_regime_id in (1, 2) and regime_id in (3, 4))
        entry_name = regime_names.get(entry_regime_id, f"R{entry_regime_id}")
        curr_name = regime_names.get(regime_id, f"R{regime_id}")
        signals.append(ExitSignal(
            rule="regime_change",
            triggered=severe,
            current_value=f"R{regime_id} (was R{entry_regime_id})",
            threshold=f"R{entry_regime_id}",
            urgency="immediate" if severe else "soon",
            action=f"Regime shifted R{entry_regime_id}→R{regime_id}: review position" if severe
                   else f"Minor regime shift R{entry_regime_id}→R{regime_id}",
            detail=f"Regime changed from {entry_name} to {curr_name}. "
                   f"{'Income structures are invalidated in trending regime — close or hedge.' if severe else 'Minor shift — monitor but no immediate action needed.'}",
        ))

    # End-of-day urgency escalation
    if time_of_day is not None:
        # 0DTE: force close after 15:00
        if structure_type in ("iron_condor", "iron_man", "credit_spread", "straddle", "strangle") and dte_remaining == 0:
            if time_of_day >= dt_time(15, 0):
                signals.append(ExitSignal(
                    rule="eod_0dte",
                    triggered=True,
                    current_value=f"{time_of_day.strftime('%H:%M')}",
                    threshold="15:00",
                    urgency="immediate",
                    action="Close 0DTE position — market closing",
                    detail=f"0DTE position at {time_of_day.strftime('%H:%M')} — must close before 16:00. Gamma risk is extreme.",
                ))
        # Non-0DTE: escalate TESTED positions after 15:30
        elif dte_remaining > 0 and time_of_day >= dt_time(15, 30):
            # Check if any existing signal has "tested" status
            any_tested = any(s.rule == "stop_loss" and s.urgency == "soon" for s in signals)
            if any_tested:
                signals.append(ExitSignal(
                    rule="eod_tested",
                    triggered=True,
                    current_value=f"{time_of_day.strftime('%H:%M')}",
                    threshold="15:30",
                    urgency="immediate",
                    action="Close tested position before overnight gap",
                    detail=f"Position tested at {time_of_day.strftime('%H:%M')} — close before overnight gap risk.",
                ))

    triggered_signals = [s for s in signals if s.triggered]
    should_close = len(triggered_signals) > 0
    most_urgent = None
    if triggered_signals:
        priority = {"immediate": 0, "soon": 1, "monitor": 2}
        most_urgent = min(triggered_signals, key=lambda s: priority.get(s.urgency, 3))

    parts = []
    if should_close:
        reasons = [s.rule for s in triggered_signals]
        parts.append(f"CLOSE: {', '.join(reasons)}")
    else:
        parts.append("HOLD")
    approaching_signals = [s for s in signals if s.urgency == "soon" and not s.triggered]
    if approaching_signals:
        parts.append(f"Watch: {', '.join(s.rule for s in approaching_signals)}")

    # Build commentary: human-readable narrative justifying the decision
    commentary_parts: list[str] = []
    if should_close:
        commentary_parts.append(
            f"{ticker} — EXIT. {most_urgent.detail}" if most_urgent else f"{ticker} — EXIT."
        )
        other_triggered = [s for s in triggered_signals if s is not most_urgent]
        if other_triggered:
            commentary_parts.append(
                f"Also triggered: {'; '.join(s.detail for s in other_triggered if s.detail)}."
            )
    else:
        commentary_parts.append(f"{ticker} — HOLD at {pnl_pct:+.0%} P&L ({pnl_dollars:+,.0f}$).")
        if approaching_signals:
            commentary_parts.append(
                f"Approaching: {'; '.join(s.detail for s in approaching_signals if s.detail)}."
            )
        else:
            # Give a positive hold reason
            if dte_remaining and dte_remaining > 14:
                commentary_parts.append(f"Healthy theta decay with {dte_remaining} DTE remaining.")
            elif pnl_pct > 0:
                commentary_parts.append("Profitable — let theta work.")

    return ExitMonitorResult(
        trade_id=trade_id,
        ticker=ticker,
        signals=signals,
        should_close=should_close,
        most_urgent=most_urgent,
        pnl_pct=round(pnl_pct, 4),
        pnl_dollars=round(pnl_dollars, 2),
        summary=" | ".join(parts),
        commentary=" ".join(commentary_parts),
    )


# ── Trade Monitoring (combines exit + adjustment) ──


class TradeHealthCheck(BaseModel):
    """Complete health check for an open trade.

    Combines exit monitoring + adjustment analysis into one API call
    that eTrading runs for every open position daily.
    """

    trade_id: str
    ticker: str
    status: str  # "healthy", "tested", "breached", "exit_triggered"
    exit_result: ExitMonitorResult
    adjustment_needed: bool
    adjustment_summary: str | None = None  # Top adjustment recommendation
    adjustment_options: list[dict] = []  # Serialized AdjustmentOption list
    overall_action: str  # "hold", "close", "adjust", "roll"
    summary: str
    commentary: str  # Human-readable decision justification for trading platform
    overnight_risk: OvernightRisk | None = None  # Late-day overnight gap risk assessment
    data_gaps: list[DataGap] = []


def check_trade_health(
    trade_id: str,
    trade_spec: TradeSpec,
    entry_price: float,
    contracts: int,
    current_mid_price: float,
    dte_remaining: int,
    regime: RegimeResult,
    technicals: TechnicalSnapshot,
    entry_regime_id: int | None = None,
    vol_surface: VolatilitySurface | None = None,
    quote_service: object | None = None,
    time_of_day: dt_time | None = None,
) -> TradeHealthCheck:
    """Complete health check for an open trade — the daily monitoring API.

    Combines:
    1. Exit condition monitoring (profit target, stop loss, DTE, regime change)
    2. Adjustment analysis (position status, roll/narrow/close recommendations)

    Args:
        trade_id: Trade identifier from portfolio.
        trade_spec: The original TradeSpec.
        entry_price: Fill price at entry.
        contracts: Number of contracts.
        current_mid_price: Current mid price to close.
        dte_remaining: Days to expiration remaining.
        regime: Current RegimeResult from regime service.
        technicals: Current TechnicalSnapshot.
        entry_regime_id: Regime when trade was opened.
        vol_surface: Optional vol surface for roll pricing.
        quote_service: Optional OptionQuoteService for adjustment pricing.
        time_of_day: Current time for end-of-day urgency escalation and overnight risk.

    Returns:
        TradeHealthCheck with combined exit + adjustment analysis.
    """
    from market_analyzer.service.adjustment import AdjustmentService

    ticker = trade_spec.ticker

    # 1. Exit monitoring
    exit_result = monitor_exit_conditions(
        trade_id=trade_id,
        ticker=ticker,
        structure_type=trade_spec.structure_type or "",
        order_side=trade_spec.order_side or "credit",
        entry_price=entry_price,
        current_mid_price=current_mid_price,
        contracts=contracts,
        dte_remaining=dte_remaining,
        regime_id=int(regime.regime),
        entry_regime_id=entry_regime_id,
        profit_target_pct=trade_spec.profit_target_pct,
        lot_size=trade_spec.lot_size,
        stop_loss_pct=trade_spec.stop_loss_pct,
        exit_dte=trade_spec.exit_dte,
        time_of_day=time_of_day,
    )

    # 2. Adjustment analysis
    adj_svc = AdjustmentService(quote_service=quote_service)
    adj_analysis = adj_svc.analyze(
        trade_spec=trade_spec,
        regime=regime,
        technicals=technicals,
        vol_surface=vol_surface,
    )

    # Determine position status
    position_status = adj_analysis.position_status.value
    adjustment_needed = position_status in ("tested", "breached")
    adj_options = []
    adj_summary = None

    if adj_analysis.adjustments:
        # Top recommendation (first non-DO_NOTHING)
        for adj in adj_analysis.adjustments:
            adj_options.append({
                "type": adj.adjustment_type.value,
                "description": adj.description,
                "estimated_cost": adj.estimated_cost,
                "risk_change": adj.risk_change,
                "urgency": adj.urgency,
                "rationale": adj.rationale,
            })
            if adj_summary is None and adj.adjustment_type.value != "do_nothing":
                adj_summary = f"{adj.adjustment_type.value}: {adj.description}"

    # Overall action
    if exit_result.should_close:
        overall_action = "close"
        status = "exit_triggered"
    elif position_status == "breached":
        overall_action = "adjust"
        status = "breached"
    elif position_status == "tested":
        overall_action = "adjust" if adj_summary else "hold"
        status = "tested"
    else:
        overall_action = "hold"
        status = "healthy"

    # 3. Overnight risk assessment (late-day only)
    overnight_result: OvernightRisk | None = None
    if time_of_day is not None and time_of_day >= dt_time(15, 0):
        overnight_result = assess_overnight_risk(
            trade_id=trade_id,
            ticker=ticker,
            structure_type=trade_spec.structure_type or "",
            order_side=trade_spec.order_side or "credit",
            dte_remaining=dte_remaining,
            regime_id=int(regime.regime),
            position_status=position_status,
        )
        if overnight_result.risk_level == OvernightRiskLevel.CLOSE_BEFORE_CLOSE:
            overall_action = "close"
            status = "exit_triggered"

    # Summary
    parts = [f"{ticker}: {status.upper()}"]
    if exit_result.should_close:
        parts.append(exit_result.summary)
    if adjustment_needed and adj_summary:
        parts.append(f"Suggested: {adj_summary}")
    if not exit_result.should_close and not adjustment_needed:
        pnl = (entry_price - current_mid_price) * trade_spec.lot_size * contracts if (trade_spec.order_side or "") == "credit" else (current_mid_price - entry_price) * trade_spec.lot_size * contracts
        parts.append(f"P&L: ${pnl:+.0f} | {dte_remaining} DTE")

    # Build commentary: comprehensive narrative for trading platform
    regime_names = {1: "Low-Vol MR", 2: "High-Vol MR", 3: "Low-Vol Trend", 4: "High-Vol Trend"}
    regime_name = regime_names.get(int(regime.regime), f"R{regime.regime}")
    commentary_parts: list[str] = []

    if exit_result.should_close:
        commentary_parts.append(exit_result.commentary)
        if adjustment_needed and adj_summary:
            commentary_parts.append(f"If not closing: {adj_summary}.")
    elif position_status == "breached":
        commentary_parts.append(
            f"{ticker} — BREACHED. Price has moved past a short strike. "
            f"Regime is {regime_name} ({regime.confidence:.0%}). "
        )
        if adj_summary:
            commentary_parts.append(f"Recommended: {adj_summary}.")
        else:
            commentary_parts.append("Consider closing to cap losses.")
    elif position_status == "tested":
        commentary_parts.append(
            f"{ticker} — TESTED. Price approaching a short strike. "
            f"Regime: {regime_name}. "
        )
        if adj_summary:
            commentary_parts.append(f"Consider: {adj_summary}.")
        else:
            commentary_parts.append("Monitor closely — may need adjustment soon.")
    else:
        commentary_parts.append(exit_result.commentary)
        commentary_parts.append(f"Regime: {regime_name} ({regime.confidence:.0%}).")

    # Add overnight risk to commentary if assessed
    if overnight_result is not None:
        if overnight_result.risk_level == OvernightRiskLevel.CLOSE_BEFORE_CLOSE:
            commentary_parts.append(
                f"OVERNIGHT: {overnight_result.summary} — close before market close."
            )
        elif overnight_result.risk_level == OvernightRiskLevel.HIGH:
            commentary_parts.append(
                f"OVERNIGHT WARNING: {overnight_result.summary}"
            )

    return TradeHealthCheck(
        trade_id=trade_id,
        ticker=ticker,
        status=status,
        exit_result=exit_result,
        adjustment_needed=adjustment_needed,
        adjustment_summary=adj_summary,
        adjustment_options=adj_options,
        overall_action=overall_action,
        summary=" | ".join(parts),
        commentary=" ".join(commentary_parts),
        overnight_risk=overnight_result,
    )


def get_adjustment_recommendation(
    trade_spec: TradeSpec,
    regime: RegimeResult,
    technicals: TechnicalSnapshot,
    vol_surface: VolatilitySurface | None = None,
    quote_service: object | None = None,
) -> AdjustmentAnalysis:
    """Get adjustment recommendations for an open trade.

    Thin wrapper around AdjustmentService.analyze() for eTrading API consistency.

    Args:
        trade_spec: The original TradeSpec.
        regime: Current RegimeResult.
        technicals: Current TechnicalSnapshot.
        vol_surface: Optional vol surface for roll pricing.
        quote_service: Optional OptionQuoteService for real prices.

    Returns:
        AdjustmentAnalysis with ranked adjustment options.
    """
    from market_analyzer.service.adjustment import AdjustmentService

    adj_svc = AdjustmentService(quote_service=quote_service)
    return adj_svc.analyze(
        trade_spec=trade_spec,
        regime=regime,
        technicals=technicals,
        vol_surface=vol_surface,
    )


# ── Overnight Risk Assessment ──


class OvernightRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CLOSE_BEFORE_CLOSE = "close_before_close"


class OvernightRisk(BaseModel):
    """Assessment of overnight gap risk for an open position."""

    trade_id: str
    ticker: str
    risk_level: OvernightRiskLevel
    reasons: list[str]
    summary: str


# Ordering for max() comparison — higher index = worse risk.
_RISK_ORDER: list[OvernightRiskLevel] = [
    OvernightRiskLevel.LOW,
    OvernightRiskLevel.MEDIUM,
    OvernightRiskLevel.HIGH,
    OvernightRiskLevel.CLOSE_BEFORE_CLOSE,
]


def _worst_risk(a: OvernightRiskLevel, b: OvernightRiskLevel) -> OvernightRiskLevel:
    """Return the worse of two risk levels."""
    return a if _RISK_ORDER.index(a) >= _RISK_ORDER.index(b) else b


def assess_overnight_risk(
    trade_id: str,
    ticker: str,
    structure_type: str,
    order_side: str,
    dte_remaining: int,
    regime_id: int,
    position_status: str,  # "safe", "tested", "breached"
    has_earnings_tomorrow: bool = False,
    has_macro_event_tomorrow: bool = False,
) -> OvernightRisk:
    """Assess overnight gap risk for a position. Call at ~15:30.

    Rules:
    - 0DTE: always CLOSE_BEFORE_CLOSE (expires today)
    - BREACHED + R4: CLOSE_BEFORE_CLOSE
    - BREACHED + any regime: HIGH
    - TESTED + R4: CLOSE_BEFORE_CLOSE
    - TESTED + R3: HIGH
    - Earnings tomorrow: HIGH (min)
    - Macro event tomorrow (FOMC/CPI/NFP): MEDIUM (min)
    - SAFE + R1/R2: LOW
    - Everything else: MEDIUM
    """
    risk = OvernightRiskLevel.LOW
    reasons: list[str] = []

    # 0DTE — must close, expires today
    if dte_remaining == 0:
        risk = _worst_risk(risk, OvernightRiskLevel.CLOSE_BEFORE_CLOSE)
        reasons.append("0DTE — position expires today, cannot hold overnight")
        return OvernightRisk(
            trade_id=trade_id,
            ticker=ticker,
            risk_level=risk,
            reasons=reasons,
            summary=f"{ticker}: CLOSE BEFORE CLOSE — 0DTE expires today",
        )

    # Position status + regime interactions
    if position_status == "breached":
        if regime_id == 4:
            risk = _worst_risk(risk, OvernightRiskLevel.CLOSE_BEFORE_CLOSE)
            reasons.append("Breached position in R4 (high-vol trending) — extreme overnight gap risk")
        else:
            risk = _worst_risk(risk, OvernightRiskLevel.HIGH)
            reasons.append(f"Breached position in R{regime_id} — high overnight gap risk")
    elif position_status == "tested":
        if regime_id == 4:
            risk = _worst_risk(risk, OvernightRiskLevel.CLOSE_BEFORE_CLOSE)
            reasons.append("Tested position in R4 (high-vol trending) — likely to breach overnight")
        elif regime_id == 3:
            risk = _worst_risk(risk, OvernightRiskLevel.HIGH)
            reasons.append("Tested position in R3 (low-vol trending) — trend may continue overnight")
        else:
            risk = _worst_risk(risk, OvernightRiskLevel.MEDIUM)
            reasons.append(f"Tested position in R{regime_id} — monitor overnight")
    else:
        # Safe position
        if regime_id in (1, 2):
            # LOW stays as default
            reasons.append(f"Safe position in R{regime_id} (mean-reverting) — low overnight risk")
        else:
            risk = _worst_risk(risk, OvernightRiskLevel.MEDIUM)
            reasons.append(f"Safe position in R{regime_id} (trending) — moderate overnight risk")

    # Earnings tomorrow — at least HIGH
    if has_earnings_tomorrow:
        risk = _worst_risk(risk, OvernightRiskLevel.HIGH)
        reasons.append("Earnings tomorrow — expect gap risk")

    # Macro event tomorrow — at least MEDIUM
    if has_macro_event_tomorrow:
        risk = _worst_risk(risk, OvernightRiskLevel.MEDIUM)
        reasons.append("Macro event tomorrow (FOMC/CPI/NFP) — volatility expected")

    # Build summary
    level_labels = {
        OvernightRiskLevel.LOW: "LOW",
        OvernightRiskLevel.MEDIUM: "MEDIUM",
        OvernightRiskLevel.HIGH: "HIGH",
        OvernightRiskLevel.CLOSE_BEFORE_CLOSE: "CLOSE BEFORE CLOSE",
    }
    label = level_labels[risk]
    summary = f"{ticker}: {label} — {reasons[0]}" if reasons else f"{ticker}: {label}"

    return OvernightRisk(
        trade_id=trade_id,
        ticker=ticker,
        risk_level=risk,
        reasons=reasons,
        summary=summary,
    )


def recommend_adjustment_action(
    trade_spec: TradeSpec,
    regime: RegimeResult,
    technicals: TechnicalSnapshot,
    vol_surface: VolatilitySurface | None = None,
    quote_service: object | None = None,
) -> AdjustmentDecision:
    """Get a single deterministic adjustment action for systematic trading.

    Thin wrapper around AdjustmentService.recommend_action() for eTrading API
    consistency. Unlike get_adjustment_recommendation() which returns a ranked
    menu, this returns exactly ONE action chosen by a deterministic decision
    tree based on position status and regime.

    Args:
        trade_spec: The original TradeSpec.
        regime: Current RegimeResult.
        technicals: Current TechnicalSnapshot.
        vol_surface: Optional vol surface for roll pricing.
        quote_service: Optional OptionQuoteService for real prices.

    Returns:
        AdjustmentDecision with exactly one action.
    """
    from market_analyzer.service.adjustment import AdjustmentService

    adj_svc = AdjustmentService(quote_service=quote_service)
    return adj_svc.recommend_action(
        trade_spec=trade_spec,
        regime=regime,
        technicals=technicals,
        vol_surface=vol_surface,
    )
