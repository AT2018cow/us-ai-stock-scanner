# Detailed Report — MSFT — MICROSOFT CORP

## MSFT — MICROSOFT CORP

- Decision date: 2026-10-12
- Company Quality: A
- Entry Quality: ENTRY_READY
- Action State: PRIORITY_REVIEW
- Priority: 5
- Fundamental data as-of: 2026-07-29
- Market data as-of: 2026-10-12
- Review trigger: Review now; downgrade if Company Quality falls below A or Entry Quality leaves ENTRY_READY.
- Previous action: n/a
- State change reason: New prospective decision snapshot.

## Company Quality

- Grade: A
- Score: 0.813333
- Confidence: 1.0
- Data as-of: 2026-07-29

### Component Scores

- balance_sheet: 0.85
- dilution: 1.0
- growth_stability: 1.0
- operating_red_flags: 0.5
- profitability_cash: 0.8
- valuation_context: 0.533333

### Positives

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.408177; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=66987000000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=1.350582; threshold=>=0.8 supportive; <0.5 weak)
- `revenue_yoy_strong` — Revenue growth supportive: Revenue growth supports the quality assessment. (polarity=positive; metric=revenue_yoy; value=0.177887; threshold=>=8% supportive; <-10% weak)
- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=0.330122; threshold=>=15% strong; <-10% weak)
- `operating_cash_flow_yoy_strong` — Operating cash-flow growth supportive: Operating cash-flow growth supports the quality assessment. (polarity=positive; metric=operating_cash_flow_yoy; value=0.34351; threshold=>=15% strong; <-10% weak)
- `net_debt_to_ebitda_strong` — Net debt / EBITDA supportive: Net debt / EBITDA supports the quality assessment. (polarity=positive; metric=net_debt_to_ebitda; value=0.052981; threshold=<=1.5 supportive; >4 weak)
- `interest_coverage_strong` — Interest coverage supportive: Interest coverage supports the quality assessment. (polarity=positive; metric=interest_coverage; value=53.470869; threshold=>=4 supportive; <1 weak)
- `current_ratio_strong` — Current ratio supportive: Current ratio supports the quality assessment. (polarity=positive; metric=current_ratio; value=1.230327; threshold=>=1 supportive; <0.75 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.001025; threshold=<=3% supportive; >12% weak)
- `pe_hist_percentile_strong` — Historical P/E percentile supportive: Historical P/E percentile supports the quality assessment. (polarity=positive; metric=pe_hist_percentile; value=0.5; threshold=<=60% supportive; >80% expensive)
- `receivables_growth_gap_strong` — Receivables growth gap supportive: Receivables growth gap supports the quality assessment. (polarity=positive; metric=receivables_growth_gap; value=-0.020945; threshold=<=5pp supportive; >25pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=75; threshold=<=400)

## Quality Applicability

- Company Quality v1 is one common financial-quality core. Specialist accounting semantics (banks, brokers, insurers, REITs, foreign or unsupported reporting models) are pending independent review; until then, cross-model comparability is UNVERIFIED for every decision, and this grade must not be read as sector-relative quality.
- Applicability for THIS decision: not disproven, but still unverified across business models — compare with caution.

## Entry Quality

- State: ENTRY_READY
- Structure: Price holds above its long-term trend inside the readiness band with non-negative momentum — a healthy structure that is not overextended.
- Score: 0.945
- Confidence: 1.0
- Market as-of: 2026-10-12

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.246015; threshold=>=1.00 healthy; <0.95 damaged)
- `price_near_sma50_ready_band` — Price near SMA50: Price is in the pre-registered SMA50 readiness band. (polarity=positive; metric=price_to_sma50; value=1.077937; threshold=0.98–1.08)
- `return_20d_ready_band` — 20d return in readiness band: Recent momentum is positive/controlled rather than chased. (polarity=positive; metric=return_20d; value=0.06993; threshold=-3% to +12%)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.37326; threshold=>=0%)
- `relative_strength_60d_qqq_ready` — 60d relative strength acceptable: The stock is keeping pace with QQQ over 60 trading days. (polarity=positive; metric=relative_strength_60d_qqq; value=0.300357; threshold=>=-3%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

## Counter-Evidence

- `accrual_ratio_weak` — Accrual quality weak: Accrual quality is a material counter-signal for Company Quality. (polarity=negative; metric=accrual_ratio; value=-0.228617; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `inventory_growth_gap_weak` — Inventory growth gap weak: Inventory growth gap is a material counter-signal for Company Quality. (polarity=negative; metric=inventory_growth_gap; value=0.311452; threshold=<=10pp supportive; >30pp weak)

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
- cik: 0000789019
- code_sha: 220a4716c411bd7e9e80f9f7f89502f6ab1ff0ac
- config_fingerprint: e778b6553cf52859581a8bfa5101af564a8be83fda011aace9b5639b8162a50e
- entry_policy_version: entry_quality_v1_2026-10-10
- filing_entity_name: MICROSOFT CORP
- fundamental_companyfacts_raw_sha256: 75bebe2eebf09fd5c1383646a761563922c8eb0f2cdb107a13e526572a5140c3
- fundamental_companyfacts_sha256: 75bebe2eebf09fd5c1383646a761563922c8eb0f2cdb107a13e526572a5140c3
- fundamental_currency_supported: True
- fundamental_edgartools_fallback_fact_count: 0
- fundamental_edgartools_fallback_status: not_needed
- fundamental_edgartools_fallback_used: False
- fundamental_effective_sha256: 553f3ad16c3be2e5dbd5c8e7be3bf6ee080e18b31f1c178f68d1eaa3d9923a93
- fundamental_facts_cover_latest_periodic: True
- fundamental_latest_periodic_accession: 0001193125-26-323660
- fundamental_latest_periodic_filing_date: 2026-07-29
- fundamental_latest_periodic_form: 10-K
- fundamental_operating_entity_detail: ticker_listed_with_core_facts
- fundamental_operating_entity_verified: True
- fundamental_reporting_currency: USD
- fundamental_source: companyfacts
- fundamental_submissions_sha256: 4d3bc92df5bdd9fbaaaa37e05ba66b5c357ba3987b8135bc8a52f13efac01df5
- identity_scoring_sha: 0b0951ca097bc27015e6338542b03a12c3f74eebbd631d7cb78a7dabe3ad60c5
- quality_policy_version: company_quality_v1_2026-10-10
- scan_config_path: outputs/config.mvp_beta.json
- strategy_style: risk_off
- watchlist_csv_path: data/ai_watchlist.csv
- watchlist_etf_count: 0
