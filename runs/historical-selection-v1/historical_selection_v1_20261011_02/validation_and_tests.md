# Validation and tests — RUN_ID historical_selection_v1_20261011_02

## Code identity

- Execution code SHA: `73a6fe6c9de8eab10ae5cf35dee1ba7cdc7f5a56`
  (PR #58 branch `research/historical-selection-validation-protocol-20261011`;
  base main `2d89194` + protocol + `--dataset-kind` extractor + at2018cow guard)
- Exact-head CI: GitHub Actions `unittest` **success**
  (run 38136576978, on the executed commit)
- Local: `python -m unittest discover -s tests` → **530 tests OK**
- Frozen inputs (`<RUN_ID>/frozen_inputs/`, `git_status.txt` empty at freeze):
  - `config.risk_off.json` SHA256 `7a967e42…c43204424`
  - `ai_watchlist.csv` SHA256 `230f32d6…d574f94478b5`
  - 38 `watchlist_history` snapshots, individually SHA256-listed
- v1 policies frozen: Quality/Entry/Action mapping, QQQ regime, IEX feed,
  $2m gate, 62-name cohort — all unchanged (verified: no src/ edits in run).

## Evaluator runs (all exit 0, local, read-only)

| evaluator | input | output prefix |
|---|---|---|
| evaluate_company_quality.py | company_quality CSV (25,025 rows) | analysis/quality_v1 |
| evaluate_entry_quality.py | entry_quality CSV (25,025 rows) | analysis/entry_v1 |
| evaluate_action_states.py --attention-cap 15 | entry_quality CSV | analysis/action_v1 |

H1–H3 research scripts (untracked `research/`, SHA256 in
analysis_code_manifest.md): hist_h1_quality / hist_h2_entry / hist_h3_action,
all exit 0. Self-checks passed: breakout UNVERIFIED=0/4969; action-count
parity vs compactness 0 mismatches/39 dates; no null scores/confidences.

## Modal execution record (profile at2018cow, foreground, no detach)

| stage | run URL suffix | wall time | exit |
|---|---|---|---|
| company_quality | ap-0PFTu7NFZjMatkF16EWhBi | ~26 min | 0 |
| entry_quality | ap-qHZaybcrYmjw6K45ZzPQrv | ~24 min | 0 |

Container: 1–2 vCPU / 8–16 GiB, single heavy container at a time, sequential
Quality→Entry. No OOM, no retry, no concurrent heavy jobs. Cache volume
`ai-scanner-cache` (at2018cow, pre-existing); research volume auto-created.
Secrets: ephemeral from local `.env` allowlist (names only in logs).
Exact billing: Modal dashboard (time-metered, sub-hour single container).
