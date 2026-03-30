#!/usr/bin/env python3
"""Pricing Regression — self-maintaining trade portfolio built from real chain data.

Connects to broker (Dhan for India, TastyTrade for US), fetches real option chains,
builds valid trades using only strikes/expiries that actually exist with liquidity,
prices them, and validates all numbers.

On each run:
1. Load existing portfolio from JSON (if any)
2. Prune expired trades
3. Replenish to target count from live chains
4. Price all active trades and validate
5. Save updated portfolio
6. Report pass/fail with actual numbers

Usage:
    python scripts/pricing_regression.py --market India
    python scripts/pricing_regression.py --market US
    python scripts/pricing_regression.py --market India --rebuild   # force rebuild all
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TARGET_TRADE_COUNT = 25
PORTFOLIO_DIR = Path.home() / ".income_desk"
PORTFOLIO_FILE_INDIA = PORTFOLIO_DIR / "test_portfolio_india.json"
PORTFOLIO_FILE_US = PORTFOLIO_DIR / "test_portfolio_us.json"

# India tickers — broad coverage across indices + large/mid cap
INDIA_TICKERS = [
    "NIFTY", "BANKNIFTY",                          # Indices
    "RELIANCE", "TCS", "INFY", "HDFCBANK",         # Large cap
    "ICICIBANK", "SBIN", "BAJFINANCE", "TATAMOTORS",  # Large cap
]

US_TICKERS = [
    "SPY", "QQQ", "IWM",                           # Index ETFs
    "AAPL", "MSFT", "NVDA", "AMZN",               # Mega cap
    "GLD", "TLT",                                   # Commodities/Bonds
]

# Structures to test per ticker
STRUCTURES = [
    "iron_condor",
    "credit_spread_put",
    "credit_spread_call",
    "iron_butterfly",
    "debit_spread_put",
    "strangle",
]

# Validation thresholds
MIN_CREDIT_INR = 1.0       # Minimum credit for India trades
MIN_CREDIT_USD = 0.05      # Minimum credit for US trades
MAX_IV = 5.0               # IV above 500% is clearly wrong
MIN_IV = 0.01              # IV below 1% is clearly wrong
MAX_SPREAD_PCT = 50.0      # Bid-ask spread > 50% is illiquid

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Broker connection
# ---------------------------------------------------------------------------


def connect_broker(market: str):
    """Connect to broker and return (market_data, market_metrics, account)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    if market == "India":
        from income_desk.broker.dhan import connect_dhan
        md, mm, acct, _wl = connect_dhan()
        return md, mm, acct
    else:
        from income_desk.broker.tastytrade import connect_tastytrade
        md, mm, acct, _wl = connect_tastytrade(is_paper=False)
        return md, mm, acct


# ---------------------------------------------------------------------------
# Chain analysis — find valid strikes with liquidity
# ---------------------------------------------------------------------------


def analyze_chain(chain: list, underlying_price: float) -> dict:
    """Analyze an option chain and find liquid strikes.

    Returns dict with:
        expiry: date
        underlying: float
        puts: list of {strike, bid, ask, mid, iv, delta, oi, volume}
        calls: list of {strike, bid, ask, mid, iv, delta, oi, volume}
        atm_strike: float (nearest to underlying)
    """
    if not chain:
        return {}

    expiry = chain[0].expiration if chain else None

    puts = []
    calls = []
    for q in chain:
        entry = {
            "strike": q.strike,
            "bid": q.bid,
            "ask": q.ask,
            "mid": q.mid,
            "iv": q.implied_volatility,
            "delta": q.delta,
            "oi": q.open_interest,
            "volume": q.volume,
            "lot_size": q.lot_size,
        }
        if q.option_type == "put":
            puts.append(entry)
        else:
            calls.append(entry)

    # Sort by strike
    puts.sort(key=lambda x: x["strike"])
    calls.sort(key=lambda x: x["strike"])

    # Find ATM strike
    all_strikes = sorted(set(q.strike for q in chain))
    atm_strike = min(all_strikes, key=lambda s: abs(s - underlying_price)) if all_strikes else 0

    return {
        "expiry": expiry,
        "underlying": underlying_price,
        "puts": puts,
        "calls": calls,
        "atm_strike": atm_strike,
        "all_strikes": all_strikes,
    }


def is_liquid(opt: dict, min_oi: int = 0) -> bool:
    """Check if an option has minimum liquidity."""
    return (
        opt["bid"] > 0
        and opt["ask"] > 0
        and opt["mid"] > 0
        and opt["oi"] >= min_oi
    )


def find_otm_put(puts: list, underlying: float, distance_pct: float) -> dict | None:
    """Find a liquid OTM put at approximately distance_pct below underlying."""
    target = underlying * (1 - distance_pct)
    candidates = [p for p in puts if p["strike"] <= underlying and is_liquid(p)]
    if not candidates:
        return None
    return min(candidates, key=lambda p: abs(p["strike"] - target))


def find_otm_call(calls: list, underlying: float, distance_pct: float) -> dict | None:
    """Find a liquid OTM call at approximately distance_pct above underlying."""
    target = underlying * (1 + distance_pct)
    candidates = [c for c in calls if c["strike"] >= underlying and is_liquid(c)]
    if not candidates:
        return None
    return min(candidates, key=lambda c: abs(c["strike"] - target))


def find_strike_at(options: list, target_strike: float) -> dict | None:
    """Find the closest liquid option to a target strike."""
    liquid = [o for o in options if is_liquid(o)]
    if not liquid:
        return None
    return min(liquid, key=lambda o: abs(o["strike"] - target_strike))


def find_wing(options: list, short_strike: float, direction: str, width_pct: float, underlying: float) -> dict | None:
    """Find a wing strike further OTM from the short strike."""
    wing_distance = underlying * width_pct
    if direction == "lower":
        target = short_strike - wing_distance
        candidates = [o for o in options if o["strike"] < short_strike and is_liquid(o)]
    else:
        target = short_strike + wing_distance
        candidates = [o for o in options if o["strike"] > short_strike and is_liquid(o)]
    if not candidates:
        return None
    return min(candidates, key=lambda o: abs(o["strike"] - target))


# ---------------------------------------------------------------------------
# Trade builders — each returns a trade dict or None
# ---------------------------------------------------------------------------


def build_iron_condor(ticker: str, analysis: dict) -> dict | None:
    """Build an iron condor from real chain data."""
    underlying = analysis["underlying"]
    puts = analysis["puts"]
    calls = analysis["calls"]

    # Short put ~3% OTM, short call ~3% OTM
    short_put = find_otm_put(puts, underlying, 0.03)
    short_call = find_otm_call(calls, underlying, 0.03)
    if not short_put or not short_call:
        return None

    # Wings ~2% further out
    long_put = find_wing(puts, short_put["strike"], "lower", 0.02, underlying)
    long_call = find_wing(calls, short_call["strike"], "higher", 0.02, underlying)
    if not long_put or not long_call:
        return None

    credit = (short_put["mid"] - long_put["mid"]) + (short_call["mid"] - long_call["mid"])
    put_width = short_put["strike"] - long_put["strike"]
    call_width = long_call["strike"] - short_call["strike"]
    max_risk = max(put_width, call_width) * analysis["puts"][0]["lot_size"] - credit

    return _make_trade(
        ticker=ticker,
        structure="iron_condor",
        expiry=analysis["expiry"],
        underlying=underlying,
        legs=[
            {"strike": long_put["strike"], "type": "put", "action": "buy", **_leg_data(long_put)},
            {"strike": short_put["strike"], "type": "put", "action": "sell", **_leg_data(short_put)},
            {"strike": short_call["strike"], "type": "call", "action": "sell", **_leg_data(short_call)},
            {"strike": long_call["strike"], "type": "call", "action": "buy", **_leg_data(long_call)},
        ],
        credit=credit,
        max_risk=max_risk,
        lot_size=analysis["puts"][0]["lot_size"],
    )


def build_credit_spread_put(ticker: str, analysis: dict) -> dict | None:
    """Build a put credit spread from real chain data."""
    underlying = analysis["underlying"]
    puts = analysis["puts"]

    short_put = find_otm_put(puts, underlying, 0.03)
    if not short_put:
        return None

    long_put = find_wing(puts, short_put["strike"], "lower", 0.02, underlying)
    if not long_put:
        return None

    credit = short_put["mid"] - long_put["mid"]
    width = short_put["strike"] - long_put["strike"]
    lot_size = puts[0]["lot_size"] if puts else 1
    max_risk = width * lot_size - credit

    return _make_trade(
        ticker=ticker,
        structure="credit_spread_put",
        expiry=analysis["expiry"],
        underlying=underlying,
        legs=[
            {"strike": long_put["strike"], "type": "put", "action": "buy", **_leg_data(long_put)},
            {"strike": short_put["strike"], "type": "put", "action": "sell", **_leg_data(short_put)},
        ],
        credit=credit,
        max_risk=max_risk,
        lot_size=lot_size,
    )


def build_credit_spread_call(ticker: str, analysis: dict) -> dict | None:
    """Build a call credit spread from real chain data."""
    underlying = analysis["underlying"]
    calls = analysis["calls"]

    short_call = find_otm_call(calls, underlying, 0.03)
    if not short_call:
        return None

    long_call = find_wing(calls, short_call["strike"], "higher", 0.02, underlying)
    if not long_call:
        return None

    credit = short_call["mid"] - long_call["mid"]
    width = long_call["strike"] - short_call["strike"]
    lot_size = calls[0]["lot_size"] if calls else 1
    max_risk = width * lot_size - credit

    return _make_trade(
        ticker=ticker,
        structure="credit_spread_call",
        expiry=analysis["expiry"],
        underlying=underlying,
        legs=[
            {"strike": short_call["strike"], "type": "call", "action": "sell", **_leg_data(short_call)},
            {"strike": long_call["strike"], "type": "call", "action": "buy", **_leg_data(long_call)},
        ],
        credit=credit,
        max_risk=max_risk,
        lot_size=lot_size,
    )


def build_iron_butterfly(ticker: str, analysis: dict) -> dict | None:
    """Build an iron butterfly from real chain data."""
    underlying = analysis["underlying"]
    puts = analysis["puts"]
    calls = analysis["calls"]
    atm = analysis["atm_strike"]

    # ATM short straddle
    short_put = find_strike_at(puts, atm)
    short_call = find_strike_at(calls, atm)
    if not short_put or not short_call:
        return None

    # Wings ~3% out
    long_put = find_wing(puts, short_put["strike"], "lower", 0.03, underlying)
    long_call = find_wing(calls, short_call["strike"], "higher", 0.03, underlying)
    if not long_put or not long_call:
        return None

    credit = (short_put["mid"] + short_call["mid"]) - (long_put["mid"] + long_call["mid"])
    put_width = short_put["strike"] - long_put["strike"]
    call_width = long_call["strike"] - short_call["strike"]
    lot_size = puts[0]["lot_size"] if puts else 1
    max_risk = max(put_width, call_width) * lot_size - credit

    return _make_trade(
        ticker=ticker,
        structure="iron_butterfly",
        expiry=analysis["expiry"],
        underlying=underlying,
        legs=[
            {"strike": long_put["strike"], "type": "put", "action": "buy", **_leg_data(long_put)},
            {"strike": short_put["strike"], "type": "put", "action": "sell", **_leg_data(short_put)},
            {"strike": short_call["strike"], "type": "call", "action": "sell", **_leg_data(short_call)},
            {"strike": long_call["strike"], "type": "call", "action": "buy", **_leg_data(long_call)},
        ],
        credit=credit,
        max_risk=max_risk,
        lot_size=lot_size,
    )


def build_debit_spread_put(ticker: str, analysis: dict) -> dict | None:
    """Build a put debit spread (bearish) from real chain data."""
    underlying = analysis["underlying"]
    puts = analysis["puts"]

    # Buy slightly OTM put, sell further OTM put
    long_put = find_otm_put(puts, underlying, 0.02)
    if not long_put:
        return None

    short_put = find_wing(puts, long_put["strike"], "lower", 0.02, underlying)
    if not short_put:
        return None

    debit = long_put["mid"] - short_put["mid"]
    width = long_put["strike"] - short_put["strike"]
    lot_size = puts[0]["lot_size"] if puts else 1
    max_risk = debit * lot_size

    return _make_trade(
        ticker=ticker,
        structure="debit_spread_put",
        expiry=analysis["expiry"],
        underlying=underlying,
        legs=[
            {"strike": long_put["strike"], "type": "put", "action": "buy", **_leg_data(long_put)},
            {"strike": short_put["strike"], "type": "put", "action": "sell", **_leg_data(short_put)},
        ],
        credit=-debit,  # negative = debit
        max_risk=max_risk,
        lot_size=lot_size,
    )


def build_strangle(ticker: str, analysis: dict) -> dict | None:
    """Build a short strangle from real chain data."""
    underlying = analysis["underlying"]
    puts = analysis["puts"]
    calls = analysis["calls"]

    # Short put ~4% OTM, short call ~4% OTM
    short_put = find_otm_put(puts, underlying, 0.04)
    short_call = find_otm_call(calls, underlying, 0.04)
    if not short_put or not short_call:
        return None

    credit = short_put["mid"] + short_call["mid"]
    lot_size = puts[0]["lot_size"] if puts else 1

    return _make_trade(
        ticker=ticker,
        structure="strangle",
        expiry=analysis["expiry"],
        underlying=underlying,
        legs=[
            {"strike": short_put["strike"], "type": "put", "action": "sell", **_leg_data(short_put)},
            {"strike": short_call["strike"], "type": "call", "action": "sell", **_leg_data(short_call)},
        ],
        credit=credit,
        max_risk=None,  # undefined risk
        lot_size=lot_size,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _leg_data(opt: dict) -> dict:
    """Extract pricing data from an option dict for storage."""
    return {
        "bid": opt["bid"],
        "ask": opt["ask"],
        "mid": opt["mid"],
        "iv": opt["iv"],
        "delta": opt["delta"],
        "oi": opt["oi"],
        "volume": opt["volume"],
    }


def _make_trade(
    ticker: str,
    structure: str,
    expiry: date | None,
    underlying: float,
    legs: list[dict],
    credit: float,
    max_risk: float | None,
    lot_size: int,
) -> dict:
    """Construct a trade dict with metadata."""
    return {
        "id": f"{ticker}-{structure}-{expiry}",
        "ticker": ticker,
        "structure": structure,
        "expiry": expiry.isoformat() if expiry else None,
        "underlying_price": underlying,
        "legs": legs,
        "net_credit": round(credit, 2),
        "max_risk": round(max_risk, 2) if max_risk is not None else None,
        "lot_size": lot_size,
        "created": datetime.now().isoformat(),
        "last_priced": datetime.now().isoformat(),
    }


BUILDERS = {
    "iron_condor": build_iron_condor,
    "credit_spread_put": build_credit_spread_put,
    "credit_spread_call": build_credit_spread_call,
    "iron_butterfly": build_iron_butterfly,
    "debit_spread_put": build_debit_spread_put,
    "strangle": build_strangle,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_trade(trade: dict, market: str) -> list[str]:
    """Validate a trade's pricing data. Returns list of failure reasons."""
    failures = []
    ticker = trade["ticker"]
    structure = trade["structure"]
    credit = trade["net_credit"]
    legs = trade["legs"]
    is_india = market == "India"
    min_credit = MIN_CREDIT_INR if is_india else MIN_CREDIT_USD

    # Credit check (skip for debit structures)
    if "debit" not in structure and credit < min_credit:
        failures.append(f"credit {credit:.2f} below minimum {min_credit}")

    # Leg-level checks
    for i, leg in enumerate(legs):
        prefix = f"leg[{i}] {leg['strike']}{leg['type'][0].upper()}"

        # Bid/ask sanity
        if leg["bid"] <= 0:
            failures.append(f"{prefix}: bid={leg['bid']} (zero/negative)")
        if leg["ask"] <= 0:
            failures.append(f"{prefix}: ask={leg['ask']} (zero/negative)")
        if leg["ask"] > 0 and leg["bid"] > 0 and leg["ask"] < leg["bid"]:
            failures.append(f"{prefix}: ask {leg['ask']} < bid {leg['bid']} (inverted)")

        # Spread check
        if leg["mid"] > 0:
            spread_pct = (leg["ask"] - leg["bid"]) / leg["mid"] * 100
            if spread_pct > MAX_SPREAD_PCT:
                failures.append(f"{prefix}: spread {spread_pct:.0f}% > {MAX_SPREAD_PCT}%")

        # IV check
        iv = leg.get("iv")
        if iv is not None:
            if iv < MIN_IV:
                failures.append(f"{prefix}: IV {iv:.4f} below {MIN_IV} (too low)")
            if iv > MAX_IV:
                failures.append(f"{prefix}: IV {iv:.4f} above {MAX_IV} (too high)")

        # Delta check (should exist for broker-sourced data)
        delta = leg.get("delta")
        if delta is not None and abs(delta) > 1.0:
            failures.append(f"{prefix}: delta {delta:.3f} out of [-1, 1]")

    # Max risk check
    if trade["max_risk"] is not None and trade["max_risk"] <= 0 and "debit" not in structure:
        failures.append(f"max_risk {trade['max_risk']} non-positive")

    # Strike ordering for spreads
    if structure == "iron_condor" and len(legs) == 4:
        strikes = [l["strike"] for l in legs]
        if not (strikes[0] < strikes[1] < strikes[2] < strikes[3]):
            failures.append(f"IC strikes not in order: {strikes}")

    return failures


# ---------------------------------------------------------------------------
# Portfolio management
# ---------------------------------------------------------------------------


def load_portfolio(filepath: Path) -> list[dict]:
    """Load portfolio from JSON file."""
    if not filepath.exists():
        return []
    try:
        with open(filepath) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_portfolio(portfolio: list[dict], filepath: Path) -> None:
    """Save portfolio to JSON file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(portfolio, f, indent=2, default=str)


def prune_expired(portfolio: list[dict]) -> tuple[list[dict], int]:
    """Remove expired trades. Returns (active_trades, removed_count)."""
    today = date.today()
    active = []
    removed = 0
    for trade in portfolio:
        exp = trade.get("expiry")
        if exp and date.fromisoformat(exp) < today:
            removed += 1
        else:
            active.append(trade)
    return active, removed


def replenish_portfolio(
    portfolio: list[dict],
    md: Any,
    tickers: list[str],
    market: str,
    target: int = TARGET_TRADE_COUNT,
) -> list[dict]:
    """Add new trades to reach target count using live chain data."""
    existing_ids = {t["id"] for t in portfolio}
    new_trades: list[dict] = []
    shadow: list[dict] = []

    for ticker in tickers:
        if len(portfolio) + len(new_trades) >= target:
            break

        print(f"  Fetching chain for {ticker}...", end=" ", flush=True)

        # Get underlying price
        try:
            price = md.get_underlying_price(ticker)
        except Exception as e:
            print(f"SKIP (price failed: {e})")
            continue

        if not price or price <= 0:
            print("SKIP (no price)")
            continue

        # Get option chain
        try:
            chain = md.get_option_chain(ticker)
        except Exception as e:
            print(f"SKIP (chain failed: {e})")
            continue

        if not chain:
            print("SKIP (empty chain)")
            continue

        print(f"${price:,.2f} | {len(chain)} quotes")

        # Rate limit for Dhan
        time.sleep(3.5)

        analysis = analyze_chain(chain, price)
        if not analysis:
            continue

        # Try each structure
        for struct_name, builder in BUILDERS.items():
            trade_id = f"{ticker}-{struct_name}-{analysis.get('expiry')}"
            if trade_id in existing_ids:
                continue

            try:
                trade = builder(ticker, analysis)
            except Exception as e:
                print(f"    {struct_name}: BUILD ERROR — {e}")
                continue

            if trade is None:
                print(f"    {struct_name}: no liquid strikes found")
                continue

            # Validate
            issues = validate_trade(trade, market)
            if issues:
                trade["shadow"] = True
                trade["issues"] = issues
                shadow.append(trade)
                print(f"    {struct_name}: SHADOW — {'; '.join(issues[:2])}")
            else:
                new_trades.append(trade)
                existing_ids.add(trade_id)
                print(f"    {struct_name}: OK — credit {trade['net_credit']:.2f}")

            if len(portfolio) + len(new_trades) >= target:
                break

    return new_trades, shadow


def reprice_portfolio(
    portfolio: list[dict],
    md: Any,
    market: str,
) -> list[dict]:
    """Re-price all trades in portfolio with current market data. Returns validation results."""
    results = []
    chains_cache: dict[str, tuple[float, list]] = {}

    for trade in portfolio:
        ticker = trade["ticker"]

        # Cache chain per ticker
        if ticker not in chains_cache:
            try:
                price = md.get_underlying_price(ticker) or 0
                chain = md.get_option_chain(ticker)
                chains_cache[ticker] = (price, chain)
                time.sleep(3.5)  # Rate limit
            except Exception as e:
                results.append({
                    "id": trade["id"],
                    "status": "ERROR",
                    "reason": f"chain fetch failed: {e}",
                })
                continue

        price, chain = chains_cache[ticker]
        chain_map = {}
        for q in chain:
            chain_map[(q.strike, q.option_type)] = q

        # Update leg prices
        all_found = True
        for leg in trade["legs"]:
            key = (leg["strike"], leg["type"])
            q = chain_map.get(key)
            if q:
                leg["bid"] = q.bid
                leg["ask"] = q.ask
                leg["mid"] = q.mid
                leg["iv"] = q.implied_volatility
                leg["delta"] = q.delta
            else:
                all_found = False

        if not all_found:
            results.append({
                "id": trade["id"],
                "status": "MISSING_STRIKES",
                "reason": "some legs not found in current chain",
            })
            continue

        trade["underlying_price"] = price
        trade["last_priced"] = datetime.now().isoformat()

        # Recalculate credit
        net = 0
        for leg in trade["legs"]:
            if leg["action"] == "sell":
                net += leg["mid"]
            else:
                net -= leg["mid"]
        trade["net_credit"] = round(net, 2)

        # Validate
        issues = validate_trade(trade, market)
        results.append({
            "id": trade["id"],
            "status": "PASS" if not issues else "FAIL",
            "credit": trade["net_credit"],
            "issues": issues,
        })

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_leg_row(leg: dict, cur: str) -> str:
    """Format a single leg as a detail row."""
    action_str = "SELL" if leg["action"] == "sell" else "BUY "
    opt_type = leg["type"][0].upper()  # P or C
    iv_str = f"{leg['iv']:.1%}" if leg.get("iv") is not None else "N/A"
    delta_str = f"{leg['delta']:.3f}" if leg.get("delta") is not None else "N/A"
    oi_str = f"{leg.get('oi', 0):,}"
    fmt = "    {action} {strike:>10.2f}{typ}  bid={bid:>8.2f}  ask={ask:>8.2f}  mid={mid:>8.2f}  IV={iv:>7s}  delta={delta:>7s}  OI={oi:>10s}"
    return fmt.format(
        action=action_str,
        strike=leg["strike"],
        typ=opt_type,
        bid=leg["bid"],
        ask=leg["ask"],
        mid=leg["mid"],
        iv=iv_str,
        delta=delta_str,
        oi=oi_str,
    )


def _compute_wing_width(trade: dict) -> str:
    """Compute wing width description for a trade."""
    legs = trade["legs"]
    structure = trade["structure"]
    if structure == "iron_condor" and len(legs) == 4:
        put_width = legs[1]["strike"] - legs[0]["strike"]
        call_width = legs[3]["strike"] - legs[2]["strike"]
        return f"put={put_width:.0f} / call={call_width:.0f}"
    elif structure in ("credit_spread_put", "debit_spread_put") and len(legs) == 2:
        width = abs(legs[1]["strike"] - legs[0]["strike"])
        return f"{width:.0f}"
    elif structure == "credit_spread_call" and len(legs) == 2:
        width = abs(legs[1]["strike"] - legs[0]["strike"])
        return f"{width:.0f}"
    elif structure == "iron_butterfly" and len(legs) == 4:
        put_width = legs[1]["strike"] - legs[0]["strike"]
        call_width = legs[3]["strike"] - legs[2]["strike"]
        return f"put={put_width:.0f} / call={call_width:.0f}"
    elif structure == "strangle":
        return "N/A (naked)"
    return "N/A"


def print_full_report(
    portfolio: list[dict],
    shadow: list[dict],
    market: str,
    detail: bool = False,
) -> None:
    """Print full trade evaluation report.

    All trades sorted: APPROVED on top, REJECTED below.
    --detail flag shows per-leg data for every trade.
    """
    cur = "INR" if market == "India" else "$"

    # Build unified list with status
    all_trades: list[tuple[str, dict, list[str]]] = []
    for t in portfolio:
        all_trades.append(("APPROVED", t, []))
    for t in shadow:
        all_trades.append(("REJECTED", t, t.get("issues", [])))

    # Sort: APPROVED first, then REJECTED; within each group sort by ticker then structure
    all_trades.sort(key=lambda x: (0 if x[0] == "APPROVED" else 1, x[1]["ticker"], x[1]["structure"]))

    total = len(all_trades)
    approved = sum(1 for s, _, _ in all_trades if s == "APPROVED")
    rejected = total - approved

    print(f"\n{'=' * 100}")
    print(f"  FULL TRADE EVALUATION REPORT — {market}")
    print(f"  {total} evaluated | {approved} approved | {rejected} rejected")
    print(f"{'=' * 100}")

    # Summary table (always shown)
    hdr_fmt = "  {:<4} {:<10} {:<8} {:<20} {:>10} {:>12} {:>12} {:>5} {:>10}"
    print()
    print(hdr_fmt.format("#", "Status", "Ticker", "Structure", "Expiry", "Net Cr/Db", "MaxRisk", "Lot", "Wing"))
    print(f"  {'-' * 96}")

    for i, (status, t, issues) in enumerate(all_trades, 1):
        exp = t.get("expiry", "N/A")
        credit = t["net_credit"]
        credit_label = "credit" if credit >= 0 else "debit"
        credit_str = f"{cur} {abs(credit):.2f}"
        risk_str = f"{cur} {t['max_risk']:,.0f}" if t.get("max_risk") else "undef"
        lot = t["lot_size"]
        wing = _compute_wing_width(t)
        total_prem = abs(credit) * lot
        total_prem_str = f"{cur} {total_prem:,.2f}"

        print(hdr_fmt.format(
            i, status, t["ticker"], t["structure"], exp,
            credit_str, risk_str, lot, wing,
        ))

        # For rejected trades, always show rejection reason (even without --detail)
        if status == "REJECTED" and issues:
            for issue in issues:
                print(f"         REASON: {issue}")

        # Per-leg detail when --detail is set
        if detail:
            for leg in t["legs"]:
                print(_format_leg_row(leg, cur))
            # Net line
            print(f"    NET {credit_label}: {cur} {abs(credit):.2f} x {lot} lot = {total_prem_str} total premium")
            print()

    # Summary stats by structure
    print(f"\n{'=' * 100}")
    print(f"  SUMMARY BY STRUCTURE")
    print(f"{'=' * 100}\n")

    struct_stats: dict[str, dict[str, int]] = {}
    for status, t, _ in all_trades:
        s = t["structure"]
        if s not in struct_stats:
            struct_stats[s] = {"approved": 0, "rejected": 0}
        if status == "APPROVED":
            struct_stats[s]["approved"] += 1
        else:
            struct_stats[s]["rejected"] += 1

    sfmt = "  {:<25} {:>10} {:>10} {:>10}"
    print(sfmt.format("Structure", "Approved", "Rejected", "Total"))
    print(f"  {'-' * 57}")
    for s_name in sorted(struct_stats.keys()):
        st = struct_stats[s_name]
        print(sfmt.format(s_name, st["approved"], st["rejected"], st["approved"] + st["rejected"]))
    print(f"  {'-' * 57}")
    print(sfmt.format("TOTAL", approved, rejected, total))


def print_portfolio(portfolio: list[dict], market: str) -> None:
    """Print portfolio summary table."""
    cur = "INR" if market == "India" else "$"

    print(f"\n{'=' * 80}")
    print(f"  TRADE PORTFOLIO — {market} ({len(portfolio)} trades)")
    print(f"{'=' * 80}\n")

    fmt = "  {:<6} {:<12} {:<20} {:>10} {:>12} {:>8} {:>8}"
    print(fmt.format("#", "Ticker", "Structure", "Expiry", "Credit", "MaxRisk", "Lot"))
    print(f"  {'-' * 78}")

    for i, t in enumerate(portfolio, 1):
        exp = t.get("expiry", "N/A")
        credit_str = f"{cur} {t['net_credit']:.2f}"
        risk_str = f"{cur} {t['max_risk']:,.0f}" if t.get("max_risk") else "undef"
        print(fmt.format(i, t["ticker"], t["structure"], exp, credit_str, risk_str, t["lot_size"]))


def print_validation(results: list[dict]) -> tuple[int, int, int]:
    """Print validation results. Returns (passed, failed, errors)."""
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errors = sum(1 for r in results if r["status"] not in ("PASS", "FAIL"))

    print(f"\n{'=' * 80}")
    print(f"  VALIDATION RESULTS")
    print(f"{'=' * 80}\n")

    for r in results:
        status_marker = "PASS" if r["status"] == "PASS" else "FAIL" if r["status"] == "FAIL" else "ERR "
        line = f"  [{status_marker}] {r['id']}"
        if r.get("credit") is not None:
            line += f" | credit={r['credit']:.2f}"
        if r.get("issues"):
            line += f" | {'; '.join(r['issues'][:3])}"
        if r.get("reason"):
            line += f" | {r['reason']}"
        print(line)

    print(f"\n  Summary: {passed} PASS / {failed} FAIL / {errors} ERROR — {len(results)} total")
    return passed, failed, errors


def print_shadow(shadow: list[dict], market: str) -> None:
    """Print shadow list (non-tradeable trades)."""
    if not shadow:
        return
    cur = "INR" if market == "India" else "$"

    print(f"\n{'=' * 80}")
    print(f"  SHADOW LIST — {len(shadow)} trades (valid structure, failed validation)")
    print(f"{'=' * 80}\n")

    for t in shadow:
        issues_str = "; ".join(t.get("issues", [])[:2])
        print(f"  {t['id']}: {issues_str}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Pricing regression — real chain data")
    parser.add_argument("--market", choices=["India", "US"], default="India")
    parser.add_argument("--rebuild", action="store_true", help="Force rebuild entire portfolio")
    parser.add_argument("--reprice-only", action="store_true", help="Only reprice existing trades")
    parser.add_argument("--target", type=int, default=TARGET_TRADE_COUNT, help="Target trade count")
    parser.add_argument("--detail", action="store_true", help="Show per-leg detail for every trade")
    args = parser.parse_args()

    market = args.market
    tickers = INDIA_TICKERS if market == "India" else US_TICKERS
    portfolio_file = PORTFOLIO_FILE_INDIA if market == "India" else PORTFOLIO_FILE_US

    print(f"\n  Pricing Regression — {market} Market")
    print(f"  {'=' * 40}")

    # Connect
    print(f"\n  Connecting to broker...")
    try:
        md, mm, acct = connect_broker(market)
        print(f"  Connected.")
    except Exception as e:
        print(f"  FAILED: {e}")
        sys.exit(1)

    # Load existing portfolio
    if args.rebuild:
        portfolio = []
        print(f"  Rebuilding portfolio from scratch.")
    else:
        portfolio = load_portfolio(portfolio_file)
        print(f"  Loaded {len(portfolio)} existing trades from {portfolio_file.name}")

    # Prune expired
    portfolio, removed = prune_expired(portfolio)
    if removed:
        print(f"  Pruned {removed} expired trades.")

    # Replenish
    shadow = []
    if not args.reprice_only and len(portfolio) < args.target:
        needed = args.target - len(portfolio)
        print(f"\n  Building {needed} new trades from live chains...\n")
        new_trades, shadow = replenish_portfolio(portfolio, md, tickers, market, args.target)
        portfolio.extend(new_trades)
        print(f"\n  Added {len(new_trades)} new trades. Portfolio: {len(portfolio)}")

    # Print portfolio
    print_portfolio(portfolio, market)

    # Reprice and validate
    if portfolio:
        print(f"\n  Repricing {len(portfolio)} trades with current market data...\n")
        results = reprice_portfolio(portfolio, md, market)
        passed, failed, errors = print_validation(results)

        # Full evaluation report (approved + shadow/rejected)
        print_full_report(portfolio, shadow, market, detail=args.detail)

        # Save
        save_portfolio(portfolio, portfolio_file)
        print(f"\n  Portfolio saved to {portfolio_file}")

        # Save shadow separately
        if shadow:
            shadow_file = portfolio_file.with_name(portfolio_file.stem + "_shadow.json")
            save_portfolio(shadow, shadow_file)
            print(f"  Shadow list saved to {shadow_file}")

        # Exit code
        if failed > 0 or errors > 0:
            print(f"\n  REGRESSION: {failed} failures, {errors} errors")
            sys.exit(1)
        else:
            print(f"\n  ALL {passed} TRADES VALIDATED OK")
    else:
        print("\n  No trades in portfolio.")


if __name__ == "__main__":
    main()
