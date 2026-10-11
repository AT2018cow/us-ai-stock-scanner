# Reviewer notes — RUN_ID historical_selection_v1_20261011_03 (fix audit)

## Fix history (祸根 → 修复 → 验证)

1. Reviewer found BKNG/KLAC −0.9x labels + WOLF continuity question in _02.
2. Root causes isolated before any code change (all reproduced on real rows):
   - split query capped at signal-window end (`extract_weight_dataset.py`,
     same pattern in `backtest.py` replay);
   - WOLF reverse splits absent from the Alpaca feed since 2020 (verified
     by direct API query for WOLF/WOLFQ, 2020→2026: empty).
3. Fixes (commit `af70b5e`, CI unittest success run 38151804814):
   - `split_query_end_iso` envelope (signal end + longest-horizon +
     10d) in both label-production paths; `{stem}.splits.json` frozen.
   - `evaluation/equity_continuity.py` + `repair_equity_discontinuity.py`:
     event cross-check (120d filing-lag lookback), price corroboration for
     collapses, backdated reorg jumps, audit-only disclosure for jumps and
     artifacts. 15 regression tests (545 total green).
4. Re-extraction _03 (at2018cow, same window/spec): split events 41 → 48
   symbols; BKNG/KLAC verified sane; repair found exactly the WOLF-Sep
   backdate (+51 audit-only records, zero other nulls).
5. H1–H3 fully re-run on corrected labels; verdicts stand (see review).

## What I verified vs did not

- Verified: both MODAL_EXIT=0, SUCCESS specs, 39/39 dates, 670 symbols,
  BKNG/KLAC spot values, WOLF null set (5 rows / 7 labels), parity and
  UNVERIFIED self-checks re-passed, `9c22f19` untouched (new dir).
- Did not: re-verify all 25,025 cells; independently confirm the 48-symbol
  split list beyond BKNG/KLAC spot checks (list frozen in splits.json for
  reviewer sampling); adjudicate the 51 audit-only anomalies beyond the
  CORZ/PKG/HEI/LAES/QUBT/UMAC/SHOP/SMCI/AMCR/ARQQ/MOVE spot review above.

## Suggested spot checks

- BKNG 2026-03-31 fwd120 (−0.037) vs v1 (−0.964): split-adjusted continuity.
- WOLF 2025-06-30 fwd120 (+24.04 → nulled): backdate boundary Sep-2025.
- CORZ early-2024 +200–300% labels (kept): post-emergence new-equity rally.
- `label_diff_by_symbol.csv`: confirm only 10 symbols changed.
- `*_discontinuities.csv`: confirm 1 nulling record + 51 disclosures.
