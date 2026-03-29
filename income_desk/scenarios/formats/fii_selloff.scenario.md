---
key: fii_selloff
name: "FII Mass Selling"
category: crash
severity: moderate
historical_analog: "2024 Q4 FII outflows"
expected_duration_days: 20
monte_carlo_paths: 1000
---

# FII Mass Selling

## Narrative

Foreign institutional investors engage in sustained, aggressive selling of Indian equities — typically Rs 10,000-20,000 crore per week for multiple weeks. This is not a single-day event but a persistent grind lower as large foreign funds reallocate away from India (to China, other EMs, or back to US). The selling creates a reflexive loop: FII outflows weaken INR, which makes India returns even worse in USD terms, prompting more selling. BANKNIFTY and large-cap financials bear the brunt as they have the highest FII ownership. Mid-caps and small-caps may initially be spared but eventually get caught in the downdraft. The correction is gradual but relentless, making it harder to time than a sharp crash.

## Trigger Conditions

- FII net selling exceeds Rs 50,000 crore in a month
- DXY strengthens above 107, making EM allocations unattractive
- China stimulus redirects EM flows away from India
- India valuation premium (PE/PB vs EM peers) becomes unsustainable
- MSCI India weight reduction triggers passive outflows

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| equity     | -8%      | Sustained FII selling pressure         |
| rates      | +2%      | Modest rates impact                    |
| volatility | +40%     | India VIX rises on persistent weakness |
| currency   | -8%      | INR depreciation from capital outflows |
| tech       | -5%      | IT sector hit by USD strength narrative|

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +6%    | Gradual IV build rather than spike     |
| skew_steepening | +4%    | Hedging demand grows over time         |

## Cross-Asset Correlations

| Pair                  | Normal | This Scenario | Why                        |
|-----------------------|--------|---------------|----------------------------|
| NIFTY - BANKNIFTY     | 0.90   | 0.93          | Banks sell hardest (FII heavy)|
| NIFTY - INR (inverse) | 0.40   | 0.75          | Strong equity-currency reflexivity |
| NIFTY - US (SPY)      | 0.35   | 0.15          | Decoupling — India-specific selloff |
| BANKNIFTY - HDFC/ICICI| 0.85   | 0.95          | Large-cap banks sell in lockstep |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | -8%           | Short puts gradually erode, hard to time exit |
| Single-stock opts | -8% to -15%   | FII-heavy names (HDFC, Infosys, RIL) worst hit |
| Bonds / Gilts     | -1%           | Minor yield rise from INR pressure |
| Gold / SGBs       | +4% to +6%    | Gold in INR terms benefits greatly |
| Cash              | 0%            | Best deployed gradually as selling exhausts |

## Trading Response

- **Immediate**: Reduce NIFTY/BANKNIFTY short put exposure by 50%. Do not fight FII flows — they have more capital than domestic markets can absorb quickly. Shift to R2 strategies.
- **Day 1-3**: Monitor daily FII flow data (NSE publishes by 6pm). Sell premium only on days when FII selling pace slows. Use weekly expiry to limit exposure duration.
- **Day 5-10**: If FII selling continues, shift to bear put spreads (directional). The grind lower is R3/R4 territory. Consider gold (SGBs) as a portfolio hedge given INR weakness amplifies gold returns.
- **Position sizing**: Reduce to 50% of normal. The slow grind is deceptive — cumulative losses compound. Keep dry powder for when FII flows stabilize.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2024-10-01 | Q4 2024 FII selling| -8%      | 17            | 45              |
| 2022-03-01 | Ukraine war FII exit| -6%     | 28            | 30              |
| 2018-09-01 | EM contagion       | -10%     | 20            | 60              |
| 2016-11-01 | Demonetization     | -7%      | 18            | 30              |
