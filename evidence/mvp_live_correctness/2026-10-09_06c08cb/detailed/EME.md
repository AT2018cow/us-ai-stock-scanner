# Detailed Report — EME — EMCOR Group, Inc.

## EME — EMCOR Group, Inc.

- Decision date: 2026-10-09
- Company Quality: A
- Entry Quality: ENTRY_READY
- Action State: PRIORITY_REVIEW
- Priority: 9
- Fundamental data as-of: 2026-07-30
- Market data as-of: 2026-10-09
- Review trigger: Review now; downgrade if Company Quality falls below A or Entry Quality leaves ENTRY_READY.
- Previous action: n/a
- State change reason: New prospective decision snapshot.

## Decision Rationale

- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=1171382000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=0.99827; threshold=>=0.8 supportive; <0.5 weak)
- `accrual_ratio_strong` — Accrual quality supportive: Accrual quality supports the quality assessment. (polarity=positive; metric=accrual_ratio; value=0.000335; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `revenue_yoy_strong` — Revenue growth supportive: Revenue growth supports the quality assessment. (polarity=positive; metric=revenue_yoy; value=0.189214; threshold=>=8% supportive; <-10% weak)
- `pe_hist_percentile_weak` — Historical P/E percentile weak: Historical P/E percentile is a material counter-signal for Company Quality. (polarity=negative; metric=pe_hist_percentile; value=1.0; threshold=<=60% supportive; >80% expensive)

## Company Quality

- Grade: A
- Score: 0.836667
- Confidence: 1.0
- Data as-of: 2026-07-30

### Component Scores

- balance_sheet: 0.916667
- dilution: 1.0
- growth_stability: 0.783333
- operating_red_flags: 1.0
- profitability_cash: 0.85
- valuation_context: 0.416667

### Positives

- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=1171382000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=0.99827; threshold=>=0.8 supportive; <0.5 weak)
- `accrual_ratio_strong` — Accrual quality supportive: Accrual quality supports the quality assessment. (polarity=positive; metric=accrual_ratio; value=0.000335; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `revenue_yoy_strong` — Revenue growth supportive: Revenue growth supports the quality assessment. (polarity=positive; metric=revenue_yoy; value=0.189214; threshold=>=8% supportive; <-10% weak)
- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=0.170074; threshold=>=15% strong; <-10% weak)
- `net_debt_to_ebitda_strong` — Net debt / EBITDA supportive: Net debt / EBITDA supports the quality assessment. (polarity=positive; metric=net_debt_to_ebitda; value=-0.497929; threshold=<=1.5 supportive; >4 weak)
- `interest_coverage_strong` — Interest coverage supportive: Interest coverage supports the quality assessment. (polarity=positive; metric=interest_coverage; value=148.3802; threshold=>=4 supportive; <1 weak)
- `current_ratio_strong` — Current ratio supportive: Current ratio supports the quality assessment. (polarity=positive; metric=current_ratio; value=1.27685; threshold=>=1 supportive; <0.75 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.014618; threshold=<=3% supportive; >12% weak)
- `fcf_yield_strong` — FCF yield supportive: FCF yield supports the quality assessment. (polarity=positive; metric=fcf_yield; value=0.03366; threshold=>=2% supportive; <-2% weak)
- `receivables_growth_gap_strong` — Receivables growth gap supportive: Receivables growth gap supports the quality assessment. (polarity=positive; metric=receivables_growth_gap; value=0.049787; threshold=<=5pp supportive; >25pp weak)
- `inventory_growth_gap_strong` — Inventory growth gap supportive: Inventory growth gap supports the quality assessment. (polarity=positive; metric=inventory_growth_gap; value=0.0; threshold=<=10pp supportive; >30pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=71; threshold=<=400)

### Risks

- `pe_hist_percentile_weak` — Historical P/E percentile weak: Historical P/E percentile is a material counter-signal for Company Quality. (polarity=negative; metric=pe_hist_percentile; value=1.0; threshold=<=60% supportive; >80% expensive)

### Missing Evidence

- none

## Entry Quality

- State: ENTRY_READY
- Score: 0.913333
- Confidence: 1.0
- Market as-of: 2026-10-09

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.01516; threshold=>=1.00 healthy; <0.95 damaged)
- `price_near_sma50_ready_band` — Price near SMA50: Price is in the pre-registered SMA50 readiness band. (polarity=positive; metric=price_to_sma50; value=1.014515; threshold=0.98–1.08)
- `return_20d_ready_band` — 20d return in readiness band: Recent momentum is positive/controlled rather than chased. (polarity=positive; metric=return_20d; value=0.011773; threshold=-3% to +12%)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.050708; threshold=>=0%)
- `relative_strength_60d_qqq_ready` — 60d relative strength acceptable: The stock is keeping pace with QQQ over 60 trading days. (polarity=positive; metric=relative_strength_60d_qqq; value=-0.013505; threshold=>=-3%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

### Risks

- none

## Decision History

- Previous action: n/a
- State change: New prospective decision snapshot.

## Provenance

- Schema version: 1
- Generated at UTC: 2026-10-10T14:41:55.127064+00:00
- Source lists: low_value, research_pool
- code_sha: 06c08cb3d7db76baee4389a93eee11958a6732dc
- config_fingerprint: a9f081748727d4a2affcf8aae93c05cfa607d45b4a2e6a6d61b413adc1070a6c
- entry_policy_version: entry_quality_v1_2026-10-10
- fundamental_currency_supported: True
- fundamental_facts_cover_latest_periodic: True
- fundamental_latest_periodic_accession: 0000105634-26-000110
- fundamental_latest_periodic_filing_date: 2026-07-30
- fundamental_latest_periodic_form: 10-Q
- fundamental_reporting_currency: USD
- quality_policy_version: company_quality_v1_2026-10-10
- scan_config_path: configs/config.risk_off.json
- strategy_style: risk_off
- watchlist_bucket: ai_enabler,ai_peripheral
- watchlist_csv_path: data/ai_watchlist.csv
- watchlist_etf_count: 3
- watchlist_etfs: FXR,IFRA,PAVE
