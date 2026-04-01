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

        print(f"\n  Scanned: {resp.total_scanned}  |  Passed: {resp.total_passed}")

        if resp.candidates:
            # Dedupe by ticker, keep highest score
            best: dict[str, Any] = {}
            for c in resp.candidates:
                if c.ticker not in best or c.score > best[c.ticker].score:
                    best[c.ticker] = c
            candidates = sorted(best.values(), key=lambda c: c.score, reverse=True)

            rows = [
                [c.ticker, f"{c.score:.2f}", c.regime_label or "?", _trunc(c.rationale, 50)]
                for c in candidates
            ]
            print_table("Candidates", ["Ticker", "Score", "Regime", "Rationale"], rows)

            return [c.ticker for c in candidates]

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

    print(f"\n  Tradeable: {resp.tradeable_count}  |  Assessed: {resp.total_assessed}")

    # ── 3b. Regime summary ──
    if resp.regime_summary:
        rows = [
            [t, f"R{r.regime_id}", r.regime_label, f"{r.confidence:.0%}", "Y" if r.tradeable else "N"]
            for t, r in resp.regime_summary.items()
        ]
        print_table("Regime Map", ["Ticker", "ID", "Label", "Confidence", "Tradeable"], rows)

    # ── 3c. Blocked trades ──
    if resp.blocked:
        rows = [
            [b.ticker, b.structure, f"{b.score:.2f}" if b.score else "-", _trunc(b.reason, 50)]
            for b in resp.blocked
        ]
        print_table("Blocked", ["Ticker", "Structure", "Score", "Reason"], rows)

    if not resp.trades:
        print("\n  No actionable trades found.")
        return

    # ── 3d. Trade ideas summary ──
    rows = [
        [
            t.rank, t.ticker, t.structure, t.expiry or "-",
            f"{t.composite_score:.2f}", t.verdict,
            f"{t.pop_pct * 100:.0f}%" if t.pop_pct else "-",
            f"{cur}{t.entry_credit:.2f}" if t.entry_credit else "-",
            f"{cur}{t.max_profit:,.0f}" if t.max_profit else "-",
            f"{cur}{t.max_risk:,.0f}" if t.max_risk else "-",
            t.contracts or "-",
            t.credit_source or "?",
        ]
        for t in resp.trades
    ]
    print_table(
        "Trade Ideas",
        ["#", "Ticker", "Structure", "Expiry", "Score", "Verdict",
         "POP", "Credit", "MaxProfit", "MaxLoss", "Lots", "Source"],
        rows,
    )

    # ── 3e. Full leg details for each trade ──
    print(f"\n{'=' * 70}")
    print("  TRADE DETAILS (leg-level pricing)")
    print(f"{'=' * 70}")

    for trade in resp.trades:
        print(f"\n  --- #{trade.rank} {trade.ticker} {trade.structure} ---")

        # Strike table
        strike_rows = []
        if trade.short_put:
            strike_rows.append([f"{trade.ticker} {trade.short_put:.0f} PE", "sell", trade.short_put])
        if trade.long_put:
            strike_rows.append([f"{trade.ticker} {trade.long_put:.0f} PE", "buy", trade.long_put])
        if trade.short_call:
            strike_rows.append([f"{trade.ticker} {trade.short_call:.0f} CE", "sell", trade.short_call])
        if trade.long_call:
            strike_rows.append([f"{trade.ticker} {trade.long_call:.0f} CE", "buy", trade.long_call])

        if strike_rows:
            print_table("Legs", ["Instrument", "Action", "Strike"], strike_rows)

        # P&L summary
        lot_size = trade.lot_size or "-"
        wing = trade.wing_width or "-"
        print(f"  Lot size     : {lot_size}")
        print(f"  Wing width   : {wing}")
        print(f"  Credit/share : {cur}{trade.entry_credit:.2f}" if trade.entry_credit else "")
        print(f"  Max profit   : {cur}{trade.max_profit:,.2f}" if trade.max_profit else "")
        print(f"  Max loss     : {cur}{trade.max_risk:,.2f}" if trade.max_risk else "")
        print(f"  POP          : {trade.pop_pct * 100:.1f}%" if trade.pop_pct else "")
        print(f"  EV           : {cur}{trade.expected_value:,.2f}" if trade.expected_value else "")
        print(f"  Contracts    : {trade.contracts}")
        if trade.rationale:
            print(f"  Rationale    : {_trunc(trade.rationale, 70)}")
        if trade.data_gaps:
            print(f"  Data gaps    : {', '.join(trade.data_gaps[:3])}")

        # ── Price from broker (live leg quotes) ──
        try:
            from income_desk.workflow import price_trade
            from income_desk.workflow.price_trade import PriceRequest

            legs = []
            if trade.short_put and trade.long_put:
                legs.append({"strike": trade.short_put, "option_type": "put", "action": "sell"})
                legs.append({"strike": trade.long_put, "option_type": "put", "action": "buy"})
            if trade.short_call and trade.long_call:
                legs.append({"strike": trade.short_call, "option_type": "call", "action": "sell"})
                legs.append({"strike": trade.long_call, "option_type": "call", "action": "buy"})

            if legs:
                preq = PriceRequest(ticker=trade.ticker, legs=legs, market=meta.market)
                presp = price_trade(preq, ma)

                if presp.leg_quotes:
                    quote_rows = [
                        [
                            f"{trade.ticker} {lq.strike:.0f} {'CE' if lq.option_type == 'call' else 'PE'}",
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
                        print(f"  Live net credit : {cur}{presp.net_credit:.2f}")
                    if presp.fill_quality is not None:
                        print(f"  Fill quality    : {presp.fill_quality}")
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
