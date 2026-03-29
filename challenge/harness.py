#!/usr/bin/env python3
"""income_desk Workflow Harness — interactive debugging, onboarding, and stability checks.

Exercises all 15 workflow APIs against live broker or simulated data.
Shows API signatures, inputs, and tabular results for every workflow.

Usage:
    python -m challenge.harness                        # Interactive
    python -m challenge.harness --all --market=US      # Non-interactive
    python -m challenge.harness --phase=2 --market=India
"""
from __future__ import annotations

import sys
import traceback
from typing import Any


# ---------------------------------------------------------------------------
# Phase catalogue
# ---------------------------------------------------------------------------

PHASES = {
    1: ("Pre-Market", "health check, daily plan, market snapshot"),
    2: ("Scanning", "scan universe, rank opportunities"),
    3: ("Trade Entry", "validate, size, price"),
    4: ("Monitoring", "monitor positions, adjust, overnight risk"),
    5: ("Portfolio Risk", "Greeks aggregation, stress test"),
    6: ("Calendar", "expiry day check"),
    7: ("Reporting", "daily report"),
}


# ---------------------------------------------------------------------------
# Session tracker — no module-level mutable state
# ---------------------------------------------------------------------------


class HarnessSession:
    """Accumulates per-workflow results for the final summary table."""

    def __init__(self) -> None:
        self.results: list[tuple[str, str, str]] = []

    def record(self, phase: str, workflow: str, status: str) -> None:
        self.results.append((phase, workflow, status))

    def print_summary(self) -> None:
        from challenge.harness_support import print_table

        if not self.results:
            print("\n  No workflows were executed.")
            return

        rows = [[p, w, s] for p, w, s in self.results]
        print_table(
            "HARNESS SUMMARY",
            ["Phase", "Workflow", "Status"],
            rows,
        )

        total = len(self.results)
        passed = sum(1 for _, _, s in self.results if s == "OK")
        failed = total - passed
        print(f"  Total: {total}  |  Passed: {passed}  |  Failed: {failed}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trunc(text: Any, width: int = 50) -> str:
    """Truncate a string to *width* characters, adding ellipsis if needed."""
    s = str(text) if text is not None else ""
    return s if len(s) <= width else s[: width - 3] + "..."


def _cur(market: str) -> str:
    """Return currency symbol for the market."""
    return "\u20b9" if market == "India" else "$"


# ---------------------------------------------------------------------------
# Phase menu
# ---------------------------------------------------------------------------


def phase_menu(interactive: bool, preset_phase: int | None = None) -> list[int]:
    """Let the user pick which phase(s) to run.

    Returns a sorted list of phase numbers.
    """
    if preset_phase is not None:
        return [preset_phase]

    if not interactive:
        return sorted(PHASES.keys())

    print("\n  Phases:")
    for num, (name, desc) in PHASES.items():
        print(f"    {num}. {name} — {desc}")
    print("    A. Run all")

    try:
        choice = input("\n  Select phase(s) [comma-separated or A]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return []

    if choice.upper() == "A":
        return sorted(PHASES.keys())

    selected: list[int] = []
    for tok in choice.split(","):
        tok = tok.strip()
        if tok.isdigit() and int(tok) in PHASES:
            selected.append(int(tok))
    return sorted(set(selected)) if selected else [1]


# ---------------------------------------------------------------------------
# Phase 1 — Pre-Market
# ---------------------------------------------------------------------------


def run_premarket(
    ma: Any,
    tickers: list[str],
    meta: Any,
    session: HarnessSession,
    interactive: bool = True,
    verbose: bool = False,
) -> None:
    from challenge.harness_support import (
        print_error,
        print_signature,
        print_table,
        wait_for_input,
    )

    phase = "1-PreMarket"
    cur = _cur(meta.market)
    capital = meta.account_nlv or 50_000.0

    # --- 1. Portfolio Health ---
    try:
        from income_desk.workflow import check_portfolio_health
        from income_desk.workflow.portfolio_health import HealthRequest

        req = HealthRequest(
            tickers=tickers,
            capital=capital,
            market=meta.market,
        )
        print_signature("check_portfolio_health", req, cli_command="analyzer-cli> health")
        resp = check_portfolio_health(req, ma)

        print(f"  Sentinel : {resp.sentinel_signal}")
        print(f"  Safe?    : {resp.is_safe_to_trade}")
        print(f"  Risk %   : {resp.risk_pct:.1f}%")
        print(f"  Budget   : {resp.risk_budget_remaining:.1f}%")
        print(f"  Data trust: {resp.data_trust}")

        # Regime table
        if resp.regimes:
            rows = [
                [t, r.regime_id, r.label, "Y" if r.tradeable else "N"]
                for t, r in resp.regimes.items()
            ]
            print_table("Regime Map", ["Ticker", "ID", "Label", "Tradeable"], rows)

        session.record(phase, "check_portfolio_health", "OK")
    except Exception as exc:
        print_error("check_portfolio_health", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "check_portfolio_health", f"FAIL: {exc}")

    action = wait_for_input(interactive)
    if action == "q":
        sys.exit(0)
    if action == "s":
        return

    # --- 2. Daily Plan ---
    try:
        from income_desk.workflow import generate_daily_plan
        from income_desk.workflow.daily_plan import DailyPlanRequest

        req = DailyPlanRequest(
            tickers=tickers,
            capital=capital,
            market=meta.market,
        )
        print_signature("generate_daily_plan", req, cli_command="analyzer-cli> plan")
        resp = generate_daily_plan(req, ma)

        print(f"  Sentinel : {resp.sentinel_signal}")
        print(f"  Safe?    : {resp.is_safe_to_trade}")
        print(f"  Tradeable: {', '.join(resp.tradeable_tickers)}")
        print(f"  Capital  : {cur}{resp.capital:,.0f}")
        print(f"  Risk dep : {resp.risk_deployed:.1f}%")
        print(f"  Budget   : {resp.risk_budget_remaining:.1f}%")
        if resp.summary:
            print(f"  Summary  : {_trunc(resp.summary, 80)}")

        # Proposed trades table
        if resp.proposed_trades:
            rows = [
                [
                    t.rank,
                    t.ticker,
                    t.structure,
                    f"{t.composite_score:.2f}",
                    f"{t.pop_pct:.0f}%",
                    f"{cur}{t.entry_credit:.2f}",
                    f"{cur}{t.max_risk:,.0f}",
                    t.contracts,
                    _trunc(t.verdict, 30),
                ]
                for t in resp.proposed_trades
            ]
            print_table(
                "Proposed Trades",
                ["#", "Ticker", "Structure", "Score", "POP", "Credit", "MaxRisk", "Cts", "Verdict"],
                rows,
            )

        # Blocked trades
        if resp.blocked_trades:
            rows = [
                [b.ticker, b.structure, f"{b.score:.2f}" if b.score else "N/A", _trunc(b.reason, 50)]
                for b in resp.blocked_trades
            ]
            print_table("Blocked Trades", ["Ticker", "Structure", "Score", "Reason"], rows)

        session.record(phase, "generate_daily_plan", "OK")
    except Exception as exc:
        print_error("generate_daily_plan", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "generate_daily_plan", f"FAIL: {exc}")

    action = wait_for_input(interactive)
    if action == "q":
        sys.exit(0)
    if action == "s":
        return

    # --- 3. Market Snapshot ---
    try:
        from income_desk.workflow import snapshot_market
        from income_desk.workflow.market_snapshot import SnapshotRequest

        req = SnapshotRequest(
            tickers=tickers,
            market=meta.market,
        )
        cli_tickers = " ".join(tickers[:4])
        print_signature("snapshot_market", req, cli_command=f"analyzer-cli> snapshot {cli_tickers}")
        resp = snapshot_market(req, ma)

        if resp.tickers:
            rows = [
                [
                    t,
                    f"{cur}{snap.price:,.2f}" if snap.price else "N/A",
                    snap.regime_label or "?",
                    f"{snap.iv_rank:.0f}" if snap.iv_rank is not None else "N/A",
                    f"{snap.atr_pct:.2f}%" if snap.atr_pct is not None else "N/A",
                    f"{snap.rsi:.1f}" if snap.rsi is not None else "N/A",
                ]
                for t, snap in resp.tickers.items()
            ]
            print_table(
                "Market Snapshot",
                ["Ticker", "Price", "Regime", "IVR", "ATR%", "RSI"],
                rows,
            )

        session.record(phase, "snapshot_market", "OK")
    except Exception as exc:
        print_error("snapshot_market", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "snapshot_market", f"FAIL: {exc}")

    wait_for_input(interactive)


# ---------------------------------------------------------------------------
# Phase 2 — Scanning
# ---------------------------------------------------------------------------


def run_scanning(
    ma: Any,
    tickers: list[str],
    meta: Any,
    session: HarnessSession,
    interactive: bool = True,
    verbose: bool = False,
) -> list[Any] | None:
    from challenge.harness_support import (
        print_error,
        print_signature,
        print_table,
        wait_for_input,
    )

    phase = "2-Scanning"
    cur = _cur(meta.market)
    capital = meta.account_nlv or 50_000.0
    proposals: list[Any] | None = None

    # --- 1. Scan Universe ---
    try:
        from income_desk.workflow import scan_universe
        from income_desk.workflow.scan_universe import ScanRequest

        req = ScanRequest(tickers=tickers, market=meta.market)
        print_signature("scan_universe", req, cli_command="analyzer-cli> scan")
        resp = scan_universe(req, ma)

        print(f"  Scanned: {resp.total_scanned}  |  Passed: {resp.total_passed}")

        if resp.candidates:
            rows = [
                [
                    c.ticker,
                    f"{c.score:.2f}",
                    c.regime_label or "?",
                    _trunc(c.rationale, 50),
                ]
                for c in resp.candidates
            ]
            print_table("Scan Candidates", ["Ticker", "Score", "Regime", "Rationale"], rows)

        session.record(phase, "scan_universe", "OK")
    except Exception as exc:
        print_error("scan_universe", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "scan_universe", f"FAIL: {exc}")

    action = wait_for_input(interactive)
    if action == "q":
        sys.exit(0)
    if action == "s":
        return None

    # --- 2. Rank Opportunities ---
    try:
        from income_desk.workflow import rank_opportunities
        from income_desk.workflow.rank_opportunities import RankRequest

        req = RankRequest(
            tickers=tickers,
            capital=capital,
            market=meta.market,
        )
        cli_tickers = " ".join(tickers[:4])
        print_signature("rank_opportunities", req, cli_command=f"analyzer-cli> rank {cli_tickers}")
        resp = rank_opportunities(req, ma)

        print(f"  Tradeable: {resp.tradeable_count}  |  Total assessed: {resp.total_assessed}")

        if resp.trades:
            rows = [
                [
                    t.rank,
                    t.ticker,
                    t.structure,
                    f"{t.composite_score:.2f}",
                    _trunc(t.verdict, 20),
                    f"{t.pop_pct:.0f}%",
                    f"{cur}{t.entry_credit:.2f}",
                    f"{cur}{t.max_risk:,.0f}",
                    t.contracts,
                ]
                for t in resp.trades
            ]
            print_table(
                "Ranked Trades",
                ["#", "Ticker", "Structure", "Score", "Verdict", "POP", "Credit", "MaxRisk", "Cts"],
                rows,
            )
            proposals = resp.trades

        if resp.blocked:
            rows = [
                [b.ticker, b.structure, f"{b.score:.2f}" if b.score else "N/A", _trunc(b.reason, 50)]
                for b in resp.blocked
            ]
            print_table("Blocked", ["Ticker", "Structure", "Score", "Reason"], rows)

        session.record(phase, "rank_opportunities", "OK")
    except Exception as exc:
        print_error("rank_opportunities", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "rank_opportunities", f"FAIL: {exc}")

    wait_for_input(interactive)
    return proposals


# ---------------------------------------------------------------------------
# Phase 3 — Trade Entry
# ---------------------------------------------------------------------------


def run_entry(
    ma: Any,
    tickers: list[str],
    proposals: list[Any] | None,
    meta: Any,
    session: HarnessSession,
    interactive: bool = True,
    verbose: bool = False,
) -> None:
    from challenge.harness_support import (
        build_demo_proposal,
        print_error,
        print_signature,
        print_table,
        wait_for_input,
    )

    phase = "3-Entry"
    cur = _cur(meta.market)

    # Resolve a single proposal to drive validate/size/price
    if proposals and len(proposals) > 0:
        top = proposals[0]
        prop = {
            "ticker": top.ticker,
            "structure": top.structure,
            "regime_id": getattr(top, "regime_id", 1),
            "entry_credit": top.entry_credit,
            "atr_pct": getattr(top, "atr_pct", 1.0),
            "current_price": getattr(top, "current_price", 0.0),
            "pop_pct": top.pop_pct,
            "max_profit": top.max_profit,
            "max_loss": top.max_risk,
            "capital": top.max_risk,
            "wing_width": getattr(top, "wing_width", 5.0),
            "dte": getattr(top, "target_dte", 30),
        }
    else:
        prop = build_demo_proposal(meta.market)
        print(f"\n  (Using demo proposal for {prop['ticker']})")

    ticker = prop["ticker"]

    # --- 1. Validate Trade ---
    try:
        from income_desk.workflow import validate_trade
        from income_desk.workflow.validate_trade import ValidateRequest

        req = ValidateRequest(
            ticker=ticker,
            entry_credit=prop["entry_credit"],
            regime_id=prop["regime_id"],
            atr_pct=prop["atr_pct"],
            current_price=prop["current_price"],
            dte=prop.get("dte", 30),
        )
        print_signature("validate_trade", req, cli_command=f"analyzer-cli> validate {ticker}")
        resp = validate_trade(req, ma)

        print(f"  Ready?       : {resp.is_ready}")
        print(f"  Failed gates : {resp.failed_gates}")
        if resp.warnings:
            print(f"  Warnings     : {', '.join(str(w) for w in resp.warnings)}")

        if resp.gates:
            rows = [
                [
                    g.name,
                    "PASS" if g.passed else "FAIL",
                    g.severity,
                    _trunc(g.detail, 50),
                ]
                for g in resp.gates
            ]
            print_table("Gate Scorecard", ["Gate", "Status", "Severity", "Detail"], rows)

        session.record(phase, "validate_trade", "OK")
    except Exception as exc:
        print_error("validate_trade", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "validate_trade", f"FAIL: {exc}")

    action = wait_for_input(interactive)
    if action == "q":
        sys.exit(0)
    if action == "s":
        return

    # --- 2. Size Position ---
    try:
        from income_desk.workflow import size_position
        from income_desk.workflow.size_position import SizeRequest

        capital = meta.account_nlv or 50_000.0
        wing = prop.get("wing_width", 5.0)
        lot_size = 25 if meta.market == "India" else 100
        risk_per_contract = wing * lot_size

        req = SizeRequest(
            pop_pct=prop["pop_pct"],
            max_profit=prop["max_profit"],
            max_loss=prop["max_loss"],
            capital=capital,
            risk_per_contract=risk_per_contract,
            regime_id=prop["regime_id"],
            wing_width=wing,
        )
        print_signature("size_position", req, cli_command="analyzer-cli> size")
        resp = size_position(req, ma)

        print(f"  Contracts    : {resp.recommended_contracts}")
        print(f"  Kelly frac   : {resp.kelly_fraction:.3f}")
        print(f"  Risk/contract: {cur}{resp.risk_per_contract:,.0f}")
        print(f"  Total risk   : {cur}{resp.total_risk:,.0f}")
        print(f"  Risk % cap   : {resp.risk_pct_of_capital:.1f}%")

        session.record(phase, "size_position", "OK")
    except Exception as exc:
        print_error("size_position", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "size_position", f"FAIL: {exc}")

    action = wait_for_input(interactive)
    if action == "q":
        sys.exit(0)
    if action == "s":
        return

    # --- 3. Price Trade ---
    try:
        from income_desk.workflow import price_trade
        from income_desk.workflow.price_trade import PriceRequest

        # Build demo legs — put credit spread ~3% and ~7% OTM
        price = prop["current_price"]
        if price > 0:
            short_strike = round(price * 0.97, 0)
            long_strike = round(price * 0.93, 0)
        else:
            short_strike = 550.0
            long_strike = 545.0

        legs = [
            {"strike": short_strike, "option_type": "put", "action": "sell"},
            {"strike": long_strike, "option_type": "put", "action": "buy"},
        ]

        req = PriceRequest(
            ticker=ticker,
            legs=legs,
            market=meta.market,
        )
        print_signature("price_trade", req, cli_command=f"analyzer-cli> price {ticker}")
        resp = price_trade(req, ma)

        print(f"  Underlying   : {cur}{resp.underlying_price:,.2f}")
        if resp.net_credit is not None:
            print(f"  Net credit   : {cur}{resp.net_credit:.2f}")
        if resp.net_debit is not None:
            print(f"  Net debit    : {cur}{resp.net_debit:.2f}")
        if resp.avg_spread_pct is not None:
            print(f"  Avg spread % : {resp.avg_spread_pct:.2f}%")
        if resp.fill_quality is not None:
            print(f"  Fill quality : {resp.fill_quality}")

        if resp.leg_quotes:
            rows = [
                [
                    f"{lq.strike:.0f}",
                    lq.option_type,
                    lq.action,
                    f"{cur}{lq.bid:.2f}" if lq.bid is not None else "N/A",
                    f"{cur}{lq.ask:.2f}" if lq.ask is not None else "N/A",
                    f"{cur}{lq.mid:.2f}" if lq.mid is not None else "N/A",
                    f"{lq.iv:.1f}%" if lq.iv is not None else "N/A",
                    f"{lq.delta:.3f}" if lq.delta is not None else "N/A",
                ]
                for lq in resp.leg_quotes
            ]
            print_table(
                "Leg Quotes",
                ["Strike", "Type", "Action", "Bid", "Ask", "Mid", "IV", "Delta"],
                rows,
            )

        session.record(phase, "price_trade", "OK")
    except Exception as exc:
        print_error("price_trade", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "price_trade", f"FAIL: {exc}")

    wait_for_input(interactive)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    from challenge.harness_support import (
        parse_args,
        pick_market,
        pick_tickers,
        print_banner,
        setup,
    )

    args = parse_args()
    interactive = not args.run_all and args.phase is None

    # Market selection
    market = pick_market(preset=args.market)

    # Setup broker / simulated data
    print(f"\n  Connecting to {market} market...")
    ma, meta = setup(market)

    # Tickers
    tickers = pick_tickers(market, meta)

    # Banner
    print_banner(meta)

    # Phase selection
    phases = phase_menu(interactive, preset_phase=args.phase)
    if not phases:
        print("  No phases selected. Exiting.")
        return

    session = HarnessSession()
    proposals: list[Any] | None = None

    for p in phases:
        name, desc = PHASES.get(p, ("?", "?"))
        print(f"\n{'#' * 60}")
        print(f"  PHASE {p}: {name.upper()} — {desc}")
        print(f"{'#' * 60}")

        if p == 1:
            run_premarket(ma, tickers, meta, session, interactive, args.verbose)
        elif p == 2:
            proposals = run_scanning(ma, tickers, meta, session, interactive, args.verbose)
        elif p == 3:
            run_entry(ma, tickers, proposals, meta, session, interactive, args.verbose)
        elif p == 4:
            # Phase 4 — Monitoring (next task)
            print("  [Phase 4 not yet implemented]")
        elif p == 5:
            # Phase 5 — Portfolio Risk (next task)
            print("  [Phase 5 not yet implemented]")
        elif p == 6:
            # Phase 6 — Calendar (next task)
            print("  [Phase 6 not yet implemented]")
        elif p == 7:
            # Phase 7 — Reporting (next task)
            print("  [Phase 7 not yet implemented]")

    # Summary — always print for non-interactive / run-all; for interactive only if multiple phases
    if not interactive or len(phases) > 1:
        session.print_summary()

    print("\n  Harness complete.\n")


if __name__ == "__main__":
    main()
