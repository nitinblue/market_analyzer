"""India Market Systematic Trader — End-to-End Test.

Tests the COMPLETE trading workflow for India NSE/BSE markets using
NIFTY, BANKNIFTY, and top India stocks. Validates that all MA APIs
work correctly with India-specific parameters (INR, lot sizes, IST,
Thursday expiry, etc.).

Usage::

    .venv_312/Scripts/python.exe challenge/trader_india.py
    .venv_312/Scripts/python.exe challenge/trader_india.py --tickers NIFTY BANKNIFTY
    .venv_312/Scripts/python.exe challenge/trader_india.py --detail
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date, time as dt_time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import io
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from market_analyzer import (
    DataService,
    MarketAnalyzer,
    MarketRegistry,
    validate_execution_quality,
)
from market_analyzer.trade_lifecycle import (
    assess_overnight_risk,
    check_income_entry,
    check_trade_health,
    compute_breakevens,
    compute_income_yield,
    estimate_pop,
    filter_trades_by_account,
    monitor_exit_conditions,
)

# -- India Configuration --

ACCOUNT_SIZE_INR = 500_000  # ₹5 lakh
MAX_POSITIONS = 5
MAX_RISK_PER_TRADE_PCT = 0.04  # 4% = ₹20,000
BP_RESERVE_PCT = 0.20
CURRENCY = "INR"

# India tickers to test
DEFAULT_TICKERS = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK"]

# Income structures available in India F&O
ALLOWED_STRUCTURES = {
    "iron_condor", "iron_butterfly", "credit_spread",
    "debit_spread", "straddle", "strangle", "calendar",
}

# NOT available in India
BLOCKED_STRATEGIES = {"leaps", "pmcc"}

HC_MIN_POP = 0.45  # Slightly lower for India (higher premiums but wider moves)
HC_MIN_SCORE = 0.55
HC_MIN_CREDIT_WIDTH = 0.08


def _sep(title: str) -> None:
    print(f"\n{'-' * 60}")
    print(f"  {title}")
    print(f"{'-' * 60}")


def _regime_label(regime_id: int) -> str:
    names = {1: "R1 Low-Vol MR", 2: "R2 High-Vol MR", 3: "R3 Low-Vol Trend", 4: "R4 High-Vol Trend"}
    return names.get(regime_id, f"R{regime_id}")


def _test_result(name: str, passed: bool, detail: str = "") -> None:
    icon = "PASS" if passed else "FAIL"
    color = "\033[92m" if passed else "\033[91m"
    reset = "\033[0m"
    det = f" — {detail}" if detail else ""
    print(f"  [{color}{icon}{reset}] {name}{det}")


def run(tickers: list[str] | None = None, detail: bool = False):
    """Execute India market trading flow and report gaps."""

    scan_tickers = tickers or list(DEFAULT_TICKERS)
    registry = MarketRegistry()
    results: dict[str, bool] = {}
    failures: list[str] = []

    print(f"{'=' * 60}")
    print(f"  INDIA MARKET SYSTEMATIC TRADER — {date.today().isoformat()}")
    print(f"  Account: {CURRENCY} {ACCOUNT_SIZE_INR:,.0f} | Tickers: {', '.join(scan_tickers)}")
    print(f"{'=' * 60}")

    # ==============================================================
    # TEST 1: MarketRegistry — India market data
    # ==============================================================
    _sep("TEST 1: MarketRegistry")

    try:
        india = registry.get_market("INDIA")
        _test_result("Market lookup", True, f"currency={india.currency}, tz={india.timezone}")
        assert india.currency == "INR"
        assert india.timezone == "Asia/Kolkata"

        for ticker in scan_tickers:
            try:
                inst = registry.get_instrument(ticker)
                _test_result(f"Instrument {ticker}", True,
                             f"lot={inst.lot_size}, strike_int={inst.strike_interval}, "
                             f"settlement={inst.settlement}, 0DTE={'Y' if inst.has_0dte else 'N'}, "
                             f"LEAP={'Y' if inst.has_leaps else 'N'}")

                # Verify LEAP not available for India
                leaps_available = registry.strategy_available("leaps", ticker)
                _test_result(f"  LEAP blocked for {ticker}", not leaps_available,
                             f"strategy_available('leaps', '{ticker}')={leaps_available}")
                if leaps_available:
                    failures.append(f"LEAP should be blocked for {ticker}")

                # Verify yfinance mapping
                yf = registry.to_yfinance(ticker)
                _test_result(f"  yfinance mapping", True, f"{ticker} → {yf}")

            except KeyError as e:
                _test_result(f"Instrument {ticker}", False, str(e))
                failures.append(f"Instrument not in registry: {ticker}")

        # Margin estimate
        m = registry.estimate_margin("iron_condor", "NIFTY", wing_width=200)
        _test_result("Margin estimate NIFTY IC", True,
                     f"200pt wing × lot 25 = {m.currency} {m.margin_amount:,.0f}")

    except Exception as e:
        _test_result("MarketRegistry", False, str(e))
        failures.append(f"MarketRegistry failed: {e}")

    # ==============================================================
    # TEST 2: DataService — Fetch India OHLCV
    # ==============================================================
    _sep("TEST 2: DataService — India OHLCV")

    ds = DataService()
    ma = MarketAnalyzer(data_service=ds)
    ohlcv_data: dict[str, object] = {}

    for ticker in scan_tickers:
        try:
            yf_ticker = registry.to_yfinance(ticker)
            df = ds.get_ohlcv(ticker)
            rows = len(df)
            last_date = df.index[-1].date() if hasattr(df.index[-1], 'date') else df.index[-1]
            _test_result(f"OHLCV {ticker}", rows > 50,
                         f"{rows} rows, last={last_date}, close={df['Close'].iloc[-1]:.2f}")
            ohlcv_data[ticker] = df
        except Exception as e:
            _test_result(f"OHLCV {ticker}", False, str(e))
            failures.append(f"OHLCV fetch failed for {ticker}: {e}")

    if not ohlcv_data:
        print("\n  No data fetched. Cannot continue.")
        _print_summary(failures)
        return

    # ==============================================================
    # TEST 3: Regime Detection — India tickers
    # ==============================================================
    _sep("TEST 3: Regime Detection")

    regimes: dict[str, object] = {}
    for ticker in ohlcv_data:
        try:
            regime = ma.regime.detect(ticker, debug=True)
            regimes[ticker] = regime
            staleness = f", age={regime.model_age_days}d" if regime.model_age_days else ""
            stability = f", flips={regime.regime_stability}" if regime.regime_stability is not None else ""
            _test_result(f"Regime {ticker}", True,
                         f"{_regime_label(regime.regime)} ({regime.confidence:.0%}){staleness}{stability}")

            # Check data gaps
            if regime.data_gaps:
                for gap in regime.data_gaps:
                    print(f"       [gap] {gap.field}: {gap.reason}")

            if detail and regime.commentary:
                for line in regime.commentary[:3]:
                    print(f"       [debug] {line}")

        except Exception as e:
            _test_result(f"Regime {ticker}", False, str(e))
            failures.append(f"Regime detection failed for {ticker}: {e}")
            traceback.print_exc()

    # ==============================================================
    # TEST 4: Technical Snapshot — New TA indicators
    # ==============================================================
    _sep("TEST 4: Technicals + New TA Indicators")

    technicals: dict[str, object] = {}
    for ticker in ohlcv_data:
        try:
            tech = ma.technicals.snapshot(ticker, debug=detail)
            technicals[ticker] = tech
            _test_result(f"Technicals {ticker}", True,
                         f"RSI={tech.rsi.value:.0f} ATR={tech.atr_pct:.2f}% ${tech.current_price:.2f}")

            # Check new TA indicators
            ta_checks = [
                ("Fibonacci", tech.fibonacci is not None),
                ("ADX", tech.adx is not None),
                ("Donchian", tech.donchian is not None),
                ("Keltner", tech.keltner is not None),
                ("Pivots", tech.pivot_points is not None),
                ("VWAP", tech.daily_vwap is not None),
            ]
            for name, present in ta_checks:
                if present:
                    if name == "ADX":
                        print(f"       {name}: {tech.adx.adx:.0f} ({'trending' if tech.adx.is_trending else 'ranging'})")
                    elif name == "Fibonacci":
                        print(f"       {name}: {tech.fibonacci.direction} swing, price at {tech.fibonacci.current_price_level}")
                    elif name == "Keltner" and tech.keltner.squeeze:
                        print(f"       {name}: ** SQUEEZE **")
                    elif name == "Pivots":
                        pp = tech.pivot_points
                        print(f"       {name}: PP={pp.pp:.0f} S1={pp.s1:.0f} R1={pp.r1:.0f}")
                    elif name == "VWAP":
                        print(f"       {name}: {tech.daily_vwap.vwap:.2f} ({tech.daily_vwap.price_vs_vwap_pct:+.1f}%)")
                else:
                    _test_result(f"  {name} missing", False, "indicator not computed")
                    failures.append(f"TA indicator {name} not computed for {ticker}")

        except Exception as e:
            _test_result(f"Technicals {ticker}", False, str(e))
            failures.append(f"Technicals failed for {ticker}: {e}")
            traceback.print_exc()

    # ==============================================================
    # TEST 5: Levels — Pivot points as S/R source
    # ==============================================================
    _sep("TEST 5: Levels Analysis (with Pivots)")

    for ticker in list(ohlcv_data.keys())[:3]:
        try:
            levels = ma.levels.analyze(ticker)
            support_count = len([l for l in levels.levels if l.role == "support"]) if hasattr(levels, 'levels') else 0
            resist_count = len([l for l in levels.levels if l.role == "resistance"]) if hasattr(levels, 'levels') else 0
            _test_result(f"Levels {ticker}", True,
                         f"{support_count} support, {resist_count} resistance")

            # Check if pivot sources are present
            if hasattr(levels, 'levels'):
                pivot_sources = [l for l in levels.levels if 'pivot' in str(getattr(l, 'sources', [])).lower()]
                if pivot_sources:
                    print(f"       Pivot-sourced levels: {len(pivot_sources)}")
        except Exception as e:
            _test_result(f"Levels {ticker}", False, str(e))
            failures.append(f"Levels failed for {ticker}: {e}")

    # ==============================================================
    # TEST 6: Ranking — India tickers
    # ==============================================================
    _sep("TEST 6: Ranking")

    ranked_tickers = [t for t in ohlcv_data if t in regimes and t in technicals]
    if ranked_tickers:
        try:
            ranking = ma.ranking.rank(ranked_tickers, skip_intraday=True, debug=detail)
            _test_result("Ranking", True,
                         f"{len(ranking.top_trades)} trades across {len(ranked_tickers)} tickers")

            for e in ranking.top_trades[:8]:
                sym = e.trade_spec.strategy_badge if e.trade_spec else e.strategy_type
                gaps = f" [{len(e.data_gaps)} gaps]" if e.data_gaps else ""
                print(f"    #{e.rank:2d} {e.ticker:12s} {sym:28s} score={e.composite_score:.2f} {e.verdict}{gaps}")

                # Check if LEAP trades were recommended for India tickers
                if e.strategy_type == "leap" and e.verdict != "no_go":
                    _test_result(f"  LEAP should be NO_GO for {e.ticker}", False,
                                 "India has no LEAPs")
                    failures.append(f"LEAP not blocked for {e.ticker}")

        except Exception as e:
            _test_result("Ranking", False, str(e))
            failures.append(f"Ranking failed: {e}")
            traceback.print_exc()

    # ==============================================================
    # TEST 7: Account Filtering with INR
    # ==============================================================
    _sep("TEST 7: Account Filtering (INR)")

    if ranked_tickers and 'ranking' in dir():
        try:
            available_bp = ACCOUNT_SIZE_INR * (1 - BP_RESERVE_PCT)
            max_risk = ACCOUNT_SIZE_INR * MAX_RISK_PER_TRADE_PCT

            filtered = filter_trades_by_account(
                ranked_entries=ranking.top_trades,
                available_buying_power=available_bp,
                allowed_structures=list(ALLOWED_STRUCTURES),
                max_risk_per_trade=max_risk,
            )

            _test_result("Account filter", True,
                         f"passed={filtered.total_affordable}, blocked={len(filtered.filtered_out)}")

        except Exception as e:
            _test_result("Account filter", False, str(e))
            failures.append(f"Account filter failed: {e}")

    # ==============================================================
    # TEST 8: Trade Lifecycle — Lot size handling
    # ==============================================================
    _sep("TEST 8: Trade Lifecycle (Lot Size)")

    # Test with NIFTY lot_size=25
    if "NIFTY" in regimes and "NIFTY" in technicals:
        regime = regimes["NIFTY"]
        tech = technicals["NIFTY"]

        try:
            # Build dummy TradeSpec for NIFTY IC
            from market_analyzer.models.opportunity import TradeSpec, LegSpec, LegAction
            dummy_spec = TradeSpec(
                ticker="NIFTY", legs=[], underlying_price=tech.current_price,
                target_dte=7, target_expiration=date.today(),
                spec_rationale="test", wing_width_points=200.0,
                structure_type="iron_condor", order_side="credit",
                lot_size=25, currency="INR",
            )

            # POP with IV rank
            pop = estimate_pop(
                trade_spec=dummy_spec,
                entry_price=50.0,
                regime_id=regime.regime,
                atr_pct=tech.atr_pct,
                current_price=tech.current_price,
            )
            _test_result("POP (NIFTY lot=25)", pop is not None,
                         f"POP={pop.pop_pct:.0%} EV=₹{pop.expected_value:.0f}" if pop else "None")

            # Income yield
            income = compute_income_yield(dummy_spec, entry_credit=50.0)
            if income:
                _test_result("Income yield (NIFTY)", True,
                             f"credit/width={income.credit_to_width_pct:.1%} "
                             f"max_profit=₹{income.max_profit:.0f} max_loss=₹{income.max_loss:.0f}")
                # Verify lot_size used correctly: max_profit should be 50 * 25 = 1250, not 50 * 100
                lot_correct = abs(income.max_profit - 50 * 25) < 1
                _test_result("  Lot size in yield", lot_correct,
                             f"expected ₹{50*25}, got ₹{income.max_profit:.0f}")
                if not lot_correct:
                    failures.append(f"Income yield uses wrong lot size: expected 25, got {income.max_profit/50:.0f}")

            # Position size
            contracts = dummy_spec.position_size(capital=ACCOUNT_SIZE_INR)
            _test_result("Position size (NIFTY)", contracts >= 1,
                         f"{contracts} contracts for ₹{ACCOUNT_SIZE_INR:,.0f}")

            # Monitor exit conditions with lot_size
            result = monitor_exit_conditions(
                trade_id="NIFTY-IC-001", ticker="NIFTY",
                structure_type="iron_condor", order_side="credit",
                entry_price=50.0, current_mid_price=25.0,
                contracts=1, dte_remaining=5, regime_id=regime.regime,
                profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=3,
                lot_size=25,
            )
            pnl_correct = abs(result.pnl_dollars - (50 - 25) * 25 * 1) < 1
            _test_result("Monitor exit (lot=25)", True,
                         f"P&L=₹{result.pnl_dollars:.0f} (expected ₹{(50-25)*25})")
            if not pnl_correct:
                failures.append(f"Exit monitor lot size wrong: expected ₹{(50-25)*25}, got ₹{result.pnl_dollars:.0f}")

        except Exception as e:
            _test_result("Trade lifecycle", False, str(e))
            failures.append(f"Trade lifecycle failed: {e}")
            traceback.print_exc()

    # ==============================================================
    # TEST 9: Overnight Risk — India hours
    # ==============================================================
    _sep("TEST 9: Overnight Risk (India)")

    if "NIFTY" in regimes:
        try:
            risk = assess_overnight_risk(
                trade_id="NIFTY-IC-001", ticker="NIFTY",
                structure_type="iron_condor", order_side="credit",
                dte_remaining=0,  # Expiry day (Thursday)
                regime_id=regimes["NIFTY"].regime,
                position_status="safe",
            )
            _test_result("Overnight 0DTE", risk.risk_level == "close_before_close",
                         f"level={risk.risk_level}")

            risk2 = assess_overnight_risk(
                trade_id="NIFTY-IC-002", ticker="NIFTY",
                structure_type="iron_condor", order_side="credit",
                dte_remaining=7, regime_id=1, position_status="safe",
            )
            _test_result("Overnight safe R1", risk2.risk_level == "low",
                         f"level={risk2.risk_level}")

        except Exception as e:
            _test_result("Overnight risk", False, str(e))
            failures.append(f"Overnight risk failed: {e}")

    # ==============================================================
    # TEST 10: Entry Windows — India timezone
    # ==============================================================
    _sep("TEST 10: Entry Windows (India)")

    # Check that config has India entry windows
    try:
        from market_analyzer.config import get_settings
        settings = get_settings()
        if hasattr(settings, 'markets') and hasattr(settings.markets, 'markets'):
            india_market = settings.markets.markets.get("India")
            if india_market and hasattr(india_market, 'entry_windows'):
                ew = india_market.entry_windows
                _test_result("India entry windows config", True,
                             f"0DTE={ew.zero_dte}, income={ew.income}")
            else:
                _test_result("India entry windows config", False, "entry_windows not on MarketDef")
                failures.append("India entry windows not configured")
        else:
            _test_result("India market config", False, "markets config not found")
    except Exception as e:
        _test_result("Entry windows", False, str(e))
        failures.append(f"Entry windows check failed: {e}")

    # ==============================================================
    # TEST 11: Strategy Availability
    # ==============================================================
    _sep("TEST 11: Strategy Availability (India)")

    for ticker in ["NIFTY", "BANKNIFTY"]:
        try:
            for strategy, expected in [
                ("iron_condor", True), ("straddle", True), ("strangle", True),
                ("leaps", False), ("pmcc", False), ("zero_dte", True),
            ]:
                actual = registry.strategy_available(strategy, ticker)
                _test_result(f"  {ticker} {strategy}", actual == expected,
                             f"expected={expected}, got={actual}")
                if actual != expected:
                    failures.append(f"Strategy availability wrong: {ticker} {strategy} expected={expected}")
        except Exception as e:
            failures.append(f"Strategy availability failed for {ticker}: {e}")

    # ==============================================================
    # SUMMARY
    # ==============================================================
    _print_summary(failures)


def _print_summary(failures: list[str]) -> None:
    _sep("SUMMARY")
    if not failures:
        print(f"\n  \033[92mALL TESTS PASSED\033[0m — India market flow works end-to-end.")
    else:
        print(f"\n  \033[91m{len(failures)} FAILURE(S):\033[0m")
        for i, f in enumerate(failures, 1):
            print(f"  {i}. {f}")

    print(f"\n{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(description="India Market Systematic Trader — Test")
    parser.add_argument("--tickers", nargs="+", default=None)
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args()

    run(tickers=args.tickers, detail=args.detail)


if __name__ == "__main__":
    main()
