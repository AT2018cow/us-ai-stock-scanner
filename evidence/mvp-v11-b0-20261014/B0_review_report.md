# MVP v1.1 PR-A — B0 canonical parity review report

Date: 2026-10-14
Executor: coding agent (local, read-only; no Modal, no SEC/Alpaca network calls)
Code under test: PR #70 head `cc25e7fb9eee600f9449707f0a5a6d5d18b5f395`
(`feature/mvp-v11-historical-optimizer-pr-a-20261014`; A0 evidence commit `5952743`)
Plan reference: `docs/mvp_v11_historical_selection_optimization_plan_20261013.md`

## 1. Verdict

**B0_FULL_REFERENCE_PARITY_PASS — 0 mismatches** across all 39 dates and all
25,025 signal_date×symbol rows: monthly action counts, Top-5/Top-15 lists, and
row-level quality grade/score/confidence, entry state/score/confidence, action
state, and risk/missing evidence codes all match the frozen original _03
references exactly.

Per the plan and runbook, this **does not authorize candidate return
experiments** (`ready_for_candidate_returns: false` in `baseline_parity.json`).
Remaining mandatory gates: PIT public-filing timing / entity identity audit,
51 audit-only price-event review, and human approval to freeze the
B0/R1–R5/E1–E4 candidates before any outcome viewing.

## 2. Reference provenance (operator-audited, not regenerated)

The B0 run used the **original locally preserved** analysis outputs of the
historical_selection_v1_20261011_03 study. Provenance evidence:

1. The archived `evidence-observations` `SHA256SUMS` does **not** pin
   `action_v1_decisions.csv` (56.9 MB, 25,025 data rows). It was therefore not
   regenerated: it is the original file from the Oct 12 00:26 run (mtime
   consistent with the run), SHA256
   `b5ce1166c38a4094158bd7ca6dd8844b5d210c2aa2a010a7aa38bdc2bac2abbc`, pinned
   via `--expected-decisions-sha256` before the run.
2. Five sibling files in the same local `analysis/` directory match the archived
   `SHA256SUMS` byte-for-byte: `action_v1_compactness.csv` (`91107b89…`),
   `ranking_paired_by_date.csv` (`4b0d25e0…`), `action_v1_cohorts.csv`
   (`7832c8c4…`), `entry_v1_meta.json` (`a1055703…`), `quality_v1_meta.json`
   (`7a5deb5a…`). The directory is internally consistent with the archived
   frozen run.
3. The two aggregate references were exported from the
   `evidence-observations` branch via `git show` into ignored
   `outputs/mvp_v11_b0/refs/` and verified against the runbook's pinned SHAs
   (`4b0d25e0…` ranking, `91107b89…` compactness) before use.

Input integrity: entry v3 CSV SHA `2a4600ee…` re-verified by the script against
`--expected-dataset-sha256`; metadata SHA `1574a855…` (original, as in A0).

## 3. How B0 was run

```bash
git fetch origin evidence-observations
python -m unittest discover -s tests            # 672 tests OK (CI on cc25e7f: pass, run 38445158106)

python scripts/mvp_v11_b0_parity.py \
  --entry-dataset outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv \
  --entry-meta outputs/historical_selection_v1_20261011_03/evidence/entry_quality_dataset_risk_off.meta.json \
  --expected-dataset-sha256 2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e \
  --archived-ranking outputs/mvp_v11_b0/refs/ranking_paired_by_date.csv \
  --archived-compactness outputs/mvp_v11_b0/refs/action_v1_compactness.csv \
  --archived-decisions outputs/historical_selection_v1_20261011_03/analysis/action_v1_decisions.csv \
  --expected-decisions-sha256 b5ce1166c38a4094158bd7ca6dd8844b5d210c2aa2a010a7aa38bdc2bac2abbc \
  --output-dir outputs/mvp_v11_b0/b0_run_01
# → B0_FULL_REFERENCE_PARITY_PASS: 0 mismatches (53 s wall, local CPU only)
```

Future-outcome isolation is enforced by the script: all `fwd_*`, `qqq_return_*`,
`label_end_*`, `mae_*`, `mfe_*`, `equity_discontinuity_*`, `split_label_*`
columns are stripped before `build_stock_decisions` runs. No returns, costs, or
candidate comparisons were computed anywhere in this run.

## 4. Parity coverage detail

- Aggregates (`archived_ranking`): `n_eligible`, `n_non_avoid`, `n_pr_total`,
  `v1_top5`, `v1_top15` — identical for all 39 dates; no missing/extra dates.
- Aggregates (`archived_compactness`): `n_decisions`, `n_non_avoid` and all six
  action counts (PRIORITY_REVIEW / WATCH_PULLBACK / WATCH_BREAKOUT /
  HOLD_MONITOR / AVOID) — identical for all 39 dates.
- Row-level (`archived_decisions`, 25,025 rows): `quality_grade`,
  `quality_score` (tol 1e-6), `quality_confidence`, `entry_state`,
  `entry_score`, `entry_confidence`, `action_state`, plus
  `quality_risk_codes`, `quality_missing_codes`, `entry_risk_codes` — all
  identical; no missing/extra date×symbol rows.
- `baseline_parity_mismatches.csv` contains only the header (empty).
- Per-date table: `baseline_parity_by_date.csv` (39 rows, committed here).

Example date (2026-03-31): 670 eligible, 456 non-AVOID, 15 PRIORITY_REVIEW,
Top-5 `KLAC;POWL;OII;CRUS;DIOD` — matches the archived reference exactly.

## 5. 346 missing-`fundamental_data_asof` rows — conservative handling verified

- All **346/346** rows resolve to `quality_grade = UNRATED`,
  `quality_confidence = 0.0`, and `action_state = AVOID` — missing fundamentals
  never raise a grade (fail-closed confirmed at row level).
- Date-level cross-check: **0** occurrences of an UNRATED symbol inside any
  date's `v1_top5` or `v1_top15` (the one symbol-level overlap in a naive
  check was a symbol UNRATED on one date but rated on a different date).
- The same rows exist identically in the original archived decisions, so
  current v1 reproduces the original conservative behaviour exactly.

## 6. Limitations carried forward (unchanged from A0, still open)

1. Intra-day SEC filing public-time availability is unproven (date-level only).
2. Security/entity identity continuity and the 51 audit-only price-event rows
   (incl. BKNG/KLAC splits fix and WOLF nulling) remain under audit.
3. Universe is `union_superset_approx` (retrospective), not true PIT ETF
   holdings; everything is a monthly historical priority/cap proxy, never a
   Daily/Weekly state-change replay.
4. Reference provenance for `action_v1_decisions.csv` rests on local archival
   consistency (five sibling SHA matches + original run timestamps), since the
   archived SHA256SUMS does not pin that file.
5. Forward labels embed ~30 bps roundtrip cost on both stock and QQQ legs; any
   later comparator must not subtract costs twice and must report net and
   recoverable-gross separately.

## 7. Files in this evidence directory

| File | SHA256 (prefix) | Note |
| --- | --- | --- |
| `baseline_parity.json` | `9cc9e846…` | verdict, SHAs, missing-asof examples |
| `baseline_parity_by_date.csv` | `f24c3ded…` | 39-date aggregate table |
| `baseline_parity_mismatches.csv` | `f17de50b…` | header only (0 mismatches) |
| `SHA256SUMS_refs.txt` | — | refs + original decisions + outputs |

Raw 25k-row CSVs stay in ignored `outputs/` and are **not** committed.

## 8. Next steps (require human approval before proceeding)

1. PIT/entity/audit-only-event review decision by the operator.
2. Human approval to freeze B0/R1–R5/E1–E4 candidate definitions, then unlock
   the paired comparator (development window 2023–2024 only).
