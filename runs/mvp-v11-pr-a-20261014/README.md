# MVP v1.1 PR-A — archived review evidence (NO-GO / KEEP V1)

Date: 2026-10-14
Final decision: `PR_A_FINAL_DECISION=NO_GO_KEEP_V1` — no X1, no 2025/2026Q1
candidate returns, no PR-B, production v1 unchanged.
Full rationale: `final_decision_20261014.md` (copy of
`docs/mvp_v11_pr_a_final_decision_20261014.md` from PR #70).

## Source

- Code PR: AT2018cow/us-ai-stock-scanner#70
  (`feature/mvp-v11-historical-optimizer-pr-a-20261014`), draft.
- PR evidence commits archived here: A0 `5952743`, B0 `5139412`, risk
  `81a0809`, SEC cases `9bdd046`, SEC verify `9890d66`, preflight `af2f0ee`,
  dev-return `ffb2673` (+2-file completion `4d442da`), final decision
  `fc7a07a5`.
- Executed code HEAD: `9514166907e7f279fd6efd6f77f672badb9bd6f7`
  (CI unittest SUCCESS, run 38547860306; local 717 tests OK).
- Frozen protocol SHA256:
  `0a911c0443a2c744a0e8fbe1da02ad4077c880fd08db76eaf96321d3d146f696`
- Historical corrected v3 SHA256:
  `2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e`
  (25,025 rows / 670 symbols / 39 monthly dates, retrospective
  union_superset_approx; raw CSV NOT archived here).
- Dev-return run: 24 dates 2023–2024 × 10 candidates × 3 horizons × 2 caps
  = 1,440 paired rows; primary 60d Top-15 best E1 +0.213pp, all candidates
  FAIL the +0.5pp gate; status AWAITING_REVIEW → reviewer NO-GO.

## Contents

| Directory | Stage |
| --- | --- |
| `mvp-v11-a0-20261014/` | A0 structural gate PASS (report, structural_gate.json, input SHAs) |
| `mvp-v11-b0-20261014/` | B0 FULL_REFERENCE_PARITY_PASS, 0 mismatches (report, parity JSON/CSVs, ref SHAs) |
| `mvp-v11-risk-20261014/` | 52-event risk triage, all UNREVIEWED (report, summary, queue, SHAs) |
| `mvp-v11-secpit-20261014/` | HEI 4-case + 9-control SEC filing evidence (manifests, summaries, JSONL reviews, reports, SHAs) |
| `mvp-v11-preflight-20261014/` | Outcome-blind 240-row membership preflight (manifest, membership, migrations, SHAs, report) |
| `mvp-v11-dev-return-20261014/` | Authorized dev-return run, 9 files incl. run_manifest, SHA256SUMS, paired/metrics/diffs, risk + recommendation notes |
| `final_decision_20261014.md` | Reviewer NO-GO / KEEP V1 decision |

Per-file SHA256: `SHA256SUMS` in this directory. Subdirectory `SHA256SUMS*`
files record the original run-output hashes.

## Exclusions (kept local, never committed)

25k-row corrected v3 CSVs, 25k-row score sidecar, raw SEC/Alpaca caches,
EdgarTools caches, `.env`/credentials/SEC identity, bulk logs, Modal
checkpoints. No secrets are stored in this archive.
