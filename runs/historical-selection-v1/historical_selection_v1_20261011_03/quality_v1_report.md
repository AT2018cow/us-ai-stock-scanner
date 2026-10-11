# Company Quality v1 — Retrospective Cohort Evaluation

> Retrospective diagnostic only. This is not OOS evidence and does not
> auto-promote thresholds or production behavior.

- Policy version: company_quality_v1_2026-10-10
- Input dataset: outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv
- Dataset kind: company_quality
- Watchlist source: mixed: pit_snapshots from 2026-09-22 + union_superset_approx before that (membership/etf_count approximated from earliest snapshot or current list; PIT data availability filters candidates; documented upward bias)
- Pre-strategy cross-section: True
- Decision rows: 25025

## Grade counts

| quality_grade | count |
| --- | --- |
| B | 9152 |
| C | 7163 |
| A | 6888 |
| UNRATED | 1822 |

## Overall cohorts

| quality_grade | horizon_days | n_valid_return | n_dates | mean_return | mean_excess_vs_qqq | hit_rate | date_equal_weight_mean_return | date_equal_weight_mean_excess_vs_qqq |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 20 | 6888 | 39 | 0.0121 | -0.0064 | 0.5295 | 0.0113 | -0.0068 |
| A | 60 | 6888 | 39 | 0.0476 | -0.0188 | 0.5602 | 0.0447 | -0.0205 |
| A | 120 | 6888 | 39 | 0.1030 | -0.0261 | 0.5993 | 0.0982 | -0.0294 |
| B | 20 | 9152 | 39 | 0.0104 | -0.0075 | 0.5105 | 0.0106 | -0.0076 |
| B | 60 | 9152 | 39 | 0.0452 | -0.0191 | 0.5431 | 0.0460 | -0.0192 |
| B | 120 | 9152 | 39 | 0.0958 | -0.0305 | 0.5685 | 0.0968 | -0.0307 |
| C | 20 | 7163 | 39 | 0.0379 | 0.0196 | 0.5059 | 0.0374 | 0.0192 |
| C | 60 | 7161 | 39 | 0.1229 | 0.0577 | 0.5417 | 0.1220 | 0.0568 |
| C | 120 | 7158 | 39 | 0.2324 | 0.1056 | 0.5694 | 0.2324 | 0.1049 |
| UNRATED | 20 | 1822 | 39 | 0.0155 | -0.0016 | 0.5110 | 0.0167 | -0.0015 |
| UNRATED | 60 | 1822 | 39 | 0.0707 | 0.0075 | 0.5620 | 0.0741 | 0.0089 |
| UNRATED | 120 | 1822 | 39 | 0.1596 | 0.0324 | 0.5966 | 0.1605 | 0.0330 |

## Concentration

| quality_grade | n_decisions | n_symbols | n_dates | top_symbol | top_symbol_share | top_date | top_date_share |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 6888 | 352 | 39 | CTS | 0.0057 | 2025-12-31 | 0.0322 |
| B | 9152 | 520 | 39 | ADP | 0.0043 | 2024-12-31 | 0.0273 |
| C | 7163 | 393 | 39 | BILL | 0.0054 | 2024-11-29 | 0.0278 |
| UNRATED | 1822 | 94 | 39 | ARQQ | 0.0214 | 2023-02-28 | 0.0307 |

## Cross-sectional rank correlation

| horizon_days | n_dates_return_ic | mean_spearman_return | n_dates_excess_ic | mean_spearman_excess_vs_qqq |
| --- | --- | --- | --- | --- |
| 20.0000 | 39.0000 | 0.0219 | 39.0000 | 0.0219 |
| 60.0000 | 39.0000 | 0.0065 | 39.0000 | 0.0065 |
| 120.0000 | 39.0000 | -0.0004 | 39.0000 | -0.0004 |

## Validation discipline

- Thresholds are defined in docs/company_quality_v1_policy.md before outcome inspection.
- The dataset is drawn before legacy list-specific hard gates.
- Historical watchlist provenance is preserved; union/frozen approximations remain labelled.
- Date-equal-weight cohort fields are reported so symbol rows are not treated as independent evidence.
- Year and regime splits are stored in the cohort CSV even when not expanded in this compact report.
