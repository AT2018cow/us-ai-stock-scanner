# Short Research v1 — Frozen Evaluation

- Scope: `smoke`
- Contract: `short_research_v1` · Rule: `short_research_rules_v1`
- Evidence class: retrospective frozen SIP cross-sections; not OOS and not a return promise.
- Verdict: **insufficient_evidence**
- Verdict reasons: fewer than 24 mature complete dates

## 1. Inputs

| dataset | freq | rows | dates | sha256 |
|---|---|---|---|---|
| sip_2016_2020_v1 | monthly | 31516 | 60 | 0944488aa43c0cd9… |
| sip_2021_2026_v1 | monthly | 49015 | 70 | aaaca3090da010e2… |

## 2. Funnel

| stage | rows |
|---|---|
| input_rows | 2445 |
| u0_rows | 1506 |
| u0_unique_rows | 1503 |
| industry_rs_rows | 871 |
| pe_eligible_rows | 1083 |
| pe_rows | 520 |
| u_rows | 493 |
| s0_rows | 171 |
| s1_rows | 18 |
| s2_rows | 4 |
| selected_rows | 4 |
- S2 signal dates: 3

## 3. Main 20d same-slot result

| metric | value |
|---|---|
| mature complete dates | 3 |
| S0 mean short gross | -2.6% |
| S1 mean short gross | -13.3% |
| S2 mean short gross | -7.1% |
| S1-S0 | -10.6% |
| S2-S1 | +6.1% |
| S2-S0 | -4.5% |
| S2-S0 95% CI | [-11.2%, +0.1%] |
| S2 95% CI | [-24.2%, +11.3%] |
| S2-S0 positive date ratio | 33.3% |
| base cost S2 mean | -12.2% |
| stress cost S2 mean | -13.5% |
| leave-one-company-out S2-S0 | -8.3% |

### By year (S2-S0, 20d same-slot)

| year | S2-S0 |
|---|---|
| 2020 | -11.2% |
| 2022 | +0.1% |
| 2025 | -2.4% |

## 4. Segments

| segment | view | dates | S2 | S2-S0 | positive ratio |
|---|---|---|---|---|---|
| ALL | same | 3 | -7.1% | -4.5% | 33.3% |
| ALL | fixed | 4 | -2.3% | +5.4% | 50.0% |
| ALL_MONTHLY | same | 3 | -7.1% | -4.5% | 33.3% |
| ALL_MONTHLY | fixed | 4 | -2.3% | +5.4% | 50.0% |
| BEAR_2022 | same | 1 | -8.5% | +0.1% | 100.0% |
| BEAR_2022 | fixed | 1 | -1.7% | +18.4% | 100.0% |
| YEAR_2016 | same | 0 | n/a | n/a | n/a |
| YEAR_2016 | fixed | 1 | +0.0% | +0.0% | 0.0% |
| YEAR_2020 | same | 1 | -24.2% | -11.2% | 0.0% |
| YEAR_2020 | fixed | 1 | -9.7% | +11.3% | 100.0% |
| YEAR_2022 | same | 1 | -8.5% | +0.1% | 100.0% |
| YEAR_2022 | fixed | 1 | -1.7% | +18.4% | 100.0% |
| YEAR_2025 | same | 1 | +11.3% | -2.4% | 0.0% |
| YEAR_2025 | fixed | 1 | +2.3% | -8.1% | 0.0% |

## 5. Casebook

| case | date | symbol | status | label | note |
|---|---|---|---|---|---|
| synthetic_missing_label | n/a | n/a | INSUFFICIENT_DATA | False | synthetic casebook entry; no historical example available |

## 6. Scan integration evidence

- Evidence type: `frozen_input_adapter_simulation`
- Statuses observed: ['no_candidates', 'ready']
- Mocked scan entry: off/on long decisions identical=True · legacy CSV identical=True · on short status=ready · truncation status=unavailable · short-failure status=unavailable
- A credentialed live SIP scan was not run here; the frozen adapter and snapshot/report contract are covered by tests and the commands file.

## 8. Honest limitations

- Monthly inputs are largely `union_superset_approx`; peer and company coverage is affected by the frozen universe.
- Labels are overlapping forward returns; date-level aggregation is used, not independent-row inference.
- Borrow evidence is `UNKNOWN` for all historical rows; no historical borrow database exists.
- Costs are assumptions, not observed borrow fees or locates.
- Period-end adverse-up is reported; intraperiod maximum adverse excursion is not verified without raw frozen daily paths.
- Retrospective results do not promote production behavior and are not OOS.
