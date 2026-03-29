---
key: commodity_meltup
name: "Commodity Super-Cycle Meltup"
category: rally
severity: moderate
historical_analog: "2021-2022 commodity rally"
expected_duration_days: 30
monte_carlo_paths: 1000
---

# Commodity Super-Cycle Meltup

## Narrative

A broad-based commodity rally where oil, gold, copper, and agricultural commodities all surge simultaneously. This is an inflationary boom scenario — strong global demand collides with supply constraints. Energy stocks lead equity markets higher while the broader index benefits modestly from the reflationary impulse. However, the rally carries the seed of its own destruction: rising input costs eventually squeeze margins and force central banks to tighten, creating a late-cycle dynamic. Volatility increases as markets oscillate between "growth is strong" and "inflation is out of control" narratives. The USD weakens as commodity currencies (AUD, CAD, BRL) strengthen.

## Trigger Conditions

- Oil breaks above $100/barrel on supply disruption
- Copper hits all-time highs on global infrastructure spending
- Gold breaks out above key resistance on inflation fears
- Bloomberg Commodity Index rises 10%+ in a month
- Central banks signal tolerance for above-target inflation

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| commodity  | +20%    | Broad commodity rally across sectors   |
| equity     | +3%      | Modest equity benefit from reflation   |
| rates      | -5%      | Bond sell-off on inflation fears       |
| volatility | +15%     | Uncertainty rises on inflation debate  |
| currency   | -3%      | USD weakens vs commodity currencies    |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +3%    | Mild IV increase on uncertainty        |
| skew_steepening | +1%    | Balanced skew — upside calls also bid  |

## Cross-Asset Correlations

| Pair              | Normal | This Scenario | Why                        |
|-------------------|--------|---------------|----------------------------|
| SPY - GLD         | 0.05   | 0.25          | Both rally on reflation    |
| SPY - TLT         | -0.30  | -0.45         | Stocks up, bonds down      |
| GLD - TLT         | 0.25   | -0.10         | Gold rallies, bonds sell   |
| XLE - SPY         | 0.65   | 0.40          | Energy outperforms broad market |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | +3%           | Short call wings at risk on rally |
| Single-stock opts | +5% to +15%   | Energy, materials, miners surge |
| Bonds / TLT       | -3% to -5%   | Bond positions lose on inflation|
| Gold / GLD        | +10% to +15% | Gold rallies strongly           |
| Cash              | 0%            | Purchasing power erodes with inflation |

## Trading Response

- **Immediate**: Close short call positions on energy and commodity names. Review iron condor call wings — they may be threatened by the upside move. This is R3 territory for commodity names.
- **Day 1-3**: Lean into commodity exposure with bull put spreads on XLE, GDX, or gold miners. The uptrend rewards directional strategies. Avoid heavy theta on trending commodity names.
- **Day 5-10**: Watch for inflation data to confirm the move. If CPI/PPI accelerate, the rally has legs — maintain commodity long bias. If inflation data is mixed, the rally may stall.
- **Position sizing**: Normal sizing for commodity trades. Reduce bond-related short put positions as yields may rise further.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2022-03-08 | Ukraine oil spike  | Oil +30% | 36 (VIX)      | N/A (inflation) |
| 2021-10-01 | Commodity supercycle| BCOM +25%| 20 (VIX)      | N/A             |
| 2008-07-03 | Oil at $147        | Oil +50% | 24 (VIX)      | Crash followed  |
| 2011-04-01 | Gold/silver rally  | Gold +15%| 18 (VIX)      | 90              |
