---
key: rbi_rate_hike
name: "RBI Surprise Rate Hike"
category: macro
severity: mild
historical_analog: "2022 surprise rate hike cycle"
expected_duration_days: 3
monte_carlo_paths: 1000
---

# RBI Surprise Rate Hike

## Narrative

The RBI delivers an unexpected 50bp rate hike outside the normal policy cycle or significantly above consensus expectations. Banking stocks initially rally on improved net interest margins, while rate-sensitive sectors (real estate, autos, NBFCs) sell off. The rupee strengthens modestly as higher rates attract carry trade flows. India VIX spikes briefly but normalizes quickly as the market digests the move. The broader NIFTY dips 2-3% as growth expectations are revised lower, but the correction is shallow because the rate hike is seen as inflation-fighting credibility (positive for long-term stability).

## Trigger Conditions

- RBI announces unscheduled policy meeting
- Inflation prints significantly above RBI's 6% upper band
- INR depreciates sharply, forcing RBI's hand on rates
- Global central banks (Fed, ECB) deliver hawkish surprises, pressuring RBI to follow

## Factor Shocks

| Factor     | Shock    | Rationale                              |
|------------|----------|----------------------------------------|
| equity     | -3%      | Mild growth concern from tighter policy|
| rates      | +15%     | Bond yields spike on rate hike         |
| volatility | +20%     | Brief uncertainty spike                |
| currency   | +3%      | INR strengthens on higher rate differential |

## IV Regime Shift

| Metric          | Value  | Rationale                              |
|-----------------|--------|----------------------------------------|
| iv_shift        | +3%    | Mild IV expansion, normalizes quickly  |
| skew_steepening | +2%    | Modest put demand on uncertainty       |

## Cross-Asset Correlations

| Pair                  | Normal | This Scenario | Why                        |
|-----------------------|--------|---------------|----------------------------|
| NIFTY - BANKNIFTY     | 0.90   | 0.75          | Banks outperform, NIFTY dips — divergence |
| NIFTY - INR (inverse) | 0.40   | 0.20          | INR strengthens while NIFTY dips |
| BANKNIFTY - Realty    | 0.50   | -0.30         | Banks rally, real estate sells |
| NIFTY - Gold (INR)    | -0.05  | -0.10         | Minimal gold impact        |

## Impact by Asset Class

| Asset Class       | Expected Move | Positioning Impact              |
|-------------------|---------------|---------------------------------|
| Index options     | -3%           | Minor impact on NIFTY positions |
| Single-stock opts | -5% to +5%    | Sector rotation — banks up, NBFCs down |
| Bonds / Gilts     | -3% to -5%    | Bond prices fall on rate hike  |
| Gold / SGBs       | -1%           | Minor negative from INR strength|
| Cash              | 0%            | Higher FD rates available       |

## Trading Response

- **Immediate**: No panic needed. This is R2 (mild) — close any short straddles on rate-sensitive names (DLF, Bajaj Finance). Banking positions can ride.
- **Day 1-3**: Sell premium on the IV spike. BANKNIFTY iron condors work well here — the bank index often stabilizes quickly after rate decisions. Use weekly expiry for faster theta decay.
- **Day 5-10**: IV normalizes. Return to R1 strategies. Look for mean-reversion trades on sectors that overreacted (NBFCs that sold off too much).
- **Position sizing**: Normal sizing. This is a mild, short-duration event.

## Historical Data Points

| Date       | Event              | Move     | VIX/India VIX | Recovery (days) |
|------------|--------------------|----------|---------------|-----------------|
| 2022-05-04 | Surprise 40bp hike | -1.5%    | 20            | 2               |
| 2022-06-08 | 50bp hike          | -0.8%    | 18            | 1               |
| 2018-06-06 | Unexpected hike    | -0.5%    | 14            | 1               |
