"""Futures and futures options analysis — basis, term structure, rolls, spreads.

Covers:
1. Futures basis analysis (spot vs futures premium/discount)
2. Term structure (contango/backwardation)
3. Roll decision engine (when and how to roll expiring contracts)
4. Calendar spread analysis (front vs back month)
5. Futures options premium analysis (selling premium on futures)
6. Margin estimation
7. India-specific futures (NIFTY/BANKNIFTY/stock futures)

All functions are pure computation — accept price data, return analysis.
eTrading handles execution and position management.
"""

from __future__ import annotations

import math
from datetime import date
from enum import StrEnum

from pydantic import BaseModel


# ═══ ENUMS ═══


class TermStructure(StrEnum):
    """Futures term structure shape."""

    CONTANGO = "contango"             # Futures > Spot (normal — storage/carry cost)
    BACKWARDATION = "backwardation"   # Futures < Spot (inverted — supply squeeze)
    FLAT = "flat"                     # Futures ≈ Spot


class RollAction(StrEnum):
    """Roll decision for expiring futures."""

    ROLL_FORWARD = "roll_forward"     # Close near, open far (most common)
    HOLD_TO_EXPIRY = "hold_to_expiry" # Let it expire/settle
    CLOSE_POSITION = "close_position" # Exit entirely
    WAIT = "wait"                     # Not time to roll yet


class FuturesDirection(StrEnum):
    LONG = "long"
    SHORT = "short"


# ═══ MODELS ═══


class FuturesBasisAnalysis(BaseModel):
    """Spot vs futures premium/discount analysis.

    WHAT IS BASIS?
    Basis = Futures Price - Spot Price. It tells you the cost or benefit
    of holding a futures contract instead of the underlying asset.

    If basis is POSITIVE (contango): futures cost more than spot.
    You're paying a premium for the convenience of not storing/holding the asset.
    This is normal for most commodities (storage costs) and financial futures (interest rates).

    If basis is NEGATIVE (backwardation): futures cost less than spot.
    This is unusual and signals supply shortage or extreme demand for immediate delivery.
    Oil in a supply crisis, gold during a bank run, VIX during panic — all go backwardated.
    """

    ticker: str
    spot_price: float
    futures_price: float
    futures_expiry: date | None
    futures_dte: int

    basis: float                     # futures - spot (positive = premium)
    basis_pct: float                 # basis / spot × 100
    annualized_basis_pct: float      # basis_pct × (365 / dte) — cost of carry

    structure: TermStructure         # contango / backwardation / flat
    fair_value_basis: float | None   # Theoretical: spot × (1 + risk_free × dte/365)
    mispricing: float | None         # Actual basis - fair value basis

    commentary: str
    educational_notes: list[str] = []  # Beginner-friendly explanations


class FuturesTermStructurePoint(BaseModel):
    """Single point on the futures term structure curve."""

    expiry_label: str                # "Mar 2026", "Apr 2026"
    expiry_date: date | None
    dte: int
    price: float
    basis_vs_spot_pct: float


class FuturesTermStructureAnalysis(BaseModel):
    """Full term structure analysis across multiple expiries.

    WHAT IS TERM STRUCTURE?
    Term structure is the curve of futures prices across different expiry dates —
    like a yield curve, but for futures. It shows you how the market prices an asset
    over time.

    CONTANGO CURVE: Each later month costs more than the previous one. This is normal
    for most markets because of storage, insurance, and financing costs. But it means
    holding a long futures position COSTS you money every time you roll.

    BACKWARDATED CURVE: Each later month costs LESS. This signals stress — the market
    wants the asset NOW so badly that near-term contracts trade at a premium. This is
    bullish for longs because you EARN money when rolling.

    WHY IT MATTERS FOR TRADERS:
    The shape of the curve determines your "carry" — the ongoing cost or benefit of
    maintaining a futures position over time. A steep contango curve can eat 10-15%
    of your position per year just from rolling costs.
    """

    ticker: str
    spot_price: float
    points: list[FuturesTermStructurePoint]
    overall_structure: TermStructure
    steepness_pct: float             # Spread between nearest and farthest
    roll_yield_monthly_pct: float    # Monthly cost/benefit of rolling
    commentary: list[str]
    educational_notes: list[str] = []  # Beginner-friendly explanations


class FuturesRollDecision(BaseModel):
    """Decision on whether/how to roll an expiring futures contract.

    WHAT IS ROLLING?
    Futures contracts expire. Unlike stocks, you can't just hold forever. When your
    contract approaches expiry, you need to "roll" — close the expiring contract and
    open the next month's contract to maintain your position.

    ROLL COST:
    The price difference between the expiring and next-month contract is your roll cost.
    In contango, the next month costs MORE, so rolling a long position costs you money.
    In backwardation, the next month costs LESS, so rolling a long position earns you money.

    WHEN TO ROLL:
    Most traders roll 3-5 days before expiry. Waiting too long means:
    - Liquidity dries up (wider bid-ask spreads)
    - Risk of accidental delivery (for physical commodities)
    - Volatile price swings as other traders roll simultaneously

    PROFESSIONAL TIP: Many institutional traders roll during the "roll window" —
    a few days when volume shifts from the expiring to the next contract. Watch
    open interest to spot this transition.
    """

    ticker: str
    current_expiry: date | None
    current_dte: int
    next_expiry: date | None
    next_dte: int

    action: RollAction
    roll_cost_pct: float             # Cost of rolling as % (contango = negative carry)
    roll_cost_dollars: float | None  # In position currency
    urgency: str                     # "immediate", "soon", "not_yet"

    rationale: str
    commentary: list[str]
    educational_notes: list[str] = []  # Beginner-friendly explanations


class CalendarSpreadAnalysis(BaseModel):
    """Front month vs back month futures spread.

    WHAT IS A CALENDAR SPREAD?
    A calendar spread (also called a "time spread") is when you simultaneously buy
    one futures expiry and sell another on the SAME underlying. For example, sell
    the March contract and buy the June contract.

    WHY TRADE CALENDAR SPREADS?
    - Lower margin than outright futures (exchanges recognize the hedge)
    - Profit from changes in the SHAPE of the term structure, not the direction
    - Less risky than outright positions — you're hedged against big moves

    NORMAL SPREAD (contango): Back month > front month. If you expect this gap to
    NARROW (convergence), sell the back month and buy the front month.

    INVERTED SPREAD (backwardation): Front month > back month. If you expect
    normalization back to contango, buy the back month and sell the front month.

    RISK: Calendar spreads can still lose money if the curve moves against you,
    or if one leg has a delivery/settlement event the other doesn't.
    """

    ticker: str
    front_price: float
    front_expiry: str
    back_price: float
    back_expiry: str

    spread: float                    # back - front
    spread_pct: float
    spread_direction: str            # "normal" (back > front) or "inverted" (front > back)
    annualized_spread_pct: float

    trade_idea: str | None           # "sell front, buy back" or vice versa
    commentary: str
    educational_notes: list[str] = []  # Beginner-friendly explanations


class FuturesOptionAnalysis(BaseModel):
    """Analysis of selling premium on futures options.

    WHAT ARE FUTURES OPTIONS?
    Options on a futures contract (not on a stock). Same concepts — calls, puts,
    strikes, expiration — but the UNDERLYING is a futures contract, not a stock.

    KEY DIFFERENCES FROM STOCK OPTIONS:
    - Settlement: Futures options settle into FUTURES POSITIONS, not cash or stock.
      If you sell a put and get assigned, you now own a leveraged LONG futures position.
    - Margin: Futures options use SPAN margin (portfolio-based), often more efficient
      than stock option margin.
    - Size: One futures option controls one futures contract. For ES (S&P 500 E-mini),
      that's $50 per point — much larger than a typical stock option.
    - Hours: Futures trade nearly 24 hours, so your options can move overnight.

    PREMIUM SELLING ON FUTURES:
    Same theta-harvesting philosophy as stock options, but with more leverage. Selling
    strangles on futures can generate high income, but the risk is proportionally larger.
    Always use defined-risk structures (iron condors) on futures unless you have significant
    experience and capital.
    """

    underlying: str                  # Futures contract
    underlying_price: float

    # Put side
    put_strike: float
    put_premium_est: float
    put_delta: float
    put_annualized_yield_pct: float
    put_breakeven: float

    # Call side
    call_strike: float
    call_premium_est: float
    call_delta: float
    call_annualized_yield_pct: float
    call_breakeven: float

    # Strangle/IC on futures
    strangle_premium: float
    strangle_annualized_yield_pct: float
    strangle_breakeven_low: float
    strangle_breakeven_high: float

    margin_estimate: float           # Approximate margin required
    regime_suitability: str
    commentary: list[str]
    educational_notes: list[str] = []  # Beginner-friendly explanations


class FuturesMarginEstimate(BaseModel):
    """Margin requirement estimation for a futures position.

    WHAT IS FUTURES MARGIN?
    Unlike stock margin (borrowing money), futures margin is a PERFORMANCE BOND —
    a good-faith deposit that ensures you can cover potential losses. You're not
    borrowing anything; you're posting collateral.

    INITIAL MARGIN: The amount required to OPEN a position. Think of it as a
    security deposit. Typically 3-12% of the contract's full value.

    MAINTENANCE MARGIN: The minimum balance you must keep while the position is open.
    Usually about 75% of initial margin. If your account drops below this level,
    you get a MARGIN CALL.

    MARGIN CALL: The broker demands you deposit more money immediately (usually
    within 24 hours). If you can't pay, they close your position at market price —
    which could lock in a large loss.

    LEVERAGE: Because you only post 5-10% of the contract value, futures give you
    10-20x leverage. A 1% move in the underlying creates a 10-20% move in your
    margin account. This amplifies both profits AND losses.

    DAILY SETTLEMENT: Unlike stocks, futures P&L is settled EVERY DAY. Profits are
    added to your account and losses are deducted at the end of each trading session.
    This is called "mark-to-market."
    """

    ticker: str
    contract_value: float            # Price × multiplier
    initial_margin: float            # Required to open
    maintenance_margin: float        # Required to maintain
    margin_pct_of_value: float       # Leverage ratio
    effective_leverage: float        # contract_value / initial_margin
    commentary: str
    educational_notes: list[str] = []  # Beginner-friendly explanations


class FuturesResearchReport(BaseModel):
    """Complete futures analysis for a single instrument.

    WHAT IS THIS REPORT?
    A comprehensive analysis of a single futures instrument covering everything
    a trader needs: basis (spot vs futures), term structure (curve shape), roll
    timing, options opportunities, and margin requirements.

    HOW TO USE THIS REPORT:
    1. Check REGIME CONTEXT first — this tells you the market environment
    2. Look at BASIS — is the market in contango or backwardation?
    3. Review TERM STRUCTURE — what's the cost of holding over time?
    4. Check ROLL DECISION — do you need to act on expiring contracts?
    5. Evaluate OPTIONS — are there premium-selling opportunities?
    6. Verify MARGIN — can your account handle this position?

    FOR BEGINNERS:
    Start with micro contracts (1/10th size of standard futures). Paper trade
    for at least 3 months before risking real capital. Futures are leveraged
    instruments — a small move creates a big P&L swing. Always use stop losses
    and never risk more than 2% of your account on a single trade.
    """

    ticker: str
    as_of_date: date
    spot_price: float

    basis: FuturesBasisAnalysis | None
    term_structure: FuturesTermStructureAnalysis | None
    roll_decision: FuturesRollDecision | None
    options_analysis: FuturesOptionAnalysis | None
    margin: FuturesMarginEstimate | None

    direction_bias: str              # "bullish", "bearish", "neutral"
    regime_context: str
    key_signals: list[str]
    commentary: list[str]
    educational_notes: list[str] = []  # Beginner-friendly explanations


# ═══ FUTURES INSTRUMENT DATA ═══

FUTURES_INSTRUMENTS = {
    # US Futures
    "ES": {"name": "S&P 500 E-mini", "multiplier": 50, "tick": 0.25, "margin_pct": 0.05, "market": "US"},
    "NQ": {"name": "Nasdaq 100 E-mini", "multiplier": 20, "tick": 0.25, "margin_pct": 0.06, "market": "US"},
    "YM": {"name": "Dow E-mini", "multiplier": 5, "tick": 1.0, "margin_pct": 0.05, "market": "US"},
    "RTY": {"name": "Russell 2000 E-mini", "multiplier": 50, "tick": 0.10, "margin_pct": 0.06, "market": "US"},
    "CL": {"name": "Crude Oil", "multiplier": 1000, "tick": 0.01, "margin_pct": 0.08, "market": "US"},
    "GC": {"name": "Gold", "multiplier": 100, "tick": 0.10, "margin_pct": 0.07, "market": "US"},
    "SI": {"name": "Silver", "multiplier": 5000, "tick": 0.005, "margin_pct": 0.10, "market": "US"},
    "ZB": {"name": "30Y Treasury Bond", "multiplier": 1000, "tick": 1/32, "margin_pct": 0.03, "market": "US"},
    "ZN": {"name": "10Y Treasury Note", "multiplier": 1000, "tick": 1/64, "margin_pct": 0.02, "market": "US"},
    "NG": {"name": "Natural Gas", "multiplier": 10000, "tick": 0.001, "margin_pct": 0.12, "market": "US"},

    # India Futures (NSE)
    "NIFTY_FUT": {"name": "NIFTY 50 Futures", "multiplier": 25, "tick": 0.05, "margin_pct": 0.12, "market": "INDIA"},
    "BANKNIFTY_FUT": {"name": "Bank NIFTY Futures", "multiplier": 15, "tick": 0.05, "margin_pct": 0.12, "market": "INDIA"},
    "FINNIFTY_FUT": {"name": "Fin NIFTY Futures", "multiplier": 40, "tick": 0.05, "margin_pct": 0.12, "market": "INDIA"},
}


# ═══ COMPUTATION FUNCTIONS ═══


def analyze_futures_basis(
    ticker: str,
    spot_price: float,
    futures_price: float,
    futures_dte: int = 30,
    risk_free_rate: float = 0.05,
    futures_expiry: date | None = None,
) -> FuturesBasisAnalysis:
    """Analyze basis between spot and futures price."""

    basis = futures_price - spot_price
    basis_pct = (basis / spot_price * 100) if spot_price > 0 else 0
    annualized = (basis_pct * 365 / max(futures_dte, 1))

    # Fair value basis (cost of carry)
    fair_basis = spot_price * (risk_free_rate * futures_dte / 365)
    mispricing = basis - fair_basis

    # Structure
    if basis_pct > 0.1:
        structure = TermStructure.CONTANGO
    elif basis_pct < -0.1:
        structure = TermStructure.BACKWARDATION
    else:
        structure = TermStructure.FLAT

    # Commentary
    if structure == TermStructure.BACKWARDATION:
        commentary = (
            f"{ticker} in backwardation (futures {basis_pct:+.2f}% vs spot). "
            f"Supply squeeze or high demand. Roll yield is positive for longs."
        )
    elif structure == TermStructure.CONTANGO:
        commentary = (
            f"{ticker} in contango (futures {basis_pct:+.2f}% premium). "
            f"Normal carry cost. Roll yield is negative for longs (pay {annualized:.1f}%/yr to roll)."
        )
    else:
        commentary = f"{ticker} flat — futures ≈ spot. No carry cost/benefit."

    if mispricing is not None and abs(mispricing) > spot_price * 0.005:
        commentary += f" Mispriced by {mispricing:+.2f} vs fair value."

    # Educational notes for beginners
    educational_notes = [
        "WHAT IS A FUTURES CONTRACT? A binding agreement to buy/sell an asset at a fixed price on a future date.",
        "WHY TRADE FUTURES? Leverage (control large positions with small margin), hedging (lock in prices), speculation.",
        f"BASIS: {ticker} futures at {futures_price:.2f} vs spot at {spot_price:.2f} = basis of {basis:+.2f}.",
        f"FAIR VALUE: Based on {risk_free_rate*100:.1f}% risk-free rate over {futures_dte} days, fair basis is {fair_basis:.2f}.",
    ]
    if structure == TermStructure.CONTANGO:
        educational_notes.extend([
            "CONTANGO means futures cost MORE than spot. This is normal.",
            "If you're LONG futures and roll each month, you LOSE money on the roll (sell low, buy high).",
            f"Annual roll cost: ~{annualized:.1f}%. This is the 'cost of carry' — like paying rent to hold the position.",
            "EXAMPLE: If gold spot is $2,000 and 3-month futures is $2,025, you pay $25 (1.25%) to hold for 3 months.",
        ])
    elif structure == TermStructure.BACKWARDATION:
        educational_notes.extend([
            "BACKWARDATION means futures cost LESS than spot. This is unusual and bullish.",
            "It signals: supply shortage, extreme demand, or panic buying of the physical asset.",
            "If you're LONG futures and roll, you EARN money on the roll (sell high, buy low). This is called 'positive roll yield'.",
            f"Annual roll yield: ~{abs(annualized):.1f}%. You get PAID to hold the position.",
            "EXAMPLE: During oil supply crises, near-month oil trades above far-month because people need oil NOW.",
        ])
    else:
        educational_notes.append("FLAT: Futures and spot are roughly equal. No significant carry cost or benefit.")
    if mispricing is not None and abs(mispricing) > spot_price * 0.005:
        educational_notes.append(
            f"MISPRICING: The actual basis differs from fair value by {mispricing:+.2f}. "
            "This could be an arbitrage opportunity for sophisticated traders, or it could reflect "
            "supply/demand factors not captured by the simple cost-of-carry model."
        )

    return FuturesBasisAnalysis(
        ticker=ticker, spot_price=round(spot_price, 2),
        futures_price=round(futures_price, 2),
        futures_expiry=futures_expiry, futures_dte=futures_dte,
        basis=round(basis, 2), basis_pct=round(basis_pct, 3),
        annualized_basis_pct=round(annualized, 2),
        structure=structure,
        fair_value_basis=round(fair_basis, 2),
        mispricing=round(mispricing, 2) if mispricing is not None else None,
        commentary=commentary,
        educational_notes=educational_notes,
    )


def analyze_term_structure(
    ticker: str,
    spot_price: float,
    futures_prices: list[tuple[str, float, int]],  # [(label, price, dte), ...]
) -> FuturesTermStructureAnalysis:
    """Analyze futures term structure from multiple expiries."""

    if not futures_prices:
        return FuturesTermStructureAnalysis(
            ticker=ticker, spot_price=spot_price,
            points=[], overall_structure=TermStructure.FLAT,
            steepness_pct=0, roll_yield_monthly_pct=0,
            commentary=["No futures price data available"],
            educational_notes=[
                "TERM STRUCTURE: How futures prices change across expiry dates (like a yield curve for futures).",
                "No futures price data was available to build the term structure curve.",
                "To see the curve, you need prices for at least 2 different expiry months.",
            ],
        )

    points = []
    for label, price, dte in sorted(futures_prices, key=lambda x: x[2]):
        basis_pct = (price - spot_price) / spot_price * 100 if spot_price > 0 else 0
        points.append(FuturesTermStructurePoint(
            expiry_label=label, expiry_date=None, dte=dte,
            price=round(price, 2), basis_vs_spot_pct=round(basis_pct, 3),
        ))

    # Overall structure from front to back
    if len(points) >= 2:
        front_basis = points[0].basis_vs_spot_pct
        back_basis = points[-1].basis_vs_spot_pct
        steepness = back_basis - front_basis

        if steepness > 0.5:
            structure = TermStructure.CONTANGO
        elif steepness < -0.5:
            structure = TermStructure.BACKWARDATION
        else:
            structure = TermStructure.FLAT
    else:
        steepness = 0
        structure = TermStructure.FLAT

    # Monthly roll yield
    if len(points) >= 2:
        front = points[0]
        next_p = points[1]
        dte_diff = max(next_p.dte - front.dte, 1)
        roll_cost_pct = (next_p.price - front.price) / front.price * 100
        roll_monthly = roll_cost_pct * 30 / dte_diff
    else:
        roll_monthly = 0

    commentary = [f"Term structure: {structure.value} (steepness {steepness:+.2f}%)"]
    if structure == TermStructure.BACKWARDATION:
        commentary.append("Backwardation — positive roll yield for longs. Supply-driven market.")
    elif structure == TermStructure.CONTANGO:
        commentary.append(f"Contango — negative roll yield for longs (~{roll_monthly:.2f}%/month carry cost).")
    if len(points) >= 2:
        commentary.append(f"Front: {points[0].expiry_label} @ {points[0].price:.2f} | Back: {points[-1].expiry_label} @ {points[-1].price:.2f}")

    # Educational notes for beginners
    educational_notes = [
        "TERM STRUCTURE: How futures prices change across expiry dates (like a yield curve for futures).",
        "CONTANGO CURVE: Each later month costs more. Like a staircase going up. Normal for most markets.",
        "BACKWARDATED CURVE: Each later month costs less. Like a staircase going down. Signals stress.",
        "WHY IT MATTERS: The shape of the curve tells you the COST of holding a position over time.",
    ]
    if structure == TermStructure.CONTANGO:
        educational_notes.append(
            f"This curve costs you ~{roll_monthly:.2f}%/month to maintain a long position. "
            f"Over a year, that's ~{roll_monthly*12:.1f}% eaten by roll costs."
        )
    elif structure == TermStructure.BACKWARDATION:
        educational_notes.append(
            f"This curve PAYS you ~{abs(roll_monthly):.2f}%/month to hold a long position. "
            f"Over a year, that's ~{abs(roll_monthly)*12:.1f}% earned from positive roll yield."
        )
    else:
        educational_notes.append("Flat curve — minimal carry cost or benefit. Rolling is roughly cost-neutral.")
    if len(points) >= 2:
        educational_notes.append(
            f"STEEPNESS: The spread between nearest ({points[0].expiry_label}) and farthest "
            f"({points[-1].expiry_label}) is {steepness:+.2f}%. "
            "Steep curves = higher roll costs. Flat curves = cheaper to maintain positions."
        )

    return FuturesTermStructureAnalysis(
        ticker=ticker, spot_price=round(spot_price, 2),
        points=points, overall_structure=structure,
        steepness_pct=round(steepness, 3),
        roll_yield_monthly_pct=round(roll_monthly, 3),
        commentary=commentary,
        educational_notes=educational_notes,
    )


def decide_futures_roll(
    ticker: str,
    current_dte: int,
    next_month_price: float | None = None,
    current_price: float | None = None,
    position_direction: str = "long",
    roll_threshold_dte: int = 5,
    current_expiry: date | None = None,
    next_expiry: date | None = None,
) -> FuturesRollDecision:
    """Decide whether to roll an expiring futures contract."""

    commentary = []

    if current_dte > roll_threshold_dte:
        return FuturesRollDecision(
            ticker=ticker,
            current_expiry=current_expiry, current_dte=current_dte,
            next_expiry=next_expiry, next_dte=current_dte + 30,
            action=RollAction.WAIT, roll_cost_pct=0, roll_cost_dollars=None,
            urgency="not_yet",
            rationale=f"{current_dte} DTE — no roll needed yet (threshold: {roll_threshold_dte})",
            commentary=[f"Roll window starts at {roll_threshold_dte} DTE"],
            educational_notes=[
                "WHAT IS ROLLING? Futures expire. To maintain your position, you close the expiring contract and open the next month's.",
                "ROLL COST: The price difference between the expiring contract and the next month's contract.",
                f"Your position has {current_dte} days to expiry. Roll window typically starts at {roll_threshold_dte} DTE.",
                "NO ACTION NEEDED YET: You have plenty of time. Monitor the spread between this month and next month.",
                "TIP: Watch the open interest shift from the current month to the next — that's when most traders are rolling.",
            ],
        )

    if next_month_price is None or current_price is None:
        return FuturesRollDecision(
            ticker=ticker,
            current_expiry=current_expiry, current_dte=current_dte,
            next_expiry=next_expiry, next_dte=current_dte + 30,
            action=RollAction.ROLL_FORWARD, roll_cost_pct=0, roll_cost_dollars=None,
            urgency="immediate" if current_dte <= 2 else "soon",
            rationale=f"{current_dte} DTE — roll forward (no price data for cost estimate)",
            commentary=["Roll recommended — expiry approaching", "No next-month price for cost estimate"],
            educational_notes=[
                "WHAT IS ROLLING? Futures expire. To maintain your position, you close the expiring contract and open the next month's.",
                f"Your position has {current_dte} days to expiry. Roll window typically starts at {roll_threshold_dte} DTE.",
                "ROLLING WITHOUT PRICE DATA: We can't estimate the roll cost because next-month price isn't available.",
                "TIP: Check your broker's roll spread quote — this shows the cost as a single trade (cheaper than two separate trades).",
                "WARNING: Don't wait until the last day. Liquidity dries up near expiry, and spreads widen significantly.",
            ],
        )

    # Roll cost
    roll_cost = next_month_price - current_price
    roll_cost_pct = (roll_cost / current_price * 100) if current_price > 0 else 0

    if position_direction == "long":
        # Longs pay roll cost in contango, earn in backwardation
        cost_impact = roll_cost
    else:
        # Shorts earn roll cost in contango, pay in backwardation
        cost_impact = -roll_cost

    commentary.append(f"Roll cost: {roll_cost_pct:+.2f}% ({roll_cost:+.2f} per unit)")
    if cost_impact > 0:
        commentary.append(f"Roll costs you {abs(cost_impact):.2f} per unit ({position_direction} position)")
    else:
        commentary.append(f"Roll earns you {abs(cost_impact):.2f} per unit ({position_direction} position)")

    urgency = "immediate" if current_dte <= 2 else "soon" if current_dte <= roll_threshold_dte else "not_yet"

    # Educational notes for beginners
    educational_notes = [
        "WHAT IS ROLLING? Futures expire. To maintain your position, you close the expiring contract and open the next month's.",
        "ROLL COST: The price difference between the expiring contract and the next month's contract.",
        f"Your position has {current_dte} days to expiry. Roll window typically starts at {roll_threshold_dte} DTE.",
    ]
    educational_notes.extend([
        "ROLLING FORWARD: Close your current contract, open the next month.",
        f"Roll cost: {roll_cost_pct:+.2f}%. {'You PAY this (contango).' if roll_cost_pct > 0 else 'You EARN this (backwardation).' if roll_cost_pct < 0 else 'Cost-neutral roll.'}",
        "TIP: Roll BEFORE the last few days — liquidity dries up near expiry, spreads widen.",
    ])
    if cost_impact > 0:
        educational_notes.append(
            f"COST IMPACT: Rolling costs you {abs(cost_impact):.2f} per unit on your {position_direction} position. "
            "This is the price you pay for maintaining exposure."
        )
    else:
        educational_notes.append(
            f"ROLL BENEFIT: Rolling earns you {abs(cost_impact):.2f} per unit on your {position_direction} position. "
            "Backwardation is working in your favor."
        )
    if urgency == "immediate":
        educational_notes.append(
            "URGENT: Only 1-2 days left. Roll NOW or risk delivery/settlement issues and poor liquidity."
        )

    return FuturesRollDecision(
        ticker=ticker,
        current_expiry=current_expiry, current_dte=current_dte,
        next_expiry=next_expiry, next_dte=current_dte + 30,
        action=RollAction.ROLL_FORWARD,
        roll_cost_pct=round(roll_cost_pct, 3),
        roll_cost_dollars=round(cost_impact, 2),
        urgency=urgency,
        rationale=f"Roll forward — {current_dte} DTE, roll cost {roll_cost_pct:+.2f}%",
        commentary=commentary,
        educational_notes=educational_notes,
    )


def analyze_calendar_spread(
    ticker: str,
    front_price: float,
    front_label: str,
    back_price: float,
    back_label: str,
    front_dte: int = 30,
    back_dte: int = 60,
) -> CalendarSpreadAnalysis:
    """Analyze futures calendar spread opportunity."""

    spread = back_price - front_price
    spread_pct = (spread / front_price * 100) if front_price > 0 else 0
    dte_diff = max(back_dte - front_dte, 1)
    annualized = spread_pct * 365 / dte_diff

    direction = "normal" if spread > 0 else "inverted"

    trade_idea = None
    if abs(spread_pct) > 0.5:
        if direction == "normal" and spread_pct > 1.0:
            trade_idea = "Contango steep — sell back month, buy front month (expect convergence)"
        elif direction == "inverted" and spread_pct < -1.0:
            trade_idea = "Backwardation steep — buy back month, sell front month (expect normalization)"

    commentary = (
        f"{ticker} {front_label}/{back_label} spread: {spread:+.2f} ({spread_pct:+.2f}%). "
        f"{'Normal contango' if direction == 'normal' else 'Inverted (backwardation)'}. "
        f"Annualized: {annualized:+.1f}%."
    )

    # Educational notes for beginners
    educational_notes = [
        "CALENDAR SPREAD: Buy one futures expiry and sell another on the SAME underlying.",
        f"You're looking at {ticker} {front_label} (front) vs {back_label} (back).",
        f"SPREAD: Back month ({back_price:.2f}) minus front month ({front_price:.2f}) = {spread:+.2f} ({spread_pct:+.2f}%).",
        "WHY TRADE THIS? Lower margin than outright futures. You profit from changes in the curve SHAPE, not direction.",
    ]
    if direction == "normal":
        educational_notes.extend([
            "NORMAL SPREAD: Back month costs more than front month (contango). This is typical.",
            "TRADE LOGIC: If you think this gap will NARROW, sell the back month and buy the front month.",
            "RISK: If the curve steepens further (gap widens), you lose. Also watch for delivery months.",
        ])
    else:
        educational_notes.extend([
            "INVERTED SPREAD: Front month costs more than back month (backwardation). This signals stress.",
            "TRADE LOGIC: If you expect normalization back to contango, buy the back month and sell the front month.",
            "RISK: If backwardation deepens (supply shortage worsens), the inversion can get much worse.",
        ])
    if trade_idea:
        educational_notes.append(f"TRADE IDEA: {trade_idea}")
    else:
        educational_notes.append("NO STRONG TRADE: The spread isn't extreme enough for a high-conviction calendar trade.")
    educational_notes.append(
        f"ANNUALIZED: This spread represents {annualized:+.1f}% annualized. "
        "Compare this to risk-free rates to see if the carry is attractive."
    )

    return CalendarSpreadAnalysis(
        ticker=ticker,
        front_price=round(front_price, 2), front_expiry=front_label,
        back_price=round(back_price, 2), back_expiry=back_label,
        spread=round(spread, 2), spread_pct=round(spread_pct, 3),
        spread_direction=direction,
        annualized_spread_pct=round(annualized, 2),
        trade_idea=trade_idea,
        commentary=commentary,
        educational_notes=educational_notes,
    )


def analyze_futures_options(
    ticker: str,
    futures_price: float,
    iv: float = 0.20,
    regime_id: int = 1,
    put_delta: float = 0.30,
    call_delta: float = 0.30,
    dte: int = 35,
    multiplier: int = 100,
    margin_pct: float = 0.10,
) -> FuturesOptionAnalysis:
    """Analyze premium selling opportunities on futures options."""

    t = dte / 365
    sqrt_t = math.sqrt(t)

    # Premium estimation (simplified)
    put_strike = round(futures_price * (1 - put_delta * iv * sqrt_t), 2)
    put_premium = round(futures_price * iv * sqrt_t * put_delta * 1.5, 2)
    put_breakeven = put_strike - put_premium
    put_yield = (put_premium / put_strike * (365 / dte) * 100) if put_strike > 0 else 0

    call_strike = round(futures_price * (1 + call_delta * iv * sqrt_t), 2)
    call_premium = round(futures_price * iv * sqrt_t * call_delta * 1.5, 2)
    call_breakeven = call_strike + call_premium
    call_yield = (call_premium / call_strike * (365 / dte) * 100) if call_strike > 0 else 0

    strangle = put_premium + call_premium
    strangle_yield = ((put_yield + call_yield) / 2)

    margin_est = futures_price * multiplier * margin_pct

    regime_names = {1: "ideal (low vol, MR)", 2: "good (high premiums)",
                    3: "risky (trending)", 4: "avoid (explosive)"}
    regime_suit = regime_names.get(regime_id, f"R{regime_id}")

    commentary = [
        f"Futures options on {ticker} @ {futures_price:.2f}",
        f"Put: sell {put_strike:.0f}P at ${put_premium:.2f} ({put_yield:.0f}%/yr)",
        f"Call: sell {call_strike:.0f}C at ${call_premium:.2f} ({call_yield:.0f}%/yr)",
        f"Strangle: ${strangle:.2f} ({strangle_yield:.0f}%/yr combined)",
        f"Margin: ~${margin_est:,.0f} per contract",
        f"Regime: {regime_suit}",
    ]

    # Educational notes for beginners
    educational_notes = [
        "FUTURES OPTIONS: Options on a futures contract (not on the stock). Same concepts, different underlying.",
        "SELLING PUTS ON FUTURES: You collect premium. If futures drop below strike, you get assigned a LONG futures position.",
        "SELLING CALLS ON FUTURES: You collect premium. If futures rise above strike, you get assigned a SHORT futures position.",
        f"STRANGLE: Sell both a put and a call. You collect ${strangle:.2f} premium. "
        f"You profit if futures stay between ${put_breakeven:.0f} and ${call_breakeven:.0f}.",
        f"MARGIN: Futures options require ~${margin_est:,.0f} margin per contract. "
        f"Much less than the full contract value of ${futures_price * multiplier:,.0f}.",
        "WARNING: Futures options settle into FUTURES POSITIONS (not cash). "
        "If assigned, you have a leveraged futures position with daily mark-to-market.",
    ]
    if regime_id in (1, 2):
        educational_notes.append(
            "Current regime supports premium selling — volatility is mean-reverting. "
            "This is the sweet spot for selling strangles and iron condors on futures."
        )
    elif regime_id == 3:
        educational_notes.append(
            "CAUTION: Current regime is trending. Premium selling is risky because "
            "the market can keep moving in one direction, breaching your short strike."
        )
    elif regime_id == 4:
        educational_notes.append(
            "DANGER: Current regime is explosive. Premium selling on futures is very risky — "
            "moves can be massive. Consider defined-risk structures only, or stay out entirely."
        )
    educational_notes.extend([
        f"PUT SIDE: Sell {put_strike:.0f} put at ${put_premium:.2f} = {put_yield:.0f}% annualized. "
        f"Breakeven at {put_breakeven:.0f} (futures must stay above this).",
        f"CALL SIDE: Sell {call_strike:.0f} call at ${call_premium:.2f} = {call_yield:.0f}% annualized. "
        f"Breakeven at {call_breakeven:.0f} (futures must stay below this).",
        "TIP: Always consider iron condors (add wings) instead of naked strangles on futures. "
        "The leverage makes naked positions extremely risky.",
    ])

    return FuturesOptionAnalysis(
        underlying=ticker, underlying_price=round(futures_price, 2),
        put_strike=put_strike, put_premium_est=put_premium,
        put_delta=put_delta, put_annualized_yield_pct=round(put_yield, 1),
        put_breakeven=round(put_breakeven, 2),
        call_strike=call_strike, call_premium_est=call_premium,
        call_delta=call_delta, call_annualized_yield_pct=round(call_yield, 1),
        call_breakeven=round(call_breakeven, 2),
        strangle_premium=round(strangle, 2),
        strangle_annualized_yield_pct=round(strangle_yield, 1),
        strangle_breakeven_low=round(put_breakeven, 2),
        strangle_breakeven_high=round(call_breakeven, 2),
        margin_estimate=round(margin_est, 2),
        regime_suitability=regime_suit,
        commentary=commentary,
        educational_notes=educational_notes,
    )


def estimate_futures_margin(
    ticker: str,
    price: float,
    contracts: int = 1,
    direction: str = "long",
) -> FuturesMarginEstimate:
    """Estimate margin requirement for a futures position."""

    instrument = FUTURES_INSTRUMENTS.get(ticker, {})
    multiplier = instrument.get("multiplier", 100)
    margin_pct = instrument.get("margin_pct", 0.10)
    name = instrument.get("name", ticker)

    contract_value = price * multiplier * contracts
    initial_margin = contract_value * margin_pct
    maintenance_margin = initial_margin * 0.75  # Typically 75% of initial
    leverage = contract_value / initial_margin if initial_margin > 0 else 1

    # Educational notes for beginners
    one_pct_move = contract_value * 0.01
    one_pct_of_margin = (one_pct_move / initial_margin * 100) if initial_margin > 0 else 0
    cushion = initial_margin - maintenance_margin

    educational_notes = [
        f"LEVERAGE: With ${initial_margin:,.0f} margin, you control ${contract_value:,.0f} of {name}. That's {leverage:.0f}x leverage.",
        "INITIAL MARGIN: What you deposit to open the position. Like a security deposit.",
        "MAINTENANCE MARGIN: Minimum balance to keep the position open. If your account drops below this, you get a MARGIN CALL.",
        f"MARGIN CALL: If {name} moves against you by ${cushion:,.0f}, broker demands more cash. "
        "If you can't pay, they close your position.",
        "DAILY MARK-TO-MARKET: Unlike stocks, futures P&L is settled EVERY DAY. Profits added to your account, losses deducted.",
        f"1% MOVE = ${one_pct_move:,.0f} P&L on this position. That's {one_pct_of_margin:.0f}% of your margin.",
        f"POSITION SIZE: {contracts} contract(s) of {name} at {price:,.2f} with {multiplier}x multiplier.",
        "FOR BEGINNERS: Start with micro contracts (1/10th size) to learn futures mechanics with less risk.",
    ]

    return FuturesMarginEstimate(
        ticker=ticker,
        contract_value=round(contract_value, 2),
        initial_margin=round(initial_margin, 2),
        maintenance_margin=round(maintenance_margin, 2),
        margin_pct_of_value=round(margin_pct * 100, 1),
        effective_leverage=round(leverage, 1),
        commentary=f"{name}: {contracts} contract(s) × {price:,.2f} × {multiplier} = "
                   f"${contract_value:,.0f} notional. "
                   f"Margin: ${initial_margin:,.0f} ({margin_pct*100:.0f}%). "
                   f"Leverage: {leverage:.0f}x.",
        educational_notes=educational_notes,
    )


def generate_futures_report(
    ticker: str,
    spot_price: float,
    futures_price: float | None = None,
    futures_dte: int = 30,
    next_month_price: float | None = None,
    iv: float = 0.20,
    regime_id: int = 1,
    direction: str = "neutral",
) -> FuturesResearchReport:
    """Generate complete futures research report for an instrument."""

    today = date.today()
    commentary = [f"Futures analysis: {ticker} as of {today}"]
    signals = []

    # Basis
    basis = None
    if futures_price is not None:
        basis = analyze_futures_basis(ticker, spot_price, futures_price, futures_dte)
        commentary.append(basis.commentary)
        if basis.structure == TermStructure.BACKWARDATION:
            signals.append(f"Backwardation — positive roll yield for longs")
        if basis.mispricing and abs(basis.mispricing) > spot_price * 0.005:
            signals.append(f"Futures mispriced by {basis.mispricing:+.2f}")

    # Term structure
    term = None
    if futures_price is not None and next_month_price is not None:
        points = [
            ("Near", futures_price, futures_dte),
            ("Next", next_month_price, futures_dte + 30),
        ]
        term = analyze_term_structure(ticker, spot_price, points)
        commentary.extend(term.commentary)

    # Roll
    roll = None
    if futures_dte <= 10 and futures_price is not None:
        roll = decide_futures_roll(ticker, futures_dte, next_month_price, futures_price)
        if roll.action == RollAction.ROLL_FORWARD:
            signals.append(f"Roll needed — {roll.urgency}: cost {roll.roll_cost_pct:+.2f}%")

    # Options
    opts = None
    instrument = FUTURES_INSTRUMENTS.get(ticker, {})
    if instrument:
        opts = analyze_futures_options(
            ticker, futures_price or spot_price, iv, regime_id,
            multiplier=instrument.get("multiplier", 100),
            margin_pct=instrument.get("margin_pct", 0.10),
        )

    # Margin
    margin = estimate_futures_margin(ticker, futures_price or spot_price)

    # Direction bias from regime
    regime_names = {1: "R1 Low-Vol MR", 2: "R2 High-Vol MR",
                    3: "R3 Low-Vol Trend", 4: "R4 High-Vol Trend"}
    regime_context = regime_names.get(regime_id, f"R{regime_id}")

    # Educational notes for beginners
    inst_name = instrument.get("name", ticker)
    inst_multiplier = instrument.get("multiplier", 100)

    educational_notes = [
        f"FUTURES REPORT: {ticker} ({inst_name}) — everything you need to know for trading this instrument.",
        "BEFORE TRADING FUTURES: Understand that futures are leveraged. A small move = big P&L.",
        "RISK MANAGEMENT: Always use stop losses. Never risk more than 2% of account on a single futures trade.",
        "FOR BEGINNERS: Start with micro contracts (1/10th size) or paper trade first.",
        f"CONTRACT SPECS: Each point in {ticker} = ${inst_multiplier} per contract.",
    ]
    if regime_id == 1:
        educational_notes.append(
            f"REGIME R1 (Low-Vol Mean Reverting): {ticker} is range-bound. "
            "Ideal for selling premium on futures options. Use iron condors or strangles."
        )
    elif regime_id == 2:
        educational_notes.append(
            f"REGIME R2 (High-Vol Mean Reverting): {ticker} has wide swings but no sustained trend. "
            "Premiums are rich — good for selling, but use wider strikes."
        )
    elif regime_id == 3:
        educational_notes.append(
            f"REGIME R3 (Low-Vol Trending): {ticker} is in a slow, persistent move. "
            "Consider directional futures trades. Avoid premium selling against the trend."
        )
    elif regime_id == 4:
        educational_notes.append(
            f"REGIME R4 (High-Vol Trending): {ticker} is making explosive moves. "
            "DANGEROUS for premium selling. Use defined-risk only. Consider reducing position size."
        )
    if direction != "neutral":
        educational_notes.append(
            f"DIRECTION BIAS: {direction.upper()}. This bias comes from regime and trend analysis, "
            "not a prediction. Use it to choose which side of a trade to favor."
        )

    return FuturesResearchReport(
        ticker=ticker, as_of_date=today, spot_price=round(spot_price, 2),
        basis=basis, term_structure=term, roll_decision=roll,
        options_analysis=opts, margin=margin,
        direction_bias=direction, regime_context=regime_context,
        key_signals=signals, commentary=commentary,
        educational_notes=educational_notes,
    )
