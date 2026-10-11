# Integrated Action-state retrospective evaluation

> Retrospective diagnostic only. This is not OOS evidence and cannot
> automatically promote thresholds or production behavior.

- Company Quality policy: company_quality_v1_2026-10-10
- Entry Quality policy: entry_quality_v1_2026-10-10
- Input dataset: outputs/historical_selection_v1_20261011_02/modal_download/datasets/datasets/entry_quality_dataset_risk_off.csv
- Watchlist source: mixed: pit_snapshots from 2026-09-22 + union_superset_approx before that (membership/etf_count approximated from earliest snapshot or current list; PIT data availability filters candidates; documented upward bias)
- Pre-strategy cross-section: True
- Attention cap: 15

## Action counts

| action_state | count |
| --- | --- |
| HOLD_MONITOR | 11115 |
| AVOID | 9838 |
| WATCH_BREAKOUT | 2115 |
| WATCH_PULLBACK | 1036 |
| PRIORITY_REVIEW | 921 |

## Overall Action cohorts

| action_state | horizon_days | n_valid_return | n_dates | mean_return | mean_excess_vs_qqq | hit_rate | date_equal_weight_mean_return | date_equal_weight_mean_excess_vs_qqq | worst_date_mean_return |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PRIORITY_REVIEW | 20 | 921 | 38 | 0.0113 | -0.0051 | 0.5342 | 0.0082 | -0.0093 | -0.1161 |
| PRIORITY_REVIEW | 60 | 921 | 38 | 0.0256 | -0.0289 | 0.5527 | 0.0288 | -0.0370 | -0.1589 |
| PRIORITY_REVIEW | 120 | 921 | 38 | 0.0766 | -0.0346 | 0.5939 | 0.0759 | -0.0518 | -0.0965 |
| WATCH_PULLBACK | 20 | 1036 | 38 | 0.0269 | 0.0103 | 0.5946 | 0.0243 | 0.0061 | -0.0808 |
| WATCH_PULLBACK | 60 | 1036 | 38 | 0.0815 | 0.0242 | 0.6091 | 0.0670 | 0.0045 | -0.1757 |
| WATCH_PULLBACK | 120 | 1036 | 38 | 0.1582 | 0.0458 | 0.6486 | 0.1516 | 0.0283 | -0.0961 |
| WATCH_BREAKOUT | 20 | 2115 | 39 | 0.0094 | -0.0058 | 0.5092 | 0.0118 | -0.0064 | -0.0859 |
| WATCH_BREAKOUT | 60 | 2115 | 39 | 0.0498 | -0.0108 | 0.5612 | 0.0503 | -0.0149 | -0.0926 |
| WATCH_BREAKOUT | 120 | 2115 | 39 | 0.1049 | -0.0189 | 0.6189 | 0.0991 | -0.0284 | -0.0688 |
| HOLD_MONITOR | 20 | 11115 | 39 | 0.0102 | -0.0087 | 0.5143 | 0.0083 | -0.0099 | -0.0734 |
| HOLD_MONITOR | 60 | 11115 | 39 | 0.0454 | -0.0224 | 0.5458 | 0.0389 | -0.0263 | -0.1207 |
| HOLD_MONITOR | 120 | 11115 | 39 | 0.0962 | -0.0334 | 0.5669 | 0.0873 | -0.0402 | -0.0734 |
| AVOID | 20 | 9838 | 39 | 0.0310 | 0.0127 | 0.5052 | 0.0331 | 0.0149 | -0.1032 |
| AVOID | 60 | 9838 | 39 | 0.1071 | 0.0426 | 0.5421 | 0.1146 | 0.0494 | -0.1676 |
| AVOID | 120 | 9838 | 39 | 0.2097 | 0.0812 | 0.5744 | 0.2202 | 0.0927 | 0.0006 |

## Attention compactness

| n_dates | mean_non_avoid | median_non_avoid | mean_capped_attention | max_capped_attention | dates_over_cap |
| --- | --- | --- | --- | --- | --- |
| 39.0000 | 389.4103 | 398.0000 | 15.0000 | 15.0000 | 39.0000 |

## Concentration

| action_state | n_decisions | n_symbols | n_dates | top_symbol | top_symbol_share | top_date | top_date_share |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PRIORITY_REVIEW | 921 | 241 | 38 | FAST | 0.0141 | 2023-08-31 | 0.0608 |
| WATCH_PULLBACK | 1036 | 257 | 38 | CAMT | 0.0164 | 2025-05-30 | 0.0531 |
| WATCH_BREAKOUT | 2115 | 304 | 39 | TEL | 0.0104 | 2023-09-29 | 0.0454 |
| HOLD_MONITOR | 11115 | 549 | 39 | BSY | 0.0035 | 2026-03-31 | 0.0343 |
| AVOID | 9838 | 508 | 39 | EVLV | 0.0040 | 2023-02-28 | 0.0354 |

## Validation discipline

- Quality and Entry policies remain the frozen v1 policies.
- Action mapping is the canonical deterministic mapping.
- Year and regime splits are stored in the cohort CSV.
- Capped attention counts measure product compression, not portfolio sizing.
- Overlapping long-horizon labels are not treated as independent significance.
