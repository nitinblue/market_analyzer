# Workflow Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interactive harness that exercises all 15 income_desk workflow APIs, connecting to live brokers or falling back to simulated data seamlessly.

**Architecture:** Two files — `challenge/harness.py` (phase menu + workflow calls + tabular output) and `challenge/harness_support.py` (broker setup, data source detection, demo positions, formatting utilities). The harness is the primary tool for daily stability checks, go-live validation, and developer onboarding.

**Tech Stack:** Python 3.12, tabulate (already a dependency), income_desk workflow APIs, Pydantic models

**Spec:** `docs/superpowers/specs/2026-03-28-workflow-harness-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `challenge/harness.py` | Main script — CLI args, phase menu, 7 `run_*` functions that call workflows and print results |
| `challenge/harness_support.py` | Broker connection, market-open detection, simulated fallback, demo positions, `print_signature()`, `print_table()`, `BannerMeta`, universe loading |

---

### Task 1: harness_support.py — Data Source Setup & Formatting

**Files:**
- Create: `challenge/harness_support.py`

This is the foundation — everything else depends on it.

- [ ] **Step 1: Create BannerMeta dataclass and print_banner()**

```python
# challenge/harness_support.py
from __future__ import annotations
import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any

from tabulate import tabulate


@dataclass
class BannerMeta:
    market: str                          # "US" or "India"
    broker_name: str | None = None       # "tastytrade", "dhan", None
    data_source: str = "Simulated"       # "LIVE", "Snapshot (6h old)", "Simulated (ideal_income)"
    account_nlv: float | None = None
    account_bp: float | None = None
    ticker_count: int = 0
    currency: str = "USD"
    tickers: list[str] = field(default_factory=list)


def print_banner(meta: BannerMeta) -> None:
    """One-time startup display showing market, broker, data source, account."""
    curr = "$" if meta.currency == "USD" else "₹"
    acct = ""
    if meta.account_nlv is not None:
        acct = f"{curr}{meta.account_nlv:,.0f} NLV"
        if meta.account_bp is not None:
            acct += f" │ {curr}{meta.account_bp:,.0f} BP"
    else:
        acct = "simulated"

    tkr_display = ", ".join(meta.tickers[:6])
    if meta.ticker_count > 6:
        tkr_display += f" + {meta.ticker_count - 6} more"

    width = 56
    lines = [
        "income_desk Workflow Harness",
        f"Market: {meta.market} │ Broker: {meta.broker_name or 'not connected'}",
        f"Data: {meta.data_source}",
        f"Tickers: {tkr_display}",
        f"Account: {acct}",
    ]
    print("┌" + "─" * width + "┐")
    for line in lines:
        print(f"│  {line:<{width - 3}}│")
    print("└" + "─" * width + "┘")
    print()
```

- [ ] **Step 2: Create print_signature() — introspects Pydantic request + shows CLI command**

```python
def print_signature(workflow_name: str, request: Any, cli_command: str = "") -> None:
    """Print workflow function signature, all request field values, and CLI equivalent."""
    req_cls = type(request)
    resp_hint = workflow_name.replace("_", " ").title().replace(" ", "") + "Response"

    print(f"\n▸ Workflow: {workflow_name}")
    print(f"  Signature: {workflow_name}({req_cls.__name__}, MarketAnalyzer) -> {resp_hint}")
    print("  Inputs:")

    for field_name, field_info in req_cls.model_fields.items():
        val = getattr(request, field_name)
        # Truncate long lists
        if isinstance(val, list) and len(val) > 8:
            display = f"[{', '.join(repr(v) for v in val[:5])}, ... ({len(val)} total)]"
        else:
            display = repr(val)
        print(f"    {field_name:<25} = {display}")

    if cli_command:
        print(f"\n  CLI equivalent: {cli_command}")
    print()
```

- [ ] **Step 3: Create print_table() and print_error()**

```python
def print_table(title: str, headers: list[str], rows: list[list], tablefmt: str = "simple_grid") -> None:
    """Print a titled table using tabulate."""
    if not rows:
        print(f"  {title}: (empty — no results)")
        return
    print(f"  {title}:")
    print(tabulate(rows, headers=headers, tablefmt=tablefmt, numalign="right", stralign="left"))
    print()


def print_error(workflow_name: str, error: Exception) -> str:
    """Print workflow error inline. Returns error string for summary."""
    err_msg = f"{type(error).__name__}: {error}"
    print(f"  ✗ ERROR in {workflow_name}: {err_msg}")
    print("  (continuing to next workflow)\n")
    return err_msg
```

- [ ] **Step 4: Create wait_for_input()**

```python
def wait_for_input(interactive: bool = True) -> str:
    """Wait for user input. Returns 'n' (next), 's' (skip phase), 'q' (quit).
    In non-interactive mode, always returns 'n'."""
    if not interactive:
        return "n"
    try:
        choice = input("  [Enter] next ─ [s] skip phase ─ [q] quit: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "q"
    if choice == "q":
        print("\nExiting harness.")
        sys.exit(0)
    return choice
```

- [ ] **Step 5: Create is_market_open()**

```python
def is_market_open(market: str) -> bool:
    """Check if market is currently open based on simple time check."""
    now = datetime.now(timezone.utc)

    if market == "US":
        # US Eastern = UTC-4 (EDT) or UTC-5 (EST)
        # Approximate: use UTC-4 during DST months
        import zoneinfo
        try:
            eastern = zoneinfo.ZoneInfo("US/Eastern")
        except Exception:
            eastern = zoneinfo.ZoneInfo("America/New_York")
        local = now.astimezone(eastern)
        market_open = time(9, 30)
        market_close = time(16, 0)
    else:  # India
        import zoneinfo
        ist = zoneinfo.ZoneInfo("Asia/Kolkata")
        local = now.astimezone(ist)
        market_open = time(9, 15)
        market_close = time(15, 30)

    # Weekend check
    if local.weekday() >= 5:
        return False
    return market_open <= local.time() <= market_close
```

- [ ] **Step 6: Create setup() — broker connection + fallback chain**

```python
def setup(market: str) -> tuple:
    """Connect broker → detect market hours → fallback to simulated.
    Returns: (MarketAnalyzer, BannerMeta)
    """
    from income_desk import MarketAnalyzer, DataService

    data_service = DataService()
    md, mm, acct, wl = None, None, None, None
    broker_name = None
    data_source = "Simulated"
    account_nlv, account_bp = None, None
    currency = "USD" if market == "US" else "INR"

    # Step 1: Try broker connection
    try:
        if market == "US":
            from income_desk.broker.tastytrade import connect_tastytrade
            md, mm, acct, wl = connect_tastytrade(is_paper=False)
            broker_name = "tastytrade (LIVE)"
        else:
            from income_desk.broker.dhan import connect_dhan
            md, mm, acct, wl = connect_dhan()
            broker_name = "dhan"
    except Exception as e:
        print(f"  Broker connection failed: {e}")
        broker_name = None

    # Step 2: Check market hours — if closed, switch to simulated
    if broker_name and is_market_open(market):
        data_source = "LIVE quotes (market open)"
        if acct:
            try:
                bal = acct.get_balance()
                account_nlv = bal.net_liquidating_value
                account_bp = bal.buying_power
            except Exception:
                pass
    else:
        # Fallback chain: snapshot → preset
        from income_desk.adapters.simulated import (
            SimulatedMarketData, SimulatedMetrics, SimulatedAccount,
            create_from_snapshot, get_snapshot_info,
            create_ideal_income, create_india_trading,
        )

        snap_info = get_snapshot_info()
        sim = create_from_snapshot()

        if sim is not None and snap_info:
            age_h = snap_info.get("age_hours", 0)
            data_source = f"Simulated (snapshot {age_h:.0f}h old)"
            md = sim
        else:
            if market == "US":
                sim = create_ideal_income()
                data_source = "Simulated (ideal_income preset)"
            else:
                sim = create_india_trading()
                data_source = "Simulated (india_trading preset)"
            md = sim

        # Extract metrics and account from simulated
        if hasattr(sim, '_tickers'):
            mm = SimulatedMetrics(sim._tickers)
            acct_data = SimulatedAccount(sim._account_nlv, sim._account_cash, sim._account_bp)
            acct = acct_data
            account_nlv = sim._account_nlv
            account_bp = sim._account_bp

    ma = MarketAnalyzer(
        data_service=data_service,
        market=market if market == "India" else None,
        market_data=md,
        market_metrics=mm,
        account_provider=acct,
        watchlist_provider=wl,
    )

    meta = BannerMeta(
        market=market,
        broker_name=broker_name,
        data_source=data_source,
        account_nlv=account_nlv,
        account_bp=account_bp,
        currency=currency,
    )

    return ma, meta
```

- [ ] **Step 7: Create pick_market() and pick_tickers()**

```python
US_DEFAULTS = ["SPY", "QQQ", "IWM", "GLD", "TLT", "AAPL", "MSFT", "NVDA"]
INDIA_DEFAULTS = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "SBIN"]


def pick_market(preset: str | None = None) -> str:
    """Prompt user for market selection or use preset."""
    if preset:
        return "India" if preset.lower().startswith("i") else "US"
    choice = input("Market: [U]S or [I]ndia? ").strip().lower()
    return "India" if choice.startswith("i") else "US"


def pick_tickers(market: str, meta: BannerMeta, preset: str | None = None) -> list[str]:
    """Show defaults, allow override, support universe loading."""
    defaults = INDIA_DEFAULTS if market == "India" else US_DEFAULTS

    if preset:
        # Non-interactive: use defaults
        meta.tickers = defaults
        meta.ticker_count = len(defaults)
        return defaults

    print(f"Default tickers: {', '.join(defaults)}")
    override = input("Tickers (comma-separated, or Enter for defaults): ").strip()

    if override:
        tickers = [t.strip().upper() for t in override.split(",") if t.strip()]
    else:
        tickers = defaults

    meta.tickers = tickers
    meta.ticker_count = len(tickers)
    return tickers


def load_universe(market: str, path: str | None = None) -> list[str]:
    """Load ticker universe from YAML/CSV or return full preset list."""
    if path:
        import pathlib
        p = pathlib.Path(path)
        if p.suffix in (".yaml", ".yml"):
            import yaml
            with open(p) as f:
                data = yaml.safe_load(f)
            return data.get("tickers", [])
        elif p.suffix == ".csv":
            with open(p) as f:
                return [line.strip() for line in f if line.strip()]

    # Return full preset ticker lists
    if market == "India":
        from income_desk.adapters.simulated import create_india_trading
        sim = create_india_trading()
        return sim.supported_tickers()
    else:
        from income_desk.adapters.simulated import create_ideal_income
        sim = create_ideal_income()
        return sim.supported_tickers()
```

- [ ] **Step 8: Create build_demo_positions()**

```python
def build_demo_positions(market: str) -> list:
    """Build realistic demo OpenPosition objects for monitoring/overnight/stress/expiry workflows."""
    from income_desk.workflow._types import OpenPosition

    if market == "India":
        return [
            OpenPosition(
                trade_id="DEMO-IND-1", ticker="NIFTY", structure_type="iron_condor",
                order_side="sell", entry_price=85.0, current_mid_price=60.0,
                contracts=1, dte_remaining=12, regime_id=1, lot_size=25,
                profit_target_pct=0.50, stop_loss_pct=2.0,
            ),
            OpenPosition(
                trade_id="DEMO-IND-2", ticker="BANKNIFTY", structure_type="put_credit_spread",
                order_side="sell", entry_price=120.0, current_mid_price=95.0,
                contracts=1, dte_remaining=5, regime_id=2, lot_size=15,
                profit_target_pct=0.50, stop_loss_pct=2.0,
            ),
            OpenPosition(
                trade_id="DEMO-IND-3", ticker="RELIANCE", structure_type="iron_condor",
                order_side="sell", entry_price=18.0, current_mid_price=22.0,
                contracts=2, dte_remaining=25, regime_id=1, lot_size=250,
                profit_target_pct=0.50, stop_loss_pct=2.0,
            ),
        ]
    else:
        return [
            OpenPosition(
                trade_id="DEMO-US-1", ticker="SPY", structure_type="iron_condor",
                order_side="sell", entry_price=1.45, current_mid_price=0.90,
                contracts=2, dte_remaining=18, regime_id=1, lot_size=100,
                profit_target_pct=0.50, stop_loss_pct=2.0,
            ),
            OpenPosition(
                trade_id="DEMO-US-2", ticker="QQQ", structure_type="put_credit_spread",
                order_side="sell", entry_price=1.10, current_mid_price=1.30,
                contracts=3, dte_remaining=8, regime_id=2, lot_size=100,
                profit_target_pct=0.50, stop_loss_pct=2.0,
            ),
            OpenPosition(
                trade_id="DEMO-US-3", ticker="IWM", structure_type="iron_condor",
                order_side="sell", entry_price=0.85, current_mid_price=0.40,
                contracts=5, dte_remaining=30, regime_id=1, lot_size=100,
                profit_target_pct=0.50, stop_loss_pct=2.0,
            ),
        ]


def build_demo_proposal(market: str) -> dict:
    """Fallback trade proposal when phase 2 wasn't run. Returns dict with fields needed for phase 3."""
    if market == "India":
        return {
            "ticker": "NIFTY",
            "structure": "iron_condor",
            "regime_id": 1,
            "entry_credit": 85.0,
            "atr_pct": 1.1,
            "current_price": 23500.0,
            "pop_pct": 0.68,
            "max_profit": 2125.0,   # 85 * 25
            "max_loss": 2375.0,
            "capital": 5_000_000,
            "wing_width": 200,
            "dte": 14,
        }
    else:
        return {
            "ticker": "SPY",
            "structure": "iron_condor",
            "regime_id": 1,
            "entry_credit": 1.45,
            "atr_pct": 1.1,
            "current_price": 580.0,
            "pop_pct": 0.70,
            "max_profit": 145.0,
            "max_loss": 355.0,
            "capital": 50_000,
            "wing_width": 5,
            "dte": 21,
        }
```

- [ ] **Step 9: Create parse_args()**

```python
def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for non-interactive mode."""
    parser = argparse.ArgumentParser(description="income_desk Workflow Harness")
    parser.add_argument("--market", choices=["US", "India"], help="Market to test")
    parser.add_argument("--all", action="store_true", help="Run all phases non-interactively")
    parser.add_argument("--phase", type=int, choices=range(1, 8), help="Run specific phase")
    parser.add_argument("--verbose", action="store_true", help="Include tracebacks on error")
    return parser.parse_args()
```

- [ ] **Step 10: Verify harness_support.py imports work**

Run: `.venv_312/Scripts/python -c "from challenge.harness_support import BannerMeta, setup, print_banner, print_signature, print_table"`

Expected: No import errors

- [ ] **Step 11: Commit**

```bash
git add challenge/harness_support.py
git commit -m "feat: harness_support — broker setup, formatting, demo data for workflow harness"
```

---

### Task 2: harness.py — Phase Menu & Phase 1 (Pre-Market)

**Files:**
- Create: `challenge/harness.py`

- [ ] **Step 1: Create main() with CLI args, setup, banner, and phase menu**

```python
#!/usr/bin/env python3
"""income_desk Workflow Harness

Interactive debugging, onboarding, and stability-check tool.
Exercises all 15 workflow APIs against live broker or simulated data.

Usage:
    python -m challenge.harness                        # Interactive
    python -m challenge.harness --all --market=US      # Non-interactive, all phases
    python -m challenge.harness --phase=2 --market=India
"""
from __future__ import annotations

import sys
import traceback
from typing import Any

from challenge.harness_support import (
    BannerMeta,
    build_demo_positions,
    build_demo_proposal,
    parse_args,
    pick_market,
    pick_tickers,
    print_banner,
    print_error,
    print_signature,
    print_table,
    setup,
    wait_for_input,
)

# ── Summary tracking ─────────────────────────────────────────────

_results: list[tuple[str, str, str]] = []  # (workflow_name, status, note)


def _record(name: str, status: str, note: str = "") -> None:
    _results.append((name, status, note))


def _print_summary() -> None:
    """Print pass/fail summary table at the end of Run All."""
    if not _results:
        return
    print("\n── Summary " + "─" * 46)
    headers = ["Workflow", "Status", "Note"]
    rows = [[n, s, nt] for n, s, nt in _results]
    passed = sum(1 for _, s, _ in _results if s == "PASS")
    total = len(_results)
    print_table("", headers, rows)
    status = "ALL PASS" if passed == total else f"{passed}/{total} PASS │ {total - passed} FAIL"
    print(f"  Result: {status}\n")


# ── Phase headers ────────────────────────────────────────────────

PHASES = {
    1: ("Pre-Market", "health check, daily plan, market snapshot"),
    2: ("Scanning", "scan universe, rank opportunities"),
    3: ("Trade Entry", "validate, size, price"),
    4: ("Monitoring", "monitor positions, adjust, overnight risk"),
    5: ("Portfolio Risk", "Greeks aggregation, stress test"),
    6: ("Calendar", "expiry day check"),
    7: ("Reporting", "daily report"),
}


def phase_menu(preset_phase: int | None = None) -> int:
    """Show phase menu and get selection. Returns 0 for all."""
    if preset_phase is not None:
        return preset_phase

    print("PHASES:")
    for num, (name, desc) in PHASES.items():
        print(f"  {num}. {name:<16} ({desc})")
    print(f"  0. Run All (step-by-step)")
    print()

    try:
        choice = input("Pick phase [0-7]: ").strip()
        return int(choice) if choice.isdigit() and 0 <= int(choice) <= 7 else 0
    except (ValueError, EOFError, KeyboardInterrupt):
        return 0
```

- [ ] **Step 2: Implement run_premarket() — Phase 1**

Phase 1 calls: `check_portfolio_health` → `generate_daily_plan` → `snapshot_market`

```python
def run_premarket(ma: Any, tickers: list[str], meta: BannerMeta, interactive: bool = True, verbose: bool = False) -> None:
    """Phase 1: Pre-Market — health check, daily plan, market snapshot."""
    print("\n── Phase 1: Pre-Market " + "─" * 35)
    capital = meta.account_nlv or (5_000_000 if meta.market == "India" else 50_000)
    market = meta.market

    # 1a. Portfolio Health
    try:
        from income_desk.workflow import check_portfolio_health
        from income_desk.workflow.portfolio_health import HealthRequest

        req = HealthRequest(tickers=tickers, capital=capital, total_risk_deployed=0, market=market)
        print_signature("check_portfolio_health", req,
                        cli_command="analyzer-cli> health SPY QQQ ...")
        resp = check_portfolio_health(req, ma)

        headers = ["Signal", "Safe to Trade", "Risk %", "Budget Remaining", "Data Trust"]
        rows = [[resp.sentinel_signal, resp.is_safe_to_trade, f"{resp.risk_pct:.1f}%",
                 f"{resp.risk_budget_remaining:,.0f}", resp.data_trust]]
        print_table("Health Check", headers, rows)

        # Regime distribution
        if resp.regimes:
            r_headers = ["Ticker", "Regime", "Label", "Tradeable"]
            r_rows = [[t, r.regime_id, r.label, r.tradeable] for t, r in resp.regimes.items()]
            print_table("Regime Distribution", r_headers, r_rows)

        _record("check_portfolio_health", "PASS", resp.sentinel_signal)
    except Exception as e:
        msg = print_error("check_portfolio_health", e)
        if verbose: traceback.print_exc()
        _record("check_portfolio_health", "FAIL", msg)

    if wait_for_input(interactive) == "s":
        return

    # 1b. Daily Plan
    try:
        from income_desk.workflow import generate_daily_plan
        from income_desk.workflow.daily_plan import DailyPlanRequest

        req = DailyPlanRequest(
            tickers=tickers, capital=capital, market=market,
            risk_tolerance="moderate", total_risk_deployed=0, max_new_trades=5,
        )
        print_signature("generate_daily_plan", req,
                        cli_command="analyzer-cli> plan")
        resp = generate_daily_plan(req, ma)

        headers = ["Signal", "Safe", "Tradeable", "Proposed", "Blocked"]
        rows = [[resp.sentinel_signal, resp.is_safe_to_trade,
                 len(resp.tradeable_tickers), len(resp.proposed_trades), len(resp.blocked_trades)]]
        print_table("Daily Plan", headers, rows)

        if resp.proposed_trades:
            t_headers = ["#", "Ticker", "Structure", "Score", "POP", "Credit", "Contracts"]
            t_rows = [[t.rank, t.ticker, t.structure, f"{t.composite_score:.1f}",
                        f"{t.pop_pct:.0%}" if t.pop_pct else "—",
                        t.entry_credit or "—", t.contracts or "—"]
                       for t in resp.proposed_trades[:10]]
            print_table("Proposed Trades", t_headers, t_rows)

        if resp.blocked_trades:
            b_headers = ["Ticker", "Reason"]
            b_rows = [[b.ticker, b.reason] for b in resp.blocked_trades[:10]]
            print_table("Blocked Trades", b_headers, b_rows)

        _record("generate_daily_plan", "PASS", f"{len(resp.proposed_trades)} trades proposed")
    except Exception as e:
        msg = print_error("generate_daily_plan", e)
        if verbose: traceback.print_exc()
        _record("generate_daily_plan", "FAIL", msg)

    if wait_for_input(interactive) == "s":
        return

    # 1c. Market Snapshot
    try:
        from income_desk.workflow import snapshot_market
        from income_desk.workflow.market_snapshot import SnapshotRequest

        req = SnapshotRequest(tickers=tickers[:6], include_chains=False, include_regime=True, market=market)
        print_signature("snapshot_market", req,
                        cli_command="analyzer-cli> snapshot SPY QQQ ...")
        resp = snapshot_market(req, ma)

        if resp.tickers:
            s_headers = ["Ticker", "Price", "Regime", "IV Rank", "ATR%", "RSI"]
            s_rows = []
            for t, snap in resp.tickers.items():
                s_rows.append([
                    t, f"{snap.price:,.2f}" if snap.price else "—",
                    snap.regime_label or "—",
                    f"{snap.iv_rank:.0f}" if snap.iv_rank is not None else "—",
                    f"{snap.atr_pct:.2f}" if snap.atr_pct is not None else "—",
                    f"{snap.rsi:.1f}" if snap.rsi is not None else "—",
                ])
            print_table("Market Snapshot", s_headers, s_rows)

        _record("snapshot_market", "PASS", f"{len(resp.tickers)} tickers")
    except Exception as e:
        msg = print_error("snapshot_market", e)
        if verbose: traceback.print_exc()
        _record("snapshot_market", "FAIL", msg)

    wait_for_input(interactive)
```

- [ ] **Step 3: Verify phase 1 runs**

Run: `.venv_312/Scripts/python -c "from challenge.harness import run_premarket; print('import ok')"`

Expected: `import ok`

- [ ] **Step 4: Commit**

```bash
git add challenge/harness.py
git commit -m "feat: harness.py — main(), phase menu, Phase 1 (pre-market)"
```

---

### Task 3: Phase 2 — Scanning

**Files:**
- Modify: `challenge/harness.py`

- [ ] **Step 1: Implement run_scanning()**

```python
def run_scanning(ma: Any, tickers: list[str], meta: BannerMeta, interactive: bool = True, verbose: bool = False) -> list | None:
    """Phase 2: Scanning — scan universe, rank opportunities. Returns proposals for phase 3."""
    print("\n── Phase 2: Scanning " + "─" * 37)
    capital = meta.account_nlv or (5_000_000 if meta.market == "India" else 50_000)
    market = meta.market
    proposals = None

    # 2a. Scan Universe
    try:
        from income_desk.workflow import scan_universe
        from income_desk.workflow.scan import ScanRequest

        req = ScanRequest(tickers=tickers, market=market, min_score=0.3, top_n=20)
        print_signature("scan_universe", req,
                        cli_command="analyzer-cli> scan")
        resp = scan_universe(req, ma)

        headers = ["Ticker", "Score", "Regime", "Rationale"]
        rows = [[c.ticker, f"{c.score:.2f}", c.regime_label or "—", c.rationale[:50]]
                for c in (resp.candidates or [])[:10]]
        print_table(f"Scan Results ({resp.total_passed}/{resp.total_scanned} passed)", headers, rows)

        _record("scan_universe", "PASS", f"{resp.total_passed} passed")
    except Exception as e:
        msg = print_error("scan_universe", e)
        if verbose: traceback.print_exc()
        _record("scan_universe", "FAIL", msg)

    if wait_for_input(interactive) == "s":
        return proposals

    # 2b. Rank Opportunities
    try:
        from income_desk.workflow import rank_opportunities
        from income_desk.workflow.rank import RankRequest

        req = RankRequest(
            tickers=tickers, capital=capital, market=market,
            risk_tolerance="moderate", skip_intraday=True, max_trades=10, min_pop=0.40,
        )
        print_signature("rank_opportunities", req,
                        cli_command="analyzer-cli> rank SPY QQQ ...")
        resp = rank_opportunities(req, ma)

        if resp.trades:
            curr = "₹" if market == "India" else "$"
            t_headers = ["#", "Ticker", "Structure", "Score", "Verdict", "POP", "Credit", "Risk", "Contracts"]
            t_rows = [[t.rank, t.ticker, t.structure, f"{t.composite_score:.1f}",
                        t.verdict,
                        f"{t.pop_pct:.0%}" if t.pop_pct else "—",
                        f"{curr}{t.entry_credit:,.2f}" if t.entry_credit else "—",
                        f"{curr}{t.max_risk:,.0f}" if t.max_risk else "—",
                        t.contracts or "—"]
                       for t in resp.trades[:10]]
            print_table(f"Ranked Trades ({len(resp.trades)} proposals, {len(resp.blocked)} blocked)",
                        t_headers, t_rows)

            # Store proposals for phase 3
            proposals = resp.trades

        if resp.blocked:
            b_headers = ["Ticker", "Structure", "Reason"]
            b_rows = [[b.ticker, b.structure, b.reason] for b in resp.blocked[:10]]
            print_table("Blocked", b_headers, b_rows)

        _record("rank_opportunities", "PASS", f"{len(resp.trades)} proposals")
    except Exception as e:
        msg = print_error("rank_opportunities", e)
        if verbose: traceback.print_exc()
        _record("rank_opportunities", "FAIL", msg)

    wait_for_input(interactive)
    return proposals
```

- [ ] **Step 2: Commit**

```bash
git add challenge/harness.py
git commit -m "feat: harness Phase 2 — scan universe + rank opportunities"
```

---

### Task 4: Phase 3 — Trade Entry

**Files:**
- Modify: `challenge/harness.py`

- [ ] **Step 1: Implement run_entry()**

```python
def run_entry(ma: Any, tickers: list[str], proposals: list | None, meta: BannerMeta, interactive: bool = True, verbose: bool = False) -> None:
    """Phase 3: Trade Entry — validate, size, price using top proposal from phase 2."""
    print("\n── Phase 3: Trade Entry " + "─" * 34)
    market = meta.market
    capital = meta.account_nlv or (5_000_000 if meta.market == "India" else 50_000)

    # Get trade details from proposal or demo fallback
    if proposals and len(proposals) > 0:
        top = proposals[0]
        trade = {
            "ticker": top.ticker, "structure": top.structure, "regime_id": 1,
            "entry_credit": top.entry_credit or 1.0, "atr_pct": 1.1,
            "current_price": 0,  # will be filled
            "pop_pct": top.pop_pct or 0.65,
            "max_profit": top.max_profit or 100, "max_loss": top.max_risk or 400,
            "capital": capital, "wing_width": top.wing_width or 5, "dte": top.target_dte or 21,
        }
        print(f"  Using top proposal from Phase 2: {top.ticker} {top.structure}")
    else:
        trade = build_demo_proposal(market)
        print(f"  Using demo proposal: {trade['ticker']} {trade['structure']}")
    print()

    # 3a. Validate Trade
    try:
        from income_desk.workflow import validate_trade
        from income_desk.workflow.validate import ValidateRequest

        req = ValidateRequest(
            ticker=trade["ticker"], entry_credit=trade["entry_credit"],
            regime_id=trade.get("regime_id", 1), atr_pct=trade.get("atr_pct", 1.1),
            current_price=trade.get("current_price", 0), dte=trade.get("dte", 21),
        )
        print_signature("validate_trade", req,
                        cli_command=f"analyzer-cli> validate {trade['ticker']}")
        resp = validate_trade(req, ma)

        g_headers = ["Gate", "Passed", "Severity", "Detail"]
        g_rows = [[g.name, "✓" if g.passed else "✗", g.severity, g.detail[:50]]
                   for g in resp.gates]
        status = "READY" if resp.is_ready else f"BLOCKED ({len(resp.failed_gates)} gates failed)"
        print_table(f"Validation Gates — {status}", g_headers, g_rows)

        _record("validate_trade", "PASS", status)
    except Exception as e:
        msg = print_error("validate_trade", e)
        if verbose: traceback.print_exc()
        _record("validate_trade", "FAIL", msg)

    if wait_for_input(interactive) == "s":
        return

    # 3b. Size Position
    try:
        from income_desk.workflow import size_position
        from income_desk.workflow.size import SizeRequest

        req = SizeRequest(
            pop_pct=trade.get("pop_pct", 0.65),
            max_profit=trade.get("max_profit", 100),
            max_loss=trade.get("max_loss", 400),
            capital=capital,
            risk_per_contract=trade.get("max_loss", 400),
            regime_id=trade.get("regime_id", 1),
            wing_width=trade.get("wing_width", 5),
        )
        print_signature("size_position", req,
                        cli_command="analyzer-cli> size")
        resp = size_position(req, ma)

        curr = "₹" if market == "India" else "$"
        s_headers = ["Contracts", "Kelly %", "Risk/Contract", "Total Risk", "Risk % Capital"]
        s_rows = [[resp.recommended_contracts, f"{resp.kelly_fraction:.3f}",
                    f"{curr}{resp.risk_per_contract:,.0f}", f"{curr}{resp.total_risk:,.0f}",
                    f"{resp.risk_pct_of_capital:.2f}%"]]
        print_table("Position Sizing (Kelly)", s_headers, s_rows)

        _record("size_position", "PASS", f"{resp.recommended_contracts} contracts")
    except Exception as e:
        msg = print_error("size_position", e)
        if verbose: traceback.print_exc()
        _record("size_position", "FAIL", msg)

    if wait_for_input(interactive) == "s":
        return

    # 3c. Price Trade
    try:
        from income_desk.workflow import price_trade
        from income_desk.workflow.price import PriceRequest

        # Build simple legs for demo
        legs = [
            {"strike": trade.get("current_price", 580) * 0.97, "option_type": "put",
             "action": "sell", "expiration": "2026-04-17"},
            {"strike": trade.get("current_price", 580) * 0.93, "option_type": "put",
             "action": "buy", "expiration": "2026-04-17"},
        ]
        req = PriceRequest(ticker=trade["ticker"], legs=legs, market=market)
        print_signature("price_trade", req,
                        cli_command=f"analyzer-cli> price {trade['ticker']}")
        resp = price_trade(req, ma)

        if resp.leg_quotes:
            l_headers = ["Strike", "Type", "Action", "Bid", "Ask", "Mid", "IV", "Delta"]
            l_rows = [[f"{q.strike:.0f}", q.option_type, q.action,
                        f"{q.bid:.2f}" if q.bid else "—", f"{q.ask:.2f}" if q.ask else "—",
                        f"{q.mid:.2f}" if q.mid else "—",
                        f"{q.iv:.1%}" if q.iv else "—", f"{q.delta:.3f}" if q.delta else "—"]
                       for q in resp.leg_quotes]
            print_table(f"Leg Quotes (fill quality: {resp.fill_quality})", l_headers, l_rows)

            p_headers = ["Net Credit", "Net Debit", "Avg Spread %"]
            p_rows = [[f"{resp.net_credit:.2f}", f"{resp.net_debit:.2f}", f"{resp.avg_spread_pct:.2%}"]]
            print_table("Pricing", p_headers, p_rows)

        _record("price_trade", "PASS", resp.fill_quality or "ok")
    except Exception as e:
        msg = print_error("price_trade", e)
        if verbose: traceback.print_exc()
        _record("price_trade", "FAIL", msg)

    wait_for_input(interactive)
```

- [ ] **Step 2: Commit**

```bash
git add challenge/harness.py
git commit -m "feat: harness Phase 3 — validate, size, price trade"
```

---

### Task 5: Phase 4 — Monitoring

**Files:**
- Modify: `challenge/harness.py`

- [ ] **Step 1: Implement run_monitoring()**

```python
def run_monitoring(ma: Any, meta: BannerMeta, interactive: bool = True, verbose: bool = False) -> None:
    """Phase 4: Monitoring — monitor positions, adjust, overnight risk."""
    print("\n── Phase 4: Monitoring " + "─" * 35)
    market = meta.market
    positions = build_demo_positions(market)
    print(f"  Using {len(positions)} demo positions for monitoring\n")

    # 4a. Monitor Positions
    try:
        from income_desk.workflow import monitor_positions
        from income_desk.workflow.monitor import MonitorRequest

        req = MonitorRequest(positions=positions, market=market)
        print_signature("monitor_positions", req,
                        cli_command="analyzer-cli> monitor")
        resp = monitor_positions(req, ma)

        if resp.statuses:
            m_headers = ["Trade ID", "Ticker", "Action", "Urgency", "P&L %", "Rationale"]
            m_rows = [[s.trade_id, s.ticker, s.action, s.urgency,
                        f"{s.pnl_pct:.1%}" if s.pnl_pct is not None else "—",
                        (s.rationale or "")[:40]]
                       for s in resp.statuses]
            print_table(f"Position Monitor ({resp.actions_needed} actions, {resp.critical_count} critical)",
                        m_headers, m_rows)

        _record("monitor_positions", "PASS", f"{resp.actions_needed} actions needed")
    except Exception as e:
        msg = print_error("monitor_positions", e)
        if verbose: traceback.print_exc()
        _record("monitor_positions", "FAIL", msg)

    if wait_for_input(interactive) == "s":
        return

    # 4b. Adjust Position (use first demo position)
    try:
        from income_desk.workflow import adjust_position
        from income_desk.workflow.adjust import AdjustRequest

        pos = positions[0]
        req = AdjustRequest(
            trade_id=pos.trade_id, ticker=pos.ticker,
            structure_type=pos.structure_type, order_side=pos.order_side,
            entry_price=pos.entry_price, current_mid_price=pos.current_mid_price or pos.entry_price,
            contracts=pos.contracts, dte_remaining=pos.dte_remaining,
            regime_id=pos.regime_id, pnl_pct=0.0,
        )
        print_signature("adjust_position", req,
                        cli_command=f"analyzer-cli> adjust {pos.trade_id}")
        resp = adjust_position(req, ma)

        if resp.recommendation:
            a_headers = ["Action", "Urgency", "Rationale"]
            a_rows = [[resp.recommendation.action, resp.recommendation.urgency,
                        (resp.recommendation.rationale or "")[:60]]]
            print_table("Adjustment Recommendation", a_headers, a_rows)

            if resp.alternatives:
                alt_rows = [[a.action, a.urgency, (a.rationale or "")[:60]]
                            for a in resp.alternatives]
                print_table("Alternatives", a_headers, alt_rows)

        _record("adjust_position", "PASS", resp.recommendation.action if resp.recommendation else "none")
    except Exception as e:
        msg = print_error("adjust_position", e)
        if verbose: traceback.print_exc()
        _record("adjust_position", "FAIL", msg)

    if wait_for_input(interactive) == "s":
        return

    # 4c. Overnight Risk
    try:
        from income_desk.workflow import assess_overnight_risk
        from income_desk.workflow.overnight import OvernightRiskRequest

        req = OvernightRiskRequest(positions=positions, market=market)
        print_signature("assess_overnight_risk", req,
                        cli_command="analyzer-cli> overnight")
        resp = assess_overnight_risk(req, ma)

        if resp.entries:
            o_headers = ["Trade ID", "Ticker", "Risk Level", "Action", "Rationale"]
            o_rows = [[e.trade_id, e.ticker, e.risk_level, e.action, (e.rationale or "")[:40]]
                       for e in resp.entries]
            print_table(f"Overnight Risk ({resp.high_risk_count} high, {resp.close_before_close_count} close-before-close)",
                        o_headers, o_rows)

        _record("assess_overnight_risk", "PASS", f"{resp.high_risk_count} high risk")
    except Exception as e:
        msg = print_error("assess_overnight_risk", e)
        if verbose: traceback.print_exc()
        _record("assess_overnight_risk", "FAIL", msg)

    wait_for_input(interactive)
```

- [ ] **Step 2: Commit**

```bash
git add challenge/harness.py
git commit -m "feat: harness Phase 4 — monitor, adjust, overnight risk"
```

---

### Task 6: Phase 5 — Portfolio Risk

**Files:**
- Modify: `challenge/harness.py`

- [ ] **Step 1: Implement run_portfolio_risk()**

```python
def run_portfolio_risk(ma: Any, meta: BannerMeta, interactive: bool = True, verbose: bool = False) -> None:
    """Phase 5: Portfolio Risk — Greeks aggregation, stress test."""
    print("\n── Phase 5: Portfolio Risk " + "─" * 31)
    market = meta.market
    capital = meta.account_nlv or (5_000_000 if meta.market == "India" else 50_000)
    positions = build_demo_positions(market)

    # 5a. Portfolio Greeks
    try:
        from income_desk.workflow import aggregate_portfolio_greeks
        from income_desk.workflow.greeks import PortfolioGreeksRequest, PositionLeg

        # Build demo legs from positions
        legs = []
        for pos in positions:
            legs.append(PositionLeg(
                ticker=pos.ticker, option_type="put", strike=0,
                expiration="2026-04-17", contracts=pos.contracts,
                lot_size=pos.lot_size, action="sell",
                delta=-0.15, gamma=0.02, theta=-0.05, vega=0.10,
                implied_volatility=0.20, market_value=pos.entry_price * pos.contracts * pos.lot_size,
            ))

        req = PortfolioGreeksRequest(legs=legs, market=market)
        print_signature("aggregate_portfolio_greeks", req,
                        cli_command="analyzer-cli> greeks")
        resp = aggregate_portfolio_greeks(req, ma)

        g_headers = ["Metric", "Portfolio Total"]
        g_rows = [
            ["Net Delta", f"{resp.portfolio_delta:.2f}"],
            ["Net Gamma", f"{resp.portfolio_gamma:.4f}"],
            ["Net Theta", f"{resp.portfolio_theta:.2f}"],
            ["Net Vega", f"{resp.portfolio_vega:.2f}"],
            ["Market Value", f"{resp.portfolio_market_value:,.0f}"],
        ]
        print_table("Portfolio Greeks", g_headers, g_rows)

        if resp.by_underlying:
            u_headers = ["Underlying", "Delta", "Gamma", "Theta", "Vega", "Risk"]
            u_rows = [[t, f"{r.net_delta:.2f}", f"{r.net_gamma:.4f}",
                        f"{r.net_theta:.2f}", f"{r.net_vega:.2f}",
                        (r.risk_summary or "")[:30]]
                       for t, r in resp.by_underlying.items()]
            print_table("By Underlying", u_headers, u_rows)

        if resp.risk_warnings:
            print("  Risk Warnings:")
            for w in resp.risk_warnings:
                print(f"    ⚠ {w}")
            print()

        _record("aggregate_portfolio_greeks", "PASS", f"delta={resp.portfolio_delta:.2f}")
    except Exception as e:
        msg = print_error("aggregate_portfolio_greeks", e)
        if verbose: traceback.print_exc()
        _record("aggregate_portfolio_greeks", "FAIL", msg)

    if wait_for_input(interactive) == "s":
        return

    # 5b. Stress Test
    try:
        from income_desk.workflow import stress_test_portfolio
        from income_desk.workflow.stress import StressTestRequest

        req = StressTestRequest(
            positions=positions, capital=capital, market=market,
            risk_limit_pct=0.30,
        )
        print_signature("stress_test_portfolio", req,
                        cli_command="analyzer-cli> stress")
        resp = stress_test_portfolio(req, ma)

        curr = "₹" if market == "India" else "$"
        s_headers = ["Scenario", "P&L", "P&L %", "Breaches Limit"]
        s_rows = [[sr.scenario_name, f"{curr}{sr.portfolio_pnl:,.0f}",
                    f"{sr.portfolio_pnl_pct:.1%}", "⚠" if sr.breaches_limit else ""]
                   for sr in (resp.scenario_results or [])[:10]]
        print_table(f"Stress Test (risk score: {resp.risk_score})", s_headers, s_rows)

        st_headers = ["Metric", "Value"]
        st_rows = [
            ["Worst Scenario", resp.worst_scenario],
            ["Worst P&L", f"{curr}{resp.worst_scenario_pnl:,.0f}"],
            ["Scenarios Breaching Limit", len(resp.scenarios_breaching_limit)],
            ["Risk Score", resp.risk_score],
        ]
        print_table("Stress Summary", st_headers, st_rows)

        _record("stress_test_portfolio", "PASS", resp.risk_score)
    except Exception as e:
        msg = print_error("stress_test_portfolio", e)
        if verbose: traceback.print_exc()
        _record("stress_test_portfolio", "FAIL", msg)

    wait_for_input(interactive)
```

- [ ] **Step 2: Commit**

```bash
git add challenge/harness.py
git commit -m "feat: harness Phase 5 — portfolio Greeks + stress test"
```

---

### Task 7: Phase 6 & 7 — Calendar & Reporting

**Files:**
- Modify: `challenge/harness.py`

- [ ] **Step 1: Implement run_calendar()**

```python
def run_calendar(ma: Any, meta: BannerMeta, interactive: bool = True, verbose: bool = False) -> None:
    """Phase 6: Calendar — expiry day check."""
    print("\n── Phase 6: Calendar " + "─" * 37)
    market = meta.market
    positions = build_demo_positions(market)

    try:
        from income_desk.workflow import check_expiry_day
        from income_desk.workflow.expiry import ExpiryDayRequest

        req = ExpiryDayRequest(positions=positions, market=market)
        print_signature("check_expiry_day", req,
                        cli_command="analyzer-cli> expiry")
        resp = check_expiry_day(req, ma)

        e_headers = ["Metric", "Value"]
        e_rows = [
            ["Expiry Index", resp.expiry_index or "None today"],
            ["Expiry Positions", resp.expiry_positions_count],
            ["Critical", resp.critical_count],
        ]
        print_table("Expiry Day", e_headers, e_rows)

        if resp.positions:
            p_headers = ["Trade ID", "Ticker", "Expiry Today", "Urgency", "Action", "Deadline"]
            p_rows = [[p.trade_id, p.ticker, "YES" if p.is_expiry_today else "no",
                        p.urgency, p.action, p.deadline or "—"]
                       for p in resp.positions]
            print_table("Position Expiry Status", p_headers, p_rows)

        _record("check_expiry_day", "PASS", resp.expiry_index or "no expiry")
    except Exception as e:
        msg = print_error("check_expiry_day", e)
        if verbose: traceback.print_exc()
        _record("check_expiry_day", "FAIL", msg)

    wait_for_input(interactive)
```

- [ ] **Step 2: Implement run_reporting()**

```python
def run_reporting(ma: Any, meta: BannerMeta, interactive: bool = True, verbose: bool = False) -> None:
    """Phase 7: Reporting — daily report."""
    print("\n── Phase 7: Reporting " + "─" * 36)
    market = meta.market
    capital = meta.account_nlv or (5_000_000 if meta.market == "India" else 50_000)

    try:
        from income_desk.workflow import generate_daily_report
        from income_desk.workflow.report import DailyReportRequest

        # Empty trades_today for demo — no trades executed
        req = DailyReportRequest(
            trades_today=[], positions_open=3, capital=capital,
            total_risk_deployed=capital * 0.15,
            regime_summary={"R1": 3, "R2": 1}, market=market,
        )
        print_signature("generate_daily_report", req,
                        cli_command="analyzer-cli> report")
        resp = generate_daily_report(req, ma)

        curr = "₹" if market == "India" else "$"
        r_headers = ["Metric", "Value"]
        r_rows = [
            ["Date", resp.date],
            ["Trades Opened", resp.trades_opened],
            ["Trades Closed", resp.trades_closed],
            ["Realized P&L", f"{curr}{resp.realized_pnl:,.0f}"],
            ["Win Rate", f"{resp.win_rate:.0%}" if resp.win_rate is not None else "N/A"],
            ["Risk Deployed", f"{resp.risk_deployed_pct:.1f}%"],
            ["Positions Open", resp.positions_open],
        ]
        print_table("Daily Report", r_headers, r_rows)

        if resp.summary:
            print(f"  Summary: {resp.summary}\n")

        _record("generate_daily_report", "PASS", f"{resp.trades_closed} closed")
    except Exception as e:
        msg = print_error("generate_daily_report", e)
        if verbose: traceback.print_exc()
        _record("generate_daily_report", "FAIL", msg)

    wait_for_input(interactive)
```

- [ ] **Step 3: Commit**

```bash
git add challenge/harness.py
git commit -m "feat: harness Phase 6 & 7 — calendar + reporting"
```

---

### Task 8: Wire main() and __main__.py

**Files:**
- Modify: `challenge/harness.py`
- Create: `challenge/__main__.py` (if needed for `python -m challenge.harness`)

- [ ] **Step 1: Complete main() with all phase dispatch**

Add to bottom of `challenge/harness.py`:

```python
def main():
    args = parse_args()

    interactive = not args.all and args.phase is None
    verbose = args.verbose if hasattr(args, "verbose") else False

    # Market selection
    market = pick_market(preset=args.market)

    # Setup: broker + fallback
    print(f"\n  Connecting to {market} market...")
    ma, meta = setup(market)

    # Ticker selection
    tickers = pick_tickers(market, meta, preset=args.market if not interactive else None)

    # Banner
    print_banner(meta)

    # Phase selection
    if args.phase:
        phase = args.phase
    elif args.all:
        phase = 0
    else:
        phase = phase_menu()

    # Phase dispatch
    proposals = None

    if phase in (0, 1):
        run_premarket(ma, tickers, meta, interactive, verbose)
    if phase in (0, 2):
        proposals = run_scanning(ma, tickers, meta, interactive, verbose)
    if phase in (0, 3):
        run_entry(ma, tickers, proposals, meta, interactive, verbose)
    if phase in (0, 4):
        run_monitoring(ma, meta, interactive, verbose)
    if phase in (0, 5):
        run_portfolio_risk(ma, meta, interactive, verbose)
    if phase in (0, 6):
        run_calendar(ma, meta, interactive, verbose)
    if phase in (0, 7):
        run_reporting(ma, meta, interactive, verbose)

    # Summary (for Run All or non-interactive)
    if phase == 0 or args.all:
        _print_summary()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test interactive mode**

Run: `.venv_312/Scripts/python -m challenge.harness`

Expected: Shows market selection prompt, then banner, then phase menu

- [ ] **Step 3: Test non-interactive mode**

Run: `.venv_312/Scripts/python -m challenge.harness --all --market=US`

Expected: Runs all 7 phases, prints summary table at end

- [ ] **Step 4: Commit**

```bash
git add challenge/harness.py
git commit -m "feat: harness main() — full phase dispatch, interactive + CLI modes"
```

---

### Task 9: Fix Runtime Issues & Polish

After running end-to-end, fix any issues with field names, missing attributes, or response shape mismatches.

- [ ] **Step 1: Run full harness in non-interactive mode against simulated data**

Run: `.venv_312/Scripts/python -m challenge.harness --all --market=US 2>&1`

Fix any import errors, AttributeError, or field name mismatches.

- [ ] **Step 2: Run against India market**

Run: `.venv_312/Scripts/python -m challenge.harness --all --market=India 2>&1`

Fix any India-specific issues (lot sizes, currency, ticker names).

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `.venv_312/Scripts/python -m pytest tests/ -x -q --timeout=60 -m "not integration"`

Expected: All existing tests pass

- [ ] **Step 4: Commit all fixes**

```bash
git add challenge/harness.py challenge/harness_support.py
git commit -m "fix: harness runtime fixes after end-to-end testing"
```

---

### Task 10: Schedule in Coworker

Two scheduled runs: India market open and US market open.

- [ ] **Step 1: Create India market open schedule**

Use Claude Code's schedule/trigger feature to run:
```bash
cd C:\Users\nitin\PythonProjects\income_desk && .venv_312/Scripts/python -m challenge.harness --all --market=India
```

Cron: `45 3 * * 1-5` (9:15 IST = 3:45 UTC, weekdays only)

- [ ] **Step 2: Create US market open schedule**

```bash
cd C:\Users\nitin\PythonProjects\income_desk && .venv_312/Scripts/python -m challenge.harness --all --market=US
```

Cron: `30 13 * * 1-5` (9:30 ET = 13:30 UTC during EDT, weekdays only)

- [ ] **Step 3: Test schedule runs**

Verify both scheduled runs execute and produce pass/fail summaries.

- [ ] **Step 4: Commit any schedule config**

---

### Task 11: Final Commit & Documentation

- [ ] **Step 1: Update USER_MANUAL.md with harness documentation**

Add a section covering:
- How to run the harness (interactive, non-interactive, per-phase)
- What each phase tests
- How to read the summary output
- CLI arguments

- [ ] **Step 2: Final commit**

```bash
git add -A
git commit -m "docs: harness usage in USER_MANUAL.md"
```
