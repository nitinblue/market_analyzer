# income-desk — Launch Post Drafts

> Ready to copy-paste. Edit the personal touches, then post.

---

## Draft 1: r/thetagang

**Title:** I built an open-source income desk that says NO to 90% of trades — here's why that's the point

**Body:**

I've been selling premium on a $35K account for 2 years. The #1 lesson: the trades you DON'T take matter more than the ones you do.

So I built a system that enforces this. It's called **income-desk** — an open-source Python library that acts as your personal trading desk brain. It's free, MIT licensed, and works with TastyTrade, Alpaca (free tier!), IBKR, Schwab, Dhan, and Zerodha.

**What happened when I ran it on March 20th (real data):**

- SPY: R2 (high-vol mean-reverting) — IC available but marginal
- QQQ: R4 (explosive bearish) — **eliminated instantly**
- IWM: R1 (calm) — best candidate
- GLD: R1 (calm) — good candidate

The system ranked GLD and IWM iron condors as GO. Entry score was 87% (deeply oversold, near support). Everything looked great.

Then the validation gate ran 10 checks: commission drag, fill quality, margin efficiency, POP, expected value, entry quality, exit discipline, strike proximity, earnings blackout, IV rank quality.

**Result: BLOCKED.** POP was 57% (below 65% threshold), EV was negative at the estimated credit. Kelly said 0 contracts.

The most valuable thing the system did that day was **say no.**

I've also built:
- **Crash sentinel** — GREEN/YELLOW/ORANGE/RED/BLUE market health signal. Currently showing ORANGE (QQQ R4 + SPY R2 = pre-crash warning)
- **4-level decision audit** — grades every trade 0-100 at leg, trade, portfolio, and risk level
- **Position-aware Kelly sizing** — correlation-adjusted, margin-regime aware, drawdown circuit breaker
- **Trust framework** — every output tells you how much to trust it (broker data = HIGH, no broker = LOW, estimated = UNRELIABLE)
- **Demo portfolio** — $100K simulated trading, no broker needed

```
pip install income-desk
income-desk --demo
```

Try it this weekend. The `--sim calm` flag works offline with simulated data. Run `regime SPY QQQ IWM GLD TLT` and see what the system says about YOUR watchlist.

GitHub: https://github.com/nitinblue/income-desk

Happy to answer questions. Built this because I couldn't find anything that did regime-gated income trading for small accounts — everything out there is either backtesting frameworks or broker SDKs. This is the decision layer in between.

---

## Draft 2: r/options

**Title:** Free tool: Does your iron condor actually make money after fees? 10-check profitability gate for small accounts

**Body:**

Quick question: On a $35K account, if you sell a 5-wide SPY IC for $0.80 credit, are you actually making money?

The answer depends on 10 things most traders never check:

| Check | What it catches |
|-------|----------------|
| Commission drag | $0.65 × 4 legs × 2 (round trip) = $5.20. That's 6.5% of your $80 credit. |
| Fill quality | Bid/ask spread 3%? You're not getting mid. Real credit is $0.70. |
| Margin efficiency | $500 tied up for $70 credit = 14% annualized. Is that worth the risk? |
| POP | 65%+ or you're flipping a weighted coin |
| Expected value | POP × profit - (1-POP) × loss. Must be positive. |
| Strike proximity | Is your short put backed by real support? Or floating in thin air? |
| Earnings blackout | 30 DTE IC with earnings in 15 days = you're straddling a gap event |

I got tired of doing this math manually so I built **income-desk** — a free, open-source tool that runs all 10 checks automatically.

```
pip install income-desk
income-desk --broker       # Connect TastyTrade, Alpaca (free!), or others
> validate SPY
```

Output:
```
DAILY VALIDATION — SPY — 10 checks
PASS  commission_drag     Credit $1.80 covers fees (4.3% drag)
PASS  fill_quality        Spread 1.2% — survives natural fill
WARN  margin_efficiency   ROC 11% — marginal (target ≥15%)
PASS  pop_gate            POP 71% ≥ 65%
PASS  ev_positive         EV +$52/contract
...
RESULT: READY TO TRADE (8 passed, 2 warnings)
```

Also includes Kelly position sizing (how MANY contracts for YOUR account), crash sentinel (is today safe to trade?), and a 4-level decision audit that grades each trade 0-100.

No backtesting. No theoretical models. Just: "given real market data and YOUR account, does this specific trade make mathematical sense?"

GitHub: https://github.com/nitinblue/income-desk

MIT licensed. Works with 6 brokers. 2300+ tests. Built by a retail theta gang trader for retail theta gang traders.

---

## Draft 3: r/algotrading

**Title:** Open-source: Per-instrument HMM regime detection + Kelly sizing + 6 broker integrations for options income trading (Python)

**Body:**

**income-desk** is a Python library for systematic options income trading on small accounts ($30-50K). It's the decision layer between your data and your broker — it decides what to trade, at what price, how many contracts, and when to exit.

**Architecture:**
- Pure functions in focused modules (no mutable state, no servers)
- Pydantic models for all public interfaces
- 2300+ tests, 80+ CLI commands
- Pluggable broker ABCs — 170 lines to add any broker

**Key technical features:**

1. **HMM regime detection (per-instrument)** — 4-state model (low-vol MR, high-vol MR, low-vol trending, high-vol trending). SPY can be R2 while GLD is R1. Strategy selection is regime-gated — no iron condors in R4.

2. **10-check validation gate** — commission drag, fill quality, margin efficiency, POP (ATR-regime based, not Black-Scholes), expected value, entry quality, exit discipline, strike proximity to S/R, earnings blackout, IV rank quality.

3. **Position-aware Kelly sizing** — `compute_position_size()` chains: Kelly fraction → correlation penalty (SPY+QQQ = ~1 position) → regime-adjusted margin → drawdown circuit breaker → final contracts.

4. **Trust framework** — every output carries a 2-dimensional trust score (data quality + context quality) with fitness-for-purpose classification. No broker connected? Trust = LOW, fit for research only. Full broker + full context? Trust = HIGH, fit for live execution.

5. **6 brokers:** TastyTrade (DXLink streaming), Alpaca (free tier!), IBKR (TWS API), Schwab (REST), Zerodha (India), Dhan (India). All map to the same `OptionQuote` model — zero core changes per broker.

6. **Simulation layer** — `income-desk --sim calm` for offline development. Capture live snapshots during market hours, replay on weekends.

**No backtesting.** This is deliberate. The system learns from real outcomes via `calibrate_weights()`, not from historical curve-fitting.

```python
pip install income-desk

from market_analyzer import MarketAnalyzer, DataService
ma = MarketAnalyzer(data_service=DataService())
regime = ma.regime.detect("SPY")  # R1/R2/R3/R4
```

GitHub: https://github.com/nitinblue/income-desk
PyPI: https://pypi.org/project/income-desk/

Looking for contributors — especially broker integrations (Webull, E*Trade) and India market features. Each broker is ~170 lines of field mapping.

---

## Draft 4: Hacker News — Show HN

**Title:** Show HN: income-desk – Systematic options trading intelligence that says "no" to 90% of trades

**URL:** https://github.com/nitinblue/income-desk

**Comment (post immediately after submitting):**

income-desk is a Python library for income-focused options trading on small accounts ($30-50K). It's the decision layer — not a backtesting framework, not a broker SDK, not a signal service.

The core insight: for small accounts, the trades you don't take matter more than the ones you do. A single bad iron condor can wipe out a month of income. So every trade goes through a 10-check profitability gate, regime detection (is this the right market condition?), position-aware Kelly sizing (how much given what you already own?), and a 4-level decision audit (legs, trade, portfolio, risk — scored 0-100).

The trust framework is unusual — every output tells you how much to trust it. No broker connected? The system says "Trust: LOW — fit for research, NOT for trading." Full broker with real quotes? "Trust: HIGH — fit for live execution." It refuses to let you execute when it doesn't trust its own data.

No backtesting. The system learns from real trade outcomes and adjusts its weights over time. Start with 1 contract, prove the edge, scale up.

`pip install income-desk` — works immediately with free yfinance data. Connect Alpaca (free, no funding needed) for delayed quotes, or TastyTrade/IBKR/Schwab for live data.

2300+ tests, MIT licensed, Python 3.11+.

---

## Draft 5: Twitter/X Thread

**Tweet 1:**
I built a trading system that says NO to 90% of trades.

Here's why that's the most important feature. 🧵

**Tweet 2:**
March 20, 2026. Market is selling off. QQQ down 15% from highs.

My system scans 5 tickers. Result:
- QQQ: R4 (explosive) → ELIMINATED
- SPY: R2 (volatile) → available but marginal
- IWM: R1 (calm) → best candidate
- GLD: R1 (calm) → good candidate

**Tweet 3:**
GLD iron condor ranks #1. Entry score 87%.

But then the validation gate runs:
- POP 57% (below 65% threshold) → FAIL
- EV negative → FAIL
- Kelly says: 0 contracts

Verdict: DON'T TRADE.

**Tweet 4:**
The system's crash sentinel is showing ORANGE.

That means: close positions with DTE > 30, tighten all stops, no new entries.

On a $35K account, the most valuable thing a system can do on a day like this is protect your capital.

**Tweet 5:**
This is income-desk — open source, free, works with 6 brokers.

Every trade suggestion is bespoke to YOUR portfolio, YOUR risk profile, YOUR capital.

Two traders with different accounts get different recommendations from the same market.

**Tweet 6:**
No backtesting. Start with 1 contract. System learns from your real outcomes. Kelly scales up as the edge is proven.

pip install income-desk
income-desk --demo

GitHub: https://github.com/nitinblue/income-desk

#thetagang #options #python #algotrading

---

## Draft 6: Blog Post — "Why I Don't Backtest"

**Title:** Why I Don't Backtest — And Why My Trading System Doesn't Either

**Subtitle:** How income-desk learns from real trades instead of historical fantasies

The graveyard of blown-up accounts is full of traders who said "but it backtested well."

Here's what backtesting actually gives you:
- **Overfitting** — your strategy is optimized for 2020-2024 data. The market in 2026 doesn't care.
- **Perfect fills** — your backtest assumed mid-price fills. Reality: you get filled at the natural, 15% worse.
- **No commissions** — $0.65 × 4 legs × 2 round-trip = $5.20/trade. On a $0.80 IC credit, that's 6.5% gone before you start.
- **No psychology** — your backtest held through a -20% drawdown without flinching. You won't.

My system, income-desk, takes a different approach:

**1. Start with proven structures.** Iron condors in R1 regime, wider wings in R2, defined risk only in R4. These aren't "discovered" by backtesting — they're the building blocks of income trading used by every professional desk.

**2. Gate every entry with real math.** 10 checks: commission drag, fill quality, margin efficiency, POP, expected value, entry quality, exit discipline, strike proximity, earnings blackout, IV rank quality. If any check fails, the trade is blocked.

**3. Size with Kelly, not gut feel.** Position-aware Kelly criterion: adjusts for portfolio correlation (SPY + QQQ = effectively one position), regime-specific margin, and drawdown circuit breaker.

**4. Learn from real outcomes.** After 20-30 trades, `calibrate_weights()` adjusts the ranking model based on YOUR actual results. Did R2 iron condors underperform? The system reduces R2 alignment weight. Did high IV-rank trades outperform? It increases IV-rank weight.

**5. Scale gradually.** Start with 1 contract, quarter Kelly. As win rate proves out, Kelly automatically increases sizing. No human override needed.

The result: a system that gets better over time from REAL data, not from fitting to the past.

```
pip install income-desk
income-desk --demo
```

Try it this weekend with simulated data. Start with `regime SPY QQQ IWM GLD TLT` and see what the market is actually doing.

https://github.com/nitinblue/income-desk

---

## Draft 7: Blog Post — "The Trust Problem in Trading Tools"

**Title:** The Trust Problem in Trading Tools — Why "POP 72%" Doesn't Mean What You Think

Every trading tool gives you a number and expects you to trust it. POP 72%. IV Rank 43. EV +$52.

But how much should you actually trust those numbers?

Was the POP computed from real broker data or estimated from stale yfinance quotes? Was the IV rank from the broker's proprietary model or a rough calculation? Was the EV based on real bid/ask or theoretical mid-price?

You'll never know. Because the tool didn't tell you.

income-desk tells you.

Every output carries a **trust report** with three dimensions:

**Dimension 1: Data Quality** — Where did this number come from?
- Broker live (DXLink real-time): HIGH trust
- yfinance (free, delayed): MEDIUM trust
- Estimated (heuristic): LOW trust
- Missing: UNRELIABLE

**Dimension 2: Context Quality** — Did you give the system everything it needs?
- Full context (regime, IV rank, levels, portfolio): HIGH
- Partial context: MEDIUM
- Missing critical inputs: LOW

**Dimension 3: Fitness for Purpose** — What can you actually DO with this output?
- Trust ≥ 80%: Live execution
- Trust ≥ 50%: Paper trading, alerts
- Trust < 50%: Research only
- Trust < 20%: Education only

The system refuses to let you execute when trust is too low. That's not a limitation — that's capital preservation.

[Continue with examples and CTA...]
