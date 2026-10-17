# Growth-Compounder Offense & Slow-Growth De-Crowding Validation (C1 / C2 / C3)

Offline, deterministic validation of three pre-registered candidates against the production v2 baseline across four mandatory gates (G1-G4). Retrospective replay only (AGENTS.md §4/§8).

## Provenance

- Runner: `scripts/validate_growth_compounder_offense.py` SHA256 `64735b48bb98797f2a70b87a45f77db39188bbe9734fbf8d7a913e7fee4b5028`.
- Reproduction command: `python scripts/validate_growth_compounder_offense.py --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv --bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv --snapshot-jsonl outputs/decision_previews/2026-10-15/risk_off/decisions_recomputed_v2.jsonl --output-dir docs/growth_compounder_offense_validation_20261017`.
- Base dataset: `company_quality_dataset_risk_off.v3.csv` (25025 rows, 39 signal dates) SHA256 `2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e`.
- 2022 bear dataset: `company_quality_dataset_risk_off.repaired.csv` (8251 rows, 12 signal dates) SHA256 `43e5cd4a440c92857c11106016db0b827202c279e2acfbdc7cb0281ff2f007d6`.
- Live snapshot: `decisions_recomputed_v2.jsonl` (538 decisions) SHA256 `a33ea635d056c7ee1348342643586f9dd153a53a15b287da9dd0193238d26dcb`.
- Segments, scope filters (ETF_SLICE `watchlist_etf_count >= 1`; FULL secondary) and dataset loading reuse `scripts/run_extended_replay_evaluation.py`; no production threshold/weight/policy changes (candidate rankings exist only in this validator).

## Gate 1 - Paired economics vs v2_baseline (TOP15, 60d, ETF_SLICE)

| candidate | DEV_2023_2024 | POST_2025_2026Q1 | BASE_ALL_39 |
|---|---|---|---|
| C1 slow-growth de-crowding | 0.002179 [-0.012687,0.019935] LOO -0.005250 pos 0.291667 | -0.003809 [-0.016337,0.008381] LOO -0.005970 pos 0.466667 | -0.000124 [-0.010404,0.013714] LOO -0.004681 pos 0.358974 |
| C2 offense compounder track | 0.014960 [-0.013994,0.048139] LOO 0.005080 pos 0.416667 | 0.050484 [0.014024,0.087505] LOO 0.038336 pos 0.733333 | 0.028623 [0.005730,0.052132] LOO 0.023002 pos 0.538462 |
| C3 barbell 8+7 | 0.013778 [-0.006714,0.039092] LOO 0.006901 pos 0.375000 | 0.035945 [0.000622,0.072713] LOO 0.023230 pos 0.733333 | 0.022304 [0.003217,0.041880] LOO 0.017260 pos 0.512821 |

Candidate TOP15 date-equal mean 60d net-QQQ excess (ETF_SLICE):

| segment | v2 baseline (production ranking) | C1 slow-growth de-crowding | C2 offense compounder track | C3 barbell 8+7 |
|---|---|---|---|---|
| DEV_2023_2024 | -0.017963 | -0.015784 | -0.003003 | -0.004185 |
| POST_2025_2026Q1 | -0.030541 | -0.034350 | 0.019942 | 0.005404 |
| BASE_ALL_39 | -0.022801 | -0.022925 | 0.005822 | -0.000497 |

## Gate 2 - Bull offense vs drawdown / 2022 bear defense (TOP15, 60d, ETF_SLICE)

| segment | candidate | mean_excess_60 | severe_loss_rate_60 |
|---|---|---|---|
| FWD_BULL_60D | v2 baseline (production ranking) | -0.032521 | 0.023656 |
| FWD_BULL_60D | C1 slow-growth de-crowding | -0.033787 | 0.034409 |
| FWD_BULL_60D | C2 offense compounder track | 0.010224 | 0.034409 |
| FWD_BULL_60D | C3 barbell 8+7 | 0.002845 | 0.030108 |
| FWD_DRAWDOWN_60D | v2 baseline (production ranking) | 0.014865 | 0.158333 |
| FWD_DRAWDOWN_60D | C1 slow-growth de-crowding | 0.019165 | 0.158333 |
| FWD_DRAWDOWN_60D | C2 offense compounder track | -0.011237 | 0.225000 |
| FWD_DRAWDOWN_60D | C3 barbell 8+7 | -0.013449 | 0.216667 |
| BEAR_2022 | v2 baseline (production ranking) | 0.020885 | 0.066667 |
| BEAR_2022 | C1 slow-growth de-crowding | 0.021444 | 0.061111 |
| BEAR_2022 | C2 offense compounder track | 0.013628 | 0.105556 |
| BEAR_2022 | C3 barbell 8+7 | 0.016278 | 0.088889 |
| BEAR_2022_FWD_DRAWDOWN_60D | v2 baseline (production ranking) | 0.054495 | 0.066667 |
| BEAR_2022_FWD_DRAWDOWN_60D | C1 slow-growth de-crowding | 0.055551 | 0.059259 |
| BEAR_2022_FWD_DRAWDOWN_60D | C2 offense compounder track | 0.050742 | 0.111111 |
| BEAR_2022_FWD_DRAWDOWN_60D | C3 barbell 8+7 | 0.054157 | 0.088889 |
| ALL_EQ(4) | v2 baseline (production ranking) | 0.024914 | 0.130556 |
| ALL_EQ(4) | C1 slow-growth de-crowding | 0.027785 | 0.128704 |
| ALL_EQ(4) | C2 offense compounder track | 0.002282 | 0.191667 |
| ALL_EQ(4) | C3 barbell 8+7 | 0.003142 | 0.177778 |

## Gate 3 - Anti-lottery (EX_TOP5_CONTRIBUTORS) & slow-growth crowding

| candidate (BASE_ALL_39, after own top-5 exclusion) | TOP15 mean_excess_60 | excluded |
|---|---|---|
| v2 baseline (production ranking) | -0.032359 (base same-excl -0.032359, delta 0.000000) | IESC;KEYS;ON;NEM;P |
| C1 slow-growth de-crowding | -0.032933 (base same-excl -0.027496, delta -0.005437) | SMCI;IESC;NEM;HWM;FIX |
| C2 offense compounder track | -0.017233 (base same-excl -0.024061, delta 0.006828) | FIX;PLTR;APP;IESC;SMCI |
| C3 barbell 8+7 | -0.019563 (base same-excl -0.024061, delta 0.004498) | FIX;APP;IESC;SMCI;PLTR |

| candidate (TOP15, 51 dates, ETF_SLICE) | low-growth share | high-growth share | median rev_yoy |
|---|---|---|---|
| v2 baseline (production ranking) | 0.426144 (rev<10%) | 0.372549 (rev>=15%) | 0.111205 (median rev YoY) |
| C1 slow-growth de-crowding | 0.290196 (rev<10%) | 0.484967 (rev>=15%) | 0.146548 (median rev YoY) |
| C2 offense compounder track | 0.121569 (rev<10%) | 0.798693 (rev>=15%) | 0.224566 (median rev YoY) |
| C3 barbell 8+7 | 0.160784 (rev<10%) | 0.707190 (rev>=15%) | 0.215274 (median rev YoY) |

## Gate 4 - 2026-10-15 live snapshot Top-15 comparison

Side-by-side Top-15 (rank, symbol, grade, entry state, revenue YoY, OCF/NI, SMA200 x, RS60) is in `snap_20261015_top15_comparison.csv` (long format, `in_v2_baseline_top15` marks baseline overlap).

- v2 baseline (production ranking): 1.ADI, 2.KEYS, 3.CRM, 4.WDAY, 5.APH, 6.EXPE, 7.JKHY, 8.VLTO, 9.FAST, 10.AMCR, 11.SAIC, 12.BILL, 13.FTNT, 14.SSNC, 15.DBX
- C1 slow-growth de-crowding: 1.ADI, 2.KEYS, 3.APH, 4.AMCR, 5.CRM, 6.FTNT, 7.WDAY, 8.BILL, 9.EXPE, 10.NTAP, 11.AMD, 12.EOG, 13.MSFT, 14.IOT, 15.FAST
- C2 offense compounder track: 1.PLTR, 2.VEEV, 3.APH, 4.GWRE, 5.ZETA, 6.ADI, 7.SNPS, 8.DT, 9.NOW, 10.MSFT, 11.KEYS, 12.META, 13.FTNT, 14.WK, 15.NTAP
- C3 barbell 8+7: 1.ADI, 2.KEYS, 3.APH, 4.AMCR, 5.CRM, 6.FTNT, 7.WDAY, 8.BILL, 9.PLTR, 10.VEEV, 11.GWRE, 12.ZETA, 13.SNPS, 14.DT, 15.NOW

## Verdict inputs (pre-registered gates)

| candidate | G1 delta>0 | G1 LOO>0 | G2 bull>0 | G2 drawdown>=0 | G2 bear>=0 | G2 ALL_EQ>=0 | G2 severe<universe | G3 ex-top5>=0 |
|---|---|---|---|---|---|---|---|---|
| C1 slow-growth de-crowding | no | no | no | yes | yes | yes | yes | no |
| C2 offense compounder track | yes | yes | yes | no | yes | yes | no | yes |
| C3 barbell 8+7 | yes | yes | yes | no | yes | yes | no | yes |

## Explicit recommendation

No candidate clears all pre-registered gate inputs on the current evidence. Per the frozen decision rule, do not adopt C1/C2/C3 into production policy; keep v2 production unchanged and revisit only with prospective immutable snapshots.

Guardrails: overlapping 60d windows (monthly dates) are handled by episode-cluster equal weighting (ALL_EQ(4)); universe snapshots are the documented `union_superset_approx` approximation; all metrics are date-equal.
