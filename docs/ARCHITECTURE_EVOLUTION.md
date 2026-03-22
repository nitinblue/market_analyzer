# income-desk — Architecture Evolution Plan

> How the project structure should evolve from "market_analyzer with everything flat" to "income-desk with clean domain boundaries."

---

## Current Architecture (v0.3.x)

```
market_analyzer/                    # Python module (mismatched with package name)
├── models/                         # 15 model files (mixed domains)
│   ├── opportunity.py              # TradeSpec, LegSpec, assessor results
│   ├── regime.py                   # RegimeResult
│   ├── technicals.py               # TechnicalSnapshot
│   ├── levels.py                   # Support/resistance
│   ├── ranking.py                  # RankedEntry
│   ├── exit.py                     # RegimeStop, MonitoringAction
│   ├── entry.py                    # EntryLevelScore, IVRankQuality
│   ├── portfolio.py                # DeskSpec, AssetAllocation
│   ├── assignment.py               # AssignmentAnalysis, CSP
│   ├── decision_audit.py           # DecisionReport
│   ├── sentinel.py                 # SentinelReport
│   ├── transparency.py             # DataTrust, TrustReport
│   ├── quotes.py                   # OptionQuote, AccountBalance
│   ├── vol_surface.py              # VolatilitySurface
│   └── ...
├── features/                       # 10 pure function modules (mixed domains)
│   ├── entry_levels.py             # Entry intelligence
│   ├── exit_intelligence.py        # Exit intelligence
│   ├── position_sizing.py          # Kelly, correlation, margin
│   ├── desk_management.py          # Desk allocation
│   ├── decision_audit.py           # 4-level audit
│   ├── crash_sentinel.py           # Market health
│   ├── data_trust.py               # Trust framework
│   ├── dte_optimizer.py            # DTE selection
│   ├── rate_risk.py                # Interest rate risk
│   └── assignment_handler.py       # Assignment workflows
├── service/                        # Service orchestrators
├── opportunity/                    # Trade assessors
├── validation/                     # Profitability gates
├── broker/                         # 6 brokers
├── adapters/                       # CSV, dict, simulation
├── data/                           # Data fetching + caching
├── cli/                            # Interactive CLI
├── demo/                           # Demo portfolio + trader
├── risk.py                         # Portfolio risk (single file!)
├── hedging.py                      # Same-ticker hedging (thin!)
├── trade_lifecycle.py              # 10 lifecycle functions (too big!)
└── ... 20+ more top-level files
```

### Problems
1. `risk.py` is ONE file for all risk — portfolio risk, stress testing, drawdown, greeks limits
2. `hedging.py` is thin — same-ticker only, no India beta-adjusted, no collars, no proxy hedging
3. `trade_lifecycle.py` is 1600+ lines — POP, filters, monitoring, overnight, all mixed together
4. Models are grouped by file, not by domain — `exit.py` and `entry.py` are in the same folder
5. No clear "hedging domain" — it's scattered across risk.py, hedging.py, features/

---

## Target Architecture (v1.0)

### Phase 1: Create Domain Facades (non-breaking)

Add a new top-level `income_desk` module that re-exports everything through clean domain APIs. The old `market_analyzer` module stays as-is for backward compatibility.

```python
# New: income_desk/__init__.py
from income_desk.desk import TradingDesk

# income_desk/desk.py
class TradingDesk:
    """The primary API for income-desk users."""

    def __init__(self, capital=100_000, market="US", risk_tolerance="moderate"):
        from market_analyzer import MarketAnalyzer, DataService
        self._ma = MarketAnalyzer(data_service=DataService())
        self.markets = MarketsAPI(self._ma)
        self.trading = TradingAPI(self._ma)
        self.risk = RiskAPI(self._ma)
        self.portfolio = PortfolioAPI(self._ma, capital, risk_tolerance, market)
        self.monitoring = MonitoringAPI(self._ma)
        self.trust = TrustAPI(self._ma)

    def connect(self, broker="auto"):
        """Connect to broker."""
        ...
```

This way:
- `from income_desk import TradingDesk` works for new users
- `from market_analyzer import MarketAnalyzer` still works for existing users / eTrading
- No breaking changes

### Phase 2: Domain Packages (within market_analyzer)

Split the big files into domain packages without changing the top-level module name:

```
market_analyzer/
├── risk/                           # EXPAND from risk.py
│   ├── __init__.py                 # Re-exports for backward compat
│   ├── portfolio_risk.py           # Risk dashboard, expected loss
│   ├── stress_testing.py           # 13 scenarios, stress suite
│   ├── drawdown.py                 # Circuit breakers, drawdown tracking
│   ├── greeks_limits.py            # Greeks concentration
│   └── correlation.py              # Pairwise correlation, effective positions
│
├── hedging/                        # EXPAND from hedging.py
│   ├── __init__.py
│   ├── same_ticker.py              # Current hedging (SPY IC → SPY put)
│   ├── beta_hedge.py               # NEW: Beta-adjusted NIFTY proxy
│   ├── collar.py                   # NEW: Protective collar builder
│   ├── proxy_mapper.py             # NEW: Non-F&O stock → index proxy mapping
│   ├── hedge_sizing.py             # NEW: How many lots to hedge a portfolio
│   ├── hedge_cost.py               # NEW: Monthly hedge cost tracking
│   └── india/                      # NEW: India-specific hedging
│       ├── nifty_hedge.py          # NIFTY/BANKNIFTY proxy hedging
│       ├── sector_exposure.py      # IT/Banking/Auto exposure analysis
│       └── fno_coverage.py         # Which stocks have F&O, which don't
│
├── portfolio/                      # EXPAND from features/desk_management.py
│   ├── __init__.py
│   ├── desk_management.py          # Current desk allocation
│   ├── rebalancing.py              # Desk rebalancing triggers
│   ├── asset_allocation.py         # Asset class → risk type → desks
│   └── multi_account.py            # NEW: Cross-broker consolidation
│
├── monitoring/                     # EXTRACT from trade_lifecycle.py
│   ├── __init__.py
│   ├── exit_conditions.py          # monitor_exit_conditions
│   ├── trade_health.py             # check_trade_health
│   ├── overnight_risk.py           # assess_overnight_risk
│   ├── position_stress.py          # run_position_stress
│   └── monitoring_action.py        # compute_monitoring_action → closing TradeSpec
│
├── markets/                        # Market intelligence
│   ├── __init__.py
│   ├── regime.py                   # Already exists (service/regime_service.py)
│   ├── technicals.py               # Already exists
│   ├── vol_surface.py              # Already exists
│   ├── macro.py                    # Already exists
│   ├── levels.py                   # Already exists
│   └── india/                      # India-specific market features
│       ├── cross_market.py         # US → India gap prediction
│       ├── expiry_calendar.py      # NIFTY Thu, BANKNIFTY Wed
│       └── fno_universe.py         # F&O eligible instruments
│
├── trading/                        # Trade construction + validation
│   ├── __init__.py
│   ├── opportunity/                # Already exists
│   ├── validation/                 # Already exists
│   ├── entry/                      # From features/entry_levels.py
│   ├── exit/                       # From features/exit_intelligence.py
│   └── sizing/                     # From features/position_sizing.py
│
├── trust/                          # Trust framework
│   ├── __init__.py
│   ├── data_quality.py             # From features/data_trust.py
│   ├── context_quality.py          # Calculation modes
│   └── fitness.py                  # Fitness for purpose
│
├── broker/                         # Unchanged — already well-structured
├── adapters/                       # Unchanged
├── data/                           # Unchanged
├── cli/                            # Unchanged
├── demo/                           # Unchanged
└── config/                         # Unchanged
```

### Phase 3: Rename Module (v2.0 — major breaking change)

Only when ready for a major version bump:
- Rename `market_analyzer/` → `income_desk/`
- Update all 200+ files
- Keep `market_analyzer` as a thin re-export shim for 1 version
- eTrading migrates imports

---

## The Hedging Domain (Priority Build)

The hedging package is the most urgent expansion. Here's what each module does:

### `hedging/same_ticker.py` (exists)
Current: "If you have SPY IC, hedge with SPY put."
Stays as-is.

### `hedging/beta_hedge.py` (NEW)
```python
def compute_beta_hedge(
    portfolio_positions: list[dict],   # [{ticker, value, beta}]
    hedge_instrument: str,             # "NIFTY" or "SPY"
    hedge_instrument_price: float,
    lot_size: int,
    target_hedge_pct: float = 0.80,    # Hedge 80% of portfolio delta
) -> BetaHedgeResult:
    """Compute how many lots of index puts to buy for portfolio protection.

    Portfolio beta = weighted average of position betas vs the index.
    Hedge lots = (portfolio_value × portfolio_beta × target_pct) / (index_price × lot_size)
    """
```

### `hedging/collar.py` (NEW)
```python
def build_protective_collar(
    ticker: str,
    shares: int,
    current_price: float,
    regime_id: int,
    atr: float,
    dte: int = 30,
) -> CollarResult:
    """Build a zero-cost or low-cost protective collar.

    Own shares + sell OTM call + buy OTM put.
    Call premium pays for the put (zero net cost).
    Caps upside but eliminates downside.

    Returns: CollarResult with put TradeSpec + call TradeSpec + net cost.
    """
```

### `hedging/proxy_mapper.py` (NEW)
```python
def map_to_hedge_proxy(
    ticker: str,
    market: str = "India",
) -> ProxyMapping:
    """Map a non-F&O stock to its best hedging proxy.

    India: most stocks don't have F&O. Map by sector:
    - IT stocks (TCS, Wipro, HCLTech) → NIFTY IT index → NIFTY put (beta-adjusted)
    - Banks (HDFC, Kotak) → BANKNIFTY put
    - Auto (Maruti, Tata Motors) → NIFTY put (0.9× beta)
    - Pharma (Sun, Dr Reddy) → NIFTY put (0.7× beta)

    US: most stocks have options, but for small positions:
    - Tech basket → QQQ put
    - Broad basket → SPY put
    """
```

### `hedging/hedge_sizing.py` (NEW)
```python
def size_portfolio_hedge(
    portfolio_value: float,
    portfolio_beta: float,
    hedge_instrument_price: float,
    lot_size: int,
    regime_id: int,
    target_protection_pct: float = 0.80,
    max_hedge_cost_pct: float = 0.02,   # Max 2% of portfolio/month
) -> HedgeSizeResult:
    """How many lots + which strike + which DTE for portfolio hedge.

    Balances: protection level vs cost vs regime.
    R1: minimal hedge (5% OTM put, 30 DTE) — cheap insurance
    R2: moderate (3% OTM put, 21 DTE) — real protection
    R4: maximum (ATM put or collar) — capital preservation mode
    """
```

### `hedging/india/fno_coverage.py` (NEW)
```python
def analyze_fno_coverage(
    portfolio_tickers: list[str],
) -> FnOCoverageResult:
    """How much of your India portfolio can be directly hedged?

    Returns:
    - covered: tickers with F&O (can buy puts directly)
    - uncovered: tickers without F&O (need proxy hedging)
    - coverage_pct: % of portfolio value that has direct F&O
    - proxy_map: {uncovered_ticker: suggested_proxy}
    """
```

### `hedging/india/sector_exposure.py` (NEW)
```python
def analyze_sector_exposure(
    portfolio_tickers: list[str],
    portfolio_values: dict[str, float],
) -> SectorExposureResult:
    """What sectors are you exposed to?

    Maps each ticker to: IT, Banking, Auto, Pharma, FMCG, Energy, etc.
    Shows: which sector is overweight, which needs hedging.
    Suggests: sector-specific hedge (BANKNIFTY for banking-heavy, NIFTY for broad).
    """
```

---

## Implementation Priority

| Phase | What | Effort | Breaking? |
|-------|------|--------|-----------|
| **1a** | Create `income_desk/` facade module with TradingDesk | Medium | No |
| **1b** | Build hedging/ domain package (6 modules) | Large | No |
| **1c** | Split risk.py into risk/ package | Medium | No (re-export from __init__) |
| **2** | Split trade_lifecycle.py into monitoring/ package | Medium | No (re-export) |
| **2** | Split features/ into trading/entry, trading/exit, trading/sizing | Medium | No |
| **3** | Rename market_analyzer → income_desk (v2.0) | Large | YES — major version |

**Recommendation:** Do 1a + 1b now. The TradingDesk facade gives new users a clean API. The hedging domain is the revenue driver. Everything else can wait.

---

## The TradingDesk API (Phase 1a)

```python
from income_desk import TradingDesk

# Create desk
desk = TradingDesk(capital=100_000, market="US", risk_tolerance="moderate")
desk.connect("alpaca")  # or "tastytrade", "dhan", etc.

# Portfolio
desk.portfolio.show()                    # Desk allocation + positions
desk.portfolio.allocate("moderate")      # Reallocate capital
desk.portfolio.import_csv("trades.csv")  # Import from any broker

# Markets
desk.markets.regime("SPY")               # Regime detection
desk.markets.sentinel()                  # Crash sentinel
desk.markets.technicals("SPY")           # Full technical snapshot

# Trading
desk.trading.rank(["SPY", "IWM", "GLD"]) # Rank opportunities
desk.trading.validate(trade_spec)         # 10-check gate
desk.trading.size(trade_spec)             # Kelly sizing
desk.trading.audit(trade_spec)            # 4-level decision
desk.trading.book(trade_spec)             # Book to demo portfolio

# Risk
desk.risk.dashboard()                     # Portfolio risk
desk.risk.stress_test()                   # 13 scenarios
desk.risk.margin("SPY")                   # Cash vs margin

# Hedging (NEW domain)
desk.risk.hedge.recommend("NIFTY")        # What hedge do I need?
desk.risk.hedge.collar("RELIANCE", 100)   # Build protective collar
desk.risk.hedge.proxy_map(["TCS", "WIPRO", "HCLTECH"])  # Non-F&O → index proxy
desk.risk.hedge.cost_report()             # Monthly hedge cost

# Monitoring
desk.monitoring.health("SPY")             # Position health
desk.monitoring.exit("SPY")               # Exit conditions
desk.monitoring.adjust("SPY")             # Adjustment recommendation

# Trust
desk.trust.report()                       # Data + context quality
desk.trust.fit_for()                      # What can I do with this data?
```

This is the API that goes in the README, the docs, and the pitch. Clean, domain-driven, discoverable.
