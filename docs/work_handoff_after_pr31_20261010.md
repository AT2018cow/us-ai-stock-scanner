# Work handoff after PR31 — 2026-10-10

This handoff becomes the current research handoff once PR #31 is merged.
Do not start a new alpha experiment before completing the small evidence
revalidation steps below.

## 1. Repository / PR state

Base main when PR31 was opened:

- `81345e527514b1af8a79c60f177d92a2beeeb7c6`

PR31:

- URL: https://github.com/AT2018cow/us-ai-stock-scanner/pull/31
- title: `Research: close PR30 parity and evidence provenance gaps`
- purpose: close research-tooling correctness/provenance only
- no production config change
- no production scanner/backtest change
- no parameter promotion
- no new alpha mechanism

PR31 full repository CI passed before this handoff document was added. After
this document/AGENTS update, require the final PR head CI to pass again before
merge.

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

The existing PR30 bundle is retained as historical evidence but marked
non-canonical until one clean-checkout rerun reproduces it.

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

### Superseded until corrected rerun

Original PR27 attribution fields downstream of research assessment are not
canonical:

- `risk_off_research_priority`;
- `risk_off_research_score`;
- `risk_off_research_risks`;
- research-gate exclusion counts;
- post-research rank;
- downstream group-cap / below-Top-N classifications when gate membership
  changed.

Pre-`9c478546` low_value weight-sweep eligibility/results are also
superseded.

The PR27 decision note has been annotated rather than deleting historical
evidence.

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

However, the committed PR30 result bundle needs the clean provenance rerun
below before being called canonical evidence.

## 5. Immediate post-merge closure: do this before new research

### Step A — clean PR30 local rerun

No new Modal compute is required.

Start from a clean checkout after PR31 merge:

```bash
git status --short
python -m unittest discover -s tests
```

`git status --short` must be empty before the evaluator starts.

Use the existing frozen PR28 expanded dataset:

```text
SHA256 bb6edd7a30d8347aeb2020f77255eb1d043d2417aa8892b1a62da8ff0cad0ad6
23,774 rows / 42 dates
```

If still local:

```bash
RUN_ID=post_pr23_baseline_202610
EXP="outputs/$RUN_ID"
DATASET="$EXP/pr28_position_ablation/expanded_dataset/weight_dataset_risk_off.csv"

python scripts/low_value_single_gate_ablation.py \
  --dataset "$DATASET" \
  --scan-config configs/config.risk_off.json \
  --output-prefix "$EXP/pr31_pr30_clean_rerun/single_range_gate"
```

If the raw file is absent, recover the existing artifact only:

```bash
MODAL_PROFILE=infi .venv/bin/python -m modal volume get \
  --force \
  ai-scanner-research \
  "/post_pr28_position_ablation_202610/datasets" \
  "outputs/post_pr23_baseline_202610/pr31_pr30_clean_rerun/recovered_dataset"
```

Do not run a new extraction/replay.

Required clean-rerun checks:

- dataset SHA exactly matches the frozen SHA above;
- config content guard passes;
- manifest `git_worktree_clean=true`;
- manifest `code_sha` equals the clean checkout commit;
- manifest `code_tree_sha` is present;
- same-state ordered parity is 168/168;
- retrospective gate remains false;
- substantive 120d result remains materially identical to the recorded
  negative PR30 result.

If any of those fail, stop and debug before interpreting alpha results.

Commit only compact clean-rerun evidence; keep the raw dataset off Git.

### Step B — corrected PR27 attribution rerun

After Step A passes, rerun only the affected attribution analysis using the
existing frozen survivor datasets and committed replay signal files.

Committed signal inputs:

- `evidence/baselines/post_pr23_005b86c/post_pr23_baseline_202610_risk_on_events_signals.csv`
- `evidence/baselines/post_pr23_005b86c/post_pr23_baseline_202610_risk_off_events_signals.csv`

Canonical survivor dataset identities:

- risk_off: 39,309 rows / 42 dates, SHA begins `4a0203d9`
- corrected risk_on: 30,355 rows / 42 dates,
  SHA `295e3de8d0e48b9f9fac0a182c2354e447a0b97c68203ddc3b65d840305a282d`

The raw survivor CSVs remain off Git. Use the existing local/Volume copies; do
not regenerate them unless a correctness proof shows they are unavailable or
insufficient.

Example once the raw paths are resolved:

```bash
python scripts/low_value_gate_attribution.py \
  --risk-on-dataset <corrected-risk-on-csv> \
  --risk-off-dataset <canonical-risk-off-csv> \
  --risk-on-signals evidence/baselines/post_pr23_005b86c/post_pr23_baseline_202610_risk_on_events_signals.csv \
  --risk-off-signals evidence/baselines/post_pr23_005b86c/post_pr23_baseline_202610_risk_off_events_signals.csv \
  --risk-on-config configs/config.risk_on.json \
  --risk-off-config configs/config.risk_off.json \
  --years 2023,2025 \
  --horizon 120 \
  --top-n 10 \
  --output-prefix outputs/post_pr23_baseline_202610/pr31_corrected_low_value_attribution
```

Compare corrected downstream attribution fields with the original PR27
artifacts and write a compact correction note. Do not silently overwrite old
historical files.

## 6. What not to do

Until Steps A and B are closed, do not:

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

For the immediate PR31 closure, no Modal research compute should be needed.
A `modal volume get` to recover an existing raw artifact is acceptable and
is not a new experiment.

## 8. Research direction after correctness closure

Only after the clean PR30 rerun and corrected attribution rerun are recorded
should a new mechanism be selected.

The current highest-value candidate direction is **low_value ranking /
research-gate interaction**, not position hard gates:

- momentum ranking has materially stronger/stabler IC;
- low_value pooled IC can be positive while decile monotonicity is weak;
- low_value monotonicity changes by year/regime;
- PR30 failed to validate the narrow position-gate mechanism.

Use one pre-registered mechanism at a time. Do not begin with a broad
parameter search.

## 9. New-conversation entry point

After PR31 merges, the next conversation should first verify the merge and
then complete Steps A and B above before proposing new alpha work.
