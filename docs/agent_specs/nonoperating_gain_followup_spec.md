# Agent Specification: Non-Operating Gain Defense Follow-up (P1-1, P1-3, P2-1..P2-4)

- **Date**: 2026-10-16
- **Companion Review**: `docs/review_nonoperating_gain_defense_followup_20261016.md`
- **Baseline**: `main` @ `517e757` (PR #90)
- **Target Execution Agent**: DeepSeek (implementation + unit tests only; no Git state mutations or live network calls)
- **Reviewer / Integrator**: Architect Agent

---

## 1. Scope & Motivation

Following PR #90 (`517e757`), `docs/review_nonoperating_gain_defense_followup_20261016.md` identified six concrete follow-up items (`P1-1`, `P1-3`, `P2-1`, `P2-2`, `P2-3`, `P2-4`, plus the `P1-2` verification checklist):

1. **P1-1 — Layer-1 Case C: Single-Quarter Non-Operating Spike Trigger (`SHOP` class)**:
   - When a company books a massive single-quarter unrealized investment gain (`SHOP` 2026-Q2: `+$1.287B` `NonoperatingIncomeExpense` on `$3.583B` quarterly revenue = `35.9%`), an earlier quarter's unrealized loss (`2026-Q1`: `-$1.016B`) can offset it in the 4-quarter TTM sum (`net_margin 15.14% - operating_margin 14.51% = +0.63pp < 5.0pp`).
   - Add **Case C** to Layer 1 so single-quarter `NonoperatingIncomeExpense / quarterly Revenue >= 25%` with an absolute dollar floor `>= $200M` (matched to the latest reconstructed revenue quarter so stale 2018/2022 facts stay silent) emits `nonoperating_gain_inflation` and applies the same `-0.06` priority penalty and `⚠️NonOp-Gain` badge.
2. **P2-3 — Traceable Operating-Basis Growth Substitution & Turnaround Guard**:
   - When Layer 1 substitutes `adjusted_ebit_yoy` / `ebit_yoy` for `adjusted_net_income_yoy` without `nonoperating_gain_inflation` (or alongside Case C), tighten the standalone YoY-gap rule so near-zero-EBIT turnarounds are not boosted (`operating_margin >= 0.10` and `abs(ebit_yoy_val) <= 2.00` when `not nonop_inflated`), and emit a non-penalizing informational risk/watchout item `operating_growth_basis_substituted` so the report explicitly explains why operating-income growth is shown instead of distorted GAAP NI YoY.
3. **P2-2 & P1-2 — True Re-Scoring & Highlight Synchronization in `render_snapshot_preview.py --recompute-v2`**:
   - Eliminate preview/live contradictions (`ZM` showing `⚠️NonOp-Gain` next to old `Margin 65.2% / EPS YoY +174.0%`, `SHOP` showing `-15.4%` instead of `+51.3%`) by updating `_with_quality_v2_adjustments` (and enriching from local `cache/parsed_fund_*.json` + `cache/facts_*.json` when available) so `--recompute-v2` reflects clean operating margins, clean operating growth rates, and Case C quarterly triggers.
4. **P2-1 — Surface Quality-Integrity Deprioritized Names in `action_list_v2.md`**:
   - Add a compact disclosure line under `Pool & Concentration` (or `Secondary Radar`) listing `PRIORITY_REVIEW` / `WATCH_*` candidates carrying `nonoperating_gain_inflation` that were pushed outside the Top-15 Action List (e.g., `ZM`, `GOOG`, `SHOP`, `WDC`, `AMZN`, `NTNX`), so the human researcher can see which notable names were deprioritized on quality-integrity grounds.
5. **P1-3 — Offline Read-Only Universe Screen Script (`scripts/audit_nonop_gain_screen.py`)**:
   - Promote the ephemeral `/tmp` screen into a tested, read-only, cache-only CLI script `scripts/audit_nonop_gain_screen.py` implementing both the TTM margin-gap lens and the P1-1 quarterly-spike lens.
6. **P2-4 — Sync `docs/review_nonoperating_investment_gain_blind_spot_20261016.md` §8 with As-Built**:
   - Record T3 as deferred with rationale and align §8 with the as-built constants.

---

## 2. Detailed Design

### 2.1 `src/ai_value_scanner/scanner.py` — Extract Latest Quarterly Non-Operating Income & Revenue

1. Define tag list near `NONRECURRING_GAIN_TAGS`:
   ```python
   NONOPERATING_INCOME_TAGS = [
       "NonoperatingIncomeExpense",
   ]
   ```
2. Add a pure helper function in `src/ai_value_scanner/scanner.py`:
   ```python
   def extract_latest_quarterly_nonop_metrics(
       companyfacts: dict[str, Any],
   ) -> tuple[float | None, float | None, float | None, str | None]:
       """Return (latest_q_nonop_income, latest_q_revenue, latest_q_nonop_to_revenue, latest_q_end).

       Matches NonoperatingIncomeExpense to the exact period_end of the latest
       reconstructed revenue quarter so stale historical tags from prior years
       cannot trigger false positives.
       """
   ```
   - Use `_reconstruct_flow_periods(companyfacts, LIVE_REVENUE_TAGS, "USD")` to obtain `q_rev` (sorted list of `(end_iso, value)`).
   - Use `_reconstruct_flow_periods(companyfacts, NONOPERATING_INCOME_TAGS, "USD")` to obtain `q_nonop`.
   - If `not q_rev` or `not q_nonop`, return `(None, None, None, None)`.
   - Take `rev_end, rev_val = q_rev[-1]`. Look up `rev_end` in `dict(q_nonop)`.
   - If `rev_end` is not in `dict(q_nonop)` or `rev_val is None` or `rev_val <= 0`: return `(None, float(rev_val) if rev_val is not None else None, None, rev_end)`.
   - Otherwise `nonop_val = float(dict(q_nonop)[rev_end])`, `ratio = nonop_val / float(rev_val)`, and return `(nonop_val, float(rev_val), ratio, rev_end)`.
3. In `load_one_fundamental` (`src/ai_value_scanner/scanner.py`), call `extract_latest_quarterly_nonop_metrics(companyfacts)` and store in `result`:
   - `"latest_quarterly_nonoperating_income": latest_q_nonop_income`
   - `"latest_quarterly_revenue": latest_q_revenue`
   - `"latest_quarterly_nonop_to_revenue": latest_q_nonop_to_revenue`
   - `"latest_quarterly_period_end": latest_q_end`
   - Also include `"latest_quarterly_nonoperating_income"`, `"latest_quarterly_revenue"`, `"latest_quarterly_nonop_to_revenue"` in the columns passed through to `build_company_quality_v2` (do **not** bump `PARSED_FUND_CACHE_VERSION = 9`).

---

### 2.2 `src/ai_value_scanner/decision/quality.py` — Layer-1 Case C & Traceable Growth Substitution (`P1-1` & `P2-3`)

1. Add constants near `QUALITY_V2_NONOP_YOY_GAP_MIN`:
   ```python
   QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN: float = 0.25
   QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR: float = 200_000_000.0
   ```
2. **Case C (Single-Quarter Non-Operating Spike Trigger)** in `build_company_quality_v2`:
   - Read:
     ```python
     q_nonop_income = _finite_value(work, "latest_quarterly_nonoperating_income")
     q_nonop_ratio = _finite_value(work, "latest_quarterly_nonop_to_revenue")
     if q_nonop_ratio is None:
         q_rev = _finite_value(work, "latest_quarterly_revenue")
         if q_nonop_income is not None and q_rev is not None and q_rev > 0.0:
             q_nonop_ratio = q_nonop_income / q_rev
     ```
   - After `if (... Case A ...) elif (... Case B ...)`, add `elif`:
     ```python
     elif (
         q_nonop_ratio is not None
         and q_nonop_ratio >= QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN
         and (
             q_nonop_income is None
             or q_nonop_income >= QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR
         )
     ):
     ```
     (Note: allowing `q_nonop_income is None` when a caller explicitly passes pre-validated `latest_quarterly_nonop_to_revenue` is convenient, **except** when `latest_quarterly_nonoperating_income` is provided it **must** be `>= QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR` (`$200M`); even better, require `q_nonop_income is not None and q_nonop_income >= QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR` so the `$200M` floor is strictly enforced!)
     **Strict rule**: Require **both** `q_nonop_income is not None and q_nonop_income >= QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR` **and** `q_nonop_ratio is not None and q_nonop_ratio >= QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN`.
   - When Case C fires:
     - `nonop_inflated = True`
     - If `operating_margin_val is not None and raw_net_margin is not None and raw_net_margin > operating_margin_val`:
       `work["net_margin"] = operating_margin_val`
     - Append `nonoperating_gain_inflation` to `risks`:
       ```python
       risks.append(
           _metric_item(
               code="nonoperating_gain_inflation",
               label="Non-operating gain / tax distortion",
               polarity="negative",
               metric="net_margin",
               value=round(q_nonop_ratio, 6),
               threshold=(
                   "quarterly nonop / revenue "
                   f"< +{QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN * 100:.0f}% "
                   f"(>=${QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR / 1e6:.0f}M)"
               ),
               message=(
                   f"Single-quarter non-operating income is "
                   f"${q_nonop_income / 1e9:.2f}B "
                   f"({q_nonop_ratio * 100:.1f}% of quarterly revenue); "
                   "quarterly mark-to-market investment gains distort GAAP earnings."
               ),
           )
       )
       ```
3. **Traceable Growth Substitution (`P2-3`)**:
   - Tighten the YoY substitution condition in `build_company_quality_v2`:
     ```python
     yoy_gap_triggered = (
         not nonop_inflated
         and operating_margin_val is not None
         and operating_margin_val >= 0.10
         and ebit_yoy_val is not None
         and abs(ebit_yoy_val) <= 2.00
         and ani_yoy_val is not None
         and abs(ani_yoy_val - ebit_yoy_val) >= QUALITY_V2_NONOP_YOY_GAP_MIN
     )
     if (
         ebit_yoy_val is not None
         and ani_yoy_val is not None
         and (nonop_inflated or yoy_gap_triggered)
     ):
         work[earnings_growth_key] = ebit_yoy_val
         if yoy_gap_triggered:
             risks.append(
                 _metric_item(
                     code="operating_growth_basis_substituted",
                     label="Growth scored on operating-income basis",
                     polarity="negative",
                     metric=earnings_growth_key,
                     value=round(ebit_yoy_val, 6),
                     threshold=f"|NI YoY - EBIT YoY| < {QUALITY_V2_NONOP_YOY_GAP_MIN * 100:.0f}pp",
                     message=(
                         f"Growth scored on operating-income basis ({ebit_yoy_val * 100:+.1f}%) "
                         f"because GAAP net-income YoY ({ani_yoy_val * 100:+.1f}%) diverged by "
                         f"{abs(ani_yoy_val - ebit_yoy_val) * 100:.1f}pp due to prior-period "
                         "non-operating or tax base effects."
                     ),
                 )
             )
     ```
   - Note: `operating_growth_basis_substituted` is a trace/watchout item in `risks` (so it appears in Watchouts and Detailed Report), and does **not** carry a priority penalty in `assign_action_priorities_v2`.

---

### 2.3 `src/ai_value_scanner/decision/view_model.py` — Inline Formatting & Quality-Integrity Deprioritized Summary (`P2-1` & `P2-3`)

1. In `_COMPACT_METRIC_LABELS` and `_inline_fragment`:
   - Add `"operating_growth_basis_substituted": "OpInc YoY Basis"` to `_COMPACT_METRIC_LABELS`.
   - In `_inline_fragment(item)`:
     ```python
     if item.code == "operating_growth_basis_substituted":
         return f"Growth on OpInc basis ({format_metric_value(item.metric, item.value)} vs distorted NI YoY)"
     ```
   - For `nonoperating_gain_inflation` in `_inline_fragment(item)` and `_extract_caution_badges(decision)`:
     - Check `"quarterly revenue" in (item.message or "")`:
       - If quarterly trigger (`"quarterly revenue" in (item.message or "")`), badge is `f"⚠️NonOp-Gain(Qtr +{val_num * 100:.0f}% rev)"` and inline fragment is `f"⚠️ Non-Op Gain (Qtr +{val_num * 100:.1f}% of rev)"`;
       - Otherwise keep `f"⚠️NonOp-Gain(+{val_num * 100:.1f}pp)"` and `f"⚠️ Non-Op Gain (+{val_num * 100:.1f}pp vs OpMargin)"`.
2. **P2-1 — Surface Quality-Integrity Deprioritized Candidates**:
   - In `SnapshotViewModel` (`src/ai_value_scanner/decision/view_model.py`), add a field:
     ```python
     deprioritized_quality_integrity_notes: tuple[str, ...] = ()
     ```
   - When building `SnapshotViewModel` in `build_snapshot_view_model(selected, all_decisions, ...)`:
     - Identify decisions in `pool` (`all_decisions` if provided, else `selected`) whose `symbol` is **not** in `primary_symbols` (`{c.symbol for c in primary_cards}`), whose `action_state` is `ActionState.PRIORITY_REVIEW`, and whose `quality.risks` contains `code == "nonoperating_gain_inflation"`.
     - Sort them by `(decision.action_priority or 9999, decision.symbol)`.
     - Format each as e.g. `f"{d.symbol} (#{d.action_priority}, Q:{d.quality.grade.value} {d.quality.score:.2f})"` (up to 10 names).
   - In `src/ai_value_scanner/decision/report.py` (`_render_action_list_v2`), right after the `Pool & Concentration` bullet (or inside the header bullets when `view.deprioritized_quality_integrity_notes` is non-empty), render:
     ```markdown
     - **Quality-Integrity Deprioritized (Off Top-15 via Non-Op Gain Guard)**: ZM (#19, Q:B 0.72), SHOP (#21, Q:A 0.84), GOOG (#31, Q:A 0.73), ...
     ```
     This directly solves `P2-1` with a 1-line transparent summary!

---

### 2.4 `scripts/render_snapshot_preview.py` — Eliminate Preview/Live Contradictions (`P2-2`)

In `scripts/render_snapshot_preview.py`:
1. Add an optional helper `_load_local_cache_enrichment(symbol: str, cache_dir: Path = Path("cache")) -> dict[str, Any]` that (read-only, never modifying cache) looks up `parsed_fund_*.json` matching `symbol` (via a lazy module-level dict cached once per process) and, if `facts_{cik}.json` exists, also computes `extract_latest_quarterly_nonop_metrics(companyfacts)`.
2. In `_with_quality_v2_adjustments(decision: StockDecision)`:
   - Pull `op_margin`, `fcf_margin`, `ani_yoy`, `ebit_yoy`, `q_nonop_income`, `q_nonop_ratio` from decision evidence first, falling back to `_load_local_cache_enrichment(decision.symbol)` when missing in the frozen JSONL!
   - Also check **Case C** (`q_nonop_income >= 200_000_000` and `q_nonop_ratio >= 0.25`) in `_with_quality_v2_adjustments` so `SHOP` gets `nonoperating_gain_inflation` in `--recompute-v2`!
   - When `nonop_gap` (Case A/B) or Case C triggers:
     - If `op_margin is not None` (or `fcf_margin` for Case B), update any existing `net_margin_strong` item in `positives`:
       - If the capped margin `>= 0.12`, replace `net_margin_strong.value` with `round(capped_margin, 6)` (so `ZM` Highlights show `Margin 23.7%` instead of `65.2%`, and `GOOG` shows `Margin 34.0%` instead of `55.7%`!);
       - If the capped margin `< 0.12` (e.g. `NTNX` `9.6%`), remove `net_margin_strong` from `positives`!
   - When `ebit_yoy` is available and (`nonop_inflated` or `yoy_gap_triggered`):
     - Remove `adjusted_net_income_yoy_weak` from `risks` (e.g. `SHOP` `-15.4%` disappears!);
     - Update or replace `adjusted_net_income_yoy_strong` in `positives` with `round(ebit_yoy, 6)` when `ebit_yoy >= 0.15` (so `ZM` Highlights show `EPS YoY +22.0%` instead of `+174.0%`, `GOOG` shows `+24.9%` instead of `+114.7%`, and `SHOP` gains `EPS YoY +51.3%`!).
     - If `yoy_gap_triggered` (without `nonop_inflated`), append `operating_growth_basis_substituted` to `risks`.

---

### 2.5 `scripts/audit_nonop_gain_screen.py` — Read-Only Universe Screen CLI (`P1-3`)

Create `scripts/audit_nonop_gain_screen.py`:
- Read-only, cache-only diagnostic CLI (zero network calls, zero scan/report side effects).
- Arguments:
  - `--cache-dir` (default `"cache"`)
  - `--output-json` (optional path to write JSON report)
  - `--min-ttm-gap` (default `0.05`)
  - `--min-quarterly-ratio` (default `0.25`)
  - `--min-quarterly-abs` (default `200000000.0`)
- Scans all `parsed_fund_*.json` (and corresponding `facts_*.json` when present) in `--cache-dir` and evaluates:
  1. `ttm_margin_gap_hit`: `raw_net_margin >= 0.12`, `(raw_net_margin - operating_margin) >= min_ttm_gap`, `ocf_to_net_income < 1.50` (plus Case B FCF fallback);
  2. `quarterly_spike_hit`: latest quarter `NonoperatingIncomeExpense / quarterly Revenue >= min_quarterly_ratio` and `NonoperatingIncomeExpense >= min_quarterly_abs` on the latest revenue quarter end date;
  3. `disposal_gain_stripped`: `nonrecurring_gain_subtraction > 0`.
- Exposes a pure function `run_nonop_gain_audit(cache_dir: Path, ...) -> list[dict[str, Any]]` so unit tests can test it directly on synthetic fixtures, and prints a clean Markdown table to stdout when run as `main()`.

---

### 2.6 Documentation Updates (`P2-4` & `P1-3`)

1. In `docs/review_nonoperating_investment_gain_blind_spot_20261016.md` §8:
   - Add a dated `As-Built & Follow-Up Sync (2026-10-16)` note recording:
     - T1/T2 implemented via `QUALITY_V2_NONOP_*` (TTM margin gap + Case C quarterly trigger) in `src/ai_value_scanner/decision/quality.py` and `H3_NONOPERATING_GAIN_PRIORITY_PENALTY = 0.06` in `src/ai_value_scanner/decision/action.py`;
     - T3 (`edgartools` mapping spike) formally marked **Deferred (2026-10-16)** because tag-agnostic Layer 1 (Cases A/B/C) supersedes tag-by-tag mapping outsourcing; revisit only if a future filing class escapes both TTM-gap and quarterly triggers.
2. Mention `scripts/audit_nonop_gain_screen.py` in `docs/README.md` or `README.md` as the post-earnings-season read-only audit command.

---

## 3. Unit Test Requirements

Extend `tests/test_nonoperating_gain_defense.py` with tests covering:
1. **P1-1 Case C (Quarterly trigger)**:
   - `SHOP` archetype (`net_margin=15.1%`, `operating_margin=14.5%`, `latest_quarterly_nonoperating_income=1.287e9`, `latest_quarterly_revenue=3.583e9` -> `35.9% >= 25%` and `>= $200M`) triggers `nonoperating_gain_inflation`, caps `net_margin` at `14.5%`, substitutes `ebit_yoy` (`+51.3%`), and receives the `⚠️NonOp-Gain(Qtr +36% rev)` badge and `-0.06` priority penalty.
   - Stale-date / sub-floor guard: fixture where `NonoperatingIncomeExpense` is `< $200M` (e.g., `$150M` even at `40%` ratio) OR where `NonoperatingIncomeExpense` period end (`2022-06-30`) does not match latest revenue quarter end (`2026-06-30`) stays completely silent.
   - `MSFT` (`$3.44B / $90.0B = 3.8%`) and `BILL` controls stay completely clean.
2. **P2-3 Traceable Growth Substitution**:
   - When `not nonop_inflated`, `operating_margin >= 0.10`, `abs(ebit_yoy) <= 2.00`, and `abs(ani_yoy - ebit_yoy) >= 0.40`, `operating_growth_basis_substituted` is emitted and rendered in Watchouts without a `-0.06` priority penalty.
   - Near-zero-EBIT turnaround (`operating_margin = 0.03`, `ebit_yoy = +7.00`) does **not** trigger standalone YoY substitution.
3. **P2-1 & P2-2 Preview / View Model**:
   - `recompute_v2_decisions` updates `ZM` positive `net_margin_strong` to `operating_margin` (`23.7%`) and removes `NTNX` `net_margin_strong` (`9.6% < 12%`), eliminating preview/live contradictions.
   - `SnapshotViewModel.deprioritized_quality_integrity_notes` surfaces off-Top-15 `PRIORITY_REVIEW` names carrying `nonoperating_gain_inflation`.
4. **P1-3 `scripts/audit_nonop_gain_screen.py`**:
   - Unit test `run_nonop_gain_audit` on a temporary directory fixture containing synthetic `parsed_fund_*.json` and `facts_*.json` records.
