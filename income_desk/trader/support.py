"""Harness support — broker setup, formatting, demo data for workflow harness.

Non-workflow concerns: connection management, data source detection,
banner/signature/table formatting, demo positions, CLI arg parsing.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tabulate import tabulate


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class BannerMeta:
    """Metadata displayed in the harness banner."""

    market: str  # "US" or "India"
    broker_name: str | None = None  # "tastytrade (LIVE)", "dhan", None
    data_source: str = "Simulated"  # descriptive string
    account_nlv: float | None = None
    account_bp: float | None = None
    ticker_count: int = 0
    currency: str = "USD"
    tickers: list[str] = field(default_factory=list)
    broker_positions: list = field(default_factory=list)  # BrokerPosition objects
    account_provider: object = None  # AccountProvider for fetching positions


# ── Formatting helpers ───────────────────────────────────────────────────────


def print_banner(meta: BannerMeta) -> None:
    """Print a bordered info box with market/broker/data state."""
    width = 68
    border = "+" + "-" * (width - 2) + "+"

    lines: list[str] = []
    lines.append(f"Market: {meta.market}")
    lines.append(f"Broker: {meta.broker_name or 'None (simulated)'}")
    lines.append(f"Data:   {meta.data_source}")

    # Tickers — show first 6, then "N more"
    if meta.tickers:
        shown = meta.tickers[:6]
        extra = len(meta.tickers) - 6
        ticker_str = ", ".join(shown)
        if extra > 0:
            ticker_str += f" + {extra} more"
        lines.append(f"Tickers ({meta.ticker_count}): {ticker_str}")

    if meta.account_nlv is not None:
        fmt_nlv = f"{meta.currency} {meta.account_nlv:,.0f}"
        fmt_bp = f"{meta.currency} {meta.account_bp:,.0f}" if meta.account_bp else "N/A"
        lines.append(f"Account: NLV {fmt_nlv}  |  BP {fmt_bp}")

    print(border)
    print(f"| {'WORKFLOW HARNESS':^{width - 4}} |")
    print(border)
    for line in lines:
        print(f"| {line:<{width - 4}} |")
    print(border)
    print()


def print_signature(workflow_name: str, request: Any, cli_command: str = "") -> None:
    """Introspect a Pydantic request and print workflow signature + field values."""
    import typing

    print(f"\n{'=' * 60}")
    print(f"  WORKFLOW: {workflow_name}")
    print(f"{'=' * 60}")

    # Resolve the return type from the actual workflow function
    return_type_name = "?"
    try:
        from income_desk import workflow as wf_mod

        func = getattr(wf_mod, workflow_name, None)
        if func is not None:
            # Try get_type_hints first, fall back to __annotations__
            ret = None
            try:
                hints = typing.get_type_hints(func)
                ret = hints.get("return")
            except Exception:
                ann = getattr(func, "__annotations__", {})
                ret = ann.get("return")
            if ret is not None:
                return_type_name = getattr(ret, "__name__", str(ret))
    except Exception:
        pass

    req_cls = type(request)
    print(f"  Request:  {req_cls.__name__}")
    print(f"  Returns:  {return_type_name}")

    # Print field values
    if hasattr(req_cls, "model_fields"):
        print(f"  {'-' * 40}")
        for name, finfo in req_cls.model_fields.items():
            val = getattr(request, name, finfo.default)
            print(f"    {name}: {val!r}")

    if cli_command:
        print(f"\n  CLI: {cli_command}")
    print()


def print_table(
    title: str,
    headers: list[str],
    rows: list[list],
    tablefmt: str = "simple_grid",
) -> None:
    """Print a formatted table with title. Handle empty rows gracefully."""
    print(f"\n  {title}")
    if not rows:
        print("  (no data)")
        return
    try:
        output = tabulate(rows, headers=headers, tablefmt=tablefmt)
        print(output)
    except UnicodeEncodeError:
        # Fall back to plain grid on terminals that can't handle box-drawing chars
        print(tabulate(rows, headers=headers, tablefmt="grid"))
    print()


def print_error(workflow_name: str, error: Exception) -> str:
    """Print error inline and return error string for summary tracking."""
    msg = f"[ERROR] {workflow_name}: {type(error).__name__}: {error}"
    print(f"\n  {msg}")
    return msg


def wait_for_input(interactive: bool = True) -> str:
    """Wait for user input: n=next, s=skip phase, q=quit.

    Non-interactive mode always returns 'n'.
    """
    if not interactive:
        return "n"
    try:
        choice = input("\n  [n]ext / [s]kip phase / [q]uit > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "q"
    if choice in ("n", "s", "q"):
        return choice
    return "n"


# ── Market hours ─────────────────────────────────────────────────────────────


def is_market_open(market: str) -> bool:
    """Check if the given market is currently open (weekday + hours)."""
    try:
        import zoneinfo

        if market.upper() == "INDIA":
            tz = zoneinfo.ZoneInfo("Asia/Kolkata")
            now = datetime.now(tz)
            if now.weekday() >= 5:  # Sat/Sun
                return False
            t = now.time()
            from datetime import time as dt_time

            return dt_time(9, 15) <= t <= dt_time(15, 30)
        else:
            tz = zoneinfo.ZoneInfo("US/Eastern")
            now = datetime.now(tz)
            if now.weekday() >= 5:
                return False
            t = now.time()
            from datetime import time as dt_time

            return dt_time(9, 30) <= t <= dt_time(16, 0)
    except Exception:
        return False


# ── Setup / connection ───────────────────────────────────────────────────────


def setup(market: str) -> tuple:
    """Connect broker (or fall back to simulated) and return (MarketAnalyzer, BannerMeta).

    Fallback chain:
    1. Live broker (tastytrade for US, dhan for India)
    2. Snapshot from ~/.income_desk/sim_snapshot.json
    3. Preset simulation data
    """
    # Load .env so broker credentials are available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from income_desk import DataService, MarketAnalyzer
    from income_desk.adapters.simulated import (
        SimulatedAccount,
        SimulatedMarketData,
        SimulatedMetrics,
        create_from_snapshot,
        create_ideal_income,
        create_india_trading,
        get_snapshot_info,
    )

    md = None
    mm = None
    acct = None
    wl = None
    meta = BannerMeta(market=market)

    if market == "India":
        meta.currency = "INR"

    # --- 1. Try broker (suppress DXLink probe warnings) ---
    import logging
    broker_ok = False
    _loggers_to_quiet = [
        "income_desk.broker.tastytrade",
        "income_desk.broker.tastytrade.session",
        "income_desk.broker.tastytrade.dxlink",
        "tastytrade",
        "income_desk.broker.dhan",
        "income_desk",
    ]
    _saved_levels = {name: logging.getLogger(name).level for name in _loggers_to_quiet}
    for name in _loggers_to_quiet:
        logging.getLogger(name).setLevel(logging.CRITICAL)
    # Also suppress root logger warnings during connection
    _root_level = logging.getLogger().level
    logging.getLogger().setLevel(logging.CRITICAL)

    if market == "India":
        try:
            from income_desk.broker.dhan import connect_dhan

            md, mm, acct, wl = connect_dhan()
            meta.broker_name = "dhan"
            broker_ok = True
        except Exception as exc:
            print(f"  [broker] Dhan connection failed: {exc}")
    else:
        try:
            from income_desk.broker.tastytrade import connect_tastytrade

            md, mm, acct, wl = connect_tastytrade(is_paper=False)
            meta.broker_name = "tastytrade (LIVE)"
            broker_ok = True
        except Exception as exc:
            print(f"  [broker] TastyTrade connection failed: {exc}")

    # Restore log levels
    for name, level in _saved_levels.items():
        logging.getLogger(name).setLevel(level)
    logging.getLogger().setLevel(_root_level)

    # --- 2. Determine data source ---
    if broker_ok and is_market_open(market):
        meta.data_source = "LIVE quotes (market open)"
    elif broker_ok:
        meta.data_source = "Broker connected (market closed)"
        # Supplement with simulated metrics for IV ranks (DXLink unavailable)
        if market == "India":
            sim_fallback = create_india_trading()
        else:
            sim_fallback = create_ideal_income()
        mm = SimulatedMetrics(sim_fallback)
        # Keep broker md for account data, but use simulated for quotes
        md = sim_fallback
    else:
        # --- Fallback: snapshot then preset ---
        snap_info = get_snapshot_info()
        snap_sim = create_from_snapshot()
        if snap_sim is not None and snap_info is not None:
            age = snap_info.get("age_hours")
            age_str = f"{age:.0f}h old" if age is not None else "age unknown"
            meta.data_source = f"Simulated (snapshot {age_str})"
            md = snap_sim
        else:
            if market == "India":
                md = create_india_trading()
            else:
                md = create_ideal_income()
            meta.data_source = "Simulated (preset)"

        mm = SimulatedMetrics(md)
        acct = SimulatedAccount(
            nlv=md._account_nlv,
            cash=md._account_cash,
            bp=md._account_bp,
        )
        wl = None

    # --- 3. Account info ---
    meta.account_provider = acct
    if acct is not None:
        try:
            bal = acct.get_balance()
            meta.account_nlv = bal.net_liquidating_value
            meta.account_bp = bal.derivative_buying_power
        except Exception:
            pass

    # --- 4. Tickers ---
    if md is not None and hasattr(md, "supported_tickers"):
        meta.tickers = md.supported_tickers()
    elif md is not None and hasattr(md, "_tickers"):
        meta.tickers = sorted(md._tickers.keys())
    meta.ticker_count = len(meta.tickers)

    # --- 5. Build MarketAnalyzer ---
    ma = MarketAnalyzer(
        data_service=DataService(),
        market="India" if market == "India" else None,
        market_data=md,
        market_metrics=mm,
        account_provider=acct,
        watchlist_provider=wl,
    )

    return ma, meta


# ── Interactive pickers ──────────────────────────────────────────────────────


def pick_market(preset: str | None = None) -> str:
    """Interactive market selection or use preset."""
    if preset:
        return preset
    print("\n  Select market:")
    print("    1. US")
    print("    2. India")
    try:
        choice = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = "1"
    return "India" if choice == "2" else "US"


def pick_tickers(
    market: str,
    meta: BannerMeta,
    preset: list[str] | None = None,
) -> list[str]:
    """Pick tickers — use preset, meta.tickers, or defaults."""
    if preset:
        return preset

    defaults = _default_tickers(market)

    # If meta already has tickers from broker/simulation, use those
    if meta.tickers:
        return meta.tickers

    return defaults


def _default_tickers(market: str) -> list[str]:
    """Return all F&O tickers from registry that have options."""
    try:
        from income_desk.registry import MarketRegistry
        reg = MarketRegistry()
        all_instruments = reg._instruments
        tickers = [
            t for t, inst in all_instruments.items()
            if inst.market.upper() == market.upper()
            and inst.options_liquidity in ("high", "medium")
        ]
        if tickers:
            return sorted(tickers)
    except Exception:
        pass
    # Fallback if registry fails
    if market == "India":
        return [
            "NIFTY", "BANKNIFTY", "RELIANCE", "TCS",
            "HDFCBANK", "ICICIBANK", "SBIN",
        ]
    return [
        "SPY", "QQQ", "IWM", "GLD", "TLT",
        "AAPL", "MSFT", "NVDA",
    ]


# ── Universe loading ─────────────────────────────────────────────────────────


def load_universe(market: str, path: str | None = None) -> list[str]:
    """Load ticker universe from YAML/CSV file or return full preset defaults."""
    if path is not None:
        from pathlib import Path

        p = Path(path)
        if p.suffix in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore[import]

                data = yaml.safe_load(p.read_text())
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and "tickers" in data:
                    return data["tickers"]
            except Exception:
                pass
        elif p.suffix == ".csv":
            try:
                lines = p.read_text().strip().splitlines()
                # First column of each row, skip header if present
                tickers = []
                for line in lines:
                    tok = line.split(",")[0].strip()
                    if tok and tok.upper() != "TICKER":
                        tickers.append(tok.upper())
                return tickers
            except Exception:
                pass

    # Fallback: full simulated preset tickers
    if market == "India":
        from income_desk.adapters.simulated import create_india_trading

        sim = create_india_trading()
        return sorted(sim._tickers.keys())
    else:
        from income_desk.adapters.simulated import create_ideal_income

        sim = create_ideal_income()
        return sorted(sim._tickers.keys())


# ── Demo data builders ───────────────────────────────────────────────────────


def broker_positions_to_open(broker_positions: list, market: str) -> list:
    """Convert BrokerPosition objects to OpenPosition objects for workflow APIs.

    Groups option legs by ticker into structures (credit spreads, iron condors).
    Equities are skipped — workflows operate on option positions.
    """
    from datetime import date as date_type

    from income_desk.workflow._types import OpenPosition

    # Group option positions by ticker
    by_ticker: dict[str, list] = {}
    for p in broker_positions:
        if p.option_type is None:
            continue  # Skip equities
        by_ticker.setdefault(p.ticker, []).append(p)

    positions: list[OpenPosition] = []
    lot_size = 25 if market == "India" else 100

    for ticker, legs in by_ticker.items():
        # Determine structure type from leg count and sides
        short_legs = [l for l in legs if l.quantity < 0]
        long_legs = [l for l in legs if l.quantity > 0]

        if len(short_legs) >= 2 and len(long_legs) >= 2:
            structure = "iron_condor"
        elif short_legs and long_legs:
            structure = "credit_spread"
        elif short_legs:
            structure = "naked_short"
        elif long_legs:
            structure = "long_option"
        else:
            continue

        # Use the first short leg for entry price, or first leg if no short legs
        primary = short_legs[0] if short_legs else long_legs[0]
        entry_price = abs(primary.average_open_price)
        current_mid = abs(primary.close_price) if primary.close_price is not None else entry_price
        contracts = abs(primary.quantity)

        # DTE from earliest expiration
        exps = [l.expiration for l in legs if l.expiration is not None]
        if exps:
            earliest = min(exps)
            dte = (earliest - date_type.today()).days
        else:
            dte = 30

        positions.append(OpenPosition(
            trade_id=f"BRK-{ticker}-001",
            ticker=ticker,
            structure_type=structure,
            order_side="credit" if short_legs else "debit",
            entry_price=entry_price,
            current_mid_price=current_mid,
            contracts=contracts,
            dte_remaining=max(dte, 0),
            regime_id=1,
            lot_size=lot_size,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
        ))

    return positions


def build_demo_positions(market: str) -> list:
    """Build 3 demo OpenPositions for monitoring/overnight/stress testing."""
    from income_desk.workflow._types import OpenPosition

    if market == "India":
        return [
            OpenPosition(
                trade_id="DEMO-IN-001",
                ticker="NIFTY",
                structure_type="iron_condor",
                order_side="credit",
                entry_price=85.0,
                current_mid_price=60.0,
                contracts=2,
                dte_remaining=12,
                regime_id=1,
                lot_size=25,
                profit_target_pct=0.50,
                stop_loss_pct=2.0,
            ),
            OpenPosition(
                trade_id="DEMO-IN-002",
                ticker="BANKNIFTY",
                structure_type="credit_spread",
                order_side="credit",
                entry_price=120.0,
                current_mid_price=95.0,
                contracts=1,
                dte_remaining=5,
                regime_id=2,
                lot_size=15,
                profit_target_pct=0.50,
                stop_loss_pct=2.0,
            ),
            OpenPosition(
                trade_id="DEMO-IN-003",
                ticker="RELIANCE",
                structure_type="credit_spread",
                order_side="credit",
                entry_price=18.0,
                current_mid_price=12.0,
                contracts=1,
                dte_remaining=20,
                regime_id=1,
                lot_size=250,
                profit_target_pct=0.50,
                stop_loss_pct=2.0,
            ),
        ]

    # US positions
    return [
        OpenPosition(
            trade_id="DEMO-US-001",
            ticker="SPY",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=2.80,
            current_mid_price=1.90,
            contracts=2,
            dte_remaining=18,
            regime_id=1,
            lot_size=100,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
        ),
        OpenPosition(
            trade_id="DEMO-US-002",
            ticker="QQQ",
            structure_type="credit_spread",
            order_side="credit",
            entry_price=1.50,
            current_mid_price=1.10,
            contracts=3,
            dte_remaining=8,
            regime_id=2,
            lot_size=100,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
        ),
        OpenPosition(
            trade_id="DEMO-US-003",
            ticker="IWM",
            structure_type="iron_condor",
            order_side="credit",
            entry_price=3.20,
            current_mid_price=2.40,
            contracts=1,
            dte_remaining=25,
            regime_id=1,
            lot_size=100,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
        ),
    ]


def load_whatif_positions(market: str) -> list:
    """Load what-if positions from the pricing regression portfolio.

    Uses real chain-built trades (from test_portfolio_india.json or
    test_portfolio_us.json) instead of hardcoded demo data.
    Falls back to build_demo_positions() if no portfolio exists.
    """
    from datetime import date as date_type
    from pathlib import Path

    from income_desk.workflow._types import OpenPosition

    portfolio_file = (
        Path.home() / ".income_desk" / f"test_portfolio_{market.lower()}.json"
    )

    if not portfolio_file.exists():
        print(f"  No what-if portfolio at {portfolio_file.name} — using demo positions")
        return build_demo_positions(market)

    try:
        import json
        with open(portfolio_file) as f:
            trades = json.load(f)
    except Exception:
        return build_demo_positions(market)

    # Filter out expired trades
    today = date_type.today()
    active = [t for t in trades if not t.get("expiry") or t["expiry"] >= today.isoformat()]
    if not active:
        print(f"  All what-if trades expired — using demo positions")
        return build_demo_positions(market)

    positions: list[OpenPosition] = []
    lot_size_default = 25 if market == "India" else 100

    for t in active[:10]:  # Cap at 10 for performance
        # Determine structure from trade
        structure = t.get("structure", "iron_condor")
        credit = t.get("net_credit", 0)

        # Estimate DTE from expiry
        dte = 30
        if t.get("expiry"):
            try:
                exp = date_type.fromisoformat(t["expiry"])
                dte = max((exp - today).days, 0)
            except ValueError:
                pass

        positions.append(OpenPosition(
            trade_id=t.get("id", f"WIF-{t['ticker']}-001"),
            ticker=t["ticker"],
            structure_type=structure.replace("_put", "").replace("_call", ""),
            order_side="credit" if credit >= 0 else "debit",
            entry_price=abs(credit),
            current_mid_price=abs(credit) * 0.8,  # Assume 20% profit for monitoring test
            contracts=1,
            dte_remaining=dte,
            regime_id=1,
            lot_size=t.get("lot_size", lot_size_default),
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
        ))

    print(f"  Loaded {len(positions)} what-if positions from {portfolio_file.name}")
    return positions


def build_demo_proposal(market: str) -> dict:
    """Fallback trade proposal when phase 2 was not run."""
    if market == "India":
        return {
            "ticker": "NIFTY",
            "structure": "iron_condor",
            "regime_id": 1,
            "entry_credit": 85.0,
            "atr_pct": 2.1,
            "current_price": 23_000.0,
            "pop_pct": 68.0,
            "max_profit": 85.0 * 25,
            "max_loss": 415.0 * 25,
            "capital": 415.0 * 25,
            "wing_width": 500.0,
            "dte": 21,
        }
    return {
        "ticker": "SPY",
        "structure": "iron_condor",
        "regime_id": 1,
        "entry_credit": 2.80,
        "atr_pct": 1.1,
        "current_price": 565.0,
        "pop_pct": 72.0,
        "max_profit": 2.80 * 100,
        "max_loss": 2.20 * 100,
        "capital": 2.20 * 100,
        "wing_width": 5.0,
        "dte": 35,
    }


# ── Position loading ────────────────────────────────────────────────────────


def load_positions(meta: BannerMeta, interactive: bool = True) -> list:
    """Load positions from broker or CSV file.

    Step 2 of the harness: after broker connects, fetch real positions.
    Falls back to CSV import or demo positions.

    Returns list of :class:`~income_desk.models.quotes.BrokerPosition`.
    """
    from income_desk.models.quotes import BrokerPosition

    # --- 1. Try broker positions ---
    if meta.account_provider is not None:
        try:
            positions = meta.account_provider.get_positions()
            if positions:
                print(f"\n  Loaded {len(positions)} positions from {meta.broker_name or 'broker'}")
                _print_broker_positions(positions, meta.currency)
                meta.broker_positions = positions
                return positions
            else:
                print(f"\n  No open positions found in broker account.")
        except Exception as exc:
            print(f"\n  Could not fetch positions from broker: {exc}")

    # --- 2. Offer CSV import ---
    if interactive:
        print("\n  No broker positions available.")
        print("    1. Load positions from CSV file")
        print("    2. Continue with demo positions")
        try:
            choice = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = "2"

        if choice == "1":
            try:
                csv_path = input("  CSV file path: ").strip().strip('"').strip("'")
            except (EOFError, KeyboardInterrupt):
                csv_path = ""

            if csv_path:
                positions = _load_positions_from_csv(csv_path, meta)
                if positions:
                    meta.broker_positions = positions
                    return positions
    else:
        print("\n  No broker positions — using demo positions.")

    return []


def _load_positions_from_csv(csv_path: str, meta: BannerMeta) -> list:
    """Import positions from a broker CSV export."""
    from pathlib import Path

    from income_desk.adapters.csv_trades import import_trades_csv
    from income_desk.models.quotes import BrokerPosition

    path = Path(csv_path)
    if not path.exists():
        print(f"  File not found: {csv_path}")
        return []

    result = import_trades_csv(csv_path)

    if result.errors:
        for err in result.errors[:5]:
            print(f"  [warn] {err}")

    if not result.positions:
        print(f"  No positions parsed from {result.broker_detected} CSV.")
        return []

    # Convert ImportedPosition -> BrokerPosition
    positions: list[BrokerPosition] = []
    for p in result.positions:
        positions.append(BrokerPosition(
            ticker=p.ticker,
            symbol=p.raw_symbol,
            instrument_type="Equity Option" if p.option_type else "Equity",
            quantity=p.quantity,
            average_open_price=p.entry_price,
            multiplier=100 if meta.market == "US" else 25,
            expiration=p.expiration,
            strike=p.strike,
            option_type=p.option_type,
            source=f"csv:{result.broker_detected}",
        ))

    print(f"\n  Imported {len(positions)} positions from {result.broker_detected} CSV")
    _print_broker_positions(positions, meta.currency)
    return positions


def _print_broker_positions(positions: list, currency: str) -> None:
    """Print a summary table of loaded positions."""
    cur = "INR " if currency == "INR" else "$"

    # Group by ticker for summary
    by_ticker: dict[str, list] = {}
    for p in positions:
        by_ticker.setdefault(p.ticker, []).append(p)

    rows = []
    for ticker, pos_list in sorted(by_ticker.items()):
        for p in pos_list:
            if p.option_type:
                desc = f"{p.strike:.0f} {p.option_type[0].upper()}"
                if p.expiration:
                    desc += f" {p.expiration.strftime('%m/%d')}"
            else:
                desc = "equity"
            rows.append([
                ticker,
                desc,
                p.quantity,
                f"{cur}{p.average_open_price:.2f}",
                p.instrument_type,
            ])

    print_table(
        "Broker Positions",
        ["Ticker", "Description", "Qty", "Avg Price", "Type"],
        rows,
    )


# ── CLI arg parsing ──────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    """Parse harness CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Workflow Harness — exercise all 15 income_desk workflow APIs",
    )
    parser.add_argument(
        "--market",
        choices=["US", "India"],
        default=None,
        help="Market to test (default: interactive prompt)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="run_all",
        help="Run all phases non-interactively",
    )
    parser.add_argument(
        "--phase",
        type=int,
        choices=range(1, 8),
        default=None,
        help="Run a single phase (1-7)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--build-snapshot",
        action="store_true",
        dest="build_snapshot",
        help="Build instrument snapshot, save to disk, and exit",
    )
    return parser.parse_args()
