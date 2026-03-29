---
key: rates_shock_up
name: "10Y Yield +100bp Spike"
category: macro
severity: moderate
historical_analog: "2022 rate shock, 2023 Q3 long-end sell-off"
expected_duration_days: 15
monte_carlo_paths: 1000
---

# 10Y Yield +100bp Spike

## Narrative

The 10-year Treasury yield spikes 100 basis points in a rapid move, crashing bond prices and hammering growth/tech stocks whose valuations depend on low discount rates. Banks and financials rally on improved net interest margins. The rate shock reprices the entire equity market — anything trading on a high P/E multiple gets crushed as the risk-free rate jumps. Mortgage rates surge, impacting housing-related stocks. The move is typically driven by hotter-than-expected inflation data, a hawkish Fed pivot, or a sudden loss of confidence in fiscal sustainability (bond vigilantes). Volatility increases as the market recalibrates fair value for all assets.

## Trigger Conditions

- 10Y yield rises 30bp+ in a single week
- Fed signals fewer rate cuts than market expects
- CPI/PCE prints significantly above consensus
- Treasury auction shows weak demand (tail > 3bp)
- Term premium surges on fiscal deficit concerns

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| rates      | -15%     | Bond prices crash on yield spike       |
| equity     | -5%      | Broad equity repricing on higher rates |
| tech       | -10%     | Growth/tech hammered by higher discount rates |
| volatility | +25%     | Uncertainty spikes on rate regime change|

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +5%    | Moderate IV expansion                  |
| skew_steepening | +3%    | Tech put demand increases              |

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| SPY - TLT         | -0.30  | 0.20          | Stocks and bonds sell together |
| QQQ - TLT         | -0.25  | 0.35          | Growth and bonds positively correlated |
| SPY - GLD         | 0.05   | -0.05         | Gold mixed on real rate rise|
| XLF - QQQ         | 0.60   | -0.20         | Banks rally, tech sells — divergence |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | -5%           | Moderate equity pullback        |
| Single-stock opts | -10% to +5%   | Tech crushed, banks rally       |
| Bonds / TLT       | -8% to -12%   | Major bond losses              |
| Gold / GLD        | -2% to +1%    | Mixed — real rates vs uncertainty |
| Cash              | 0%            | Higher yields on new money      |

## Trading Response

- **Immediate**: Close any long TLT or bond positions. Reduce QQQ/tech short put exposure. Financials (XLF) short puts are safe — banks benefit from higher rates.
- **Day 1-3**: Sell premium on tech names where IV has spiked. QQQ put spreads at wider widths. Sell call spreads on TLT if rates are still rising. This is R2 for tech (high-vol mean reverting).
- **Day 5-10**: Watch for yield stabilization. Once 10Y finds a level, tech starts to stabilize. Begin rebuilding tech premium selling positions. The rate adjustment creates a new equilibrium.
- **Position sizing**: Normal for financials, 50% for tech until rates stabilize.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2023-10-19 | 10Y hits 5%        | SPX -8%  | 22 (VIX)      | 30              |
| 2022-06-14 | Fed +75bp          | SPX -5%  | 34 (VIX)      | 15              |
| 2022-01-05 | Rate shock begins  | QQQ -15% | 30 (VIX)      | 60              |
| 2018-02-02 | Wage inflation scare| SPX -10%| 37 (VIX)      | 20              |
