# market_analyzer

**Historical market data service and HMM-based regime detection for options trading.**

Serves as the canonical historical data layer for the entire ecosystem (market_analyzer, cotrader, decision agent). Detects per-instrument regime state (R1–R4) using Hidden Markov Models, enabling regime-aware strategy selection for small options accounts. Real-time/streaming data remains with broker connections in cotrader.

---

## Ownership

| Section | Owner | Notes |
|---------|-------|-------|
| Domain rules, regime definitions, strategy mappings | Nitin | Trading philosophy, account constraints, regime semantics |
| Code architecture, module structure | Claude | Package layout, dependency graph, implementation |
| API contracts, data models | Claude | Pydantic models, input/output specs |
| Data provider contracts | Claude | ABC design, provider implementations, caching |
| Caching strategy | Claude | Parquet cache, delta-fetch, staleness logic |
| Data source selection | Nitin | Which providers to use, API key provisioning |
| Feature engineering | Claude | Domain guidance from Nitin; implementation by Claude |
| HMM model spec | Claude | Regime definitions from Nitin; hmmlearn config by Claude |
| Testing strategy | Claude | Unit, integration, regime validation |

---

## Standing Instructions for Claude

- **Read this file completely before any work.** All code decisions must align with the domain rules below.
- **No decision logic runs without a regime label.** This is the core invariant.
- **All decisions must be explainable.** No black-box outputs—every regime label must trace back to features and model state.
- **Per-instrument regime detection.** Never build a single global "market regime." Each ticker gets its own regime.
- **Income-first bias.** Default to theta-harvesting strategies; directional only when regime permits.
- **Hedging is same-ticker only.** No beta-weighted index hedging.
- **Small account constraints.** Design for 50K taxable, 200K IRA. Margin efficiency matters.
- **Keep it a library.** This package is imported by cotrader—no CLI, no server, no UI.
- **Prefer simplicity.** Minimal dependencies, no over-engineering, no speculative abstractions.
- **Type everything.** Use Pydantic models for all public interfaces. Type hints on all functions.
- **Historical data flows through this module.** All projects in the ecosystem (cotrader, decision agent) use `market_analyzer.data.DataService` for historical data. No other module fetches its own historical data.
- **Cache before fetch.** Always check parquet cache first. Only hit network for delta-fetch (missing date ranges). Never re-download data that's already cached.
- **Provider failures are not silent.** Raise typed exceptions on fetch failures, rate limits, bad tickers. Callers must be able to distinguish "no data exists" from "fetch failed."
- **No API keys in code.** All credentials come from environment variables or config files. Never hardcode keys, tokens, or passwords.
- **Data and regime modules are independently usable.** `data/` must work without `hmm/` or `features/`. `hmm/` must work with caller-provided DataFrames. No circular dependencies between the two halves.

---

## Domain Rules (Owner: Nitin)

### Trading Philosophy

- **All decisions are explainable**
- **Designed for small accounts (50K taxable, 200K IRA)**
- **Income-first (theta harvesting), directional only when regime allows**
- **Hedging is same-ticker only (no beta-weighted index hedging)**

### Why Regime First?

Options strategies **only make sense relative to regime**:
- Theta is fragile in trend acceleration
- Directional trades are expensive in chop
- Vega behaves differently in metals vs tech

> **No decision logic runs without a regime label**

### Regime States (4-State Model)

| Regime ID | Name | Description |
|-----------|------|-------------|
| R1 | Low-Vol Mean Reverting | Chop, range-bound, IV compression |
| R2 | High-Vol Mean Reverting | Wide swings, but no sustained trend |
| R3 | Low-Vol Trending | Slow, persistent directional move |
| R4 | High-Vol Trending | Explosive moves, IV expansion |

### Asset-Specific Regimes

- Regime is detected at **instrument level**
- Optional **sector-level HMM** for confirmation
- No single "market regime"

Examples:
- Gold can be trending while Tech is mean reverting
- Metals behave structurally differently from equities

### Regime -> Strategy Mapping

| Regime | Income (Theta) | Directional | Vega | Notes |
|--------|----------------|-------------|------|-------|
| R1: Low-Vol MR | Primary | Avoid | Short Vega | Ideal for iron condors, strangles |
| R2: High-Vol MR | Selective | Avoid | Neutral | Wider wings, defined risk |
| R3: Low-Vol Trend | Light | Primary | — | Directional spreads |
| R4: High-Vol Trend | Avoid | Selective | Long Vega | Risk-defined only |

### Income-First Bias

Default preference order:
1. Short theta
2. Neutral delta
3. Defined risk
4. Minimal margin usage

Directional trades only when:
- Regime = R3 or R4
- Portfolio delta budget allows

---

## Architecture & Module Structure (Owner: Claude)

```
market_analyzer/
├── __init__.py
├── models/
│   ├── __init__.py
│   ├── regime.py          # Pydantic models: RegimeState, RegimeResult, RegimeConfig
│   ├── features.py        # Pydantic models: FeatureConfig, FeatureVector
│   └── data.py            # Pydantic models: DataRequest, DataResult, CacheMeta
├── features/
│   ├── __init__.py
│   └── pipeline.py        # Feature computation: log returns, realized vol, ATR, trend strength
├── hmm/
│   ├── __init__.py
│   ├── trainer.py          # HMM training: fit, refit, persist
│   └── inference.py        # Regime inference: predict current regime from features
├── service/
│   ├── __init__.py
│   └── regime_service.py   # Top-level regime API: accepts DataFrame or auto-fetches
├── data/
│   ├── __init__.py
│   ├── service.py          # DataService: orchestrates cache + providers
│   ├── cache/
│   │   ├── __init__.py
│   │   └── parquet_cache.py  # ParquetCache: read/write/freshness checks
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py         # DataProvider ABC
│   │   ├── yfinance.py     # YFinanceProvider (OHLCV)
│   │   ├── cboe.py         # CBOEProvider (options/IV)
│   │   └── tastytrade.py   # TastyTradeProvider (broker history)
│   └── registry.py         # Maps (ticker, data_type) → provider
└── tests/
    ├── __init__.py
    ├── test_features.py
    ├── test_hmm.py
    ├── test_service.py
    ├── test_regime_validation.py
    ├── test_data_service.py
    ├── test_cache.py
    └── test_providers.py
```

### Dependency Graph

```
service/regime_service.py
    ├── features/pipeline.py
    │       └── models/features.py
    ├── hmm/trainer.py
    │       └── models/regime.py
    ├── hmm/inference.py
    │       └── models/regime.py
    └── data/service.py  (optional, for auto-fetch)
            ├── data/cache/parquet_cache.py
            ├── data/providers/yfinance.py
            ├── data/providers/cboe.py
            ├── data/providers/tastytrade.py
            ├── data/registry.py
            └── models/data.py

data/service.py  (independently usable by cotrader)
    ├── data/cache/parquet_cache.py
    ├── data/providers/*.py
    ├── data/registry.py
    └── models/data.py
```

### Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `models/` | Pydantic data models only. No logic. |
| `features/` | Compute feature vectors from OHLCV DataFrames. Normalization lives here. |
| `hmm/` | hmmlearn wrapper. Training, persistence, inference. |
| `service/` | Regime orchestration. Entry point for regime detection callers. |
| `data/service.py` | Data orchestration. Entry point for historical data callers. Cache-first fetch logic. |
| `data/cache/` | Parquet read/write, freshness checks, delta-date computation. |
| `data/providers/` | Network fetchers. Each provider implements the `DataProvider` ABC. |
| `data/registry.py` | Maps (ticker, data_type) to the correct provider. |
| `opportunity/setups/` | Price-based directional pattern detection (breakout, momentum, mean_reversion). |
| `opportunity/option_plays/` | Horizon-specific option structure recommendations (zero_dte, leap, earnings). |

---

## API Contracts (Owner: Claude)

### Core Regime Models (Existing)

```python
from enum import IntEnum
from pydantic import BaseModel
import pandas as pd
from datetime import date

class RegimeID(IntEnum):
    R1_LOW_VOL_MR = 1    # Low-Vol Mean Reverting
    R2_HIGH_VOL_MR = 2   # High-Vol Mean Reverting
    R3_LOW_VOL_TREND = 3  # Low-Vol Trending
    R4_HIGH_VOL_TREND = 4 # High-Vol Trending

class RegimeResult(BaseModel):
    ticker: str
    regime: RegimeID
    confidence: float          # Posterior probability of assigned regime
    regime_probabilities: dict[RegimeID, float]  # All 4 state probabilities
    as_of_date: date
    model_version: str

class RegimeConfig(BaseModel):
    n_states: int = 4
    training_lookback_years: float = 2.0
    feature_lookback_days: int = 60
    refit_frequency_days: int = 30
```

### Data Models (New)

```python
from enum import StrEnum
from pydantic import BaseModel
from datetime import date, datetime
from pathlib import Path

class DataType(StrEnum):
    OHLCV = "ohlcv"
    OPTIONS_IV = "options_iv"
    BROKER_HISTORY = "broker_history"

class ProviderType(StrEnum):
    YFINANCE = "yfinance"
    CBOE = "cboe"
    TASTYTRADE = "tastytrade"

class DataRequest(BaseModel):
    ticker: str
    data_type: DataType
    start_date: date | None = None   # None = use default lookback
    end_date: date | None = None     # None = today

class CacheMeta(BaseModel):
    ticker: str
    data_type: DataType
    provider: ProviderType
    first_date: date                 # Earliest date in cached data
    last_date: date                  # Latest date in cached data
    last_fetched: datetime           # When we last hit the network
    row_count: int
    file_path: Path

class DataResult(BaseModel):
    ticker: str
    data_type: DataType
    provider: ProviderType
    from_cache: bool                 # True if served entirely from cache
    date_range: tuple[date, date]    # (first, last) date in returned data
    row_count: int
    # Actual DataFrame returned separately (not in Pydantic model)

    class Config:
        arbitrary_types_allowed = True
```

### Data Provider ABC

```python
from abc import ABC, abstractmethod

class DataProvider(ABC):
    @property
    @abstractmethod
    def provider_type(self) -> ProviderType: ...

    @property
    @abstractmethod
    def supported_data_types(self) -> list[DataType]: ...

    @abstractmethod
    def fetch(self, request: DataRequest) -> pd.DataFrame:
        """Fetch data from remote source. Raises on failure."""
        ...

    @abstractmethod
    def validate_ticker(self, ticker: str) -> bool:
        """Check if ticker is valid for this provider."""
        ...
```

### Data Service Interface

```python
class DataService:
    def get(self, request: DataRequest) -> tuple[pd.DataFrame, DataResult]:
        """Get data (cache-first, delta-fetch if stale)."""
        ...

    def get_ohlcv(self, ticker: str, start_date: date | None = None,
                  end_date: date | None = None) -> pd.DataFrame:
        """Convenience: fetch OHLCV data for a ticker."""
        ...

    def get_options_iv(self, ticker: str, start_date: date | None = None,
                       end_date: date | None = None) -> pd.DataFrame:
        """Convenience: fetch options/IV data for a ticker."""
        ...

    def cache_status(self, ticker: str,
                     data_type: DataType | None = None) -> list[CacheMeta]:
        """Check what's cached for a ticker."""
        ...

    def invalidate_cache(self, ticker: str,
                         data_type: DataType | None = None) -> None:
        """Force re-fetch on next request."""
        ...
```

### Regime Service Interface (Updated)

```python
class RegimeService:
    def __init__(self, config: RegimeConfig = RegimeConfig(),
                 data_service: DataService | None = None):
        """
        If data_service is provided, detect() can auto-fetch OHLCV data.
        If not, caller must always provide ohlcv DataFrame.
        """
        ...

    def detect(self, ticker: str,
               ohlcv: pd.DataFrame | None = None) -> RegimeResult:
        """
        Detect current regime for a single instrument.
        If ohlcv is None and data_service is available, auto-fetches.
        Raises ValueError if ohlcv is None and no data_service.
        """
        ...

    def detect_batch(self, tickers: list[str] | None = None,
                     data: dict[str, pd.DataFrame] | None = None
                     ) -> dict[str, RegimeResult]:
        """
        Detect regimes for multiple instruments.
        Can accept ticker list (auto-fetch) or dict of DataFrames.
        """
        ...

    def fit(self, ticker: str, ohlcv: pd.DataFrame | None = None) -> None:
        """Train/retrain HMM for a given instrument."""
        ...
```

---

## Feature Engineering (Owner: Claude, domain guidance from Nitin)

### Feature Pipeline

Computed per **instrument**, not globally. The feature pipeline is data-source-agnostic—it accepts a DataFrame and doesn't care whether it came from cache, yfinance, or the caller.

| Feature | Computation | Notes |
|---------|-------------|-------|
| Log returns (1d) | `log(close_t / close_{t-1})` | Primary return signal |
| Log returns (5d) | `log(close_t / close_{t-5})` | Weekly momentum |
| Realized volatility | Rolling std of log returns (20-day) | Volatility regime signal |
| ATR (normalized) | ATR / close price | Normalized for cross-asset comparison |
| Trend strength | Slope of 20-day SMA, normalized | Directional signal |
| Volume anomaly | Volume / 20-day avg volume | Optional; liquidity signal |

### Normalization

- All features are z-score normalized **per ticker** using a rolling window
- Window length matches `feature_lookback_days` in config
- IV Rank / IV Percentile deferred until options data integration with cotrader

### Historical Windows

| Component | Lookback |
|-----------|----------|
| Feature calculation | 30–90 days |
| HMM training | 1–3 years (rolling) |
| Regime inference | Daily or intraday |

---

## HMM Model Spec (Owner: Claude, regime definitions from Nitin)

### Model Configuration

- **Library:** hmmlearn `GaussianHMM`
- **n_components:** 4 (maps to R1–R4)
- **covariance_type:** "full" (captures feature correlations)
- **n_iter:** 100 (EM iterations)
- **random_state:** seeded for reproducibility

### Why HMM?

- Captures **latent market structure**
- Separates *observation noise* from *true regime*
- Well-understood, explainable, robust
- Online inference with periodic re-fitting

### Training Pipeline

1. Fetch or receive OHLCV data (1–3 years)
2. Compute feature matrix via `features/pipeline.py`
3. Fit `GaussianHMM` on feature matrix
4. **Post-fit label alignment:** HMM states are arbitrary integers. Map them to R1–R4 using feature means (e.g., lowest vol + lowest trend = R1, highest vol + highest trend = R4)
5. Persist fitted model (pickle or joblib)

### Inference Pipeline

1. Receive recent OHLCV data
2. Compute feature vector
3. Run `model.predict()` on recent window
4. Return mapped regime label + posterior probabilities

### Label Alignment Strategy

HMM hidden states have no inherent meaning. After fitting, align states to R1–R4 by sorting on:
- **Volatility axis:** mean realized vol per state (low vs high)
- **Trend axis:** mean absolute trend strength per state (mean-reverting vs trending)

This gives a 2x2 mapping that naturally produces R1–R4.

---

## Data Service (Owner: Claude, data source selection by Nitin)

### Scope

- **Historical data only.** This module serves all historical/daily data needs for the ecosystem.
- **Real-time data stays with cotrader.** Streaming quotes, live fills, and order book data come from broker connections in cotrader.
- **Boundary:** if it's bar data (daily or slower) and it's historical, it lives here.

### Data Providers

| Provider | Data Types | Auth Required | Notes |
|----------|-----------|---------------|-------|
| yfinance | OHLCV | No | Free, rate-limited. Primary source for price data. |
| CBOE | OPTIONS_IV | Yes (API key) | IV, skew, term structure. Details TBD. |
| TastyTrade | BROKER_HISTORY | Yes (username/password) | Trade history, P&L. Via tastytrade-sdk. |

### Cache Strategy

**Location:** `~/.market_analyzer/cache/`

**Directory layout:**
```
~/.market_analyzer/cache/
├── ohlcv/
│   ├── GLD.parquet
│   ├── SPY.parquet
│   └── AAPL.parquet
├── options_iv/
│   └── SPY.parquet
├── broker_history/
│   └── trades.parquet
└── _meta.json              # CacheMeta entries for all cached files
```

**Cache behavior:**
- **Staleness threshold:** 18 hours by default (configurable). Data older than this triggers a delta-fetch.
- **Delta-fetch:** Only request dates from `last_cached_date + 1` to today. Append to existing parquet.
- **Weekend/holiday awareness:** Don't mark cache as stale on Saturday/Sunday or market holidays. Last trading day's data is fresh until next trading day.
- **Atomic writes:** Write to temp file, then rename. No partial parquet files.
- **Cache miss:** Full fetch from provider, write complete parquet file.
- **`_meta.json`:** Single file tracking all cache entries (ticker, data_type, date range, last_fetched timestamp, row count, file path).

### DataFrame Contracts

**OHLCV DataFrame:**
- Columns: `Open`, `High`, `Low`, `Close`, `Volume`
- Index: `DatetimeIndex` (daily frequency)
- Sorted ascending by date
- No NaN values in required columns

**Options/IV DataFrame:** TBD (pending CBOE integration design)

**Broker History DataFrame:** TBD (pending TastyTrade integration design)

### Provider Configuration

All credentials via environment variables (stored in eTrading `.env`):

| Variable Pattern | Provider | Notes |
|------------------|----------|-------|
| `TASTYTRADE_***_LIVE` | TastyTrade | Client secret + refresh token for live session |
| `TASTYTRADE_***_PAPER` | TastyTrade | Client secret + refresh token for paper session |
| `TASTYTRADE_***_DATA` | TastyTrade | Client secret + refresh token for DXLink streaming |
| `CBOE_API_KEY` | CBOE | Required for options/IV data |

**Credential loading order:** env vars first (no YAML needed), YAML fallback.
DXLink data session uses `_DATA` credentials (always live, even when trading session is paper).
CLI helper (`cli/_broker.py`) auto-loads eTrading `.env` for credentials.

### Usage Patterns

**Pattern 1: Auto-fetch via RegimeService**
```python
from market_analyzer.data.service import DataService
from market_analyzer.service.regime_service import RegimeService

data_svc = DataService()
regime_svc = RegimeService(data_service=data_svc)

# No DataFrame needed — auto-fetches and caches OHLCV
result = regime_svc.detect(ticker="GLD")
```

**Pattern 2: Direct DataService use by cotrader**
```python
from market_analyzer.data.service import DataService

data_svc = DataService()

# Any project can fetch historical data through this module
ohlcv = data_svc.get_ohlcv("SPY")
iv_data = data_svc.get_options_iv("SPY")
```

**Pattern 3: Caller provides data (backward compatible)**
```python
from market_analyzer.service.regime_service import RegimeService

regime_svc = RegimeService()  # No data_service
result = regime_svc.detect(ticker="GLD", ohlcv=my_dataframe)
```

---

## Tech Stack

| Dependency | Purpose | Required |
|------------|---------|----------|
| Python 3.11+ | Runtime | Yes |
| hmmlearn | HMM fitting and inference | Yes |
| pandas | DataFrame handling | Yes |
| numpy | Numerical computation | Yes |
| pydantic | Data models, validation | Yes |
| scikit-learn | hmmlearn dependency | Yes (transitive) |
| yfinance | OHLCV data fetching | Yes |
| pyarrow | Parquet read/write for cache | Yes |
| requests | HTTP client for CBOE provider | Yes |
| joblib | Model persistence | Yes |
| tastytrade-sdk | TastyTrade broker history | Optional |
| pytest | Testing | Dev |
| pytest-mock | Mock providers in tests | Dev |

---

## Testing Strategy (Owner: Claude)

### Test Layers

| Layer | What | How |
|-------|------|-----|
| Unit | Feature computation correctness | Known OHLCV -> expected features |
| Unit | Pydantic model validation | Invalid inputs rejected |
| Unit | ParquetCache read/write | Write parquet, read back, verify roundtrip |
| Unit | Cache freshness logic | Mock clock, verify staleness detection, weekend awareness |
| Unit | Delta date computation | Given cached range + today, compute correct fetch range |
| Integration | Full regime pipeline: OHLCV -> RegimeResult | Synthetic + real data |
| Integration | DataService full cycle: cache miss -> fetch -> cache hit | Mock provider, real parquet cache |
| Contract | DataProvider implementations | Each provider returns correct DataFrame schema |
| Regime validation | Label alignment makes sense | Verify R1 has lowest vol, R4 has highest vol+trend |
| Regression | Regime stability on known data | Fitted model produces consistent labels on historical data |
| Provider integration | Live provider tests | Real network calls, marked `@pytest.mark.integration` |

### Test Data

- **Synthetic data** for unit tests (deterministic, no network)
- **Real data via yfinance** for integration tests (marked with `@pytest.mark.integration`)
- **Fixture data** (saved CSVs) for regression tests
- **Mock providers** for DataService tests (deterministic, no network)

---

## Integration with cotrader

This library is used by `cotrader` (trading platform at `C:\Users\nitin\PythonProjects\eTrading`).

### Data Integration Contract

```
cotrader → market_analyzer.data.DataService.get_ohlcv() → cached OHLCV DataFrame
cotrader → market_analyzer.data.DataService.get_options_iv() → cached IV DataFrame
```

All historical data requests from cotrader flow through `market_analyzer.data.DataService`. Cotrader does not fetch its own historical data.

### Regime Integration Contract

```
cotrader → market_analyzer.RegimeService.detect() → RegimeResult
cotrader uses RegimeResult to gate strategy selection in Decision Agent
```

### Architecture Context

```
cotrader (execution, broker, real-time data)
    │
    ├── real-time quotes, fills, order book → broker connections (cotrader-owned)
    │
    ├── historical OHLCV, IV, trade history → market_analyzer.data.DataService
    │
    ▼
market_analyzer (this library) ← historical data + regime detection
    │
    ▼
Decision Agent (separate library) ← strategy selection
    │
    ▼
What-if Evaluator (part of cotrader) ← PnL, Greeks, Margin
```

**Boundary:** real-time data = cotrader, historical data = market_analyzer.

---

## Quick Reference — Command Lines

All commands assume you're in the project root (`C:\Users\nitin\PythonProjects\market_analyzer`).

### Setup

```bash
# Create venv (Python 3.12 — hmmlearn has no 3.14 wheels yet)
py -3.12 -m venv .venv

# Install package + dev deps
.venv/Scripts/pip install -e ".[dev]"
```

### Running Tests

```bash
# All tests
.venv/Scripts/python -m pytest tests/ -v

# Individual test files
.venv/Scripts/python -m pytest tests/test_features.py -v
.venv/Scripts/python -m pytest tests/test_hmm.py -v
.venv/Scripts/python -m pytest tests/test_cache.py -v
.venv/Scripts/python -m pytest tests/test_data_service.py -v
.venv/Scripts/python -m pytest tests/test_providers.py -v
.venv/Scripts/python -m pytest tests/test_service.py -v
.venv/Scripts/python -m pytest tests/test_regime_validation.py -v
.venv/Scripts/python -m pytest tests/test_technicals.py -v
.venv/Scripts/python -m pytest tests/test_phases.py -v
.venv/Scripts/python -m pytest tests/test_fundamentals.py -v
.venv/Scripts/python -m pytest tests/test_macro.py -v
.venv/Scripts/python -m pytest tests/test_opportunity.py -v
.venv/Scripts/python -m pytest tests/test_breakout.py -v
.venv/Scripts/python -m pytest tests/test_momentum.py -v
.venv/Scripts/python -m pytest tests/test_orb.py -v
.venv/Scripts/python -m pytest tests/test_price_structure.py -v
.venv/Scripts/python -m pytest tests/test_analyzer.py -v
.venv/Scripts/python -m pytest tests/test_ranking.py -v
.venv/Scripts/python -m pytest tests/test_context.py -v
.venv/Scripts/python -m pytest tests/test_instrument.py -v
.venv/Scripts/python -m pytest tests/test_screening.py -v
.venv/Scripts/python -m pytest tests/test_entry.py -v
.venv/Scripts/python -m pytest tests/test_strategy.py -v
.venv/Scripts/python -m pytest tests/test_exit.py -v
.venv/Scripts/python -m pytest tests/test_mean_reversion.py -v
.venv/Scripts/python -m pytest tests/test_earnings.py -v

# Run a single test by name
.venv/Scripts/python -m pytest tests/test_hmm.py::TestRegimeInference::test_predict_returns_regime_result -v

# Integration tests only (requires network)
.venv/Scripts/python -m pytest -m integration -v

# Skip integration tests
.venv/Scripts/python -m pytest -m "not integration" -v
```

### CLI Commands (after pip install)

```bash
# Interactive regime exploration (default tickers: SPY, GLD, QQQ, TLT)
analyzer-explore
analyzer-explore --tickers AAPL MSFT AMZN
analyzer-explore --tickers GLD

# Regime chart with price, volume, RSI, confidence panels (requires [plot])
analyzer-plot
analyzer-plot --tickers AAPL MSFT
analyzer-plot --tickers GLD --save

# Interactive REPL (Claude-like interface)
analyzer-cli
analyzer-cli --market india
```

### Script Wrappers (no install required)

```bash
.venv/Scripts/python explore.py
.venv/Scripts/python explore.py --tickers GLD
.venv/Scripts/python plot_regime.py
.venv/Scripts/python plot_regime.py --tickers GLD --save
```

### Quick Python Usage

```bash
# Detect regime (via facade)
.venv/Scripts/python -c "
from market_analyzer import MarketAnalyzer, DataService
ma = MarketAnalyzer(data_service=DataService())
r = ma.regime.detect('SPY')
print(f'{r.ticker}: R{r.regime} ({r.confidence:.0%})')
"

# Batch regime detection
.venv/Scripts/python -c "
from market_analyzer import MarketAnalyzer, DataService
ma = MarketAnalyzer(data_service=DataService())
for t, r in ma.regime.detect_batch(tickers=['SPY','GLD','QQQ','TLT']).items():
    print(f'{t}: R{r.regime} ({r.confidence:.0%})')
"

# Technical snapshot
.venv/Scripts/python -c "
from market_analyzer import MarketAnalyzer, DataService
ma = MarketAnalyzer(data_service=DataService())
t = ma.technicals.snapshot('SPY')
print(f'RSI: {t.rsi.value:.1f}, ATR: {t.atr_pct:.2f}%')
"

# Levels with R:R
.venv/Scripts/python -c "
from market_analyzer import MarketAnalyzer, DataService
ma = MarketAnalyzer(data_service=DataService())
print(ma.levels.analyze('SPY').summary)
"

# Rank trades across tickers
.venv/Scripts/python -c "
from market_analyzer import MarketAnalyzer, DataService
ma = MarketAnalyzer(data_service=DataService())
result = ma.ranking.rank(['SPY', 'GLD', 'QQQ', 'TLT'])
for e in result.top_trades[:5]:
    print(f'#{e.rank} {e.ticker} {e.strategy_type} score={e.composite_score:.2f} {e.verdict}')
"

# Black swan alert
.venv/Scripts/python -c "
from market_analyzer import MarketAnalyzer, DataService
ma = MarketAnalyzer(data_service=DataService())
alert = ma.black_swan.alert()
print(f'Alert: {alert.alert_level} (score={alert.composite_score:.2f})')
"

# Fetch OHLCV data only (cache-first)
.venv/Scripts/python -c "
from market_analyzer import DataService
df = DataService().get_ohlcv('GLD')
print(df.tail())
"

# Check what's cached
.venv/Scripts/python -c "
from market_analyzer import DataService
for m in DataService().cache_status('SPY'):
    print(f'{m.data_type}: {m.first_date} → {m.last_date} ({m.row_count} rows)')
"
```

### Workflow APIs (NEW)

```bash
# Market context (environment assessment)
.venv/Scripts/python -c "
from market_analyzer import MarketAnalyzer, DataService
ma = MarketAnalyzer(data_service=DataService())
ctx = ma.context.assess()
print(f'Environment: {ctx.environment_label}, Trading: {ctx.trading_allowed}')
"

# Full instrument analysis
.venv/Scripts/python -c "
from market_analyzer import MarketAnalyzer, DataService
ma = MarketAnalyzer(data_service=DataService())
a = ma.instrument.analyze('SPY')
print(f'{a.ticker}: R{a.regime_id} | {a.phase.phase_name} | RSI {a.technicals.rsi.value:.0f} | {a.trend_bias}')
"

# Screen for setups
.venv/Scripts/python -c "
from market_analyzer import MarketAnalyzer, DataService
ma = MarketAnalyzer(data_service=DataService())
result = ma.screening.scan(['SPY', 'GLD', 'QQQ', 'TLT'])
for c in result.candidates[:5]:
    print(f'{c.ticker} [{c.screen}] score={c.score:.2f}: {c.reason}')
"

# Entry confirmation
.venv/Scripts/python -c "
from market_analyzer import MarketAnalyzer, DataService, EntryTriggerType
ma = MarketAnalyzer(data_service=DataService())
e = ma.entry.confirm('SPY', EntryTriggerType.BREAKOUT_CONFIRMED)
print(f'Entry: {\"CONFIRMED\" if e.confirmed else \"NOT CONFIRMED\"} ({e.confidence:.0%})')
"

# Strategy selection + sizing
.venv/Scripts/python -c "
from market_analyzer import MarketAnalyzer, DataService
ma = MarketAnalyzer(data_service=DataService())
r = ma.regime.detect('SPY')
t = ma.technicals.snapshot('SPY')
params = ma.strategy.select('SPY', regime=r, technicals=t)
size = ma.strategy.size(params, current_price=t.current_price)
print(f'{params.primary_structure.structure_type} | {size.suggested_contracts} contracts | max risk \${size.max_risk_dollars:.0f}')
"
```

### Cache Management

```bash
# Cache location
ls ~/.market_analyzer/cache/ohlcv/

# Invalidate cache for a ticker (forces re-fetch on next request)
.venv/Scripts/python -c "
from market_analyzer import DataService
DataService().invalidate_cache('SPY')
print('Cache invalidated for SPY')
"

# Invalidate all cached data for a ticker
.venv/Scripts/python -c "
from market_analyzer import DataService
DataService().invalidate_cache('SPY', data_type=None)
"
```

---

## Performance: Plan Generation & DXLink

### Known Bottleneck: Intraday Candle Fetches

`ranking.rank()` iterates tickers × strategies sequentially. For 0DTE assessments, `assess_zero_dte()` calls `technical_service.orb()` which triggers `get_intraday_candles()` via DXLink streaming. Each call has a 15s timeout, and on failure falls back to yfinance (another network call). With 3 0DTE tickers this adds 45-60s+ to plan generation.

**Solution:** `ranking.rank(skip_intraday=True)` passes an empty DataFrame as intraday data, skipping DXLink and yfinance ORB fetches entirely. ORB is optional for daily plan generation (it's intraday monitoring data). The `plan.generate(skip_intraday=True)` parameter threads through to ranking.

### `_run_async()` in `broker/tastytrade/market_data.py`

Bridges async DXLink coroutines to sync callers. Two paths:
- **Running event loop detected** (e.g. FastAPI): submits `asyncio.run(coro)` to a 2-worker thread pool
- **No running loop** (standalone/CLI): uses persistent event loop with `run_until_complete`

Both paths have timeouts. Callers must `coro.close()` in except blocks to prevent "coroutine was never awaited" warnings when `_run_async` fails before consuming the coroutine.

### Performance Budget (13 tickers × 9 strategies = 83 assessments)

| Component | Time | Notes |
|-----------|------|-------|
| Black swan check | <5s | Single call |
| Technicals + regime per ticker | ~1s each | 13 tickers = ~13s |
| Levels analysis per ticker | <1s each | 13 tickers = ~13s |
| Opportunity assessments | ~1-2s each | 83 assessments = ~80-160s |
| **DXLink intraday (if enabled)** | **15s each** | **3 tickers = 45s+ (skip for plan!)** |
| Total with skip_intraday=True | ~60-120s | |
| Total without skip | ~120-200s | Likely to timeout |

---

## SaaS Deployment Contract (Owner: Nitin)

### Principle: market_analyzer is Stateless

market_analyzer is a **pure library** — it computes and returns results. It holds **no tenant state, no sessions, no persistent caches** between calls. The SaaS application (eTrading) owns all state: authentication, sessions, tenant isolation, caching policy, and credential management.

**Invariant:** A fresh `MarketAnalyzer()` instance per request must produce identical results to a reused one. No call should depend on prior calls having been made on the same instance.

### Two Broker Connection Modes

#### Mode 1: Standalone / CLI (market_analyzer authenticates)

Used when running market_analyzer directly from terminal. The library loads credentials and manages the broker session lifecycle.

```python
# CLI usage: analyzer-cli --broker --paper
# Internally uses cli/_broker.py → connect_broker()

from market_analyzer.broker.tastytrade import connect_tastytrade

market_data, metrics = connect_tastytrade(is_paper=True)
ma = MarketAnalyzer(
    data_service=DataService(),
    market_data=market_data,
    market_metrics=metrics,
)
```

**Credential chain:** env vars (`TASTYTRADE_***_LIVE`, `_PAPER`, `_DATA`) → YAML fallback (`tastytrade_broker.yaml`) → fail with clear error.

**Session class:** `TastyTradeBrokerSession` — loads credentials itself, manages connect/disconnect.

#### Mode 2: SaaS / Embedded (caller passes pre-authenticated sessions)

Used when eTrading (or any SaaS app) calls market_analyzer. The caller owns authentication — market_analyzer **never sees credentials**.

```python
# eTrading already has authenticated tastytrade SDK sessions
from market_analyzer.broker.tastytrade import connect_from_sessions
from market_analyzer import MarketAnalyzer, DataService

market_data, metrics = connect_from_sessions(
    sdk_session=tenant_sdk_session,      # Pre-authenticated Session
    data_session=tenant_data_session,    # DXLink session (optional, defaults to sdk_session)
)
ma = MarketAnalyzer(
    data_service=DataService(cache=tenant_scoped_cache),
    market_data=market_data,
    market_metrics=metrics,
)
```

**Session class:** `ExternalBrokerSession` — wraps pre-authenticated SDK sessions. `connect()` returns True immediately. `disconnect()` is a no-op (caller owns lifecycle).

**Key files:**
- `broker/tastytrade/__init__.py` — `connect_tastytrade()` (Mode 1), `connect_from_sessions()` (Mode 2)
- `broker/tastytrade/session.py` — `TastyTradeBrokerSession` (Mode 1), `ExternalBrokerSession` (Mode 2)
- `broker/base.py` — `BrokerSession`, `MarketDataProvider`, `MarketMetricsProvider` ABCs
- `cli/_broker.py` — CLI-only helper, loads eTrading `.env`, not used in SaaS mode

### Statelessness Violations (Must Fix)

The following module-level mutable state must be eliminated for clean SaaS deployment:

| Location | Variable | What it holds | Fix |
|----------|----------|---------------|-----|
| `config/__init__.py:549` | `_cached_settings` | Singleton Settings object | Accept `Settings` via constructor; no global cache |
| `fundamentals/fetch.py:28` | `_cache` | Per-ticker fundamentals with TTL | Move to caller-owned cache or accept cache dict as param |
| `macro/calendar.py:100` | `_ALL_EVENTS` | Lazy-built macro event list | Build fresh per call or accept as param |
| `broker/tastytrade/market_data.py:28` | `_thread_pool` | 2-worker ThreadPoolExecutor | Accept executor as dependency or create per-instance |
| `broker/tastytrade/market_data.py:349` | `_loop_lock` | Class-level threading.Lock | Make instance-level, not class-level |
| `service/regime_service.py` | `self._trainers` | In-memory HMM model cache | Caller provides model store or flush between requests |
| `service/ranking.py:363` | feedback parquet path | Writes to `~/.market_analyzer/feedback/` | Accept feedback store as dependency |

**Rule for Claude:** When adding new code, never introduce module-level mutable state. All caches, connections, and config must be injectable via constructor parameters.

### Multi-Broker Architecture

Three ABCs in `broker/base.py` — any broker can implement:

| ABC | Responsibility | TastyTrade impl |
|-----|---------------|-----------------|
| `BrokerSession` | Auth, connect/disconnect lifecycle | `TastyTradeBrokerSession`, `ExternalBrokerSession` |
| `MarketDataProvider` | Option chains, quotes, Greeks, intraday candles | `TastyTradeMarketData` (DXLink streamer) |
| `MarketMetricsProvider` | IV rank, IV percentile, beta, liquidity | `TastyTradeMetrics` (REST API) |

**Adding a new broker (e.g., Schwab, IBKR):**
1. Create `broker/<name>/session.py` implementing `BrokerSession`
2. Create `broker/<name>/market_data.py` implementing `MarketDataProvider`
3. Create `broker/<name>/metrics.py` implementing `MarketMetricsProvider` (optional)
4. Add `connect_<name>()` and `connect_from_sessions()` in `broker/<name>/__init__.py`
5. All existing services work unchanged — they only see the ABCs

**Design constraint:** Services never import broker implementations directly. They accept `MarketDataProvider` / `MarketMetricsProvider` via constructor. The caller (CLI or eTrading) decides which broker to wire in.

### Multi-Market Architecture

**Current state: ~40% wired.**

Configuration exists (`MarketDef` with timezone, hours, suffix, reference tickers for US + India). CLI accepts `--market india`. But the market parameter only flows through `MarketContextService` — most services ignore it.

**What works today:**
- `config/__init__.py` — `MarketDef` and `MarketSettings` with US + India definitions
- `service/context.py` — Uses market-specific reference tickers and VIX equivalent
- `cli/interactive.py` — `--market` flag wired to `MarketAnalyzer(market=...)`
- `macro/_rbi_dates.py` — RBI MPC dates defined (dormant, not wired into macro calendar)

**What's missing for true multi-market:**

| Gap | Impact | Where to fix |
|-----|--------|-------------|
| Ticker suffix not applied (`.NS` for India) | Data fetches fail for Indian tickers | `DataService` or `YFinanceProvider._resolve_ticker()` |
| Macro calendar US-only (FOMC/NFP/CPI) | India shows no macro events | `macro/calendar.py` — conditional event loading |
| `market` param not threaded through services | No market-specific thresholds | `RegimeService`, `TechnicalService`, `OpportunityService` constructors |
| BlackSwanService hardcodes `^VIX` | India alerts use wrong volatility | Use `market_def.stress_vix_ticker` |
| No holiday calendars per market | Cache staleness wrong on NSE holidays | `ParquetCache` needs market-aware holiday logic |
| ORB hardcodes market_close=16:00 | Wrong for India (15:30) | Read from `market_def.market_close` |
| Option expiry structure US-only | India has different weekly expiry rules | Opportunity assessors need market-aware expiry logic |

**Adding a new market:**
1. Add `MarketDef` entry in `config/defaults.yaml` under `markets`
2. Add macro dates file in `macro/` (like `_rbi_dates.py`)
3. Wire macro dates into `macro/calendar.py` conditional on market
4. Add ticker alias mapping if needed (like `_YFINANCE_ALIASES`)
5. Add holiday calendar for cache staleness logic

### SaaS Caller Contract (eTrading)

eTrading is responsible for:

| Responsibility | How |
|----------------|-----|
| **Tenant authentication** | eTrading authenticates with broker per-tenant, passes SDK sessions via `connect_from_sessions()` |
| **Tenant-scoped cache** | eTrading creates `ParquetCache(cache_dir=tenant_path)` and passes to `DataService(cache=...)` |
| **Tenant-scoped config** | eTrading creates `Settings(...)` directly (not via `get_settings()` singleton) and passes to services |
| **Broker lifecycle** | eTrading owns connect/disconnect. `ExternalBrokerSession` is a thin wrapper, not a lifecycle manager |
| **Request isolation** | eTrading creates `MarketAnalyzer()` per request (or per tenant session). Never shares across tenants |
| **Credential storage** | eTrading stores broker credentials securely. market_analyzer never persists credentials |
| **Rate limiting** | eTrading manages API rate limits for yfinance/broker per tenant |

market_analyzer is responsible for:

| Responsibility | How |
|----------------|-----|
| **Computation** | Pure analysis: regime detection, technicals, opportunity assessment, ranking |
| **Data fetching** | Fetch via providers when asked, but caller controls cache layer |
| **No side effects** | No writes to shared state, no credential reads in SaaS mode |
| **Graceful degradation** | Works without broker (returns None for live data). Works without cache (fetches fresh) |

---

## SaaS Readiness Gap Analysis (2026-03-12)

Comprehensive audit of market_analyzer fitness for deployment inside eTrading SaaS. Organized by category with priority for remediation.

### GAP-1: Statelessness Violations (Module-Level Mutable State)

market_analyzer must be stateless — no global caches, no singletons, no mutable module state. The SaaS app (eTrading) owns all state.

| ID | Location | Variable | What it holds | Priority | Fix |
|----|----------|----------|---------------|----------|-----|
| S1 | `config/__init__.py:549` | `_cached_settings` | Singleton Settings | HIGH | Accept `Settings` via constructor; remove global |
| S2 | `fundamentals/fetch.py:28` | `_cache` | Per-ticker fundamentals dict | HIGH | Move to caller-owned cache or param |
| S3 | `macro/calendar.py:100` | `_ALL_EVENTS` | Lazy-built macro list | LOW | Build fresh per call (cheap) or accept as param |
| S4 | `broker/tastytrade/market_data.py:28` | `_thread_pool` | 2-worker ThreadPoolExecutor | HIGH | Per-instance or injected executor |
| S5 | `broker/tastytrade/market_data.py:349` | `_loop_lock` | Class-level Lock | HIGH | Make instance-level |
| S6 | `service/regime_service.py` | `self._trainers` | In-memory HMM model cache | MEDIUM | Flush per request or inject model store |
| S7 | `service/ranking.py:363` | feedback parquet | Writes to `~/.market_analyzer/feedback/` | LOW | Accept feedback dir as param |

### GAP-2: Hardcoded Paths (No Tenant Isolation)

All paths default to `~/.market_analyzer/`. In SaaS, multiple tenants share the same process — these paths collide.

| ID | Location | Path | Configurable? | Priority | Fix |
|----|----------|------|---------------|----------|-----|
| P1 | `data/cache/parquet_cache.py:32` | `~/.market_analyzer/cache/` | Partial (`cache_dir` param exists) | MEDIUM | Always require explicit `cache_dir` in SaaS |
| P2 | `service/regime_service.py:57` | `~/.market_analyzer/models/` | Partial (`model_dir` config) | MEDIUM | Same — explicit path |
| P3 | `config/__init__.py:546` | `~/.market_analyzer/config.yaml` | Partial (`user_config_path` param) | MEDIUM | In SaaS, pass `Settings` directly, skip YAML |
| P4 | `service/ranking.py:363` | `~/.market_analyzer/feedback/` | **No** | LOW | Add `feedback_dir` to config |
| P5 | `broker/tastytrade/session.py:236` | `~/.market_analyzer/*.yaml` | Partial (`config_path` param) | LOW | Not used in SaaS (Mode 2 skips this) |
| P6 | `cli/_broker.py:44` | `~/PythonProjects/eTrading/.env` | **No** | LOW | CLI-only, not used in SaaS |

### GAP-3: Thread Safety & Async (SaaS/FastAPI Incompatible)

The broker layer mixes sync/async patterns that are unsafe in concurrent server environments.

| ID | Location | Pattern | Severity | Impact |
|----|----------|---------|----------|--------|
| A1 | `market_data.py:28` | Global `ThreadPoolExecutor(max_workers=2)` | CRITICAL | 2 workers for all tenants — bottleneck, timeout cascades |
| A2 | `market_data.py:349` | Class-level `_loop_lock = threading.Lock()` | CRITICAL | All instances serialize on one lock — deadlocks under load |
| A3 | `market_data.py:65`, `metrics.py:33`, `session.py:101` | Direct `asyncio.run()` calls | CRITICAL | Crashes in FastAPI (can't nest `asyncio.run()` in running loop) |
| A4 | `market_data.py:206,277,316` | `asyncio.get_event_loop().time()` in async code | HIGH | Should use `asyncio.get_running_loop()` |
| A5 | `market_data.py:373` | `asyncio.new_event_loop()` stored on instance | HIGH | Thread-affinity violations in worker pools |
| A6 | `market_data.py:206-347` | Spin-loops (10/5/15s) waiting for DXLink snapshots | MEDIUM | Blocks event loop, slows concurrent requests |

**Current state:** Broker integration works for **standalone CLI**. For SaaS, the async layer needs redesign — either fully async public API or properly isolated sync wrappers.

### GAP-4: Multi-Market Execution (Config Exists, Wiring Incomplete)

`MarketDef` and `MarketSettings` are fully defined in config. The `market` param only flows through `MarketContextService` — 15+ other services ignore it.

| ID | Gap | Where | Impact | Priority |
|----|-----|-------|--------|----------|
| M1 | Ticker suffix (`.NS`) never applied | `DataService`, `YFinanceProvider._resolve_ticker()` | India data fetches return wrong ticker | HIGH |
| M2 | BlackSwanService hardcodes `^VIX` | `service/black_swan.py:54` | India alerts use wrong volatility index | HIGH |
| M3 | Macro calendar returns all events | `macro/calendar.py` | India user sees FOMC, US user sees RBI | MEDIUM |
| M4 | RBI MPC dates defined but dormant | `macro/_rbi_dates.py` | India market has no monetary policy events | MEDIUM |
| M5 | ORB hardcodes `market_close=16:00` | `features/patterns/orb.py:52-59` | Wrong for India (15:30) | MEDIUM |
| M6 | `market` not threaded through services | 15+ services in `service/` | Can't apply market-specific thresholds | MEDIUM |
| M7 | No holiday calendars per market | `ParquetCache` staleness logic | Cache marked stale on NSE holidays | LOW |
| M8 | Option expiry structure US-only | Opportunity assessors | India weeklies have different patterns | LOW |

### GAP-5: Multi-Broker (Architecture Ready, CLI Needs Selection)

Broker ABCs are clean and broker-agnostic. All services use ABCs, never concrete types. Only one implementation exists (TastyTrade).

| ID | Gap | Where | Priority |
|----|-----|-------|----------|
| B1 | CLI hardcoded to TastyTrade | `cli/_broker.py:52-59` | LOW (until second broker added) |
| B2 | `BrokerSettings.credentials_path` defaults to tastytrade | `config/__init__.py:498` | LOW |
| B3 | No Schwab/IBKR implementations | `broker/` | FUTURE (implement when needed) |

**Not a gap:** Service layer, models, opportunity assessors, adjustment service — all broker-agnostic already.

### GAP-6: Data Transparency (Partially Fixed 2026-03-12)

| ID | Gap | Status | Notes |
|----|-----|--------|-------|
| D1 | Plan generates full results when DXLink is down | **FIXED** | Added `data_warnings` to `DailyTradingPlan`, surfaced in CLI |
| D2 | DXLink errors logged at WARNING, never bubbled | OPEN | Services silently degrade — caller doesn't know data quality |
| D3 | `max_entry_price=None` without explanation | **FIXED** | Warning now explains "DXLink streaming may be down" |
| D4 | No data freshness indicator on plan output | OPEN | Should show cache age for each ticker's OHLCV |

### GAP-7: Cache Concurrency (Single-User Assumptions)

| ID | Gap | Where | Priority |
|----|-----|-------|----------|
| C1 | `_meta.json` read-modify-write race | `parquet_cache.py:47-76` | MEDIUM (concurrent writes corrupt meta) |
| C2 | No file locking on cache writes | `parquet_cache.py:93-112` | MEDIUM (parquet writes are atomic, meta is not) |

### Remediation Priority Order

**Phase 1 — Must fix before SaaS launch:**
1. A3: Replace `asyncio.run()` with `iscoroutine` guards (partially done — session.py:101 done, market_data.py:65 and metrics.py:33 done)
2. S1: Make `get_settings()` non-singleton (accept Settings via constructor)
3. S2: Remove global `_cache` in fundamentals
4. D1: Data warnings on plan (**done**)

**Phase 2 — Fix for production quality:**
5. A1+A2: Redesign `_run_async()` — per-instance lock, configurable thread pool
6. M1: Apply market ticker suffix in DataService/yfinance
7. M2: Use `market_def.stress_vix_ticker` in BlackSwanService
8. P1-P3: Require explicit paths in SaaS mode (constructor enforcement)
9. S4+S5: Per-instance thread pool and lock

**Phase 3 — Complete multi-market:**
10. M3+M4: Market-aware macro calendar
11. M5: Market-aware ORB hours
12. M6: Thread `market` through all services
13. M7+M8: Holiday calendars and expiry patterns

**Phase 4 — Future:**
14. B1-B3: Multi-broker CLI selection (when second broker needed)
15. C1-C2: Cache concurrency (when serving concurrent users)
16. A4-A6: Full async redesign of broker layer

---

## Option Chain & Real-Time Market Data Architecture

### Overview

All real-time option and market data flows through the `broker/tastytrade/` sub-package. This is the **only** path for live data — no Black-Scholes, no theoretical pricing, no hardcoded values.

```
broker/tastytrade/
├── __init__.py       # connect_tastytrade(), connect_from_sessions()
├── _async.py         # run_sync() — async-to-sync bridge (persistent event loop)
├── session.py        # TastyTradeBrokerSession, ExternalBrokerSession
├── market_data.py    # TastyTradeMarketData (MarketDataProvider ABC)
├── metrics.py        # TastyTradeMetrics (MarketMetricsProvider ABC)
├── account.py        # TastyTradeAccount (AccountProvider ABC)
├── dxlink.py         # Low-level DXLink fetch utilities (quotes, Greeks, candles)
└── symbols.py        # Streamer symbol conversion (build, parse, OCC↔DXLink)
```

### Two Connection Modes

| Mode | Who authenticates | Entry point | Used by |
|------|-------------------|-------------|---------|
| **Standalone** | market_analyzer CLI | `connect_tastytrade()` | analyzer-cli, analyzer-explore |
| **SaaS (embedded)** | eTrading | `connect_from_sessions(sdk_session, data_session)` | cotrader, API endpoints |

Both return a 3-tuple: `(TastyTradeMarketData, TastyTradeMetrics, TastyTradeAccount)`.

### DXLink Data Flow

```
Caller → MarketDataProvider ABC
  → TastyTradeMarketData (market_data.py)
    → dxlink.fetch_quotes()      # bid/ask via DXQuote events
    → dxlink.fetch_greeks()      # delta/gamma/theta/vega via DXGreeks events
    → dxlink.fetch_candles()     # intraday OHLCV via Candle events
    → dxlink.fetch_underlying_price()  # equity mid via DXQuote
    → dxlink.fetch_option_chain_symbols()  # NestedOptionChain → streamer symbols
    All via _async.run_sync() → persistent event loop
```

### DXLink Timeouts (aligned with eTrading)

| Data type | Total timeout | Per-event timeout | Notes |
|-----------|--------------|-------------------|-------|
| Quotes (bid/ask) | 3s | 0.5s | Fast — just price levels |
| Greeks | 15s | 2s | Slower — computed server-side |
| Underlying price | 5s | 5s | Single event |
| Intraday candles | 10s | 2s | Snapshot collection |

### Streamer Symbol Format

DXLink uses `.{TICKER}{YYMMDD}{C|P}{STRIKE}` (e.g., `.SPY260320P580`).

Utilities in `symbols.py`:
- `build_streamer_symbol(ticker, exp, type, strike)` → `.SPY260320P580`
- `parse_streamer_symbol(".SPY260320P580")` → `ParsedSymbol(ticker, exp, type, strike)`
- `leg_to_streamer_symbol(ticker, leg)` → streamer symbol from LegSpec
- `occ_to_streamer()` / `streamer_to_occ()` — OCC ↔ DXLink conversion

### Error Classification

`dxlink.classify_error(exc)` returns `DXLinkError`:
- `GRANT_REVOKED` — token expired, need re-auth
- `TIMEOUT` — no data within deadline
- `CONNECTION_FAILED` — WebSocket/network issue
- `NO_DATA` — connected but no events
- `UNKNOWN` — unrecognized error

### Quote Caching (OptionQuoteService)

`service/option_quotes.py` caches quotes at the leg level:
- Key: `strike|type|expiration` (e.g., `580.00|put|2026-03-20`)
- `prefetch_leg_quotes(all_legs)` — batch fetch + dedup before plan iteration
- `clear_cache()` — reset between plan runs
- Eliminates duplicate DXLink connections for same ticker across strategies

### Option Chain via NestedOptionChain (SDK v12)

SDK v12 removed `Option.get_option_chain()`. We use `NestedOptionChain.get()`:
```python
chains = NestedOptionChain.get(session, ticker)
for chain in chains:
    for exp in chain.expirations:
        for strike in exp.strikes:
            # strike.call_streamer_symbol → ".SPY260320C580"
            # strike.put_streamer_symbol → ".SPY260320P580"
```
Then DXLink fetches live bid/ask and Greeks for those symbols.

### run_sync() — Async Bridge

`_async.py` provides `run_sync(coro, timeout)` for calling async DXLink code from sync contexts:
- **CLI/standalone**: Uses persistent event loop with `loop.run_until_complete()`
- **FastAPI/SaaS**: Detects running loop, submits to thread pool with `asyncio.run()`
- **Thread-safe**: Shared lock protects event loop creation
- **Prevents "Event loop is closed"**: Reuses loop instead of `asyncio.run()` which closes it

### Data Session Fallback Chain

DXLink requires a valid session. The fallback order:
1. **DATA credentials** (`TASTYTRADE_***_DATA`) — dedicated live-only session
2. **Reuse trading session** (if live, not paper)
3. **LIVE credentials** (new session from `TASTYTRADE_***_LIVE`)

Validation: opens a DXLinkStreamer, subscribes to SPY, confirms one quote arrives.

---

## Change Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-02-21 | Initial design doc | Established 4-state HMM, per-instrument regime, income-first bias |
| 2026-02-21 | Package structure defined | models/, features/, hmm/, service/, data/ modules |
| 2026-02-21 | yfinance as optional dependency | Core library must work with caller-provided DataFrames |
| 2026-02-21 | Label alignment via vol+trend axes | 2x2 sorting maps arbitrary HMM states to R1–R4 semantically |
| 2026-02-21 | Expanded to canonical historical data service | market_analyzer owns all historical data for ecosystem; added DataService, parquet cache, three providers (yfinance, CBOE, TastyTrade); yfinance now required |
| 2026-02-23 | Trading workflow restructure | Added 6 workflow services (context, instrument, screening, entry, strategy, exit), 5 new model files, multi-market config (US + India), interactive CLI (analyzer-cli), API.md. Additive — no existing files moved, all 580 tests pass. |
| 2026-02-23 | Opportunity folder reorganized | Split opportunity/ into setups/ (breakout, momentum, mean_reversion) and option_plays/ (zero_dte, leap, earnings). Top-level __init__.py re-exports everything for backward compat. |
| 2026-03-11 | skip_intraday for plan generation | DXLink intraday candle fetches (15s/ticker) caused plan timeouts. Added `skip_intraday` flag to `rank()` and `plan.generate()`. ORB data not needed for daily plan. Also added timeout to `_run_async()` and `coro.close()` cleanup. |
| 2026-03-12 | SaaS deployment contract documented | Two broker modes (standalone vs embedded), statelessness violations cataloged, multi-broker/multi-market gaps identified. eTrading is the SaaS app; market_analyzer is stateless library. |
| 2026-03-12 | SaaS readiness gap analysis | 7 gap categories, 30+ individual items cataloged. Phased remediation plan. Fixed: DXLink data session fallback, data_warnings on DailyTradingPlan, $-prefix ticker resolution. |
| 2026-03-12 | DXLink refactoring + utilities | Extracted DXLink fetch logic into `dxlink.py` (5 async utilities + error classification). Created `symbols.py` (streamer symbol build/parse/convert). `market_data.py` now thin orchestrator. Added `AccountProvider` ABC + `TastyTradeAccount`. `connect_from_sessions` returns 3-tuple. eTrading engine.py updated. 990 tests. |
