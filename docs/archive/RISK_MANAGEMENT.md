# Risk Management Framework

**Primary Goal: Capital Preservation.** Making money is secondary to not losing it.

**Principle:** MA computes all risk metrics as pure functions. eTrading enforces limits and stores state. Every risk check is a gate — if it fails, the trade doesn't happen.

---

## Risk Dimensions

| Dimension | What it measures | Why it matters |
|-----------|-----------------|----------------|
| **Position count** | How many open trades | Each position = potential loss. More positions = more things to go wrong. |
| **Per-ticker concentration** | Positions on same underlying | Multiple SPY trades = amplified single-stock risk |
| **Strategy concentration** | Too many of same strategy type | 5 iron condors = concentrated short-vol bet. If vol explodes, all lose. |
| **Directional concentration** | Net portfolio delta exposure | Bullish bias across trades = directional bet. Market drops = all lose. |
| **Sector concentration** | Risk in one sector | All tech positions = correlated loss when sector rotates |
| **Correlation risk** | Positions that move together | SPY IC + QQQ IC = 0.9 correlated. Effectively same trade. |
| **Portfolio VaR** | Max expected loss in N days at X% confidence | "95% confident portfolio won't lose more than $X in 1 day" |
| **Greeks limits** | Portfolio-level delta, theta, vega, gamma | Max theta = income dependency. Max vega = vol sensitivity. |
| **Margin utilization** | BP used vs available | >80% utilization = one bad trade away from margin call |
| **Drawdown circuit breaker** | Account peak-to-trough decline | Halt trading if account drops 10% from peak |
| **Macro regime gate** | Current macro environment | DEFLATIONARY = no new trades. STAGFLATION = 30% size. |

---

## What MA Provides (Pure Computation)

### Already Built

| Function | Risk Dimension | What it does |
|----------|---------------|-------------|
| `filter_trades_with_portfolio()` | Position count, per-ticker, sector, portfolio risk | 7-step filter cascade |
| `assess_overnight_risk()` | Per-position overnight gap | LOW/MEDIUM/HIGH/CLOSE_BEFORE_CLOSE |
| `assess_hedge()` | Per-position hedge need | Regime-aware: R4 = protective put immediate |
| `check_trade_health()` | Per-position monitoring | HEALTHY/TESTED/BREACHED/EXIT_TRIGGERED |
| `recommend_action()` | Per-position adjustment | Deterministic: BREACHED+R4 = CLOSE_FULL |
| `validate_execution_quality()` | Per-trade liquidity | GO/WIDE_SPREAD/ILLIQUID/NO_QUOTE |
| `estimate_pop()` | Per-trade probability | POP + EV + R:R + trade_quality_score |
| `detect_drift()` | Strategy performance degradation | WARNING/CRITICAL when win rate drops |
| `classify_macro_regime()` | Macro environment | position_size_factor: 0.2 (deflationary) to 1.0 (risk-on) |
| `compute_drawdown()` | Historical drawdown | Max drawdown from trade outcomes |

### Built (2026-03-15)

| Function | Risk Dimension | Status |
|----------|---------------|--------|
| `compute_portfolio_var()` | **VaR** | **DONE** — parametric ATR-based, regime-adjusted, correlation-aware |
| `check_portfolio_greeks()` | **Greeks limits** | **DONE** — net delta/theta/vega vs configurable limits |
| `check_strategy_concentration()` | **Strategy concentration** | **DONE** — flags >50% in one strategy |
| `check_directional_concentration()` | **Directional concentration** | **DONE** — net score, flags >0.5 magnitude |
| `check_correlation_risk()` | **Correlation risk** | **DONE** — effective positions, diversification score |
| `check_drawdown_circuit_breaker()` | **Drawdown** | **DONE** — triggers at configurable threshold (default 10%) |
| `compute_risk_dashboard()` | **All combined** | **DONE** — master gate, alerts, commentary, CLI `risk` |

---

## Risk Models

```python
class PortfolioGreeks(BaseModel):
    """Portfolio-level aggregated Greeks."""
    net_delta: float        # Directional exposure (-1 to +1 per contract)
    net_gamma: float        # Delta sensitivity
    net_theta: float        # Daily time decay (positive = earning, negative = paying)
    net_vega: float         # IV sensitivity
    theta_dollars_per_day: float  # Net theta in dollars
    delta_dollars: float    # Dollar exposure from delta (delta × price × lot_size)

class GreeksLimits(BaseModel):
    """Limits on portfolio-level Greeks."""
    max_abs_delta: float = 50.0     # Max net delta in dollar terms (% of NLV)
    max_abs_theta_pct: float = 0.5  # Max daily theta as % of NLV (earning OR paying)
    max_abs_vega_pct: float = 1.0   # Max vega exposure as % of NLV
    max_abs_gamma: float = 10.0     # Max gamma (rate of delta change)

class VaRResult(BaseModel):
    """Portfolio Value at Risk."""
    var_1d_95: float        # 1-day VaR at 95% confidence (dollars)
    var_1d_99: float        # 1-day VaR at 99% confidence
    var_5d_95: float        # 5-day VaR at 95% confidence
    var_pct_of_nlv: float   # 1-day 95% VaR as % of NLV
    method: str             # "parametric_atr" or "historical"
    commentary: str

class StrategyConcentration(BaseModel):
    """How concentrated the portfolio is by strategy type."""
    by_strategy: dict[str, int]     # {"iron_condor": 3, "credit_spread": 1}
    dominant_strategy: str | None   # Most common strategy
    dominant_pct: float             # What % of positions is the dominant strategy
    is_concentrated: bool           # >50% in one strategy type
    recommendation: str

class DirectionalExposure(BaseModel):
    """Net directional bias of the portfolio."""
    net_delta_score: float          # -1 (bearish) to +1 (bullish)
    bullish_positions: int
    bearish_positions: int
    neutral_positions: int
    direction: str                  # "bullish", "bearish", "neutral", "mixed"
    is_concentrated: bool           # >70% in one direction
    recommendation: str

class CorrelationRisk(BaseModel):
    """Correlation between open positions."""
    highly_correlated_pairs: list[tuple[str, str, float]]  # (ticker_a, ticker_b, corr)
    effective_positions: float      # Adjusted count after correlation (5 correlated = ~2 effective)
    diversification_score: float    # 0-1 (1 = fully diversified, 0 = all same bet)
    recommendation: str

class DrawdownStatus(BaseModel):
    """Current drawdown vs circuit breaker threshold."""
    account_peak: float             # Highest NLV ever (or this month)
    current_nlv: float
    drawdown_pct: float             # (peak - current) / peak
    drawdown_dollars: float
    circuit_breaker_pct: float      # Threshold (e.g., 10%)
    is_triggered: bool              # True if drawdown > threshold
    recommendation: str

class RiskDashboard(BaseModel):
    """Complete portfolio risk assessment."""
    as_of_date: date
    account_nlv: float
    # Position risk
    open_positions: int
    max_positions: int
    slots_remaining: int
    portfolio_risk_pct: float       # Total max loss / NLV
    # Greeks
    greeks: PortfolioGreeks | None
    greeks_within_limits: bool
    # VaR
    var: VaRResult | None
    # Concentrations
    strategy_concentration: StrategyConcentration
    directional_exposure: DirectionalExposure
    sector_concentration: dict[str, float]  # sector -> % of risk
    correlation_risk: CorrelationRisk | None
    # Circuit breaker
    drawdown: DrawdownStatus
    # Macro
    macro_regime: str               # From research report
    macro_position_factor: float    # 0-1 scaling
    # Overall
    overall_risk_level: str         # "low", "moderate", "elevated", "high", "critical"
    can_open_new_trades: bool       # Master gate
    max_new_trade_size_pct: float   # Scale factor for any new trade
    alerts: list[str]               # What's wrong
    commentary: list[str]           # Human-readable risk narrative
```

---

## VaR Computation

eTrading has VaR implemented. MA should provide a pure computation version so it's consistent across the system.

**Parametric VaR (ATR-based, regime-adjusted):**

For each position:
- `position_var = max_loss` (defined risk) or `notional × ATR% × regime_factor × √days` (undefined)
- Regime factors: R1=0.40, R2=0.70, R3=1.10, R4=1.50

Portfolio VaR:
- Not simple sum (that's worst case, not VaR)
- Use `sqrt(sum(individual_var²))` for uncorrelated positions
- Adjust by correlation: `portfolio_var = sqrt(Σ var_i² + 2 × Σ ρ_ij × var_i × var_j)`

**Why MA should compute VaR:**
- MA has regime data (regime-adjusted expected moves)
- MA has ATR data (volatility per instrument)
- MA has correlation data (cross-asset correlation matrix)
- eTrading has position data (notional, max_loss, direction)
- **Together:** MA computes risk from data eTrading passes in

---

## Implementation Status — ALL DONE

| # | Function | Status |
|---|----------|--------|
| RM1 | `compute_portfolio_var()` | **DONE** |
| RM2 | `check_portfolio_greeks()` | **DONE** |
| RM3 | `check_strategy_concentration()` | **DONE** |
| RM4 | `check_directional_concentration()` | **DONE** |
| RM5 | `check_correlation_risk()` | **DONE** |
| RM6 | `check_drawdown_circuit_breaker()` | **DONE** |
| RM7 | `compute_risk_dashboard()` | **DONE** |
| RM8 | CLI `do_risk` | **DONE** |

---

## eTrading Risk Framework Recommendation

MA provides the computation engine. eTrading should build the framework around it:

### 1. Pre-Trade Risk Gate (on every new trade)

```python
# eTrading calls this BEFORE placing any order
dashboard = compute_risk_dashboard(
    positions=load_open_positions(),  # From portfolio DB
    account_nlv=get_account_nlv(),
    peak_nlv=get_peak_nlv(),          # Track and store the highest NLV
    regime_id=current_regime.regime,
    correlations=get_cached_correlations(),  # From MA's compute_correlation_matrix()
    greeks_limits=desk_config.greeks_limits,
    drawdown_threshold=desk_config.drawdown_threshold,  # Default 0.10
)

if not dashboard.can_open_new_trades:
    BLOCK_ORDER()
    log_risk_rejection(dashboard.alerts)
    notify_trader(dashboard.alerts)
    return

# Scale new trade size
new_trade_size = base_size * dashboard.max_new_trade_size_pct
```

### 2. Continuous Monitoring (every 30 min during market hours)

```python
# eTrading schedules this
dashboard = compute_risk_dashboard(positions, nlv, peak, regime, correlations)

if dashboard.drawdown.is_triggered:
    EMERGENCY: close_all_positions()
    notify_trader("DRAWDOWN CIRCUIT BREAKER — all positions closed")

for alert in dashboard.alerts:
    send_notification(alert)
```

### 3. Risk Configuration (per desk/user)

```yaml
risk:
  drawdown_threshold: 0.10       # Halt at 10% drawdown from peak
  max_positions: 5
  max_per_ticker: 2
  max_sector_pct: 0.40
  max_portfolio_risk_pct: 0.25
  greeks_limits:
    max_abs_delta: 50.0
    max_abs_theta_pct: 0.5
    max_abs_vega_pct: 1.0
  macro_halt_regimes: ["deflationary"]
  macro_reduce_regimes: ["risk_off", "stagflation"]
```

### 4. Peak NLV Tracking

eTrading must track the highest account value for drawdown calculation:

```python
# On every account update:
current_nlv = get_account_balance().net_liquidating_value
peak_nlv = max(stored_peak_nlv, current_nlv)
save_peak_nlv(peak_nlv)
```

### 5. Risk Audit Trail

Every risk check should be logged:
- `dashboard.commentary` → decision lineage
- `dashboard.alerts` → risk event log
- `dashboard.can_open_new_trades` → order gate log

---

## eTrading Integration

eTrading provides:
- `list[OpenPosition]` with ticker, structure, direction, max_loss, greeks (if available)
- `account_nlv`, `account_peak` (for drawdown)
- OHLCV data for correlation (or MA fetches via DataService)

MA returns:
- `RiskDashboard` with all metrics, alerts, and master gate (`can_open_new_trades`)

eTrading enforces:
- If `can_open_new_trades == False` → block all new orders
- If `max_new_trade_size_pct < 1.0` → scale down position sizes
- Display `alerts` in trading dashboard
- Log `commentary` in risk audit trail
