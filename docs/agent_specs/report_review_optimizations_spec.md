# Report Review Optimizations Spec — Pre-Earnings Window, Medium-Term Extension Deduction, Split Share-Basis Guard & Concentration Disclosure

> **Target Agent**: Muse Spark 1.3 (Execution Agent)
> **Reviewer**: Chief Technical Lead / Architect
> **Base `main` Reference**: Post-PR #85 (`9c94940`)

---

## 1. Objective & User Decisions

Based on real-world review of the `2026-10-15` daily MVP v2 report, we implement four surgical enhancements in the `v2` policy and `v2` report presentation layer (while keeping `v1` 100% untouched and preserving all existing M0–M5 unit test assertions):

1. **Pre-Earnings Window Warning + Priority Ranking Penalty (`Filing Age >= 70d`)**:
   - **User Decision**: Keep `ENTRY_READY` / `PRIORITY_REVIEW` state unchanged; add a prominent **`⚠️Pre-Earnings(<age>d)`** warning badge + `pre_earnings_window_risk` counter-evidence item + a `-0.06` priority-sort penalty in `assign_action_priorities_v2` so stocks with fresh post-earnings filings (`<70d`) rank ahead of stocks entering their imminent quarterly earnings binary window (`>=70d`, e.g. `MSFT 78d`, `AMD 71d`, `FTNT 77d`, `FAST 91d`, `FDS 106d`).
2. **Medium-Term Extension (`60d Return > +35%` or `Price/SMA200 > 1.35x`) Entry Score Deduction + Warning Badge**:
   - **User Decision**: Keep `ENTRY_READY` / `PRIORITY_REVIEW` state unchanged; deduct from `entry.score` in `build_entry_quality_v2` + emit explicit counter-evidence (`price_extended_above_sma200` / `return_60d_extended`) + show **`⚠️Extended(...)`** badge so stocks that rallied `+45%..+53%` over 60 days or sit `1.43x..1.51x` above SMA200 (`CRM`, `FIVN`, `WDAY`, `FTNT`, `AMD`, `MSFT`) no longer get an artificial `1.00` Entry score and rank behind unextended setups (`KEYS`, `ADI`, `EXPE`).
3. **Reverse-Split / Share-Basis Discontinuity Guard (`shares_yoy < -0.30` or `> 1.00`)**:
   - Fix the accounting distortion observed on `AMCR` (`Shares YoY = -79.9%` due to a 1-for-5 reverse split in Jan 2026 where prior-year XBRL share count was pre-split and 2026 10-K cover share count was post-split, falsely awarding `Dilution = 1.00 Strong`).
   - In `build_company_quality_v2`, when `shares_yoy < -0.30` or `shares_yoy > 1.00`: neutralize the `dilution` pillar score to `0.50` (instead of `1.00` or `0.0`), do not emit `shares_yoy_strong`, and emit an explicit risk `EvidenceItem` (`code="shares_yoy_split_or_basis_discontinuity"`).
4. **Universe / Bucket / ETF Concentration & Share-Basis Disclosure in `v2` Reports**:
   - Add a `- **Universe & Concentration**:` header line to `render_action_list_v2` summarizing the evaluated candidate pool size, `ai_core` vs `ai_peripheral` shortlist breakdown, and top source ETFs.
   - Show `- **Company**: ... · **Action**: ... · **Pool**: ...` on each card when `watchlist_bucket` / `watchlist_etfs` provenance is present.
   - Surface compact warning badges (`⚠️Pre-Earnings(78d)`, `⚠️Extended(...)`, `⚠️Share-Basis/Split`) directly in `<summary>` headers and `Entry Gate Check` / `Fundamental Watchouts` lines.

---

## 2. Shared-Worktree Safety & Allowed Files

### Shared-Worktree Rules:
- **DO NOT** run `git checkout`, `git switch`, `git branch`, `git add`, `git commit`, `git push`, `git stash`, `git reset`, or `git clean`.
- **DO NOT** make any live network calls in unit tests.
- Never output absolute filesystem paths (`/home/...` or `/tmp/...`) in any generated file.

### Allowed to Modify / Create:
1. `src/ai_value_scanner/decision/quality.py` **(MODIFY — add `QUALITY_V2_PRE_EARNINGS_WARN_DAYS = 70` `pre_earnings_window_risk` item and `shares_yoy_split_or_basis_discontinuity` guard in `build_company_quality_v2` only; keep `build_company_quality_v1` 100% untouched)**
2. `src/ai_value_scanner/decision/entry.py` **(MODIFY — add `price_extended_above_sma200` and `return_60d_extended` score deductions + risk items in `build_entry_quality_v2` only; keep `build_entry_quality_v1` 100% untouched)**
3. `src/ai_value_scanner/decision/action.py` **(MODIFY — add `H3_PRE_EARNINGS_PRIORITY_PENALTY = 0.06` in `assign_action_priorities_v2` when `pre_earnings_window_risk` is in `decision.quality.risks`)**
4. `src/ai_value_scanner/decision/view_model.py` **(MODIFY — handle non-blocking entry extension warnings in `_build_entry_checklist` & `_build_entry_blockers_inline`, add `warning_badges_inline` and `pool_display` on `StockCardViewModel`, and `concentration_summary_line` on `SnapshotViewModel`)**
5. `src/ai_value_scanner/reporting/decision.py` **(MODIFY — render `concentration_summary_line`, `pool_display`, and `warning_badges_inline` in `render_action_list_v2` / `render_detailed_report_v2`; keep `v1` renderers 100% untouched)**
6. `tests/test_report_review_optimizations.py` **(NEW — comprehensive unit tests for all 4 enhancements + verification that existing M0–M5 unit tests pass)**

---

## 3. Exact Implementation Specifications

### 3.1 `src/ai_value_scanner/decision/quality.py` (`build_company_quality_v2` ONLY)
1. Define constants near `QUALITY_V2_POLICY_VERSION`:
   ```python
   QUALITY_V2_PRE_EARNINGS_WARN_DAYS = 70
   QUALITY_V2_ORGANIC_SHARES_YOY_MIN = -0.30
   QUALITY_V2_ORGANIC_SHARES_YOY_MAX = 1.00
   ```
2. **Reverse-Split / Share-Basis Discontinuity Guard**:
   - In `build_company_quality_v2`, check `shares_yoy_val = _finite_value(work, "shares_yoy")`.
   - If `shares_yoy_val is not None and (shares_yoy_val < QUALITY_V2_ORGANIC_SHARES_YOY_MIN or shares_yoy_val > QUALITY_V2_ORGANIC_SHARES_YOY_MAX)`:
     - Do NOT call `_assess_numeric_metric(work, key="shares_yoy", ...)` (which would falsely score `-79.9%` as `1.0` strong or `>+100%` forward split as `0.0` weak).
     - Instead, set `dilution_scores = [0.50]` (neutral `0.50` score with `1.0` coverage so confidence is not penalized) and append to `risks`:
       ```python
       risks.append(
           _metric_item(
               code="shares_yoy_split_or_basis_discontinuity",
               label="Share-count split / basis discontinuity",
               polarity="negative",
               metric="shares_yoy",
               value=round(shares_yoy_val, 6),
               threshold="-30% to +100% organic YoY range",
               message=(
                   f"Reported YoY share change ({shares_yoy_val * 100:+.1f}%) is outside "
                   "the organic buyback/issuance band and likely reflects a stock split "
                   "or share-basis discontinuity; dilution score neutralized to 0.50 and "
                   "per-share YoY metrics require manual verification."
               ),
           )
       )
       ```
     - Also in `severe_checks` of `build_company_quality_v2`, do NOT count `shares_yoy > 0.15` as a severe risk if `shares_yoy_val > QUALITY_V2_ORGANIC_SHARES_YOY_MAX` (or keep `0.15 < x <= 1.00` for organic severe dilution).
   - Otherwise (`-0.30 <= shares_yoy_val <= 1.00` or `None`), run the existing `_assess_numeric_metric(work, key="shares_yoy", ...)` unchanged.
3. **Pre-Earnings Window Warning (`age_days >= 70`)**:
   - In `build_company_quality_v2`, inside `if decision_dt is not None and data_dt is not None:`, after computing `age_days = (decision_dt - data_dt).days`:
   - Keep the existing `age_days > QUALITY_V1_STALE_UNRATED_DAYS` (`180`), `elif age_days > QUALITY_V1_STALE_WARN_DAYS` (`120`), `elif not data_integrity_blocked:` (`fundamental_data_fresh`) branches intact.
   - In addition, when `QUALITY_V2_PRE_EARNINGS_WARN_DAYS <= age_days <= QUALITY_V1_STALE_WARN_DAYS`:
     append to `risks`:
     ```python
     risks.append(
         _metric_item(
             code="pre_earnings_window_risk",
             label="Pre-earnings window (aging filing)",
             polarity="negative",
             metric="fundamental_data_age_days",
             value=age_days,
             threshold=f"<{QUALITY_V2_PRE_EARNINGS_WARN_DAYS}d before next quarterly window",
             message=(
                 f"Latest periodic filing is {age_days}d old (~90d quarterly cycle); "
                 "next earnings release is likely imminent (binary event risk)."
             ),
         )
     )
     ```
   - Note: `pre_earnings_window_risk` does NOT reduce `quality.score`, `quality.confidence`, or `quality.grade`.

### 3.2 `src/ai_value_scanner/decision/entry.py` (`build_entry_quality_v2` ONLY)
1. Define constants near `ENTRY_V2_POLICY_VERSION`:
   ```python
   ENTRY_V2_SMA200_EXTENDED_WARN = 1.35
   ENTRY_V2_SMA200_EXTENDED_SEVERE = 1.45
   ENTRY_V2_RET60_EXTENDED_WARN = 0.35
   ENTRY_V2_RET60_EXTENDED_SEVERE = 0.45
   ENTRY_V2_EXTENSION_MILD_PENALTY = 0.06
   ENTRY_V2_EXTENSION_SEVERE_PENALTY = 0.10
   ```
2. In `build_entry_quality_v2`:
   - Read `return_60d = _finite_value(metrics, "return_60d")`.
   - **Check 1 (`sma200 > ENTRY_V2_SMA200_EXTENDED_WARN`)**:
     - If `sma200 is not None and sma200 > ENTRY_V2_SMA200_EXTENDED_WARN`:
       - `penalty = ENTRY_V2_EXTENSION_SEVERE_PENALTY if sma200 > ENTRY_V2_SMA200_EXTENDED_SEVERE else ENTRY_V2_EXTENSION_MILD_PENALTY`
       - `score = max(0.0, round(score - penalty, 6))`
       - Append to `risks`:
         ```python
         _item(
             code="price_extended_above_sma200",
             label="Extended above SMA200",
             polarity="negative",
             metric="price_to_sma200",
             value=round(sma200, 6),
             threshold=f"<={ENTRY_V2_SMA200_EXTENDED_WARN:.2f}x preferred",
             message=(
                 f"Price is {sma200:.2f}x 200d SMA (>{ENTRY_V2_SMA200_EXTENDED_WARN:.2f}x medium-term extension); "
                 "entry score reduced to reflect thinner margin of safety vs long-term trend."
             ),
         )
         ```
   - **Check 2 (`return_60d > ENTRY_V2_RET60_EXTENDED_WARN`)**:
     - If `return_60d is not None and return_60d > ENTRY_V2_RET60_EXTENDED_WARN`:
       - `penalty = ENTRY_V2_EXTENSION_SEVERE_PENALTY if return_60d > ENTRY_V2_RET60_EXTENDED_SEVERE else ENTRY_V2_EXTENSION_MILD_PENALTY`
       - `score = max(0.0, round(score - penalty, 6))`
       - Append to `risks`:
         ```python
         _item(
             code="return_60d_extended",
             label="60d rally extended",
             polarity="negative",
             metric="return_60d",
             value=round(return_60d, 6),
             threshold=f"<={ENTRY_V2_RET60_EXTENDED_WARN:.0%} preferred",
             message=(
                 f"60d return is {return_60d * 100:+.1f}% (>{ENTRY_V2_RET60_EXTENDED_WARN:.0%} quarterly surge); "
                 "entry score reduced to penalize medium-term momentum chasing."
             ),
         )
         ```
   - State remains `ENTRY_READY` (if it was `ENTRY_READY`); only `score` and `risks` are updated.

### 3.3 `src/ai_value_scanner/decision/action.py` (`assign_action_priorities_v2` ONLY)
1. Define constant:
   ```python
   H3_PRE_EARNINGS_PRIORITY_PENALTY = 0.06
   ```
2. In `assign_action_priorities_v2`:
   - Helper `_has_pre_earnings_risk(decision: StockDecision) -> bool`:
     returns `any(item.code == "pre_earnings_window_risk" for item in decision.quality.risks)`.
   - Inside `_sort_key(decision: StockDecision)`:
     - Compute `pre_earn_penalty = H3_PRE_EARNINGS_PRIORITY_PENALTY if _has_pre_earnings_risk(decision) else 0.0`.
     - For `ActionState.PRIORITY_REVIEW`:
       `bonus = H3_GRADE_A_BONUS if decision.quality.grade is QualityGrade.A else 0.0`
       `return (action_order, -(joint + bonus - pre_earn_penalty), decision.symbol)`
     - For `ActionState.HOLD_MONITOR`:
       `return (action_order, ready_first, -(joint - pre_earn_penalty), decision.symbol)`
     - For all other states:
       `return (action_order, _QUALITY_ORDER_V2[decision.quality.grade], -(joint - pre_earn_penalty), decision.symbol)`

### 3.4 `src/ai_value_scanner/decision/view_model.py` & `src/ai_value_scanner/reporting/decision.py`
1. **Non-Blocking Entry Extension Risks in `_build_entry_checklist`**:
   - Define `_NON_BLOCKING_ENTRY_WARN_CODES = frozenset({"price_extended_above_sma200", "return_60d_extended"})`.
   - In `_build_entry_checklist(decision)`:
     when matching `neg = _gate_matches(decision.entry.risks, ...)`:
     filter `decision.entry.risks` to exclude `item.code in _NON_BLOCKING_ENTRY_WARN_CODES` so that `price_extended_above_sma200` and `return_60d_extended` do NOT turn a passing `sma200_trend` or `ret60_trend` gate into `FAIL_BLOCKER`!
   - In `_build_entry_blockers_inline(decision, checklist)`:
     when `decision.entry.state is EntryState.ENTRY_READY`:
     check if any item in `decision.entry.risks` has `item.code in _NON_BLOCKING_ENTRY_WARN_CODES`.
     - If none: return `"All 7 readiness gates passed"` (exact backward-compatible string!).
     - If present: format them compactly, e.g.:
       `"All 7 readiness gates passed (⚠️ Extended: SMA200 1.47x · 60d Ret +51.4%)"`
2. **Compact Label for `pre_earnings_window_risk` and `shares_yoy_split_or_basis_discontinuity`**:
   - In `_inline_fragment(item: EvidenceItem)` in `view_model.py`:
     - If `item.code == "pre_earnings_window_risk"`:
       return `f"⚠️ Pre-Earnings ({format_metric_value(item.metric, item.value)} filing)"`
     - If `item.code == "shares_yoy_split_or_basis_discontinuity"`:
       return `f"⚠️ Share Split/Basis ({format_metric_value(item.metric, item.value)})"`
3. **Warning Badges & Pool Provenance on `StockCardViewModel`**:
   - Add two fields with default `""` to `StockCardViewModel`:
     - `warning_badges_inline: str = ""`
     - `pool_display: str = ""`
   - `_build_warning_badges_inline(decision: StockDecision, data_trust: DataTrustBadge) -> str`:
     Build a list of ultra-compact badges:
     - If `pre_earnings_window_risk` in `decision.quality.risks`:
       add `f"⚠️Pre-Earnings({age}d)"`
     - If `price_extended_above_sma200` or `return_60d_extended` in `decision.entry.risks`:
       collect parts (e.g. `SMA200 1.47x`, `60d +51.4%`) and add `f"⚠️Extended({', '.join(parts)})"`
     - If `shares_yoy_split_or_basis_discontinuity` in `decision.quality.risks` or `"weighted-average fallback"` in `" ".join(data_trust.warnings)`:
       add `"⚠️Share-Basis/Split"`
     Return `" · ".join(badges)`.
   - `_build_pool_display(decision: StockDecision) -> str`:
     Check `bucket = str(decision.provenance.get("watchlist_bucket") or "").strip()` and `etfs = str(decision.provenance.get("watchlist_etfs") or "").strip()`.
     - If `bucket` and `etfs`: return `f"`{bucket}` ({etfs})"`
     - Elif `bucket`: return `f"`{bucket}`"`
     - Elif `etfs`: return `f"({etfs})"`
     - Else: return `""` (empty when provenance has no watchlist metadata, preserving synthetic test fixtures).
4. **Shortlist Concentration Summary Line on `SnapshotViewModel`**:
   - Add `concentration_summary_line: str = ""` to `SnapshotViewModel`.
   - In `build_snapshot_view_model(...)`:
     If `primary_cards` have at least one card with `watchlist_bucket` or `watchlist_etfs` in `card.decision.provenance`:
     - Count `bucket` distribution across `primary_cards` (e.g. `ai_core 11/15, ai_peripheral 4/15`) and top 4 ETFs across `primary_cards` (splitting comma-separated `watchlist_etfs`, e.g. `XLK (5), IGV (4), SMH (3)`), plus total candidate count `len(all_decisions)` if `all_decisions` is provided.
     - Set `concentration_summary_line` to a concise 1-line summary, e.g.:
       `"AI-theme pool (511 names) · Shortlist buckets: ai_core 11/15, ai_peripheral 4/15 · Top ETFs: XLK (5), IGV (4) — diversify across sectors manually"`
     - If no card in `primary_cards` has `watchlist_bucket` or `watchlist_etfs` (as in synthetic unit tests), `concentration_summary_line` MUST be `""` so synthetic tests stay 100% unchanged!
5. **Render in `src/ai_value_scanner/reporting/decision.py` (`render_action_list_v2` & `_v2_stock_card_block`)**:
   - In `_v2_stock_card_block`:
     - If `card.warning_badges_inline` is non-empty, append `f" · {card.warning_badges_inline}"` right before `</summary>` on the `<summary>` line!
     - On the `- **Company**:` line, if `card.pool_display` is non-empty, append `f" · **Pool**: {card.pool_display}"`.
   - In `render_action_list_v2`:
     - If `snapshot.concentration_summary_line` is non-empty, insert:
       `f"- **Pool & Concentration**: {snapshot.concentration_summary_line}"`
       right below the `- **Date**:` line!

---

## 4. Follow-Up Polish & Secondary Radar Wiring (Post-PR #86 Review)

Based on review of the regenerated `2026-10-15` report, implement the following three targeted refinements by modifying ONLY:
1. `src/ai_value_scanner/decision/view_model.py`
2. `src/ai_value_scanner/reporting/decision.py`
3. `src/ai_value_scanner/reporting/snapshot.py`
4. `scripts/render_snapshot_preview.py`
5. `tests/test_report_review_optimizations.py`

### 4.1 Primary-Bucket Normalization & Clean Multi-Bucket Formatting (`view_model.py`)
In `data/ai_watchlist.csv`, a stock belonging to multiple buckets has a comma-separated string such as `"ai_enabler,core_ai"`. Treating `"ai_enabler,core_ai"` as an atomic bucket string caused `ai_enabler,core_ai 4/15` and `core_ai 3/15` to appear side-by-side in `concentration_summary_line`.
1. Define canonical bucket priority in `src/ai_value_scanner/decision/view_model.py`:
   ```python
   _BUCKET_PRIORITY: tuple[str, ...] = (
       "core_ai",
       "ai_core",
       "ai_enabler",
       "ai_peripheral",
       "ai_smallcap",
   )
   ```
2. Add two helpers in `src/ai_value_scanner/decision/view_model.py`:
   - `_normalize_primary_bucket(raw_bucket: Any) -> str`:
     Split `str(raw_bucket or "")` on `","` into stripped non-empty tokens. If empty, return `""`. Return the first token matching `_BUCKET_PRIORITY` in priority order (or `tokens[0]` if none are in `_BUCKET_PRIORITY`).
     - Example: `"ai_enabler,core_ai"` $\rightarrow$ `"core_ai"`; `"ai_core"` $\rightarrow$ `"ai_core"`.
   - `_format_bucket_tokens(raw_bucket: Any) -> str`:
     Split `str(raw_bucket or "")` on `","` into unique stripped non-empty tokens, sorted by `_BUCKET_PRIORITY` index (then alphabetically), joined with `"/"`.
     - Example: `"ai_enabler,core_ai"` $\rightarrow$ `"core_ai/ai_enabler"`; `"ai_core"` $\rightarrow$ `"ai_core"`.
3. In `_build_pool_display(decision: StockDecision)`:
   Use `bucket = _format_bucket_tokens(decision.provenance.get("watchlist_bucket"))` so single-bucket strings remain `` `ai_core` `` while multi-bucket strings render cleanly as `` `core_ai/ai_enabler` ``.
4. In `_build_concentration_summary_line(primary_cards, pool_size)`:
   Count `bucket = _normalize_primary_bucket(card.decision.provenance.get("watchlist_bucket"))` per card so each shortlist stock is counted once under its canonical primary bucket (`core_ai 7/15, ai_peripheral 3/15, ai_smallcap 3/15, ai_enabler 2/15`), summing to `15/15` with zero composite `"a,b"` keys!

### 4.2 Wire `all_decisions` in `write_decision_snapshot` & Expand Secondary Radar Cap-Omitted Priority Review to 15 with Warning Badges (`snapshot.py`, `view_model.py`, `reporting/decision.py`)
1. **Why `Pool (538 names)` and `Secondary Radar` were omitted during `write_decision_snapshot`**:
   In `src/ai_value_scanner/reporting/snapshot.py` (`write_decision_snapshot`, lines 245–262), `render_action_list(daily_tuple, ...)` and `render_action_list(weekly_tuple, ...)` were called without `all_decisions=decisions_tuple`!
   - Fix in `src/ai_value_scanner/reporting/snapshot.py`:
     - Pass `all_decisions=decisions_tuple` to both `render_action_list(daily_tuple, ..., layout_version=layout_version, all_decisions=decisions_tuple)` and `render_action_list(weekly_tuple, ..., layout_version=layout_version, all_decisions=decisions_tuple)`. (Note: when `layout_version == "v1"`, `render_action_list` ignores `all_decisions`, so `v1` output remains 100% byte-identical!)
     - When `layout_version == "v2"`, also include the symbols from `daily_view.cap_omitted_priority_cards`, `weekly_view.cap_omitted_priority_cards`, `daily_view.secondary_b_ready_cards`, and `weekly_view.secondary_b_ready_cards` (via `build_snapshot_view_model`) in `detailed_symbols` (lines 286–297) so that every `[Full Report →](./detailed/<SYMBOL>.md)` link in `Secondary Radar` has its `detailed/<SYMBOL>.md` file generated!
2. **Increase `cap_omitted_priority_cards` slice from `[:5]` to `[:15]` in `build_snapshot_view_model` (`src/ai_value_scanner/decision/view_model.py`)**:
   - On `2026-10-15`, `FDS` is `#19`, `AMD` is `#20`, `MSFT` is `#22`, and `FIVN` is `#28`. Slicing `[:5]` cut off at `#20` and hid `MSFT` (`#22`) and `FIVN` (`#28`)!
   - Change the `cap_omitted` slice in `build_snapshot_view_model` from `[:5]` to **`[:15]`** (so up to 15 cap-omitted `PRIORITY_REVIEW` names `#16..#30` are shown in the collapsible `Cap-Omitted Priority Review` drawer; keep `secondary_b_ready_cards` at `[:5]`).
3. **Include Warning Badges & Entry Snapshot in `Secondary Radar` (`src/ai_value_scanner/reporting/decision.py`)**:
   - In `render_action_list_v2` (`src/ai_value_scanner/reporting/decision.py`), for each `card` in `snapshot.cap_omitted_priority_cards` and `snapshot.secondary_b_ready_cards`:
     - If `card.warning_badges_inline` is non-empty, include `f" · {card.warning_badges_inline}"` right before `· [Full Report →]({rel_report})` on the main bullet line!
     - Also include `f"  - **Entry**: {_plain(card.entry_Snapshot_inline)}"` right between `Highlights` and `Watchouts` so reviewers checking `MSFT` or `AMD` in `Secondary Radar` can immediately see their `SMA200 / SMA50 / 20d / 60d` numbers and `⚠️Pre-Earnings(78d) · ⚠️Extended(...)` badges without even opening the detailed report!

### 4.3 Non-Destructive `--recompute-v2` Mode in `scripts/render_snapshot_preview.py`
To ensure we never overwrite an immutable formal snapshot in `outputs/decisions/<date>/<style>/` when testing or previewing `v2` policy/report updates on the same day:
- Add `--recompute-v2` (`action="store_true", default=False`) to `scripts/render_snapshot_preview.py`.
- When `--recompute-v2` is NOT passed (default): preserve 100% of existing behavior.
- When `--recompute-v2` IS passed:
  - Read `decisions.jsonl` and `run_manifest.json` from `--snapshot-dir` **read-only** (never modify anything in `--snapshot-dir`).
  - Recompute the `v2` Quality/Entry/Action adjustments on the loaded `StockDecision` list (applying `shares_yoy_split_or_basis_discontinuity` guard when `shares_yoy < -0.30` or `> 1.00`, `pre_earnings_window_risk` when `70 <= age_days <= 400`, `price_extended_above_sma200` / `return_60d_extended` Entry score deductions when not already present, `map_action_state_v2`, `assign_action_priorities_v2`, and `select_daily_attention`/`select_weekly_attention` with `cap=15`).
  - Write `action_list_v2.md`, `weekly_review_v2.md`, `detailed_v2/*.md`, and `decisions_recomputed_v2.jsonl` to `--output-dir`.

---

## 5. Verification Commands

Run locally:
```bash
.venv/bin/python -m unittest discover -s tests -p "test_report_review_optimizations.py"
.venv/bin/python -m unittest discover -s tests -p "test_decision_view_model_and_report_v2.py"
.venv/bin/python -m unittest discover -s tests -p "test_m3_candidate_preflight.py"
.venv/bin/python -m unittest discover -s tests -p "test_m4_paired_validation.py"
.venv/bin/python -m unittest discover -s tests
```
When all tests pass, stop and report for Chief Architect review.
