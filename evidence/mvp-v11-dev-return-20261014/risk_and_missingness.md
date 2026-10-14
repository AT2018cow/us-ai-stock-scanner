# Risk and missingness — retrospective monthly attention-cap proxy

The v3 stock and QQQ forward return legs are already net of estimated
15bps entry + 15bps exit per leg. No second cost was applied.
This is NOT an executed portfolio NAV or a fresh independent OOS.
Data universe is retrospective / union_superset_approx.

Known risk: HEI mixed share-class and weighted-average denominators;
51 unresolved audit-only events, incomplete historical SEC CIK/accession
source binding; WOLF already nulled labels; possible true rallies.
Masks never changed historical ranks; sensitivity drops entire
paired dates when *either* B0 or candidate contains a flagged name.

## Primary Top-15 60d paired date coverage

| ID | Valid / 24 | Event sensitivity | Score sensitivity |
|---|---:|---:|---:|
| B0 | 24 / 24 | 18 | 15 |
| E1 | 24 / 24 | 18 | 15 |
| E2 | 24 / 24 | 18 | 15 |
| E3 | 24 / 24 | 18 | 15 |
| E4 | 24 / 24 | 18 | 15 |
| R1 | 24 / 24 | 17 | 14 |
| R2 | 24 / 24 | 17 | 14 |
| R3 | 24 / 24 | 17 | 14 |
| R4 | 24 / 24 | 17 | 14 |
| R5 | 24 / 24 | 17 | 13 |

2023 and 2024 individual-year metrics are present in
metrics_by_period.csv; do not treat these overlapping views
as independent candidate trials or choose on a single year.

Market regime distribution (B0 dates only):
- down: 4 dates
- up: 20 dates
