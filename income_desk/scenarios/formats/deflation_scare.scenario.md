---
key: deflation_scare
name: "Deflation Scare"
category: macro
severity: mild
historical_analog: "2015 China devaluation scare"
expected_duration_days: 10
monte_carlo_paths: 1000
---

# Deflation Scare

## Narrative

A sudden demand collapse triggers deflation fears — commodities crash, consumer prices fall, and the market prices in aggressive monetary easing. Bonds rally strongly as real rates rise and central banks are expected to cut aggressively. Equities have a mixed reaction: the growth scare hurts cyclicals and commodities, but tech and long-duration growth stocks benefit from lower rates. Gold is ambiguous — it rallies on monetary easing expectations but is hurt by the deflationary impulse. The scenario is typically triggered by a China slowdown, an EM crisis, or a sudden evaporation of consumer demand. Volatility rises modestly as the market reprices growth but doesn't panic.

## Trigger Conditions

- China PMI drops below 45, signaling hard landing
- Oil crashes 20%+ on demand destruction
- CPI prints negative month-over-month
- ISM Prices Paid collapses below 40
- Multiple major retailers issue profit warnings citing weak demand

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| commodity  | -15%     | Demand destruction crashes commodities |
| rates      | +15%     | Bond prices surge on rate cut expectations |
| equity     | -3%      | Mild equity weakness, not a panic      |
| volatility | +15%     | Modest vol increase on uncertainty     |
| tech       | +5%      | Tech benefits from lower rate expectations |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +3%    | Mild IV expansion                      |
| skew_steepening | +2%    | Modest put demand increase             |

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| SPY - TLT         | -0.30  | -0.50         | Bonds rally, stocks dip    |
| SPY - GLD         | 0.05   | 0.00          | Gold mixed on deflation    |
| QQQ - XLE         | 0.55   | -0.30         | Tech up, energy crushed    |
| TLT - GLD         | 0.25   | 0.10          | Both benefit but different magnitudes |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | -3%           | Minor impact on short puts      |
| Single-stock opts | -10% to +5%   | Energy/materials crushed, tech up |
| Bonds / TLT       | +5% to +8%    | Strong bond rally               |
| Gold / GLD        | -2% to +3%    | Mixed — deflation vs easing     |
| Cash              | 0%            | Cash gains purchasing power     |

## Trading Response

- **Immediate**: Close short puts on energy and commodity names. Tech positions are safe and may benefit. Consider adding long TLT exposure via bull put spreads.
- **Day 1-3**: Sell premium on tech names — lower rates support valuations, and the mild vol bump provides decent premium. Iron condors on QQQ work in this R1/R2 environment.
- **Day 5-10**: If deflation fears persist, lean into bond-friendly trades. If data improves, the deflation scare fades quickly and positions normalize.
- **Position sizing**: Normal sizing. This is a mild event — no need to reduce exposure significantly.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2015-08-24 | China devaluation  | SPX -11% | 40 (VIX)      | 20              |
| 2019-05-31 | Trade war deflation| SPX -7%  | 20 (VIX)      | 15              |
| 2014-10-15 | Global deflation scare| SPX -5%| 26 (VIX)      | 10              |
| 2016-01-20 | Oil/China fears    | SPX -10% | 27 (VIX)      | 30              |
