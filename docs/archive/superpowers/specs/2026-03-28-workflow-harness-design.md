# Workflow Harness Design

**Date**: 2026-03-28
**Status**: Approved
**Purpose**: Interactive debugging/onboarding harness that exercises all 15 income_desk workflow APIs

---

## Problem

income_desk has grown large. There's no single script that:
- Proves all 15 workflow APIs work end-to-end with real or simulated data
- Shows a new developer the complete trading day lifecycle
- Serves as a daily pre-market stability check
- Answers "is the platform ready to go live?"

The existing `challenge/trader.py` uses raw MarketAnalyzer APIs (not workflows), has no API signature printing, no tabular output, and isn't interactive.

## Solution

Two files in `challenge/`:

| File | Purpose |
|------|---------|
| `challenge/harness.py` | Main script — phase menu, workflow calls, signature + table output |
| `challenge/harness_support.py` | Non-income-desk concerns: broker setup, data source detection, demo positions, formatting |

## Usage Scenarios

### 1. Developer Onboarding
A new developer runs the harness, picks a market, and walks through each phase. They see:
- The exact function signature and Pydantic request fields for every workflow
- Real inputs with real values
- Tabular output showing what each workflow returns
- How workflows chain (rank output feeds validate/size/price)

### 2. Daily Pre-Market Check
Claude runs the harness at start of trading day:
- Connect to live broker (TastyTrade LIVE for US, Dhan for India)
- Run all 7 phases
- Verify every workflow returns valid, non-empty results
- Flag any errors, empty results, or data trust issues
- Report pass/fail before Nitin trades

### 3. Go-Live Readiness
When asked "is the platform ready?", Claude runs harness against both markets and produces a comprehensive pass/fail report covering all 15 workflows.

---

## Data Source Strategy

```
Startup:
  1. Pick market (US / India)
  2. Connect broker:
     - US  → TastyTrade LIVE (connect_tastytrade(is_paper=False))
     - India → Dhan
  3. Detect market open/closed:
     ├─ Market OPEN  → use live broker data
     ├─ Market CLOSED → fallback chain:
     │   ├─ Saved snapshot (~/.income_desk/sim_snapshot.json) → use it, show age
     │   └─ No snapshot → use preset (create_ideal_income / create_india_trading)
     └─ Broker connection FAILED → same fallback chain
  4. Wrap in unified MarketAnalyzer
  5. yfinance always available as OHLCV fallback (regime, technicals)
```

**Key principle**: Data source is displayed ONCE in the startup banner, then invisible. All workflow calls look identical regardless of source. The user/developer never writes different code for live vs simulated.

### Startup Banner

```
┌──────────────────────────────────────────────────┐
│  income_desk Workflow Harness                    │
│  Market: US │ Broker: tastytrade (LIVE)          │
│  Data: LIVE quotes (market open)                 │
│  Tickers: SPY, QQQ, AAPL, GLD, IWM, TLT         │
│  Account: $52,340 NLV │ $38,200 BP               │
└──────────────────────────────────────────────────┘
```

Or when market is closed:
```
┌──────────────────────────────────────────────────┐
│  income_desk Workflow Harness                    │
│  Market: US │ Broker: not connected              │
│  Data: Simulated (snapshot from 6h ago)          │
│  Tickers: SPY, QQQ, IWM, GLD, TLT + 12 more    │
│  Account: $50,000 NLV (simulated)               │
└──────────────────────────────────────────────────┘
```

## Default Tickers

| Market | Defaults | Simulated Preset |
|--------|----------|------------------|
| US | SPY, QQQ, IWM, GLD, TLT, AAPL, MSFT, NVDA | `create_ideal_income()` — 17 tickers |
| India | NIFTY, BANKNIFTY, RELIANCE, TCS, HDFCBANK, ICICIBANK, SBIN | `create_india_trading()` — 25+ tickers |

Defaults match simulated presets exactly, so weekend runs always work.

Full universe support: `load_universe(market, path="universe_us.yaml")` loads arbitrary ticker lists for screening.

## Interactive Flow

### Phase Menu
```
PHASES:
  1. Pre-Market     (health check, daily plan, market snapshot)
  2. Scanning       (scan universe, rank opportunities)
  3. Trade Entry    (validate, size, price)
  4. Monitoring     (monitor positions, adjust, overnight risk)
  5. Portfolio Risk (Greeks aggregation, stress test)
  6. Calendar       (expiry day check)
  7. Reporting      (daily report)
  0. Run All (step-by-step)

Pick phase [0-7]:
```

### Per-Workflow Output Format
```
── Phase 2: Scanning ──────────────────────────────

▸ Workflow: rank_opportunities
  Signature: rank_opportunities(RankRequest, MarketAnalyzer) -> RankResponse
  Inputs:
    tickers        = ['SPY', 'QQQ', 'AAPL', 'GLD']
    capital        = 50000
    market         = 'US'
    risk_tolerance = 'moderate'

  [calling...]

  Result (3 proposals, 1 blocked):
  ┌────────┬──────────────┬───────┬───────┬────────┬─────────┐
  │ Ticker │ Structure    │ Score │ POP   │ Credit │ Regime  │
  ├────────┼──────────────┼───────┼───────┼────────┼─────────┤
  │ SPY    │ iron_condor  │ 82.3  │ 71%   │ $1.45  │ R1      │
  │ GLD    │ put_spread   │ 76.1  │ 68%   │ $0.90  │ R3      │
  │ QQQ    │ iron_condor  │ 71.8  │ 65%   │ $1.20  │ R1      │
  └────────┴──────────────┴───────┴───────┴────────┴─────────┘

  Blocked:
  ┌────────┬────────────────────────────┐
  │ AAPL   │ No liquid strikes (IV<15)  │
  └────────┴────────────────────────────┘

  [Enter] next ─ [s] skip phase ─ [q] quit
```

## Phase → Workflow Mapping

> **Note**: `check_portfolio_health` is categorized under "Portfolio risk" in the workflow module, but we intentionally place it in Phase 1 as a quick pre-trade safety gate (crash sentinel + risk budget). Phase 5 exercises the deeper portfolio analytics (Greeks aggregation, stress testing).

| Phase | Workflows | Chains From |
|-------|-----------|-------------|
| 1. Pre-Market | `check_portfolio_health` → `generate_daily_plan` → `snapshot_market` | — |
| 2. Scanning | `scan_universe` → `rank_opportunities` | — |
| 3. Trade Entry | `validate_trade` → `size_position` → `price_trade` | Top proposal from phase 2 |
| 4. Monitoring | `monitor_positions` → `adjust_position` → `assess_overnight_risk` | Demo positions (from support) |
| 5. Portfolio Risk | `aggregate_portfolio_greeks` → `stress_test_portfolio` | Demo positions |
| 6. Calendar | `check_expiry_day` | Demo positions |
| 7. Reporting | `generate_daily_report` | Stats from prior phases |

### Workflow Chaining

Phase 2's `rank_opportunities` returns `TradeProposal` objects. Phase 3 uses the top-ranked proposal to:
- `validate_trade` — run 10-check gate
- `size_position` — Kelly criterion sizing
- `price_trade` — get live/simulated leg quotes

If phase 2 wasn't run (user jumped to phase 3), `harness_support` provides a sensible demo TradeProposal.

Phases 4-6 use demo positions from `harness_support.build_demo_positions(market)` — realistic OpenPosition objects that exercise monitoring, adjustment, overnight risk, Greeks, stress, and expiry logic.

## File Structure

### `harness.py` (~300 lines)

```python
# Clean, readable flow — a new developer reads this file to understand the platform
def main():
    market = pick_market()                    # "US" or "India"
    ma, meta = setup(market)                  # broker + fallback, returns MarketAnalyzer
    print_banner(meta)
    tickers = pick_tickers(market, meta)

    phase = phase_menu()
    proposals = None  # populated by phase 2, fallback demo if skipped

    if phase in (0, 1): run_premarket(ma, tickers, meta)
    if phase in (0, 2): proposals = run_scanning(ma, tickers, meta)
    if phase in (0, 3): run_entry(ma, tickers, proposals, meta)  # uses build_demo_proposal() if proposals is None
    if phase in (0, 4): run_monitoring(ma, meta)
    if phase in (0, 5): run_portfolio_risk(ma, meta)
    if phase in (0, 6): run_calendar(ma, meta)
    if phase in (0, 7): run_reporting(ma, meta)
```

Each `run_*` function:
1. Builds the Pydantic request
2. Calls `print_signature(workflow_fn, request)` — shows function name, types, field values
3. Calls the workflow
4. Calls `print_table(...)` — formats response into aligned table
5. Waits for user input (`[Enter] next`, `[s] skip`, `[q] quit`)

### `harness_support.py` (~200 lines)

All non-income-desk concerns:

```python
def setup(market: str) -> tuple[MarketAnalyzer, BannerMeta]:
    """Connect broker → detect market hours → fallback to simulated → return MA"""

def pick_market() -> str:
    """Prompt: [U]S or [I]ndia"""

def pick_tickers(market: str, meta: BannerMeta) -> list[str]:
    """Show defaults, allow override, support universe loading"""

def load_universe(market: str, path: str | None = None) -> list[str]:
    """Load ticker list from YAML/CSV or return full preset"""

def build_demo_positions(market: str) -> list[OpenPosition]:
    """Realistic fake positions for monitoring/overnight/stress/expiry demos"""

def build_demo_proposal(market: str) -> TradeProposal:
    """Fallback proposal when phase 2 wasn't run"""

def print_banner(meta: BannerMeta) -> None:
    """One-time startup info display"""

def print_signature(func, request) -> None:
    """Introspect workflow function + Pydantic model, print name/types/values"""

def print_table(title: str, headers: list[str], rows: list[list]) -> None:
    """Aligned tabular output"""

def wait_for_input() -> str:
    """[Enter] next, [s] skip, [q] quit"""

@dataclass
class BannerMeta:
    market: str
    broker_name: str | None
    data_source: str          # "LIVE", "Snapshot (6h old)", "Simulated (ideal_income)"
    account_nlv: float | None
    account_bp: float | None
    ticker_count: int
    currency: str
```

## Broker Connection

| Market | Broker | Mode | Connection |
|--------|--------|------|------------|
| US | TastyTrade | **LIVE** | `connect_tastytrade(is_paper=False)` |
| India | Dhan | LIVE | Existing Dhan adapter |

Connection failure is not fatal — falls through to simulated data with a one-line note in the banner.

## What This File Does NOT Do

- **No test assertions** — that's `trader_india.py`'s job
- **No broker session management** — connect once at startup, use throughout

## Error Handling

Every workflow call is wrapped in try/except. Errors don't abort the harness — they're displayed inline and the phase continues.

```
▸ Workflow: price_trade
  ...
  ✗ ERROR: ConnectionError — broker session expired
  (continuing to next workflow)
```

**Per-workflow error display**: error type, message, one-line context. No tracebacks unless `--verbose`.

**Empty result detection**: Each `run_*` function knows what "empty" means for its workflows:
- `rank_opportunities` → 0 proposals and 0 blocked = empty
- `monitor_positions` → 0 positions checked = empty
- `snapshot_market` → 0 tickers returned = empty

**Run All summary**: After all phases complete, print a pass/fail summary table:

```
── Summary ────────────────────────────────────────
┌─────────────────────────┬────────┬──────────────┐
│ Workflow                │ Status │ Note         │
├─────────────────────────┼────────┼──────────────┤
│ check_portfolio_health  │ PASS   │ GREEN signal │
│ generate_daily_plan     │ PASS   │ 3 trades     │
│ snapshot_market         │ PASS   │ 6 tickers    │
│ ...                     │        │              │
│ price_trade             │ FAIL   │ ConnError    │
│ ...                     │        │              │
└─────────────────────────┴────────┴──────────────┘
Result: 14/15 PASS │ 1 FAIL
```

## CLI Arguments

```bash
# Interactive (default)
python -m challenge.harness

# Non-interactive — runs all phases, prints summary (for Claude's daily checks)
python -m challenge.harness --all --market=US

# Specific phase, non-interactive
python -m challenge.harness --phase=2 --market=India

# Verbose — include tracebacks on error
python -m challenge.harness --all --market=US --verbose
```

## Trust Verification (Phase 8 — optional)

When running with live broker data, an optional Phase 8 cross-checks income_desk calculations against raw broker values:

| Check | Method |
|-------|--------|
| Option mid prices | Compare `price_trade` output vs raw broker quotes |
| IV rank | Compare computed IV rank vs broker-reported |
| Greeks | Compare `aggregate_portfolio_greeks` vs broker portfolio page |
| Strike liquidity | Verify selected strikes have actual OI > threshold |
| Position sizing | Verify Kelly output matches manual calculation |

This phase only runs when broker is connected (live data). Returns a trust score: percentage of checks within tolerance.

> **Note**: This is point-in-time verification only. Outcome-based benchmarking (did regime predictions come true? did POP estimates calibrate?) requires trade outcome data over time and is a separate system (performance feedback loop in CLAUDE.md).

## Success Criteria

1. A new developer can run `python -m challenge.harness` with zero credentials and see all 15 workflows execute with simulated data
2. With broker credentials, the same script uses live data seamlessly
3. Claude can run this daily to verify platform stability (`--all --market=US`)
4. Every workflow's inputs and outputs are visible and inspectable
5. The script serves as executable documentation of the workflow API surface
6. Pass/fail summary at the end of Run All gives a clear go/no-go signal
