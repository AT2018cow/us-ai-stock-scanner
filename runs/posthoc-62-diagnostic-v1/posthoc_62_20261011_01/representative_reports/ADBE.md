# Detailed Report — ADBE — ADOBE INC.

## ADBE — ADOBE INC.

- Decision date: 2026-10-09
- Company Quality: A
- Entry Quality: TREND_DAMAGED
- Action State: HOLD_MONITOR
- Priority: 23
- Fundamental data as-of: 2026-09-22
- Market data as-of: 2026-10-09
- Review trigger: Re-review on a Quality or Entry state change; prioritize only if Quality A reaches ENTRY_READY.
- Previous action: HOLD_MONITOR
- State change reason: n/a

## Decision Rationale

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.280477; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=10592000000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=1.483526; threshold=>=0.8 supportive; <0.5 weak)
- `revenue_yoy_strong` — Revenue growth supportive: Revenue growth supports the quality assessment. (polarity=positive; metric=revenue_yoy; value=0.120314; threshold=>=8% supportive; <-10% weak)
- `accrual_ratio_weak` — Accrual quality weak: Accrual quality is a material counter-signal for Company Quality. (polarity=negative; metric=accrual_ratio; value=-0.384582; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `price_materially_below_sma200` — Price materially below SMA200: Long-term price structure is materially damaged. (polarity=negative; metric=price_to_sma200; value=0.942566; threshold=>=1.00 healthy; <0.95 damaged)
- `price_below_sma50` — Price below SMA50: Shorter-term trend confirmation is weak. (polarity=negative; metric=price_to_sma50; value=0.939285; threshold=>=0.97)

## Company Quality

- Grade: A
- Score: 0.805
- Confidence: 1.0
- Data as-of: 2026-09-22

### Component Scores

- balance_sheet: 0.8
- dilution: 1.0
- growth_stability: 0.7
- operating_red_flags: 1.0
- profitability_cash: 0.75
- valuation_context: 0.8

### Positives

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.280477; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=10592000000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=1.483526; threshold=>=0.8 supportive; <0.5 weak)
- `revenue_yoy_strong` — Revenue growth supportive: Revenue growth supports the quality assessment. (polarity=positive; metric=revenue_yoy; value=0.120314; threshold=>=8% supportive; <-10% weak)
- `net_debt_to_ebitda_strong` — Net debt / EBITDA supportive: Net debt / EBITDA supports the quality assessment. (polarity=positive; metric=net_debt_to_ebitda; value=-0.085882; threshold=<=1.5 supportive; >4 weak)
- `interest_coverage_strong` — Interest coverage supportive: Interest coverage supports the quality assessment. (polarity=positive; metric=interest_coverage; value=75.373984; threshold=>=4 supportive; <1 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.070234; threshold=<=3% supportive; >12% weak)
- `fcf_yield_strong` — FCF yield supportive: FCF yield supports the quality assessment. (polarity=positive; metric=fcf_yield; value=0.11236; threshold=>=2% supportive; <-2% weak)
- `ps_hist_percentile_strong` — Historical P/S percentile supportive: Historical P/S percentile supports the quality assessment. (polarity=positive; metric=ps_hist_percentile; value=0.4; threshold=<=60% supportive; >80% expensive)
- `pe_hist_percentile_strong` — Historical P/E percentile supportive: Historical P/E percentile supports the quality assessment. (polarity=positive; metric=pe_hist_percentile; value=0.4; threshold=<=60% supportive; >80% expensive)
- `receivables_growth_gap_strong` — Receivables growth gap supportive: Receivables growth gap supports the quality assessment. (polarity=positive; metric=receivables_growth_gap; value=-0.126047; threshold=<=5pp supportive; >25pp weak)
- `inventory_growth_gap_strong` — Inventory growth gap supportive: Inventory growth gap supports the quality assessment. (polarity=positive; metric=inventory_growth_gap; value=0.0; threshold=<=10pp supportive; >30pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=17; threshold=<=400)

### Risks

- `accrual_ratio_weak` — Accrual quality weak: Accrual quality is a material counter-signal for Company Quality. (polarity=negative; metric=accrual_ratio; value=-0.384582; threshold=|accrual|<=0.10 supportive; >0.35 weak)

### Missing Evidence

- none

## Entry Quality

- State: TREND_DAMAGED
- Score: 0.325
- Confidence: 1.0
- Market as-of: 2026-10-09

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.029236; threshold=>=0%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

### Risks

- `price_materially_below_sma200` — Price materially below SMA200: Long-term price structure is materially damaged. (polarity=negative; metric=price_to_sma200; value=0.942566; threshold=>=1.00 healthy; <0.95 damaged)
- `price_below_sma50` — Price below SMA50: Shorter-term trend confirmation is weak. (polarity=negative; metric=price_to_sma50; value=0.939285; threshold=>=0.97)

## Decision History

- Previous action: HOLD_MONITOR
- State change: n/a

## Provenance

- Schema version: 1
- Generated at UTC: 2026-10-12T02:22:26.219967+00:00
- Source lists: n/a
- code_sha: 6711919c8ea91dbe27345829c957cd72611533e0
- cohort: generalized_v0_62frozen
- entry_policy_version: entry_quality_v1_2026-10-10
- membership_asof: 2026-10-11 (NOT PIT for these dates)
- mode: retrospective_posthoc_cohort
- quality_policy_version: company_quality_v1_2026-10-10
- watchlist_bucket: posthoc:us_core
- watchlist_etf_count: 1
- watchlist_etfs: -
