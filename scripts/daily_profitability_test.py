#!/usr/bin/env python3
"""Daily Profitability Test — Repeatable India Market Evaluation.

Run every market day (Mon-Fri, IST 9:30-15:00) to evaluate whether
the income_desk trading pipeline produces profitable, trustworthy
trade recommendations against LIVE Dhan data.

Usage::

    .venv_312/Scripts/python.exe scripts/daily_profitability_test.py
    .venv_312/Scripts/python.exe scripts/daily_profitability_test.py --sim   # offline mode
    .venv_312/Scripts/python.exe scripts/daily_profitability_test.py --verbose

What it tests (every run):
  1. Dhan API connectivity & option chain quality
  2. Regime detection on live data (NIFTY, BANKNIFTY + stocks)
  3. Trade recommendation quality (POP, EV, structure type)
  4. Validation gate pass/fail rates
  5. Position sizing sanity (lot-size aware)
  6. Option chain depth (OI, bid-ask spreads)
  7. Produces a GO / CAUTION / NO-GO profitability verdict

Output saved to: ~/.income_desk/profitability_reports/YYYY-MM-DD.json
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import traceback
import warnings
from datetime import date, datetime, time as dt_time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

# ── Config ──────────────────────────────────────────────────────────────────

INDIA_UNIVERSE = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK"]
CAPITAL_INR = 5_000_000  # 50 lakh
MIN_POP_INCOME = 0.55    # income trades need >55% POP
MIN_POP_DIRECTIONAL = 0.40
MIN_SCORE = 0.40
MAX_BID_ASK_PCT = 0.05   # 5% max spread for liquid options

# Scoring weights for the profitability verdict
WEIGHTS = {
    "dhan_connected": 15,
    "chain_quality": 15,
    "regime_detection": 15,
    "trade_quality": 25,
    "validation_gate": 15,
    "sizing_sanity": 15,
}


def _sep(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def _result(name: str, passed: bool, detail: str = "", score: float = 0) -> dict:
    icon = "\033[92mPASS\033[0m" if passed else "\033[91mFAIL\033[0m"
    det = f" — {detail}" if detail else ""
    print(f"  [{icon}] {name}{det}")
    return {"name": name, "passed": passed, "detail": detail, "score": score}


def run(use_sim: bool = False, verbose: bool = False) -> dict:
    """Execute the full profitability evaluation."""

    today = date.today()
    now_ist = datetime.now()  # Assume local time is IST or close enough
    results: list[dict] = []
    section_scores: dict[str, float] = {}

    print(f"{'=' * 60}")
    print(f"  DAILY PROFITABILITY TEST — {today.isoformat()}")
    print(f"  Universe: {', '.join(INDIA_UNIVERSE)}")
    print(f"  Capital: INR {CAPITAL_INR:,.0f} (₹{CAPITAL_INR/100_000:.0f} lakh)")
    weekday = today.strftime("%A")
    expiry = {"Tuesday": "FINNIFTY", "Wednesday": "BANKNIFTY", "Thursday": "NIFTY"}.get(weekday)
    if expiry:
        print(f"  TODAY: {weekday} — {expiry} expiry day!")
    print(f"{'=' * 60}")

    # ================================================================
    # SECTION 1: Dhan Connectivity
    # ================================================================
    _sep("1. DHAN CONNECTIVITY")

    md = mm = ma = None
    if use_sim:
        from income_desk.adapters.simulated import (
            SimulatedMetrics, create_india_trading,
        )
        from income_desk import DataService, MarketAnalyzer

        sim = create_india_trading()
        ma = MarketAnalyzer(
            data_service=DataService(),
            market_data=sim,
            market_metrics=SimulatedMetrics(sim),
        )
        r = _result("Dhan connection", True, "SIMULATED MODE (offline)", score=0.7)
        results.append(r)
        section_scores["dhan_connected"] = 0.7
    else:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            from income_desk.broker.dhan import connect_dhan
            md, mm, acct, _wl = connect_dhan()

            from income_desk import DataService, MarketAnalyzer
            ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm)

            r = _result("Dhan connection", True, f"provider={md.provider_name}, currency={md.currency}", score=1.0)
            results.append(r)
            section_scores["dhan_connected"] = 1.0
        except Exception as e:
            r = _result("Dhan connection", False, str(e), score=0.0)
            results.append(r)
            section_scores["dhan_connected"] = 0.0
            print("\n  Cannot proceed without data source. Use --sim for offline mode.")
            return _build_verdict(today, results, section_scores)

    # ================================================================
    # SECTION 2: Option Chain Quality (live broker only)
    # ================================================================
    _sep("2. OPTION CHAIN QUALITY")

    chain_scores: list[float] = []
    chain_details: dict[str, dict] = {}

    if md is not None:
        for ticker in ["NIFTY", "BANKNIFTY"]:
            try:
                raw_chain = md.get_option_chain(ticker)

                # Dhan returns list[OptionQuote] — normalise to list of dicts
                if raw_chain is None or len(raw_chain) == 0:
                    r = _result(f"Chain {ticker}", False, "empty chain", score=0.0)
                    chain_scores.append(0.0)
                    results.append(r)
                    continue

                # Convert OptionQuote objects to dicts if needed
                if hasattr(raw_chain[0], "__dict__"):
                    chain_list = [
                        vars(q) if not hasattr(q, "model_dump") else q.model_dump()
                        for q in raw_chain
                    ]
                elif isinstance(raw_chain[0], dict):
                    chain_list = raw_chain
                else:
                    chain_list = [{"raw": str(q)} for q in raw_chain]

                # Evaluate chain quality
                total_rows = len(chain_list)
                has_greeks = any(q.get("delta") is not None for q in chain_list)
                has_oi = sum(q.get("open_interest", 0) or 0 for q in chain_list) > 0
                has_iv = any(q.get("implied_volatility") is not None for q in chain_list)
                has_bid_ask = any(q.get("bid", 0) > 0 or q.get("ask", 0) > 0 for q in chain_list)

                avg_spread_pct = 0.0
                if has_bid_ask:
                    spreads = []
                    for q in chain_list:
                        b, a = q.get("bid", 0) or 0, q.get("ask", 0) or 0
                        m = (b + a) / 2
                        if m > 0:
                            spreads.append((a - b) / m)
                    avg_spread_pct = sum(spreads) / len(spreads) if spreads else 0.0

                total_oi = sum(q.get("open_interest", 0) or 0 for q in chain_list)

                quality = 0.0
                if total_rows > 20:
                    quality += 0.25
                if has_greeks:
                    quality += 0.25
                if has_oi and total_oi > 10_000:
                    quality += 0.25
                if has_iv:
                    quality += 0.25

                chain_details[ticker] = {
                    "rows": total_rows,
                    "greeks": has_greeks,
                    "oi": total_oi,
                    "iv": has_iv,
                    "avg_spread_pct": round(avg_spread_pct, 4) if avg_spread_pct else 0,
                }

                detail = (
                    f"{total_rows} strikes, OI={total_oi:,}, "
                    f"greeks={'Y' if has_greeks else 'N'}, "
                    f"IV={'Y' if has_iv else 'N'}, "
                    f"spread={avg_spread_pct:.2%}" if avg_spread_pct else f"{total_rows} strikes"
                )
                r = _result(f"Chain {ticker}", quality >= 0.5, detail, score=quality)
                chain_scores.append(quality)
                results.append(r)

            except Exception as e:
                r = _result(f"Chain {ticker}", False, str(e), score=0.0)
                chain_scores.append(0.0)
                results.append(r)
                if verbose:
                    traceback.print_exc()

        section_scores["chain_quality"] = sum(chain_scores) / max(len(chain_scores), 1)
    else:
        r = _result("Chain quality", True, "simulated — skipped", score=0.5)
        results.append(r)
        section_scores["chain_quality"] = 0.5

    # ================================================================
    # SECTION 3: Regime Detection
    # ================================================================
    _sep("3. REGIME DETECTION")

    regimes: dict[str, dict] = {}
    regime_scores: list[float] = []

    for ticker in INDIA_UNIVERSE:
        try:
            regime = ma.regime.detect(ticker, debug=verbose)
            label = {1: "R1 Low-Vol MR", 2: "R2 High-Vol MR", 3: "R3 Low-Vol Trend", 4: "R4 High-Vol Trend"}
            regimes[ticker] = {
                "regime": regime.regime,
                "confidence": regime.confidence,
                "label": label.get(regime.regime, f"R{regime.regime}"),
                "age_days": regime.model_age_days,
            }

            # Score: high confidence = good, R4 = tradeable but limited
            score = min(regime.confidence, 1.0)
            if regime.regime == 4:
                score *= 0.5  # R4 limits income plays

            r = _result(
                f"Regime {ticker}", True,
                f"{label.get(regime.regime, '?')} ({regime.confidence:.0%}), age={regime.model_age_days}d",
                score=score,
            )
            regime_scores.append(score)
            results.append(r)

        except Exception as e:
            r = _result(f"Regime {ticker}", False, str(e), score=0.0)
            regime_scores.append(0.0)
            results.append(r)

    tradeable = [t for t, r in regimes.items() if r["regime"] in (1, 2, 3)]
    r4_count = sum(1 for r in regimes.values() if r["regime"] == 4)
    print(f"\n  Tradeable: {len(tradeable)}/{len(INDIA_UNIVERSE)} "
          f"({r4_count} in R4 — skipped for income)")

    section_scores["regime_detection"] = sum(regime_scores) / max(len(regime_scores), 1)

    # ================================================================
    # SECTION 4: Trade Recommendation Quality
    # ================================================================
    _sep("4. TRADE RECOMMENDATION QUALITY")

    trade_scores: list[float] = []
    trade_details: list[dict] = []

    if tradeable:
        try:
            ranking = ma.ranking.rank(tradeable, skip_intraday=True, debug=verbose)
            top = ranking.top_trades[:10] if ranking else []

            income_trades = []
            directional_trades = []
            equity_trades = []

            for entry in top:
                st = entry.trade_spec.structure_type if entry.trade_spec else ""
                if st in ("equity_long", "equity_short"):
                    equity_trades.append(entry)
                elif st in ("iron_condor", "iron_butterfly", "credit_spread", "strangle", "straddle"):
                    income_trades.append(entry)
                else:
                    directional_trades.append(entry)

                detail = {
                    "ticker": entry.ticker,
                    "structure": str(st),
                    "score": entry.composite_score,
                    "verdict": entry.verdict,
                    "gaps": len(entry.data_gaps) if entry.data_gaps else 0,
                }
                trade_details.append(detail)

                badge = entry.trade_spec.strategy_badge if entry.trade_spec else str(st)
                print(f"    #{entry.rank:2d} {entry.ticker:12s} {badge:28s} "
                      f"score={entry.composite_score:.2f} {entry.verdict}")

            # Score trade quality
            total = len(top)
            if total == 0:
                trade_quality = 0.0
                print("  No trade recommendations generated.")
            else:
                # Prefer income trades, penalize equity trades
                income_pct = len(income_trades) / total
                equity_pct = len(equity_trades) / total
                avg_score = sum(e.composite_score for e in top) / total
                go_pct = sum(1 for e in top if e.verdict == "go") / total

                trade_quality = (
                    0.30 * income_pct +       # income trades are what we want
                    0.30 * avg_score +         # higher scores = better
                    0.25 * go_pct +            # go verdicts = better
                    0.15 * (1 - equity_pct)    # fewer equity = better
                )

                print(f"\n  Income: {len(income_trades)}, Directional: {len(directional_trades)}, "
                      f"Equity: {len(equity_trades)}")
                print(f"  Avg score: {avg_score:.2f}, Go rate: {go_pct:.0%}")

            trade_scores.append(trade_quality)
            r = _result("Trade quality", trade_quality > 0.3,
                         f"quality={trade_quality:.2f}", score=trade_quality)
            results.append(r)

        except Exception as e:
            r = _result("Ranking", False, str(e), score=0.0)
            trade_scores.append(0.0)
            results.append(r)
            if verbose:
                traceback.print_exc()
    else:
        print("  All tickers in R4 — no income plays available today.")
        r = _result("Trade quality", False, "no tradeable tickers", score=0.0)
        trade_scores.append(0.0)
        results.append(r)

    section_scores["trade_quality"] = sum(trade_scores) / max(len(trade_scores), 1)

    # ================================================================
    # SECTION 5: Validation Gate
    # ================================================================
    _sep("5. VALIDATION GATE")

    from income_desk.validation import run_daily_checks

    gate_scores: list[float] = []
    gate_pass = 0
    gate_fail = 0

    # Use actual ranked entries with trade_specs (not None)
    gate_entries = []
    if tradeable and 'ranking' in dir() and ranking:
        gate_entries = [e for e in ranking.top_trades[:10] if e.trade_spec is not None][:5]

    for entry in gate_entries:
        ticker = entry.ticker
        ts = entry.trade_spec
        try:
            tech = ma.technicals.snapshot(ticker)
            atr_pct = tech.atr_pct if tech else 1.0
            price = tech.current_price if tech else 100.0

            # Estimate realistic entry credit from trade spec
            entry_credit = 1.0
            if ts and ts.max_entry_price:
                entry_credit = ts.max_entry_price
            elif ts and ts.wing_width_points:
                # Rough estimate: 25-30% of wing width for credit trades
                entry_credit = ts.wing_width_points * 0.28

            rpt = run_daily_checks(
                ticker=ticker,
                trade_spec=ts,
                entry_credit=entry_credit,
                regime_id=regimes.get(ticker, {}).get("regime", 1),
                atr_pct=atr_pct,
                current_price=price,
                avg_bid_ask_spread_pct=0.03,
                dte=ts.target_dte if ts else 30,
                rsi=tech.rsi.value if tech and tech.rsi else 50,
                iv_rank=50.0,
                contracts=1,
            )

            passed = rpt.is_ready if rpt else False
            if passed:
                gate_pass += 1
            else:
                gate_fail += 1
                if rpt:
                    fails = [c.name for c in rpt.checks if c.severity.value == "fail"]
                    print(f"    {ticker}: BLOCKED — {', '.join(fails)}")

            gate_scores.append(1.0 if passed else 0.0)

        except Exception as e:
            gate_scores.append(0.0)
            gate_fail += 1
            if verbose:
                print(f"    {ticker}: ERROR — {e}")

    gate_rate = gate_pass / max(gate_pass + gate_fail, 1)
    r = _result("Validation gate", gate_rate > 0.3,
                 f"{gate_pass} pass / {gate_fail} fail ({gate_rate:.0%})", score=gate_rate)
    results.append(r)
    section_scores["validation_gate"] = gate_rate

    # ================================================================
    # SECTION 6: Position Sizing Sanity
    # ================================================================
    _sep("6. POSITION SIZING SANITY")

    from income_desk import MarketRegistry
    registry = MarketRegistry()

    sizing_ok = True
    for ticker in ["NIFTY", "BANKNIFTY"]:
        try:
            inst = registry.get_instrument(ticker)
            lot = inst.lot_size
            # Check: can we afford at least 1 lot with 4% risk?
            max_risk = CAPITAL_INR * 0.04
            # Approximate: 200pt wing IC on NIFTY = 200 * 25 = 5000 margin
            margin = registry.estimate_margin("iron_condor", ticker, wing_width=200)
            can_afford = margin.margin_amount <= max_risk
            r = _result(
                f"Sizing {ticker}", can_afford,
                f"lot={lot}, margin=INR {margin.margin_amount:,.0f}, "
                f"4% risk=INR {max_risk:,.0f}",
                score=1.0 if can_afford else 0.0,
            )
            results.append(r)
            if not can_afford:
                sizing_ok = False
        except Exception as e:
            r = _result(f"Sizing {ticker}", False, str(e), score=0.0)
            results.append(r)
            sizing_ok = False

    section_scores["sizing_sanity"] = 1.0 if sizing_ok else 0.5

    # ================================================================
    # VERDICT
    # ================================================================
    return _build_verdict(today, results, section_scores, regimes, trade_details, chain_details)


def _build_verdict(
    today: date,
    results: list[dict],
    section_scores: dict[str, float],
    regimes: dict | None = None,
    trade_details: list | None = None,
    chain_details: dict | None = None,
) -> dict:
    """Compute weighted profitability verdict."""

    _sep("PROFITABILITY VERDICT")

    # Weighted score
    total_weight = sum(WEIGHTS.values())
    weighted_score = sum(
        section_scores.get(k, 0) * w for k, w in WEIGHTS.items()
    ) / total_weight

    # Verdict thresholds
    if weighted_score >= 0.70:
        verdict = "GO"
        color = "\033[92m"
    elif weighted_score >= 0.45:
        verdict = "CAUTION"
        color = "\033[93m"
    else:
        verdict = "NO-GO"
        color = "\033[91m"

    reset = "\033[0m"

    print(f"\n  Section scores:")
    for section, weight in WEIGHTS.items():
        score = section_scores.get(section, 0)
        bar = "█" * int(score * 20) + "░" * (20 - int(score * 20))
        print(f"    {section:<20s} {bar} {score:.0%} (weight: {weight})")

    print(f"\n  {'=' * 40}")
    print(f"  WEIGHTED SCORE: {weighted_score:.0%}")
    print(f"  VERDICT: {color}{verdict}{reset}")
    print(f"  {'=' * 40}")

    # Actionable recommendations + enhancement suggestions
    enhancements: list[str] = []

    print(f"\n  RECOMMENDATIONS:")
    if section_scores.get("dhan_connected", 0) < 0.5:
        print("    - Fix Dhan API connection (check DHAN_TOKEN in .env)")
        enhancements.append("BROKER: Dhan token expired or missing — refresh via Dhan web console")
    if section_scores.get("chain_quality", 0) < 0.5:
        print("    - Option chains are thin — avoid illiquid strikes")
        enhancements.append("DATA: Improve chain quality — add OI threshold filter, pre-market IV fallback")
    if section_scores.get("chain_quality", 0) < 1.0 and section_scores.get("chain_quality", 0) >= 0.5:
        enhancements.append("DATA: Chain quality fair — add Greeks validation, check IV consistency across strikes")
    if section_scores.get("regime_detection", 0) < 0.5:
        print("    - Most tickers in R4 — reduce position sizes, risk-defined only")
        enhancements.append("REGIME: Too many R4 tickers — consider expanding universe or adding R4-safe strategies")
    if section_scores.get("trade_quality", 0) < 0.3:
        print("    - Trade quality low — check if ranking produces income strategies")
        enhancements.append("RANKING: No income trades — check iron_condor assessor, vol surface, _should_use_equity()")
    elif section_scores.get("trade_quality", 0) < 0.5:
        enhancements.append("RANKING: Trade quality moderate — add IV rank from broker to ranking, improve POP estimation")
    if section_scores.get("validation_gate", 0) < 0.3:
        print("    - Validation blocking too many trades — check IV rank, POP inputs")
        enhancements.append("VALIDATION: Gate blocking all trades — check entry_credit estimation, POP model accuracy")
    elif section_scores.get("validation_gate", 0) < 0.7:
        enhancements.append("VALIDATION: Some trades blocked — tune POP/EV thresholds for India market dynamics")
    if weighted_score >= 0.70:
        print("    - Pipeline looks profitable. Proceed with small size to validate.")
        enhancements.append("EXECUTION: Ready for paper trading — run for 5 consecutive GO days before live")

    # Always suggest next improvements
    if section_scores.get("trade_quality", 0) > 0 and section_scores.get("trade_quality", 0) < 0.8:
        enhancements.append("ENHANCEMENT: Wire real Dhan IV rank into ranking (currently using estimate)")
    if section_scores.get("regime_detection", 0) > 0:
        r4_pct = sum(1 for r in (regimes or {}).values() if r.get("regime") == 4) / max(len(regimes or {}), 1)
        if r4_pct > 0.3:
            enhancements.append(f"ENHANCEMENT: {r4_pct:.0%} universe in R4 — add VIX-based R4 strategies (long put spreads)")
    enhancements.append("ENHANCEMENT: Add POP calibration — track predicted vs actual win rates over 30 trades")
    enhancements.append("ENHANCEMENT: Add regime accuracy tracking — did R2 actually mean-revert?")

    if enhancements:
        print(f"\n  SUGGESTED ENHANCEMENTS ({len(enhancements)}):")
        for i, enh in enumerate(enhancements, 1):
            print(f"    {i}. {enh}")

    # Save report
    report = {
        "date": today.isoformat(),
        "market": "India",
        "verdict": verdict,
        "weighted_score": round(weighted_score, 4),
        "section_scores": {k: round(v, 4) for k, v in section_scores.items()},
        "regimes": regimes or {},
        "trade_count": len(trade_details or []),
        "trades": trade_details or [],
        "chain_quality": chain_details or {},
        "enhancements": enhancements,
        "test_results": [
            {"name": r["name"], "passed": r["passed"], "detail": r["detail"]}
            for r in results
        ],
    }

    report_dir = Path.home() / ".income_desk" / "profitability_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{today.isoformat()}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\n  Report saved: {report_path}")

    # Also save latest for quick lookup
    latest = report_dir / "latest.json"
    latest.write_text(json.dumps(report, indent=2, default=str))

    print(f"\n{'=' * 60}")
    return report


def main():
    parser = argparse.ArgumentParser(description="Daily Profitability Test — India Market")
    parser.add_argument("--sim", action="store_true", help="Use simulated data (offline mode)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show debug output")
    args = parser.parse_args()

    report = run(use_sim=args.sim, verbose=args.verbose)

    # Exit code for CI/automation
    if report.get("verdict") == "GO":
        sys.exit(0)
    elif report.get("verdict") == "CAUTION":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
