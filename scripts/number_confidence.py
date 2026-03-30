#!/usr/bin/env python3
"""Number confidence checker — verifies every computed value against broker data.

Connects to broker, fetches real data, computes values, cross-checks.
Reports confidence per data point with evidence.

Usage:
    python scripts/number_confidence.py --market India
    python scripts/number_confidence.py --market US
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date

logging.basicConfig(level=logging.ERROR)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def check_underlying_prices(md, tickers: list[str], market: str) -> list[dict]:
    """Verify underlying prices from broker match expected ranges."""
    results = []
    for ticker in tickers:
        try:
            price = md.get_underlying_price(ticker)
            status = "PASS" if price and price > 0 else "FAIL"
            results.append({
                "check": f"price({ticker})",
                "value": f"{price:.2f}" if price else "None",
                "status": status,
                "reason": "" if status == "PASS" else "Price is None or 0",
            })
        except Exception as e:
            results.append({
                "check": f"price({ticker})",
                "value": "ERROR",
                "status": "FAIL",
                "reason": str(e)[:50],
            })
    return results


def check_chain_data(md, ticker: str, market: str) -> list[dict]:
    """Verify chain data quality for a single ticker."""
    results = []

    try:
        chain = md.get_option_chain(ticker)
    except Exception as e:
        return [{"check": f"chain({ticker})", "value": "ERROR", "status": "FAIL", "reason": str(e)[:50]}]

    results.append({
        "check": f"chain({ticker}).count",
        "value": str(len(chain)),
        "status": "PASS" if len(chain) > 10 else "FAIL",
        "reason": "" if len(chain) > 10 else "Too few quotes",
    })

    liquid = [q for q in chain if q.bid > 0 and q.ask > 0]
    results.append({
        "check": f"chain({ticker}).liquid",
        "value": str(len(liquid)),
        "status": "PASS" if len(liquid) > 5 else "FAIL",
        "reason": "" if len(liquid) > 5 else "Too few liquid quotes",
    })

    # Check IV range
    ivs = [q.implied_volatility for q in liquid if q.implied_volatility is not None]
    if ivs:
        min_iv, max_iv = min(ivs), max(ivs)
        iv_ok = 0.01 < min_iv and max_iv < 5.0
        results.append({
            "check": f"chain({ticker}).iv_range",
            "value": f"{min_iv:.2f}-{max_iv:.2f}",
            "status": "PASS" if iv_ok else "FAIL",
            "reason": "" if iv_ok else f"IV out of range",
        })
    else:
        results.append({
            "check": f"chain({ticker}).iv_range",
            "value": "no IV data",
            "status": "FAIL",
            "reason": "No IV on any liquid quote",
        })

    # Check delta range
    deltas = [q.delta for q in liquid if q.delta is not None]
    if deltas:
        delta_ok = all(-1.0 <= d <= 1.0 for d in deltas)
        results.append({
            "check": f"chain({ticker}).delta_range",
            "value": f"{min(deltas):.3f} to {max(deltas):.3f}",
            "status": "PASS" if delta_ok else "FAIL",
            "reason": "" if delta_ok else "Delta out of [-1, 1]",
        })

    # Check bid < ask
    inverted = [q for q in liquid if q.ask < q.bid]
    results.append({
        "check": f"chain({ticker}).bid_ask_order",
        "value": f"{len(inverted)} inverted",
        "status": "PASS" if len(inverted) == 0 else "FAIL",
        "reason": "" if not inverted else f"{len(inverted)} quotes with ask < bid",
    })

    # Check spreads reasonable
    wide = [q for q in liquid if q.mid > 0 and (q.ask - q.bid) / q.mid > 0.50]
    results.append({
        "check": f"chain({ticker}).spread_quality",
        "value": f"{len(wide)}/{len(liquid)} wide (>50%)",
        "status": "PASS" if len(wide) < len(liquid) * 0.5 else "WARN",
        "reason": "" if len(wide) < len(liquid) * 0.5 else "Most quotes have wide spreads",
    })

    return results


def check_pop_calculation(market: str) -> list[dict]:
    """Verify POP produces reasonable values for known inputs."""
    from income_desk.trade_lifecycle import estimate_pop
    from unittest.mock import MagicMock
    from income_desk.models.opportunity import LegAction
    from datetime import timedelta

    results = []

    # Test 1: 7-DTE iron butterfly, should be ~50-70%
    ts = MagicMock()
    ts.structure_type = "iron_butterfly"
    ts.target_dte = 7
    ts.wing_width_points = 10.0
    ts.lot_size = 100 if market == "US" else 25
    ts.order_side = "credit"
    legs = []
    price = 550.0 if market == "US" else 22000.0
    for strike, otype, action in [
        (price, "put", LegAction.SELL_TO_OPEN),
        (price, "call", LegAction.SELL_TO_OPEN),
        (price - 10 if market == "US" else price - 500, "put", LegAction.BUY_TO_OPEN),
        (price + 10 if market == "US" else price + 500, "call", LegAction.BUY_TO_OPEN),
    ]:
        leg = MagicMock()
        leg.strike = strike
        leg.option_type = otype
        leg.action = action
        leg.expiration = date.today() + timedelta(days=7)
        legs.append(leg)
    ts.legs = legs

    r = estimate_pop(ts, entry_price=5.0 if market == "US" else 200.0, regime_id=1, atr_pct=1.2, current_price=price)
    if r:
        pop_ok = 0.30 < r.pop_pct < 0.80
        results.append({
            "check": "pop(iron_butterfly_7dte)",
            "value": f"{r.pop_pct:.1%}",
            "status": "PASS" if pop_ok else "FAIL",
            "reason": "" if pop_ok else f"POP {r.pop_pct:.1%} outside 30-80% range for 7DTE IFly",
        })
    else:
        results.append({"check": "pop(iron_butterfly_7dte)", "value": "None", "status": "FAIL", "reason": "estimate_pop returned None"})

    # Test 2: 30-DTE iron condor with wide wings, should be ~60-85%
    ts2 = MagicMock()
    ts2.structure_type = "iron_condor"
    ts2.target_dte = 30
    ts2.wing_width_points = 5.0 if market == "US" else 50.0
    ts2.lot_size = 100 if market == "US" else 25
    ts2.order_side = "credit"
    legs2 = []
    wing = 5.0 if market == "US" else 50.0
    for strike, otype, action in [
        (price * 0.96, "put", LegAction.SELL_TO_OPEN),
        (price * 0.96 - wing, "put", LegAction.BUY_TO_OPEN),
        (price * 1.04, "call", LegAction.SELL_TO_OPEN),
        (price * 1.04 + wing, "call", LegAction.BUY_TO_OPEN),
    ]:
        leg = MagicMock()
        leg.strike = strike
        leg.option_type = otype
        leg.action = action
        leg.expiration = date.today() + timedelta(days=30)
        legs2.append(leg)
    ts2.legs = legs2

    r2 = estimate_pop(ts2, entry_price=2.0 if market == "US" else 80.0, regime_id=1, atr_pct=1.2, current_price=price)
    if r2:
        pop_ok = 0.40 < r2.pop_pct < 0.90
        results.append({
            "check": "pop(iron_condor_30dte)",
            "value": f"{r2.pop_pct:.1%}",
            "status": "PASS" if pop_ok else "FAIL",
            "reason": "" if pop_ok else f"POP {r2.pop_pct:.1%} outside 40-90% range for 30DTE IC",
        })
    else:
        results.append({"check": "pop(iron_condor_30dte)", "value": "None", "status": "FAIL", "reason": "estimate_pop returned None"})

    return results


def check_account(acct, market: str) -> list[dict]:
    """Verify account balance fields."""
    results = []
    try:
        bal = acct.get_balance()
        results.append({
            "check": "account.nlv",
            "value": f"{bal.net_liquidating_value:,.0f}",
            "status": "PASS" if bal.net_liquidating_value > 0 else "FAIL",
            "reason": "" if bal.net_liquidating_value > 0 else "NLV is 0",
        })
        results.append({
            "check": "account.buying_power",
            "value": f"{bal.derivative_buying_power:,.0f}",
            "status": "PASS" if bal.derivative_buying_power > 0 else "WARN",
            "reason": "" if bal.derivative_buying_power > 0 else "BP is 0 (may be legitimate if fully deployed)",
        })
    except Exception as e:
        results.append({"check": "account.balance", "value": "ERROR", "status": "FAIL", "reason": str(e)[:50]})
    return results


def check_repricing(md, ticker: str, market: str) -> list[dict]:
    """Verify PricingService reprice_trade produces consistent results."""
    from income_desk.workflow.pricing_service import reprice_trade
    from unittest.mock import MagicMock
    from income_desk.models.opportunity import LegAction
    from datetime import timedelta

    results = []

    try:
        chain = md.get_option_chain(ticker)
    except Exception:
        return [{"check": f"reprice({ticker})", "value": "ERROR", "status": "FAIL", "reason": "chain fetch failed"}]

    liquid = [q for q in chain if q.bid > 0 and q.ask > 0]
    if len(liquid) < 4:
        return [{"check": f"reprice({ticker})", "value": f"{len(liquid)} liquid", "status": "SKIP", "reason": "Not enough liquid quotes"}]

    # Build a trade from actual liquid strikes
    puts = sorted([q for q in liquid if q.option_type == "put"], key=lambda q: q.strike)
    calls = sorted([q for q in liquid if q.option_type == "call"], key=lambda q: q.strike)

    if len(puts) < 2 or len(calls) < 2:
        return [{"check": f"reprice({ticker})", "value": "few puts/calls", "status": "SKIP", "reason": "Need 2+ liquid puts and calls"}]

    # Pick ATM-ish strikes
    price = md.get_underlying_price(ticker) or 0
    short_put = min(puts, key=lambda q: abs(q.strike - price * 0.97))
    long_put = min(puts, key=lambda q: abs(q.strike - price * 0.94))
    short_call = min(calls, key=lambda q: abs(q.strike - price * 1.03))
    long_call = min(calls, key=lambda q: abs(q.strike - price * 1.06))

    ts = MagicMock()
    ts.structure_type = "iron_condor"
    ts.lot_size = liquid[0].lot_size
    ts.wing_width_points = short_put.strike - long_put.strike
    legs = []
    for q, action in [(short_put, LegAction.SELL_TO_OPEN), (long_put, LegAction.BUY_TO_OPEN),
                       (short_call, LegAction.SELL_TO_OPEN), (long_call, LegAction.BUY_TO_OPEN)]:
        leg = MagicMock()
        leg.strike = q.strike
        leg.option_type = q.option_type
        leg.action = action
        leg.expiration = q.expiration
        legs.append(leg)
    ts.legs = legs

    rp = reprice_trade(ts, chain, ticker, price, 1.5, 1)

    results.append({
        "check": f"reprice({ticker}).legs_found",
        "value": str(rp.legs_found),
        "status": "PASS" if rp.legs_found else "FAIL",
        "reason": rp.block_reason or "",
    })
    results.append({
        "check": f"reprice({ticker}).credit_source",
        "value": rp.credit_source,
        "status": "PASS" if rp.credit_source == "chain" else "FAIL",
        "reason": "",
    })
    results.append({
        "check": f"reprice({ticker}).credit",
        "value": f"{rp.entry_credit:.2f}",
        "status": "PASS" if rp.entry_credit > 0 else "WARN",
        "reason": "" if rp.entry_credit > 0 else "Zero or negative credit",
    })

    # Cross-check: manually compute credit from chain
    manual_credit = 0
    for leg in ts.legs:
        q = next((c for c in chain if c.strike == leg.strike and c.option_type == leg.option_type and c.bid > 0), None)
        if q:
            action_str = getattr(leg.action, "value", str(leg.action)).lower()
            if action_str in ("sto", "stc", "sell", "short"):
                manual_credit += q.mid
            else:
                manual_credit -= q.mid

    diff = abs(rp.entry_credit - manual_credit)
    results.append({
        "check": f"reprice({ticker}).cross_check",
        "value": f"reprice={rp.entry_credit:.2f} manual={manual_credit:.2f} diff={diff:.4f}",
        "status": "PASS" if diff < 0.01 else "FAIL",
        "reason": "" if diff < 0.01 else f"Repricing differs from manual by {diff:.4f}",
    })

    return results


def main():
    parser = argparse.ArgumentParser(description="Number confidence checker")
    parser.add_argument("--market", choices=["India", "US"], required=True)
    args = parser.parse_args()

    market = args.market

    from dotenv import load_dotenv
    load_dotenv()

    print(f"\n  Number Confidence Check — {market}")
    print(f"  {'=' * 50}\n")

    # Connect
    if market == "India":
        from income_desk.broker.dhan import connect_dhan
        md, mm, acct, wl = connect_dhan()
        tickers = ["NIFTY", "RELIANCE", "SBIN"]
    else:
        from income_desk.broker.tastytrade import connect_tastytrade
        md, mm, acct, wl = connect_tastytrade(is_paper=False)
        tickers = ["SPY", "QQQ", "IWM"]

    print(f"  Connected to {market} broker\n")

    all_results = []

    # 1. Underlying prices
    print("  Checking underlying prices...")
    all_results.extend(check_underlying_prices(md, tickers, market))

    # 2. Chain data quality
    print("  Checking chain data...")
    for ticker in tickers[:2]:  # First 2 to save time
        all_results.extend(check_chain_data(md, ticker, market))
        time.sleep(4 if market == "India" else 0)

    # 3. POP calculation
    print("  Checking POP calculation...")
    all_results.extend(check_pop_calculation(market))

    # 4. Account
    print("  Checking account...")
    if acct:
        all_results.extend(check_account(acct, market))

    # 5. Repricing cross-check
    print("  Checking repricing consistency...")
    for ticker in tickers[:1]:  # First ticker
        all_results.extend(check_repricing(md, ticker, market))

    # Report
    print(f"\n  {'=' * 70}")
    print(f"  NUMBER CONFIDENCE REPORT — {market}")
    print(f"  {'=' * 70}\n")

    passed = failed = warned = skipped = 0
    for r in all_results:
        marker = {"PASS": "OK", "FAIL": "XX", "WARN": "!!", "SKIP": "--"}[r["status"]]
        line = f"  [{marker}] {r['check']:<40s} {r['value']}"
        if r["reason"]:
            line += f"  ({r['reason']})"
        print(line)

        if r["status"] == "PASS":
            passed += 1
        elif r["status"] == "FAIL":
            failed += 1
        elif r["status"] == "WARN":
            warned += 1
        else:
            skipped += 1

    total = passed + failed + warned + skipped
    pct = 100 * passed / total if total > 0 else 0
    print(f"\n  {passed} PASS / {failed} FAIL / {warned} WARN / {skipped} SKIP — {total} checks")
    print(f"  Confidence: {pct:.0f}%")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
