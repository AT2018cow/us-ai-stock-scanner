# MVP v1.1 PR-A — HEI SEC/PIT audit report (evidence only)

Date: 2026-10-14
Code under test: PR #70 head `1d688dad8283ed4870f1e9899bcb0f82a60675dd`
(CI pass on this head, run 38513133665; local 686 tests OK)
Scope: HEI 4 signal dates only; 9 control cases frozen but NOT queried.
No v3 bytes, masks, decisions, or returns touched. All case verdicts stay
`UNVERIFIED` by tool design (`n_cases_pit_fully_verified: 0`).

## 1. Deliverables (in this directory)

| File | SHA256 |
| --- | --- |
| `case_manifest.json` | `c93082d7…` |
| `sec_pit_cases.csv` | `ed20b66a…` (13 cases: 4 HEI + 9 controls) |
| `sec_pit_audit_summary.json` | `b711f5d4…` |
| `sec_pit_filing_review.jsonl` | `67de7f00…` (4 HEI rows) |

Run: step-1 `prepare` (offline, 13 cases frozen); step-2 `verify`
(`--allow-network --inspect-xbrl --max-cases 4`, edgartools 5.61.1,
identity source `EDGAR_IDENTITY`, courteous sequential queries, no retries
needed). Filing timing for all 4 cases: `FILING_PUBLIC_BEFORE_SIGNAL_DATE`.

## 2. Filings retrieved (CIK 46619, HEICO)

| Signal date | Filing used | Accession | Accepted (UTC / ET) |
| --- | --- | --- | --- |
| 2023-12-29 | 10-K FY2023 | 0000046619-23-000163 | 2023-12-20 21:41 / 16:41 ET |
| 2024-12-31 | 10-K FY2024 | 0000046619-24-000111 | 2024-12-19 21:55 / 16:55 ET |
| 2025-08-29 | 10-Q Q3 FY2025 | 0000046619-25-000062 | 2025-08-27 20:31 / 16:31 ET |
| 2025-12-31 | 10-K FY2025 | 0000046619-25-000082 | 2025-12-22 21:44 / 16:44 ET |

Date-level public availability holds for all four (acceptance 2–12 days before
the signal date, all after 16:00 ET close — irrelevant given the multi-day
gap). This does **not** prove the original 2023–2026 scorer used these
accessions; no historical CIK/accession binding exists in the frozen v3.

## 3. Factual cross-check: class-scope mixing confirmed in frozen inputs

Each filing's XBRL exposes two share classes with distinct labels:

- `Heico Common Stock` (ticker HEI): ~54.7M → 55.1M across FY2023–FY2025
  (period-end outstanding: 54,721,000 / 54,986,000 / 55,143,000).
- `Common/Class A Common Stock` (ticker HEI.A): ~83.5M → 84.2M
  (83,507,000 / 83,827,000 / 84,198,000).

Frozen v3 `shares_outstanding` alternates between two different definitions:

| Signal date | Frozen shares | Matches filing fact | Class scope |
| --- | --- | --- | --- |
| 2023-12-29 | 137,185,000 | WeightedAverage basic FY2023 **exactly** | Common + Class A combined |
| 2024-12-31 | 138,455,000 | WeightedAverage basic FY2024 **exactly** | Common + Class A combined |
| 2025-08-29 | 55,054,000 | CommonStockSharesOutstanding 2025-07-31 **exactly** | Common only |
| 2025-12-31 | 139,048,000 | WeightedAverage basic FY2025 **exactly** | Common + Class A combined |

Frozen `market_cap` equals `shares_outstanding × HEI price` on all four dates
(verified to <1e-6), so on the three 10-K dates it multiplies a **two-class
share total by a single-class price** — the exact error the runbook warned
against:

| Signal date | Frozen mcap | Common-only mcap (HEI px) | Inflation ratio |
| --- | --- | --- | --- |
| 2023-12-29 | $24.56B | $9.80B | **2.51×** |
| 2024-12-31 | $32.93B | $13.08B | **2.52×** |
| 2025-08-29 | $17.19B | $17.19B | 1.00× (consistent) |
| 2025-12-31 | $44.97B | $17.84B | **2.52×** |

The v3 `shares_yoy` / valuation-percentile inputs built on these denominators
flip ~2.5× between 10-K and 10-Q dates for this issuer, while the price leg
stays continuous (price_ratio 0.87–1.05 across the same boundaries).

## 4. What this does and does not establish

- Establishes: annual 10-K filings for CIK 46619 were publicly accepted before
  each December signal date; their XBRL contains per-class share facts that
  exactly reproduce the frozen inputs under the two definitions above.
- Does not establish: that the original scorer consumed these accessions; the
  historical ticker→CIK binding; intraday availability beyond date granularity;
  currency/restatement continuity; or any return impact (no outcomes read).
- The 9 control cases and the unchanged 52-event UNREVIEWED queue are untouched.

## 5. Open items for your adjudication

1. Handling principle for the HEI share-scope flip (e.g. outcome-blind
   uncertainty flags on affected Quality valuation/dilution inputs, or a
   localized class-consistent repair) and whether the same 10-K-vs-10-Q source
   alternation affects other two-class issuers.
2. Whether additional PIT evidence (historical accession/CIK binding from
   frozen SEC cache or research manifests) is required before freezing masks.
3. Whether to run the 9 frozen control cases through the same bounded verify
   after this HEI review.
