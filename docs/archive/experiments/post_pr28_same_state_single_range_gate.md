# Post-PR28 same-state single range-gate protocol

## Objective

Resolve the PR28 validity problem before testing a narrower alpha intervention.

PR28 failed its historical replay-vs-extraction ordered parity gate because the replay and expanded extraction were created from mutable external/cache state at different times. That hard-stop record remains valid and must not be rewritten. This protocol instead tests code-path equivalence on one immutable cross-section state, then evaluates one fixed gate change on that exact same state.

## Immutable input

The canonical input is the already-generated PR28 expanded risk_off low_value dataset:

```text
SHA256 bb6edd7a30d8347aeb2020f77255eb1d043d2417aa8892b1a62da8ff0cad0ad6
23774 rows
42 signal dates
```

Its metadata must state:

- style = risk_off;
- list_types = [low_value];
- research_expanded_survivor_dataset = true;
- latest-watchlist fallback = false;
- skipped structural hard steps are exactly max_range_position_52w, min_drawdown_from_52w_high, max_price_to_sma200.

The script refuses any other dataset hash or skipped-step set. It also locks `configs/config.risk_off.json` to Git blob SHA1 `8214689234b6ff2994a85d8a494763b54e56178d`; a later production-config change requires a new experiment rather than silently reinterpreting this dataset.

## Same-state production oracle

For each signal date, the expanded dataset repeats symbols across channels. Before calling the canonical selector, the evaluator validates that all raw fields agree across same-date/same-symbol channel duplicates except channel and extracted soft-pass counters, then reconstructs one row per symbol.

Arm A is selected with the canonical production-parity helper `rank_and_pick_symbols_with_diagnostics` from `ai_value_scanner.backtest`.

A second research reconstruction of the unchanged baseline is run on the same rows. Ordered selections must match the canonical oracle for every channel and for the final combined list. Any mismatch is a hard stop before B-arm outcomes are interpreted.

This same-state oracle parity is a code-equivalence test. It does not claim that mutable Oct-9 data exactly reproduces the Oct-8 historical replay. The committed PR28 114/126 replay-vs-extraction mismatch remains evidence of input-state drift.

## Fixed intervention

Only one condition changes:

```text
max_range_position_52w: hard -> soft
```

The other two PR28 position gates remain hard:

```text
min_drawdown_from_52w_high
max_price_to_sma200
```

Everything else remains unchanged: risk_off config, production score weights, all core/base hard filters, remaining structural/soft rules, research assessment/gate, diversification caps, channel order, Top-N=10, entry/exit/cost conventions, QQQ benchmark and labels.

Do not edit production config.

## Execution

Canonical evidence must be generated from a **clean committed Git checkout**. The evaluator now hard-fails if tracked or untracked non-ignored worktree changes are present, and records both commit SHA and Git tree SHA in the manifest. Commit code fixes before running evidence; never run canonical evidence from a dirty working tree.

No new Modal compute is required.

If the raw PR28 dataset is still local:

```bash
RUN_ID=post_pr23_baseline_202610
EXP="outputs/$RUN_ID"
DATASET="$EXP/pr28_position_ablation/expanded_dataset/weight_dataset_risk_off.csv"
test -f "$DATASET"

python scripts/low_value_single_gate_ablation.py \
  --dataset "$DATASET" \
  --scan-config configs/config.risk_off.json \
  --output-prefix "$EXP/pr30_single_range_gate/single_range_gate"
```

If the local raw file was deleted, recover the existing artifact only; do not run a new extraction:

```bash
RUN_ID=post_pr23_baseline_202610
EXP="outputs/$RUN_ID"
mkdir -p "$EXP/pr30_single_range_gate/recovered_dataset"

MODAL_PROFILE=infi .venv/bin/python -m modal volume get \
  --force \
  ai-scanner-research \
  "/post_pr28_position_ablation_202610/datasets" \
  "$EXP/pr30_single_range_gate/recovered_dataset"
```

Then point `--dataset` at the recovered `weight_dataset_risk_off.csv`.

Do not use `modal run`. Never use `--detach`.

## Pre-registered retrospective gate

Primary horizon is 120d; 20d/60d are diagnostics. The single-gate mechanism passes only if all conditions hold:

1. same-state canonical-oracle vs unchanged research reconstruction ordered parity is 100% for every date/channel and combined list;
2. B-A average 120d return is positive separately in 2023, 2024 and 2025;
3. each of 2023/2024/2025 has at least 8 mature monthly observations;
4. more than 50% of all mature 120d dates improve;
5. no single date contributes 35% or more of total absolute 120d paired delta;
6. pooled median A/B selected-symbol Jaccard is at least 0.70;
7. each full-year 2023/2024/2025 median Jaccard is at least 0.60;
8. average 120d B-A return in down regime is non-negative;
9. no single B-only added symbol contributes 35% or more of total positive 120d excess among additions;
10. pooled 120d circular moving-block-bootstrap 90% confidence lower bound for mean B-A is above zero.

For overlap-aware bootstrap, block length is fixed at ceil(horizon_days / 21). Thus the primary 120d block length is 6 monthly observations, seed is deterministic, and 5000 bootstrap samples are used.

2023 and 2025 contributed to hypothesis formation. 2024 is the key full-year stress check. 2026YTD remains diagnostic because 120d labels are immature.

Passing this retrospective gate does not authorize a production change. It only justifies a later anchored chronological fixed-B validation with purged label boundaries.

## Evidence outputs

The script writes:

- `*_input_manifest.json` with dataset/meta/config hashes, code SHA, Git tree SHA, and `git_worktree_clean=true`;
- `*_oracle_parity.csv`;
- `*_events.csv`;
- `*_paired.csv`;
- `*_paired_summary.csv` including overlap-aware bootstrap intervals;
- `*_switch_cases.csv` and `*_switch_symbol_summary.csv`;
- `*_arm_summary.csv`;
- `*_report.md`;
- `*_summary.json` with `production_promotion_allowed=false`.

Raw dataset remains off Git. Commit only compact evidence if/when the run is executed.

## Stop discipline

Do not inspect or narrate B-arm returns as evidence if same-state oracle parity fails. Do not weaken parity or overlap thresholds after observing outcomes. Record unfavorable outcomes.
