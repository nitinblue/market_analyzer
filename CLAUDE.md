# market_analyzer

**A library that helps make money trading options.** Not a theoretical exercise — a production tool for real capital deployment.

Serves as the canonical data + analysis layer for the trading ecosystem (market_analyzer, cotrader/eTrading, decision agent). Detects per-instrument regime state (R1–R4) using HMMs, generates ranked trade recommendations, and provides every analytical building block needed to make informed options trading decisions.

---

## Core Principle: Reliability Over Cleverness

This library handles real money. Every output must be trustworthy or explicitly marked as unavailable. The user's edge depends on trusting what MA tells them.

### Data Integrity Rules

- **NO fake data. NO placeholder values. NO theoretical pricing.** If you don't have real data, return `None`. Never invent numbers. A missing value is infinitely better than a wrong one.
- **NO Black-Scholes pricing — EVER.** All option prices (bid/ask/mid, Greeks, IV) come from the broker via DXLink streamer. If no broker is connected, the value is `None`. yfinance provides historical OHLCV and chain structure (strikes/expirations) only.
- **Every value must trace to its source.** Broker quote? yfinance historical? Calculated from OHLCV? The user must always know. CLI output MUST show data source for any options-related data.
- **Calculated values need commentary.** When MA computes something (regime label, trend strength, POP estimate), the calculation path should be traceable — what inputs, what formula, what assumptions.
- **Cache before fetch, but never serve stale data silently.** Cache is an optimization, not a data source. If cache is stale and fetch fails, say so — don't silently serve yesterday's data as if it's current.

### Trading Philosophy (Owner: Nitin)

- **Income-first.** Default to theta harvesting. Directional only when regime permits.
- **Small accounts (50K taxable, 200K IRA).** Margin efficiency matters. Every trade must fit.
- **Per-instrument regime detection.** Gold can trend while tech chops. No global "market regime."
- **No decision without a regime label.** This is the core invariant.
- **Same-ticker hedging only.** No beta-weighted index hedging.
- **All decisions are explainable.** Every regime label traces to features and model state.

### Regime States (4-State Model)

| Regime | Name | Primary Strategy | Avoid |
|--------|------|------------------|-------|
| R1 | Low-Vol Mean Reverting | Iron condors, strangles (theta) | Directional |
| R2 | High-Vol Mean Reverting | Wider wings, defined risk (selective theta) | Directional |
| R3 | Low-Vol Trending | Directional spreads | Heavy theta |
| R4 | High-Vol Trending | Risk-defined only, long vega | Theta |

---

## Vision: Debug Mode & Continuous Learning

MA should evolve from "compute and return" to "compute, explain, and learn."

### Calculation Commentary (Debug Mode)

Every analytical step should be able to produce a commentary trace — not just for debugging, but for methodology review. Over time, this lets the user (and ML) evaluate whether the methodology is working.

Example of what debug mode should expose:
```
REGIME DETECTION: SPY as of 2026-03-14
  Features computed from 60 days OHLCV (2026-01-02 to 2026-03-14)
  ├─ log_return_1d: -0.0023 (z-score: -0.41)
  ├─ realized_vol_20d: 0.0142 (z-score: +1.23) → elevated
  ├─ atr_norm: 0.0089 (z-score: +0.87)
  ├─ trend_strength: -0.31 (z-score: -0.92) → weak downtrend
  └─ volume_anomaly: 1.34 (z-score: +0.55)
  HMM inference: state probabilities [R1: 0.12, R2: 0.61, R3: 0.08, R4: 0.19]
  Result: R2 (confidence: 61%) — High-Vol Mean Reverting
  Rationale: Elevated vol (z=+1.23) with weak trend (z=-0.92) → mean-reverting with wide swings
```

This applies to ALL services: regime detection, technical analysis, opportunity assessment, ranking scores, entry confirmation, strategy selection. Every number should have a "why."

### Gap Identification (Self-Awareness)

MA should actively identify where its analysis is weak or incomplete. Examples:
- "POP estimate uses regime-adjusted ATR — no skew data available (broker not connected)"
- "Breakout score based on price only — volume confirmation unavailable for this ticker"
- "Calendar spread assessment lacks term structure IV data — using flat vol assumption"
- "Ranking score for AAPL missing: earnings in 3 days but no earnings vol data"

These gaps should be structured and queryable, not just log messages. They represent the roadmap for what to improve next.

### Performance Tracking & ML (Future)

The end goal: MA tracks the accuracy of its own predictions and learns from outcomes.

- **Regime accuracy:** Did R2 actually mean-revert? Did R3 actually trend?
- **Trade recommendation quality:** Did ranked trades perform as scored?
- **POP calibration:** Are 70% POP trades actually winning 70% of the time?
- **Entry timing:** Did confirmed entries outperform unconfirmed ones?

This data feeds back into model improvement — retrain HMM weights, adjust scoring matrices, recalibrate thresholds. MA becomes more profitable over time, not just more featureful.

---

## Standing Instructions for Claude

- **Read this file before any work.**
- **Never introduce module-level mutable state.** All caches, connections, config must be injectable via constructor.
- **Keep it a library.** Imported by cotrader — no server, no UI (CLI is for dev/exploration only).
- **Type everything.** Pydantic models for public interfaces. Type hints on all functions.
- **Every new capability gets a CLI command** in `cli/interactive.py`. Non-negotiable.
- **Data and regime modules are independently usable.** `data/` works without `hmm/`. `hmm/` works with caller-provided DataFrames. No circular dependencies.
- **Provider failures are not silent.** Raise typed exceptions. Callers must distinguish "no data exists" from "fetch failed."
- **No API keys in code.** Credentials from env vars or config files only.
- **Prefer simplicity.** Minimal dependencies, no over-engineering. The goal is making money, not beautiful abstractions.
- **DXLink is the only path for live data.** `from tastytrade.streamer import DXLinkStreamer`, `from tastytrade.dxfeed import Greeks as DXGreeks, Quote as DXQuote`.
- **Additive changes preferred** over moving existing files.
- **Update SYSTEMATIC_GAPS.md after any gap-related work.** Mark status, add implementation details, update test counts. This is the single source of truth for what's done vs open.

---

## Quick Reference

### Setup & Tests

```bash
# Venv: Python 3.12 (hmmlearn has no 3.14 wheels)
py -3.12 -m venv .venv_312
.venv_312/Scripts/pip install -e ".[dev]"

# Run tests
.venv_312/Scripts/python -m pytest tests/ -v
.venv_312/Scripts/python -m pytest -m "not integration" -v  # skip network tests
```

### CLI Entry Points

```bash
analyzer-cli                    # Interactive REPL (primary interface)
analyzer-cli --broker --paper   # With broker connection
analyzer-explore                # Regime exploration
analyzer-plot                   # Regime charts
```

### Key Python Usage

```python
from market_analyzer import MarketAnalyzer, DataService

ma = MarketAnalyzer(data_service=DataService())

# Regime detection
r = ma.regime.detect('SPY')

# Daily trading plan
plan = ma.plan.generate(skip_intraday=True)

# Rank trades
result = ma.ranking.rank(['SPY', 'GLD', 'QQQ', 'TLT'])

# With broker (real quotes)
from market_analyzer.broker.tastytrade import connect_tastytrade
md, mm, acct, wl = connect_tastytrade(is_paper=True)
ma = MarketAnalyzer(data_service=DataService(), market_data=md, market_metrics=mm)
```

### Integration with eTrading (SaaS)

market_analyzer is a **stateless library**. eTrading owns auth, tenant isolation, caching, credentials. Two broker modes:
- **Standalone:** `connect_tastytrade()` — library manages credentials
- **Embedded:** `connect_from_sessions(sdk_session, data_session)` — caller passes pre-authenticated sessions

---

## Systematic Trading Readiness

MA's end state: enable a fully systematic trading system where **no human decisions are needed during a trading day**. eTrading executes; MA decides.

**Current state: ALL 9 systematic gaps DONE & WIRED.** See [`SYSTEMATIC_GAPS.md`](SYSTEMATIC_GAPS.md) for full status.

### What's Complete
- Deterministic adjustment decisions (no menus — single action per situation)
- Execution quality validation (spread, OI, volume checks)
- Entry time windows on every TradeSpec (09:45-14:00 for 0DTE, 10:00-15:00 for income, etc.)
- Time-of-day urgency escalation (0DTE force-close after 15:00, tested escalation after 15:30)
- Overnight risk assessment (auto-checks in health check after 15:00)
- Auto-select screening (min_score filtering, top_n limiting)
- Performance feedback loop (TradeOutcome → calibrate_weights() — pure functions)
- Debug/commentary mode on 4 services + threading through ranking to assessors
- Data gap self-identification in 8 assessors (vol_surface, broker, ORB, fundamentals, earnings)

### Library Boundary
- **eTrading passes in** → current quotes, trade outcomes, account state
- **MA computes and returns** → rankings, exit signals, adjustments, calibrated weights
- **MA never stores** → positions, fills, P&L history, session state
- Risk checks (E01-E10) belong to eTrading

### What's Next (Library Quality)
- **Richer setup signals** — breakout/momentum/mean_reversion assessors use basic indicators; need multi-factor scoring
- **Richer option play logic** — leap/earnings assessors are thin; need deeper fundamental integration
- **ML regime validation** — track regime predictions against actual price behavior; auto-retrain HMM
- **POP calibration** — compare estimated POP against actual win rates from TradeOutcome data
