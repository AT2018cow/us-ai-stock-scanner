# MVP v2 Completion & Internal Work-Tracking Handoff (M0–M5)

> **Date**: 2026-10-16
> **Status**: **M0–M5 + Post-Review Production Hardening COMPLETE** (`895` unit tests passing on `main`)
> **Roadmap Executed**: `docs/next_phase_v1_failure_attribution_and_v2_research_plan_20261014.md`

---

## 1. Milestone & PR Ledger (M0–M5 & Production Rollout)

| Phase / Track | PR & `main` Commit | `evidence-observations` Commit | Core Deliverable & Outcome |
| :--- | :--- | :--- | :--- |
| **Roadmap & Housekeeping** | PR #71 (`42f21c5`), PR #72 (`1a2612e`) | — | Merged M0–M5 roadmap; archived superseded handoffs/configs/snapshots; closed PR #67. |
| **Phase M0 — Baseline & Usage Audit** | PR #73 (`ef9cc55`) | `e4028d1d1b0fca1ac7a189ab6c311e65259a082e` | `docs/m0_baseline_review_20261014/`: 18-case stratified human review worksheet, 3 failure families, and M1 correctness gate. |
| **Parallel Specs (Track A + Track B)** | PR #74 (`64876a8`) | — | `docs/agent_specs/`: Presentation IR (`view_model.py`) contract and zero-conflict parallel track specs. |
| **Track A — Presentation IR & Report v2** | PR #75 (`3b6c0e8`) | — | `src/ai_value_scanner/decision/view_model.py`, `layout_version="v2"` in `reporting/decision.py`, `scripts/render_snapshot_preview.py`. |
| **Phase M1 — Share-Scope & Silent Gates** | PR #76 (`ff26ed5`) | — | Separated `POINT_IN_TIME_SHARES_TAGS` vs `WEIGHTED_AVERAGE_SHARES_TAGS` in `fundamentals/shares.py`; eliminated all silent non-ready gates in `decision/entry.py`. |
| **Phase M2 / M2.1 — v1 Failure Attribution** | PR #77 (`f3d12e0`), PR #78 (`238afe0`) | `b5621e75e778a8db988d9466f809fce9853f5ee3` | `docs/m2_v1_failure_attribution_20261015/`: 8-axis metric audit, 6-pillar Quality decomposition, 6-bucket industry bias table, 38-case 36-col casebook, and parity checks. |
| **Phase M3 — v2 Candidate Policies & Preflight** | PR #79 (`dca24b6`) | `8c9864b7d1e96773d98c67cb651e56348ef08c8c` | `H1-Quality` (`quality.py`), `H2-Entry` (`entry.py`), `H3-Action` (`action.py`), `integrated.py` wiring, and `docs/m3_candidate_preflight_20261015/`. |
| **Phase M4 — Dual-Track Paired Validation** | PR #80 (`374ea90`) | `e976300de2b5a6de92c81b9aa2202cc5834965b5` | `docs/m4_paired_validation_20261015/`: Track 1 Human Utility (`PASS`) + Track 2 Paired Economics across `DEV_2023_2024`, unsealed `POST2024_HELD_OUT`, and `ALL_39_DATES`. |
| **Phase M5 — CLI & Shadow Snapshot Wiring** | PR #81 (`e4c17cf`), PR #82 (`355f55b`) | — | Added `decision_policy_version`, `report_layout_version`, and `enable_v2_shadow` to `ScanConfig`, `write_decision_snapshot`, and `run_scan.py`, plus full user/internal documentation. |
| **Production Default v2 & SEC Cache Persistence** | PR #83 (`6e59510`) | — | Switched `config.risk_off.json`, `config.risk_on.json`, and `config.strict_candidate.json` defaults to `v2`; persisted EdgarTools 10-Q fallback and terminal-pending checks in `parsed_fund_{cik}.json` (`PARSED_FUND_CACHE_VERSION = 9`). |
| **Daily Cron Orchestrator & Two-Tier TTL** | PR #84 (`1e0a861`), PR #85 (`9c94940`) | — | Separated pure `scripts/refresh_sec_cache.py` (`run_sec_prewarm`) from dedicated `scripts/run_daily_cron.py` (`--max-age-hours 4.0`, `--alpaca-ttl-sec 3600`, `allow_existing_decision_snapshot=True`, `outputs/decisions/latest_<style>.json` pointer, and `21600s` [6h] interactive TTL). |
| **Post-Review v2 & Report Enhancements** | PR #86 (`0200825`) | — | Added pre-earnings window warning (`pre_earnings_window_risk` at `70..400d` + `-0.06` priority penalty), 60d/SMA200 extension score deduction (`price_extended_above_sma200`, `return_60d_extended`), reverse-split share discontinuity guard (`shares_yoy_split_or_basis_discontinuity`), and `Pool & Concentration` disclosure. |

---

## 2. Summary of Technical Updates in MVP v2

### 2.1 Data & Accounting Scope Integrity (Phase M1)
1. **Point-in-Time vs Weighted-Average Share-Count Separation (`src/ai_value_scanner/fundamentals/shares.py`)**:
   - Split SEC share-count tags into `POINT_IN_TIME_SHARES_TAGS` (`EntityCommonStockSharesOutstanding`, `CommonStockSharesOutstanding`, `CommonStockSharesIssued`) for market-cap / valuation denominators and `WEIGHTED_AVERAGE_SHARES_TAGS` (`WeightedAverageNumberOfDilutedSharesOutstanding`, `WeightedAverageNumberOfSharesOutstandingBasic`) for YoY dilution (`shares_yoy`).
   - Added `select_consistent_share_records` to require basis and tag consistency between current and prior-year share records, resolving the `HEI` dual-class 55M vs 139M share-count alternation bug (`+154%` fake dilution).
2. **Complete Non-Ready Entry Gate Transparency (`src/ai_value_scanner/decision/entry.py`)**:
   - Every `WATCH_BREAKOUT` and `TREND_DAMAGED` decision now emits explicit negative `EvidenceItem`s for all unmet `ENTRY_READY` conditions (`price_to_sma50_outside_ready_band`, `return_20d_outside_ready_band`, `relative_strength_60d_qqq_below_ready`, `drawdown_from_52w_high_above_ready_cap`, `days_below_sma200_above_ready_cap`, `price_below_sma200_trend`), reducing silent non-ready decisions from `87` (`snap510`) and `11` (`snap62`) to **`0`**.

### 2.2 Key Empirical Findings from Phase M2 Attribution (`docs/m2_v1_failure_attribution_20261015/`)
1. **Why Historical Quality v1 Grade A Underperformed Grade B/C Rebounds**:
   - Out of `2,692` high-growth observations (`revenue_yoy >= 25%`) on the 24 development dates (`2023–2024`), **v1 downgraded 80.7% (`2,173` rows) into Grade B or C (`BC_HIGH_GROWTH`)**, which subsequently generated **`+8.79%` date-equal 60d net QQQ excess**, while leaving Grade A **86.5% occupied by low-growth mature stocks (`A_LOW_GROWTH`, `3,330` rows)** with **`-2.26%` 60d net QQQ excess**.
2. **Root Causes of v1 Misgrading and Attention Misallocation**:
   - **Axis 1 (`abs(accrual_ratio)` Sign-Inversion Bug)**: `quality.py` scored `abs((Adjusted NI - OCF) / Current Assets)`, penalizing cash-cow companies whose operating cash flow exceeded net income (`accrual_ratio < 0`). Across all 39 historical dates, **6,930 observations (`3,997` on dev dates, `110` on `snap510`, `17` on `snap62` including `META, EOG, CRM, MSFT, AMT`)** were falsely penalized despite `OCF/NI >= 1.0` and `FCF > 0`.
   - **Axis 2 (High-Growth Working-Capital Time-Base Mismatch)**: Subtracting TTM revenue YoY from quarter-end point-in-time receivables/inventory YoY mechanically penalized **30.4% (`363 / 1,194`)** of high-growth cash-generative leaders (`revenue_yoy >= 25%`, `OCF/NI >= 0.80`, including `NVDA, MU, AVGO, TER`).
   - **Axis 3 & 4 (Binary `FCF > 0` & Self-History Valuation Drag)**: `958` thin-margin (`< 3%`) rows scored `1.0` on binary `FCF > 0`, while `60.6%` (`364 / 601`) of `PRIORITY_REVIEW` stocks carried `ps/pe_hist_percentile_weak` flags simply for being in multi-year uptrends.Meanwhile, `operating_margin` (`86.2%` coverage) and `fcf_margin` (`88.8%` coverage) were computable from existing SEC facts with zero extra network calls.
   - **Axis 5, 6, 8 (Entry Pullback Dead-Zone, `WATCH_BREAKOUT` Heterogeneity, and MA Inversion)**: `626` rows across 39 dates (`411` on dev dates) in the `(1.08, 1.10]` SMA50 or `(12%, 15%]` `return_20d` seam were misrouted to `WATCH_BREAKOUT` instead of `WATCH_PULLBACK`; `50.4%` of `WATCH_BREAKOUT` rows were lagging structures (`-2.17%` 60d excess) vs `40.4%` near-breakout consolidations (`+0.29%` 60d excess); and `7.9%` (`140 / 1,781`) of `ENTRY_READY` rows had inverted moving averages (`SMA50 < SMA200`).
   - **Axis 7 (Top-15 Truncation & `B + ENTRY_READY` Suppression)**: `18 / 24` dev dates truncated `A + ENTRY_READY` names (`399` truncated across all 39 dates), while `272` high-score `B + ENTRY_READY` observations (`NVDA, MU, AMZN`) were buried in `HOLD_MONITOR` behind `A + WATCH_BREAKOUT` rows.

### 2.3 MVP v2 Selection Engine (`H1-Quality`, `H2-Entry`, `H3-Action` — Phase M3)
Implemented in `decision/quality.py`, `decision/entry.py`, `decision/action.py`, and wired via `policy_version="v2"` in `decision/integrated.py`:
1. **`H1-Quality` (`build_company_quality_v2`, policy `company_quality_v2_2026-10-15`)**:
   - **Sign-Aware Accrual Scoring (`_score_accrual_v2`)**: Scores `accrual_ratio <= 0.0` as `1.0` whenever `ocf_to_net_income >= 0.80` (or unknown), penalizing only positive accruals (`NI > OCF`).
   - **Scale-Normalized Profitability (`fcf_margin` + `operating_margin`)**: Replaces binary `free_cash_flow > 0` with `fcf_margin = free_cash_flow / revenue` (`>= 15% -> 1.0`, `>= 8% -> 0.85`, `>= 3% -> 0.65`, `0..3% -> 0.25 [weak]`, with graceful fallback to `_score_fcf` when `revenue` is absent) and adds `operating_margin = adjusted_ebit / revenue` (`>= 20% -> 1.0`, `>= 12% -> 0.80`) to `profitability_cash`.
   - **High-Growth Working-Capital Exemption**: When `revenue_yoy >= 0.25` and `ocf_to_net_income >= 0.80`, floors `receivables_growth_gap` and `inventory_growth_gap` scores at `0.75` AND exempts them from `severe_checks`, allowing cash-generative high-growth leaders (`MU`, `TER`, `ACLS`, `CARG`) to reach `Quality A`.
   - **Valuation Percentile Floor**: Floors `ps_hist_percentile` and `pe_hist_percentile` at `0.35` when `fcf_yield >= 0.02` or high-growth cash-generative.
   - **Reverse-Split / Share-Basis Discontinuity Guard (PR #86)**: When `shares_yoy < -0.30` or `> 1.00` (outside organic buyback/issuance range, e.g., `AMCR` `-79.9%` after a 1-for-5 reverse split), neutralizes `dilution` pillar to `0.50`, emits `shares_yoy_split_or_basis_discontinuity`, and restricts organic severe dilution checks to `0.15 < shares_yoy <= 1.00`.
   - **Pre-Earnings Window Warning (PR #86)**: When `70 <= age_days <= 400`, emits informational `pre_earnings_window_risk` (without changing `Quality` score/grade/confidence) so downstream ranking and cards highlight imminent quarterly earnings risk.
2. **`H2-Entry` (`build_entry_quality_v2`, policy `entry_quality_v2_2026-10-15`)**:
   - **Pullback Dead-Zone Closure**: Routes healthy-trend stocks whose only readiness failure is `price_to_sma50 > 1.08` or `return_20d > 0.12` directly to `WATCH_PULLBACK`.
   - **Moving-Average Alignment Gate (`sma50_to_sma200 >= 0.98`)**: Computes `sma50_to_sma200 = price_to_sma200 / price_to_sma50`; requires `>= 0.98` for `ENTRY_READY`, emits `sma50_above_sma200_aligned` when `>= 1.00`, and emits `sma50_below_sma200_inverted` when `< 1.00`.
   - **`WATCH_BREAKOUT` Sub-Bucket Differentiation**: Emits `watch_breakout_near_consolidation` vs `watch_breakout_lagging_structure` (`-0.10` score penalty on lagging structures).
   - **Medium-Term Extension Deduction (PR #86)**: Deducts `0.06` (mild: `price_to_sma200 > 1.35` or `return_60d > 0.35`) or `0.10` (severe: `price_to_sma200 > 1.45` or `return_60d > 0.45`) from `entry.score` and emits non-blocking `price_extended_above_sma200` / `return_60d_extended` risk items while preserving `EntryState.ENTRY_READY`.
3. **`H3-Action` (`map_action_state_v2` & `assign_action_priorities_v2`)**:
   - **High-Conviction `B + ENTRY_READY` Promotion**: Promotes `Quality B (score >= 0.68, confidence >= 0.80) + ENTRY_READY (score >= 0.80)` into `ActionState.PRIORITY_REVIEW` with explicit `h3_b_ready_promotion` rationale.
   - **Joint Conviction Ranking + Pre-Earnings Penalty**: Ranks within `PRIORITY_REVIEW` by `0.60 * quality.score + 0.40 * entry.score + 0.04 * I(grade == A) - 0.06 * I(pre_earnings_window_risk)`, and ranks remaining `ENTRY_READY` ahead of `TREND_DAMAGED` inside `HOLD_MONITOR`.

### 2.4 Presentation IR & Report Readability v2 (Track A + PR #86)
Implemented in `src/ai_value_scanner/decision/view_model.py` and `src/ai_value_scanner/reporting/decision.py` (`layout_version="v2"`):
- **Action List v2**: Quick-jump anchor bar, top `- **Pool & Concentration**:` summary line (`watchlist_bucket` + top source ETFs), collapsible `<details>` accordion cards with inline warning badges (`⚠️Pre-Earnings(78d)`, `⚠️Extended(...)`, `⚠️Share-Basis/Split`), per-card `**Pool**:` provenance, cross-pillar `Why Own` highlights, explicit `Entry Gate Check` / `What to Wait For` lines, and compact Secondary Radar summary.
- **Detailed Report v2**: One-screen 6-Pillar Quality Scorecard table, 7-Gate Entry Readiness Checklist table (`PASS`/`WAIT`/`FAIL` with actual vs target values; non-blocking extension warnings never flip passing gates), and collapsible Audit Trail & Provenance sections with relative-only links and zero absolute paths.

### 2.5 Dual-Track Validation Summary (Phase M4 — `docs/m4_paired_validation_20261015/`) & Production Configuration
- **Track 1 (Human Utility)**: `v2_combined` eliminates `100%` (`4,949 -> 0`) of contradictory cash-cow accrual narratives across all 39 dates, eliminates `100%` of silent non-ready gates, raises Top-15 `ENTRY_READY` share (`40.0% -> 66.7%` on `snap62`, `92.4% -> 96.9%` on `POST2024_HELD_OUT`, `90.6% -> 94.7%` on `ALL_39_DATES`), and passes Report v2 parity checks (`0` exceptions, `0` ordering mismatches, `0` absolute paths).
- **Track 2 (Paired Economics)**:
  - On `PRIORITY_REVIEW`, `v2_combined` achieves **`+0.64%` mean / `+1.32%` median 60d paired delta** (`66.7%` win rate, `LOO_min = +0.23%`, `+1.52%` on 120d) on the 15 unsealed `POST2024_HELD_OUT` dates and **`+0.55%` mean delta** (`LOO_min = +0.36%`, `POSITIVE_ROBUST`) across `ALL_39_DATES`, outperforming `v1_baseline` in all 4 calendar periods (`2023`, `2024`, `2025`, `2026Q1`).
  - On `TOP15`, `h2_entry_only` (`+0.34%`, `LOO_min = +0.16%`) and `h3_action_only` (`+0.46%`, `LOO_min = +0.14%`) are `POSITIVE_ROBUST` across all 39 dates, while `v2_combined` achieves `+0.09%` mean / `+0.96%` median (`66.7%` win rate, `+0.94%` on 120d) on `POST2024_HELD_OUT`.
- **Production Default & Backward Compatibility (PR #83–#85)**: Production configs (`configs/config.risk_off.json`, `configs/config.risk_on.json`, `configs/config.strict_candidate.json`) default to `"decision_policy_version": "v2", "report_layout_version": "v2"` with a 6-hour (`21600s`) interactive Alpaca TTL, while `ScanConfig` Python defaults remain `"v1"` so all historical v1 unit tests stay unmodified. Daily scheduled execution runs via `scripts/run_daily_cron.py` (Stage 1 SEC prewarm via `refresh_sec_cache.run_sec_prewarm` at `4.0h` max age + Stage 2 `run_scan` at `3600s` Alpaca TTL, updating `outputs/decisions/latest_<style>.json`).
