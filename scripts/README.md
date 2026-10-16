# Scripts Index (`scripts/`)

 CLI entrypoints and research utilities organized by functional role. Note: existing filenames in `scripts/` are preserved at their current paths where referenced by `tests/`.

## 1. Core MVP Execution & Validation

- `run_daily_cron.py` — Dedicated daily cron orchestrator: Stage 1 SEC parsed-cache prewarm (`run_sec_prewarm`) + Stage 2 MVP v2 scan (`run_scan(..., allow_existing_decision_snapshot=True)` with `3600s` Alpaca freshness window and `outputs/decisions/latest_<style>.json` pointer).
- `run_mvp_full_scan.py` — Run end-to-end MVP scan emitting `decisions.jsonl`, `action_list.md`, `weekly_review.md`, `detailed/*.md`, and `run_manifest.json`.
- `render_snapshot_preview.py` — Offline preview CLI to re-render any existing decision snapshot into Report Layout v2 (`action_list_v2.md`, `weekly_review_v2.md`, `detailed_v2/*.md`).
- `validate_mvp_snapshot.py` — Validate decision snapshot integrity, renderer consistency, and provenance completeness.
- `audit_mvp_strategy_snapshot.py` — Read-only cross-sectional audit of an MVP decision snapshot.
- `m0_build_baseline_review.py` — Deterministic read-only builder for Phase M0 baseline inventory, 18-case human review worksheet, attention failure families, and M1 gate.
- `preview_discovery_sources.py` — Preview and verify multi-source candidate discovery unions (`us_core`, `thematic`, `manual`).
- `validate_small_scale.py` — Small-scale smoke test runner.

## 2. Data, SEC Cache & Watchlist Maintenance

- `refresh_sec_cache.py` — Prewarm and validate SEC submissions / Company Facts caches with periodic accession parity checks.
- `diagnose_sec_with_edgartools.py` — Bounded SEC / EdgarTools diagnostic utility.
- `audit_nonop_gain_screen.py` — Read-only, cache-only post-earnings-season audit for non-operating gain / tax distortion candidates (TTM margin-gap + latest-quarter spike lenses; no network, no scan/report side effects).
- `refresh_ai_watchlist.py` — Refresh ETF-seeded AI thematic watchlist snapshot.
- `export_generalized_pit_bars.py` — Export point-in-time market bar diagnostics.

## 3. Historical Decision & Cohort Evaluators

- `evaluate_company_quality.py` — Evaluate Company Quality v1 cohorts across historical decision snapshots.
- `evaluate_entry_quality.py` — Evaluate Entry Quality v1 states and transitions conditional on Quality.
- `evaluate_action_states.py` — Evaluate integrated Action states and attention-cap cohorts.
- `research_generalized_selection.py` — Generalized-v0 multi-dimension research harness.
- `audit_liquidity_gate_bias.py` — Audit IEX dollar-volume gate coverage and proxy agreement.
- `repair_equity_discontinuity.py` — Repair split/corporate-action label discontinuities on historical datasets.

## 4. Completed Historical Experiment Utilities

- **PR #70 (MVP v1.1 Historical Optimizer — Closed `NO-GO / KEEP V1`)**:
  - `mvp_v11_a0.py`, `mvp_v11_b0_parity.py`, `mvp_v11_data_risk_audit.py`, `mvp_v11_sec_pit_audit.py`, `mvp_v11_candidate_preflight.py`, `mvp_v11_event_exposure_preflight.py`, `mvp_v11_dev_return_experiment.py`
- **Legacy Pre-MVP / Gate Ablation / Weight Sweeps**:
  - `extract_weight_dataset.py`, `modal_baseline_executor.py`, `modal_executor.py`, `low_value_gate_ablation.py`, `low_value_gate_attribution.py`, `low_value_single_gate_ablation.py`, `sweep_score_weights.py`, `tune_parameters.py`, `ic_analysis.py`, `refactor_baseline.py`, `fast_strategy_gate.py`
- `scripts/archive/` — Retired root-level legacy helpers (`analyze_scan.py`, `extract_all_candidates.py`).
