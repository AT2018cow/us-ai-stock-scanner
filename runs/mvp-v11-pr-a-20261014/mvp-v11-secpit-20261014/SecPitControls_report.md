# MVP v1.1 PR-A — nine frozen SEC control cases (evidence only)

Date: 2026-10-14
Code: PR #70 head `b05c61204005d50a1c58cf4b8ff103567eb5ac4b`
(CI pass, run 38520265582; local 712 tests OK)
Approval basis: runbook "Reviewer follow-up: nine frozen controls approved"
+ adjudication doc §HEI; original 13-case CSV unchanged
(SHA `ed20b66a…`), `--case-type FIXED_TOP15_CONTROL --max-cases 9`,
edgartools 5.61.1, private EDGAR_IDENTITY env only. HEI not re-queried.
All 9 verdicts stay UNVERIFIED by design (`n_cases_pit_fully_verified: 0`).

## 1. Deliverables (same evidence dir as HEI)

| File | SHA256 |
| --- | --- |
| `sec_pit_controls_summary.json` | `5ebaf53c…` |
| `sec_pit_controls_review.jsonl` | `86970213…` (9 rows) |

Summary: `case_count: 9`, timing `FILING_PUBLIC_BEFORE_SIGNAL_DATE: 9`,
`ready_for_candidate_returns: false`.

## 2. Filings retrieved (all 10-Q, all accepted before signal dates)

| Signal date | Case | Filing | Accession | Accepted UTC |
| --- | --- | --- | --- | --- |
| 2023-01-31 | VSH Top-1 | 10-Q | 0000103730-22-000072 | 2022-11-02 |
| 2023-01-31 | VRSN Top-8 | 10-Q | 0001014473-22-000027 | 2022-10-27 |
| 2023-01-31 | BRKR Top-15 | 10-Q | 0000950170-22-022163 | 2022-11-04 |
| 2024-01-31 | BRKR Top-1 | 10-Q | 0000950170-23-062192 | 2023-11-09 |
| 2024-01-31 | CSGP Top-8 | 10-Q | 0001057352-23-000127 | 2023-10-25 |
| 2024-01-31 | TEL Top-15 | 10-Q | 0001558370-24-000581 | 2024-01-26 |
| 2024-12-31 | ANET Top-1 | 10-Q | 0001596532-24-000368 | 2024-11-07 |
| 2024-12-31 | GOOGL Top-8 | 10-Q | 0001652044-24-000118 | 2024-10-29 |
| 2024-12-31 | AMZN Top-15 | 10-Q | 0001018724-24-000161 | 2024-10-31 |

CIKs: VSH 103730, VRSN 1014473, BRKR 1109354, CSGP 1057352, TEL 1385157,
ANET 1596532, GOOGL 1652044, AMZN 1018724.

## 3. Frozen shares vs filing facts (outcome-blind cross-check)

- **7 of 9 match the DEI cover point-in-time share count exactly:**
  BRKR ×2 (147,082,724 / 138,411,212), VRSN (106,016,456), CSGP
  (408,363,368), TEL (308,798,987), AMZN (10,515,011,008), ANET (314,939,883).
  Single-class scope, price leg continuous — no HEI-style flip.
- **VSH**: frozen 143,983,000 equals the filing's weighted-average basic
  (period ended 2022-10-01) exactly — same *concept* as HEI's 10-K source,
  but VSH's Class B is small (~12.1M of ~141.7M cover total, ~8.5%) and there
  is no observed alternation for this issuer. Flagged as a concept note, not
  a scope flip.
- **GOOGL**: frozen 12,264,000,000 (asof 2024-09-30) vs filing DEI facts at
  2024-10-22 totaling ~12,241M across Class A + B + C — within 0.2% on
  slightly different as-of dates; three-class total scope, no flip observed.
  (Class B is non-traded, ~7% of the total; full-issuer-cap semantics for
  multi-class names remain an open definition question, same as HEI.)

No control shows the ~2.5× definition alternation seen in HEI. Frozen
`shares_asof_end` values match the corresponding filing instants.

## 4. Correction accepted (runbook follow-up)

The 2.51–2.52× figures in the HEI report compare frozen inputs against
**HEI Common-only equity value**, not verified full issuer market cap
(HEI.A is separately priced). I retract any "true issuer mcap" reading:
the established fact is a **confirmed inconsistent input scope**
(annual weighted-average two-class total vs quarterly Common-only),
not an approved numeric repair or inflation factor.

## 5. Still open (unchanged)

Historical ticker→CIK binding, proof of which accession the original scorer
used, intraday timing beyond dates, restatements, and any return impact.
`ready_for_candidate_returns: false`. No dev-return command executed; no
merge. Awaiting your final risk-gate review and the exact-SHA run
authorization (`I_APPROVE_FROZEN_2023_2024_DEV_ONLY` + code/protocol SHAs).
Reference SHAs for that authorization: code `b05c61204005d50a1c58cf4b8ff103567eb5ac4b`,
protocol `ce5234ece45756135c8d2e01614757fa4b0dfd4f3bcc5b6b0fa23bab4cd7c589`,
registry `385070b343188237dc518b7f8690ed154f8906b38e641588159deaee3d0d393d`,
preflight manifest `6b3fdc526e9519c3fc3b6c03068953f15dc831a47ff538e459f95113b18633fb`.
