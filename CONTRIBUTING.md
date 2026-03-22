# Contributing to market_analyzer

## Development Setup

```bash
git clone https://github.com/nitinblue/market_analyzer.git
cd market-analyzer

# Python 3.12 required (hmmlearn has no 3.13+ wheels)
py -3.12 -m venv .venv_312
.venv_312/Scripts/pip install -e ".[dev]"

# Run tests
.venv_312/Scripts/python -m pytest tests/ -v
```

## Running Tests

```bash
# All tests
.venv_312/Scripts/python -m pytest tests/ -v

# Skip integration tests (no network)
.venv_312/Scripts/python -m pytest -m "not integration" -v

# Single test file
.venv_312/Scripts/python -m pytest tests/test_regime.py -v
```

## Code Standards

- **Type everything.** Pydantic models for public interfaces. Type hints on all functions.
- **No module-level mutable state.** All caches, connections, config injectable via constructor.
- **Pure functions preferred.** Features in `features/` are pure — no data fetching, no side effects.
- **Every function that recommends a trade returns a TradeSpec.** No text-only recommendations.
- **No Black-Scholes pricing — ever.** All option prices from broker or None.
- **TDD.** Write failing test first, then implement.

## Adding a New Broker

1. Create `market_analyzer/broker/yourbroker/` with 4 files
2. Implement 3-5 ABCs from `broker/base.py`
3. Map your broker's data format to `OptionQuote`, `MarketMetrics`, `AccountBalance`
4. Add `connect_yourbroker()` function
5. Add to setup wizard in `cli/_setup.py`
6. See `broker/alpaca/` as a clean example (~200 lines total)

## Pull Request Process

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Write tests first (TDD)
4. Implement the feature
5. Run full test suite (`pytest tests/ -v`)
6. Submit PR with description of what and why

## Architecture

```
market_analyzer/
  models/          # Pydantic data models (no logic)
  features/        # Pure functions (no data fetching)
  service/         # Service layer (orchestrates data + features)
  opportunity/     # Trade assessors (setups + option plays)
  validation/      # Profitability gates and stress tests
  broker/          # Broker integrations (6 supported)
  adapters/        # BYOD adapters (CSV, dict, templates)
  data/            # Data fetching + caching
  cli/             # Interactive CLI
  config/          # Settings
```
