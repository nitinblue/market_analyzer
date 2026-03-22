"""Interactive REPL for market_analyzer — Claude-like interface.

Usage:
    analyzer-cli
    analyzer-cli --market india
"""

from __future__ import annotations

import argparse
import cmd
import sys
import traceback
from datetime import date

from tabulate import tabulate


from income_desk.cli._broker import _styled, connect_broker

# Trade lifecycle & factory imports (lazy-safe: all are pure functions)
from income_desk.trade_lifecycle import (
    aggregate_greeks,
    align_strikes_to_levels,
    check_income_entry,
    check_trade_health,
    compute_breakevens,
    compute_income_yield,
    estimate_pop,
    filter_trades_by_account,
    monitor_exit_conditions,
)
from income_desk.trade_spec_factory import (
    from_dxlink_symbols,
    parse_dxlink_symbol,
    to_dxlink_symbols,
)


def _print_header(title: str) -> None:
    print(f"\n{_styled('=' * 60, 'dim')}")
    print(f"  {_styled(title, 'bold')}")
    print(f"{_styled('=' * 60, 'dim')}")


def _profile_tag(structure_type: str | None, order_side: str | None = None,
                 direction: str | None = None) -> str:
    """Format a compact profile tag: '/‾‾\\ neutral · defined'."""
    if not structure_type:
        return ""
    from income_desk.models.opportunity import get_structure_profile, RiskProfile
    p = get_structure_profile(structure_type, order_side, direction)
    risk_str = (
        _styled("UNDEFINED", "red") if p.risk_profile == RiskProfile.UNDEFINED
        else _styled("defined", "green")
    )
    return f"{p.payoff_graph} {p.bias} · {risk_str}"


class AnalyzerCLI(cmd.Cmd):
    """Interactive REPL for market analysis."""

    intro = (
        "\n"
        + _styled("market_analyzer", "bold")
        + " — interactive analysis REPL\n"
        + _styled("Type 'help' for commands, 'quit' to exit.", "dim")
        + "\n"
    )
    prompt = _styled("market_analyzer> ", "cyan") if sys.stdout.isatty() else "market_analyzer> "

    def __init__(
        self,
        market: str = "US",
        broker: bool = False,
        sim_market_data=None,
        sim_market_metrics=None,
        sim_account=None,
    ) -> None:
        super().__init__()
        self._market = market
        self._broker = broker
        self._sim_market_data = sim_market_data
        self._sim_market_metrics = sim_market_metrics
        self._sim_account = sim_account
        self._ma = None  # Lazy-init
        self._watchlist_provider = None  # Set on broker connect

    def _get_ma(self):
        """Lazy-initialize MarketAnalyzer (avoids slow import on startup)."""
        if self._ma is None:
            print("Initializing services...")
            from income_desk import DataService, MarketAnalyzer

            market_data = None
            market_metrics = None
            account_provider = None

            if self._sim_market_data is not None:
                # Simulated mode — no broker connection needed
                market_data = self._sim_market_data
                market_metrics = self._sim_market_metrics
                account_provider = self._sim_account
            elif self._broker:
                market_data, market_metrics, account_provider, self._watchlist_provider = connect_broker()

            self._ma = MarketAnalyzer(
                data_service=DataService(),
                market=self._market,
                market_data=market_data,
                market_metrics=market_metrics,
                account_provider=account_provider,
                watchlist_provider=self._watchlist_provider,
            )
            print(_styled("Ready.", "green"))
        return self._ma

    def _resolve_tickers(self, arg: str, allow_watchlist: bool = True) -> list[str]:
        """Parse tickers from arg, supporting --watchlist, --preset, and auto-default.

        Sources (in priority order):
        1. Explicit tickers: ``rank SPY GLD QQQ``
        2. ``--watchlist NAME``: pull from broker watchlist (requires broker)
        3. ``--preset NAME``: pull from registry universe (no broker needed)
        4. Auto-default: if nothing specified, use registry default for current market
        """
        parts = arg.strip().split()
        tickers: list[str] = []
        i = 0
        while i < len(parts):
            if parts[i] == "--watchlist" and i + 1 < len(parts) and allow_watchlist:
                wl_name = parts[i + 1]
                if self._watchlist_provider is None:
                    print(_styled(f"No broker connected — cannot fetch watchlist '{wl_name}'", "yellow"))
                else:
                    wl_tickers = self._watchlist_provider.get_watchlist(wl_name)
                    if wl_tickers:
                        print(f"  Loaded {len(wl_tickers)} tickers from watchlist '{wl_name}'")
                        tickers.extend(wl_tickers)
                    else:
                        print(_styled(f"Watchlist '{wl_name}' not found or empty", "yellow"))
                i += 2
            elif parts[i] == "--preset" and i + 1 < len(parts):
                preset_name = parts[i + 1].lower()
                ma = self._get_ma()
                preset_tickers = ma.registry.get_universe(preset=preset_name, market=self._market)
                if preset_tickers:
                    print(f"  Loaded {len(preset_tickers)} tickers from preset '{preset_name}' ({self._market})")
                    tickers.extend(preset_tickers)
                else:
                    print(_styled(f"Preset '{preset_name}' returned no tickers for {self._market}", "yellow"))
                i += 2
            elif parts[i].startswith("--"):
                break  # Stop at other flags
            else:
                tickers.append(parts[i].upper())
                i += 1

        # Auto-default: if no tickers from any source, use market default
        if not tickers:
            ma = self._get_ma()
            default_preset = "income" if self._market.upper() == "US" else "india_fno"
            tickers = ma.registry.get_universe(preset=default_preset, market=self._market)
            if tickers:
                print(f"  Using default '{default_preset}' universe ({len(tickers)} tickers)")

        return tickers

    def _parse_tickers(self, arg: str) -> list[str]:
        """Parse space-separated tickers from command argument."""
        return arg.upper().split() if arg.strip() else []

    # --- Commands ---

    def do_watchlist(self, arg: str) -> None:
        """Show or load broker watchlists.\nUsage: watchlist           — list all watchlists\n       watchlist NAME      — show tickers in a watchlist"""
        self._get_ma()  # Ensure broker connected

        if self._watchlist_provider is None:
            print(_styled("No broker connected. Run with --broker for watchlists.", "yellow"))
            return

        name = arg.strip()
        if not name:
            # List all watchlists
            try:
                names = self._watchlist_provider.list_watchlists()
                _print_header("Broker Watchlists")
                if not names:
                    print("\n  No watchlists found.")
                else:
                    for n in names:
                        print(f"  {n}")
                print(f"\n  {_styled('Use: watchlist NAME to see tickers', 'dim')}")
                print(f"  {_styled('Use: screen --watchlist NAME to scan a watchlist', 'dim')}")
            except Exception as exc:
                print(f"{_styled('ERROR:', 'red')} {exc}")
        else:
            # Show tickers in a specific watchlist
            try:
                tickers = self._watchlist_provider.get_watchlist(name)
                _print_header(f"Watchlist: {name} ({len(tickers)} tickers)")
                if tickers:
                    # Show in columns of 8
                    for i in range(0, len(tickers), 8):
                        row = tickers[i:i+8]
                        print(f"  {', '.join(row)}")
                else:
                    print(f"\n  Watchlist '{name}' not found or empty.")
                print(f"\n  {_styled('Use: screen --watchlist ' + name + ' to scan these tickers', 'dim')}")
            except Exception as exc:
                print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_universe(self, arg: str) -> None:
        """Scan broker universe with filters to build trading watchlist.
\nUsage: universe                          — scan with default filters
       universe income                    — use income preset (ETF, IV rank 30-80, liq 4+)
       universe directional               — use directional preset (ETF+equity, beta 0.8-2.0)
       universe high_vol                   — use high_vol preset (IV rank 60+)
       universe broad                      — broad scan (ETF+equity, liq 2+, 100 symbols)
       universe income --save MA-Income    — scan and save as TastyTrade watchlist
       universe --iv-rank 40 80 --liq 4    — custom filters\n
Presets: income, directional, high_vol, broad
Requires --broker connection."""
        ma = self._get_ma()

        if not ma.universe.has_broker:
            print(_styled("No broker connected. Run with --broker for universe scanning.", "yellow"))
            return

        from income_desk.models.universe import PRESETS, UniverseFilter

        parts = arg.strip().split()
        preset_name: str | None = None
        save_name: str | None = None
        custom_filter: UniverseFilter | None = None

        # Parse args
        i = 0
        custom_kwargs: dict = {}
        while i < len(parts):
            p = parts[i]
            if p == "--save" and i + 1 < len(parts):
                save_name = parts[i + 1]
                i += 2
            elif p == "--iv-rank" and i + 2 < len(parts):
                custom_kwargs["iv_rank_min"] = float(parts[i + 1])
                custom_kwargs["iv_rank_max"] = float(parts[i + 2])
                i += 3
            elif p == "--liq" and i + 1 < len(parts):
                custom_kwargs["min_liquidity_rating"] = int(parts[i + 1])
                i += 2
            elif p == "--beta" and i + 2 < len(parts):
                custom_kwargs["beta_min"] = float(parts[i + 1])
                custom_kwargs["beta_max"] = float(parts[i + 2])
                i += 2
            elif p == "--max" and i + 1 < len(parts):
                custom_kwargs["max_symbols"] = int(parts[i + 1])
                i += 2
            elif p == "--etf-only":
                custom_kwargs["asset_types"] = ["ETF"]
                i += 1
            elif p == "--no-earnings" and i + 1 < len(parts):
                custom_kwargs["exclude_earnings_within_days"] = int(parts[i + 1])
                i += 2
            elif p in PRESETS:
                preset_name = p
                i += 1
            else:
                i += 1

        if custom_kwargs and not preset_name:
            custom_filter = UniverseFilter(**custom_kwargs)

        try:
            _print_header("Universe Scan")
            label = preset_name or ("custom" if custom_filter else "default")
            print(f"\n  Filter: {_styled(label, 'bold')}")
            if preset_name and preset_name in PRESETS:
                f = PRESETS[preset_name]
                details = []
                if f.iv_rank_min is not None or f.iv_rank_max is not None:
                    details.append(f"IV rank {f.iv_rank_min or 0}-{f.iv_rank_max or 100}")
                if f.min_liquidity_rating:
                    details.append(f"liquidity >= {f.min_liquidity_rating}")
                if f.beta_min is not None or f.beta_max is not None:
                    details.append(f"beta {f.beta_min or 0}-{f.beta_max or 'any'}")
                details.append(f"max {f.max_symbols} symbols")
                print(f"  Criteria: {', '.join(details)}")

            print(f"  Scanning broker universe...\n")

            result = ma.universe.scan(
                filter_config=custom_filter,
                preset=preset_name,
                save_watchlist=save_name,
            )

            if not result.candidates:
                print(_styled("  No symbols passed filters.", "yellow"))
                return

            # Table output
            from tabulate import tabulate
            rows = []
            for c in result.candidates:
                rows.append({
                    "Ticker": c.ticker,
                    "Type": c.asset_type,
                    "IV Rank": f"{c.iv_rank:.0f}" if c.iv_rank is not None else "-",
                    "IV%ile": f"{c.iv_percentile:.0f}" if c.iv_percentile is not None else "-",
                    "HV30": f"{c.hv_30_day:.1f}" if c.hv_30_day is not None else "-",
                    "IV-HV": f"{c.iv_hv_spread:+.1f}" if c.iv_hv_spread is not None else "-",
                    "Beta": f"{c.beta:.2f}" if c.beta is not None else "-",
                    "Liq": f"{c.liquidity_rating:.0f}" if c.liquidity_rating is not None else "-",
                    "Earnings": c.earnings_date or "-",
                })

            print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))
            print(f"\n  Scanned: {result.total_scanned} | Passed: {result.total_passed}")

            if result.include_forced:
                print(f"  Forced include: {', '.join(result.include_forced)}")

            if result.watchlist_saved:
                print(_styled(f"\n  Saved as TastyTrade watchlist: '{result.watchlist_saved}'", "green"))

            # Hint
            tickers_str = " ".join(c.ticker for c in result.candidates[:10])
            print(f"\n  {_styled(f'Use: rank {tickers_str}', 'dim')}")
            if save_name:
                print(f"  {_styled(f'Use: screen --watchlist {save_name}', 'dim')}")

        except Exception as exc:
            traceback.print_exc()
            print(f"\n{_styled('ERROR:', 'red')} {exc}")

    def do_context(self, arg: str) -> None:
        """Show market environment assessment.\nUsage: context"""
        try:
            ma = self._get_ma()
            ctx = ma.context.assess()

            _print_header(f"Market Context — {ctx.market} ({ctx.as_of_date})")
            print(f"\n  Environment:  {_styled(ctx.environment_label, 'bold')}")
            print(f"  Trading:      {'ALLOWED' if ctx.trading_allowed else _styled('HALTED', 'red')}")
            print(f"  Size Factor:  {ctx.position_size_factor:.0%}")
            print(f"  Black Swan:   {ctx.black_swan.alert_level} (score: {ctx.black_swan.composite_score:.2f})")

            # Macro events
            events_7 = ctx.macro.events_next_7_days
            if events_7:
                print(f"\n  Macro events next 7 days:")
                for e in events_7:
                    print(f"    {e.date} | {e.name} ({e.impact})")

            # Intermarket
            if ctx.intermarket.entries:
                print(f"\n  Intermarket dashboard:")
                rows = []
                for entry in ctx.intermarket.entries:
                    rows.append({
                        "Ticker": entry.ticker,
                        "Regime": f"R{entry.regime}",
                        "Confidence": f"{entry.confidence:.0%}",
                        "Direction": entry.trend_direction or "",
                    })
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

            print(f"\n  {_styled(ctx.summary, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_analyze(self, arg: str) -> None:
        """Show full instrument analysis.\nUsage: analyze SPY"""
        tickers = self._parse_tickers(arg)
        if not tickers:
            print("Usage: analyze TICKER [TICKER ...]")
            return

        ma = self._get_ma()
        for ticker in tickers:
            try:
                a = ma.instrument.analyze(ticker, include_opportunities=True)
                _print_header(f"{ticker} — Instrument Analysis ({a.as_of_date})")

                print(f"\n  Regime:       R{a.regime_id} ({a.regime.confidence:.0%})")
                print(f"  Phase:        {a.phase.phase_name} ({a.phase.confidence:.0%})")
                print(f"  Trend Bias:   {a.trend_bias}")
                print(f"  Volatility:   {a.volatility_label}")
                print(f"  Price:        ${a.technicals.current_price:.2f}")
                print(f"  RSI:          {a.technicals.rsi.value:.1f}")
                print(f"  ATR%:         {a.technicals.atr_pct:.2f}%")

                # Levels
                if a.levels:
                    print(f"\n  Levels:")
                    if a.levels.stop_loss:
                        print(f"    Stop:     ${a.levels.stop_loss.price:.2f} ({a.levels.stop_loss.distance_pct:+.1f}%)")
                    if a.levels.best_target:
                        print(f"    Target:   ${a.levels.best_target.price:.2f} (R:R {a.levels.best_target.risk_reward_ratio:.1f})")

                # Opportunities
                if a.actionable_setups:
                    print(f"\n  Actionable:   {', '.join(a.actionable_setups)}")

                print(f"\n  {_styled(a.summary, 'dim')}")

            except Exception as exc:
                print(f"{_styled('ERROR:', 'red')} {ticker}: {exc}")

    def do_screen(self, arg: str) -> None:
        """Screen tickers for setups.\nUsage: screen SPY GLD QQQ TLT\n       screen --watchlist MA-Income"""
        tickers = self._resolve_tickers(arg)
        if not tickers:
            from income_desk.config import get_settings
            tickers = get_settings().display.default_tickers
            print(f"Using default tickers: {' '.join(tickers)}")

        try:
            ma = self._get_ma()
            result = ma.screening.scan(tickers)
            _print_header(f"Screening Results ({result.as_of_date})")

            if not result.candidates:
                print("\n  No candidates found.")
            else:
                rows = []
                for c in result.candidates:
                    rows.append({
                        "Ticker": c.ticker,
                        "Screen": c.screen,
                        "Score": f"{c.score:.2f}",
                        "Regime": f"R{c.regime_id}",
                        "RSI": f"{c.rsi:.0f}",
                        "ATR%": f"{c.atr_pct:.2f}",
                        "Reason": c.reason[:60],
                    })
                print()
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

            print(f"\n  {_styled(result.summary, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_entry(self, arg: str) -> None:
        """Confirm entry signal.\nUsage: entry SPY breakout"""
        parts = arg.strip().split()
        if len(parts) < 2:
            print("Usage: entry TICKER TRIGGER_TYPE")
            print("  Trigger types: breakout, pullback, momentum, mean_reversion, orb")
            return

        ticker = parts[0].upper()
        trigger_map = {
            "breakout": "breakout_confirmed",
            "pullback": "pullback_to_support",
            "momentum": "momentum_continuation",
            "mean_reversion": "mean_reversion_extreme",
            "orb": "orb_breakout",
        }
        trigger_name = trigger_map.get(parts[1].lower(), parts[1].lower())

        try:
            from income_desk.models.entry import EntryTriggerType
            trigger = EntryTriggerType(trigger_name)

            ma = self._get_ma()
            result = ma.entry.confirm(ticker, trigger)

            _print_header(f"{ticker} — Entry Confirmation ({result.trigger_type.value})")
            status = _styled("CONFIRMED", "green") if result.confirmed else _styled("NOT CONFIRMED", "red")
            print(f"\n  Status:      {status}")
            print(f"  Confidence:  {result.confidence:.0%}")
            print(f"  Conditions:  {result.conditions_met}/{result.conditions_total}")

            if result.suggested_entry_price:
                print(f"  Entry Price: ${result.suggested_entry_price:.2f}")
            if result.suggested_stop_price:
                print(f"  Stop Price:  ${result.suggested_stop_price:.2f}")
            if result.risk_per_share:
                print(f"  Risk/Share:  ${result.risk_per_share:.2f}")

            print("\n  Conditions:")
            for c in result.conditions:
                icon = _styled("+", "green") if c.met else _styled("-", "red")
                print(f"    {icon} {c.name}: {c.description}")

        except ValueError as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")
        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_strategy(self, arg: str) -> None:
        """Show strategy recommendation.\nUsage: strategy SPY"""
        tickers = self._parse_tickers(arg)
        if not tickers:
            print("Usage: strategy TICKER")
            return

        try:
            ma = self._get_ma()
            ticker = tickers[0]
            ohlcv = ma.data.get_ohlcv(ticker) if ma.data else None
            regime = ma.regime.detect(ticker, ohlcv)
            technicals = ma.technicals.snapshot(ticker, ohlcv)

            result = ma.strategy.select(ticker, regime=regime, technicals=technicals)

            _print_header(f"{ticker} — Strategy Recommendation")
            p = result.primary_structure
            print(f"\n  Structure:   {p.structure_type.value}")
            print(f"  Direction:   {p.direction}")
            print(f"  Max Loss:    {p.max_loss}")
            print(f"  Theta:       {p.theta_exposure}")
            print(f"  Vega:        {p.vega_exposure}")
            print(f"  DTE Range:   {result.suggested_dte_range[0]}-{result.suggested_dte_range[1]}")
            print(f"  Delta Range: {result.suggested_delta_range[0]:.0%}-{result.suggested_delta_range[1]:.0%}")
            if result.wing_width_suggestion:
                print(f"  Wing Width:  {result.wing_width_suggestion}")

            # Position size
            size = ma.strategy.size(result, current_price=technicals.current_price)
            print(f"\n  Position Sizing:")
            print(f"    Account:     ${size.account_size:,.0f}")
            print(f"    Max Risk:    ${size.max_risk_dollars:,.0f} ({size.max_risk_pct:.0f}%)")
            print(f"    Contracts:   {size.suggested_contracts} (max {size.max_contracts})")
            if size.margin_estimate:
                print(f"    Margin Est:  ${size.margin_estimate:,.0f}")

            # Position size for common account sizes
            print(f"\n  Position Size (at current price ${technicals.current_price:.2f}):")
            for acct in [30000, 50000, 200000]:
                sz = ma.strategy.size(result, current_price=technicals.current_price)
                # Also use TradeSpec position_size if available
                print(f"    ${acct:>7,}: ~{max(1, int(acct * 0.02 / (sz.max_risk_dollars / max(sz.suggested_contracts, 1))))} contracts")

            print(f"\n  {_styled(result.regime_rationale, 'dim')}")

            if result.alternative_structures:
                print(f"\n  Alternatives:")
                for alt in result.alternative_structures:
                    print(f"    - {alt.structure_type.value} ({alt.direction}): {alt.rationale}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_exit_plan(self, arg: str) -> None:
        """Show exit plan for a position.\nUsage: exit_plan SPY 580"""
        parts = arg.strip().split()
        if len(parts) < 2:
            print("Usage: exit_plan TICKER ENTRY_PRICE")
            return

        ticker = parts[0].upper()
        try:
            entry_price = float(parts[1])
        except ValueError:
            print("Entry price must be a number.")
            return

        try:
            ma = self._get_ma()
            ohlcv = ma.data.get_ohlcv(ticker) if ma.data else None
            regime = ma.regime.detect(ticker, ohlcv)
            technicals = ma.technicals.snapshot(ticker, ohlcv)
            levels = ma.levels.analyze(ticker, ohlcv=ohlcv)
            strategy = ma.strategy.select(ticker, regime=regime, technicals=technicals)

            plan = ma.exit.plan(
                ticker, strategy, entry_price=entry_price,
                regime=regime, technicals=technicals, levels=levels,
            )

            _print_header(f"{ticker} — Exit Plan ({plan.strategy_type} @ ${entry_price:.2f})")

            if plan.profit_targets:
                print(f"\n  Profit Targets:")
                for t in plan.profit_targets:
                    print(f"    ${t.price:.2f} ({t.pct_from_entry:+.1f}%) — {t.action}: {t.description}")

            if plan.stop_loss:
                print(f"\n  Stop Loss:")
                print(f"    ${plan.stop_loss.price:.2f} ({plan.stop_loss.pct_from_entry:+.1f}%) — {plan.stop_loss.description}")

            if plan.trailing_stop:
                print(f"\n  Trailing Stop:")
                print(f"    ${plan.trailing_stop.price:.2f} — {plan.trailing_stop.description}")

            if plan.risk_reward_ratio:
                print(f"\n  R:R Ratio:   {plan.risk_reward_ratio:.1f}")

            if plan.dte_exit_threshold:
                print(f"  Time Exit:   Close at {plan.dte_exit_threshold} DTE")
            if plan.theta_decay_exit_pct:
                print(f"  Theta Exit:  Close at {plan.theta_decay_exit_pct:.0f}% max profit")

            if plan.adjustments:
                print(f"\n  Adjustments:")
                for adj in plan.adjustments:
                    print(f"    [{adj.urgency}] {adj.condition}")
                    print(f"      → {adj.action}")

            print(f"\n  Regime Change: {plan.regime_change_action}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_rank(self, arg: str) -> None:
        """Rank trades across tickers.\nUsage: rank SPY GLD QQQ TLT [--account 30000] [--debug]\n       rank --watchlist MA-Income --account 30000"""
        # Extract --account and --debug before _resolve_tickers
        parts = arg.strip().split()
        account_bp: float | None = None
        debug: bool = False
        filtered_parts = []
        i = 0
        while i < len(parts):
            if parts[i] == "--account" and i + 1 < len(parts):
                try:
                    account_bp = float(parts[i + 1])
                except ValueError:
                    print(f"Invalid account size: {parts[i + 1]}")
                    return
                i += 2
            elif parts[i] == "--debug":
                debug = True
                i += 1
            else:
                filtered_parts.append(parts[i])
                i += 1

        tickers = self._resolve_tickers(" ".join(filtered_parts))
        if not tickers:
            from income_desk.config import get_settings
            tickers = get_settings().display.default_tickers

        try:
            ma = self._get_ma()
            if not ma.quotes.has_broker:
                print(_styled(
                    "  *** ESTIMATED DATA — No broker connected. Credits, POP, and sizing are approximate. ***\n"
                    "  *** Connect broker (--broker) for real DXLink quotes and accurate analysis.         ***",
                    "yellow",
                ))
            result = ma.ranking.rank(tickers, debug=debug)
            source = ma.quotes.source
            _print_header(f"Trade Ranking ({result.as_of_date})  [data: {source}]")

            if result.black_swan_gate:
                print(f"\n  {_styled('TRADING HALTED — Black Swan CRITICAL', 'red')}")

            trades_to_show = result.top_trades

            # Account filter
            if account_bp is not None and trades_to_show:
                filtered = filter_trades_by_account(
                    trades_to_show,
                    available_buying_power=account_bp,
                )
                print(f"\n  Account filter: ${account_bp:,.0f} BP — "
                      f"{filtered.total_affordable}/{filtered.total_input} trades affordable")
                if filtered.filtered_out:
                    for fo in filtered.filtered_out[:3]:
                        print(f"    {_styled('x', 'red')} {fo['ticker']} {fo['strategy_type']}: {fo.get('filter_reason', '')}")
                # Map back to RankedEntry objects
                affordable_keys = {(t["ticker"], t["strategy_type"]) for t in filtered.affordable}
                trades_to_show = [e for e in trades_to_show
                                  if (e.ticker, str(e.strategy_type)) in affordable_keys]

            if trades_to_show:
                rows = []
                for e in trades_to_show[:10]:
                    legs_str = ""
                    exit_str = ""
                    badge = ""
                    if e.trade_spec is not None:
                        legs_str = " | ".join(e.trade_spec.leg_codes[:2])
                        if len(e.trade_spec.leg_codes) > 2:
                            legs_str += " ..."
                        exit_str = e.trade_spec.exit_summary
                        badge = e.trade_spec.strategy_badge
                    rows.append({
                        "#": e.rank,
                        "Ticker": e.ticker,
                        "Badge": badge or "—",
                        "Verdict": e.verdict,
                        "Score": f"{e.composite_score:.2f}",
                        "Legs": legs_str or "—",
                        "Exit": exit_str or "—",
                    })
                print()
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

            print(f"\n  {_styled(result.summary, 'dim')}")

            # Debug: show commentary for top 3 trades
            if debug and trades_to_show:
                print(f"\n  {_styled('Debug Commentary:', 'bold')}")
                for e in trades_to_show[:3]:
                    if e.commentary:
                        print(f"\n    {_styled(f'#{e.rank} {e.ticker} {e.strategy_type}', 'bold')}")
                        for line in e.commentary:
                            print(f"      {line}")
                if result.commentary:
                    print(f"\n    {_styled('Overall:', 'bold')}")
                    for line in result.commentary:
                        print(f"      {line}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_plan(self, arg: str) -> None:
        """Generate daily trading plan.\nUsage: plan [TICKER ...] [--date YYYY-MM-DD]"""
        parts = arg.strip().split()
        tickers: list[str] = []
        plan_date = None

        i = 0
        while i < len(parts):
            if parts[i] == "--date" and i + 1 < len(parts):
                try:
                    plan_date = date.fromisoformat(parts[i + 1])
                except ValueError:
                    print(f"Invalid date: {parts[i + 1]}")
                    return
                i += 2
            else:
                tickers.append(parts[i].upper())
                i += 1

        try:
            ma = self._get_ma()
            if not ma.quotes.has_broker:
                print(_styled(
                    "WARNING: No broker connected — fill prices unavailable. "
                    "Plan uses historical data only (no live quotes/Greeks).\n"
                    "For full data: analyzer-cli --broker\n", "yellow",
                ))
            plan = ma.plan.generate(
                tickers=tickers or None,
                plan_date=plan_date,
            )

            # Header
            day_str = plan.plan_for_date.strftime("%a %b %d, %Y")
            source = ma.quotes.source
            _print_header(f"Daily Trading Plan — {day_str}  [data: {source}]")

            # Day verdict
            verdict_color = {
                "trade": "green", "trade_light": "yellow",
                "avoid": "red", "no_trade": "red",
            }
            vc = verdict_color.get(plan.day_verdict, "")
            print(f"\n  Day: {_styled(plan.day_verdict.value.upper().replace('_', ' '), vc)}")
            if plan.day_verdict_reasons:
                for r in plan.day_verdict_reasons:
                    print(f"       {_styled(r, 'dim')}")

            # Risk budget
            b = plan.risk_budget
            acct_label = (
                f"${b.account_size:,.0f} (broker)"
                if b.account_source == "broker"
                else f"${b.account_size:,.0f} (config default)"
            )
            print(f"  Account: {acct_label}")
            print(f"  Risk: max {b.max_new_positions} new positions | "
                  f"${b.max_daily_risk_dollars:,.0f} daily risk budget | "
                  f"sizing {b.position_size_factor:.0%}")

            # Expiry events
            if plan.expiry_events:
                labels = [f"{e.label} ({e.date})" for e in plan.expiry_events]
                print(f"  Expiry: {', '.join(labels)}")
            if plan.upcoming_expiries:
                future = [e for e in plan.upcoming_expiries if e.date > plan.plan_for_date]
                if future:
                    nxt = future[0]
                    print(f"  Next: {nxt.label} ({nxt.date})")

            if not plan.all_trades:
                print(f"\n  {_styled('No actionable trades.', 'dim')}")
            else:
                # Group by horizon
                from income_desk.models.trading_plan import PlanHorizon
                horizon_labels = {
                    PlanHorizon.ZERO_DTE: "0DTE",
                    PlanHorizon.WEEKLY: "Weekly",
                    PlanHorizon.MONTHLY: "Monthly",
                    PlanHorizon.LEAP: "LEAP",
                }
                for h in PlanHorizon:
                    trades = plan.trades_by_horizon.get(h, [])
                    if not trades:
                        continue
                    print(f"\n  {_styled(f'--- {horizon_labels[h]} ({len(trades)} trades) ---', 'bold')}")
                    for t in trades:
                        v_color = {"go": "green", "caution": "yellow"}.get(t.verdict, "")
                        v_text = _styled(t.verdict.value.upper(), v_color)

                        legs_str = ""
                        exit_str = ""
                        st_type = None
                        side = None
                        if t.trade_spec is not None:
                            legs_str = " | ".join(t.trade_spec.leg_codes)
                            exit_str = t.trade_spec.exit_summary
                            st_type = t.trade_spec.structure_type
                            side = t.trade_spec.order_side

                        badge = ""
                        if t.trade_spec is not None:
                            badge = t.trade_spec.strategy_badge
                        tag = _profile_tag(st_type, side, t.direction)
                        badge_str = f"  [{badge}]" if badge else ""
                        print(f"  #{t.rank} {_styled(t.ticker, 'bold')}  {t.strategy_type}  "
                              f"{v_text}  {t.composite_score:.2f}{badge_str}")
                        if tag:
                            print(f"     {tag}")
                        if legs_str:
                            print(f"     {legs_str}")
                        # Max profit / max loss
                        if t.trade_spec:
                            mp = t.trade_spec.max_profit_desc or ""
                            ml = t.trade_spec.max_loss_desc or ""
                            if mp or ml:
                                print(f"     Max profit: {mp} | Max loss: {ml}")
                            if exit_str:
                                print(f"     {exit_str}")
                        # Chase limit
                        if t.max_entry_price is not None:
                            print(f"     Chase limit: ${t.max_entry_price:.2f}")
                        # Expiry note
                        if t.expiry_note:
                            print(f"     {_styled(f'NOTE: {t.expiry_note}', 'yellow')}")

            print(f"\n  {_styled(plan.summary, 'dim')}")

            # Data warnings (broker failures, data gaps)
            if plan.data_warnings:
                print()
                for w in plan.data_warnings:
                    if w.startswith("Data source:"):
                        print(f"  {_styled(w, 'dim')}")
                    else:
                        print(f"  {_styled(f'⚠ {w}', 'yellow')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")
            if "--debug" in arg:
                traceback.print_exc()

    def do_regime(self, arg: str) -> None:
        """Detect regime for ticker(s).\nUsage: regime SPY GLD\n       regime --watchlist MA-Income"""
        tickers = self._resolve_tickers(arg)
        if not tickers:
            from income_desk.config import get_settings
            tickers = get_settings().display.default_tickers

        try:
            ma = self._get_ma()
            results = ma.regime.detect_batch(tickers=tickers)
            _print_header("Regime Detection")
            rows = []
            for t, r in results.items():
                rows.append({
                    "Ticker": t,
                    "Regime": f"R{r.regime}",
                    "Confidence": f"{r.confidence:.0%}",
                    "Direction": r.trend_direction or "",
                    "Date": str(r.as_of_date),
                })
            print()
            print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_technicals(self, arg: str) -> None:
        """Show technical snapshot.\nUsage: technicals SPY"""
        tickers = self._parse_tickers(arg)
        if not tickers:
            print("Usage: technicals TICKER")
            return

        try:
            ma = self._get_ma()
            ticker = tickers[0]
            t = ma.technicals.snapshot(ticker)

            _print_header(f"{ticker} — Technical Snapshot ({t.as_of_date})")
            print(f"\n  Price:       ${t.current_price:.2f}")
            print(f"  RSI:         {t.rsi.value:.1f} {'(OB)' if t.rsi.is_overbought else '(OS)' if t.rsi.is_oversold else ''}")
            print(f"  ATR:         ${t.atr:.2f} ({t.atr_pct:.2f}%)")
            print(f"  MACD:        {t.macd.histogram:+.4f} {'↑' if t.macd.is_bullish_crossover else '↓' if t.macd.is_bearish_crossover else ''}")

            ma_data = t.moving_averages
            print(f"\n  Moving Averages:")
            print(f"    SMA 20:    ${ma_data.sma_20:.2f} ({ma_data.price_vs_sma_20_pct:+.1f}%)")
            print(f"    SMA 50:    ${ma_data.sma_50:.2f} ({ma_data.price_vs_sma_50_pct:+.1f}%)")
            print(f"    SMA 200:   ${ma_data.sma_200:.2f} ({ma_data.price_vs_sma_200_pct:+.1f}%)")

            print(f"\n  Bollinger:   BW={t.bollinger.bandwidth:.4f}, %B={t.bollinger.percent_b:.2f}")
            print(f"  Stochastic:  K={t.stochastic.k:.0f}, D={t.stochastic.d:.0f}")
            print(f"  Phase:       {t.phase.phase.value} ({t.phase.confidence:.0%})")

            if t.signals:
                print(f"\n  Signals:")
                for s in t.signals[:5]:
                    print(f"    [{s.direction}] {s.name}: {s.description}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_levels(self, arg: str) -> None:
        """Show support/resistance levels.\nUsage: levels SPY"""
        tickers = self._parse_tickers(arg)
        if not tickers:
            print("Usage: levels TICKER")
            return

        try:
            ma = self._get_ma()
            ticker = tickers[0]
            result = ma.levels.analyze(ticker)
            _print_header(f"{ticker} — Levels Analysis ({result.as_of_date})")
            print(f"\n{result.summary}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_macro(self, arg: str) -> None:
        """Show macro economic calendar.\nUsage: macro"""
        try:
            ma = self._get_ma()
            cal = ma.macro.calendar()
            _print_header("Macro Calendar")

            if cal.next_event:
                print(f"\n  Next event:  {cal.next_event.name} ({cal.next_event.date}) — {cal.days_to_next}d")
            if cal.next_fomc:
                print(f"  Next FOMC:   {cal.next_fomc.date} — {cal.days_to_next_fomc}d")

            if cal.events_next_30_days:
                print(f"\n  Next 30 days:")
                rows = []
                for e in cal.events_next_30_days:
                    rows.append({
                        "Date": str(e.date),
                        "Event": e.name,
                        "Impact": e.impact,
                    })
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_macro_indicators(self, arg: str) -> None:
        """Macro economic indicators — bonds, credit, dollar, inflation.
        Usage: macro_indicators
        Fetches TNX (10Y yield), TLT (long bond), HYG (high yield), UUP (dollar), TIP (TIPS)"""
        try:
            ma = self._get_ma()
            ds = ma.data

            if ds is None:
                print("DataService required for macro indicators.")
                return

            _print_header("Macro Economic Indicators")

            from income_desk.macro_indicators import compute_macro_dashboard

            # Fetch macro tickers
            tickers = {
                "TNX": "TNX",
                "TLT": "TLT",
                "HYG": "HYG",
                "UUP": "UUP",
                "TIP": "TIP",
            }
            data: dict[str, object] = {}
            for name, ticker in tickers.items():
                try:
                    data[name] = ds.get_ohlcv(ticker)
                    print(f"  Fetched {name} ({ticker})")
                except Exception as e:
                    print(f"  {name} unavailable: {e}")
                    data[name] = None

            dashboard = compute_macro_dashboard(
                tnx_ohlcv=data.get("TNX"),
                tlt_ohlcv=data.get("TLT"),
                hyg_ohlcv=data.get("HYG"),
                uup_ohlcv=data.get("UUP"),
                tip_ohlcv=data.get("TIP"),
            )

            print()
            if dashboard.bond_market:
                b = dashboard.bond_market
                print("  Bond Market:")
                color = (
                    "red"
                    if b.tnx_trend == "rising"
                    else "green" if b.tnx_trend == "falling" else "yellow"
                )
                print(
                    f"    10Y Yield: {b.tnx_yield:.2f}%"
                    f" ({_styled(b.tnx_trend, color)}, {b.tnx_change_20d:+.0f}bp/20d)"
                )
                print(f"    TLT 20d:   {b.tlt_return_20d_pct:+.1f}% ({b.tlt_trend})")
                print(f"    {b.interpretation}")

            if dashboard.credit_spreads:
                c = dashboard.credit_spreads
                color = "red" if c.risk_level in ("elevated", "high") else "green"
                print(f"\n  Credit Spreads:")
                print(
                    f"    HYG/TLT:   {c.hyg_tlt_ratio:.3f}"
                    f" ({c.spread_trend}, {_styled(c.risk_level, color)})"
                )
                print(f"    Percentile: {c.ratio_percentile_60d:.0f}th (60d)")
                print(f"    {c.interpretation}")

            if dashboard.dollar_strength:
                d = dashboard.dollar_strength
                print(f"\n  Dollar Strength:")
                print(
                    f"    UUP 20d:   {d.uup_return_20d_pct:+.1f}% ({d.dollar_trend})"
                )
                print(f"    US impact: {d.impact_on_us}")
                print(f"    India:     {d.impact_on_india}")

            if dashboard.inflation_expectations:
                i = dashboard.inflation_expectations
                print(f"\n  Inflation Expectations:")
                print(f"    TIP/TLT:   {i.tip_tlt_ratio:.3f} ({i.inflation_trend})")
                print(f"    {i.interpretation}")

            color = {
                "low": "green",
                "moderate": "yellow",
                "elevated": "red",
                "high": "red",
            }[dashboard.overall_risk]
            print(
                f"\n  Overall Macro Risk: {_styled(dashboard.overall_risk.upper(), color)}"
            )
            print(f"  Trading Impact: {dashboard.trading_impact}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_stress(self, arg: str) -> None:
        """Show black swan / tail-risk alert.\nUsage: stress"""
        try:
            ma = self._get_ma()
            alert = ma.black_swan.alert()
            _print_header(f"Tail-Risk Alert ({alert.as_of_date})")

            level_color = {
                "normal": "green",
                "elevated": "yellow",
                "high": "yellow",
                "critical": "red",
            }
            color = level_color.get(alert.alert_level, "")
            print(f"\n  Alert:   {_styled(alert.alert_level.upper(), color)}")
            print(f"  Score:   {alert.composite_score:.2f}")
            print(f"  Action:  {alert.action}")

            if alert.indicators:
                print(f"\n  Indicators:")
                rows = []
                for ind in alert.indicators:
                    rows.append({
                        "Name": ind.name,
                        "Status": ind.status,
                        "Score": f"{ind.score:.2f}",
                        "Value": f"{ind.value:.2f}" if ind.value is not None else "N/A",
                    })
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

            if alert.triggered_breakers > 0:
                print(f"\n  {_styled(f'{alert.triggered_breakers} circuit breaker(s) triggered!', 'red')}")

            print(f"\n  {_styled(alert.summary, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_vol(self, arg: str) -> None:
        """Show volatility surface.\nUsage: vol SPY"""
        tickers = self._parse_tickers(arg)
        if not tickers:
            print("Usage: vol TICKER")
            return

        try:
            ma = self._get_ma()
            ticker = tickers[0]
            surf = ma.vol_surface.surface(ticker)

            _print_header(f"{ticker} — Volatility Surface ({surf.as_of_date})")
            print(f"\n  Underlying:  ${surf.underlying_price:.2f}")
            print(f"  Front IV:    {surf.front_iv:.1%}")
            print(f"  Back IV:     {surf.back_iv:.1%}")
            print(f"  Term Slope:  {surf.term_slope:+.1%} ({'contango' if surf.is_contango else 'backwardation'})")
            print(f"  Calendar Edge: {surf.calendar_edge_score:.2f}")
            print(f"  Data Quality:  {surf.data_quality}")

            if surf.term_structure:
                print(f"\n  Term Structure:")
                rows = []
                for pt in surf.term_structure:
                    rows.append({
                        "Expiry": str(pt.expiration),
                        "DTE": pt.days_to_expiry,
                        "ATM IV": f"{pt.atm_iv:.1%}",
                        "Strike": f"${pt.atm_strike:.0f}",
                    })
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

            if surf.skew_by_expiry:
                print(f"\n  Skew (front expiry):")
                sk = surf.skew_by_expiry[0]
                print(f"    ATM IV:     {sk.atm_iv:.1%}")
                print(f"    OTM Put IV: {sk.otm_put_iv:.1%} (skew: +{sk.put_skew:.1%})")
                print(f"    OTM Call IV:{sk.otm_call_iv:.1%} (skew: +{sk.call_skew:.1%})")
                print(f"    Skew Ratio: {sk.skew_ratio:.1f}")

            if surf.best_calendar_expiries:
                f, b = surf.best_calendar_expiries
                print(f"\n  Best Calendar: sell {f} / buy {b} (diff: {surf.iv_differential_pct:+.1f}%)")

            print(f"\n  {_styled(surf.summary, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_setup(self, arg: str) -> None:
        """Assess price-based setups (breakout, momentum, mean_reversion, orb).\nUsage: setup SPY [type]\n  Types: breakout, momentum, mr (mean_reversion), orb, all (default)\n  Note: ORB requires intraday data; shows NO_GO without it."""
        parts = arg.strip().split()
        if not parts:
            print("Usage: setup TICKER [type]")
            print("  Types: breakout, momentum, mr (mean_reversion), orb, all (default)")
            return

        ticker = parts[0].upper()
        setup_type = parts[1].lower() if len(parts) > 1 else "all"

        type_map = {
            "breakout": ["breakout"],
            "momentum": ["momentum"],
            "mr": ["mean_reversion"],
            "mean_reversion": ["mean_reversion"],
            "orb": ["orb"],
            "all": ["breakout", "momentum", "mean_reversion", "orb"],
        }
        setups = type_map.get(setup_type)
        if setups is None:
            print(f"Unknown setup: '{setup_type}'. Use: breakout, momentum, mr, orb, all")
            return

        try:
            ma = self._get_ma()
            _print_header(f"{ticker} — Setup Assessment")

            for s in setups:
                try:
                    if s == "breakout":
                        result = ma.opportunity.assess_breakout(ticker)
                    elif s == "momentum":
                        result = ma.opportunity.assess_momentum(ticker)
                    elif s == "mean_reversion":
                        result = ma.opportunity.assess_mean_reversion(ticker)
                    elif s == "orb":
                        from income_desk.opportunity.setups.orb import assess_orb as _orb_assess
                        regime = ma.regime.detect(ticker)
                        technicals = ma.technicals.snapshot(ticker)
                        try:
                            orb_data = ma.technicals.orb(ticker, daily_atr=technicals.atr)
                        except Exception:
                            orb_data = None
                        result = _orb_assess(ticker, regime, technicals, orb=orb_data)
                    else:
                        continue

                    verdict_color = {"go": "green", "caution": "yellow", "no_go": "red"}
                    v = result.verdict if isinstance(result.verdict, str) else result.verdict.value
                    v_color = verdict_color.get(v, "")
                    v_text = _styled(v.upper(), v_color)

                    name = s.replace("_", " ").title()
                    conf = result.confidence if hasattr(result, "confidence") else 0
                    print(f"\n  {_styled(name, 'bold')}: {v_text} ({conf:.0%})")

                    if hasattr(result, "hard_stops") and result.hard_stops:
                        for hs in result.hard_stops[:2]:
                            print(f"    {_styled('STOP:', 'red')} {hs.description}")

                    if hasattr(result, "direction") and result.direction != "neutral":
                        print(f"    Direction: {result.direction.title()}")
                    if hasattr(result, "strategy") and isinstance(result.strategy, str):
                        print(f"    Strategy:  {result.strategy.replace('_', ' ').title()}")

                    # ORB-specific fields
                    if hasattr(result, "orb_status") and result.orb_status != "none":
                        print(f"    ORB Status: {result.orb_status}")
                        print(f"    Range:     {result.range_pct:.2f}%")
                        if result.range_vs_daily_atr_pct is not None:
                            print(f"    Range/ATR: {result.range_vs_daily_atr_pct:.0f}%")

                    if hasattr(result, "signals"):
                        for sig in result.signals[:3]:
                            icon = _styled("+", "green") if sig.favorable else _styled("-", "red")
                            desc = sig.description if isinstance(sig.description, str) else str(sig.description)
                            print(f"    {icon} {desc[:70]}")

                    # Trade spec (actionable parameters)
                    if hasattr(result, "trade_spec") and result.trade_spec is not None:
                        ts = result.trade_spec
                        direction = getattr(result, "direction", None)
                        if direction is None and hasattr(result, "strategy") and hasattr(result.strategy, "direction"):
                            direction = result.strategy.direction
                        if ts.structure_type:
                            tag = _profile_tag(ts.structure_type, ts.order_side, direction)
                            print(f"    {_styled(ts.strategy_badge, 'bold')}  {tag}")
                        print(f"    Legs:")
                        for code in ts.leg_codes:
                            print(f"      {code}")
                        if ts.exit_summary:
                            print(f"    Exit:      {ts.exit_summary}")

                    print(f"    {_styled(result.summary, 'dim')}")

                except Exception as exc:
                    print(f"\n  {s.replace('_', ' ').title()}: {_styled(str(exc), 'red')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_opportunity(self, arg: str) -> None:
        """Assess option play opportunities.\nUsage: opportunity SPY [play]\n  Plays: ic, ifly, calendar, diagonal, ratio, zero_dte, leap, earnings, all\n  Default: all"""
        parts = arg.strip().split()
        if not parts:
            print("Usage: opportunity TICKER [play]")
            print("  Plays: ic (iron condor), ifly (iron butterfly), calendar, diagonal,")
            print("         ratio (ratio spread), zero_dte, leap, earnings, all (default)")
            return

        ticker = parts[0].upper()
        play = parts[1].lower() if len(parts) > 1 else "all"

        ma = self._get_ma()
        if not ma.quotes.has_broker:
            print(_styled(
                "WARNING: No broker — option plays assessed without live pricing.\n", "yellow",
            ))

        play_map = {
            "ic": ["iron_condor"],
            "iron_condor": ["iron_condor"],
            "ifly": ["iron_butterfly"],
            "iron_butterfly": ["iron_butterfly"],
            "calendar": ["calendar"],
            "cal": ["calendar"],
            "diagonal": ["diagonal"],
            "diag": ["diagonal"],
            "ratio": ["ratio_spread"],
            "ratio_spread": ["ratio_spread"],
            "zero_dte": ["zero_dte"],
            "0dte": ["zero_dte"],
            "leap": ["leap"],
            "earnings": ["earnings"],
            "all": ["iron_condor", "iron_butterfly", "calendar", "diagonal", "ratio_spread", "earnings"],
        }
        plays = play_map.get(play)
        if plays is None:
            print(f"Unknown play: '{play}'. Use: ic, ifly, calendar, diagonal, ratio, zero_dte, leap, earnings, all")
            return

        try:
            ma = self._get_ma()
            _print_header(f"{ticker} — Option Play Assessment")

            for p in plays:
                try:
                    method = getattr(ma.opportunity, f"assess_{p}")
                    result = method(ticker)

                    verdict_color = {"go": "green", "caution": "yellow", "no_go": "red"}
                    v_color = verdict_color.get(result.verdict.value, "")
                    v_text = _styled(result.verdict.value.upper(), v_color)

                    name = p.replace("_", " ").title()
                    print(f"\n  {_styled(name, 'bold')}: {v_text} ({result.confidence:.0%})")

                    if result.hard_stops:
                        for hs in result.hard_stops[:2]:
                            print(f"    {_styled('STOP:', 'red')} {hs.description}")

                    if hasattr(result, "strategy") and result.verdict != "no_go":
                        print(f"    Strategy:  {result.strategy.name}")
                        print(f"    Structure: {result.strategy.structure[:80]}")
                        if result.strategy.risk_notes:
                            print(f"    Risk:      {result.strategy.risk_notes[0]}")

                    # Iron condor specific
                    if hasattr(result, "wing_width_suggestion") and result.verdict != "no_go":
                        print(f"    Wings:     {result.wing_width_suggestion}")

                    # ORB decision (0DTE with ORB data)
                    if hasattr(result, "orb_decision") and result.orb_decision is not None:
                        od = result.orb_decision
                        print(f"    {_styled('ORB:', 'bold')}  {od.status} | {od.direction} | "
                              f"Range {od.range_low:.2f}–{od.range_high:.2f} ({od.range_pct:.1f}%)")
                        print(f"    ORB Decision: {od.decision[:100]}")
                        # Show key levels
                        level_strs = []
                        for k, v in od.key_levels.items():
                            if k not in ("range_high", "range_low"):
                                level_strs.append(f"{k}={v:.2f}")
                        if level_strs:
                            print(f"    ORB Levels: {', '.join(level_strs[:6])}")

                    # Trade spec (actionable parameters)
                    if hasattr(result, "trade_spec") and result.trade_spec is not None:
                        ts = result.trade_spec
                        direction = getattr(result, "direction", None)
                        if direction is None and hasattr(result, "strategy") and hasattr(result.strategy, "direction"):
                            direction = result.strategy.direction
                        if ts.structure_type:
                            tag = _profile_tag(ts.structure_type, ts.order_side, direction)
                            print(f"    {_styled(ts.strategy_badge, 'bold')}  {tag}")
                        print(f"    Expiry:    {ts.target_expiration} ({ts.target_dte}d)")
                        if ts.front_expiration and ts.back_expiration:
                            print(f"    Front:     {ts.front_expiration} ({ts.front_dte}d, IV {ts.iv_at_front:.1%})")
                            print(f"    Back:      {ts.back_expiration} ({ts.back_dte}d, IV {ts.iv_at_back:.1%})")
                        if ts.wing_width_points:
                            print(f"    Wing Width: ${ts.wing_width_points:.0f}")
                        print(f"    Legs:")
                        for code in ts.leg_codes:
                            print(f"      {code}")
                        # Exit guidance
                        if ts.exit_summary:
                            print(f"    Exit:      {ts.exit_summary}")
                        if ts.exit_notes:
                            for note in ts.exit_notes[:3]:
                                print(f"      - {note}")

                        # Entry window
                        if ts.entry_window_start is not None:
                            end_str = ts.entry_window_end.strftime("%H:%M") if ts.entry_window_end else "close"
                            print(f"    Entry window: {ts.entry_window_start.strftime('%H:%M')} - {end_str}")

                        # Trade lifecycle analytics on the trade_spec
                        self._show_trade_analytics(ts, ticker)

                    # Ratio spread specific
                    if hasattr(result, "margin_warning") and result.margin_warning:
                        print(f"    {_styled('MARGIN:', 'yellow')} {result.margin_warning}")

                except Exception as exc:
                    print(f"\n  {p.replace('_', ' ').title()}: {_styled(str(exc), 'red')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def _show_trade_analytics(self, ts, ticker: str) -> None:
        """Show trade lifecycle analytics (yield, POP, breakevens, entry check) for a TradeSpec."""
        try:
            ma = self._get_ma()
            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)

            # Yield (credit trades only)
            if ts.order_side == "credit" and ts.max_entry_price:
                yi = compute_income_yield(ts, ts.max_entry_price)
                if yi:
                    print(f"    {_styled('Yield:', 'bold')} credit/width {yi.credit_to_width_pct:.1%} | "
                          f"ROC {yi.return_on_capital_pct:.1%} | "
                          f"annualized {yi.annualized_roc_pct:.1%}")
                    print(f"           max profit ${yi.max_profit:.0f} | max loss ${yi.max_loss:.0f}")

            # Breakevens
            if ts.max_entry_price:
                be = compute_breakevens(ts, ts.max_entry_price)
                parts = []
                if be.low is not None:
                    parts.append(f"low ${be.low:.2f}")
                if be.high is not None:
                    parts.append(f"high ${be.high:.2f}")
                if parts:
                    print(f"    {_styled('Breakevens:', 'bold')} {' | '.join(parts)}")

            # POP
            if ts.max_entry_price:
                pop = estimate_pop(
                    ts, ts.max_entry_price, regime.regime,
                    tech.atr_pct, tech.current_price,
                )
                if pop:
                    ev_color = "green" if pop.expected_value > 0 else "red"
                    print(f"    {_styled('POP:', 'bold')} {pop.pop_pct:.0%} | "
                          f"EV {_styled(f'${pop.expected_value:+.0f}', ev_color)} | "
                          f"{pop.notes}")

            # Income entry check (credit trades)
            if ts.order_side == "credit":
                metrics = None
                try:
                    metrics = ma.quotes.get_metrics(ticker)
                except Exception:
                    pass
                entry_check = check_income_entry(
                    iv_rank=metrics.iv_rank if metrics else None,
                    iv_percentile=metrics.iv_percentile if metrics else None,
                    dte=ts.target_dte or 30,
                    rsi=tech.rsi.value,
                    atr_pct=tech.atr_pct,
                    regime_id=regime.regime,
                )
                status = _styled("CONFIRMED", "green") if entry_check.confirmed else _styled("NOT CONFIRMED", "red")
                print(f"    {_styled('Entry:', 'bold')} {status} (score {entry_check.score:.0%})")
                failed = [c["name"] for c in entry_check.conditions if not c["passed"]]
                if failed:
                    print(f"           failed: {', '.join(failed)}")

            # Strike alignment to S/R levels
            try:
                levels = ma.levels.analyze(ticker)
                aligned = align_strikes_to_levels(ts, levels)
                if aligned:
                    for a in aligned:
                        if a.improved:
                            print(f"    {_styled('S/R align:', 'bold')} "
                                  f"${a.original_strike:.0f} -> ${a.aligned_strike:.0f} "
                                  f"({a.level_source} @ ${a.level_price:.2f})")
            except Exception:
                pass

            # Position sizing for common account sizes
            sizes = []
            for acct in [30000, 50000, 200000]:
                c = ts.position_size(capital=acct)
                sizes.append(f"${acct // 1000}K:{c}ct")
            print(f"    {_styled('Size:', 'bold')} {' | '.join(sizes)}")

        except Exception as exc:
            print(f"    {_styled('Analytics error:', 'red')} {exc}")

    def do_yield(self, arg: str) -> None:
        """Compute income yield for a credit trade.\nUsage: yield TICKER CREDIT [WING_WIDTH] [DTE]\n  Example: yield GLD 0.72 5 35"""
        parts = arg.strip().split()
        if len(parts) < 2:
            print("Usage: yield TICKER CREDIT [WING_WIDTH] [DTE]")
            print("  CREDIT: net credit received per spread")
            print("  WING_WIDTH: distance between short and long strikes (default: 5)")
            print("  DTE: days to expiration (default: 30)")
            return

        ticker = parts[0].upper()
        try:
            credit = float(parts[1])
            wing = float(parts[2]) if len(parts) > 2 else 5.0
            dte = int(parts[3]) if len(parts) > 3 else 30
        except ValueError:
            print("Invalid numbers. Usage: yield TICKER CREDIT [WING_WIDTH] [DTE]")
            return

        try:
            from income_desk.models.opportunity import (
                LegAction, LegSpec, OrderSide, StructureType, TradeSpec,
            )
            from datetime import timedelta

            # Build a minimal IC TradeSpec for the computation
            ma = self._get_ma()
            tech = ma.technicals.snapshot(ticker)
            price = tech.current_price
            exp = date.today() + timedelta(days=dte)

            short_put = price - wing
            long_put = short_put - wing
            short_call = price + wing
            long_call = short_call + wing

            def _leg(action, otype, strike):
                return LegSpec(
                    role=f"{'short' if action == LegAction.SELL_TO_OPEN else 'long'}_{otype}",
                    action=action, option_type=otype, strike=strike,
                    strike_label=f"{strike:.0f} {otype}",
                    expiration=exp, days_to_expiry=dte,
                )

            ts = TradeSpec(
                ticker=ticker,
                legs=[
                    _leg(LegAction.SELL_TO_OPEN, "put", short_put),
                    _leg(LegAction.BUY_TO_OPEN, "put", long_put),
                    _leg(LegAction.SELL_TO_OPEN, "call", short_call),
                    _leg(LegAction.BUY_TO_OPEN, "call", long_call),
                ],
                underlying_price=price, target_dte=dte, target_expiration=exp,
                wing_width_points=wing,
                structure_type=StructureType.IRON_CONDOR,
                order_side=OrderSide.CREDIT,
            )

            yi = compute_income_yield(ts, credit)
            if yi is None:
                print("Cannot compute yield (not a credit trade or missing wing width)")
                return

            _print_header(f"{ticker} — Income Yield (${credit:.2f} credit, ${wing:.0f} wings, {dte}d)")
            print(f"\n  Credit/Width:    {yi.credit_to_width_pct:.1%}")
            print(f"  ROC:             {yi.return_on_capital_pct:.1%}")
            print(f"  Annualized ROC:  {yi.annualized_roc_pct:.1%}")
            print(f"  Max Profit:      ${yi.max_profit:.0f}")
            print(f"  Max Loss:        ${yi.max_loss:.0f}")
            if yi.breakeven_low:
                print(f"  Breakeven Low:   ${yi.breakeven_low:.2f}")
            if yi.breakeven_high:
                print(f"  Breakeven High:  ${yi.breakeven_high:.2f}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_pop(self, arg: str) -> None:
        """Estimate probability of profit for a ticker/structure.\nUsage: pop TICKER [ENTRY_PRICE] [STRUCTURE]\n  Example: pop GLD 0.72 iron_condor"""
        parts = arg.strip().split()
        if not parts:
            print("Usage: pop TICKER [ENTRY_PRICE] [STRUCTURE]")
            print("  ENTRY_PRICE: net credit/debit (default: uses representative IC)")
            print("  STRUCTURE: iron_condor, credit_spread, etc.")
            return

        ticker = parts[0].upper()
        entry_price = float(parts[1]) if len(parts) > 1 else 0.50
        structure = parts[2] if len(parts) > 2 else "iron_condor"

        try:
            ma = self._get_ma()
            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)

            from income_desk.models.opportunity import (
                LegAction, LegSpec, OrderSide, StructureType, TradeSpec,
            )
            from datetime import timedelta
            from income_desk.opportunity.option_plays._trade_spec_helpers import compute_otm_strike, snap_strike

            price = tech.current_price
            atr = tech.atr
            dte = 35
            exp = date.today() + timedelta(days=dte)
            wing = snap_strike(atr * 0.5, price) or 5.0

            short_put = compute_otm_strike(price, atr, 1.0, "put", price)
            short_call = compute_otm_strike(price, atr, 1.0, "call", price)

            def _leg(action, otype, strike):
                return LegSpec(
                    role=f"{'short' if action == LegAction.SELL_TO_OPEN else 'long'}_{otype}",
                    action=action, option_type=otype, strike=strike,
                    strike_label=f"{strike:.0f} {otype}",
                    expiration=exp, days_to_expiry=dte,
                )

            ts = TradeSpec(
                ticker=ticker,
                legs=[
                    _leg(LegAction.SELL_TO_OPEN, "put", short_put),
                    _leg(LegAction.BUY_TO_OPEN, "put", short_put - wing),
                    _leg(LegAction.SELL_TO_OPEN, "call", short_call),
                    _leg(LegAction.BUY_TO_OPEN, "call", short_call + wing),
                ],
                underlying_price=price, target_dte=dte, target_expiration=exp,
                wing_width_points=wing,
                structure_type=StructureType(structure),
                order_side=OrderSide.CREDIT,
            )

            pop = estimate_pop(ts, entry_price, regime.regime, tech.atr_pct, price)
            if pop is None:
                print("Cannot estimate POP for this structure.")
                return

            _print_header(f"{ticker} — POP Estimate (R{regime.regime}, {structure})")
            ev_color = "green" if pop.expected_value > 0 else "red"
            print(f"\n  POP:      {pop.pop_pct:.0%}")
            print(f"  EV:       {_styled(f'${pop.expected_value:+.0f}', ev_color)}")
            print(f"  Method:   {pop.method}")
            print(f"  Regime:   R{pop.regime_id}")
            print(f"  {_styled(pop.notes, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_income_entry(self, arg: str) -> None:
        """Check income entry conditions for a ticker.\nUsage: income_entry TICKER [DTE]\n  Example: income_entry GLD 35"""
        parts = arg.strip().split()
        if not parts:
            print("Usage: income_entry TICKER [DTE]")
            return

        ticker = parts[0].upper()
        dte = int(parts[1]) if len(parts) > 1 else 35

        try:
            ma = self._get_ma()
            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)

            metrics = None
            try:
                metrics = ma.quotes.get_metrics(ticker)
            except Exception:
                pass

            result = check_income_entry(
                iv_rank=metrics.iv_rank if metrics else None,
                iv_percentile=metrics.iv_percentile if metrics else None,
                dte=dte,
                rsi=tech.rsi.value,
                atr_pct=tech.atr_pct,
                regime_id=regime.regime,
            )

            _print_header(f"{ticker} — Income Entry Check ({dte} DTE)")
            status = _styled("CONFIRMED", "green") if result.confirmed else _styled("NOT CONFIRMED", "red")
            print(f"\n  Status:  {status}")
            print(f"  Score:   {result.score:.0%}")

            print(f"\n  Conditions:")
            for c in result.conditions:
                icon = _styled("+", "green") if c["passed"] else _styled("-", "red")
                val = c["value"] if c["value"] is not None else "N/A"
                print(f"    {icon} {c['name']}: {val} (threshold: {c['threshold']}, weight: {c['weight']})")

            print(f"\n  {_styled(result.summary, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_validate(self, arg: str) -> None:
        """Run profitability validation using live broker data.

        Usage:
            validate TICKER [--suite daily|adversarial|full]
            validate SPY
            validate SPY --suite adversarial
            validate SPY --suite full

        Suites:
            daily       7-check pre-trade validation (default)
                        commission_drag, fill_quality, margin_efficiency,
                        pop_gate, ev_positive, entry_quality, exit_discipline
            adversarial Stress tests: gamma_stress, vega_shock, breakeven_spread
            full        Both suites combined (10 checks)

        Data sources:
            Regime, ATR, RSI      — yfinance OHLCV (always available)
            Vol surface, spread   — yfinance options chain (always available)
            TradeSpec strikes     — assess_iron_condor() with real vol + levels
            Entry credit          — DXLink real mid prices (broker required)
                                    Falls back to IV-based estimate if no broker.
            IV rank               — TastyTrade REST API (broker required)

        Output is MCP-consumable: structured PASS/WARN/FAIL per check.
        Run pre-market before trading.
        """
        from income_desk.models.opportunity import LegAction, Verdict
        from income_desk.opportunity.option_plays.iron_condor import assess_iron_condor
        from income_desk.validation import run_adversarial_checks, run_daily_checks
        from income_desk.validation.models import Severity

        # ── Argument parsing ──────────────────────────────────────────────────
        parts = arg.strip().split()
        if not parts or parts[0].startswith("-"):
            print("Usage: validate TICKER [--suite daily|adversarial|full]")
            return

        ticker = parts[0].upper()
        suite_arg = "daily"
        for i, p in enumerate(parts[1:], 1):
            if p == "--suite" and i + 1 < len(parts):
                suite_arg = parts[i + 1]

        if suite_arg not in ("daily", "adversarial", "full"):
            print(f"Unknown suite '{suite_arg}'. Use: daily, adversarial, full")
            return

        try:
            ma = self._get_ma()

            if not getattr(ma, 'market_data', None):
                print(_styled(
                    "  *** ESTIMATED DATA — No broker connected. Credits, POP, and sizing are approximate. ***\n"
                    "  *** Connect broker (--broker) for real DXLink quotes and accurate analysis.         ***",
                    "yellow",
                ))

            # ── Step 1: Fetch real market data ────────────────────────────────
            regime = ma.regime.detect(ticker)
            tech   = ma.technicals.snapshot(ticker)
            vol    = ma.vol_surface.compute(ticker)   # VolatilitySurface | None

            regime_id     = int(regime.regime)
            current_price = tech.current_price
            atr_pct       = tech.atr_pct
            rsi           = tech.rsi.value
            avg_spread_pct = vol.avg_bid_ask_spread_pct if vol else 2.0

            # IV rank from broker metrics (None if not connected)
            metrics  = ma.quotes.get_metrics(ticker) if ma.quotes else None
            iv_rank  = metrics.iv_rank if metrics else None

            _print_header(f"VALIDATION — {ticker} — {suite_arg.upper()} SUITE")

            # ── Step 2: Run assessor → real TradeSpec ─────────────────────────
            ic_result = assess_iron_condor(ticker, regime, tech, vol)

            if ic_result.verdict == Verdict.NO_GO:
                stop_msg = ic_result.hard_stops[0].description if ic_result.hard_stops else "hard stop"
                print(f"  {_styled('✗ FAIL', 'red')}  {'assessor_gate':<22s}  {stop_msg}")
                print()
                print(f"  {_styled('NOT READY', 'red')}  (hard stopped — no trade possible in current regime)")
                print(f"  Regime: R{regime_id} | ATR: {atr_pct:.2f}% | RSI: {rsi:.0f}")
                return

            spec = ic_result.trade_spec
            if spec is None:
                print(f"  {_styled('ERROR:', 'red')} Assessor returned GO but no TradeSpec")
                return

            # ── Step 3: Get real entry credit from DXLink ─────────────────────
            entry_credit: float | None = None
            credit_source = "none"

            if ma.quotes and ma.quotes.has_broker:
                try:
                    leg_quotes = ma.quotes.get_leg_quotes(spec.legs)
                    if leg_quotes and len(leg_quotes) == len(spec.legs):
                        entry_credit = sum(
                            q.mid * (1 if leg.action == LegAction.SELL_TO_OPEN else -1)
                            for leg, q in zip(spec.legs, leg_quotes)
                            if q is not None and q.mid is not None
                        )
                        credit_source = f"DXLink ({ma.quotes.source})"
                except Exception:
                    pass  # fall through to estimate

            if entry_credit is None or entry_credit <= 0:
                # Fallback: estimate from IV — approximate IC credit per spread.
                # Heuristic: wing_width × front_iv × 0.40 captures ~20-30% of the
                # wing width as credit at typical IV levels. This is tighter than the
                # old `front_iv × price × 0.05` which overestimates on high-priced tickers.
                # Example: 5-wide GLD ($426, IV 28.6%): 5 × 0.286 × 0.40 = $0.57/share
                # (realistic range for a 5-wide IC is $0.60–$1.80)
                front_iv = vol.front_iv if vol else 0.20
                wing_pts = spec.wing_width_points if spec.wing_width_points else 5.0
                entry_credit = round(wing_pts * front_iv * 0.40, 2)
                # Floor at $0.05/share so we never feed zero into stress checks
                entry_credit = max(entry_credit, 0.05)
                credit_source = "IV estimate (no broker quotes)"
                print(f"  {_styled('⚠ WARN', 'yellow')}  {'broker_quotes':<22s}  "
                      f"No live quotes — using credit estimate ${entry_credit:.2f} ({credit_source})")

            # ── Step 4: Run validation with real data ─────────────────────────
            reports = []

            if suite_arg in ("daily", "full"):
                report = run_daily_checks(
                    ticker=ticker,
                    trade_spec=spec,
                    entry_credit=entry_credit,
                    regime_id=regime_id,
                    atr_pct=atr_pct,
                    current_price=current_price,
                    avg_bid_ask_spread_pct=avg_spread_pct,
                    dte=spec.target_dte,
                    rsi=rsi,
                    iv_rank=iv_rank,
                    iv_percentile=metrics.iv_percentile if metrics else None,
                )
                reports.append(report)

            if suite_arg in ("adversarial", "full"):
                report_adv = run_adversarial_checks(
                    ticker=ticker,
                    trade_spec=spec,
                    entry_credit=entry_credit,
                    atr_pct=atr_pct,
                )
                reports.append(report_adv)

            # ── Step 5: Display results ────────────────────────────────────────
            for report in reports:
                if len(reports) > 1:
                    print(f"\n  [{report.suite.upper()}]")
                for check in report.checks:
                    icon  = "✓" if check.severity == Severity.PASS else (
                            "⚠" if check.severity == Severity.WARN else "✗")
                    color = "green" if check.severity == Severity.PASS else (
                            "yellow" if check.severity == Severity.WARN else "red")
                    label = _styled(f"{icon} {check.severity.upper():4s}", color)
                    print(f"  {label}  {check.name:<22s}  {check.message}")

            print()
            all_checks = [c for r in reports for c in r.checks]
            passed   = sum(1 for c in all_checks if c.severity == Severity.PASS)
            warnings = sum(1 for c in all_checks if c.severity == Severity.WARN)
            failures = sum(1 for c in all_checks if c.severity == Severity.FAIL)
            is_ready = failures == 0

            status_text  = "READY TO TRADE" if is_ready else "NOT READY"
            status_color = "green" if is_ready else "red"
            print("  " + "─" * 60)
            print(f"  {_styled(status_text, status_color)}  "
                  f"({passed}/{len(all_checks)} passed, {warnings} warnings, {failures} failures)")
            print(f"  Regime: R{regime_id} ({regime.confidence:.0%}) | "
                  f"ATR: {atr_pct:.2f}% | RSI: {rsi:.0f} | "
                  f"IV Rank: {f'{iv_rank:.0f}' if iv_rank else 'N/A'} | "
                  f"Credit: ${entry_credit:.2f} [{credit_source}]")

            # ── Trust score ────────────────────────────────────────────────────
            from income_desk.features.data_trust import compute_trust_report
            has_broker_conn = bool(ma.quotes and ma.quotes.has_broker)
            _credit_src = (
                "broker" if has_broker_conn and credit_source.startswith("DXLink")
                else ("estimated" if entry_credit is not None else "none")
            )
            trust = compute_trust_report(
                has_broker=has_broker_conn,
                has_iv_rank=iv_rank is not None,
                has_vol_surface=vol is not None,
                has_levels=False,  # levels computed lazily in playbook below
                entry_credit_source=_credit_src,
                regime_confidence=regime.confidence,
                has_entry_credit=entry_credit is not None,
            )
            trust_color = "green" if trust.overall_trust >= 0.80 else (
                "yellow" if trust.overall_trust >= 0.50 else "red"
            )
            print(f"  {_styled(f'TRUST: {trust.overall_trust:.0%} {trust.overall_level.upper()}', trust_color)}")
            print(f"    Data:    {trust.data_quality.trust_score:.0%} {trust.data_quality.trust_level.upper()}"
                  f" ({trust.data_quality.primary_source.value})")
            print(f"    Context: {trust.context_score:.0%} {trust.context_level.upper()}", end="")
            if trust.context_gaps:
                _critical_gaps = [g for g in trust.context_gaps if g.importance == "critical"]
                if _critical_gaps:
                    print(f" — MISSING: {', '.join(g.parameter for g in _critical_gaps)}", end="")
            print()
            print(f"    {trust.fit_for_summary}")
            if not has_broker_conn:
                print(f"    >> Connect broker (--broker --paper) for HIGH trust analysis.")

            # ── No-trade playbook ─────────────────────────────────────────────
            if not is_ready:
                print(f"\n  {_styled('NO TRADE PLAYBOOK:', 'yellow')}")
                # Suggest pullback alert levels
                try:
                    from income_desk.features.entry_levels import compute_pullback_levels
                    levels = ma.levels.analyze(ticker)
                    pullbacks = compute_pullback_levels(current_price, levels, atr=current_price * atr_pct / 100)
                    if pullbacks:
                        best = pullbacks[0]
                        print(f"    Set alert at ${best.alert_price:.0f} ({best.level_source}) — "
                              f"+{best.roc_improvement_pct:.1f}% ROC improvement at that level")
                    else:
                        print(f"    No nearby S/R pullback levels within 2 ATR — wait for IV expansion")
                except Exception:
                    pass  # Levels are optional — don't let this block the playbook
                print(f"    Re-check after 14:00 ET for intraday stabilization")
                if not (ma.quotes and ma.quotes.has_broker):
                    print(f"    Connect broker (--broker) for real quotes — estimated credits may be off by 2-3x")
                # Show failing check names for quick diagnosis
                fail_names = [c.name for c in all_checks if c.severity == Severity.FAIL]
                if fail_names:
                    print(f"    Blocking checks: {', '.join(fail_names)}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_entry_analysis(self, arg: str) -> None:
        """Analyze entry levels for a ticker: entry_analysis TICKER

        Runs full entry-level intelligence:
        1. Strike-to-S/R proximity check (are your short strikes backed?)
        2. Skew-optimal strike suggestion (where is IV richest?)
        3. Multi-factor entry score (enter now vs wait?)
        4. Limit order price (patient/normal/aggressive fill target)
        5. Pullback alert levels (where does the trade get better?)
        """
        ticker = arg.strip().upper() or "SPY"

        try:
            ma = self._get_ma()

            if not getattr(ma, 'market_data', None):
                print(_styled(
                    "  *** ESTIMATED DATA — No broker connected. Credits, POP, and sizing are approximate. ***\n"
                    "  *** Connect broker (--broker) for real DXLink quotes and accurate analysis.         ***",
                    "yellow",
                ))

            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)
            levels = ma.levels.analyze(ticker)
            vol = ma.vol_surface.compute(ticker)

            from income_desk.opportunity.option_plays.iron_condor import assess_iron_condor
            ic = assess_iron_condor(ticker, regime, tech, vol)

            if ic.trade_spec is None:
                print(f"No trade spec for {ticker} (verdict: {ic.verdict})")
                return

            from income_desk.features.entry_levels import (
                compute_strike_support_proximity,
                select_skew_optimal_strike,
                score_entry_level,
                compute_limit_entry_price,
                compute_pullback_levels,
            )

            atr = tech.atr
            price = tech.current_price

            # 1. Strike proximity
            proximity = compute_strike_support_proximity(ic.trade_spec, levels, atr=atr)
            print(f"\nENTRY ANALYSIS — {ticker} — {tech.as_of_date}")
            print("-" * 50)
            status = "PASS" if proximity.all_backed else "WARN"
            print(f"{status}  Strike Proximity   {proximity.summary}")

            # 2. Skew optimal
            if vol and vol.skew_by_expiry:
                skew = vol.skew_by_expiry[0]
                put_opt = select_skew_optimal_strike(price, atr, regime.regime.value, skew, "put")
                call_opt = select_skew_optimal_strike(price, atr, regime.regime.value, skew, "call")
                if put_opt.iv_advantage_pct >= 5:
                    print(f"UP    Skew Put          {put_opt.rationale}")
                else:
                    print(f"--    Skew Put          No meaningful skew advantage ({put_opt.iv_advantage_pct:.1f}%)")
                if call_opt.iv_advantage_pct >= 5:
                    print(f"UP    Skew Call         {call_opt.rationale}")
                else:
                    print(f"--    Skew Call         No meaningful skew advantage ({call_opt.iv_advantage_pct:.1f}%)")
            else:
                print(f"--    Skew              No vol surface data")

            # 3. Entry level score
            entry_score = score_entry_level(tech, levels, direction="neutral")
            action_label = entry_score.action.upper()
            print(f"{action_label:6s}Entry Score        {entry_score.overall_score:.0%} -> {entry_score.action} ({entry_score.rationale})")

            # 4. Limit price
            entry_credit = ic.trade_spec.max_entry_price
            if entry_credit is not None:
                spread = vol.avg_bid_ask_spread_pct / 100 * price / 100 if vol else 0.10
                urgency_map = {1: "patient", 2: "normal", 3: "aggressive", 4: "aggressive"}
                urgency = urgency_map.get(regime.regime.value, "normal")
                limit = compute_limit_entry_price(
                    current_mid=entry_credit, bid_ask_spread=spread, urgency=urgency,
                )
                print(f"$     Limit Price       {limit.rationale}")
            else:
                print(f"--    Limit Price       No entry price available (connect broker for real quotes)")

            # 5. Pullback levels
            pullbacks = compute_pullback_levels(price, levels, atr=atr)
            if pullbacks:
                print(f"\nPullback Alerts ({len(pullbacks)}):")
                for pb in pullbacks[:3]:
                    print(f"   -> Wait for {pb.alert_price:.0f} ({pb.level_source}) — +{pb.roc_improvement_pct:.1f}% ROC improvement")
            else:
                print(f"\n   No pullback levels within 2 ATR")

            print("-" * 50)

        except Exception as e:
            print(f"Error: {e}")

    def do_parse(self, arg: str) -> None:
        """Parse DXLink symbols into a TradeSpec.\nUsage: parse .GLD260417P455 .GLD260417P450 STO BTO [PRICE]\n  Symbols first, then actions (STO/BTO) in same order, optional price last."""
        parts = arg.strip().split()
        if len(parts) < 2:
            print("Usage: parse SYMBOL1 SYMBOL2 ... ACTION1 ACTION2 ... [PRICE]")
            print("  Example: parse .GLD260417P455 .GLD260417P450 STO BTO 0.72")
            print("  Symbols: DXLink format (.TICKER YYMMDD C/P STRIKE)")
            print("  Actions: STO (sell to open) or BTO (buy to open)")
            return

        # Separate symbols from actions
        symbols = []
        actions = []
        price = None
        for p in parts:
            if p.upper() in ("STO", "BTO"):
                actions.append(p.upper())
            elif p.startswith(".") or (len(p) > 6 and p[0].isalpha()):
                symbols.append(p)
            else:
                try:
                    price = float(p)
                except ValueError:
                    symbols.append(p)

        if len(symbols) != len(actions):
            print(f"Mismatch: {len(symbols)} symbols but {len(actions)} actions.")
            print("Provide one STO/BTO per symbol.")
            return

        try:
            # Parse individual symbols first
            _print_header("DXLink Symbol Parse")
            for sym in symbols:
                parsed = parse_dxlink_symbol(sym)
                print(f"  {sym} -> {parsed['ticker']} {parsed['expiration']} "
                      f"{parsed['option_type']} ${parsed['strike']:.0f}")

            # Get underlying price
            ma = self._get_ma()
            ticker = parse_dxlink_symbol(symbols[0])["ticker"]
            tech = ma.technicals.snapshot(ticker)

            ts = from_dxlink_symbols(
                symbols=symbols,
                actions=actions,
                underlying_price=tech.current_price,
                entry_price=price,
            )

            print(f"\n  {_styled('TradeSpec:', 'bold')}")
            print(f"    Ticker:     {ts.ticker}")
            print(f"    Structure:  {ts.structure_type}")
            print(f"    Badge:      {ts.strategy_badge}")
            print(f"    Side:       {ts.order_side}")
            print(f"    Price:      ${tech.current_price:.2f}")
            if ts.wing_width_points:
                print(f"    Wing Width: ${ts.wing_width_points:.0f}")
            print(f"    Legs:")
            for code in ts.leg_codes:
                print(f"      {code}")
            if ts.exit_summary:
                print(f"    Exit:       {ts.exit_summary}")

            # DXLink roundtrip
            dxl = to_dxlink_symbols(ts)
            print(f"    DXLink:     {' '.join(dxl)}")

            # Show analytics if we have a price
            if price:
                self._show_trade_analytics(ts, ticker)

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_monitor(self, arg: str) -> None:
        """Monitor exit conditions for an open position.\nUsage: monitor TICKER ENTRY_PRICE CURRENT_PRICE DTE [STRUCTURE]\n  Example: monitor GLD 0.72 0.35 25 iron_condor"""
        parts = arg.strip().split()
        if len(parts) < 4:
            print("Usage: monitor TICKER ENTRY_PRICE CURRENT_MID DTE [STRUCTURE]")
            print("  ENTRY_PRICE: original fill price")
            print("  CURRENT_MID: current mid price to close")
            print("  DTE: days to expiration remaining")
            print("  STRUCTURE: iron_condor (default), credit_spread, etc.")
            return

        ticker = parts[0].upper()
        try:
            entry_price = float(parts[1])
            current_mid = float(parts[2])
            dte = int(parts[3])
        except ValueError:
            print("Invalid numbers.")
            return
        structure = parts[4] if len(parts) > 4 else "iron_condor"

        # Determine side from structure defaults
        credit_structures = {"iron_condor", "iron_butterfly", "credit_spread", "strangle", "straddle"}
        side = "credit" if structure in credit_structures else "debit"

        # Default exit rules by structure
        exit_defaults = {
            "iron_condor": (0.50, 2.0, 21),
            "iron_butterfly": (0.25, 2.0, 21),
            "credit_spread": (0.50, 2.0, 14),
            "calendar": (0.50, 0.50, 14),
            "debit_spread": (1.0, 0.50, 14),
        }
        tp, sl, exit_dte = exit_defaults.get(structure, (0.50, 2.0, 21))

        try:
            ma = self._get_ma()
            regime = ma.regime.detect(ticker)

            result = monitor_exit_conditions(
                trade_id=f"{ticker}-{structure}-CLI",
                ticker=ticker,
                structure_type=structure,
                order_side=side,
                entry_price=entry_price,
                current_mid_price=current_mid,
                contracts=1,
                dte_remaining=dte,
                regime_id=regime.regime,
                profit_target_pct=tp,
                stop_loss_pct=sl,
                exit_dte=exit_dte,
            )

            _print_header(f"{ticker} — Exit Monitor ({structure}, {dte} DTE)")

            action_color = "red" if result.should_close else "green"
            action_text = _styled("CLOSE", "red") if result.should_close else _styled("HOLD", "green")
            print(f"\n  Action:  {action_text}")

            if result.signals:
                print(f"\n  Signals:")
                for sig in result.signals:
                    icon = _styled("!", "red") if sig.triggered else _styled(".", "dim")
                    urg_style = {"immediate": "red", "soon": "yellow", "monitor": "dim"}.get(sig.urgency, "")
                    print(f"    {icon} {sig.rule}: {sig.current_value} vs {sig.threshold} "
                          f"[{_styled(sig.urgency, urg_style)}]")
                    print(f"      {sig.action}")

            print(f"\n  P&L:     {result.pnl_pct:+.0%} ({result.pnl_dollars:+,.0f}$)")
            print(f"\n  {_styled('Commentary:', 'bold')} {result.commentary}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_health(self, arg: str) -> None:
        """Check trade health (exit + adjustment combined).\nUsage: health TICKER ENTRY_PRICE CURRENT_MID DTE [CONTRACTS]\n  Example: health GLD 0.72 0.55 30"""
        parts = arg.strip().split()
        if len(parts) < 4:
            print("Usage: health TICKER ENTRY_PRICE CURRENT_MID DTE [CONTRACTS]")
            return

        ticker = parts[0].upper()
        try:
            entry_price = float(parts[1])
            current_mid = float(parts[2])
            dte = int(parts[3])
            contracts = int(parts[4]) if len(parts) > 4 else 1
        except ValueError:
            print("Invalid numbers.")
            return

        try:
            ma = self._get_ma()
            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)

            # Build representative IC
            from income_desk.models.opportunity import (
                LegAction, LegSpec, OrderSide, StructureType, TradeSpec,
            )
            from datetime import timedelta
            from income_desk.opportunity.option_plays._trade_spec_helpers import compute_otm_strike, snap_strike

            price = tech.current_price
            atr = tech.atr
            exp = date.today() + timedelta(days=dte)
            wing = snap_strike(atr * 0.5, price) or 5.0
            short_put = compute_otm_strike(price, atr, 1.0, "put", price)
            short_call = compute_otm_strike(price, atr, 1.0, "call", price)

            def _leg(action, otype, strike):
                return LegSpec(
                    role=f"{'short' if action == LegAction.SELL_TO_OPEN else 'long'}_{otype}",
                    action=action, option_type=otype, strike=strike,
                    strike_label=f"{strike:.0f} {otype}",
                    expiration=exp, days_to_expiry=dte,
                )

            ts = TradeSpec(
                ticker=ticker,
                legs=[
                    _leg(LegAction.SELL_TO_OPEN, "put", short_put),
                    _leg(LegAction.BUY_TO_OPEN, "put", short_put - wing),
                    _leg(LegAction.SELL_TO_OPEN, "call", short_call),
                    _leg(LegAction.BUY_TO_OPEN, "call", short_call + wing),
                ],
                underlying_price=price, target_dte=dte, target_expiration=exp,
                wing_width_points=wing,
                structure_type=StructureType.IRON_CONDOR,
                order_side=OrderSide.CREDIT,
                profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
                max_entry_price=entry_price,
            )

            result = check_trade_health(
                trade_id=f"{ticker}-IC-CLI",
                trade_spec=ts,
                entry_price=entry_price,
                contracts=contracts,
                current_mid_price=current_mid,
                dte_remaining=dte,
                regime=regime,
                technicals=tech,
            )

            _print_header(f"{ticker} — Trade Health Check")

            status_style = {"healthy": "green", "warning": "yellow", "critical": "red"}.get(result.status, "")
            print(f"\n  Status:  {_styled(result.status.upper(), status_style)}")
            print(f"  Action:  {_styled(result.overall_action, 'bold')}")

            if result.exit_result:
                er = result.exit_result
                close_str = _styled("CLOSE", "red") if er.should_close else _styled("HOLD", "green")
                print(f"  Exit:    {close_str} — {er.summary}")

            if result.adjustment_needed:
                print(f"  Adjust:  {_styled('NEEDED', 'yellow')}")
                if result.adjustment_summary:
                    print(f"  Top adj: {result.adjustment_summary}")
                if result.adjustment_options:
                    for i, opt in enumerate(result.adjustment_options[:3], 1):
                        print(f"    #{i} {opt.get('type', '?')}: {opt.get('rationale', '')}")

            print(f"\n  {_styled('Commentary:', 'bold')} {result.commentary}")

            # Position stress report
            if result.position_stress:
                ps = result.position_stress
                checks = ps.get("checks", [])
                failures = [c for c in checks if c.get("severity") == "fail"]
                warnings = [c for c in checks if c.get("severity") == "warn"]
                passed_count = sum(1 for c in checks if c.get("severity") == "pass")
                print(f"\n  {_styled('Position Stress:', 'bold')} {passed_count}/{len(checks)} passed"
                      + (f", {len(failures)} FAIL" if failures else "")
                      + (f", {len(warnings)} warn" if warnings else ""))
                for c in checks:
                    sev = c.get("severity", "")
                    color = "red" if sev == "fail" else "yellow" if sev == "warn" else "green"
                    icon = "FAIL" if sev == "fail" else "WARN" if sev == "warn" else "PASS"
                    print(f"    [{_styled(icon, color)}] {c.get('name', '?')}: {c.get('message', '')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_greeks(self, arg: str) -> None:
        """Show aggregated Greeks for a structure.\nUsage: greeks TICKER [STRUCTURE]\n  Builds a representative structure and fetches live Greeks from broker.\n  Requires --broker. Structures: ic (default), cs, ifly"""
        parts = arg.strip().split()
        if not parts:
            print("Usage: greeks TICKER [STRUCTURE]")
            print("  Structures: ic (iron condor, default), cs (credit spread), ifly (iron butterfly)")
            return

        ticker = parts[0].upper()
        structure = parts[1].lower() if len(parts) > 1 else "ic"

        try:
            ma = self._get_ma()
            if not ma.quotes.has_broker:
                print(_styled("Requires --broker for live Greeks.", "yellow"))
                return

            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)
            price = tech.current_price
            atr = tech.atr

            from income_desk.models.opportunity import (
                LegAction, LegSpec, OrderSide, StructureType, TradeSpec,
            )
            from datetime import timedelta
            from income_desk.opportunity.option_plays._trade_spec_helpers import compute_otm_strike, snap_strike

            dte = 35
            exp = date.today() + timedelta(days=dte)
            wing = snap_strike(atr * 0.5, price) or 5.0

            short_put = compute_otm_strike(price, atr, 1.0, "put", price)
            short_call = compute_otm_strike(price, atr, 1.0, "call", price)

            def _leg(action, otype, strike):
                return LegSpec(
                    role=f"{'short' if action == LegAction.SELL_TO_OPEN else 'long'}_{otype}",
                    action=action, option_type=otype, strike=strike,
                    strike_label=f"{strike:.0f} {otype}",
                    expiration=exp, days_to_expiry=dte,
                )

            if structure in ("ic", "iron_condor"):
                legs = [
                    _leg(LegAction.SELL_TO_OPEN, "put", short_put),
                    _leg(LegAction.BUY_TO_OPEN, "put", short_put - wing),
                    _leg(LegAction.SELL_TO_OPEN, "call", short_call),
                    _leg(LegAction.BUY_TO_OPEN, "call", short_call + wing),
                ]
                st = StructureType.IRON_CONDOR
            elif structure in ("cs", "credit_spread"):
                legs = [
                    _leg(LegAction.SELL_TO_OPEN, "put", short_put),
                    _leg(LegAction.BUY_TO_OPEN, "put", short_put - wing),
                ]
                st = StructureType.CREDIT_SPREAD
            elif structure in ("ifly", "iron_butterfly"):
                atm = snap_strike(price, price)
                legs = [
                    _leg(LegAction.SELL_TO_OPEN, "put", atm),
                    _leg(LegAction.SELL_TO_OPEN, "call", atm),
                    _leg(LegAction.BUY_TO_OPEN, "put", atm - wing),
                    _leg(LegAction.BUY_TO_OPEN, "call", atm + wing),
                ]
                st = StructureType.IRON_BUTTERFLY
            else:
                print(f"Unknown structure: {structure}")
                return

            ts = TradeSpec(
                ticker=ticker, legs=legs, underlying_price=price,
                target_dte=dte, target_expiration=exp,
                wing_width_points=wing, structure_type=st,
                order_side=OrderSide.CREDIT,
            )

            # Fetch leg quotes from broker
            leg_quotes = ma.quotes.get_leg_quotes(legs)
            if not leg_quotes:
                print(_styled("Could not fetch leg quotes from broker.", "yellow"))
                return

            greeks = aggregate_greeks(ts, leg_quotes)
            if greeks is None:
                print(_styled("Greeks not available in broker quotes.", "yellow"))
                return

            _print_header(f"{ticker} — Aggregated Greeks ({ts.strategy_badge})")
            print(f"\n  Legs:")
            for i, (leg, q) in enumerate(zip(legs, leg_quotes)):
                d_str = f"d={q.delta:+.3f}" if q.delta is not None else ""
                t_str = f"t={q.theta:+.3f}" if q.theta is not None else ""
                print(f"    {leg.action.value} {leg.option_type} ${leg.strike:.0f}  "
                      f"mid=${q.mid:.2f}  {d_str}  {t_str}")

            d_color = "green" if abs(greeks.net_delta) < 0.10 else "yellow"
            print(f"\n  {_styled('Net Greeks:', 'bold')}")
            print(f"    Delta:  {_styled(f'{greeks.net_delta:+.4f}', d_color)}")
            print(f"    Gamma:  {greeks.net_gamma:+.6f}")
            print(f"    Theta:  {greeks.net_theta:+.4f} (${greeks.daily_theta_dollars:+.2f}/day)")
            print(f"    Vega:   {greeks.net_vega:+.4f}")
            print(f"\n  Source: {_styled(ma.quotes.source, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_size(self, arg: str) -> None:
        """Compute position size for a trade.\nUsage: size TICKER CAPITAL [RISK_PCT] [STRUCTURE]\n  Example: size GLD 50000 0.02 iron_condor"""
        parts = arg.strip().split()
        if len(parts) < 2:
            print("Usage: size TICKER CAPITAL [RISK_PCT] [STRUCTURE]")
            print("  CAPITAL: total account capital in dollars")
            print("  RISK_PCT: max fraction of capital per trade (default: 0.02 = 2%)")
            print("  STRUCTURE: iron_condor (default), credit_spread, etc.")
            return

        ticker = parts[0].upper()
        try:
            capital = float(parts[1])
            risk_pct = float(parts[2]) if len(parts) > 2 else 0.02
        except ValueError:
            print("Invalid numbers.")
            return
        structure = parts[3] if len(parts) > 3 else "iron_condor"

        try:
            ma = self._get_ma()
            tech = ma.technicals.snapshot(ticker)
            regime = ma.regime.detect(ticker)
            price = tech.current_price
            atr = tech.atr

            from income_desk.models.opportunity import (
                LegAction, LegSpec, OrderSide, StructureType, TradeSpec,
            )
            from datetime import timedelta
            from income_desk.opportunity.option_plays._trade_spec_helpers import compute_otm_strike, snap_strike

            dte = 35
            exp = date.today() + timedelta(days=dte)
            wing = snap_strike(atr * 0.5, price) or 5.0
            short_put = compute_otm_strike(price, atr, 1.0, "put", price)
            short_call = compute_otm_strike(price, atr, 1.0, "call", price)

            def _leg(action, otype, strike):
                return LegSpec(
                    role=f"{'short' if action == LegAction.SELL_TO_OPEN else 'long'}_{otype}",
                    action=action, option_type=otype, strike=strike,
                    strike_label=f"{strike:.0f} {otype}",
                    expiration=exp, days_to_expiry=dte,
                )

            ts = TradeSpec(
                ticker=ticker,
                legs=[
                    _leg(LegAction.SELL_TO_OPEN, "put", short_put),
                    _leg(LegAction.BUY_TO_OPEN, "put", short_put - wing),
                    _leg(LegAction.SELL_TO_OPEN, "call", short_call),
                    _leg(LegAction.BUY_TO_OPEN, "call", short_call + wing),
                ],
                underlying_price=price, target_dte=dte, target_expiration=exp,
                wing_width_points=wing,
                structure_type=StructureType(structure),
                order_side=OrderSide.CREDIT,
            )

            contracts = ts.position_size(capital=capital, risk_pct=risk_pct)
            risk_per = wing * 100
            max_risk = risk_per * contracts
            bp_needed = risk_per * contracts

            _print_header(f"{ticker} — Position Size ({ts.strategy_badge})")
            print(f"\n  Capital:           ${capital:,.0f}")
            print(f"  Risk Budget:       {risk_pct:.0%} = ${capital * risk_pct:,.0f}")
            print(f"  Wing Width:        ${wing:.0f} (risk per spread: ${risk_per:.0f})")
            print(f"  Contracts:         {_styled(str(contracts), 'bold')}")
            print(f"  Total Max Risk:    ${max_risk:,.0f}")
            print(f"  BP Required:       ${bp_needed:,.0f}")
            print(f"  % of Capital:      {max_risk / capital:.1%}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_kelly(self, arg: str) -> None:
        """Kelly-optimal position sizing: kelly TICKER [ACCOUNT_SIZE]

        Computes Kelly criterion sizing for a representative iron condor on the ticker.
        Shows: full Kelly, half Kelly (conservative), portfolio-adjusted, recommended contracts.

        Examples:
            kelly SPY
            kelly SPY 50000
            kelly AAPL 200000
        """
        parts = arg.strip().split()
        ticker = parts[0].upper() if parts else "SPY"
        capital = float(parts[1]) if len(parts) > 1 else 50000.0

        try:
            ma = self._get_ma()

            if not getattr(ma, 'market_data', None):
                print(_styled(
                    "  *** ESTIMATED DATA — No broker connected. Credits, POP, and sizing are approximate. ***\n"
                    "  *** Connect broker (--broker) for real DXLink quotes and accurate analysis.         ***",
                    "yellow",
                ))

            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)
            vol = ma.vol_surface.compute(ticker)

            from income_desk.opportunity.option_plays.iron_condor import assess_iron_condor
            ic = assess_iron_condor(ticker, regime, tech, vol)

            if ic.trade_spec is None:
                print(f"No trade spec for {ticker} (verdict: {ic.verdict})")
                return

            # Get POP estimate
            from income_desk.trade_lifecycle import estimate_pop
            pop_est = estimate_pop(
                trade_spec=ic.trade_spec,
                entry_price=ic.trade_spec.max_entry_price or 1.50,
                regime_id=regime.regime.value,
                atr_pct=tech.atr_pct,
            )

            # Compute risk per contract
            wing_width = ic.trade_spec.wing_width_points or 5.0
            lot_size = ic.trade_spec.lot_size
            risk_per_contract = wing_width * lot_size

            from income_desk.features.position_sizing import (
                compute_kelly_position_size,
                compute_kelly_fraction,
            )

            # Without portfolio context (standalone)
            result = compute_kelly_position_size(
                capital=capital,
                pop_pct=pop_est.pop_pct,
                max_profit=pop_est.max_profit,
                max_loss=pop_est.max_loss,
                risk_per_contract=risk_per_contract,
            )

            print(f"\nKELLY SIZING — {ticker} — ${capital:,.0f} account")
            print("-" * 50)
            print(f"Trade: {ic.trade_spec.structure_type or 'iron_condor'}")
            print(f"POP:   {pop_est.pop_pct:.0%}  |  Max Profit: ${pop_est.max_profit:.0f}  |  Max Loss: ${pop_est.max_loss:.0f}")
            print(f"Risk/contract: ${risk_per_contract:.0f}")
            print()
            print(f"Full Kelly:     {result.full_kelly_fraction:.1%} of capital (${capital * result.full_kelly_fraction:,.0f})")
            print(f"Half Kelly:     {result.half_kelly_fraction:.1%} of capital (${capital * result.half_kelly_fraction:,.0f})")
            print(f"Fixed 2%:       ${capital * 0.02:,.0f}")
            print()
            print(f"Recommended:    {result.recommended_contracts} contracts")
            print(f"Max by risk:    {result.max_contracts_by_risk} contracts (2% cap)")
            print()

            # Compare sizing methods
            fixed_contracts = max(1, int(capital * 0.02 / risk_per_contract))
            kelly_contracts = result.recommended_contracts
            if kelly_contracts > fixed_contracts:
                print(f"Kelly suggests MORE than fixed 2%: {kelly_contracts} vs {fixed_contracts} (high-quality trade)")
            elif kelly_contracts < fixed_contracts:
                print(f"Kelly suggests LESS than fixed 2%: {kelly_contracts} vs {fixed_contracts} (lower-quality trade)")
            else:
                print(f"Kelly agrees with fixed 2%: {kelly_contracts} contracts")

            print("-" * 50)

        except Exception as e:
            print(f"Error: {e}")

    def do_audit(self, arg: str) -> None:
        """Full 4-level trade decision audit: audit TICKER [CAPITAL]

        Evaluates a proposed iron condor at leg, trade, portfolio, and risk levels.
        Produces a Decision Report Card with scores and grades.

        Usage: audit TICKER [CAPITAL]
          TICKER  — underlying symbol (default: SPY)
          CAPITAL — account size in dollars (default: 35000)

        Example: audit SPY 50000
        """
        parts = arg.strip().split()
        ticker = parts[0].upper() if parts else "SPY"
        capital = float(parts[1]) if len(parts) > 1 else 35000.0

        try:
            ma = self.ma
            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)
            vol = ma.vol_surface.surface(ticker)
            levels = ma.levels.analyze(ticker)

            from income_desk.opportunity.option_plays.iron_condor import assess_iron_condor
            ic = assess_iron_condor(ticker, regime, tech, vol)
            if ic.trade_spec is None:
                print(f"No trade spec for {ticker}")
                return

            ts = ic.trade_spec
            wing = ts.wing_width_points or 5.0
            ec = wing * vol.front_iv * 0.40 if vol else 1.00

            from income_desk.trade_lifecycle import estimate_pop
            pop = estimate_pop(ts, ec, regime.regime.value, tech.atr_pct, tech.current_price)

            from income_desk.features.entry_levels import score_entry_level
            entry = score_entry_level(tech, levels, direction="neutral")

            from income_desk.features.position_sizing import (
                compute_position_size,
                PortfolioExposure,
                compute_kelly_fraction,
            )
            kelly_f = compute_kelly_fraction(pop.pop_pct, pop.max_profit, pop.max_loss)
            sz = compute_position_size(
                pop_pct=pop.pop_pct,
                max_profit=pop.max_profit,
                max_loss=pop.max_loss,
                capital=capital,
                risk_per_contract=wing * ts.lot_size,
                wing_width=wing,
                regime_id=regime.regime.value,
                exposure=PortfolioExposure(open_position_count=0, max_positions=5),
            )

            from income_desk.validation.stress_scenarios import check_gamma_stress, check_vega_shock
            gamma = check_gamma_stress(ts, ec, tech.atr_pct)
            vega = check_vega_shock(ts, ec)
            stress_ok = gamma.severity.value != "fail" and vega.severity.value != "fail"

            skew = vol.skew_by_expiry[0] if vol and vol.skew_by_expiry else None

            from income_desk.features.decision_audit import audit_decision
            report = audit_decision(
                ticker=ticker,
                trade_spec=ts,
                levels=levels,
                skew=skew,
                atr=tech.atr,
                pop_pct=pop.pop_pct,
                expected_value=pop.expected_value,
                entry_credit=ec,
                entry_score=entry.overall_score,
                regime_id=regime.regime.value,
                atr_pct=tech.atr_pct,
                capital=capital,
                contracts=sz.recommended_contracts,
                stress_passed=stress_ok,
                kelly_fraction=kelly_f,
            )

            has_broker = getattr(self.ma, "market_data", None) is not None
            if not has_broker:
                print(_styled(
                    "  *** ESTIMATED DATA — No broker connected ***",
                    "yellow",
                ))

            print(f"\nDECISION AUDIT — {ticker} {ts.structure_type or 'IC'} — R{regime.regime.value}")
            print("=" * 55)

            if report.leg_audit:
                la = report.leg_audit
                print(f"\nLEG LEVEL ({len(la.checks)} checks) — {la.score}/100 {la.grade}")
                for c in la.checks:
                    print(f"  {c.grade:3s}  {c.name:<25s} {c.detail}")

            ta = report.trade_audit
            print(f"\nTRADE LEVEL ({len(ta.checks)} checks) — {ta.score}/100 {ta.grade}")
            for c in ta.checks:
                print(f"  {c.grade:3s}  {c.name:<25s} {c.detail}")

            pa = report.portfolio_audit
            print(f"\nPORTFOLIO LEVEL ({len(pa.checks)} checks) — {pa.score}/100 {pa.grade}")
            for c in pa.checks:
                print(f"  {c.grade:3s}  {c.name:<25s} {c.detail}")

            ra = report.risk_audit
            print(f"\nRISK LEVEL ({len(ra.checks)} checks) — {ra.score}/100 {ra.grade}")
            for c in ra.checks:
                print(f"  {c.grade:3s}  {c.name:<25s} {c.detail}")

            print(f"\n{'=' * 55}")
            verdict_color = "green" if report.approved else "red"
            print(_styled(
                f"OVERALL: {report.overall_score}/100 {report.overall_grade} — "
                f"{'APPROVED' if report.approved else 'REJECTED'}",
                verdict_color,
            ))
            print("=" * 55)

            # ── Trust score ────────────────────────────────────────────────────
            from income_desk.features.data_trust import compute_trust_report
            metrics_audit = ma.quotes.get_metrics(ticker) if ma.quotes else None
            iv_rank_audit = metrics_audit.iv_rank if metrics_audit else None
            has_broker_audit = bool(ma.quotes and ma.quotes.has_broker)
            trust = compute_trust_report(
                has_broker=has_broker_audit,
                has_iv_rank=iv_rank_audit is not None,
                has_vol_surface=vol is not None,
                has_levels=levels is not None,
                entry_credit_source="estimated",  # audit always uses estimated credit (ec = heuristic)
                regime_confidence=regime.confidence,
                has_entry_credit=False,  # audit doesn't pass real entry credit
            )
            trust_color = "green" if trust.overall_trust >= 0.80 else (
                "yellow" if trust.overall_trust >= 0.50 else "red"
            )
            print(f"\n{_styled(f'TRUST: {trust.overall_trust:.0%} {trust.overall_level.upper()}', trust_color)}")
            print(f"  Data:    {trust.data_quality.trust_score:.0%} {trust.data_quality.trust_level.upper()}"
                  f" ({trust.data_quality.primary_source.value})")
            print(f"  Context: {trust.context_score:.0%} {trust.context_level.upper()}", end="")
            if trust.context_gaps:
                _critical_gaps = [g for g in trust.context_gaps if g.importance == "critical"]
                if _critical_gaps:
                    print(f" — MISSING: {', '.join(g.parameter for g in _critical_gaps)}", end="")
            print()
            print(f"  {trust.fit_for_summary}")
            if not has_broker_audit:
                print("  >> Connect broker (--broker --paper) for HIGH trust analysis.")

        except Exception as e:
            print(f"Error: {e}")

    def do_adjust(self, arg: str) -> None:
        """Analyze trade adjustments for a ticker.\nUsage: adjust TICKER"""
        tickers = self._parse_tickers(arg)
        if not tickers:
            print("Usage: adjust TICKER")
            return
        ticker = tickers[0]

        try:
            ma = self._get_ma()
            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)
            price = tech.current_price
            atr = tech.atr

            # Build a representative IC trade for analysis
            from income_desk.models.opportunity import LegAction, LegSpec, OrderSide, StructureType, TradeSpec
            from income_desk.opportunity.option_plays._trade_spec_helpers import (
                build_iron_condor_legs,
                find_best_expiration,
            )

            vol_surface = None
            try:
                vol_surface = ma.vol_surface.get(ticker)
            except Exception:
                pass

            # Try to build from vol surface, fallback to synthetic
            exp_pt = None
            if vol_surface and vol_surface.term_structure:
                exp_pt = find_best_expiration(vol_surface.term_structure, 30, 45)

            if exp_pt:
                legs, wing_width = build_iron_condor_legs(
                    price, atr, regime.regime, exp_pt.expiration,
                    exp_pt.days_to_expiry, exp_pt.atm_iv,
                )
                trade = TradeSpec(
                    ticker=ticker, legs=legs, underlying_price=price,
                    target_dte=exp_pt.days_to_expiry, target_expiration=exp_pt.expiration,
                    wing_width_points=wing_width,
                    spec_rationale="Representative IC for adjustment analysis",
                    structure_type=StructureType.IRON_CONDOR,
                    order_side=OrderSide.CREDIT,
                    profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
                )
            else:
                # Synthetic fallback
                from datetime import timedelta
                from income_desk.opportunity.option_plays._trade_spec_helpers import (
                    compute_otm_strike, snap_strike,
                )
                dte = 30
                exp = date.today() + timedelta(days=dte)
                short_put = compute_otm_strike(price, atr, 1.0, "put", price)
                short_call = compute_otm_strike(price, atr, 1.0, "call", price)
                long_put = snap_strike(short_put - atr * 0.5, price)
                long_call = snap_strike(short_call + atr * 0.5, price)
                ww = short_put - long_put

                def _leg(role, action, otype, strike):
                    return LegSpec(
                        role=role, action=action, option_type=otype, strike=strike,
                        strike_label=f"{strike:.0f} {otype}",
                        expiration=exp, days_to_expiry=dte, atm_iv_at_expiry=0.25,
                    )

                trade = TradeSpec(
                    ticker=ticker,
                    legs=[
                        _leg("short_put", LegAction.SELL_TO_OPEN, "put", short_put),
                        _leg("long_put", LegAction.BUY_TO_OPEN, "put", long_put),
                        _leg("short_call", LegAction.SELL_TO_OPEN, "call", short_call),
                        _leg("long_call", LegAction.BUY_TO_OPEN, "call", long_call),
                    ],
                    underlying_price=price, target_dte=dte, target_expiration=exp,
                    wing_width_points=ww,
                    spec_rationale="Synthetic IC for adjustment analysis",
                    structure_type=StructureType.IRON_CONDOR,
                    order_side=OrderSide.CREDIT,
                    profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
                )

            result = ma.adjustment.analyze(trade, regime, tech, vol_surface)

            # Also run exit monitoring on the same trade
            exit_result = monitor_exit_conditions(
                trade_id=f"{ticker}-IC-adjust",
                ticker=ticker,
                structure_type="iron_condor",
                order_side="credit",
                entry_price=trade.max_entry_price or 0.50,
                current_mid_price=trade.max_entry_price or 0.50,  # Same as entry (no live fill data)
                contracts=1,
                dte_remaining=trade.target_dte or 30,
                regime_id=regime.regime,
                profit_target_pct=trade.profit_target_pct,
                stop_loss_pct=trade.stop_loss_pct,
                exit_dte=trade.exit_dte,
            )

            # Display
            _print_header(f"{ticker} — Trade Adjustment Analysis")

            # Data source
            src = ma.adjustment.quote_source
            src_style = "green" if "real" in src else "dim"
            print(f"\n  {_styled('Source:', 'dim')} {_styled(src, src_style)}")

            # Position summary
            short_puts = [l for l in trade.legs
                          if l.option_type == "put" and l.action == LegAction.SELL_TO_OPEN]
            short_calls = [l for l in trade.legs
                           if l.option_type == "call" and l.action == LegAction.SELL_TO_OPEN]
            long_puts = [l for l in trade.legs
                         if l.option_type == "put" and l.action == LegAction.BUY_TO_OPEN]
            long_calls = [l for l in trade.legs
                          if l.option_type == "call" and l.action == LegAction.BUY_TO_OPEN]

            legs_desc = ""
            if short_puts and long_puts and short_calls and long_calls:
                sp = max(l.strike for l in short_puts)
                lp = min(l.strike for l in long_puts)
                sc = min(l.strike for l in short_calls)
                lc = max(l.strike for l in long_calls)
                legs_desc = f"{lp:.0f}P/{sp:.0f}P — {sc:.0f}C/{lc:.0f}C"

            profile = _profile_tag(trade.structure_type, trade.order_side)
            print(f"\n  Position: Iron Condor  {legs_desc}  {result.remaining_dte} DTE  {profile}")

            status_style = {
                "safe": "green", "tested": "yellow", "breached": "red", "max_loss": "red",
            }.get(result.position_status, "")
            tested_str = (
                f" ({result.tested_side} side)"
                if result.tested_side != "none" else ""
            )
            print(f"  Status: {_styled(result.position_status.upper(), status_style)}{tested_str}  |  "
                  f"Price: ${result.current_price:.0f}", end="")
            if result.distance_to_short_put_pct is not None:
                print(f"  |  Short put: {result.distance_to_short_put_pct:+.1f}%", end="")
            if result.distance_to_short_call_pct is not None:
                print(f"  |  Short call: {result.distance_to_short_call_pct:+.1f}%", end="")
            print()
            pnl_str = f"${result.mark_pnl:+.2f}" if result.mark_pnl is not None else _styled("N/A (DXLink fetch failed)", "yellow")
            print(f"  P&L: {pnl_str}  |  Regime: R{result.regime_id}")

            # Adjustments
            print()
            for i, adj in enumerate(result.adjustments, 1):
                type_label = adj.adjustment_type.value.upper().replace("_", " ")
                print(f"  #{i}  {_styled(type_label, 'bold')} — {adj.rationale}")
                if adj.mid_cost is not None:
                    cost_str = f"${adj.mid_cost:+.2f}" if adj.mid_cost != 0 else "$0"
                else:
                    cost_str = _styled("N/A (DXLink fetch failed)", "yellow")
                risk_str = f"${adj.risk_change:+.0f}" if adj.risk_change != 0 else "unchanged"
                if adj.efficiency is not None:
                    eff_str = f"{adj.efficiency:.2f}"
                elif adj.mid_cost is not None and adj.mid_cost <= 0 and adj.risk_change < 0:
                    eff_str = "∞"
                else:
                    eff_str = "—"
                urgency_style = {"immediate": "red", "soon": "yellow", "monitor": "dim"}.get(adj.urgency, "")
                print(f"      Cost: {cost_str}  |  Risk: {risk_str}  |  "
                      f"Efficiency: {eff_str}  |  "
                      f"Urgency: {_styled(adj.urgency, urgency_style)}")
                if adj.description and adj.description != adj.rationale:
                    print(f"      {_styled(adj.description, 'dim')}")
                # Warn on poor cost/risk ratio for paid adjustments
                if adj.mid_cost is not None and adj.mid_cost > 0 and adj.risk_change < 0:
                    ratio = abs(adj.risk_change) / adj.mid_cost
                    if ratio < 1.0:
                        print(f"      {_styled(f'⚠ POOR — paying ${adj.mid_cost:.2f} to reduce ${abs(adj.risk_change):.0f} risk', 'yellow')}")
                print()

            # Exit monitoring signals
            if exit_result.signals:
                print(f"  {_styled('Exit Signals:', 'bold')}")
                for sig in exit_result.signals:
                    icon = _styled("!", "red") if sig.triggered else _styled(".", "dim")
                    print(f"    {icon} {sig.rule}: {sig.current_value} vs {sig.threshold} [{sig.urgency}]")
                print()

            print(f"  {_styled(result.recommendation, 'bold')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_balance(self, arg: str) -> None:
        """Show broker account balance and buying power.\nUsage: balance"""
        ma = self._get_ma()
        if ma.account_provider is None:
            print(_styled("No broker connected. Run with --broker for account balance.", "yellow"))
            return

        try:
            bal = ma.account_provider.get_balance()
        except Exception as e:
            print(_styled(f"Failed to fetch balance: {e}", "red"))
            return

        _print_header(f"Account Balance — {bal.account_number}")
        print(f"  Net Liquidating Value:   {_styled(f'${bal.net_liquidating_value:>12,.2f}', 'bold')}")
        print(f"  Cash Balance:            ${bal.cash_balance:>12,.2f}")
        print(f"  Option Buying Power:     {_styled(f'${bal.derivative_buying_power:>12,.2f}', 'green')}")
        print(f"  Equity Buying Power:     ${bal.equity_buying_power:>12,.2f}")
        print(f"  Maintenance Requirement: ${bal.maintenance_requirement:>12,.2f}")
        if bal.pending_cash:
            print(f"  Pending Cash:            ${bal.pending_cash:>12,.2f}")
        print(f"  Source: {_styled(bal.source, 'dim')}")

    def do_quotes(self, arg: str) -> None:
        """Show option chain quotes for a ticker.\nUsage: quotes TICKER [EXPIRATION]"""
        parts = arg.strip().split()
        if not parts:
            print("Usage: quotes TICKER [YYYY-MM-DD]")
            return
        ticker = parts[0].upper()

        expiration = None
        if len(parts) > 1:
            try:
                expiration = date.fromisoformat(parts[1])
            except ValueError:
                print(f"Invalid date: {parts[1]} (use YYYY-MM-DD)")
                return

        try:
            ma = self._get_ma()
            snap = ma.quotes.get_chain(ticker, expiration)

            _print_header(f"{ticker} Option Chain — Source: {snap.source}")
            if not snap.quotes:
                print(f"\n  No quotes available for {ticker}")
                return

            print(f"\n  Underlying: ${snap.underlying_price:.2f}")

            # Market metrics if available
            metrics = ma.quotes.get_metrics(ticker)
            if metrics:
                parts_m = []
                if metrics.iv_rank is not None:
                    parts_m.append(f"IV Rank: {metrics.iv_rank:.1f}")
                if metrics.iv_percentile is not None:
                    parts_m.append(f"IV Pctl: {metrics.iv_percentile:.1f}")
                if metrics.beta is not None:
                    parts_m.append(f"Beta: {metrics.beta:.2f}")
                if metrics.liquidity_rating is not None:
                    parts_m.append(f"Liq: {metrics.liquidity_rating:.1f}")
                if parts_m:
                    print(f"  {' | '.join(parts_m)}")

            # Group by expiration
            from collections import defaultdict
            by_exp: dict[date, list] = defaultdict(list)
            for q in snap.quotes:
                by_exp[q.expiration].append(q)

            for exp_date in sorted(by_exp.keys()):
                qs = by_exp[exp_date]
                dte = (exp_date - date.today()).days
                print(f"\n  {_styled(f'Expiration: {exp_date} ({dte} DTE)', 'bold')}")

                # Show puts and calls around ATM
                calls = sorted([q for q in qs if q.option_type == "call"], key=lambda q: q.strike)
                puts = sorted([q for q in qs if q.option_type == "put"], key=lambda q: q.strike)

                # Filter to near-ATM strikes (within ~10% of price)
                if snap.underlying_price > 0:
                    lo = snap.underlying_price * 0.90
                    hi = snap.underlying_price * 1.10
                    calls = [q for q in calls if lo <= q.strike <= hi]
                    puts = [q for q in puts if lo <= q.strike <= hi]

                has_greeks = any(q.delta is not None for q in calls + puts)

                # Header
                if has_greeks:
                    hdr = f"  {'Strike':>8}  {'Type':>5}  {'Bid':>7}  {'Ask':>7}  {'Mid':>7}  {'IV':>7}  {'Delta':>7}  {'Theta':>7}"
                else:
                    hdr = f"  {'Strike':>8}  {'Type':>5}  {'Bid':>7}  {'Ask':>7}  {'Mid':>7}  {'IV':>7}  {'Vol':>7}  {'OI':>7}"
                print(_styled(hdr, 'dim'))

                for q in puts + calls:
                    iv_str = f"{q.implied_volatility:.2%}" if q.implied_volatility else "  —"
                    if has_greeks:
                        d_str = f"{q.delta:>7.3f}" if q.delta is not None else "    —"
                        t_str = f"{q.theta:>7.3f}" if q.theta is not None else "    —"
                        print(f"  {q.strike:>8.0f}  {q.option_type:>5}  {q.bid:>7.2f}  {q.ask:>7.2f}  {q.mid:>7.2f}  {iv_str:>7}  {d_str}  {t_str}")
                    else:
                        print(f"  {q.strike:>8.0f}  {q.option_type:>5}  {q.bid:>7.2f}  {q.ask:>7.2f}  {q.mid:>7.2f}  {iv_str:>7}  {q.volume:>7}  {q.open_interest:>7}")

                # Limit output
                if len(by_exp) > 3 and exp_date != sorted(by_exp.keys())[0]:
                    break  # Only show first expiration in detail if many

            # Aggregate Greeks for a representative IC if broker has Greeks
            if ma.quotes.has_broker and snap.underlying_price > 0:
                try:
                    tech = ma.technicals.snapshot(ticker)
                    atr = tech.atr

                    from income_desk.models.opportunity import (
                        LegAction, LegSpec, OrderSide, StructureType, TradeSpec,
                    )
                    from datetime import timedelta
                    from income_desk.opportunity.option_plays._trade_spec_helpers import (
                        compute_otm_strike, snap_strike,
                    )

                    p = snap.underlying_price
                    wing = snap_strike(atr * 0.5, p) or 5.0
                    sp = compute_otm_strike(p, atr, 1.0, "put", p)
                    sc = compute_otm_strike(p, atr, 1.0, "call", p)
                    dte = 35
                    exp_d = date.today() + timedelta(days=dte)

                    def _ql(action, otype, strike):
                        return LegSpec(
                            role=f"{'short' if action == LegAction.SELL_TO_OPEN else 'long'}_{otype}",
                            action=action, option_type=otype, strike=strike,
                            strike_label=f"{strike:.0f} {otype}",
                            expiration=exp_d, days_to_expiry=dte,
                        )

                    ic_legs = [
                        _ql(LegAction.SELL_TO_OPEN, "put", sp),
                        _ql(LegAction.BUY_TO_OPEN, "put", sp - wing),
                        _ql(LegAction.SELL_TO_OPEN, "call", sc),
                        _ql(LegAction.BUY_TO_OPEN, "call", sc + wing),
                    ]
                    ic_ts = TradeSpec(
                        ticker=ticker, legs=ic_legs, underlying_price=p,
                        target_dte=dte, target_expiration=exp_d,
                        wing_width_points=wing, structure_type=StructureType.IRON_CONDOR,
                        order_side=OrderSide.CREDIT,
                    )

                    leg_quotes = ma.quotes.get_leg_quotes(ic_legs)
                    if leg_quotes:
                        greeks = aggregate_greeks(ic_ts, leg_quotes)
                        if greeks:
                            print(f"\n  {_styled(f'Aggregate Greeks (IC {sp:.0f}P/{sc:.0f}C, {wing:.0f} wings):', 'bold')}")
                            print(f"    Delta: {greeks.net_delta:+.4f}  Gamma: {greeks.net_gamma:+.6f}  "
                                  f"Theta: {greeks.net_theta:+.4f} (${greeks.daily_theta_dollars:+.2f}/day)  "
                                  f"Vega: {greeks.net_vega:+.4f}")
                except Exception:
                    pass  # Greeks are a bonus, don't fail the whole command

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")
            traceback.print_exc()

    def do_broker(self, arg: str) -> None:
        """Show broker connection status and capabilities.\nUsage: broker"""
        ma = self._get_ma()

        _print_header("Broker Status")

        if ma.quotes.has_broker:
            print(f"\n  Status:        {_styled('CONNECTED', 'green')}")
            print(f"  Broker:        {ma.quotes.source}")

            # Try to get account details from the underlying session
            md = ma.quotes._market_data
            if hasattr(md, '_session'):
                session = md._session
                try:
                    acct = session.account
                    print(f"  Account:       {acct.account_number}")
                    mode = "PAPER" if session._is_paper else "LIVE"
                    print(f"  Mode:          {mode}")
                    # Show all accounts if multiple
                    if len(session._accounts) > 1:
                        others = [a for a in session._accounts if a != acct.account_number]
                        print(f"  Other accts:   {', '.join(others)}")
                except Exception:
                    pass

            print(f"\n  {_styled('Data Capabilities:', 'bold')}")
            print(f"    Option chains    DXLink streamer (real-time bid/ask)")
            print(f"    Greeks           DXLink DXGreeks (real-time delta/gamma/theta/vega)")
            print(f"    Underlying       DXLink DXQuote (real-time mid price)")
            print(f"    Intraday bars    DXLink Candle (5m bars)")
            print(f"    IV metrics       TastyTrade API (IV rank/percentile/beta)")
            print(f"    Historical       yfinance (OHLCV, cached)")

            # Show adjustment data source
            if hasattr(ma, 'adjustment') and hasattr(ma.adjustment, 'quote_source'):
                print(f"\n  Adjustment pricing: {ma.adjustment.quote_source}")

            # Quick connectivity test — try underlying price
            print(f"\n  {_styled('Quick test:', 'dim')} ", end="", flush=True)
            try:
                price = md.get_underlying_price("SPY")
                if price:
                    print(_styled(f"SPY = ${price:.2f} (live)", "green"))
                else:
                    print(_styled("SPY price unavailable", "yellow"))
            except Exception as e:
                print(_styled(f"failed: {e}", "red"))

        else:
            print(f"\n  Status:        {_styled('NOT CONNECTED', 'yellow')}")
            print(f"  Data source:   yfinance (historical OHLCV only)")
            print(f"  Options data:  {_styled('UNAVAILABLE', 'yellow')} — no live quotes, Greeks, or IV")
            print(f"  Pricing:       {_styled('UNAVAILABLE', 'yellow')} — cannot compute fill prices")
            print(f"\n  {_styled('To connect:', 'bold')} analyzer-cli --broker")
            print(f"  Requires:      TASTYTRADE_***_DATA env vars in eTrading/.env")

    def do_refresh_sim(self, arg: str) -> None:
        """Capture live market data for simulation: refresh_sim [TICKERS]

        Run during market hours with --broker connected.
        Saves snapshot to ~/.income_desk/sim_snapshot.json.
        Use 'analyzer-cli --sim snapshot' to load it offline.

        Examples:
            refresh_sim                    # Default: SPY QQQ IWM GLD TLT
            refresh_sim SPY QQQ NIFTY      # Custom tickers
        """
        tickers = arg.strip().split() if arg.strip() else None

        from income_desk.adapters.simulated import refresh_simulation_data

        print("Capturing live market data...")
        snapshot = refresh_simulation_data(self._get_ma(), tickers)

        captured = len([t for t in snapshot["tickers"].values() if "error" not in t])
        errors = len([t for t in snapshot["tickers"].values() if "error" in t])

        print(f"Captured {captured} tickers" + (f" ({errors} errors)" if errors else ""))
        for ticker, info in snapshot["tickers"].items():
            if "error" in info:
                print(f"  {ticker}: ERROR — {info['error']}")
            else:
                iv_str = f"IV {info['iv']:.1%}" if info.get("iv") else ""
                ivr_str = f"IVR {info['iv_rank']:.0f}%" if info.get("iv_rank") is not None else ""
                print(f"  {ticker}: ${info['price']:.2f}  R{info.get('regime_id', '?')}  {iv_str}  {ivr_str}")

        from income_desk.adapters.simulated import SIM_SNAPSHOT_FILE
        print(f"\nSaved to {SIM_SNAPSHOT_FILE}")
        print("Use: analyzer-cli --sim snapshot")

    def do_risk(self, arg: str) -> None:
        """Show portfolio risk dashboard from demo positions.\nUsage: risk\n       risk --nlv 50000 --peak 52000\n\nBuilds a demo portfolio to show what the risk dashboard computes.\neTrading provides real positions; this command shows the computation."""
        import traceback

        parts = arg.strip().split()
        nlv = 50000.0
        peak = 52000.0

        # Parse --nlv and --peak flags
        i = 0
        while i < len(parts):
            if parts[i] == "--nlv" and i + 1 < len(parts):
                try:
                    nlv = float(parts[i + 1])
                except ValueError:
                    print(f"Invalid NLV: {parts[i + 1]}")
                    return
                i += 2
            elif parts[i] == "--peak" and i + 1 < len(parts):
                try:
                    peak = float(parts[i + 1])
                except ValueError:
                    print(f"Invalid peak: {parts[i + 1]}")
                    return
                i += 2
            else:
                i += 1

        try:
            from income_desk.risk import (
                PortfolioPosition,
                GreeksLimits,
                estimate_portfolio_loss,
                check_portfolio_greeks,
                check_strategy_concentration,
                check_directional_concentration,
                check_drawdown_circuit_breaker,
                compute_risk_dashboard,
            )

            # Build demo positions to illustrate the risk engine
            demo_positions = [
                PortfolioPosition(
                    ticker="SPY", structure_type="iron_condor", direction="neutral",
                    sector="broad_market", max_loss=500, buying_power_used=500,
                    notional_value=57000, delta=-0.02, gamma=-0.001, theta=0.15, vega=-0.30,
                    regime_at_entry=1, dte_remaining=28, current_pnl_pct=0.25,
                ),
                PortfolioPosition(
                    ticker="QQQ", structure_type="iron_condor", direction="neutral",
                    sector="tech", max_loss=450, buying_power_used=450,
                    notional_value=49000, delta=-0.03, gamma=-0.001, theta=0.12, vega=-0.25,
                    regime_at_entry=1, dte_remaining=35, current_pnl_pct=0.10,
                ),
                PortfolioPosition(
                    ticker="GLD", structure_type="credit_spread", direction="bullish",
                    sector="commodities", max_loss=300, buying_power_used=300,
                    notional_value=28000, delta=0.15, gamma=0.002, theta=0.08, vega=-0.10,
                    regime_at_entry=3, dte_remaining=21, current_pnl_pct=0.40,
                ),
            ]

            # Correlation data (SPY/QQQ highly correlated)
            corr_data = {
                ("SPY", "QQQ"): 0.92,
                ("SPY", "GLD"): 0.05,
                ("QQQ", "GLD"): -0.10,
            }

            # ATR and regime data
            atr_data = {"SPY": 0.012, "QQQ": 0.015, "GLD": 0.010}
            regime_data = {"SPY": 1, "QQQ": 1, "GLD": 3}

            # Try to get real macro data
            macro_regime = "unknown"
            macro_factor = 1.0
            try:
                ma = self._get_ma()
                from income_desk.macro_research import classify_macro_regime
                from income_desk import DataService
                ds = ma._data_service or DataService()
                macro = classify_macro_regime(ds)
                macro_regime = macro.regime.value
                macro_factor = macro.position_size_factor
            except Exception:
                pass

            dashboard = compute_risk_dashboard(
                positions=demo_positions,
                account_nlv=nlv,
                account_peak=peak,
                max_positions=5,
                greeks_limits=GreeksLimits(),
                circuit_breaker_pct=0.10,
                atr_by_ticker=atr_data,
                regime_by_ticker=regime_data,
                correlation_data=corr_data,
                avg_underlying_price=450,
                macro_regime=macro_regime,
                macro_position_factor=macro_factor,
            )

            _print_header(f"Portfolio Risk Dashboard — {dashboard.as_of_date}")

            # Overall status
            level_colors = {
                "low": "green", "moderate": "green",
                "elevated": "yellow", "high": "red", "critical": "red",
            }
            level_color = level_colors.get(dashboard.overall_risk_level, "")
            gate_str = _styled("OPEN", "green") if dashboard.can_open_new_trades else _styled("BLOCKED", "red")
            print(f"\n  Risk Level:  {_styled(dashboard.overall_risk_level.upper(), level_color)}")
            print(f"  New Trades:  {gate_str}  (size factor: {dashboard.max_new_trade_size_pct:.0%})")
            print(f"  NLV:         ${dashboard.account_nlv:,.0f}")

            # Positions
            print(f"\n  {_styled('Positions', 'bold')}")
            print(f"    Open:       {dashboard.open_positions}/{dashboard.max_positions} "
                  f"({dashboard.slots_remaining} slots remaining)")
            print(f"    Total risk: {dashboard.portfolio_risk_pct:.1f}% of NLV "
                  f"(${sum(p.max_loss for p in demo_positions):,.0f})")

            # Drawdown
            dd = dashboard.drawdown
            dd_color = "red" if dd.is_triggered else ("yellow" if dd.drawdown_pct > 0.05 else "green")
            print(f"\n  {_styled('Drawdown', 'bold')}")
            print(f"    Peak:       ${dd.account_peak:,.0f}")
            print(f"    Current:    ${dd.current_nlv:,.0f}")
            print(f"    Drawdown:   {_styled(f'{dd.drawdown_pct:.1%}', dd_color)} "
                  f"(${dd.drawdown_dollars:,.0f})")
            print(f"    Breaker:    {dd.circuit_breaker_pct:.0%} "
                  f"({'TRIGGERED' if dd.is_triggered else 'OK'})")

            # Expected Loss (ATR-based)
            if dashboard.expected_loss:
                v = dashboard.expected_loss
                loss_color = "red" if v.loss_pct_of_nlv > 5 else ("yellow" if v.loss_pct_of_nlv > 2 else "green")
                print(f"\n  {_styled('Expected Loss (ATR-based)', 'bold')}")
                print(f"    1-day expected:  {_styled(f'${v.expected_loss_1d:,.0f}', loss_color)} "
                      f"({v.loss_pct_of_nlv:.1f}% of NLV)")
                print(f"    1-day severe:    ${v.severe_loss_1d:,.0f}")
                print(f"    Total max loss:  ${v.total_max_loss:,.0f}")

            # Greeks
            if dashboard.greeks:
                g = dashboard.greeks
                gl_str = _styled("OK", "green") if dashboard.greeks_within_limits else _styled("BREACH", "red")
                print(f"\n  {_styled('Portfolio Greeks', 'bold')} [{gl_str}]")
                print(f"    Delta: {g.net_delta:+.4f}  (${g.delta_dollars:+,.0f})")
                print(f"    Gamma: {g.net_gamma:+.6f}")
                print(f"    Theta: {g.net_theta:+.4f}  (${g.theta_dollars_per_day:+,.2f}/day)")
                print(f"    Vega:  {g.net_vega:+.4f}")

            # Strategy concentration
            sc = dashboard.strategy_concentration
            sc_color = "yellow" if sc.is_concentrated else "green"
            print(f"\n  {_styled('Strategy Mix', 'bold')} [{_styled('CONCENTRATED' if sc.is_concentrated else 'OK', sc_color)}]")
            for strat, count in sorted(sc.by_strategy.items(), key=lambda x: -x[1]):
                bar = "#" * count
                print(f"    {strat:20s} {count}  {bar}")

            # Directional exposure
            de = dashboard.directional_exposure
            de_color = "yellow" if de.is_concentrated else "green"
            print(f"\n  {_styled('Directional Exposure', 'bold')} [{_styled(de.direction.upper(), de_color)}]")
            print(f"    Score:    {de.net_delta_score:+.2f}  "
                  f"(bull={de.bullish_positions} bear={de.bearish_positions} neutral={de.neutral_positions})")

            # Correlation
            if dashboard.correlation_risk:
                cr = dashboard.correlation_risk
                print(f"\n  {_styled('Correlation Risk', 'bold')}")
                print(f"    Effective positions: {cr.effective_positions:.1f} "
                      f"(diversification: {cr.diversification_score:.0%})")
                if cr.highly_correlated_pairs:
                    for a, b, c in cr.highly_correlated_pairs:
                        print(f"    {_styled(f'{a}/{b}: {c:.2f}', 'yellow')}")

            # Sector concentration
            if dashboard.sector_concentration:
                print(f"\n  {_styled('Sector Concentration', 'bold')}")
                for sector, pct in sorted(dashboard.sector_concentration.items(), key=lambda x: -x[1]):
                    bar = "#" * int(pct / 5)
                    print(f"    {sector:20s} {pct:5.1f}%  {bar}")

            # Macro
            print(f"\n  {_styled('Macro', 'bold')}")
            print(f"    Regime:   {dashboard.macro_regime}")
            print(f"    Size factor: {dashboard.macro_position_factor:.0%}")

            # Alerts
            if dashboard.alerts:
                print(f"\n  {_styled('Alerts', 'bold')}")
                for alert in dashboard.alerts:
                    print(f"    {_styled('!', 'red')} {alert}")

            # Commentary
            if dashboard.commentary:
                print(f"\n  {_styled('Commentary', 'dim')}")
                for line in dashboard.commentary:
                    print(f"    {line}")

            print(f"\n  {_styled('Note:', 'dim')} Using demo positions. "
                  f"eTrading provides real positions for live risk assessment.")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")
            traceback.print_exc()

    def do_overnight(self, arg: str) -> None:
        """Assess overnight gap risk for a position.\nUsage: overnight TICKER [--dte N] [--status safe|tested|breached]\n  Example: overnight GLD --dte 14 --status tested"""
        parts = arg.strip().split()
        if not parts:
            print("Usage: overnight TICKER [--dte N] [--status safe|tested|breached]")
            print("  --dte N:      days to expiration (default: 30)")
            print("  --status S:   position status: safe, tested, breached (default: safe)")
            return

        ticker = parts[0].upper()
        dte = 30
        position_status = "safe"
        i = 1
        while i < len(parts):
            if parts[i] == "--dte" and i + 1 < len(parts):
                try:
                    dte = int(parts[i + 1])
                except ValueError:
                    print(f"Invalid DTE: {parts[i + 1]}")
                    return
                i += 2
            elif parts[i] == "--status" and i + 1 < len(parts):
                position_status = parts[i + 1].lower()
                if position_status not in ("safe", "tested", "breached"):
                    print(f"Invalid status: '{position_status}'. Use: safe, tested, breached")
                    return
                i += 2
            else:
                i += 1

        try:
            from income_desk.trade_lifecycle import assess_overnight_risk

            ma = self._get_ma()
            regime = ma.regime.detect(ticker)

            result = assess_overnight_risk(
                trade_id=f"{ticker}-CLI",
                ticker=ticker,
                structure_type="iron_condor",
                order_side="credit",
                dte_remaining=dte,
                regime_id=int(regime.regime),
                position_status=position_status,
            )

            _print_header(f"{ticker} — Overnight Risk ({dte} DTE, {position_status})")

            level_colors = {
                "low": "green",
                "medium": "yellow",
                "high": "red",
                "close_before_close": "red",
            }
            level_color = level_colors.get(result.risk_level.value, "")
            level_label = result.risk_level.value.upper().replace("_", " ")
            print(f"\n  Risk Level: {_styled(level_label, level_color)}")
            print(f"  Regime:     R{regime.regime} ({regime.confidence:.0%})")

            if result.reasons:
                print(f"\n  Reasons:")
                for reason in result.reasons:
                    print(f"    - {reason}")

            print(f"\n  {_styled('Summary:', 'bold')} {result.summary}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_quality(self, arg: str) -> None:
        """Check execution quality for a trade.\nUsage: quality TICKER [STRATEGY]\n  STRATEGY: ic, ifly, calendar, diagonal, ratio (default: ic)\n  Requires --broker for live quotes."""
        parts = arg.strip().split()
        if not parts:
            print("Usage: quality TICKER [STRATEGY]")
            print("  STRATEGY: ic, ifly, calendar, diagonal, ratio (default: ic)")
            print("  Requires --broker for live quotes.")
            return

        ticker = parts[0].upper()
        strategy = parts[1].lower() if len(parts) > 1 else "ic"

        strategy_map = {
            "ic": "iron_condor",
            "iron_condor": "iron_condor",
            "ifly": "iron_butterfly",
            "iron_butterfly": "iron_butterfly",
            "calendar": "calendar",
            "cal": "calendar",
            "diagonal": "diagonal",
            "diag": "diagonal",
            "ratio": "ratio_spread",
            "ratio_spread": "ratio_spread",
        }
        play = strategy_map.get(strategy)
        if play is None:
            print(f"Unknown strategy: '{strategy}'. Use: ic, ifly, calendar, diagonal, ratio")
            return

        try:
            ma = self._get_ma()
            if not ma.quotes.has_broker:
                print(_styled(
                    "WARNING: No broker connected — execution quality requires live quotes.\n"
                    "For full data: analyzer-cli --broker\n", "yellow",
                ))
                return

            # Get opportunity assessment to obtain trade_spec
            method = getattr(ma.opportunity, f"assess_{play}")
            result = method(ticker)

            if not hasattr(result, "trade_spec") or result.trade_spec is None:
                print(f"No trade spec generated for {play.replace('_', ' ')} "
                      f"(verdict: {result.verdict.value})")
                return

            ts = result.trade_spec

            # Get quotes for all legs
            leg_quotes = ma.quotes.get_leg_quotes(ts.legs)

            from income_desk.execution_quality import validate_execution_quality

            eq = validate_execution_quality(ts, leg_quotes)

            _print_header(f"{ticker} — Execution Quality ({play.replace('_', ' ').title()})")

            verdict_colors = {"go": "green", "wide_spread": "yellow", "illiquid": "yellow", "no_quote": "red"}
            v_color = verdict_colors.get(eq.overall_verdict.value, "")
            tradeable_str = _styled("TRADEABLE", "green") if eq.tradeable else _styled("NOT TRADEABLE", "red")
            print(f"\n  Verdict:    {_styled(eq.overall_verdict.value.upper(), v_color)} — {tradeable_str}")

            if eq.total_spread_cost_pct is not None:
                print(f"  Spread cost: {eq.total_spread_cost_pct:.2f}% of underlying")

            if eq.legs:
                print(f"\n  Legs:")
                for lq in eq.legs:
                    leg_verdict_color = verdict_colors.get(lq.verdict.value, "")
                    bid_str = f"${lq.bid:.2f}" if lq.bid is not None else "N/A"
                    ask_str = f"${lq.ask:.2f}" if lq.ask is not None else "N/A"
                    spread_str = f"{lq.spread_pct:.1f}%" if lq.spread_pct is not None else "N/A"
                    oi_str = f"{lq.open_interest}" if lq.open_interest is not None else "N/A"
                    print(f"    {lq.strike:.0f} {lq.option_type}: "
                          f"bid {bid_str} / ask {ask_str} "
                          f"(spread {spread_str}, OI {oi_str}) "
                          f"[{_styled(lq.verdict.value.upper(), leg_verdict_color)}]")
                    if lq.issue:
                        print(f"      {_styled(lq.issue, 'yellow')}")

            print(f"\n  {_styled('Summary:', 'bold')} {eq.summary}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_performance(self, arg: str) -> None:
        """Analyze trade performance from historical outcomes.\nUsage: performance\n\nThis command requires TradeOutcome records from eTrading.\nmarket_analyzer provides the analysis functions; eTrading stores the data."""
        _print_header("Performance Analysis")
        print(f"\n  {_styled('Not available in standalone CLI.', 'yellow')}")
        print()
        print("  Performance analysis requires TradeOutcome records from eTrading.")
        print("  market_analyzer provides two pure functions for this:")
        print()
        print(f"  {_styled('compute_performance_report(outcomes) -> PerformanceReport', 'bold')}")
        print("    Accepts a list of TradeOutcome records, returns per-strategy stats,")
        print("    per-regime breakdowns, win rates, profit factors, and score correlation.")
        print()
        print(f"  {_styled('calibrate_weights(outcomes) -> CalibrationResult', 'bold')}")
        print("    Suggests regime-strategy weight adjustments based on actual results.")
        print()
        print("  Usage in eTrading:")
        print()
        print(f"    {_styled('from income_desk.performance import compute_performance_report, calibrate_weights', 'dim')}")
        print(f"    {_styled('from income_desk.models.feedback import TradeOutcome', 'dim')}")
        print()
        print(f"    {_styled('outcomes: list[TradeOutcome] = load_from_database()', 'dim')}")
        print(f"    {_styled('report = compute_performance_report(outcomes)', 'dim')}")
        print(f"    {_styled('calibration = calibrate_weights(outcomes)', 'dim')}")

    def do_registry(self, arg: str) -> None:
        """Browse market registry — instruments, markets, strategies.\nUsage: registry [TICKER|MARKET|strategies]\n  registry           — list markets\n  registry US        — US market info\n  registry INDIA     — India market info\n  registry NIFTY     — instrument info\n  registry SPY       — instrument info\n  registry strategies NIFTY — available strategies"""
        ma = self._get_ma()
        parts = arg.strip().split()
        registry = ma.registry

        if not parts:
            _print_header("Markets")
            for mid in ("US", "INDIA"):
                m = registry.get_market(mid)
                print(f"\n  {_styled(mid, 'bold')} ({m.currency})")
                print(f"    Timezone:   {m.timezone}")
                print(f"    Hours:      {m.open_time.strftime('%H:%M')}-{m.close_time.strftime('%H:%M')}")
                print(f"    Settlement: T+{m.settlement_days}")
                instruments = registry.list_instruments(market=mid)
                print(f"    Instruments: {len(instruments)}")
            return

        query = parts[0].upper()

        # Strategies for a ticker
        if query == "STRATEGIES" and len(parts) > 1:
            ticker = parts[1].upper()
            _print_header(f"Strategies for {ticker}")
            strategies = ["iron_condor", "iron_butterfly", "credit_spread", "debit_spread",
                          "calendar", "diagonal", "straddle", "strangle", "leaps",
                          "zero_dte", "ratio_spread", "pmcc", "earnings", "covered_call"]
            for s in strategies:
                available = registry.strategy_available(s, ticker)
                icon = _styled("YES", "green") if available else _styled("NO", "red")
                print(f"    {s:20s} {icon}")
            return

        # Try as market
        try:
            m = registry.get_market(query)
            _print_header(f"Market: {query}")
            print(f"  Currency:     {m.currency}")
            print(f"  Timezone:     {m.timezone}")
            print(f"  Hours:        {m.open_time.strftime('%H:%M')}-{m.close_time.strftime('%H:%M')}")
            print(f"  Settlement:   T+{m.settlement_days}")
            print(f"  Force close:  {m.force_close_time.strftime('%H:%M')}")
            instruments = registry.list_instruments(market=query)
            print(f"\n  Instruments ({len(instruments)}):")
            for inst in instruments[:25]:
                print(f"    {inst.ticker:12s} lot={inst.lot_size:5d}  strike_int={inst.strike_interval:6.1f}  "
                      f"{'0DTE' if inst.has_0dte else '    '} {'LEAP' if inst.has_leaps else '    '} "
                      f"{inst.settlement:8s} {inst.exercise_style}")
            if len(instruments) > 25:
                print(f"    ... and {len(instruments) - 25} more")
            return
        except KeyError:
            pass

        # Try as instrument
        try:
            inst = registry.get_instrument(query)
            _print_header(f"Instrument: {inst.ticker} ({inst.market})")
            print(f"  Lot size:       {inst.lot_size}")
            print(f"  Strike interval: {inst.strike_interval}")
            print(f"  Expiry types:   {', '.join(inst.expiry_types)}")
            if inst.weekly_expiry_day:
                print(f"  Weekly expiry:  {inst.weekly_expiry_day}")
            print(f"  Settlement:     {inst.settlement}")
            print(f"  Exercise:       {inst.exercise_style}")
            print(f"  0DTE:           {'Yes' if inst.has_0dte else 'No'}")
            print(f"  LEAPs:          {'Yes' if inst.has_leaps else 'No'}")
            print(f"  Max DTE:        {inst.max_dte}")
            print(f"  yfinance:       {inst.yfinance_symbol}")
            # Margin estimate
            m = registry.estimate_margin("iron_condor", inst.ticker, wing_width=5 if inst.market == "US" else 200)
            print(f"  Margin (IC):    {m.currency} {m.margin_amount:,.0f} ({m.method})")
            return
        except KeyError:
            pass

        print(f"  Unknown market or instrument: '{query}'")
        print("  Try: registry US, registry INDIA, registry SPY, registry NIFTY")

    def do_sharpe(self, arg: str) -> None:
        """Compute Sharpe ratio from trade outcomes.\nUsage: sharpe\n\nRequires TradeOutcome records from eTrading."""
        _print_header("Sharpe Ratio")
        print(f"\n  {_styled('Not available in standalone CLI.', 'yellow')}")
        print()
        print("  Requires TradeOutcome records from eTrading.")
        print(f"  {_styled('from income_desk import compute_sharpe', 'dim')}")
        print(f"  {_styled('result = compute_sharpe(outcomes, risk_free_rate=0.05)', 'dim')}")
        print(f"  {_styled('# -> SharpeResult(sharpe_ratio, sortino_ratio, annualized_return_pct, ...)', 'dim')}")

    def do_drawdown(self, arg: str) -> None:
        """Compute max drawdown from trade outcomes.\nUsage: drawdown\n\nRequires TradeOutcome records from eTrading."""
        _print_header("Drawdown Analysis")
        print(f"\n  {_styled('Not available in standalone CLI.', 'yellow')}")
        print()
        print("  Requires TradeOutcome records from eTrading.")
        print(f"  {_styled('from income_desk import compute_drawdown', 'dim')}")
        print(f"  {_styled('result = compute_drawdown(outcomes)', 'dim')}")
        print(f"  {_styled('# -> DrawdownResult(max_drawdown_pct, max_drawdown_dollars, ...)', 'dim')}")

    def do_drift(self, arg: str) -> None:
        """Detect strategy performance drift.\nUsage: drift\n\nRequires TradeOutcome records from eTrading."""
        _print_header("Strategy Drift Detection")
        print(f"\n  {_styled('Not available in standalone CLI.', 'yellow')}")
        print()
        print("  Requires TradeOutcome records from eTrading.")
        print(f"  {_styled('from income_desk import detect_drift', 'dim')}")
        print(f"  {_styled('alerts = detect_drift(outcomes, window=20)', 'dim')}")
        print(f"  {_styled('# -> list[DriftAlert] with severity WARNING/CRITICAL', 'dim')}")

    def do_bandit(self, arg: str) -> None:
        """Thompson Sampling strategy selection.\nUsage: bandit\n\nRequires trade history from eTrading."""
        _print_header("Thompson Sampling Bandits")
        print(f"\n  {_styled('Not available in standalone CLI.', 'yellow')}")
        print()
        print("  Requires trade outcome history from eTrading.")
        print(f"  {_styled('from income_desk import build_bandits, select_strategies', 'dim')}")
        print(f"  {_styled('bandits = build_bandits(outcomes)', 'dim')}")
        print(f"  {_styled('selected = select_strategies(bandits, regime_id, strategies, n=5)', 'dim')}")
        print(f"  {_styled('# -> [(StrategyType, sampled_score), ...]', 'dim')}")

    def do_margin(self, arg: str) -> None:
        """Estimate margin for a strategy on an instrument.\nUsage: margin TICKER [STRATEGY] [--width N]\n  margin NIFTY ic --width 200\n  margin SPY ic --width 5"""
        ma = self._get_ma()
        parts = arg.strip().split()
        if not parts:
            print("Usage: margin TICKER [STRATEGY] [--width N]")
            print("  STRATEGY: ic, cs, straddle, etc. (default: iron_condor)")
            print("  --width N: wing width in points (default: 5 for US, 200 for India)")
            return

        ticker = parts[0].upper()
        strategy = "iron_condor"
        width = None

        i = 1
        while i < len(parts):
            if parts[i] == "--width" and i + 1 < len(parts):
                try:
                    width = float(parts[i + 1])
                except ValueError:
                    print(f"Invalid width: {parts[i + 1]}")
                    return
                i += 2
            else:
                strategy = parts[i].lower()
                strategy_map = {"ic": "iron_condor", "cs": "credit_spread", "ds": "debit_spread",
                                "cal": "calendar", "ifly": "iron_butterfly", "str": "straddle"}
                strategy = strategy_map.get(strategy, strategy)
                i += 1

        registry = ma.registry
        try:
            inst = registry.get_instrument(ticker)
            if width is None:
                width = 5.0 if inst.market == "US" else 200.0
        except KeyError:
            if width is None:
                width = 5.0

        for contracts in (1, 2, 5, 10):
            m = registry.estimate_margin(strategy, ticker, wing_width=width, contracts=contracts)
            print(f"  {contracts:2d} contracts: {m.currency} {m.margin_amount:>10,.0f}  ({m.method})")

    def do_hedge(self, arg: str) -> None:
        """Recommend hedge for a position: hedge TICKER [SHARES] [--market US|India]

        Resolves best hedging approach (direct/futures/proxy) and shows ranked comparison.

        Examples:
            hedge SPY
            hedge SPY 100
            hedge RELIANCE 250 --market India
        """
        from income_desk.hedging import compare_hedge_methods

        ma = self._get_ma()
        parts = arg.strip().split()
        if not parts:
            print("Usage: hedge TICKER [SHARES] [--market US|India]")
            print("  Example: hedge SPY")
            print("  Example: hedge SPY 100")
            print("  Example: hedge RELIANCE 250 --market India")
            return

        ticker = parts[0].upper()
        shares = 100
        market = self._market.upper()

        i = 1
        while i < len(parts):
            if parts[i] == "--market" and i + 1 < len(parts):
                market = parts[i + 1].upper()
                i += 2
            else:
                try:
                    shares = int(parts[i])
                except ValueError:
                    print(f"Invalid shares: {parts[i]}")
                    return
                i += 1

        _print_header(f"Hedge Analysis: {ticker} ({shares} shares, {market})")

        try:
            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)
        except Exception as e:
            print(f"  {_styled(f'Error fetching data for {ticker}: {e}', 'red')}")
            return

        current_price = tech.current_price
        regime_id = int(regime.regime)
        atr = current_price * (tech.atr_pct or 1.5) / 100

        regime_name = {1: "R1 Low-Vol MR", 2: "R2 High-Vol MR",
                       3: "R3 Low-Vol Trend", 4: "R4 High-Vol Trend"}.get(
            regime_id, f"R{regime_id}")

        print(f"\n  Ticker:    {_styled(ticker, 'cyan')}")
        print(f"  Price:     ${current_price:,.2f}")
        print(f"  Shares:    {shares:,}")
        print(f"  Value:     ${shares * current_price:,.0f}")
        print(f"  Regime:    {_styled(regime_name, 'yellow')} ({regime.confidence:.0%})")
        print(f"  ATR:       {tech.atr_pct or 0:.2f}% (${atr:,.2f})")

        try:
            cmp = compare_hedge_methods(
                ticker=ticker,
                shares=shares,
                current_price=current_price,
                regime_id=regime_id,
                atr=atr,
                market=market,
            )
        except Exception as e:
            print(f"\n  {_styled(f'Hedge comparison error: {e}', 'red')}")
            return

        # Print recommendation
        rec = cmp.recommended
        if rec.available:
            print(f"\n  {_styled('RECOMMENDED:', 'bold')} {_styled(rec.hedge_type.upper().replace('_', ' '), 'green')} "
                  f"({rec.tier})")
            print(f"  {cmp.recommendation_rationale}")
        else:
            print(f"\n  {_styled('NO HEDGE AVAILABLE', 'red')}: {rec.unavailable_reason}")

        # Print comparison table
        rows = []
        for m in cmp.methods:
            avail_str = _styled("YES", "green") if m.available else _styled("no", "dim")
            cost_str = f"{m.cost_pct:.1f}%" if m.cost_pct is not None else "—"
            delta_str = f"{m.delta_reduction:.0%}" if m.delta_reduction else "—"
            hedge_name = m.hedge_type.replace("_", " ").title()
            reason = m.unavailable_reason or ""
            if len(reason) > 40:
                reason = reason[:37] + "..."
            rows.append([
                hedge_name,
                m.tier.value,
                avail_str,
                cost_str,
                delta_str,
                m.basis_risk,
                reason if not m.available else (", ".join(m.pros[:1]) if m.pros else ""),
            ])

        print()
        print(tabulate(
            rows,
            headers=["Method", "Tier", "Avail", "Cost%", "Delta↓", "Basis Risk", "Notes"],
            tablefmt="simple",
        ))

        # Show trade spec for recommended method
        if rec.available and rec.trade_spec:
            spec = rec.trade_spec
            print(f"\n  {_styled('Trade Spec:', 'bold')} {spec.description or spec.structure_type or 'hedge'}")
            for leg in spec.legs:
                print(f"    {leg.short_code}")
        print()

    def do_portfolio_hedge(self, arg: str) -> None:
        """Analyze hedging for entire demo portfolio: portfolio_hedge [--market US|India]

        Classifies all open positions, builds hedges for each, shows tier breakdown,
        total cost, and all TradeSpecs ready for execution.

        Requires demo portfolio (run: analyzer-cli --demo first).
        """
        from income_desk.demo import load_demo_portfolio
        from income_desk.hedging import analyze_portfolio_hedge

        market = self._market.upper()
        parts = arg.strip().split()
        i = 0
        while i < len(parts):
            if parts[i] == "--market" and i + 1 < len(parts):
                market = parts[i + 1].upper()
                i += 2
            else:
                i += 1

        port = load_demo_portfolio()
        if port is None:
            print("No demo portfolio. Run: analyzer-cli --demo")
            return

        if not port.positions:
            print("No open positions in demo portfolio.")
            return

        _print_header(f"Portfolio Hedge Analysis ({market})")

        ma = self._get_ma()

        # Build position dicts from open positions
        positions = []
        for p in port.positions:
            try:
                tech = ma.technicals.snapshot(p.ticker)
                current_price = tech.current_price
                atr_pct = tech.atr_pct or 1.5
            except Exception:
                current_price = p.entry_price
                atr_pct = 1.5
            contracts = p.contracts or 1
            # Approximate shares: 1 contract = 100 shares for US options
            shares = contracts * 100
            positions.append({
                "ticker": p.ticker,
                "shares": shares,
                "value": shares * current_price,
                "current_price": current_price,
                "atr": current_price * atr_pct / 100,
            })

        atr_by_ticker = {pos["ticker"]: pos["atr"] for pos in positions}
        account_nlv = port.current_nlv

        print(f"\n  Account NLV:    ${account_nlv:,.0f}")
        print(f"  Open positions: {len(positions)}")
        print(f"  Market:         {market}")

        try:
            analysis = analyze_portfolio_hedge(
                positions=positions,
                account_nlv=account_nlv,
                market=market,
                atr_by_ticker=atr_by_ticker,
            )
        except Exception as e:
            print(f"\n  {_styled(f'Portfolio hedge error: {e}', 'red')}")
            return

        # Tier breakdown
        print(f"\n  {_styled('TIER BREAKDOWN', 'bold')}")
        for tier, count in analysis.tier_counts.items():
            value = analysis.tier_values.get(tier, 0.0)
            print(f"    {tier:<22} {count:>3} positions  ${value:>10,.0f}")

        print(f"\n  Coverage:        {analysis.coverage_pct:.0%} of portfolio value")
        print(f"  Total hedge cost: ${analysis.total_hedge_cost:,.0f} ({analysis.hedge_cost_pct:.1f}%)")
        print(f"  Delta before:    {analysis.portfolio_delta_before:.2f}")
        print(f"  Delta after:     {analysis.portfolio_delta_after:.2f}")

        # Per-position detail
        print(f"\n  {_styled('PER-POSITION HEDGES', 'bold')}")
        rows = []
        for ph in analysis.position_hedges:
            tier_str = ph.tier.value if ph.tier else "—"
            hedge_str = (ph.hedge_type or "none").replace("_", " ").title()
            cost_str = f"${ph.cost_estimate:,.0f}" if ph.cost_estimate is not None else "—"
            rows.append([
                ph.ticker,
                f"${ph.position_value:,.0f}",
                tier_str,
                hedge_str,
                cost_str,
                f"{ph.delta_before:.2f} → {ph.delta_after:.2f}",
            ])
        print()
        print(tabulate(
            rows,
            headers=["Ticker", "Value", "Tier", "Method", "Cost", "Delta"],
            tablefmt="simple",
        ))

        # Alerts
        if analysis.alerts:
            print(f"\n  {_styled('ALERTS:', 'yellow')}")
            for alert in analysis.alerts:
                print(f"    {_styled('!', 'yellow')} {alert}")

        # Trade specs summary
        if analysis.trade_specs:
            print(f"\n  {_styled(f'{len(analysis.trade_specs)} TradeSpecs ready for execution', 'green')}")
            for spec in analysis.trade_specs[:5]:  # Show first 5
                print(f"    {spec.description or spec.structure_type or 'hedge'}: "
                      f"{', '.join(leg.short_code for leg in spec.legs[:2])}")
            if len(analysis.trade_specs) > 5:
                print(f"    ... and {len(analysis.trade_specs) - 5} more")

        print(f"\n  {analysis.summary}")
        print()

    def do_fno_coverage(self, arg: str) -> None:
        """Show F&O coverage for tickers: fno_coverage TICKER [TICKER...] [--market US|India]

        Classifies each ticker: direct (liquid options), futures, or proxy hedging available.

        Examples:
            fno_coverage SPY QQQ GLD TLT
            fno_coverage RELIANCE INFY TCS --market India
        """
        from income_desk.hedging import get_fno_coverage

        parts = arg.strip().split()
        if not parts:
            print("Usage: fno_coverage TICKER [TICKER...] [--market US|India]")
            print("  Example: fno_coverage SPY QQQ GLD TLT")
            print("  Example: fno_coverage RELIANCE INFY TCS --market India")
            return

        market = self._market.upper()
        tickers = []
        i = 0
        while i < len(parts):
            if parts[i] == "--market" and i + 1 < len(parts):
                market = parts[i + 1].upper()
                i += 2
            else:
                tickers.append(parts[i].upper())
                i += 1

        if not tickers:
            print("No tickers provided.")
            return

        _print_header(f"F&O Coverage: {', '.join(tickers)} ({market})")

        try:
            coverage = get_fno_coverage(tickers=tickers, market=market)
        except Exception as e:
            print(f"  {_styled(f'Error: {e}', 'red')}")
            return

        print(f"\n  Tickers:         {coverage.total_tickers}")
        print(f"  Direct (T1):     {coverage.direct_hedge_count}  (liquid options)")
        print(f"  Futures (T2):    {coverage.futures_hedge_count}  (futures hedging)")
        print(f"  Proxy only (T3): {coverage.proxy_only_count}   (index proxy)")
        print(f"  No hedge:        {coverage.no_hedge_count}")
        print(f"  Coverage:        {coverage.coverage_pct:.0%}  (direct + futures / total)")

        # Per-tier breakdown
        rows = []
        for tier, ticker_list in coverage.tier_breakdown.items():
            if ticker_list:
                for t in ticker_list:
                    tier_label = {
                        "direct": _styled("DIRECT", "green"),
                        "futures_synthetic": _styled("FUTURES", "yellow"),
                        "proxy_index": _styled("PROXY", "dim"),
                        "none": _styled("NONE", "red"),
                    }.get(tier, tier)
                    rows.append([t, tier_label])

        rows.sort(key=lambda r: r[0])
        print()
        print(tabulate(rows, headers=["Ticker", "Hedge Tier"], tablefmt="simple"))
        print(f"\n  {coverage.commentary}")
        print()

    def do_currency(self, arg: str) -> None:
        """Currency conversion and FX P&L decomposition.
        Usage: currency AMOUNT FROM TO [--entry-rate N]
        Example: currency 100000 INR USD
        Example: currency 5000 USD INR --entry-rate 82.5"""
        parts = arg.strip().split()
        if len(parts) < 3:
            print("Usage: currency AMOUNT FROM TO [--entry-rate N]")
            print("  Example: currency 100000 INR USD")
            print("  Example: currency 5000 USD INR --entry-rate 82.5")
            return

        try:
            amount = float(parts[0].replace(",", ""))
        except ValueError:
            print(f"Invalid amount: {parts[0]}")
            return

        from_ccy = parts[1].upper()
        to_ccy = parts[2].upper()

        entry_rate = None
        i = 3
        while i < len(parts):
            if parts[i] == "--entry-rate" and i + 1 < len(parts):
                try:
                    entry_rate = float(parts[i + 1])
                except ValueError:
                    print(f"Invalid entry rate: {parts[i + 1]}")
                    return
                i += 2
            else:
                i += 1

        _print_header("Currency Conversion")

        # Illustrative rate — not live
        illustrative_rate = 83.5  # USD/INR
        print(f"\n  {_styled('WARNING: Using illustrative USD/INR rate of 83.5', 'yellow')}")
        print(f"  {_styled('For live rates, use eTrading which fetches from broker.', 'dim')}")

        from income_desk.currency import CurrencyPair, convert_amount, compute_currency_pnl

        pair = CurrencyPair(
            base="USD", quote="INR", rate=illustrative_rate,
            as_of=date.today(),
        )
        rates = {"USD/INR": pair}

        try:
            converted = convert_amount(amount, from_ccy, to_ccy, rates)
        except KeyError:
            print(f"\n  {_styled(f'No exchange rate available for {from_ccy}/{to_ccy}', 'red')}")
            print(f"  Currently only USD/INR conversion is supported illustratively.")
            return

        print(f"\n  {from_ccy} {amount:>15,.2f}")
        print(f"  {to_ccy} {converted:>15,.2f}")
        print(f"  Rate: 1 USD = {illustrative_rate} INR")

        if entry_rate is not None:
            print(f"\n  {_styled('FX P&L Decomposition:', 'bold')}")

            # Determine which currency is local vs base
            if from_ccy == "INR" or to_ccy == "INR":
                local_ccy = "INR"
                base_ccy = "USD"
            else:
                local_ccy = from_ccy
                base_ccy = to_ccy

            # For illustration: assume trading P&L is 0, show pure FX impact
            pnl = compute_currency_pnl(
                ticker="PORTFOLIO",
                trading_pnl_local=0.0,
                position_value_local=amount if from_ccy == local_ccy else amount * illustrative_rate,
                local_currency=local_ccy,
                base_currency=base_ccy,
                fx_rate_at_entry=entry_rate,
                fx_rate_current=illustrative_rate,
            )
            print(f"  Entry rate:    1 USD = {entry_rate} INR")
            print(f"  Current rate:  1 USD = {illustrative_rate} INR")
            print(f"  FX change:     {pnl.fx_change_pct:+.2f}%")
            print(f"  FX P&L impact: {base_ccy} {pnl.currency_pnl_base:+,.2f}")
            if pnl.currency_pnl_base < 0:
                print(f"  {_styled('INR depreciated — position worth less in USD', 'red')}")
            elif pnl.currency_pnl_base > 0:
                print(f"  {_styled('INR appreciated — position worth more in USD', 'green')}")
        print()

    def do_exposure(self, arg: str) -> None:
        """Show cross-market portfolio exposure.
        Usage: exposure
        Note: Requires position data from eTrading. Shows API usage."""
        _print_header("Cross-Market Exposure")
        print(f"\n  {_styled('Not available in standalone CLI.', 'yellow')}")
        print()
        print("  Requires position data from eTrading for multi-market exposure.")
        print(f"  {_styled('from income_desk import compute_portfolio_exposure, CurrencyPair, PositionExposure', 'dim')}")
        print(f"  {_styled('positions = [PositionExposure(ticker=\"SPY\", market=\"US\", currency=\"USD\", ...)]', 'dim')}")
        print(f"  {_styled('rates = {{\"USD/INR\": CurrencyPair(base=\"USD\", quote=\"INR\", rate=83.5, ...)}}', 'dim')}")
        print(f"  {_styled('exposure = compute_portfolio_exposure(positions, rates)', 'dim')}")
        print(f"  {_styled('# -> PortfolioExposure with currency_risk_pct, converted totals', 'dim')}")
        print()
        print(f"  {_styled('from income_desk import assess_currency_exposure', 'dim')}")
        print(f"  {_styled('hedge = assess_currency_exposure(positions, rates)', 'dim')}")
        print(f"  {_styled('# -> CurrencyHedgeAssessment with recommendation + risk_per_1pct_fx_move', 'dim')}")
        print()

    def do_crossmarket(self, arg: str) -> None:
        """Cross-market correlation analysis (US -> India).
        Usage: crossmarket [US_TICKER INDIA_TICKER]
          Default: SPY NIFTY
        Example: crossmarket SPY NIFTY
                 crossmarket QQQ BANKNIFTY"""

        ma = self._get_ma()
        parts = arg.strip().split()
        us_ticker = parts[0] if len(parts) > 0 else "SPY"
        india_ticker = parts[1] if len(parts) > 1 else "NIFTY"

        # Fetch OHLCV for both
        try:
            us_ohlcv = ma.data_service.get_ohlcv(us_ticker)
        except Exception as e:
            print(f"  {_styled(f'Failed to fetch {us_ticker}: {e}', 'red')}")
            return
        try:
            india_ohlcv = ma.data_service.get_ohlcv(india_ticker)
        except Exception as e:
            print(f"  {_styled(f'Failed to fetch {india_ticker}: {e}', 'red')}")
            return

        # Get regimes
        try:
            us_regime = ma.regime.detect(us_ticker)
        except Exception:
            print(f"  {_styled(f'Failed to detect regime for {us_ticker}', 'yellow')}")
            return
        try:
            india_regime = ma.regime.detect(india_ticker)
        except Exception:
            print(f"  {_styled(f'Failed to detect regime for {india_ticker}', 'yellow')}")
            return

        # Run analysis
        from income_desk.cross_market import analyze_cross_market

        result = analyze_cross_market(
            us_ticker,
            india_ticker,
            us_ohlcv,
            india_ohlcv,
            int(us_regime.regime),
            int(india_regime.regime),
        )

        # Display
        _print_header(f"Cross-Market: {us_ticker} (US) -> {india_ticker} (India)")
        print(f"\n  Correlation (20d): {result.correlation_20d:.2f}")
        print(f"  Correlation (60d): {result.correlation_60d:.2f}")
        print(f"  US last close:     {result.us_close_return_pct:+.2f}%")
        print(
            f"  India predicted gap: {result.predicted_india_gap_pct:+.2f}% "
            f"(confidence R^2={result.prediction_confidence:.2f})"
        )
        print(
            f"  Regime sync:       {result.sync_status} "
            f"(US=R{result.source_regime}, India=R{result.target_regime})"
        )

        if result.signals:
            print(f"\n  Signals:")
            for s in result.signals:
                color = (
                    "green"
                    if s.direction == "bullish"
                    else "red"
                    if s.direction == "bearish"
                    else "yellow"
                )
                print(f"    [{_styled(s.direction.upper(), color)}] {s.description}")
        else:
            print(f"\n  No significant cross-market signals.")
        print()

    def do_india_context(self, arg: str) -> None:
        """India market context with US lead-lag analysis.
        Usage: india_context"""

        ma = self._get_ma()

        _print_header("India Market Context")

        # Get US and India regimes
        us_regime = None
        try:
            us_regime = ma.regime.detect("SPY")
            print(f"\n  US (SPY):      R{us_regime.regime} ({us_regime.confidence:.0%})")
        except Exception:
            print(f"\n  US (SPY):      {_styled('unavailable', 'yellow')}")

        nifty_regime = None
        try:
            nifty_regime = ma.regime.detect("NIFTY")
            print(f"  India (NIFTY): R{nifty_regime.regime} ({nifty_regime.confidence:.0%})")
        except Exception:
            print(f"  India (NIFTY): {_styled('unavailable', 'yellow')}")

        try:
            bn_regime = ma.regime.detect("BANKNIFTY")
            print(f"  BankNIFTY:     R{bn_regime.regime} ({bn_regime.confidence:.0%})")
        except Exception:
            pass

        # Cross-market analysis
        if us_regime and nifty_regime:
            from income_desk.cross_market import analyze_cross_market

            try:
                us_ohlcv = ma.data_service.get_ohlcv("SPY")
                nifty_ohlcv = ma.data_service.get_ohlcv("NIFTY")

                cm = analyze_cross_market(
                    "SPY",
                    "NIFTY",
                    us_ohlcv,
                    nifty_ohlcv,
                    int(us_regime.regime),
                    int(nifty_regime.regime),
                )

                print(f"\n  US -> India Correlation: {cm.correlation_20d:.2f} (20d)")
                print(f"  US last close: {cm.us_close_return_pct:+.2f}%")
                print(f"  India predicted gap: {cm.predicted_india_gap_pct:+.2f}%")
                print(f"  Regime sync: {cm.sync_status}")

                for s in cm.signals:
                    color = (
                        "green"
                        if s.direction == "bullish"
                        else "red"
                        if s.direction == "bearish"
                        else "yellow"
                    )
                    print(f"  [{_styled(s.direction.upper(), color)}] {s.description}")
            except Exception as e:
                print(f"\n  {_styled(f'Cross-market analysis failed: {e}', 'yellow')}")

        # India-specific checks
        print(f"\n  India Market Rules:")
        print(f"  Settlement: Cash (index), Physical (stocks)")
        print(f"  Exercise: European (no early assignment)")
        print(f"  Weekly expiry: NIFTY=Thu, BANKNIFTY=Wed, FINNIFTY=Tue")
        print(f"  Max DTE: ~90 days (no LEAPs)")
        print()

    def do_scan_universe(self, arg: str) -> None:
        """Browse built-in scanning universes — no broker needed.\nUsage: scan_universe [PRESET] [--market US|INDIA]\n  Presets: income, directional, us_etf, us_mega, sector_etf, india_fno, india_index, nifty50, macro, all\n  Example: scan_universe income\n           scan_universe nifty50\n           scan_universe directional --market INDIA"""
        ma = self._get_ma()
        parts = arg.strip().split()
        preset = None
        market = None

        i = 0
        while i < len(parts):
            if parts[i] == "--market" and i + 1 < len(parts):
                market = parts[i + 1].upper()
                i += 2
            else:
                preset = parts[i].lower()
                i += 1

        registry = ma.registry
        presets = ["income", "directional", "us_etf", "us_mega", "sector_etf",
                   "india_fno", "india_index", "nifty50", "macro", "all"]

        if not preset:
            _print_header("Scanning Universes (Built-in)")
            print("\n  No broker needed — curated instrument lists.\n")
            for p in presets:
                tickers = registry.get_universe(preset=p, market=market)
                print(f"  {p:15s}  {len(tickers):3d} tickers  {', '.join(tickers[:6])}{'...' if len(tickers) > 6 else ''}")
            print(f"\n  Usage: scan_universe PRESET [--market US|INDIA]")
            return

        tickers = registry.get_universe(preset=preset, market=market)
        mkt_label = f" ({market})" if market else ""
        _print_header(f"Universe: {preset}{mkt_label} — {len(tickers)} tickers")

        if not tickers:
            print(f"\n  No tickers match preset '{preset}'{mkt_label}.")
            return

        for ticker in tickers:
            try:
                inst = registry.get_instrument(ticker)
                liq = {"high": _styled("HIGH", "green"), "medium": _styled("MED", "yellow"),
                       "low": _styled("LOW", "red"), "none": _styled("NONE", "dim"),
                       "unknown": "?"}.get(inst.options_liquidity, "?")
                print(f"  {ticker:12s} {inst.market:5s} {inst.asset_type:7s} {inst.sector:18s} "
                      f"lot={inst.lot_size:5d}  opts={liq}")
            except KeyError:
                print(f"  {ticker:12s} (no registry data)")

        print(f"\n  To scan these: screen {' '.join(tickers[:5])}...")
        print(f"  To rank these: rank {' '.join(tickers[:5])}...")

    def do_leg_plan(self, arg: str) -> None:
        """Plan leg execution order for India single-leg markets.\nUsage: leg_plan TICKER [STRATEGY]\n  Example: leg_plan NIFTY ic\n           leg_plan BANKNIFTY straddle"""
        ma = self._get_ma()
        parts = arg.strip().split()
        if not parts:
            print("Usage: leg_plan TICKER [STRATEGY]")
            print("  Shows the safest execution order for multi-leg trades in India.")
            print("  India brokers execute one leg at a time — order matters!")
            return

        ticker = parts[0].upper()
        strategy = parts[1].lower() if len(parts) > 1 else "ic"
        strategy_map = {"ic": "iron_condor", "ifly": "iron_butterfly",
                        "cs": "credit_spread", "str": "straddle", "strg": "strangle"}
        strategy = strategy_map.get(strategy, strategy)

        # Get a trade spec
        assess_map = {
            "iron_condor": "assess_iron_condor",
            "iron_butterfly": "assess_iron_butterfly",
            "straddle": "assess_mean_reversion",  # Proxy
        }
        method = assess_map.get(strategy)
        if method is None:
            print(f"  Strategy '{strategy}' not supported for leg planning.")
            return

        try:
            result = getattr(ma.opportunity, method)(ticker)
            spec = result.trade_spec
            if spec is None:
                print(f"  No trade spec generated for {ticker} {strategy} (verdict: {result.verdict})")
                return
        except Exception as e:
            print(f"  Failed: {e}")
            return

        from income_desk.leg_execution import plan_leg_execution

        # Detect market
        market = "INDIA"
        try:
            inst = ma.registry.get_instrument(ticker)
            market = inst.market
        except KeyError:
            pass

        plan = plan_leg_execution(spec, market=market)

        _print_header(f"Leg Execution Plan: {ticker} {spec.strategy_badge}")
        print(f"\n  Market: {plan.market} ({'single-leg execution' if plan.market == 'INDIA' else 'multi-leg native'})")
        print(f"  Total legs: {plan.total_legs}")
        print(f"  Estimated slippage: {plan.total_estimated_slippage_pct:.1f}%")

        print(f"\n  Execution Order:")
        for el in plan.execution_order:
            risk_color = {"safe": "green", "moderate": "yellow", "high": "red", "critical": "red"}
            color = risk_color.get(el.risk_after, "white")
            print(f"    {el.sequence}. {el.action_desc:30s} [{_styled(el.risk_after.upper(), color)}]")
            print(f"       {el.risk_description}")

        print(f"\n  Max exposure: {plan.max_naked_exposure}")
        print(f"\n  Abort rule:")
        print(f"    {plan.abort_rule}")

        if plan.notes:
            print(f"\n  Notes:")
            for note in plan.notes:
                print(f"    - {note}")

    def do_research(self, arg: str) -> None:
        """Full macro research report — assets, sentiment, regime, economics.
        Usage: research [daily|weekly|monthly] [--fred-key KEY]"""

        ma = self._get_ma()
        parts = arg.strip().split()
        timeframe = "daily"
        fred_key = None

        i = 0
        while i < len(parts):
            if parts[i] == "--fred-key" and i + 1 < len(parts):
                fred_key = parts[i + 1]
                i += 2
            elif parts[i] in ("daily", "weekly", "monthly"):
                timeframe = parts[i]
                i += 1
            else:
                i += 1

        _print_header(f"Macro Research Report ({timeframe})")
        print(f"\n  Fetching data for research assets...")

        # Fetch all research tickers
        from income_desk.macro_research import (
            RESEARCH_ASSETS,
            generate_research_report,
        )

        # Get DataService
        ds = None
        if ma.regime and hasattr(ma.regime, "data_service"):
            ds = ma.regime.data_service
        if ds is None:
            from income_desk import DataService

            ds = DataService()

        data: dict = {}
        for ticker in RESEARCH_ASSETS:
            try:
                data[ticker] = ds.get_ohlcv(ticker)
            except Exception:
                pass  # Graceful — skip missing tickers

        print(f"  Fetched {len(data)}/{len(RESEARCH_ASSETS)} assets")

        # Get SPY P/E
        spy_pe = None
        try:
            import yfinance as yf

            spy_pe = yf.Ticker("SPY").info.get("trailingPE")
        except Exception:
            pass

        report = generate_research_report(data, timeframe, fred_key, spy_pe)

        # Display
        print(f"\n{report.research_note}")

        # Regime
        regime = report.regime
        color_map = {
            "risk_on": "green",
            "risk_off": "red",
            "stagflation": "red",
            "reflation": "yellow",
            "deflationary": "red",
            "transition": "yellow",
        }
        print(
            f"\n  Regime: {_styled(regime.regime.value.upper(), color_map.get(regime.regime.value, 'white'))}"
            f" ({regime.confidence:.0%})"
        )
        for ev in regime.evidence:
            print(f"    - {ev}")
        print(f"  Position size: {regime.position_size_factor:.0%}")
        if regime.favor_sectors:
            print(f"  Favor: {', '.join(regime.favor_sectors)}")
        if regime.avoid_sectors:
            print(f"  Avoid: {', '.join(regime.avoid_sectors)}")

        # Sentiment
        s = report.sentiment
        sent_color = {
            "extreme_fear": "red",
            "fear": "red",
            "neutral": "yellow",
            "greed": "green",
            "extreme_greed": "green",
        }
        print(
            f"\n  Sentiment: {_styled(s.overall_sentiment.upper(), sent_color.get(s.overall_sentiment, 'white'))}"
            f" ({s.sentiment_score:+.2f})"
        )
        print(f"    VIX: {s.vix_level:.1f} ({s.vix_trend}, {s.vix_term_structure})")
        if s.gold_silver_ratio:
            print(f"    Gold/Silver ratio: {s.gold_silver_ratio:.1f}")
        if s.equity_risk_premium is not None:
            print(f"    Equity risk premium: {s.equity_risk_premium:.1f}%")

        # Top/bottom assets
        if report.asset_scores:
            sorted_scores = sorted(
                report.asset_scores, key=lambda sc: sc.period_return_pct, reverse=True
            )
            print(f"\n  Asset Performance ({timeframe}):")
            for score in sorted_scores[:5]:
                sig_color = "green" if score.signal_score > 0 else "red"
                print(
                    f"    {score.name:25s} {score.period_return_pct:+6.1f}%"
                    f"  RSI={score.rsi:4.0f}"
                    f"  {_styled(score.signal.upper(), sig_color)}"
                )
            if len(sorted_scores) > 10:
                print(f"    ...")
            for score in sorted_scores[-3:]:
                sig_color = "green" if score.signal_score > 0 else "red"
                print(
                    f"    {score.name:25s} {score.period_return_pct:+6.1f}%"
                    f"  RSI={score.rsi:4.0f}"
                    f"  {_styled(score.signal.upper(), sig_color)}"
                )

        # Key signals
        if report.key_signals:
            print(f"\n  Key Signals:")
            for sig in report.key_signals[:8]:
                print(f"    - {sig}")

        # India
        print(f"\n  India Context:")
        for c in report.india.commentary:
            print(f"    {c}")

        # Economics
        if report.economics and report.economics.data_source == "fred":
            print(f"\n  Economic Fundamentals (FRED):")
            for c in report.economics.commentary:
                print(f"    {c}")
        elif report.economics:
            print(f"\n  {_styled(report.economics.commentary[0], 'yellow')}")

    def do_stress_test(self, arg: str) -> None:
        """Run stress test scenarios against portfolio.
        Usage: stress_test [SCENARIO]
          Scenarios: market_down_1pct, market_down_3pct, market_down_5pct, market_down_10pct,
                     market_up_3pct, vix_spike_50pct, vix_spike_100pct, flash_crash,
                     black_monday, covid_march_2020, india_crash, fed_surprise
          No args = run standard suite (7 scenarios)"""

        from income_desk.stress_testing import (
            run_stress_suite,
            run_stress_test,
            get_predefined_scenario,
        )
        from income_desk.risk import PortfolioPosition

        # Demo positions (in real use, eTrading passes from portfolio DB)
        demo_positions = [
            PortfolioPosition(
                ticker="SPY", structure_type="iron_condor", direction="neutral",
                sector="index", max_loss=420, notional_value=66000,
                delta=0.03, theta=0.04, vega=-0.10, dte_remaining=25,
            ),
            PortfolioPosition(
                ticker="QQQ", structure_type="credit_spread", direction="bullish",
                sector="tech", max_loss=300, notional_value=48000,
                delta=-0.15, theta=0.02, vega=-0.05, dte_remaining=18,
            ),
            PortfolioPosition(
                ticker="GLD", structure_type="equity_long", direction="bullish",
                sector="commodity", max_loss=5000, notional_value=25000,
                delta=1.0, theta=0, vega=0, dte_remaining=0,
            ),
        ]
        account_nlv = 50000

        _print_header("Portfolio Stress Test")
        print(f"\n  Demo portfolio: {len(demo_positions)} positions, NLV=${account_nlv:,}")
        for p in demo_positions:
            print(f"    {p.ticker:6s} {p.structure_type:15s} max_loss=${p.max_loss:,.0f}")

        parts = arg.strip().split()

        if parts:
            # Single scenario
            scenario_name = parts[0].lower()
            try:
                params = get_predefined_scenario(scenario_name)
                result = run_stress_test(demo_positions, params, account_nlv)

                print(f"\n  Scenario: {result.scenario.name}")
                print(f"  {result.scenario.description}")
                color = (
                    "red" if result.total_impact_pct < -3
                    else "yellow" if result.total_impact_pct < -1
                    else "green"
                )
                print(
                    f"\n  Portfolio Impact: "
                    f"{_styled(f'{result.total_impact_dollars:+,.0f} ({result.total_impact_pct:+.1f}%)', color)}"
                )
                print(
                    f"  Survives: "
                    f"{'YES' if result.portfolio_survives else _styled('NO', 'red')}"
                )
                print(f"\n  Position Details:")
                for pi in result.position_impacts:
                    ic = (
                        "red" if pi.new_status in ("breached", "max_loss")
                        else "yellow" if pi.new_status == "tested"
                        else "green"
                    )
                    print(
                        f"    {pi.ticker:6s} {pi.impact_dollars:+8,.0f}  "
                        f"[{_styled(pi.new_status.upper(), ic)}] {pi.action_needed}"
                    )
                print(f"\n  Action: {result.recommended_action}")
            except KeyError:
                print(f"  Unknown scenario: '{scenario_name}'")
                print(f"  Available: market_down_1pct, market_down_3pct, market_down_5pct,")
                print(f"    vix_spike_50pct, flash_crash, black_monday, fed_surprise, india_crash")
        else:
            # Full suite
            suite = run_stress_suite(demo_positions, account_nlv)
            print(f"\n  {suite.summary}")
            print()
            for result in suite.results:
                color = (
                    "red" if result.total_impact_pct < -3
                    else "yellow" if result.total_impact_pct < -1
                    else "green"
                )
                survives = (
                    "OK" if result.portfolio_survives
                    else _styled("FAIL", "red")
                )
                print(
                    f"  {result.scenario.name:25s} "
                    f"{_styled(f'{result.total_impact_pct:+6.1f}%', color)} "
                    f"({result.total_impact_dollars:+8,.0f})  {survives}"
                )

            print(f"\n  Worst: {suite.worst_scenario} ({suite.worst_impact_pct:+.1f}%)")
            print(
                f"  Survives all: "
                f"{'YES' if suite.survives_all else _styled('NO — REDUCE RISK', 'red')}"
            )

    def do_stock(self, arg: str) -> None:
        """Analyze a stock — fundamental + technical multi-strategy scoring.
        Usage: stock TICKER [--horizon long|medium]
        Example: stock RELIANCE --horizon long
                 stock AAPL"""
        parts = arg.strip().split()
        if not parts:
            print("Usage: stock TICKER [--horizon long|medium]")
            return

        ticker = parts[0].upper()
        horizon_str = "long"
        i = 1
        while i < len(parts):
            if parts[i] == "--horizon" and i + 1 < len(parts):
                horizon_str = parts[i + 1].lower()
                i += 2
            else:
                i += 1

        from income_desk.equity_research import (
            InvestmentHorizon,
            analyze_stock,
        )

        horizon_map = {
            "long": InvestmentHorizon.LONG_TERM,
            "long_term": InvestmentHorizon.LONG_TERM,
            "medium": InvestmentHorizon.MEDIUM_TERM,
            "medium_term": InvestmentHorizon.MEDIUM_TERM,
            "med": InvestmentHorizon.MEDIUM_TERM,
        }
        horizon = horizon_map.get(horizon_str, InvestmentHorizon.LONG_TERM)

        try:
            # Fetch OHLCV for technical signals
            ma = self._get_ma()
            ohlcv = None
            try:
                ohlcv = ma.data.get_ohlcv(ticker)
            except Exception:
                print(_styled("  (No OHLCV data — technicals unavailable)", "dim"))

            rec = analyze_stock(
                ticker, ohlcv=ohlcv, horizon=horizon, market=self._market,
            )

            _print_header(f"Stock Analysis: {rec.name} ({rec.ticker})")
            print(f"\n  Sector:    {rec.sector}")
            print(f"  Market:    {rec.market}")
            print(f"  Horizon:   {rec.horizon.value}")
            f = rec.fundamental
            if f.market_cap is not None:
                if f.market_cap >= 1e12:
                    mcap_str = f"${f.market_cap / 1e12:.1f}T"
                elif f.market_cap >= 1e9:
                    mcap_str = f"${f.market_cap / 1e9:.1f}B"
                else:
                    mcap_str = f"${f.market_cap / 1e6:.0f}M"
                print(f"  Market Cap: {mcap_str} ({f.market_cap_category})")

            # Overall rating
            rating_color = {
                "strong_buy": "green", "buy": "green",
                "hold": "yellow", "sell": "red", "strong_sell": "red",
            }.get(rec.rating.value, "dim")
            print(
                f"\n  Composite: {rec.composite_score:.0f}/100 — "
                f"{_styled(rec.rating.value.upper().replace('_', ' '), rating_color)}"
            )
            print(f"  Best fit:  {rec.primary_strategy.value}")

            # Fundamentals snapshot
            print(f"\n  {_styled('Fundamentals:', 'bold')}")
            vals = []
            if f.pe_trailing is not None:
                vals.append(f"P/E {f.pe_trailing:.1f}")
            if f.pe_forward is not None:
                vals.append(f"Fwd P/E {f.pe_forward:.1f}")
            if f.pb_ratio is not None:
                vals.append(f"P/B {f.pb_ratio:.1f}")
            if f.peg_ratio is not None:
                vals.append(f"PEG {f.peg_ratio:.1f}")
            if vals:
                print(f"    Valuation: {' | '.join(vals)}")

            prof = []
            if f.roe is not None:
                prof.append(f"ROE {f.roe:.0f}%")
            if f.profit_margin is not None:
                prof.append(f"Margin {f.profit_margin:.0f}%")
            if f.revenue_growth_yoy is not None:
                prof.append(f"Rev Growth {f.revenue_growth_yoy:.0f}%")
            if prof:
                print(f"    Profitability: {' | '.join(prof)}")

            bal = []
            if f.debt_to_equity is not None:
                bal.append(f"D/E {f.debt_to_equity:.0f}")
            if f.current_ratio is not None:
                bal.append(f"Current {f.current_ratio:.1f}")
            if f.dividend_yield is not None and f.dividend_yield > 0:
                bal.append(f"Yield {f.dividend_yield:.1f}%")
            if bal:
                print(f"    Balance Sheet: {' | '.join(bal)}")

            if f.from_52w_high_pct is not None:
                print(f"    52-wk position: {f.from_52w_high_pct:.0f}% from high")

            # Entry/Stop/Target
            if rec.entry_price is not None:
                print(f"\n  {_styled('Entry Plan:', 'bold')}")
                print(f"    Entry:   ${rec.entry_price:.2f}")
                if rec.stop_loss is not None:
                    print(f"    Stop:    ${rec.stop_loss:.2f}")
                if rec.target_price is not None:
                    print(f"    Target:  ${rec.target_price:.2f}")
                if rec.risk_reward is not None:
                    print(f"    R:R      {rec.risk_reward:.1f}")

            # Strategy scores
            print(f"\n  {_styled('Strategy Scores:', 'bold')}")
            for s in rec.strategy_scores:
                bar_len = int(s.score / 5)
                bar = "|" * bar_len
                s_color = (
                    "green" if s.score >= 60
                    else "yellow" if s.score >= 45
                    else "red"
                )
                print(
                    f"    {s.strategy.value:20s} "
                    f"{_styled(f'{s.score:5.0f}', s_color)} "
                    f"{_styled(bar, s_color)} "
                    f"({s.rating.value})"
                )

            # Thesis
            print(f"\n  {_styled('Thesis:', 'bold')}")
            print(f"    {rec.thesis}")

            # Top strengths & risks
            all_strengths = []
            all_risks = []
            for s in rec.strategy_scores:
                all_strengths.extend(s.strengths[:1])
                all_risks.extend(s.risks[:1])
            if all_strengths:
                print(f"\n  {_styled('Key Strengths:', 'bold')}")
                for st in dict.fromkeys(all_strengths):  # dedupe, preserve order
                    print(f"    {_styled('+', 'green')} {st}")
            if all_risks:
                print(f"\n  {_styled('Key Risks:', 'bold')}")
                for rk in dict.fromkeys(all_risks):
                    print(f"    {_styled('-', 'red')} {rk}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")
            traceback.print_exc()

    def do_stock_screen(self, arg: str) -> None:
        """Screen stocks for a strategy.
        Usage: stock_screen [--strategy value|growth|dividend|quality|turnaround] [--preset nifty50|us_mega|us_etf] [--market US|INDIA] [--horizon long|medium] [--top N] [TICKERS...]
        Example: stock_screen --strategy value --preset nifty50
                 stock_screen --strategy dividend --preset us_mega
                 stock_screen AAPL MSFT GOOGL AMZN"""
        parts = arg.strip().split()

        strategy_str: str | None = None
        preset: str | None = None
        market_str: str | None = None
        horizon_str = "long"
        top_n = 10
        explicit_tickers: list[str] = []

        i = 0
        while i < len(parts):
            if parts[i] == "--strategy" and i + 1 < len(parts):
                strategy_str = parts[i + 1].lower()
                i += 2
            elif parts[i] == "--preset" and i + 1 < len(parts):
                preset = parts[i + 1].lower()
                i += 2
            elif parts[i] == "--market" and i + 1 < len(parts):
                market_str = parts[i + 1].upper()
                i += 2
            elif parts[i] == "--horizon" and i + 1 < len(parts):
                horizon_str = parts[i + 1].lower()
                i += 2
            elif parts[i] == "--top" and i + 1 < len(parts):
                try:
                    top_n = int(parts[i + 1])
                except ValueError:
                    pass
                i += 2
            elif not parts[i].startswith("--"):
                explicit_tickers.append(parts[i].upper())
                i += 1
            else:
                i += 1

        from income_desk.equity_research import (
            InvestmentHorizon,
            InvestmentStrategy,
            screen_stocks,
        )
        from income_desk.registry import MarketRegistry

        # Resolve strategy
        strategy_map = {
            "value": InvestmentStrategy.VALUE,
            "growth": InvestmentStrategy.GROWTH,
            "dividend": InvestmentStrategy.DIVIDEND_INCOME,
            "quality": InvestmentStrategy.QUALITY_MOMENTUM,
            "quality_momentum": InvestmentStrategy.QUALITY_MOMENTUM,
            "turnaround": InvestmentStrategy.TURNAROUND,
            "sector": InvestmentStrategy.SECTOR_ROTATION,
            "blend": InvestmentStrategy.BLEND,
        }
        strategy = strategy_map.get(strategy_str) if strategy_str else None

        # Resolve horizon
        horizon_map = {
            "long": InvestmentHorizon.LONG_TERM,
            "long_term": InvestmentHorizon.LONG_TERM,
            "medium": InvestmentHorizon.MEDIUM_TERM,
            "medium_term": InvestmentHorizon.MEDIUM_TERM,
            "med": InvestmentHorizon.MEDIUM_TERM,
        }
        horizon = horizon_map.get(horizon_str, InvestmentHorizon.LONG_TERM)

        # Resolve market
        market = market_str or self._market

        # Resolve tickers
        if explicit_tickers:
            tickers = explicit_tickers
        elif preset:
            reg = MarketRegistry()
            tickers = reg.get_universe(preset=preset, market=market if not preset.startswith("india") else "INDIA")
            if not tickers:
                print(f"{_styled('No tickers found for preset:', 'yellow')} {preset}")
                return
        else:
            # Default presets by market
            reg = MarketRegistry()
            if market.upper() == "INDIA":
                tickers = reg.get_universe(preset="nifty50", market="INDIA")
            else:
                tickers = reg.get_universe(preset="us_mega", market="US")
                if not tickers:
                    tickers = reg.get_universe(preset="us_etf", market="US")

        if not tickers:
            print("No tickers to screen. Provide tickers or use --preset.")
            return

        print(f"  Screening {len(tickers)} tickers ({market}, {horizon.value})...")

        try:
            # Optionally fetch OHLCV for technical signals
            ma = self._get_ma()
            ohlcv_data: dict = {}
            for t in tickers:
                try:
                    ohlcv_data[t] = ma.data.get_ohlcv(t)
                except Exception:
                    pass  # Skip tickers with no OHLCV

            result = screen_stocks(
                tickers,
                ohlcv_data=ohlcv_data if ohlcv_data else None,
                strategy=strategy,
                horizon=horizon,
                market=market,
                top_n=top_n,
            )

            strat_label = strategy.value if strategy else "blend"
            _print_header(f"Equity Screen: {strat_label} ({market}, {horizon.value})")
            print(f"\n  {result.summary}")

            if not result.top_picks:
                print("\n  No stocks passed the minimum score threshold.")
            else:
                # Table of top picks
                rows = []
                for r in result.top_picks:
                    best_strat = r.primary_strategy.value[:10]
                    pe_str = f"{r.fundamental.pe_trailing:.1f}" if r.fundamental.pe_trailing else "—"
                    roe_str = f"{r.fundamental.roe:.0f}%" if r.fundamental.roe else "—"
                    div_str = f"{r.fundamental.dividend_yield:.1f}%" if r.fundamental.dividend_yield and r.fundamental.dividend_yield > 0 else "—"
                    from52 = f"{r.fundamental.from_52w_high_pct:.0f}%" if r.fundamental.from_52w_high_pct is not None else "—"
                    rating_color = {
                        "strong_buy": "green", "buy": "green",
                        "hold": "yellow", "sell": "red", "strong_sell": "red",
                    }.get(r.rating.value, "dim")
                    rows.append({
                        "Ticker": r.ticker,
                        "Name": r.name[:18],
                        "Score": f"{r.composite_score:.0f}",
                        "Rating": _styled(r.rating.value.replace("_", " ").upper(), rating_color),
                        "Strategy": best_strat,
                        "P/E": pe_str,
                        "ROE": roe_str,
                        "Div": div_str,
                        "52wk": from52,
                        "Sector": r.sector[:12],
                    })

                print()
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

            # Sector allocation
            if result.sector_allocation:
                print(f"\n  {_styled('Sector Allocation:', 'bold')}")
                for sector, count in sorted(result.sector_allocation.items(), key=lambda x: -x[1]):
                    print(f"    {sector}: {count}")

            # Top pick thesis
            if result.top_picks:
                top = result.top_picks[0]
                print(f"\n  {_styled('Top Pick:', 'bold')} {top.ticker}")
                print(f"    {top.thesis}")

            for c in result.commentary:
                print(f"\n  {_styled(c, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")
            traceback.print_exc()

    # --- Capital Deployment Commands ---

    def do_valuation(self, arg: str) -> None:
        """Show market valuation assessment.\nUsage: valuation TICKER [--pe 22.5] [--div-yield 1.3] [--bond-yield 7.1]\n       valuation SPY\n       valuation NIFTY --pe 20.5 --bond-yield 7.1"""
        parts = arg.strip().split()
        if not parts:
            print("Usage: valuation TICKER [--pe PE] [--div-yield YIELD] [--bond-yield YIELD]")
            return

        ticker = parts[0].upper()
        current_pe: float | None = None
        div_yield: float | None = None
        bond_yield: float | None = None

        i = 1
        while i < len(parts):
            if parts[i] == "--pe" and i + 1 < len(parts):
                current_pe = float(parts[i + 1])
                i += 2
            elif parts[i] == "--div-yield" and i + 1 < len(parts):
                div_yield = float(parts[i + 1])
                i += 2
            elif parts[i] == "--bond-yield" and i + 1 < len(parts):
                bond_yield = float(parts[i + 1])
                i += 2
            else:
                i += 1

        try:
            ma = self._get_ma()
            ohlcv = ma.data_service.get_ohlcv(ticker)
            from income_desk.capital_deployment import compute_market_valuation

            val = compute_market_valuation(
                ticker=ticker,
                ohlcv=ohlcv,
                current_pe=current_pe,
                dividend_yield=div_yield,
                bond_yield=bond_yield,
            )

            _print_header(f"Valuation — {val.name} ({val.ticker})")
            zone_colors = {
                "deep_value": "green", "value": "green",
                "fair": "cyan", "expensive": "yellow", "bubble": "red",
            }
            color = zone_colors.get(val.zone, "white")
            print(f"\n  Zone:           {_styled(val.zone.upper(), color)} (score: {val.zone_score:+.2f})")

            if val.current_pe is not None:
                print(f"  P/E:            {val.current_pe:.1f}")
            if val.pe_5y_avg is not None:
                print(f"  P/E (5y avg):   {val.pe_5y_avg:.1f}")
            if val.pe_percentile is not None:
                print(f"  PE percentile:  {val.pe_percentile:.0f}th")
            if val.earnings_yield is not None:
                print(f"  Earnings yield: {val.earnings_yield:.2f}%")
            if val.dividend_yield is not None:
                print(f"  Dividend yield: {val.dividend_yield:.1f}%")
            print(f"  From 52w high:  {val.from_52w_high_pct:+.1f}%")
            print(f"  From 52w low:   {val.from_52w_low_pct:+.1f}%")

            if val.historical_return_at_this_pe:
                print(f"\n  {_styled(val.historical_return_at_this_pe, 'dim')}")

            if val.commentary:
                print()
                for c in val.commentary:
                    print(f"  {c}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_deploy(self, arg: str) -> None:
        """Create a systematic capital deployment plan.\nUsage: deploy AMOUNT [--months 12] [--market INDIA] [--risk moderate]\n       deploy 5000000 --months 12 --market INDIA --risk moderate\n       deploy 200000 --months 6 --market US --risk aggressive"""
        parts = arg.strip().split()
        if not parts:
            print("Usage: deploy AMOUNT [--months N] [--market INDIA|US] [--risk conservative|moderate|aggressive]")
            return

        try:
            total_capital = float(parts[0].replace(",", ""))
        except ValueError:
            print("First argument must be a number (total capital).")
            return

        months = 12
        market = self._market.upper()
        risk = "moderate"
        regime_id = 2
        val_zone = "fair"

        i = 1
        while i < len(parts):
            if parts[i] == "--months" and i + 1 < len(parts):
                months = int(parts[i + 1])
                i += 2
            elif parts[i] == "--market" and i + 1 < len(parts):
                market = parts[i + 1].upper()
                i += 2
            elif parts[i] == "--risk" and i + 1 < len(parts):
                risk = parts[i + 1].lower()
                i += 2
            elif parts[i] == "--regime" and i + 1 < len(parts):
                regime_id = int(parts[i + 1])
                i += 2
            elif parts[i] == "--valuation" and i + 1 < len(parts):
                val_zone = parts[i + 1].lower()
                i += 2
            else:
                i += 1

        is_india = market in ("INDIA", "IN")
        currency = "INR" if is_india else "USD"

        try:
            from income_desk.capital_deployment import recommend_core_portfolio

            portfolio = recommend_core_portfolio(
                total_capital=total_capital,
                currency=currency,
                market=market,
                regime_id=regime_id,
                valuation_zone=val_zone,
                risk_tolerance=risk,
                deployment_months=months,
            )

            _print_header(f"Capital Deployment Plan — {portfolio.market}")
            print(f"\n  Total Capital:  {currency} {total_capital:,.0f}")
            print(f"  Risk Profile:   {risk}")
            print(f"  Deploy Over:    {months} months")
            print(f"  Allocation:     {portfolio.total_equity_pct:.0f}% equity | "
                  f"{portfolio.total_gold_pct:.0f}% gold | "
                  f"{portfolio.total_debt_pct:.0f}% debt")

            # Core Holdings
            print(f"\n  {_styled('Core Holdings:', 'bold')}")
            rows = []
            for h in portfolio.holdings:
                amt = total_capital * (h.allocation_pct / 100.0)
                rows.append({
                    "Ticker": h.ticker,
                    "Category": h.category,
                    "Alloc%": f"{h.allocation_pct:.1f}%",
                    "Amount": f"{currency} {amt:,.0f}",
                    "Entry": h.entry_approach,
                })
            print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

            # Deployment Schedule (first 3 months + last)
            if portfolio.deployment:
                dep = portfolio.deployment
                print(f"\n  {_styled('Deployment Schedule:', 'bold')}")
                print(f"  Base monthly: {currency} {dep.base_monthly:,.0f}")
                print(f"  Regime:       {dep.regime_adjustment}")
                print(f"  Valuation:    {dep.valuation_adjustment}")

                allocs = dep.monthly_allocations
                show = allocs[:3]
                if len(allocs) > 3:
                    show.append(allocs[-1])

                dep_rows = []
                for ma_item in show:
                    note = ma_item.acceleration_reason or ma_item.deceleration_reason or ""
                    dep_rows.append({
                        "Month": ma_item.month,
                        "Date": str(ma_item.date),
                        "Total": f"{currency} {ma_item.amount:,.0f}",
                        "Equity": f"{currency} {ma_item.equity_amount:,.0f}",
                        "Gold": f"{currency} {ma_item.gold_amount:,.0f}",
                        "Debt": f"{currency} {ma_item.debt_amount:,.0f}",
                        "Note": note[:50] if note else "",
                    })
                if len(allocs) > 4:
                    dep_rows.insert(3, {
                        "Month": "...", "Date": "...", "Total": "...",
                        "Equity": "...", "Gold": "...", "Debt": "...", "Note": "",
                    })
                print(tabulate(dep_rows, headers="keys", tablefmt="simple", stralign="right"))

            # Commentary
            if portfolio.commentary:
                print()
                for c in portfolio.commentary:
                    print(f"  {_styled(c, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_allocate(self, arg: str) -> None:
        """Show recommended asset allocation.\nUsage: allocate [--market INDIA] [--regime risk_off] [--valuation value] [--risk moderate] [--age 35]\n       allocate --market INDIA --regime risk_off --valuation deep_value\n       allocate --risk conservative --age 45"""
        parts = arg.strip().split()

        market = self._market.upper()
        regime = "risk_off"
        val_zone = "value"
        risk = "moderate"
        age: int | None = None

        i = 0
        while i < len(parts):
            if parts[i] == "--market" and i + 1 < len(parts):
                market = parts[i + 1].upper()
                i += 2
            elif parts[i] == "--regime" and i + 1 < len(parts):
                regime = parts[i + 1].lower()
                i += 2
            elif parts[i] == "--valuation" and i + 1 < len(parts):
                val_zone = parts[i + 1].lower()
                i += 2
            elif parts[i] == "--risk" and i + 1 < len(parts):
                risk = parts[i + 1].lower()
                i += 2
            elif parts[i] == "--age" and i + 1 < len(parts):
                age = int(parts[i + 1])
                i += 2
            else:
                i += 1

        try:
            from income_desk.capital_deployment import compute_asset_allocation

            alloc = compute_asset_allocation(
                market=market,
                regime=regime,
                valuation_zone=val_zone,
                risk_tolerance=risk,
                age=age,
            )

            _print_header(f"Asset Allocation — {market}")
            print(f"\n  Equity:  {_styled(f'{alloc.equity_pct:.1f}%', 'bold')}")
            print(f"  Gold:    {alloc.gold_pct:.1f}%")
            print(f"  Debt:    {alloc.debt_pct:.1f}%")
            print(f"  Cash:    {alloc.cash_pct:.1f}%")

            print(f"\n  {_styled('Equity Sub-Allocation:', 'bold')}")
            for k, v in alloc.equity_split.items():
                print(f"    {k:25s} {v:.0f}%")

            print(f"\n  Regime:     {_styled(alloc.regime_context, 'dim')}")
            print(f"  Rebalance:  {alloc.rebalance_trigger}")

            if alloc.rationale:
                print(f"\n  {_styled('Rationale:', 'bold')}")
                for r in alloc.rationale:
                    print(f"    {r}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_rebalance(self, arg: str) -> None:
        """Check if portfolio needs rebalancing.\nUsage: rebalance EQUITY_PCT GOLD_PCT DEBT_PCT CASH_PCT --target EQ_T GOLD_T DEBT_T CASH_T --value PORTFOLIO_VALUE [--threshold 5]\n       rebalance 70 12 8 10 --target 60 15 15 10 --value 5000000\n       rebalance 55 20 20 5 --target 60 15 15 10 --value 200000 --threshold 3"""
        parts = arg.strip().split()

        if len(parts) < 4:
            print("Usage: rebalance EQ% GOLD% DEBT% CASH% --target EQ% GOLD% DEBT% CASH% --value VALUE [--threshold 5]")
            return

        try:
            current = {
                "equity": float(parts[0]),
                "gold": float(parts[1]),
                "debt": float(parts[2]),
                "cash": float(parts[3]),
            }
        except (ValueError, IndexError):
            print("First 4 args must be current allocation percentages (equity gold debt cash).")
            return

        target = {"equity": 60.0, "gold": 15.0, "debt": 15.0, "cash": 10.0}
        portfolio_value = 0.0
        threshold = 5.0

        i = 4
        while i < len(parts):
            if parts[i] == "--target" and i + 4 < len(parts):
                target = {
                    "equity": float(parts[i + 1]),
                    "gold": float(parts[i + 2]),
                    "debt": float(parts[i + 3]),
                    "cash": float(parts[i + 4]),
                }
                i += 5
            elif parts[i] == "--value" and i + 1 < len(parts):
                portfolio_value = float(parts[i + 1].replace(",", ""))
                i += 2
            elif parts[i] == "--threshold" and i + 1 < len(parts):
                threshold = float(parts[i + 1])
                i += 2
            else:
                i += 1

        if portfolio_value <= 0:
            print("--value PORTFOLIO_VALUE is required (total portfolio value).")
            return

        try:
            from income_desk.capital_deployment import check_rebalance

            result = check_rebalance(
                current_allocation=current,
                target_allocation=target,
                portfolio_value=portfolio_value,
                drift_threshold_pct=threshold,
            )

            _print_header("Rebalance Check")
            status = _styled("REBALANCE NEEDED", "yellow") if result.needs_rebalance else _styled("ON TARGET", "green")
            print(f"\n  Status:    {status}")
            print(f"  Trigger:   {result.trigger}")

            print(f"\n  {_styled('Asset Drift:', 'bold')}")
            rows = []
            for a in result.actions:
                action_color = "green" if a.action == "buy" else ("red" if a.action == "sell" else "dim")
                rows.append({
                    "Asset": a.asset.title(),
                    "Current": f"{a.current_pct:.1f}%",
                    "Target": f"{a.target_pct:.1f}%",
                    "Drift": f"{a.drift_pct:+.1f}%",
                    "Action": a.action.upper(),
                    "Amount": f"{a.amount:,.0f}" if a.amount > 0 else "-",
                })
            print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

            if result.commentary:
                print()
                for c in result.commentary:
                    print(f"  {_styled(c, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_leap_vs_stock(self, arg: str) -> None:
        """Compare LEAP call vs stock purchase for a ticker.\nUsage: leap_vs_stock TICKER [--price 150] [--iv 0.25] [--div-yield 1.5] [--dte 365]\n       leap_vs_stock AAPL\n       leap_vs_stock MSFT --price 420 --iv 0.22 --div-yield 0.8"""
        parts = arg.strip().split()
        if not parts:
            print("Usage: leap_vs_stock TICKER [--price PRICE] [--iv IV] [--div-yield PCT] [--dte DAYS]")
            return

        ticker = parts[0].upper()
        price: float | None = None
        iv = 0.20
        div_yield = 0.0
        dte = 365
        leap_premium: float | None = None
        leap_strike: float | None = None

        i = 1
        while i < len(parts):
            if parts[i] == "--price" and i + 1 < len(parts):
                price = float(parts[i + 1])
                i += 2
            elif parts[i] == "--iv" and i + 1 < len(parts):
                iv = float(parts[i + 1])
                i += 2
            elif parts[i] == "--div-yield" and i + 1 < len(parts):
                div_yield = float(parts[i + 1])
                i += 2
            elif parts[i] == "--dte" and i + 1 < len(parts):
                dte = int(parts[i + 1])
                i += 2
            elif parts[i] == "--premium" and i + 1 < len(parts):
                leap_premium = float(parts[i + 1])
                i += 2
            elif parts[i] == "--strike" and i + 1 < len(parts):
                leap_strike = float(parts[i + 1])
                i += 2
            else:
                i += 1

        try:
            # Auto-fetch price if not provided
            if price is None:
                ma = self._get_ma()
                ohlcv = ma.data_service.get_ohlcv(ticker)
                price = float(ohlcv["Close"].iloc[-1])

            from income_desk.capital_deployment import compare_leap_vs_stock

            result = compare_leap_vs_stock(
                ticker=ticker,
                current_price=price,
                dividend_yield_pct=div_yield,
                leap_premium=leap_premium,
                leap_strike=leap_strike,
                leap_dte=dte,
                iv=iv,
            )

            _print_header(f"LEAP vs Stock — {ticker} @ ${price:,.2f}")

            # Stock side
            print(f"\n  {_styled('Stock Purchase (100 shares):', 'bold')}")
            print(f"    Cost:            ${result.stock_cost:,.0f}")
            print(f"    Breakeven:       ${result.stock_breakeven:,.2f}")
            print(f"    Annual Dividend: ${result.stock_annual_dividend:,.0f}")
            print(f"    Max Loss:        {result.stock_max_loss}")

            # LEAP side
            print(f"\n  {_styled('LEAP Call:', 'bold')}")
            print(f"    Strike:          ${result.leap_strike:,.2f} ({result.leap_dte} DTE)")
            print(f"    Cost:            ${result.leap_cost:,.0f}")
            print(f"    Delta:           {result.leap_delta:.2f}")
            print(f"    Breakeven:       ${result.leap_breakeven:,.2f}")
            print(f"    Daily Theta:     ${result.leap_daily_theta:,.2f}")
            print(f"    Annual Theta:    ${result.leap_annual_theta_cost:,.0f}")
            print(f"    Expiration:      {result.leap_expiration}")
            print(f"    Max Loss:        {result.leap_max_loss}")

            # Comparison
            print(f"\n  {_styled('Comparison:', 'bold')}")
            print(f"    Capital Efficiency:       {result.capital_efficiency:.1f}x")
            print(f"    Capital Saved:            ${result.leap_capital_saved:,.0f}")
            print(f"    Dividend Forgone:         ${result.dividend_forgone:,.0f}/yr")
            print(f"    Theta Cost:               ${result.theta_cost_annual:,.0f}/yr")
            print(f"    Interest on Saved Capital:${result.interest_on_saved_capital:,.0f}/yr")
            print(f"    Net Annual Cost of LEAP:  ${result.net_annual_cost_of_leap:,.0f}")

            # Verdict
            color = "green" if result.leap_advantage else "yellow"
            print(f"\n  Verdict: {_styled(result.verdict, color)}")
            for r in result.rationale:
                print(f"    {r}")

            # When to use each
            print(f"\n  {_styled('LEAP best when:', 'dim')}")
            for item in result.leap_best_when:
                print(f"    - {item}")
            print(f"\n  {_styled('Stock best when:', 'dim')}")
            for item in result.stock_best_when:
                print(f"    - {item}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_wheel(self, arg: str) -> None:
        """Analyze the Wheel strategy for a ticker.\nUsage: wheel TICKER [--price 150] [--iv 0.25] [--regime 1] [--dte 35] [--put-delta 0.30]\n       wheel AAPL\n       wheel MSFT --price 420 --iv 0.30 --regime 2"""
        parts = arg.strip().split()
        if not parts:
            print("Usage: wheel TICKER [--price PRICE] [--iv IV] [--regime 1-4] [--dte DAYS] [--put-delta DELTA]")
            return

        ticker = parts[0].upper()
        price: float | None = None
        iv = 0.20
        regime_id = 1
        dte = 35
        put_delta = 0.30
        call_delta = 0.30
        div_yield = 0.0

        i = 1
        while i < len(parts):
            if parts[i] == "--price" and i + 1 < len(parts):
                price = float(parts[i + 1])
                i += 2
            elif parts[i] == "--iv" and i + 1 < len(parts):
                iv = float(parts[i + 1])
                i += 2
            elif parts[i] == "--regime" and i + 1 < len(parts):
                regime_id = int(parts[i + 1])
                i += 2
            elif parts[i] == "--dte" and i + 1 < len(parts):
                dte = int(parts[i + 1])
                i += 2
            elif parts[i] == "--put-delta" and i + 1 < len(parts):
                put_delta = float(parts[i + 1])
                i += 2
            elif parts[i] == "--call-delta" and i + 1 < len(parts):
                call_delta = float(parts[i + 1])
                i += 2
            elif parts[i] == "--div-yield" and i + 1 < len(parts):
                div_yield = float(parts[i + 1])
                i += 2
            else:
                i += 1

        try:
            # Auto-fetch price if not provided
            if price is None:
                ma = self._get_ma()
                ohlcv = ma.data_service.get_ohlcv(ticker)
                price = float(ohlcv["Close"].iloc[-1])

            from income_desk.capital_deployment import analyze_wheel_strategy

            result = analyze_wheel_strategy(
                ticker=ticker,
                current_price=price,
                iv=iv,
                regime_id=regime_id,
                put_delta=put_delta,
                call_delta=call_delta,
                dte=dte,
                dividend_yield_pct=div_yield,
            )

            _print_header(f"Wheel Strategy — {ticker} @ ${price:,.2f}")

            # Phase 1: Cash-Secured Put
            print(f"\n  {_styled('Phase 1: Cash-Secured Put', 'bold')}")
            print(f"    Strike:            ${result.put_strike:,.2f}")
            print(f"    Premium:           ${result.put_premium:,.0f}")
            print(f"    DTE:               {result.put_dte} days")
            print(f"    Annualized Yield:  {result.put_annualized_yield:.1f}%")
            print(f"    Breakeven:         ${result.put_breakeven:,.2f}")
            print(f"    Capital Required:  ${result.put_capital_required:,.0f}")

            # Phase 2: Covered Call
            print(f"\n  {_styled('Phase 2: Covered Call (if assigned)', 'bold')}")
            print(f"    Strike:            ${result.call_strike:,.2f}")
            print(f"    Premium:           ${result.call_premium:,.0f}")
            print(f"    DTE:               {result.call_dte} days")
            print(f"    Annualized Yield:  {result.call_annualized_yield:.1f}%")

            # Full Wheel Metrics
            print(f"\n  {_styled('Full Wheel Metrics:', 'bold')}")
            print(f"    Total Premium:       ${result.total_premium_if_wheeled:,.0f}")
            print(f"    Effective Cost Basis:${result.effective_cost_basis:,.2f}")
            print(f"    Cost Reduction:      {result.cost_reduction_pct:.1f}%")
            print(f"    Annualized Yield:    {result.annualized_wheel_yield:.1f}%")
            print(f"    Combined Breakeven:  ${result.call_breakeven:,.2f}")

            # Risk Assessment
            print(f"\n  {_styled('Risk Assessment:', 'bold')}")
            print(f"    Max Loss:            {result.max_loss_scenario}")
            print(f"    Assignment Prob:     {result.assignment_probability}")

            # Regime suitability
            regime_color = "green" if regime_id in (1, 2) else "yellow" if regime_id == 3 else "red"
            print(f"    Regime:              {_styled(result.regime_suitability, regime_color)}")

            # Vs stock
            print(f"\n  {_styled('vs Stock:', 'bold')} {result.vs_stock_advantage}")

            # Verdict
            if "ATTRACTIVE" in result.verdict:
                v_color = "green"
            elif "AVOID" in result.verdict:
                v_color = "red"
            elif "CAUTION" in result.verdict:
                v_color = "yellow"
            else:
                v_color = "cyan"
            print(f"\n  Verdict: {_styled(result.verdict, v_color)}")
            for r in result.rationale:
                print(f"    {r}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_assignment(self, arg: str) -> None:
        """Handle an assignment/exercise event and recommend: sell, wheel, or cover.\n\nUsage: assignment TICKER STRIKE [put|call] [CONTRACTS] [--nlv NLV] [--bp BP] [--iv IV_RANK]\n\nExamples:\n    assignment SPY 650 put\n    assignment IWM 240 put 2\n    assignment SPY 660 call\n    assignment IWM 240 put 1 --nlv 80000 --bp 50000 --iv 45"""
        parts = arg.strip().split()
        if len(parts) < 2:
            print("Usage: assignment TICKER STRIKE [put|call] [CONTRACTS] [--nlv NLV] [--bp BP] [--iv IV_RANK]")
            return

        ticker = parts[0].upper()
        try:
            strike_price = float(parts[1])
        except ValueError:
            print(f"Invalid strike price: {parts[1]}")
            return

        # Optional positional: assignment type and contracts
        assignment_type_str = "put"
        contracts = 1
        if len(parts) > 2 and not parts[2].startswith("--"):
            assignment_type_str = parts[2].lower()
        if len(parts) > 3 and not parts[3].startswith("--"):
            try:
                contracts = int(parts[3])
            except ValueError:
                pass

        # Parse optional flags
        account_nlv: float | None = None
        available_bp: float | None = None
        iv_rank: float | None = None
        i = 4
        while i < len(parts):
            if parts[i] == "--nlv" and i + 1 < len(parts):
                account_nlv = float(parts[i + 1])
                i += 2
            elif parts[i] == "--bp" and i + 1 < len(parts):
                available_bp = float(parts[i + 1])
                i += 2
            elif parts[i] == "--iv" and i + 1 < len(parts):
                iv_rank = float(parts[i + 1])
                i += 2
            else:
                i += 1

        from income_desk.models.assignment import AssignmentType
        if "call" in assignment_type_str:
            assignment_type = AssignmentType.CALL_ASSIGNED
        else:
            assignment_type = AssignmentType.PUT_ASSIGNED

        try:
            ma = self._get_ma()
            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)
            current_price = tech.current_price
            atr = tech.atr
            atr_pct = (atr / current_price * 100) if current_price > 0 else 1.5

            # Auto-detect ETF via registry
            is_etf = True
            try:
                from income_desk.registry import MarketRegistry
                inst = MarketRegistry().get_instrument(ticker)
                if inst:
                    is_etf = inst.asset_class in ("equity_etf", "etf")
            except Exception:
                pass

            # Use defaults for NLV/BP if not provided
            if account_nlv is None:
                account_nlv = 100000.0
                print(f"  {_styled('NOTE:', 'yellow')} Using default NLV $100,000 — pass --nlv for accurate sizing")
            if available_bp is None:
                available_bp = account_nlv * 0.50
                print(f"  {_styled('NOTE:', 'yellow')} Using default BP ${available_bp:,.0f} (50% of NLV) — pass --bp for accuracy")

            from income_desk.features.assignment_handler import handle_assignment
            result = handle_assignment(
                ticker=ticker,
                assignment_type=assignment_type,
                strike_price=strike_price,
                contracts=contracts,
                current_price=current_price,
                regime_id=regime.regime,
                regime_confidence=regime.confidence,
                atr=atr,
                atr_pct=atr_pct,
                account_nlv=account_nlv,
                available_bp=available_bp,
                iv_rank=iv_rank,
                is_etf=is_etf,
            )

            # --- Display ---
            _print_header(f"Assignment Handler — {ticker} @ ${current_price:,.2f}")

            type_label = "PUT ASSIGNED" if assignment_type == AssignmentType.PUT_ASSIGNED else "CALL ASSIGNED"
            print(f"\n  {_styled('Event:', 'bold')}          {type_label} — {contracts} contract(s), strike ${strike_price:,.2f}")
            print(f"  {_styled('Shares:', 'bold')}         {result.shares}")
            print(f"  {_styled('Current Price:', 'bold')}  ${current_price:,.2f}")

            # P&L
            pnl_color = "green" if result.unrealized_pnl >= 0 else "red"
            pnl_sign = "+" if result.unrealized_pnl >= 0 else ""
            print(f"  {_styled('Unrealized P&L:', 'bold')} {_styled(f'{pnl_sign}${result.unrealized_pnl:,.0f} ({pnl_sign}{result.unrealized_pnl_pct:.1%})', pnl_color)}")

            # Capital
            print(f"\n  {_styled('Capital Impact:', 'bold')}")
            print(f"    Tied Up:   ${result.capital_tied_up:,.0f} ({result.capital_pct_of_nlv:.1%} of NLV)")
            margin_color = "red" if result.margin_impact == "margin_call" else ("yellow" if result.margin_impact == "margin_warning" else "green")
            print(f"    Margin:    {_styled(result.margin_impact, margin_color)}")

            # Regime
            regime_color = "green" if regime.regime in (1, 2) else ("yellow" if regime.regime == 3 else "red")
            print(f"\n  {_styled('Regime:', 'bold')}         {_styled(f'R{regime.regime} ({regime.confidence:.0%})', regime_color)} — {result.regime_rationale}")

            # Decision
            action_color = {
                "sell_immediately": "red",
                "hold_and_wheel": "green",
                "hold_core": "cyan",
                "partial_sell": "yellow",
                "cover_short": "red",
            }.get(result.recommended_action, "white")
            urgency_color = "red" if result.urgency == "immediate" else ("yellow" if result.urgency == "today" else "green")

            print(f"\n  {_styled('Decision:', 'bold')}       {_styled(result.recommended_action.upper(), action_color)}")
            print(f"  {_styled('Urgency:', 'bold')}         {_styled(result.urgency, urgency_color)}")

            print(f"\n  {_styled('Reasons:', 'bold')}")
            for r in result.reasons:
                print(f"    • {r}")

            # Response TradeSpec
            if result.response_trade_spec:
                ts = result.response_trade_spec
                print(f"\n  {_styled('Response Trade:', 'bold')}")
                print(f"    Structure: {ts.structure_type}")
                print(f"    Rationale: {ts.spec_rationale}")
                if ts.legs:
                    leg = ts.legs[0]
                    print(f"    Action:    {leg.action.value} {leg.quantity} shares at market")

            # Wheel TradeSpec
            if result.wheel_trade_spec:
                wts = result.wheel_trade_spec
                print(f"\n  {_styled('Wheel Trade (Covered Call):', 'bold')}")
                if wts.legs:
                    leg = wts.legs[0]
                    print(f"    Strike:    ${leg.strike:,.2f} ({leg.strike_label})")
                    print(f"    Exp:       {leg.expiration} ({leg.days_to_expiry} DTE)")
                    print(f"    Action:    {leg.action.value} {leg.quantity} contract(s)")
                print(f"    Exit:      {wts.exit_summary}")
                print(f"    Rationale: {result.wheel_rationale}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")
            import traceback as _tb
            _tb.print_exc()

    def do_optimal_dte(self, arg: str) -> None:
        """Find optimal DTE for a ticker: optimal_dte TICKER

        Compares theta/IV ratio across expirations and recommends the best DTE
        for the current regime.
        """
        ticker = arg.strip().upper() or "SPY"
        try:
            regime = self.ma.regime.detect(ticker)
            vol = self.ma.vol_surface.compute(ticker)
            if vol is None:
                print(f"No vol surface data for {ticker}")
                return

            from income_desk.features.dte_optimizer import select_optimal_dte
            result = select_optimal_dte(vol, regime.regime.value, "iron_condor")

            print(f"\nOPTIMAL DTE — {ticker} — R{regime.regime.value}")
            print("-" * 50)
            print(f"Recommended: {result.recommended_dte} DTE ({result.recommended_expiration})")
            print(f"IV at expiry: {result.iv_at_expiration:.1%}")
            print(f"Theta proxy:  {result.theta_proxy:.4f}")
            print(f"Regime pref:  {result.regime_preference}")
            print()
            if result.all_candidates:
                print("All candidates:")
                for c in result.all_candidates:
                    marker = " <-- BEST" if c.get("dte") == result.recommended_dte else ""
                    print(f"  {c.get('dte', '?'):3d} DTE | IV {c.get('iv', 0):.1%} | theta_proxy {c.get('theta_proxy', 0):.4f}{marker}")
            print("-" * 50)
        except Exception as e:
            print(f"Error: {e}")

    def do_exit_intelligence(self, arg: str) -> None:
        """Exit intelligence for a hypothetical position: exit_intelligence TICKER [DAYS_HELD] [PROFIT_PCT]

        Shows regime stop, time-adjusted target, and theta decay analysis.

        Examples:
            exit_intelligence SPY
            exit_intelligence SPY 10 0.30
        """
        parts = arg.strip().split()
        ticker = parts[0].upper() if parts else "SPY"
        days_held = int(parts[1]) if len(parts) > 1 else 10
        profit_pct = float(parts[2]) if len(parts) > 2 else 0.25

        try:
            regime = self.ma.regime.detect(ticker)

            from income_desk.features.exit_intelligence import (
                compute_regime_stop,
                compute_time_adjusted_target,
                compute_remaining_theta_value,
            )

            # Regime stop
            stop = compute_regime_stop(regime.regime.value, "iron_condor")
            print(f"\nEXIT INTELLIGENCE — {ticker} — R{regime.regime.value}")
            print("-" * 50)
            print(f"Regime Stop:    {stop.base_multiplier:.1f}x credit ({stop.rationale})")

            # Time-adjusted target (assuming 30 DTE entry)
            dte_at_entry = 30
            target = compute_time_adjusted_target(days_held, dte_at_entry, profit_pct)
            if target.acceleration_reason:
                print(f"Profit Target:  {target.adjusted_target_pct:.0%} (was {target.original_target_pct:.0%}) — {target.acceleration_reason}")
            else:
                print(f"Profit Target:  {target.adjusted_target_pct:.0%} (standard, no acceleration)")

            # Theta decay
            dte_remaining = max(0, dte_at_entry - days_held)
            theta = compute_remaining_theta_value(dte_remaining, dte_at_entry, profit_pct)
            print(f"Theta Status:   {theta.recommendation.upper()} — {theta.rationale}")

            print("-" * 50)
        except Exception as e:
            print(f"Error: {e}")

    def do_sentinel(self, arg: str) -> None:
        """Crash sentinel — check market health signal: sentinel [TICKERS]

        Signals:
          GREEN  — Normal operations. Income trading as usual.
          YELLOW — Elevated risk. Tighten stops, reduce new entries.
          ORANGE — Pre-crash. Close positions, raise cash.
          RED    — Crash active. 100% cash. Wait for R4→R2 transition.
          BLUE   — Post-crash opportunity. Deploy per crash playbook.

        Examples:
            sentinel                        — default tickers (SPY QQQ IWM GLD TLT)
            sentinel SPY QQQ IWM GLD TLT    — explicit tickers
        """
        from income_desk.features.crash_sentinel import assess_crash_sentinel

        # Parse optional ticker list
        parts = arg.strip().upper().split()
        tickers = parts if parts else ["SPY", "QQQ", "IWM", "GLD", "TLT"]

        try:
            ma = self._get_ma()

            # --- Collect regime results ---
            regime_results: dict[str, dict] = {}
            for ticker in tickers:
                try:
                    r = ma.regime.detect(ticker)
                    r4_prob = (
                        r.regime_probabilities.get(4, 0.0)
                        if r.regime_probabilities
                        else 0.0
                    )
                    regime_results[ticker] = {
                        "regime_id": r.regime.value,
                        "confidence": r.confidence,
                        "r4_prob": r4_prob,
                    }
                except Exception as e:
                    print(_styled(f"  Skipping {ticker}: {e}", "dim"))

            # --- Collect IV ranks (broker only — no fake data) ---
            iv_ranks: dict[str, float] = {}
            for ticker in tickers:
                try:
                    m = ma.quotes.get_metrics(ticker)
                    if m and m.iv_rank is not None:
                        iv_ranks[ticker] = m.iv_rank
                except Exception:
                    pass

            # --- Context ---
            environment = "normal"
            trading_allowed = True
            position_size_factor = 1.0
            try:
                ctx = ma.context.assess()
                trading_allowed = ctx.trading_allowed
                environment = ctx.environment_label
                position_size_factor = ctx.position_size_factor
            except Exception:
                pass

            # --- SPY technicals ---
            spy_rsi = 50.0
            spy_atr_pct = 1.0
            try:
                spy_tech = ma.technicals.snapshot("SPY")
                spy_rsi = float(spy_tech.rsi.value) if spy_tech.rsi else 50.0
                spy_atr_pct = float(spy_tech.atr_pct) if spy_tech.atr_pct else 1.0
            except Exception:
                pass

            # --- Assess ---
            report = assess_crash_sentinel(
                regime_results=regime_results,
                iv_ranks=iv_ranks,
                environment=environment,
                trading_allowed=trading_allowed,
                position_size_factor=position_size_factor,
                spy_atr_pct=spy_atr_pct,
                spy_rsi=spy_rsi,
            )

            # --- Display ---
            signal_colors = {
                "green": "green",
                "yellow": "yellow",
                "orange": "yellow",   # tabulate doesn't have orange; yellow is close
                "red": "red",
                "blue": "cyan",
            }
            sig_color = signal_colors.get(report.signal, "bold")

            _print_header(f"Crash Sentinel — {report.as_of.strftime('%Y-%m-%d %H:%M')}")
            print(f"\n  Signal:      {_styled(report.signal.upper(), sig_color)}")
            print(f"  Environment: {environment}  |  Size factor: {position_size_factor:.2f}")
            print(f"  SPY RSI: {spy_rsi:.1f}  |  ATR: {spy_atr_pct:.1f}%")
            print()

            # Regime table
            if report.tickers:
                rows = []
                for t in report.tickers:
                    ivr = f"{t.iv_rank:.0f}%" if t.iv_rank is not None else "N/A"
                    flag = " <<<" if t.regime_id == 4 else ""
                    rows.append({
                        "Ticker": t.ticker,
                        "Regime": f"R{t.regime_id}",
                        "Conf": f"{t.regime_confidence:.0%}",
                        "R4 Prob": f"{t.r4_probability:.0%}",
                        "IV Rank": ivr,
                        "": flag,
                    })
                print(tabulate(rows, headers="keys", tablefmt="simple"))
                print()

            print(f"  Counts: R4={report.r4_count}  R2={report.r2_count}  R1={report.r1_count}")
            print(f"  Avg IV Rank: {report.avg_iv_rank:.0f}%  |  Max R4 prob: {report.max_r4_probability:.0%}")
            print()

            print(f"  {_styled('Signal: ' + report.signal.upper(), sig_color)}")
            for reason in report.reasons:
                print(f"    Reason: {reason}")
            for action in report.actions:
                print(f"    >> {action}")
            print()

            print(f"  Playbook phase: {_styled(report.playbook_phase, 'bold')}")
            if report.sizing_params:
                params_str = "  |  ".join(f"{k}={v}" for k, v in report.sizing_params.items())
                print(f"  Sizing: {params_str}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_assignment_risk(self, arg: str) -> None:
        """Assess assignment risk on short options BEFORE assignment happens.
\nUsage: assignment_risk TICKER [DTE] [american|european]
  Example: assignment_risk SPY 5 american
  Builds a representative IC and shows which legs are at risk."""
        parts = arg.strip().split()
        if not parts:
            print("Usage: assignment_risk TICKER [DTE] [american|european]")
            return
        ticker = parts[0].upper()
        dte_remaining = int(parts[1]) if len(parts) > 1 else 7
        exercise_style = parts[2].lower() if len(parts) > 2 else "american"

        try:
            from income_desk.features.assignment_handler import assess_assignment_risk
            from income_desk.models.assignment import AssignmentRisk
            from income_desk.models.opportunity import LegAction, LegSpec, OrderSide, StructureType, TradeSpec
            from income_desk.opportunity.option_plays._trade_spec_helpers import (
                build_iron_condor_legs, find_best_expiration, compute_otm_strike, snap_strike,
            )
            from datetime import timedelta

            ma = self._get_ma()
            tech = ma.technicals.snapshot(ticker)
            regime = ma.regime.detect(ticker)
            price = tech.current_price
            atr = tech.atr

            # Build a representative IC using ATR-based strikes (as if currently open)
            vol_surface = None
            try:
                vol_surface = ma.vol_surface.get(ticker)
            except Exception:
                pass

            exp_pt = None
            if vol_surface and vol_surface.term_structure:
                exp_pt = find_best_expiration(vol_surface.term_structure, 20, 45)

            if exp_pt:
                legs, wing_width = build_iron_condor_legs(
                    price, atr, regime.regime, exp_pt.expiration,
                    exp_pt.days_to_expiry, exp_pt.atm_iv,
                )
                trade = TradeSpec(
                    ticker=ticker, legs=legs, underlying_price=price,
                    target_dte=exp_pt.days_to_expiry, target_expiration=exp_pt.expiration,
                    wing_width_points=wing_width,
                    spec_rationale="IC for assignment risk analysis",
                    structure_type=StructureType.IRON_CONDOR,
                    order_side=OrderSide.CREDIT,
                )
            else:
                dte = 30
                exp = date.today() + timedelta(days=dte)
                short_put = compute_otm_strike(price, atr, 1.0, "put", price)
                short_call = compute_otm_strike(price, atr, 1.0, "call", price)
                long_put = snap_strike(short_put - atr * 0.5, price)
                long_call = snap_strike(short_call + atr * 0.5, price)
                ww = short_put - long_put

                def _leg(role, action, otype, strike):
                    return LegSpec(
                        role=role, action=action, option_type=otype, strike=strike,
                        strike_label=f"{strike:.0f} {otype}",
                        expiration=exp, days_to_expiry=dte, atm_iv_at_expiry=0.25,
                    )

                trade = TradeSpec(
                    ticker=ticker,
                    legs=[
                        _leg("short_put", LegAction.SELL_TO_OPEN, "put", short_put),
                        _leg("long_put", LegAction.BUY_TO_OPEN, "put", long_put),
                        _leg("short_call", LegAction.SELL_TO_OPEN, "call", short_call),
                        _leg("long_call", LegAction.BUY_TO_OPEN, "call", long_call),
                    ],
                    underlying_price=price, target_dte=dte, target_expiration=exp,
                    wing_width_points=ww,
                    spec_rationale="Synthetic IC for assignment risk analysis",
                    structure_type=StructureType.IRON_CONDOR,
                    order_side=OrderSide.CREDIT,
                )

            result = assess_assignment_risk(
                trade, current_price=price, dte_remaining=dte_remaining,
                exercise_style=exercise_style,
            )

            _print_header(f"{ticker} — Assignment Risk ({dte_remaining} DTE, {exercise_style.capitalize()})")

            # Risk level with color
            risk_color = {
                "none": "green", "low": "green", "moderate": "yellow",
                "high": "red", "imminent": "red",
            }.get(result.risk_level.value, "")
            urgency_color = {
                "none": "dim", "monitor": "yellow", "prepare": "yellow", "act_now": "red",
            }.get(result.urgency, "")

            print(f"\n  Price: ${price:.2f}  |  ATR: ${atr:.2f}  |  Regime: R{regime.regime}")
            print(f"\n  Risk Level: {_styled(result.risk_level.value.upper(), risk_color)}"
                  f"  |  Urgency: {_styled(result.urgency.upper(), urgency_color)}")
            print(f"  Action: {_styled(result.recommended_action, 'bold')}")

            if result.european_note:
                print(f"\n  {_styled(result.european_note, 'dim')}")

            # Per-leg breakdown
            print(f"\n  {'Leg':<20} {'Strike':>8} {'ITM Amt':>10} {'ITM%':>8} {'Risk':<10}")
            print(f"  {'-'*20} {'-'*8} {'-'*10} {'-'*8} {'-'*10}")
            for leg in result.at_risk_legs:
                leg_risk_color = {
                    "none": "dim", "low": "green", "moderate": "yellow",
                    "high": "red", "imminent": "red",
                }.get(str(leg["risk_level"]), "")
                itm_str = f"${leg['itm_amount']:+.2f}" if leg["itm_amount"] != 0 else "OTM"
                itm_pct_str = f"{leg['itm_pct']:.2%}" if leg["itm_pct"] > 0 else "OTM"
                print(
                    f"  {leg['role']:<20} {leg['strike']:>8.0f} {itm_str:>10}"
                    f" {itm_pct_str:>8}"
                    f" {_styled(str(leg['risk_level']).upper(), leg_risk_color):<10}"
                )

            # Reasons
            print(f"\n  {_styled('Risk Factors:', 'bold')}")
            for reason in result.reasons:
                print(f"    • {reason}")

            # Response trade spec if needed
            if result.response_trade_spec:
                spec = result.response_trade_spec
                print(f"\n  {_styled('Recommended Action Spec:', 'bold')}")
                for leg in spec.legs:
                    print(f"    {leg.action.value.upper()} {leg.quantity}x {leg.strike:.0f} {leg.option_type.upper()}")
                print(f"    Rationale: {spec.spec_rationale}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_margin(self, arg: str) -> None:
        """Show cash vs margin analysis for a hypothetical IC trade.
\nUsage: margin TICKER [NLV] [AVAILABLE_BP] [REGIME]
  Example: margin SPY 200000 100000 2"""
        parts = arg.strip().split()
        if not parts:
            print("Usage: margin TICKER [NLV] [AVAILABLE_BP] [REGIME]")
            return
        ticker = parts[0].upper()
        account_nlv = float(parts[1]) if len(parts) > 1 else 200000.0
        available_bp = float(parts[2]) if len(parts) > 2 else account_nlv * 0.5
        regime_id = int(parts[3]) if len(parts) > 3 else 1

        try:
            from income_desk.features.position_sizing import compute_margin_analysis
            from income_desk.models.opportunity import LegAction, LegSpec, OrderSide, StructureType, TradeSpec
            from income_desk.opportunity.option_plays._trade_spec_helpers import (
                build_iron_condor_legs, find_best_expiration, compute_otm_strike, snap_strike,
            )
            from datetime import timedelta

            ma = self._get_ma()
            tech = ma.technicals.snapshot(ticker)
            price = tech.current_price
            atr = tech.atr

            # Build a representative IC
            vol_surface = None
            try:
                vol_surface = ma.vol_surface.get(ticker)
            except Exception:
                pass

            exp_pt = None
            if vol_surface and vol_surface.term_structure:
                exp_pt = find_best_expiration(vol_surface.term_structure, 30, 45)

            if exp_pt:
                legs, wing_width = build_iron_condor_legs(
                    price, atr, regime_id, exp_pt.expiration,
                    exp_pt.days_to_expiry, exp_pt.atm_iv,
                )
                trade = TradeSpec(
                    ticker=ticker, legs=legs, underlying_price=price,
                    target_dte=exp_pt.days_to_expiry, target_expiration=exp_pt.expiration,
                    wing_width_points=wing_width,
                    spec_rationale="IC for margin analysis",
                    structure_type=StructureType.IRON_CONDOR,
                    order_side=OrderSide.CREDIT,
                )
            else:
                dte = 30
                exp = date.today() + timedelta(days=dte)
                short_put = compute_otm_strike(price, atr, 1.0, "put", price)
                short_call = compute_otm_strike(price, atr, 1.0, "call", price)
                long_put = snap_strike(short_put - atr * 0.5, price)
                long_call = snap_strike(short_call + atr * 0.5, price)
                ww = short_put - long_put

                def _leg(role, action, otype, strike):
                    return LegSpec(
                        role=role, action=action, option_type=otype, strike=strike,
                        strike_label=f"{strike:.0f} {otype}",
                        expiration=exp, days_to_expiry=dte, atm_iv_at_expiry=0.25,
                    )

                trade = TradeSpec(
                    ticker=ticker,
                    legs=[
                        _leg("short_put", LegAction.SELL_TO_OPEN, "put", short_put),
                        _leg("long_put", LegAction.BUY_TO_OPEN, "put", long_put),
                        _leg("short_call", LegAction.SELL_TO_OPEN, "call", short_call),
                        _leg("long_call", LegAction.BUY_TO_OPEN, "call", long_call),
                    ],
                    underlying_price=price, target_dte=dte, target_expiration=exp,
                    wing_width_points=ww,
                    spec_rationale="Synthetic IC for margin analysis",
                    structure_type=StructureType.IRON_CONDOR,
                    order_side=OrderSide.CREDIT,
                )

            result = compute_margin_analysis(
                trade, account_nlv=account_nlv, available_bp=available_bp,
                regime_id=regime_id,
            )

            _print_header(f"{ticker} — Cash vs Margin Analysis (R{regime_id})")

            print(f"\n  Underlying Price:   ${price:,.2f}")
            print(f"  Structure:         {result.structure_type}  |  Wing: ${trade.wing_width_points or 0:.0f}")
            print()
            print(f"  Account NLV:       ${account_nlv:,.0f}")
            print(f"  Available BP:      ${available_bp:,.0f}")
            print()
            print(f"  Cash Required:     ${result.cash_required:,.0f}  (full defined-risk)")
            print(f"  Margin Required:   ${result.margin_required:,.0f}  (broker minimum)")
            print(f"  BP Consumed:       ${result.buying_power_reduction:,.0f}  "
                  f"(regime R{regime_id} x{result.regime_margin_multiplier:.1f})")
            print()
            bp_fits = result.buying_power_reduction <= available_bp
            bp_style = "green" if bp_fits else "red"
            print(f"  BP After Trade:    {_styled(f'${result.bp_after_trade:,.0f}', bp_style)}")
            print(f"  BP Utilization:    {result.bp_utilization_pct:.1%}")
            margin_style = "green" if result.margin_cushion_pct > 0.2 else "yellow" if result.margin_cushion_pct > 0.1 else "red"
            print(f"  Margin Cushion:    {_styled(f'{result.margin_cushion_pct:.1%}', margin_style)}  "
                  f"(lower = closer to margin call)")
            print()
            regime_fit = result.regime_adjusted_bp <= available_bp
            regime_style = "green" if regime_fit else "red"
            print(f"  Regime-Adj BP:     {_styled(f'${result.regime_adjusted_bp:,.0f}', regime_style)}  "
                  f"({'FITS' if regime_fit else 'EXCEEDS AVAILABLE BP'})")

            if result.margin_call_at_price is not None:
                print(f"\n  Margin Call At:    ${result.margin_call_at_price:,.2f}  "
                      f"(${result.max_adverse_before_call:,.2f} adverse move)")

            print(f"\n  {_styled(result.summary, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_rate_risk(self, arg: str) -> None:
        """Assess interest rate risk for one or more tickers.
\nUsage: rate_risk TICKER [TICKER2 ...] [--bps 25] [--regime 2]
  Example: rate_risk TLT SPY XLU --bps 20 --regime 2"""
        import shlex
        try:
            tokens = shlex.split(arg.strip()) if arg.strip() else []
        except ValueError:
            tokens = arg.strip().split()

        tickers = []
        yield_change_bps = 0.0
        regime_id = 1
        i = 0
        while i < len(tokens):
            if tokens[i] == "--bps" and i + 1 < len(tokens):
                try:
                    yield_change_bps = float(tokens[i + 1])
                    i += 2
                except ValueError:
                    i += 1
            elif tokens[i] == "--regime" and i + 1 < len(tokens):
                try:
                    regime_id = int(tokens[i + 1])
                    i += 2
                except ValueError:
                    i += 1
            else:
                tickers.append(tokens[i].upper())
                i += 1

        if not tickers:
            print("Usage: rate_risk TICKER [TICKER2 ...] [--bps YIELD_CHANGE] [--regime 1-4]")
            print("  TICKER: ticker symbol(s) to assess (e.g. TLT SPY XLU)")
            print("  --bps:  recent 10Y yield change in basis points (+ve = rising)")
            print("  --regime: market regime 1-4 (default 1)")
            return

        try:
            from income_desk.features.rate_risk import assess_rate_risk, assess_portfolio_rate_risk, RateRiskLevel

            if len(tickers) == 1:
                # Single ticker — detailed view
                result = assess_rate_risk(
                    tickers[0], current_yield_change_bps=yield_change_bps, regime_id=regime_id,
                )
                _print_header(f"{tickers[0]} — Interest Rate Risk Assessment")

                risk_color = {
                    "low": "green", "moderate": "yellow", "elevated": "yellow", "high": "red",
                }.get(result.rate_risk_level.value, "")

                print(f"\n  Sensitivity:     {result.rate_sensitivity.upper()}")
                print(f"  Duration:        {result.estimated_duration:.1f} years")
                print(f"  Yield Corr:      {result.yield_correlation:+.2f} (vs 10Y TNX)")
                print(f"  Yield Trend:     {result.current_yield_trend}  "
                      f"({yield_change_bps:+.0f}bp recent change)")
                print(f"\n  Risk Level:      {_styled(result.rate_risk_level.value.upper(), risk_color)}")
                print(f"  Impact / 25bp:   {result.impact_per_25bp:+.2%}")
                print(f"  Impact / 100bp:  {result.impact_per_100bp:+.2%}")
                print(f"\n  {_styled('Reasons:', 'bold')}")
                for r in result.reasons:
                    print(f"    • {r}")
                rec_style = "red" if result.recommendation == "avoid_long_duration" else "yellow" if result.recommendation == "reduce_exposure" else "green"
                print(f"\n  Recommendation:  {_styled(result.recommendation.replace('_', ' ').upper(), rec_style)}")

            else:
                # Portfolio view
                port = assess_portfolio_rate_risk(
                    tickers, current_yield_change_bps=yield_change_bps, regime_id=regime_id,
                )
                _print_header(f"Portfolio Rate Risk — {', '.join(tickers)}")

                print(f"\n  Yield Change:          {yield_change_bps:+.0f}bp  |  Regime: R{regime_id}")
                print(f"  Portfolio Sensitivity: {port.portfolio_rate_sensitivity.upper()}")
                print(f"  Portfolio Duration:    {port.portfolio_duration:.1f} years")
                print(f"  Impact / 100bp:        {port.estimated_portfolio_impact_100bp:+.2%}")

                if port.high_risk_tickers:
                    print(f"\n  {_styled('HIGH RISK tickers:', 'red')} {', '.join(port.high_risk_tickers)}")

                print(f"\n  {'Ticker':<8} {'Sensitivity':<12} {'Duration':>10} {'Corr':>8} {'Impact/100bp':>14} {'Risk':<12}")
                print(f"  {'-'*8} {'-'*12} {'-'*10} {'-'*8} {'-'*14} {'-'*12}")
                for r in port.ticker_risks:
                    risk_color = {
                        "low": "green", "moderate": "yellow", "elevated": "yellow", "high": "red",
                    }.get(r.rate_risk_level.value, "")
                    print(
                        f"  {r.ticker:<8} {r.rate_sensitivity:<12} {r.estimated_duration:>10.1f}"
                        f" {r.yield_correlation:>+8.2f} {r.impact_per_100bp:>+14.2%}"
                        f" {_styled(r.rate_risk_level.value, risk_color):<12}"
                    )

                rec_style = "red" if "reduce" in port.recommendation or "avoid" in port.recommendation else "green"
                print(f"\n  Recommendation:  {_styled(port.recommendation.replace('_', ' ').upper(), rec_style)}")
                print(f"\n  {_styled(port.summary, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_csp(self, arg: str) -> None:
        """Analyze a Cash-Secured Put trade — intentional assignment / wheel entry.

Usage: csp TICKER STRIKE [PREMIUM] [DTE] [--intent wheel_entry|income_only|acquire_stock]
       csp IWM 240 2.50 30
       csp SPY 640 3.00 21 --intent income_only
       csp AAPL 200 2.00 30 --intent acquire_stock

Shows effective buy price, discount from current, annualized yield, assignment
probability, margin/cash requirement, and a pre-built covered call for wheel step 2."""
        parts = arg.strip().split()
        if not parts:
            print("Usage: csp TICKER STRIKE [PREMIUM] [DTE] [--intent wheel_entry|income_only|acquire_stock]")
            return

        ticker = parts[0].upper()
        strike: float | None = None
        premium: float = 2.00
        dte: int = 30
        intent: str = "wheel_entry"

        i = 1
        while i < len(parts):
            if parts[i] == "--intent" and i + 1 < len(parts):
                intent = parts[i + 1].lower()
                i += 2
            elif strike is None:
                try:
                    strike = float(parts[i])
                except ValueError:
                    pass
                i += 1
            elif i == 2:
                try:
                    premium = float(parts[i])
                except ValueError:
                    pass
                i += 1
            elif i == 3:
                try:
                    dte = int(parts[i])
                except ValueError:
                    pass
                i += 1
            else:
                i += 1

        if strike is None:
            print("Usage: csp TICKER STRIKE [PREMIUM] [DTE] [--intent ...]")
            return

        try:
            from income_desk.features.assignment_handler import analyze_cash_secured_put

            ma = self._get_ma()
            tech = ma.technicals.snapshot(ticker)
            current_price = tech.current_price
            atr = tech.atr

            # Attempt to get regime for context
            regime_id = 1
            try:
                r = ma.regime.detect(ticker)
                regime_id = r.regime_id
            except Exception:
                pass

            account_nlv = 100000.0
            try:
                if ma.account is not None:
                    bal = ma.account.get_balance()
                    account_nlv = bal.net_liquidating_value
            except Exception:
                pass

            result = analyze_cash_secured_put(
                ticker=ticker,
                strike=strike,
                premium=premium,
                current_price=current_price,
                dte=dte,
                regime_id=regime_id,
                atr=atr,
                account_nlv=account_nlv,
                intent=intent,
            )

            _print_header(f"Cash-Secured Put — {ticker} {strike:.0f}P | {result.intent.value.replace('_', ' ').title()}")

            print(f"\n  {_styled('Economics:', 'bold')}")
            print(f"    Current price:        ${current_price:,.2f}")
            print(f"    Strike:               ${result.strike:,.2f}")
            print(f"    Premium collected:    ${result.premium_collected:.2f}/share")
            print(f"    Effective buy price:  ${result.effective_buy_price:.2f}  "
                  f"({result.discount_from_current_pct:.1%} discount from current)")
            print(f"    Annualized yield:     {result.annualized_yield_if_not_assigned:.1%}  (if not assigned)")
            print(f"    Breakeven:            ${result.breakeven:.2f}")

            print(f"\n  {_styled('Capital Requirements:', 'bold')}")
            print(f"    Cash to secure:       ${result.cash_to_secure:,.0f}")
            print(f"    Margin to secure:     ${result.margin_to_secure:,.0f}  (~20% portfolio margin)")

            print(f"\n  {_styled('Risk:', 'bold')}")
            print(f"    Max loss:             ${result.max_loss:,.0f}  (stock → $0)")
            ap_color = "green" if result.assignment_probability == "low" else \
                       "yellow" if result.assignment_probability == "moderate" else "red"
            print(f"    Assignment prob:      {_styled(result.assignment_probability.upper(), ap_color)}")

            print(f"\n  {_styled('Post-Assignment Plan:', 'bold')}")
            print(f"    Plan:                 {result.post_assignment_plan.replace('_', ' ').title()}")

            if result.covered_call_spec is not None:
                cc_leg = result.covered_call_spec.legs[0]
                print(f"\n  {_styled('Pre-Built Covered Call (Wheel Step 2):', 'bold')}")
                print(f"    Strike:               ${cc_leg.strike:.0f}  (1 ATR above current)")
                print(f"    Expiration:           {result.covered_call_spec.target_expiration}")
                print(f"    DTE:                  {cc_leg.days_to_expiry} days")
                print(f"    {_profile_tag('covered_call', 'credit')}")

            if result.margin_analysis:
                ma_data = result.margin_analysis
                print(f"\n  {_styled('Margin Analysis:', 'bold')}")
                print(f"    Cash required:        ${ma_data.get('cash_required', 0):,.0f}")
                print(f"    Margin required:      ${ma_data.get('margin_required', 0):,.0f}")
                print(f"    BP after trade:       ${ma_data.get('bp_after_trade', 0):,.0f}")
                print(f"    Regime mult:          {ma_data.get('regime_margin_multiplier', 1.0):.1f}x  (R{regime_id})")

            print(f"\n  {_styled(result.summary, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")
            import traceback as _tb
            _tb.print_exc()

    def do_covered_call(self, arg: str) -> None:
        """Analyze selling a Covered Call against owned shares — wheel step 2.

Usage: covered_call TICKER COST_BASIS [SHARES] [--dte DAYS] [--iv IV_RANK]
       covered_call IWM 240 100
       covered_call SPY 550 200 --dte 45
       covered_call AAPL 180 100 --iv 35

Shows regime-aware strike selection, scenarios (called away vs income only),
annualized yield, and a ready TradeSpec for execution."""
        parts = arg.strip().split()
        if not parts:
            print("Usage: covered_call TICKER COST_BASIS [SHARES] [--dte DAYS] [--iv IV_RANK]")
            return

        ticker = parts[0].upper()
        cost_basis: float | None = None
        shares_owned: int = 100
        dte: int = 30
        iv_rank: float | None = None

        i = 1
        while i < len(parts):
            if parts[i] == "--dte" and i + 1 < len(parts):
                try:
                    dte = int(parts[i + 1])
                except ValueError:
                    pass
                i += 2
            elif parts[i] == "--iv" and i + 1 < len(parts):
                try:
                    iv_rank = float(parts[i + 1])
                except ValueError:
                    pass
                i += 2
            elif cost_basis is None:
                try:
                    cost_basis = float(parts[i])
                except ValueError:
                    pass
                i += 1
            else:
                try:
                    shares_owned = int(parts[i])
                except ValueError:
                    pass
                i += 1

        if cost_basis is None:
            print("Usage: covered_call TICKER COST_BASIS [SHARES] [--dte DAYS] [--iv IV_RANK]")
            return

        try:
            from income_desk.features.assignment_handler import analyze_covered_call

            ma = self._get_ma()
            tech = ma.technicals.snapshot(ticker)
            current_price = tech.current_price
            atr = tech.atr

            regime_id = 1
            try:
                r = ma.regime.detect(ticker)
                regime_id = r.regime_id
            except Exception:
                pass

            result = analyze_covered_call(
                ticker=ticker,
                shares_owned=shares_owned,
                cost_basis=cost_basis,
                current_price=current_price,
                regime_id=regime_id,
                atr=atr,
                dte=dte,
                iv_rank=iv_rank,
            )

            _print_header(f"Covered Call — {ticker} | {shares_owned} shares @ ${cost_basis:.2f} cost")

            print(f"\n  {_styled('Position:', 'bold')}")
            print(f"    Shares owned:         {result.shares_owned}")
            print(f"    Cost basis:           ${result.cost_basis:.2f}/share")
            print(f"    Current price:        ${result.current_price:.2f}/share")
            unrealized = (current_price - cost_basis) * shares_owned
            unr_color = "green" if unrealized >= 0 else "red"
            print(f"    Unrealized P&L:       {_styled(f'${unrealized:,.0f}', unr_color)}")

            print(f"\n  {_styled('Recommended Covered Call (R' + str(regime_id) + '):', 'bold')}")
            print(f"    Strike:               ${result.call_strike:.0f}")
            print(f"    Expiration:           {result.call_expiration}  ({result.call_dte} DTE)")
            print(f"    Est. premium:         ${result.estimated_premium:.2f}/share  "
                  f"(${result.if_not_called_income:,.0f} total)")
            print(f"    {_profile_tag('covered_call', 'credit')}")

            print(f"\n  {_styled('Scenarios:', 'bold')}")
            called_color = "green" if result.if_called_away_profit >= 0 else "red"
            print(f"    If called away:       "
                  f"{_styled(f'${result.if_called_away_profit:,.0f} ({result.if_called_away_pct:.1%})', called_color)}")
            print(f"    If NOT called:        ${result.if_not_called_income:,.0f}  (premium only)")
            print(f"    Annualized yield:     {result.annualized_yield:.1%}")
            print(f"    Upside cap:           ${result.upside_cap:.0f}  (called away above this)")

            print(f"\n  {_styled(result.summary, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_margin_buffer(self, arg: str) -> None:
        """Show structure-based margin buffer recommendations for a ticker.

Usage: margin_buffer TICKER [NLV] [REGIME]
       margin_buffer SPY
       margin_buffer IWM 80000 2

Shows recommended margin buffer above base requirement for each structure type,
stratified by risk category (defined / semi_defined / undefined)."""
        parts = arg.strip().split()
        if not parts:
            print("Usage: margin_buffer TICKER [NLV] [REGIME]")
            return

        ticker = parts[0].upper()
        account_nlv = float(parts[1]) if len(parts) > 1 else 100000.0
        regime_id = int(parts[2]) if len(parts) > 2 else 1

        try:
            from income_desk.features.position_sizing import compute_margin_buffer
            from income_desk.models.opportunity import LegAction, LegSpec, OrderSide, StructureType, TradeSpec
            from datetime import timedelta

            ma = self._get_ma()
            tech = ma.technicals.snapshot(ticker)
            price = tech.current_price

            # Auto-detect regime if not provided
            if len(parts) <= 2:
                try:
                    r = ma.regime.detect(ticker)
                    regime_id = r.regime_id
                except Exception:
                    pass

            _print_header(f"Margin Buffer Analysis — {ticker} @ ${price:,.2f} | R{regime_id}")

            structures = [
                ("iron_condor",     500.0,             "IC: 5-wide wing"),
                ("credit_spread",   500.0,             "Credit spread: 5-wide"),
                ("debit_spread",    500.0,             "Debit spread: 5-wide"),
                ("cash_secured_put", price * 100,      f"CSP: ${price:.0f} * 100"),
                ("covered_call",    price * 100 * 0.20, "Covered call: 20% margin"),
                ("straddle",        price * 100 * 0.20, "Short straddle (naked)"),
                ("ratio_spread",    price * 100 * 0.15, "Ratio spread (naked leg)"),
            ]

            exp = date.today() + timedelta(days=30)
            rows = []
            for structure, base_margin, desc in structures:
                try:
                    ts = TradeSpec(
                        ticker=ticker,
                        legs=[LegSpec(
                            role="short_put", action=LegAction.SELL_TO_OPEN, quantity=1,
                            option_type="put", strike=price * 0.95,
                            strike_label=f"{price * 0.95:.0f}P",
                            expiration=exp, days_to_expiry=30, atm_iv_at_expiry=0.25,
                        )],
                        underlying_price=price,
                        target_dte=30, target_expiration=exp,
                        spec_rationale="margin buffer analysis",
                        structure_type=StructureType(structure),
                        order_side=OrderSide.CREDIT,
                    )
                    buf = compute_margin_buffer(ts, base_margin=base_margin, regime_id=regime_id)
                    rows.append([
                        structure,
                        buf.risk_category,
                        f"${base_margin:,.0f}",
                        f"{buf.recommended_buffer_pct:.0%}",
                        f"${buf.recommended_buffer_dollars:,.0f}",
                        f"${buf.total_recommended:,.0f}",
                    ])
                except Exception:
                    pass

            if rows:
                print(tabulate(
                    rows,
                    headers=["Structure", "Risk Cat", "Base Margin", "Buffer %", "Buffer $", "Total Reserve"],
                    tablefmt="simple",
                ))
            print(f"\n  Regime R{regime_id} buffer multiplier applied.")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_wizard(self, arg: str) -> None:
        """First-time setup wizard: wizard

        Guides you through broker connection, saves credentials, and verifies.
        Run this once after installing market_analyzer.
        """
        from income_desk.cli._setup import run_setup_wizard
        run_setup_wizard()

    def do_desk(self, arg: str) -> None:
        """Recommend desk structure for a given capital amount.

        Usage:
            desk CAPITAL [TOLERANCE] [--regime R1,R2,...]
            desk 100000                  # moderate, US market
            desk 200000 conservative
            desk 100000 aggressive --regime SPY:4,QQQ:3

        TOLERANCE: conservative | moderate (default) | aggressive
        --regime:  comma-separated ticker:regime pairs (e.g. SPY:4,QQQ:3)
        """
        from income_desk.features.desk_management import recommend_desk_structure

        parts = arg.strip().split()
        if not parts:
            print("Usage: desk CAPITAL [TOLERANCE] [--regime TICKER:R,...]")
            return

        # Parse capital
        try:
            total_capital = float(parts[0].replace(",", ""))
        except ValueError:
            print(f"Invalid capital amount: {parts[0]}")
            return

        # Parse tolerance
        risk_tolerance = "moderate"
        if len(parts) > 1 and not parts[1].startswith("--"):
            rt = parts[1].lower()
            if rt in ("conservative", "moderate", "aggressive"):
                risk_tolerance = rt
            else:
                print(f"Unknown tolerance '{parts[1]}'. Use: conservative | moderate | aggressive")
                return

        # Parse --regime
        regime: dict[str, int] | None = None
        if "--regime" in parts:
            idx = parts.index("--regime")
            if idx + 1 < len(parts):
                regime = {}
                for pair in parts[idx + 1].split(","):
                    try:
                        ticker_r, r_val = pair.split(":")
                        regime[ticker_r.upper()] = int(r_val)
                    except ValueError:
                        print(f"Invalid regime pair: '{pair}' (expected TICKER:1-4)")
                        return

        market = self._market

        try:
            rec = recommend_desk_structure(
                total_capital=total_capital,
                risk_tolerance=risk_tolerance,
                market=market,
                regime=regime,
            )

            _print_header(
                f"Portfolio Allocation — ${total_capital:,.0f} | {risk_tolerance.capitalize()} | {market}"
            )

            # ── Asset class view ──────────────────────────────────────────────
            print(f"\n  Cash Reserve: {_styled(f'${rec.cash_reserve_dollars:,.0f}', 'yellow')} "
                  f"({rec.cash_reserve_pct:.0%} of total)")

            if rec.regime_adjustments:
                for note in rec.regime_adjustments:
                    print(f"  {_styled('Regime:', 'dim')} {_styled(note, 'dim')}")

            print(f"\n  {_styled('ASSET CLASS ALLOCATION', 'bold')}")
            alloc_rows = []
            for a in rec.allocations:
                alloc_rows.append([
                    _styled(a.asset_class.upper(), "bold"),
                    f"${a.allocation_dollars:,.0f}",
                    f"{a.allocation_pct:.0%}",
                    f"${a.defined_risk_dollars:,.0f}",
                    f"${a.undefined_risk_dollars:,.0f}",
                ])
            print(tabulate(
                alloc_rows,
                headers=["Asset Class", "Allocation", "Pct", "Defined", "Undefined"],
                tablefmt="simple",
            ))

            # ── Desk view ─────────────────────────────────────────────────────
            print(f"\n  {_styled('DESKS (derived from allocation)', 'bold')}")
            desk_rows = []
            for desk in rec.desks:
                risk_flag = (
                    _styled("YES", "red") if desk.allow_undefined_risk
                    else _styled("no", "green")
                )
                desk_rows.append([
                    _styled(desk.desk_key, "bold"),
                    f"${desk.capital_allocation:,.0f}",
                    f"{desk.dte_min}-{desk.dte_max}",
                    desk.max_positions,
                    risk_flag,
                    ", ".join(desk.strategy_types[:3]) + ("..." if len(desk.strategy_types) > 3 else ""),
                ])

            print(tabulate(
                desk_rows,
                headers=["Desk", "Capital", "DTE", "MaxPos", "Undef", "Strategies"],
                tablefmt="simple",
            ))

            print(f"\n  {_styled(rec.rationale, 'dim')}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_desk_health(self, arg: str) -> None:
        """Evaluate desk health from trade history.

        Usage:
            desk_health DESK_KEY CAPITAL [--regime R] [--wins W --losses L]
            desk_health desk_income 50000
            desk_health desk_income 50000 --regime 2
            desk_health desk_income 50000 --wins 8 --losses 2 --win_pnl 200 --loss_pnl -100

        Simulates trade history from win/loss counts if provided.
        """
        from income_desk.features.desk_management import evaluate_desk_health

        parts = arg.strip().split()
        if len(parts) < 2:
            print("Usage: desk_health DESK_KEY CAPITAL [--regime R] [--wins W --losses L]")
            return

        desk_key = parts[0]
        try:
            capital = float(parts[1].replace(",", ""))
        except ValueError:
            print(f"Invalid capital: {parts[1]}")
            return

        # Parse optional flags
        regime_id: int | None = None
        n_wins = 6
        n_losses = 4
        win_pnl = 200.0
        loss_pnl = -100.0

        i = 2
        while i < len(parts):
            flag = parts[i]
            if flag == "--regime" and i + 1 < len(parts):
                try:
                    regime_id = int(parts[i + 1])
                    i += 2
                except ValueError:
                    print(f"Invalid regime: {parts[i+1]}")
                    return
            elif flag == "--wins" and i + 1 < len(parts):
                try:
                    n_wins = int(parts[i + 1])
                    i += 2
                except ValueError:
                    print(f"Invalid wins: {parts[i+1]}")
                    return
            elif flag == "--losses" and i + 1 < len(parts):
                try:
                    n_losses = int(parts[i + 1])
                    i += 2
                except ValueError:
                    print(f"Invalid losses: {parts[i+1]}")
                    return
            elif flag == "--win_pnl" and i + 1 < len(parts):
                try:
                    win_pnl = float(parts[i + 1])
                    i += 2
                except ValueError:
                    print(f"Invalid win_pnl: {parts[i+1]}")
                    return
            elif flag == "--loss_pnl" and i + 1 < len(parts):
                try:
                    loss_pnl = float(parts[i + 1])
                    i += 2
                except ValueError:
                    print(f"Invalid loss_pnl: {parts[i+1]}")
                    return
            else:
                i += 1

        # Build synthetic trade history
        trade_history = []
        for _ in range(n_wins):
            trade_history.append({"pnl": win_pnl, "won": True, "days_held": 20.0})
        for _ in range(n_losses):
            trade_history.append({"pnl": loss_pnl, "won": False, "days_held": 20.0})

        try:
            report = evaluate_desk_health(
                desk_key=desk_key,
                trade_history=trade_history,
                capital_deployed=capital,
                current_regime=regime_id,
            )

            _print_header(f"Desk Health — {desk_key}")

            health_color = {
                "excellent": "green",
                "good": "green",
                "caution": "yellow",
                "poor": "red",
                "critical": "red",
            }.get(report.health.value, "white")

            print(f"\n  Health:   {_styled(report.health.value.upper(), health_color)}")
            print(f"  Score:    {report.score:.2f} / 1.00")

            metrics_parts = []
            if report.win_rate is not None:
                metrics_parts.append(f"Win Rate: {report.win_rate:.0%}")
            if report.profit_factor is not None:
                pf_str = f"{report.profit_factor:.2f}" if report.profit_factor != float("inf") else "∞"
                metrics_parts.append(f"Profit Factor: {pf_str}")
            if report.avg_days_held is not None:
                metrics_parts.append(f"Avg Days: {report.avg_days_held:.0f}")
            metrics_parts.append(f"Cap Efficiency: {report.capital_efficiency:.1%}/yr")

            print(f"  Metrics:  {' | '.join(metrics_parts)}")
            print(f"  Regime Fit: {_styled(report.regime_fit, 'dim')}")

            if report.issues:
                print(f"\n  {_styled('Issues:', 'red')}")
                for issue in report.issues:
                    print(f"    - {issue}")

            if report.suggestions:
                print(f"\n  {_styled('Suggestions:', 'yellow')}")
                for sug in report.suggestions:
                    print(f"    → {sug}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    # --- Demo portfolio commands ---

    def do_portfolio(self, arg: str) -> None:
        """Show demo portfolio status: portfolio

        Shows desk allocation, open positions, P&L, and drawdown.
        Create demo portfolio first: analyzer-cli --demo
        """
        from income_desk.demo import load_demo_portfolio, get_demo_summary

        port = load_demo_portfolio()
        if port is None:
            print("No demo portfolio. Run: analyzer-cli --demo")
            return

        summary = get_demo_summary(port)

        print(f"\nDEMO PORTFOLIO — ${summary['capital']:,.0f} ({summary['risk_tolerance']})")
        print("=" * 55)
        print(f"NLV:          ${summary['current_nlv']:,.0f}")
        print(f"Cash:         ${summary['cash']:,.0f}")
        print(f"Open:         {summary['open_positions']} positions")
        print(f"Closed:       {summary['closed_trades']} trades")
        print(f"Total P&L:    ${summary['total_pnl']:,.0f}")
        print(f"Win Rate:     {summary['win_rate']:.0%}")
        print(f"Drawdown:     {summary['drawdown_pct']:.1%}")

        # Show positions by desk
        if port.positions:
            print(f"\nOPEN POSITIONS:")
            for p in port.positions:
                days = (date.today() - date.fromisoformat(p.entry_date)).days
                print(f"  {p.position_id}  {p.ticker:<6} {p.structure_type:<16} {p.desk_key:<20} {p.contracts}x  day {days}  entry ${p.entry_price:.2f}")

        # Show desk utilization
        print(f"\nDESK ALLOCATION:")
        for desk_data in port.desks:
            dk = desk_data.get("desk_key", "?")
            cap = desk_data.get("capital_allocation", 0)
            pos_in_desk = len([p for p in port.positions if p.desk_key == dk])
            max_pos = desk_data.get("max_positions", 5)
            print(f"  {dk:<24} ${cap:>8,.0f}  {pos_in_desk}/{max_pos} positions")

    def do_trade(self, arg: str) -> None:
        """Place a simulated trade in demo portfolio: trade TICKER

        Runs full pipeline: assess -> validate -> size -> route to desk -> book.

        Example:
            trade SPY
            trade GLD
        """
        from income_desk.demo import load_demo_portfolio, add_demo_position

        port = load_demo_portfolio()
        if port is None:
            print("No demo portfolio. Run: analyzer-cli --demo")
            return

        ticker = arg.strip().upper() or "SPY"
        ma = self._get_ma()

        # Full pipeline
        try:
            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)
            vol = ma.vol_surface.surface(ticker)

            from income_desk.opportunity.option_plays.iron_condor import assess_iron_condor
            ic = assess_iron_condor(ticker, regime, tech, vol)

            if ic.trade_spec is None:
                print(f"No trade available for {ticker} (verdict: {ic.verdict})")
                return

            ts = ic.trade_spec
            wing = ts.wing_width_points or 5.0
            ec = wing * (vol.front_iv if vol else 0.20) * 0.40  # Estimated credit

            # Validate
            from income_desk.validation.daily_readiness import run_daily_checks
            levels = ma.levels.analyze(ticker)
            rpt = run_daily_checks(
                ticker=ticker,
                trade_spec=ts,
                entry_credit=ec,
                regime_id=regime.regime.value,
                atr_pct=tech.atr_pct,
                current_price=tech.current_price,
                avg_bid_ask_spread_pct=vol.avg_bid_ask_spread_pct if vol else 2.0,
                dte=ts.target_dte,
                rsi=tech.rsi.value,
                ticker_type="etf",
                levels=levels,
            )

            if not rpt.is_ready:
                fails = [c for c in rpt.checks if c.severity.value == "fail"]
                print(f"Trade BLOCKED: {', '.join(c.name for c in fails)}")
                return

            # Size
            from income_desk.features.position_sizing import compute_position_size, PortfolioExposure
            from income_desk.trade_lifecycle import estimate_pop

            pop = estimate_pop(ts, ec, regime.regime.value, tech.atr_pct, tech.current_price)
            risk_per = wing * ts.lot_size

            deployed = sum(p.max_loss for p in port.positions)
            sz = compute_position_size(
                pop_pct=pop.pop_pct,
                max_profit=pop.max_profit,
                max_loss=pop.max_loss,
                capital=port.current_nlv,
                risk_per_contract=risk_per,
                wing_width=wing,
                regime_id=regime.regime.value,
                exposure=PortfolioExposure(
                    open_position_count=len(port.positions),
                    max_positions=5,
                    current_risk_pct=deployed / port.current_nlv if port.current_nlv > 0 else 0,
                ),
            )

            if sz.recommended_contracts == 0:
                print(f"Kelly says 0 contracts. POP: {pop.pop_pct:.0%}, EV: ${pop.expected_value:.0f}")
                return

            # Route to desk
            from income_desk.features.desk_management import suggest_desk_for_trade
            desk_result = suggest_desk_for_trade(
                desks=port.desks,
                trade_dte=ts.target_dte,
                strategy_type=str(ts.structure_type or "iron_condor"),
                ticker=ticker,
            )
            desk_key = desk_result.get("desk_key", "desk_income_defined")

            # Book it
            pos = add_demo_position(
                port, ticker, desk_key, ts, ec, sz.recommended_contracts, regime.regime.value,
            )

            print(f"\nTRADE BOOKED (demo)")
            print(f"  {pos.position_id}: {ticker} {ts.structure_type} {sz.recommended_contracts}x")
            print(f"  Desk: {desk_key}")
            print(f"  Credit: ${ec:.2f}/contract")
            print(f"  Max profit: ${pos.max_profit:.0f} | Max loss: ${pos.max_loss:.0f}")
            print(f"  Cash remaining: ${port.cash_balance:,.0f}")

        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")

    def do_close_trade(self, arg: str) -> None:
        """Close a demo position: close_trade POSITION_ID [CLOSE_PRICE] [REASON]"""
        from income_desk.demo import load_demo_portfolio, close_demo_position

        parts = arg.strip().split()
        if not parts:
            print("Usage: close_trade POSITION_ID [CLOSE_PRICE] [REASON]")
            return

        port = load_demo_portfolio()
        if port is None:
            print("No demo portfolio.")
            return

        pid = parts[0]
        close_price = float(parts[1]) if len(parts) > 1 else 0.0  # Default: expired worthless = full profit
        reason = parts[2] if len(parts) > 2 else "manual"

        pos = close_demo_position(port, pid, close_price, reason)
        if pos is None:
            print(f"Position {pid} not found")
            return

        print(f"CLOSED: {pos.ticker} {pos.structure_type} -> P&L: ${pos.pnl:+,.0f} ({pos.close_reason})")

    def do_import_trades(self, arg: str) -> None:
        """Import trades from broker CSV: import_trades PATH [BROKER]

        Auto-detects broker format from CSV headers.
        Supported: thinkorswim, tastytrade, schwab, ibkr, fidelity, webull, generic

        Examples:
            import_trades ~/Downloads/trades.csv
            import_trades ~/Downloads/tos_trades.csv thinkorswim
        """
        from income_desk.adapters.csv_trades import import_trades_csv, detect_broker_format

        parts = arg.strip().split()
        if not parts:
            print("Usage: import_trades PATH [BROKER]")
            return

        file_path = parts[0]
        broker_hint = parts[1] if len(parts) > 1 else None

        try:
            result = import_trades_csv(file_path, broker=broker_hint)
        except Exception as exc:
            print(f"{_styled('ERROR:', 'red')} {exc}")
            return

        _print_header(f"CSV Trade Import — {result.broker_detected}")
        print(f"\n  File:     {result.file_path}")
        print(f"  Broker:   {result.broker_detected}")
        print(f"  Imported: {result.total_imported}")
        print(f"  Skipped:  {result.skipped}")

        if result.errors:
            print(f"\n  {_styled('Parse errors:', 'yellow')}")
            for err in result.errors[:10]:
                print(f"    {err}")
            if len(result.errors) > 10:
                print(f"    ... and {len(result.errors) - 10} more")

        if result.total_imported == 0:
            return

        print(f"\n  Positions:")
        rows = []
        for pos in result.positions:
            if pos.option_type:
                instrument = (
                    f"{pos.ticker} {pos.strike} {pos.option_type.upper()[:1]}"
                    f" {pos.expiration}"
                )
            else:
                instrument = pos.ticker
            rows.append({
                "Symbol": instrument,
                "Qty": pos.quantity,
                "Entry $": f"{pos.entry_price:.2f}",
                "Date": str(pos.entry_date),
                "Type": pos.structure_type,
            })
        print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

    def do_quit(self, arg: str) -> bool:
        """Exit the REPL."""
        print("Goodbye.")
        return True

    def do_exit(self, arg: str) -> bool:
        """Exit the REPL."""
        return self.do_quit(arg)

    do_EOF = do_quit

    def default(self, line: str) -> None:
        """Handle unknown commands."""
        print(f"Unknown command: '{line}'. Type 'help' for available commands.")

    def emptyline(self) -> None:
        """Do nothing on empty line (don't repeat last command)."""
        pass


def _ensure_utf8_stdout() -> None:
    """Reconfigure stdout to UTF-8 on Windows to handle Unicode payoff graphs."""
    import io
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    elif hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace",
        )


def main() -> None:
    _ensure_utf8_stdout()

    parser = argparse.ArgumentParser(description="Interactive market analyzer REPL")
    parser.add_argument(
        "--market",
        default="US",
        choices=["US", "India"],
        help="Default market (default: US)",
    )
    parser.add_argument(
        "--broker",
        action="store_true",
        help="Connect to TastyTrade broker for live quotes/Greeks",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run first-time setup wizard (configure broker credentials)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Start with $100K demo portfolio",
    )
    parser.add_argument(
        "--sim",
        choices=[
            "calm", "volatile", "crash", "india", "snapshot",
            "income", "recovery", "wheel", "india_trading",
        ],
        help=(
            "Start with simulated market data — no broker or internet required. "
            "Scenarios: calm (R1-like), volatile (R2-like), crash (R4-like), india (NSE), "
            "snapshot (last saved live capture), "
            "income (R1 elevated IV — all gates pass), "
            "recovery (post-crash R2, very rich premiums), "
            "wheel (stocks at support, CSP-ready), "
            "india_trading (NIFTY/BANKNIFTY with tradeable IV). "
            "Trust: UNRELIABLE — for testing/development only."
        ),
    )
    parser.add_argument(
        "--trader",
        choices=["us", "india"],
        help="Run full end-to-end trading simulation and print report. No REPL is started.",
    )
    args = parser.parse_args()

    if args.trader:
        from income_desk.demo.trader import (
            print_trader_report,
            run_india_trader,
            run_us_trader,
        )

        if args.trader == "us":
            report = run_us_trader()
        else:
            report = run_india_trader()
        print_trader_report(report)
        return

    if args.setup:
        from income_desk.cli._setup import run_setup_wizard
        run_setup_wizard()
        return

    if args.demo:
        from income_desk.demo import load_demo_portfolio, create_demo_portfolio
        port = load_demo_portfolio()
        if port is None:
            print("Creating demo portfolio ($100,000, moderate risk)...")
            port = create_demo_portfolio()
            print(f"Created! {len(port.desks)} desks allocated.")
            print("Run 'portfolio' to see your desk allocation.")
            print("Run 'trade SPY' to place your first simulated trade.")
        else:
            print(f"Demo portfolio loaded: ${port.current_nlv:,.0f} NLV, {len(port.positions)} open positions")

    sim_market_data = None
    sim_market_metrics = None
    sim_account = None

    if args.sim:
        from income_desk.adapters.simulated import (
            SimulatedAccount,
            SimulatedMetrics,
            create_calm_market,
            create_crash_scenario,
            create_india_market,
            create_volatile_market,
            create_ideal_income,
            create_post_crash_recovery,
            create_wheel_opportunity,
            create_india_trading,
        )

        if args.sim == "snapshot":
            from income_desk.adapters.simulated import (
                create_from_snapshot,
                get_snapshot_info,
            )
            info = get_snapshot_info()
            if info:
                age_str = f"{info['age_hours']:.0f}h ago" if info["age_hours"] is not None else "unknown age"
                print(_styled(f"[SIM] Loading snapshot from {info['captured_at']} ({age_str})", "yellow"))
                print(_styled(f"Tickers: {', '.join(info['tickers'])}", "yellow"))
            sim_market_data = create_from_snapshot()
            if sim_market_data is None:
                print("No snapshot found. Run 'refresh_sim' during market hours with --broker.")
                return
            sim_market_metrics = SimulatedMetrics(sim_market_data)
            sim_account = SimulatedAccount()
        else:
            _sim_scenarios = {
                "calm": create_calm_market,
                "volatile": create_volatile_market,
                "crash": create_crash_scenario,
                "india": create_india_market,
                "income": create_ideal_income,
                "recovery": create_post_crash_recovery,
                "wheel": create_wheel_opportunity,
                "india_trading": create_india_trading,
            }
            sim_market_data = _sim_scenarios[args.sim]()
            sim_market_metrics = SimulatedMetrics(sim_market_data)
            sim_account = SimulatedAccount()
            print(_styled(f"[SIM] Scenario: {args.sim}", "yellow"))
        print(_styled("Trust: UNRELIABLE — simulated data, for testing/development only.", "yellow"))

    try:
        cli = AnalyzerCLI(
            market=args.market,
            broker=args.broker,
            sim_market_data=sim_market_data,
            sim_market_metrics=sim_market_metrics,
            sim_account=sim_account,
        )
        cli.cmdloop()
    except KeyboardInterrupt:
        print("\nGoodbye.")


if __name__ == "__main__":
    main()
