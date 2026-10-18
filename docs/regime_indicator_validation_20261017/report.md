# E4a — Trailing Regime-Indicator Separation Audit (Diagnostic Only)

- Pre-registered spec: `docs/agent_specs/regime_indicator_validation_spec.md` (v2, architect-revised).
- Runner: `scripts/audit_regime_separation.py` SHA256 `670220f5695a0e85293f341dac0f53ac34c6bebb28161a4d25f26a103fefa5c3`.
- Fully offline and deterministic; frozen datasets read-only; zero network calls; no production code or config changes.
- **This audit proposes no policy change.** Its only output is a go/no-go for a *future* pre-registered E4b experiment ticket (AGENTS.md §8: retrospective results cannot auto-promote).

## 0. E4b go/no-go verdict (up front)

**NO-GO / STOP** — on this frozen evidence there is no pre-registered separation to condition a future E4b policy on. **No E4b ticket will be opened and no policy change follows.** The pre-registered spec treats this outcome as a full result, not a failure to hide.

| gate | requirement | result | detail |
|---|---|---|---|
| S0 | bear-2022 safety check (0 R1 UPTREND dates) | PASS | 0 R1 UPTREND date(s) in BEAR_2022: - |
| T1 | abs(UP - DOWN) > 0.02 on primary R1 cell | FAIL | diff=-0.011834 (bar met: False) |
| MATERIAL | T2 or T3 differs materially between UP and DOWN | PASS | T2 material=True, T3 material=False |
| DROP-WORST | drop-worst-date re-check keeps the sign | FAIL | qualifying cells: T2 (sign kept=False) |

Failed gates: T1: diff=-0.011834 (bar met: False); DROP-WORST: qualifying cells: T2 (sign kept=False).

> Warning: T1 is a loose descriptive screen only — it can be passed by sample-specific rebound artifacts and is **not** predictive-validity evidence; T1 alone can never pass the go rule.

## 1. Provenance

- Base dataset: `company_quality_dataset_risk_off.v3.csv` (25025 rows, 39 signal dates, SHA256 `2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e`).
- 2022 bear dataset: `company_quality_dataset_risk_off.repaired.csv` (8251 rows, 12 signal dates, SHA256 `43e5cd4a440c92857c11106016db0b827202c279e2acfbdc7cb0281ff2f007d6`).
- Merged primary sample: 51 dates (disjoint, deduplicated, chronologically sorted; 2022 dates first, vol_high sequence computed over this merged order).
- Reproduction command: `python scripts/audit_regime_separation.py --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv --bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv --out-dir docs/regime_indicator_validation_20261017`.
- Primary scope: `ETF_SLICE` (`watchlist_etf_count >= 1`); `FULL` and `BASE_39_ONLY` tables are secondary context and cannot trigger a go.
- Decisions rebuilt per date via shared `build_scope_records` (`scripts/run_extended_replay_evaluation.py`), v1_current and v2_current; R0/R2/R1 labels use trailing-only inputs.
- Universe approximation: the current watchlist is applied to all historical dates (`union_superset_approx`); the ETF-slice cut is the bias-reduced read (AGENTS.md §4).
- Retrospective replay only, not OOS; overlapping 60d windows are not independent samples (AGENTS.md §8).

## 2. S0 safety check (hard gate, primary indicator R1)

Result: **PASS** — 0 R1 UPTREND date(s) in BEAR_2022: -.

| indicator | role | UPTREND dates in BEAR_2022 | DOWNTREND dates in BEAR_2022 |
|---|---|---|---|
| R0 | context | 1 | 11 |
| R1 | primary | 0 | 11 |
| R2 | context | 0 | 12 |

Only R1 is the primary indicator; R0/R2 UPTREND counts in the 2022 bear sample are context only.

## 3. Indicator label counts (dates)

| indicator | role | MERGED_51 (primary sample) | BASE_39_ONLY (secondary) |
|---|---|---|---|
| R0 | context | UP 30 / DOWN 21 / NEUTRAL 0 | UP 29 / DOWN 10 / NEUTRAL 0 |
| R1 | primary | UP 16 / DOWN 19 / NEUTRAL 16 | UP 7 / DOWN 9 / NEUTRAL 23 |
| R2 | context | UP 36 / DOWN 15 / NEUTRAL 0 | UP 36 / DOWN 3 / NEUTRAL 0 |

## 4. Separation tests T1–T3 (all three indicators)

Rows are ordered primary first: MERGED_51 / ETF_SLICE, then MERGED_51 / FULL, then BASE_39_ONLY / ETF_SLICE and BASE_39_ONLY / FULL. Sensitivity rows are excluded here (section 6).

### T1 — universe 60d net-QQQ excess: UPTREND vs DOWNTREND dates

| sample / scope | ind | role | n_up | n_down | mean UP | mean DOWN | diff | bar met |
|---|---|---|---|---|---|---|---|---|
| MERGED_51 (primary) / ETF_SLICE | R0 | context | 30 | 21 | +0.3% | +0.6% | -0.2% | False |
| MERGED_51 (primary) / ETF_SLICE | R1 | primary | 16 | 19 | -0.5% | +0.7% | -1.2% | False |
| MERGED_51 (primary) / ETF_SLICE | R2 | context | 36 | 15 | +0.0% | +1.4% | -1.3% | False |
| MERGED_51 (primary) / FULL | R0 | context | 30 | 21 | -0.2% | +1.7% | -1.9% | False |
| MERGED_51 (primary) / FULL | R1 | primary | 16 | 19 | -1.3% | +1.9% | -3.2% | True |
| MERGED_51 (primary) / FULL | R2 | context | 36 | 15 | +0.2% | +1.6% | -1.4% | False |
| BASE_39_ONLY (secondary) / ETF_SLICE | R0 | context | 29 | 10 | +0.3% | -0.5% | +0.8% | False |
| BASE_39_ONLY (secondary) / ETF_SLICE | R1 | primary | 7 | 9 | -0.4% | -0.8% | +0.4% | False |
| BASE_39_ONLY (secondary) / ETF_SLICE | R2 | context | 36 | 3 | +0.0% | +0.1% | -0.0% | False |
| BASE_39_ONLY (secondary) / FULL | R0 | context | 29 | 10 | -0.4% | +2.9% | -3.3% | True |
| BASE_39_ONLY (secondary) / FULL | R1 | primary | 7 | 9 | -0.8% | +3.1% | -3.8% | True |
| BASE_39_ONLY (secondary) / FULL | R2 | context | 36 | 3 | +0.2% | +3.3% | -3.1% | True |

date-equal means; diff = mean(UP) - mean(DOWN); bootstrap 95% CI of the difference; bar met = |diff| > 2pp.

### T2 — date-paired v2-minus-v1 TOP15 60d delta per regime

| sample / scope | ind | role | n_up | n_down | mean delta UP [CI95] | mean delta DOWN [CI95] | diff | pos share UP/DOWN | material |
|---|---|---|---|---|---|---|---|---|---|
| MERGED_51 (primary) / ETF_SLICE | R0 | context | 30 | 21 | +0.4% [-0.7%,+1.5%] | -0.2% [-2.1%,+2.0%] | +0.6% | +63.3% / +42.9% | True |
| MERGED_51 (primary) / ETF_SLICE | R1 | primary | 16 | 19 | +0.3% [-1.5%,+1.8%] | -0.1% [-2.2%,+2.1%] | +0.4% | +62.5% / +47.4% | True |
| MERGED_51 (primary) / ETF_SLICE | R2 | context | 36 | 15 | +0.7% [-0.4%,+1.8%] | -1.2% [-3.3%,+1.2%] | +1.9% | +63.9% / +33.3% | True |
| MERGED_51 (primary) / FULL | R0 | context | 30 | 21 | +0.2% [-0.8%,+1.2%] | +0.3% [-1.9%,+2.2%] | -0.1% | +53.3% / +52.4% | False |
| MERGED_51 (primary) / FULL | R1 | primary | 16 | 19 | +0.6% [-0.9%,+1.9%] | +0.2% [-2.0%,+2.4%] | +0.4% | +56.2% / +52.6% | False |
| MERGED_51 (primary) / FULL | R2 | context | 36 | 15 | +0.7% [-0.3%,+1.7%] | -1.0% [-3.3%,+1.4%] | +1.7% | +58.3% / +40.0% | True |
| BASE_39_ONLY (secondary) / ETF_SLICE | R0 | context | 29 | 10 | +0.4% [-0.7%,+1.6%] | -0.8% [-3.6%,+2.6%] | +1.2% | +65.5% / +40.0% | True |
| BASE_39_ONLY (secondary) / ETF_SLICE | R1 | primary | 7 | 9 | -1.6% [-3.6%,+0.5%] | -0.8% [-4.2%,+3.1%] | -0.8% | +57.1% / +44.4% | False |
| BASE_39_ONLY (secondary) / ETF_SLICE | R2 | context | 36 | 3 | +0.7% [-0.4%,+1.8%] | -6.7% [-9.2%,-3.0%] | +7.4% | +63.9% / +0.0% | True |
| BASE_39_ONLY (secondary) / FULL | R0 | context | 29 | 10 | +0.3% [-0.7%,+1.2%] | -0.4% [-4.0%,+3.0%] | +0.7% | +55.2% / +50.0% | True |
| BASE_39_ONLY (secondary) / FULL | R1 | primary | 7 | 9 | -0.6% [-3.0%,+2.4%] | -0.8% [-4.8%,+2.9%] | +0.2% | +28.6% / +44.4% | False |
| BASE_39_ONLY (secondary) / FULL | R2 | context | 36 | 3 | +0.7% [-0.3%,+1.7%] | -7.6% [-10.5%,-3.0%] | +8.3% | +58.3% / +0.0% | True |

per-regime mean / bootstrap CI / LOO-min / positive-date share (E0 paired_delta_stats); material = regimes differ in sign or |diff| > 2pp.

### T3 — tier-16–30-minus-universe gap per regime

| sample / scope | ind | role | n_up | n_down | gap UP (t) | gap DOWN (t) | diff | material |
|---|---|---|---|---|---|---|---|---|
| MERGED_51 (primary) / ETF_SLICE | R0 | context | 30 | 21 | -1.4% (t=-1.539914) | -1.1% (t=-0.800764) | -0.4% | False |
| MERGED_51 (primary) / ETF_SLICE | R1 | primary | 16 | 19 | -2.1% (t=-2.374929) | -1.0% (t=-0.664410) | -1.1% | False |
| MERGED_51 (primary) / ETF_SLICE | R2 | context | 36 | 15 | -2.0% (t=-2.185487) | +0.4% (t=0.320565) | -2.5% | True |
| MERGED_51 (primary) / FULL | R0 | context | 30 | 21 | -1.6% (t=-1.432008) | -5.0% (t=-2.421072) | +3.4% | True |
| MERGED_51 (primary) / FULL | R1 | primary | 16 | 19 | -2.3% (t=-1.512450) | -5.0% (t=-2.207013) | +2.7% | True |
| MERGED_51 (primary) / FULL | R2 | context | 36 | 15 | -3.4% (t=-2.697990) | -2.0% (t=-0.930409) | -1.4% | False |
| BASE_39_ONLY (secondary) / ETF_SLICE | R0 | context | 29 | 10 | -1.3% (t=-1.384642) | -4.1% (t=-1.989813) | +2.8% | True |
| BASE_39_ONLY (secondary) / ETF_SLICE | R1 | primary | 7 | 9 | -1.9% (t=-1.151004) | -4.2% (t=-1.806666) | +2.3% | True |
| BASE_39_ONLY (secondary) / ETF_SLICE | R2 | context | 36 | 3 | -2.0% (t=-2.185487) | -2.5% (t=-0.538797) | +0.5% | False |
| BASE_39_ONLY (secondary) / FULL | R0 | context | 29 | 10 | -1.6% (t=-1.378140) | -12.2% (t=-4.990623) | +10.6% | True |
| BASE_39_ONLY (secondary) / FULL | R1 | primary | 7 | 9 | -3.1% (t=-1.028608) | -12.6% (t=-4.680866) | +9.5% | True |
| BASE_39_ONLY (secondary) / FULL | R2 | context | 36 | 3 | -3.4% (t=-2.697990) | -15.1% (t=-4.675202) | +11.6% | True |

per-regime mean gap and paired t-stat over dates; material = regimes differ in sign or |diff| > 2pp.

## 5. E4b go/no-go — drop-worst-date re-check detail

| cell | full | LOO-min | LOO-max | worst date dropped | recomputed without worst | sign kept |
|---|---|---|---|---|---|---|
| T2 | +0.4% | -0.1% | +1.0% | 2026-03-31 | -0.1% | False |

Reminder (equal prominence for the stop path): the pre-registered spec states that if any gate fails, there is **no E4b follow-up** — a NO-GO closes this line of work rather than deferring it.

## 6. R1 ±0.05 breadth-cutoff sensitivity (diagnostic only)

| indicator | MERGED_51 label counts | T1 diff (ETF_SLICE) |
|---|---|---|
| R1_SENS_LO | UP 18 / DOWN 19 / NEUTRAL 14 | -2.2% |
| R1_SENS_HI | UP 15 / DOWN 20 / NEUTRAL 16 | -1.2% |

Per spec, the ±0.05 variants are reported for transparency only: they cannot select the indicator and cannot trigger a go.

## 7. Honest limitations

- Merged sample is 51 monthly dates (39 base 2023-01..2026-03 / 12 bear-2022); the R1 primary split has 16 UPTREND / 19 DOWNTREND / 16 NEUTRAL dates (status-quo R0 trailing-down dates: 21). Regime cells are small and every aggregate is date-equal.
- Attack evidence base = a single bull regime (2023-01..2026-03); defense has two eras (2023-2026 dips + 2022 bear). Even a GO licenses only a pre-registered E4b with prospective/shadow evidence; retrospective results can never auto-promote.
- Merged-sequence vol_high warm-up: the first 6 merged dates (2022-01-31, 2022-02-28, 2022-03-31, 2022-04-29, 2022-05-31, 2022-06-30) inherit vol_high=False by the min-6-prior-dates rule; the BASE_39-only sequence has its own warm-up over its first 6 dates (2023-01-31, 2023-02-28, 2023-03-31, 2023-04-28, 2023-05-31, 2023-06-30).
- Forward labels (`fwd_ret_*`, `qqq_return_*`) are used strictly as scored outcomes in T1–T3; the indicator definitions never read them (firewall-tested).
- Overlapping 60d label windows are not independent samples; LOO / sign-keep checks are robustness probes, not significance tests; the sample is small.
- Universe drift caveat inherited from both frozen datasets (union approximation; ETF_SLICE is the bias-reduced read).

## 8. Reproduction

1. Delete `docs/regime_indicator_validation_20261017` and re-run the documented command below; outputs are deterministic (seed-stable bootstrap, chronological sort, no wall-clock use).
2. Command: `python scripts/audit_regime_separation.py --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv --bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv --out-dir docs/regime_indicator_validation_20261017`
3. Verify every file against `SHA256SUMS` (this directory).
