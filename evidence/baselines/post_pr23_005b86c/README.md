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

## PR27 score-weight audit note

The historical replay, anchored OOS returns and survivor datasets remain valid.
Only the old offline score-weight sweep candidate-zero interpretation is
invalidated: `sweep_score_weights.py` normalized component columns correctly
but failed to multiply those normalized axes by the configured production base
weights before applying candidate multipliers. PR27 corrects the formula to
`production_base_weight * candidate_multiplier`.

Until the two cheap candidate-zero sweeps are rerun, do not cite
`weightsweep_parity_risk_off_results.csv` or
`weightsweep_parity_risk_on_results.csv` as current-config parity evidence.

A second PR27 audit finding affects the original `weight_dataset_risk_on.csv`: the extractor did not pass `strategy_style` to `partition_filter_steps`, so the old risk_on extraction used the default risk_off hard/soft partition. Because risk_on can configure risk_off-style conditions as soft criteria, the old risk_on dataset may have incorrectly hard-excluded rows and is **not canonical for survivor-ranking/IC research**. The risk_off dataset is unaffected by this specific bug. Rebuild risk_on only with the corrected extractor before PR27 attribution. Production replay/tuner evidence is unaffected.

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
- `pr28_position_ablation/` — single risk_off low_value expanded-dataset
  rebuild (meta + SHA256/rows only; raw CSV off-repo) plus compact
  parity/paired/summary/report artifacts and a hard-stop decision note.
  Baseline ordered parity reached 114/126 with 12 Top-10 boundary swaps,
  so B-arm returns are quarantined per protocol; see
  `decision_note_hard_stop.md`.
- `pr30_single_range_gate/` — same-state single-gate rerun after fixing a
  research-tooling bug (dataset `channel` column leaked into research
  assessment, +0.7/priority flip for ai_enabler rows; production has no
  channel at assessment). Same-state oracle parity is 168/168; the
  single-gate B-arm then fails substantively (2024 −0.01%, 2025 −0.56%,
  pooled CI covers zero). **Provenance correction:** this bundle was first
  produced from a dirty working tree while HEAD still pointed at the PR30
  merge; a clean-checkout rerun on `39e46a5`
  (`git_worktree_clean=true`, manifest commit/tree SHA verified) reproduced
  it byte-identically except the manifest itself, so the bundle is canonical.
  See `decision_note.md` and `provenance_correction.md`.
- `weightsweep_parity_*` — **superseded pre-PR27 artifacts**. PR27 audit found that the old offline sweep applied multiplier=1 without first multiplying by each channel's configured production base-weight vector. Do not use the recorded candidate-zero scores for research conclusions; rerun candidate zero with the corrected sweep before any weight study.
- `research_decision.md` — conclusions, limits, next hypotheses.
- `portfolio_viability_stage1/` — Stage 1 offline list-triage from canonical replay evidence: momentum vs industry_trend vs a 50/50 signal-level proxy, with annual/regime stability, date/symbol/channel concentration, selected-set overlap/turnover proxy, style similarity, provenance manifest, and the frozen two-candidate decision. **Not account NAV or fresh OOS evidence; no production change/replay/tuning.**
