# Validation and tests — RUN_ID historical_selection_v1_20261011_03

## Code identity

- Execution code SHA: `af70b5ea06209271bf8e815a9bf3a8bc911334c6`
  (PR #58 branch; base 2d89194 + protocol + dataset-kind + at2018cow guard
  + corporate-action label-integrity fix)
- Exact-head CI: GitHub Actions `unittest` **success** (run 38151804814)
- Local: `python -m unittest discover -s tests` → **545 tests OK**
  (530 prior + 15 new `test_corporate_action_label_integrity`)
- Frozen inputs: config `7a967e42…`, watchlist `230f32d6…`, 38 snapshots
  SHA256-listed; `git_status.txt` holds only `?? research/` (untracked
  analysis scripts, not shipped to Modal, not read by the extractor).
- v1 policies frozen (no src/ policy edits; scanner/decision untouched).

## Offline runs (all exit 0)

- repair script on both datasets (52 audit records each; 5 flagged rows).
- 3 evaluators on v2 (intermediate, local `analysis_v2/`) and on v3
  (`analysis/`): quality/entry/action baselines re-issued.
- H1/H2/H3 research scripts re-run on v3 (UNVERIFIED=0, parity 0 mismatch).
- `diff_v1_v3_labels.py`: 57-row diff + cohort pivot (`label_diff_*.csv`).

## Modal execution (profile at2018cow, foreground, sequential, no detach)

| stage | run | wall | exit |
|---|---|---|---|
| company_quality | ap-LK2D3nAcp9a5hOJIV2wZMg | ~26 min | 0 |
| entry_quality | ap-umoNkcJo6ZSjmpaN4pGj4O | ~21 min | 0 |

1–2 vCPU / 8–16 GiB single container; no OOM/retry; warm cache reuse
(bars + filings; only split fetch + label math redone). Billing: dashboard.
