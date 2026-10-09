# PR27 alpha-attribution decision note

Date: 2026-10-09
Inputs: frozen `weight_dataset_risk_off.csv` (SHA `4a0203d9…`, unchanged) +
corrected `weight_dataset_risk_on.csv` (SHA `295e3de8…`, 30355 rows / 42
dates, rebuilt once on Modal with the style-aware extractor).

## Mechanism that survives (1 of 1)

**risk_off range/position hard gates exclude continuation winners in
low_value.** Over 2023+2025, 412 risk_on-only channel-selection cases:

- `hard:max_range_position_52w`: 189 cases, 117 QQQ-winners, avg +11.7%
- `hard:min_drawdown_from_52w_high`: 98 cases, 61 winners, avg +14.4%
- `hard:max_price_to_sma200`: 96 cases, 58 winners, avg +14.6%
- paired per-date substitution diagnostic: +11.5%
- top misses: MU (+296%), LRCX (+146%), NVDA (+123%), VRT (+116%),
  AMAT (+85%), KLAC (+89%) — all extended names (near 52w high, above
  SMA200) that kept running.

Repeated soft co-failures (`max_ps/ps_hist_percentile`, `max_20d_return`,
`min_value_discount_any`) confirm the same "don't chase extended value"
posture in scored mode.

## Ranking check

Production-score rank IC is positive in every list/horizon cell
(0.02–0.10; momentum 120d strongest at ~0.095, t≈4.5–4.8). Top-minus-bottom
decile excess is positive except risk_off low_value 20d/60d (small negative).
The score ranks; it is the defensive hard gates — not the score — that
remove the edge.

## PR28 candidate (one mechanism only)

Narrow ablation: relax the low_value range/position hard gates
(`max_range_position_52w`, `min_drawdown_from_52w_high`,
`max_price_to_sma200`) toward soft/neutral for risk_off low_value and test
on the frozen datasets + anchored folds. No production change, no broad
parameter search, no replay until the offline mechanism is stable.
