# Addendum 1 — denominator correction + fail-closed hardening record

Date: 2026-10-11. Appends to (never modifies):
- `runs/historical-selection-v1/historical_selection_v1_20261011_02/`
  (evidence `9c22f1932620ef042017a2e59dfbd10931c4a709`)
- `runs/historical-selection-v1/historical_selection_v1_20261011_03/`
  (evidence `a3bec3d9ae4164f450c94c546d57d36a5d63e063`)

Both directories are byte-identical to their submitted state; verify with
their own `SHA256SUMS`. This addendum only ADDS this file (+ its hash).

## 1. Correction: C-grade denominator in _03 `coverage_and_integrity.md`

The "Grade mix v3" line wrote **C 7,158** (summing to 25,020). That is the
count of C rows **with a valid 120d label**, not the C grade total. The
verified counts from `action_v1_decisions.csv` (RUN _03) are:

| grade | grade records (rows) | valid fwd_ret_120 | difference |
|---|---|---|---|
| A | 6,888 | 6,888 | 0 |
| B | 9,152 | 9,152 | 0 |
| C | **7,163** | **7,158** | **5 = WOLF nulled labels** |
| UNRATED | 1,822 | 1,822 | 0 |
| total | **25,025** | 25,020 | 5 |

All 5 nulled rows are grade C (WOLF, `equity_discontinuity_flag=1`).
A/B/UNRATED lines in the report were coincidentally correct (no nulls in
those grades). Unaffected: `research_review.md` magnitudes (label-based),
all H-tables (row-count based), `label_diff_*` (explicit n_valid columns),
evaluator reports (report both n_decisions and n_valid_return).

Rule going forward: every cohort table must state which denominator it
uses (rows vs valid-labels); the two differ exactly by nulled/immature
labels.

## 2. Fail-closed hardening (no re-extract; small engineering change)

`extract_weight_dataset.py` previously logged a warning and continued with
unadjusted bars when the corporate-actions endpoint failed — the exact
hole that produced the BKNG/KLAC class. Commit `6711919c8ea91dbe2…`
(PR #58 branch) adds `fetch_split_events_or_raise`: a fetch failure now
aborts label production (nonzero exit, no CSV/SUCCESS written, retry
allowed). Exact-head CI unittest success (run 38156989599); local suite
548 tests OK (incl. 3 new fail-closed tests: raise / arg pass-through /
empty-dict).

No 25,025-row re-extract was run for this change (by design — behavior
only triggers on endpoint failure; the _03 run fetched splits
successfully). Next extract automatically inherits the guard.

Known sibling: `src/ai_value_scanner/backtest.py` replay path still fails
open on split-fetch errors. Flagged as follow-up; NOT changed in this
commit (scoped to the extraction path per review instruction).
