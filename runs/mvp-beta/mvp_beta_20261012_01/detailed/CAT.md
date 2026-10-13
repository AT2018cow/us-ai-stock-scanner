# Detailed Report — CAT — CATERPILLAR INC

## CAT — CATERPILLAR INC

- Decision date: 2026-10-12
- Company Quality: A
- Entry Quality: WATCH_BREAKOUT
- Action State: WATCH_BREAKOUT
- Priority: 12
- Fundamental data as-of: 2026-08-05
- Market data as-of: 2026-10-12
- Review trigger: Re-review when market structure confirms ENTRY_READY or deteriorates into TREND_DAMAGED.
- Previous action: n/a
- State change reason: New prospective decision snapshot.

## Company Quality

- Grade: A
- Score: 0.815
- Confidence: 0.933333
- Data as-of: 2026-08-05

### Component Scores

- balance_sheet: 0.775
- dilution: 1.0
- growth_stability: 1.0
- operating_red_flags: 0.65
- profitability_cash: 0.95
- valuation_context: 0.616667

### Positives

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.153086; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=10698000000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=1.186101; threshold=>=0.8 supportive; <0.5 weak)
- `accrual_ratio_strong` — Accrual quality supportive: Accrual quality supports the quality assessment. (polarity=positive; metric=accrual_ratio; value=-0.0391; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `revenue_yoy_strong` — Revenue growth supportive: Revenue growth supports the quality assessment. (polarity=positive; metric=revenue_yoy; value=0.183563; threshold=>=8% supportive; <-10% weak)
- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=0.187461; threshold=>=15% strong; <-10% weak)
- `operating_cash_flow_yoy_strong` — Operating cash-flow growth supportive: Operating cash-flow growth supports the quality assessment. (polarity=positive; metric=operating_cash_flow_yoy; value=0.193089; threshold=>=15% strong; <-10% weak)
- `net_debt_to_ebitda_strong` — Net debt / EBITDA supportive: Net debt / EBITDA supports the quality assessment. (polarity=positive; metric=net_debt_to_ebitda; value=1.492408; threshold=<=1.5 supportive; >4 weak)
- `current_ratio_strong` — Current ratio supportive: Current ratio supports the quality assessment. (polarity=positive; metric=current_ratio; value=1.368434; threshold=>=1 supportive; <0.75 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.018837; threshold=<=3% supportive; >12% weak)
- `fcf_yield_strong` — FCF yield supportive: FCF yield supports the quality assessment. (polarity=positive; metric=fcf_yield; value=0.029109; threshold=>=2% supportive; <-2% weak)
- `pe_hist_percentile_strong` — Historical P/E percentile supportive: Historical P/E percentile supports the quality assessment. (polarity=positive; metric=pe_hist_percentile; value=0.5; threshold=<=60% supportive; >80% expensive)
- `inventory_growth_gap_strong` — Inventory growth gap supportive: Inventory growth gap supports the quality assessment. (polarity=positive; metric=inventory_growth_gap; value=-0.074287; threshold=<=10pp supportive; >30pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=68; threshold=<=400)

## Quality Applicability

- Company Quality v1 is one common financial-quality core. Specialist accounting semantics (banks, brokers, insurers, REITs, foreign or unsupported reporting models) are pending independent review; until then, cross-model comparability is UNVERIFIED for every decision, and this grade must not be read as sector-relative quality.
- Applicability for THIS decision: not disproven, but still unverified across business models — compare with caution.

## Entry Quality

- State: WATCH_BREAKOUT
- Structure: A mixed remainder, not a single chart story: not damaged and not overextended, but missing at least one readiness condition — read the unmet conditions below instead of assuming a basing pattern.
- Score: 0.504167
- Confidence: 1.0
- Market as-of: 2026-10-12

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `return_20d_ready_band` — 20d return in readiness band: Recent momentum is positive/controlled rather than chased. (polarity=positive; metric=return_20d; value=0.020577; threshold=-3% to +12%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

## Counter-Evidence

- `return_60d_weak` — 60d trend weak: Medium-term momentum is weak. (polarity=negative; metric=return_60d; value=-0.091786; threshold=>-8% preferred)
- `relative_strength_60d_qqq_weak` — 60d relative strength weak: The stock is materially lagging QQQ. (polarity=negative; metric=relative_strength_60d_qqq; value=-0.164689; threshold=>-10% preferred)

## Missing Evidence

- `interest_coverage_missing` — Interest coverage missing: Interest coverage is unavailable, so it cannot support Company Quality. (polarity=missing; metric=interest_coverage; threshold=>=4 supportive; <1 weak)

## Next Review Conditions

- Trigger: Re-review when market structure confirms ENTRY_READY or deteriorates into TREND_DAMAGED.
- Supplement: Interest coverage missing (interest_coverage_missing).
- Structure: Watch for confirmation into ENTRY_READY or deterioration into TREND_DAMAGED.

## Decision History

- Previous action: n/a
- State change: New prospective decision snapshot.

## Evidence & Provenance

- Schema version: 1
- Generated at UTC: 2026-10-13T09:32:59.988550+00:00
- Source lists: n/a
- cik: 0000018230
- code_sha: 220a4716c411bd7e9e80f9f7f89502f6ab1ff0ac
- config_fingerprint: e778b6553cf52859581a8bfa5101af564a8be83fda011aace9b5639b8162a50e
- entry_policy_version: entry_quality_v1_2026-10-10
- filing_entity_name: CATERPILLAR INC
- fundamental_companyfacts_raw_sha256: ff12ca34c0b88d51c13e2ecce17403ffb2d716d03287311f483936f3ed5425cf
- fundamental_companyfacts_sha256: ff12ca34c0b88d51c13e2ecce17403ffb2d716d03287311f483936f3ed5425cf
- fundamental_currency_supported: True
- fundamental_edgartools_fallback_fact_count: 0
- fundamental_edgartools_fallback_status: not_needed
- fundamental_edgartools_fallback_used: False
- fundamental_effective_sha256: efd79495a62c613eecc6a6142013f68f86c071ced146b1727cb1a9cb8b845dd2
- fundamental_facts_cover_latest_periodic: True
- fundamental_latest_periodic_accession: 0000018230-26-000046
- fundamental_latest_periodic_filing_date: 2026-08-05
- fundamental_latest_periodic_form: 10-Q
- fundamental_operating_entity_detail: ticker_listed_with_core_facts
- fundamental_operating_entity_verified: True
- fundamental_reporting_currency: USD
- fundamental_source: companyfacts
- fundamental_submissions_sha256: 1b4929dd69bd2c2143e7f255712ed58f0fca243c99324460c38ca4ac10b979ba
- identity_scoring_sha: 70cfbb11842b1ce5c51cddfb8cc89d5ec924fa03a9677a16aa278175b8f22814
- quality_policy_version: company_quality_v1_2026-10-10
- scan_config_path: outputs/config.mvp_beta.json
- strategy_style: risk_off
- watchlist_csv_path: data/ai_watchlist.csv
- watchlist_etf_count: 0
