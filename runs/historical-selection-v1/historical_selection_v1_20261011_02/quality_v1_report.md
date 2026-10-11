# Company Quality v1 — Retrospective Cohort Evaluation

> Retrospective diagnostic only. This is not OOS evidence and does not
> auto-promote thresholds or production behavior.

- Policy version: company_quality_v1_2026-10-10
- Input dataset: outputs/historical_selection_v1_20261011_02/modal_download/datasets/datasets/company_quality_dataset_risk_off.csv
- Dataset kind: company_quality
- Watchlist source: mixed: pit_snapshots from 2026-09-22 + union_superset_approx before that (membership/etf_count approximated from earliest snapshot or current list; PIT data availability filters candidates; documented upward bias)
- Pre-strategy cross-section: True
- Decision rows: 25025

## Grade counts

| quality_grade | count |
| --- | --- |
| B | 9165 |
| C | 7158 |
| A | 6880 |
| UNRATED | 1822 |

## Overall cohorts

| quality_grade | horizon_days | n_valid_return | n_dates | mean_return | mean_excess_vs_qqq | hit_rate | date_equal_weight_mean_return | date_equal_weight_mean_excess_vs_qqq |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 20 | 6880 | 39 | 0.0118 | -0.0067 | 0.5292 | 0.0111 | -0.0071 |
| A | 60 | 6880 | 39 | 0.0462 | -0.0202 | 0.5590 | 0.0436 | -0.0216 |
| A | 120 | 6880 | 39 | 0.0999 | -0.0292 | 0.5972 | 0.0957 | -0.0318 |
| B | 20 | 9165 | 39 | 0.0104 | -0.0076 | 0.5103 | 0.0105 | -0.0077 |
| B | 60 | 9165 | 39 | 0.0450 | -0.0192 | 0.5428 | 0.0458 | -0.0194 |
| B | 120 | 9165 | 39 | 0.0962 | -0.0301 | 0.5680 | 0.0971 | -0.0304 |
| C | 20 | 7158 | 39 | 0.0379 | 0.0196 | 0.5061 | 0.0374 | 0.0192 |
| C | 60 | 7158 | 39 | 0.1276 | 0.0624 | 0.5423 | 0.1266 | 0.0614 |
| C | 120 | 7158 | 39 | 0.2415 | 0.1147 | 0.5697 | 0.2412 | 0.1137 |
| UNRATED | 20 | 1822 | 39 | 0.0155 | -0.0016 | 0.5110 | 0.0167 | -0.0015 |
| UNRATED | 60 | 1822 | 39 | 0.0707 | 0.0075 | 0.5620 | 0.0741 | 0.0089 |
| UNRATED | 120 | 1822 | 39 | 0.1596 | 0.0324 | 0.5966 | 0.1605 | 0.0330 |

## Concentration

| quality_grade | n_decisions | n_symbols | n_dates | top_symbol | top_symbol_share | top_date | top_date_share |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 6880 | 353 | 39 | CTSH | 0.0057 | 2025-12-31 | 0.0321 |
| B | 9165 | 521 | 39 | ADP | 0.0043 | 2024-12-31 | 0.0273 |
| C | 7158 | 393 | 39 | BILL | 0.0054 | 2024-11-29 | 0.0278 |
| UNRATED | 1822 | 94 | 39 | ARQQ | 0.0214 | 2023-02-28 | 0.0307 |

## Cross-sectional rank correlation

| horizon_days | n_dates_return_ic | mean_spearman_return | n_dates_excess_ic | mean_spearman_excess_vs_qqq |
| --- | --- | --- | --- | --- |
| 20.0000 | 39.0000 | 0.0212 | 39.0000 | 0.0212 |
| 60.0000 | 39.0000 | 0.0046 | 39.0000 | 0.0046 |
| 120.0000 | 39.0000 | -0.0032 | 39.0000 | -0.0032 |

## Validation discipline

- Thresholds are defined in docs/company_quality_v1_policy.md before outcome inspection.
- The dataset is drawn before legacy list-specific hard gates.
- Historical watchlist provenance is preserved; union/frozen approximations remain labelled.
- Date-equal-weight cohort fields are reported so symbol rows are not treated as independent evidence.
- Year and regime splits are stored in the cohort CSV even when not expanded in this compact report.
