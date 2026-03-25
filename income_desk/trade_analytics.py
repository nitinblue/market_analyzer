"""Trade analytics — P&L, structure risk, portfolio analytics, circuit breakers.

Pure-computation functions for eTrading to call instead of doing calculations
inline. Every function is stateless: no I/O, no broker calls, no side effects.

Mark-to-market functions (get_current_prices, mark_positions_to_market) are the
exception — they accept optional broker/data providers for price fetching.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from income_desk.broker.base import MarketDataProvider
    from income_desk.data import DataService
    from income_desk.models.feedback import TradeOutcome
    from income_desk.models.opportunity import LegSpec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models — P&L Attribution
# ---------------------------------------------------------------------------

class PnLAttribution(BaseModel):
    """Greek-based P&L decomposition via Taylor expansion."""

    delta_pnl: float
    gamma_pnl: float
    theta_pnl: float
    vega_pnl: float
    model_pnl: float
    actual_pnl: float
    unexplained_pnl: float
    underlying_change: float
    iv_change: float
    days_elapsed: float


# ---------------------------------------------------------------------------
# Models — Trade P&L
# ---------------------------------------------------------------------------

class LegPnLInput(BaseModel):
    """Input for a single leg's P&L calculation."""

    quantity: int  # signed: +1 long, -1 short
    entry_price: float  # price when trade was opened
    current_price: float  # price right now
    open_price: float  # price at today's market open
    multiplier: int = 100


class LegPnL(BaseModel):
    """P&L result for a single leg."""

    pnl_inception: float
    pnl_today: float
    entry_price: float
    current_price: float
    open_price: float
    quantity: int


class TradePnL(BaseModel):
    """Aggregated P&L for a multi-leg trade."""

    pnl_inception: float
    pnl_inception_pct: float
    pnl_today: float
    pnl_today_pct: float
    entry_cost: float
    current_value: float
    open_value: float
    legs: list[LegPnL]


# ---------------------------------------------------------------------------
# Models — Structure Risk
# ---------------------------------------------------------------------------

class StructureRisk(BaseModel):
    """Max profit, max loss, breakevens, risk/reward for any structure."""

    max_profit: float | None  # None = unlimited
    max_loss: float | None  # None = unlimited
    breakeven_low: float | None
    breakeven_high: float | None
    risk_reward_ratio: float | None
    wing_width: float | None
    risk_profile: str  # "defined" or "undefined"
    strategy_label: str


# ---------------------------------------------------------------------------
# Models — Portfolio Analytics
# ---------------------------------------------------------------------------

class PositionSnapshot(BaseModel):
    """Snapshot of a single position for portfolio aggregation."""

    ticker: str
    structure_type: str = "unknown"
    entry_price: float = 0
    current_price: float = 0
    open_price: float = 0  # value at today's market open
    quantity: int = 1
    multiplier: int = 100
    delta: float = 0
    gamma: float = 0
    theta: float = 0
    vega: float = 0
    underlying_price: float = 0
    max_loss: float | None = None


class UnderlyingExposure(BaseModel):
    """Aggregated Greek exposure for a single underlying."""

    ticker: str
    net_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float
    delta_dollars: float
    pnl_inception: float
    pnl_today: float
    position_count: int


class PortfolioAnalytics(BaseModel):
    """Full portfolio-level analytics."""

    total_pnl_inception: float
    total_pnl_today: float
    total_pnl_pct: float
    net_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float
    delta_dollars: float
    theta_dollars_per_day: float
    total_margin_at_risk: float
    margin_utilization_pct: float
    by_underlying: dict[str, UnderlyingExposure]


# ---------------------------------------------------------------------------
# Models — Performance Ledger
# ---------------------------------------------------------------------------

class PerformanceLedger(BaseModel):
    """Comprehensive trade performance statistics."""

    total_trades: int
    total_pnl: float
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float
    cagr_pct: float | None
    mar_ratio: float | None
    max_consecutive_wins: int
    max_consecutive_losses: int
    avg_holding_days: float
    best_trade_pnl: float
    worst_trade_pnl: float
    expectancy_per_trade: float
    current_equity: float
    return_pct: float


# ---------------------------------------------------------------------------
# Models — Circuit Breakers
# ---------------------------------------------------------------------------

class CircuitBreakerConfig(BaseModel):
    """Thresholds for portfolio circuit breakers."""

    daily_loss_pct: float = 2.0
    weekly_loss_pct: float = 5.0
    vix_halt_threshold: float = 35.0
    max_drawdown_pct: float = 10.0
    consecutive_loss_pause: int = 3
    consecutive_loss_halt: int = 5


class BreakerTripped(BaseModel):
    """A single circuit breaker that was triggered."""

    name: str
    threshold: float
    current_value: float
    severity: str  # "pause" or "halt"


class CircuitBreakerResult(BaseModel):
    """Result of circuit breaker evaluation."""

    is_halted: bool
    is_paused: bool
    breakers_tripped: list[BreakerTripped]
    can_open_new: bool
    resume_conditions: list[str]


# =========================================================================
# Function 1: compute_pnl_attribution
# =========================================================================

def compute_pnl_attribution(
    entry_delta: float,
    entry_gamma: float,
    entry_theta: float,
    entry_vega: float,
    underlying_change: float,
    iv_change: float,
    days_elapsed: float,
    actual_pnl: float,
    multiplier: int = 100,
    quantity: int = 1,
) -> PnLAttribution:
    """Greek-based P&L decomposition via Taylor expansion.

    Decomposes observed P&L into delta, gamma, theta, and vega components.
    The unexplained residual captures higher-order effects and model error.

    Args:
        entry_delta: Position delta at entry.
        entry_gamma: Position gamma at entry.
        entry_theta: Position theta at entry (per day).
        entry_vega: Position vega at entry.
        underlying_change: Current underlying price minus entry price.
        iv_change: Current IV minus entry IV in vol points (e.g. 0.03 = 3%).
        days_elapsed: Calendar days since entry.
        actual_pnl: Observed P&L from market prices.
        multiplier: Contract multiplier (default 100).
        quantity: Signed quantity (+1 long, -1 short).

    Returns:
        PnLAttribution with component breakdown and unexplained residual.
    """
    dS = underlying_change
    dIV = iv_change

    delta_pnl = round(entry_delta * dS * multiplier * quantity, 2)
    gamma_pnl = round(0.5 * entry_gamma * dS * dS * multiplier * quantity, 2)
    theta_pnl = round(entry_theta * days_elapsed * multiplier * quantity, 2)
    vega_pnl = round(entry_vega * dIV * multiplier * quantity, 2)
    model_pnl = round(delta_pnl + gamma_pnl + theta_pnl + vega_pnl, 2)
    unexplained_pnl = round(actual_pnl - model_pnl, 2)

    return PnLAttribution(
        delta_pnl=delta_pnl,
        gamma_pnl=gamma_pnl,
        theta_pnl=theta_pnl,
        vega_pnl=vega_pnl,
        model_pnl=model_pnl,
        actual_pnl=round(actual_pnl, 2),
        unexplained_pnl=unexplained_pnl,
        underlying_change=underlying_change,
        iv_change=iv_change,
        days_elapsed=days_elapsed,
    )


# =========================================================================
# Function 2: compute_trade_pnl
# =========================================================================

def compute_trade_pnl(legs: list[LegPnLInput]) -> TradePnL:
    """Compute P&L since inception and since today's market open.

    Aggregates across all legs of a trade structure, providing both
    total-life and intraday P&L with percentage returns.

    Args:
        legs: List of leg inputs with entry/current/open prices.

    Returns:
        TradePnL with per-leg and aggregate P&L.
    """
    leg_results: list[LegPnL] = []
    total_pnl_inception = 0.0
    total_pnl_today = 0.0
    entry_cost = 0.0
    current_value = 0.0
    open_value = 0.0

    for leg in legs:
        leg_pnl_inception = round(
            (leg.current_price - leg.entry_price) * leg.quantity * leg.multiplier, 2
        )
        leg_pnl_today = round(
            (leg.current_price - leg.open_price) * leg.quantity * leg.multiplier, 2
        )
        total_pnl_inception += leg_pnl_inception
        total_pnl_today += leg_pnl_today
        entry_cost += abs(leg.entry_price * leg.quantity * leg.multiplier)
        current_value += abs(leg.current_price * leg.quantity * leg.multiplier)
        open_value += abs(leg.open_price * leg.quantity * leg.multiplier)

        leg_results.append(
            LegPnL(
                pnl_inception=leg_pnl_inception,
                pnl_today=leg_pnl_today,
                entry_price=leg.entry_price,
                current_price=leg.current_price,
                open_price=leg.open_price,
                quantity=leg.quantity,
            )
        )

    total_pnl_inception = round(total_pnl_inception, 2)
    total_pnl_today = round(total_pnl_today, 2)
    entry_cost = round(entry_cost, 2)
    current_value = round(current_value, 2)
    open_value = round(open_value, 2)

    pnl_inception_pct = round(
        total_pnl_inception / entry_cost if entry_cost != 0 else 0.0, 4
    )
    pnl_today_pct = round(
        total_pnl_today / open_value if open_value != 0 else 0.0, 4
    )

    return TradePnL(
        pnl_inception=total_pnl_inception,
        pnl_inception_pct=pnl_inception_pct,
        pnl_today=total_pnl_today,
        pnl_today_pct=pnl_today_pct,
        entry_cost=entry_cost,
        current_value=current_value,
        open_value=open_value,
        legs=leg_results,
    )


# =========================================================================
# Function 3: compute_structure_risk
# =========================================================================

# Structures with defined risk
_DEFINED_RISK: set[str] = {
    "iron_condor",
    "iron_butterfly",
    "iron_man",
    "credit_spread",
    "debit_spread",
    "calendar",
    "diagonal",
    "pmcc",
    "covered_call",
    "cash_secured_put",
    "long_option",
    "double_calendar",
}

# Structures with undefined risk
_UNDEFINED_RISK: set[str] = {
    "strangle",
    "straddle",
    "ratio_spread",
    "equity_short",
    "futures_short",
}


def _classify_legs(
    legs: list[LegSpec],
) -> tuple[list[LegSpec], list[LegSpec], list[LegSpec], list[LegSpec]]:
    """Split legs into short puts, long puts, short calls, long calls."""
    short_puts: list[LegSpec] = []
    long_puts: list[LegSpec] = []
    short_calls: list[LegSpec] = []
    long_calls: list[LegSpec] = []

    for leg in legs:
        is_short = leg.action in ("STO", "STC")
        if leg.option_type == "put":
            if is_short:
                short_puts.append(leg)
            else:
                long_puts.append(leg)
        else:  # call
            if is_short:
                short_calls.append(leg)
            else:
                long_calls.append(leg)

    return short_puts, long_puts, short_calls, long_calls


def _compute_wing_width(
    short_legs: list[LegSpec], long_legs: list[LegSpec]
) -> float | None:
    """Wing width = |short_strike - long_strike| for a vertical spread side."""
    if short_legs and long_legs:
        return abs(short_legs[0].strike - long_legs[0].strike)
    return None


def compute_structure_risk(
    structure_type: str,
    legs: list[LegSpec],
    net_credit_debit: float,
    multiplier: int = 100,
    contracts: int = 1,
    underlying_price: float | None = None,
) -> StructureRisk:
    """Compute max profit, max loss, breakevens, and risk/reward for any structure.

    Args:
        structure_type: Strategy name (iron_condor, credit_spread, etc.).
        legs: Option legs with strike, option_type, action.
        net_credit_debit: Positive = credit received, negative = debit paid.
        multiplier: Contract multiplier (default 100).
        contracts: Number of contracts.
        underlying_price: Current underlying price (needed for some breakevens).

    Returns:
        StructureRisk with max profit/loss, breakevens, and risk profile.
    """
    st = structure_type.lower().replace(" ", "_")
    short_puts, long_puts, short_calls, long_calls = _classify_legs(legs)

    max_profit: float | None = None
    max_loss: float | None = None
    breakeven_low: float | None = None
    breakeven_high: float | None = None
    wing_width: float | None = None
    credit = net_credit_debit  # positive means net credit

    # --- Iron Condor / Iron Butterfly ---
    if st in ("iron_condor", "iron_butterfly"):
        put_wing = _compute_wing_width(short_puts, long_puts)
        call_wing = _compute_wing_width(short_calls, long_calls)
        if put_wing is not None and call_wing is not None:
            wing_width = min(put_wing, call_wing)
        elif put_wing is not None:
            wing_width = put_wing
        elif call_wing is not None:
            wing_width = call_wing

        max_profit = round(credit * multiplier * contracts, 2)
        if wing_width is not None:
            max_loss = round((wing_width - credit) * multiplier * contracts, 2)

        if short_puts:
            breakeven_low = round(short_puts[0].strike - credit, 2)
        if short_calls:
            breakeven_high = round(short_calls[0].strike + credit, 2)

    # --- Credit Spread ---
    elif st == "credit_spread":
        # Could be bull put or bear call
        if short_puts:
            # Bull put credit spread
            wing_width = _compute_wing_width(short_puts, long_puts)
            max_profit = round(credit * multiplier * contracts, 2)
            if wing_width is not None:
                max_loss = round(
                    (wing_width - credit) * multiplier * contracts, 2
                )
            breakeven_low = round(short_puts[0].strike - credit, 2)
        elif short_calls:
            # Bear call credit spread
            wing_width = _compute_wing_width(short_calls, long_calls)
            max_profit = round(credit * multiplier * contracts, 2)
            if wing_width is not None:
                max_loss = round(
                    (wing_width - credit) * multiplier * contracts, 2
                )
            breakeven_high = round(short_calls[0].strike + credit, 2)

    # --- Debit Spread ---
    elif st == "debit_spread":
        debit = abs(credit)
        max_loss = round(debit * multiplier * contracts, 2)

        if long_calls:
            # Bull call debit spread
            wing_width = _compute_wing_width(short_calls, long_calls)
            if wing_width is not None:
                max_profit = round(
                    (wing_width - debit) * multiplier * contracts, 2
                )
            breakeven_low = round(long_calls[0].strike + debit, 2)
        elif long_puts:
            # Bear put debit spread
            wing_width = _compute_wing_width(short_puts, long_puts)
            if wing_width is not None:
                max_profit = round(
                    (wing_width - debit) * multiplier * contracts, 2
                )
            breakeven_high = round(long_puts[0].strike - debit, 2)

    # --- Iron Man (long iron condor / inverse) ---
    elif st == "iron_man":
        debit = abs(credit)
        put_wing = _compute_wing_width(short_puts, long_puts)
        call_wing = _compute_wing_width(short_calls, long_calls)
        if put_wing is not None and call_wing is not None:
            wing_width = min(put_wing, call_wing)
        elif put_wing is not None:
            wing_width = put_wing
        elif call_wing is not None:
            wing_width = call_wing

        max_loss = round(debit * multiplier * contracts, 2)
        if wing_width is not None:
            max_profit = round(
                (wing_width - debit) * multiplier * contracts, 2
            )

        if long_puts:
            breakeven_low = round(long_puts[0].strike + debit, 2)
        if long_calls:
            breakeven_high = round(long_calls[0].strike - debit, 2)

    # --- Strangle / Straddle (credit — naked) ---
    elif st in ("strangle", "straddle") and credit > 0:
        max_profit = round(credit * multiplier * contracts, 2)
        max_loss = None  # unlimited

        if short_puts:
            breakeven_low = round(short_puts[0].strike - credit, 2)
        if short_calls:
            breakeven_high = round(short_calls[0].strike + credit, 2)

    # --- Strangle / Straddle (debit — long) ---
    elif st in ("strangle", "straddle") and credit <= 0:
        debit = abs(credit)
        max_loss = round(debit * multiplier * contracts, 2)
        max_profit = None  # unlimited

        if long_puts:
            breakeven_low = round(long_puts[0].strike - debit, 2)
        if long_calls:
            breakeven_high = round(long_calls[0].strike + debit, 2)

    # --- Long Option ---
    elif st == "long_option":
        debit = abs(credit)
        max_loss = round(debit * multiplier * contracts, 2)

        if long_calls:
            max_profit = None  # unlimited upside
            breakeven_low = round(long_calls[0].strike + debit, 2)
        elif long_puts:
            # Max profit = strike × multiplier × contracts - premium
            max_profit = round(
                (long_puts[0].strike - debit) * multiplier * contracts, 2
            )
            breakeven_high = round(long_puts[0].strike - debit, 2)

    # --- Cash-Secured Put ---
    elif st == "cash_secured_put":
        max_profit = round(credit * multiplier * contracts, 2)
        if short_puts:
            # Max loss = (strike - credit) × mult × contracts (stock goes to 0)
            max_loss = round(
                (short_puts[0].strike - credit) * multiplier * contracts, 2
            )
            breakeven_low = round(short_puts[0].strike - credit, 2)

    # --- Covered Call ---
    elif st == "covered_call":
        max_profit = round(credit * multiplier * contracts, 2)
        if short_calls and underlying_price is not None:
            # Add upside from stock to short call strike
            upside = short_calls[0].strike - underlying_price
            max_profit = round(
                (credit + upside) * multiplier * contracts, 2
            )
        # Max loss is stock going to 0 minus premium received
        if underlying_price is not None:
            max_loss = round(
                (underlying_price - credit) * multiplier * contracts, 2
            )
        breakeven_low = round(
            (underlying_price - credit) if underlying_price else 0, 2
        )

    # --- Jade Lizard ---
    elif st == "jade_lizard":
        # Short put + short call spread; no upside risk
        put_credit = credit  # simplified — full net credit
        max_profit = round(credit * multiplier * contracts, 2)
        call_wing = _compute_wing_width(short_calls, long_calls)
        if call_wing is not None:
            # Max loss on call side eliminated if credit > call wing
            max_loss = round(
                max(call_wing - credit, 0) * multiplier * contracts, 2
            )
        if short_puts:
            breakeven_low = round(short_puts[0].strike - credit, 2)

    # --- PMCC (Poor Man's Covered Call) ---
    elif st == "pmcc":
        debit = abs(credit)
        max_loss = round(debit * multiplier * contracts, 2)
        if long_calls and short_calls:
            wing_width = abs(short_calls[0].strike - long_calls[0].strike)
            max_profit = round(
                (wing_width - debit) * multiplier * contracts, 2
            )
            breakeven_low = round(long_calls[0].strike + debit, 2)

    # --- Calendar / Diagonal / Double Calendar ---
    elif st in ("calendar", "diagonal", "double_calendar"):
        debit = abs(credit) if credit < 0 else 0
        max_loss = round(debit * multiplier * contracts, 2) if debit > 0 else None
        max_profit = None  # depends on IV at expiration
        # Breakevens depend on IV — cannot compute without vol surface

    # --- Ratio Spread ---
    elif st == "ratio_spread":
        max_profit = None  # varies
        max_loss = None  # undefined risk
        if credit > 0:
            max_profit = round(credit * multiplier * contracts, 2)

    # --- Fallback for unrecognized structures ---
    else:
        if credit > 0:
            max_profit = round(credit * multiplier * contracts, 2)
        else:
            max_loss = round(abs(credit) * multiplier * contracts, 2)

    # --- Risk profile classification ---
    risk_profile = "defined" if st in _DEFINED_RISK else "undefined"

    # --- Risk/reward ratio ---
    risk_reward_ratio: float | None = None
    if max_profit is not None and max_loss is not None and max_loss > 0:
        risk_reward_ratio = round(max_profit / max_loss, 4)

    # --- Strategy label ---
    strategy_label = _build_strategy_label(
        st, risk_profile, short_puts, short_calls, long_puts, long_calls, credit
    )

    return StructureRisk(
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven_low=breakeven_low,
        breakeven_high=breakeven_high,
        risk_reward_ratio=risk_reward_ratio,
        wing_width=wing_width,
        risk_profile=risk_profile,
        strategy_label=strategy_label,
    )


def _build_strategy_label(
    st: str,
    risk_profile: str,
    short_puts: list[LegSpec],
    short_calls: list[LegSpec],
    long_puts: list[LegSpec],
    long_calls: list[LegSpec],
    credit: float,
) -> str:
    """Build a human-readable strategy label."""
    risk_tag = "defined risk" if risk_profile == "defined" else "undefined risk"
    side_tag = "credit" if credit > 0 else "debit"

    labels: dict[str, str] = {
        "iron_condor": f"Iron condor · {risk_tag}",
        "iron_butterfly": f"Iron butterfly · {risk_tag}",
        "iron_man": f"Long iron condor · {risk_tag}",
        "strangle": f"Strangle {side_tag} · {risk_tag}",
        "straddle": f"Straddle {side_tag} · {risk_tag}",
        "long_option": "Long option · defined risk",
        "cash_secured_put": "Cash-secured put · defined risk",
        "covered_call": "Covered call · defined risk",
        "jade_lizard": f"Jade lizard · {risk_tag}",
        "pmcc": "PMCC · defined risk",
        "calendar": f"Calendar · {risk_tag}",
        "diagonal": f"Diagonal · {risk_tag}",
        "double_calendar": f"Double calendar · {risk_tag}",
        "ratio_spread": f"Ratio spread · {risk_tag}",
    }

    if st in labels:
        return labels[st]

    # Credit/debit spread — infer direction from legs
    if st == "credit_spread":
        if short_puts:
            return f"Bull put credit spread · {risk_tag}"
        elif short_calls:
            return f"Bear call credit spread · {risk_tag}"
        return f"Credit spread · {risk_tag}"

    if st == "debit_spread":
        if long_calls:
            return f"Bull call debit spread · {risk_tag}"
        elif long_puts:
            return f"Bear put debit spread · {risk_tag}"
        return f"Debit spread · {risk_tag}"

    return f"{st.replace('_', ' ').title()} · {risk_tag}"


# =========================================================================
# Function 4: compute_portfolio_analytics
# =========================================================================

def compute_portfolio_analytics(
    positions: list[PositionSnapshot],
    account_nlv: float,
) -> PortfolioAnalytics:
    """Aggregate portfolio-level analytics from position snapshots.

    Computes net Greeks, dollar exposures, P&L, and margin utilization
    across all positions, with per-underlying breakdown.

    Args:
        positions: List of current position snapshots with Greeks.
        account_nlv: Account net liquidation value.

    Returns:
        PortfolioAnalytics with aggregate and per-underlying breakdown.
    """
    net_delta = 0.0
    net_gamma = 0.0
    net_theta = 0.0
    net_vega = 0.0
    delta_dollars = 0.0
    theta_dollars = 0.0
    total_pnl_inception = 0.0
    total_pnl_today = 0.0
    total_margin = 0.0
    total_entry_cost = 0.0

    by_underlying: dict[str, UnderlyingExposure] = {}

    for pos in positions:
        qty = pos.quantity

        # Aggregate Greeks
        net_delta += pos.delta * qty
        net_gamma += pos.gamma * qty
        net_theta += pos.theta * qty
        net_vega += pos.vega * qty

        # Dollar exposures
        pos_delta_dollars = pos.delta * qty * pos.underlying_price
        delta_dollars += pos_delta_dollars
        theta_dollars += pos.theta * qty * pos.multiplier

        # P&L
        pos_pnl_inception = (pos.current_price - pos.entry_price) * qty * pos.multiplier
        pos_pnl_today = (pos.current_price - pos.open_price) * qty * pos.multiplier
        total_pnl_inception += pos_pnl_inception
        total_pnl_today += pos_pnl_today

        # Margin
        if pos.max_loss is not None:
            total_margin += pos.max_loss

        # Entry cost for pct calc
        total_entry_cost += abs(pos.entry_price * qty * pos.multiplier)

        # Per-underlying grouping
        ticker = pos.ticker
        if ticker not in by_underlying:
            by_underlying[ticker] = UnderlyingExposure(
                ticker=ticker,
                net_delta=0.0,
                net_gamma=0.0,
                net_theta=0.0,
                net_vega=0.0,
                delta_dollars=0.0,
                pnl_inception=0.0,
                pnl_today=0.0,
                position_count=0,
            )

        exp = by_underlying[ticker]
        by_underlying[ticker] = UnderlyingExposure(
            ticker=ticker,
            net_delta=round(exp.net_delta + pos.delta * qty, 4),
            net_gamma=round(exp.net_gamma + pos.gamma * qty, 4),
            net_theta=round(exp.net_theta + pos.theta * qty, 4),
            net_vega=round(exp.net_vega + pos.vega * qty, 4),
            delta_dollars=round(exp.delta_dollars + pos_delta_dollars, 2),
            pnl_inception=round(exp.pnl_inception + pos_pnl_inception, 2),
            pnl_today=round(exp.pnl_today + pos_pnl_today, 2),
            position_count=exp.position_count + 1,
        )

    total_pnl_pct = round(
        total_pnl_inception / total_entry_cost if total_entry_cost > 0 else 0.0, 4
    )
    margin_util = round(
        total_margin / account_nlv if account_nlv > 0 else 0.0, 4
    )

    return PortfolioAnalytics(
        total_pnl_inception=round(total_pnl_inception, 2),
        total_pnl_today=round(total_pnl_today, 2),
        total_pnl_pct=total_pnl_pct,
        net_delta=round(net_delta, 4),
        net_gamma=round(net_gamma, 4),
        net_theta=round(net_theta, 4),
        net_vega=round(net_vega, 4),
        delta_dollars=round(delta_dollars, 2),
        theta_dollars_per_day=round(theta_dollars, 2),
        total_margin_at_risk=round(total_margin, 2),
        margin_utilization_pct=margin_util,
        by_underlying=by_underlying,
    )


# =========================================================================
# Function 5: compute_performance_ledger
# =========================================================================

def compute_performance_ledger(
    outcomes: list[TradeOutcome],
    initial_capital: float,
    risk_free_rate: float = 0.05,
) -> PerformanceLedger:
    """Compute comprehensive performance statistics from trade outcomes.

    Uses income_desk.performance for Sharpe and drawdown calculations.
    All other metrics computed inline.

    Args:
        outcomes: Completed trade outcomes sorted by exit_date.
        initial_capital: Starting capital for CAGR and equity calculations.
        risk_free_rate: Annual risk-free rate as decimal (0.05 = 5%).

    Returns:
        PerformanceLedger with win rate, profit factor, Sharpe, drawdown, etc.
    """
    from income_desk.performance import compute_drawdown, compute_sharpe

    if not outcomes:
        return PerformanceLedger(
            total_trades=0,
            total_pnl=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            sharpe_ratio=0.0,
            max_drawdown_pct=0.0,
            cagr_pct=None,
            mar_ratio=None,
            max_consecutive_wins=0,
            max_consecutive_losses=0,
            avg_holding_days=0.0,
            best_trade_pnl=0.0,
            worst_trade_pnl=0.0,
            expectancy_per_trade=0.0,
            current_equity=initial_capital,
            return_pct=0.0,
        )

    total_trades = len(outcomes)
    wins = [o for o in outcomes if o.pnl_dollars > 0]
    losses = [o for o in outcomes if o.pnl_dollars <= 0]

    total_pnl = round(sum(o.pnl_dollars for o in outcomes), 2)
    win_rate = round(len(wins) / total_trades, 4)

    # Profit factor
    gross_profit = sum(w.pnl_dollars for w in wins)
    gross_loss = abs(sum(lo.pnl_dollars for lo in losses))
    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 4)
    else:
        profit_factor = 999.99 if gross_profit > 0 else 0.0

    # Sharpe via existing module
    sharpe_result = compute_sharpe(outcomes, risk_free_rate=risk_free_rate)
    sharpe_ratio = sharpe_result.sharpe_ratio

    # Drawdown via existing module
    dd_result = compute_drawdown(outcomes)
    max_drawdown_pct = dd_result.max_drawdown_pct

    # Max consecutive wins/losses
    sorted_outcomes = sorted(outcomes, key=lambda o: o.exit_date)
    max_con_wins = 0
    max_con_losses = 0
    cur_wins = 0
    cur_losses = 0
    for o in sorted_outcomes:
        if o.pnl_dollars > 0:
            cur_wins += 1
            cur_losses = 0
            max_con_wins = max(max_con_wins, cur_wins)
        else:
            cur_losses += 1
            cur_wins = 0
            max_con_losses = max(max_con_losses, cur_losses)

    # Holding days
    avg_holding = round(
        sum(o.holding_days for o in outcomes) / total_trades, 2
    )

    # Best / worst
    pnls = [o.pnl_dollars for o in outcomes]
    best_trade = round(max(pnls), 2)
    worst_trade = round(min(pnls), 2)

    # Expectancy
    expectancy = round(total_pnl / total_trades, 2)

    # Equity / return
    current_equity = round(initial_capital + total_pnl, 2)
    return_pct = round(
        total_pnl / initial_capital if initial_capital > 0 else 0.0, 4
    )

    # CAGR
    cagr_pct: float | None = None
    if sorted_outcomes and len(sorted_outcomes) >= 2:
        first_date = sorted_outcomes[0].entry_date
        last_date = sorted_outcomes[-1].exit_date
        total_days = (last_date - first_date).days
        if total_days >= 365 and current_equity > 0 and initial_capital > 0:
            cagr_pct = round(
                ((current_equity / initial_capital) ** (365.25 / total_days) - 1)
                * 100,
                4,
            )

    # MAR ratio
    mar_ratio: float | None = None
    if cagr_pct is not None and cagr_pct > 0 and max_drawdown_pct > 0:
        mar_ratio = round(cagr_pct / max_drawdown_pct, 4)

    return PerformanceLedger(
        total_trades=total_trades,
        total_pnl=total_pnl,
        win_rate=win_rate,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe_ratio,
        max_drawdown_pct=max_drawdown_pct,
        cagr_pct=cagr_pct,
        mar_ratio=mar_ratio,
        max_consecutive_wins=max_con_wins,
        max_consecutive_losses=max_con_losses,
        avg_holding_days=avg_holding,
        best_trade_pnl=best_trade,
        worst_trade_pnl=worst_trade,
        expectancy_per_trade=expectancy,
        current_equity=current_equity,
        return_pct=return_pct,
    )


# =========================================================================
# Function 6: evaluate_circuit_breakers
# =========================================================================

def evaluate_circuit_breakers(
    daily_pnl_pct: float,
    weekly_pnl_pct: float,
    vix: float | None = None,
    portfolio_drawdown_pct: float = 0,
    consecutive_losses: int = 0,
    config: CircuitBreakerConfig | None = None,
) -> CircuitBreakerResult:
    """Evaluate portfolio circuit breakers against current conditions.

    Checks daily/weekly loss limits, VIX threshold, drawdown, and
    consecutive losses. Returns halt/pause status with resume conditions.

    Args:
        daily_pnl_pct: Today's P&L as percentage (negative = loss).
        weekly_pnl_pct: This week's P&L as percentage (negative = loss).
        vix: Current VIX level (None if unavailable).
        portfolio_drawdown_pct: Current drawdown from peak as positive pct.
        consecutive_losses: Number of consecutive losing trades.
        config: Breaker thresholds (uses defaults if None).

    Returns:
        CircuitBreakerResult with halt/pause status and resume conditions.
    """
    if config is None:
        config = CircuitBreakerConfig()

    tripped: list[BreakerTripped] = []
    resume: list[str] = []

    # Daily loss check
    if daily_pnl_pct < -config.daily_loss_pct:
        tripped.append(
            BreakerTripped(
                name="daily_loss",
                threshold=config.daily_loss_pct,
                current_value=abs(daily_pnl_pct),
                severity="halt",
            )
        )
        resume.append(
            f"Daily loss ({abs(daily_pnl_pct):.1f}%) exceeds "
            f"{config.daily_loss_pct:.1f}% limit — resume tomorrow"
        )

    # Weekly loss check
    if weekly_pnl_pct < -config.weekly_loss_pct:
        tripped.append(
            BreakerTripped(
                name="weekly_loss",
                threshold=config.weekly_loss_pct,
                current_value=abs(weekly_pnl_pct),
                severity="halt",
            )
        )
        resume.append(
            f"Weekly loss ({abs(weekly_pnl_pct):.1f}%) exceeds "
            f"{config.weekly_loss_pct:.1f}% limit — resume next week"
        )

    # VIX halt
    if vix is not None and vix > config.vix_halt_threshold:
        tripped.append(
            BreakerTripped(
                name="vix_halt",
                threshold=config.vix_halt_threshold,
                current_value=vix,
                severity="halt",
            )
        )
        resume.append(
            f"VIX ({vix:.1f}) above {config.vix_halt_threshold:.0f} "
            f"— resume when VIX drops below threshold"
        )

    # Max drawdown
    if portfolio_drawdown_pct > config.max_drawdown_pct:
        tripped.append(
            BreakerTripped(
                name="max_drawdown",
                threshold=config.max_drawdown_pct,
                current_value=portfolio_drawdown_pct,
                severity="halt",
            )
        )
        resume.append(
            f"Drawdown ({portfolio_drawdown_pct:.1f}%) exceeds "
            f"{config.max_drawdown_pct:.1f}% limit — manual review required"
        )

    # Consecutive loss halt (check before pause — halt takes precedence)
    if consecutive_losses >= config.consecutive_loss_halt:
        tripped.append(
            BreakerTripped(
                name="consecutive_loss_halt",
                threshold=float(config.consecutive_loss_halt),
                current_value=float(consecutive_losses),
                severity="halt",
            )
        )
        resume.append(
            f"{consecutive_losses} consecutive losses (halt at "
            f"{config.consecutive_loss_halt}) — manual review required"
        )
    elif consecutive_losses >= config.consecutive_loss_pause:
        tripped.append(
            BreakerTripped(
                name="consecutive_loss_pause",
                threshold=float(config.consecutive_loss_pause),
                current_value=float(consecutive_losses),
                severity="pause",
            )
        )
        resume.append(
            f"{consecutive_losses} consecutive losses (pause at "
            f"{config.consecutive_loss_pause}) — reduce size or wait for next win"
        )

    is_halted = any(b.severity == "halt" for b in tripped)
    is_paused = not is_halted and any(b.severity == "pause" for b in tripped)
    can_open_new = not is_halted and not is_paused

    return CircuitBreakerResult(
        is_halted=is_halted,
        is_paused=is_paused,
        breakers_tripped=tripped,
        can_open_new=can_open_new,
        resume_conditions=resume,
    )


# ---------------------------------------------------------------------------
# Models — Mark-to-Market
# ---------------------------------------------------------------------------


class PriceResult(BaseModel):
    """Current price for a single ticker with provenance."""

    ticker: str
    price: float
    source: str  # "broker_live", "yfinance_delayed", "unavailable"
    trust: str  # "HIGH", "LOW", "NONE"


class PositionInput(BaseModel):
    """Input for marking a single position to market."""

    trade_id: str
    ticker: str
    entry_price: float
    quantity: int
    multiplier: int = 100  # 100 for options, 1 for equity
    structure_type: str = ""


class MarkedPosition(BaseModel):
    """A single position after mark-to-market."""

    trade_id: str
    ticker: str
    entry_price: float
    current_price: float
    pnl: float
    pnl_pct: float
    data_source: str
    trust: str


class MarkedPositions(BaseModel):
    """Aggregate result of marking all positions to market."""

    positions: list[MarkedPosition]
    total_pnl: float
    tickers_marked: int
    tickers_failed: int
    overall_trust: str  # worst trust across all positions


# ---------------------------------------------------------------------------
# Functions — Mark-to-Market
# ---------------------------------------------------------------------------

_TRUST_ORDER = {"NONE": 0, "LOW": 1, "HIGH": 2}


def get_current_prices(
    tickers: list[str],
    market_data: MarketDataProvider | None = None,
    data_service: DataService | None = None,
) -> dict[str, PriceResult]:
    """Fetch current prices for a list of tickers.

    Resolution order per ticker:
    1. ``market_data.get_underlying_price()`` → broker_live / HIGH
    2. ``data_service.get_ohlcv()`` last Close → yfinance_delayed / LOW
    3. Fallback → price=0 / unavailable / NONE
    """
    results: dict[str, PriceResult] = {}

    for ticker in tickers:
        # Already resolved (duplicate in list)
        if ticker in results:
            continue

        # 1. Try broker live price
        if market_data is not None:
            try:
                price = market_data.get_underlying_price(ticker)
                if price is not None and price > 0:
                    results[ticker] = PriceResult(
                        ticker=ticker,
                        price=price,
                        source="broker_live",
                        trust="HIGH",
                    )
                    continue
            except Exception:
                logger.debug("Broker price fetch failed for %s", ticker)

        # 2. Try yfinance delayed (last close)
        if data_service is not None:
            try:
                df = data_service.get_ohlcv(ticker)
                if df is not None and not df.empty:
                    last_close = float(df["Close"].iloc[-1])
                    if last_close > 0:
                        results[ticker] = PriceResult(
                            ticker=ticker,
                            price=last_close,
                            source="yfinance_delayed",
                            trust="LOW",
                        )
                        continue
            except Exception:
                logger.debug("yfinance price fetch failed for %s", ticker)

        # 3. Unavailable
        results[ticker] = PriceResult(
            ticker=ticker,
            price=0,
            source="unavailable",
            trust="NONE",
        )

    return results


def mark_positions_to_market(
    positions: list[PositionInput],
    market_data: MarketDataProvider | None = None,
    data_service: DataService | None = None,
) -> MarkedPositions:
    """Mark a list of positions to market using best-available prices.

    PnL = (current_price - entry_price) * quantity * multiplier.
    For equity (multiplier=1) this simplifies to (current - entry) * quantity.
    """
    if not positions:
        return MarkedPositions(
            positions=[],
            total_pnl=0.0,
            tickers_marked=0,
            tickers_failed=0,
            overall_trust="NONE",
        )

    # Collect unique tickers and fetch prices once
    unique_tickers = list({p.ticker for p in positions})
    prices = get_current_prices(unique_tickers, market_data, data_service)

    marked: list[MarkedPosition] = []
    total_pnl = 0.0
    tickers_failed = 0
    worst_trust = "HIGH"

    failed_tickers: set[str] = set()
    seen_tickers: set[str] = set()

    for pos in positions:
        pr = prices[pos.ticker]
        pnl = (pr.price - pos.entry_price) * pos.quantity * pos.multiplier
        pnl_pct = (
            ((pr.price - pos.entry_price) / pos.entry_price * 100.0)
            if pos.entry_price != 0
            else 0.0
        )

        marked.append(
            MarkedPosition(
                trade_id=pos.trade_id,
                ticker=pos.ticker,
                entry_price=pos.entry_price,
                current_price=pr.price,
                pnl=pnl,
                pnl_pct=pnl_pct,
                data_source=pr.source,
                trust=pr.trust,
            )
        )
        total_pnl += pnl

        # Track worst trust
        if _TRUST_ORDER.get(pr.trust, 0) < _TRUST_ORDER.get(worst_trust, 0):
            worst_trust = pr.trust

        # Track failed tickers (count unique)
        if pr.source == "unavailable" and pos.ticker not in failed_tickers:
            failed_tickers.add(pos.ticker)
        seen_tickers.add(pos.ticker)

    tickers_marked = len(seen_tickers) - len(failed_tickers)
    tickers_failed = len(failed_tickers)

    return MarkedPositions(
        positions=marked,
        total_pnl=total_pnl,
        tickers_marked=tickers_marked,
        tickers_failed=tickers_failed,
        overall_trust=worst_trust,
    )
