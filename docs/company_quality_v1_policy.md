# Company Quality v1 policy

> Status: **pre-registered MVP v1 policy**
>
> Date frozen for Implementation PR 2: 2026-10-10
>
> Policy version: `company_quality_v1_2026-10-10`

This document records the first Company Quality rules **before final historical
outcome tables are inspected**. The purpose is to keep the first evaluation
diagnostic rather than tune grades to retrospective returns.

## 1. Inputs

Company Quality v1 reuses the existing PIT accounting and valuation features.
It does not introduce a new data provider or new fundamental reconstruction.

The six components are:

| Component | Weight | Inputs |
|---|---:|---|
| Profitability / cash quality | 30% | net margin, free cash flow, OCF / net income, accrual ratio |
| Growth / stability | 20% | revenue YoY, adjusted earnings YoY when available (otherwise reported earnings YoY), OCF YoY |
| Balance-sheet strength | 20% | net debt / EBITDA, interest coverage, current ratio |
| Dilution | 10% | shares YoY |
| Valuation context | 10% | FCF yield, historical P/S percentile, historical P/E percentile |
| Operating red flags | 10% | receivables growth gap, inventory growth gap |

AI/theme membership is not a Quality component. ETF membership remains candidate
discovery context only.

## 2. Missing-data rule

Missing metrics do **not** receive a neutral 0.5 fallback.

For each component:

1. the component score is the mean of observed metric scores;
2. component coverage is observed metrics / expected metrics;
3. the component contributes
   `weight × component_score × component_coverage`;
4. total confidence is the weighted component coverage.

Therefore deleting a weak metric cannot mechanically improve the effective
Quality score. Missing data also emits explicit `missing` evidence.

A rated grade requires confidence >= 0.50. Quality A requires confidence >= 0.80.

## 3. Metric thresholds

### Profitability / cash quality

- net margin:
  - >= 20% -> 1.00
  - >= 10% -> 0.80
  - >= 3% -> 0.60
  - >= 0% -> 0.40
  - < 0% -> 0.00
- free cash flow:
  - > 0 -> 1.00
  - = 0 -> 0.50
  - < 0 -> 0.00
- OCF / net income:
  - >= 1.0 -> 1.00
  - >= 0.8 -> 0.80
  - >= 0.5 -> 0.50
  - >= 0 -> 0.25
  - < 0 -> 0.00
- absolute accrual ratio:
  - <= 0.05 -> 1.00
  - <= 0.10 -> 0.80
  - <= 0.20 -> 0.50
  - <= 0.35 -> 0.20
  - > 0.35 -> 0.00

### Growth / stability

Revenue YoY:

- >= 15% -> 1.00
- >= 8% -> 0.80
- >= 0% -> 0.50
- >= -10% -> 0.25
- < -10% -> 0.00

Adjusted earnings YoY when available, otherwise reported earnings YoY:

- >= 15% -> 1.00
- >= 0% -> 0.65
- >= -10% -> 0.35
- < -10% -> 0.00

Operating cash-flow YoY uses the same bands as earnings YoY.

### Balance sheet

Net debt / EBITDA:

- <= 0 -> 1.00
- <= 1.5 -> 0.80
- <= 3.0 -> 0.55
- <= 4.0 -> 0.30
- > 4.0 -> 0.00

Interest coverage:

- >= 8 -> 1.00
- >= 4 -> 0.80
- >= 2 -> 0.50
- >= 1 -> 0.25
- < 1 -> 0.00

Current ratio:

- >= 1.5 -> 1.00
- >= 1.0 -> 0.75
- >= 0.75 -> 0.40
- < 0.75 -> 0.10

### Dilution

Shares YoY:

- <= 0% -> 1.00
- <= 3% -> 0.80
- <= 7% -> 0.50
- <= 12% -> 0.25
- > 12% -> 0.00

### Valuation context

FCF yield:

- >= 5% -> 1.00
- >= 2% -> 0.75
- >= 0% -> 0.50
- >= -2% -> 0.25
- < -2% -> 0.00

Historical P/S and P/E percentile:

- <= 35% -> 1.00
- <= 60% -> 0.70
- <= 80% -> 0.40
- > 80% -> 0.10

Valuation has only 10% weight and cannot by itself create Quality A.

### Operating red flags

Receivables growth minus revenue growth:

- <= 5 percentage points -> 1.00
- <= 15pp -> 0.60
- <= 25pp -> 0.30
- > 25pp -> 0.00

Inventory growth minus revenue growth:

- <= 10pp -> 1.00
- <= 20pp -> 0.60
- <= 30pp -> 0.30
- > 30pp -> 0.00

## 4. Grade mapping

The effective score is the weighted, coverage-adjusted component score.

- **UNRATED**
  - confidence < 0.50; or
  - fundamental data is more than 550 days stale.
- **A**
  - score >= 0.72;
  - confidence >= 0.80;
  - profitability/cash component >= 0.60 with at least 75% component coverage;
  - balance-sheet component >= 0.50 with at least two of three inputs present;
  - no severe red flag.
- **B**
  - score >= 0.50;
  - confidence >= 0.65;
  - fewer than two severe red flags.
- **C**
  - any other rated case.

Severe red flags for v1 are:

- net debt / EBITDA > 5;
- interest coverage < 1;
- share-count growth > 15%;
- receivables growth gap > 30pp;
- inventory growth gap > 35pp;
- negative net margin and negative free cash flow together.

One severe flag blocks A. Two or more prevent B.

## 5. Freshness

Historical replay records the latest visible SEC filing date among the canonical
fundamental fact records used by the PIT reconstruction.

- data age <= 400 days: freshness is supportive;
- 401–550 days: explicit stale-data risk and confidence is reduced by 10%;
- > 550 days: UNRATED;
- missing as-of provenance: Quality A is suppressed.

A fundamental as-of date after the decision date is a hard validation error.

## 6. Historical evaluation

The retrospective dataset must be taken **before legacy list-specific hard
gates**. It may use the archived PIT watchlist snapshots, or the already
documented pre-snapshot union approximation. The latter must remain labelled as
a universe approximation.

Required diagnostics:

- counts / coverage for A, B, C, UNRATED;
- 20d / 60d / 120d return and QQQ excess by grade;
- row-level and decision-date-equal-weight means;
- year splits;
- regime splits;
- symbol / date concentration;
- cross-sectional Spearman correlation where the numeric score exists.

These are retrospective diagnostics, not automatic promotion criteria. This PR
does not tune any threshold from those outcomes.
