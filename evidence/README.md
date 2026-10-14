# Evidence Directory Policy (`evidence/`)

## 1. Storage Rule (No Bulk Files on `main`)

Per `docs/research_evidence_workflow.md`, routine and milestone research evidence is archived on the append-only **`evidence-observations`** branch under `runs/`, pinned by commit SHA and `SHA256SUMS`.

To keep `main` lightweight:
- Do **not** commit multi-megabyte `decisions.jsonl` dumps, raw 25k-row historical datasets, or duplicate experiment trees to `main`.
- Only compact baseline references or small audit summaries belong under `evidence/` on `main`.

## 2. Contents on `main`

- `evidence/baselines/` — Historical pre-MVP and post-PR23 baseline summary tables.
- `evidence/archive/` — Compact historical MVP engineering validation manifests and the single preserved 2026-10-09 510-symbol reference snapshot (`evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff/`) used by `scripts/audit_mvp_strategy_snapshot.py`.

## 3. Canonical Archive on `evidence-observations`

Key pinned evidence runs on `origin/evidence-observations`:
- **PR #70 v1.1 Historical Optimizer (`NO-GO / KEEP V1`)**: `runs/mvp-v11-pr-a-20261014/` (commit `68143bff19f60f014e237d1f95eda28adf074b9b`)
- **MVP v1 Beta 62-Symbol Delivery Snapshot (2026-10-12)**: `runs/mvp-beta/mvp_beta_20261012_01/` (commit `a8d5059b760dea7acadc3fc21550d8484734d625`)
- **Action List Usage Acceptance (Frozen Generalized-v0)**: `runs/generalized-v0/acceptance_20261013/` (commit `5862ad8f8884c1ac9399d027cb54a453535a52c3`)
- **P0 Financial Identity Acceptance (`_02`)**: `runs/p0-identity-v1/p0_identity_20261013_02/` (commit `fd8328b389a0efe0c300ce8654dd30448ef8f265`)
- **Generalized-v0 End-to-End Experiment (2026-10-12)**: `runs/generalized-v0/2026-10-12_2d89194_generalized_v0_20261012_01/` (commit `69cc9930938ec3410f4426422a4251ce2771fa72`)
- **Historical Selection v1 Repaired Cohort (`_03`)**: `runs/historical-selection-v1/historical_selection_v1_20261011_03/` (commit `a3bec3d9ae4164f450c94c546d57d36a5d63e063`)
