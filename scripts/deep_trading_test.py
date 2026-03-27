#!/usr/bin/env python3
"""Deep Trading Test — run every workflow, validate every trade, find every issue.

Tests the complete trading pipeline with live Dhan data:
1. Snapshot all tickers
2. Rank opportunities
3. For each GO trade: verify liquidity, validate gates, size position, price legs
4. Run monitoring, adjustment, overnight risk
5. Report every issue found

Usage:
    .venv_312/Scripts/python.exe scripts/deep_trading_test.py
"""
from __future__ import annotations

import sys
import io
import time
from datetime import date

sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from income_desk import MarketAnalyzer, DataService
from income_desk.broker.dhan import connect_dhan

TICKERS = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK"]
CAPITAL = 5_000_000

issues: list[str] = []
passes: list[str] = []


def ok(name: str, detail: str = ""):
    passes.append(f"{name}: {detail}")
    print(f"  [OK]   {name} — {detail}")


def fail(name: str, detail: str):
    issues.append(f"{name}: {detail}")
    print(f"  [FAIL] {name} — {detail}")


def main():
    print("Connecting to Dhan...")
    md, mm, acct, wl = connect_dhan()
    ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm)
    print(f"Connected. Market data: {md.provider_name}\n")

    # ================================================================
    # PHASE 1: Market Snapshot
    # ================================================================
    print("=" * 70)
    print("PHASE 1: MARKET SNAPSHOT")
    print("=" * 70)

    from income_desk.workflow import snapshot_market, SnapshotRequest
    snap = snapshot_market(SnapshotRequest(tickers=TICKERS, market="India"), ma)

    for ticker, s in snap.tickers.items():
        if s.price and s.price > 0:
            ok(f"Price {ticker}", f"{s.price:,.2f}")
        else:
            fail(f"Price {ticker}", "None or 0")

        if s.regime_id:
            ok(f"Regime {ticker}", f"R{s.regime_id} ({s.regime_confidence:.0%})")
        else:
            fail(f"Regime {ticker}", "not detected")

        if s.atr_pct and s.atr_pct > 0:
            ok(f"ATR {ticker}", f"{s.atr_pct:.2f}%")
        else:
            fail(f"ATR {ticker}", "missing")

    # ================================================================
    # PHASE 2: Rank Opportunities
    # ================================================================
    print(f"\n{'=' * 70}")
    print("PHASE 2: RANK OPPORTUNITIES")
    print("=" * 70)

    from income_desk.workflow import rank_opportunities, RankRequest
    ranked = rank_opportunities(
        RankRequest(tickers=TICKERS, capital=CAPITAL, market="India"),
        ma,
    )

    print(f"\n  Tradeable: {ranked.tradeable_count}/{len(ranked.regime_summary)}")
    print(f"  Trades: {len(ranked.trades)}, Blocked: {len(ranked.blocked)}")
    print(f"  Total assessed: {ranked.total_assessed}")

    if ranked.meta.warnings:
        for w in ranked.meta.warnings:
            fail("Ranking warning", w)

    # ================================================================
    # PHASE 3: Validate Every Trade (What-If)
    # ================================================================
    print(f"\n{'=' * 70}")
    print("PHASE 3: VALIDATE EVERY TRADE")
    print("=" * 70)

    from income_desk.workflow import validate_trade, ValidateRequest

    for t in ranked.trades:
        print(f"\n  --- {t.ticker} {t.strategy_badge} (score={t.composite_score:.2f}) ---")

        # Check liquid strikes
        if t.short_put is not None:
            ok(f"Liquid strikes {t.ticker}",
               f"SP={t.short_put:.0f} LP={t.long_put:.0f} SC={t.short_call:.0f} LC={t.long_call:.0f}")
            ok(f"OI {t.ticker}",
               f"SP_OI={t.short_put_oi:,d} SC_OI={t.short_call_oi:,d}")
        else:
            fail(f"Liquid strikes {t.ticker}", "NOT VERIFIED — strikes may not exist in chain")

        # POP
        if t.pop_pct is not None:
            if t.pop_pct >= 0.55:
                ok(f"POP {t.ticker}", f"{t.pop_pct:.0%}")
            elif t.pop_pct >= 0.40:
                ok(f"POP {t.ticker}", f"{t.pop_pct:.0%} (marginal)")
            else:
                fail(f"POP {t.ticker}", f"{t.pop_pct:.0%} — too low for income")
        else:
            fail(f"POP {t.ticker}", "None — not computed")

        # Contracts & margin
        if t.contracts and t.contracts > 0:
            margin_per = (t.max_risk / t.contracts) if t.contracts else 0
            pct = (t.max_risk or 0) / CAPITAL
            if pct > 0.05:
                fail(f"Margin {t.ticker}", f"{t.contracts} lots, INR {t.max_risk:,.0f} ({pct:.1%}) — exceeds 5%")
            else:
                ok(f"Margin {t.ticker}", f"{t.contracts} lots x INR {margin_per:,.0f} = INR {t.max_risk:,.0f} ({pct:.1%})")
        else:
            fail(f"Sizing {t.ticker}", "0 contracts")

        # Credit
        if t.net_credit_per_unit and t.net_credit_per_unit > 0:
            total_credit = t.net_credit_per_unit * (t.lot_size or 1) * (t.contracts or 1)
            ok(f"Credit {t.ticker}", f"INR {t.net_credit_per_unit:.2f}/unit = INR {total_credit:,.0f} total")
        else:
            fail(f"Credit {t.ticker}", "no credit data — can't assess profitability")

        # Validate through gate
        try:
            tech = ma.technicals.snapshot(t.ticker)
            v = validate_trade(ValidateRequest(
                ticker=t.ticker,
                entry_credit=t.net_credit_per_unit or t.entry_credit or 1.0,
                regime_id=ranked.regime_summary.get(t.ticker).regime_id if ranked.regime_summary.get(t.ticker) else 1,
                atr_pct=tech.atr_pct if tech else 1.0,
                current_price=tech.current_price if tech else 100.0,
                dte=t.target_dte or 30,
                rsi=tech.rsi.value if tech and tech.rsi else 50,
                iv_rank=50.0,
                contracts=t.contracts or 1,
            ))
            if v.is_ready:
                ok(f"Validation {t.ticker}", f"PASS ({len(v.gates)} gates)")
            else:
                fail(f"Validation {t.ticker}", f"FAILED: {v.failed_gates}")
        except Exception as e:
            fail(f"Validation {t.ticker}", str(e))

    # ================================================================
    # PHASE 4: Monitor & Risk
    # ================================================================
    print(f"\n{'=' * 70}")
    print("PHASE 4: POSITION MONITORING & RISK")
    print("=" * 70)

    from income_desk.workflow import monitor_positions, MonitorRequest, assess_overnight_risk, OvernightRiskRequest
    from income_desk.workflow._types import OpenPosition
    from income_desk.workflow import check_expiry_day, ExpiryDayRequest

    # Create simulated positions from proposed trades
    positions = []
    for t in ranked.trades:
        positions.append(OpenPosition(
            trade_id=f"{t.ticker}-IC", ticker=t.ticker,
            structure_type=t.structure, order_side="credit",
            entry_price=t.net_credit_per_unit or 1.0,
            current_mid_price=(t.net_credit_per_unit or 1.0) * 0.6,
            contracts=t.contracts or 1,
            dte_remaining=t.target_dte or 3,
            regime_id=ranked.regime_summary.get(t.ticker).regime_id if ranked.regime_summary.get(t.ticker) else 1,
            lot_size=t.lot_size or 150,
        ))

    if positions:
        # Monitor
        try:
            m = monitor_positions(MonitorRequest(positions=positions, market="India"), ma)
            for s in m.statuses:
                ok(f"Monitor {s.ticker}", f"action={s.action} urgency={s.urgency}")
        except Exception as e:
            fail("Monitor", str(e))

        # Overnight risk
        try:
            o = assess_overnight_risk(OvernightRiskRequest(positions=positions, market="India"), ma)
            for entry in o.entries:
                ok(f"Overnight {entry.ticker}", f"risk={entry.risk_level}")
        except Exception as e:
            fail("Overnight risk", str(e))

        # Expiry check
        try:
            ed = check_expiry_day(ExpiryDayRequest(positions=positions, market="India"), ma)
            ok("Expiry check", f"index={ed.expiry_index} expiry_positions={ed.expiry_positions_count}")
        except Exception as e:
            fail("Expiry check", str(e))

    # ================================================================
    # PHASE 5: Portfolio Health
    # ================================================================
    print(f"\n{'=' * 70}")
    print("PHASE 5: PORTFOLIO HEALTH")
    print("=" * 70)

    from income_desk.workflow import check_portfolio_health, HealthRequest

    try:
        h = check_portfolio_health(
            HealthRequest(tickers=TICKERS, capital=CAPITAL, market="India"), ma,
        )
        ok("Sentinel", h.sentinel_signal)
        ok("Data trust", h.data_trust)
        ok("Risk budget", f"INR {h.risk_budget_remaining:,.0f} remaining")
    except Exception as e:
        fail("Portfolio health", str(e))

    # ================================================================
    # PHASE 6: Blocked Trade Analysis
    # ================================================================
    if ranked.blocked:
        print(f"\n{'=' * 70}")
        print("PHASE 6: BLOCKED TRADE ANALYSIS")
        print("=" * 70)
        for b in ranked.blocked:
            print(f"  {b.ticker:<12} {b.structure:<20} {b.reason}")

    # ================================================================
    # SUMMARY
    # ================================================================
    print(f"\n{'=' * 70}")
    print("DEEP TEST SUMMARY")
    print("=" * 70)
    print(f"  Passes: {len(passes)}")
    print(f"  Issues: {len(issues)}")

    if issues:
        print(f"\n  ISSUES FOUND:")
        for i, issue in enumerate(issues, 1):
            print(f"    {i}. {issue}")
    else:
        print(f"\n  ALL CLEAR — no issues found")

    print(f"\n{'=' * 70}")


if __name__ == "__main__":
    main()
