# PR-A — Frozen development-return executor (code review, not yet authorized)

**Status:** Code and synthetic tests delivered. Owner has NOT authorized
running real v3 candidate returns. No data experiment was executed by the
author. Do not merge PR #70 on the existence of the CLI or a green CI alone.
The 9 previously frozen SEC controls and outcome-blind label/event coverage
still require project-owner review. Original HEI historical score-source
semantics remain inconsistent. `ready_for_candidate_returns=false`
until explicit approval **in the PR conversation**.

## Fixed scope — impossible to use this entrypoint for temporal selection

- Exactly 24 signal dates in **2023–2024**, ten IDs B0/R1–R5/E1–E4.
  No X1 or 2025/2026Q1 return/evaluation output.
- 20/60/120 trading-day v3 frozen **net** forward returns, Top-5/Top-15.
  Stock and QQQ labels were already net of assumed 15bps on entry,
  15bps on exit; no extra cost is charged. Not trade execution/P&L.
- Primary unit: each valid date's **Top-15 60d equally weighted
  stock net return minus QQQ net return**. Candidate minus B0
  paired on the same date; then **equal weight across dates**. +0.5
  percentage points = **0.005 decimal** is the predeclared economic
  reference, not a p-value.
- If either selected list has one missing stock/QQQ label or missing
  label_end_h, the **entire same date×horizon×Top-k pair is invalid**.
  No replacement/fill, no use of separate B0 versus candidate dates.
- Primary retains all originally valid v3 labels (except original WOLF
  nulling) and no new post-hoc stock deletions.
- Two **separate, prespecified sensitivity views**: (a) retrospective
  52-event detection-interval overlap with selected 20/60/120 holding
  period; (b) date×symbol as-of Quality source uncertainty (HEI all
  dates, missing fundamental as-of, severe source-audit shares on event
  detection date). Only drop the **entire date pair** if EITHER chosen
  list is flagged. Never change historical decision membership using a
  future event/suspicion flag. Report paired dates lost under each view.
- Rebuild decisions with canonical builder plus frozen offline E1–E4
  gate overrides; assert **every date×candidate Top-5/15 and migration
  count** agrees with the SHA-pinned already approved membership
  preflight `bc9130edcb62c362d893166d69b7c363087f254ed91bca4127322faac93f6f60`.
- The output includes 2023/2024 separate diagnostics, worst dates,
  Top-15 replacement contributions, model state changes and a
  conservative review report **without automatic GO**.
  No automatic candidate selection, no numerical HEI repair or
  stock-as-of reconstruction, no statistical independent-25k claims.

## Prerequisites — all are blocking

1. Reviewer accepts the exact code SHA, CI and synthetic tests.
2. Frozen nine-control SEC/PIT sample outcome submitted and reviewed.
   Missing historical SEC accession/CIK remains UNVERIFIED; any winner
   materially reliant on uncertain data must be INCONCLUSIVE/KEEP V1.
3. Previously generated event interval flags can be regenerated from
   frozen input + SHA inside the CLI; the new `build_event_interval_flags`
   code and `score_source_flags` reviewed *before* returns.
4. Owner explicitly authorizes exactly one development outcome run,
   with the **exact PR HEAD SHA**, **exact protocol SHA** and
   `I_APPROVE_FROZEN_2023_2024_DEV_ONLY` authorization.
   Approval is not implied by a green CI.
5. Worktree clean or protected, GitHub Actions green at that same HEAD,
   no SEC/Alpaca network access, no Modal, no secrets.

The frozen protocol is `configs/mvp_v11_dev_return_protocol.json`.
The numeric/frozen candidate registry is
`configs/mvp_v11_candidate_registry.json`. Each runner checks their
hashes and refuses mismatches, wrong HEAD or existing output directories.

## Local command TEMPLATE — DO NOT EXECUTE BEFORE OWNER APPROVAL

When all prerequisites are satisfied, calculate the actual checkout HEAD
with `git rev-parse HEAD`, protocol fingerprint with
`sha256sum configs/mvp_v11_dev_return_protocol.json`, and verify them
against the owner's approval comment. On a fully checked-out PR-A branch,
after running all project tests:

~~~bash
python scripts/mvp_v11_dev_return_experiment.py \
  --authorize-2023-2024-dev-returns I_APPROVE_FROZEN_2023_2024_DEV_ONLY \
  --expected-code-sha APPROVED_EXACT_PR_HEAD_SHA \
  --expected-protocol-sha256 APPROVED_PROTOCOL_SHA256 \
  --entry-dataset outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv \
  --entry-meta outputs/historical_selection_v1_20261011_03/evidence/entry_quality_dataset_risk_off.meta.json \
  --event-audit outputs/historical_selection_v1_20261011_03/repaired/entry_quality_discontinuities.csv \
  --event-review outputs/mvp_v11_risk/risk_run_01/event_review_queue.csv \
  --frozen-membership outputs/mvp_v11_preflight/membership_run_01/membership_by_date.csv \
  --output-dir outputs/mvp_v11_dev_return/authorized_run_01
~~~

**Do not use this command before review authorization.** Paths are
grounded by prior A0/B0/preflight runs and must point to the actual
verified original local files (do not rename source inputs). Test
execution locally first only with artificial rows; the runner is not
a background/paid compute job.

Outputs inside the new ignored output directory:
- `paired_by_date.csv` — **24×10×3×2 = 1,440** complete date-pair
  diagnostics; explicit label, score and event masks and ticker sets.
- `top15_diff_cases.csv` — actual ticker swaps and their **60d
  net QQQ-excess contribution** to the delta (where valid).
- `entry_state_migrations.csv` — E1–E4 state changes.
- `metrics_by_period.csv` — full 2023–2024 and 2023/2024 annual slices,
  all 20/60/120 × Top5/15 views; primary one is 60d Top15 full dev.
- `risk_and_missingness.md` — scope, model/data source limitations,
  sensitivity mask sample attrition and per-regime date distribution.
- `decision_recommendation.md` — **AWAITING_REVIEW**, no automatic GO,
  economic reference and cautious primary table.
- `dataset_inventory.csv`, `run_manifest.json`, `SHA256SUMS`.

Review the exact 24-date date-equal paired delta, Top-15 replacements,
20d/120d and Top-5 diagnostics, 2023 vs 2024 consistency, worst 3 dates,
HEI/52-event sensitivity attrition, extreme contributors and no-effect
cases. A mean >+0.5pp without robustness is insufficient for promotion.
The number of dated rows is the sample size, **not 25k independent
stock signals**. If all R/E fail, STOP, KEEP V1, do not open PR-B.

Only after the development winner is recorded and its R/E credentials
locked may a separate, reviewed **2025/2026Q1 temporal-diagnostic
implementation and run** be proposed. Those periods are not fresh OOS.


## Nine frozen controls reviewed — limited risk-gate disposition (2026-10-14)

Evidence commit `7834c7b365246f0bd4db832533cea8c85f22975d`,
`evidence/mvp-v11-secpit-20261014/`. Both HEI and the nine
pre-registered SEC controls are now complete. All 9/9 control filing
headers precede the corresponding signal dates; 7/9 source facts match
cover DEI outstanding shares, while VSH uses a filing's period-weighted
basic-share count and GOOGL uses a multi-class share aggregate with
time-offset differences. **None of the 13 observations proves the
original extraction's historical ticker→CIK/accession binding**;
`UNVERIFIED` is retained. There was no second HEI-like ~2.5x alternation
in these nine frozen controls, but sample size is far too small to
certify the 25k-row universe.

Before any returns, the conservative `score_source_flags` sidecar now
includes two **date-specific, outcome-blind** control warnings:
`(2023-01-31,VSH)` for weighted-average rather than point-in-time
shares, and `(2024-12-31,GOOGL)` for multi-class price/quantity basis.
They are added to HEI-all-dates, the original missing as-of and the
unresolved severe share-event detection-date markers. They NEVER alter
v3, B0, candidate lists, forward labels, or the original 52-event
audit queue. Only the sensitivity date-pair validity may change.
The previously filed 240-row membership and 24-date Top-k snapshots
remain pinned and valid, as no historical selection input changed.

This **revised protocol is still awaiting project-owner approval**.
The owner must read this updated runbook and check the exact latest
GitHub CI before supplying:
- the exact new 40-character PR-A HEAD SHA;
- the SHA256 of the current on-disk
  `configs/mvp_v11_dev_return_protocol.json` (the previous
  `ce5234ec...` fingerprint is obsolete after the sidecar update);
- explicit approval of exactly one offline 2023–2024 development run.

Reviewer's limited conclusion: data-quality *inventory and pre-return
uncertainty rule* are acceptable for a **descriptive development
experiment**, not for declaring actual historical issuer/PIT correctness
or production promotion. Any candidate whose apparent improvement
depends materially on unverified source facts/interval events must be
`INCONCLUSIVE/KEEP_V1`. Separate temporal 2025/2026 diagnostic results
remain sealed until the development recommendation has been locked.

**Do not reuse the old `b05c6120` approval SHA or the original protocol
SHA.** Do not run real candidate returns merely because the code and
nine SEC checks have passed. The project owner must explicitly authorize
the new exact SHA pair.
