# Post-PR23 risk_on / risk_off baseline experiment

> Scope: first alpha-research checkpoint after PR #23.  
> Production strategy parameters are frozen. This protocol does not promote or
> rewrite `configs/config.risk_on.json` / `configs/config.risk_off.json`.

## 1. Evidence classes

Keep these two result classes separate.

1. **current-config retrospective baseline**
   - Runs the already-frozen production configs over historical dates.
   - Useful for attribution and paired style comparison.
   - **Not automatically OOS** because the current configs were previously
     informed by parts of the same historical period.

2. **anchored OOS selection baseline**
   - Candidate selection uses prior windows only.
   - The next chronological window is held out until after selection.
   - Any forward-return label whose `label_end_date` crosses the held-out
     boundary is purged from training.
   - Only this result class may be labelled anchored OOS.

Do not combine the two classes into one "OOS" headline table.

## 2. Code and input freeze

PR #23 merged main before this research PR:

```
ca1baee60d617b07f013710c96c7e99a03195c60
```

After this PR is merged, record the actual merge SHA as the experiment code
SHA. Strategy selection, pricing, labels and production parameters are
unchanged. The replay engine now also supports per-signal-date checkpoints for
long research runs; checkpointing must not change selected symbols or returns.

Run first:

```bash
git status --short
git rev-parse HEAD
python -m unittest discover -s tests
```

The working tree must be clean before the experiment.

Create one immutable experiment directory. Replace `<RUN_ID>` once and do
not reuse it for a later rerun.

```bash
RUN_ID=post_pr23_baseline_202610
EXP=outputs/$RUN_ID
mkdir -p "$EXP/frozen_inputs"

cp configs/config.risk_off.json "$EXP/frozen_inputs/"
cp configs/config.risk_on.json  "$EXP/frozen_inputs/"
cp data/ai_watchlist.csv        "$EXP/frozen_inputs/"

# The experiment environment may contain local PIT snapshots not tracked by git.
# Freeze exactly the directory used by replay.
cp -a data/watchlist_history "$EXP/frozen_inputs/watchlist_history"

sha256sum   "$EXP/frozen_inputs/config.risk_off.json"   "$EXP/frozen_inputs/config.risk_on.json"   "$EXP/frozen_inputs/ai_watchlist.csv"   > "$EXP/frozen_inputs/input_sha256.txt"

find "$EXP/frozen_inputs/watchlist_history" -type f -print0   | sort -z   | xargs -0 sha256sum   > "$EXP/frozen_inputs/watchlist_history_sha256.txt"

git rev-parse HEAD > "$EXP/code_sha.txt"
git status --short > "$EXP/git_status.txt"
```

Do not refresh the watchlist or delete/refresh caches between risk_off and
risk_on. The two styles must see the same frozen data state.

Record the Alpaca feed, market-data data-as-of/cache provenance and SEC cache
state from the generated network diagnostics. If a same-day SEC refresh occurs
between the two style runs, discard the pair and rerun both against one frozen
data state.

## 3. Fixed retrospective replay

Use a fixed signal-date end so rerunning the protocol later does not silently
add new signal dates. This checkpoint uses the last complete month before the
PR23 handoff:

```
start = 2023-01-01
end   = 2026-09-30
rebalance = monthly
horizons = 20,60,120
cost = 15 bps one-way
entry = next_open
exit = close
theme_source = rules_proxy
latest-watchlist fallback = OFF
pre-snapshot universe = union
```

Run all four research lists. The first three AI channels are the primary
comparison set; `ai_smallcap` remains auxiliary observation and is excluded
from this paired baseline.

### risk_off

```bash
python run_backtest.py   --mode historical_replay   --scan-config "$EXP/frozen_inputs/config.risk_off.json"   --watchlist-csv-path "$EXP/frozen_inputs/ai_watchlist.csv"   --watchlist-history-dir "$EXP/frozen_inputs/watchlist_history"   --output-prefix "$RUN_ID"_risk_off   --outputs-dir "$EXP"   --list-types low_value,industry_trend,momentum,research_pool   --include-channels core_ai,ai_enabler,ai_peripheral   --horizons 20,60,120   --start-date 2023-01-01   --end-date 2026-09-30   --rebalance-frequency monthly   --trading-cost-bps 15   --entry-price-mode next_open   --exit-price-mode close   --theme-source rules_proxy   --pre-snapshot-universe union   --no-latest-watchlist-fallback   --no-perturbation
```

### risk_on

Use the identical command with:

```bash
--scan-config "$EXP/frozen_inputs/config.risk_on.json"
--output-prefix "$RUN_ID"_risk_on
```

Do not interpret a higher aggregate return as proof that one style is better.
The first review is paired by identical signal dates, benchmark/cost convention
and mature labels.

### Recommended executor for the retrospective replay

The full 2023-2026 PIT replay can exceed an 8 GB host. For this experiment,
prefer the dedicated Modal runner instead of running the commands above on the
small launcher host.

The Modal runner uses a bounded resource envelope instead of a large fixed
reservation: `cpu=(1.0, 2.0)` and `memory=(8192, 16384)` MiB. The first
value is the request and the second is the hard limit. This gives the replay
room to exceed the 8 GB launcher that OOM-killed the local run without
reserving 24 GB for the entire job. Raise the memory limit to 24 GiB only after
a reproducible OOM at 16 GiB. It mounts the existing `ai-scanner-cache`
Volume, writes artifacts/checkpoints to the persistent
`ai-scanner-research` Volume, and commits after every completed signal date.

Run Modal in the foreground. **Do not use `--detach` or any detached-app
mode** for this experiment. Foreground execution keeps logs/failures attached
to the launcher and makes checkpoint/resume state unambiguous.

Before launch, repository-local `configs/`, `data/ai_watchlist.csv` and
`data/watchlist_history` must still hash-identically to the frozen inputs.
The runner checks this and aborts on mismatch.

```bash
RUN_ID=post_pr23_baseline_202610

# Test/experiment environment: always target the infi Modal workspace/profile
# explicitly; do not rely on the host's current/default Modal profile.
MODAL_PROFILE=infi .venv/bin/python -m modal run \
  scripts/modal_baseline_executor.py \
  --run-id "$RUN_ID" \
  --stage replay \
  --styles risk_off,risk_on
```

The two styles run sequentially so they share one controlled cache state
without competing writes.

If a Modal container is interrupted or OOM-killed, rerun the **same command**.
The runner resumes from committed signal-date checkpoints. It also stores a
run-spec guard containing the code SHA/style/date range; a changed spec is
rejected instead of silently reusing stale checkpoints.

To intentionally discard the remote replay checkpoints and restart, run with
`--no-resume`. Do this only when starting a new evidence run or after an
explicitly documented invalidation.

The partial local replay produced before checkpoint support cannot be imported
as a valid checkpoint. For example, a run killed after `4/45` dates has no
durable signal rows from those dates because the old replay wrote
`*_signals.csv` only after all signal dates finished. Cached SEC/Alpaca files
may still be reused, but the signal replay itself must restart.

Remote files can be inspected with Modal's Volume CLI. Do **not** download
the checkpoint tree merely to continue a run; resume reads it directly from the
persistent Volume.

```bash
MODAL_PROFILE=infi .venv/bin/python -m modal volume ls \
  ai-scanner-research "/$RUN_ID"
```

After both replay styles finish, copy back the final replay artifacts:

```bash
mkdir -p "$EXP/modal_download/replay"
MODAL_PROFILE=infi .venv/bin/python -m modal volume get \
  --force \
  ai-scanner-research \
  "/$RUN_ID/replay" \
  "$EXP/modal_download/replay"
```

After the dataset stage finishes, copy back the survivor datasets and metadata:

```bash
mkdir -p "$EXP/modal_download/datasets"
MODAL_PROFILE=infi .venv/bin/python -m modal volume get \
  --force \
  ai-scanner-research \
  "/$RUN_ID/datasets" \
  "$EXP/modal_download/datasets"
```

The `checkpoints/` tree is **not a required download**. Keep it on
`ai-scanner-research` until the evidence run is accepted; it exists for
resume/recovery, not as a review artifact. The `ai-scanner-cache` Volume is
also not an experiment result and should not be copied into Git.

To retain the foreground Modal launcher log without detaching, use
`tee` with pipefail:

```bash
mkdir -p "$EXP/logs"
set -o pipefail
MODAL_PROFILE=infi .venv/bin/python -m modal run \
  scripts/modal_baseline_executor.py \
  --run-id "$RUN_ID" \
  --stage replay \
  --styles risk_off,risk_on \
  2>&1 | tee "$EXP/logs/modal_replay.log"
```

A launcher log is useful for failure diagnosis but is not normally a Git
evidence artifact.

For a local replay on a sufficiently large host, checkpointing is also
available directly:

```bash
# First attempt
python run_backtest.py ... \
  --signal-checkpoint-dir "$EXP/checkpoints/risk_off"

# After interruption, rerun the identical command plus:
# --resume-signal-checkpoints
```

A resume manifest mismatch is a hard error. Do not bypass it by copying old
checkpoint files into a new run.

After the first successful full replay, inspect actual Modal resource/billing
metrics before changing the envelope. For example:

```bash
MODAL_PROFILE=infi .venv/bin/python -m modal billing report \
  --for today --show-resources
```

If memory usage stays comfortably below the request, lower the request on the
next evidence run. If the container hits the 16 GiB hard limit, raise only the
memory limit (for example to 24 GiB) and rerun the same checkpointed command.
Do not add CPU merely to address a memory OOM.

## 4. One-time survivor datasets for offline research

Generate these **once** after the retrospective replay. Reuse them for IC,
weight sweeps and later ablations instead of rebuilding PIT for every
candidate.

The first checkpoint extracts the two lists that directly drive the current
risk-style hypotheses: `low_value` and `momentum`. Do not expand to the
diagnostic lists until the first attribution says they are decision-relevant.

### risk_off dataset

```bash
python scripts/extract_weight_dataset.py   --scan-config "$EXP/frozen_inputs/config.risk_off.json"   --output "$EXP/weight_dataset_risk_off.csv"   --list-types low_value,momentum   --start-date 2023-01-01   --end-date 2026-09-30   --rebalance-frequency monthly   --horizons 20,60,120   --trading-cost-bps 15   --entry-price-mode next_open   --exit-price-mode close   --watchlist-history-dir "$EXP/frozen_inputs/watchlist_history"   --watchlist-csv-path "$EXP/frozen_inputs/ai_watchlist.csv"   --pre-snapshot-universe union   --no-latest-watchlist-fallback   --theme-source rules_proxy   --include-channels core_ai,ai_enabler,ai_peripheral
```

### risk_on dataset

Use the same command with the risk_on frozen config and
`$EXP/weight_dataset_risk_on.csv`.

The generated `.meta.json` files are part of the evidence and must be kept.

On an 8 GB launcher host, generate both survivor datasets on Modal after the
replay stage:

```bash
MODAL_PROFILE=infi .venv/bin/python -m modal run \
  scripts/modal_baseline_executor.py \
  --run-id "$RUN_ID" \
  --stage dataset \
  --styles risk_off,risk_on
```

Or use `--stage all` to run replay first and then both datasets. Dataset
extraction is stage-resumable: a completed dataset with a matching run spec is
skipped. Unlike the replay stage it does not checkpoint individual signal
dates, so an interrupted dataset extraction restarts that one dataset.

## 5. Offline sweep parity gate

This PR fixes three previously-missing parity rules in
`scripts/sweep_score_weights.py`:

- low-value research gate before diversification;
- production sector / watchlist-ETF caps before per-channel top-N;
- `ScanConfig.channel_profiles` order before cross-channel symbol
  normalization.

Before using any sweep result, run candidate zero and record it as the
**current-config offline baseline**. It must be checked against the equivalent
replay selection on overlapping dates before candidate rankings are trusted.

Example diagnostic sweeps:

```bash
python scripts/sweep_score_weights.py   --dataset "$EXP/weight_dataset_risk_off.csv"   --scan-config "$EXP/frozen_inputs/config.risk_off.json"   --n-candidates 1   --split-date 2026-01-01   --output-prefix "$EXP/weightsweep_parity_risk_off"

python scripts/sweep_score_weights.py   --dataset "$EXP/weight_dataset_risk_on.csv"   --scan-config "$EXP/frozen_inputs/config.risk_on.json"   --n-candidates 1   --split-date 2026-01-01   --output-prefix "$EXP/weightsweep_parity_risk_on"
```

This is a correctness gate, not a parameter recommendation.

## 6. Anchored OOS selection run

Use the existing anchored chronological tuner. Keep promotion disabled and
retain artifacts for audit.

### risk_off

```bash
python scripts/tune_parameters.py   --base-config "$EXP/frozen_inputs/config.risk_off.json"   --param-space configs/tuner.param_space.json   --outputs-dir "$EXP/tuner_risk_off"   --work-dir "$EXP/tuner_work_risk_off"   --windows     2023:2023-01-01:2023-12-31,2024:2024-01-01:2024-12-31,2025:2025-01-01:2025-12-31,2026YTD:2026-01-01:2026-09-30   --selection-mode walk_forward   --rebalance-frequency monthly   --max-candidates 36   --random-seed 42   --watchlist-csv-path "$EXP/frozen_inputs/ai_watchlist.csv"   --watchlist-history-dir "$EXP/frozen_inputs/watchlist_history"   --pre-snapshot-universe union   --no-latest-watchlist-fallback   --no-prune-backtest-artifacts   --no-promote
```

### risk_on

Use:

```bash
--base-config "$EXP/frozen_inputs/config.risk_on.json"
--param-space configs/tuner.param_space.momentum.json
--outputs-dir "$EXP/tuner_risk_on"
--work-dir "$EXP/tuner_work_risk_on"
```

with the same windows, seed, frozen inputs and no-promotion rules.

### Modal for the anchored tuner

In the test/experiment environment, the tuner must also use the `infi` Modal workspace/profile. Set `MODAL_PROFILE=infi` on the foreground tuner command; do not rely on a globally active/default profile.

The retrospective replay/dataset stages use
`scripts/modal_baseline_executor.py` above. The anchored tuner has a separate
existing candidate-level Modal executor.

The tuner Modal image packages repository-local `configs/` and `data/`, but
it does **not** package `outputs/<RUN_ID>/frozen_inputs`. Do not pass the
`outputs/` frozen paths directly to remote candidates.

Before a Modal run:

1. verify that repository-local `data/ai_watchlist.csv` and
   `data/watchlist_history` still hash-identically to the frozen copies;
2. keep those files unchanged for the whole batch;
3. use repository-local data paths in the tuner arguments;
4. add `--executor modal`.

Use these substitutions:

```bash
--watchlist-csv-path data/ai_watchlist.csv
--watchlist-history-dir data/watchlist_history
--executor modal
```

Do not change candidate count, seed, windows or any other experiment setting.
If the repository-local data paths no longer match the frozen hashes, do not
use Modal until the frozen state is restored or explicitly staged into the
Modal image.

The current-config replay and survivor dataset should normally be generated
once in the experiment environment where the canonical frozen caches live.

## 7. Artifact retention and Git evidence policy

There are three different storage classes. Do not mix them.

### A. Must be copied back from Modal

Keep these locally under `outputs/<RUN_ID>/` for analysis even though
`outputs/` is gitignored:

- final replay directories for **both** `risk_off` and `risk_on`, including:
  - `*_signals.csv`
  - `*_events.csv`
  - `*_benchmarks.csv`
  - `*_summary.csv`
  - `*_segments.csv`
  - `*_signal_diagnostics.csv`
  - `*_signal_channel_summary.csv`
  - `*_report.md`
  - `*_report_network.json`
  - Modal `_SUCCESS.json`
- both survivor datasets:
  - `weight_dataset_risk_off.csv`
  - `weight_dataset_risk_off.csv.meta.json`
  - `weight_dataset_risk_on.csv`
  - `weight_dataset_risk_on.csv.meta.json`
  - their `*.SUCCESS.json` markers.

These are the working research inputs for attribution, IC analysis and the next
ablation. Do not delete them after producing the compact Git evidence.

### B. Keep off GitHub

Do **not** commit any of the following:

- `cache/` or the `ai-scanner-cache` Volume contents;
- `checkpoints/` / per-signal-date checkpoint JSON files;
- the full raw survivor dataset CSVs by default;
- tuner `work_dir` candidate configs and per-candidate raw replay trees;
- bulk Modal runtime logs;
- `.env`, API keys, secrets or credentials.

For off-repo artifacts used by a conclusion, record SHA256, file size/row count,
schema/version metadata and the retained location in `baseline_manifest.json`.
If a raw artifact is later lost, the Git evidence must make that limitation
explicit.

### C. Commit to GitHub after the experiment passes

Create a compact evidence directory, for example:

```
evidence/baselines/post_pr23_<MERGE_SHA_SHORT>/
```

Commit the following reviewable evidence:

- `README.md`: exact commands, evidence class, limitations and result index;
- `baseline_manifest.json`: code SHA, frozen-input hashes, raw-artifact
  hashes, feed/cache provenance, dates/costs/label maturity;
- both replay `*_summary.csv`, `*_segments.csv`,
  `*_signal_diagnostics.csv`, `*_signal_channel_summary.csv`,
  `*_report.md` and `*_report_network.json`;
- replay `*_signals.csv`, `*_events.csv` and `*_benchmarks.csv` when they
  remain ordinary review-sized CSVs. If any becomes unexpectedly large, keep
  it off-repo and commit its SHA256/row count instead of forcing it into Git;
- both survivor dataset `.meta.json` files plus SHA256/row counts for the
  corresponding raw dataset CSVs; do not commit the full survivor CSVs by
  default;
- `current_config_replay_summary.csv` (or JSON);
- `anchored_oos_fold_summary.csv` (or JSON) after the tuner stage;
- `selection_attribution.csv` (or JSON);
- `research_decision.md`;
- compact tuner `*_results.csv`, `*_summary.json` and `*_report.md` after
  anchored OOS completes.

The Git evidence directory is the durable audit record. `outputs/` remains a
local working area and `ai-scanner-research` remains the remote recovery/raw
artifact store.

Do not commit production config changes as part of this evidence checkpoint.

## 8. Required review outputs

Before any production parameter discussion, prepare these five evidence objects:

1. `baseline_manifest.json`
   - experiment code SHA and PR23 parent SHA;
   - dirty status;
   - frozen config/watchlist/history hashes;
   - feed/cache/data-as-of provenance;
   - window/cost/entry/exit/theme settings;
   - label maturity and purge boundaries.

2. `current_config_replay_summary`
   - clearly labelled **retrospective / not automatically OOS**;
   - style x list_type x horizon x regime/year;
   - total/valid/no-signal/unpriced counts;
   - avg/median return, win rate, QQQ excess;
   - non-overlapping cumulative only as a sampling diagnostic.

3. `anchored_oos_fold_summary`
   - train_end, held-out start/end;
   - selected candidate;
   - purged label/event counts;
   - effective valid sample size;
   - horizon maturity;
   - OOS return/excess metrics.

4. `selection_attribution`
   - style x list_type x channel x horizon x regime x fold;
   - selected/valid counts;
   - symbol and sector concentration;
   - top contributors and detractors;
   - top-1/top-3 contribution share;
   - result after removing the largest winner.

5. `research_decision.md`
   - data limitations and evidence grade;
   - whether results depend on one year / one symbol / one channel;
   - only 1-2 next ablation hypotheses;
   - no production parameter changes.

If the existing raw artifacts cannot support one of these fields, mark it
explicitly as unavailable rather than reconstructing it with a different data
state.

## 9. Acceptance / stop rules

This checkpoint passes only if:

- full unit tests pass;
- risk_on and risk_off use the same frozen inputs;
- latest-watchlist fallback is off;
- retrospective and anchored OOS results are labelled separately;
- tuner training labels are purged at every held-out boundary;
- no production config is modified;
- no `--promote` is used;
- offline candidate-zero selection passes replay parity checks before any sweep
  candidate is interpreted.

Stop and investigate instead of continuing to ablation if:

- paired runs have different input/cache data states;
- candidate-zero offline selections disagree materially with replay;
- one symbol or one year explains most of the apparent style advantage;
- sample sizes are too small for the claimed comparison.

The next research PR should be chosen from the attribution result, not from a
pooled parameter sweep.
