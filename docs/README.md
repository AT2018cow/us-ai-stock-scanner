# Documentation Index (`docs/`)

This directory separates **active product/architecture contracts and current phase plans** from **completed historical handoffs and experiment protocols**.

## 1. Active Product & Architecture Contracts

- `product_direction_low_frequency_manual_selection.md` — Product north star: low-frequency, human-decision-support stock selection (`Company Quality × Entry Quality → Action List → Detailed Report`).
- `mvp_design_low_frequency_manual_selection.md` — Canonical MVP v1 architecture, `StockDecision` contract, and validation invariants.
- `general_purpose_discovery_and_quality_v2_design.md` — Market-agnostic three-source discovery (`us_core`, `thematic`, `manual`) and business-model-aware Quality v2 design contract.
- `next_phase_v1_failure_attribution_and_v2_research_plan_20261014.md` — **Current roadmap (M0–M5)**: v1 failure attribution, financial-data integrity, and evidence-gated v2 research plan.
- `agent_specs/` — **Parallel-track engineering specs & execution-agent contracts**:
  - `00_parallel_tracks_and_view_ir_contract.md` — Intermediate Presentation IR (`view_model.py`) contract and zero-conflict file boundaries.
  - `track_a_report_readability_v2_spec.md` — Spec for Track A (Report Readability v2 & `view_model.py`).
  - `track_b_m1_data_scope_and_silent_gates_spec.md` — Spec for Track B (M1 Share-Scope Separation & Entry Silent-Gate Completeness).

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
- `mvp_v1_strategy_audit_20261011.md` — Descriptive audit of the 2026-10-09 510-symbol v1 snapshot (`313c5ff`).
- `work_handoff_after_pr62_20261013.md` — Baseline summary after Generalized-v0 and PR #62 business-model audit.
- `mvp_v11_pr_a_final_decision_20261014.md` — Formal `NO-GO / KEEP V1` decision for the PR #70 v1.1 historical parameter study.

## 4. Historical Archive (`docs/archive/`)

- `docs/archive/handoffs/` — Earlier milestone handoffs (`work_handoff_after_pr8` through `pr47`, `next_conversation_prompt_20261013.md`).
- `docs/archive/experiments/` — Completed experiment protocols, runbooks (`mvp_v11_*_runbook.md`, `post_pr23/26/27/28`), and earlier refactoring reviews.
