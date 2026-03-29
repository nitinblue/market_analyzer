# Trader MD — Markdown-Driven Trading Platform

**Date**: 2026-03-29
**Status**: Design

---

## Overview

Two parallel trading paths inside income_desk, same engine underneath:

```
income_desk/
  trader/              ← Python path (renamed from challenge/)
  trader_md/           ← MD path (everything new, declarative)
```

Both call the same engine (`workflow/`, `service/`, `scenarios/`, `broker/`). The difference is how the trading logic is defined: Python code vs markdown files.

## Goals

1. **trader/** — rename `challenge/` to `trader/`, clean up naming, no functional changes
2. **trader_md/** — MD-driven trading where `.workflow.md` IS the strategy
3. **Zero changes** to engine layer (`workflow/`, `service/`, `broker/`, etc.)
4. **Open spec** — the MD formats are documented so anyone can build a parser

## Folder Structure

```
income_desk/
  │
  ├── [engine layer — UNTOUCHED]
  │   ├── workflow/              15 APIs
  │   ├── service/               MarketAnalyzer, regime, technicals
  │   ├── scenarios/
  │   │   ├── definitions.py     Python scenario definitions (stays)
  │   │   ├── engine.py          Scenario engine (stays)
  │   │   └── parser.py          .scenario.md parser (stays — engine code)
  │   ├── broker/                tastytrade, dhan, etc.
  │   ├── adapters/              simulated, csv, dict
  │   ├── models/                Pydantic models
  │   └── features/              market pulse (sentinel), data trust, etc.
  │
  ├── trader/                    PATH 1: Python-driven (renamed from challenge/)
  │   ├── __init__.py
  │   ├── trader.py              renamed from harness.py
  │   ├── support.py             renamed from harness_support.py
  │   ├── trader_india.py        India test suite (as-is)
  │   ├── trader_stocks.py       stock screener (as-is)
  │   ├── portfolio.py           portfolio tracker (as-is)
  │   ├── models.py              portfolio models (as-is)
  │   └── diag_dxlink.py         DXLink diagnostics (as-is)
  │
  ├── trader_md/                 PATH 2: MD-driven (everything new)
  │   ├── __init__.py
  │   ├── runner.py              THE runner — reads MD, calls engine
  │   ├── parser.py              parses all MD types
  │   ├── models.py              WorkflowPlan, Phase, Step, Gate, Binding
  │   ├── workflows/
  │   │   ├── daily_us.workflow.md
  │   │   ├── daily_india.workflow.md
  │   │   ├── zero_dte.workflow.md
  │   │   └── crash_response.workflow.md
  │   ├── scenarios/             .scenario.md files (moved from scenarios/formats/)
  │   │   ├── sp500_down_5.scenario.md
  │   │   ├── black_monday.scenario.md
  │   │   └── ... (all 18)
  │   ├── universes/
  │   │   ├── us_large_cap.universe.md
  │   │   └── india_fno.universe.md
  │   ├── risk_profiles/
  │   │   ├── conservative.risk.md
  │   │   ├── moderate.risk.md
  │   │   └── aggressive.risk.md
  │   ├── broker_profiles/
  │   │   ├── tastytrade_live.broker.md
  │   │   ├── dhan_live.broker.md
  │   │   └── simulated.broker.md
  │   ├── specs/
  │   │   ├── workflow-spec.md
  │   │   ├── scenario-spec.md
  │   │   ├── universe-spec.md
  │   │   ├── risk-profile-spec.md
  │   │   └── broker-profile-spec.md
  │   ├── .env.example           committed — credential template
  │   └── .env.trading           gitignored — user's secrets
  │
  └── templates/                 starter files for new users
      ├── daily_us.workflow.md
      ├── moderate.risk.md
      ├── us_large_cap.universe.md
      └── tastytrade_live.broker.md
```

---

## MD File Formats

### .workflow.md — The Strategy

```markdown
---
name: daily_us_income
description: Daily income trading for US market
broker: tastytrade_live
universe: us_large_cap
risk_profile: moderate
---

# Daily US Income Trading

## Phase 1: Market Assessment

### Step: Market Pulse
workflow: check_portfolio_health
inputs:
  tickers: $universe
  capital: $capital
outputs:
  pulse: $result.sentinel_signal
  safe: $result.is_safe_to_trade
  regimes: $result.regimes
gate:
  - pulse != "RED"
  - safe == True
on_fail: HALT "Market pulse {pulse} — trading halted"

### Step: Snapshot
workflow: snapshot_market
inputs:
  tickers: $universe
  include_regime: true
outputs:
  snapshots: $result.tickers
  iv_rank_map: $result.tickers.*.iv_rank

## Phase 2: Scanning

### Step: Rank
workflow: rank_opportunities
inputs:
  tickers: $universe
  capital: $capital
  iv_rank_map: $phase1.iv_rank_map
  min_pop: $risk.min_pop
  max_trades: 5
outputs:
  proposals: $result.trades
  blocked: $result.blocked
gate:
  - len(proposals) > 0
on_fail: SKIP "No opportunities found"

## Phase 3: Entry

### Step: Validate
workflow: validate_trade
inputs:
  ticker: $phase2.proposals[0].ticker
  entry_credit: $phase2.proposals[0].entry_credit
  regime_id: $phase2.proposals[0].regime_id
gate:
  - is_ready == True
on_fail: SKIP "Validation failed: {failed_gates}"

### Step: Size
workflow: size_position
inputs:
  pop_pct: $phase2.proposals[0].pop_pct
  max_profit: $phase2.proposals[0].max_profit
  max_loss: $phase2.proposals[0].max_risk
  capital: $capital
gate:
  - risk_pct_of_capital < $risk.max_risk_per_trade_pct
on_fail: BLOCK "Risk {risk_pct_of_capital}% exceeds limit"

### Step: Price
workflow: price_trade
inputs:
  ticker: $phase2.proposals[0].ticker
  legs: $phase2.proposals[0].legs
requires: live_broker
on_simulated: WARN "Simulated quotes — not tradeable"

## Phase 4: Monitoring

requires_positions: true

### Step: Monitor
workflow: monitor_positions
inputs:
  positions: $positions
gate:
  - critical_count == 0
on_fail: ALERT "Critical: {critical_count} positions need action"

### Step: Overnight Risk
workflow: assess_overnight_risk
inputs:
  positions: $positions
gate:
  - close_before_close_count == 0
on_fail: ALERT "Close before EOD: {close_before_close_count} positions"

## Phase 5: Risk

### Step: Stress Test
workflow: stress_test_portfolio
inputs:
  positions: $positions
  capital: $capital
  scenarios: null
gate:
  - risk_score != "critical"
on_fail: ALERT "Portfolio stress: {risk_score}"
```

### .broker.md — Broker Configuration

```markdown
---
name: tastytrade_live
broker_type: tastytrade
mode: live
market: US
currency: USD
credentials: .env.trading
fallback: simulated
---

# TastyTrade Live Connection

## Settings
timeout: 30
streaming: dxlink
paper_fallback: false

## Credentials (from .env.trading)
- TASTYTRADE_CLIENT_SECRET_LIVE
- TASTYTRADE_REFRESH_TOKEN_LIVE
```

### .universe.md — Ticker Lists

```markdown
---
name: us_large_cap
market: US
description: US large cap stocks + major ETFs
---

# US Large Cap Universe

## Core ETFs
- SPY    # S&P 500
- QQQ    # Nasdaq 100
- IWM    # Russell 2000
- DIA    # Dow 30

## Bonds & Commodities
- TLT    # 20Y Treasury
- GLD    # Gold

## Mega Cap Tech
- AAPL
- MSFT
- NVDA
- AMZN
- GOOGL
- META
- TSLA
```

### .risk.md — Risk Profile

```markdown
---
name: moderate
description: Moderate risk tolerance for income trading
---

# Moderate Risk Profile

## Position Limits
max_risk_per_trade_pct: 3.0
max_portfolio_risk_pct: 30.0
max_positions: 8
max_correlated_positions: 3

## Trade Filters
min_pop: 0.50
min_dte: 7
max_dte: 45
min_iv_rank: 20
max_spread_pct: 0.05

## Regime Rules
r1_allowed: true       # Low-Vol MR — full income
r2_allowed: true       # High-Vol MR — selective, wider wings
r3_allowed: false      # Low-Vol Trend — no income trades
r4_allowed: false      # High-Vol Trend — no trades

## Exit Rules
profit_target_pct: 0.50
stop_loss_pct: 2.0
exit_dte: 5
```

---

## Binding & Expression Language

### Variable Resolution

| Syntax | Resolves to |
|--------|------------|
| `$universe` | Tickers from the referenced `.universe.md` file |
| `$capital` | Account NLV from broker, or `capital` in frontmatter |
| `$risk.<field>` | Field from the referenced `.risk.md` file |
| `$result.<field>` | Current step's response field |
| `$phase1.<output>` | Named output from a previous phase |
| `$phase2.proposals[0]` | First item in a list output |
| `$positions` | Live positions (from broker or demo) |

### Gate Expressions

Simple boolean conditions evaluated after each step:

```
gate:
  - pulse != "RED"                    # string comparison
  - safe == True                       # boolean
  - len(proposals) > 0                 # length check
  - risk_pct_of_capital < 5.0         # numeric comparison
  - risk_pct_of_capital < $risk.max_risk_per_trade_pct   # reference to risk profile
```

### On-Fail Actions

| Action | Behavior |
|--------|----------|
| `HALT "message"` | Stop entire workflow, print message |
| `SKIP "message"` | Skip this step, continue to next |
| `BLOCK "message"` | Block this step, continue to next phase |
| `ALERT "message"` | Log warning, continue execution |
| `WARN "message"` | Soft warning, continue |

---

## Runner Architecture

### runner.py — The single Python file that matters

```python
class TradingRunner:
    def __init__(self, workflow_path: str):
        """Load and parse workflow MD + all referenced MD files."""

    def run(self, interactive: bool = False) -> ExecutionReport:
        """Execute the workflow plan."""

    def validate(self) -> list[str]:
        """Check workflow references, gate syntax, binding validity."""

    def dry_run(self) -> str:
        """Show what would execute without calling any APIs."""
```

### Execution flow

```
1. Parse .workflow.md → WorkflowPlan
2. Resolve references:
   - Load .broker.md → connect broker (or simulated fallback)
   - Load .universe.md → ticker list
   - Load .risk.md → risk parameters
   - Load .env.trading → credentials
3. Build MarketAnalyzer with resolved broker
4. For each Phase:
   For each Step:
     a. Resolve input bindings ($phase1.iv_rank_map → actual value)
     b. Build Pydantic request from resolved inputs
     c. Call workflow function
     d. Store outputs in context
     e. Evaluate gates
     f. On gate failure: execute on_fail action
     g. Print results (tabular, like current harness)
5. Return ExecutionReport
```

### parser.py — Reads all MD types

```python
def parse_workflow(path: Path) -> WorkflowPlan
def parse_broker(path: Path) -> BrokerProfile
def parse_universe(path: Path) -> UniverseSpec
def parse_risk(path: Path) -> RiskProfile
```

All use YAML frontmatter + section parsing (same pattern as scenario parser).

### models.py — Data structures

```python
@dataclass
class Gate:
    expression: str
    on_fail: str              # HALT, SKIP, BLOCK, ALERT, WARN
    message: str

@dataclass
class Binding:
    expression: str           # "$phase1.iv_rank_map"

@dataclass
class Step:
    name: str
    workflow: str             # "check_portfolio_health"
    inputs: dict[str, Binding]
    outputs: dict[str, Binding]
    gates: list[Gate]
    requires: str | None      # "live_broker", None
    on_simulated: str | None  # "WARN ..."

@dataclass
class Phase:
    name: str
    number: int
    steps: list[Step]
    requires_positions: bool

@dataclass
class BrokerProfile:
    name: str
    broker_type: str
    mode: str
    market: str
    currency: str
    credentials_source: str   # ".env.trading"
    fallback: str             # "simulated"

@dataclass
class UniverseSpec:
    name: str
    market: str
    tickers: list[str]

@dataclass
class RiskProfile:
    name: str
    max_risk_per_trade_pct: float
    max_portfolio_risk_pct: float
    max_positions: int
    min_pop: float
    min_dte: int
    max_dte: int
    min_iv_rank: float
    max_spread_pct: float
    profit_target_pct: float
    stop_loss_pct: float
    exit_dte: int
    regime_rules: dict[str, bool]

@dataclass
class WorkflowPlan:
    name: str
    description: str
    broker_ref: str           # "tastytrade_live" → loads .broker.md
    universe_ref: str         # "us_large_cap" → loads .universe.md
    risk_ref: str             # "moderate" → loads .risk.md
    phases: list[Phase]
```

---

## CLI

```bash
# Path 1: Python way (renamed from challenge)
python -m income_desk.trader --all --market=US

# Path 2: MD way
python -m income_desk.trader_md run workflows/daily_us.workflow.md
python -m income_desk.trader_md validate workflows/daily_us.workflow.md
python -m income_desk.trader_md dry-run workflows/daily_us.workflow.md
python -m income_desk.trader_md run workflows/daily_us.workflow.md --interactive
```

---

## Naming Conventions

| Internal (engine) | MD Layer (user-facing) |
|-------------------|----------------------|
| sentinel_signal | market_pulse |
| check_portfolio_health | Market Pulse step |
| SCENARIOS dict | .scenario.md files |
| RankRequest.iv_rank_map | $phase1.iv_rank_map |
| TradeProposal | proposal (in bindings) |

The runner maps between MD names and engine names. Internal code unchanged.

---

## Credentials

**Never in MD files.** MD files are committed to git.

```
.env.trading              ← gitignored, user creates from .env.example
.env.example              ← committed, shows required vars
```

Broker MD references: `credentials: .env.trading`
Runner loads: `load_dotenv(".env.trading")`

For Claude Skill distribution:
```
User: "Set up my broker"
Claude: "Create .env.trading with your credentials:
         TASTYTRADE_CLIENT_SECRET_LIVE=<your secret>
         ..."
```

---

## Migration

1. Rename `challenge/` → `trader/` (update imports, README, scheduled agents)
2. Move `scenarios/formats/*.scenario.md` → `trader_md/scenarios/`
3. Update `load_all_scenarios()` path reference
4. Create `trader_md/` package with parser, models, runner
5. Create initial MD files (workflows, universes, risk profiles, broker profiles)
6. Create specs/ with format documentation

---

## What's NOT in scope

- No formula definition language (future)
- No visual editor
- No marketplace
- No multi-tenant auth
- No changes to engine layer
- No deprecation of trader/ (Python path lives alongside MD path)

---

## Success Criteria

1. `python -m income_desk.trader_md run daily_us.workflow.md` executes all phases against simulated data
2. Same output quality as current harness (tables, signatures, pass/fail)
3. Changing `min_pop: 0.50` to `min_pop: 0.60` in `.risk.md` changes behavior — no Python edit needed
4. A new user copies template MD files, sets up `.env.trading`, and trades — no Python knowledge needed
5. All existing tests pass (engine untouched)
6. `python -m income_desk.trader` still works (renamed from challenge)
