"""Portfolio Risk Management APIs — pure computation for eTrading.

Seven risk management functions covering every dimension of portfolio risk:

    RM1: compute_portfolio_var()           — Value at Risk from positions + ATR + regime
    RM2: check_portfolio_greeks()          — Net Greeks vs limits
    RM3: check_strategy_concentration()    — Too many of same strategy type
    RM4: check_directional_concentration() — Net bullish/bearish exposure
    RM5: check_correlation_risk()          — Correlated positions
    RM6: check_drawdown_circuit_breaker()  — Halt if drawdown > threshold
    RM7: compute_risk_dashboard()          — Everything combined

Every function takes inputs and returns results. No state, no broker calls,
no data fetching. eTrading provides the data, market_analyzer computes the answer.
"""

from __future__ import annotations

import math
from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    pass


# ── Models ──────────────────────────────────────────────────────────────────


class PortfolioPosition(BaseModel):
    """Position snapshot for risk assessment — richer than OpenPosition.

    eTrading builds this from its portfolio DB + broker Greeks.
    """

    ticker: str
    structure_type: str = "iron_condor"  # "iron_condor", "credit_spread", "equity_long", etc.
    direction: str = "neutral"  # "bullish", "bearish", "neutral"
    sector: str = ""
    max_loss: float = 0  # Max loss in dollars (defined risk)
    buying_power_used: float = 0
    notional_value: float = 0  # Underlying value x lot_size x contracts
    # Greeks (from broker or computed)
    delta: float = 0
    gamma: float = 0
    theta: float = 0
    vega: float = 0
    # Meta
    regime_at_entry: int = 0  # RegimeID at time of entry (0 = unknown)
    dte_remaining: int = 0
    current_pnl_pct: float = 0  # Current P&L as % of max profit


class PortfolioGreeks(BaseModel):
    """Portfolio-level aggregated Greeks."""

    net_delta: float  # Sum of per-position delta
    net_gamma: float  # Sum of per-position gamma
    net_theta: float  # Daily time decay (positive = earning, negative = paying)
    net_vega: float  # IV sensitivity
    theta_dollars_per_day: float  # Net theta in dollars (theta x 100)
    delta_dollars: float  # Dollar exposure from delta (net_delta x avg_price x 100)


class GreeksLimits(BaseModel):
    """Limits on portfolio-level Greeks — eTrading configures per desk."""

    max_abs_delta: float = 50.0  # Max net delta in dollar terms (% of NLV)
    max_abs_theta_pct: float = 0.5  # Max daily theta as % of NLV
    max_abs_vega_pct: float = 1.0  # Max vega exposure as % of NLV
    max_abs_gamma: float = 10.0  # Max gamma (rate of delta change)


class GreeksCheckResult(BaseModel):
    """Result of portfolio Greeks limit check."""

    greeks: PortfolioGreeks
    limits: GreeksLimits
    within_limits: bool
    violations: list[str]  # What limits are breached


class ExpectedLossResult(BaseModel):
    """Estimated portfolio loss — ATR-based, regime-adjusted.

    NOT a formal VaR model. For defined-risk positions, this is simply max_loss.
    For undefined risk, uses ATR × regime factor as expected move estimate.
    Use stress_testing.run_stress_suite() for scenario-specific analysis.
    """

    expected_loss_1d: float     # Expected worst-case 1-day loss (dollars)
    expected_loss_5d: float     # Expected worst-case 5-day loss
    severe_loss_1d: float       # Severe case (99th percentile estimate)
    loss_pct_of_nlv: float      # 1-day expected loss as % of NLV
    total_max_loss: float       # Absolute worst case: sum of all max_loss
    method: str                 # "atr_regime" or "max_loss"
    per_position: list[dict]    # [{ticker, expected_loss, method}, ...]
    commentary: str


# Keep VaRResult as alias for backward compat
VaRResult = ExpectedLossResult


class StrategyConcentration(BaseModel):
    """How concentrated the portfolio is by strategy type."""

    by_strategy: dict[str, int]  # {"iron_condor": 3, "credit_spread": 1}
    dominant_strategy: str | None  # Most common strategy
    dominant_pct: float  # What % of positions is the dominant strategy
    is_concentrated: bool  # >50% in one strategy type
    recommendation: str


class DirectionalExposure(BaseModel):
    """Net directional bias of the portfolio."""

    net_delta_score: float  # -1 (bearish) to +1 (bullish)
    bullish_positions: int
    bearish_positions: int
    neutral_positions: int
    direction: str  # "bullish", "bearish", "neutral", "mixed"
    is_concentrated: bool  # Score magnitude > 0.5
    recommendation: str


class CorrelationRisk(BaseModel):
    """Correlation between open positions."""

    highly_correlated_pairs: list[tuple[str, str, float]]  # (ticker_a, ticker_b, corr)
    effective_positions: float  # Adjusted count after correlation
    diversification_score: float  # 0-1 (1 = fully diversified)
    recommendation: str


class DrawdownStatus(BaseModel):
    """Current drawdown vs circuit breaker threshold."""

    account_peak: float  # Highest NLV ever (or this month)
    current_nlv: float
    drawdown_pct: float  # (peak - current) / peak
    drawdown_dollars: float
    circuit_breaker_pct: float  # Threshold (e.g., 10%)
    is_triggered: bool  # True if drawdown > threshold
    recommendation: str


class RiskDashboard(BaseModel):
    """Complete portfolio risk assessment — the master risk view."""

    as_of_date: date
    account_nlv: float
    # Position risk
    open_positions: int
    max_positions: int
    slots_remaining: int
    portfolio_risk_pct: float  # Total max loss / NLV
    # Greeks
    greeks: PortfolioGreeks | None
    greeks_within_limits: bool
    # VaR
    var: VaRResult | None
    # Concentrations
    strategy_concentration: StrategyConcentration
    directional_exposure: DirectionalExposure
    sector_concentration: dict[str, float]  # sector -> % of risk
    correlation_risk: CorrelationRisk | None
    # Circuit breaker
    drawdown: DrawdownStatus
    # Macro
    macro_regime: str  # From research report
    macro_position_factor: float  # 0-1 scaling
    # Overall
    overall_risk_level: str  # "low", "moderate", "elevated", "high", "critical"
    can_open_new_trades: bool  # Master gate
    max_new_trade_size_pct: float  # Scale factor for any new trade
    alerts: list[str]  # What's wrong
    commentary: list[str]  # Human-readable risk narrative


# ── Regime factors for VaR ──────────────────────────────────────────────────

_REGIME_VAR_FACTORS: dict[int, float] = {
    1: 0.40,  # R1: Low-Vol Mean Reverting — small moves expected
    2: 0.70,  # R2: High-Vol Mean Reverting — larger but bounded
    3: 1.10,  # R3: Low-Vol Trending — persistent directional
    4: 1.50,  # R4: High-Vol Trending — explosive moves
}

# ── Defined-risk structures (max loss is capped) ───────────────────────────

_DEFINED_RISK_STRUCTURES = frozenset({
    "iron_condor", "iron_butterfly", "iron_man",
    "credit_spread", "debit_spread",
    "calendar", "double_calendar",
    "diagonal", "pmcc",
    "long_option", "long_call", "long_put",
})


# ── RM1: Portfolio VaR ─────────────────────────────────────────────────────


def estimate_portfolio_loss(
    positions: list[PortfolioPosition],
    account_nlv: float,
    atr_by_ticker: dict[str, float] | None = None,
    regime_by_ticker: dict[str, int] | None = None,
    correlation_data: dict[tuple[str, str], float] | None = None,
    holding_days: int = 1,
) -> ExpectedLossResult:
    """Estimate expected portfolio loss — ATR-based, regime-adjusted.

    NOT a formal VaR model. This is a practical expected loss estimate:
    - Defined-risk positions: expected loss = max_loss (loss is capped)
    - Undefined risk: expected loss = notional × ATR% × regime_factor × √days
    - Portfolio: correlation-adjusted aggregation

    For scenario-specific analysis, use stress_testing.run_stress_suite().

    Args:
        positions: Current portfolio positions from eTrading.
        account_nlv: Net liquidating value.
        atr_by_ticker: ATR as decimal % per ticker. For undefined-risk positions.
        regime_by_ticker: Regime ID (1-4) per ticker. Defaults to R2.
        correlation_data: Pairwise correlations for aggregation.
        holding_days: Holding period in days (default 1).

    Returns:
        ExpectedLossResult with expected and severe loss estimates.
    """
    if not positions:
        return VaRResult(
            expected_loss_1d=0, expected_loss_5d=0, severe_loss_1d=0,
            loss_pct_of_nlv=0, total_max_loss=0, method="parametric_atr",
            per_position=[], commentary="No open positions.",
        )

    atr_map = atr_by_ticker or {}
    regime_map = regime_by_ticker or {}
    corr_map = correlation_data or {}

    per_position: list[dict] = []
    individual_vars: list[float] = []  # 1-day base VaR per position
    tickers: list[str] = []

    for pos in positions:
        is_defined = pos.structure_type in _DEFINED_RISK_STRUCTURES

        if is_defined and pos.max_loss > 0:
            # Defined risk: VaR = max_loss (worst case is known)
            base_var = pos.max_loss
            method = "max_loss"
        elif pos.notional_value > 0:
            # Undefined risk: parametric estimation
            atr_pct = atr_map.get(pos.ticker, 0.015)  # Default 1.5% if unknown
            regime_id = regime_map.get(pos.ticker, 2)  # Default R2 (conservative)
            regime_factor = _REGIME_VAR_FACTORS.get(regime_id, 0.70)
            base_var = pos.notional_value * atr_pct * regime_factor
            method = "parametric_atr"
        else:
            # Fallback: use max_loss or buying_power as proxy
            base_var = pos.max_loss if pos.max_loss > 0 else pos.buying_power_used
            method = "proxy"

        individual_vars.append(base_var)
        tickers.append(pos.ticker)
        per_position.append({
            "ticker": pos.ticker,
            "structure_type": pos.structure_type,
            "var_1d_95": round(base_var * 1.65, 2),
            "method": method,
        })

    # Portfolio aggregation with correlation
    n = len(individual_vars)
    # Start with sum of squares (diagonal terms)
    portfolio_var_sq = sum(v ** 2 for v in individual_vars)

    # Add cross terms: 2 * rho_ij * var_i * var_j
    for i in range(n):
        for j in range(i + 1, n):
            pair = (tickers[i], tickers[j])
            pair_rev = (tickers[j], tickers[i])
            rho = corr_map.get(pair, corr_map.get(pair_rev, 0.0))
            portfolio_var_sq += 2 * rho * individual_vars[i] * individual_vars[j]

    # Guard against negative due to negative correlations
    portfolio_var_base = math.sqrt(max(portfolio_var_sq, 0))

    # Scale by holding period
    sqrt_days = math.sqrt(max(holding_days, 1))

    var_1d_base = portfolio_var_base
    var_1d_95 = var_1d_base * 1.65
    var_1d_99 = var_1d_base * 2.33
    var_5d_95 = var_1d_95 * math.sqrt(5)

    var_pct = (var_1d_95 / account_nlv * 100) if account_nlv > 0 else 0

    # Commentary
    if var_pct < 2:
        commentary = "Portfolio VaR is conservative. Risk is well-contained."
    elif var_pct < 5:
        commentary = "Portfolio VaR is moderate. Acceptable for income portfolio."
    elif var_pct < 10:
        commentary = "Portfolio VaR is elevated. Consider reducing position sizes."
    else:
        commentary = "Portfolio VaR is HIGH. Reduce exposure immediately."

    total_max_loss = sum(p.max_loss for p in positions if p.max_loss > 0)

    return VaRResult(
        expected_loss_1d=round(var_1d_95, 2),
        expected_loss_5d=round(var_5d_95, 2),
        severe_loss_1d=round(var_1d_99, 2),
        loss_pct_of_nlv=round(var_pct, 2),
        total_max_loss=round(total_max_loss, 2),
        method="parametric_atr",
        per_position=per_position,
        commentary=commentary,
    )


# Backward compat alias
compute_portfolio_var = estimate_portfolio_loss


# ── RM2: Portfolio Greeks Check ─────────────────────────────────────────────


def check_portfolio_greeks(
    positions: list[PortfolioPosition],
    account_nlv: float,
    limits: GreeksLimits = GreeksLimits(),
    avg_underlying_price: float = 0,
) -> GreeksCheckResult:
    """Sum delta, gamma, theta, vega across positions and compare against limits.

    Args:
        positions: Current portfolio positions with Greeks populated.
        account_nlv: Net liquidating value.
        limits: Greeks limits (configurable per desk).
        avg_underlying_price: Average underlying price across positions.
            Used for delta_dollars computation. If 0, computed from notional.

    Returns:
        GreeksCheckResult with aggregated Greeks and violations.
    """
    net_delta = sum(p.delta for p in positions)
    net_gamma = sum(p.gamma for p in positions)
    net_theta = sum(p.theta for p in positions)
    net_vega = sum(p.vega for p in positions)

    # Theta in dollars (theta is per-share, multiply by lot size=100)
    theta_dollars = net_theta * 100

    # Delta dollars: use avg price if provided, else estimate from notional
    if avg_underlying_price > 0:
        delta_dollars = net_delta * avg_underlying_price * 100
    elif positions:
        # Estimate from notional values
        total_notional = sum(p.notional_value for p in positions if p.notional_value > 0)
        delta_dollars = net_delta * (total_notional / max(len(positions), 1))
    else:
        delta_dollars = 0

    greeks = PortfolioGreeks(
        net_delta=round(net_delta, 4),
        net_gamma=round(net_gamma, 6),
        net_theta=round(net_theta, 4),
        net_vega=round(net_vega, 4),
        theta_dollars_per_day=round(theta_dollars, 2),
        delta_dollars=round(delta_dollars, 2),
    )

    violations: list[str] = []

    # Check delta as % of NLV
    if account_nlv > 0:
        delta_pct = abs(delta_dollars) / account_nlv * 100
        if delta_pct > limits.max_abs_delta:
            violations.append(
                f"Delta exposure {delta_pct:.1f}% of NLV exceeds limit {limits.max_abs_delta:.1f}%"
            )

        theta_pct = abs(theta_dollars) / account_nlv * 100
        if theta_pct > limits.max_abs_theta_pct:
            violations.append(
                f"Theta exposure {theta_pct:.2f}% of NLV exceeds limit {limits.max_abs_theta_pct:.2f}%"
            )

        vega_dollars = abs(net_vega) * 100  # vega per 1% IV move
        vega_pct = vega_dollars / account_nlv * 100
        if vega_pct > limits.max_abs_vega_pct:
            violations.append(
                f"Vega exposure {vega_pct:.2f}% of NLV exceeds limit {limits.max_abs_vega_pct:.2f}%"
            )

    if abs(net_gamma) > limits.max_abs_gamma:
        violations.append(
            f"Gamma {abs(net_gamma):.4f} exceeds limit {limits.max_abs_gamma:.4f}"
        )

    return GreeksCheckResult(
        greeks=greeks,
        limits=limits,
        within_limits=len(violations) == 0,
        violations=violations,
    )


# ── RM3: Strategy Concentration ─────────────────────────────────────────────


def check_strategy_concentration(
    positions: list[PortfolioPosition],
    concentration_threshold: float = 0.50,
) -> StrategyConcentration:
    """Check if portfolio is over-concentrated in one strategy type.

    Args:
        positions: Current open positions.
        concentration_threshold: Fraction above which concentration is flagged.
            Default 0.50 (50%).

    Returns:
        StrategyConcentration with breakdown and recommendation.
    """
    if not positions:
        return StrategyConcentration(
            by_strategy={},
            dominant_strategy=None,
            dominant_pct=0,
            is_concentrated=False,
            recommendation="No open positions.",
        )

    by_strategy: dict[str, int] = {}
    for pos in positions:
        st = pos.structure_type
        by_strategy[st] = by_strategy.get(st, 0) + 1

    total = len(positions)
    dominant = max(by_strategy, key=by_strategy.get)  # type: ignore[arg-type]
    dominant_count = by_strategy[dominant]
    dominant_pct = dominant_count / total

    is_concentrated = dominant_pct > concentration_threshold

    if is_concentrated:
        recommendation = (
            f"Over-concentrated in {dominant.replace('_', ' ')} "
            f"({dominant_count}/{total} positions). "
            f"Diversify — add directional or calendar spreads to balance."
        )
    elif len(by_strategy) == 1 and total <= 2:
        recommendation = "Limited positions open. Concentration is acceptable at this size."
    else:
        recommendation = "Strategy mix is diversified."

    return StrategyConcentration(
        by_strategy=by_strategy,
        dominant_strategy=dominant,
        dominant_pct=round(dominant_pct, 2),
        is_concentrated=is_concentrated,
        recommendation=recommendation,
    )


# ── RM4: Directional Concentration ──────────────────────────────────────────


def check_directional_concentration(
    positions: list[PortfolioPosition],
    threshold: float = 0.50,
) -> DirectionalExposure:
    """Check net directional bias of the portfolio.

    Each position gets a direction score: bullish=+1, bearish=-1, neutral=0.
    Net score is averaged across positions.

    Args:
        positions: Current open positions with direction field.
        threshold: Magnitude above which directional concentration is flagged.

    Returns:
        DirectionalExposure with bias assessment and recommendation.
    """
    if not positions:
        return DirectionalExposure(
            net_delta_score=0,
            bullish_positions=0,
            bearish_positions=0,
            neutral_positions=0,
            direction="neutral",
            is_concentrated=False,
            recommendation="No open positions.",
        )

    direction_scores = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}
    total_score = 0.0
    bullish = 0
    bearish = 0
    neutral = 0

    for pos in positions:
        score = direction_scores.get(pos.direction, 0.0)
        total_score += score
        if pos.direction == "bullish":
            bullish += 1
        elif pos.direction == "bearish":
            bearish += 1
        else:
            neutral += 1

    net_score = total_score / len(positions)

    if net_score > threshold:
        direction = "bullish"
        is_concentrated = True
        recommendation = (
            f"Portfolio has bullish bias ({bullish} bullish vs {bearish} bearish). "
            f"Reduce bullish exposure or add neutral income trades."
        )
    elif net_score < -threshold:
        direction = "bearish"
        is_concentrated = True
        recommendation = (
            f"Portfolio has bearish bias ({bearish} bearish vs {bullish} bullish). "
            f"Reduce bearish exposure or add neutral income trades."
        )
    elif abs(net_score) > 0.2:
        direction = "mixed"
        is_concentrated = False
        recommendation = "Slight directional tilt but within acceptable range."
    else:
        direction = "neutral"
        is_concentrated = False
        recommendation = "Portfolio is directionally balanced."

    return DirectionalExposure(
        net_delta_score=round(net_score, 2),
        bullish_positions=bullish,
        bearish_positions=bearish,
        neutral_positions=neutral,
        direction=direction,
        is_concentrated=is_concentrated,
        recommendation=recommendation,
    )


# ── RM5: Correlation Risk ───────────────────────────────────────────────────


def check_correlation_risk(
    positions: list[PortfolioPosition],
    correlation_data: dict[tuple[str, str], float] | None = None,
    high_correlation_threshold: float = 0.85,
) -> CorrelationRisk:
    """Check for highly correlated positions in the portfolio.

    Args:
        positions: Current open positions.
        correlation_data: Dict of (ticker_a, ticker_b) -> correlation.
            eTrading provides this from historical data or MA's cross-market module.
        high_correlation_threshold: Correlation above which pairs are flagged.

    Returns:
        CorrelationRisk with diversification score.
    """
    if not positions or len(positions) < 2:
        return CorrelationRisk(
            highly_correlated_pairs=[],
            effective_positions=float(len(positions)),
            diversification_score=1.0,
            recommendation="Too few positions for correlation analysis." if positions
            else "No open positions.",
        )

    corr_map = correlation_data or {}

    # Find unique tickers
    unique_tickers = list({p.ticker for p in positions})
    n = len(unique_tickers)

    if n < 2:
        return CorrelationRisk(
            highly_correlated_pairs=[],
            effective_positions=float(len(positions)),
            diversification_score=1.0 if n == 1 else 0.0,
            recommendation="All positions on same ticker — no diversification benefit."
            if len(positions) > 1
            else "Single ticker.",
        )

    # Check pairs
    highly_correlated: list[tuple[str, str, float]] = []
    total_corr = 0.0
    pair_count = 0

    for i in range(n):
        for j in range(i + 1, n):
            ta, tb = unique_tickers[i], unique_tickers[j]
            pair = (ta, tb)
            pair_rev = (tb, ta)
            rho = corr_map.get(pair, corr_map.get(pair_rev, 0.0))

            if abs(rho) >= high_correlation_threshold:
                highly_correlated.append((ta, tb, round(rho, 3)))

            total_corr += abs(rho)
            pair_count += 1

    # Average pairwise correlation
    avg_corr = total_corr / max(pair_count, 1)

    # Effective positions = n / (1 + (n-1) * avg_corr)
    # This is the standard diversification ratio
    effective = n / (1 + (n - 1) * avg_corr) if avg_corr < 1 else 1.0
    # Scale by total positions (multiple positions on same ticker count)
    effective_scaled = effective * (len(positions) / max(n, 1))

    diversification_score = min(effective_scaled / max(len(positions), 1), 1.0)

    if highly_correlated:
        pair_strs = [f"{a}/{b} ({c:.2f})" for a, b, c in highly_correlated[:3]]
        recommendation = (
            f"Highly correlated pairs: {', '.join(pair_strs)}. "
            f"These are effectively the same position — "
            f"consider replacing one with an uncorrelated ticker."
        )
    elif diversification_score < 0.5:
        recommendation = "Moderate correlation across positions. Consider adding uncorrelated assets."
    else:
        recommendation = "Portfolio has good diversification across positions."

    return CorrelationRisk(
        highly_correlated_pairs=highly_correlated,
        effective_positions=round(effective_scaled, 1),
        diversification_score=round(diversification_score, 2),
        recommendation=recommendation,
    )


# ── RM6: Drawdown Circuit Breaker ───────────────────────────────────────────


def check_drawdown_circuit_breaker(
    current_nlv: float,
    account_peak: float,
    circuit_breaker_pct: float = 0.10,
) -> DrawdownStatus:
    """Check if account drawdown exceeds circuit breaker threshold.

    Args:
        current_nlv: Current net liquidating value.
        account_peak: Highest NLV recorded (this month or all-time).
        circuit_breaker_pct: Threshold as decimal (0.10 = 10%).

    Returns:
        DrawdownStatus with halt recommendation if triggered.
    """
    if account_peak <= 0:
        return DrawdownStatus(
            account_peak=account_peak,
            current_nlv=current_nlv,
            drawdown_pct=0,
            drawdown_dollars=0,
            circuit_breaker_pct=circuit_breaker_pct,
            is_triggered=False,
            recommendation="No peak value recorded. Cannot compute drawdown.",
        )

    drawdown_dollars = max(account_peak - current_nlv, 0)
    drawdown_pct = drawdown_dollars / account_peak
    is_triggered = drawdown_pct >= circuit_breaker_pct

    if is_triggered:
        recommendation = (
            f"HALT — capital preservation mode. "
            f"Account is down {drawdown_pct:.1%} (${drawdown_dollars:,.0f}) from peak. "
            f"Close losing positions, no new trades until recovery."
        )
    elif drawdown_pct > circuit_breaker_pct * 0.7:
        recommendation = (
            f"WARNING — approaching circuit breaker. "
            f"Down {drawdown_pct:.1%} (${drawdown_dollars:,.0f}) from peak. "
            f"Reduce position sizes and tighten stops."
        )
    elif drawdown_pct > 0.02:
        recommendation = f"Minor drawdown of {drawdown_pct:.1%}. Within normal range."
    else:
        recommendation = "Account near peak. No drawdown concern."

    return DrawdownStatus(
        account_peak=round(account_peak, 2),
        current_nlv=round(current_nlv, 2),
        drawdown_pct=round(drawdown_pct, 4),
        drawdown_dollars=round(drawdown_dollars, 2),
        circuit_breaker_pct=circuit_breaker_pct,
        is_triggered=is_triggered,
        recommendation=recommendation,
    )


# ── RM7: Risk Dashboard (Master View) ───────────────────────────────────────


def compute_risk_dashboard(
    positions: list[PortfolioPosition],
    account_nlv: float,
    account_peak: float,
    max_positions: int = 5,
    greeks_limits: GreeksLimits = GreeksLimits(),
    circuit_breaker_pct: float = 0.10,
    atr_by_ticker: dict[str, float] | None = None,
    regime_by_ticker: dict[str, int] | None = None,
    correlation_data: dict[tuple[str, str], float] | None = None,
    avg_underlying_price: float = 0,
    macro_regime: str = "unknown",
    macro_position_factor: float = 1.0,
) -> RiskDashboard:
    """Compute the complete portfolio risk dashboard.

    Calls all six risk functions and synthesizes into a single view
    with overall risk level, master gate, and actionable alerts.

    Args:
        positions: Current portfolio positions from eTrading.
        account_nlv: Net liquidating value.
        account_peak: Highest NLV recorded.
        max_positions: Maximum allowed positions.
        greeks_limits: Greeks limits (per desk config).
        circuit_breaker_pct: Drawdown threshold.
        atr_by_ticker: ATR as decimal % per ticker.
        regime_by_ticker: Regime ID (1-4) per ticker.
        correlation_data: Pairwise correlation coefficients.
        avg_underlying_price: Average underlying price for delta dollars.
        macro_regime: Current macro regime label.
        macro_position_factor: Position size scaling from macro (0-1).

    Returns:
        RiskDashboard with all risk metrics, alerts, and master gate.
    """
    alerts: list[str] = []
    commentary: list[str] = []

    # ── Position basics ──
    open_count = len(positions)
    slots = max(max_positions - open_count, 0)
    total_max_loss = sum(p.max_loss for p in positions)
    portfolio_risk_pct = (total_max_loss / account_nlv * 100) if account_nlv > 0 else 0

    if portfolio_risk_pct > 25:
        alerts.append(f"Portfolio risk at {portfolio_risk_pct:.0f}% of NLV — exceeds 25% limit")
    if open_count >= max_positions:
        alerts.append(f"At maximum positions ({open_count}/{max_positions})")

    # ── RM1: VaR ──
    var_result: VaRResult | None = None
    if positions:
        var_result = compute_portfolio_var(
            positions=positions,
            account_nlv=account_nlv,
            atr_by_ticker=atr_by_ticker,
            regime_by_ticker=regime_by_ticker,
            correlation_data=correlation_data,
        )
        # VaR alerts removed — use stress scenarios for risk assessment
        commentary.append(var_result.commentary)

    # ── RM2: Greeks ──
    greeks_result: GreeksCheckResult | None = None
    has_greeks = any(
        p.delta != 0 or p.gamma != 0 or p.theta != 0 or p.vega != 0
        for p in positions
    )
    if has_greeks:
        greeks_result = check_portfolio_greeks(
            positions=positions,
            account_nlv=account_nlv,
            limits=greeks_limits,
            avg_underlying_price=avg_underlying_price,
        )
        if not greeks_result.within_limits:
            for v in greeks_result.violations:
                alerts.append(v)

    # ── RM3: Strategy concentration ──
    strategy_conc = check_strategy_concentration(positions)
    if strategy_conc.is_concentrated:
        alerts.append(
            f"Strategy concentration: {strategy_conc.dominant_pct:.0%} in "
            f"{strategy_conc.dominant_strategy}"
        )
        commentary.append(strategy_conc.recommendation)

    # ── RM4: Directional exposure ──
    directional = check_directional_concentration(positions)
    if directional.is_concentrated:
        alerts.append(f"Directional bias: {directional.direction}")
        commentary.append(directional.recommendation)

    # ── RM5: Correlation risk ──
    corr_risk: CorrelationRisk | None = None
    if correlation_data and len(positions) >= 2:
        corr_risk = check_correlation_risk(
            positions=positions,
            correlation_data=correlation_data,
        )
        if corr_risk.highly_correlated_pairs:
            alerts.append(
                f"{len(corr_risk.highly_correlated_pairs)} highly correlated position pair(s)"
            )
            commentary.append(corr_risk.recommendation)

    # ── RM6: Drawdown ──
    drawdown = check_drawdown_circuit_breaker(
        current_nlv=account_nlv,
        account_peak=account_peak,
        circuit_breaker_pct=circuit_breaker_pct,
    )
    if drawdown.is_triggered:
        alerts.insert(0, f"CIRCUIT BREAKER: drawdown {drawdown.drawdown_pct:.1%} exceeds {circuit_breaker_pct:.0%}")
        commentary.insert(0, drawdown.recommendation)

    # ── Sector concentration ──
    sector_risk: dict[str, float] = {}
    for pos in positions:
        if pos.sector:
            sector_risk[pos.sector] = sector_risk.get(pos.sector, 0) + pos.max_loss
    # Normalize to percentages
    sector_pcts: dict[str, float] = {}
    if total_max_loss > 0:
        sector_pcts = {
            s: round(v / total_max_loss * 100, 1) for s, v in sector_risk.items()
        }
        for sector, pct in sector_pcts.items():
            if pct > 40:
                alerts.append(f"Sector concentration: {sector} at {pct:.0f}% of total risk")

    # ── Macro gate ──
    if macro_position_factor < 0.5:
        alerts.append(f"Macro regime ({macro_regime}) restricts position sizes to {macro_position_factor:.0%}")

    # ── Overall risk level ──
    risk_score = 0
    if drawdown.is_triggered:
        risk_score += 50
    if portfolio_risk_pct > 25:
        risk_score += 20
    elif portfolio_risk_pct > 15:
        risk_score += 10
    if var_result and var_result.loss_pct_of_nlv > 10:
        risk_score += 20
    elif var_result and var_result.loss_pct_of_nlv > 5:
        risk_score += 10
    if greeks_result and not greeks_result.within_limits:
        risk_score += 15
    if strategy_conc.is_concentrated:
        risk_score += 5
    if directional.is_concentrated:
        risk_score += 10
    if corr_risk and corr_risk.diversification_score < 0.3:
        risk_score += 10
    if macro_position_factor < 0.5:
        risk_score += 15

    if risk_score >= 50:
        overall = "critical"
    elif risk_score >= 30:
        overall = "high"
    elif risk_score >= 15:
        overall = "elevated"
    elif risk_score >= 5:
        overall = "moderate"
    else:
        overall = "low"

    # ── Master gate ──
    can_open = True
    if drawdown.is_triggered:
        can_open = False
    if open_count >= max_positions:
        can_open = False
    if portfolio_risk_pct > 30:
        can_open = False
    if macro_position_factor <= 0.2:
        can_open = False

    # ── Max new trade size ──
    # Start at 100%, scale down by worst risk factor
    size_pct = 1.0
    size_pct = min(size_pct, macro_position_factor)
    if portfolio_risk_pct > 20:
        size_pct = min(size_pct, 0.50)
    elif portfolio_risk_pct > 15:
        size_pct = min(size_pct, 0.75)
    if drawdown.drawdown_pct > circuit_breaker_pct * 0.7:
        size_pct = min(size_pct, 0.50)
    if var_result and var_result.loss_pct_of_nlv > 5:
        size_pct = min(size_pct, 0.75)
    if not can_open:
        size_pct = 0.0

    if not commentary:
        commentary.append("Portfolio risk is within acceptable bounds.")

    return RiskDashboard(
        as_of_date=date.today(),
        account_nlv=round(account_nlv, 2),
        open_positions=open_count,
        max_positions=max_positions,
        slots_remaining=slots,
        portfolio_risk_pct=round(portfolio_risk_pct, 2),
        greeks=greeks_result.greeks if greeks_result else None,
        greeks_within_limits=greeks_result.within_limits if greeks_result else True,
        var=var_result,
        strategy_concentration=strategy_conc,
        directional_exposure=directional,
        sector_concentration=sector_pcts,
        correlation_risk=corr_risk,
        drawdown=drawdown,
        macro_regime=macro_regime,
        macro_position_factor=macro_position_factor,
        overall_risk_level=overall,
        can_open_new_trades=can_open,
        max_new_trade_size_pct=round(size_pct, 2),
        alerts=alerts,
        commentary=commentary,
    )
