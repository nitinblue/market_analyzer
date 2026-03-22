# Data Interfaces — How income_desk Gets Its Data

> When you install income_desk, it works out of the box with free data (yfinance). Connect a broker for real-time quotes. Or plug in your own data source.

---

## Quick Start: What Works Immediately

```bash
pip install market-analyzer
```

```python
from income_desk import MarketAnalyzer, DataService

ma = MarketAnalyzer(data_service=DataService())
regime = ma.regime.detect("SPY")      # Downloads 2yr OHLCV from yfinance, trains HMM
tech = ma.technicals.snapshot("SPY")  # RSI, ATR, Bollinger, MACD, support/resistance
```

**No credentials, no API keys, no setup.** yfinance is free and bundled. First call takes 10–30 seconds (downloading + caching). Subsequent calls are instant (parquet cache).

---

## Data Tiers

income_desk has three tiers of data, each adding more capability:

| Tier | Source | Setup | What You Get | Trust Level |
|------|--------|-------|--------------|-------------|
| **Free (default)** | yfinance | None | OHLCV, regime detection, technicals, screening, options chain structure | LOW-MEDIUM |
| **Broker** | TastyTrade / Zerodha / Dhan | Account + credentials | Real-time quotes, Greeks, IV rank, account balance, execution quality | HIGH |
| **Economic** | FRED | Free API key | Yield curve, macro indicators, tail risk assessment | Supplementary |

---

## Tier 1: Free Data (yfinance)

### What it provides
- **Historical OHLCV** — 2 years of daily bars (Open, High, Low, Close, Volume)
- **Options chain structure** — strikes, expirations, bid/ask (delayed; often stale or zero after hours)

### What it does NOT provide
- Real-time option quotes (bid/ask are delayed or zero after hours)
- Greeks (delta, gamma, theta, vega)
- IV rank, IV percentile
- Account balance or buying power

### How it works internally

```
DataService.get_ohlcv("SPY")
    → ProviderRegistry.resolve("SPY", DataType.OHLCV) → YFinanceProvider
    → ParquetCache.read("SPY", "ohlcv")
        → If fresh (< 18 hours): return cached DataFrame
        → If stale: delta-fetch (only missing dates from yfinance)
    → ParquetCache.write(merged DataFrame)
    → Return DataFrame[Open, High, Low, Close, Volume] with DatetimeIndex
```

**Cache is checked first, every time.** A stale fetch failure will raise `DataFetchError` — stale data is never silently served as current.

### DataService API

```python
from income_desk.data.service import DataService
from income_desk.models.data import DataRequest, DataType

ds = DataService()

# Convenience methods
df = ds.get_ohlcv("SPY")                        # 2yr daily OHLCV (default lookback)
df = ds.get_ohlcv("SPY", start_date=date(2024, 1, 1))  # Custom range
chain = ds.get_options_chain("SPY")             # Full options chain snapshot
iv_df = ds.get_options_iv("SPY")               # Historical IV time series

# Low-level (any DataRequest)
df, result = ds.get(DataRequest(
    ticker="SPY",
    data_type=DataType.OHLCV,
    start_date=date(2024, 1, 1),
    end_date=date(2025, 1, 1),
))
# result.provider, result.from_cache, result.row_count

# Cache management
metas = ds.cache_status("SPY")                # List[CacheMeta] for all data types
ds.invalidate_cache("SPY")                    # Force re-fetch next request
ds.invalidate_cache("SPY", DataType.OHLCV)   # Specific data type only
```

**OHLCV DataFrame schema:**
```
Index: DatetimeIndex (ascending)
Columns: Open (float), High (float), Low (float), Close (float), Volume (int)
```

**Options chain DataFrame schema** (snapshot, full refresh):
```
Index: RangeIndex
Columns: expiration (date), strike (float), option_type ("call"|"put"),
         bid (float), ask (float), last_price (float),
         volume (int), open_interest (int),
         implied_volatility (float), in_the_money (bool)
```

### Ticker aliases

MA automatically translates common tickers before passing to yfinance:

| You type | yfinance fetches | Instrument |
|----------|-----------------|------------|
| SPX | ^GSPC | S&P 500 Index |
| NDX | ^NDX | Nasdaq-100 Index |
| DJX | ^DJI | Dow Jones Industrial Average |
| RUT | ^RUT | Russell 2000 Index |
| VIX | ^VIX | CBOE Volatility Index |
| TNX | ^TNX | 10-Year Treasury Yield |
| COMP | ^IXIC | Nasdaq Composite |
| SOX | ^SOX | PHLX Semiconductor Index |
| OEX | ^OEX | S&P 100 Index |
| XSP | ^GSPC | Mini-SPX (same underlying as SPX) |
| NIFTY | ^NSEI | Nifty 50 (India) |
| BANKNIFTY | ^NSEBANK | Bank Nifty (India) |
| SENSEX | ^BSESN | BSE Sensex (India) |

Tickers prefixed with `$` (DXLink style — `$SPX`) are also resolved correctly.

### Cache behavior

- **Location:** `~/.income_desk/cache/` (legacy: `~/.market_regime/cache/`)
- **OHLCV staleness:** 18 hours (configurable via `settings.yaml`)
- **Options chain staleness:** 4 hours (snapshot, always full refresh — no delta-fetch)
- **Weekend awareness:** If today is Saturday or Sunday and last cached date is the most recent Friday, OHLCV data is considered fresh. (Options chain does not apply weekend logic.)
- **Delta-fetch:** On stale OHLCV, only the missing date range is downloaded and appended. If cache start date is more than 5 days after the requested start, a full re-fetch is triggered instead.
- **Atomic writes:** Cache writes use temp file + `os.replace()` — no partial writes.

---

## Tier 2: Broker Data (Real-Time)

### Supported Brokers

| Broker | Status | Market | Install |
|--------|--------|--------|---------|
| **TastyTrade** | Fully implemented | US options (DXLink streaming) | `pip install "market-analyzer[tastytrade]"` |
| **Zerodha** | Fully implemented | India NSE/NFO (Kite REST API) | `pip install "market-analyzer[zerodha]"` |
| **Dhan** | Stub (not yet implemented) | India NSE/BSE | — |
| **Your broker** | Implement ABCs below | Any | See "Adding Your Own Broker" |

### TastyTrade Setup

```bash
pip install "market-analyzer[tastytrade]"
```

**Option A — Standalone (credentials from YAML):**

```bash
# Copy template and fill in values (or use env vars)
cp tastytrade_broker.yaml.template tastytrade_broker.yaml
```

```yaml
# tastytrade_broker.yaml
broker:
  live:
    client_secret: ${TT_LIVE_SECRET}
    refresh_token: ${TT_LIVE_TOKEN}
  paper:
    client_secret: ${TT_PAPER_SECRET}
    refresh_token: ${TT_PAPER_TOKEN}
```

Credential files are searched in order:
1. `./tastytrade_broker.yaml`
2. `~/.income_desk/tastytrade_broker.yaml`
3. Relative to the broker package directory

```python
from income_desk.broker.tastytrade import connect_tastytrade
from income_desk import MarketAnalyzer, DataService

md, mm, acct, wl = connect_tastytrade(is_paper=False)
ma = MarketAnalyzer(
    data_service=DataService(),
    market_data=md,            # DXLink real-time quotes + Greeks
    market_metrics=mm,         # IV rank, IV percentile, beta
    account_provider=acct,     # Balance, buying power
    watchlist_provider=wl,     # Broker watchlists
)
```

**Option B — SaaS / eTrading (pre-authenticated sessions):**

```python
from income_desk.broker.tastytrade import connect_from_sessions

# sdk_session: authenticated tastytrade.Session (REST API)
# data_session: authenticated tastytrade.Session (DXLink streaming)
md, mm, acct, wl = connect_from_sessions(sdk_session, data_session)
```

Use this pattern when the calling platform owns authentication and passes sessions to MA.
MA never handles credentials in this mode.

### Zerodha Setup

```bash
pip install "market-analyzer[zerodha]"
```

**Option A — Standalone:**

```python
from income_desk.broker.zerodha import connect_zerodha
md, mm, acct, wl = connect_zerodha(api_key="...", access_token="...")
ma = MarketAnalyzer(
    data_service=DataService(),
    market="India",            # Required: configures lot sizes, expiry conventions
    market_data=md,
    market_metrics=mm,
    account_provider=acct,
    watchlist_provider=wl,
)
```

Access tokens expire daily. See `zerodha_credentials.yaml.template` for the OAuth refresh flow.

**Option B — SaaS / eTrading:**

```python
from income_desk.broker.zerodha import connect_zerodha_from_session

# session: pre-authenticated KiteConnect instance
md, mm, acct, wl = connect_zerodha_from_session(session)
```

### What broker data enables

| Feature | Without Broker | With Broker |
|---------|---------------|-------------|
| Regime detection | Works (yfinance OHLCV) | Same |
| Technicals (RSI, ATR, etc.) | Works | Same |
| Options chain structure | yfinance (delayed) | Real-time DXLink |
| Option quotes (bid/ask/mid) | Stale/zero | Real-time from broker |
| Greeks (delta, gamma, theta, vega) | None | Real from broker |
| IV rank / IV percentile | None | From broker REST API |
| Underlying real-time price | None | Real mid from broker |
| Intraday candles (ORB, 0DTE) | None | 5-minute DXLink bars |
| POP estimate | Approximate (ATR-based) | IV-rank calibrated |
| Position monitoring P&L | None | Real mid prices |
| Account balance / buying power | None | Real from broker |
| Broker watchlists | None | Broker-managed lists |
| Fit for | Screening, research | Live execution |

### MarketAnalyzer constructor (full signature)

```python
MarketAnalyzer(
    data_service: DataService | None = None,
    config: RegimeConfig = RegimeConfig(),
    market: str | None = None,              # "US" (default) or "India"
    market_data: MarketDataProvider | None = None,
    market_metrics: MarketMetricsProvider | None = None,
    account_provider: AccountProvider | None = None,
    watchlist_provider: WatchlistProvider | None = None,
)
```

All broker arguments are optional. Any omitted component degrades gracefully — no errors, reduced capability.

---

## Tier 3: Economic Data (FRED)

```bash
pip install "market-analyzer[fred]"
export FRED_API_KEY=your_free_key_from_fred.stlouisfed.org
```

Used exclusively by `BlackSwanService` for yield curve inversion and macro stress indicators.
Without it, those specific checks are skipped — all other analysis still runs.

`FREDFetcher.available` returns `False` silently if the package is not installed or `FRED_API_KEY` is unset. There are no errors.

---

## The 5 Broker Interfaces (ABCs)

Every broker implements up to 5 abstract classes, all in `income_desk/broker/base.py`. You only need to implement what you intend to use — the others can be omitted.

### 1. `MarketDataProvider` — Live Quotes, Greeks, Intraday

```python
class MarketDataProvider(ABC):

    # --- REQUIRED ---

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """'tastytrade', 'schwab', 'zerodha', etc."""

    @abstractmethod
    def get_option_chain(
        self, ticker: str, expiration: date | None = None
    ) -> list[OptionQuote]:
        """Full option chain with bid/ask/IV. None = all expirations."""

    @abstractmethod
    def get_quotes(
        self,
        legs: list[LegSpec],
        *,
        ticker: str = "",
        include_greeks: bool = True,
    ) -> list[OptionQuote]:
        """Quotes for specific option legs (strike + expiration + type)."""

    @abstractmethod
    def get_greeks(self, legs: list[LegSpec]) -> dict[str, dict]:
        """Greeks for specific legs. Returns {leg_key: {delta, gamma, theta, vega}}."""

    # --- OPTIONAL (default no-ops) ---

    def get_intraday_candles(self, ticker: str, interval: str = "5m") -> pd.DataFrame:
        """Today's intraday OHLCV bars. Returns empty DataFrame if not supported."""
        return pd.DataFrame()

    def get_underlying_price(self, ticker: str) -> float | None:
        """Real-time mid price of the underlying. None if not supported."""
        return None

    def get_quotes_batch(
        self,
        ticker_legs: list[tuple[str, list]],
        *,
        include_greeks: bool = False,
    ) -> dict[str, list[OptionQuote]]:
        """Batch quotes across multiple tickers. Default: calls get_quotes() per ticker."""
        ...

    def is_token_valid(self) -> bool:
        """Session token still valid? Default: True."""
        return True

    # --- MARKET PROPERTIES (override per-broker / per-market) ---

    @property
    def rate_limit_per_second(self) -> int: return 10

    @property
    def supports_batch(self) -> bool: return False

    @property
    def currency(self) -> str: return "USD"

    @property
    def timezone(self) -> str: return "US/Eastern"

    @property
    def market_hours(self) -> tuple: return (time(9, 30), time(16, 0))

    @property
    def lot_size_default(self) -> int: return 100
```

### 2. `MarketMetricsProvider` — IV Rank, Beta, Liquidity

```python
class MarketMetricsProvider(ABC):

    @abstractmethod
    def get_metrics(self, tickers: list[str]) -> dict[str, MarketMetrics]:
        """IV rank, IV percentile, beta, liquidity per ticker.

        Returns:
            {ticker: MarketMetrics} — missing tickers simply absent from dict.
        """
```

`MarketMetrics` fields (all optional — return `None` for unavailable):

```python
class MarketMetrics(BaseModel):
    ticker: str
    iv_rank: float | None         # 0–100: current IV vs 52-week range
    iv_percentile: float | None   # 0–100: % of time IV was lower
    iv_index: float | None        # Current IV index value
    iv_30_day: float | None       # 30-day implied volatility
    hv_30_day: float | None       # 30-day historical volatility
    hv_60_day: float | None       # 60-day historical volatility
    beta: float | None            # Beta vs SPY
    corr_spy: float | None        # Correlation with SPY
    liquidity_rating: float | None  # 1–5 scale
    earnings_date: date | None
```

### 3. `AccountProvider` — Balance and Buying Power

```python
class AccountProvider(ABC):

    @abstractmethod
    def get_balance(self) -> AccountBalance:
        """Current account balance (NLV, buying power, margin in use)."""
```

`AccountBalance` fields:

```python
class AccountBalance(BaseModel):
    account_number: str
    net_liquidating_value: float     # Total account value
    cash_balance: float
    derivative_buying_power: float   # Options buying power (use this for sizing)
    equity_buying_power: float       # Stock buying power
    maintenance_requirement: float   # Margin currently in use
    pending_cash: float = 0.0
    source: str = ""                 # "tastytrade", "zerodha", etc.
    currency: str = "USD"
    timezone: str = "US/Eastern"
```

### 4. `WatchlistProvider` — Broker-Managed Ticker Lists

```python
class WatchlistProvider(ABC):

    @abstractmethod
    def get_watchlist(self, name: str) -> list[str]:
        """Tickers from a named watchlist. Returns [] if not found."""

    @abstractmethod
    def list_watchlists(self) -> list[str]:
        """All available watchlist names (private + public)."""

    # Optional
    def create_watchlist(self, name: str, tickers: list[str]) -> bool:
        """Create or update a watchlist. Returns True on success."""
        return False  # Default: not supported

    def get_all_equities(
        self,
        is_etf: bool | None = None,
        is_index: bool | None = None,
    ) -> list[dict]:
        """All tradeable instruments. Returns [{symbol, is_etf, is_index, description}].
        Default: not supported (returns []).
        """
        return []
```

### 5. `BrokerSession` — Authentication Lifecycle

```python
class BrokerSession(ABC):

    @abstractmethod
    def connect(self) -> bool:
        """Authenticate and establish session. Returns True on success."""

    @abstractmethod
    def disconnect(self) -> None:
        """Clean up session resources."""

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """'tastytrade', 'schwab', 'zerodha', etc."""

    def is_token_valid(self) -> bool:
        """Token still valid? Default: True."""
        return True
```

**Note:** `BrokerSession` is used internally by provider implementations. When using `connect_tastytrade()` or `connect_zerodha()`, you never instantiate `BrokerSession` directly — the connect functions handle auth and return the four providers.

---

## Typed Exceptions

The data layer raises typed exceptions so callers can handle failures explicitly.

```python
from income_desk.data.exceptions import (
    DataFetchError,      # Provider network/API failure
    InvalidTickerError,  # Ticker not recognized by provider
    CacheError,          # Cache read/write failure
    NoProviderError,     # No provider registered for the requested DataType
)
```

```python
# DataFetchError carries structured context
try:
    df = ds.get_ohlcv("BADTICKER")
except DataFetchError as e:
    print(e.provider)  # "yfinance"
    print(e.ticker)    # "BADTICKER"
    print(str(e))      # "[yfinance] Failed to fetch BADTICKER: ..."
```

**"No data exists" vs "fetch failed" are distinct.** `InvalidTickerError` means the ticker is not valid. `DataFetchError` means the ticker may be valid but the fetch failed (network, rate limit, etc.).

---

## Adding Your Own Data Source

### Option A: Historical Data Provider (OHLCV or chain structure)

Use this for Polygon, Alpha Vantage, local files, or any source that returns historical time-series data.

```python
from income_desk.data.providers.base import DataProvider
from income_desk.models.data import DataRequest, DataType, ProviderType
import pandas as pd

class PolygonProvider(DataProvider):

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.YFINANCE  # Reuse an existing ProviderType, or extend the enum

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.OHLCV]

    def fetch(self, request: DataRequest) -> pd.DataFrame:
        # Must return DataFrame with:
        #   Index: DatetimeIndex (ascending, no timezone)
        #   Columns: Open, High, Low, Close, Volume (float/int)
        # Raise DataFetchError on failure. Never return an empty DataFrame.
        ...

    def validate_ticker(self, ticker: str) -> bool:
        # Return True if ticker is valid for this provider
        ...


# Register alongside default providers
from income_desk import DataService
from income_desk.data.registry import ProviderRegistry
from income_desk.data.cache.parquet_cache import ParquetCache

registry = ProviderRegistry()
registry.register(PolygonProvider())
ds = DataService(registry=registry)
ma = MarketAnalyzer(data_service=ds)
```

`ProviderRegistry.resolve()` returns the first registered provider that supports the requested `DataType`. Register your provider before the default yfinance provider if you want it to take precedence.

### Option B: New Broker Integration

For adding Schwab, IBKR, Webull, or any other broker:

```python
from income_desk.broker.base import MarketDataProvider
from income_desk.models.quotes import OptionQuote
from datetime import date
import pandas as pd

class SchwabMarketData(MarketDataProvider):

    @property
    def provider_name(self) -> str:
        return "schwab"

    def get_option_chain(
        self, ticker: str, expiration: date | None = None
    ) -> list[OptionQuote]:
        # Call Schwab API, return list[OptionQuote]
        ...

    def get_quotes(
        self, legs, *, ticker: str = "", include_greeks: bool = True
    ) -> list[OptionQuote]:
        ...

    def get_greeks(self, legs) -> dict[str, dict]:
        ...

    # Optional: override for real-time underlying price
    def get_underlying_price(self, ticker: str) -> float | None:
        ...

    # Optional: override for intraday bars (ORB, 0DTE)
    def get_intraday_candles(self, ticker: str, interval: str = "5m") -> pd.DataFrame:
        ...


ma = MarketAnalyzer(
    data_service=DataService(),
    market_data=SchwabMarketData(...),
)
```

Only `get_option_chain`, `get_quotes`, `get_greeks`, and `provider_name` are required. All other methods have working defaults.

### Option C: Local Data (CSV or Parquet files)

For research, backtesting, or replaying saved data:

```python
from pathlib import Path
from income_desk.data.providers.base import DataProvider
from income_desk.models.data import DataRequest, DataType, ProviderType
from income_desk.data.exceptions import DataFetchError, InvalidTickerError
import pandas as pd

class LocalCSVProvider(DataProvider):

    def __init__(self, data_dir: str) -> None:
        self._dir = Path(data_dir)

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.YFINANCE  # Reuse; ProviderType is just metadata

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.OHLCV]

    def fetch(self, request: DataRequest) -> pd.DataFrame:
        path = self._dir / f"{request.ticker.upper()}.csv"
        if not path.exists():
            raise InvalidTickerError("local_csv", request.ticker)
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            df.index = pd.DatetimeIndex(df.index)
            df.sort_index(inplace=True)
            return df[["Open", "High", "Low", "Close", "Volume"]]
        except Exception as e:
            raise DataFetchError("local_csv", request.ticker, str(e)) from e

    def validate_ticker(self, ticker: str) -> bool:
        return (self._dir / f"{ticker.upper()}.csv").exists()


# Usage
registry = ProviderRegistry()
registry.register(LocalCSVProvider("/path/to/csvs"))
ds = DataService(registry=registry)
```

---

## Data Flow Summary

```
                    ┌──────────────┐
                    │  Your Code   │
                    └──────┬───────┘
                           │
                    ┌──────▼────────┐
                    │ MarketAnalyzer │   Single entry point
                    └──────┬────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
     ┌────────▼───┐  ┌─────▼─────┐  ┌──▼────────────┐
     │ DataService │  │QuoteService│  │Other Services  │
     │ (historical)│  │(live)      │  │(regime, tech,  │
     └─────┬───────┘  └─────┬─────┘  │ macro, levels) │
           │               │         └────────────────┘
     ┌─────▼─────┐   ┌─────▼──────┐
     │  Parquet   │   │  Broker    │
     │  Cache     │   │(MarketData,│
     │            │   │ Metrics,   │
     └─────┬─────┘   │ Account,   │
           │         │ Watchlist) │
     ┌─────▼─────┐   └─────┬──────┘
     │ yfinance  │         │
     │ (free,    │   ┌─────▼──────────────┐
     │  default) │   │ TastyTrade (DXLink) │
     └───────────┘   │ Zerodha (Kite REST) │
                     │ Dhan (stub)         │
                     │ Your broker (ABCs)  │
                     └────────────────────┘
```

**OptionQuoteService** (`ma.quotes`) is the runtime bridge between `DataService` and broker providers. It:
- Serves broker quotes when a `MarketDataProvider` is wired in
- Falls back to yfinance chain data for structure (strikes/expirations) only — never for bid/ask or Greeks
- Maintains a 60-second TTL cache per leg (prevents redundant DXLink connections)
- Uses a circuit breaker: after 3 consecutive failures, broker calls are suspended for 60 seconds to prevent cascading failures

---

## Configuration

Settings are loaded from `~/.income_desk/settings.yaml` (optional). All defaults work without a config file.

```yaml
# ~/.income_desk/settings.yaml

cache:
  staleness_hours: 18.0        # OHLCV cache max age before re-fetch
  cache_dir: null              # Default: ~/.income_desk/cache/
  model_dir: null              # Default: ~/.income_desk/models/
```

The `CacheSettings` class (from `income_desk.config`):

```python
class CacheSettings(BaseModel):
    staleness_hours: float = 18.0
    cache_dir: str | None = None   # None → ~/.income_desk/cache/
    model_dir: str | None = None   # None → ~/.income_desk/models/
```

You can also pass a custom `ParquetCache` directly to `DataService`:

```python
from income_desk.data.cache.parquet_cache import ParquetCache

cache = ParquetCache(
    cache_dir=Path("/custom/cache/path"),
    staleness_hours=6.0,
)
ds = DataService(cache=cache)
```

---

## Available Data Types

`DataType` (from `income_desk.models.data`):

| Value | Description | Provider | Cache strategy |
|-------|-------------|----------|----------------|
| `ohlcv` | Daily Open/High/Low/Close/Volume | yfinance | Delta-fetch (append only) |
| `options_chain` | Full options chain snapshot | yfinance | Full refresh every 4 hours |
| `options_iv` | Historical implied volatility time-series | CBOE (stub) | Delta-fetch |
| `broker_history` | Broker trade history | TastyTrade (stub) | Delta-fetch |

`options_iv` and `broker_history` providers are stubs (`NotImplementedError`). They define the interface for future implementation.
