# Reviewer notes — business-model study, first submission

## What this PR contains (design + inventory + first diagnostics)

- `research_protocol.md` (frozen questions/method/grades), this notes file.
- `company_identity_and_pit_inventory.csv` (11 names; local-cache only;
  currency column currently assumed USD — must be verified per name
  from filing context before any conclusion).
- `accounting_semantics_matrix.csv` (DRAFT hypotheses; cells need case
  validation, especially every DOUBTFUL).
- `quality_failure_cases.md`, `entry_readiness_diagnostics.csv`
  (built by `research/build_entry_diagnostics.py` from frozen post-hoc
  decisions + run manifests; SILENT_* rows are reconstructed, labelled).
- `candidate_interpretation_policy.md` (no scores).

## Known limits / open questions for review

1. Business-model labels: SIC-major + 10-K descriptions cited per class;
   REIT/broker flags need per-name quotes before final.
2. XOM entity selection (holdings vs operating CIK) unresolved — the
   central open question of Q3.
3. Silent-band reconstructions (EQIX/AAPL RS, EQIX ret60) use run-manifest
   QQQ trailing + row values; exact to the scorer's inputs by construction,
   but confirm the convention before citing magnitudes.
4. Currency: USD assumed; foreign/test names (none in the 11) would need
   the existing currency gate path.
5. No forwards used anywhere in this submission; no thresholds touched.
6. Heavy compute: none spent. IF later phases need history beyond cache,
   a Modal extraction spec (fields/window/budget) will be filed for
   approval first.
