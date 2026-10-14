# MVP v1.1 PR-A — final development-study review (2026-10-14)

**Formal reviewer decision: NO-GO for v1.1 parameter promotion / KEEP V1.**
This is a reproducible negative finding, **not** a bug in the completed
2023–2024 study. Do not open PR-B, execute conditional X1, expand the
parameter search, inspect 2025/2026Q1 candidate outcome diagnostics,
recompute corrected historical data, or change production v1 in response.

## Registered evidence reviewed

- PR-A development study evidence commit:
  `ffb267374eac139ca50efdf13289a9b3b27a31fb`
- Authorized executed **code HEAD**:
  `9514166907e7f279fd6efd6f77f672badb9bd6f7`
- Frozen research protocol SHA256:
  `0a911c0443a2c744a0e8fbe1da02ad4077c880fd08db76eaf96321d3d146f696`
- Historical corrected v3 SHA256:
  `2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e`
- Frozen 240 membership preflight SHA256:
  `bc9130edcb62c362d893166d69b7c363087f254ed91bca4127322faac93f6f60`
- Main study files:
  `evidence/mvp-v11-dev-return-20261014/{run_manifest.json,SHA256SUMS,paired_by_date.csv,metrics_by_period.csv,top15_diff_cases.csv,risk_and_missingness.md,decision_recommendation.md}`
- Validated GitHub Actions on evidence commit:
  run `38553349651`, SUCCESS.

Checked study content: 1,440 date×candidate×horizon×cap rows;
24 dates, 10 frozen IDs B0/R1–R5/E1–E4, 20/60/120d and Top-5/15;
all 24 primary date pairs label-valid; only 2023–2024. B0's
self-comparison is exactly zero. X1, 2025 and 2026Q1 were not executed.
The original forward stock and QQQ return legs each already include
the 30 bps roundtrip assumption; no second transaction charge.
These are **retrospective monthly attention-cap proxies**, not trades
or executed portfolio NAV.

## Registered primary economic gate: 60d Top-15

Date-equal paired net QQQ-excess delta, in **percentage points**:

| Candidate | 2023–24 | Predeclared +0.5 pp threshold |
| --- | ---: | --- |
| B0 | 0.000 | Reference only |
| E1 | +0.213 | FAIL |
| E4 | +0.084 | FAIL |
| R1 | −0.038 | FAIL |
| E3 | −0.055 | FAIL |
| R2 | −0.156 | FAIL |
| R4 | −0.156 | FAIL |
| R3 | −0.200 | FAIL |
| R5 | −0.240 | FAIL |
| E2 | −0.276 | FAIL |

**Nine of nine modifications fail the economic threshold.** The +0.5pp
reference is an ex ante practical threshold, not statistical
significance. No candidate meets the necessary development gate.

## Why the apparent leader is not robust

E1 has +0.213pp overall, but +0.056pp in 2023 and +0.369pp in
2024, still below +0.5pp even in 2024. Only 8/24 monthly
deltas are positive, 7/24 have identical Top-15 and zero
delta, and 9/24 are negative. The three worst dates are:
2023-07-31 **−4.709pp**, 2023-12-29 **−1.125pp**,
2023-03-31 **−1.085pp**.

The largest positive date, **2023-11-30 +6.573pp**, has five
Top-15 swaps and fails **both** event-overlap and score-source
sensitivity validity. The sum of monthly E1 deltas is approx
+5.107pp (24-date mean +0.213pp), while dropping that single
largest date **only as a diagnostic** changes the mean to
approximately **−0.064pp across 23 dates**. This is not a new
post-hoc winner-selection rule.

The pre-registered full 24-date E1 sensitivity results are
**−0.125pp** on 18 event-clean paired dates and **−0.048pp**
on 15 score-source-clean paired dates (rather than +0.213pp).
Do not reinterpret the reduction in date counts as new independent
OOS samples. The split is only 20 regime-up and 4 regime-down dates.

E4 has +0.084pp, just two dates of Top-15 membership change,
and no change at all on the other 22 dates. This is insufficient
economic effect, even when narrow sensitivity views remain
slightly positive.

R candidates' 60d Top-15 primary metrics are all negative. Some
Top-5 or 120d secondary metrics are positive (e.g. R5 Top-5
60d +0.622pp); **these cannot replace the preregistered
Top-15 60d primary**. R2/R4 have identical Top-15 results.

## Risk, source and interpretation caveats

- No historical production Daily/Weekly state transition replay:
  historical priority/cap is a **proxy**.
- `retrospective / union_superset_approx` stock universe; not a
  point-in-time membership guarantee.
- SEC: HEI mixed share-class and time-basis denominator confirmed;
  VSH and GOOGL bounded controls have additional class/weighted-average
  caveats; 51 events remain audit-only and historical SEC scorer-to-
  accession/CIK binding unresolved. The existing WOLF nulls stay null.
- Score-sidecar uncertainties are **retrospective evaluation diagnostics**
  only: they did NOT remove names from B0 or candidates at signal time.
- Long holding windows overlap. 24 monthly dates are not 25,025
  independent observations; do not claim a p-value or statistical
  significance from row count.

These caveats are independently reasons to avoid promoting a
fragile result; here the registered primary gate fails **before**
invoking them.

## Final stop and handoff

1. **Lock the result:** `PR_A_FINAL_DECISION=NO_GO_KEEP_V1`.
   No qualifying R or E candidate exists to justify conditional X1.
2. **Preserve 2025 / 2026 Q1 embargo:** no development winner exists
   to lock for confirmatory temporal diagnostics. Do not peek for a
   new alternative or retune the current model after observing them.
3. **Do not open PR-B.** Continue the current canonical v1 Beta
   unchanged, with existing Quality / Entry / Action / Top-k rules.
4. **Complete PR-A evidence governance only:** copy/append the
   permitted compact A0, B0, SEC, membership, dev-run and final
   decision evidence to `evidence-observations` following the
   repository's append-only process; pin exact evidence commit SHA,
   data/code/protocol hashes and CI. Do not push bulk corrected v3,
   original SEC/Alpaca material, secret files or 25k-row raw data.
5. Run final exact-HEAD CI and PR reviewer checks. Owner alone
   decides whether to merge PR-A as a **negative-result research/
   reproducibility PR**; leave it draft until evidence archive and
   administrative checks are complete. Merging PR-A must not enable
   production optimization or silently claim a v1.1 release.
6. Improvements to SEC/PIT capture or data-quality monitoring, if
   valuable, should be scoped independently as correctness work,
   **not** used to reopen this already frozen candidate search
   without a separately approved future research plan.

This NO-GO is definitive for the **registered v1.1 historical
candidate batch and data/protocol version**, not proof that no
future research could ever produce an improvement.
