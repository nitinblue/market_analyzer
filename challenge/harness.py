#!/usr/bin/env python3
"""income_desk Workflow Harness -interactive debugging, onboarding, and stability checks.

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
# Session tracker -no module-level mutable state
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
    return "INR " if market == "India" else "$"


def _fetch_iv_rank_map(ma: Any, tickers: list[str]) -> dict[str, float]:
    """Fetch IV ranks from market_metrics if available."""
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
        print(f"    {num}. {name} -{desc}")
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
# Phase 1 -Pre-Market
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
        print(f"  Budget   : {resp.risk_budget_remaining:,.0f}")
        print(f"  Data trust: {resp.data_trust}")

        # Regime table
        if resp.regimes:
            rows = [
                [t, r.regime_id, r.regime_label, "Y" if r.tradeable else "N"]
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

        iv_map = _fetch_iv_rank_map(ma, tickers)
        req = DailyPlanRequest(
            tickers=tickers,
            capital=capital,
            market=meta.market,
            iv_rank_map=iv_map or None,
        )
        print_signature("generate_daily_plan", req, cli_command="analyzer-cli> plan")
        resp = generate_daily_plan(req, ma)

        print(f"  Sentinel : {resp.sentinel_signal}")
        print(f"  Safe?    : {resp.is_safe_to_trade}")
        print(f"  Tradeable: {', '.join(resp.tradeable_tickers)}")
        print(f"  Capital  : {cur}{resp.capital:,.0f}")
        print(f"  Risk dep : {resp.risk_deployed:.1f}%")
        print(f"  Budget   : {resp.risk_budget_remaining:,.0f}")
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
        cli_tickers = " ".join(tickers[:3]) + (" ..." if len(tickers) > 3 else "")
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
# Phase 2 -Scanning
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

        iv_map = _fetch_iv_rank_map(ma, tickers)
        req = RankRequest(
            tickers=tickers,
            capital=capital,
            market=meta.market,
            iv_rank_map=iv_map or None,
        )
        cli_tickers = " ".join(tickers[:3]) + (" ..." if len(tickers) > 3 else "")
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
# Phase 3 -Trade Entry
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
        wing = prop.get("wing_width") or 5.0
        lot_size = 25 if meta.market == "India" else 100
        risk_per_contract = wing * lot_size
        pop = prop.get("pop_pct") or 65.0
        mx_profit = prop.get("max_profit") or (prop.get("entry_credit", 1.0) * lot_size)
        mx_loss = prop.get("max_loss") or (risk_per_contract)

        req = SizeRequest(
            pop_pct=pop,
            max_profit=mx_profit,
            max_loss=mx_loss,
            capital=capital,
            risk_per_contract=risk_per_contract,
            regime_id=prop.get("regime_id", 1),
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

        # Build demo legs -put credit spread ~3% and ~7% OTM
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
# Phase 4 -Monitoring
# ---------------------------------------------------------------------------


def run_monitoring(
    ma: Any,
    tickers: list[str],
    meta: Any,
    session: HarnessSession,
    interactive: bool = True,
    verbose: bool = False,
) -> None:
    from challenge.harness_support import (
        build_demo_positions,
        print_error,
        print_signature,
        print_table,
        wait_for_input,
    )

    phase = "4-Monitoring"
    cur = _cur(meta.market)
    positions = build_demo_positions(meta.market)

    # --- 1. Monitor Positions ---
    try:
        from income_desk.workflow import monitor_positions
        from income_desk.workflow.monitor_positions import MonitorRequest

        req = MonitorRequest(positions=positions, market=meta.market)
        print_signature("monitor_positions", req, cli_command="analyzer-cli> monitor")
        resp = monitor_positions(req, ma)

        print(f"  Actions needed : {resp.actions_needed}")
        print(f"  Critical count : {resp.critical_count}")

        if resp.statuses:
            rows = [
                [
                    s.trade_id,
                    s.ticker,
                    s.action,
                    s.urgency,
                    f"{s.pnl_pct:.1%}" if s.pnl_pct is not None else "N/A",
                    _trunc(s.rationale, 40),
                ]
                for s in resp.statuses
            ]
            print_table(
                "Position Statuses",
                ["TradeID", "Ticker", "Action", "Urgency", "PnL%", "Rationale"],
                rows,
            )

        session.record(phase, "monitor_positions", "OK")
    except Exception as exc:
        print_error("monitor_positions", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "monitor_positions", f"FAIL: {exc}")

    action = wait_for_input(interactive)
    if action == "q":
        sys.exit(0)
    if action == "s":
        return

    # --- 2. Adjust Position ---
    try:
        from income_desk.workflow import adjust_position
        from income_desk.workflow.adjust_position import AdjustRequest

        pos = positions[0]
        req = AdjustRequest(
            trade_id=pos.trade_id,
            ticker=pos.ticker,
            structure_type=pos.structure_type,
            order_side=pos.order_side,
            entry_price=pos.entry_price,
            current_mid_price=pos.current_mid_price,
            contracts=pos.contracts,
            dte_remaining=pos.dte_remaining,
            regime_id=pos.regime_id,
            pnl_pct=(pos.entry_price - pos.current_mid_price) / pos.entry_price if pos.entry_price > 0 else 0,
        )
        print_signature("adjust_position", req, cli_command=f"analyzer-cli> adjust {pos.trade_id}")
        resp = adjust_position(req, ma)

        print(f"  Trade ID    : {resp.trade_id}")
        print(f"  Ticker      : {resp.ticker}")
        if resp.recommendation:
            print(f"  Action      : {resp.recommendation.action}")
            print(f"  Urgency     : {resp.recommendation.urgency}")
            print(f"  Rationale   : {_trunc(resp.recommendation.rationale, 60)}")

        if resp.alternatives:
            rows = [
                [a.action, a.urgency, _trunc(a.rationale, 50)]
                for a in resp.alternatives
            ]
            print_table("Alternatives", ["Action", "Urgency", "Rationale"], rows)

        session.record(phase, "adjust_position", "OK")
    except Exception as exc:
        print_error("adjust_position", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "adjust_position", f"FAIL: {exc}")

    action = wait_for_input(interactive)
    if action == "q":
        sys.exit(0)
    if action == "s":
        return

    # --- 3. Overnight Risk ---
    try:
        from income_desk.workflow import assess_overnight_risk
        from income_desk.workflow.overnight_risk import OvernightRiskRequest

        req = OvernightRiskRequest(positions=positions, market=meta.market)
        print_signature("assess_overnight_risk", req, cli_command="analyzer-cli> overnight")
        resp = assess_overnight_risk(req, ma)

        print(f"  High risk count       : {resp.high_risk_count}")
        print(f"  Close-before-close    : {resp.close_before_close_count}")

        if resp.entries:
            rows = [
                [
                    e.trade_id,
                    e.ticker,
                    e.risk_level,
                    e.action,
                    _trunc(e.rationale, 40),
                ]
                for e in resp.entries
            ]
            print_table(
                "Overnight Risk",
                ["TradeID", "Ticker", "Risk", "Action", "Rationale"],
                rows,
            )

        session.record(phase, "assess_overnight_risk", "OK")
    except Exception as exc:
        print_error("assess_overnight_risk", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "assess_overnight_risk", f"FAIL: {exc}")

    wait_for_input(interactive)


# ---------------------------------------------------------------------------
# Phase 5 -Portfolio Risk
# ---------------------------------------------------------------------------


def run_portfolio_risk(
    ma: Any,
    tickers: list[str],
    meta: Any,
    session: HarnessSession,
    interactive: bool = True,
    verbose: bool = False,
) -> None:
    from challenge.harness_support import (
        build_demo_positions,
        print_error,
        print_signature,
        print_table,
        wait_for_input,
    )

    phase = "5-PortfolioRisk"
    cur = _cur(meta.market)
    capital = meta.account_nlv or 50_000.0
    positions = build_demo_positions(meta.market)

    # --- 1. Aggregate Portfolio Greeks ---
    try:
        from income_desk.workflow import aggregate_portfolio_greeks
        from income_desk.workflow.portfolio_greeks import PortfolioGreeksRequest, PositionLeg

        legs = [
            PositionLeg(
                ticker=pos.ticker,
                option_type="put",
                strike=0,
                expiration="2026-04-17",
                contracts=pos.contracts,
                lot_size=pos.lot_size,
                action="short",
                delta=-0.15,
                gamma=0.02,
                theta=-0.05,
                vega=0.10,
                implied_volatility=0.20,
                market_value=pos.entry_price * pos.contracts * pos.lot_size,
            )
            for pos in positions
        ]

        req = PortfolioGreeksRequest(legs=legs, market=meta.market)
        print_signature("aggregate_portfolio_greeks", req, cli_command="analyzer-cli> greeks")
        resp = aggregate_portfolio_greeks(req, ma)

        print(f"  Portfolio Delta : {resp.portfolio_delta:+.2f}")
        print(f"  Portfolio Gamma : {resp.portfolio_gamma:+.4f}")
        print(f"  Portfolio Theta : {cur}{resp.portfolio_theta:+.2f}")
        print(f"  Portfolio Vega  : {resp.portfolio_vega:+.2f}")
        if resp.portfolio_market_value is not None:
            print(f"  Market Value    : {cur}{resp.portfolio_market_value:,.0f}")
        if resp.largest_delta_exposure:
            print(f"  Largest Delta   : {resp.largest_delta_exposure}")
        if resp.largest_vega_exposure:
            print(f"  Largest Vega    : {resp.largest_vega_exposure}")

        if resp.by_underlying:
            rows = [
                [
                    t,
                    u.position_count,
                    f"{u.net_delta:+.2f}",
                    f"{u.net_gamma:+.4f}",
                    f"{cur}{u.net_theta:+.2f}",
                    f"{u.net_vega:+.2f}",
                    f"{u.weighted_iv:.0%}" if u.weighted_iv else "N/A",
                ]
                for t, u in resp.by_underlying.items()
            ]
            print_table(
                "Greeks by Underlying",
                ["Ticker", "Legs", "Delta", "Gamma", "Theta", "Vega", "IV"],
                rows,
            )

        if resp.risk_warnings:
            for w in resp.risk_warnings:
                print(f"  ⚠ {w}")

        session.record(phase, "aggregate_portfolio_greeks", "OK")
    except Exception as exc:
        print_error("aggregate_portfolio_greeks", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "aggregate_portfolio_greeks", f"FAIL: {exc}")

    action = wait_for_input(interactive)
    if action == "q":
        sys.exit(0)
    if action == "s":
        return

    # --- 2. Stress Test Portfolio ---
    try:
        from income_desk.workflow import stress_test_portfolio
        from income_desk.workflow.stress_test import StressTestRequest

        req = StressTestRequest(
            positions=positions,
            capital=capital,
            market=meta.market,
        )
        print_signature("stress_test_portfolio", req, cli_command="analyzer-cli> stress")
        resp = stress_test_portfolio(req, ma)

        print(f"  Worst scenario  : {resp.worst_scenario}")
        print(f"  Worst PnL       : {cur}{resp.worst_scenario_pnl:,.0f} ({resp.worst_scenario_pnl_pct:.1%})")
        print(f"  Best scenario   : {resp.best_scenario}")
        print(f"  Risk score      : {resp.risk_score}")
        print(f"  Portfolio at risk: {cur}{resp.portfolio_at_risk:,.0f}")

        if resp.scenarios_breaching_limit:
            print(f"  Breaching limit : {', '.join(resp.scenarios_breaching_limit)}")

        if resp.scenario_results:
            rows = [
                [
                    s.scenario_name,
                    f"{cur}{s.portfolio_pnl:,.0f}",
                    f"{s.portfolio_pnl_pct:.1%}",
                    "YES" if s.breaches_limit else "no",
                ]
                for s in resp.scenario_results[:10]  # top 10
            ]
            print_table(
                "Scenario Results (top 10)",
                ["Scenario", "PnL", "PnL%", "Breach?"],
                rows,
            )

        if resp.most_vulnerable_positions:
            print(f"  Most vulnerable : {', '.join(str(v) for v in resp.most_vulnerable_positions[:5])}")

        session.record(phase, "stress_test_portfolio", "OK")
    except Exception as exc:
        print_error("stress_test_portfolio", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "stress_test_portfolio", f"FAIL: {exc}")

    wait_for_input(interactive)


# ---------------------------------------------------------------------------
# Phase 6 -Calendar
# ---------------------------------------------------------------------------


def run_calendar(
    ma: Any,
    meta: Any,
    session: HarnessSession,
    interactive: bool = True,
    verbose: bool = False,
) -> None:
    from challenge.harness_support import (
        build_demo_positions,
        print_error,
        print_signature,
        print_table,
        wait_for_input,
    )

    phase = "6-Calendar"
    positions = build_demo_positions(meta.market)

    # --- 1. Expiry Day Check ---
    try:
        from income_desk.workflow import check_expiry_day
        from income_desk.workflow.expiry_day import ExpiryDayRequest

        req = ExpiryDayRequest(positions=positions, market=meta.market)
        print_signature("check_expiry_day", req, cli_command="analyzer-cli> expiry")
        resp = check_expiry_day(req, ma)

        print(f"  Expiry index       : {resp.expiry_index or 'None'}")
        print(f"  Expiry positions   : {resp.expiry_positions_count}")
        print(f"  Critical count     : {resp.critical_count}")

        if resp.positions:
            rows = [
                [
                    p.trade_id,
                    p.ticker,
                    "YES" if p.is_expiry_today else "no",
                    p.urgency,
                    p.action,
                    p.deadline or "N/A",
                    _trunc(p.rationale, 35),
                ]
                for p in resp.positions
            ]
            print_table(
                "Expiry Positions",
                ["TradeID", "Ticker", "Expiry?", "Urgency", "Action", "Deadline", "Rationale"],
                rows,
            )

        session.record(phase, "check_expiry_day", "OK")
    except Exception as exc:
        print_error("check_expiry_day", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "check_expiry_day", f"FAIL: {exc}")

    wait_for_input(interactive)


# ---------------------------------------------------------------------------
# Phase 7 -Reporting
# ---------------------------------------------------------------------------


def run_reporting(
    ma: Any,
    meta: Any,
    session: HarnessSession,
    interactive: bool = True,
    verbose: bool = False,
) -> None:
    from challenge.harness_support import (
        print_error,
        print_signature,
        wait_for_input,
    )

    phase = "7-Reporting"
    cur = _cur(meta.market)
    capital = meta.account_nlv or 50_000.0

    # --- 1. Daily Report ---
    try:
        from income_desk.workflow import generate_daily_report
        from income_desk.workflow.daily_report import DailyReportRequest

        req = DailyReportRequest(
            trades_today=[],
            positions_open=3,
            capital=capital,
            market=meta.market,
        )
        print_signature("generate_daily_report", req, cli_command="analyzer-cli> report")
        resp = generate_daily_report(req, ma)

        print(f"  Date           : {resp.date}")
        print(f"  Trades opened  : {resp.trades_opened}")
        print(f"  Trades closed  : {resp.trades_closed}")
        print(f"  Trades adjusted: {resp.trades_adjusted}")
        print(f"  Realized PnL   : {cur}{resp.realized_pnl:,.2f}")
        print(f"  Win/Loss       : {resp.win_count}W / {resp.loss_count}L")
        if resp.win_rate is not None:
            print(f"  Win rate       : {resp.win_rate:.0%}")
        if resp.best_trade:
            print(f"  Best trade     : {_trunc(resp.best_trade, 50)}")
        if resp.worst_trade:
            print(f"  Worst trade    : {_trunc(resp.worst_trade, 50)}")
        if resp.risk_deployed_pct is not None:
            print(f"  Risk deployed  : {resp.risk_deployed_pct:.1f}%")
        print(f"  Positions open : {resp.positions_open}")
        if resp.summary:
            print(f"  Summary        : {_trunc(resp.summary, 70)}")

        session.record(phase, "generate_daily_report", "OK")
    except Exception as exc:
        print_error("generate_daily_report", exc)
        if verbose:
            traceback.print_exc()
        session.record(phase, "generate_daily_report", f"FAIL: {exc}")

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

    # Suppress noisy library warnings (FRED tracebacks, yfinance, etc.)
    # Use --verbose to see them
    import logging
    if not args.verbose:
        logging.getLogger("income_desk").setLevel(logging.ERROR)
        logging.getLogger("fredapi").setLevel(logging.ERROR)

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
        print(f"  PHASE {p}: {name.upper()} -{desc}")
        print(f"{'#' * 60}")

        if p == 1:
            run_premarket(ma, tickers, meta, session, interactive, args.verbose)
        elif p == 2:
            proposals = run_scanning(ma, tickers, meta, session, interactive, args.verbose)
        elif p == 3:
            run_entry(ma, tickers, proposals, meta, session, interactive, args.verbose)
        elif p == 4:
            run_monitoring(ma, tickers, meta, session, interactive, args.verbose)
        elif p == 5:
            run_portfolio_risk(ma, tickers, meta, session, interactive, args.verbose)
        elif p == 6:
            run_calendar(ma, meta, session, interactive, args.verbose)
        elif p == 7:
            run_reporting(ma, meta, session, interactive, args.verbose)

    # Summary -always print for non-interactive / run-all; for interactive only if multiple phases
    if not interactive or len(phases) > 1:
        session.print_summary()

    print("\n  Harness complete.\n")


if __name__ == "__main__":
    main()
