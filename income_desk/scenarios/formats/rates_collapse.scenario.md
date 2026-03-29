---
key: rates_collapse
name: "Rate Collapse / Flight to Safety"
category: macro
severity: moderate
historical_analog: "2019 rate inversion, 2020 March"
expected_duration_days: 20
monte_carlo_paths: 1000
---

# Rate Collapse / Flight to Safety

## Narrative

Recession fears trigger a dramatic collapse in interest rates as money floods into treasuries. The 10-year yield drops 100bp+ as the market prices in aggressive rate cuts. Bond prices surge, generating outsized returns for long-duration holders. Equities sell off as the recession signal spooks risk assets, but the decline is measured rather than panicked — this is a slow grind driven by deteriorating economic data rather than a sudden shock. Gold rallies as both a safe haven and on lower real rates. The yield curve may un-invert or steepen dramatically. Defensive sectors (utilities, staples, healthcare) outperform while cyclicals and financials underperform.

## Trigger Conditions

- ISM Manufacturing drops below 45
- Non-farm payrolls miss expectations significantly (negative print)
- Fed pivots to emergency rate cuts
- Yield curve inversion deepens then rapidly steepens
- Leading economic indicators decline for 6+ consecutive months

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| rates      | +20%     | Bond prices surge on rate collapse     |
| equity     | -8%      | Recession fears hit equities           |
| volatility | +40%     | Uncertainty rises on growth scare      |
| commodity  | +10%     | Gold rallies on lower real rates       |
| tech       | -3%      | Growth stocks mixed — lower rates help but recession hurts |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +8%    | Elevated vol on recession pricing      |
| skew_steepening | +5%    | Downside protection demand increases   |

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| SPY - TLT         | -0.30  | -0.60         | Classic flight to safety   |
| SPY - GLD         | 0.05   | -0.20         | Gold rises as equities fall|
| QQQ - TLT         | -0.25  | -0.50         | Bonds rally while growth sells |
| XLF - TLT         | -0.35  | -0.65         | Banks crushed, bonds surge |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | -8%           | Short puts tested, need adjustment |
| Single-stock opts | -5% to -15%   | Cyclicals and banks hit hardest |
| Bonds / TLT       | +10% to +15%  | Massive bond rally             |
| Gold / GLD        | +5% to +10%   | Strong rally on lower rates    |
| Cash              | 0%            | Lock in yields before they fall further |

## Trading Response

- **Immediate**: Take profits on any long TLT/bond positions. Reduce cyclical and financial short put exposure. Shift equity exposure to defensive names (utilities, staples). This is R3/R4 for cyclicals.
- **Day 1-3**: Sell premium on defensive stocks where IV is lower. Put credit spreads on XLU, XLP. Avoid banks (XLF) — lower rates compress NIMs. Gold bull put spreads benefit from lower rate thesis.
- **Day 5-10**: If recession signals intensify, reduce overall equity exposure further. TLT call spreads if the bond rally has room to run. Watch Fed communication closely for emergency cut signals.
- **Position sizing**: Reduce equity to 50-75% of normal. Increase bond/gold allocation. The slow grind means patience is rewarded.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2020-03-09 | COVID rate collapse | 10Y: 0.5%| 54 (VIX)     | N/A (new regime)|
| 2019-08-14 | Yield curve inversion| SPX -6% | 22 (VIX)     | 15              |
| 2019-06-03 | Trade war recession fear| SPX -7%| 20 (VIX)    | 30              |
| 2011-08-05 | US downgrade       | 10Y: 2.0%| 48 (VIX)     | 60              |
