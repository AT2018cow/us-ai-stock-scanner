# Agent Specification: E4a — Trailing Regime-Indicator Validation (Diagnostic Only, v2)

- **Date**: 2026-10-17 (v2, architect-revised)

- **Companion evidence**: `outputs/m4_revalidation_current_20261016/SUMMARY.md` (E0–E3 scratch study);
  `docs/drawdown_and_bear_replay_20261017/report.md` (forward-drawdown attribution, frozen-grade).
- **Frozen reference study**: `docs/m4_paired_validation_20261015/` (do not modify).
- **Frozen 39-date dataset (`2023-01..2026-03`)**: `outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv` (read-only).
- **Frozen 2022 bear dataset (`2022-01..2022-12`, 12 dates, provenance closed in PR #97/#98)**:
  `outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv` (read-only).
- **Related specs (read first, do not duplicate)**: `docs/agent_specs/regime_extension_replay_spec.md`
  (Route A/B executed; §7 review contract applies to future Modal work, not to this ticket — this ticket is fully offline).
- **Target Execution Agent**: offline implementation + unit tests only; no Git state mutations,
  no network calls, no production code changes.
- **Reviewer / Integrator**: Architect Agent.

---

## 1. Motivation & Intent (bull-attack framing, recorded before the run)

Three findings jointly force this ticket:

1. E1/E2 (SUMMARY.md): within the AI-theme pool, the v2 ranking is anti-predictive at the top
   (tiers 6–30 lag the pool; ENTRY_READY lags WATCH_PULLBACK; extension wins) — on the
   **full 39-date bull-dominated sample**.
2. `drawdown_and_bear_replay_20261017`: on the 8 forward-drawdown dates the ordering
   **flips** — on the FULL universe, FWD_DRAWDOWN_60D: Grade A `+0.37%` / Grade B `+0.63%` /
   Grade C `−2.27%`; ENTRY_READY `+1.96%`, WATCH_BREAKOUT `+2.21%`, TREND_DAMAGED `−2.82%`;
   PRIORITY_REVIEW v2−v1 mean delta `+1.33pp` with severe-loss rate `15.2% → 13.3%`
   (the ~40% relative tail reduction `11.1% → 6.7%` is the ETF-slice 2022-fwd-drawdown TOP15 cell,
   a different cell — cited exactly here). Product behavior is **regime-conditional**, but every
   regime label used so far is either forward-looking (unusable live) or trailing-naive
   (the TRAILING_DOWN TOP15/PRIORITY_REVIEW cells ran `−6%..−8%` because trailing dips in a bull tape
   are rebound markers, not defense markers).
3. `risk_on` autopsy: the old `risk_on`/`risk_off` pair was 16 hard-filter thresholds in the
   scanner's legacy channel path; the decision layer never reads `strategy_style`
   (verified: zero references under `src/ai_value_scanner/decision/**`). Reviving it changes
   **zero** v2 decisions.

**Intent (architect-recorded):** the downstream E4b goal is to strengthen **bull-market attack
capability** — allow more aggressive entry/ordering semantics *only when a validated trailing
indicator says the tape is a confirmed broad, low-vol uptrend*. E3 already closed the
**unconditional** loosening of the extension guard (FAIL: DEV-negative, regime-inconsistent).
E4b's only remaining legitimate shape is **conditional aggression**. E4a is its mandatory first
gate: validate that a trailing-only, live-executable regime indicator has real separation power
**before** any policy is conditioned on it. E4a itself proposes **no policy change**.

**Intent guardrails:**
- The E4a go rule below is deliberately **direction-agnostic** (it asks "does regime conditioning
  have something to work with?", not "does the attack story win?"). The bull-attack intent is
  recorded for E4b's future pre-registration and must NOT steer E4a's reading or acceptance.
- **Attack evidence base is thin**: defense has two eras (2023–2026 dips + 2022 bear); attack has
  exactly one (the 2023–2026 AI mania). Even an E4a GO only licenses a *pre-registered E4b
  experiment with prospective/shadow evidence*; retrospective results can never auto-promote
  (AGENTS.md §8).

---

## 2. Scope & Hard Constraints

### In scope (diagnostic only)
1. Implement `scripts/audit_regime_separation.py` (offline, deterministic, zero network calls)
   that computes the 3 pre-registered trailing-only regime labels (§3) and runs the
   pre-registered separation tests (§4), reusing current-build v1/v2 decisions.
   - **Primary sample = merged BASE_39 + BEAR_2022 (51 dates)**; signal-date overlap across
     inputs is rejected (reuse `validate_disjoint_dates` from `scripts/run_extended_replay_evaluation.py`).
   - **BASE_39-only tables are reported as secondary context** (E1–E3 continuity) and can never
     trigger a go.
   - **Primary universe scope = `ETF_SLICE`** (`watchlist_etf_count >= 1`, the bias-reduced read);
     `FULL` scope is reported as secondary context. Rationale (design calibration, computed
     pre-run from frozen E1/E2 outputs): under the proposed 2pp T1 bar, the perfect forward
     oracle measures 2.46pp on ETF_SLICE (passes) vs 0.73pp on FULL (fails), while the naive
     trailing label measures 0.80pp on ETF_SLICE (fails) vs 3.34pp on FULL (passes as a rebound
     artifact). ETF_SLICE is therefore the only scope where the T1 bar discriminates in the
     intended direction.
   - **Decision rebuild must reuse `build_scope_records` (and, where applicable,
     `cohort_member`) imported from `scripts/run_extended_replay_evaluation.py`** — no duplicated
     decision-rebuild code paths (anti-drift requirement).
2. Unit tests `tests/test_audit_regime_separation.py` (stdlib `unittest`, synthetic frames).
3. Compact evidence under `docs/regime_indicator_validation_20261017/`:
   `separation_summary.csv`, `per_date_regimes.csv`, `tier_by_regime.csv`, `report.md`,
   `SHA256SUMS` (< 140 KB total, no absolute paths).

### Out of scope (hard — violations fail review)
- Any threshold / weight / penalty / policy change, including to entry extension handling.
- Any promotion, shadow, or production implication; E4a output is a go/no-go for a *future*
  E4b ticket only.
- Touching frozen M4 artifacts, the v3 dataset, the 2022 repaired dataset, `src/ai_value_scanner/**`,
  configs, or data files.
- Using forward labels (`fwd_ret_*`, `qqq_return_*`) anywhere except as the *scored outcome*
  (they must never enter an indicator definition). Note: `qqq_trailing_return_60d` is a trailing
  column and is allowed.

---

## 3. Pre-registered Candidate Indicators (exactly 3; R1 is primary)

All definitions use only trailing-observable columns present in both frozen datasets:
`qqq_trailing_return_60d`, `benchmark_trend_ok`, `price_to_sma200`, `volatility_60d`.

- **R0 (status-quo reference)**: the datasets' `regime` column as-is (`up`/`down`).
  Documents what production sees today. No new computation.
- **R1 (primary hypothesis)**: trend + breadth + volatility composite, per signal date `d`:
  - `trend_up(d)` := `qqq_trailing_return_60d(d) > 0`; `trend_down(d)` := `< 0`.
  - `breadth(d)` := share of rows on `d` with finite `price_to_sma200 > 1.0`.
  - `vol_high(d)` := cross-sectional median `volatility_60d` on `d` above its own expanding
    trailing median computed over the **merged, deduplicated, chronologically sorted date
    sequence** (min 6 prior dates; the first 6 merged dates inherit `False`; when only
    `--base-dataset` is supplied the sequence is the 39 base dates).
  - `R1(d) = UPTREND` iff `trend_up` AND `breadth >= 0.50` AND NOT `vol_high`;
    `DOWNTREND` iff `trend_down` AND (`breadth < 0.45` OR `vol_high`); else `NEUTRAL`.
  - Rationale (recorded before running): single-confirmation trailing flags whipsaw
    (the TRAILING_DOWN `−6%..−8%` lesson); multi-confirmation is the only form worth testing.
- **R2 (simplicity challenger)**: `benchmark_trend_ok` as-is (`True`→UPTREND, `False`→DOWNTREND,
  missing→NEUTRAL). Tests whether breadth/vol add anything over the existing flag.

Cutoffs (0.50/0.45) are majority-rule constants, not tuned values; report a ±0.05 sensitivity
column as **diagnostic output only** (it must not select the indicator).

---

## 4. Pre-registered Separation Tests (run once; no iteration)

All tests are computed on the **primary sample (merged 51 dates)** and **primary scope
(`ETF_SLICE`)**, with `FULL` and `BASE_39-only` versions reported as secondary context.
v1/v2 decisions are rebuilt per date via `build_scope_records`.

- **S0 (safety check, hard)**: within the 12 `BEAR_2022` dates, the primary indicator R1 must
  yield **0 UPTREND dates**. Any UPTREND date in the bear sample → **immediate STOP (no-go)**,
  regardless of economics. (For an attack switch, firing in a bear tape is the fatal failure
  mode; this check is pre-registered before the run. R0/R2 UPTREND counts in `BEAR_2022` are
  reported for context only.)
- **T1 (universe separation, loose screen)**: date-equal mean 60d net-QQQ universe excess in UP
  vs DOWN dates; report means, n, bootstrap 95% CI of the difference, LOO-min over dates.
  **Interpretation guardrail (pre-registered): T1 is a loose descriptive screen only — it can be
  passed by sample-specific rebound artifacts and is NOT predictive-validity evidence (see §2
  calibration). T1 alone can never pass the go rule.**
- **T2 (policy-gap separation)**: date-paired v2-minus-v1 TOP15 60d delta (same
  `paired_delta_stats` used in E0) computed **separately** within UP dates and DOWN dates;
  report mean/CI/LOO/positive-share per regime.
- **T3 (tier-inversion separation)**: tier-16–30-minus-universe gap (the E1 headline cell)
  within UP vs DOWN dates; report means and paired t-stat vs that regime's universe.

**"Differs materially" pre-definition (for T2/T3)**: the UP and DOWN regime means differ in
sign, OR |mean(UP) − mean(DOWN)| > 0.02, in the respective metric's units.

**E4b-go rule (all must hold; else STOP, no E4b):**
1. S0 holds (0 UPTREND dates of R1 in `BEAR_2022`);
2. T1 shows |UP − DOWN| > 0.02 on R1 (loose screen; see guardrail);
3. (T2 or T3) "differs materially" (per the pre-definition above) between UP and DOWN on R1
   (i.e., regime conditioning has something to work with);
4. No single date drives any of the above (drop-worst-date re-check keeps the sign of the
   qualifying cells in #2 and #3).
R0/R2 are reported for context only and cannot trigger a go by themselves.
Multiple-comparison note: 3 indicators × 3 tests are reported in full; the go/no-go reads
**only** the pre-declared primary cells above (primary sample, primary scope, R1).

---

## 5. Unit Test Requirements (`tests/test_audit_regime_separation.py`)

Offline, synthetic frames only:
1. R1 labeling: hand-built frames covering trend_up/down × breadth above/below cutoffs ×
   vol_high true/false (incl. the first-6-dates fallback) produce exactly the specified labels.
2. **Merged-sequence vol_high**: verify the expanding trailing median is computed over the
   merged 51-date sequence (2022 dates first), and that `--base-dataset`-only runs use the
   39-date sequence.
3. **S0 safety check**: a synthetic bear sample with a would-be UPTREND date triggers the
   STOP/no-go path; a clean bear sample does not.
4. Missing-data behavior: absent `benchmark_trend_ok` → R2 NEUTRAL; all-NaN vol column →
   `vol_high=False`; empty date → excluded, never imputed.
5. Forward-label firewall: a test asserting the indicator code path never references any
   column whose name starts with `fwd_` or `qqq_return_` (guard against copy-paste leakage
   from attribution scripts).
6. Aggregation math: date-equal means, paired t-stat, and bootstrap CI on a toy frame with
   hand-computed expectations.
7. Output hygiene: rendered CSV/MD contain no absolute paths.
8. Anti-drift: a test asserting `scripts/audit_regime_separation.py` imports and uses
   `build_scope_records` from `scripts/run_extended_replay_evaluation.py` (e.g. a
   monkeypatched equivalence check on a small frame).

---

## 6. Acceptance Criteria (reviewer checks)

1. `python -m unittest discover -s tests` green (full suite, not just the new file).
2. `git status` shows only: this spec, the new script + tests, and the new evidence dir.
   Zero changes under `src/`, `configs/`, `data/`, frozen docs, or `outputs/`.
3. Evidence dir reproduces from scratch by deleting it and re-running the documented single
   command:
   `python scripts/audit_regime_separation.py --base-dataset <frozen v3> --bear-2022-dataset <repaired 2022> --out-dir <docs/regime_indicator_validation_20261017>`.
4. `report.md` contains: the S0 safety-check result stated explicitly (pass/fail); the three
   indicators' UP/DOWN/NEUTRAL date counts (merged primary + BASE_39 secondary); T1–T3 tables for
   all three indicators (primary scope first, FULL secondary); the E4b go/no-go verdict with the
   drop-worst-date check; an explicit statement that no policy change is proposed; and a
   one-line warning that T1 is a loose screen, not predictive validity.
5. Honest-limitation section present: 51 merged dates (39 base / 12 bear-2022) with ~21 trailing-down
   dates; **attack evidence = single bull regime (2023-01..2026-03)**; union-approximation
   universe caveat inherited from both frozen datasets; merged-sequence vol_high warm-up
   disclosure (first 6 merged dates inherit `vol_high=False`); forward labels used as outcomes only.

---

## 7. Review Evidence Contract (no credentialed run required)

This ticket needs **no Modal, no network, no secrets**: the executor runs everything
locally against the frozen CSVs. Review is a code + evidence review:

- Reviewer reruns: `python scripts/audit_regime_separation.py --base-dataset <frozen v3> --bear-2022-dataset <repaired 2022> --out-dir <tmp>`.
- Commit for review: the script, its tests, this spec, and
  `docs/regime_indicator_validation_20261017/` (5 compact files + SHA256SUMS).
- Do NOT commit: dataset CSVs, caches, logs, or anything under `outputs/`.
- Reviewer questions: (a) does any indicator definition touch forward data?
  (b) is the E4b-go rule evaluated exactly as pre-registered (incl. S0 and the T1 guardrail)?
  (c) is the "stop" path (no-go) given equal prominence to "go"?
  (d) is `build_scope_records` reused rather than duplicated?

---

## 8. Architect Decisions (recorded 2026-10-17, before execution)

1. **R1 cutoffs 0.50/0.45**: ACCEPTED as non-tuned majority-rule constants. The
   `vol_high` first-6-dates fallback is retained and disclosed (merged-sequence warm-up).
   Changing cutoffs after seeing results is forbidden.
2. **Materiality bar**: 2pp kept for T1, but T1 is re-classified as a loose descriptive screen
   (see §4 guardrail; calibration: perfect oracle fails FULL, passes ETF_SLICE; naive trailing
   passes FULL as rebound artifact, fails ETF_SLICE). The decisive cells are T2/T3 under the
   pre-defined "differs materially" rule + the drop-worst-date check.
3. **Primary sample/scope changed to merged-51 / ETF_SLICE**; BASE_39-only and FULL are
   secondary context that cannot trigger a go.
4. **S0 safety check added** (0 UPTREND of R1 in BEAR_2022): the 2022 bear sample is deployed
   primarily as the false-positive control for the bull-attack switch, secondarily to raise
   DOWN-side n from 10 to ~21.
5. **Bias guards**: the go rule stays direction-agnostic; the bull-attack intent is recorded
   for E4b's pre-registration and must not steer E4a's reading.
6. **Dec-refresh re-run pre-approved in principle**: when the extension dataset (2026-04..09,
   ～December maturity) lands, re-run E4a **unchanged** on BASE_39 + BEAR_2022 + EXT with the
   same pre-registered rules; no second ticket needed. Until then, no extension work.
7. **E4b entry conditions (recorded now)**: any GO from E4a licenses only a *new pre-registered
   E4b experiment ticket* (bounded variants, DEV-only iteration, single held-out look, then
   shadow). Even an E4b success must go through prospective/shadow evidence before any
   production promotion (AGENTS.md §8); retrospective results cannot auto-promote.
