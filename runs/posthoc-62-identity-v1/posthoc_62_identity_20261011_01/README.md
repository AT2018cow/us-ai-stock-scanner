# Post-hoc 62 identity verification samples — posthoc_62_identity_20261011_01

 Companion to `runs/phase2-report-before-after/2026-10-09/` (renderer
 before/after). This pack shows the P0 identity fix + fixed renderers on
 real decisions: XOM (UNVERIFIED subsidiary binding), GS (verified entity,
 tag-vocabulary gap), JPM (verified bank C), ABBV (verified priority).

## Exact code composition (no single pushed SHA covers the run)

- `fix/identity-verification-20261011` @ `763fddd` (identity verification)
- `phase2/report-clarity-20261011` @ `8d34abb` (renderer fixes incl.
  BREAKOUT honesty + asof-MISSING display)
- `research/historical-selection-validation-protocol-20261011` @ `6711919`
  (post-hoc diagnostic entry + split helpers; unmerged research)
- TICKET: local throwaway merge `1cba0ba` (NOT pushed; composition above
  is the auditable identity — re-merge the three SHAs to reproduce).

Per-date `manifest.json` files record the throwaway merge SHA in
`code_sha`; read it together with this note. All three branches are
fetchable from origin.

## What to check

- XOM: `operating_entity_unverified` in Missing Evidence, identity banner,
  provenance shows `cik: 0002115436` + `filing_entity_name: ExxonMobil
  Holdings Corp` — traceable to the wrong-entity binding, no reliable
  grade claimed.
- GS: verified binding (0000886982), UNRATED via normal missingness
  (broker tag vocabulary — separate research, not identity).
- JPM: verified binding, grade C shown with the applicability caveat.
- ABBV: verified, priority review, renderer fixes visible (no basing
  narrative; structure + review conditions sections).
- `decisions.jsonl` + `action_list.md` are the full 2026-10-09 rerun
  (62/62, chained previous, posthoc mode).

Mode: `retrospective_posthoc_cohort` (same limits as the v1 pack).
