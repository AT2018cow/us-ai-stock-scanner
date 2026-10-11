# Historical Selection v1 — H1–H3 evidence (`historical_selection_v1_20261011_02`)

Retrospective exploratory + temporal diagnostics on 39 monthly signal dates
(2023-01-31 → 2026-03-31), 670 symbols, 25,025 rows × 2 datasets.
**Universe: `union_superset_approx` — not true PIT, not OOS, not a v2 case.**

## Run facts

- Code `73a6fe6c9de8eab10ae5cf35dee1ba7cdc7f5a56` (PR #58, CI unittest success
  run 38136576978); config `configs/config.risk_off.json` (compat loader);
  frozen inputs SHA256-listed in `study_manifest.json`.
- Modal profile **at2018cow**, foreground, single 1–2vCPU/8–16GiB container,
  Quality (~26 min, exit 0) then Entry (~24 min, exit 0). No detach/OOM/retry.
- v1 Quality/Entry/Action/liquidity-gate all frozen. H4 = INCONCLUSIVE.

## File index (this directory)

- `README.md` (this file), `study_manifest.json`, `data_inventory.csv`,
  `coverage_and_integrity.md`, `validation_and_tests.md`,
  `analysis_code_manifest.md` (+ `hist_h1_quality.py`, `hist_h2_entry.py`,
  `hist_h3_action.py` — exact rerun scripts)
- Baselines: `quality_v1_{cohorts,rank_ic,concentration,report}.csv/md`,
  `entry_v1_{cohorts,transitions,persistence,concentration,report}.csv/md`,
  `action_v1_{cohorts,compactness,concentration,transitions,report}.csv/md`
- H1: `quality_grade_year_regime.csv`, `quality_composition.csv`,
  `quality_coverage.csv`, `quality_failure_cases.csv` (17)
- H2: `entry_state_by_year_regime.csv`, `breakout_reason_cases.csv`,
  `breakout_reason_summary.csv`, `entry_ready_deterioration.csv`,
  `entry_failure_cases.csv` (16)
- H3: `ranking_paired_by_date.csv`, `ranking_diff_cases.csv`, `b_ready_cases.csv`
- H4: `liquidity_limitations.md` (INCONCLUSIVE, no extra fetch)
- R: `research_review.md`, `candidate_policy.md`, `reviewer_notes.md`
- `SHA256SUMS` (this dir, generated at submit time; verify with
  `sha256sum -c SHA256SUMS`)

## Headline results (details in research_review.md)

- A/B forward QQQ-excess negative at 60/120d in nearly all year×regime
  cells; C positive — compositional (distressed rebound), rank IC ~0.
- READY rare (12.7%) and weak; BREAKOUT = weak-side reasons (UNVERIFIED 0);
  READY persistence 28%.
- Action-count parity 0 mismatches; cap 15 vs 260–440/month; E-first forward
  excess identical → rejected; B+READY 100% HOLD + negative → not promoted.

## Review pointers

1. `research_review.md` verdict table → 2. `candidate_policy.md` (nothing
   promoted) → 3. `reviewer_notes.md` (audit limits + spot checks).
   Raw datasets stay on the at2018cow Modal Volume + local mirror (too large
   for Git); identified by SHA256 in `study_manifest.json`.
