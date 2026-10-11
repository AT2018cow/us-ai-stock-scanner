# Entry Quality v1 — Retrospective State Evaluation

> Retrospective diagnostic only. This is not OOS evidence and does not
> auto-promote Entry thresholds or production behavior.

- Entry policy version: entry_quality_v1_2026-10-10
- Company Quality policy version: company_quality_v1_2026-10-10
- Input dataset: outputs/historical_selection_v1_20261011_02/modal_download/datasets/datasets/entry_quality_dataset_risk_off.csv
- Dataset kind: entry_quality
- Watchlist source: mixed: pit_snapshots from 2026-09-22 + union_superset_approx before that (membership/etf_count approximated from earliest snapshot or current list; PIT data availability filters candidates; documented upward bias)
- Pre-strategy cross-section: True
- Quality A/B decision rows: 16010

## Entry state counts

| entry_state | count |
| --- | --- |
| TREND_DAMAGED | 5785 |
| WATCH_BREAKOUT | 4969 |
| WATCH_PULLBACK | 2392 |
| ENTRY_READY | 2041 |
| INSUFFICIENT_DATA | 823 |

## Overall state cohorts

| entry_state | horizon_days | n_valid_return | n_dates | mean_return | mean_excess_vs_qqq | hit_rate | date_equal_weight_mean_return | date_equal_weight_mean_excess_vs_qqq | worst_date_mean_return | worst_date_mean_excess_vs_qqq |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ENTRY_READY | 20 | 2041 | 39 | 0.0095 | -0.0072 | 0.5169 | 0.0089 | -0.0093 | -0.0922 | -0.0819 |
| ENTRY_READY | 60 | 2041 | 39 | 0.0301 | -0.0256 | 0.5502 | 0.0348 | -0.0304 | -0.1140 | -0.1795 |
| ENTRY_READY | 120 | 2041 | 39 | 0.0814 | -0.0290 | 0.6075 | 0.0881 | -0.0394 | -0.0718 | -0.2470 |
| WATCH_PULLBACK | 20 | 2392 | 39 | 0.0223 | 0.0071 | 0.5564 | 0.0190 | 0.0008 | -0.0904 | -0.0845 |
| WATCH_PULLBACK | 60 | 2392 | 39 | 0.0672 | 0.0095 | 0.5564 | 0.0564 | -0.0088 | -0.2235 | -0.1966 |
| WATCH_PULLBACK | 120 | 2392 | 39 | 0.1537 | 0.0403 | 0.5974 | 0.1495 | 0.0220 | -0.0465 | -0.2957 |
| WATCH_BREAKOUT | 20 | 4969 | 39 | 0.0069 | -0.0083 | 0.5061 | 0.0086 | -0.0096 | -0.0814 | -0.0843 |
| WATCH_BREAKOUT | 60 | 4969 | 39 | 0.0450 | -0.0137 | 0.5558 | 0.0481 | -0.0171 | -0.0990 | -0.1644 |
| WATCH_BREAKOUT | 120 | 4969 | 39 | 0.0934 | -0.0286 | 0.5955 | 0.0917 | -0.0358 | -0.0596 | -0.2225 |
| TREND_DAMAGED | 20 | 5785 | 39 | 0.0111 | -0.0110 | 0.5188 | 0.0044 | -0.0138 | -0.0758 | -0.0778 |
| TREND_DAMAGED | 60 | 5785 | 39 | 0.0471 | -0.0304 | 0.5494 | 0.0251 | -0.0401 | -0.1389 | -0.1810 |
| TREND_DAMAGED | 120 | 5785 | 39 | 0.0913 | -0.0503 | 0.5533 | 0.0628 | -0.0647 | -0.1333 | -0.2506 |
| INSUFFICIENT_DATA | 20 | 823 | 28 | 0.0050 | -0.0157 | 0.4787 | 0.0076 | -0.0133 | -0.1449 | -0.1384 |
| INSUFFICIENT_DATA | 60 | 823 | 28 | 0.0093 | -0.0529 | 0.4860 | 0.0442 | -0.0259 | -0.1501 | -0.2436 |
| INSUFFICIENT_DATA | 120 | 823 | 28 | 0.0441 | -0.1023 | 0.5541 | 0.0629 | -0.0720 | -0.1853 | -0.4078 |

## Concentration

| entry_state | n_decisions | n_symbols | n_dates | top_symbol | top_symbol_share | top_date | top_date_share |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ENTRY_READY | 2041 | 427 | 39 | FAST | 0.0078 | 2023-08-31 | 0.0583 |
| WATCH_PULLBACK | 2392 | 487 | 39 | VRT | 0.0071 | 2023-12-29 | 0.0585 |
| WATCH_BREAKOUT | 4969 | 518 | 39 | ECL | 0.0052 | 2024-04-30 | 0.0400 |
| TREND_DAMAGED | 5785 | 538 | 39 | FIVN | 0.0052 | 2025-04-30 | 0.0500 |
| INSUFFICIENT_DATA | 823 | 128 | 28 | CCSI | 0.0109 | 2023-07-31 | 0.1324 |

## State persistence

| from_state | n_transitions | same_state_rate | median_gap_days |
| --- | --- | --- | --- |
| ENTRY_READY | 2003 | 0.2806 | 30.0000 |
| INSUFFICIENT_DATA | 819 | 0.8486 | 31.0000 |
| TREND_DAMAGED | 5490 | 0.7554 | 31.0000 |
| WATCH_BREAKOUT | 4793 | 0.4571 | 31.0000 |
| WATCH_PULLBACK | 2352 | 0.3376 | 31.0000 |
| ALL | 15457 | 0.5427 | 31.0000 |

## Validation discipline

- Entry thresholds are frozen in docs/entry_quality_v1_policy.md before final outcome inspection.
- Entry evaluation is conditioned on Company Quality A/B.
- The dataset is drawn before legacy list-specific hard gates.
- ENTRY_READY explicitly excludes extreme recent-return / SMA50-extension cases.
- Year, regime and Quality-grade splits are stored in the cohort CSV.
- Transition diagnostics describe consecutive Quality-eligible observations for each symbol.
- Long-horizon overlapping observations are not presented as independent statistical significance.
