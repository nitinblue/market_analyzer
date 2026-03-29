---
key: nifty_down_10
name: "NIFTY -10% + INR Depreciation"
category: crash
severity: moderate
historical_analog: "2024 election volatility, 2022 FII sell-off"
expected_duration_days: 10
monte_carlo_paths: 1000
---

# NIFTY -10% + INR Depreciation

## Narrative

A sharp 10% correction in NIFTY driven by FII outflows and rupee depreciation. The sell-off is amplified by the reflexive relationship between equity outflows and currency weakness — as FIIs sell equities, they repatriate dollars, pushing INR lower, which triggers more selling. BANKNIFTY typically leads the decline as banking sector is most sensitive to FII positioning. India VIX spikes to 20+ from sub-14 levels. Domestic mutual fund SIP flows provide some support but cannot offset the pace of foreign selling. The correction often coincides with global risk-off but has an India-specific amplifier (election uncertainty, regulatory action, or EM contagion).

## Trigger Conditions

- FII net selling exceeds Rs 5,000 crore for 5+ consecutive sessions
- INR breaks above 85/USD (weakens past key psychological level)
- India VIX rises above 18 from sub-13 levels
- NIFTY breaks below 200-day moving average
- Global EM selloff with DXY strengthening above 106

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| equity     | -10%     | Broad NIFTY correction                 |
| rates      | +3%      | RBI may defend rupee with rate stance  |
| volatility | +50%     | India VIX spikes sharply               |
| currency   | -5%      | INR depreciates against USD            |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +8%    | IV expansion across NIFTY/BANKNIFTY options |
| skew_steepening | +6%    | Put demand surges on hedging activity  |

## Cross-Asset Correlations

| Pair                  | Normal | This Scenario | Why                        |
|-----------------------|--------|---------------|----------------------------|
| NIFTY - BANKNIFTY     | 0.90   | 0.95          | Banks lead the sell-off     |
| NIFTY - INR (inverse) | 0.40   | 0.70          | Equity-currency reflexivity |
| NIFTY - Gold (INR)    | -0.05  | -0.25         | Gold in INR terms rallies   |
| BANKNIFTY - TCS/INFY  | 0.60   | 0.80          | Correlation spikes in panic |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | -10%          | Short NIFTY/BANKNIFTY puts at risk |
| Single-stock opts | -10% to -18%  | Mid-cap/small-cap options destroyed |
| Bonds / Gilts     | -1% to -2%    | Yields may rise on INR defense |
| Gold / SGBs       | +3% to +5%    | Gold in INR terms benefits from depreciation |
| Cash              | 0%            | Deploy into IV spike            |

## Trading Response

- **Immediate**: Close short BANKNIFTY strangles — BANKNIFTY has higher beta and will overshoot. Reduce NIFTY short put exposure. This is R4 for India markets.
- **Day 1-3**: Wait for India VIX to peak. Watch FII flow data daily — stabilization of outflows is the first signal. Do not sell premium while VIX is still rising.
- **Day 5-10**: Once FII selling slows and INR stabilizes, sell elevated premium on NIFTY/BANKNIFTY. Use put spreads at 2x normal width with weekly expiry. Transition from R4 to R2 strategies.
- **Position sizing**: Reduce India allocation to 50% of normal. Single-leg execution means adjustment is slower — keep positions smaller to compensate.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2024-06-04 | Election result shock| -5.9% (1 day) | 26       | 5               |
| 2022-06-17 | FII sell-off       | -13%     | 24            | 60              |
| 2020-03-23 | COVID India bottom | -38%     | 84            | 180             |
| 2018-10-26 | IL&FS/NBFC crisis  | -11%     | 22            | 40              |
