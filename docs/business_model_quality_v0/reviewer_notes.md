# Reviewer notes — business-model study, first submission

## Correction round (reviewer audit 2026-10-13; all verified on raw evidence)

- Bank C attribution first version wrongly claimed leverage/coverage
  SCORED against JPM/BAC/MS/WFC. Truth from decisions.jsonl: those codes
  are MISSING (balance_sheet component None); the scored risks are OCF
  conversion/growth and revenue YoY. Cases rewritten with the
  scored-vs-missing-vs-inapplicable split; see
  `quality_driver_attribution.csv` (11 rows).
- WFC removed from study rows (outside the registered 11); kept as a
  labelled corroborating note only.
- XOM row rewritten with split records: posthoc-1009 (UNRATED/14-missing)
  vs frozen-1012 (B/5-missing, opco-scale values) at the SAME asof
  08-03 — labels flap with feed content, not filings. Same-asof flips
  also documented for HON (live integrity cap, legit), FCX
  (threshold edge), NEE (genuine Q2 upgrade).
- PLD asof gap explained as fact-coverage lag (Q2 10-Q filed 07-29 in
  submissions; Q2 accession absent from observed companyfacts snapshots);
  TTL-vs-endpoint mechanism undetermined, stated as open.
- `entry_readiness_diagnostics.csv` rebuilt by committed
  `research/build_entry_diagnostics.py` (+ synthetic rebuild test);
  silent-band rows carry reconstructed values, never NONE.
- Matrix holds 15 indicator rows (PR body text corrected separately).

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

## Registered follow-ups (not in this PR)

- P1 cache hardening (bulk-batch stale tails): `AlpacaClient.get_daily_bars`
  serves a batch cache hit as fresh when its earliest timestamp predates
  the requested start, without checking tail freshness — observed serving
  2026-09-25 tails for 47 names while 2026-10-12 existed provider-side.
  Proposed regression test: seed a cache entry whose head predates `start`
  but whose tail predates the latest provider session, then assert the
  client enriches (or marks stale) instead of serving it as fresh. No
  evidence re-run needed (frozen v0 experiment fetched its own bars and
  passed validation).
