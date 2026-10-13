# Detailed Report — TMO — THERMO FISHER SCIENTIFIC INC.

## TMO — THERMO FISHER SCIENTIFIC INC.

- Decision date: 2026-10-12
- Company Quality: A
- Entry Quality: ENTRY_READY
- Action State: PRIORITY_REVIEW
- Priority: 6
- Fundamental data as-of: 2026-07-31
- Market data as-of: 2026-10-12
- Review trigger: Review now; downgrade if Company Quality falls below A or Entry Quality leaves ENTRY_READY.
- Previous action: n/a
- State change reason: New prospective decision snapshot.

## Company Quality

- Grade: A
- Score: 0.801667
- Confidence: 1.0
- Data as-of: 2026-07-31

### Component Scores

- balance_sheet: 0.783333
- dilution: 1.0
- growth_stability: 0.716667
- operating_red_flags: 1.0
- profitability_cash: 0.9
- valuation_context: 0.316667

### Positives

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.153919; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=7318000000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=1.263741; threshold=>=0.8 supportive; <0.5 weak)
- `accrual_ratio_strong` — Accrual quality supportive: Accrual quality supports the quality assessment. (polarity=positive; metric=accrual_ratio; value=-0.080505; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `operating_cash_flow_yoy_strong` — Operating cash-flow growth supportive: Operating cash-flow growth supports the quality assessment. (polarity=positive; metric=operating_cash_flow_yoy; value=0.189364; threshold=>=15% strong; <-10% weak)
- `interest_coverage_strong` — Interest coverage supportive: Interest coverage supports the quality assessment. (polarity=positive; metric=interest_coverage; value=5.779555; threshold=>=4 supportive; <1 weak)
- `current_ratio_strong` — Current ratio supportive: Current ratio supports the quality assessment. (polarity=positive; metric=current_ratio; value=1.550534; threshold=>=1 supportive; <0.75 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.021833; threshold=<=3% supportive; >12% weak)
- `fcf_yield_strong` — FCF yield supportive: FCF yield supports the quality assessment. (polarity=positive; metric=fcf_yield; value=0.029881; threshold=>=2% supportive; <-2% weak)
- `receivables_growth_gap_strong` — Receivables growth gap supportive: Receivables growth gap supports the quality assessment. (polarity=positive; metric=receivables_growth_gap; value=0.027426; threshold=<=5pp supportive; >25pp weak)
- `inventory_growth_gap_strong` — Inventory growth gap supportive: Inventory growth gap supports the quality assessment. (polarity=positive; metric=inventory_growth_gap; value=-0.060062; threshold=<=10pp supportive; >30pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=73; threshold=<=400)

## Quality Applicability

- Company Quality v1 is one common financial-quality core. Specialist accounting semantics (banks, brokers, insurers, REITs, foreign or unsupported reporting models) are pending independent review; until then, cross-model comparability is UNVERIFIED for every decision, and this grade must not be read as sector-relative quality.
- Applicability for THIS decision: not disproven, but still unverified across business models — compare with caution.

## Entry Quality

- State: ENTRY_READY
- Structure: Price holds above its long-term trend inside the readiness band with non-negative momentum — a healthy structure that is not overextended.
- Score: 1.0
- Confidence: 1.0
- Market as-of: 2026-10-12

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.214544; threshold=>=1.00 healthy; <0.95 damaged)
- `price_near_sma50_ready_band` — Price near SMA50: Price is in the pre-registered SMA50 readiness band. (polarity=positive; metric=price_to_sma50; value=1.054339; threshold=0.98–1.08)
- `return_20d_ready_band` — 20d return in readiness band: Recent momentum is positive/controlled rather than chased. (polarity=positive; metric=return_20d; value=0.079123; threshold=-3% to +12%)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.244654; threshold=>=0%)
- `relative_strength_60d_qqq_ready` — 60d relative strength acceptable: The stock is keeping pace with QQQ over 60 trading days. (polarity=positive; metric=relative_strength_60d_qqq; value=0.171751; threshold=>=-3%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

## Counter-Evidence

- `ps_hist_percentile_weak` — Historical P/S percentile weak: Historical P/S percentile is a material counter-signal for Company Quality. (polarity=negative; metric=ps_hist_percentile; value=1.0; threshold=<=60% supportive; >80% expensive)
- `pe_hist_percentile_weak` — Historical P/E percentile weak: Historical P/E percentile is a material counter-signal for Company Quality. (polarity=negative; metric=pe_hist_percentile; value=1.0; threshold=<=60% supportive; >80% expensive)

## Missing Evidence

- none

## Next Review Conditions

- Trigger: Review now; downgrade if Company Quality falls below A or Entry Quality leaves ENTRY_READY.
- Structure: Watch for loss of the readiness band or momentum breakdown.

## Decision History

- Previous action: n/a
- State change: New prospective decision snapshot.

## Evidence & Provenance

- Schema version: 1
- Generated at UTC: 2026-10-13T09:32:59.988550+00:00
- Source lists: n/a
- cik: 0000097745
- code_sha: 220a4716c411bd7e9e80f9f7f89502f6ab1ff0ac
- config_fingerprint: e778b6553cf52859581a8bfa5101af564a8be83fda011aace9b5639b8162a50e
- entry_policy_version: entry_quality_v1_2026-10-10
- filing_entity_name: THERMO FISHER SCIENTIFIC INC.
- fundamental_companyfacts_raw_sha256: 0461c15e7ec810f6e85e8ee23e5901bf2fe65af49af16f14de8e64a8f45ce039
- fundamental_companyfacts_sha256: 0461c15e7ec810f6e85e8ee23e5901bf2fe65af49af16f14de8e64a8f45ce039
- fundamental_currency_supported: True
- fundamental_edgartools_fallback_fact_count: 0
- fundamental_edgartools_fallback_status: not_needed
- fundamental_edgartools_fallback_used: False
- fundamental_effective_sha256: 3cb549b428702cc5eda50cad02d5991128119b33de0ea2f33acb92a06260bb17
- fundamental_facts_cover_latest_periodic: True
- fundamental_latest_periodic_accession: 0000097745-26-000144
- fundamental_latest_periodic_filing_date: 2026-07-31
- fundamental_latest_periodic_form: 10-Q
- fundamental_operating_entity_detail: ticker_listed_with_core_facts
- fundamental_operating_entity_verified: True
- fundamental_reporting_currency: USD
- fundamental_source: companyfacts
- fundamental_submissions_sha256: 505ec20acb0ed157fa1eac86453e42bb82aced4fcf5e900a9e4f2d5b17b36723
- identity_scoring_sha: 81555e6fb1cad0f1fd1b303215acfb3c16003c3743fbca73fe7f2d9146d9eefc
- quality_policy_version: company_quality_v1_2026-10-10
- scan_config_path: outputs/config.mvp_beta.json
- strategy_style: risk_off
- watchlist_csv_path: data/ai_watchlist.csv
- watchlist_etf_count: 0
