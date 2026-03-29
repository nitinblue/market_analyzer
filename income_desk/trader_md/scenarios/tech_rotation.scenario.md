---
key: tech_rotation
name: "Tech-to-Value Rotation"
category: rotation
severity: moderate
historical_analog: "2021 Q1 rotation, 2022 value outperformance"
expected_duration_days: 20
monte_carlo_paths: 1000
---

# Tech-to-Value Rotation

## Narrative

Money rotates aggressively from technology and growth stocks into value, cyclical, and small-cap names. QQQ drops 10-12% while IWM and value indices rally. The rotation is driven by rising rates, improving economic data, or a repricing of tech multiples after an extended AI/momentum run. The S&P 500 itself is roughly flat because the decline in mega-cap tech is offset by broad participation elsewhere. This is a diversification event, not a crash — total market cap may even increase. However, for concentrated tech portfolios (or income traders selling premium on FAANG), the move is painful. Volatility is sector-specific rather than market-wide.

## Trigger Conditions

- QQQ underperforms IWM by 5%+ over two weeks
- 10Y yield rises while SPX is flat or up
- Value factor (HML) outperforms momentum by 3%+ in a month
- FAANG earnings disappoint while cyclical earnings beat
- Concentration ratio (top 10 stocks as % of SPX) starts declining

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| tech       | -12%     | Tech sector rotation out               |
| equity     | +2%      | Broad market flat to slightly up       |
| rates      | -3%      | Rates rise modestly, hurting growth    |
| commodity  | +5%      | Cyclical/commodity stocks benefit      |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +0%    | No broad IV shift — sector-specific    |
| skew_steepening | +2%    | Tech put skew increases                |

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| QQQ - IWM         | 0.75   | 0.20          | Dramatic divergence         |
| SPY - QQQ         | 0.85   | 0.60          | SPX held up by non-tech     |
| QQQ - XLF         | 0.50   | -0.15         | Banks rally, tech sells     |
| SPY - TLT         | -0.30  | -0.20         | Normal relationship         |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | 0% to +2%    | SPY positions mostly safe       |
| Single-stock opts | -12% to +8%  | AAPL, NVDA down; banks, industrials up |
| Bonds / TLT       | -2%           | Mild bond weakness on rising rates |
| Gold / GLD        | +1% to +3%   | Modest commodity bid            |
| Cash              | 0%            | Redeploy from tech to value     |

## Trading Response

- **Immediate**: Close short puts on QQQ and mega-cap tech names (NVDA, AAPL, MSFT). Do NOT close SPY positions — the index is held up by value rotation. Assess any FAANG-concentrated positions.
- **Day 1-3**: Sell premium on value names that are rallying (banks, industrials). XLF, XLI put spreads benefit from the rotation. Avoid selling tech premium until the rotation shows signs of exhaustion (R3 for tech = directional, avoid theta).
- **Day 5-10**: Watch for rotation exhaustion signals (IWM momentum fading, tech bouncing). Once tech stabilizes, rebuild tech premium selling at lower strikes — you get better entry points on quality names.
- **Position sizing**: Normal for value/cyclical. Reduce tech to 25-50% until rotation stabilizes. SPY sizing unchanged.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2021-03-08 | Growth-to-value    | QQQ -10% | 24 (VIX)      | 30              |
| 2022-01-03 | Rate-driven rotation| QQQ -15%| 28 (VIX)      | 60              |
| 2020-09-02 | Post-COVID rotation| QQQ -12% | 33 (VIX)      | 20              |
| 2016-11-09 | Trump reflation    | QQQ -3%  | 15 (VIX)      | 10              |
