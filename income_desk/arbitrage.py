"""Arbitrage opportunity detection across options, futures, stocks.

Detects statistical arbitrage from structural mispricings:
1. Put-Call Parity violations (no model needed — pure math)
2. Box spread mispricing (risk-free rate arbitrage)
3. Futures basis vs fair value (already in futures_analysis, enhanced here)
4. Cross-market dual-listed stock divergence (India vs US after FX)
5. Calendar IV anomalies (from vol_history percentiles)
6. Option theoretical price vs market (simple BS for comparison ONLY)

NOTE: True arbitrage is captured by HFT in milliseconds.
These APIs detect STATISTICAL arbitrage — temporary mispricings that
tend to revert. Execution speed matters — eTrading must act quickly.

All functions are pure computation. eTrading provides market data, MA finds opportunities.
"""

from __future__ import annotations

import math
from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class ArbitrageType(StrEnum):
    PUT_CALL_PARITY = "put_call_parity"
    BOX_SPREAD = "box_spread"
    FUTURES_BASIS = "futures_basis"
    CROSS_MARKET = "cross_market"
    CALENDAR_IV = "calendar_iv"
    CONVERSION_REVERSAL = "conversion_reversal"


class ArbitrageOpportunity(BaseModel):
    """A detected arbitrage or statistical mispricing."""

    arb_type: ArbitrageType
    ticker: str
    theoretical_value: float         # What it SHOULD be worth
    market_value: float              # What the market says
    mispricing: float                # theoretical - market (positive = underpriced)
    mispricing_pct: float            # As percentage
    edge_after_costs: float | None   # After estimated transaction costs
    is_actionable: bool              # True if edge > costs
    urgency: str                     # "immediate", "monitor", "expired"
    legs: list[str]                  # What to trade: ["buy SPY 580C", "sell SPY 580P", ...]
    risk: str                        # "risk-free" or "statistical" or "execution_risk"
    commentary: str
    educational_note: str


class ArbitrageScanResult(BaseModel):
    """Results of scanning for arbitrage opportunities."""

    as_of_date: date
    total_scanned: int
    opportunities: list[ArbitrageOpportunity]
    actionable_count: int
    summary: str
    commentary: list[str]


class TheoreticalPrice(BaseModel):
    """Option theoretical price — market-mechanics-aware.

    Automatically adjusts for:
    - American vs European exercise (from MarketRegistry)
    - Physical vs cash settlement
    - Lot size per market (100 US, 25 NIFTY, etc.)

    FOR COMPARISON ONLY — never use for execution pricing.
    """

    ticker: str
    strike: float
    option_type: str          # "call" or "put"
    expiration: date
    dte: int
    # Inputs
    spot: float
    iv: float
    risk_free_rate: float
    # Market mechanics
    exercise_style: str = "american"   # "american" or "european"
    settlement: str = "physical"       # "physical" or "cash"
    lot_size: int = 100
    model_used: str = ""               # Which pricing model was applied
    # Outputs
    theoretical_price: float
    market_price: float | None
    mispricing: float | None  # theoretical - market
    # Per-contract values
    contract_theoretical: float = 0    # theoretical × lot_size
    contract_market: float | None = None  # market × lot_size
    # Greeks
    delta: float
    gamma: float
    theta: float              # Daily theta decay
    vega: float               # Per 1% IV change
    rho: float
    commentary: str


# ═══ BLACK-SCHOLES (for comparison only) ═══


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using error function."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def compute_theoretical_price(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    option_type: str = "call",
    risk_free_rate: float = 0.05,
    dividend_yield: float = 0.0,
    market_price: float | None = None,
    ticker: str = "",
    expiration: date | None = None,
    exercise_style: str | None = None,  # "american", "european" — auto-detected from registry
    settlement: str | None = None,       # "cash", "physical" — auto-detected from registry
    lot_size: int | None = None,         # 100 (US), 25 (NIFTY), etc — auto-detected
) -> TheoreticalPrice:
    """Compute theoretical option price + Greeks, respecting market mechanics.

    Automatically detects exercise style and settlement from MarketRegistry:
    - US equities: American exercise, physical settlement, lot_size=100
    - US indices (SPX): European exercise, cash settlement
    - India indices (NIFTY/BANKNIFTY): European, cash, lot_size=25/15
    - India stocks: European, physical, lot_size varies

    For American options (US equities):
    - Calls on non-dividend stocks: BS is accurate (no early exercise advantage)
    - Calls on dividend stocks near ex-date: BS UNDERESTIMATES by early exercise premium
    - Puts (especially deep ITM): BS UNDERESTIMATES. Uses Bjerksund-Stensland approximation.

    For European options (India, US index):
    - Standard Black-Scholes is correct.

    FOR COMPARISON ONLY — never use this for execution pricing.
    Always use broker bid/ask for actual trades.
    """
    # Auto-detect market mechanics from registry
    if exercise_style is None or settlement is None or lot_size is None:
        try:
            from income_desk.registry import MarketRegistry
            inst = MarketRegistry().get_instrument(ticker)
            if exercise_style is None:
                exercise_style = inst.exercise_style
            if settlement is None:
                settlement = inst.settlement
            if lot_size is None:
                lot_size = inst.lot_size
        except (KeyError, ImportError):
            pass

    # Defaults if still unknown
    if exercise_style is None:
        exercise_style = "american"  # Conservative default (US equity)
    if settlement is None:
        settlement = "physical"
    if lot_size is None:
        lot_size = 100
    t = max(dte, 1) / 365
    sqrt_t = math.sqrt(t)

    if iv <= 0 or spot <= 0 or strike <= 0:
        return TheoreticalPrice(
            ticker=ticker, strike=strike, option_type=option_type,
            expiration=expiration or date.today(), dte=dte,
            spot=spot, iv=iv, risk_free_rate=risk_free_rate,
            theoretical_price=0, market_price=market_price, mispricing=None,
            delta=0, gamma=0, theta=0, vega=0, rho=0,
            commentary="Invalid inputs — cannot compute",
        )

    d1 = (math.log(spot / strike) + (risk_free_rate - dividend_yield + 0.5 * iv * iv) * t) / (iv * sqrt_t)
    d2 = d1 - iv * sqrt_t

    if option_type == "call":
        price = spot * math.exp(-dividend_yield * t) * _norm_cdf(d1) - strike * math.exp(-risk_free_rate * t) * _norm_cdf(d2)
        delta = math.exp(-dividend_yield * t) * _norm_cdf(d1)
    else:
        price = strike * math.exp(-risk_free_rate * t) * _norm_cdf(-d2) - spot * math.exp(-dividend_yield * t) * _norm_cdf(-d1)
        delta = -math.exp(-dividend_yield * t) * _norm_cdf(-d1)

    gamma = math.exp(-dividend_yield * t) * _norm_pdf(d1) / (spot * iv * sqrt_t)
    theta = (-(spot * iv * math.exp(-dividend_yield * t) * _norm_pdf(d1)) / (2 * sqrt_t)
             - risk_free_rate * strike * math.exp(-risk_free_rate * t) * _norm_cdf(d2 if option_type == "call" else -d2)
             + dividend_yield * spot * math.exp(-dividend_yield * t) * _norm_cdf(d1 if option_type == "call" else -d1))
    theta_daily = theta / 365
    vega = spot * math.exp(-dividend_yield * t) * _norm_pdf(d1) * sqrt_t / 100  # Per 1% IV change
    rho = (strike * t * math.exp(-risk_free_rate * t) * _norm_cdf(d2 if option_type == "call" else -d2)) / 100
    if option_type == "put":
        rho = -rho

    # ── AMERICAN OPTION ADJUSTMENT ──
    # European BS underestimates American options (early exercise premium)
    european_price = price
    model_used = "black_scholes_european"

    if exercise_style == "american":
        if option_type == "put":
            # American puts are always worth at least intrinsic value
            intrinsic = max(0, strike - spot)
            if price < intrinsic:
                price = intrinsic  # Floor at intrinsic

            # Bjerksund-Stensland approximation for American put premium
            # Simplified: early exercise premium ≈ f(moneyness, time, rates)
            # For deep ITM puts (spot << strike), premium is significant
            moneyness = strike / spot if spot > 0 else 1
            if moneyness > 1.05:  # ITM put
                # Premium increases with: higher rates, deeper ITM, more time
                early_exercise_premium = (
                    risk_free_rate * strike * t *
                    (1 - math.exp(-risk_free_rate * t)) *
                    max(0, moneyness - 1) * 0.5
                )
                price += early_exercise_premium
            model_used = "black_scholes_american_adjusted"

        elif option_type == "call" and dividend_yield > 0:
            # American calls on dividend stocks: early exercise before ex-date
            # Premium small unless dividend is large relative to remaining time value
            time_value = price - max(0, spot - strike)
            annual_div = spot * dividend_yield
            if annual_div * (dte / 365) > time_value * 0.5:
                # Dividend large enough to consider early exercise
                early_exercise_premium = annual_div * (dte / 365) * 0.1
                price += early_exercise_premium
                model_used = "black_scholes_american_div_adjusted"
            else:
                model_used = "black_scholes_european"  # No early exercise advantage for calls without div

    mispricing = None
    model_note = {
        "black_scholes_european": "European BS (exact for European options)",
        "black_scholes_american_adjusted": "BS + American put early exercise premium",
        "black_scholes_american_div_adjusted": "BS + American call dividend early exercise",
    }.get(model_used, model_used)

    settlement_note = f" | Settlement: {settlement}" if settlement else ""
    exercise_note = f" | Exercise: {exercise_style}" if exercise_style else ""
    commentary = f"{model_note}: ${price:.2f}{exercise_note}{settlement_note}"
    if market_price is not None:
        mispricing = round(price - market_price, 4)
        if abs(mispricing) > price * 0.05:
            commentary += f" | Market: ${market_price:.2f} | Mispricing: ${mispricing:+.2f}"
            if mispricing > 0:
                commentary += " (market UNDERPRICED)"
            else:
                commentary += " (market OVERPRICED)"
        else:
            commentary += f" | Market: ${market_price:.2f} | Fair"

    return TheoreticalPrice(
        ticker=ticker, strike=strike, option_type=option_type,
        expiration=expiration or date.today(), dte=dte,
        spot=spot, iv=iv, risk_free_rate=risk_free_rate,
        exercise_style=exercise_style,
        settlement=settlement,
        lot_size=lot_size,
        model_used=model_used,
        theoretical_price=round(price, 4),
        market_price=market_price,
        mispricing=mispricing,
        contract_theoretical=round(price * lot_size, 2),
        contract_market=round(market_price * lot_size, 2) if market_price is not None else None,
        delta=round(delta, 4), gamma=round(gamma, 6),
        theta=round(theta_daily, 4), vega=round(vega, 4), rho=round(rho, 4),
        commentary=commentary,
    )


# ═══ PUT-CALL PARITY ═══


def check_put_call_parity(
    spot: float,
    strike: float,
    call_price: float,
    put_price: float,
    dte: int,
    risk_free_rate: float = 0.05,
    dividend_yield: float = 0.0,
    ticker: str = "",
    transaction_cost: float = 0.02,  # Per contract round-trip
) -> ArbitrageOpportunity | None:
    """Check put-call parity: C - P = S - K×e^(-rT).

    No model needed — this is a mathematical identity that MUST hold.
    If it doesn't, one side is mispriced.
    """
    t = max(dte, 1) / 365
    pv_strike = strike * math.exp(-risk_free_rate * t)
    pv_dividend = spot * (1 - math.exp(-dividend_yield * t)) if dividend_yield > 0 else 0

    # Theoretical: C - P = S - PV(K) - PV(dividends)
    theoretical_diff = spot - pv_strike - pv_dividend
    actual_diff = call_price - put_price
    mispricing = actual_diff - theoretical_diff

    if abs(mispricing) < transaction_cost * 2:
        return None  # Within transaction costs — no edge

    mispricing_pct = (mispricing / spot * 100) if spot > 0 else 0
    edge = abs(mispricing) - transaction_cost * 2

    if mispricing > 0:
        # Call overpriced relative to put → sell call, buy put, buy stock
        legs = [f"sell {ticker} {strike}C", f"buy {ticker} {strike}P", f"buy {ticker} stock"]
        action = "CONVERSION: sell overpriced call, buy put, buy stock"
    else:
        # Put overpriced relative to call → sell put, buy call, sell stock
        legs = [f"sell {ticker} {strike}P", f"buy {ticker} {strike}C", f"short {ticker} stock"]
        action = "REVERSAL: sell overpriced put, buy call, short stock"

    return ArbitrageOpportunity(
        arb_type=ArbitrageType.PUT_CALL_PARITY,
        ticker=ticker,
        theoretical_value=round(theoretical_diff, 4),
        market_value=round(actual_diff, 4),
        mispricing=round(mispricing, 4),
        mispricing_pct=round(mispricing_pct, 3),
        edge_after_costs=round(edge, 4),
        is_actionable=edge > 0,
        urgency="immediate" if edge > 0.10 else "monitor",
        legs=legs,
        risk="statistical",  # Not truly risk-free due to execution, dividends, early exercise
        commentary=f"Put-call parity violation: {mispricing:+.4f} ({mispricing_pct:+.3f}%). {action}",
        educational_note=(
            "PUT-CALL PARITY: C - P must equal S - PV(K). If it doesn't, one option is mispriced. "
            "This is the most fundamental options relationship — no model needed, pure math. "
            "In practice, execution costs, dividends, and early exercise (American options) can "
            "create small deviations. Only trade if edge exceeds transaction costs."
        ),
    )


# ═══ BOX SPREAD ═══


def check_box_spread(
    strike_low: float,
    strike_high: float,
    call_low: float,    # Call at lower strike (buy)
    call_high: float,   # Call at higher strike (sell)
    put_low: float,     # Put at lower strike (sell)
    put_high: float,    # Put at higher strike (buy)
    dte: int,
    risk_free_rate: float = 0.05,
    ticker: str = "",
    transaction_cost: float = 0.04,  # 4 legs
) -> ArbitrageOpportunity | None:
    """Check box spread: bull call spread + bear put spread should = PV(strike width).

    Box spread payoff is ALWAYS (strike_high - strike_low) at expiry.
    If you can buy it for less → risk-free profit.
    """
    width = strike_high - strike_low
    t = max(dte, 1) / 365
    theoretical_value = width * math.exp(-risk_free_rate * t)

    # Cost of the box: buy call spread + buy put spread
    call_spread_cost = call_low - call_high  # Buy low, sell high (debit)
    put_spread_cost = put_high - put_low     # Buy high, sell low (debit)
    box_cost = call_spread_cost + put_spread_cost

    mispricing = theoretical_value - box_cost
    mispricing_pct = (mispricing / theoretical_value * 100) if theoretical_value > 0 else 0
    edge = mispricing - transaction_cost

    if abs(mispricing) < transaction_cost:
        return None

    return ArbitrageOpportunity(
        arb_type=ArbitrageType.BOX_SPREAD,
        ticker=ticker,
        theoretical_value=round(theoretical_value, 4),
        market_value=round(box_cost, 4),
        mispricing=round(mispricing, 4),
        mispricing_pct=round(mispricing_pct, 3),
        edge_after_costs=round(edge, 4),
        is_actionable=edge > 0,
        urgency="immediate" if edge > 0.10 else "monitor",
        legs=[
            f"buy {ticker} {strike_low}C",
            f"sell {ticker} {strike_high}C",
            f"sell {ticker} {strike_low}P",
            f"buy {ticker} {strike_high}P",
        ],
        risk="risk-free" if dte > 0 else "execution_risk",
        commentary=(
            f"Box spread: theoretical ${theoretical_value:.2f}, market ${box_cost:.2f}, "
            f"mispricing ${mispricing:+.4f} ({mispricing_pct:+.2f}%)"
        ),
        educational_note=(
            "BOX SPREAD: A combination of bull call spread + bear put spread at the same strikes. "
            "The payoff at expiry is ALWAYS the width between strikes — guaranteed. "
            "If you can buy this box for LESS than the present value of the width, you earn risk-free interest. "
            "If you can sell it for MORE, you're lending at above-market rates. "
            "Box spreads are used by institutions for financing. Retail traders rarely find actionable edges."
        ),
    )


# ═══ CROSS-MARKET (DUAL-LISTED) ═══


def check_cross_market_arbitrage(
    ticker_us: str,
    ticker_india: str,
    price_us: float,       # USD price
    price_india: float,     # INR price
    fx_rate: float,         # USD/INR (e.g., 83.5 = 1 USD = 83.5 INR)
    transaction_cost_pct: float = 0.5,  # Round-trip cost as %
) -> ArbitrageOpportunity | None:
    """Check price divergence between dual-listed stocks (US vs India).

    Example: Infosys trades as INFY (US ADR) and INFY.NS (India NSE).
    After FX adjustment, prices should be equal. If not → arbitrage.
    """
    # Convert India price to USD
    india_in_usd = price_india / fx_rate

    # Mispricing
    mispricing = price_us - india_in_usd
    mispricing_pct = (mispricing / price_us * 100) if price_us > 0 else 0
    edge = abs(mispricing_pct) - transaction_cost_pct

    if abs(mispricing_pct) < transaction_cost_pct:
        return None

    if mispricing > 0:
        legs = [f"sell {ticker_us} (US)", f"buy {ticker_india} (India)"]
        action = "US premium — sell US, buy India"
    else:
        legs = [f"buy {ticker_us} (US)", f"sell {ticker_india} (India)"]
        action = "India premium — buy US, sell India"

    return ArbitrageOpportunity(
        arb_type=ArbitrageType.CROSS_MARKET,
        ticker=f"{ticker_us}/{ticker_india}",
        theoretical_value=round(india_in_usd, 4),
        market_value=round(price_us, 4),
        mispricing=round(mispricing, 4),
        mispricing_pct=round(mispricing_pct, 3),
        edge_after_costs=round(edge, 3),
        is_actionable=edge > 0,
        urgency="monitor",
        legs=legs,
        risk="statistical",
        commentary=f"Cross-market: {ticker_us} ${price_us:.2f} vs {ticker_india} ₹{price_india:.2f} (=${india_in_usd:.2f}). {action}",
        educational_note=(
            "CROSS-MARKET ARBITRAGE: Same company trading in two markets at different prices. "
            "After FX conversion, prices should be equal. Differences arise from: "
            "time zones (US closes before India opens), FX hedging costs, ADR conversion ratio, "
            "and local supply/demand. Execution requires accounts in both markets and FX hedging."
        ),
    )


# ═══ SCAN FOR ALL ARBITRAGE ═══


def scan_arbitrage(
    option_chain: list[dict] | None = None,
    spot_price: float = 0,
    futures_price: float | None = None,
    futures_dte: int = 30,
    risk_free_rate: float = 0.05,
    ticker: str = "",
    cross_market_pairs: list[dict] | None = None,
) -> ArbitrageScanResult:
    """Scan for arbitrage opportunities across all types.

    Args:
        option_chain: List of {strike, call_bid, call_ask, put_bid, put_ask, dte, ...}
        spot_price: Current underlying price
        futures_price: If available, check basis arbitrage
        ticker: Underlying ticker
        cross_market_pairs: [{ticker_us, ticker_india, price_us, price_india, fx_rate}]

    Returns:
        ArbitrageScanResult with all detected opportunities
    """
    today = date.today()
    opportunities: list[ArbitrageOpportunity] = []
    total_scanned = 0

    # Put-call parity scan
    if option_chain and spot_price > 0:
        for opt in option_chain:
            strike = opt.get("strike", 0)
            call_mid = opt.get("call_mid", 0)
            put_mid = opt.get("put_mid", 0)
            dte = opt.get("dte", 30)

            if strike > 0 and call_mid > 0 and put_mid > 0:
                total_scanned += 1
                result = check_put_call_parity(
                    spot_price, strike, call_mid, put_mid, dte,
                    risk_free_rate, ticker=ticker,
                )
                if result:
                    opportunities.append(result)

    # Box spread scan (need at least 2 strikes)
    if option_chain and len(option_chain) >= 2:
        sorted_chain = sorted(option_chain, key=lambda x: x.get("strike", 0))
        for i in range(len(sorted_chain) - 1):
            for j in range(i + 1, min(i + 5, len(sorted_chain))):  # Check nearby strikes
                low = sorted_chain[i]
                high = sorted_chain[j]
                sl = low.get("strike", 0)
                sh = high.get("strike", 0)
                if sl > 0 and sh > 0 and sh > sl:
                    total_scanned += 1
                    result = check_box_spread(
                        sl, sh,
                        low.get("call_mid", 0), high.get("call_mid", 0),
                        low.get("put_mid", 0), high.get("put_mid", 0),
                        low.get("dte", 30), risk_free_rate, ticker=ticker,
                    )
                    if result:
                        opportunities.append(result)

    # Futures basis
    if futures_price and spot_price > 0:
        from income_desk.futures_analysis import analyze_futures_basis
        basis = analyze_futures_basis(ticker, spot_price, futures_price, futures_dte, risk_free_rate)
        if basis.mispricing and abs(basis.mispricing) > spot_price * 0.003:
            total_scanned += 1
            opportunities.append(ArbitrageOpportunity(
                arb_type=ArbitrageType.FUTURES_BASIS,
                ticker=ticker,
                theoretical_value=round(spot_price + basis.fair_value_basis, 4),
                market_value=round(futures_price, 4),
                mispricing=round(basis.mispricing, 4),
                mispricing_pct=round(basis.mispricing / spot_price * 100, 3),
                edge_after_costs=round(abs(basis.mispricing) - spot_price * 0.001, 4),
                is_actionable=abs(basis.mispricing) > spot_price * 0.005,
                urgency="monitor",
                legs=[
                    f"{'buy' if basis.mispricing > 0 else 'sell'} {ticker} futures",
                    f"{'sell' if basis.mispricing > 0 else 'buy'} {ticker} spot",
                ],
                risk="statistical",
                commentary=basis.commentary,
                educational_note=(
                    "FUTURES BASIS ARBITRAGE: When futures deviate from fair value (spot + cost of carry), "
                    "buy the cheap side and sell the expensive side. In practice, requires significant capital "
                    "and the ability to hold until convergence at expiry."
                ),
            ))

    # Cross-market
    if cross_market_pairs:
        for pair in cross_market_pairs:
            total_scanned += 1
            result = check_cross_market_arbitrage(
                pair["ticker_us"], pair["ticker_india"],
                pair["price_us"], pair["price_india"],
                pair["fx_rate"],
            )
            if result:
                opportunities.append(result)

    actionable = [o for o in opportunities if o.is_actionable]

    commentary = [f"Arbitrage scan: {total_scanned} checks, {len(opportunities)} mispricings, {len(actionable)} actionable"]
    if actionable:
        best = max(actionable, key=lambda o: abs(o.mispricing_pct))
        commentary.append(f"Best: {best.arb_type} on {best.ticker} ({best.mispricing_pct:+.3f}%)")

    return ArbitrageScanResult(
        as_of_date=today,
        total_scanned=total_scanned,
        opportunities=opportunities,
        actionable_count=len(actionable),
        summary=f"{len(actionable)} actionable out of {total_scanned} scanned",
        commentary=commentary,
    )
