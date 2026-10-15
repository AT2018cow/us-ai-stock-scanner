# Phase M4 Execution Spec — Dual-Track Paired Validation (Human Utility + Held-Out 2025/2026Q1 Economics) & Promotion Gate

> **Target Agent**: Muse Spark 1.3 (Execution Agent)
> **Reviewer**: Chief Technical Lead / Independent Research Auditor
> **Roadmap Reference**: `docs/next_phase_v1_failure_attribution_and_v2_research_plan_20261014.md` (§4 M4, §5.4 Gates G4–G5)
> **Prerequisite Evidence**:
> - Phase M2 (`docs/m2_v1_failure_attribution_20261015/`)
> - Phase M3 (`docs/m3_candidate_preflight_20261015/m3_preregistration_protocol.json`)

---

## 1. Objective

With the 5 candidate variants (`v1_baseline`, `h1_quality_only`, `h2_entry_only`, `h3_action_only`, `v2_combined`) frozen and pre-registered in Phase M3, execute **Phase M4 Dual-Track Validation**:
1. **Track 1 — Human Utility & Explainability Gate**: Quantify improvements in narrative consistency, silent-gate elimination, Top-15 `ENTRY_READY` concentration, and Presentation IR / Report v2 rendering parity across `snap62`, `snap510`, and all 39 historical dates.
2. **Track 2 — Paired Economic Outcome Gate (Unsealing the 2025/2026Q1 Post-2024 Period Once)**: Perform a single, pre-registered paired evaluation across `DEV_2023_2024` (24 dates), `POST2024_HELD_OUT` (`2025-01-31..2026-03-31`, 15 dates), and `ALL_39_DATES` (39 dates) with date-level block bootstrap confidence intervals, year/regime splits, and leave-one-date-out concentration checks.
3. **Track 3 — Honest Gate G4/G5 Verdict**: Issue the formal M4 decision artifact (`m4_promotion_gate.json`) adhering to the roadmap's epistemic rule that retrospective replay is labeled `RETROSPECTIVE_HELD_OUT` (never fake "prospective OOS") and default `v1` remains untouched unless explicitly promoted in M5.

---

## 2. Strict Scope & Shared-Worktree Rules

### Shared-Worktree Safety (CRITICAL):
- You share `/home/ss/opencode_ws/us-ai-stock-scanner` with the Chief Architect.
- **DO NOT** run `git checkout`, `git switch`, `git branch`, `git add`, `git commit`, `git push`, `git stash`, `git reset`, or `git clean`.
- **DO NOT** make any network calls (no SEC / Alpaca / Modal calls).
- **DO NOT** tune, tweak, or alter ANY threshold or weight in `decision/quality.py`, `decision/entry.py`, `decision/action.py`, or `decision/integrated.py`! The M3 candidates are **frozen**. M4 must evaluate them **as-is**, even if a variant underperforms on 2025/2026Q1!

### Allowed to Create:
1. `src/ai_value_scanner/research/m4_paired_validation.py` **(NEW — pure dual-track evaluation module)**
2. `scripts/m4_run_paired_validation.py` **(NEW — deterministic CLI producing `docs/m4_paired_validation_20261015/`)**
3. `tests/test_m4_paired_validation.py` **(NEW — unit tests covering paired date-equal excess, block bootstrap CI, concentration/LOO checks, human-utility metrics, and honest epistemic labeling)**
4. `docs/m4_paired_validation_20261015/` **(NEW directory with 5 compact deliverables + `SHA256SUMS`, total `< 140 KB`, zero `/home/...` or `/tmp/...` paths)**

---

## 3. Exact Specification for `src/ai_value_scanner/research/m4_paired_validation.py`

### 3.1 Epistemic Period Partition
Define 3 exact date partitions on `historical_v3` (39 signal dates, 25,025 rows):
1. `DEV_2023_2024`: 24 signal dates (`2023-01-31` .. `2024-12-31`), evidence tier `"RETROSPECTIVE_DEVELOPMENT"`.
2. `POST2024_HELD_OUT`: 15 signal dates (`2025-01-31` .. `2026-03-31`), evidence tier `"RETROSPECTIVE_POST2024_HELD_OUT_APPROX_UNIVERSE"`.
3. `ALL_39_DATES`: all 39 signal dates (`2023-01-31` .. `2026-03-31`), evidence tier `"RETROSPECTIVE_FULL_REPLAY_APPROX_UNIVERSE"`.

### 3.2 Track 1: Human Utility & Explainability Metrics (`evaluate_human_utility`)
For each scope (`snap62`, `snap510`, `DEV_2023_2024`, `POST2024_HELD_OUT`, `ALL_39_DATES`) and each of the 5 variants (`v1_baseline`, `h1_quality_only`, `h2_entry_only`, `h3_action_only`, `v2_combined`), compute:
1. `n_contradictory_cash_accrual`: count of rated decisions that simultaneously emit `ocf_to_net_income_strong` (or `OCF/NI >= 1.0` with `FCF > 0`) AND `accrual_ratio_weak`.
2. `n_silent_non_ready_entry`: count of `WATCH_BREAKOUT` or `TREND_DAMAGED` decisions with zero negative `entry.risks`.
3. `mean_top15_ready_share`: average across signal dates of the fraction of Top-15 decisions (`priority <= 15`) that have `entry.state == ENTRY_READY` (`ActionState.PRIORITY_REVIEW` or `ENTRY_READY`).
4. `mean_top15_quality_a_share`: average across signal dates of the fraction of Top-15 decisions with `quality.grade == QualityGrade.A`.
5. `mean_top15_high_growth_share`: average across signal dates of the fraction of Top-15 decisions with `revenue_yoy >= 0.25`.
6. `report_v2_parity_ok`: boolean verifying that for a sample date/snapshot, `build_decision_report_view` and `render_action_list_markdown(..., layout_version="v2")` + `render_detailed_decision_markdown(..., layout_version="v2")` succeed with `0` exceptions, `0` ordering mismatches, and `0` absolute paths.

### 3.3 Track 2: Paired Economic Outcome Metrics (`evaluate_paired_economics`)
For each period (`DEV_2023_2024`, `POST2024_HELD_OUT`, `ALL_39_DATES`), each variant, and each cohort (`TOP5`, `TOP15`, `PRIORITY_REVIEW`, `QUALITY_A`, `ENTRY_READY`):
1. **Multi-Horizon Date-Equal Net QQQ Excess (`20d`, `60d`, `120d`)**:
   - Per signal date $t$, compute the cohort mean excess return:
     $$E_{t, h}^{(v)} = \frac{1}{|C_{t}^{(v)}|} \sum_{i \in C_{t}^{(v)}} \left(\text{fwd\_ret}_{h, i, t} - \text{qqq\_return}_{h, i, t}\right)$$
     for horizons $h \in \{20, 60, 120\}$ over rows with finite forward returns.
   - Report `n_matured_dates`, `n_total_obs`, `mean_excess_20d`, `mean_excess_60d`, `median_date_excess_60d`, `mean_excess_120d`, `p10_date_excess_60d` (10th percentile across dates), and `worst_date_excess_60d`.
2. **Paired Date-by-Date Delta vs `v1_baseline` on 60d Excess (`paired_delta_60d`)**:
   - On every signal date $t$ where both `variant` and `v1_baseline` have non-empty cohort $C_t$:
     $$\Delta_t = E_{t, 60}^{(\text{variant})} - E_{t, 60}^{(\text{v1\_baseline})}$$
   - Report:
     - `mean_paired_delta_60d`: mean of $\Delta_t$ across dates;
     - `median_paired_delta_60d`: median of $\Delta_t$ across dates;
     - `positive_delta_date_share`: fraction of dates with $\Delta_t > 0$;
     - `ci95_low_60d`, `ci95_high_60d`: deterministic stationary/date bootstrap 95% confidence interval (`n_boot=1000`, `seed=20261015`) resampling signal dates with replacement;
     - `loo_min_mean_delta_60d`: worst leave-one-date-out mean $\Delta_t$ (proving whether a single outlier date flips the sign of `mean_paired_delta_60d`).
3. **Year & Market-Regime Sub-Splits (`evaluate_regime_and_year_splits`)**:
   - For `TOP15` and `PRIORITY_REVIEW` on 60d net QQQ excess, report `v1_baseline` vs `h1_quality_only`, `h2_entry_only`, `h3_action_only`, `v2_combined` broken down by:
     - Calendar year: `2023`, `2024`, `2025`, `2026Q1`;
     - Market regime: `UP_SUPPORTIVE` (`regime == "up"` and `benchmark_trend_ok is True`) vs `DEFENSIVE_OR_DOWN` (`regime == "down"` or `benchmark_trend_ok is False`).

---

## 4. Required Deliverables under `docs/m4_paired_validation_20261015/`

Your CLI `scripts/m4_run_paired_validation.py` must deterministically generate these **5 compact files + `SHA256SUMS`** (total size `< 140 KB`, zero `/home/...` or `/tmp/...` paths):

1. **`m4_human_utility_summary.csv`**:
   - Track 1 results across all 5 scopes and 5 variants (`n_contradictory_cash_accrual`, `n_silent_non_ready_entry`, `mean_top15_ready_share`, `mean_top15_quality_a_share`, `mean_top15_high_growth_share`, `report_v2_parity_ok`).
2. **`m4_paired_economic_summary.csv`**:
   - Track 2 results across all 3 periods (`DEV_2023_2024`, `POST2024_HELD_OUT`, `ALL_39_DATES`), 5 variants, and 5 cohorts (`TOP5`, `TOP15`, `PRIORITY_REVIEW`, `QUALITY_A`, `ENTRY_READY`), including `mean_excess_20d`, `mean_excess_60d`, `median_date_excess_60d`, `mean_excess_120d`, `p10_date_excess_60d`, `worst_date_excess_60d`, `mean_paired_delta_60d`, `median_paired_delta_60d`, `positive_delta_date_share`, `ci95_low_60d`, `ci95_high_60d`, and `loo_min_mean_delta_60d`.
3. **`m4_year_and_regime_splits.csv`**:
   - Breakdown of `TOP15` and `PRIORITY_REVIEW` 60d net QQQ excess and paired deltas by year (`2023`, `2024`, `2025`, `2026Q1`) and by regime (`UP_SUPPORTIVE` vs `DEFENSIVE_OR_DOWN`).
4. **`m4_promotion_gate.json`**:
   - Structured Gate G4/G5 decision artifact recording:
     - `human_utility_verdict`: per-variant verdict (`PASS` / `FAIL`) based on eliminating contradictory narratives, eliminating silent gates, and preserving/improving Top-15 `ENTRY_READY` share;
     - `economic_verdict`: per-variant honest classification on `POST2024_HELD_OUT` and `ALL_39_DATES` (`POSITIVE_ROBUST` if `mean_paired_delta_60d > 0` and `loo_min_mean_delta_60d > 0`; `POSITIVE_POINT_ESTIMATE_CI_WIDE` if `mean_paired_delta_60d > 0` but `ci95_low_60d <= 0`; `NEGATIVE_OR_FLAT` if `mean_paired_delta_60d <= 0`);
     - `overall_m4_recommendation`: explicit recommendation for M5 (e.g., which stages merit opt-in shadow deployment alongside default `v1`, while keeping `policy_version="v1"` as the production default).
5. **`m4_validation_report.md`**:
   - Concise, decision-grade validation report presenting Track 1 (Human Utility), Track 2 (Paired Economics across Dev vs Post-2024 Held-Out vs All-39), Year/Regime robustness, and the final Gate G4/G5 recommendation.

---

## 5. Verification Commands

Run locally:
```bash
.venv/bin/python scripts/m4_run_paired_validation.py
.venv/bin/python -m unittest discover -s tests -p "test_m4_paired_validation.py"
.venv/bin/python -m unittest discover -s tests
```
When all tests pass and `docs/m4_paired_validation_20261015/` is generated, stop and report for Chief Architect review.
