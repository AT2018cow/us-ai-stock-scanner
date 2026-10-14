# PR-A bounded historical SEC / EdgarTools audit

**This is evidence collection, not candidate optimization.** A0 structural and
B0 historical parity have passed; PIT and the 52-event risk review remain
open. The script never edits historical v3 inputs, source masks, decisions,
production v1 or candidate returns.

Uses the repository's existing edgartools==5.61.1 dependency and
fundamentals.edgartools_diagnostic identity configuration. There are two
separate modes and only the first four HEI cases are approved for the
initial network audit.

## Step 0: exact code and tests

Protect uncommitted local work, fetch PR #70 branch, check HEAD and wait for
CI PASS on that precise commit. Then run:

~~~bash
git status --short
git rev-parse HEAD
python -m unittest discover -s tests
~~~

No Modal, Alpaca, new historical data extraction or production changes.

## Step 1: freeze 13 or fewer cases OFFLINE (zero SEC requests)

~~~bash
python scripts/mvp_v11_sec_pit_audit.py prepare \
  --entry-dataset outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv \
  --entry-meta outputs/historical_selection_v1_20261011_03/evidence/entry_quality_dataset_risk_off.meta.json \
  --archived-ranking outputs/mvp_v11_b0/refs/ranking_paired_by_date.csv \
  --output-dir outputs/mvp_v11_sec_pit/cases_01
~~~

If metadata is in a different verified local directory, use its original
path. Never rename or edit it. This creates case_manifest.json with
cases_sha256 and sec_pit_cases.csv. The case list is four HEI signal dates
(2023-12-29, 2024-12-31, 2025-08-29, 2025-12-31) FIRST, then predeclared
Top-1, Top-8 and Top-15 controls on 2023-01-31, 2024-01-31 and
2024-12-31. No historical return columns are read during case selection.

Stop on SHA/date/row count/duplicate errors. Do not modify the frozen
sec_pit_cases.csv after producing its SHA.

## Step 2: bounded SEC queries, HEI ONLY

Copy cases_sha256 from case_manifest.json. Set EDGAR_IDENTITY privately
to a valid SEC request identity, never print/email/commit it.

~~~bash
python scripts/mvp_v11_sec_pit_audit.py verify \
  --cases outputs/mvp_v11_sec_pit/cases_01/sec_pit_cases.csv \
  --expected-cases-sha256 YOUR_CASES_SHA256 \
  --allow-network \
  --inspect-xbrl \
  --max-cases 4 \
  --output-dir outputs/mvp_v11_sec_pit/hei_01
~~~

The explicit --allow-network flag is required. Each audit case is limited
to at most three SEC filing-header inspections for forms 10-K, 10-Q and
amendments, bounded by its signal_date, and one selected filing's
share-facts XBRL query. Some library lookups fetch SEC submissions metadata,
so use courteous request rates. Stop and report SEC rate limits rather than
running uncontrolled retries.

The script converts SGML filing.header.acceptance_datetime from naive
US/Eastern to UTC, not from UTC-naive. Same-day filings are always
UNVERIFIED until a reliable historical early-close calendar is available.
A filing visible before the signal date is *not* proof that the original
2023–2026 feature extraction used that accession. Current ticker-to-CIK
lookup is not verified historical identity.

Outputs:
- sec_pit_filing_review.jsonl: up to four small case rows with exact
  filing accession, CIK, time, source permalink and bounded share facts;
  SEC class/dimension ambiguity remains explicit.
- sec_pit_audit_summary.json: query counts/hashes and
  ready_for_candidate_returns=false.

## Step 3: HEI source interpretation (manual, outcome-blind)

Cross-check HEI vs HEI.A classes, dated accession and acceptance, XBRL
share units and dimensions, then contrast frozen shares_outstanding,
shares_asof_end and market_cap at the four signal dates. Check whether
historical scoring effectively used Common-only or both classes. Do not
multiply two-class total shares by one single-class price to certify
issuer market cap. Missing class dimension is UNVERIFIED, never inferred.

Find original historical accession/CIK binding only in previously frozen
SEC cache or research manifests, without rewriting source rows or silently
using a 2026 ticker map for 2023. Record source permalink/byte hash and
the evidence cutoff. Later restatements cannot be backfilled.

Do not run the additional nine fixed control cases before this HEI
review is examined. Do not edit the 52-event UNREVIEWED queue. No
R/E/X1 return calculations or candidate comparisons.

## Deliverables for review

Send compact Markdown note, case_manifest.json, sec_pit_audit_summary.json,
the limited sec_pit_filing_review.jsonl, exact PR HEAD, green CI result,
all input/output SHA256 and a list of remaining UNVERIFIED findings.
Keep raw 25k-row CSV, full SEC caches, credentials and network material
inside ignored outputs. Do not commit sensitive or licensed raw payloads.

This evidence-only run cannot unlock candidate returns by itself.
