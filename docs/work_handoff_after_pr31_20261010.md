# Work handoff after PR31 — 2026-10-10

This is the current research handoff after PR #31 and its post-merge evidence
closure. The PR30 clean-provenance rerun and corrected PR27 attribution rerun
are complete; do not repeat them unless a new correctness issue is found.

## 1. Repository / PR state

Reviewed closure state:

- PR31 merge: `39e46a519ce98d793fde21c41cbbe20299d9ad63`
- post-merge evidence closure: `fc781d744d76c6c0b916796d89c190839f3dc60b`
- PR31 URL: https://github.com/AT2018cow/us-ai-stock-scanner/pull/31
- final PR head: `02ff54d744323acb7f479fbf6876a823f521438f`
- final PR-head GitHub Actions run #136: success
- no production config change
- no production scanner/backtest change
- no parameter promotion
- no new alpha mechanism

## 2. What PR31 fixes

### 2.1 Remaining channel-column leak

Extracted survivor datasets contain a `channel` column. Production
cross-sections do not contain that column when
`apply_research_assessment` runs.

Passing the extracted channel into assessment can cause an `ai_enabler` row
to self-award `ai_infrastructure_exposure`, adding +0.7 research score and
possibly changing research priority/gate eligibility.

A complete direct-call audit of `scripts/*.py` found only three research
assessment/gate call sites:

- `scripts/low_value_gate_ablation.py` — fixed in `9c478546...`;
- `scripts/sweep_score_weights.py` — fixed in `9c478546...`, regression
  strengthened in PR31;
- `scripts/low_value_gate_attribution.py` — remaining affected call site,
  fixed in PR31.

PR31 adds a dedicated attribution regression test requiring the assessment
callback to receive no dataset `channel` column.

Audit:
`docs/research_channel_column_parity_audit_20261010.md`

### 2.2 PR30 dirty-worktree provenance

The first post-merge PR30 rerun was executed after the channel fix was edited
but before it was committed. Its manifest therefore records HEAD
`20a610b9...` even though the executed working tree contained code later
committed in `9c478546...`.

PR31 prevents recurrence:

- canonical PR30 evaluator requires a readable Git checkout;
- any dirty tracked or untracked non-ignored state hard-fails;
- manifest records commit SHA;
- manifest records Git tree SHA;
- manifest records `git_worktree_clean=true`.

The original dirty-worktree provenance issue is now closed: a clean checkout
at PR31 merge `39e46a5` reproduced the PR30 result and refreshed the
manifest with commit/tree provenance. The PR30 bundle is canonical.

Correction:
`evidence/baselines/post_pr23_005b86c/pr30_single_range_gate/provenance_correction.md`

## 3. Prior evidence: what survives / what is superseded

### Survives this specific channel-column audit

PR27 evidence upstream of research assessment remains usable:

- structural hard first-fail counts;
- direct soft-step failures;
- production composite score before research assessment;
- pre-research rank;
- actual replay risk_on/risk_off selected membership;
- paired replay-selection diagnostics;
- `scripts/ic_analysis.py` IC / decile evidence.

The channel leak does not affect `ic_analysis.py` because that script does
not call research assessment/gating.

### Corrected attribution closure

The affected PR27 attribution was rerun with the fixed tool after PR31 merge.
Only 10 of 412 channel-level cases changed in downstream
research-assessment-related fields; the headline hard-gate counts, direct soft
failures and paired replay-selection diagnostic were unchanged.

The corrected `low_value_gate_cases.csv` is committed. The historical
headline attribution conclusions therefore survive this specific bug.

Pre-`9c478546` low_value weight-sweep eligibility/results remain superseded;
do not use them as canonical evidence for a new weight search.

## 4. PR28 / PR30 conclusions

Do not rewrite the historical PR28 cross-run hard stop:

- PR28 historical replay-vs-extraction ordered parity remains 114/126;
- 10 mismatches were ai_enabler, one ai_peripheral, one core_ai;
- those runs also used different mutable data/cache states.

The channel-column fix proves the **same-state code-path** defect was fixed; it
does not prove every Oct-8-vs-Oct-9 historical difference had the same cause.

PR30 same-state result observed after the fix:

- 168/168 ordered oracle parity;
- single intervention:
  `max_range_position_52w: hard -> soft`;
- pooled 120d B-A about +0.00018;
- positive-date ratio about 38%;
- block-6 90% CI about [-0.0033, +0.0036];
- 2024 slightly negative;
- 2025 about -0.56 percentage points;
- down regime slightly negative;
- retrospective gate failed.

Scientific conclusion remains:

**Do not continue the single range-position gate path and do not promote a
production change.**

The clean-checkout rerun at `39e46a5` reproduced 168/168 parity and the same
five retrospective gate failures. All non-manifest PR30 rerun artifacts were
byte-identical to the earlier bundle; the refreshed manifest records commit
SHA, tree SHA and `git_worktree_clean=true`. PR30 evidence is canonical.

## 5. PR31 evidence closure — completed

Both required closure steps are complete in commit
`fc781d744d76c6c0b916796d89c190839f3dc60b`.

### Clean PR30 rerun

- clean checkout: `39e46a519ce98d793fde21c41cbbe20299d9ad63`
- tree: `5cdb7047a7929e97d262d9003732e147b3ed31d2`
- `git_worktree_clean=true`
- frozen expanded dataset SHA unchanged:
  `bb6edd7a30d8347aeb2020f77255eb1d043d2417aa8892b1a62da8ff0cad0ad6`
- same-state ordered parity: 168/168
- same five retrospective gate failures
- non-manifest artifacts byte-identical to the previous PR30 bundle

### Corrected PR27 attribution

The fixed attribution rerun used the existing frozen datasets/signals. Only
downstream research-assessment fields changed in 10/412 channel-level cases.
Headline hard-gate attribution counts, soft-failure diagnostics and paired
selection result are unchanged.

No new Modal compute, replay or dataset extraction was needed.

## 6. What not to do

Do not:

- start a new alpha ablation;
- modify production risk_off/risk_on thresholds;
- revive the PR28 three-gate B arm;
- tune `max_range_position_52w`;
- launch a broad score-weight sweep;
- launch the 36-candidate tuner;
- run a new historical replay;
- regenerate frozen survivor datasets without a correctness need;
- call retrospective results anchored OOS;
- use `--detach` with Modal.

## 7. Compute rules

User requirement: **never use Modal detach**.

If Modal becomes necessary later:

- foreground `modal run` only;
- explicit `MODAL_PROFILE=infi`;
- no reliance on default profile;
- tuner in-flight candidate cap <= 80.

PR31 correctness closure required no new Modal research compute. For future
research, a `modal volume get` to recover an existing raw artifact is not a
new experiment.

## 8. Research direction after correctness closure

The PR31 correctness closure is complete, so a new mechanism may now be
selected.

The current highest-value candidate direction is **low_value ranking /
research-gate interaction**, not position hard gates:

- momentum ranking has materially stronger/stabler IC;
- low_value pooled IC can be positive while decile monotonicity is weak;
- low_value monotonicity changes by year/regime;
- PR30 failed to validate the narrow position-gate mechanism.

Use one pre-registered mechanism at a time. Do not begin with a broad
parameter search.

## 9. New-conversation entry point

The next conversation can move directly to selecting and pre-registering the
next narrow alpha mechanism. Start from the corrected/canonical evidence above;
do not rerun PR30 or PR27 attribution again unless a new correctness issue is
found. Prefer low_value ranking / research-gate interaction diagnostics over
position-gate work, broad tuning or a new full replay.
