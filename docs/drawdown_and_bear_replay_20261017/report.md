# Drawdown Protection & Bear-Market Replay Evaluation

Route A: forward-drawdown attribution on the frozen 39-date dataset (production `build_stock_decisions` v1/v2 rebuild per date, FULL vs ETF_SLICE scope). Route B: 2022 bear-market replay when provided.

## Provenance

- Base dataset: `company_quality_dataset_risk_off.v3.csv` (25025 rows, 39 signal dates).
- 2022 bear market dataset: `company_quality_dataset_risk_off.repaired.csv` (8251 rows, 12 signal dates).
- Runner: `scripts/run_extended_replay_evaluation.py` SHA256 `62e38f206e43e31b06636510cc0647ed8d2f6f3f186ecac78b3739720d843c90`.
- Reproduction command: `python scripts/run_extended_replay_evaluation.py --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv --bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv --base-reference-dir outputs/m4_revalidation_current_20261016 --output-dir docs/drawdown_and_bear_replay_20261017`.
- Base dataset SHA256: `2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e`.
- 2022 bear dataset `company_quality_dataset_risk_off.repaired.csv` (8251 rows, 12 signal dates) SHA256 `43e5cd4a440c92857c11106016db0b827202c279e2acfbdc7cb0281ff2f007d6`.
- 2022 Modal extraction: run_id `historical_selection_bear2022_20261017_01`, code_sha `5b0b0657e21adcd5ec0f7d6426b4831906e4323a`, generated_utc `2026-10-17T07:17:06.196933+00:00`, raw_csv_sha256 `3fbd9db3b7a1525223e22f34bac10494ecf2ca83e619f4255007490239eda13e`, splits_json_sha256 `2d7949cca42dddc8fb20910b0b9d3cfc30a6fcec4f8770e44a936254152eb9cf`.
- 2022 split-repair audit: discontinuities rows 13, flagged 1; artifacts `bear_2022_provenance.json` + `bear_2022_discontinuities.csv`.
- Securities addressed by CIK/ticker rename hygiene at refresh time; universe snapshots are the documented `union_superset_approx` approximation (AGENTS.md §4): the current watchlist applied to all historical dates, not true PIT ETF-constituent history; the ETF-slice (etf_count>=1) cut is the bias-reduced read.
- Retrospective replay only; no threshold/weight/policy promotion implied (AGENTS.md §8).

## 1. E0 baseline reproduction check

Status: **PASS** (15 cohort rows checked vs `e0_current_cohorts.csv` v1_current, tolerance 1e-05).

## 2. Trailing regime vs forward-drawdown protection

`regime == "down"` is a trailing indicator (benchmark trailing 60d return on the signal date). In the 2023-2026 bull market most trailing dips were followed by V-shaped rebounds; the forward lens `qqq_return_60 < 0` isolates dates whose NEXT 60 trading days were actual market drawdowns.

- FWD_DRAWDOWN_60D: 8 dates, next-60d QQQ range -10.3%..-0.9%.
- TRAILING_DOWN: 10 dates, next-60d QQQ range +1.6%..+21.6% (post-dip rebound measure).

## 2b. Forward-Drawdown & 2022 Bear Signal-Date Manifest (with 60d Window Overlap)

| signal_date | segment_tag | episode_cluster | trailing_regime | qqq_ret20 | qqq_ret60 | qqq_label_end_60 | qqq_ret120 | overlaps_prev_60d_window |
|---|---|---|---|---|---|---|---|---|
| 2023-06-30 | FWD_DRAWDOWN_60D | EP1_2023Q3 | up | +3.4% | -4.6% | 2023-09-26 | +8.6% | no |
| 2023-07-31 | FWD_DRAWDOWN_60D | EP1_2023Q3 | up | -4.4% | -6.4% | 2023-10-24 | +10.0% | yes |
| 2024-11-29 | FWD_DRAWDOWN_60D | EP2_2024Q4_2025Q1 | up | +0.6% | -0.9% | 2025-02-28 | +1.7% | no |
| 2024-12-31 | FWD_DRAWDOWN_60D | EP2_2024Q4_2025Q1 | up | +1.3% | -9.1% | 2025-03-31 | +5.9% | yes |
| 2025-01-31 | FWD_DRAWDOWN_60D | EP2_2024Q4_2025Q1 | up | -3.4% | -7.7% | 2025-04-29 | +10.1% | yes |
| 2025-10-31 | FWD_DRAWDOWN_60D | EP3_2025Q4 | up | -3.1% | -1.2% | 2026-01-29 | +4.3% | no |
| 2025-11-28 | FWD_DRAWDOWN_60D | EP3_2025Q4 | up | +0.9% | -1.0% | 2026-02-26 | +16.6% | yes |
| 2025-12-31 | FWD_DRAWDOWN_60D | EP3_2025Q4 | up | -0.0% | -10.3% | 2026-03-30 | +15.2% | yes |
| 2022-01-31 | BEAR_2022 | EP0_BEAR_2022 | down | -6.6% | -13.4% | 2022-04-27 | -17.9% | no |
| 2022-02-28 | BEAR_2022 | EP0_BEAR_2022 | down | +5.3% | -17.2% | 2022-05-24 | -6.9% | yes |
| 2022-03-31 | BEAR_2022 | EP0_BEAR_2022 | down | -13.9% | -22.2% | 2022-06-28 | -23.1% | yes |
| 2022-04-29 | BEAR_2022 | EP0_BEAR_2022 | down | -1.5% | -2.3% | 2022-07-27 | -14.3% | yes |
| 2022-05-31 | BEAR_2022 | - | down | -8.9% | +2.9% | 2022-08-25 | -8.6% | yes |
| 2022-06-30 | BEAR_2022 | EP0_BEAR_2022 | down | +12.7% | -2.1% | 2022-09-26 | -3.7% | yes |
| 2022-07-29 | BEAR_2022 | EP0_BEAR_2022 | down | -2.3% | -11.5% | 2022-10-24 | -10.1% | yes |
| 2022-08-31 | BEAR_2022 | EP0_BEAR_2022 | down | -8.6% | -3.6% | 2022-11-25 | -0.2% | yes |
| 2022-09-30 | BEAR_2022 | EP0_BEAR_2022 | down | +4.2% | -2.4% | 2022-12-27 | +15.3% | yes |
| 2022-10-31 | BEAR_2022 | - | down | -0.7% | +4.8% | 2023-01-27 | +9.7% | yes |
| 2022-11-30 | BEAR_2022 | EP0_BEAR_2022 | up | -9.6% | -0.3% | 2023-02-28 | +12.6% | yes |
| 2022-12-30 | BEAR_2022 | - | down | +9.4% | +16.1% | 2023-03-29 | +32.9% | yes |

`overlaps_prev_60d_window` = `signal_date < previous listed date's qqq_label_end_60`: monthly signal dates inside one drawdown episode share overlapping 60-trading-day (~3-month) forward windows and are therefore NOT independent samples (AGENTS.md §8); the episode-cluster equal-weight table below gives each contiguous drawdown episode one vote.

Episode-cluster equal-weight summary - mean 60d net-QQQ excess:

| scope | cohort | variant | EP1_2023Q3 | EP2_2024Q4_2025Q1 | EP3_2025Q4 | EP0_BEAR_2022 | FWD_EQ(3) | ALL_EQ(4) | DATE_EQUAL |
|---|---|---|---|---|---|---|---|---|---|
| FULL | TOP15 | v1_current | +0.2% | -7.4% | +4.5% | +3.3% | -0.9% | +0.2% | -1.0% |
| FULL | PRIORITY_REVIEW | v1_current | +2.3% | -6.1% | +7.0% | +8.0% | +1.1% | +2.8% | +0.9% |
| FULL | QUALITY_A | v1_current | -2.8% | -2.6% | +4.8% | +3.9% | -0.2% | +0.8% | +0.1% |
| FULL | UNIVERSE | v1_current | -5.4% | -2.2% | +5.4% | +1.9% | -0.7% | -0.1% | -0.1% |
| FULL | TOP15 | v2_current | +0.6% | -7.0% | +3.3% | +4.1% | -1.0% | +0.2% | -1.2% |
| FULL | PRIORITY_REVIEW | v2_current | +1.4% | -3.0% | +8.0% | +4.7% | +2.1% | +2.8% | +2.2% |
| FULL | QUALITY_A | v2_current | -2.9% | -2.2% | +5.1% | +3.4% | +0.0% | +0.9% | +0.4% |
| FULL | UNIVERSE | v2_current | -5.4% | -2.2% | +5.4% | +1.9% | -0.7% | -0.1% | -0.1% |
| ETF_SLICE | TOP15 | v1_current | +0.8% | -6.8% | +7.3% | +4.8% | +0.4% | +1.5% | +0.4% |
| ETF_SLICE | PRIORITY_REVIEW | v1_current | +4.7% | -6.6% | +9.2% | +8.0% | +2.5% | +3.9% | +2.2% |
| ETF_SLICE | QUALITY_A | v1_current | -1.0% | -1.9% | +7.1% | +4.2% | +1.4% | +2.1% | +1.7% |
| ETF_SLICE | UNIVERSE | v1_current | -2.8% | -0.4% | +7.6% | +3.0% | +1.5% | +1.9% | +2.0% |
| ETF_SLICE | TOP15 | v2_current | +1.7% | -5.6% | +8.5% | +5.4% | +1.5% | +2.5% | +1.5% |
| ETF_SLICE | PRIORITY_REVIEW | v2_current | +2.6% | -3.3% | +10.1% | +6.0% | +3.2% | +3.9% | +3.2% |
| ETF_SLICE | QUALITY_A | v2_current | -0.9% | -1.6% | +7.8% | +3.8% | +1.8% | +2.3% | +2.1% |
| ETF_SLICE | UNIVERSE | v2_current | -2.8% | -0.4% | +7.6% | +3.0% | +1.5% | +1.9% | +2.0% |

Episode-cluster equal-weight summary - severe loss rate (fwd_ret_60 <= -20%):

| scope | cohort | variant | EP1_2023Q3 | EP2_2024Q4_2025Q1 | EP3_2025Q4 | EP0_BEAR_2022 | FWD_EQ(3) | ALL_EQ(4) | DATE_EQUAL |
|---|---|---|---|---|---|---|---|---|---|
| FULL | TOP15 | v1_current | +3.3% | +31.1% | +13.3% | +14.8% | +15.9% | +15.6% | +17.5% |
| FULL | PRIORITY_REVIEW | v1_current | +6.2% | +25.8% | +10.6% | +6.0% | +14.2% | +12.2% | +15.2% |
| FULL | QUALITY_A | v1_current | +14.5% | +20.4% | +20.0% | +13.8% | +18.3% | +17.2% | +18.8% |
| FULL | UNIVERSE | v1_current | +24.1% | +24.7% | +23.9% | +23.2% | +24.2% | +24.0% | +24.3% |
| FULL | TOP15 | v2_current | +6.7% | +26.7% | +17.8% | +9.6% | +17.0% | +15.2% | +18.3% |
| FULL | PRIORITY_REVIEW | v2_current | +8.3% | +18.5% | +11.3% | +10.2% | +12.7% | +12.1% | +13.3% |
| FULL | QUALITY_A | v2_current | +14.2% | +19.3% | +20.1% | +15.4% | +17.9% | +17.3% | +18.3% |
| FULL | UNIVERSE | v2_current | +24.1% | +24.7% | +23.9% | +23.2% | +24.2% | +24.0% | +24.3% |
| ETF_SLICE | TOP15 | v1_current | +10.0% | +26.7% | +8.9% | +11.1% | +15.2% | +14.2% | +15.8% |
| ETF_SLICE | PRIORITY_REVIEW | v1_current | +4.5% | +24.2% | +6.6% | +6.1% | +11.8% | +10.4% | +12.7% |
| ETF_SLICE | QUALITY_A | v1_current | +8.7% | +18.0% | +15.6% | +12.3% | +14.1% | +13.6% | +14.7% |
| ETF_SLICE | UNIVERSE | v1_current | +16.5% | +18.7% | +17.9% | +18.0% | +17.7% | +17.8% | +17.8% |
| ETF_SLICE | TOP15 | v2_current | +10.0% | +24.4% | +11.1% | +6.7% | +15.2% | +13.1% | +15.8% |
| ETF_SLICE | PRIORITY_REVIEW | v2_current | +9.4% | +17.9% | +7.6% | +5.8% | +11.6% | +10.1% | +11.9% |
| ETF_SLICE | QUALITY_A | v2_current | +7.7% | +16.7% | +14.8% | +13.2% | +13.1% | +13.1% | +13.7% |
| ETF_SLICE | UNIVERSE | v2_current | +16.5% | +18.7% | +17.9% | +18.0% | +17.7% | +17.8% | +17.8% |

## 3. Rank tiers: FWD_BULL_60D vs FWD_DRAWDOWN_60D (v2_current)

| scope | segment | tier | n | mean_ex60 | diff_vs_univ | win_rate | raw_ret60 | severe_loss60 |
|---|---|---|---|---|---|---|---|---|
| FULL | FWD_BULL_60D | 1-5 | 31 | -0.027565 | -0.033417 | 0.225806 | 0.067720 | 0.025806 |
| FULL | FWD_BULL_60D | 6-15 | 31 | -0.034400 | -0.040252 | 0.258065 | 0.060885 | 0.035484 |
| FULL | FWD_BULL_60D | 16-30 | 31 | -0.052759 | -0.058611 | 0.193548 | 0.042526 | 0.049462 |
| FULL | FWD_BULL_60D | 31-50 | 31 | -0.007625 | -0.013478 | 0.483871 | 0.087659 | 0.027419 |
| FULL | FWD_BULL_60D | 51-100 | 31 | -0.005939 | -0.011791 | 0.548387 | 0.089346 | 0.046452 |
| FULL | FWD_BULL_60D | 101+ | 31 | 0.010098 | 0.004246 | 0.580645 | 0.105383 | 0.088360 |
| FULL | FWD_BULL_60D | universe | 31 | 0.005852 | 0.000000 | 0.612903 | 0.101137 | 0.080912 |
| FULL | FWD_DRAWDOWN_60D | 1-5 | 8 | 0.002005 | 0.003455 | 0.500000 | -0.049393 | 0.200000 |
| FULL | FWD_DRAWDOWN_60D | 6-15 | 8 | -0.019687 | -0.018238 | 0.250000 | -0.071085 | 0.175000 |
| FULL | FWD_DRAWDOWN_60D | 16-30 | 8 | 0.015707 | 0.017157 | 0.625000 | -0.035691 | 0.141667 |
| FULL | FWD_DRAWDOWN_60D | 31-50 | 8 | 0.030838 | 0.032288 | 0.375000 | -0.020560 | 0.162500 |
| FULL | FWD_DRAWDOWN_60D | 51-100 | 8 | 0.041676 | 0.043125 | 0.500000 | -0.009722 | 0.162500 |
| FULL | FWD_DRAWDOWN_60D | 101+ | 8 | -0.006692 | -0.005243 | 0.375000 | -0.058090 | 0.257463 |
| FULL | FWD_DRAWDOWN_60D | universe | 8 | -0.001449 | 0.000000 | 0.375000 | -0.052848 | 0.242702 |
| ETF_SLICE | FWD_BULL_60D | 1-5 | 31 | -0.028208 | -0.023617 | 0.290323 | 0.067077 | 0.025806 |
| ETF_SLICE | FWD_BULL_60D | 6-15 | 31 | -0.034678 | -0.030087 | 0.354839 | 0.060607 | 0.022581 |
| ETF_SLICE | FWD_BULL_60D | 16-30 | 31 | -0.032409 | -0.027818 | 0.354839 | 0.062876 | 0.034409 |
| ETF_SLICE | FWD_BULL_60D | 31-50 | 31 | -0.006377 | -0.001786 | 0.387097 | 0.088908 | 0.029032 |
| ETF_SLICE | FWD_BULL_60D | 51-100 | 31 | -0.007020 | -0.002429 | 0.419355 | 0.088265 | 0.031613 |
| ETF_SLICE | FWD_BULL_60D | 101+ | 31 | -0.001364 | 0.003227 | 0.483871 | 0.093921 | 0.061259 |
| ETF_SLICE | FWD_BULL_60D | universe | 31 | -0.004591 | 0.000000 | 0.516129 | 0.090694 | 0.053616 |
| ETF_SLICE | FWD_DRAWDOWN_60D | 1-5 | 8 | 0.012758 | -0.007276 | 0.500000 | -0.038640 | 0.175000 |
| ETF_SLICE | FWD_DRAWDOWN_60D | 6-15 | 8 | 0.015918 | -0.004116 | 0.625000 | -0.035480 | 0.150000 |
| ETF_SLICE | FWD_DRAWDOWN_60D | 16-30 | 8 | 0.027649 | 0.007615 | 0.625000 | -0.023749 | 0.075000 |
| ETF_SLICE | FWD_DRAWDOWN_60D | 31-50 | 8 | 0.070900 | 0.050865 | 0.625000 | 0.019502 | 0.125000 |
| ETF_SLICE | FWD_DRAWDOWN_60D | 51-100 | 8 | 0.024967 | 0.004933 | 0.625000 | -0.026431 | 0.142500 |
| ETF_SLICE | FWD_DRAWDOWN_60D | 101+ | 8 | 0.015861 | -0.004174 | 0.500000 | -0.035538 | 0.193534 |
| ETF_SLICE | FWD_DRAWDOWN_60D | universe | 8 | 0.020035 | 0.000000 | 0.500000 | -0.031364 | 0.178234 |

## 4. Cohorts & severe-loss rates (v2_current)

| scope | segment | cohort | n | mean_ex60 | median_ex60 | severe_loss60 | severe_under60 |
|---|---|---|---|---|---|---|---|
| FULL | FWD_BULL_60D | TOP15 | 31 | -0.032122 | -0.031605 | 0.032258 | 0.133333 |
| FULL | FWD_BULL_60D | PRIORITY_REVIEW | 31 | -0.041534 | -0.034248 | 0.033962 | 0.143790 |
| FULL | FWD_DRAWDOWN_60D | TOP15 | 8 | -0.012456 | -0.010033 | 0.183333 | 0.083333 |
| FULL | FWD_DRAWDOWN_60D | PRIORITY_REVIEW | 8 | 0.022322 | 0.013245 | 0.132712 | 0.064565 |
| FULL | TRAILING_DOWN | TOP15 | 10 | -0.063720 | -0.041623 | 0.060000 | 0.226667 |
| FULL | TRAILING_DOWN | PRIORITY_REVIEW | 10 | -0.076047 | -0.073482 | 0.044640 | 0.231014 |
| FULL | BASE_ALL_39 | TOP15 | 39 | -0.028088 | -0.031562 | 0.063248 | 0.123077 |
| FULL | BASE_ALL_39 | PRIORITY_REVIEW | 39 | -0.028435 | -0.023587 | 0.054219 | 0.127538 |
| ETF_SLICE | FWD_BULL_60D | TOP15 | 31 | -0.032521 | -0.031961 | 0.023656 | 0.122581 |
| ETF_SLICE | FWD_BULL_60D | PRIORITY_REVIEW | 31 | -0.041655 | -0.036728 | 0.026445 | 0.133204 |
| ETF_SLICE | FWD_DRAWDOWN_60D | TOP15 | 8 | 0.014865 | 0.008326 | 0.158333 | 0.058333 |
| ETF_SLICE | FWD_DRAWDOWN_60D | PRIORITY_REVIEW | 8 | 0.032298 | 0.022348 | 0.118842 | 0.053462 |
| ETF_SLICE | TRAILING_DOWN | TOP15 | 10 | -0.069524 | -0.057214 | 0.046667 | 0.220000 |
| ETF_SLICE | TRAILING_DOWN | PRIORITY_REVIEW | 10 | -0.080895 | -0.081695 | 0.034012 | 0.223706 |
| ETF_SLICE | BASE_ALL_39 | TOP15 | 39 | -0.022801 | -0.027022 | 0.051282 | 0.109402 |
| ETF_SLICE | BASE_ALL_39 | PRIORITY_REVIEW | 39 | -0.026485 | -0.020585 | 0.045398 | 0.116846 |

## 5. Entry state / SMA200 extension / grade crosscuts (v2_current, FWD_DRAWDOWN_60D)

| scope | cut | bucket | n | mean_ex60 | severe_loss60 |
|---|---|---|---|---|---|
| FULL | entry_state | ENTRY_READY|all_grades | 8 | 0.019559 | 0.176820 |
| FULL | entry_state | WATCH_PULLBACK|all_grades | 8 | 0.012163 | 0.303167 |
| FULL | entry_state | WATCH_BREAKOUT|all_grades | 8 | 0.022096 | 0.178569 |
| FULL | entry_state | TREND_DAMAGED|all_grades | 8 | -0.028213 | 0.276874 |
| FULL | entry_state | INSUFFICIENT_DATA|all_grades | 8 | -0.035249 | 0.339115 |
| FULL | entry_state | ENTRY_READY|grade_A_only | 8 | 0.022058 | 0.135434 |
| FULL | entry_state | WATCH_PULLBACK|grade_A_only | 8 | 0.026900 | 0.228987 |
| FULL | entry_state | WATCH_BREAKOUT|grade_A_only | 8 | 0.018270 | 0.133976 |
| FULL | entry_state | TREND_DAMAGED|grade_A_only | 8 | -0.011992 | 0.202153 |
| FULL | entry_state | INSUFFICIENT_DATA|grade_A_only | 5 | -0.009077 | 0.155263 |
| FULL | sma200_extension | <1.00x|all_grades | 8 | -0.029507 | 0.273309 |
| FULL | sma200_extension | 1.00-1.25x|all_grades | 8 | 0.019990 | 0.172781 |
| FULL | sma200_extension | 1.25-1.35x|all_grades | 8 | 0.004665 | 0.261006 |
| FULL | sma200_extension | 1.35-1.45x|all_grades | 8 | -0.023120 | 0.333514 |
| FULL | sma200_extension | >1.45x|all_grades | 8 | 0.046743 | 0.348830 |
| FULL | sma200_extension | <1.00x|grade_A_only | 8 | -0.015012 | 0.208753 |
| FULL | sma200_extension | 1.00-1.25x|grade_A_only | 8 | 0.014332 | 0.138113 |
| FULL | sma200_extension | 1.25-1.35x|grade_A_only | 8 | 0.013661 | 0.189635 |
| FULL | sma200_extension | 1.35-1.45x|grade_A_only | 8 | 0.029573 | 0.216444 |
| FULL | sma200_extension | >1.45x|grade_A_only | 8 | 0.093036 | 0.147569 |
| FULL | quality_grade | A | 8 | 0.003658 | 0.183325 |
| FULL | quality_grade | B | 8 | 0.006305 | 0.195950 |
| FULL | quality_grade | C | 8 | -0.022730 | 0.371209 |
| FULL | quality_grade | UNRATED | 8 | 0.025575 | 0.216190 |
| ETF_SLICE | entry_state | ENTRY_READY|all_grades | 8 | 0.026963 | 0.158126 |
| ETF_SLICE | entry_state | WATCH_PULLBACK|all_grades | 8 | 0.022405 | 0.270177 |
| ETF_SLICE | entry_state | WATCH_BREAKOUT|all_grades | 8 | 0.033393 | 0.139372 |
| ETF_SLICE | entry_state | TREND_DAMAGED|all_grades | 8 | -0.000548 | 0.181740 |
| ETF_SLICE | entry_state | INSUFFICIENT_DATA|all_grades | 8 | -0.016249 | 0.300787 |
| ETF_SLICE | entry_state | ENTRY_READY|grade_A_only | 8 | 0.033340 | 0.117948 |
| ETF_SLICE | entry_state | WATCH_PULLBACK|grade_A_only | 8 | 0.039603 | 0.199814 |
| ETF_SLICE | entry_state | WATCH_BREAKOUT|grade_A_only | 8 | 0.020611 | 0.125755 |
| ETF_SLICE | entry_state | TREND_DAMAGED|grade_A_only | 8 | 0.020904 | 0.124674 |
| ETF_SLICE | entry_state | INSUFFICIENT_DATA|grade_A_only | 5 | 0.031399 | 0.044123 |
| ETF_SLICE | sma200_extension | <1.00x|all_grades | 8 | 0.000283 | 0.181662 |
| ETF_SLICE | sma200_extension | 1.00-1.25x|all_grades | 8 | 0.028704 | 0.137315 |
| ETF_SLICE | sma200_extension | 1.25-1.35x|all_grades | 8 | 0.030915 | 0.226484 |
| ETF_SLICE | sma200_extension | 1.35-1.45x|all_grades | 8 | -0.015216 | 0.319563 |
| ETF_SLICE | sma200_extension | >1.45x|all_grades | 8 | 0.058914 | 0.313389 |
| ETF_SLICE | sma200_extension | <1.00x|grade_A_only | 8 | 0.014619 | 0.141056 |
| ETF_SLICE | sma200_extension | 1.00-1.25x|grade_A_only | 8 | 0.021348 | 0.119662 |
| ETF_SLICE | sma200_extension | 1.25-1.35x|grade_A_only | 8 | 0.042433 | 0.134761 |
| ETF_SLICE | sma200_extension | 1.35-1.45x|grade_A_only | 7 | 0.038972 | 0.130556 |
| ETF_SLICE | sma200_extension | >1.45x|grade_A_only | 8 | 0.062984 | 0.250521 |
| ETF_SLICE | quality_grade | A | 8 | 0.021158 | 0.137460 |
| ETF_SLICE | quality_grade | B | 8 | 0.024836 | 0.141995 |
| ETF_SLICE | quality_grade | C | 8 | -0.011292 | 0.318657 |
| ETF_SLICE | quality_grade | UNRATED | 8 | 0.077930 | 0.141774 |

## 6. 2022 tech bear market (BEAR_2022)

| scope | tier | n | mean_ex60 | diff_vs_univ | severe_loss60 |
|---|---|---|---|---|---|
| FULL | 1-5 | 12 | 0.022800 | 0.011659 | 0.116667 |
| FULL | 6-15 | 12 | 0.012970 | 0.001829 | 0.066667 |
| FULL | 16-30 | 12 | 0.023558 | 0.012417 | 0.122222 |
| FULL | 31-50 | 12 | 0.015096 | 0.003955 | 0.112500 |
| FULL | 51-100 | 12 | 0.031953 | 0.020811 | 0.095000 |
| FULL | 101+ | 12 | 0.008773 | -0.002369 | 0.209175 |
| FULL | universe | 12 | 0.011141 | 0.000000 | 0.193395 |
| ETF_SLICE | 1-5 | 12 | 0.003173 | -0.013556 | 0.116667 |
| ETF_SLICE | 6-15 | 12 | 0.029740 | 0.013011 | 0.041667 |
| ETF_SLICE | 16-30 | 12 | 0.028485 | 0.011755 | 0.077778 |
| ETF_SLICE | 31-50 | 12 | 0.027881 | 0.011151 | 0.075000 |
| ETF_SLICE | 51-100 | 12 | 0.028992 | 0.012262 | 0.086667 |
| ETF_SLICE | 101+ | 12 | 0.013298 | -0.003431 | 0.169468 |
| ETF_SLICE | universe | 12 | 0.016730 | 0.000000 | 0.147880 |

## 7. Interpretive guardrails

- Overlapping 60d/120d windows are not independent samples; aggregation is date-equal and the sample is small (39 base dates, 8 forward-drawdown dates).
- `severe_loss_rate_60` = share of cohort members with `fwd_ret_60 <= -20%` (date-equal mean); tail metrics need many more drawdown dates before any promotion-grade conclusion.
- Forward labels beyond the dataset's frozen horizon are matured retrospectively; never call them OOS.
