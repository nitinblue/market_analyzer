# income_desk Roadmap

> From current state to 100K downloads.
> Written: 2026-03-28 | Last updated: 2026-03-28

---

## Current State

**Published:** PyPI v1.1.1, MIT license, GitHub Actions CI + publish.

| Dimension | What Exists |
|-----------|-------------|
| Python engine | 15 workflow APIs, HMM 4-state regime detection, 6 broker integrations (tastytrade, alpaca, ibkr, schwab, zerodha, dhan), simulated data layer |
| trader/ (Python path) | Interactive harness, 15/15 workflows, scheduled daily checks, US + India runners |
| trader_md/ (MD path) | Parser, runner, 7 format specs (.workflow.md, .scenario.md, .universe.md, .risk.md, .broker.md, .gate.md, .binding.md) |
| Scenarios | 18 stress test scenarios as .scenario.md files |
| Benchmarking | Calibration APIs (POP, regime accuracy, score-vs-outcome), workflow, report generator |
| Tests | 2940 tests (unit + functional + integration), all green |
| CLI | 67+ commands via interactive REPL |
| Validation | 10-check profitability gate, 3-check adversarial suite |
| Risk | Crash sentinel (5 phases), Kelly sizing, decision audit (4-level), overnight risk |
| Docs | USER_MANUAL, ETRADING_INTEGRATION, CRASH_PLAYBOOK, TRUST_FRAMEWORK, 7 format specs |

**What's production-ready:** Regime detection, profitability gating, Kelly sizing, crash sentinel, trade ranking, position monitoring, stress testing, US + India market support.

**What's prototype-grade:** Backtesting (deliberately absent), ML regime validation, POP calibration from real outcomes, strategy marketplace, API server mode.

**What blocks 100K downloads (working backward):**
1. Non-Python users cannot access the engine (no Claude skill, no MCP, no REST API)
2. First-time experience requires Python knowledge and broker credentials
3. No historical replay / walk-forward testing for credibility
4. No community infrastructure beyond GitHub Discussions
5. Single-maintainer project with no plugin system

---

## Business Objectives

| # | Objective | Why it matters |
|---|-----------|---------------|
| B1 | First 1,000 users | Prove product-market fit |
| B2 | Cross-model access | Not locked to Claude -- any LLM, any language |
| B3 | MD format as standard | The moat -- who owns the format owns the market |
| B4 | Production-grade risk | Real money demands real reliability |
| B5 | Community ecosystem | Growth through contributions, not just features |
| B6 | Enterprise readiness | Revenue from commercial licensing |

---

## Phase 1: First 1,000 Users (Claude Skill + Standalone MD Access)

### Priority: P0
### Timeline: Q2 2026 (Months 1-2)

The fastest path to users: let anyone with Claude Code run `income_desk` without writing Python. Two paths: Claude skill for Claude users, improved MD documentation for everyone else.

#### 1a. Claude Code Skill Distribution

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Skill manifest file | Create `.claude/skill.json` with name, description, version, required tools (Bash, Read, Write), permissions (filesystem read/write to workspace, network for broker APIs) | None | S | B1 |
| Skill prompt engineering | System prompt that teaches Claude the trader_md format, available workflows, regime model, and trading philosophy. Must produce correct .workflow.md from natural language like "scan for iron condors on SPY and QQQ with moderate risk" | None | L | B1 |
| Natural language to .workflow.md | Skill generates valid .workflow.md files from conversational requests. Map intents: "find trades" -> scan_universe + rank_opportunities, "check my portfolio" -> portfolio_health + monitor_positions, "stress test" -> stress_test with scenario selection | Skill prompt | L | B1, B3 |
| Skill onboarding flow | Step-by-step: (1) `pip install income-desk`, (2) choose broker or `--sim` mode, (3) pick a universe (.universe.md), (4) generate first daily plan, (5) review and execute. Skill detects missing config and guides through setup | Skill manifest | M | B1 |
| Error handling in skill context | Skill catches common failures (broker auth expired, market closed, no data for ticker) and provides actionable recovery steps instead of stack traces. Maps Python exceptions to human-readable guidance | Skill prompt | M | B1, B4 |
| Skill-generated reports | After workflow execution, skill formats results as readable markdown: regime table, ranked trades with scores, risk warnings, suggested actions. Not raw JSON dumps | Skill prompt | M | B1 |
| Skill testing harness | Automated tests that verify skill produces valid .workflow.md for 20+ natural language inputs. Regression suite for prompt changes | Skill manifest | M | B4 |
| Publish to Claude skill registry | Package skill for distribution. Users install with a single command. Include README with screenshots | All above | S | B1 |

#### 1b. End-to-End User Guide (MD-Based Access)

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| "First Trade in 5 Minutes" guide | From `pip install income-desk` to first simulated trade execution. Uses `--sim` mode, no broker needed. Covers: install, run daily plan, read regime output, understand ranked trades, validate top pick | None | M | B1 |
| Recipe book: 10 common workflows | (1) Morning scan, (2) Check open positions, (3) Stress test portfolio, (4) Find earnings plays, (5) End-of-day review, (6) Weekly regime report, (7) Size a new trade, (8) Adjust a losing position, (9) Overnight risk check, (10) Compare two strategies | First Trade guide | L | B1, B5 |
| .workflow.md template library | 15+ pre-built workflows for common trading patterns: income_weekly.workflow.md, earnings_avoidance.workflow.md, crash_recovery.workflow.md, 0dte_scan.workflow.md, portfolio_rebalance.workflow.md | None | M | B1, B3 |
| Broker connection guides | Per-broker setup: tastytrade (API token from settings), alpaca (key+secret from dashboard), dhan (client_id+access_token), zerodha (enctoken flow), ibkr (TWS gateway), schwab (OAuth2 dance). Screenshots for each | None | L | B1 |
| Troubleshooting guide | Top 20 errors users will hit: "No data for ticker X" (market closed), "Broker auth failed" (token expired), "Regime unavailable" (insufficient history), "Kelly says 0 contracts" (edge too thin). Each with cause + fix | First Trade guide | M | B1 |

#### 1c. Simulated Mode Polish

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| `income-desk --demo` one-command experience | Single command that runs a full trading day simulation: regime scan of 8 tickers, rank top 3, validate #1, size it, show audit report. No config needed. Output is self-explanatory | None | M | B1 |
| Demo portfolio with realistic positions | Pre-built portfolio (3-4 open positions) that ships with the package. Users can monitor, stress test, and practice adjustments without a broker | None | S | B1 |
| Guided walkthrough mode | `income-desk --tutorial` that explains each step as it runs. "Step 1: We're checking the regime for SPY... The HMM model says R2 (High-Vol Mean Reverting). This means..." | Demo mode | M | B1 |

---

## Phase 2: Cross-Model Compatibility + API Layer (1K to 10K Users)

### Priority: P0
### Timeline: Q2-Q3 2026 (Months 2-4)

Claude skill gets early adopters. Reaching 10K requires model-agnostic access. Three paths: MCP server (any LLM with tool use), REST API (any programming language), and direct MD-based access (no LLM needed).

#### 2a. MCP Server for Universal LLM Access

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| MCP server implementation | FastMCP server exposing income_desk workflows as MCP tools. Each workflow API becomes a tool: `scan_universe(tickers, risk_profile)`, `rank_opportunities(tickers)`, `stress_test(portfolio, scenario)`, etc. | None | L | B2 |
| Tool schema definitions | JSON Schema for every tool's inputs and outputs. Rich descriptions that any LLM can understand: parameter constraints, example values, return format | MCP server | M | B2 |
| Resource endpoints | Expose .universe.md, .scenario.md, .risk.md files as MCP resources. LLMs can read available universes and scenarios without filesystem access | MCP server | M | B2, B3 |
| Prompt templates | MCP prompt templates for common tasks: "Generate a daily trading plan for {universe} with {risk_profile}", "Stress test {portfolio} against {scenario}" | MCP server | S | B2 |
| GPT-4 / Gemini / Llama testing | Verify MCP tools work correctly with non-Claude models. Document model-specific quirks (e.g., Gemini may need simpler schemas, Llama may need more examples in descriptions) | MCP server | M | B2 |
| MCP server packaging | `income-desk-mcp` as a separate PyPI package or entry point. `income-desk --mcp` starts the server. Configuration via .env or CLI flags | MCP server | S | B2 |

#### 2b. REST API Server

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| FastAPI server wrapping workflow APIs | `/api/v1/scan`, `/api/v1/rank`, `/api/v1/regime/{ticker}`, `/api/v1/stress-test`, `/api/v1/validate-trade`, `/api/v1/size-position`. Pydantic models already exist; expose them as request/response schemas | None | L | B2 |
| Authentication layer | API key authentication for self-hosted instances. No multi-tenant auth yet (that's Phase 4). Rate limiting per key | FastAPI server | M | B6 |
| OpenAPI spec generation | Auto-generated from FastAPI. Enables client generation in TypeScript, Go, Rust, Java. Publish spec to GitHub releases | FastAPI server | S | B2 |
| WebSocket feed for live monitoring | `/ws/positions` streams position updates, regime changes, alert triggers. Replaces polling for real-time dashboards | FastAPI server | L | B2, B4 |
| Client SDK: TypeScript | `npm install income-desk` -- typed client generated from OpenAPI spec. Enables web dashboard builders, Node.js bots, Electron apps | OpenAPI spec | M | B2 |
| Client SDK: Go | `go get github.com/nitinblue/income-desk-go` -- for high-performance trading systems that call income_desk as a service | OpenAPI spec | M | B2 |

#### 2c. Model-Agnostic vs Claude-Specific Features

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Document model-agnostic core | All workflow APIs, trader_md parser/runner, regime detection, validation, sizing, benchmarking are model-agnostic. Document this boundary clearly | None | S | B2 |
| Document Claude-specific features | Claude skill (natural language to .workflow.md), debug commentary generation, gap identification prose -- these leverage Claude's reasoning and are Claude-specific | None | S | B2 |
| Prompt adapter layer | For non-Claude models that support tool use: adapter that translates income_desk tool schemas into model-specific formats (OpenAI function calling, Gemini tool declarations) | MCP server | M | B2 |

---

## Phase 3: MD Format Enhancements (Foundation for Scale)

### Priority: P1
### Timeline: Q3 2026 (Months 3-5)

The .md format is income_desk's moat. Making it more expressive enables power users, community contributions, and eventually a strategy marketplace.

#### 3a. Language Enhancements

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Formula definition language | Mathematical expressions in .scenario.md: `shock: SPY_price * -0.10`, `new_iv: base_iv * (1 + vix_spike_pct)`. Parser evaluates expressions against current state. Safer than arbitrary code, more flexible than fixed percentages | Parser update | L | B3 |
| Conditional phases | `if: regime == "R4"` / `else:` blocks in .workflow.md. Enables adaptive workflows: scan aggressively in R1, defensively in R4. Parser validates conditions against known state keys | Parser update | L | B3 |
| Workflow composition via imports | `import: shared/market_assessment.phase.md` -- reusable phase definitions. DRY across workflows. Resolver searches workspace then package defaults | Parser update | M | B3, B5 |
| Parameterized workflow templates | `template: iron_condor_scan` with `params: {min_dte: 30, max_dte: 45, universe: "sp500_liquid"}`. Instantiate with overrides: `income-desk run iron_condor_scan --min_dte 21` | Composition | M | B3 |
| Versioned workflows | `version: 2` header in .workflow.md. Runner checks compatibility. Breaking changes (renamed outputs, removed phases) cause clear error: "This workflow requires income_desk >= 1.3.0" | None | S | B3 |
| Workflow variables and state passing | `set: total_candidates = scan_result.count` in a step, reference `{total_candidates}` in later steps. Typed state bag that flows through phases | Conditional phases | M | B3 |

#### 3b. Tooling

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Workflow validation CLI | `income-desk validate my_workflow.workflow.md` -- checks syntax, verifies all referenced workflows exist, validates gate expressions, reports unused outputs. Exit code 0/1 for CI integration | None | M | B3, B4 |
| Workflow diff/compare | `income-desk diff workflow_v1.md workflow_v2.md` -- shows added/removed/changed phases, steps, gates. Useful for reviewing workflow changes in PRs | None | M | B3 |
| Workflow visualization | `income-desk viz my_workflow.workflow.md` -- generates Mermaid diagram of phases, steps, gates, data flow. Renderable in GitHub, VS Code, documentation sites | None | M | B3 |
| Custom validators | `.validator.md` format: define custom validation rules per workflow. "scan_universe output must have >= 3 tickers", "stress_test must include at least one crash scenario" | Validation CLI | M | B3 |
| MD format linter | VS Code extension or CLI tool that provides autocomplete, syntax highlighting, and real-time validation for .workflow.md, .scenario.md, etc. | Validation CLI | L | B3, B5 |

---

## Phase 4: Industry-Standard MD Definitions (Complete Trading Platform)

### Priority: P1
### Timeline: Q3-Q4 2026 (Months 4-7)

Expand the MD format to cover every dimension of a production trading operation. Each new format gets: spec document, parser support, runner integration, CLI command, tests.

#### 4a. Portfolio and Desk Definitions

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| portfolio.md spec | Define desk structure, capital allocation per desk, asset class restrictions, rebalance frequency. Example: `desks: [{name: theta_harvest, capital_pct: 60, strategies: [iron_condor, strangle]}, {name: directional, capital_pct: 20}]` | None | M | B3 |
| desk.md spec | Per-desk mandate: allowed strategies, capital limit, max positions, allowed underlyings, allowed regimes. Enforced by gate framework during trade validation | portfolio.md | M | B3 |
| allocation_rules.md spec | Rules for deploying capital across desks: "if crash_sentinel == RED, move 50% of theta_harvest capital to cash", "if regime(SPY) == R1, increase theta_harvest allocation by 10%" | portfolio.md | L | B3, B4 |

#### 4b. Risk Management Definitions

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| position_limits.md spec | Per-position: max delta, max notional, max contracts. Per-sector: max allocation %. Per-correlation: max correlated exposure. Runner enforces during sizing | None | M | B3, B4 |
| margin_rules.md spec | Margin calculation rules per broker/account type: Reg-T, Portfolio Margin, India span. Buffer requirements per strategy. Runner validates margin availability before trade | None | L | B3, B4 |
| drawdown_rules.md spec | Max drawdown per desk, per portfolio, per day. Circuit breakers: "if daily_loss > 2%, halt new entries", "if weekly_loss > 5%, reduce all positions by 50%". Crash sentinel integration | None | M | B4 |
| concentration_limits.md spec | Sector concentration (max 30% in tech), single-ticker concentration (max 10% per ticker), correlation concentration (max 3 positions with correlation > 0.7). Validated during ranking | None | M | B4 |

#### 4c. P&L, Greeks, and Hedging

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| pnl_rules.md spec | Profit targets per strategy (IC: close at 50% max profit), stop losses (close at 2x credit received), time-based exits (close at 7 DTE regardless). Runner generates exit signals | None | M | B3, B4 |
| greeks_limits.md spec | Portfolio-level limits: max absolute delta, max gamma exposure, min theta per day, max vega. Per-position limits. Runner checks after sizing and flags violations | None | M | B4 |
| hedge_rules.md spec | When to hedge: "if portfolio delta > 15, buy protective puts", "if vega > X, add calendar". How to hedge: same-ticker only (per CLAUDE.md philosophy). Automated hedge suggestion in monitor workflow | None | L | B4 |

#### 4d. Market Structure

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| market.md spec | Trading hours, pre-market/after-hours rules, circuit breaker levels, holiday calendar. Currently hardcoded in several places; extract to declarative format. Per-market (US, India) definitions | None | M | B3 |
| expiry_calendar.md spec | Monthly/weekly/daily expiry rules per market. Options expiry day special handling (pin risk, early assignment). 0DTE identification. Currently scattered across codebase | market.md | M | B3 |
| lot_sizes.md spec | Lot size per instrument per market. India: NIFTY=25, BANKNIFTY=15. US: standard 100. Custom for futures. Used by sizing engine | None | S | B3 |

#### 4e. Compliance

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| compliance.md spec | PDT rules (US: 3 day trades in 5 days under 25K), wash sale rules (30-day window), India F&O margin rules. Runner warns before violation, blocks if configured to enforce | None | L | B4, B6 |
| audit_trail.md spec | What to log per trade: entry time, fill price, slippage, regime at entry, gate results, sizing rationale, exit reason. Retention policy. Format for export to CSV/JSON | None | M | B4, B6 |

---

## Phase 5: Deployment and Operations (10K to 50K Users)

### Priority: P1
### Timeline: Q4 2026 (Months 5-8)

Users who rely on income_desk for real money need deployment options beyond "run on my laptop."

#### 5a. Standalone Deployment

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Decouple from eTrading assumptions | Audit all code paths that assume eTrading context. Extract any eTrading-specific logic behind feature flags or config. Library must work identically standalone vs embedded | None | M | B1 |
| Docker image | `docker run -p 8080:8080 income-desk --api` -- pre-built image with all dependencies. Mount volume for config (.env, .workflow.md files). Multi-arch (amd64, arm64 for Mac M-series) | REST API (Phase 2b) | M | B1, B6 |
| Docker Compose for full stack | income-desk API + Redis (cache) + optional Postgres (outcome storage for calibration). One `docker compose up` for complete trading infrastructure | Docker image | M | B6 |
| Helm chart for Kubernetes | For users running on cloud Kubernetes clusters. Configurable replicas, resource limits, secrets management via K8s secrets | Docker image | L | B6 |

#### 5b. Cloud Deployment

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| AWS Lambda deployment guide | Package workflow APIs as Lambda functions behind API Gateway. Event-driven: CloudWatch cron triggers daily plan at market open. Guide + Terraform/CDK template | REST API | L | B6 |
| Google Cloud Run deployment | Containerized API on Cloud Run. Auto-scales to zero when market is closed. Cloud Scheduler for daily/weekly workflows. Guide + gcloud CLI commands | Docker image | M | B6 |
| Railway/Render one-click deploy | `Deploy to Railway` button in README for users who want hosted without managing infrastructure. Procfile + railway.json | REST API | S | B1 |

#### 5c. Multi-Tenant Support

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Tenant isolation model | Each tenant has: own broker credentials, own portfolio state, own risk profile, own workflow customizations. No data leakage between tenants. Design doc before implementation | REST API | M | B6 |
| Per-tenant credential vault | Encrypted credential storage per tenant. Support for AWS Secrets Manager, GCP Secret Manager, HashiCorp Vault, or local encrypted file. Never store credentials in plaintext | Tenant isolation | L | B6 |
| Per-tenant rate limiting | Broker API rate limits are per-account. Ensure tenant A's heavy usage doesn't exhaust tenant B's rate budget. Queue-based execution with per-tenant quotas | Tenant isolation | M | B6 |

#### 5d. Real-Time Operations

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Live position monitoring workflow | Continuous monitoring loop: check positions every N minutes, evaluate exit rules (pnl_rules.md), check Greeks limits (greeks_limits.md), trigger alerts. Currently one-shot; needs persistent mode | pnl_rules.md, greeks_limits.md | L | B4 |
| Alert system | Configurable alerts via webhook (Slack, Discord, Telegram), email (SendGrid/SES), or stdout. Alert types: regime change, stop loss approaching, margin warning, crash sentinel escalation | Monitoring workflow | L | B4 |
| Auto-adjustment workflows | When monitoring detects a position breaching rules, automatically generate adjustment TradeSpec. Human approval gate configurable: auto-execute (brave) or notify-and-wait (cautious) | Monitoring + alerts | XL | B4 |
| Market hours awareness | Workflows know when markets are open/closed. Pre-market prep runs at 9:00. Intraday monitoring runs 9:30-16:00. Post-market review runs at 16:15. No wasted broker API calls outside hours | market.md (Phase 4d) | M | B4 |
| Real-time P&L feed | WebSocket endpoint streaming portfolio P&L, per-position P&L, Greeks, regime status. Feed for dashboards (web, terminal, mobile). Update frequency: 5-second for active monitoring, 60-second for passive | WebSocket (Phase 2b) | L | B4 |

---

## Phase 6: Backtesting and Performance Validation (Credibility at Scale)

### Priority: P2
### Timeline: Q4 2026 - Q1 2027 (Months 6-10)

income_desk's philosophy is forward-testing. But for 100K downloads, users need to validate strategies before risking capital. Build historical replay that's honest about its limitations.

#### 6a. Historical Data Integration

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| yfinance historical OHLCV loader | Load daily OHLCV for any ticker for any date range. Cache locally in Parquet format. Replay through workflow runner as if it were live data. This exists partially; formalize the replay interface | None | M | B4 |
| Historical options chain snapshots | Partner with data providers (CBOE DataShop, OptionMetrics, or free: optionsdx.com) for historical options data. Without this, backtesting uses synthetic chains (clearly labeled SYNTHETIC) | None | L | B4 |
| Replay engine | Feed historical data day-by-day through the workflow runner. State accumulates: positions opened on day 5 are monitored on day 6. Regime detection runs on trailing window. Output: trade log with entry/exit/P&L | OHLCV loader | XL | B1, B4 |
| Walk-forward testing | Split history into train/test windows. Train HMM on window 1, test on window 2, slide forward. Report: regime accuracy, strategy performance, drawdown by window. Detects overfitting | Replay engine | L | B4 |

#### 6b. Performance Analytics

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Monte Carlo simulation on workflows | Run a workflow 1000 times with randomized entry/exit fills (within bid-ask spread), randomized regime transitions. Output: P&L distribution, max drawdown distribution, probability of ruin | Replay engine | L | B4 |
| Strategy comparison framework | Run two workflows against the same historical period, same starting capital. Output: Sharpe ratio, Sortino ratio, max drawdown, win rate, avg win/loss, risk-adjusted return. Side-by-side table | Replay engine | M | B4, B5 |
| Performance attribution | Break down P&L by: regime (how much did R1 trades contribute?), strategy type (IC vs vertical), ticker, month. Identify where edge comes from and where it leaks | Replay engine | M | B4 |
| Benchmark comparison | Compare workflow performance against buy-and-hold SPY, 60/40 portfolio, and risk-free rate. Calculate alpha, beta, information ratio. Users need to know if the complexity is worth it | Strategy comparison | M | B1 |

#### 6c. Calibration from Outcomes

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| POP calibration pipeline | Compare predicted POP at entry against actual win/loss. Bucket by POP range (60-70%, 70-80%, etc.). If 70% POP trades win only 55% of the time, adjust POP model. Pure function: input outcomes, output calibration factors | Benchmarking APIs (exists) | M | B4 |
| Regime accuracy tracking | For each regime assignment, track what actually happened: did R1 mean-revert? Did R3 trend? Accuracy by ticker, by time period. Feed into HMM retraining decisions | Benchmarking APIs | M | B4 |
| Automated weight recalibration | `calibrate_weights(outcomes)` exists as pure function. Build the pipeline: collect outcomes -> compute new weights -> validate against holdout -> apply if improvement > threshold. Guard against overfitting with regularization | POP calibration | L | B4 |

---

## Phase 7: Testing and Security for Production Users

### Priority: P1
### Timeline: Continuous, starting Q2 2026

Users trading real money need to trust the software. This is table-stakes, not a feature.

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Integration tests with real brokers | Nightly CI job (separate from unit tests) that connects to paper trading accounts for tastytrade + alpaca. Runs: authenticate, fetch quotes, place paper order, cancel order, fetch positions. Catches API changes before users do | CI infrastructure | L | B4 |
| Credential security audit | Third-party review of credential handling: how are API keys stored, transmitted, cached? Are there any paths where credentials could leak to logs, error messages, or telemetry? Publish audit results | None | M | B4, B6 |
| Fuzz testing on MD parser | Feed malformed .workflow.md, .scenario.md files to parser. Ensure no crashes, no code execution, no infinite loops. Parser must reject invalid input with clear errors, never silently accept garbage | None | M | B4 |
| Performance benchmarks | Measure and publish: regime detection latency (target: <500ms), workflow execution time (target: <5s for daily plan), memory usage (target: <200MB). CI fails if regression >20% | CI infrastructure | M | B4 |
| Rate limiting and retry logic | All broker API calls go through rate limiter respecting per-broker limits. Exponential backoff on transient failures. Circuit breaker after N consecutive failures. Currently partial; needs systematic audit and completion | None | L | B4 |
| Telemetry (opt-in) | Anonymous usage analytics: which workflows are popular, which brokers are used, common error patterns. Strictly opt-in, no PII, no trading data. Helps prioritize development. Use PostHog or similar privacy-first tool | REST API | M | B1 |
| Dependency security scanning | Dependabot + `pip-audit` in CI. Alert on vulnerable dependencies. Pin major versions of critical deps (pandas, numpy, hmmlearn). Automated PR for security patches | CI infrastructure | S | B4 |

---

## Phase 8: Community and Ecosystem (50K to 100K Users)

### Priority: P2
### Timeline: Q1-Q2 2027 (Months 10-14)

At 50K users, growth comes from community contributions, not just core development.

#### 8a. Strategy Marketplace

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Workflow sharing format | Standard package format for shareable workflows: `income_desk_strategy_xyz/` containing .workflow.md, .risk.md, .universe.md, README, and metadata.json (author, description, target account size, expected performance) | MD format v2 (Phase 3) | M | B5 |
| Community repository | GitHub repo `income-desk-strategies` where users submit workflows via PR. Review process: maintainer validates workflow runs without errors, risk profile is sane, no hardcoded credentials | Sharing format | M | B5 |
| Strategy installation | `income-desk install community/iron_condor_weekly` -- downloads workflow package to local workspace. `income-desk list-strategies` shows installed and available. Version pinning | Community repo | M | B5 |
| Strategy ratings and reviews | After community repo reaches 20+ strategies: add GitHub Discussions-based review system. Users report: "ran this for 3 months, 12% return, 8% max drawdown, R1 accuracy was good, R4 accuracy was poor" | Community repo | S | B5 |

#### 8b. Plugin System

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Plugin interface specification | Define extension points: custom workflow steps, custom data sources, custom assessors, custom gate checks, custom report formats. Each plugin type has an ABC with clear contract | None | L | B5 |
| Plugin discovery and loading | `income-desk install-plugin my-custom-assessor` -- pip-installable plugins that register via entry points. Runner discovers and loads at startup. Namespace isolation | Plugin interface | L | B5 |
| Plugin: custom data sources | Example plugin: load data from Quandl, Alpha Vantage, or Polygon.io instead of yfinance. Demonstrates the data source plugin interface | Plugin interface | M | B2, B5 |
| Plugin: custom report format | Example plugin: generate PDF trade reports, Excel position summaries, or HTML dashboards. Demonstrates the report plugin interface | Plugin interface | M | B5 |

#### 8c. Documentation and Community Infrastructure

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Documentation site (MkDocs Material) | Hosted at docs.income-desk.dev. Auto-generated API reference from docstrings. Tutorials, how-to guides, format specs, architecture overview. Search. Versioned docs per release | None | L | B1, B5 |
| Contributing guide expansion | Beyond current CONTRIBUTING.md: "How to add a broker" tutorial, "How to write a workflow" tutorial, "How to add an assessor" tutorial. Lower the barrier for first-time contributors | None | M | B5 |
| Issue templates with triage | Bug report (with version, broker, OS, steps to reproduce), feature request (with use case, expected behavior), broker integration request, format enhancement proposal. Auto-label on creation | None | S | B5 |
| Discord server | Channels: #general, #strategies, #broker-help, #india-market, #dev, #show-your-workflow. Bot that posts daily regime scan. Moderation guidelines | 500+ GitHub stars | M | B5 |
| Office hours / live streams | Monthly 30-minute live stream: walk through a real trading day with income_desk. Show regime scan, trade selection, sizing, execution. Answer questions. Record and post to YouTube | Discord | S | B1, B5 |

---

## Phase 9: Advanced Trading Features (Deepening the Moat)

### Priority: P3
### Timeline: Q2-Q3 2027 (Months 14-18)

Features that make income_desk the best options income tool, not just the most accessible one.

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Multi-leg strategy builder | Given a market view (bearish, range-bound, vol crush expected), generate optimal multi-leg structure: IC, butterfly, jade lizard, ratio spread. Score each by EV, margin efficiency, risk/reward | None | XL | B4 |
| Volatility surface modeling | Build vol surface from broker quotes (strike x expiry -> IV). Detect skew anomalies, term structure inversions, vol smile changes. Feed into strategy selection: steep skew -> sell puts, flat skew -> IC | Broker live data | XL | B4 |
| Earnings strategy engine | Historical earnings move analysis (from yfinance). Pre-earnings: sell premium if IV percentile > 80. Post-earnings: directional if surprise > 2 sigma. Earnings calendar integration | Historical data (Phase 6a) | L | B4 |
| Correlation matrix monitoring | Real-time correlation between portfolio positions. Alert when correlation increases (portfolio risk concentrating). Feed into position_limits.md enforcement | Live monitoring (Phase 5d) | L | B4 |
| Multi-market arbitrage detection | Cross-market opportunities: NIFTY vs SPY correlation, ADR spreads, currency-adjusted returns. For users with both US and India accounts | India + US broker support | L | B4 |
| Tax-aware exit optimization | Model tax impact of closing positions: short-term vs long-term gains, wash sale implications, tax-loss harvesting opportunities. US and India tax rules as configurable .compliance.md | compliance.md (Phase 4e) | XL | B6 |

---

## Phase 10: Enterprise and Scale (100K+ Downloads)

### Priority: P3
### Timeline: Q3-Q4 2027 (Months 18-24)

At 100K downloads, income_desk serves individual traders, small funds, and fintech companies embedding it.

| Item | Description | Depends On | Effort | Serves |
|------|-------------|-----------|--------|--------|
| Enterprise licensing | Dual license: MIT for individuals, commercial license for companies embedding income_desk in paid products. Revenue funds continued development | Legal review | M | B6 |
| SLA-grade reliability | 99.9% uptime for API server mode. Health check endpoints, graceful degradation, automatic failover between data sources. Runbook for operators | Docker + monitoring | XL | B6 |
| Multi-tenant SaaS mode | Full tenant isolation: separate databases, separate credential vaults, separate rate limits, separate billing. Admin dashboard for tenant management | Multi-tenant (Phase 5c) | XL | B6 |
| Audit and compliance module | SOC 2 Type II readiness. Immutable audit logs, access controls, data retention policies, encryption at rest. Required for institutional adoption | Audit trail (Phase 4e) | XL | B6 |
| White-label support | Fintech companies embed income_desk as their analytics engine with custom branding. Configurable: strategy names, risk labels, report templates | Plugin system (Phase 8b) | L | B6 |

---

## Download Growth Model

| Phase | Target Downloads | Key Driver | Timeline |
|-------|-----------------|------------|----------|
| Phase 1 | 0 -> 1,000 | Claude skill + Reddit/HN launch + "first trade in 5 min" | Q2 2026 |
| Phase 2 | 1K -> 5K | MCP server (any LLM), REST API (any language) | Q2-Q3 2026 |
| Phase 3-4 | 5K -> 15K | Rich MD format becomes a standard, community workflows | Q3-Q4 2026 |
| Phase 5 | 15K -> 30K | Docker one-click, cloud deploy, real-time monitoring | Q4 2026 |
| Phase 6 | 30K -> 50K | Backtesting + walk-forward gives credibility, blog posts cite results | Q4 2026-Q1 2027 |
| Phase 7 | (continuous) | Trust: security audit, broker integration tests, performance benchmarks | Ongoing |
| Phase 8 | 50K -> 80K | Strategy marketplace, plugin ecosystem, Discord community | Q1-Q2 2027 |
| Phase 9-10 | 80K -> 100K+ | Advanced features, enterprise adoption, white-label | Q2-Q4 2027 |

---

## Dependency Graph (Critical Path)

```
Phase 1 (Claude Skill + Guides)
    |
    v
Phase 2a (MCP Server) -----> Phase 2b (REST API) -----> Phase 5a (Docker)
    |                              |                          |
    v                              v                          v
Phase 2c (Cross-model)       Phase 5b (Cloud)           Phase 5c (Multi-tenant)
                                   |
Phase 3 (MD Enhancements)         |
    |                              v
    v                         Phase 5d (Real-time Ops)
Phase 4 (Industry Defs)           |
    |                              v
    v                         Phase 8 (Community)
Phase 6 (Backtesting)             |
    |                              v
    v                         Phase 10 (Enterprise)
Phase 9 (Advanced Trading)

Phase 7 (Security/Testing) -- runs in parallel with everything
```

---

## Effort Legend

| Size | Meaning | Approximate Time |
|------|---------|-----------------|
| S | Small | 1-2 days |
| M | Medium | 3-5 days |
| L | Large | 1-2 weeks |
| XL | Extra Large | 3-4 weeks |

---

## What's Explicitly NOT on This Roadmap

- **Backtesting-first philosophy** — income_desk is forward-testing by design. Phase 6 adds historical replay for validation, not for strategy discovery.
- **Mobile app** — focus on API + SDK and let others build mobile UIs.
- **Proprietary data feeds** — income_desk uses broker data (free with account) and yfinance (free). No Bloomberg/Refinitiv dependency.
- **Copy trading / social trading** — share strategies, not positions. No "follow this trader" features.
- **Crypto** — options on crypto are structurally different (24/7 markets, different margin models). Out of scope until the core platform is mature.
- **High-frequency trading** — income_desk is for income strategies with holding periods of days to weeks. Sub-second execution is not a goal.
