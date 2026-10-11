# Entry Quality v1 — Retrospective State Evaluation

> Retrospective diagnostic only. This is not OOS evidence and does not
> auto-promote Entry thresholds or production behavior.

- Entry policy version: entry_quality_v1_2026-10-10
- Company Quality policy version: company_quality_v1_2026-10-10
- Input dataset: outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv
- Dataset kind: entry_quality
- Watchlist source: mixed: pit_snapshots from 2026-09-22 + union_superset_approx before that (membership/etf_count approximated from earliest snapshot or current list; PIT data availability filters candidates; documented upward bias)
- Pre-strategy cross-section: True
- Quality A/B decision rows: 16040

## Entry state counts

| entry_state | count |
| --- | --- |
| TREND_DAMAGED | 5783 |
| WATCH_BREAKOUT | 4987 |
| WATCH_PULLBACK | 2398 |
| ENTRY_READY | 2046 |
| INSUFFICIENT_DATA | 826 |

## Overall state cohorts

| entry_state | horizon_days | n_valid_return | n_dates | mean_return | mean_excess_vs_qqq | hit_rate | date_equal_weight_mean_return | date_equal_weight_mean_excess_vs_qqq | worst_date_mean_return | worst_date_mean_excess_vs_qqq |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ENTRY_READY | 20 | 2046 | 39 | 0.0099 | -0.0067 | 0.5176 | 0.0096 | -0.0086 | -0.0922 | -0.0819 |
| ENTRY_READY | 60 | 2046 | 39 | 0.0310 | -0.0245 | 0.5503 | 0.0366 | -0.0286 | -0.1161 | -0.1795 |
| ENTRY_READY | 120 | 2046 | 39 | 0.0830 | -0.0273 | 0.6090 | 0.0899 | -0.0376 | -0.0718 | -0.2470 |
| WATCH_PULLBACK | 20 | 2398 | 39 | 0.0226 | 0.0074 | 0.5575 | 0.0192 | 0.0010 | -0.0904 | -0.0845 |
| WATCH_PULLBACK | 60 | 2398 | 39 | 0.0691 | 0.0114 | 0.5584 | 0.0576 | -0.0076 | -0.2235 | -0.1966 |
| WATCH_PULLBACK | 120 | 2398 | 39 | 0.1570 | 0.0439 | 0.6009 | 0.1519 | 0.0244 | -0.0465 | -0.2957 |
| WATCH_BREAKOUT | 20 | 4987 | 39 | 0.0069 | -0.0083 | 0.5061 | 0.0086 | -0.0095 | -0.0815 | -0.0843 |
| WATCH_BREAKOUT | 60 | 4987 | 39 | 0.0454 | -0.0134 | 0.5570 | 0.0483 | -0.0169 | -0.0990 | -0.1644 |
| WATCH_BREAKOUT | 120 | 4987 | 39 | 0.0955 | -0.0265 | 0.5974 | 0.0938 | -0.0337 | -0.0589 | -0.2225 |
| TREND_DAMAGED | 20 | 5783 | 39 | 0.0114 | -0.0108 | 0.5193 | 0.0045 | -0.0137 | -0.0758 | -0.0776 |
| TREND_DAMAGED | 60 | 5783 | 39 | 0.0480 | -0.0296 | 0.5504 | 0.0257 | -0.0395 | -0.1389 | -0.1810 |
| TREND_DAMAGED | 120 | 5783 | 39 | 0.0911 | -0.0505 | 0.5544 | 0.0626 | -0.0649 | -0.1333 | -0.2506 |
| INSUFFICIENT_DATA | 20 | 826 | 28 | 0.0051 | -0.0155 | 0.4794 | 0.0077 | -0.0132 | -0.1449 | -0.1384 |
| INSUFFICIENT_DATA | 60 | 826 | 28 | 0.0100 | -0.0523 | 0.4879 | 0.0444 | -0.0257 | -0.1501 | -0.2436 |
| INSUFFICIENT_DATA | 120 | 826 | 28 | 0.0449 | -0.1015 | 0.5557 | 0.0632 | -0.0717 | -0.1853 | -0.4078 |

## Concentration

| entry_state | n_decisions | n_symbols | n_dates | top_symbol | top_symbol_share | top_date | top_date_share |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ENTRY_READY | 2046 | 428 | 39 | FAST | 0.0078 | 2023-08-31 | 0.0582 |
| WATCH_PULLBACK | 2398 | 488 | 39 | POWL | 0.0071 | 2023-12-29 | 0.0580 |
| WATCH_BREAKOUT | 4987 | 518 | 39 | ECL | 0.0052 | 2024-04-30 | 0.0401 |
| TREND_DAMAGED | 5783 | 539 | 39 | FIVN | 0.0052 | 2025-04-30 | 0.0501 |
| INSUFFICIENT_DATA | 826 | 129 | 28 | CCSI | 0.0109 | 2023-07-31 | 0.1332 |

## State persistence

| from_state | n_transitions | same_state_rate | median_gap_days |
| --- | --- | --- | --- |
| ENTRY_READY | 2008 | 0.2809 | 30.0000 |
| INSUFFICIENT_DATA | 822 | 0.8479 | 31.0000 |
| TREND_DAMAGED | 5487 | 0.7551 | 31.0000 |
| WATCH_BREAKOUT | 4811 | 0.4581 | 31.0000 |
| WATCH_PULLBACK | 2358 | 0.3388 | 31.0000 |
| ALL | 15486 | 0.5429 | 31.0000 |

## Validation discipline

- Entry thresholds are frozen in docs/entry_quality_v1_policy.md before final outcome inspection.
- Entry evaluation is conditioned on Company Quality A/B.
- The dataset is drawn before legacy list-specific hard gates.
- ENTRY_READY explicitly excludes extreme recent-return / SMA50-extension cases.
- Year, regime and Quality-grade splits are stored in the cohort CSV.
- Transition diagnostics describe consecutive Quality-eligible observations for each symbol.
- Long-horizon overlapping observations are not presented as independent statistical significance.
