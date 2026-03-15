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


from market_analyzer.cli._broker import _styled, connect_broker

# Trade lifecycle & factory imports (lazy-safe: all are pure functions)
from market_analyzer.trade_lifecycle import (
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
from market_analyzer.trade_spec_factory import (
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
    from market_analyzer.models.opportunity import get_structure_profile, RiskProfile
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

    def __init__(self, market: str = "US", broker: bool = False) -> None:
        super().__init__()
        self._market = market
        self._broker = broker
        self._ma = None  # Lazy-init
        self._watchlist_provider = None  # Set on broker connect

    def _get_ma(self):
        """Lazy-initialize MarketAnalyzer (avoids slow import on startup)."""
        if self._ma is None:
            print("Initializing services...")
            from market_analyzer import DataService, MarketAnalyzer

            market_data = None
            market_metrics = None
            account_provider = None

            if self._broker:
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
        """Parse tickers from arg, supporting --watchlist NAME.

        If --watchlist NAME is given and broker is connected, pulls tickers
        from the named TastyTrade watchlist. Can combine with explicit tickers.
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
            elif parts[i].startswith("--"):
                break  # Stop at other flags
            else:
                tickers.append(parts[i].upper())
                i += 1
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

        from market_analyzer.models.universe import PRESETS, UniverseFilter

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
            from market_analyzer.config import get_settings
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
            from market_analyzer.models.entry import EntryTriggerType
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
            from market_analyzer.config import get_settings
            tickers = get_settings().display.default_tickers

        try:
            ma = self._get_ma()
            if not ma.quotes.has_broker:
                print(_styled(
                    "WARNING: No broker connected — options pricing unavailable. "
                    "Ranking uses historical data only (no live quotes/Greeks).\n"
                    "For full data: analyzer-cli --broker\n", "yellow",
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
                from market_analyzer.models.trading_plan import PlanHorizon
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
            from market_analyzer.config import get_settings
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

            from market_analyzer.macro_indicators import compute_macro_dashboard

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
                        from market_analyzer.opportunity.setups.orb import assess_orb as _orb_assess
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
            from market_analyzer.models.opportunity import (
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

            from market_analyzer.models.opportunity import (
                LegAction, LegSpec, OrderSide, StructureType, TradeSpec,
            )
            from datetime import timedelta
            from market_analyzer.opportunity.option_plays._trade_spec_helpers import compute_otm_strike, snap_strike

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
            from market_analyzer.models.opportunity import (
                LegAction, LegSpec, OrderSide, StructureType, TradeSpec,
            )
            from datetime import timedelta
            from market_analyzer.opportunity.option_plays._trade_spec_helpers import compute_otm_strike, snap_strike

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

            from market_analyzer.models.opportunity import (
                LegAction, LegSpec, OrderSide, StructureType, TradeSpec,
            )
            from datetime import timedelta
            from market_analyzer.opportunity.option_plays._trade_spec_helpers import compute_otm_strike, snap_strike

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

            from market_analyzer.models.opportunity import (
                LegAction, LegSpec, OrderSide, StructureType, TradeSpec,
            )
            from datetime import timedelta
            from market_analyzer.opportunity.option_plays._trade_spec_helpers import compute_otm_strike, snap_strike

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
            from market_analyzer.models.opportunity import LegAction, LegSpec, OrderSide, StructureType, TradeSpec
            from market_analyzer.opportunity.option_plays._trade_spec_helpers import (
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
                from market_analyzer.opportunity.option_plays._trade_spec_helpers import (
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
            pnl_str = f"${result.pnl_estimate:+.2f}" if result.pnl_estimate is not None else "N/A (no broker)"
            print(f"  P&L: {pnl_str}  |  Regime: R{result.regime_id}")

            # Adjustments
            print()
            for i, adj in enumerate(result.adjustments, 1):
                type_label = adj.adjustment_type.value.upper().replace("_", " ")
                print(f"  #{i}  {_styled(type_label, 'bold')} — {adj.rationale}")
                if adj.estimated_cost is not None:
                    cost_str = f"${adj.estimated_cost:+.2f}" if adj.estimated_cost != 0 else "$0"
                else:
                    cost_str = _styled("N/A", "dim")
                risk_str = f"${adj.risk_change:+.0f}" if adj.risk_change != 0 else "unchanged"
                if adj.efficiency is not None:
                    eff_str = f"{adj.efficiency:.2f}"
                elif adj.estimated_cost is not None and adj.estimated_cost <= 0 and adj.risk_change < 0:
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
                if adj.estimated_cost is not None and adj.estimated_cost > 0 and adj.risk_change < 0:
                    ratio = abs(adj.risk_change) / adj.estimated_cost
                    if ratio < 1.0:
                        print(f"      {_styled(f'⚠ POOR — paying ${adj.estimated_cost:.2f} to reduce ${abs(adj.risk_change):.0f} risk', 'yellow')}")
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

                    from market_analyzer.models.opportunity import (
                        LegAction, LegSpec, OrderSide, StructureType, TradeSpec,
                    )
                    from datetime import timedelta
                    from market_analyzer.opportunity.option_plays._trade_spec_helpers import (
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
            from market_analyzer.trade_lifecycle import assess_overnight_risk

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

            from market_analyzer.execution_quality import validate_execution_quality

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
        print(f"    {_styled('from market_analyzer.performance import compute_performance_report, calibrate_weights', 'dim')}")
        print(f"    {_styled('from market_analyzer.models.feedback import TradeOutcome', 'dim')}")
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
        print(f"  {_styled('from market_analyzer import compute_sharpe', 'dim')}")
        print(f"  {_styled('result = compute_sharpe(outcomes, risk_free_rate=0.05)', 'dim')}")
        print(f"  {_styled('# -> SharpeResult(sharpe_ratio, sortino_ratio, annualized_return_pct, ...)', 'dim')}")

    def do_drawdown(self, arg: str) -> None:
        """Compute max drawdown from trade outcomes.\nUsage: drawdown\n\nRequires TradeOutcome records from eTrading."""
        _print_header("Drawdown Analysis")
        print(f"\n  {_styled('Not available in standalone CLI.', 'yellow')}")
        print()
        print("  Requires TradeOutcome records from eTrading.")
        print(f"  {_styled('from market_analyzer import compute_drawdown', 'dim')}")
        print(f"  {_styled('result = compute_drawdown(outcomes)', 'dim')}")
        print(f"  {_styled('# -> DrawdownResult(max_drawdown_pct, max_drawdown_dollars, ...)', 'dim')}")

    def do_drift(self, arg: str) -> None:
        """Detect strategy performance drift.\nUsage: drift\n\nRequires TradeOutcome records from eTrading."""
        _print_header("Strategy Drift Detection")
        print(f"\n  {_styled('Not available in standalone CLI.', 'yellow')}")
        print()
        print("  Requires TradeOutcome records from eTrading.")
        print(f"  {_styled('from market_analyzer import detect_drift', 'dim')}")
        print(f"  {_styled('alerts = detect_drift(outcomes, window=20)', 'dim')}")
        print(f"  {_styled('# -> list[DriftAlert] with severity WARNING/CRITICAL', 'dim')}")

    def do_bandit(self, arg: str) -> None:
        """Thompson Sampling strategy selection.\nUsage: bandit\n\nRequires trade history from eTrading."""
        _print_header("Thompson Sampling Bandits")
        print(f"\n  {_styled('Not available in standalone CLI.', 'yellow')}")
        print()
        print("  Requires trade outcome history from eTrading.")
        print(f"  {_styled('from market_analyzer import build_bandits, select_strategies', 'dim')}")
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
        """Assess same-ticker hedge for a position.
        Usage: hedge TICKER [POSITION_TYPE]
          POSITION_TYPE: long_equity, iron_condor, credit_spread, short_straddle (default: long_equity)
        Example: hedge NIFTY iron_condor"""
        ma = self._get_ma()
        parts = arg.strip().split()
        if not parts:
            print("Usage: hedge TICKER [POSITION_TYPE]")
            print("  POSITION_TYPE: long_equity, iron_condor, credit_spread, short_straddle")
            print("  Example: hedge SPY long_equity")
            print("  Example: hedge NIFTY iron_condor")
            return

        ticker = parts[0].upper()
        position_type = parts[1].lower() if len(parts) > 1 else "long_equity"

        valid_types = {"long_equity", "iron_condor", "credit_spread", "short_straddle"}
        if position_type not in valid_types:
            print(f"Invalid position type: {position_type}")
            print(f"  Valid types: {', '.join(sorted(valid_types))}")
            return

        _print_header(f"Hedge Assessment: {ticker} ({position_type})")

        try:
            regime = ma.regime.detect(ticker)
            tech = ma.technicals.snapshot(ticker)
        except Exception as e:
            print(f"  {_styled(f'Error fetching data for {ticker}: {e}', 'red')}")
            return

        current_price = tech.current_price
        # Estimate position value: price * lot_size (100 for US options)
        try:
            inst = ma.registry.get_instrument(ticker)
            lot_size = inst.lot_size or 100
        except KeyError:
            lot_size = 100
        position_value = current_price * lot_size

        regime_name = {1: "R1 Low-Vol MR", 2: "R2 High-Vol MR",
                       3: "R3 Low-Vol Trend", 4: "R4 High-Vol Trend"}.get(
            int(regime.regime), f"R{regime.regime}")

        print(f"\n  Ticker:    {_styled(ticker, 'cyan')}")
        print(f"  Price:     ${current_price:,.2f}")
        print(f"  Position:  {position_type.replace('_', ' ').title()}")
        print(f"  Regime:    {_styled(regime_name, 'yellow')} ({regime.confidence:.0%})")
        print(f"  Est Value: ${position_value:,.0f}")

        # Hedge decision tree (from HEDGING_PLAN.md)
        r = int(regime.regime)
        urgency = "none"
        recommendation = ""
        rationale = ""

        if position_type == "long_equity":
            if r == 1:
                recommendation = "NO HEDGE"
                rationale = "Theta decay on protective puts wastes money in range-bound regime"
                urgency = "none"
            elif r == 2:
                recommendation = "COLLAR"
                rationale = "Sell OTM call + buy OTM put — zero-cost hedge possible in high IV"
                urgency = "monitor"
            elif r == 3:
                trend = getattr(regime, "trend_direction", None)
                if trend and str(trend).lower() in ("bearish", "down"):
                    recommendation = "PROTECTIVE PUT"
                    rationale = "Counter-trend detected in low-vol trending regime"
                    urgency = "soon"
                else:
                    recommendation = "NO HEDGE"
                    rationale = "Trend is favorable — hedge would cap upside unnecessarily"
                    urgency = "none"
            elif r == 4:
                recommendation = "PROTECTIVE PUT"
                rationale = "High-vol trend regime — buy ATM put immediately"
                urgency = "immediate"

        elif position_type == "iron_condor":
            if r <= 2:
                recommendation = "NO HEDGE"
                rationale = "IC is already defined risk — wings are the hedge"
                urgency = "none"
            elif r == 3:
                recommendation = "DELTA HEDGE"
                rationale = "Add directional leg if trend threatens short strike"
                urgency = "soon"
            elif r == 4:
                recommendation = "CLOSE POSITION"
                rationale = "Iron condor in R4 is the wrong trade — exit, don't hedge"
                urgency = "immediate"

        elif position_type == "credit_spread":
            if r <= 2:
                recommendation = "NO HEDGE"
                rationale = "Defined risk position in mean-reverting regime"
                urgency = "none"
            elif r == 3:
                recommendation = "ROLL AWAY"
                rationale = "Roll short strike further OTM in direction of trend"
                urgency = "soon"
            elif r == 4:
                recommendation = "CLOSE POSITION"
                rationale = "Exit undefined-direction credit spread in volatile trend"
                urgency = "immediate"

        elif position_type == "short_straddle":
            if r == 1:
                recommendation = "NO HEDGE"
                rationale = "Mean-reverting regime supports straddle"
                urgency = "none"
            elif r == 2:
                recommendation = "ADD WINGS"
                rationale = "Convert to iron butterfly — define risk in high vol"
                urgency = "monitor"
            elif r == 3:
                recommendation = "DELTA HEDGE"
                rationale = "Add directional spread on trending side"
                urgency = "soon"
            elif r == 4:
                recommendation = "CLOSE POSITION"
                rationale = "Undefined risk in R4 = immediate exit"
                urgency = "immediate"

        # Color-coded urgency
        urgency_colors = {
            "none": "green", "monitor": "yellow", "soon": "yellow", "immediate": "red",
        }
        urgency_color = urgency_colors.get(urgency, "white")

        print(f"\n  {_styled('Recommendation:', 'bold')} {_styled(recommendation, urgency_color)}")
        print(f"  {_styled('Urgency:', 'bold')}        {_styled(urgency.upper(), urgency_color)}")
        print(f"  {_styled('Rationale:', 'bold')}      {rationale}")

        # ATR context
        if tech.atr_pct:
            print(f"\n  ATR:       {tech.atr_pct:.2f}% (${current_price * tech.atr_pct / 100:,.2f})")
        if tech.rsi:
            print(f"  RSI:       {tech.rsi.value:.1f}")
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

        from market_analyzer.currency import CurrencyPair, convert_amount, compute_currency_pnl

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
        print(f"  {_styled('from market_analyzer import compute_portfolio_exposure, CurrencyPair, PositionExposure', 'dim')}")
        print(f"  {_styled('positions = [PositionExposure(ticker=\"SPY\", market=\"US\", currency=\"USD\", ...)]', 'dim')}")
        print(f"  {_styled('rates = {{\"USD/INR\": CurrencyPair(base=\"USD\", quote=\"INR\", rate=83.5, ...)}}', 'dim')}")
        print(f"  {_styled('exposure = compute_portfolio_exposure(positions, rates)', 'dim')}")
        print(f"  {_styled('# -> PortfolioExposure with currency_risk_pct, converted totals', 'dim')}")
        print()
        print(f"  {_styled('from market_analyzer import assess_currency_exposure', 'dim')}")
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
        from market_analyzer.cross_market import analyze_cross_market

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
            from market_analyzer.cross_market import analyze_cross_market

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
    args = parser.parse_args()

    try:
        cli = AnalyzerCLI(market=args.market, broker=args.broker)
        cli.cmdloop()
    except KeyboardInterrupt:
        print("\nGoodbye.")


if __name__ == "__main__":
    main()
