# Quality failure cases v1 (corrected — 2026-10-09 post-hoc decisions)

CORRECTION vs the first version: bank leverage/interest-coverage metrics
did NOT score against JPM/BAC/MS/WFC — they are MISSING (the entire
`balance_sheet` component is None). The C grades reflect (a) narrow scored
risks, (b) absent balance-sheet support, (c) structurally inapplicable
semantics. The three mechanisms are now separated per name; see
`quality_driver_attribution.csv` for the machine-readable table.

No re-weighting proposed. No thresholds touched.

## JPM — C without a single leverage score (mixed mechanisms)

- Scored (1 risk): `ocf_to_net_income_weak` (-2.45) — genuine OCF
  conversion weakness, though the OCF definition itself is bank-doubtful.
- Missing (8): free_cash_flow, accrual, net_debt_to_ebitda,
  interest_coverage, current_ratio, fcf_yield, ps percentile,
  receivables gap — i.e. the whole balance-sheet component is None.
- Inapplicable: net_debt/interest_coverage/current_ratio/fcf_yield for a
  deposit franchise (deposits as debt; NII as the earnings engine).
- Conclusion: absent support + one OCF risk, NOT a leverage verdict.

## BAC — C on one growth risk plus silence (mixed)

- Scored (1): `operating_cash_flow_yoy_weak` (-5.18).
- Missing (7): same balance-sheet silence as JPM.
- Note `profitability_cash` reads 1.0 — C is not uniform weakness.

## MS — C on two OCF risks (mixed, broker caveat)

- Scored (2): OCF conversion (-0.77), OCF YoY (-0.12). Both use the
  broker OCF definition — scored, but the definition is under review.
- Missing (8): same silence. Inapplicable leverage set as JPM.

## WFC — same pattern, outside the registered 11 (corroboration only)

- Scored (2): `revenue_yoy_weak` (-13.8% — needs NII/noninterest split
  before calling it demand weakness), OCF YoY (-3.10).
- Missing (8): same silence. Growth component only 0.217.

## GS — UNRATED on vocabulary + artifacts (missing-coverage)

- Correct entity (0000886982). Scored cash negatives (-$41.5B FCF,
  OCF/NI -1.87) are broker cash-flow classification artifacts.
- Missing (9): revenue tags absent (`RevenuesNetOfInterestExpense` et al.
  not in v1 map). Settling work is tag-vocabulary research.

## XOM — UNRATED on entity/content (unmeasurable, see inventory)

- 14 missings, zero risks. Holdings-mapped entity yields no usable
  operating values; provider serves opco-scale facts under the successor
  CIK on some fetches and shell-only on others (flap observed 6.6MB ↔
  84KB within the hour). Neither run's XOM label is stable evidence.

## AMT / EQIX — readable B's, unverified models

- AMT: accrual (-0.70) + current-ratio (0.35) risks are REIT depreciation
  and working-capital structure, not distress. EQIX: -$875M FCF is
  property capex, not burn. Both fully measured — and both must stay
  non-comparable with ordinary B's until FFO/AFFO semantics land.
