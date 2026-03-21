# Open Source Readiness: market_analyzer

> Written: 2026-03-21 | Version: 0.3.0

---

## 0. Product Vision

**market_analyzer brings institutional-grade systematic trading to small accounts.**

There are tools for institutions (Bloomberg, expensive). There are tools for retail (TOS, manual). The space in between — systematic income trading for $30-50K accounts with real risk management — is empty. MA fills it.

### The Pitch

"Every trade suggestion is bespoke to YOUR portfolio, YOUR risk profile, YOUR capital. The system tells you WHICH structure, WHAT strikes, HOW MANY contracts, and WHEN to exit — tailored to what you already own and what you can afford to lose. Start with 1 contract. Track what happens. The system learns from YOUR real outcomes and gets better for YOU."

Two traders with different accounts, different open positions, and different risk tolerances get **different recommendations** from the same market data. This isn't a signal service — it's a personal trading intelligence system.

### Core Differentiators (What Nobody Else Has)

1. **Per-instrument regime detection** — SPY can be R2 while GLD is R1. Not one global "market is bullish/bearish."
2. **10-check profitability gate** — answers "will this IC actually make money after fees on a $35K account?"
3. **Position-aware Kelly sizing** — correlation-adjusted, margin-regime aware, drawdown circuit breaker.
4. **Crash sentinel** — GREEN/YELLOW/ORANGE/RED/BLUE with automatic sizing overrides per phase.
5. **Decision audit** — 4-level report card (leg/trade/portfolio/risk) grades every trade 0-100.
6. **Forward testing, not backtesting** — no historical optimization. Start small, trade real, system learns from YOUR outcomes.

### Philosophy: Learn by Trading

MA does NOT have a backtesting engine. This is deliberate. Backtesting overfits to the past. MA's approach:

```
Start small (1 contract) → Validation gates protect capital → Record outcomes →
calibrate_weights() learns from real data → Kelly scales up as edge is proven → Repeat
```

The system gets better over time from REAL outcomes, not from curve-fitting history.

---

## 1. Current State Assessment

### What Exists
- **Public GitHub repository** — code is publicly visible
- **1,820 tests** — high test coverage across all subsystems
- **67 CLI commands** — comprehensive interactive interface
- **Internal documentation** — USER_MANUAL.md, ETRADING_INTEGRATION.md, SYSTEMATIC_GAPS.md, API docs
- **pyproject.toml** — proper Python packaging with optional dependencies

### What Was Missing (Now Fixed)
| Item | Status |
|------|--------|
| LICENSE file | **Fixed** — MIT License added |
| `__version__` in `__init__.py` | **Fixed** — 0.3.0 |
| `py.typed` marker | **Fixed** — PEP 561 compliance |
| `.env.example` | **Fixed** — credential template |
| Hardcoded eTrading path in `_broker.py` | **Fixed** — uses `~/.market_analyzer/.env` |
| CHANGELOG.md | **Fixed** — version history added |

### Still Needed for Full OSS Readiness
| Item | Priority | Effort |
|------|----------|--------|
| README.md (root) | P0 | 2h |
| GitHub Actions CI | P0 | 1h |
| CONTRIBUTING.md | P1 | 1h |
| PyPI publication | P1 | 1h |
| Code coverage badge | P2 | 30m |
| SECURITY.md | P2 | 30m |

---

## 2. What Makes a Project "Open Source" (Legally)

**A LICENSE file is the ONLY legal requirement.** Without one, all code is "all rights reserved" by default — no one can legally use, modify, or distribute it, even if it's publicly visible on GitHub.

### License Options

| License | Best For | Key Property |
|---------|----------|--------------|
| **MIT** ✓ | Tools, libraries, broad adoption | Most permissive — use for anything |
| Apache 2.0 | Larger projects, corporate use | Adds patent grant — protects contributors |
| GPL v3 | Force-open derivatives | Any derivative must also be GPL — limits corporate adoption |

**Recommendation: MIT** (already applied). It maximizes adoption while maintaining attribution. Users can build commercial products on top of market_analyzer without restriction, which drives ecosystem growth.

---

## 3. Credibility Signals (What Makes People Trust Your Project)

Trust is earned in tiers. Each tier roughly doubles your project's perceived credibility.

### Tier 1 — Must Have (Without These, People Move On)
1. **LICENSE file** — done
2. **README with**: what it does, install command, quick start, feature list, link to docs
3. **Tests passing badge** — requires CI first
4. **Version number** — done (`__version__ = "0.3.0"`)

### Tier 2 — Expected (Signals Active Maintenance)
1. **CHANGELOG.md** — done
2. **CONTRIBUTING.md** — setup instructions, how to run tests, how to submit PRs
3. **GitHub Actions CI** — tests run on every push/PR
4. **PyPI publication** — `pip install market-analyzer` works
5. **Code coverage badge** — shows test depth at a glance

### Tier 3 — Differentiators (Signals a Serious Project)
1. **Documentation site** — ReadTheDocs or GitHub Pages from existing docs/
2. **Architecture diagram** — the 5-layer pipeline (scan → rank → gate → size → execute)
3. **Example notebooks** — Jupyter demos for regime detection, ranking, trade planning
4. **Issue templates** — bug report, feature request
5. **Code of Conduct** — signals inclusive community
6. **Sponsors/Funding** — FUNDING.yml if accepting sponsors
7. **Security policy** — SECURITY.md with vulnerability reporting instructions
8. **Discord/Discussions** — community Q&A

---

## 4. The "Broker Token" Problem for Open Source Users

### Problem
market_analyzer uses TastyTrade for live quotes and Greeks. External users won't have your credentials.

### Solution: Pluggable Broker Architecture (Already Built)

`broker/base.py` defines five ABCs:
- `BrokerSession` — authentication
- `MarketDataProvider` — live quotes, Greeks, candles
- `MarketMetricsProvider` — IV rank, IV percentile, beta
- `AccountProvider` — balance, buying power
- `WatchlistProvider` — ticker lists from broker

TastyTrade is one implementation. Anyone can implement these ABCs for their broker (IBKR, Schwab, Webull, etc.).

### User Flow (After OSS Release)

```bash
# Basic usage — no broker needed (yfinance provides historical data)
pip install market-analyzer
analyzer-cli

# With TastyTrade broker
pip install market-analyzer[tastytrade]

# Credentials — option 1: environment variables
export TASTYTRADE_CLIENT_SECRET_LIVE=your_secret
export TASTYTRADE_REFRESH_TOKEN_LIVE=your_token

# Credentials — option 2: config file
mkdir ~/.market_analyzer
cp .env.example ~/.market_analyzer/.env
# Edit ~/.market_analyzer/.env with your credentials

# Launch with broker
analyzer-cli --broker
```

### Documentation Needed
A "How to Connect Your Broker" guide in docs/ covering:
- TastyTrade setup (token acquisition)
- How to implement `MarketDataProvider` for a new broker
- Environment variable reference
- YAML credential file format

---

## 5. The "State Layer" Problem

### Problem
market_analyzer is a stateless library. Users need somewhere to store:
- Open positions (so `filter_trades_with_portfolio()` works)
- Trade outcomes (so `calibrate_weights()` improves over time)
- Personal preferences (default tickers, account size, risk limits)

### Solution: User Context Store (Proposed)

```
~/.market_analyzer/
    config.yaml          # User preferences (default tickers, account size, risk limits)
    cache/               # OHLCV cache (already exists, auto-created)
    models/              # HMM models (already exists, auto-created)
    portfolio.yaml       # User's open positions (NEW — for filter_trades_with_portfolio)
    outcomes.csv         # Trade outcome history (NEW — for calibrate_weights)
    broker.yaml          # Broker credentials (already exists)
    .env                 # Alternative credential format (already supported)
```

**Design principle:** MA remains stateless. The CLI reads/writes user state files. eTrading manages its own state in a database. Third-party users use the config/portfolio files for standalone use.

### portfolio.yaml Format (Proposed)
```yaml
positions:
  - ticker: SPY
    structure: iron_condor
    short_put: 480
    short_call: 520
    expiration: "2026-04-17"
    credit_received: 2.45
    quantity: 1
  - ticker: GLD
    structure: credit_spread
    short_strike: 185
    expiration: "2026-04-17"
    credit_received: 1.20
    quantity: 2
```

---

## 6. PyPI Publication Checklist

```
Step 1:  Choose license → MIT  ✓ (done)
Step 2:  Fix README.md → write root README  (pending)
Step 3:  Add __version__ to __init__.py  ✓ (done)
Step 4:  Create py.typed marker  ✓ (done)
Step 5:  Fix hardcoded paths  ✓ (done — _broker.py)
Step 6:  Create .env.example (no secrets)  ✓ (done)
Step 7:  Test: pip install -e ".[dev]" on clean venv
Step 8:  Test: python -m pytest passes
Step 9:  Build: python -m build
Step 10: Upload test: twine upload --repository testpypi dist/*
Step 11: Test install: pip install -i https://test.pypi.org/simple/ market-analyzer
Step 12: Upload prod: twine upload dist/*
Step 13: Verify: pip install market-analyzer
```

### pyproject.toml Additions Needed
```toml
[project.urls]
Homepage = "https://github.com/yourusername/market-analyzer"
Documentation = "https://github.com/yourusername/market-analyzer/tree/main/docs"
Changelog = "https://github.com/yourusername/market-analyzer/blob/main/CHANGELOG.md"

[project]
keywords = ["options", "trading", "regime-detection", "HMM", "quantitative-finance"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Financial and Insurance Industry",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Office/Business :: Financial :: Investment",
]
```

---

## 7. GitHub Repository Hygiene

### Branch Protection
```
Settings → Branches → Add rule → main:
  ✓ Require pull request reviews (1 reviewer)
  ✓ Require status checks (CI tests)
  ✓ Require branches up to date
```

### GitHub Actions CI (`.github/workflows/test.yml`)
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: python -m pytest tests/ -m "not integration" -v
```

### Issue Templates (`.github/ISSUE_TEMPLATE/`)
Two templates:
- `bug_report.yml` — ticker, regime state, error message, expected vs actual behavior
- `feature_request.yml` — which part of the pipeline, trading rationale, implementation idea

### Badges for README
```markdown
[![Tests](https://github.com/youruser/market-analyzer/actions/workflows/test.yml/badge.svg)](...)
[![PyPI version](https://badge.fury.io/py/market-analyzer.svg)](...)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](...)
```

---

## 8. How People Discover Your Package

### Primary Discovery Channels (Ranked by ROI)

1. **PyPI listing** — searchable once published. Keywords matter:
   - `options-trading`, `regime-detection`, `HMM`, `systematic-trading`, `quantitative-finance`

2. **GitHub topics** — add to repo settings:
   - `options-trading`, `quant`, `systematic-trading`, `hmm`, `regime-detection`, `tastytrade`, `python`

3. **README quality** — GitHub indexes README content for search. Key phrases to include:
   - "HMM regime detection", "options income trading", "iron condor", "theta harvesting"

4. **Awesome lists** — submit to:
   - [awesome-quant](https://github.com/wilsonfreitas/awesome-quant)
   - [awesome-python-trading](https://github.com/CodeForTrading/awesome-algo-trading)

5. **Community posts**:
   - r/algotrading — post "Show and Tell" with regime detection demo
   - r/options — post "I built a systematic options analyzer"
   - QuantConnect community forum
   - Twitter/X — tag `#QuantFinance`, `#AlgoTrading`, `#OptionsTrading`

6. **Blog post** — "Building a systematic options framework with HMM regime detection"
   - Medium, Substack, or personal site
   - Include a compelling chart (regime overlay on SPY price history)

---

## 9. Roadmap for Community Contributors

These are well-scoped areas where contributors can add value without needing to understand the full codebase:

### High Value / Well-Defined
| Area | Description | Skills Needed |
|------|-------------|---------------|
| **IBKR broker integration** | Implement `MarketDataProvider` for Interactive Brokers | Python, IBKR API |
| **Schwab broker integration** | Implement for Charles Schwab (post-TD Ameritrade migration) | Python, Schwab API |
| **Webull integration** | Implement for Webull (popular retail broker) | Python, Webull API |
| **Backtesting engine** | Feed historical OHLCV through MA's pure functions | Python, pandas |

### Medium Value / Research-Heavy
| Area | Description | Skills Needed |
|------|-------------|---------------|
| **Web dashboard** | Streamlit/Flask frontend for the CLI | Python, Streamlit |
| **Crypto markets** | Add Bitcoin/ETH regime detection | Python, crypto API |
| **Forex markets** | Add FX regime detection and carry trade signals | Python, FX data |
| **ML regime validation** | Compare HMM predictions vs actual outcomes | ML, statistics |

### Advanced
| Area | Description | Skills Needed |
|------|-------------|---------------|
| **POP calibration** | Track estimated vs actual win rates | Statistics, ML |
| **Multi-leg execution** | Smart leg sequencing for complex structures | Execution logic |
| **Alternative data** | Earnings call sentiment, news flow signals | NLP, APIs |

---

## 10. Security Considerations

### Before Release
1. **Audit git history** — ensure no credentials were ever committed:
   ```bash
   git log --all --full-history -- "*.env"
   git log --all --full-history -- "*credentials*"
   ```
   If credentials found, use BFG Repo Cleaner or `git filter-branch` to purge.

2. **Run bandit** — Python security linter:
   ```bash
   pip install bandit
   bandit -r market_analyzer/ -ll
   ```

3. **Check .gitignore** — verify these are excluded:
   ```
   .env
   *.yaml (credential files)
   ~/.market_analyzer/
   ```

4. **Rotate any exposed credentials** — if TastyTrade tokens appeared in git history, invalidate them.

### Ongoing
- Add `SECURITY.md` with:
  - How to report vulnerabilities (private email or GitHub Security Advisories)
  - What is and isn't in scope
  - Response timeline commitment

### Sample SECURITY.md
```markdown
# Security Policy

## Reporting a Vulnerability

Please DO NOT file a public GitHub issue for security vulnerabilities.

Email: security@yourdomain.com (or use GitHub Security Advisories)

We will respond within 48 hours and provide a fix within 7 days for critical issues.

## Scope
- Credential handling in broker/ modules
- Data integrity (fake/stale data returned as real)
- Dependency vulnerabilities (run: pip audit)

## Out of Scope
- Trading losses (MA provides analysis, not financial advice)
- Broker API bugs (report to your broker)
```

---

## 11. README Structure (What to Write)

The root README.md is the most important file in the repository. People decide whether to use your project in 30 seconds of reading it. Recommended structure:

```markdown
# market_analyzer

> Systematic options analysis library: HMM regime detection, ranked trade recommendations,
> and every analytical building block for informed options trading decisions.

[![Tests](badge)] [![PyPI](badge)] [![License: MIT](badge)]

## What It Does
- Detects per-instrument market regime (R1–R4) using Hidden Markov Models
- Ranks and scores trade opportunities across 11 option structures
- Generates daily trading plans with horizon-bucketed recommendations
- Validates execution quality, manages position lifecycle, sizes positions via Kelly criterion
- Works without a broker (yfinance fallback); connects to TastyTrade for live quotes

## Quick Start
pip install market-analyzer
analyzer-cli

## With Live Broker Quotes
pip install market-analyzer[tastytrade]
analyzer-cli --broker

## Key Concepts
### Regime States
| R1 | Low-Vol Mean Reverting | Iron condors, strangles |
| R2 | High-Vol Mean Reverting | Wider wings, defined risk |
| R3 | Low-Vol Trending | Directional spreads |
| R4 | High-Vol Trending | Long vega only |

## Documentation
- [User Manual](docs/USER_MANUAL.md)
- [API Reference](docs/API_REFERENCE.md)
- [eTrading Integration](ETRADING_INTEGRATION.md)
- [Changelog](CHANGELOG.md)

## Architecture
[diagram here]

## License
MIT
```

---

*This document was generated 2026-03-21 to track market_analyzer's readiness for public release.*
