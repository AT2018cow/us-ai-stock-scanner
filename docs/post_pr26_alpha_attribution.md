# Post-PR26 alpha-attribution protocol

## Goal

Use the completed post-PR23 survivor datasets to answer two questions before any new tuner/replay:

1. Does the current production composite score rank survivors monotonically toward higher future returns?
2. Why did `risk_on` low_value select winners that `risk_off` did not in the retrospective edge years 2023 and 2025?

This stage is offline-only: no SEC, Alpaca, Modal or historical replay, and no production parameter change.

## Corrected OOS starting point

PR26 rescoring confirms the instability is real: 2024 held-out excess is negative, 2025 can be strongly positive, 2026YTD is immature and turns negative for the risk_on search, and all profiles remain `promotion_eligible=false`. Therefore the next useful work is mechanism attribution, not another broad parameter search.

## Weight-sweep correctness repair

PR27 audit found that the pre-PR27 `sweep_score_weights.py` candidate-zero formula omitted each channel's configured production base-weight vector. Multiplier 1.0 therefore did not reproduce production scoring when production weights differed.

The corrected formula is:

```text
effective_axis_weight = production_base_weight * candidate_multiplier
```

The old tracked `weightsweep_parity_*` artifacts are superseded for weight research. Historical replay, tuner return observations and survivor datasets are unaffected.

## Locate frozen survivor datasets

```bash
RUN_ID=post_pr23_baseline_202610
EXP="outputs/$RUN_ID"

RISK_OFF_DATASET="$(find "$EXP" -type f -name 'weight_dataset_risk_off.csv' -print -quit)"
RISK_ON_DATASET="$(find "$EXP" -type f -name 'weight_dataset_risk_on.csv' -print -quit)"

test -n "$RISK_OFF_DATASET" && test -f "$RISK_OFF_DATASET"
test -n "$RISK_ON_DATASET" && test -f "$RISK_ON_DATASET"
```

Do not regenerate the datasets if their SHA256 values still match `evidence/baselines/post_pr23_005b86c/weight_dataset_sha256.txt`.

## A. Corrected candidate-zero sweep check

Run one candidate only, locally:

```bash
mkdir -p "$EXP/alpha_attribution"

python scripts/sweep_score_weights.py \
  --dataset "$RISK_OFF_DATASET" \
  --scan-config configs/config.risk_off.json \
  --n-candidates 1 \
  --split-date 2026-01-01 \
  --output-prefix "$EXP/alpha_attribution/weightsweep_candidate0_risk_off"

python scripts/sweep_score_weights.py \
  --dataset "$RISK_ON_DATASET" \
  --scan-config configs/config.risk_on.json \
  --n-candidates 1 \
  --split-date 2026-01-01 \
  --output-prefix "$EXP/alpha_attribution/weightsweep_candidate0_risk_on"
```

This is a correctness checkpoint, not an alpha search. Do not increase `--n-candidates` in this PR. If candidate-zero selection/parity still disagrees with equivalent production replay dates, stop and debug parity.

## B. Production-score rank IC and decile monotonicity

```bash
python scripts/ic_analysis.py \
  --dataset "$RISK_OFF_DATASET" \
  --scan-config configs/config.risk_off.json \
  --output-prefix "$EXP/alpha_attribution/ic_risk_off"

python scripts/ic_analysis.py \
  --dataset "$RISK_ON_DATASET" \
  --scan-config configs/config.risk_on.json \
  --output-prefix "$EXP/alpha_attribution/ic_risk_on"
```

Each run writes `*_ic_by_date.csv`, `*_ic_summary.csv`, `*_deciles.csv`, `*_monotonicity.csv`, and `*_report.md`.

Interpretation gate: do not tune weights merely because pooled IC is positive. A useful ranking signal should show positive IC at more than one horizon, positive top-minus-bottom decile excess, reasonably monotone adjacent deciles, similar sign in more than one year, and no dependence on only one channel or regime.

## C. risk_on-only low_value exclusion attribution

```bash
python scripts/low_value_gate_attribution.py \
  --risk-on-dataset "$RISK_ON_DATASET" \
  --risk-off-dataset "$RISK_OFF_DATASET" \
  --risk-on-signals evidence/baselines/post_pr23_005b86c/post_pr23_baseline_202610_risk_on_events_signals.csv \
  --risk-off-signals evidence/baselines/post_pr23_005b86c/post_pr23_baseline_202610_risk_off_events_signals.csv \
  --risk-on-config configs/config.risk_on.json \
  --risk-off-config configs/config.risk_off.json \
  --years 2023,2025 \
  --horizon 120 \
  --top-n 10 \
  --output-prefix "$EXP/alpha_attribution/low_value_gate"
```

Outputs: `low_value_gate_cases.csv`, `low_value_gate_summary.csv`, `low_value_gate_paired_selection.csv`, and `low_value_gate_report.md`.

For each channel-level stock selected by risk_on low_value but not risk_off, the script diagnoses the risk_off pipeline in order: hard filter -> research gate -> group cap -> per-channel Top-N. For names that pass hard filters but rank below Top-N, it also records failed risk_off soft conditions. In scored mode most valuation/quality conditions are soft, so do not call every ranking difference a hard-gate exclusion.

`paired_selection.csv` compares risk_on-only versus risk_off-only selected-symbol forward returns on the same dates. It is a selection-substitution diagnostic, not account P&L.

## Stop conditions

Stop before any ablation if corrected candidate-zero parity fails; `selection_mismatch` or `data_mismatch` is material; the apparent edge is confined to one date/symbol; the dominant exclusion reason does not repeat across dates; or score monotonicity is weak and the exclusion mechanism has no stable positive-excess pattern.

## What may justify PR28

A narrow ablation is justified only if one mechanism survives both ranking and selection attribution, for example the same risk_off structural step or research gate repeatedly removes positive-excess names across 2023 and 2025. Test one mechanism at a time. Do not launch another 36-candidate search.

## Evidence to commit after the offline run

Keep raw survivor CSVs in `outputs/`. Commit only compact candidate-zero results/reports, IC summaries/deciles/monotonicity/reports, low-value summary/paired/report (and cases if review-sized), plus a short decision note naming at most one or two next mechanisms. Do not commit production config changes.
