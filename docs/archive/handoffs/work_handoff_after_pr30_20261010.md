# Work handoff after PR30 — 2026-10-10

This is the current handoff for the post-PR23 stock-selection research phase.
Read this before starting any new alpha experiment.

## 1. Current repository state

Current reviewed main before this handoff:

- main: `9c4785460cae4d4426fe83b9a733d7831ff1fd4a`
- PR #30 merge: `20a610b9e99f44268d21939a761c7b72ff5192d9`
- PR #30 head: `fc4bb7e809708fdfc3a46b1f15cba8879832b417`
- PR #30 URL: https://github.com/AT2018cow/us-ai-stock-scanner/pull/30
- PR-head GitHub Actions run #128 passed the full
  `python -m unittest discover -s tests` suite.
- The post-merge direct commit `9c478546...` has no recorded Actions run in
  the connected GitHub view. Treat its regression test as committed but not
  independently CI-verified on that exact commit.

No production config was changed and no production parameter was promoted.

## 2. What PR30 established

PR30 introduced a same-state oracle so research reconstruction can be compared
with the canonical production-parity selector on the exact same in-memory
cross-section, eliminating mutable SEC/cache timing from the code-equivalence
test.

Frozen input contract:

- PR28 expanded risk_off low_value dataset:
  `bb6edd7a30d8347aeb2020f77255eb1d043d2417aa8892b1a62da8ff0cad0ad6`
- 23,774 rows / 42 signal dates
- dataset skipped exactly:
  - `max_range_position_52w`
  - `min_drawdown_from_52w_high`
  - `max_price_to_sma200`
- risk_off config Git blob:
  `8214689234b6ff2994a85d8a494763b54e56178d`
- Top-N = 10
- channels = core_ai, ai_enabler, ai_peripheral
- horizons = 20/60/120
- retrospective only; `production_promotion_allowed=false`

Protocol:
`docs/post_pr28_same_state_single_range_gate.md`

Evaluator:
`scripts/low_value_single_gate_ablation.py`

## 3. Post-merge research-tooling bug found and fixed

Commit `9c478546...` fixed a real research-only parity bug.

Cause:

- extracted datasets carry a `channel` column;
- production cross-sections do **not** carry that column when
  `apply_research_assessment` runs;
- the old research path passed the dataset channel into assessment;
- an `ai_enabler` row could therefore self-award
  `ai_infrastructure_exposure` (+0.7 research score and sometimes a priority
  flip) even when its bucket/ETF evidence would not trigger that tag in
  production.

Fixes landed in:

- `scripts/low_value_gate_ablation.py`: drop `channel` before research
  assessment, then re-attach it after ranking/gating.
- `scripts/sweep_score_weights.py`: same production-parity treatment before
  low_value research-gate eligibility.
- `tests/test_low_value_gate_ablation.py`: regression test
  `test_rank_channel_ignores_dataset_channel_column`.

The regression reproduces the pre-fix 2.7-vs-2.0 research-score signature and
requires identical results with/without the dataset channel label after the
fix.

This is research tooling only. Production scanner/backtest behavior was not
changed.

## 4. PR30 valid outcome after the fix

Evidence:
`evidence/baselines/post_pr23_005b86c/pr30_single_range_gate/`

Decision note:
`evidence/baselines/post_pr23_005b86c/pr30_single_range_gate/decision_note.md`

Same-state ordered oracle parity after the fix:

- **168 / 168 exact**
- every date/channel plus combined list matches.

Fixed B intervention:

`max_range_position_52w: hard -> soft`

The other two position gates remained hard.

Primary 120d results:

- pooled B-A mean: +0.000177 (~+0.02 percentage points)
- pooled median: 0
- positive dates: 37.8%
- pooled median Jaccard: 0.923
- block-6 90% CI: [-0.00333, +0.00363]
- 2023: +0.00680, but the largest date is 48.0% of absolute yearly delta
- 2024: -0.000129
- 2025: -0.00560, only 20% positive dates
- down regime: -0.000456

Pre-registered failures:

- `2024_120d_delta_not_positive`
- `2025_120d_delta_not_positive`
- `all_120d_positive_date_ratio_not_above_half`
- `all_120d_block_bootstrap_lower_not_positive`
- `down_regime_120d_degraded`

Verdict:

**The single max_range_position_52w hard-to-soft mechanism fails. Do not
continue or promote it. The position-gate path is stopped unless a genuinely
new interaction mechanism is pre-registered from independent evidence.**

Do not resurrect the quarantined PR28 three-gate B returns as evidence.

## 5. Important review caveats after PR30

### 5.1 PR30 evidence provenance needs one cheap clean rerun

The committed PR30 input manifest says:

`code_sha = 20a610b9...`

but the channel-leak fix and evidence were committed together in
`9c478546...`.

The likely sequence was: edit working tree -> run evidence while HEAD still
pointed to the PR30 merge -> commit code fix and evidence together.

That does not invalidate the observed 168/168 parity or negative result, but
the manifest alone does not prove the outputs came from a clean committed
checkout.

**First task in the next PR/work session:** on a clean current-main checkout,
rerun only `scripts/low_value_single_gate_ablation.py` with the same frozen
dataset and require the parity/summary metrics to reproduce. No Modal compute
is needed. Refresh the compact evidence provenance if identical. If results
differ, stop and debug.

### 5.2 Do not overstate what the channel leak explains

The post-fix same-state code-path mismatch was explained by the channel leak.

That is not identical to proving the old cross-run PR28 historical parity gap
was fully explained. PR28's committed replay-vs-extraction parity had 12
channel-date mismatches:

- 10 ai_enabler
- 1 ai_peripheral
- 1 core_ai

Those runs were also created at different mutable data/cache states. Therefore:

- same-state code-equivalence is now proven;
- the old PR28 `114/126` historical cross-run hard stop remains historical
  evidence and is not retroactively changed to 126/126;
- do not claim all Oct-8-vs-Oct-9 input drift was root-caused.

### 5.3 Audit the channel-leak blast radius before the next alpha hypothesis

`scripts/low_value_gate_attribution.py` still constructs channel-specific
dataset rows and calls `apply_research_assessment` without first removing the
dataset `channel` column.

Therefore PR27 attribution fields that depend on the **research assessment /
research gate / post-research rank** may be contaminated by the same research
tooling bug, especially in ai_enabler.

The following parts are different:

- PR27 hard first-fail counts for structural hard gates are upstream of
  research assessment and are not directly changed by this specific leak.
- `scripts/ic_analysis.py` does not call research assessment/gating; its
  production-score IC/decile analysis is not affected by this particular
  channel-label leak.
- pre-`9c478546` low_value weight-sweep eligibility/results should be
  considered superseded until rerun with the fixed gate semantics.

Do not launch a broad weight search until this audit is closed.

## 6. Highest-value next PR

Recommended next PR objective:

**Close the channel-column research parity blast radius and revalidate the
affected offline low_value evidence.**

Keep this mechanical/reproducibility-focused. Do not mix a new alpha
intervention into the same PR.

Suggested scope:

1. Fix `scripts/low_value_gate_attribution.py` so research assessment sees
   production-equivalent rows without the dataset `channel` column.
2. Add a regression test analogous to
   `test_rank_channel_ignores_dataset_channel_column`.
3. Search every research script for `apply_research_assessment` /
   `apply_low_value_research_gate` on extracted channel-bearing rows and
   classify each call as safe or affected.
4. Clean-rerun PR30 locally from committed code and verify the exact same-state
   parity and materially identical summary.
5. Recompute only affected compact PR27 attribution / candidate-zero evidence
   from existing frozen datasets. No historical replay and no new dataset
   extraction unless a correctness proof shows the stored data are
   insufficient.
6. Write a corrected decision note stating which earlier findings survive and
   which are superseded.
7. Only after that choose the next alpha hypothesis.

Expected next research direction, if the audit does not reveal another
mechanical issue:

- shift attention away from position hard gates;
- investigate **low_value ranking / research-gate interaction** because
  low_value score monotonicity was weak/unstable while momentum ranking was
  much stronger;
- use one pre-registered mechanism at a time;
- do not start with a broad 36-candidate tuner or broad score-weight search.

## 7. Evidence context that still matters

Post-PR23 frozen protocol:

- 2023-01-01 through 2026-09-30
- monthly rebalance (~42 mature dataset dates / ~45 replay signal dates)
- 20/60/120 day horizons
- 15 bps trading cost
- next_open entry / close exit
- rules_proxy theme source
- latest-watchlist fallback OFF
- pre-snapshot universe = union approximation
- channels = core_ai / ai_enabler / ai_peripheral
- max 800 symbols
- retrospective replay is not automatically OOS.

Key frozen/canonical datasets:

- original risk_off survivor dataset SHA:
  `4a0203d9...`
- corrected risk_on survivor dataset:
  30,355 rows / 42 dates,
  SHA `295e3de8d0e48b9f9fac0a182c2354e447a0b97c68203ddc3b65d840305a282d`
- PR28 expanded risk_off low_value dataset:
  23,774 rows / 42 dates,
  SHA `bb6edd7a30d8347aeb2020f77255eb1d043d2417aa8892b1a62da8ff0cad0ad6`

PR26 anchored OOS result still stands:

- all final profile/search combinations were promotion-ineligible;
- candidate selection was unstable across folds;
- no production parameter change.

PR27 rank evidence still useful:

- momentum score has materially stronger/stabler IC than low_value;
- low_value pooled IC can be positive while decile monotonicity is weak and
  regime/year behavior changes sign;
- this is why ranking/research-gate interaction remains a candidate research
  direction after the position-gate path failed.

## 8. Modal / compute rules

User requirement: **never use Modal detach**.

If Modal is ever justified:

- always foreground `modal run`;
- explicitly set `MODAL_PROFILE=infi`;
- do not rely on the active/default profile;
- keep launcher/orchestrator on the small host;
- do not exceed 80 total in-flight tuner candidate containers.

For the immediate next work described above:

**No new Modal compute should be necessary.**

If the PR28 raw dataset is missing locally, recover the existing Volume
artifact only:

```bash
MODAL_PROFILE=infi .venv/bin/python -m modal volume get \
  --force \
  ai-scanner-research \
  "/post_pr28_position_ablation_202610/datasets" \
  "outputs/post_pr23_baseline_202610/pr30_single_range_gate/recovered_dataset"
```

This is a volume download, not a research run.

## 9. Commands / validation

Repository tests:

```bash
python -m unittest discover -s tests
```

Clean PR30 local rerun:

```bash
RUN_ID=post_pr23_baseline_202610
EXP="outputs/$RUN_ID"
DATASET="$EXP/pr28_position_ablation/expanded_dataset/weight_dataset_risk_off.csv"

python scripts/low_value_single_gate_ablation.py \
  --dataset "$DATASET" \
  --scan-config configs/config.risk_off.json \
  --output-prefix "$EXP/pr30_single_range_gate_clean/single_range_gate"
```

Hard expectations before accepting the clean rerun:

- dataset SHA must equal
  `bb6edd7a30d8347aeb2020f77255eb1d043d2417aa8892b1a62da8ff0cad0ad6`;
- config content guard must pass;
- same-state oracle parity must be 168/168;
- retrospective gate must remain false for the same substantive reasons;
- pooled 120d result should remain approximately +0.00018 with bootstrap CI
  spanning zero;
- no production promotion.

## 10. What not to do next

Do not:

- change production risk_off thresholds based on PR28 or PR30;
- revive the three-gate PR28 B arm;
- tune `max_range_position_52w`;
- launch the broad tuner;
- launch a new replay merely to re-answer PR30;
- regenerate frozen datasets without a demonstrated correctness need;
- interpret equal-weight signal-label portfolios as account NAV;
- call retrospective evidence anchored OOS;
- use old pre-fix low_value sweep/gate outputs as canonical;
- use `--detach` with Modal.

## 11. Suggested new-conversation starting point

The next conversation should begin by reading this file and then auditing the
channel-column leak blast radius. The first implementation target should be a
small PR that fixes/revalidates research tooling and evidence only, before any
new alpha mechanism is selected.
