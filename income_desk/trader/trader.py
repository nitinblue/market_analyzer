#!/usr/bin/env python3
"""income_desk Trading Harness — clean single-pass trading workflow.

Flow: Market Context → Scan → Rank → Trade Ideas (with full leg details)

Usage:
    python -m income_desk.trader.trader                  # Interactive
    python -m income_desk.trader.trader --all --market=India
"""
from __future__ import annotations

import sys
import traceback
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cur(market: str) -> str:
    return "INR " if market == "India" else "$"


def _trunc(text: Any, width: int = 60) -> str:
    s = str(text) if text is not None else ""
    return s if len(s) <= width else s[: width - 3] + "..."


def _fetch_iv_rank_map(ma: Any, tickers: list[str]) -> dict[str, float]:
    iv_map: dict[str, float] = {}
    if not hasattr(ma, "market_metrics") or ma.market_metrics is None:
        return iv_map
    try:
        metrics = ma.market_metrics.get_metrics(tickers)
        for ticker, m in metrics.items():
            if hasattr(m, "iv_rank") and m.iv_rank is not None:
                iv_map[ticker] = m.iv_rank
    except Exception:
        pass
    return iv_map


# ---------------------------------------------------------------------------
# Step 1: Market Context — is it safe to trade?
# ---------------------------------------------------------------------------


def step_market_context(ma: Any, meta: Any, verbose: bool = False) -> bool:
    """Assess macro environment. Returns True if safe to trade."""
    from income_desk.trader.support import print_table

    print(f"\n{'=' * 70}")
    print("  STEP 1: MARKET CONTEXT")
    print(f"{'=' * 70}")

    try:
        ctx = ma.context.assess()

        print(f"\n  Environment : {ctx.environment_label}")
        print(f"  Trading     : {'ALLOWED' if ctx.trading_allowed else 'HALTED'}")
        print(f"  Size Factor : {ctx.position_size_factor:.0%}")
        print(f"  Risk Level  : {ctx.black_swan.alert_level} (score: {ctx.black_swan.composite_score:.2f})")

        if ctx.intermarket.entries:
            rows = [
                [e.ticker, f"R{e.regime}", f"{e.confidence:.0%}", e.trend_direction or ""]
                for e in ctx.intermarket.entries
            ]
            print_table("Intermarket", ["Ticker", "Regime", "Conf", "Direction"], rows)

        events_7 = ctx.macro.events_next_7_days
        if events_7:
            rows = [[str(e.date), e.name, e.impact] for e in events_7]
            print_table("Upcoming Events", ["Date", "Event", "Impact"], rows)

        print(f"\n  {ctx.summary}")

        if not ctx.trading_allowed:
            print("\n  TRADING HALTED — stopping here.")
            return False
        return True

    except Exception as exc:
        print(f"\n  [ERROR] market_context: {exc}")
        if verbose:
            traceback.print_exc()
        return True  # Don't block on context failure


# ---------------------------------------------------------------------------
# Step 2: Scan Universe — which tickers have opportunity?
# ---------------------------------------------------------------------------


def step_scan(ma: Any, tickers: list[str], meta: Any, verbose: bool = False) -> list[str]:
    """Scan universe, return tickers that passed."""
    from income_desk.trader.support import print_table

    print(f"\n{'=' * 70}")
    print("  STEP 2: SCAN UNIVERSE")
    print(f"{'=' * 70}")

    try:
        from income_desk.workflow import scan_universe
        from income_desk.workflow.scan_universe import ScanRequest

        req = ScanRequest(tickers=tickers, market=meta.market)
        resp = scan_universe(req, ma)

        if resp.candidates:
            # Dedupe by ticker, keep highest score
            best: dict[str, Any] = {}
            for c in resp.candidates:
                if c.ticker not in best or c.score > best[c.ticker].score:
                    best[c.ticker] = c
            candidates = sorted(best.values(), key=lambda c: c.score, reverse=True)

            print(f"\n  Scanned: {resp.total_scanned}  |  Passed: {len(candidates)} tickers")

            rows = [
                [c.ticker, f"{c.score:.2f}", c.regime_label or "?", _trunc(c.rationale, 50)]
                for c in candidates
            ]
            print_table("Candidates", ["Ticker", "Score", "Regime", "Rationale"], rows)

            return [c.ticker for c in candidates]
        else:
            print(f"\n  Scanned: {resp.total_scanned}  |  Passed: 0")

        print("  No candidates passed scan.")
        return tickers  # Fallback to full list

    except Exception as exc:
        print(f"\n  [ERROR] scan: {exc}")
        if verbose:
            traceback.print_exc()
        return tickers


# ---------------------------------------------------------------------------
# Step 3: Rank & Show Trade Ideas — the core output
# ---------------------------------------------------------------------------


def step_rank_and_show(
    ma: Any,
    tickers: list[str],
    meta: Any,
    verbose: bool = False,
) -> None:
    """Rank opportunities and show full trade details with leg pricing."""
    from income_desk.trader.support import print_table

    cur = _cur(meta.market)
    capital = meta.account_nlv or (500_000.0 if meta.market == "India" else 50_000.0)

    print(f"\n{'=' * 70}")
    print("  STEP 3: RANK OPPORTUNITIES")
    print(f"{'=' * 70}")

    # ── 3a. Rank ──
    try:
        from income_desk.workflow import rank_opportunities
        from income_desk.workflow.rank_opportunities import RankRequest

        iv_map = _fetch_iv_rank_map(ma, tickers)
        req = RankRequest(
            tickers=tickers,
            capital=capital,
            market=meta.market,
            iv_rank_map=iv_map or None,
        )
        resp = rank_opportunities(req, ma)
    except Exception as exc:
        print(f"\n  [ERROR] ranking: {exc}")
        if verbose:
            traceback.print_exc()
        return

    n_go = len(resp.trades)
    n_blocked = len(resp.blocked)
    print(f"\n  Tradeable: {resp.tradeable_count}  |  Assessed: {resp.total_assessed}  |  GO: {n_go}  |  NO GO: {n_blocked}")

    # ── 3b. Regime summary ──
    if resp.regime_summary:
        rows = [
            [t, f"R{r.regime_id}", r.regime_label, f"{r.confidence:.0%}", "Y" if r.tradeable else "N"]
            for t, r in resp.regime_summary.items()
        ]
        print_table("Regime Map", ["Ticker", "ID", "Label", "Confidence", "Tradeable"], rows)

    # ── 3c. NO GO trades — why each was rejected ──
    if resp.blocked:
        nogo_rows = []
        for b in resp.blocked:
            # Build legs string from strikes if available
            parts = []
            if b.short_put:
                parts.append(f"SP:{b.short_put:.0f}")
            if b.long_put:
                parts.append(f"LP:{b.long_put:.0f}")
            if b.short_call:
                parts.append(f"SC:{b.short_call:.0f}")
            if b.long_call:
                parts.append(f"LC:{b.long_call:.0f}")
            legs_str = " ".join(parts) if parts else "-"

            nogo_rows.append([
                b.ticker, b.structure,
                b.expiry or "-",
                legs_str,
                f"{b.score:.2f}" if b.score else "-",
                _trunc(b.reason, 60),
            ])
        print_table(
            f"NO GO ({len(resp.blocked)} trades)",
            ["Ticker", "Strategy", "Expiry", "Legs", "Score", "Reason"],
            nogo_rows,
        )

    if not resp.trades:
        print("\n  No actionable trades found.")
        return

    # ── 3d. GO trades — full details ──
    go_rows = []
    for t in resp.trades:
        parts = []
        if t.short_put:
            parts.append(f"SP:{t.short_put:.0f}")
        if t.long_put:
            parts.append(f"LP:{t.long_put:.0f}")
        if t.short_call:
            parts.append(f"SC:{t.short_call:.0f}")
        if t.long_call:
            parts.append(f"LC:{t.long_call:.0f}")
        legs_str = " ".join(parts) if parts else "-"

        go_rows.append([
            t.rank, t.ticker, t.structure, t.expiry or "-",
            f"{t.pop_pct * 100:.0f}%" if t.pop_pct else "-",
            f"{cur}{t.entry_credit:.2f}" if t.entry_credit else "-",
            f"{cur}{t.max_profit:,.0f}" if t.max_profit else "-",
            f"{cur}{t.max_risk:,.0f}" if t.max_risk else "-",
            t.lot_size or "-",
            t.contracts or "-",
            legs_str,
            _trunc(t.rationale or t.verdict, 40),
        ])
    print_table(
        f"GO ({len(resp.trades)} trades)",
        ["#", "Ticker", "Structure", "Expiry", "POP", "Credit",
         "MaxProfit", "MaxLoss", "Lot", "Lots", "Legs", "Rationale"],
        go_rows,
    )

    # ── 3e. Full leg details for ALL trades (GO + NO GO with strikes) ──
    print(f"\n{'=' * 70}")
    print("  TRADE DETAILS (leg-level)")
    print(f"{'=' * 70}")

    # Build unified list: GO trades first, then NO GO trades that have strikes
    all_details = []
    for t in resp.trades:
        all_details.append({
            "ticker": t.ticker, "structure": t.structure, "verdict": "GO",
            "sp": t.short_put, "lp": t.long_put, "sc": t.short_call, "lc": t.long_call,
            "expiry": t.expiry, "lot_size": t.lot_size, "wing_width": t.wing_width,
            "entry_credit": t.entry_credit, "max_profit": t.max_profit,
            "max_loss": t.max_risk, "pop": t.pop_pct, "ev": t.expected_value,
            "contracts": t.contracts, "rationale": t.rationale,
            "data_gaps": t.data_gaps, "rank": t.rank,
        })
    for b in resp.blocked:
        if b.short_put or b.short_call or b.long_put or b.long_call:
            all_details.append({
                "ticker": b.ticker, "structure": b.structure, "verdict": f"NO GO",
                "sp": b.short_put, "lp": b.long_put, "sc": b.short_call, "lc": b.long_call,
                "expiry": b.expiry, "lot_size": None, "wing_width": None,
                "entry_credit": None, "max_profit": None,
                "max_loss": None, "pop": None, "ev": None,
                "contracts": None, "rationale": b.reason,
                "data_gaps": None, "rank": None,
            })

    for d in all_details:
        label = f"#{d['rank']} " if d['rank'] else ""
        print(f"\n  --- {label}{d['ticker']} {d['structure']} [{d['verdict']}] ---")

        # Strikes + expiry
        print(f"  Expiry       : {d['expiry'] or '-'}")
        if d['sp']:
            print(f"  Short Put    : {d['sp']:.0f}")
        if d['lp']:
            print(f"  Long Put     : {d['lp']:.0f}")
        if d['sc']:
            print(f"  Short Call   : {d['sc']:.0f}")
        if d['lc']:
            print(f"  Long Call    : {d['lc']:.0f}")

        # P&L (GO trades only)
        if d['verdict'] == "GO":
            print(f"  Lot size     : {d['lot_size'] or '-'}")
            print(f"  Wing width   : {d['wing_width'] or '-'}")
            if d['entry_credit']:
                print(f"  Credit/share : {cur}{d['entry_credit']:.2f}")
            if d['max_profit']:
                print(f"  Max profit   : {cur}{d['max_profit']:,.2f}")
            if d['max_loss']:
                print(f"  Max loss     : {cur}{d['max_loss']:,.2f}")
            if d['pop']:
                print(f"  POP          : {d['pop'] * 100:.1f}%")
            if d['ev']:
                print(f"  EV           : {cur}{d['ev']:,.2f}")
            if d['contracts']:
                print(f"  Contracts    : {d['contracts']}")
        if d['rationale']:
            print(f"  Rationale    : {_trunc(d['rationale'], 70)}")
        if d.get('data_gaps'):
            print(f"  Data gaps    : {', '.join(d['data_gaps'][:3])}")

        # ── Price from broker (live leg quotes) ──
        try:
            from income_desk.workflow import price_trade
            from income_desk.workflow.price_trade import PriceRequest

            legs = []
            if d['sp']:
                legs.append({"strike": d['sp'], "option_type": "put", "action": "sell"})
            if d['lp']:
                legs.append({"strike": d['lp'], "option_type": "put", "action": "buy"})
            if d['sc']:
                legs.append({"strike": d['sc'], "option_type": "call", "action": "sell"})
            if d['lc']:
                legs.append({"strike": d['lc'], "option_type": "call", "action": "buy"})

            if legs:
                preq = PriceRequest(ticker=d['ticker'], legs=legs, market=meta.market)
                presp = price_trade(preq, ma)

                if presp.leg_quotes:
                    quote_rows = [
                        [
                            f"{d['ticker']} {lq.strike:.0f} {'CE' if lq.option_type == 'call' else 'PE'}",
                            lq.action,
                            f"{cur}{lq.bid:.2f}" if lq.bid is not None else "-",
                            f"{cur}{lq.ask:.2f}" if lq.ask is not None else "-",
                            f"{cur}{lq.mid:.2f}" if lq.mid is not None else "-",
                            f"{lq.iv * 100:.1f}%" if lq.iv is not None else "-",
                            f"{lq.delta:.3f}" if lq.delta is not None else "-",
                        ]
                        for lq in presp.leg_quotes
                    ]
                    print_table(
                        "Leg Quotes",
                        ["Instrument", "Action", "Bid", "Ask", "Mid", "IV", "Delta"],
                        quote_rows,
                    )

                    if presp.net_credit is not None:
                        print(f"  Live credit  : {cur}{presp.net_credit:.2f}")
                    if presp.fill_quality is not None:
                        print(f"  Fill quality : {presp.fill_quality}")
        except Exception as exc:
            if verbose:
                print(f"  [pricing error: {exc}]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    from income_desk.trader.support import (
        parse_args,
        pick_market,
        pick_tickers,
        print_banner,
        setup,
    )

    args = parse_args()

    import logging
    if not args.verbose:
        logging.getLogger("income_desk").setLevel(logging.ERROR)
        logging.getLogger("fredapi").setLevel(logging.ERROR)

    # Connect
    market = pick_market(preset=args.market)
    print(f"\n  Connecting to {market} market...")
    ma, meta = setup(market)

    # Tickers
    tickers = pick_tickers(market, meta)

    # Banner
    print_banner(meta)

    # Step 1: Market context
    safe = step_market_context(ma, meta, args.verbose)
    if not safe:
        return

    # Step 2: Scan
    scan_tickers = step_scan(ma, tickers, meta, args.verbose)

    # Step 3: Rank + full trade details
    step_rank_and_show(ma, scan_tickers, meta, args.verbose)

    print(f"\n  {'=' * 70}")
    print("  Done.")
    print(f"  {'=' * 70}\n")


if __name__ == "__main__":
    main()
