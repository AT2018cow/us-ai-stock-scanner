# Post-PR23 baseline evidence

RUN_ID: `post_pr23_baseline_202610`
Code: experiment run on Modal at `26f93e4` (PR #25 merge); tuner delivery
resilience fix `005b86c` changes orchestrator placement only — candidate
evaluation math is unchanged. Production configs **unchanged**; no `--promote`.

Source working area (gitignored): `outputs/post_pr23_baseline_202610/`
Remote raw store: Modal volume `ai-scanner-research:/post_pr23_baseline_202610`
(checkpoints kept there for resume; not a review artifact).

## Evidence class

1. `*_summary.csv` / `_by_year.csv` / attribution CSVs — **retrospective**
   (current frozen configs over 2023-01-01 → 2026-09-30; useful for paired
   comparison, **not automatically OOS**).
2. `anchored_oos_fold_summary.csv` (+ risk_off/risk_on tuner
   results/summary/report) — anchored walk-forward with label purge; only
   this class may be called anchored OOS. Both runs conclude
   `promotion_eligible=False`.

## Reproduction reference (foreground only)

```bash
RUN_ID=post_pr23_baseline_202610
MODAL_PROFILE=infi .venv/bin/python -m modal run \
  scripts/modal_baseline_executor.py --run-id "$RUN_ID" --stage replay --styles risk_off,risk_on
MODAL_PROFILE=infi .venv/bin/python -m modal run \
  scripts/modal_baseline_executor.py --run-id "$RUN_ID" --stage dataset --styles risk_off,risk_on
MODAL_PROFILE=infi MODAL_TUNER_CONCURRENCY=40 .venv/bin/python scripts/tune_parameters.py \
  --base-config outputs/$RUN_ID/frozen_inputs/config.risk_off.json \
  --param-space configs/tuner.param_space.json \
  --outputs-dir outputs/$RUN_ID/tuner_risk_off --work-dir outputs/$RUN_ID/tuner_work_risk_off \
  --windows "2023:2023-01-01:2023-12-31,2024:2024-01-01:2024-12-31,2025:2025-01-01:2025-12-31,2026YTD:2026-01-01:2026-09-30" \
  --selection-mode walk_forward --rebalance-frequency monthly --max-candidates 36 \
  --random-seed 42 --watchlist-csv-path data/ai_watchlist.csv \
  --watchlist-history-dir data/watchlist_history --pre-snapshot-universe union \
  --no-latest-watchlist-fallback --no-prune-backtest-artifacts --no-promote --executor modal
# risk_on: same with config.risk_on.json / tuner.param_space.momentum.json /
# tuner_risk_on outputs. Total in-flight candidate containers ≤ 80.
```

## Limitations (see research_decision.md §4 for detail)

- IEX volumes are tape-proxy, not real liquidity; cumulative diagnostics are
  not account NAV; universe is the fixed current pool with union
  approximation before 2026-09-22 snapshots; SEC live-data drift exists
  (documented 1-symbol diff at the final unpriced date); held-out samples
  are small.

## File index

- `baseline_manifest.json` — SHA, frozen-input hashes, provenance, settings.
- `replay_*` — compact replay summaries/segments/diagnostics/reports/network
  per style plus signals/events/benchmarks (review-sized).
- `weight_dataset_*.meta.json` + `weight_dataset_sha256.txt` — dataset
  metadata, SHA256 and row counts (raw 55/63 MB CSVs stay off-repo).
- `current_config_replay_summary.csv`, `current_config_replay_by_year.csv`,
  `selection_attribution_*.csv`, `paired_style_diff.csv` — replay + attribution.
- `anchored_oos_fold_summary.csv` (+ `.meta.json`) — 12 held-out folds.
- `tuner_*_results.csv`, `tuner_*_summary.json`, `tuner_*_report.md` —
  compact tuner evidence per style.
- `weightsweep_parity_*` — sweep candidate-zero offline baselines.
- `research_decision.md` — conclusions, limits, next hypotheses.
