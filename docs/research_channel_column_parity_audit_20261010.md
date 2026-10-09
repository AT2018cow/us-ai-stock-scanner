# Research channel-column parity audit — 2026-10-10

## Scope

This audit closes the research-tooling defect discovered after PR30: extracted
survivor datasets carry a `channel` column, but production cross-sections do
not carry that column when `apply_research_assessment` runs.

Because `build_research_assessment` treats an `ai_enabler` channel string as
evidence for `ai_infrastructure_exposure`, passing the extracted dataset
label into assessment can add +0.7 research score and change priority/gate
eligibility relative to production.

This is a research-only parity defect. Production scanner/backtest semantics
are unchanged.

## Direct-call audit

All Python files under `scripts/` were checked for direct calls to
`apply_research_assessment` or `apply_low_value_research_gate`.

Only three scripts call them:

1. `scripts/low_value_gate_ablation.py`
   - fixed in `9c478546...`;
   - drops extracted `channel` before assessment;
   - regression:
     `test_rank_channel_ignores_dataset_channel_column`.

2. `scripts/sweep_score_weights.py`
   - fixed in `9c478546...`;
   - drops extracted `channel` before low_value research-gate assessment;
   - PR31 strengthens the parity test to assert that the assessment callback
     cannot see a `channel` column.

3. `scripts/low_value_gate_attribution.py`
   - affected before PR31;
   - PR31 drops extracted `channel` before assessment;
   - PR31 adds a dedicated regression test.

No other `scripts/*.py` file directly calls these assessment/gate functions.
In particular, `scripts/ic_analysis.py` does not use research assessment or
the low_value research gate.

## Effect on prior evidence

### Unaffected by this specific defect

The following PR27 evidence is upstream of research assessment or comes from
actual replay selections and therefore survives this channel-column audit:

- structural hard first-fail diagnosis;
- soft-step pass/fail diagnosis calculated directly from filter functions;
- production composite score before research assessment;
- pre-research rank;
- replay-derived risk_on-only / risk_off-only selection membership;
- paired selection-only date diagnostics built from actual replay signals;
- `ic_analysis.py` production-score IC/decile evidence.

This does not upgrade retrospective evidence to OOS evidence.

### Affected / superseded until recomputed

Original PR27 low_value attribution fields downstream of
`apply_research_assessment` are not canonical:

- `risk_off_research_priority`;
- `risk_off_research_score`;
- `risk_off_research_risks`;
- `research_gate` exclusion counts;
- post-research rank;
- downstream group-cap / below-Top-N classifications when research-gate
  membership changed.

Pre-`9c478546` low_value weight-sweep eligibility/results are also
superseded because the research gate could see the extracted channel label.

Do not delete the historical files; retain them as an audit trail and label
corrected reruns separately.

## PR28 / PR30 interpretation

The channel-column defect explains the pre-fix **same-state code-path**
mismatches: after removing the leaked column, the PR30 oracle comparison is
168/168 exact.

It does not retroactively make the old Oct-8 replay vs Oct-9 extraction PR28
cross-run comparison pass. That historical artifact remains 114/126 and spans
different mutable data/cache states.

The PR30 single-gate negative result was generated after the channel fix but
from a dirty working tree whose HEAD still pointed to the merge commit. PR31
therefore adds a clean-worktree hard guard to the evaluator. The existing
result must be clean-rerun once before its provenance is canonical.

## Required closure before new alpha work

1. Merge the PR31 research-tooling fixes.
2. On a clean committed checkout, rerun only the fixed PR30 local evaluator
   against the existing frozen PR28 expanded dataset.
3. Require 168/168 same-state parity and the same substantive negative
   single-gate result.
4. Recompute only the affected PR27 attribution outputs from existing frozen
   datasets/signals.
5. Record a corrected attribution decision note.
6. Only then select a new alpha mechanism.

No new historical replay, dataset extraction, Modal compute or broad tuner is
required for this closure.
