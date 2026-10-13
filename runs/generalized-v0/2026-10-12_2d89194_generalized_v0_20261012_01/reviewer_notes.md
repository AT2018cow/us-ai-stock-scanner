# Reviewer notes — generalized-v0 2026-10-12 experiment

## Scope and non-claims

- Single diagnostic session on a purposive 62-name cohort (12 strata × 5
  + AI/manual overlap). NOT a random market sample, NOT an official US
  Core universe, NOT OOS proof, NOT a production-promotion case.
- Provisional coverage groups are review strata, not verified GICS sectors
  or homogeneous accounting models. Group-level Quality means must not be
  read as issuer-comparable scores.

## Limitations and anomalies (all retained)

1. Raw bars withheld (see README): liquidity/entry comparisons rest on the
   committed derived diagnostics + manifest (76 symbols, 9,728 rows,
   dataset SHA `4be88e1a…`). Re-fetch is independently reproducible.
2. Validator warning: 1 decision whose latest periodic filing is not
   covered by recognized Company Facts (fact-asof trails the filing;
   existing fail-closed path, no silent promotion).
3. Readiness-probe artifact (same-host cache only, NOT provider data):
   a bulk-batch bars query served stale tails (through 2026-09-25) for 47
   names due to a min-timestamp cache-freshness quirk; small-batch and
   single-session re-queries confirmed provider-side 10-12 completeness
   for all 62+QQQ+SPY before launch, and the scanner's own freshness
   handling resolved decision_date=2026-10-12 from observed bars. Filed
   as a future cache-hardening note; it did not touch this evidence
   (scan fetched its own bars and passed validation).
4. Legacy AI-channel ranked lists are empty for this universe (expected:
   the 62 names carry posthoc source tags, not AI buckets). Decisions do
   not depend on those lists.

## What would change my reading

- A second, temporally distinct (or prospective) cohort with the same
  frozen policy.
- Archived snapshot-dollar-volume series enabling same-date
  snapshot-vs-bar liquidity pairs (currently INCONCLUSIVE by construction).
- An independent business-model classifier before any cross-industry
  Quality comparison.
