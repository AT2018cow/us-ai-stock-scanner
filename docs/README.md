# Documentation Index (`docs/`)

This directory separates **active product/architecture contracts and current phase plans** from **completed historical handoffs and experiment protocols**.

## 1. Active Product & Architecture Contracts

- `product_direction_low_frequency_manual_selection.md` — Product north star: low-frequency, human-decision-support stock selection (`Company Quality × Entry Quality → Action List → Detailed Report`).
- `mvp_design_low_frequency_manual_selection.md` — Canonical MVP v1 architecture, `StockDecision` contract, and validation invariants.
- `general_purpose_discovery_and_quality_v2_design.md` — Market-agnostic three-source discovery (`us_core`, `thematic`, `manual`) and business-model-aware Quality v2 design contract.
- `mvp_v2_completion_and_handoff_20261015.md` — **Canonical MVP v2 (M0–M5) completion & internal work-tracking handoff**: PR ledger, data/accounting fixes, `H1-Quality` / `H2-Entry` / `H3-Action` formulas, Report v2 architecture, and M4 dual-track validation results.
- `next_phase_v1_failure_attribution_and_v2_research_plan_20261014.md` — M0–M5 research & validation roadmap (completed 2026-10-15).
- `agent_specs/` — **Parallel-track engineering specs & execution-agent contracts**:
  - `00_parallel_tracks_and_view_ir_contract.md` — Intermediate Presentation IR (`view_model.py`) contract and zero-conflict file boundaries.
  - `track_a_report_readability_v2_spec.md` — Spec for Track A (Report Readability v2 & `view_model.py`).
  - `track_b_m1_data_scope_and_silent_gates_spec.md` — Spec for Track B (M1 Share-Scope Separation & Entry Silent-Gate Completeness).
  - `track_b_m2_failure_attribution_and_metric_audit_spec.md` — Spec for Phase M2 (Systematic v1 Selection Failure Attribution & Metric Validity Audit).
  - `track_b_m3_selection_v2_candidates_spec.md` — Spec for Phase M3 (Pre-Registered Quality/Entry/Action v2 Candidates & Non-Return Preflight).
  - `track_b_m4_paired_validation_and_promotion_gate_spec.md` — Spec for Phase M4 (Dual-Track Paired Validation & Promotion Gate).
  - `daily_cron_scan_and_ttl_spec.md` — Spec for Single-Responsibility Cron Orchestrator (`scripts/run_daily_cron.py` vs `scripts/refresh_sec_cache.py`) & Two-Tier Freshness TTL.
  - `report_review_optimizations_spec.md` — Spec for Pre-Earnings Window Warning + Priority Penalty, 60d/SMA200 Extension Score Deduction, Reverse-Split Share Discontinuity Guard & Pool/Concentration Disclosure.
  - `nonoperating_gain_defense_spec.md` — Spec for Three-Layer Non-Operating Investment Gain & Tax Distortion Defense (`GOOG`, `ZM`, `NTNX`, `AMZN`, `WDC`, `SHOP`, `SNPS`).

## 2. Active Policy & Operational Specs

- `company_quality_v1_policy.md` — Pre-registered Company Quality v1 components, thresholds, and coverage rules.
- `entry_quality_v1_policy.md` — Pre-registered Entry Quality v1 states and readiness rules.
- `mvp_candidate_universe_provenance.md` — Candidate universe provenance and `universe_exclusions.jsonl` contract.
- `general_discovery_implementation.md` — Multi-source discovery implementation specification.
- `mvp_full_scan_acceptance.md` — Full-scan execution and validator acceptance contract.
- `sec_edgartools_live_fallback.md` — Exact-filing EdgarTools fallback specification for live SEC gaps.
- `research_evidence_workflow.md` — Append-only `evidence-observations` branch workflow and SHA256 pinning rules.
- `identity_version_consistency/design_v0.md` — P0 financial-data identity, L0/L1/L2 provenance hashes, and `UNCOMPARABLE` audit state specification.
- `business_model_quality_v0/` — 11-company cross-business-model accounting semantics research and entry diagnostics.

## 3. Current Baseline Reviews & Decisions

- `m0_baseline_review_20261014/` — **Phase M0 deliverable set**: `baseline_inventory.md`, `human_review_worksheet.csv` (18 stratified cases), `attention_failure_cases.md` (3 failure families + M1 correctness contract), and `review_gate.json`.
- `m2_v1_failure_attribution_20261015/` — **Phase M2 deliverable set**: 8-axis quantitative failure attribution across `snap62`, `snap510`, and 25,025 historical rows (`attention_failure_attribution.md`, `component_and_routing_diagnostics.csv`, `metric_and_routing_diagnostics.csv`, `v1_failure_casebook.csv`, `case_registry_frozen.json`, `report_evidence_parity_checks.json`, `hypothesis_backlog.md`, `SHA256SUMS`).
- `m3_candidate_preflight_20261015/` — **Phase M3 deliverable set**: Pre-registered `H1-Quality`, `H2-Entry`, `H3-Action`, and `v2_combined` non-return preflight and 38-case verification (`m3_preregistration_protocol.json`, `m3_preflight_comparison.csv`, `m3_casebook_verification.csv`, `m3_top15_diff_snap62_and_snap510.csv`, `m3_preflight_report.md`, `SHA256SUMS`).
- `m4_paired_validation_20261015/` — **Phase M4 deliverable set**: Dual-track validation (Human Utility + Paired Economics across `DEV_2023_2024`, unsealed `POST2024_HELD_OUT`, and `ALL_39_DATES`) and Gate G4/G5 decision artifact (`m4_human_utility_summary.csv`, `m4_paired_economic_summary.csv`, `m4_year_and_regime_splits.csv`, `m4_promotion_gate.json`, `m4_validation_report.md`, `SHA256SUMS`).
- `review_nonoperating_investment_gain_blind_spot_20261016.md` — Empirical audit of non-operating investment gains & tax distortions (`GOOG`, `AMZN`, `SHOP`, `WDC`, `SNPS`, plus `ZM`/`NTNX`) and the three-layer defense architecture.
- `mvp_v1_strategy_audit_20261011.md` — Descriptive audit of the 2026-10-09 510-symbol v1 snapshot (`313c5ff`).
- `work_handoff_after_pr62_20261013.md` — Baseline summary after Generalized-v0 and PR #62 business-model audit.
- `mvp_v11_pr_a_final_decision_20261014.md` — Formal `NO-GO / KEEP V1` decision for the PR #70 v1.1 historical parameter study.

## 4. Historical Archive (`docs/archive/`)

- `docs/archive/handoffs/` — Earlier milestone handoffs (`work_handoff_after_pr8` through `pr47`, `next_conversation_prompt_20261013.md`).
- `docs/archive/experiments/` — Completed experiment protocols, runbooks (`mvp_v11_*_runbook.md`, `post_pr23/26/27/28`), and earlier refactoring reviews.
