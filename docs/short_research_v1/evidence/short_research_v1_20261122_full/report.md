# Short Research v1 — Frozen Evaluation

- Scope: `full`
- Contract: `short_research_v1` · Rule: `short_research_rules_v1`
- Evidence class: retrospective frozen SIP cross-sections; not OOS and not a return promise.
- Verdict: **signal_or_increment_failed**
- Verdict reasons: S2 absolute short gross return is not positive; S2-S0 paired difference is not positive

## 1. Inputs

| dataset | freq | rows | dates | sha256 |
|---|---|---|---|---|
| sip_2016_2020_v1 | monthly | 31516 | 60 | 0944488aa43c0cd9… |
| sip_2021_2026_v1 | monthly | 49015 | 70 | aaaca3090da010e2… |
| sip_covid_weekly_v1 | weekly | 11861 | 21 | 9518f538d0db3e67… |
| sip_bear_weekly_v1 | weekly | 35747 | 52 | d2fd0dc9b7a21d17… |

## 2. Funnel

| stage | rows |
|---|---|
| input_rows | 128139 |
| u0_rows | 95945 |
| u0_unique_rows | 95743 |
| industry_rs_rows | 54083 |
| pe_eligible_rows | 69495 |
| pe_rows | 32949 |
| u_rows | 31134 |
| s0_rows | 8692 |
| s1_rows | 734 |
| s2_rows | 165 |
| selected_rows | 163 |
- S2 signal dates: 103

## 3. Main 20d same-slot result

| metric | value |
|---|---|
| mature complete dates | 64 |
| S0 mean short gross | -0.9% |
| S1 mean short gross | -2.7% |
| S2 mean short gross | -0.9% |
| S1-S0 | -1.8% |
| S2-S1 | +1.8% |
| S2-S0 | -0.0% |
| S2-S0 95% CI | [-3.6%, +2.8%] |
| S2 95% CI | [-3.3%, +1.4%] |
| S2-S0 positive date ratio | 48.4% |
| base cost S2 mean | -0.4% |
| stress cost S2 mean | -1.5% |
| leave-one-company-out S2-S0 | -0.5% |

### By year (S2-S0, 20d same-slot)

| year | S2-S0 |
|---|---|
| 2016 | -0.2% |
| 2017 | +2.4% |
| 2018 | +0.3% |
| 2019 | +11.2% |
| 2020 | -7.4% |
| 2021 | -0.7% |
| 2022 | -4.4% |
| 2023 | -2.8% |
| 2024 | +0.7% |
| 2025 | -7.7% |
| 2026 | +9.8% |

## 4. Segments

| segment | view | dates | S2 | S2-S0 | positive ratio |
|---|---|---|---|---|---|
| ALL | same | 102 | +0.6% | +1.5% | 48.0% |
| ALL | fixed | 202 | +0.1% | +0.8% | 53.5% |
| ALL_MONTHLY | same | 64 | -0.9% | -0.0% | 48.4% |
| ALL_MONTHLY | fixed | 129 | -0.2% | +0.3% | 51.2% |
| ALL_WEEKLY | same | 38 | +3.1% | +4.0% | 47.4% |
| ALL_WEEKLY | fixed | 73 | +0.6% | +1.5% | 57.5% |
| COVID_2020_02_03 | same | 4 | +14.0% | -2.3% | 25.0% |
| COVID_2020_02_03 | fixed | 8 | +2.3% | -10.8% | 37.5% |
| COVID_2020_04_06 | same | 10 | -2.4% | +15.8% | 80.0% |
| COVID_2020_04_06 | fixed | 13 | -0.4% | +11.7% | 100.0% |
| BEAR_2022 | same | 30 | +3.7% | -0.8% | 36.7% |
| BEAR_2022 | fixed | 64 | +0.6% | +0.5% | 50.0% |
| YEAR_2016 | same | 7 | -0.0% | -0.2% | 57.1% |
| YEAR_2016 | fixed | 12 | -0.2% | -0.2% | 41.7% |
| YEAR_2017 | same | 5 | +0.7% | +2.4% | 60.0% |
| YEAR_2017 | fixed | 12 | -0.0% | +0.2% | 58.3% |
| YEAR_2018 | same | 6 | +0.5% | +0.3% | 33.3% |
| YEAR_2018 | fixed | 12 | +0.1% | -0.3% | 50.0% |
| YEAR_2019 | same | 4 | -5.8% | +11.2% | 100.0% |
| YEAR_2019 | fixed | 12 | -0.6% | +1.0% | 58.3% |
| YEAR_2020 | same | 18 | +0.5% | +6.6% | 55.6% |
| YEAR_2020 | fixed | 33 | +0.2% | +3.2% | 75.8% |
| YEAR_2021 | same | 4 | -0.9% | -0.7% | 50.0% |
| YEAR_2021 | fixed | 12 | +0.0% | -1.4% | 50.0% |
| YEAR_2022 | same | 30 | +3.7% | -0.8% | 36.7% |
| YEAR_2022 | fixed | 64 | +0.6% | +0.5% | 50.0% |
| YEAR_2023 | same | 7 | -3.2% | -2.8% | 42.9% |
| YEAR_2023 | fixed | 12 | -0.9% | -1.8% | 41.7% |
| YEAR_2024 | same | 11 | +1.5% | +0.7% | 45.5% |
| YEAR_2024 | fixed | 12 | +0.3% | +1.1% | 33.3% |
| YEAR_2025 | same | 5 | -2.1% | -7.7% | 40.0% |
| YEAR_2025 | fixed | 12 | -0.2% | -0.8% | 50.0% |
| YEAR_2026 | same | 5 | -4.7% | +9.8% | 60.0% |
| YEAR_2026 | fixed | 9 | -1.6% | +5.1% | 55.6% |

## 5. Casebook

| case | date | symbol | status | label | note |
|---|---|---|---|---|---|
| confirmed_not_selected_cap | 2024-04-30 | KNX | CONFIRMED | True | CONFIRMED but outside the five-slot list |
| selected_group_member_missing_label | 2026-10-30 | ADBE | NO_SIGNAL | False | missing endpoint kept as missing; no substitution |

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
