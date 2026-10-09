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

## Corrected OOS rescore (PR #26, no new compute)

The original anchored-OOS interpretation used fixed sample-size guardrails
(`min_window_valid_events=20`, `min_total_valid_events=120`) that are
structurally impossible for monthly annual folds (12 signal dates per year).
PR #26 caps absolute targets at 80% of actually-available events and requires
the promotion decision to consider the whole OOS fold sequence (≥2 folds,
≥2/3 passing, ≥2/3 positive excess, final training + held-out pass).

The two existing 36-candidate result files were rescored offline
(`--rescore-results`; no backtests, no SEC/Alpaca, no Modal):

- `oos_rescore_risk_off_report.md` / `oos_rescore_risk_off_summary.json`
- `oos_rescore_risk_on_report.md` / `oos_rescore_risk_on_summary.json`
- `anchored_oos_fold_summary_corrected.csv` (+ `.meta.json`) — 12 folds with
  corrected guardrails (supersedes `anchored_oos_fold_summary.csv` for
  pass/fail interpretation; the return observations are unchanged).

Headline: fold selections are unchanged (selection uses rank score only);
training failures move from impossible sample gates to genuine return
metrics (`avg_excess_vs_qqq_too_low`); 2025 held-out shows +8.0%/+8.5%
excess (PASS) from training-invalid selections, 2026YTD fails on both sample
(4/9 < 8) and excess (−2.0%); all four profiles remain
`promotion_eligible=False`. Instability is real, not gate pollution.

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
- `anchored_oos_fold_summary.csv` (+ `.meta.json`) — 12 held-out folds
  (original guardrails); `anchored_oos_fold_summary_corrected.csv` (+ `.meta.json`)
  — same 12 folds under corrected attainable guardrails (PR #26).
- `tuner_*_results.csv`, `tuner_*_summary.json`, `tuner_*_report.md` —
  compact tuner evidence per style.
- `oos_rescore_*` — corrected offline OOS rescore (PR #26) per style.
- `weightsweep_parity_*` — sweep candidate-zero offline baselines.
- `research_decision.md` — conclusions, limits, next hypotheses.
