# The Trust Framework — Why income_desk Never Lies to You

> Most trading tools give you a number and expect you to trust it. income_desk tells you **how much to trust the number** — and what you can safely do with it.

---

## The Problem With Every Other Trading Tool

You run an analysis. It says "POP 72%, sell this iron condor." You sell it. It loses money.

Was the POP estimate wrong? Was it based on stale data? Was it using a Black-Scholes approximation while the real market had moved? Was the bid/ask spread so wide that your fill was 30% worse than the model assumed?

**You'll never know.** Because the tool didn't tell you how confident it was, where the data came from, what was estimated vs real, or what the output was actually suitable for.

income_desk does.

---

## Three Dimensions of Trust

Every output from income_desk carries a `TrustReport` with three dimensions:

### Dimension 1: Data Quality — Is the data accurate and fresh?

| Source | Trust Score | What it means |
|--------|-------------|---------------|
| Broker live (DXLink real-time) | +0.30 | Real bid/ask, real Greeks, real IV — this is what the market is actually doing |
| yfinance OHLCV (free) | +0.30 (base) | Historical daily bars — reliable for regime detection and technicals |
| Estimated (heuristic) | +0.03 | We guessed. The system tells you it guessed. |
| None | 0.00 | We don't have this data. The system tells you it's missing. |

**The key rule:** If we don't have real data, we return `None` — never a fake number. A missing value is infinitely better than a wrong one.

### Dimension 2: Context Quality — Did you give the system everything it needs?

This is what makes the framework unique. It's not just about data quality — it's about whether the **caller** provided full context.

```python
# This call has LOW context quality:
run_daily_checks(ticker="SPY", trade_spec=ts, entry_credit=1.50,
                 regime_id=1, atr_pct=0.86, current_price=580.0,
                 dte=35, rsi=52.0)
# Missing: iv_rank, levels, days_to_earnings, ticker_type
# Result: 4 checks will WARN with "insufficient data"

# This call has HIGH context quality:
run_daily_checks(ticker="SPY", trade_spec=ts, entry_credit=1.50,
                 regime_id=1, atr_pct=0.86, current_price=580.0,
                 dte=35, rsi=52.0,
                 iv_rank=42.0,                    # From broker
                 ticker_type="etf",               # From registry
                 days_to_earnings=None,            # ETF — no earnings
                 levels=levels_analysis,           # From ma.levels.analyze()
                 avg_bid_ask_spread_pct=1.2)       # From vol surface
# Result: All 10 checks run with full information
```

**Same function, same market, different trust — because one caller provided full context and the other didn't.**

### Dimension 3: Fitness for Purpose — What can you actually DO with this output?

Based on the combined trust score, every output tells you exactly what it's suitable for:

```
TRUST: 85% HIGH
  Data:    90% HIGH (broker_live)
  Context: 85% HIGH (full mode, all inputs provided)
  Fit for: ALL purposes including live execution

TRUST: 42% LOW
  Data:    60% MEDIUM (yfinance, no broker)
  Context: 42% LOW — MISSING: entry_credit, iv_rank, levels
  Fit for: screening, research, education
  NOT fit for: live_execution, position_monitoring, risk_assessment
```

| Trust Level | What You Can Do | What You CAN'T Do |
|-------------|-----------------|---------------------|
| **HIGH (80%+)** | Execute trades with real money | — |
| **MEDIUM (50-79%)** | Paper trade, set alerts, screen candidates | Deploy real capital |
| **LOW (20-49%)** | Research, explore regimes, learn the system | Make any trading decision |
| **UNRELIABLE (<20%)** | Read documentation | Anything involving money |

---

## How It Works in Practice

### Scenario 1: New User, No Broker

```python
from income_desk import MarketAnalyzer, DataService, compute_trust_report

ma = MarketAnalyzer(data_service=DataService())
regime = ma.regime.detect("SPY")

trust = compute_trust_report(
    has_broker=False,          # No broker connected
    has_iv_rank=False,         # Can't get without broker
    has_vol_surface=True,      # yfinance options chain
    has_levels=True,           # Computed from OHLCV
    regime_confidence=regime.confidence,
)

print(trust.overall_trust)      # 0.43
print(trust.overall_level)      # "low"
print(trust.fit_for_summary)    # "Fit for: screening, research. NOT fit for: live_execution"
```

**What this tells you:** "You can explore, screen tickers, understand regimes — but don't trade off this data alone. Connect your broker for real quotes."

### Scenario 2: Broker Connected, Full Context

```python
trust = compute_trust_report(
    has_broker=True,
    has_iv_rank=True,
    has_vol_surface=True,
    has_levels=True,
    has_fundamentals=True,
    entry_credit_source="broker",
    regime_confidence=0.95,
    has_entry_credit=True,
    has_days_to_earnings=True,
    has_ticker_type=True,
    has_correlation_data=True,
    has_portfolio_exposure=True,
)

print(trust.overall_trust)      # 0.92
print(trust.overall_level)      # "high"
print(trust.fit_for_summary)    # "Fit for ALL purposes including live execution"
```

**What this tells you:** "Every input is real, every context parameter is provided. You can trust this analysis for real money decisions."

### Scenario 3: Broker Connected but Incomplete Context

```python
trust = compute_trust_report(
    has_broker=True,            # Good — real quotes
    has_iv_rank=True,           # Good — from broker
    has_vol_surface=True,
    has_entry_credit=True,
    entry_credit_source="broker",
    regime_confidence=0.90,
    # MISSING: levels, portfolio_exposure, correlation_data
)

print(trust.overall_trust)      # 0.68
print(trust.overall_level)      # "medium"
print(trust.fit_for_summary)    # "Fit for: paper_trading, alerting. NOT fit for: live_execution"
```

**What this tells you:** "The data is real (broker connected), but you didn't pass your portfolio state and levels. The system can't check strike proximity or correlation-adjust your sizing. Good enough for paper trading, not for real money."

---

## What Makes This Different

### Every other tool: "Here's a number. Trust it."

```
POP: 72%
Credit: $1.50
Recommendation: SELL
```

No source attribution. No quality indicator. No context check. No fitness classification.

### income_desk: "Here's a number. Here's exactly how much to trust it, and what you can do with it."

```
POP: 72% (regime_historical, R1 calibrated, IV rank adjusted)
Credit: $1.50 (broker DXLink mid, SPY 4/24/26 IC)
Recommendation: SELL

TRUST: 87% HIGH
  Data:    90% HIGH (broker_live)
  Context: 87% HIGH (full mode)
  Degraded: none
  Fit for: ALL purposes including live execution

DECISION AUDIT: 85/100 B+ — APPROVED
  Legs: 90/100 A (strikes backed by SMA-200 + swing support)
  Trade: 82/100 B (POP 72%, EV +$52, 4.3% commission drag)
  Portfolio: 88/100 B+ (2/5 slots, 0.15 correlation, 12% risk deployed)
  Risk: 92/100 A (1 contract, 1.4% of NLV, Kelly aligned)
```

**The trader knows:**
- Where the data came from (broker live, not estimated)
- What's degraded (nothing — full context provided)
- What this analysis is fit for (real money)
- How each dimension of the trade was graded
- Whether to proceed or wait

---

## The Two Modes

### Full Mode (Default) — For Production Trading

Every calculation is portfolio-aware, position-aware, and risk-aware. If critical context is missing, the trust report flags it and `is_actionable` returns `False`.

**Used by:** eTrading (automated), CLI with `--broker` (manual trading)

### Standalone Mode — For Exploration

Single-trade analysis without portfolio context. Missing portfolio state doesn't degrade trust.

**Used by:** CLI exploration, research, learning

```python
# Full mode (default) — strictest
trust = compute_trust_report(mode="full", ...)
# Missing portfolio context → trust drops, NOT fit for execution

# Standalone mode — relaxed
trust = compute_trust_report(mode="standalone", ...)
# Missing portfolio context → expected, doesn't reduce trust
```

---

## For Developers: Adding Trust to Your Integration

```python
from income_desk import compute_trust_report, FitnessCategory

# After running any analysis, compute trust:
trust = compute_trust_report(
    has_broker=ma.quotes.has_broker,
    has_iv_rank=iv_rank is not None,
    has_vol_surface=vol is not None,
    has_levels=levels is not None,
    has_entry_credit=entry_credit > 0,
    entry_credit_source="broker" if ma.quotes.has_broker else "estimated",
    regime_confidence=regime.confidence,
    has_days_to_earnings=days_to_earnings is not None,
    has_portfolio_exposure=exposure is not None,
)

# Gate execution on fitness
if "live_execution" not in trust.fit_for:
    raise ValueError(f"Cannot execute: {trust.fit_for_summary}")

# Or check actionability
if not trust.is_actionable:
    log(f"Analysis not actionable: {trust.summary}")
    return
```

---

## The Philosophy

> "A trading system that doesn't know what it doesn't know is more dangerous than no system at all."

Most blown-up accounts don't fail because the strategy was wrong. They fail because the trader trusted data that shouldn't have been trusted — stale quotes, estimated fills, missing risk context. The trust framework makes this impossible. Every output tells you exactly how much to trust it, and the system refuses to let you execute when the trust is too low.

**That's not a limitation. That's capital preservation.**
