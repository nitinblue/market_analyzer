"""Live Market Drill -- End-to-end broker validation.

Connects to TastyTrade, fetches real positions/balance/quotes,
runs regime + ranking + health checks, validates number sanity.

Usage:
    .venv_312/Scripts/python -X utf8 scripts/live_drill.py
"""
from __future__ import annotations

import os
import sys

# Ensure project root is on sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import traceback
from datetime import date, datetime

# -- Drill result tracking ---------------------------------------------------
PASS = 0
FAIL = 0
WARN = 0
RESULTS: list[tuple[str, str, str]] = []


def _record(name: str, status: str, detail: str = "") -> None:
    global PASS, FAIL, WARN
    RESULTS.append((name, status, detail))
    if status == "PASS":
        PASS += 1
    elif status == "FAIL":
        FAIL += 1
    else:
        WARN += 1
    icon = {"PASS": "OK", "FAIL": "XX", "WARN": "!!"}.get(status, "??")
    print(f"  [{icon}] {name}: {status} {detail}")


def _section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# -- 1. Broker Connection ----------------------------------------------------
def test_broker_connection():
    _section("1. BROKER CONNECTION")
    from income_desk.cli._broker import connect_broker
    md, mm, acct, wl = connect_broker()
    if md is None:
        _record("broker_connect", "FAIL", "No broker -- check credentials")
        return None, None, None, None
    _record("broker_connect", "PASS", "TastyTrade session active")
    return md, mm, acct, wl


# -- 2. Account Balance ------------------------------------------------------
def test_balance(acct):
    _section("2. ACCOUNT BALANCE")
    if acct is None:
        _record("balance_fetch", "FAIL", "No account provider")
        return None

    bal = acct.get_balance()
    nlv = bal.net_liquidating_value
    cash = bal.cash_balance
    bp = bal.derivative_buying_power
    maint = bal.maintenance_requirement

    print(f"    Account:     {bal.account_number}")
    print(f"    NLV:         ${nlv:>12,.2f}")
    print(f"    Cash:        ${cash:>12,.2f}")
    print(f"    Option BP:   ${bp:>12,.2f}")
    print(f"    Maint Req:   ${maint:>12,.2f}")

    if nlv <= 0:
        _record("balance_nlv", "FAIL", f"NLV is ${nlv:,.2f}")
    elif nlv < 1_000:
        _record("balance_nlv", "WARN", f"NLV ${nlv:,.2f} -- suspiciously low")
    else:
        _record("balance_nlv", "PASS", f"${nlv:,.2f}")

    if cash < 0 and abs(cash) > nlv:
        _record("balance_cash", "WARN", f"Negative cash ${cash:,.2f} > NLV")
    else:
        _record("balance_cash", "PASS", f"${cash:,.2f}")

    if bp < 0:
        _record("balance_bp", "FAIL", f"Negative buying power ${bp:,.2f}")
    elif bp > nlv * 3:
        _record("balance_bp", "WARN", f"BP ${bp:,.2f} > 3x NLV")
    else:
        _record("balance_bp", "PASS", f"${bp:,.2f}")

    return bal


# -- 3. Positions -------------------------------------------------------------
def test_positions(acct):
    _section("3. LIVE POSITIONS")
    if acct is None:
        _record("positions_fetch", "FAIL", "No account provider")
        return []

    positions = acct.get_positions()
    print(f"    Found {len(positions)} positions")

    if not positions:
        _record("positions_fetch", "WARN", "No open positions")
        return []

    _record("positions_fetch", "PASS", f"{len(positions)} positions")

    # Extract underlying tickers (dedupe)
    underlyings = set()
    for pos in positions:
        ticker = getattr(pos, 'symbol', getattr(pos, 'underlying_symbol', '?'))
        qty = getattr(pos, 'quantity', getattr(pos, 'signed_quantity', '?'))
        ptype = getattr(pos, 'instrument_type', getattr(pos, 'type', '?'))
        close_price = getattr(pos, 'close_price', None)

        detail = f"{ticker} qty={qty} type={ptype}"
        if close_price is not None:
            detail += f" close=${close_price:,.4f}"
        print(f"      {detail}")

        # Extract underlying ticker
        underlying = getattr(pos, 'ticker', None)
        if underlying:
            underlyings.add(underlying)

    print(f"    Underlying tickers: {sorted(underlyings)}")
    return positions, sorted(underlyings)


# -- 4. Live Quotes -----------------------------------------------------------
def test_quotes(ma, tickers):
    _section("4. LIVE QUOTES (broker)")
    for ticker in tickers[:6]:
        try:
            snap = ma.quotes.get_chain(ticker)
            price = snap.underlying_price
            source = snap.source
            n_quotes = len(snap.quotes) if snap.quotes else 0

            if price is None or price <= 0:
                _record(f"quote_{ticker}", "FAIL", "No underlying price")
            elif source == "simulated":
                _record(f"quote_{ticker}", "WARN", f"${price:.2f} source=SIMULATED")
            else:
                _record(f"quote_{ticker}", "PASS", f"${price:.2f} src={source} chains={n_quotes}")

            # IV Rank from broker metrics
            metrics = ma.quotes.get_metrics(ticker)
            if metrics and metrics.iv_rank is not None:
                ivr = metrics.iv_rank
                if ivr < 0 or ivr > 100:
                    _record(f"ivrank_{ticker}", "FAIL", f"IV Rank {ivr:.1f} out of [0,100]")
                else:
                    _record(f"ivrank_{ticker}", "PASS", f"IV Rank {ivr:.1f}")
            else:
                _record(f"ivrank_{ticker}", "WARN", "No IV Rank from broker")

        except Exception as e:
            _record(f"quote_{ticker}", "FAIL", f"Exception: {e}")


# -- 5. Regime Detection -------------------------------------------------------
def test_regime(ma, tickers):
    _section("5. REGIME DETECTION")
    for ticker in tickers[:5]:
        try:
            r = ma.regime.detect(ticker)
            # Fields: regime (int), confidence (float)
            state = r.regime
            conf = r.confidence

            if state < 1 or state > 4:
                _record(f"regime_{ticker}", "FAIL", f"State {state} outside R1-R4")
            elif conf < 0.25:
                _record(f"regime_{ticker}", "WARN", f"R{state} conf={conf:.0%} -- very low")
            else:
                _record(f"regime_{ticker}", "PASS", f"R{state} conf={conf:.0%}")

        except Exception as e:
            _record(f"regime_{ticker}", "FAIL", f"Exception: {e}")


# -- 6. Ranking ----------------------------------------------------------------
def test_ranking(ma, tickers):
    _section("6. RANKING (broker-enhanced)")
    try:
        result = ma.ranking.rank(tickers)
        # Fields: top_trades (list[RankedEntry]), total_assessed, total_actionable
        ranked = result.top_trades
        print(f"    Assessed: {result.total_assessed} | Actionable: {result.total_actionable}")

        if not ranked:
            _record("ranking", "WARN", "No actionable trades ranked")
            return

        _record("ranking", "PASS", f"{len(ranked)} trades ranked")

        for item in ranked[:5]:
            ticker = item.ticker
            score = item.composite_score
            verdict = item.verdict
            strat = item.strategy_name

            if score < 0 or score > 100:
                _record(f"rank_{ticker}", "FAIL", f"Score {score:.1f} out of [0,100]")
            else:
                _record(f"rank_{ticker}", "PASS", f"Score {score:.1f} {strat} -> {verdict}")

            # Check trade spec
            if item.trade_spec:
                ts = item.trade_spec
                st = ts.structure_type.value if hasattr(ts.structure_type, 'value') else str(ts.structure_type)
                entry = f"${ts.max_entry_price:.2f}" if ts.max_entry_price else "N/A"
                print(f"      {ticker}: {st} {ts.target_dte}DTE entry={entry}")

    except Exception as e:
        _record("ranking", "FAIL", f"Exception: {e}")
        traceback.print_exc()


# -- 7. Daily Plan --------------------------------------------------------------
def test_daily_plan(ma, tickers):
    _section("7. DAILY PLAN")
    try:
        # DailyTradingPlan fields: day_verdict, all_trades, total_trades, summary
        plan = ma.plan.generate(tickers=tickers[:5], skip_intraday=True)

        print(f"    Date:        {plan.plan_for_date}")
        print(f"    Verdict:     {plan.day_verdict}")
        print(f"    Trades:      {plan.total_trades}")
        print(f"    Summary:     {plan.summary[:100] if plan.summary else 'N/A'}")

        if plan.total_trades > 0:
            _record("plan_trades", "PASS", f"{plan.total_trades} trade ideas")
        else:
            _record("plan_trades", "WARN", "No trade ideas in plan")

        if plan.day_verdict:
            _record("plan_verdict", "PASS", f"{plan.day_verdict}")
        else:
            _record("plan_verdict", "WARN", "No day verdict")

        if plan.data_warnings:
            for w in plan.data_warnings[:3]:
                print(f"    DATA WARNING: {w}")

    except Exception as e:
        _record("daily_plan", "FAIL", f"Exception: {e}")
        traceback.print_exc()


# -- 8. Risk Check --------------------------------------------------------------
def test_risk(acct):
    _section("8. RISK METRICS")
    if acct is None:
        _record("risk", "FAIL", "No account provider")
        return

    try:
        bal = acct.get_balance()
        positions = acct.get_positions()

        nlv = bal.net_liquidating_value
        maint = bal.maintenance_requirement
        bp = bal.derivative_buying_power

        if nlv > 0 and maint > 0:
            margin_util = maint / nlv
            print(f"    Margin utilization: {margin_util:.1%}")
            if margin_util > 0.80:
                _record("margin_util", "FAIL", f"{margin_util:.1%} -- dangerous")
            elif margin_util > 0.50:
                _record("margin_util", "WARN", f"{margin_util:.1%} -- elevated")
            else:
                _record("margin_util", "PASS", f"{margin_util:.1%}")
        else:
            _record("margin_util", "PASS", "No margin used")

        if nlv > 0:
            bp_ratio = bp / nlv
            print(f"    BP/NLV ratio:      {bp_ratio:.1%}")
            if bp_ratio < 0.10:
                _record("bp_ratio", "WARN", f"{bp_ratio:.1%} -- low BP")
            else:
                _record("bp_ratio", "PASS", f"{bp_ratio:.1%}")

        n_pos = len(positions)
        max_rec = 20 if nlv > 100_000 else 10 if nlv > 50_000 else 5
        print(f"    Positions: {n_pos} (max recommended: {max_rec} for ${nlv:,.0f})")
        if n_pos > max_rec:
            _record("position_count", "WARN", f"{n_pos} > {max_rec}")
        else:
            _record("position_count", "PASS", f"{n_pos} positions")

    except Exception as e:
        _record("risk", "FAIL", f"Exception: {e}")
        traceback.print_exc()


# -- 9. Cross-Validation -------------------------------------------------------
def test_number_confidence(ma):
    _section("9. NUMBER CROSS-VALIDATION")
    try:
        from income_desk import DataService
        ds = DataService()

        # yfinance SPY close
        yf_data = ds.get_ohlcv("SPY")
        if yf_data is not None and len(yf_data) > 0:
            yf_price = float(yf_data["Close"].iloc[-1])
        else:
            yf_price = None

        # Broker SPY price
        snap = ma.quotes.get_chain("SPY")
        broker_price = snap.underlying_price if snap else None

        if yf_price and broker_price:
            diff_pct = abs(broker_price - yf_price) / yf_price
            print(f"    SPY yfinance (prior close): ${yf_price:.2f}")
            print(f"    SPY broker (live):          ${broker_price:.2f}")
            print(f"    Diff:                       {diff_pct:.2%}")
            print(f"    (Note: yfinance = prior close, broker = live. Gap expected during market hours.)")

            if diff_pct > 0.10:
                _record("spy_xcheck", "FAIL", f"10%+ divergence yf=${yf_price:.2f} vs broker=${broker_price:.2f}")
            elif diff_pct > 0.05:
                _record("spy_xcheck", "WARN", f"5%+ diff -- large intraday move?")
            else:
                _record("spy_xcheck", "PASS", f"delta {diff_pct:.2%} (within normal intraday range)")
        else:
            _record("spy_xcheck", "WARN", f"Missing source: yf={yf_price} broker={broker_price}")

    except Exception as e:
        _record("spy_xcheck", "FAIL", f"Exception: {e}")


# -- MAIN ----------------------------------------------------------------------
def main():
    print(f"\n{'#'*60}")
    print(f"  LIVE MARKET DRILL -- {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}")
    print(f"  Market: US | Broker: TastyTrade (LIVE)")
    print(f"{'#'*60}")

    # 1. Connect
    md, mm, acct, wl = test_broker_connection()
    if md is None:
        print("\n  DRILL ABORTED: Cannot connect to broker.")
        return

    # 2. Init MA
    _section("INITIALIZING MarketAnalyzer")
    from income_desk import DataService, MarketAnalyzer
    ma = MarketAnalyzer(
        data_service=DataService(),
        market="US",
        market_data=md,
        market_metrics=mm,
        account_provider=acct,
        watchlist_provider=wl,
    )
    _record("ma_init", "PASS", "MarketAnalyzer ready with broker")

    # 3. Positions -- extract underlying tickers
    result = test_positions(acct)
    if isinstance(result, tuple):
        positions, position_underlyings = result
    else:
        positions, position_underlyings = result, []

    # Build test ticker list: known underlyings + defaults (NO option symbols)
    test_tickers = list(dict.fromkeys(
        ["SPY", "QQQ", "GLD"] + [t for t in position_underlyings if len(t) <= 5]
    ))
    print(f"\n    Test tickers: {test_tickers}")

    # 4-9. Run tests
    test_balance(acct)
    test_quotes(ma, test_tickers)
    test_regime(ma, test_tickers[:5])
    test_number_confidence(ma)
    test_ranking(ma, test_tickers[:5])
    test_daily_plan(ma, test_tickers)
    test_risk(acct)

    # -- SUMMARY ---------------------------------------------------------------
    _section("DRILL SUMMARY")
    total = PASS + FAIL + WARN
    print(f"\n    PASS: {PASS}/{total}")
    print(f"    FAIL: {FAIL}/{total}")
    print(f"    WARN: {WARN}/{total}")

    if FAIL == 0 and WARN <= 3:
        confidence = "HIGH (80-90%)"
    elif FAIL == 0:
        confidence = "MEDIUM-HIGH (60-80%)"
    elif FAIL <= 2:
        confidence = "MEDIUM (40-60%)"
    else:
        confidence = "LOW (<40%)"

    print(f"\n    GO-LIVE CONFIDENCE: {confidence}")

    if FAIL > 0:
        print(f"\n    FAILURES (must fix before Friday):")
        for name, status, detail in RESULTS:
            if status == "FAIL":
                print(f"      XX {name}: {detail}")

    if WARN > 0:
        print(f"\n    WARNINGS (review before Friday):")
        for name, status, detail in RESULTS:
            if status == "WARN":
                print(f"      !! {name}: {detail}")

    print()


if __name__ == "__main__":
    main()
