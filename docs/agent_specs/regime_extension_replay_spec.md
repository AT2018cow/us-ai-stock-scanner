# Agent Specification: Forward-Drawdown Attribution (Route A) & 2022 Tech Bear Replay (Route B)

- **Date**: 2026-10-17
- **Companion evidence**: `outputs/m4_revalidation_current_20261016/SUMMARY.md` (E0–E3 scratch study)
- **Frozen reference study**: `docs/m4_paired_validation_20261015/` (do not modify)
- **Frozen 39-date dataset (`2023-01..2026-03`)**: `outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv` (read-only)
- **Target Execution Agent**: DeepSeek (offline implementation of `scripts/run_extended_replay_evaluation.py` + unit tests `tests/test_run_extended_replay_evaluation.py` + Route A execution on the frozen 39-date dataset; no Git state mutations, no network calls, no production code changes)
- **Reviewer / Integrator**: Architect Agent

---

## 1. Motivation & Key Empirical Finding

1. **Why the original `2026-04 → 2026-09` extension spec was mis-targeted**:
   - Real Alpaca market data shows `QQQ` rallied **`+26.6%`** from `2026-04-01` (`$584.34`) to `2026-09-30` (`$739.51`), so `2026-04..09` was a continuation of the bull rally rather than a bear/drawdown regime; moreover, `2026-07..09` has `0/3` matured 60d forward-return labels as of `2026-10-17`.
2. **Why previous `regime == "down"` splits missed `v2`'s drawdown protection**:
   - `regime == "down"` is a *trailing* indicator (`benchmark_trailing_60d < 0` on `signal_date`). In the 2023–2026 bull market, every trailing dip was followed by a sharp V-shaped rebound (`qqq_return_60` of `+14%` to `+21%`).
   - When the existing 39 signal dates are instead partitioned by **Forward Market Direction** (`FWD_DRAWDOWN_60D`: `qqq_return_60 < 0`, `n=8` pre-drop peak dates vs `FWD_BULL_60D`: `qqq_return_60 >= 0`, `n=31` dates), the bias-reduced ETF slice (`watchlist_etf_count >= 1`) shows that `v2`'s top tiers (`1-5`, `6-15`, `16-30`, `31-50`) flip from lagging QQQ in runaway bull months to **outperforming QQQ (`+1.28%`, `+1.59%`, `+2.76%`, `+7.09%`) during forward market drawdowns**.
3. **Two-Route Plan (Route A + Route B)**:
   - **Route A (Immediate Offline Attribution on Frozen 39 Dates `2023-01..2026-03`)**:
     Quantify `v2` vs `v1` cohort economics, rank-tier excess returns, severe tail-loss / blowup rates (`fwd_ret_60 <= -0.20`), and `price_to_sma200` overextension crash exposure across `FWD_DRAWDOWN_60D` (`n=8`), `FWD_BULL_60D` (`n=31`), `FWD_DRAWDOWN_20D` (`n=12`), and `TRAILING_DOWN` (`n=10`), on both the Full Universe (`FULL`) and the Bias-Reduced ETF Slice (`ETF_SLICE`: `watchlist_etf_count >= 1`).
   - **Route B (2022 Full-Year Tech Bear Market Replay `2022-01-31 → 2022-12-30`, 12 Monthly Signal Dates, QQQ `-33.7%`)**:
     Support stitching and evaluating an extracted+repaired 2022 `company_quality` dataset (`--bear-2022-dataset`) where `QQQ` fell `-33.7%` and 100% of 20d/60d/120d forward labels are matured (`BEAR_2022_FULL` and `BEAR_2022_ETF_SLICE`).

---

## 2. Scope & Hard Constraints

### In Scope for DeepSeek (Offline Deliverable):
1. Implement `scripts/run_extended_replay_evaluation.py` (offline, deterministic, zero network calls) supporting:
   - Route A on `--base-dataset` (`outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv`);
   - Route B when `--bear-2022-dataset` (and/or `--extension-dataset`) is provided;
   - Reproduction check against `--base-reference-dir` (`outputs/m4_revalidation_current_20261016/`).
2. Implement unit tests in `tests/test_run_extended_replay_evaluation.py` (`unittest`, synthetic fixtures, no network, no real cache writes).
3. Run `scripts/run_extended_replay_evaluation.py` on the frozen 39-date `--base-dataset` to populate the initial Route A artifacts under `docs/drawdown_and_bear_replay_20261017/`.

### Out of Scope (Hard):
- Do **not** modify any files under `src/ai_value_scanner/**`, `configs/**`, `data/**`, `docs/m4_paired_validation_20261015/**`, or `outputs/historical_selection_v1_20261011_03/**`.
- Do **not** change any production threshold, weight, penalty, or policy.
- Do **not** run Modal or any network commands during DeepSeek execution (the Architect / Operator will run the 2022 Modal extraction in Phase 2 and re-run the script with `--bear-2022-dataset`).

---

## 3. Detailed Design of `scripts/run_extended_replay_evaluation.py`

### 3.1 CLI Interface

```bash
.venv/bin/python scripts/run_extended_replay_evaluation.py \
  --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv \
  [--bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv] \
  [--extension-dataset <optional post-2026-03 csv>] \
  [--base-reference-dir outputs/m4_revalidation_current_20261016] \
  [--output-dir docs/drawdown_and_bear_replay_20261017]
```

### 3.2 Rebuilding Canonical `v1` and `v2` Decisions Per Date

For a given dataset slice (`FULL`: all rows; `ETF_SLICE`: rows where `pd.to_numeric(df["watchlist_etf_count"], errors="coerce").fillna(0) >= 1`):
- Group by `signal_date` (sorted ascending).
- For each `signal_date` group, call the canonical production builder from `ai_value_scanner.decision.integrated`:
  ```python
  decisions_v1 = build_stock_decisions(
      group,
      decision_date=signal_date,
      generated_at_utc=f"{signal_date}T00:00:00Z",
      policy_version="v1",
  )
  decisions_v2 = build_stock_decisions(
      group,
      decision_date=signal_date,
      generated_at_utc=f"{signal_date}T00:00:00Z",
      policy_version="v2",
  )
  ```
- Note: In `FULL` (and separately in `ETF_SLICE`), calling `build_stock_decisions` on `group` automatically assigns `decision.priority` (`1..N`) using the exact current production ranking logic (`assign_action_priorities` for `v1`, `assign_action_priorities_v2` for `v2` including pre-earnings, non-op gain, split/basis, and overextension adjustments).
- Attach forward outcomes from `group` per `symbol`:
  - `fwd_ret_20`, `fwd_ret_60`, `fwd_ret_120`
  - `qqq_return_20`, `qqq_return_60`, `qqq_return_120`
  - Net-QQQ excess returns per symbol and horizon $h \in \{20, 60, 120\}$:
    `excess_h = fwd_ret_h - qqq_return_h` (when both are finite; `None`/`NaN` otherwise).
  - Also retain `price_to_sma200`, `return_60d`, `regime`, `benchmark_trend_ok`, `watchlist_etf_count`.

### 3.3 Segment & Regime Definitions

1. **On `--base-dataset` (`2023-01..2026-03`, 39 dates)**:
   - `BASE_ALL_39`: all 39 dates (`2023-01-31` .. `2026-03-31`)
   - `DEV_2023_2024`: `signal_date <= "2024-12-31"` (24 dates, for E0 reproduction check)
   - `POST_2025_2026Q1`: `"2025-01-01" <= signal_date <= "2026-03-31"` (15 dates, for E0 reproduction check)
   - `FWD_DRAWDOWN_60D`: dates in `BASE_ALL_39` where date-level `qqq_return_60 < 0.0` (8 dates: `2023-06-30`, `2023-07-31`, `2024-11-29`, `2024-12-31`, `2025-01-31`, `2025-10-31`, `2025-11-28`, `2025-12-31`)
   - `FWD_BULL_60D`: dates in `BASE_ALL_39` where date-level `qqq_return_60 >= 0.0` (31 dates)
   - `FWD_DRAWDOWN_20D`: dates in `BASE_ALL_39` where date-level `qqq_return_20 < 0.0` (12 dates)
   - `FWD_BULL_20D`: dates in `BASE_ALL_39` where date-level `qqq_return_20 >= 0.0` (27 dates)
   - `TRAILING_DOWN`: dates in `BASE_ALL_39` where `regime == "down"` (10 dates)
   - `TRAILING_UP`: dates in `BASE_ALL_39` where `regime == "up"` (29 dates)
2. **When `--bear-2022-dataset` is provided (`2022-01..2022-12`, 12 dates)**:
   - `BEAR_2022`: all dates in `--bear-2022-dataset` (`2022-01-31` .. `2022-12-30`)
   - `BEAR_2022_FWD_DRAWDOWN_60D`: dates in `BEAR_2022` where `qqq_return_60 < 0.0`
   - `COMBINED_DRAWDOWN_60D`: union of `BEAR_2022_FWD_DRAWDOWN_60D` + `FWD_DRAWDOWN_60D`
3. **When `--extension-dataset` is provided**:
   - `EXT_2026H1` (`2026-04-01` .. `2026-06-30`), `EXT_2026H2` (`2026-07-01` .. `2026-09-30`), `EXT_PIT_20260930` (`2026-09-30`).

### 3.4 Required Output Tables & Metrics (`--output-dir`, default `docs/drawdown_and_bear_replay_20261017/`)

All outputs must be deterministic, contain **zero absolute file paths** (`contains_absolute_path` check), and keep total directory size `< 140 KB`:

1. **`cohort_economics_by_regime.csv`**:
   - Columns:
     `universe_scope` (`FULL` | `ETF_SLICE`), `segment`, `variant` (`v1_current` | `v2_current`), `cohort` (`TOP5` | `TOP15` | `PRIORITY_REVIEW` | `QUALITY_A` | `ENTRY_READY` | `UNIVERSE`), `n_dates_20`, `n_dates_60`, `n_dates_120`, `obs_60`, `mean_excess_20`, `mean_excess_60`, `median_excess_60`, `worst_date_excess_60`, `mean_excess_120`, `win_rate_vs_qqq_60` (share of matured dates with date-mean `excess_60 > 0`), `mean_raw_ret_60`, `severe_loss_rate_60` (date-equal mean share of cohort members with `fwd_ret_60 <= -0.20`), `severe_underperform_rate_60` (date-equal mean share of cohort members with `excess_60 <= -0.20`).
   - Cohort definitions per date:
     - `TOP5`: `decision.priority <= 5`
     - `TOP15`: `decision.priority <= 15`
     - `PRIORITY_REVIEW`: `decision.action_state.value == "PRIORITY_REVIEW"`
     - `QUALITY_A`: `decision.quality.grade.value == "A"`
     - `ENTRY_READY`: `decision.entry.state.value == "ENTRY_READY"`
     - `UNIVERSE`: all evaluated rows on that date.
2. **`paired_deltas_by_regime.csv`**:
   - Uses `paired_delta_stats(v1_by_date, v2_by_date)` from `ai_value_scanner.research.m4_paired_validation`.
   - Columns:
     `universe_scope`, `segment`, `cohort` (`TOP5`, `TOP15`, `PRIORITY_REVIEW`, `QUALITY_A`), `horizon` (`20`, `60`, `120`), `n_paired_dates`, `mean_delta`, `median_delta`, `ci_low`, `ci_high`, `loo_min`, `positive_date_share`, `mean_severe_loss_delta_60` (paired date-equal mean of `severe_loss_rate_60(v2) - severe_loss_rate_60(v1)`).
3. **`rank_tiers_by_regime.csv`**:
   - For `v2_current` across `universe_scope` (`FULL`, `ETF_SLICE`) and `segment`:
   - Rank tiers by `decision.priority`: `1-5`, `6-15`, `16-30`, `31-50`, `51-100`, `101+`, `universe`.
   - Columns:
     `universe_scope`, `segment`, `tier`, `n_dates_60`, `obs_60`, `mean_excess_20`, `mean_excess_60`, `median_excess_60`, `diff_vs_universe_60`, `win_rate_vs_qqq_60`, `mean_raw_ret_60`, `severe_loss_rate_60` (`fwd_ret_60 <= -0.20`).
4. **`entry_and_extension_crosscut.csv`**:
   - For `v2_current` across `universe_scope` (`FULL`, `ETF_SLICE`) and `segment` (`BASE_ALL_39`, `FWD_BULL_60D`, `FWD_DRAWDOWN_60D`, `TRAILING_DOWN`, plus `BEAR_2022` when provided):
   - Breakdown dimensions:
     - `cut_type == "entry_state"` (`ENTRY_READY`, `WATCH_PULLBACK`, `WATCH_BREAKOUT`, `TREND_DAMAGED`, `INSUFFICIENT_DATA`, both `all_grades` and `grade_A_only`);
     - `cut_type == "sma200_extension"` (`<1.00x`, `1.00-1.25x`, `1.25-1.35x`, `1.35-1.45x`, `>1.45x`, both `all_grades` and `grade_A_only`);
     - `cut_type == "quality_grade"` (`A`, `B`, `C`, `UNRATED`).
   - Columns:
     `universe_scope`, `segment`, `cut_type`, `bucket`, `n_dates_60`, `obs_60`, `mean_excess_20`, `mean_excess_60`, `median_excess_60`, `mean_raw_ret_60`, `severe_loss_rate_60`.
5. **`report.md`** & **`SHA256SUMS`**:
   - Concise, human-readable Markdown report summarizing:
     1. E0 baseline reproduction check status (comparing `DEV_2023_2024`, `POST_2025_2026Q1`, `BASE_ALL_39` on `v1_current` against `--base-reference-dir` within tolerance `1e-5`);
     2. Why trailing `regime == "down"` in 2023–2026 measures V-shaped post-dip rebounds (`+14%..+21%` QQQ), whereas `FWD_DRAWDOWN_60D` (`qqq_return_60 < 0`, `n=8` dates) measures true peak-to-trough drawdown protection;
     3. Key tables comparing `FWD_BULL_60D` vs `FWD_DRAWDOWN_60D` (and `BEAR_2022` when present) across Rank Tiers, Cohorts, Quality Grades, Entry States, and `price_to_sma200` Extension buckets, including `severe_loss_rate_60` (`fwd_ret_60 <= -20%`);
     4. Explicit provenance and universe-approximation disclosures per `AGENTS.md` §4 & §8.

---

## 4. Phase 2 — 2022 Bear Market Dataset Extraction Commands (For Operator / Architect Execution After Runner Is Built)

Once `scripts/run_extended_replay_evaluation.py` is implemented and verified on Route A, Route B (`2022-01-01 → 2022-12-31`, 12 monthly signal dates) is executed via:

```bash
# 1. Freeze inputs
RUN_ID=historical_selection_bear2022_20261017_01
mkdir -p outputs/$RUN_ID/frozen_inputs
cp data/ai_watchlist.csv            outputs/$RUN_ID/frozen_inputs/
cp -r data/watchlist_history        outputs/$RUN_ID/frozen_inputs/
cp configs/config.risk_off.json     outputs/$RUN_ID/frozen_inputs/

# 2. Extract 2022 company_quality dataset on Modal (foreground only, MODAL_PROFILE=at2018cow)
MODAL_PROFILE=at2018cow .venv/bin/modal run scripts/modal_baseline_executor.py \
  --run-id $RUN_ID \
  --stage dataset \
  --styles risk_off \
  --start-date 2022-01-01 \
  --end-date 2022-12-31 \
  --dataset-kind company_quality

# 3. Download & repair splits
MODAL_PROFILE=at2018cow .venv/bin/modal volume get ai-scanner-research \
  $RUN_ID/datasets \
  outputs/$RUN_ID/modal_download/datasets

.venv/bin/python scripts/repair_equity_discontinuity.py \
  --input      outputs/$RUN_ID/modal_download/datasets/company_quality_dataset_risk_off.csv \
  --splits-json outputs/$RUN_ID/modal_download/datasets/company_quality_dataset_risk_off.splits.json \
  --output     outputs/$RUN_ID/repaired/company_quality_dataset_risk_off.repaired.csv \
  --audit-out  outputs/$RUN_ID/repaired/company_quality_discontinuities.csv

# 4. Re-run evaluation runner with both Route A (39 dates) and Route B (2022 bear market)
.venv/bin/python scripts/run_extended_replay_evaluation.py \
  --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv \
  --bear-2022-dataset outputs/$RUN_ID/repaired/company_quality_dataset_risk_off.repaired.csv \
  --base-reference-dir outputs/m4_revalidation_current_20261016 \
  --output-dir docs/drawdown_and_bear_replay_20261017
```

---

## 5. Unit Test Requirements (`tests/test_run_extended_replay_evaluation.py`)

Create `tests/test_run_extended_replay_evaluation.py` (`unittest`, zero network calls, zero writes to repo `cache/` or `docs/`) covering:
1. **Segment & forward-regime partitioning**:
   - Synthetic multi-date dataset verifies `FWD_DRAWDOWN_60D` (`qqq_return_60 < 0`), `FWD_BULL_60D` (`qqq_return_60 >= 0`), `FWD_DRAWDOWN_20D`, `TRAILING_DOWN` (`regime == "down"`), and `BEAR_2022` stitching (rejecting overlapping `signal_date` between base and bear/extension datasets).
2. **`FULL` vs `ETF_SLICE` filtering**:
   - Rows with `watchlist_etf_count == 0` (e.g. `SRC:NASDAQ_SCREEN` only) are included in `FULL` and excluded from `ETF_SLICE`, and priorities `1..N` are re-ranked within `ETF_SLICE`.
3. **Cohort economics & `severe_loss_rate_60` math**:
   - Verifies date-equal means, matured-date counts with `NaN` forward labels, `win_rate_vs_qqq_60`, `severe_loss_rate_60` (`fwd_ret_60 <= -0.20`), and `severe_underperform_rate_60` (`excess_60 <= -0.20`).
4. **Reproduction check tolerance**:
   - Verifies reproduction check passes when `v1_current` matches reference values within tolerance and raises/reports clearly on mismatch.
5. **End-to-end CLI into a `tempfile.TemporaryDirectory()`**:
   - Verifies all 5 files + `SHA256SUMS` are written, `contains_absolute_path` is `False` across all outputs, and repo `cache/` is untouched.
