# market_analyzer --- User Manual

> Every trade suggestion is bespoke to YOUR portfolio, YOUR risk profile, YOUR capital. This is not a signal service --- it is a personal trading intelligence system.

Two traders with different accounts, different open positions, and different risk tolerances will get **different trade recommendations** from the same market data. The system does not say "this is a good trade." It says "this is a good trade **for you, right now, given what you already have.**"

---

## Table of Contents

- [Part 1: Getting Started](#part-1-getting-started)
- [Part 2: Trading Decision APIs](#part-2-trading-decision-apis)
- [Part 3: Features by Geography](#part-3-features-by-geography)
- [Part 4: Features by Purpose](#part-4-features-by-purpose)
- [Part 5: Flow Runners](#part-5-flow-runners)
- [Part 6: CLI Command Reference](#part-6-cli-command-reference)
- [Part 7: Python API Quick Reference](#part-7-python-api-quick-reference)
- [Part 8: Appendix](#part-8-appendix)

---

## Part 1: Getting Started

### 1.1 Installation

```bash
pip install market-analyzer
```

One install. TastyTrade, Alpaca, Dhan, FRED included. IBKR, Schwab, and Zerodha are optional extras:

```bash
pip install "market-analyzer[tastytrade]"   # US options (DXLink streaming)
pip install "market-analyzer[zerodha]"      # India NSE/NFO (Kite REST)
pip install "market-analyzer[fred]"         # Macro economic data from FRED
```

**Requirements:** Python 3.12 (hmmlearn has no 3.14 wheels yet).

```bash
# Development setup
py -3.12 -m venv .venv_312
.venv_312/Scripts/pip install -e ".[dev]"
```

### 1.2 First Run --- 60 Seconds to Your First Analysis

```bash
analyzer-cli
> regime SPY
> technicals SPY
> rank SPY QQQ IWM GLD TLT
```

No broker needed. yfinance provides free historical OHLCV data. Regime detection, technical analysis, screening, and ranking all work immediately with zero configuration. The first call takes 10-30 seconds (downloading data and training the HMM). Subsequent calls are instant (parquet cache).

**Example output:**

```
REGIME: SPY --- R2 (100%) High-Vol Mean Reverting
  Trend: bearish  |  Model age: 1 day  |  Stability: 2 flips in 20d
  Probabilities: R1=0.00  R2=1.00  R3=0.00  R4=0.00

REGIME: GLD --- R1 (100%) Low-Vol Mean Reverting
  Trend: none  |  Model age: 1 day  |  Stability: 0 flips in 20d

REGIME: QQQ --- R4 (96%) High-Vol Trending
  Trend: bearish  |  Model age: 1 day  |  Stability: 3 flips in 20d
```

### 1.3 Connect Your Broker

```bash
analyzer-cli --broker --paper   # Paper trading mode
analyzer-cli --broker           # Live mode
```

Connecting a broker upgrades every analysis with real-time quotes, Greeks, IV rank, and account data. Without a broker you can research and screen; with a broker you can execute.

**TastyTrade setup:**

```bash
cp tastytrade_broker.yaml.template tastytrade_broker.yaml
# Fill in credentials (or use env vars: TT_LIVE_SECRET, TT_LIVE_TOKEN)
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

**Zerodha setup** (India market):

```bash
pip install "market-analyzer[zerodha]"
cp zerodha_credentials.yaml.template zerodha_credentials.yaml
# Access token expires daily --- re-authenticate each morning
```

**After connecting:**

```bash
analyzer-cli --broker
> validate SPY                     # 10-check profitability gate
> kelly SPY 35000                  # Kelly criterion position sizing
> audit SPY                        # 4-level decision report card
> sentinel                         # Crash sentinel (GREEN/YELLOW/ORANGE/RED/BLUE)
```

### 1.4 Understanding Trust Levels

Every output from market_analyzer tells you how much to trust it. Three dimensions are evaluated:

**Dimension 1: Data Quality** --- Is the data accurate and fresh?

| Source | Trust | Meaning |
|--------|-------|---------|
| Broker live (DXLink/Kite) | HIGH | Real bid/ask, real Greeks, real IV |
| yfinance OHLCV (free) | MEDIUM | Historical daily bars --- reliable for regime and technicals |
| Estimated (heuristic) | LOW | The system guessed and tells you it guessed |
| None | ZERO | Data unavailable --- the system tells you it is missing |

**Dimension 2: Context Quality** --- Did you provide everything the system needs?

The same function with the same market data produces different trust levels depending on whether you passed portfolio state, IV rank, levels analysis, and earnings data. Full context = high trust. Partial context = reduced trust with explicit warnings about what is missing.

**Dimension 3: Fitness for Purpose** --- What can you DO with this output?

| Trust Level | What You Can Do | What You Cannot Do |
|-------------|-----------------|---------------------|
| **HIGH (80%+)** | Execute trades with real money | --- |
| **MEDIUM (50-79%)** | Paper trade, set alerts, screen candidates | Deploy real capital |
| **LOW (20-49%)** | Research, explore regimes, learn the system | Make any trading decision |
| **UNRELIABLE (<20%)** | Read documentation | Anything involving money |

```python
from market_analyzer import compute_trust_report

trust = compute_trust_report(
    has_broker=True, has_iv_rank=True, has_vol_surface=True,
    has_levels=True, regime_confidence=0.95,
)
print(trust.overall_trust)      # 0.92
print(trust.overall_level)      # "high"
print(trust.fit_for_summary)    # "Fit for ALL purposes including live execution"
```

For a deep dive, see `docs/TRUST_FRAMEWORK.md`.

### 1.5 Data Sources --- What Powers the Analysis

**Tier 1 --- Free (yfinance, default):** Historical OHLCV (2 years daily bars), options chain structure (strikes and expirations). No credentials needed.

**Tier 2 --- Broker (real-time):** Live quotes with bid/ask/mid, Greeks (delta/gamma/theta/vega), IV rank and percentile, account balance and buying power, intraday candles for ORB/0DTE.

**Tier 3 --- Economic (FRED, optional):** Yield curve, macro stress indicators for black swan detection. Free API key from fred.stlouisfed.org.

| Feature | Without Broker | With Broker |
|---------|---------------|-------------|
| Regime detection | Works | Works |
| Technicals (RSI, ATR, etc.) | Works | Works |
| Option quotes (bid/ask/mid) | Stale or zero | Real-time |
| Greeks | None | Real from broker |
| IV rank / IV percentile | None | From broker REST API |
| Intraday candles (ORB, 0DTE) | None | 5-minute bars |
| Account balance / buying power | None | Real from broker |
| **Fit for** | **Screening, research** | **Live execution** |

For full details on data interfaces, see `docs/DATA_INTERFACES.md`.

### 1.6 The Forward Testing Philosophy

market_analyzer does not have a backtesting engine. This is deliberate.

Backtesting gives false confidence --- it overfits to the past, assumes perfect fills, ignores commissions, and teaches traders to trust historical patterns that may never repeat. MA takes a different approach:

```
1. START SMALL      -> System protects you (validation gates, Kelly quarter-sizing)
2. TRADE REAL       -> 1 contract, real money, real fills, real emotions
3. RECORD OUTCOME   -> TradeOutcome captures everything: entry, exit, regime, P&L
4. SYSTEM LEARNS    -> calibrate_weights() adjusts ranking from YOUR real outcomes
5. SCALE UP         -> Kelly automatically increases sizing as win rate is proven
6. REPEAT           -> Each cycle makes the system more tuned to YOUR trading
```

A new user starts with proven defaults (regime-gated iron condors, 50% profit target, 2x stop). The validation gate (10 checks) and Kelly sizing protect capital during the learning phase. After 20-30 trades, `calibrate_weights()` has real data to work with. The system gets better over time from REAL outcomes, not from fitting to the past.

---

## Part 2: Trading Decision APIs

Every trading decision answers one of four questions: What to buy, When to buy, How much to buy, and When to exit. This section organizes all capabilities around those four questions, plus portfolio-level intelligence and assignment handling.

### 2.1 What to Buy --- Structure Selection

#### Regime Detection

Every analysis starts with regime. Regime determines which strategies are appropriate and which are forbidden.

```bash
> regime SPY GLD QQQ
```

```python
regime = ma.regime.detect("SPY", debug=True)
# -> RegimeResult: regime (R1-R4), confidence, trend_direction, commentary
```

| Regime | Name | What to Trade | What to Avoid |
|--------|------|--------------|---------------|
| R1 | Low-Vol Mean Reverting | Iron condors, strangles (theta) | Directional |
| R2 | High-Vol Mean Reverting | Wider wings, defined risk (selective theta) | Directional |
| R3 | Low-Vol Trending | Directional spreads | Heavy theta |
| R4 | High-Vol Trending | Risk-defined only, long vega | Theta selling |

**What it needs:** Historical OHLCV (2 years, from yfinance or DataService). No broker required.

**Model health indicators:**
- `regime.model_age_days` --- if > 60, model may be stale (retrain recommended)
- `regime.regime_stability` --- if > 4 flips in 20 days, model is churning
- `regime.data_gaps` --- warnings about confidence, staleness
- `regime.regime_probabilities` --- full probability vector (e.g., {R1: 0.05, R2: 0.65, R3: 0.05, R4: 0.25})

**Key insight:** The probability vector is the leading indicator. A 15% R4 probability while the label is still R1 is your early warning. Do not wait for the label to change.

#### Opportunity Assessment

Assess all 11 option plays for a single ticker. Each assessor returns a verdict (GO/CAUTION/NO_GO), a confidence score, a rationale, and a machine-readable `TradeSpec`.

```bash
> opportunity SPY
```

```python
ic = assess_iron_condor("SPY", regime, technicals, vol_surface)
# -> IronCondorOpportunity: verdict, confidence, rationale, trade_spec
```

**12 assessors available:**

| Assessor | Best Regime | What it Looks For |
|----------|-------------|-------------------|
| Iron condor | R1, R2 | Neutral market, range-bound, rich premiums |
| Iron butterfly | R2 | ATM straddle + wings, high IV + mean reversion |
| Calendar | R1, R2 | Front vs back month IV differential |
| Diagonal | R3 | Calendar with different strikes, mild trend |
| Ratio spread | R1 | Buy 1 ATM, sell 2 OTM (naked leg warning) |
| Credit spread | R1, R2 | Directional bias with defined risk |
| Zero DTE | R1, R2 | 0DTE with ORB integration, Iron Man for narrow ranges |
| LEAP | R3 | Long-dated directional (US only, not available for India) |
| Earnings | R1, R2 | IV crush harvest around earnings |
| Breakout | R3 | VCP, Bollinger squeeze, near resistance |
| Momentum | R3 | MACD crossover, RSI zone, MA alignment |
| Mean reversion | R1, R2 | RSI extreme, Bollinger bands, stochastic |

#### Ranking

Score and rank all opportunities across multiple tickers. The single most important command for finding trades.

```bash
> rank SPY GLD QQQ --debug --account 50000
> rank --preset income              # Scan built-in income universe (12 tickers)
> rank --preset nifty50             # Scan NIFTY 50 stocks
> rank --watchlist MA-Income        # Scan broker watchlist
```

```python
ranking = ma.ranking.rank(
    tickers=["SPY", "GLD", "QQQ"],
    skip_intraday=True,
    debug=True,
    iv_rank_map={"SPY": 45, "GLD": 32, "QQQ": 55},
)
# -> TradeRankingResult: top_trades sorted by composite_score
```

**Scoring formula:**
```
composite_score = verdict_score * confidence
                 + regime_alignment + phase_alignment
                 + income_bias_boost
                 - black_swan_penalty - macro_penalty - earnings_penalty
```

Each `RankedEntry` includes:
- `trade_spec` --- complete legs, strikes, expiration (ready to trade)
- `composite_score` --- 0-1 quality score
- `data_gaps` --- what is missing in the analysis
- `commentary` --- step-by-step reasoning (when debug=True)

#### Screening

Filter a universe of tickers by specific setup types.

```bash
> screen SPY GLD QQQ --watchlist MA-Income
```

**4 screens:**
- **Breakout:** VCP, Bollinger squeeze, near resistance
- **Momentum:** MACD crossover, RSI zone, MA alignment, ADX trend
- **Mean Reversion:** RSI extreme, Bollinger bands, stochastic
- **Income:** R1/R2 regime, neutral RSI, stable ATR

Liquidity filter (ATR < 0.3% auto-removed) and correlation dedup applied automatically.

#### Strategy Recommendation

Get a single strategy recommendation for a ticker based on current regime and technicals.

```bash
> strategy SPY
```

#### Universe --- What to Scan

MA ships with 10 built-in scanning universes. No broker required.

```bash
> scan_universe income          # 12 tickers (high options liquidity)
> scan_universe nifty50         # 43 NIFTY 50 stocks
> scan_universe india_fno       # 23 India F&O instruments
> scan_universe sector_etf      # 12 US sector ETFs
> scan_universe us_mega         # 17 US mega-cap equities
> scan_universe directional     # 31 liquid equities (US + India)
```

```python
tickers = ma.registry.get_universe(preset="income")
tickers = ma.registry.get_universe(market="INDIA", sector="finance")
```

85+ instruments with sector, options liquidity rating (high/medium/low), and scan group tags.

### 2.2 When to Buy --- Entry Levels and Timing

#### Entry Analysis (5 Functions)

The most comprehensive pre-entry intelligence. Five independent analyses in one command.

```bash
> entry_analysis SPY
```

| Function | What it Answers | Example |
|----------|----------------|---------|
| **Strike proximity** | Are strikes backed by support/resistance levels? | "Short put at 570 backed by SMA-200 at 568" |
| **Skew optimal** | Where is IV richest for selling premium? | "Put skew elevated --- sell put spread for richer credit" |
| **Entry score** | Enter now or wait for a better level? | "ENTER_NOW (RSI neutral, regime stable, within entry window)" |
| **Limit price** | What price to use: patient, normal, or aggressive? | "Patient: $1.65 / Normal: $1.80 / Aggressive: $1.92" |
| **Pullback alerts** | Where does the entry get better if you wait? | "SPY pullback to 572 = 15% better entry on IC" |

```python
from market_analyzer import (
    compute_strike_support_proximity, select_skew_optimal_strike,
    score_entry_level, compute_limit_entry_price, compute_pullback_levels,
)
```

#### Optimal DTE

Select the best days-to-expiration based on vol surface term structure.

```bash
> optimal_dte SPY
```

Uses the vol surface to find where theta decay is steepest relative to gamma risk. During IV normalization (e.g., post-crash recovery), the term structure is steep and front-month DTE often wins.

#### Profitability Gate (validate)

Before placing any trade, run the profitability gate. This answers one question: **is this trade actually profitable for a small account after fees, slippage, and real-world constraints?**

```bash
> validate SPY
> validate SPY --suite adversarial
> validate SPY --suite full
```

**Daily suite --- 7 checks:**

| Check | What it Catches | Threshold |
|-------|----------------|-----------|
| `commission_drag` | Fees eating your credit ($0.65 x 4 legs on a $0.50 IC is a loser) | PASS <10%, WARN 10-25%, FAIL >25% |
| `fill_quality` | Wide bid/ask means bad fills | PASS <=1.5%, WARN 1.5-3%, FAIL >3% |
| `margin_efficiency` | Low ROC = capital tied up for nothing | PASS >=15% annualized, WARN 10-15%, FAIL <10% |
| `pop_gate` | Probability of profit sufficient? | PASS >=65% POP |
| `ev_positive` | Expected value must be positive | PASS if EV > 0 |
| `entry_quality` | Right regime and timing? | PASS in entry window + regime match |
| `exit_discipline` | Defined profit target, stop, and DTE exit? | PASS if all three defined |

**Adversarial suite --- 3 additional checks:**

| Check | What it Tests | Threshold |
|-------|--------------|-----------|
| `gamma_stress` | IC if underlying moves 2-sigma in 24 hours | PASS risk:reward <5x |
| `vega_shock` | IC if VIX spikes 30% overnight | PASS loss <25% of credit |
| `breakeven_spread` | At what bid/ask spread does this trade become EV-negative? | PASS if breakeven >2% |

**Example output:**

```
DAILY VALIDATION --- SPY --- 2026-03-19
------------------------------------------
PASS  commission_drag       IC credit $1.80 covers $0.52 round-trip fees (drag: 7.1%)
PASS  fill_quality          Spread 1.2% --- survives natural fill
WARN  margin_efficiency     ROC 11.4% annualized --- marginal (target >=15%)
PASS  pop_gate              POP 71.4% >= 65% minimum
PASS  ev_positive           EV +$52 per contract
PASS  entry_quality         R1 regime, entry window open
PASS  exit_discipline       TP 50%, SL 2x credit, close <=21 DTE
------------------------------------------
RESULT: READY TO TRADE (6/7 passed, 1 warning)
```

**Decision rule:** `is_ready = True` when there are zero FAIL checks. Warnings are tradeable. A FAIL on `commission_drag` means the math does not work --- do not trade regardless of how good the setup looks.

```python
from market_analyzer import run_daily_checks, run_adversarial_checks

report = run_daily_checks(
    ticker="SPY", trade_spec=trade_spec, entry_credit=1.80,
    regime_id=1, atr_pct=0.85, current_price=580.0,
    avg_bid_ask_spread_pct=1.2, dte=35, rsi=52.0, iv_rank=42.0,
)

if report.is_ready:
    # Proceed to sizing
    pass

stress = run_adversarial_checks("SPY", trade_spec, 1.80, atr_pct=0.85)
```

#### Income Entry Confirmation

Quick check whether conditions favor income (theta) entries right now.

```bash
> income_entry SPY
```

```python
from market_analyzer import check_income_entry
entry = check_income_entry(
    iv_rank=45, iv_percentile=50, dte=35, rsi=50, atr_pct=1.2,
    regime_id=1, has_earnings_within_dte=False, has_macro_event_today=False,
)
# -> IncomeEntryCheck: confirmed (bool), score, conditions
```

#### Entry Window

Every `TradeSpec` carries entry window times. Only submit orders within the window --- outside it means unfavorable fills.

| Strategy | US Entry Window | India Entry Window |
|----------|----------------|-------------------|
| 0DTE | 09:45 - 14:00 ET | 09:30 - 13:30 IST |
| Income (IC, IFly, calendar) | 10:00 - 15:00 ET | 09:30 - 14:30 IST |
| Earnings | 10:00 - 14:30 ET | 09:30 - 14:00 IST |

### 2.3 How Much to Buy --- Position Sizing

#### Kelly Criterion Sizing

The primary sizing method. Accounts for win probability, payoff ratio, correlation, margin regime, and drawdown circuit breaker.

```bash
> kelly SPY 35000
```

```python
from market_analyzer import compute_kelly_fraction, compute_position_size

kelly = compute_kelly_fraction(win_prob=0.70, win_amount=80, loss_amount=420)
contracts = compute_position_size(
    pop_pct=0.70, max_profit=80, max_loss=420, capital=35000,
    risk_per_contract=500, wing_width=5.0, regime_id=1,
    exposure=portfolio_exposure, safety_factor=0.50,  # Half Kelly (default)
)
```

**The sizing pipeline:**

1. **Kelly fraction** --- mathematical optimal bet size from win rate and payoff
2. **Safety factor** --- half Kelly (0.50) for normal, quarter Kelly (0.25) post-crash
3. **Regime adjustment** --- R1=1.0x, R2=0.75x, R3=0.50x, R4=0.25x
4. **Confidence adjustment** --- scale down if HMM confidence < 80%
5. **Correlation deduction** --- correlated positions count as partially the same bet
6. **Margin check** --- ensure buying power can support the position
7. **Drawdown circuit breaker** --- 0-5% drawdown = full; 5-8% = 75%; 8-10% = 50%; >10% = HALT

#### Basic Position Size

Quick sizing without the full Kelly pipeline.

```bash
> size SPY 50000
```

Uses `lot_size` from the instrument (100 for US, 25 for NIFTY, 250 for RELIANCE, etc.).

#### Margin Analysis

Cash versus margin comparison for the position.

```bash
> margin SPY ic --width 5
```

```python
from market_analyzer import compute_margin_analysis
analysis = compute_margin_analysis(trade_spec, account_nlv=35000, regime_id=1)
```

#### Margin Buffer

Structure-based margin buffer calculation. How much cushion exists before a margin call.

```bash
> margin_buffer SPY
```

```python
from market_analyzer import compute_margin_buffer
buffer = compute_margin_buffer(trade_spec, account_nlv=35000, buying_power=24000)
```

#### Account Balance

Check real account balance and buying power (broker required).

```bash
> balance
```

### 2.4 When to Exit --- Exit Management

#### Exit Condition Monitoring

Check all 4 exit rules on an open position.

```bash
> monitor SPY 0.80 0.40 25
```

```python
from market_analyzer import monitor_exit_conditions
result = monitor_exit_conditions(
    trade_id="SPY-IC-001", ticker="SPY",
    structure_type="iron_condor", order_side="credit",
    entry_price=0.80, current_mid_price=0.40,
    contracts=1, dte_remaining=25, regime_id=1,
    profit_target_pct=0.50, stop_loss_pct=2.0, exit_dte=21,
    entry_regime_id=1, time_of_day=time(15, 30), lot_size=100,
)
# -> ExitMonitorResult: should_close, signals, pnl_pct, summary
```

**4 exit rules checked:**

1. **Profit target** --- close at 50% of max profit
2. **Stop loss** --- close if loss > 2x credit received
3. **DTE exit** --- close when <=21 DTE (gamma risk)
4. **Regime change** --- close if regime shifted from MR to trending

**Time-of-day escalation:**
- 0DTE after 15:00 ET -> force close (immediate)
- Tested position after 15:30 -> escalate to immediate

#### Exit Intelligence

Regime-contingent stops, trailing profit targets, and theta decay curves combined into one analysis.

```bash
> exit_intelligence SPY 10 0.30
```

**Regime-contingent stops:**

| Regime | Stop Multiplier | Rationale |
|--------|----------------|-----------|
| R1 | 2.0x credit | Normal swings |
| R2 | 3.0x credit | Wide mean-reversion swings |
| R3 | 1.5x credit | Trending --- tighter leash |
| R4 | 1.5x credit | Explosive --- tightest stops |

```python
from market_analyzer import compute_regime_stop, compute_time_adjusted_target, compute_remaining_theta_value
stop = compute_regime_stop(regime_id=2)  # 3.0x
target = compute_time_adjusted_target(dte_remaining=25, profit_target_pct=0.50)
theta = compute_remaining_theta_value(dte_remaining=25, entry_credit=1.80)
```

#### Trade Health Check

Comprehensive health assessment combining exit monitoring, position stress, and overnight risk.

```bash
> health SPY 0.80 0.55 30
```

```python
from market_analyzer import check_trade_health
health = check_trade_health(
    trade_id="SPY-IC-001", trade_spec=spec,
    entry_price=0.80, contracts=1, current_mid_price=0.55,
    dte_remaining=30, regime=regime, technicals=tech,
    time_of_day=time(15, 30),
)
# -> TradeHealthCheck: status, overall_action, overnight_risk
```

| Status | Action |
|--------|--------|
| `healthy` | Hold --- theta working |
| `tested` | Monitor closely, consider adjustment |
| `breached` | Adjust or close |
| `exit_triggered` | Close immediately |

**Includes overnight risk** (auto-checked after 15:00):
- 0DTE -> CLOSE_BEFORE_CLOSE (expires today)
- R4 + tested -> CLOSE_BEFORE_CLOSE
- Earnings tomorrow -> HIGH risk
- Safe + R1 -> LOW

#### Adjustment Recommendations

Deterministic adjustment decisions --- no menus, one action per situation.

```bash
> adjust SPY
```

```python
analysis = ma.adjustment.analyze(trade_spec, regime, technicals, vol_surface)
action = analysis.recommended_adjustments[0]  # Top recommendation = the action
```

**Decision tree (no human judgment):**

| Condition | Action |
|-----------|--------|
| SAFE + any regime | DO_NOTHING |
| TESTED + R1/R2 | DO_NOTHING (swings revert) |
| TESTED + R3 | ROLL_AWAY |
| TESTED + R4 | CLOSE_FULL |
| BREACHED + R1/R2 | ROLL_AWAY |
| BREACHED + R3/R4 | CLOSE_FULL |
| MAX_LOSS | CLOSE_FULL (always) |

Adjustments by structure: IC gets roll_away/narrow_untested/convert_to_diagonal, credit spread gets roll, ratio gets add_wing, straddle gets add_wing/close_tested.

#### Exit Plan Display

Show the full exit plan for a position including profit target, stop, DTE exit, and regime-contingent rules.

```bash
> exit_plan SPY
```

### 2.5 Portfolio-Level Intelligence

#### Crash Sentinel

The single most important pre-market check. Aggregates VIX, regime probabilities, breadth, and macro into one signal.

```bash
> sentinel
```

```python
from market_analyzer import assess_crash_sentinel
signal = assess_crash_sentinel(regimes, vix_level, breadth_data, macro_regime)
```

| Signal | Color | Action |
|--------|-------|--------|
| ALL_CLEAR | GREEN | Trade normally |
| CAUTION | YELLOW | Reduce position sizes by 25% |
| WARNING | ORANGE | Reduce by 50%, defined risk only, no new entries |
| DANGER | RED | NO TRADING --- protect capital, close positions |
| RECOVERY | BLUE | Post-crash stabilization --- start deploying (quarter Kelly) |

#### Decision Audit

4-level report card that grades every dimension of a trade decision. The final gatekeeper before execution.

```bash
> audit SPY
```

```python
from market_analyzer import audit_decision
audit = audit_decision(
    ticker="SPY", trade_spec=spec, regime=regime, technicals=tech,
    levels=levels, portfolio_exposure=exposure, account_nlv=35000,
)
```

**Output example:**

```
DECISION AUDIT: 85/100 B+ --- APPROVED
  Legs: 90/100 A (strikes backed by SMA-200 + swing support)
  Trade: 82/100 B (POP 72%, EV +$52, 4.3% commission drag)
  Portfolio: 88/100 B+ (2/5 slots, 0.15 correlation, 12% risk deployed)
  Risk: 92/100 A (1 contract, 1.4% of NLV, Kelly aligned)
```

#### Portfolio Risk Dashboard

Full 7-dimension risk picture. Check before placing ANY new trade.

```bash
> risk
```

```python
from market_analyzer import compute_risk_dashboard, PortfolioPosition

dashboard = compute_risk_dashboard(
    positions=portfolio_positions,
    account_nlv=50000, peak_nlv=52000, regime_id=2,
)
```

**7 risk dimensions:**

| Dimension | What it Checks | Gate |
|-----------|---------------|------|
| Expected Loss | ATR-based worst-case 1-day loss | Loss > 5% NLV -> reduce size |
| Greeks | Net delta, theta, vega vs limits | Excessive exposure -> hedge |
| Strategy | >50% in one strategy type? | Diversify strategy mix |
| Directional | Net bullish/bearish score | >0.5 -> concentration alert |
| Correlation | Positions moving together? | Corr > 0.85 -> same trade |
| Drawdown | Current NLV vs peak | >10% drawdown -> HALT ALL TRADING |
| Macro | Macro regime from research | DEFLATIONARY -> halt |

**Master gate:** `dashboard.can_open_new_trades` --- False if any critical gate fails.

#### Stress Testing

"What happens to my portfolio if the market crashes 5% tomorrow?"

```bash
> stress_test                       # Full suite (7 scenarios)
> stress_test flash_crash           # Single scenario
```

```python
from market_analyzer import run_stress_suite, run_stress_test, get_predefined_scenario

suite = run_stress_suite(positions, account_nlv=50000)
print(suite.summary)
# -> "Stress tested 7 scenarios | Worst: Flash Crash (-8.2%) | Survives all: YES"
```

**13 predefined scenarios:**

| Scenario | Price | Vol | Simulates |
|----------|-------|-----|-----------|
| Market -1% | -1% | +10% | Mild selloff |
| Market -3% | -3% | +30% | Significant drop |
| Market -5% | -5% | +60% | Sharp selloff |
| Market -10% | -10% | +150% | Crash |
| Market +3% | +3% | -20% | Strong rally |
| VIX Spike 50% | --- | +50% | Volatility shock |
| VIX Doubles | --- | +100% | Vol explosion |
| Flash Crash | -7% | +200% | 2015-style |
| Black Monday | -20% | +300% | 1987 scenario |
| COVID March | -12% | +200% | March 2020 |
| India Crash | -5% | +80% | India-specific + INR weakness |
| Fed Surprise | -2% | +20% | Unexpected hawkish signal |
| Rate Shock | -2% | +15% | 10Y yield +50bp |

**Capital preservation rule:** If `suite.survives_all == False` -> reduce positions until it does.

### 2.6 Assignment and Wheel Strategy

#### Handle Assignment Event

When you get assigned on a short option, MA tells you exactly what to do next.

```bash
> assignment SPY 570 put
```

```python
from market_analyzer import handle_assignment
result = handle_assignment(ticker="SPY", strike=570.0, option_type="put",
                            current_price=565.0, regime_id=1)
```

#### Assignment Risk Warning

Pre-assignment warning for open positions. Especially important for US American-style options near dividends.

```bash
> assignment_risk SPY
```

```python
from market_analyzer import assess_assignment_risk
risk = assess_assignment_risk(ticker="SPY", trade_spec=spec, current_price=580.0,
                               days_to_expiry=5, days_to_dividend=3)
```

#### Cash-Secured Put Analysis

Analyze a CSP before selling it. Shows yield, assignment probability, and effective cost basis.

```bash
> csp IWM 240 2.50 30
```

```python
from market_analyzer import analyze_cash_secured_put
csp = analyze_cash_secured_put("IWM", strike=240, premium=2.50, dte=30, regime_id=1)
```

#### Covered Call After Assignment

After getting assigned shares, analyze the best covered call to sell.

```bash
> covered_call IWM 240
```

```python
from market_analyzer import analyze_covered_call
cc = analyze_covered_call("IWM", cost_basis=240.0, current_price=238.0, regime_id=1)
```

#### Wheel Strategy

The full wheel: sell put -> get assigned -> sell covered call -> called away -> repeat.

```bash
> wheel AAPL
```

```python
from market_analyzer import analyze_wheel_strategy, decide_wheel_action, WheelPosition

wheel = analyze_wheel_strategy("AAPL", current_price=227.0, iv=0.25, regime_id=1)
# -> put yield 37%/yr, call yield 36%/yr, effective basis 7% below market

decision = decide_wheel_action(position, regime_id=1)
# -> SELL_CALL at $227 for ~$7.72 premium (35d)
```

Best in R1/R2 (mean-reverting, rich premiums). Avoid in R4 (explosive moves = assignment at bad prices).

#### Rate Risk

Interest rate sensitivity analysis for rate-sensitive tickers.

```bash
> rate_risk SPY TLT GLD XLU
```

```python
from market_analyzer import assess_rate_risk, assess_portfolio_rate_risk
risk = assess_rate_risk("TLT", ohlcv, tnx_ohlcv, regime_id=1)
portfolio_risk = assess_portfolio_rate_risk(positions, tnx_ohlcv)
```

---

## Part 3: Features by Geography

### 3.1 US Market

**Supported brokers:** TastyTrade (DXLink streaming), Alpaca (free tier for paper), IBKR (optional), Schwab (optional)

**Key characteristics:**

| Aspect | Details |
|--------|---------|
| Exercise style | American (can be assigned anytime) |
| Lot size | 100 (all equities and ETFs) |
| Trading hours | 9:30 AM - 4:00 PM ET |
| 0DTE support | Yes (SPY, QQQ, IWM have daily expirations) |
| Options chain | Full from broker or yfinance |
| LEAPs | Yes (1-3 years out) |
| Multi-leg orders | Atomic execution (all legs fill or none) |
| Default tickers | SPX, QQQ, IWM, GLD, TLT |
| VIX | ^VIX |

**Assignment risk is real for US options.** Any short American-style option can be assigned at any time, especially near dividends and near expiration. Use `assignment_risk` to monitor.

**0DTE with ORB integration:** The zero-DTE assessor waits 30 minutes after open for the Opening Range to form, then makes a systematic decision:

- Narrow ORB (< 0.3% of price) -> Iron Man (profits from breakout in either direction)
- Wide ORB (> 1.5%) -> Standard short IC (collect theta within range)
- Directional bias + confirming regime -> Directional spread above/below ORB

### 3.2 India Market

**Supported brokers:** Dhan, Zerodha (Kite Connect)

**Delayed data available via eTrading backend --- no account needed for research.**

**Key characteristics:**

| Aspect | Details |
|--------|---------|
| Exercise style | European (assignment only at expiry) |
| Lot sizes | NIFTY=25, BANKNIFTY=15, FINNIFTY=25, SENSEX=10 |
| Strike intervals | NIFTY=50, BANKNIFTY=100 (from market registry) |
| Trading hours | 9:15 AM - 3:30 PM IST |
| Expiry days | NIFTY=Thursday, BANKNIFTY=Wednesday, FINNIFTY=Tuesday |
| 0DTE support | Yes (weekly expiries) |
| LEAPs | No (max ~90 days) |
| Multi-leg orders | Single-leg execution (use `leg_plan` for safe ordering) |
| Default tickers | NIFTY, BANKNIFTY, RELIANCE, TCS, INFY |
| VIX | ^INDIAVIX |

**European exercise = no early assignment risk.** This is a significant advantage for income strategies --- you never get assigned before expiry.

**India stock options have limited depth.** Wide spreads, monthly-only expiry. MA automatically recommends cash equity trades instead of options for India stocks:

```
RELIANCE breakout -> EQ bullish . defined
  Action: BUY 1 lot (250 shares) at Rs1,380
  Stop: Rs1,326 (1.5 ATR)
  Target: Rs1,454 (2.0 ATR, R:R 1.33)
```

**India leg execution:** Multi-leg orders execute one leg at a time. Always buy protective legs BEFORE selling short legs.

```bash
> leg_plan NIFTY ic
```

```
Execution Order:
  1. BTO NIFTY 22300P  [SAFE]      -- long put wing (protective)
  2. BTO NIFTY 22800C  [SAFE]      -- long call wing (protective)
  3. STO NIFTY 22500P  [MODERATE]  -- short put (covered by wing)
  4. STO NIFTY 22600C  [MODERATE]  -- short call (covered by wing)

Abort rule: If any BUY fails -> ABORT. Never sell short without protective wing.
```

**India-specific configuration in MA:**
- LEAP assessor returns NO_GO for all India tickers
- Calendar/diagonal assessors enforce max 90-day DTE
- Exit notes include "no assignment risk" for cash-settled European options
- Macro context includes India VIX (^INDIAVIX) and RBI MPC dates

### 3.3 Multi-Market

#### Cross-Market Analysis (US -> India)

US closes at 4:00 PM ET = 1:30 AM IST. India opens at 9:15 AM IST. US closing behavior predicts India opening.

```bash
> crossmarket
> india_context
```

```python
from market_analyzer import analyze_cross_market
cm = analyze_cross_market("SPY", "NIFTY", us_ohlcv, india_ohlcv,
                           us_regime_id, india_regime_id)
```

| Field | Meaning |
|-------|---------|
| `correlation_20d` | How much India moves with US (0-1) |
| `predicted_india_gap_pct` | Expected India opening gap based on US close |
| `prediction_confidence` | R-squared of the prediction model |
| `sync_status` | SYNCHRONIZED / DIVERGENT / LEADING / LAGGING |

**Signals generated:**
- US closes -2%+ -> "crash_warning: India likely gap-down"
- US closes +2%+ -> "rally_signal: India likely gap-up"
- Both R4 -> "regime_sync_risk: correlated risk amplified"

#### Currency Exposure

For traders in both US and India markets.

```bash
> currency 100000 INR USD --entry-rate 83.0
> exposure
```

```python
from market_analyzer import compute_currency_pnl
pnl = compute_currency_pnl(
    ticker="NIFTY", trading_pnl_local=5000,
    position_value_local=500000,
    local_currency="INR", base_currency="USD",
    fx_rate_at_entry=83.0, fx_rate_current=84.5,
)
# -> NIFTY: trade $59 + FX -$53 = $6 total (FX +1.8% against you)
```

#### Full Macro Research Report

The most comprehensive pre-market analysis --- covers 22 assets across equities, bonds, commodities, currencies, and volatility.

```bash
> research                      # Daily
> research weekly               # Weekly summary
> research monthly --fred-key YOUR_KEY   # With economic fundamentals
```

```python
from market_analyzer import generate_research_report, RESEARCH_ASSETS
data = {ticker: ds.get_ohlcv(ticker) for ticker in RESEARCH_ASSETS}
report = generate_research_report(data, "daily", fred_api_key=None, spy_pe=26.3)
```

**Macro regime classification:**
- **RISK_ON:** Stocks up + credit tightening + VIX down + gold flat
- **RISK_OFF:** Stocks down + gold/bonds up + VIX elevated
- **STAGFLATION:** Stocks down + yields up + gold/oil up
- **REFLATION:** Stocks up + yields up + oil/copper up
- **DEFLATIONARY:** Everything falling (liquidity crisis)

**22 assets tracked:** SPY, QQQ, IWM, DIA (US equity) | NIFTY, BANKNIFTY (India) | EFA, EEM (global) | GLD, SLV, USO, COPX (commodities) | TLT, SHY, TNX, TIP (bonds) | HYG, LQD (credit) | UUP (dollar) | VIX, VIX3M, India VIX (volatility)

**14 correlation pairs tracked** with divergence detection.

---

## Part 4: Features by Purpose

### 4.1 For Live Trading (Trust: HIGH, broker required)

This is the full systematic trading pipeline. Every step is gated, sized, and audited.

**1. Pre-market:**
```bash
> sentinel                          # Market health signal
> context                          # Environment assessment
> regime SPY QQQ IWM GLD TLT      # Regime scan
> rank SPY IWM GLD --debug         # Rank opportunities
```

**2. Entry:**
```bash
> validate SPY                     # 10-check profitability gate
> entry_analysis SPY               # 5-function entry intelligence
> kelly SPY 35000                  # Kelly criterion sizing
> audit SPY                        # 4-level decision report card --- must be APPROVED
```

**3. Monitoring (midday):**
```bash
> health SPY                       # Trade health + overnight risk
> monitor SPY 0.80 0.40 25        # Exit condition check
> exit_intelligence SPY 10 0.30    # Regime stop + trailing target + theta decay
```

**4. Adjustment:**
```bash
> adjust SPY                       # Deterministic adjustment recommendation
> assignment_risk SPY              # Pre-assignment warning
```

**5. Close:** Monitoring produces closing `TradeSpec` automatically when exit conditions trigger.

### 4.2 For Paper Trading (Trust: MEDIUM, free broker tier)

Same flow as live trading but with delayed quotes. Connect Alpaca (free tier) or TastyTrade paper mode.

```bash
analyzer-cli --broker --paper
```

Record outcomes and feed them back into the system:

```python
from market_analyzer import calibrate_weights, TradeOutcome

outcomes = [
    TradeOutcome(ticker="SPY", strategy="iron_condor",
                 entry_date=date(2026, 3, 11), exit_date=date(2026, 3, 18),
                 entry_credit=1.80, exit_debit=0.90,
                 max_profit=180, max_loss=320,
                 regime_at_entry=RegimeID.R1, actual_pop=1,
                 exit_reason="profit_target"),
]

new_weights = calibrate_weights(outcomes)
# -> Weight adjustments per (regime, strategy) cell
```

After 20-30 trades, the system is calibrated to YOUR outcomes.

### 4.3 For Research and Screening (Trust: LOW, no broker needed)

Everything in this category works immediately after install. No broker, no credentials, no setup.

```bash
> regime SPY GLD QQQ TLT           # Understand market structure
> technicals SPY                    # 25+ indicators
> vol SPY                          # Volatility surface analysis
> levels SPY                       # Support/resistance from 21 sources
> research                         # Full macro research (22 assets)
> stress                           # Black swan / tail risk
> rate_risk SPY TLT GLD            # Interest rate sensitivity
> stock RELIANCE --horizon long    # Single stock analysis (5 strategies)
> stock_screen --strategy value --preset nifty50  # Screen India value stocks
```

**Technical indicators available:**

| Indicator | Trading Use |
|-----------|-------------|
| RSI | Overbought (>70) / Oversold (<30) |
| ATR / ATR% | Volatility level, position sizing |
| MACD | Momentum direction |
| Bollinger Bands | Squeeze = breakout setup |
| Stochastic | Short-term momentum, entry timing |
| ADX | Trend strength (>25 trending, <20 ranging) |
| Fibonacci | Retracement levels (38.2%-78.6%) |
| Donchian | 20-day high/low breakout |
| Keltner | ATR-based bands + squeeze detection |
| Pivot Points | PP, S1-S3, R1-R3 |
| VWAP | Volume-weighted mean reversion anchor |
| VCP | Volatility Contraction Pattern |
| Smart Money | Order blocks, fair value gaps |

**Levels analysis** clusters support/resistance from 21 sources (swing highs/lows, SMA 20/50/200, EMA 9/21, Bollinger bands, VWMA, VCP pivot, order blocks, fair value gaps, pivot points), weighted by conviction.

### 4.4 For Education and Learning

Use MA to understand options trading concepts with real market data.

```bash
> context                          # Understand market environment labels
> regime SPY GLD QQQ               # See how different instruments have different regimes
> opportunity SPY                  # Explore all 11 option structures with explanations
> strategy SPY                     # See why specific strategies are recommended
> optimal_dte SPY                  # Understand theta decay and DTE selection
> exit_intelligence SPY 10 0.30    # Explore exit scenarios
> pop SPY 0.80 iron_condor        # Understand probability of profit
> validate SPY                     # See what profitability checks look like
```

Every command supports `--debug` for step-by-step reasoning.

### 4.5 Equity Research and Capital Deployment

For core portfolio construction --- especially India where options depth is limited.

#### Single Stock Analysis

```bash
> stock RELIANCE --horizon long
> stock AAPL --horizon medium
```

**5 strategies scored per stock:**

| Strategy | What it Looks For | Best For |
|----------|------------------|----------|
| Value | Low P/E, low P/B, high dividend, strong balance sheet | Beaten-down quality |
| Growth | High revenue/EPS growth, expanding margins, low PEG | Tech, pharma, consumer |
| Dividend | High sustainable yield, low payout, growing dividends | Income generation |
| Quality + Momentum | High ROE + positive price momentum (GARP) | Core holdings |
| Turnaround | Down 30%+ from high with improving fundamentals | Contrarian, higher risk |

#### Stock Screening

```bash
> stock_screen --strategy value --preset nifty50 --market INDIA
```

#### Capital Deployment

For deploying a large cash position systematically over 6-18 months.

```bash
> valuation NIFTY                  # Is the market cheap?
> deploy 500000 --market India --months 12   # How much per month?
> allocate --market India --regime risk_off   # Asset allocation
> rebalance                        # When to adjust
> leap_vs_stock SPY                # LEAP vs stock comparison (US only)
```

**Valuation zones:**

| Zone | Score | Action |
|------|-------|--------|
| Deep Value | < -0.5 | Accelerate deployment +30% |
| Value | -0.5 to -0.2 | Accelerate +15% |
| Fair | -0.2 to +0.2 | Deploy at base rate |
| Expensive | +0.2 to +0.5 | Decelerate -30% |
| Bubble | > +0.5 | Decelerate -50%, hold cash |

### 4.6 Futures Trading

MA tracks 13 futures instruments and provides analysis of basis, term structure, roll decisions, and futures options.

```bash
> registry ES                      # Futures instrument info
```

| Ticker | Name | Multiplier | Market |
|--------|------|-----------|--------|
| ES | S&P 500 E-mini | $50/point | US |
| NQ | Nasdaq 100 E-mini | $20/point | US |
| YM | Dow E-mini | $5/point | US |
| RTY | Russell 2000 | $50/point | US |
| CL | Crude Oil | $1,000/barrel | US |
| GC | Gold | $100/oz | US |
| SI | Silver | $5,000/oz | US |
| ZB | 30Y Treasury Bond | $1,000/point | US |
| ZN | 10Y Treasury Note | $1,000/point | US |
| NG | Natural Gas | $10,000/mmBtu | US |
| NIFTY_FUT | NIFTY 50 | Rs25/point | India |
| BANKNIFTY_FUT | Bank NIFTY | Rs15/point | India |
| FINNIFTY_FUT | Fin NIFTY | Rs40/point | India |

```python
from market_analyzer import analyze_futures_basis, analyze_term_structure, decide_futures_roll
from market_analyzer import analyze_futures_options, estimate_futures_margin, generate_futures_report
```

**Always use defined risk on futures** (iron condors, not naked strangles) unless you have significant experience and capital. A 5% overnight gap in ES = $13,000 P&L per contract.

---

## Part 5: Flow Runners

Recommended command sequences for common trading scenarios.

### 5.1 Morning Pre-Market Flow

```bash
analyzer-cli --broker
> sentinel                          # Market health signal (GREEN/YELLOW/ORANGE/RED/BLUE)
> context                          # Environment assessment + tradeable instruments
> regime SPY QQQ IWM GLD TLT      # Regime scan across watchlist
> rank SPY IWM GLD --debug         # Rank opportunities with commentary
> validate SPY                     # 10-check profitability gate on best candidate
> entry_analysis SPY               # 5-function entry intelligence
> kelly SPY 35000                  # Position sizing (Kelly criterion)
> audit SPY                        # Final 4-level decision --- must be APPROVED
```

### 5.2 Midday Position Monitoring Flow

```bash
> health SPY                       # Trade health + position stress + overnight risk
> exit_intelligence SPY 10 0.30    # Regime stop + trailing target + theta decay
> assignment_risk SPY              # Check for assignment warning (US only)
> sentinel                         # Has the market health signal changed?
```

### 5.3 End of Day Flow

```bash
> sentinel                         # Final signal check
> risk                            # Portfolio risk dashboard (7 dimensions)
> stress_test                     # Run stress scenarios
> rate_risk SPY TLT GLD           # Rate risk check (if holding rate-sensitive)
> overnight SPY --dte 14 --status tested   # Overnight risk assessment
```

### 5.4 Post-Crash Recovery Flow

See `docs/CRASH_PLAYBOOK.md` for the complete playbook. Key sequence:

```bash
> sentinel                         # Wait for BLUE signal (recovery)
> regime SPY QQQ IWM GLD TLT      # Check R4 -> R2 transition
> rank GLD TLT --debug            # Uncorrelated tickers FIRST
> validate GLD                     # Full gate with elevated IV
> kelly GLD 35000                  # Quarter Kelly (safety_factor=0.25)
> audit GLD                        # Must be APPROVED
```

**Post-crash rules:**
- Max 3 positions (not 5) --- leave room for surprises
- Max 15% of NLV at risk (not 25%)
- 5% drawdown circuit breaker (not 10%)
- Quarter Kelly sizing
- 21 DTE max (not 35) --- shorter exposure to tail risk
- 3.0x stops in R2 (mean-reversion swings are WIDE)
- Uncorrelated first: GLD + TLT before SPY + IWM
- Do not touch QQQ until R2 with 80%+ confidence

**The money is in the first 6 months of recovery.** VIX at 35 means premiums are 2-3x normal. A 5-wide SPY IC that normally collects $1.20 now collects $3.00-$4.00.

### 5.5 Wheel Strategy Flow

```bash
> csp IWM 240 2.50 30             # Analyze cash-secured put
> validate IWM                     # Profitability gate
> kelly IWM 35000                  # Size the CSP
# --- After assignment: ---
> assignment IWM 240 put           # Handle assignment event
> covered_call IWM 240             # Analyze covered call on assigned shares
```

### 5.6 India Market Flow

```bash
analyzer-cli --broker              # Connect Dhan or Zerodha
> regime NIFTY BANKNIFTY           # India regime detection
> crossmarket                      # US -> India overnight analysis
> india_context                    # India-specific context
> rank NIFTY BANKNIFTY             # Rank India opportunities
> validate NIFTY                   # Gate check (European exercise noted)
> assignment_risk NIFTY            # European = no early assignment risk
> leg_plan NIFTY ic                # Safe single-leg execution order
```

### 5.7 India Expiry Day Flow

India options expire weekly --- NIFTY on Thursday, BANKNIFTY on Wednesday, FINNIFTY on Tuesday.

```bash
> context                          # Checks india_weekly_expiry_today
> regime BANKNIFTY                 # Check regime (R4 = do nothing)
> setup orb BANKNIFTY              # ORB analysis after first 30 minutes
> opportunity BANKNIFTY            # 0DTE is the only structure (expires today)
```

Expiry day dynamics: ATM options have extreme gamma, OTM options decay 3x faster than normal. Enter by 10:00 AM IST.

### 5.8 Weekly Calibration (Weekend)

```bash
# Feed week's outcomes into the learning system
```

```python
from market_analyzer import calibrate_weights, calibrate_pop_factors
from market_analyzer import build_bandits, optimize_thresholds, detect_drift

# Step 1: Calibrate ranking weights from real outcomes
new_weights = calibrate_weights(outcomes)

# Step 2: Calibrate POP factors by regime
factors = calibrate_pop_factors(outcomes, min_trades_per_regime=10)
# Default: {R1: 0.40, R2: 0.70, R3: 1.10, R4: 1.50}
# Calibrated from YOUR data replaces defaults

# Step 3: Update strategy bandits (Thompson sampling)
bandits = build_bandits(outcomes)
selected = select_strategies(bandits, regime_id=1, available_strategies, n=5)

# Step 4: Detect drift (win rate dropping?)
alerts = detect_drift(outcomes, window=20)
# WARNING: >15pp drop -> reduce allocation 50%
# CRITICAL: >25pp drop -> suspend this (regime, strategy) cell

# Step 5: Optimize thresholds
optimized = optimize_thresholds(outcomes, current=ThresholdConfig())
```

---

## Part 6: CLI Command Reference

### All Commands by Category

**Market Analysis (12 commands):**

| Command | What it Does |
|---------|-------------|
| `context` | Market environment assessment (risk-on/cautious/defensive/crisis) + tradeable instruments |
| `regime TICKERS` | Regime detection (R1-R4) with probabilities and confidence |
| `technicals TICKER` | 25+ technical indicators snapshot |
| `vol TICKER` | Volatility surface analysis (term structure, skew, IV differential) |
| `levels TICKER` | Support/resistance from 21 sources, clustered and weighted |
| `macro` | Macro calendar (FOMC, CPI, NFP, PCE, OpEx, VIX settlement) |
| `macro_indicators` | Bond market, credit spreads, dollar strength, inflation expectations |
| `research [daily/weekly/monthly]` | Full 22-asset macro research report |
| `stress` | Black swan alert (NORMAL/ELEVATED/HIGH/CRITICAL) |
| `rate_risk TICKERS` | Interest rate sensitivity analysis |
| `crossmarket` | US -> India cross-market analysis and gap prediction |
| `india_context` | India-specific context (VIX, FII flows, NIFTY-SPY correlation) |

**Opportunity Discovery (7 commands):**

| Command | What it Does |
|---------|-------------|
| `screen TICKERS` | Filter by setup type (breakout, momentum, MR, income) |
| `rank TICKERS [--debug] [--account N]` | Rank and score all opportunities across tickers |
| `opportunity TICKER` | Assess all 11 option plays for one ticker |
| `setup TYPE TICKER` | Price-based setups (breakout, momentum, mr, orb, all) |
| `strategy TICKER` | Strategy recommendation based on regime + technicals |
| `scan_universe PRESET` | Scan built-in universe (income, nifty50, sector_etf, etc.) |
| `registry TICKER` | Instrument info (lot size, strike interval, settlement, exercise) |

**Trade Entry (8 commands):**

| Command | What it Does |
|---------|-------------|
| `validate TICKER [--suite TYPE]` | 7-10 check profitability gate (daily, adversarial, full) |
| `entry_analysis TICKER` | 5-function entry intelligence (strike proximity, skew, score, price, pullback) |
| `entry TICKER` | Income entry confirmation |
| `optimal_dte TICKER` | DTE optimization from vol surface term structure |
| `pop TICKER CREDIT STRUCTURE` | Probability of profit + expected value + risk:reward |
| `income_entry TICKER` | Quick income entry check (IV rank, DTE, RSI, regime) |
| `quality TICKER STRUCTURE` | Execution quality gate (spread width, OI, volume) |
| `wizard` | Guided setup wizard for broker connection |

**Position Sizing (5 commands):**

| Command | What it Does |
|---------|-------------|
| `kelly TICKER CAPITAL` | Kelly criterion sizing with regime + correlation + drawdown |
| `size TICKER CAPITAL` | Basic position size calculation |
| `margin TICKER STRUCTURE [--width N]` | Cash vs margin analysis |
| `margin_buffer TICKER` | Structure-based margin buffer (how much cushion before margin call) |
| `balance` | Account balance and buying power from broker |

**Decision Making (2 commands):**

| Command | What it Does |
|---------|-------------|
| `audit TICKER` | 4-level decision report card (legs + trade + portfolio + risk) |
| `sentinel` | Crash sentinel (GREEN/YELLOW/ORANGE/RED/BLUE) |

**Position Monitoring (6 commands):**

| Command | What it Does |
|---------|-------------|
| `monitor TICKER ENTRY CURRENT DTE` | Exit condition check (profit target, stop, DTE, regime) |
| `health TICKER ENTRY CURRENT DTE` | Full health check + overnight risk |
| `exit_intelligence TICKER DTE PNL_PCT` | Regime stop + trailing target + theta decay curve |
| `exit_plan TICKER` | Exit plan display |
| `overnight TICKER [--dte N] [--status S]` | Overnight risk assessment |
| `assignment_risk TICKER` | Pre-assignment warning (dividend, deep ITM, near expiry) |

**Adjustment and Assignment (4 commands):**

| Command | What it Does |
|---------|-------------|
| `adjust TICKER` | Deterministic adjustment recommendation |
| `assignment TICKER STRIKE TYPE` | Handle assignment event |
| `csp TICKER STRIKE PREMIUM DTE` | Cash-secured put analysis |
| `covered_call TICKER COST_BASIS` | Covered call analysis after assignment |

**Risk Management (5 commands):**

| Command | What it Does |
|---------|-------------|
| `risk` | Portfolio risk dashboard (7 dimensions) |
| `stress_test [SCENARIO]` | Run stress scenarios (13 predefined) |
| `hedge TICKER POSITION_TYPE` | Hedging assessment (same-ticker only) |
| `greeks TICKER` | Aggregated Greeks for position |
| `exposure` | Portfolio currency and cross-market exposure |

**Account and Broker (5 commands):**

| Command | What it Does |
|---------|-------------|
| `broker` | Broker connection status |
| `balance` | Account balance from broker |
| `quotes TICKER [EXPIRATION]` | Option chain with bid/ask/Greeks from broker |
| `watchlist [NAME]` | List or show broker watchlists |
| `universe [PRESET]` | Scan and filter broker universe |

**Equity Research (7 commands):**

| Command | What it Does |
|---------|-------------|
| `stock TICKER [--horizon H]` | Single stock analysis (5 strategies, entry/stop/target) |
| `stock_screen [--strategy S] [--preset P]` | Screen stocks by strategy and universe |
| `valuation TICKER` | Market valuation zone (deep_value to bubble) |
| `leap_vs_stock TICKER` | LEAP call vs 100 shares comparison (US only) |
| `wheel TICKER` | Wheel strategy analysis (CSP -> assignment -> CC -> repeat) |
| `deploy AMOUNT [--market M] [--months N]` | Capital deployment plan (systematic over time) |
| `allocate [--market M] [--regime R]` | Asset allocation (equity/gold/debt/cash) |

**Capital Deployment (1 command):**

| Command | What it Does |
|---------|-------------|
| `rebalance` | Check if portfolio needs rebalancing vs target allocation |

**Performance and Learning (5 commands):**

| Command | What it Does |
|---------|-------------|
| `performance` | Performance report (win rate, Sharpe, Sortino, profit factor, POP accuracy) |
| `sharpe` | Sharpe ratio calculation |
| `drawdown` | Max drawdown analysis |
| `drift` | Drift detection (win rate dropping in any strategy/regime cell) |
| `bandit` | Thompson sampling strategy selection (adaptive exploration/exploitation) |

**Utilities (5 commands):**

| Command | What it Does |
|---------|-------------|
| `parse SYMBOL` | Parse OCC/DXLink option symbol |
| `leg_plan TICKER STRUCTURE` | Leg execution order for India single-leg markets |
| `currency AMOUNT FROM TO` | Currency conversion with P&L |
| `quit` / `exit` | Exit the CLI |

**Global flags for many commands:**
- `--debug` --- enable step-by-step commentary
- `--watchlist NAME` --- pull tickers from broker watchlist
- `--preset NAME` --- use built-in universe (income, nifty50, sector_etf, etc.)
- `--account N` --- filter by buying power

---

## Part 7: Python API Quick Reference

### Core Setup

```python
from market_analyzer import MarketAnalyzer, DataService

# Without broker (research mode)
ma = MarketAnalyzer(data_service=DataService())

# With TastyTrade broker
from market_analyzer.broker.tastytrade import connect_tastytrade
md, mm, acct, wl = connect_tastytrade(is_paper=True)
ma = MarketAnalyzer(
    data_service=DataService(),
    market_data=md, market_metrics=mm,
    account_provider=acct, watchlist_provider=wl,
)

# With Zerodha broker (India)
from market_analyzer.broker.zerodha import connect_zerodha
md, mm, acct, wl = connect_zerodha(api_key="...", access_token="...")
ma = MarketAnalyzer(
    data_service=DataService(), market="India",
    market_data=md, market_metrics=mm,
    account_provider=acct, watchlist_provider=wl,
)
```

### Service APIs (via MarketAnalyzer facade)

```python
# Regime detection
regime = ma.regime.detect("SPY", debug=True)

# Technical analysis
tech = ma.technicals.snapshot("SPY", debug=True)

# Levels analysis
levels = ma.levels.analyze("SPY")

# Vol surface
vol = ma.vol_surface.compute("SPY")

# Market context
ctx = ma.context.assess(debug=True)

# Screening
scan = ma.screening.scan(["SPY", "GLD", "QQQ"], min_score=0.6, top_n=10)

# Ranking
ranking = ma.ranking.rank(["SPY", "GLD", "QQQ"], skip_intraday=True, debug=True)

# Daily trading plan
plan = ma.plan.generate(tickers=["SPY", "GLD", "QQQ"], skip_intraday=True)

# Adjustment analysis
analysis = ma.adjustment.analyze(trade_spec, regime, technicals, vol_surface)

# Option quotes (broker)
chain = ma.quotes.get_chain("SPY")
leg_quotes = ma.quotes.get_leg_quotes(legs)
metrics = ma.quotes.get_metrics("SPY")
```

### Pure Function APIs

```python
from market_analyzer import (
    # Validation
    run_daily_checks,              # 7-check profitability gate
    run_adversarial_checks,        # 3-check stress gate
    run_position_stress,           # Position stress analysis

    # Entry Intelligence
    score_entry_level,             # Enter now vs wait
    compute_limit_entry_price,     # Patient/normal/aggressive limit
    compute_pullback_levels,       # Where entry gets better
    compute_strike_support_proximity,  # Are strikes backed by S/R?
    select_skew_optimal_strike,    # Where is IV richest?
    compute_iv_rank_quality,       # IV rank quality assessment

    # Sizing
    compute_position_size,         # Full regime-aware sizing
    compute_kelly_fraction,        # Kelly criterion
    compute_margin_analysis,       # Cash vs margin
    compute_margin_buffer,         # Margin cushion

    # Exit
    compute_regime_stop,           # Regime-contingent stop multiplier
    compute_time_adjusted_target,  # Trailing profit target
    compute_remaining_theta_value, # Theta decay remaining
    compute_monitoring_action,     # What to do right now
    build_closing_trade_spec,      # Machine-readable close order

    # Monitoring
    monitor_exit_conditions,       # 4 exit rules
    check_trade_health,            # Full health check
    assess_overnight_risk,         # Overnight risk level

    # Decision
    audit_decision,                # 4-level report card
    assess_crash_sentinel,         # Crash sentinel signal

    # Portfolio Risk
    compute_risk_dashboard,        # 7-dimension risk dashboard
    run_stress_suite,              # Multi-scenario stress test
    run_stress_test,               # Single scenario stress
    get_predefined_scenario,       # Access 13 predefined scenarios
    evaluate_trade_gates,          # 17-gate BLOCK/SCALE/WARN framework
    filter_trades_by_account,      # Account-level trade filter
    filter_trades_with_portfolio,  # Portfolio-aware filter (7-step cascade)

    # Assignment
    handle_assignment,             # Assignment event handler
    assess_assignment_risk,        # Pre-assignment warning
    analyze_cash_secured_put,      # CSP analysis
    analyze_covered_call,          # CC analysis after assignment

    # Rate Risk
    assess_rate_risk,              # Single ticker rate sensitivity
    assess_portfolio_rate_risk,    # Portfolio rate risk

    # Trust
    compute_trust_report,          # 3-dimension trust assessment

    # POP and Yield
    estimate_pop,                  # Probability of profit + EV + quality
    compute_income_yield,          # Credit/width, ROC, annualized
    compute_breakevens,            # Breakeven prices
    check_income_entry,            # Income entry confirmation
    aggregate_greeks,              # Net Greeks for position

    # Hedging and Execution
    assess_hedge,                  # Hedging recommendation (same-ticker)
    validate_execution_quality,    # Spread, OI, volume check
    plan_leg_execution,            # India single-leg ordering

    # Performance and Learning
    compute_performance_report,    # Win rate, Sharpe, Sortino, PF
    compute_sharpe,                # Sharpe ratio
    compute_drawdown,              # Max drawdown
    calibrate_weights,             # Recalibrate ranking weights
    calibrate_pop_factors,         # Recalibrate POP regime factors
    optimize_thresholds,           # Optimize gate thresholds
    detect_drift,                  # Win rate drift detection
    build_bandits,                 # Thompson sampling bandits
    select_strategies,             # Adaptive strategy selection

    # Macro Research
    generate_research_report,      # 22-asset macro research
    compute_macro_dashboard,       # Bond/credit/dollar/inflation
    analyze_cross_market,          # US -> India analysis

    # Equity Research
    analyze_stock,                 # 5-strategy stock analysis
    screen_stocks,                 # Stock screening
    compute_market_valuation,      # Valuation zone
    plan_deployment,               # Capital deployment plan
    compute_asset_allocation,      # Asset allocation
    analyze_wheel_strategy,        # Wheel strategy analysis
    decide_wheel_action,           # Wheel state machine decision
    compare_leap_vs_stock,         # LEAP vs stock comparison

    # Currency
    compute_currency_pnl,          # Currency P&L decomposition

    # Data Adapters (bring your own data)
    CSVProvider,                   # Load OHLCV from CSV files
    DictQuoteProvider,             # Provide quotes from dict
    DictMetricsProvider,           # Provide metrics from dict
)
```

### TradeSpec --- The Universal Trade Contract

Every trade recommendation produces a `TradeSpec`. This is the machine-readable contract that a broker or execution platform consumes.

```python
spec.ticker              # "SPY"
spec.structure_type      # "iron_condor"
spec.order_side          # "credit"
spec.legs                # [LegSpec(STO P570, BTO P565, STO C590, BTO C595)]
spec.max_entry_price     # 0.80 (don't pay more)
spec.profit_target_pct   # 0.50 (close at 50% max profit)
spec.stop_loss_pct       # 2.0 (close if loss = 2x credit)
spec.exit_dte            # 21 (close when <=21 DTE)
spec.entry_window_start  # time(10, 0)
spec.entry_window_end    # time(15, 0)
spec.lot_size            # 100 (US) or 25 (NIFTY)
spec.currency            # "USD" or "INR"
spec.settlement          # "cash" or "physical"
spec.exercise_style      # "european" or "american"

# Computed properties
spec.strategy_badge      # "IC neutral . defined"
spec.strategy_symbol     # "IC"
spec.exit_summary        # "TP 50% | SL 2x credit | close <=21 DTE"
spec.order_data          # Machine-readable for broker submission
spec.position_size(50000)# Number of contracts for $50K account
spec.leg_codes           # ["STO 1x SPY P570 3/27/26", ...]
```

**Structure types:** iron_condor, iron_man, iron_butterfly, credit_spread, debit_spread, calendar, double_calendar, diagonal, ratio_spread, straddle, strangle, long_option, pmcc

### Trade Gate Framework

Not all gates should block trades. The framework classifies every check:

```python
from market_analyzer import evaluate_trade_gates

report = evaluate_trade_gates(
    ticker="SPY", strategy="iron_condor",
    trade_quality_score=0.45, macro_regime="risk_off",
    position_count=3, max_positions=5, bp_sufficient=True,
    strategy_concentrated=True,
)

print(report.final_action)       # "scale"
print(report.final_scale_factor) # 0.38
print(report.can_proceed)        # True
```

| Tier | Effect | What Fires It |
|------|--------|--------------|
| **BLOCK** | Trade does NOT proceed | Drawdown breaker, portfolio full, no BP, DEFLATIONARY |
| **SCALE** | Reduce position size | Low quality score, macro caution, wide spreads, no IV rank |
| **WARN** | Log and alert, allow trade | Strategy/directional/sector concentration, model stale |

17 gates total: 5 BLOCK, 5 SCALE, 7 WARN.

---

## Part 8: Appendix

### A. Regime Model Reference

| Regime | Name | Primary Strategy | Avoid | Stop Multiplier |
|--------|------|------------------|-------|----------------|
| R1 | Low-Vol Mean Reverting | Iron condors, strangles (theta) | Directional | 2.0x |
| R2 | High-Vol Mean Reverting | Wider wings, defined risk (selective theta) | Directional | 3.0x |
| R3 | Low-Vol Trending | Directional spreads (debit, diagonal, PMCC) | Heavy theta | 1.5x |
| R4 | High-Vol Trending | Risk-defined only, long vega | Theta selling | 1.5x |

**Regime determines what is available:**

| Regime | Options | Stocks | Futures |
|--------|---------|--------|---------|
| R1 (calm) | Full suite (8 strategies) | All 5 styles | All strategies |
| R2 (high vol) | Defined risk (5) | All 5 styles | Premium selling |
| R3 (trending) | Directional only (3) | All 5 styles | Trend-following |
| R4 (explosive) | Defined risk ONLY | Value + turnaround | EXTREME CAUTION |
| Black Swan | **NO OPTIONS** | **NO STOCKS** | **NO FUTURES** |

**POP regime factors** (used in probability of profit estimation):
- R1: 0.40 (low ATR, tight range)
- R2: 0.70 (elevated ATR, wide swings)
- R3: 1.10 (trending, directional moves)
- R4: 1.50 (explosive, fat tails)

### B. Validation Checks Reference

**Daily suite (7 checks):**

| # | Check | Threshold | PASS | WARN | FAIL |
|---|-------|-----------|------|------|------|
| 1 | Commission drag | Fees / credit | <10% | 10-25% | >25% |
| 2 | Fill quality | Bid/ask spread | <=1.5% | 1.5-3% | >3% |
| 3 | Margin efficiency | Annualized ROC | >=15% | 10-15% | <10% |
| 4 | POP gate | Probability of profit | >=65% | --- | <65% |
| 5 | EV positive | Expected value | >0 | --- | <=0 |
| 6 | Entry quality | Regime + timing | In window + match | --- | Outside or mismatch |
| 7 | Exit discipline | TP + SL + DTE defined | All defined | --- | Any missing |

**Adversarial suite (3 checks):**

| # | Check | Threshold | PASS | WARN | FAIL |
|---|-------|-----------|------|------|------|
| 8 | Gamma stress | Risk:reward after 2-sigma move | <5x | 5-10x | >=10x |
| 9 | Vega shock | Loss if VIX +30% | <25% of credit | --- | >=25% |
| 10 | Breakeven spread | Spread that makes EV negative | >2% | --- | <=2% |

**Decision rule:** Zero FAIL checks = `is_ready = True`. Warnings are tradeable but logged.

### C. Trust Level Reference

| Overall Trust | Level | Fit For | Not Fit For |
|--------------|-------|---------|-------------|
| 80%+ | HIGH | All purposes including live execution | --- |
| 50-79% | MEDIUM | Paper trading, alerts, screening | Real capital |
| 20-49% | LOW | Research, exploration, education | Any trading decision |
| <20% | UNRELIABLE | Reading documentation | Anything involving money |

**Trust score composition:**
- Data quality: broker live = +0.30, yfinance = +0.30 (base), estimated = +0.03, none = 0
- Context quality: full inputs = high, missing portfolio/levels/IV rank = reduced
- Regime confidence: high confidence = boost, low confidence = penalty

### D. Assignment Risk Reference

| Market | Exercise Style | Assignment Risk |
|--------|---------------|-----------------|
| US equities | American | YES --- can be assigned anytime, especially near dividends and expiry |
| US index options (SPX, NDX) | European | NO --- settlement only at expiry, cash-settled |
| India indices (NIFTY, BANKNIFTY) | European | NO --- cash-settled at expiry |
| India stocks | European | At expiry only (physical settlement) |

**Dividend assignment risk (US only):** Short calls deep ITM near ex-dividend dates can be assigned early. The assignment risk assessor checks for this automatically.

**When to worry:** Short option with intrinsic value > time value remaining, near expiration, near dividend.

### E. Rate Sensitivity Reference

| Ticker | Rate Sensitivity | Direction | Notes |
|--------|-----------------|-----------|-------|
| TLT | Very High | Inverse | 20+ year Treasuries, ~20x duration leverage |
| XLU | High | Inverse | Utilities compete with bond yields |
| XLRE | High | Inverse | REITs --- rate-sensitive income vehicles |
| GLD | Moderate | Inverse | Real rates matter (nominal - inflation) |
| XLF | Moderate | Positive | Banks profit from rate spread |
| SPY | Low-Moderate | Negative | Higher rates = higher discount rate |
| QQQ | Moderate | Negative | Growth stocks = long duration equity |
| IWM | Moderate | Negative | Small caps = more rate-sensitive borrowing |

### F. Market Context Labels

```python
ctx = ma.context.assess()
```

| Label | Meaning | Action |
|-------|---------|--------|
| `risk-on` | Bull market, low vol, trending up | Full trading |
| `cautious` | Elevated vol or mixed signals | Reduce position sizes 25% |
| `defensive` | High vol or macro stress | Defined risk only, reduce 50% |
| `crisis` | Black swan critical | NO TRADING |

**Tradeable instruments per environment:**

```python
t = ctx.tradeable
t.options_available      # True/False
t.options_strategies     # ["iron_condor", "iron_butterfly", ...]
t.stocks_available       # True/False
t.stocks_strategies      # ["value", "growth", "dividend", ...]
t.futures_available      # True/False
t.futures_strategies     # ["futures options (iron condor)", ...]
t.india_weekly_expiry_today   # True if India expiry day
t.india_expiry_instrument     # "NIFTY", "BANKNIFTY", or "FINNIFTY"
```

### G. Black Swan Alert Levels

```python
alert = ma.black_swan.alert()
```

| Alert Level | Composite Score | Action |
|------------|----------------|--------|
| NORMAL | Low | Trade normally |
| ELEVATED | Moderate | Reduce position sizes by 25% |
| HIGH | High | Reduce by 50%, defined risk only |
| CRITICAL | Extreme | NO TRADING --- protect capital |

### H. Data Gaps and Transparency

Every analysis result can carry `data_gaps`:

```python
DataGap(
    field="iv_rank",
    reason="broker not connected",
    impact="medium",
    affects="premium assessment --- POP may be 10-15% off",
)
```

The system never hides what it does not know. If broker is down, IV rank is missing, or the model is stale, it tells you. Trust is built on transparency.

**8 assessors that self-identify data gaps:** vol_surface, broker connection, ORB data, fundamentals, earnings, term structure, correlation, order book depth.

### I. Ticker Aliases

MA automatically translates common tickers before passing to yfinance:

| You Type | yfinance Fetches | Instrument |
|----------|-----------------|------------|
| SPX | ^GSPC | S&P 500 Index |
| NDX | ^NDX | Nasdaq-100 Index |
| DJX | ^DJI | Dow Jones Industrial Average |
| RUT | ^RUT | Russell 2000 Index |
| VIX | ^VIX | CBOE Volatility Index |
| TNX | ^TNX | 10-Year Treasury Yield |
| COMP | ^IXIC | Nasdaq Composite |
| SOX | ^SOX | PHLX Semiconductor Index |
| NIFTY | ^NSEI | Nifty 50 (India) |
| BANKNIFTY | ^NSEBANK | Bank Nifty (India) |
| SENSEX | ^BSESN | BSE Sensex (India) |

DXLink-style tickers prefixed with `$` (e.g., `$SPX`) are also resolved correctly.

---

## Quant's Cookbook --- Creative API Combinations

> Think of market_analyzer as a set of building blocks. Each individual API tells you one thing. The real edge comes from **combining them** --- stacking regime detection with vol surface with profitability gates to make decisions no single metric could make alone.

### Recipe 1: The Full Entry Decision Stack

Gate every entry through 5 layers, each eliminating a different failure mode:

```python
# Layer 1: Is today safe?
ctx = ma.context.assess()
if not ctx.trading_allowed: return

# Layer 2: Right regime?
regime = ma.regime.detect("SPY")
if regime.regime == RegimeID.R4: return

# Layer 3: Positive expected value?
ic = assess_iron_condor("SPY", regime, technicals, vol_surface)
if ic.verdict == Verdict.NO_GO: return

# Layer 4: Profitable after fees and slippage?
report = run_daily_checks("SPY", ic.trade_spec, entry_credit=1.80, ...)
if not report.is_ready: return

# Layer 5: Survives stress?
stress = run_adversarial_checks("SPY", ic.trade_spec, 1.80, atr_pct=0.85)
if stress.failures: return

# All gates passed --- size and execute
```

### Recipe 2: Regime-Adaptive Position Sizing

Scale size by regime confidence AND drawdown state:

```python
regime_factors = {RegimeID.R1: 1.0, RegimeID.R2: 0.75, RegimeID.R3: 0.50, RegimeID.R4: 0.25}
base_factor = regime_factors[regime.regime]
confidence_factor = min(1.0, regime.confidence / 0.80)

drawdown_pct = dashboard.drawdown_pct
if drawdown_pct >= 0.10: return  # Circuit breaker
drawdown_factor = max(0.50, 1.0 - (drawdown_pct / 0.10))

contracts = max(1, round(base_contracts * base_factor * confidence_factor * drawdown_factor))
```

### Recipe 3: Vol Surface Timing for Calendars

Calendar spreads only make money when IV differential exists:

```python
vol = ma.vol_surface.compute("SPY")
if vol.iv_differential_pct >= 10 and vol.is_backwardation:
    quality = "ideal"  # Sell expensive front, buy cheap back
elif vol.iv_differential_pct >= 5:
    quality = "good"
elif vol.iv_differential_pct < 2:
    return  # No edge --- calendar is a coin flip
```

### Recipe 4: 0DTE ORB Decision Engine

Wait 30 minutes for real data, then decide systematically:

```python
zero_dte = assess_zero_dte("SPY", regime, technicals, vol_surface, phase)
orb = zero_dte.orb_decision

# Narrow ORB (< 0.3%) = breakout coming -> Iron Man (long IC)
# Wide ORB (> 1.5%) = range set -> Short IC at ORB edges
# Directional ORB + confirming regime -> Directional spread
```

### Recipe 5: Cross-Market Gap Fade (US -> India)

```python
cm = analyze_cross_market("SPY", "NIFTY", us_ohlcv, india_ohlcv, us_regime_id, india_regime_id)

if cm.predicted_india_gap_pct < -0.8 and cm.prediction_confidence > 0.6:
    india_regime = ma.regime.detect("NIFTY")
    if india_regime.regime in (RegimeID.R1, RegimeID.R2):
        # Mean-reverting regime + predicted gap = gap fade opportunity
        # Gap fills 65% of the time within first 30 minutes
        pass
```

### Recipe 6: Regime Transition Early Warning

Watch the probability vector, not just the label:

```python
probs = regime.regime_probabilities
if probs[4] > 0.15:  # R4 creeping in
    # Start de-risking NOW: no new ICs, close DTE > 30, tighten to 1.5x stops
elif probs[2] > 0.30:  # R2 forming
    # Widen wings 10-15%, reduce size 25%, prefer iron butterfly
```

### Recipe 7: Sector Rotation from Macro Research

```python
report = generate_research_report(data, "daily")
favor = report.regime.favor_sectors    # ["energy", "commodity"] in stagflation
avoid = report.regime.avoid_sectors    # ["tech", "bonds"]

# Scan WITHIN high-conviction sectors, not the same 10 tickers every day
ranking = ma.ranking.rank(tickers=sector_to_tickers[favor[0]], debug=True)
```

### Recipe 8: Mechanical Adjustment Protocol

```python
for position in open_positions:
    exit_signal = monitor_exit_conditions(...)
    if exit_signal.should_exit:
        print(f"EXIT {position.ticker}: {exit_signal.reason}")
        continue

    health = check_trade_health(...)
    if health.status == "BREACHED":
        action = adj_service.analyze(position.trade_spec, regime, tech)
        print(f"ADJUST: {action.recommended_adjustments[0].description}")
```

### Recipe 9: Shadow Portfolio (Learning from Rejections)

```python
from market_analyzer import analyze_gate_effectiveness

effectiveness = analyze_gate_effectiveness(gate_history, shadow_outcomes, actual_outcomes)

if effectiveness.shadow_win_rate > 0.60:
    # Gates too tight --- blocking good trades
    for gate in effectiveness.gates_too_tight:
        print(f"  {gate.name}: {gate.shadow_win_rate:.0%} win rate when blocked")
```

### Recipe 10: Weekly Calibration Loop

```python
from market_analyzer import calibrate_weights, TradeOutcome

outcomes = [TradeOutcome(ticker="SPY", strategy="iron_condor", ...)]
new_weights = calibrate_weights(outcomes)
# -> "Iron condor win rate 71% in R1 --- increase R1 alignment weight"
```

### The Mental Model

```
TIER 1 --- WHAT IS THE MARKET DOING?
  ma.regime.detect()           -> R1/R2/R3/R4?
  ma.context.assess()          -> Safe to trade?
  ma.technicals.snapshot()     -> Price structure?
  ma.vol_surface.compute()     -> Vol surface saying?
  generate_research_report()   -> Macro environment?

TIER 2 --- WHAT SHOULD I TRADE?
  assess_iron_condor() etc.    -> Specific structure valid?
  ma.ranking.rank()            -> What ranks highest?
  filter_trades_with_portfolio() -> Fits my portfolio?
  evaluate_trade_gates()       -> Scale or block?

TIER 3 --- IS THIS TRADE ACTUALLY PROFITABLE?
  run_daily_checks()           -> Commission drag, fill quality, ROC, POP, EV
  run_adversarial_checks()     -> Survives gamma stress, vega shock?
  check_trade_health()         -> Existing position status
  monitor_exit_conditions()    -> Should I exit now?
```

**The edge is in Tier 3.** Most systematic platforms have Tier 1 and Tier 2. The profitability gate is what separates a platform that makes money from one that only looks like it should.

---

*market_analyzer --- capital preservation first, income second, growth third.*
*1072+ tests. 75+ CLI commands. US + India markets. TastyTrade + Zerodha brokers.*
*Options + equities + futures + capital deployment. 75+ position-aware functions.*
*5 investment strategies. 13 stress test scenarios. 17 trade gates. 22 macro assets tracked.*
