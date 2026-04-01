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
    snapshot: Any = None,
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
            snapshot=snapshot,
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

        # Determine risk type and direction
        _defined = t.structure in ("iron_condor", "iron_butterfly", "credit_spread",
                                    "debit_spread", "calendar", "diagonal")
        risk_type = "Defined" if _defined else "Undefined"
        direction = getattr(t, 'direction', None) or (
            "neutral" if t.structure in ("iron_condor", "iron_butterfly") else
            "bearish" if "call" in (t.structure or "") else
            "bullish" if "put" in (t.structure or "") else "neutral"
        )

        go_rows.append([
            t.rank, t.ticker, t.structure, direction, risk_type,
            t.expiry or "-",
            f"{t.pop_pct * 100:.0f}%" if t.pop_pct else "-",
            f"{cur}{t.entry_credit:.2f}" if t.entry_credit else "-",
            t.lot_size or "-",
            t.contracts or "-",
            legs_str,
        ])
    print_table(
        f"GO ({len(resp.trades)} trades)",
        ["#", "Ticker", "Structure", "Direction", "Risk", "Expiry",
         "POP", "Credit", "Lot", "Lots", "Legs"],
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

    from income_desk.workflow import price_trade
    from income_desk.workflow.price_trade import PriceRequest

    for d in all_details:
        label = f"#{d['rank']} " if d['rank'] else ""
        print(f"\n  --- {label}{d['ticker']} {d['structure']} [{d['verdict']}] ---")

        # Fetch live leg quotes from broker
        leg_quotes = []
        net_credit_live = None
        fill_quality = None
        try:
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
                presp = price_trade(PriceRequest(ticker=d['ticker'], legs=legs, market=meta.market), ma)
                leg_quotes = presp.leg_quotes or []
                net_credit_live = presp.net_credit
                fill_quality = presp.fill_quality
        except Exception:
            pass

        # Build combined table: legs with OI
        if leg_quotes:
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
                for lq in leg_quotes
            ]
            print_table("Leg Quotes", ["Instrument", "Action", "Bid", "Ask", "Mid", "IV", "Delta"], quote_rows)

        # ALWAYS compute max profit / max risk from live bid/ask
        # The ranking credit is stale — live quotes are the truth
        lot_size_val = d['lot_size']
        credit_val = None
        max_profit_val = None
        max_risk_val = None
        wing_put = None
        wing_call = None
        be_low = None
        be_high = None
        underlying_price = None
        dte_val = None

        # Get underlying price
        try:
            underlying_price = ma.market_data.get_underlying_price(d['ticker']) if ma.market_data else None
        except Exception:
            pass

        # Compute DTE
        if d['expiry']:
            try:
                from datetime import date as _d
                exp = _d.fromisoformat(d['expiry'])
                dte_val = (exp - _d.today()).days
            except Exception:
                pass

        if leg_quotes:
            # Net credit/debit from live bid/ask
            live_net = 0.0
            sell_puts = {}   # strike -> bid
            buy_puts = {}    # strike -> ask
            sell_calls = {}
            buy_calls = {}
            for lq in leg_quotes:
                if lq.action == "sell" and lq.bid is not None and lq.bid > 0:
                    live_net += lq.bid
                    if lq.option_type == "put":
                        sell_puts[lq.strike] = lq
                    else:
                        sell_calls[lq.strike] = lq
                elif lq.action == "buy" and lq.ask is not None and lq.ask > 0:
                    live_net -= lq.ask
                    if lq.option_type == "put":
                        buy_puts[lq.strike] = lq
                    else:
                        buy_calls[lq.strike] = lq

            credit_val = live_net

            # Get lot size from broker chain
            if not lot_size_val:
                lot_size_val = getattr(leg_quotes[0], 'lot_size', None)
                if not lot_size_val:
                    try:
                        from income_desk.registry import MarketRegistry
                        lot_size_val = MarketRegistry().get_instrument(d['ticker'], meta.market).lot_size
                    except Exception:
                        lot_size_val = 1

            # Wing widths from actual strikes
            if sell_puts and buy_puts:
                wing_put = max(sell_puts.keys()) - min(buy_puts.keys())
            if sell_calls and buy_calls:
                wing_call = max(buy_calls.keys()) - min(sell_calls.keys())

            wing = min(w for w in [wing_put, wing_call] if w is not None and w > 0) if any(w and w > 0 for w in [wing_put, wing_call]) else None

            if live_net > 0 and lot_size_val:
                # Credit trade
                max_profit_val = live_net * lot_size_val
                if wing and wing > live_net:
                    max_risk_val = (wing - live_net) * lot_size_val
                # Breakevens
                if sell_puts:
                    be_low = max(sell_puts.keys()) - live_net
                if sell_calls:
                    be_high = min(sell_calls.keys()) + live_net
            elif live_net < 0 and lot_size_val:
                # Debit trade
                debit = abs(live_net)
                max_risk_val = debit * lot_size_val
                if wing and wing > debit:
                    max_profit_val = (wing - debit) * lot_size_val

        # Delta-derived POP cross-check
        pop_delta_str = "-"
        if leg_quotes:
            sell_deltas = [abs(lq.delta) for lq in leg_quotes if lq.action == "sell" and lq.delta]
            if len(sell_deltas) >= 2:
                pop_d = 1.0
                for sd in sell_deltas:
                    pop_d *= (1.0 - sd)
                pop_delta_str = f"{pop_d * 100:.0f}%"
            elif len(sell_deltas) == 1:
                pop_delta_str = f"{(1.0 - sell_deltas[0]) * 100:.0f}%"

        # EV from live data
        ev_str = "-"
        if max_profit_val and max_risk_val and d['pop']:
            ev = d['pop'] * max_profit_val - (1 - d['pop']) * max_risk_val
            ev_str = f"{cur}{ev:,.0f}"

        # R:R
        rr_str = "-"
        if max_profit_val and max_risk_val and max_risk_val > 0:
            rr_str = f"1:{max_profit_val / max_risk_val:.2f}"

        # Breakevens
        be_str = "-"
        if be_low or be_high:
            parts = []
            if be_low:
                parts.append(f"{be_low:.0f}")
            if be_high:
                parts.append(f"{be_high:.0f}")
            be_str = " - ".join(parts)

        # Wing
        wing_str = "-"
        if wing_put is not None and wing_call is not None and wing_put != wing_call:
            wing_str = f"{wing_put:.0f}/{wing_call:.0f}"
        elif wing_put or wing_call:
            wing_str = f"{(wing_put or wing_call):.0f}"

        # Credit/debit
        cd_str = "-"
        if credit_val is not None:
            cd_str = f"{cur}{credit_val:.2f}" if credit_val >= 0 else f"-{cur}{abs(credit_val):.2f}"

        # Horizontal trade summary (1 row of data)
        summary_headers = ["Underlying", "Expiry", "DTE", "Lot", "Wing",
                           "Credit", "MaxProfit", "MaxRisk", "R:R",
                           "Breakevens", "POP", "POP(d)", "EV", "Verdict"]
        summary_row = [[
            f"{cur}{underlying_price:,.2f}" if underlying_price else "-",
            d['expiry'] or "-",
            str(dte_val) if dte_val is not None else "-",
            str(lot_size_val or "-"),
            wing_str,
            cd_str,
            f"{cur}{max_profit_val:,.0f}" if max_profit_val is not None and max_profit_val > 0 else ("N/A" if d['structure'] in ("calendar", "diagonal") else "-"),
            "UNLIMITED" if d['structure'] in ("strangle", "straddle", "ratio_spread") and (max_risk_val is None or max_risk_val == 0) else (f"{cur}{max_risk_val:,.0f}" if max_risk_val is not None and max_risk_val > 0 else ("N/A" if d['structure'] in ("calendar", "diagonal") else "-")),
            rr_str,
            be_str,
            f"{d['pop'] * 100:.0f}%" if d['pop'] and d['pop'] > 0 else ("N/A" if d['structure'] in ("calendar", "diagonal") else "-"),
            pop_delta_str,
            ev_str,
            d['verdict'],
        ]]
        print_table("Trade Summary", summary_headers, summary_row)

        # Rationale on its own line
        if d['rationale']:
            print(f"  Rationale: {_trunc(d['rationale'], 90)}")


# ---------------------------------------------------------------------------
# Step 4: Monitor Positions
# ---------------------------------------------------------------------------


def step_monitor_positions(
    ma: Any,
    meta: Any,
    verbose: bool = False,
) -> None:
    """Fetch open positions from broker and show monitoring status."""
    from income_desk.trader.support import (
        broker_positions_to_open,
        load_positions,
        print_table,
    )

    print(f"\n{'=' * 70}")
    print("  STEP 4: MONITOR POSITIONS")
    print(f"{'=' * 70}")

    cur = _cur(meta.market)

    # Fetch broker positions
    broker_pos = load_positions(meta, interactive=False)
    if not broker_pos:
        print("\n  No open positions found.")
        return

    # Convert to OpenPosition for workflow
    open_positions = broker_positions_to_open(broker_pos, meta.market)
    if not open_positions:
        print(f"\n  {len(broker_pos)} equity-only positions (no option positions to monitor).")
        return

    # Detect regime for each position ticker
    for pos in open_positions:
        try:
            r = ma.regime.detect(pos.ticker)
            pos.regime_id = r.regime if isinstance(r.regime, int) else r.regime.value
        except Exception:
            pass

    # Run monitor workflow
    try:
        from income_desk.workflow.monitor_positions import MonitorRequest, monitor_positions
        req = MonitorRequest(positions=open_positions, market=meta.market)
        resp = monitor_positions(req, ma)
    except Exception as exc:
        print(f"\n  [ERROR] monitoring: {exc}")
        if verbose:
            traceback.print_exc()
        return

    # Display position status table
    rows = []
    for s in resp.statuses:
        pnl_str = f"{cur}{s.pnl:,.0f}" if s.pnl else "-"
        pnl_pct_str = f"{s.pnl_pct:+.1%}" if s.pnl_pct else "-"
        rows.append([
            s.ticker,
            s.trade_id,
            s.action.upper(),
            s.urgency.upper(),
            pnl_str,
            pnl_pct_str,
            _trunc(s.rationale, 50),
        ])

    print_table(
        f"Position Monitor ({len(resp.statuses)} positions | {resp.actions_needed} actions | {resp.critical_count} critical)",
        ["Ticker", "Trade ID", "Action", "Urgency", "P&L", "P&L%", "Rationale"],
        rows,
    )

    # Show adjustment recommendations for non-hold positions
    action_positions = [s for s in resp.statuses if s.action != "hold"]
    if action_positions:
        print(f"\n  ADJUSTMENT RECOMMENDATIONS:")
        try:
            from income_desk.workflow.adjust_position import AdjustRequest, adjust_position
            for s in action_positions:
                # Find matching OpenPosition
                pos = next((p for p in open_positions if p.trade_id == s.trade_id), None)
                if pos is None:
                    continue
                adj_req = AdjustRequest(
                    trade_id=pos.trade_id,
                    ticker=pos.ticker,
                    structure_type=pos.structure_type,
                    entry_price=pos.entry_price,
                    current_mid_price=pos.current_mid_price or pos.entry_price,
                    dte_remaining=pos.dte_remaining,
                    pnl_pct=s.pnl_pct,
                )
                adj_resp = adjust_position(adj_req, ma)
                rec = adj_resp.recommendation
                print(f"  {pos.ticker} ({pos.structure_type}): "
                      f"{rec.action.upper()} [{rec.urgency}] — {rec.rationale}")
        except Exception as exc:
            print(f"  [ERROR] adjustment analysis: {exc}")
            if verbose:
                traceback.print_exc()

    # Show raw broker positions for snapshot
    print(f"\n  RAW POSITIONS (open market snapshot):")
    snap_rows = []
    for p in broker_pos:
        qty = p.quantity
        mark = p.close_price if p.close_price is not None else "-"
        avg = p.average_open_price if p.average_open_price is not None else "-"
        exp = str(p.expiration) if p.expiration else "-"
        snap_rows.append([
            p.ticker,
            p.symbol or "-",
            p.option_type or "equity",
            f"{p.strike:.1f}" if p.strike else "-",
            exp,
            str(qty),
            f"{cur}{avg}" if isinstance(avg, (int, float)) else avg,
            f"{cur}{mark}" if isinstance(mark, (int, float)) else mark,
        ])
    print_table(
        "Broker Positions Snapshot",
        ["Ticker", "Symbol", "Type", "Strike", "Expiry", "Qty", "Avg Open", "Mark"],
        snap_rows,
    )


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

    # --build-snapshot: build snapshot, save, print summary, exit
    if args.build_snapshot:
        from income_desk.service.snapshot import SnapshotService

        registry = None
        try:
            from income_desk.registry import MarketRegistry
            registry = MarketRegistry()
        except Exception:
            pass

        snap_svc = SnapshotService(market_data=ma.market_data, registry=registry)
        print(f"\n  Building snapshot for {len(tickers)} tickers...")
        snapshot = snap_svc.build(tickers, market)
        path = snap_svc.save(snapshot)
        print(f"\n  Snapshot saved: {path}")
        print(f"  Instruments: {len(snapshot.instruments)}")
        for t, inst in snapshot.instruments.items():
            n_exp = len(inst.expiries)
            n_tradeable = sum(
                1 for e in inst.expiries for s in e.strikes if s.is_tradeable
            )
            print(f"    {t}: {n_exp} expiries, {n_tradeable} tradeable strikes")
        return

    # Try loading today's snapshot for faster chain fetching
    snapshot = None
    try:
        from income_desk.service.snapshot import SnapshotService
        snapshot = SnapshotService.load(market)
        if snapshot:
            print(f"  Loaded snapshot: {len(snapshot.instruments)} instruments, "
                  f"created {snapshot.created_at:%H:%M UTC}")
    except Exception:
        pass

    # Banner
    print_banner(meta)

    # Step 1: Market context
    safe = step_market_context(ma, meta, args.verbose)
    if not safe:
        return

    # Step 2: Scan
    scan_tickers = step_scan(ma, tickers, meta, args.verbose)

    # Step 3: Rank + full trade details
    step_rank_and_show(ma, scan_tickers, meta, args.verbose, snapshot=snapshot)

    # Step 4: Monitor open positions
    if meta.account_provider is not None:
        step_monitor_positions(ma, meta, args.verbose)

    print(f"\n  {'=' * 70}")
    print("  Done.")
    print(f"  {'=' * 70}\n")


if __name__ == "__main__":
    main()
