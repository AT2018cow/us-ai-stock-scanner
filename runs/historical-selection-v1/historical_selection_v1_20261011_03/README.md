# Historical Selection v1 — corporate-action fix (`historical_selection_v1_20261011_03`)

Supersedes the **return tables** of `_02` (evidence `9c22f19`, NOT
overwritten). Same window/universe/discipline: 39 monthly dates
2023-01-31→2026-03-31, 670 symbols, 25,025 rows × 2, union_superset_approx,
retrospective only, no OOS, no v2 case, no production change.

## What changed and why

- Split query now ends 2026-09-25 (covers max label_end 2026-09-22):
  48 symbols w/ events (was 41). BKNG −0.97→sane, KLAC −0.88→+0.2…+1.0.
- Continuity repair: WOLF Sep-2025 backdate nulls 7 spanning labels;
  51 anomalies disclosed audit-only (artifacts/dilution/meme spikes kept).
- 64 grade-drift rows on live-SEC refetch (mostly UNRATED → graded).

## File index (this directory)

- `README.md`, `study_manifest.json`, `data_inventory.csv`,
  `coverage_and_integrity.md`, `validation_and_tests.md`,
  `analysis_code_manifest.md` (+ `hist_h1_quality.py`, `hist_h2_entry.py`,
  `hist_h3_action.py`, `diff_v1_v3_labels.py`)
- Baselines on corrected labels: `quality/entry/action_v1_*`
- H1/H2/H3 re-run: grade/year/regime, composition, coverage (25,025),
  failure cases (17); state/year/regime, breakout reasons+summary,
  deterioration, failure cases (16); ranking pairs/diffs, b_ready
- Fix proof: `label_diff_by_symbol.csv` (57 rows, 10 symbols),
  `label_diff_cohorts.csv`, `entry/company_quality_discontinuities.csv`,
  `entry/company_quality_dataset_risk_off.{meta,splits}.json`
- H4: `liquidity_limitations.md` (INCONCLUSIVE, unchanged)
- R: `research_review.md`, `candidate_policy.md`, `reviewer_notes.md`
- `SHA256SUMS` (verify with `sha256sum -c SHA256SUMS`)

## Review pointers

1. `research_review.md` fix section + verdict table → 2. `label_diff_*`
   (only 10 symbols changed) → 3. `reviewer_notes.md` spot checks.
   Raw 25k-row datasets stay on the at2018cow Volume + local mirror,
   identified by SHA256 in `study_manifest.json`.
