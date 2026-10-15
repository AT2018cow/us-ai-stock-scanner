# Phase M2.1 Completion Spec — Full Roadmap Compliance for v1 Failure Attribution

> **Target Agent**: Muse Spark 1.3 (Execution Agent)
> **Reviewer**: Chief Technical Lead / Independent Research Auditor
> **Roadmap Reference**: `docs/next_phase_v1_failure_attribution_and_v2_research_plan_20261014.md` (§4 M2, lines 205–243)

---

## 1. Why M2.1 Is Required Before Starting M3

Chief Architect audit of PR #77 (`docs/m2_v1_failure_attribution_20261015/`) against the authoritative M2 checklist in `docs/next_phase_v1_failure_attribution_and_v2_research_plan_20261014.md` identified **5 specific gaps** that must be completed before Phase M2 can be certified `100% COMPLETE`:

1. **Gap 1 — Full 39-Date Cross-Sectional Coverage + Same-Date Top-15 Opportunity-Cost Pairing (Problem 1)**:
   - While forward-return statistics (`fwd_ret_*`) must remain strictly restricted to the **24 development dates (`2023-01-31..2024-12-31`)**, **cross-sectional feature, grade, state, and Top-15 truncation counts** (which do not touch future returns) must be reported across **all 39 historical signal dates (`2023-01-31..2026-03-31`, 25,025 rows)** as well as the 24 development dates and 2 snapshots.
   - Must also include a **Same-Date Opportunity-Cost / Replacement Comparison** (`same_date_replacement_comparison` in the report and diagnostics): when high-conviction `Quality A + ENTRY_READY` (rank 16+) or `Quality B + ENTRY_READY` (like `NVDA`, `MU`, `AMZN`) are excluded from Top-15, explicitly show the marginal #11–#15 names that took their Top-15 slots on the same date (e.g., slower-growth or valuation-flagged `A + ENTRY_READY` or `A + WATCH_BREAKOUT` names in `snap62` / `snap510` / dev dates) and compare their characteristics and dev-period date-equal 60d excess.

2. **Gap 2 — Full 6-Pillar Company Quality v1 Decomposition Across Grades A / B / C (Problem 2)**:
   - Must decompose **Company Quality v1's 6 canonical pillars**:
     1. `profitability_and_cash_conversion` (weight `0.25`)
     2. `growth_and_stability` (weight `0.20`)
     3. `balance_sheet_resilience` (weight `0.20`)
     4. `dilution_and_capital_discipline` (weight `0.10`)
     5. `valuation_context` (weight `0.10`)
     6. `red_flags` (weight `0.15`)
   - Compute and report the mean pillar score, coverage/missing rate, and weak-flag rate for each of the 6 pillars stratified by `Quality Grade (A, B, C, UNRATED)` across `snap62`, `snap510`, `hist_dev_24_dates`, and `hist_all_39_dates`, plus dev-period 60d excess stratified by high-growth vs low-growth `Quality A` vs `Quality B/C`. This directly answers **why historical Grade A underperformed Grade C rebounds** (low-growth mature companies with cheap self-history valuation percentiles dominating Grade A while high-growth leaders get penalized on `valuation_context` and `red_flags`).

3. **Gap 3 — Cross-Industry / Business-Model Systematic Bias Audit (Problem 4)**:
   - Classify the universe into **6 transparent business-model / sector archetypes** (using existing ticker/sector metadata or deterministic accounting/industry mapping):
     1. `SOFTWARE_AND_ASSET_LIGHT_TECH` (SaaS, internet, cloud, cybersecurity)
     2. `SEMICONDUCTOR_AND_AI_HARDWARE` (semis, semi-cap equipment, networking/compute hardware)
     3. `INDUSTRIAL_AND_MANUFACTURING` (electrical, aerospace, machinery, automation)
     4. `HEAVY_ASSET_AND_UTILITIES` (regulated utilities, telecom, pipelines, transport)
     5. `CYCLICAL_RESOURCES_AND_ENERGY` (oil & gas, mining, materials, chemicals)
     6. `FINANCIALS_AND_SPECIALIST_REITS` (banks, insurers, capital markets, REITs)
   - For each business-model bucket across `snap62`, `snap510`, and `hist_all_39_dates`, report:
     - Total observations, `Quality A / B / C / UNRATED` share, mean confidence, top missing metrics, and top weak-risk flags (`accrual_ratio_weak`, `receivables_growth_gap_weak`, `net_debt_to_ebitda_weak`, `ps_hist_percentile_weak`, `specialist_accounting_unrated`).

4. **Gap 4 — Canonical 36-Column `v1_failure_casebook.csv` Schema + `RETROSPECTIVE_EXPLORATORY` Paired Cases**:
   - The roadmap (`docs/next_phase_v1_failure_attribution_and_v2_research_plan_20261014.md`, lines 221–232) specifies these exact **36 columns** for `v1_failure_casebook.csv`:
     ```text
     study_case_id,case_selection_method,evidence_tier,signal_date,symbol,
     source_snapshot_sha,scanner_code_sha,config_sha,candidate_universe_asof,
     security_id_or_unverified,issuer_cik_or_unverified,filing_accession_or_unverified,
     facts_fingerprint_or_unverified,quality_grade,quality_score,confidence,
     quality_evidence_codes,missing_codes,entry_state,entry_evidence_codes,
     action_state,priority,selected_top5,selected_top15,excluded_reason,
     review_question,observed_failure_hypothesis,alternate_explanations,
     data_verdict,human_review_verdict,review_time_or_unknown,
     future_label_valid,forward_label_definition,realized_outcome_if_exploratory,
     reviewer_notes,source_links
     ```
   - `observed_failure_hypothesis` must use the roadmap's canonical taxonomy tags (`DATA/IDENTITY ERROR`, `ACCOUNTING SEMANTIC GAP`, `EVIDENCE PRESENTATION GAP`, `RANK/CAP STRUCTURAL GAP`, `ENTRY TIMING GAP`, `UNIVERSE/PIT BIAS`, `CORPORATE_ACTION/LABEL UNCERTAINTY`, `IRREDUCIBLE UNCERTAINTY`, or `POSITIVE_CONTROL`).
   - In addition to the 28 `STRATIFIED_PRE` cases and 6 `POSITIVE_CONTROL` cases, include **4 paired `RETROSPECTIVE_EXPLORATORY` cases** on development dates (`2023–2024`) showing both **"selected Top-15 winner/laggard"** and **"rejected/suppressed opportunity on the same date"** (with `realized_outcome_if_exploratory` populated ONLY for `RETROSPECTIVE_EXPLORATORY` dev-date cases, and `"UNPEEKED_PRE_STRATIFIED"` for `STRATIFIED_PRE` / snapshot cases!).

5. **Gap 5 — Missing Standard Files (`component_and_routing_diagnostics.csv` & `report_evidence_parity_checks.json`)**:
   - Generate **`component_and_routing_diagnostics.csv`** (containing the 6-pillar Quality decomposition, Entry sub-gate breakdown across all 39 dates, Cross-Industry Business-Model bias table, and Same-Date Top-15 replacement comparison; you may either keep `metric_and_routing_diagnostics.csv` or unify/emit both so no existing reference breaks).
   - Generate **`report_evidence_parity_checks.json`** (required by roadmap line 242): programmatic verification across `snap62`, `snap510`, and the M1-rebuilt decisions proving whether Action List, Detailed Report, and `StockDecision` are 100% consistent and quantifying pre-M1 vs post-M1 silent-gate parity (`0` silent `WATCH_BREAKOUT` / `TREND_DAMAGED` rows after M1).

---

## 2. Shared-Worktree Rules

- **DO NOT** run `git checkout`, `git switch`, `git branch`, `git add`, `git commit`, `git push`, `git stash`, `git reset`, or `git clean`.
- **DO NOT** make network calls or modify production scoring files (`quality.py`, `entry.py`, `action.py`, `scanner.py`).
- **DO NOT** start M3 yet: finish M2.1 first so M2 is 100% compliant.
- Modify ONLY:
  1. `src/ai_value_scanner/research/m2_failure_attribution.py`
  2. `scripts/m2_build_failure_attribution.py`
  3. `tests/test_m2_failure_attribution.py`
  4. `docs/m2_v1_failure_attribution_20261015/` (including `case_registry_frozen.json`, `v1_failure_casebook.csv` [36 columns], `component_and_routing_diagnostics.csv`, `metric_and_routing_diagnostics.csv`, `report_evidence_parity_checks.json`, `attention_failure_attribution.md`, `hypothesis_backlog.md`, and `SHA256SUMS`; keep total directory size `< 160 KB`).

---

## 3. Verification Commands

```bash
.venv/bin/python scripts/m2_build_failure_attribution.py
.venv/bin/python -m unittest discover -s tests -p "test_m2_failure_attribution.py"
.venv/bin/python -m unittest discover -s tests
```
When all tests pass and all M2 deliverables are updated in `docs/m2_v1_failure_attribution_20261015/`, stop and report for Chief Architect review.
