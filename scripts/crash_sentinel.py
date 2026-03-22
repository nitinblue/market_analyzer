"""Crash Sentinel — Run in loop, signals when crash playbook should activate.

Usage:
    python scripts/crash_sentinel.py              # Single check
    python scripts/crash_sentinel.py --loop 15    # Check every 15 minutes
    python scripts/crash_sentinel.py --loop 5     # Check every 5 minutes (active crash)

Signals:
    GREEN  — Normal operations. Income trading as usual.
    YELLOW — Elevated risk. Tighten stops, reduce new entries.
    ORANGE — Pre-crash. Close positions, raise cash.
    RED    — Crash active. 100% cash. Wait for R4→R2 transition.
    BLUE   — Post-crash opportunity. Deploy per crash playbook Phase 2.

Exit codes:
    0 = GREEN/YELLOW (safe)
    1 = ORANGE (action needed)
    2 = RED (crash active)
    3 = BLUE (opportunity)
"""
import sys
import io
import time
import warnings
import logging
import argparse
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)


def run_check():
    from income_desk.cli._broker import connect_broker
    from income_desk import MarketAnalyzer, DataService

    md, mm, acct, wl = connect_broker(is_paper=False)
    if md is None:
        print("[ERROR] Broker connection failed")
        return None

    ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm)
    bal = acct.get_balance()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- Collect signals ---
    tickers = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
    regimes = {}
    iv_ranks = {}
    r4_count = 0
    r2_count = 0
    r1_count = 0
    max_r4_prob = 0.0

    for t in tickers:
        try:
            r = ma.regime.detect(t)
            regimes[t] = r
            if r.regime.value == 4:
                r4_count += 1
            elif r.regime.value == 2:
                r2_count += 1
            elif r.regime.value == 1:
                r1_count += 1
            # Track R4 probability even on non-R4 tickers
            r4_prob = r.regime_probabilities.get(4, 0) if r.regime_probabilities else 0
            max_r4_prob = max(max_r4_prob, r4_prob)
        except Exception as e:
            regimes[t] = None

    # IV rank from broker
    for t in tickers:
        try:
            m = ma.quotes.get_metrics(t)
            if m and hasattr(m, "iv_rank") and m.iv_rank:
                iv_ranks[t] = m.iv_rank
            elif isinstance(m, dict) and m.get("ivRank"):
                iv_ranks[t] = m["ivRank"]
        except Exception:
            pass

    # Context
    try:
        ctx = ma.context.assess()
        trading_allowed = ctx.trading_allowed
        env = ctx.environment_label
        size_factor = ctx.position_size_factor
    except Exception:
        trading_allowed = True
        env = "unknown"
        size_factor = 1.0

    # SPY technicals for VIX proxy
    try:
        spy_tech = ma.technicals.snapshot("SPY")
        spy_rsi = spy_tech.rsi.value
        spy_atr_pct = spy_tech.atr_pct
        spy_price = spy_tech.current_price
        spy_bb = spy_tech.bollinger.percent_b if spy_tech.bollinger else 0.5
    except Exception:
        spy_rsi = 50
        spy_atr_pct = 1.0
        spy_price = 0
        spy_bb = 0.5

    avg_iv_rank = sum(iv_ranks.values()) / len(iv_ranks) if iv_ranks else 0

    # --- Determine signal level ---
    signal = "GREEN"
    reasons = []
    actions = []
    exit_code = 0

    # RED: Crash active
    if not trading_allowed:
        signal = "RED"
        reasons.append("Black swan alert — trading disabled")
        actions.append("100% CASH. Do not trade. Wait for all-clear.")
        exit_code = 2
    elif r4_count >= 3:
        signal = "RED"
        reasons.append(f"{r4_count}/5 tickers in R4 — broad-based crash")
        actions.append("100% CASH. Close all positions immediately.")
        actions.append("Set alerts at SPY -10%/-15%/-20% from here.")
        exit_code = 2
    elif r4_count >= 2 and spy_atr_pct > 2.0:
        signal = "RED"
        reasons.append(f"{r4_count} R4 tickers + SPY ATR {spy_atr_pct:.1f}% (elevated)")
        actions.append("Close all positions. Raise to 100% cash.")
        exit_code = 2

    # ORANGE: Pre-crash warning
    elif r4_count >= 1 and r2_count >= 2:
        signal = "ORANGE"
        reasons.append(f"R4 on {[t for t,r in regimes.items() if r and r.regime.value==4]}, R2 spreading")
        actions.append("Close any position with DTE > 30.")
        actions.append("Tighten ALL stops to 1.5x credit.")
        actions.append("No new entries. Prepare for Phase 1.")
        exit_code = 1
    elif max_r4_prob > 0.30 and r4_count >= 1:
        signal = "ORANGE"
        reasons.append(f"R4 probability rising ({max_r4_prob:.0%} max) with {r4_count} confirmed R4")
        actions.append("Reduce position count. Tighten stops.")
        exit_code = 1
    elif r4_count >= 1 and spy_rsi < 30:
        signal = "ORANGE"
        reasons.append(f"R4 active + SPY RSI {spy_rsi:.0f} (deeply oversold)")
        actions.append("Close DTE > 21 positions. No new entries.")
        exit_code = 1

    # BLUE: Post-crash opportunity
    elif r4_count == 0 and r2_count >= 2 and avg_iv_rank > 60:
        signal = "BLUE"
        reasons.append(f"No R4, {r2_count} R2 tickers, avg IV rank {avg_iv_rank:.0f}% — premiums rich")
        actions.append("CRASH PLAYBOOK PHASE 2: Deploy per stabilization rules.")
        actions.append("Quarter Kelly, 3 max positions, 21 DTE, 3.0x stops.")
        actions.append("Uncorrelated tickers first (GLD, TLT before SPY).")
        exit_code = 3
    elif r2_count >= 1 and r1_count >= 2 and avg_iv_rank > 45:
        signal = "BLUE"
        reasons.append(f"Recovery: {r1_count} R1 + {r2_count} R2, IV rank {avg_iv_rank:.0f}% still elevated")
        actions.append("CRASH PLAYBOOK PHASE 3: Scale up deployment.")
        actions.append("Half Kelly, 5 positions, 25% risk budget.")
        actions.append("DTE optimizer for front-month theta advantage.")
        exit_code = 3

    # YELLOW: Elevated risk
    elif r4_count == 1:
        signal = "YELLOW"
        r4_ticker = [t for t, r in regimes.items() if r and r.regime.value == 4][0]
        reasons.append(f"{r4_ticker} in R4 — contagion risk")
        actions.append(f"Avoid {r4_ticker}. Reduce correlated positions.")
        actions.append("Tighten stops on all positions to 2.0x max.")
    elif max_r4_prob > 0.20:
        signal = "YELLOW"
        reasons.append(f"R4 probability elevated ({max_r4_prob:.0%}) — regime transition possible")
        actions.append("No new positions on affected tickers.")
    elif spy_atr_pct > 2.0 and env == "cautious":
        signal = "YELLOW"
        reasons.append(f"SPY ATR {spy_atr_pct:.1f}% elevated, market cautious")
        actions.append("Trade at 75% size. Shorter DTE (21 not 35).")

    # GREEN: Normal
    else:
        reasons.append("All systems normal")
        actions.append("Standard income trading operations.")

    # --- Print report ---
    colors = {
        "GREEN": "\033[92m", "YELLOW": "\033[93m", "ORANGE": "\033[33m",
        "RED": "\033[91m", "BLUE": "\033[94m", "RESET": "\033[0m",
    }
    c = colors.get(signal, "")
    r = colors["RESET"]

    print(f"\n{'='*60}")
    print(f"CRASH SENTINEL | {now}")
    print(f"{'='*60}")
    print(f"Signal: {c}{signal}{r}")
    print(f"Account: ${bal.net_liquidating_value:,.0f} NLV")
    print()

    # Regime table
    print(f"{'Ticker':<8}{'Regime':<8}{'Conf':<8}{'R4 Prob':<10}{'IV Rank':<10}")
    print("-" * 46)
    for t in tickers:
        rg = regimes.get(t)
        if rg:
            r4p = rg.regime_probabilities.get(4, 0) if rg.regime_probabilities else 0
            ivr = f"{iv_ranks.get(t, 0):.0f}%" if t in iv_ranks else "N/A"
            flag = " <<<" if rg.regime.value == 4 else ""
            print(f"{t:<8}R{rg.regime.value:<7}{rg.confidence:.0%}{'':>4}{r4p:>6.0%}   {ivr:>6}{flag}")

    print(f"\nEnvironment: {env} | Size factor: {size_factor}")
    print(f"SPY: ${spy_price:.2f} | RSI {spy_rsi:.1f} | ATR {spy_atr_pct:.1f}% | %B {spy_bb:.2f}")
    print(f"R4 count: {r4_count} | R2 count: {r2_count} | R1 count: {r1_count}")
    print(f"Avg IV Rank: {avg_iv_rank:.0f}%")

    print(f"\n{c}SIGNAL: {signal}{r}")
    for reason in reasons:
        print(f"  Reason: {reason}")
    for action in actions:
        print(f"  >> {action}")

    print(f"{'='*60}\n")

    return exit_code


def main():
    parser = argparse.ArgumentParser(description="Crash Sentinel — market crash monitoring")
    parser.add_argument("--loop", type=int, default=0,
                        help="Run in loop every N minutes (0 = single check)")
    args = parser.parse_args()

    if args.loop <= 0:
        code = run_check()
        sys.exit(code or 0)
    else:
        print(f"Crash Sentinel running every {args.loop} minutes. Ctrl+C to stop.\n")
        while True:
            try:
                code = run_check()
                if code == 2:
                    print("*** RED ALERT — Check every 5 minutes recommended ***")
                elif code == 3:
                    print("*** BLUE — Opportunity window. Run dry_run_portfolio.py ***")
                time.sleep(args.loop * 60)
            except KeyboardInterrupt:
                print("\nSentinel stopped.")
                break


if __name__ == "__main__":
    main()
