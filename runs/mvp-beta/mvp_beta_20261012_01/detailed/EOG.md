# Detailed Report — EOG — EOG RESOURCES INC

## EOG — EOG RESOURCES INC

- Decision date: 2026-10-12
- Company Quality: A
- Entry Quality: ENTRY_READY
- Action State: PRIORITY_REVIEW
- Priority: 3
- Fundamental data as-of: 2026-08-04
- Market data as-of: 2026-10-12
- Review trigger: Review now; downgrade if Company Quality falls below A or Entry Quality leaves ENTRY_READY.
- Previous action: n/a
- State change reason: New prospective decision snapshot.

## Company Quality

- Grade: A
- Score: 0.836667
- Confidence: 1.0
- Data as-of: 2026-08-04

### Component Scores

- balance_sheet: 0.933333
- dilution: 1.0
- growth_stability: 1.0
- operating_red_flags: 0.65
- profitability_cash: 0.75
- valuation_context: 0.6

### Positives

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.254422; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=12460000000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=1.942699; threshold=>=0.8 supportive; <0.5 weak)
- `revenue_yoy_strong` — Revenue growth supportive: Revenue growth supports the quality assessment. (polarity=positive; metric=revenue_yoy; value=0.19073; threshold=>=8% supportive; <-10% weak)
- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=0.199581; threshold=>=15% strong; <-10% weak)
- `operating_cash_flow_yoy_strong` — Operating cash-flow growth supportive: Operating cash-flow growth supports the quality assessment. (polarity=positive; metric=operating_cash_flow_yoy; value=0.251687; threshold=>=15% strong; <-10% weak)
- `net_debt_to_ebitda_strong` — Net debt / EBITDA supportive: Net debt / EBITDA supports the quality assessment. (polarity=positive; metric=net_debt_to_ebitda; value=0.217568; threshold=<=1.5 supportive; >4 weak)
- `interest_coverage_strong` — Interest coverage supportive: Interest coverage supports the quality assessment. (polarity=positive; metric=interest_coverage; value=37.893617; threshold=>=4 supportive; <1 weak)
- `current_ratio_strong` — Current ratio supportive: Current ratio supports the quality assessment. (polarity=positive; metric=current_ratio; value=1.851359; threshold=>=1 supportive; <0.75 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.039312; threshold=<=3% supportive; >12% weak)
- `fcf_yield_strong` — FCF yield supportive: FCF yield supports the quality assessment. (polarity=positive; metric=fcf_yield; value=0.157849; threshold=>=2% supportive; <-2% weak)
- `inventory_growth_gap_strong` — Inventory growth gap supportive: Inventory growth gap supports the quality assessment. (polarity=positive; metric=inventory_growth_gap; value=-0.195013; threshold=<=10pp supportive; >30pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=69; threshold=<=400)

## Quality Applicability

- Company Quality v1 is one common financial-quality core. Specialist accounting semantics (banks, brokers, insurers, REITs, foreign or unsupported reporting models) are pending independent review; until then, cross-model comparability is UNVERIFIED for every decision, and this grade must not be read as sector-relative quality.
- Applicability for THIS decision: not disproven, but still unverified across business models — compare with caution.

## Entry Quality

- State: ENTRY_READY
- Structure: Price holds above its long-term trend inside the readiness band with non-negative momentum — a healthy structure that is not overextended.
- Score: 0.87
- Confidence: 1.0
- Market as-of: 2026-10-12

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.128768; threshold=>=1.00 healthy; <0.95 damaged)
- `price_near_sma50_ready_band` — Price near SMA50: Price is in the pre-registered SMA50 readiness band. (polarity=positive; metric=price_to_sma50; value=1.040698; threshold=0.98–1.08)
- `return_20d_ready_band` — 20d return in readiness band: Recent momentum is positive/controlled rather than chased. (polarity=positive; metric=return_20d; value=0.012991; threshold=-3% to +12%)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.075774; threshold=>=0%)
- `relative_strength_60d_qqq_ready` — 60d relative strength acceptable: The stock is keeping pace with QQQ over 60 trading days. (polarity=positive; metric=relative_strength_60d_qqq; value=0.002871; threshold=>=-3%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

## Counter-Evidence

- `accrual_ratio_weak` — Accrual quality weak: Accrual quality is a material counter-signal for Company Quality. (polarity=negative; metric=accrual_ratio; value=-0.656272; threshold=|accrual|<=0.10 supportive; >0.35 weak)

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
- cik: 0000821189
- code_sha: 220a4716c411bd7e9e80f9f7f89502f6ab1ff0ac
- config_fingerprint: e778b6553cf52859581a8bfa5101af564a8be83fda011aace9b5639b8162a50e
- entry_policy_version: entry_quality_v1_2026-10-10
- filing_entity_name: EOG RESOURCES INC
- fundamental_companyfacts_raw_sha256: 151c695b202ed21c1efc1899573ff0a2a428dbdc09387f4e11ddda07aefbf719
- fundamental_companyfacts_sha256: 151c695b202ed21c1efc1899573ff0a2a428dbdc09387f4e11ddda07aefbf719
- fundamental_currency_supported: True
- fundamental_edgartools_fallback_fact_count: 0
- fundamental_edgartools_fallback_status: not_needed
- fundamental_edgartools_fallback_used: False
- fundamental_effective_sha256: 9ca635aea65327a2263ce17082805f4b3bca2c792db02bc2c27cd5923b5b2d09
- fundamental_facts_cover_latest_periodic: True
- fundamental_latest_periodic_accession: 0000821189-26-000149
- fundamental_latest_periodic_filing_date: 2026-08-04
- fundamental_latest_periodic_form: 10-Q
- fundamental_operating_entity_detail: ticker_listed_with_core_facts
- fundamental_operating_entity_verified: True
- fundamental_reporting_currency: USD
- fundamental_source: companyfacts
- fundamental_submissions_sha256: cf447113861736330f8c10b5ee024991da7168407159b588030e88c126b2451f
- identity_scoring_sha: e6b561d74139fcba8f5cef4f55da707c4f3ab0ed59c8471f3ed6bf9e22c9090d
- quality_policy_version: company_quality_v1_2026-10-10
- scan_config_path: outputs/config.mvp_beta.json
- strategy_style: risk_off
- watchlist_csv_path: data/ai_watchlist.csv
- watchlist_etf_count: 0
