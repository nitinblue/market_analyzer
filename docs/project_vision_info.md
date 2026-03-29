# income_desk -- Project

> Why this exists and where it's going.

---

## Mission

Make options income trading systematic, accessible, and trustworthy.

Not a signal service. Not a backtest platform. A personal trading desk brain -- the analytical engine that detects market regimes, ranks opportunities, validates trades, sizes positions, and monitors risk. Every output is either real data or explicitly marked unavailable. No fake numbers, no theoretical pricing, no guessing.

---

## Philosophy

- **Income-first.** Default to theta harvesting. Directional only when regime permits.
- **Small accounts.** Built for 50K-250K portfolios where margin efficiency matters and every trade must fit.
- **Per-instrument regime.** Gold can trend while tech chops. No global "market regime" -- each ticker gets its own HMM state (R1-R4).
- **No decision without a regime label.** This is the core invariant. The regime drives strategy selection, position sizing, and risk management.
- **Same-ticker hedging only.** SPY position hedged with SPY puts. No beta-weighted index hedging.
- **All decisions are explainable.** Every regime label traces to features and model state. Debug mode exposes the full calculation path.

---

## Audience

- **Individual options traders** (50K-250K accounts) who want systematic discipline without building their own infrastructure.
- **Trading platforms** (eTrading) that embed income_desk as their analytical engine -- stateless library, no auth, no UI, just computation.
- **AI-native traders** who describe strategies in English and let Claude generate executable workflows.

---

## The Big Vision: MD as Universal Trading Language

Documentation IS the code. Like GitHub Actions YAML did for CI/CD, `.workflow.md` does for options trading.

**Three distribution layers, each built on the one below:**

1. **Python library** (`pip install income-desk`) -- for developers who want full control. 15 workflow APIs, 67+ CLI commands, Pydantic models throughout.

2. **MD-based platform** -- for traders who don't write Python. Define your strategy in `.workflow.md`, your universe in `.universe.md`, your risk limits in `.risk.md`. The parser reads it, the runner executes it. Edit thresholds in a text file, not code.

3. **Claude Code skill** -- for anyone. Describe what you want in English. Claude generates the `.workflow.md`, connects your broker, runs the analysis, explains the results. No installation, no configuration, just conversation.

Anyone can describe a strategy in English. Claude generates `.workflow.md`. The engine executes it. The trader reviews results. Strategy becomes versionable, diffable, auditable, shareable.

---

## What Makes This Different

- **Not a signal service.** income_desk doesn't tell you what to trade. It gives you the analytical infrastructure to make your own decisions systematically.
- **Not a backtest platform.** Forward-testing by design. Historical replay exists for validation, not strategy discovery.
- **Real data or nothing.** No Black-Scholes pricing. No theoretical Greeks. Broker quotes or `None`. The trust score on every output tells you exactly what data is real.
- **Regime-first.** Every other platform screens by IV rank or delta. income_desk starts with "what state is this market in?" and lets that drive everything downstream.

---

## Markets

| Market | Brokers | Status |
|--------|---------|--------|
| US | TastyTrade (DXLink), Alpaca, IBKR, Schwab | Production-ready |
| India | Dhan, Zerodha (Kite REST) | Production-ready |

Cross-market: US-India correlation analysis, gap prediction, currency risk decomposition.

---

## Current State

- **v1.1.1** on PyPI (`pip install income-desk`)
- 15 workflow APIs covering the full trading lifecycle
- 18 stress test scenarios as `.scenario.md` files
- HMM 4-state regime detection, per-instrument
- 10-check profitability gate + 3-check adversarial suite
- Kelly criterion sizing, crash sentinel (5 phases), decision audit (4 levels)
- trader_md runner with 7 MD format types
- 2940+ tests (unit + functional + integration), all green
- 67+ CLI commands via interactive REPL
- 6 broker integrations, 2 markets (US + India)
- Hedging domain (10 modules), macro research (8 indicators), equity research (5 strategies)
