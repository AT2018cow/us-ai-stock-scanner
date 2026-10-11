# Fallback cases (from canonical decisions.jsonl)

Source snapshot: outputs/decision_experiments/risk_off_20261010T235815Z/2026-10-09/risk_off
Code SHA: 313c5ffedc9c1cf837b70d5e95d01d545d5c592f

### EXLS — ExlService Holdings, Inc.
- Quality grade: A (confidence 1.0)
- Action: PRIORITY_REVIEW / Entry: ENTRY_READY
- fundamental_data_asof: 2026-07-28
- latest periodic filing: 10-Q 2026-07-28 (accession 0001297989-26-000023)
- fundamental_source: companyfacts+edgartools_exact_10q
- fallback used: True / status: used / version: usd_10q_v1 / fact count: 63
- reporting currency: USD (supported: True)
- facts_cover_latest_periodic: True
- missing/risk evidence codes: none

### JCI — Johnson Controls International plc
- Quality grade: A (confidence 1.0)
- Action: PRIORITY_REVIEW / Entry: ENTRY_READY
- fundamental_data_asof: 2026-07-29
- latest periodic filing: 10-Q 2026-07-29 (accession 0000833444-26-000087)
- fundamental_source: companyfacts+edgartools_exact_10q
- fallback used: True / status: used / version: usd_10q_v1 / fact count: 62
- reporting currency: USD (supported: True)
- facts_cover_latest_periodic: True
- missing/risk evidence codes: ps_hist_percentile_weak

### PYPL — PayPal Holdings, Inc.
- Quality grade: A (confidence 1.0)
- Action: WATCH_BREAKOUT / Entry: WATCH_BREAKOUT
- fundamental_data_asof: 2026-07-28
- latest periodic filing: 10-Q 2026-07-28 (accession 0001633917-26-000082)
- fundamental_source: companyfacts+edgartools_exact_10q
- fallback used: True / status: used / version: usd_10q_v1 / fact count: 55
- reporting currency: USD (supported: True)
- facts_cover_latest_periodic: True
- missing/risk evidence codes: none

### CDNS — CADENCE DESIGN SYSTEMS INC
- Quality grade: C (confidence 1.0)
- Action: AVOID / Entry: WATCH_PULLBACK
- fundamental_data_asof: 2026-07-29
- latest periodic filing: 10-Q 2026-07-29 (accession 0000813672-26-000092)
- fundamental_source: companyfacts+edgartools_exact_10q
- fallback used: True / status: used / version: usd_10q_v1 / fact count: 59
- reporting currency: USD (supported: True)
- facts_cover_latest_periodic: True
- missing/risk evidence codes: accrual_ratio_weak, receivables_growth_gap_weak, inventory_growth_gap_weak

### NXPI — NXP Semiconductors N.V.
- Quality grade: A (confidence 1.0)
- Action: HOLD_MONITOR / Entry: TREND_DAMAGED
- fundamental_data_asof: 2026-07-28
- latest periodic filing: 10-Q 2026-07-28 (accession 0001413447-26-000045)
- fundamental_source: companyfacts+edgartools_exact_10q
- fallback used: True / status: used / version: usd_10q_v1 / fact count: 73
- reporting currency: USD (supported: True)
- facts_cover_latest_periodic: True
- missing/risk evidence codes: none

### NEE — NEXTERA ENERGY INC
- Quality grade: B (confidence 0.933333)
- Action: HOLD_MONITOR / Entry: TREND_DAMAGED
- fundamental_data_asof: 2026-07-24
- latest periodic filing: 10-Q 2026-07-24 (accession 0000753308-26-000060)
- fundamental_source: companyfacts+edgartools_exact_10q
- fallback used: True / status: used / version: usd_10q_v1 / fact count: 64
- reporting currency: USD (supported: True)
- facts_cover_latest_periodic: True
- missing/risk evidence codes: interest_coverage_missing, accrual_ratio_weak, net_debt_to_ebitda_weak, current_ratio_weak

### TTAN — ServiceTitan, Inc.
- Quality grade: UNRATED (confidence 0.49)
- Action: AVOID / Entry: TREND_DAMAGED
- fundamental_data_asof: 2026-09-08
- latest periodic filing: 10-Q 2026-09-08 (accession 0001638826-26-000096)
- fundamental_source: companyfacts
- fallback used: False / status: filing_mismatch / version: n/a (no version key in provenance) / fact count: 0
- reporting currency: None (supported: None)
- facts_cover_latest_periodic: False
- missing/risk evidence codes: interest_coverage_missing, pe_hist_percentile_missing, latest_periodic_filing_not_covered, net_margin_weak, ocf_to_net_income_weak, accrual_ratio_weak, adjusted_net_income_yoy_weak, net_debt_to_ebitda_weak

### TSM — TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD
- Quality grade: UNRATED (confidence 0.166667)
- Action: AVOID / Entry: ENTRY_READY
- fundamental_data_asof: 2026-04-16
- latest periodic filing: 20-F 2026-04-16 (accession 0001628280-26-025362)
- fundamental_source: companyfacts
- fallback used: False / status: ineligible_form / version: n/a (no version key in provenance) / fact count: 0
- reporting currency: None (supported: None)
- facts_cover_latest_periodic: False
- missing/risk evidence codes: net_margin_missing, free_cash_flow_missing, ocf_to_net_income_missing, accrual_ratio_missing, revenue_yoy_missing, operating_cash_flow_yoy_missing, net_debt_to_ebitda_missing, interest_coverage_missing, current_ratio_missing, fcf_yield_missing, ps_hist_percentile_missing, pe_hist_percentile_missing, receivables_growth_gap_missing, inventory_growth_gap_missing, latest_periodic_filing_not_covered

### ASML — ASML HOLDING NV
- Quality grade: UNRATED (confidence 0.1)
- Action: AVOID / Entry: WATCH_BREAKOUT
- fundamental_data_asof: 2026-02-25
- latest periodic filing: 20-F 2026-02-25 (accession 0001628280-26-011378)
- fundamental_source: companyfacts
- fallback used: False / status: not_needed / version: n/a (no version key in provenance) / fact count: 0
- reporting currency: EUR (supported: False)
- facts_cover_latest_periodic: True
- missing/risk evidence codes: net_margin_missing, free_cash_flow_missing, ocf_to_net_income_missing, accrual_ratio_missing, revenue_yoy_missing, net_income_yoy_missing, operating_cash_flow_yoy_missing, net_debt_to_ebitda_missing, interest_coverage_missing, current_ratio_missing, fcf_yield_missing, ps_hist_percentile_missing, pe_hist_percentile_missing, receivables_growth_gap_missing, inventory_growth_gap_missing, fundamental_currency_unsupported

### SAP — SAP SE
- Quality grade: UNRATED (confidence 0.1)
- Action: AVOID / Entry: WATCH_BREAKOUT
- fundamental_data_asof: 2026-02-26
- latest periodic filing: 20-F 2026-02-26 (accession 0001104659-26-020058)
- fundamental_source: companyfacts
- fallback used: False / status: not_needed / version: n/a (no version key in provenance) / fact count: 0
- reporting currency: EUR (supported: False)
- facts_cover_latest_periodic: True
- missing/risk evidence codes: net_margin_missing, free_cash_flow_missing, ocf_to_net_income_missing, accrual_ratio_missing, revenue_yoy_missing, net_income_yoy_missing, operating_cash_flow_yoy_missing, net_debt_to_ebitda_missing, interest_coverage_missing, current_ratio_missing, fcf_yield_missing, ps_hist_percentile_missing, pe_hist_percentile_missing, receivables_growth_gap_missing, inventory_growth_gap_missing, fundamental_currency_unsupported

## Additional decisions with fallback used=true or status other than not_needed/ineligible_form

| symbol | grade | action/entry | fallback used | status | fact count | latest periodic |
|---|---|---|---|---|---|---|
| AEP | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 61 | 10-Q 2026-07-30 |
| AMKR | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 68 | 10-Q 2026-07-28 |
| BE | UNRATED | AVOID/WATCH_PULLBACK | False | filing_mismatch | 0 | 10-Q 2026-07-29 |
| CNP | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 74 | 10-Q 2026-07-28 |
| CTSH | A | HOLD_MONITOR/TREND_DAMAGED | True | used | 74 | 10-Q 2026-07-29 |
| D | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 70 | 10-Q 2026-07-31 |
| DLR | B | HOLD_MONITOR/WATCH_BREAKOUT | True | used | 56 | 10-Q 2026-07-31 |
| DOW | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 65 | 10-Q 2026-07-24 |
| DTE | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 58 | 10-Q 2026-07-28 |
| DUK | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 62 | 10-Q 2026-08-04 |
| ED | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 65 | 10-Q 2026-08-06 |
| EIX | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 58 | 10-Q 2026-07-30 |
| ENPH | C | AVOID/TREND_DAMAGED | True | used | 59 | 10-Q 2026-07-28 |
| ETR | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 69 | 10-Q 2026-07-31 |
| EVRG | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 65 | 10-Q 2026-08-06 |
| EXC | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 61 | 10-Q 2026-07-30 |
| FE | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 60 | 10-Q 2026-07-28 |
| GD | A | HOLD_MONITOR/TREND_DAMAGED | True | used | 46 | 10-Q 2026-07-29 |
| HUBB | A | HOLD_MONITOR/TREND_DAMAGED | True | used | 68 | 10-Q 2026-07-29 |
| IDA | UNRATED | AVOID/TREND_DAMAGED | False | ttm_not_fresh | 0 | 10-Q 2026-07-30 |
| KNX | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 66 | 10-Q 2026-07-29 |
| LII | A | HOLD_MONITOR/TREND_DAMAGED | True | used | 58 | 10-Q 2026-07-29 |
| LNT | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 66 | 10-Q 2026-07-31 |
| MAA | C | AVOID/TREND_DAMAGED | True | used | 58 | 10-Q 2026-07-30 |
| MAS | A | HOLD_MONITOR/TREND_DAMAGED | True | used | 60 | 10-Q 2026-07-29 |
| OGE | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 66 | 10-Q 2026-07-29 |
| PLD | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 43 | 10-Q 2026-07-29 |
| PPG | A | HOLD_MONITOR/TREND_DAMAGED | True | used | 71 | 10-Q 2026-07-29 |
| PPL | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 64 | 10-Q 2026-08-07 |
| PSN | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 68 | 10-Q 2026-07-29 |
| RMBS | B | HOLD_MONITOR/WATCH_PULLBACK | True | used | 61 | 10-Q 2026-07-28 |
| RS | A | WATCH_BREAKOUT/WATCH_BREAKOUT | True | used | 60 | 10-Q 2026-07-28 |
| SMTC | A | WATCH_PULLBACK/WATCH_PULLBACK | True | used | 67 | 10-Q 2026-08-26 |
| SO | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 62 | 10-Q 2026-07-30 |
| SRE | B | HOLD_MONITOR/TREND_DAMAGED | True | used | 58 | 10-Q 2026-08-06 |
| URI | B | HOLD_MONITOR/WATCH_BREAKOUT | True | used | 66 | 10-Q 2026-07-22 |
| VLTO | A | WATCH_BREAKOUT/WATCH_BREAKOUT | True | used | 63 | 10-Q 2026-07-29 |
| VMC | A | HOLD_MONITOR/TREND_DAMAGED | True | used | 71 | 10-Q 2026-07-29 |
| VRSK | A | HOLD_MONITOR/TREND_DAMAGED | True | used | 60 | 10-Q 2026-07-29 |
| WELL | C | AVOID/WATCH_BREAKOUT | True | used | 46 | 10-Q 2026-07-28 |

Decisions with fallback used=true: 44.
