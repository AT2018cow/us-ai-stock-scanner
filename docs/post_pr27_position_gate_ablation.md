# PR28 risk_off low_value position-gate ablation protocol

## Objective

Test one mechanism only: whether the risk_off low_value pullback/position structural gates are too destructive when implemented as hard exclusions.

The pre-registered A/B is:

```text
A = current risk_off low_value production semantics
B = move exactly these three steps from hard to soft:
    max_range_position_52w
    min_drawdown_from_52w_high
    max_price_to_sma200
```

The thresholds themselves do not change. Production score weights, every other hard/soft condition, research gate, sector/watchlist-source caps, channel order, Top-N, trading cost, labels and universe contract remain unchanged.

This is retrospective mechanism validation. The hypothesis was formed from 2023/2025 attribution, so PR28 cannot be promotion evidence or true OOS.

## Why a new expanded risk_off dataset is necessary

The canonical risk_off survivor dataset already removed names that failed the three target hard gates. It therefore cannot evaluate a hard-gate relaxation: the counterfactual candidates are missing.

The corrected risk_on dataset is also insufficient because risk_on has its own structural hard gates and would selectively omit some candidates that the PR28 risk_off counterfactual should contain.

PR28 therefore performs one targeted extraction that skips only the three risk_off structural hard steps while keeping all other risk_off hard filters. The extractor safety check rejects attempts to skip core/base or non-structural hard filters.

## Cloud extraction: one job only

Use the `infi` Modal workspace and foreground execution only. Do not use `--detach`.

```bash
RUN_ID=post_pr23_baseline_202610
PR28_RUN_ID=post_pr28_position_ablation_202610
EXP="outputs/$RUN_ID"

MODAL_PROFILE=infi .venv/bin/python -m modal run \
  scripts/modal_baseline_executor.py \
  --run-id "$PR28_RUN_ID" \
  --stage dataset \
  --styles risk_off \
  --start-date 2023-01-01 \
  --end-date 2026-09-30 \
  --frozen-input-dir "$EXP/frozen_inputs" \
  --dataset-list-types low_value \
  --research-skip-low-value-hard-steps \
    max_range_position_52w,min_drawdown_from_52w_high,max_price_to_sma200
```

Do not run replay and do not run tuner.

Copy back only the dataset stage:

```bash
mkdir -p "$EXP/pr28_position_ablation/expanded_dataset"

MODAL_PROFILE=infi .venv/bin/python -m modal volume get \
  --force \
  ai-scanner-research \
  "/$PR28_RUN_ID/datasets" \
  "$EXP/pr28_position_ablation/expanded_dataset"
```

Verify that `weight_dataset_risk_off.meta.json` records:

- `style=risk_off`
- `list_types=["low_value"]`
- `research_expanded_survivor_dataset=true`
- the exact three skipped hard steps
- latest-watchlist fallback disabled
- the same frozen config/watchlist/history hashes used by the post-PR23 baseline launcher check

## Local A/B evaluation

```bash
PR28_DATASET="$(find "$EXP/pr28_position_ablation/expanded_dataset" -type f -name 'weight_dataset_risk_off.csv' -print -quit)"
test -n "$PR28_DATASET" && test -f "$PR28_DATASET"

python scripts/low_value_gate_ablation.py \
  --dataset "$PR28_DATASET" \
  --scan-config configs/config.risk_off.json \
  --baseline-signals \
    evidence/baselines/post_pr23_005b86c/post_pr23_baseline_202610_risk_off_events_signals.csv \
  --output-prefix "$EXP/pr28_position_ablation/position_gate"
```

This step is local/offline and must not call Modal, SEC, Alpaca or historical replay.

## Baseline parity is a hard stop

The A arm reconstructs current risk_off selection from the expanded dataset and compares every available channel/date selection against the canonical production replay signals.

PR28 interpretation is invalid unless channel/date selected-symbol parity is exact. Any non-empty `actual_only` or `expected_only` is a stop condition; debug parity before looking at B-arm returns.

## Pre-registered retrospective robustness gate

Primary horizon is 120d. 20d/60d are diagnostics.

PR28 passes the retrospective mechanism gate only if all of the following hold:

1. baseline replay selection parity is exact;
2. B-A average 120d return is positive separately in 2023, 2024 and 2025;
3. each of those full years has at least 8 mature monthly observations;
4. across all mature 120d dates, more than 50% of paired dates improve;
5. no single date contributes 35% or more of total absolute paired delta;
6. median A/B selected-symbol Jaccard is at least 0.50;
7. average 120d B-A return in down regime is non-negative;
8. no single added symbol contributes 35% or more of total positive 120d excess among B-only additions.

2023 and 2025 are hypothesis-forming years. 2024 is the key full-year stress check. 2026YTD is diagnostic only because 120d labels are immature.

Passing this gate does not authorize production changes. It only justifies one later narrow validation PR. Failing any condition stops the position-gate path unless a correctness bug is found.

## Outputs

`scripts/low_value_gate_ablation.py` writes:

- `*_events.csv`: A/B date-level selections and returns;
- `*_baseline_parity.csv`: exact channel/date selection parity;
- `*_paired.csv`: per-date A/B return delta and selection overlap;
- `*_switch_cases.csv`: added/removed symbols with forward return/excess;
- `*_switch_symbol_summary.csv`: repeated-symbol concentration among added/removed names;
- `*_arm_summary.csv`: absolute/excess metrics by year/regime/horizon;
- `*_paired_summary.csv`: paired delta, concentration and leave-one-date-out diagnostics;
- `*_report.md`;
- `*_summary.json` with `production_promotion_allowed=false`.

## Git evidence policy

Keep the raw expanded dataset CSV in `outputs/`. Commit only its `.meta.json`, SHA256/row count, the compact parity/paired/summary/report artifacts, and a short decision note.

Do not change `configs/config.risk_off.json` or any production parameter in PR28.
