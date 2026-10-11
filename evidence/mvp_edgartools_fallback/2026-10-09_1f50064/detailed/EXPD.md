# Detailed Report — EXPD — EXPEDITORS INTERNATIONAL OF WASHINGTON INC

## EXPD — EXPEDITORS INTERNATIONAL OF WASHINGTON INC

- Decision date: 2026-10-09
- Company Quality: A
- Entry Quality: ENTRY_READY
- Action State: PRIORITY_REVIEW
- Priority: 15
- Fundamental data as-of: 2026-08-05
- Market data as-of: 2026-10-09
- Review trigger: Review now; downgrade if Company Quality falls below A or Entry Quality leaves ENTRY_READY.
- Previous action: n/a
- State change reason: New prospective decision snapshot.

## Decision Rationale

- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=923864000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=1.058492; threshold=>=0.8 supportive; <0.5 weak)
- `accrual_ratio_strong` — Accrual quality supportive: Accrual quality supports the quality assessment. (polarity=positive; metric=accrual_ratio; value=-0.013412; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `net_debt_to_ebitda_strong` — Net debt / EBITDA supportive: Net debt / EBITDA supports the quality assessment. (polarity=positive; metric=net_debt_to_ebitda; value=-0.832964; threshold=<=1.5 supportive; >4 weak)
- `ps_hist_percentile_weak` — Historical P/S percentile weak: Historical P/S percentile is a material counter-signal for Company Quality. (polarity=negative; metric=ps_hist_percentile; value=1.0; threshold=<=60% supportive; >80% expensive)
- `pe_hist_percentile_weak` — Historical P/E percentile weak: Historical P/E percentile is a material counter-signal for Company Quality. (polarity=negative; metric=pe_hist_percentile; value=1.0; threshold=<=60% supportive; >80% expensive)

## Company Quality

- Grade: A
- Score: 0.786667
- Confidence: 1.0
- Data as-of: 2026-08-05

### Component Scores

- balance_sheet: 1.0
- dilution: 1.0
- growth_stability: 0.6
- operating_red_flags: 0.65
- profitability_cash: 0.9
- valuation_context: 0.316667

### Positives

- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=923864000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=1.058492; threshold=>=0.8 supportive; <0.5 weak)
- `accrual_ratio_strong` — Accrual quality supportive: Accrual quality supports the quality assessment. (polarity=positive; metric=accrual_ratio; value=-0.013412; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `net_debt_to_ebitda_strong` — Net debt / EBITDA supportive: Net debt / EBITDA supports the quality assessment. (polarity=positive; metric=net_debt_to_ebitda; value=-0.832964; threshold=<=1.5 supportive; >4 weak)
- `interest_coverage_strong` — Interest coverage supportive: Interest coverage supports the quality assessment. (polarity=positive; metric=interest_coverage; value=246.54125; threshold=>=4 supportive; <1 weak)
- `current_ratio_strong` — Current ratio supportive: Current ratio supports the quality assessment. (polarity=positive; metric=current_ratio; value=1.565586; threshold=>=1 supportive; <0.75 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.042204; threshold=<=3% supportive; >12% weak)
- `fcf_yield_strong` — FCF yield supportive: FCF yield supports the quality assessment. (polarity=positive; metric=fcf_yield; value=0.036845; threshold=>=2% supportive; <-2% weak)
- `inventory_growth_gap_strong` — Inventory growth gap supportive: Inventory growth gap supports the quality assessment. (polarity=positive; metric=inventory_growth_gap; value=0.0; threshold=<=10pp supportive; >30pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=65; threshold=<=400)

### Risks

- `ps_hist_percentile_weak` — Historical P/S percentile weak: Historical P/S percentile is a material counter-signal for Company Quality. (polarity=negative; metric=ps_hist_percentile; value=1.0; threshold=<=60% supportive; >80% expensive)
- `pe_hist_percentile_weak` — Historical P/E percentile weak: Historical P/E percentile is a material counter-signal for Company Quality. (polarity=negative; metric=pe_hist_percentile; value=1.0; threshold=<=60% supportive; >80% expensive)

### Missing Evidence

- none

## Entry Quality

- State: ENTRY_READY
- Score: 0.835
- Confidence: 1.0
- Market as-of: 2026-10-09

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.177982; threshold=>=1.00 healthy; <0.95 damaged)
- `price_near_sma50_ready_band` — Price near SMA50: Price is in the pre-registered SMA50 readiness band. (polarity=positive; metric=price_to_sma50; value=1.031292; threshold=0.98–1.08)
- `return_20d_ready_band` — 20d return in readiness band: Recent momentum is positive/controlled rather than chased. (polarity=positive; metric=return_20d; value=0.001012; threshold=-3% to +12%)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.060037; threshold=>=0%)
- `relative_strength_60d_qqq_ready` — 60d relative strength acceptable: The stock is keeping pace with QQQ over 60 trading days. (polarity=positive; metric=relative_strength_60d_qqq; value=-0.004176; threshold=>=-3%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

### Risks

- none

## Decision History

- Previous action: n/a
- State change: New prospective decision snapshot.

## Provenance

- Schema version: 1
- Generated at UTC: 2026-10-10T17:59:12.254542+00:00
- Source lists: n/a
- code_sha: 1f500648b9a00382fdc5b32bbf09330d0fdf5211
- config_fingerprint: a9f081748727d4a2affcf8aae93c05cfa607d45b4a2e6a6d61b413adc1070a6c
- entry_policy_version: entry_quality_v1_2026-10-10
- fundamental_currency_supported: True
- fundamental_edgartools_fallback_fact_count: 0
- fundamental_edgartools_fallback_status: not_needed
- fundamental_edgartools_fallback_used: False
- fundamental_facts_cover_latest_periodic: True
- fundamental_latest_periodic_accession: 0001193125-26-334457
- fundamental_latest_periodic_filing_date: 2026-08-05
- fundamental_latest_periodic_form: 10-Q
- fundamental_reporting_currency: USD
- fundamental_source: companyfacts
- quality_policy_version: company_quality_v1_2026-10-10
- scan_config_path: configs/config.risk_off.json
- strategy_style: risk_off
- watchlist_bucket: ai_peripheral
- watchlist_csv_path: data/ai_watchlist.csv
- watchlist_etf_count: 1
- watchlist_etfs: IYT
