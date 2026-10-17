# Agent Specification: Bull-Market Offense & Slow-Growth De-Crowding Validation (`C1` / `C2` / `C3`)

- **Date**: 2026-10-17
- **Baseline**: `main` @ `b71d9de` (PR #98)
- **Frozen 39-date dataset (`2023-01..2026-03`)**: `outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv` (read-only)
- **Frozen 2022 bear dataset (`2022-01..2022-12`)**: `outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv` (read-only)
- **Target Execution Agent**: DeepSeek (offline implementation + unit tests + validation run only; no Git state mutations, no network calls, no production code changes under `src/`)
- **Reviewer / Integrator**: Architect Agent

---

## 1. Architectural Hypothesis & Motivation

1. **Why current `v2 TOP15` (`PRIORITY_REVIEW`) excels at bear/drawdown defense but lags in bull markets**:
   - In `Company Quality v2`, 80% of the score weight comes from profitability/cash conversion (`30%`), balance sheet (`20%`), valuation percentile (`20%`), and dilution (`10%`), while growth stability is only `20%`. Combined with `ENTRY_READY`'s tight `0.98 <= price_to_sma50 <= 1.08` band, low-volatility slow-growth cash cows (`revenue_yoy < 10%`, e.g. `AMCR`, `FAST`, `VLTO`, `JKHY`, `DBX`) heavily populate the top of `PRIORITY_REVIEW`.
   - Meanwhile, genuine **High-Growth Cash-Flow Compounders** (`Quality Grade A/B`, `revenue_yoy >= 15%`, `ocf_to_net_income >= 0.80`, no `nonoperating_gain_inflation`, `price_to_sma200 >= 1.00`, `relative_strength_60d_qqq >= 0.0`) frequently sit in `WATCH_PULLBACK` during bull trends (e.g. `PLTR`, `TEAM`, `VEEV`, `NOW`, `AMD`, `MSFT`) and are excluded from `TOP15`.
2. **Why Stock-Level Compounder Offense is superior to a Trailing Macro Regime Switch**:
   - Trailing 60d market indicators inevitably classify pre-drawdown market peaks (`2023-06/07`, `2024-11`, `2025-10`) as `UPTREND`.
   - By contrast, requiring **both** verified fundamental cash-flow growth (`Quality A/B + Rev YoY >= 15% + OCF/NI >= 0.80`) **and** healthy long-term trend/relative strength (`SMA200 >= 1.00 + RS60 >= 0.0`) provides built-in quality protection during drawdowns/bear markets without relying on macro market-timing switches.

---

## 2. Pre-Registered Candidates (Frozen Before Validation Run)

All candidates reuse the exact canonical `v2` decisions (`build_stock_decisions(..., policy_version="v2")`) per `signal_date` and scope (`ETF_SLICE` primary: `watchlist_etf_count >= 1`; `FULL` secondary):

### Baseline: `v2_baseline`
- Current production `v2` ordering (`decision.priority <= 15` for `TOP15`, `decision.priority <= 5` for `TOP5`, `action_state == "PRIORITY_REVIEW"` for `PRIORITY_REVIEW`).

### Candidate 1: `C1_de_crowd_slow_growth` (Slow-Growth De-Crowding Within `PRIORITY_REVIEW`)
- Keeps `Quality v2`, `Entry v2`, and `Action State v2` membership 100% unchanged.
- Re-ranks within each `action_state` bucket by modifying the effective priority score:
  - Base priority score = `0.60 * quality_score + 0.40 * entry_score` minus existing `v2` penalties (`0.06` for `pre_earnings_window_risk`, `0.06` for `nonoperating_gain_inflation`);
  - **Slow-growth deduction (`-0.08`)**: if `revenue_yoy is None` or `revenue_yoy < 0.08` (`< 8%` YoY revenue growth), subtract `0.08` from the priority score;
  - **Verified growth-compounder bonus (`+0.05`)**: if `revenue_yoy >= 0.15` and `ocf_to_net_income >= 0.80` and `"nonoperating_gain_inflation"` not in `quality.risks`, add `+0.05` to the priority score.
- Ties broken by `(-quality_score, -entry_score, symbol)`.

### Candidate 2: `C2_offense_compounder_track` (Pure Growth-Compounder Offense Track)
- Defines a stock as eligible for the **Growth-Compounder Offense Track** (`is_offense_compounder == True`) iff all 6 conditions hold:
  1. `quality.grade.value in {"A", "B"}` and `quality.score >= 0.68`;
  2. `"nonoperating_gain_inflation"` not in `{r.code for r in quality.risks}`;
  3. `revenue_yoy is not None and revenue_yoy >= 0.15`;
  4. `ocf_to_net_income is not None and ocf_to_net_income >= 0.80`;
  5. `entry.state.value in {"ENTRY_READY", "WATCH_PULLBACK"}` and `price_to_sma200 is not None and price_to_sma200 >= 1.00` (and `price_to_sma200 <= 1.60` hard sanity cap to avoid extreme parabolic blowups);
  6. `relative_strength_60d_qqq is not None and relative_strength_60d_qqq >= 0.0`.
- Ranking key among eligible offense compounders:
  - `offense_score = quality.score + 0.50 * min(max(revenue_yoy, 0.0), 1.0) + 0.50 * min(max(relative_strength_60d_qqq, 0.0), 1.0)` ( minus `0.06` if `pre_earnings_window_risk` in `quality.risks`).
  - If fewer than 15 names qualify on a given date (e.g. deep bear market), fill remaining slots after all qualifying compounders using `C1_de_crowd_slow_growth` order.

### Candidate 3: `C3_barbell_top15` (8 Core Defensive Ready + 7 Growth-Compounder Offense Leaders)
- Constructs a 15-name Barbell Action List on each date:
  - **Slots 1–8 (Defensive Ready Anchor)**: Top 8 names from `C1_de_crowd_slow_growth` (which are `PRIORITY_REVIEW` / `ENTRY_READY` names with slow-growth de-crowding applied);
  - **Slots 9–15 (Offense Growth Leaders)**: Top 7 names from `C2_offense_compounder_track` (`is_offense_compounder == True`) that are not already in Slots 1–8 (if fewer than 7 qualify on a date, backfill remaining slots up to 15 from `C1_de_crowd_slow_growth`).
- For `TOP5` evaluation on `C3_barbell_top15`: take Top 3 from `C1_de_crowd_slow_growth` + Top 2 non-overlapping from `C2_offense_compounder_track`.

---

## 3. Four Mandatory Validation Gates (`G1`–`G4`)

Implement `scripts/validate_growth_compounder_offense.py` (offline, deterministic, reusing dataset/segment helpers from `scripts/run_extended_replay_evaluation.py`) to evaluate `v2_baseline`, `C1_de_crowd_slow_growth`, `C2_offense_compounder_track`, and `C3_barbell_top15` across all 4 gates:

1. **Gate 1 — Paired Economics across `DEV_2023_2024` (24 dates), `POST_2025_2026Q1` (15 dates), and `BASE_ALL_39` (39 dates)**:
   - For `TOP5` and `TOP15` across horizons `20d`, `60d`, `120d` (both `ETF_SLICE` primary and `FULL` secondary):
   - Compute date-equal `mean_excess`, `median_excess`, `win_rate_vs_qqq`, `severe_loss_rate_60` (`fwd_ret_60 <= -0.20`), and paired deltas (`candidate - v2_baseline`) with 95% Bootstrap CI, `loo_min`, and `positive_date_share`.
2. **Gate 2 — Bull-Market Offense vs Drawdown & 2022 Bear Defense**:
   - Evaluate across:
     - `FWD_BULL_60D` (`n=31` bull dates in 2023–2025)
     - `FWD_DRAWDOWN_60D` (`n=8` pre-drop peak dates in 2023–2025)
     - `BEAR_2022` (`n=12` bear-market dates in 2022)
     - `BEAR_2022_FWD_DRAWDOWN_60D` (`n=9` crash dates in 2022)
     - `ALL_EQ(4)` (4 non-overlapping drawdown episodes: `EP1_2023Q3`, `EP2_2024Q4_2025Q1`, `EP3_2025Q4`, `EP0_BEAR_2022`).
   - Check whether `C1`, `C2`, `C3` improve `FWD_BULL_60D` while keeping `FWD_DRAWDOWN_60D`, `BEAR_2022`, and `ALL_EQ(4)` positive vs QQQ and keeping `severe_loss_rate_60` below the universe rate.
3. **Gate 3 — Anti-Lottery / Top-5 Contributor Exclusion & Median Robustness**:
   - For each candidate's `TOP15` (`ETF_SLICE`), identify the 5 symbols with the largest cumulative positive 60d excess contribution across the 51 dates, exclude those 5 symbols from the dataset, and re-run the evaluation (`EX_TOP5_CONTRIBUTORS`) to verify whether the improvement over `v2_baseline` survives without the top 5 winners.
   - Report slow-growth crowding statistics: average share of `TOP15` with `revenue_yoy < 0.10` vs `revenue_yoy >= 0.15`, and median `revenue_yoy` of `TOP15` under `v2_baseline`, `C1`, `C2`, and `C3`.
4. **Gate 4 — `2026-10-15` Live Snapshot Top-15 Comparison (`snap_20261015_top15_comparison.csv`)**:
   - Load `outputs/decision_previews/2026-10-15/risk_off/decisions_recomputed_v2.jsonl` (enriching from read-only local `cache/parsed_fund_*.json` when a metric is in a neutral band) and list the side-by-side Top 15 symbols, grades, entry states, `revenue_yoy`, `ocf_to_net_income`, `price_to_sma200`, and `relative_strength_60d_qqq` for `v2_baseline`, `C1`, `C2`, and `C3`.

---

## 4. Outputs & Unit Tests

### 4.1 Output Directory (`docs/growth_compounder_offense_validation_20261017/`)
Emit 5 files + `SHA256SUMS` (total `< 160 KB`, zero absolute paths):
- `candidate_cohort_economics.csv`
- `paired_deltas_vs_v2.csv`
- `robustness_ex_top5_and_episodes.csv`
- `snap_20261015_top15_comparison.csv`
- `report.md` (with full provenance, CLI reproduction command, input dataset SHA256s, Gate 1–4 tables, slow-growth crowding comparison, and explicit recommendation)
- `SHA256SUMS`

### 4.2 Unit Tests (`tests/test_validate_growth_compounder_offense.py`)
Create `tests/test_validate_growth_compounder_offense.py` (`unittest`, synthetic fixtures, zero network calls, zero writes to repo `cache/`) covering:
1. `C1` slow-growth deduction (`revenue_yoy < 0.08`) and compounder bonus (`revenue_yoy >= 0.15` & `ocf_to_net_income >= 0.80`, blocked when `nonoperating_gain_inflation` is present);
2. `C2` 6-condition offense compounder gate (including `WATCH_PULLBACK` eligibility, `price_to_sma200 <= 1.60` cap, and fallback backfill when fewer than 15 names qualify);
3. `C3` 8+7 Barbell construction and deduplication (no duplicate symbols in Top 15);
4. Top-5 contributor identification and exclusion math;
5. End-to-end CLI execution into a temporary directory with `contains_absolute_path == False` check.
