# Integrated Action-state retrospective evaluation

> Retrospective diagnostic only. This is not OOS evidence and cannot
> automatically promote thresholds or production behavior.

- Company Quality policy: company_quality_v1_2026-10-10
- Entry Quality policy: entry_quality_v1_2026-10-10
- Input dataset: outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv
- Watchlist source: mixed: pit_snapshots from 2026-09-22 + union_superset_approx before that (membership/etf_count approximated from earliest snapshot or current list; PIT data availability filters candidates; documented upward bias)
- Pre-strategy cross-section: True
- Attention cap: 15

## Action counts

| action_state | count |
| --- | --- |
| HOLD_MONITOR | 11106 |
| AVOID | 9811 |
| WATCH_BREAKOUT | 2137 |
| WATCH_PULLBACK | 1042 |
| PRIORITY_REVIEW | 929 |

## Overall Action cohorts

| action_state | horizon_days | n_valid_return | n_dates | mean_return | mean_excess_vs_qqq | hit_rate | date_equal_weight_mean_return | date_equal_weight_mean_excess_vs_qqq | worst_date_mean_return |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PRIORITY_REVIEW | 20 | 929 | 38 | 0.0123 | -0.0041 | 0.5350 | 0.0097 | -0.0078 | -0.1161 |
| PRIORITY_REVIEW | 60 | 929 | 38 | 0.0279 | -0.0261 | 0.5544 | 0.0330 | -0.0328 | -0.1610 |
| PRIORITY_REVIEW | 120 | 929 | 38 | 0.0801 | -0.0310 | 0.5974 | 0.0796 | -0.0481 | -0.0965 |
| WATCH_PULLBACK | 20 | 1042 | 38 | 0.0273 | 0.0108 | 0.5960 | 0.0244 | 0.0061 | -0.0808 |
| WATCH_PULLBACK | 60 | 1042 | 38 | 0.0840 | 0.0272 | 0.6113 | 0.0682 | 0.0056 | -0.1757 |
| WATCH_PULLBACK | 120 | 1042 | 38 | 0.1629 | 0.0507 | 0.6545 | 0.1522 | 0.0288 | -0.0961 |
| WATCH_BREAKOUT | 20 | 2137 | 39 | 0.0093 | -0.0058 | 0.5091 | 0.0117 | -0.0065 | -0.0862 |
| WATCH_BREAKOUT | 60 | 2137 | 39 | 0.0504 | -0.0103 | 0.5639 | 0.0508 | -0.0144 | -0.0943 |
| WATCH_BREAKOUT | 120 | 2137 | 39 | 0.1088 | -0.0149 | 0.6219 | 0.1032 | -0.0243 | -0.0686 |
| HOLD_MONITOR | 20 | 11106 | 39 | 0.0103 | -0.0086 | 0.5148 | 0.0084 | -0.0098 | -0.0734 |
| HOLD_MONITOR | 60 | 11106 | 39 | 0.0461 | -0.0219 | 0.5465 | 0.0393 | -0.0259 | -0.1207 |
| HOLD_MONITOR | 120 | 11106 | 39 | 0.0966 | -0.0331 | 0.5678 | 0.0876 | -0.0399 | -0.0734 |
| AVOID | 20 | 9811 | 39 | 0.0310 | 0.0127 | 0.5046 | 0.0331 | 0.0149 | -0.1034 |
| AVOID | 60 | 9809 | 39 | 0.1037 | 0.0391 | 0.5409 | 0.1111 | 0.0459 | -0.1676 |
| AVOID | 120 | 9806 | 39 | 0.2031 | 0.0745 | 0.5733 | 0.2134 | 0.0859 | 0.0006 |

## Attention compactness

| n_dates | mean_non_avoid | median_non_avoid | mean_capped_attention | max_capped_attention | dates_over_cap |
| --- | --- | --- | --- | --- | --- |
| 39.0000 | 390.1026 | 399.0000 | 15.0000 | 15.0000 | 39.0000 |

## Concentration

| action_state | n_decisions | n_symbols | n_dates | top_symbol | top_symbol_share | top_date | top_date_share |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PRIORITY_REVIEW | 929 | 241 | 38 | FAST | 0.0140 | 2024-01-31 | 0.0603 |
| WATCH_PULLBACK | 1042 | 258 | 38 | VRT | 0.0163 | 2025-05-30 | 0.0518 |
| WATCH_BREAKOUT | 2137 | 306 | 39 | TEL | 0.0103 | 2023-09-29 | 0.0454 |
| HOLD_MONITOR | 11106 | 550 | 39 | BSY | 0.0035 | 2026-03-31 | 0.0344 |
| AVOID | 9811 | 508 | 39 | EVLV | 0.0040 | 2023-02-28 | 0.0355 |

## Validation discipline

- Quality and Entry policies remain the frozen v1 policies.
- Action mapping is the canonical deterministic mapping.
- Year and regime splits are stored in the cohort CSV.
- Capped attention counts measure product compression, not portfolio sizing.
- Overlapping long-horizon labels are not treated as independent significance.
