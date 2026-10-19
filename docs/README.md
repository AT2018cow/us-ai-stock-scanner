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
  - `watchlist_refresh_safe_merge_spec.md` — Spec for Safe Additive Watchlist Refresh Merge & Manual/Smallcap Protection (preserve `SRC:*`, `ai_smallcap`, `enabled=0`; auto-archive snapshots).
  - `net_interest_income_exemption_spec.md` — Spec for Net Interest Income Deduction in the Non-Operating Margin Gap (`PLTR` exemption).
  - `watchlist_cik_hygiene_spec.md` — Spec for Automatic CIK-Based Ticker Rename Migration & Delisting Hygiene (`reconcile_watchlist_corporate_actions`).
  - `nonoperating_gain_followup_spec.md` — Spec for the Non-Operating Gain Defense Follow-up tickets (`P1-1`, `P1-3`, `P2-1..P2-4`).
  - `test_cache_isolation_spec.md` — Spec for Test Cache Isolation (unit tests must never write the real `cache/`; tests-only PR).
  - `regime_extension_replay_spec.md` — Spec for Forward-Drawdown Attribution (Route A) & 2022 Tech Bear Replay (Route B) — `scripts/run_extended_replay_evaluation.py`.
  - `growth_compounder_offense_validation_spec.md` — Spec for pre-registered Bull-Market Offense & Slow-Growth De-Crowding Validation (`C1`/`C2`/`C3` vs Gates G1–G4).
  - `report_growth_compounder_offense_track_spec.md` — Spec for Report Layout v2 `Growth Compounder Leaders (Bull Offense Track)` section (dedup vs Secondary Radar + drawdown caveat).
  - `regime_indicator_validation_spec.md` — Spec for E4a Trailing Regime-Indicator Separation Audit (`R0`/`R1`/`R2`; `S0`/`T1`/`T2`/`T3` gates; executed 2026-10-18, verdict `NO-GO`).

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

- [2026-10-18 代码审查与修复交接](code_review_and_repair_handoff_20261018.md) — 8 项缺陷、2 项结构建议、离线复现、DeepSeek 实施边界及 Codex 逐项验收契约（历史基线）。
- [2026-10-18 代码审查修复结果](code_review_repair_results_20261018.md) — R01–R08/A01/A02 实施记录；R03–R05 已完成 Codex 复验，完整测试 1188 项通过。
- `m0_baseline_review_20261014/` — **Phase M0 deliverable set**: `baseline_inventory.md`, `human_review_worksheet.csv` (18 stratified cases), `attention_failure_cases.md` (3 failure families + M1 correctness contract), and `review_gate.json`.
- `m2_v1_failure_attribution_20261015/` — **Phase M2 deliverable set**: 8-axis quantitative failure attribution across `snap62`, `snap510`, and 25,025 historical rows (`attention_failure_attribution.md`, `component_and_routing_diagnostics.csv`, `metric_and_routing_diagnostics.csv`, `v1_failure_casebook.csv`, `case_registry_frozen.json`, `report_evidence_parity_checks.json`, `hypothesis_backlog.md`, `SHA256SUMS`).
- `m3_candidate_preflight_20261015/` — **Phase M3 deliverable set**: Pre-registered `H1-Quality`, `H2-Entry`, `H3-Action`, and `v2_combined` non-return preflight and 38-case verification (`m3_preregistration_protocol.json`, `m3_preflight_comparison.csv`, `m3_casebook_verification.csv`, `m3_top15_diff_snap62_and_snap510.csv`, `m3_preflight_report.md`, `SHA256SUMS`).
- `m4_paired_validation_20261015/` — **Phase M4 deliverable set**: Dual-track validation (Human Utility + Paired Economics across `DEV_2023_2024`, unsealed `POST2024_HELD_OUT`, and `ALL_39_DATES`) and Gate G4/G5 decision artifact (`m4_human_utility_summary.csv`, `m4_paired_economic_summary.csv`, `m4_year_and_regime_splits.csv`, `m4_promotion_gate.json`, `m4_validation_report.md`, `SHA256SUMS`).
- `review_nonoperating_investment_gain_blind_spot_20261016.md` — Empirical audit of non-operating investment gains & tax distortions (`GOOG`, `AMZN`, `SHOP`, `WDC`, `SNPS`, plus `ZM`/`NTNX`) and the three-layer defense architecture.
- `review_nonoperating_gain_defense_followup_20261016.md` — Post-PR #90 (`517e757`) residual-issue list for the three-layer defense (companion to the audit above and `agent_specs/nonoperating_gain_defense_spec.md`): `SHOP`-class quarterly-spike hole, priority items P1-1–P1-3 (next round) and backlog P2-1–P2-4; nothing blocking.
- `drawdown_and_bear_replay_20261017/` — **Forward-Drawdown Attribution (Route A, 39 frozen dates) & 2022 Tech Bear Market Replay (Route B, 12 monthly dates)**: cohort economics, paired `v2` vs `v1` deltas, rank-tier returns, `SMA200` extension / entry-state / quality-grade crosscuts, and `<= -20%` severe-loss rates (`cohort_economics_by_regime.csv`, `paired_deltas_by_regime.csv`, `rank_tiers_by_regime.csv`, `entry_and_extension_crosscut.csv`, `report.md`, `SHA256SUMS`).
- `growth_compounder_offense_validation_20261017/` — **Bull-Market Offense & Slow-Growth De-Crowding Validation (`C1` / `C2` / `C3` across 51 dates, Gates G1–G4)**: paired economics vs `v2_baseline`, bull vs drawdown/2022-bear defense, top-5 contributor exclusion (`EX_TOP5_CONTRIBUTORS`), and `2026-10-15` live snapshot Top-15 comparison (`candidate_cohort_economics.csv`, `paired_deltas_vs_v2.csv`, `robustness_ex_top5_and_episodes.csv`, `snap_20261015_top15_comparison.csv`, `report.md`, `SHA256SUMS`).
- `regime_indicator_validation_20261017/` — **Trailing Regime-Indicator Separation Audit (E4a, pre-registered, verdict `NO-GO`)**: trailing-only `R0`/`R1`/`R2` regime labels plus pre-registered `S0`/`T1`/`T2`/`T3` separation tests on the merged 51-date frozen sample (39 base + 12 bear-2022; primary scope `ETF_SLICE`); no policy change proposed and no E4b ticket opened (`report.md`, `separation_summary.csv`, `per_date_regimes.csv`, `tier_by_regime.csv`, `SHA256SUMS`).
- `mvp_v1_strategy_audit_20261011.md` — Descriptive audit of the 2026-10-09 510-symbol v1 snapshot (`313c5ff`).
- `work_handoff_after_pr62_20261013.md` — Baseline summary after Generalized-v0 and PR #62 business-model audit.
- `mvp_v11_pr_a_final_decision_20261014.md` — Formal `NO-GO / KEEP V1` decision for the PR #70 v1.1 historical parameter study.

## 4. Historical Archive (`docs/archive/`)

- `docs/archive/handoffs/` — Earlier milestone handoffs (`work_handoff_after_pr8` through `pr47`, `next_conversation_prompt_20261013.md`).
- `docs/archive/experiments/` — Completed experiment protocols, runbooks (`mvp_v11_*_runbook.md`, `post_pr23/26/27/28`), and earlier refactoring reviews.
