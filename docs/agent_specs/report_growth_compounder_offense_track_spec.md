# Agent Specification: Dual-Track Report Layout v2 — Adding `Growth Compounder Leaders (Bull Offense Track)`

- **Date**: 2026-10-17
- **Baseline**: `main` @ `39e2d25` (PR #99)
- **Empirical Justification**: `docs/growth_compounder_offense_validation_20261017/report.md` (Candidate `C2_offense_compounder_track`)
- **Target Execution Agent**: DeepSeek (implementation + unit tests + preview regeneration only; no Git state mutations, no network calls)
- **Reviewer / Integrator**: Architect Agent

---

## 1. Motivation & Product Design

Per the Gate G1–G4 validation in `docs/growth_compounder_offense_validation_20261017/report.md`:
1. **Defensive Entry-Ready Anchor (`Priority Review — Ready for Evaluation`, Top 15)**:
   - Preserving the current `v2` production `PRIORITY_REVIEW` ranking unchanged maintains its superior drawdown/bear-market protection (`+1.49%` on `FWD_DRAWDOWN_60D`, `+2.09%` and `6.7%` severe-loss rate on `BEAR_2022`).
2. **Bull-Market Offense Track (`Growth Compounder Leaders — Bull Offense Track`, up to 10 names)**:
   - Candidate `C2_offense_compounder_track` (`Quality Grade A/B` with `score >= 0.68`, no `nonoperating_gain_inflation`, `revenue_yoy >= 15%`, `ocf_to_net_income >= 0.80`, `entry.state in {ENTRY_READY, WATCH_PULLBACK}`, `1.00 <= price_to_sma200 <= 1.60`, and `relative_strength_60d_qqq >= 0.0`) beat `v2_baseline` by **`+1.50pp` on `DEV`**, **`+5.05pp` on `POST`** (95% CI `[+1.40pp, +8.75pp]`), **`+4.27pp` across the 31 bull months (`FWD_BULL_60D`)**, and **`+0.68pp` even after excluding the top 5 winners (`PLTR, APP, SMCI, FIX, IESC`)**, while still beating QQQ (`+1.36%` / `+5.07%`) in the 2022 bear market.
   - Because many of these high-growth compounders sit in `WATCH_PULLBACK` during bull trends (e.g. `PLTR`, `VEEV`, `GWRE`, `ZETA`, `SNPS`, `DT`, `NOW`, `META` on `2026-10-15`), surfacing them in a dedicated **Growth Compounder Leaders (Bull Offense Track)** section in `action_list_v2.md` (and `weekly_review_v2.md`) gives the human researcher immediate visibility into bull-market offense leaders without diluting the defensive `Priority Review` anchor.

---

## 2. Detailed Design

### 2.1 `src/ai_value_scanner/decision/view_model.py` — `growth_compounder_offense_cards`

1. In `SnapshotViewModel` (`src/ai_value_scanner/decision/view_model.py`), add a field with a default empty tuple (preserving backward compatibility for any caller constructing `SnapshotViewModel` directly):
   ```python
   growth_compounder_offense_cards: tuple[StockCardViewModel, ...] = ()
   ```
2. Add pure helper functions in `src/ai_value_scanner/decision/view_model.py`:
   ```python
   OFFENSE_COMPOUNDER_MIN_QUALITY_SCORE: float = 0.68
   OFFENSE_COMPOUNDER_MIN_REV_YOY: float = 0.15
   OFFENSE_COMPOUNDER_MIN_OCF_NI: float = 0.80
   OFFENSE_COMPOUNDER_MIN_SMA200: float = 1.00
   OFFENSE_COMPOUNDER_MAX_SMA200: float = 1.60
   OFFENSE_COMPOUNDER_MIN_RS60: float = 0.0
   OFFENSE_COMPOUNDER_PRE_EARNINGS_PENALTY: float = 0.06
   ```
   - Helper `_decision_metric_value(decision: StockDecision, metric: str) -> float | None`:
     Searches `decision.quality.positives`, `decision.quality.risks`, `decision.entry.positives`, and `decision.entry.risks` for `item.metric == metric` and returns `_as_float(item.value)` if finite, else `None`.
     *(Note: Because `revenue_yoy >= 0.15` always emits `revenue_yoy_strong`, `ocf_to_net_income >= 0.80` always emits `ocf_to_net_income_strong`, `price_to_sma200 >= 1.00` always emits `price_above_sma200`, and `relative_strength_60d_qqq >= 0.0` always emits `relative_strength_60d_qqq_ready`, all four gate metrics are guaranteed to be present in `StockDecision` evidence whenever a stock qualifies!)*
   - Helper `is_growth_compounder_offense_eligible(decision: StockDecision) -> bool`:
     Returns `True` iff all 6 conditions hold:
     1. `decision.quality.grade in {QualityGrade.A, QualityGrade.B}` and `decision.quality.score is not None and float(decision.quality.score) >= OFFENSE_COMPOUNDER_MIN_QUALITY_SCORE`;
     2. `not any(item.code == "nonoperating_gain_inflation" for item in decision.quality.risks)`;
     3. `rev_yoy is not None and rev_yoy >= OFFENSE_COMPOUNDER_MIN_REV_YOY`;
     4. `ocf_ni is not None and ocf_ni >= OFFENSE_COMPOUNDER_MIN_OCF_NI`;
     5. `decision.entry.state in {EntryState.ENTRY_READY, EntryState.WATCH_PULLBACK}` and `sma200 is not None and OFFENSE_COMPOUNDER_MIN_SMA200 <= sma200 <= OFFENSE_COMPOUNDER_MAX_SMA200`;
     6. `rs60 is not None and rs60 >= OFFENSE_COMPOUNDER_MIN_RS60`.
   - Helper `growth_compounder_offense_order_key(decision: StockDecision) -> tuple[float, float, float, str]`:
     - Computes:
       ```python
       q_score = float(decision.quality.score or 0.0)
       rev_yoy = _decision_metric_value(decision, "revenue_yoy") or 0.0
       rs60 = _decision_metric_value(decision, "relative_strength_60d_qqq") or 0.0
       penalty = (
           OFFENSE_COMPOUNDER_PRE_EARNINGS_PENALTY
           if any(item.code == "pre_earnings_window_risk" for item in decision.quality.risks)
           else 0.0
       )
       offense_score = (
           q_score
           + 0.50 * min(max(rev_yoy, 0.0), 1.0)
           + 0.50 * min(max(rs60, 0.0), 1.0)
           - penalty
       )
       e_score = float(decision.entry.score or 0.0)
       return (-round(offense_score, 6), -round(q_score, 6), -round(e_score, 6), decision.symbol)
       ```
3. In `build_snapshot_view_model`:
   - When `all_decisions is not None`:
     - Select all `decision` in `all_decisions` where `is_growth_compounder_offense_eligible(decision)` is `True` and `decision.symbol not in primary_symbols` (so names already in the Top-15 `Priority Review` primary cards are not duplicated, while off-list offense compounders in `WATCH_PULLBACK` or `ENTRY_READY` beyond Top-15 — such as `PLTR`, `VEEV`, `GWRE`, `ZETA`, `SNPS`, `DT`, `NOW`, `MSFT`, `META` — are surfaced!).
     - Sort them by `growth_compounder_offense_order_key` and take the top `10`:
       ```python
       offense_cards = tuple(
           build_stock_card_view_model(decision)
           for decision in sorted(eligible_offense, key=growth_compounder_offense_order_key)[:10]
       )
       ```
     - Pass `growth_compounder_offense_cards=offense_cards` to `SnapshotViewModel(...)`.

---

### 2.2 `src/ai_value_scanner/reporting/decision.py` — Render `Growth Compounder Leaders (Bull Offense Track)` Section

In `render_action_list_v2` (`src/ai_value_scanner/reporting/decision.py`):
1. In the `- **Sections**:` navigation bar (around line 585), include `· [Growth Leaders (Offense)](#growth-leaders-offense)` right before `· [Secondary Radar](#secondary-radar)`.
2. Right before `<a id="secondary-radar"></a>` (around line 627), render the new section:
   ```python
   lines.extend(
       [
           '<a id="growth-leaders-offense"></a>',
           f"## Growth Compounder Leaders — Bull Offense Track ({len(snapshot.growth_compounder_offense_cards)})",
           "",
       ]
   )
   if not snapshot.growth_compounder_offense_cards:
       lines.extend(
           [
               "- No additional off-list growth compounder leaders (Quality A/B, Rev YoY >= 15%, OCF/NI >= 0.80x, SMA200 1.00–1.60x, RS60 >= 0%).",
               "",
           ]
       )
   else:
       lines.extend(
           [
               "- *High-growth cash-flow compounders (Quality A/B, Rev YoY >= 15%, OCF/NI >= 0.80x, SMA200 1.00–1.60x, 60d RS vs QQQ >= 0%) outside the Top-15 defensive shortlist — suited for bull-market trend offense or pullback-to-SMA20/50 entries.*",
               "",
           ]
       )
       for idx, card in enumerate(snapshot.growth_compounder_offense_cards, start=1):
           rel_report = f"./{detailed_subdir.strip('/')}/{card.symbol}.md"
           lines.extend(
               [
                   f"- **Offense #{idx} {card.symbol}** ({_plain(card.company_name)}, Rank #{card.rank}) — "
                   f"Q:**{card.quality_grade}** ({card.quality_score_display}) · "
                   f"E:**{_short_entry(card.entry_state)}** ({card.entry_score_display})"
                   f"{(' · ' + card.warning_badges_inline) if card.warning_badges_inline else ''} · "
                   f"[Full Report →]({rel_report})",
                   f"  - **Highlights**: {_plain(card.quality_highlights_inline)}",
                   f"  - **Entry**: {_plain(card.entry_snapshot_inline)}",
                   f"  - **Watchouts**: {_plain(card.fundamental_watchouts_inline)}",
               ]
           )
       lines.extend(["", "[↑ Top](#top)", ""])
   ```
   *(Note: verify the exact attribute name on `StockCardViewModel` for the entry inline string — in `reporting/decision.py` lines 653/677 it is `card.entry_snapshot_inline`; use the exact attribute name already used in `Secondary Radar`!)*

---

### 2.3 `src/ai_value_scanner/reporting/snapshot.py` & `scripts/render_snapshot_preview.py` — Generate Detailed Reports for Offense Cards

1. In `src/ai_value_scanner/reporting/snapshot.py` (around lines 303–306):
   Include `*view.growth_compounder_offense_cards` alongside `*view.cap_omitted_priority_cards` and `*view.secondary_b_ready_cards` so `detailed/{symbol}.md` is always written for every offense leader in live scans.
2. In `scripts/render_snapshot_preview.py` (both in `main()` around lines 428–435 and in `_write_recompute_preview()` around lines 495–505):
   Include `{card.symbol for card in daily_view.growth_compounder_offense_cards}` and `{card.symbol for card in weekly_view.growth_compounder_offense_cards}` in `symbols` so `detailed_v2/{symbol}.md` is always written for every offense leader in preview runs.
   Also in `scripts/render_snapshot_preview.py` (`_load_local_cache_enrichment` / `_with_quality_v2_adjustments`):
   Ensure that when `--recompute-v2` runs on a frozen v1 snapshot (where `ocf_to_net_income_strong` was emitted at `>= 1.0` in v1 rather than `>= 0.80` in v2), if `ocf_ni` from `_evidence_or_enrichment("ocf_to_net_income")` is `>= 0.80` and `"ocf_to_net_income_strong"` is not yet in `positives`, append `EvidenceItem(code="ocf_to_net_income_strong", label="Operating cash-flow conversion supportive", polarity="positive", metric="ocf_to_net_income", value=round(ocf_ni, 6), threshold=">=0.8 supportive; <0.5 weak", message="Operating cash flow converts a healthy share of earnings.")` to `positives` so that `0.80 <= ocf_to_net_income < 1.0` stocks are also recognized in `--recompute-v2` previews!

---

### 2.4 Documentation & Preview Update

1. Update `README.md` (Report Layout v2 section) to document the new `Growth Compounder Leaders — Bull Offense Track` section in `action_list_v2.md`.
2. Re-run:
   ```bash
   .venv/bin/python scripts/render_snapshot_preview.py \
     --snapshot-dir outputs/decisions/2026-10-15/risk_off \
     --output-dir outputs/decision_previews/2026-10-15/risk_off \
     --recompute-v2
   ```
   to update the local `2026-10-15` preview with the new `Growth Compounder Leaders — Bull Offense Track` section.

---

## 3. Unit Test Requirements

Add unit tests (in `tests/test_validate_growth_compounder_offense.py` or `tests/test_decision_view_model_v2.py`) covering:
1. `is_growth_compounder_offense_eligible` and `growth_compounder_offense_order_key` on `StockDecision` objects (verifying all 6 gates, `WATCH_PULLBACK` inclusion, `nonoperating_gain_inflation` exclusion, `pre_earnings_window_risk` `-0.06` deduction, and `primary_symbols` deduplication);
2. `render_action_list_v2` renders the `## Growth Compounder Leaders — Bull Offense Track` section with clickable `[Full Report →]` links;
3. `write_decision_snapshot(..., layout_version="v2")` writes `detailed/{symbol}.md` for symbols appearing in `growth_compounder_offense_cards`.
