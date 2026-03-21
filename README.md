# market_analyzer

**Systematic options trading intelligence for small accounts.**

Every trade suggestion is bespoke to your portfolio, your risk profile, your capital. This isn't a signal service — it's a personal trading intelligence system.

[![Tests](https://github.com/YOUR_USER/market-analyzer/actions/workflows/test.yml/badge.svg)](https://github.com/YOUR_USER/market-analyzer/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)

## What It Does

market_analyzer brings institutional-grade trading intelligence to $30-50K accounts:

- **Per-instrument regime detection** — SPY can be R2 (high-vol mean-reverting) while GLD is R1 (calm). Not one global "market is bullish."
- **10-check profitability gate** — answers "will this iron condor actually make money after fees on a $35K account?"
- **Position-aware Kelly sizing** — correlation-adjusted, margin-regime aware, drawdown circuit breaker
- **Crash sentinel** — GREEN/YELLOW/ORANGE/RED/BLUE signals with automatic sizing overrides
- **4-level decision audit** — grades every trade 0-100 across legs, trade, portfolio, and risk
- **Trust framework** — every output tells you how much to trust it and what you can do with it

No backtesting. Start with 1 contract, trade real, system learns from YOUR outcomes.

## Quick Start

```bash
pip install market-analyzer
analyzer-cli
```

```
> regime SPY QQQ IWM GLD TLT

Ticker  Regime  Confidence
SPY     R2      100%        High-vol mean-reverting
QQQ     R4      96%         Explosive — NO TRADE
IWM     R1      99%         Calm mean-reverting — ideal for income
GLD     R1      100%        Calm — ideal for income
TLT     R2      100%        High-vol mean-reverting

> rank IWM GLD

#  Ticker  Strategy        Score  Verdict
1  IWM     iron_condor     0.60   go
2  GLD     iron_condor     0.59   go

> validate IWM

DAILY VALIDATION — IWM — 10 checks
PASS  commission_drag     Credit covers fees
PASS  fill_quality        Spread survives natural fill
...
READY TO TRADE (8 passed, 2 warnings)

> audit IWM 35000

DECISION AUDIT — IWM IC — 85/100 B+ — APPROVED
  Legs: 90/100 A    Trade: 82/100 B    Portfolio: 88/100 B+    Risk: 92/100 A
```

## Connect Your Broker

```bash
analyzer-cli --setup    # Interactive wizard
```

| Broker | Market | Cost | Setup |
|--------|--------|------|-------|
| Alpaca | US | Free (delayed quotes) | 2-minute signup, no funding |
| TastyTrade | US | Account required | Full DXLink streaming |
| IBKR | US/Global | Account required | TWS or IB Gateway |
| Schwab | US | Account required | OAuth2 developer app |
| Dhan | India | Free API access | 20K requests/day |
| Zerodha | India | Account required | Kite Connect API |

Works without any broker (yfinance free data). Connect a broker for real-time quotes, Greeks, and HIGH trust analysis.

## Key Concepts

### The 4 Trading Questions

| Question | What MA does |
|----------|-------------|
| **What to buy?** | 11 option strategies assessed per ticker, regime-gated, ranked by composite score |
| **At what price?** | Strike proximity to S/R, skew-optimal selection, limit order pricing, pullback alerts |
| **How many?** | Kelly criterion + correlation adjustment + margin-regime cap + drawdown circuit breaker |
| **When to exit?** | Regime-contingent stops, trailing profit targets, theta decay curve, position stress monitoring |

### Trust Framework

Every output carries a trust score:

```
TRUST: 85% HIGH
  Data:    90% HIGH (broker_live)
  Context: 85% HIGH (full mode)
  Fit for: ALL purposes including live execution
```

No broker? Trust is LOW — fit for research and screening only. The system refuses to let you execute when trust is too low.

### Forward Testing, Not Backtesting

MA does not have a backtesting engine. This is deliberate. Start small, trade real, system learns:

```
1 contract → validation gates protect → record outcome →
calibrate_weights() learns → Kelly scales up → repeat
```

## Documentation

- [User Manual](USER_MANUAL.md) — complete guide organized by purpose
- [Trust Framework](docs/TRUST_FRAMEWORK.md) — how MA scores data reliability
- [Data Interfaces](docs/DATA_INTERFACES.md) — bring your own data
- [Crash Playbook](docs/CRASH_PLAYBOOK.md) — systematic crash response
- [API Reference](API.md) — full Python API

## 80+ CLI Commands

Trading: `validate`, `rank`, `screen`, `opportunity`, `entry_analysis`, `kelly`, `audit`, `sentinel`
Monitoring: `health`, `monitor`, `exit_intelligence`, `adjust`, `assignment_risk`
Research: `regime`, `technicals`, `vol`, `levels`, `research`, `stress`, `rate_risk`
Account: `balance`, `quotes`, `watchlist`, `csp`, `covered_call`, `margin`

Run `help` in the CLI for the full list.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

MIT — see [LICENSE](LICENSE).
