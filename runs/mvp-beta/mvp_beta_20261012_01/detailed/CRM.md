# Detailed Report — CRM — Salesforce, Inc.

## CRM — Salesforce, Inc.

- Decision date: 2026-10-12
- Company Quality: A
- Entry Quality: WATCH_BREAKOUT
- Action State: WATCH_BREAKOUT
- Priority: 10
- Fundamental data as-of: 2026-08-27
- Market data as-of: 2026-10-12
- Review trigger: Re-review when market structure confirms ENTRY_READY or deteriorates into TREND_DAMAGED.
- Previous action: n/a
- State change reason: New prospective decision snapshot.

## Company Quality

- Grade: A
- Score: 0.846667
- Confidence: 1.0
- Data as-of: 2026-08-27

### Component Scores

- balance_sheet: 0.65
- dilution: 1.0
- growth_stability: 0.933333
- operating_red_flags: 1.0
- profitability_cash: 0.8
- valuation_context: 0.9

### Positives

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.236287; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=15154000000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=1.517049; threshold=>=0.8 supportive; <0.5 weak)
- `revenue_yoy_strong` — Revenue growth supportive: Revenue growth supports the quality assessment. (polarity=positive; metric=revenue_yoy; value=0.112298; threshold=>=8% supportive; <-10% weak)
- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=0.47572; threshold=>=15% strong; <-10% weak)
- `operating_cash_flow_yoy_strong` — Operating cash-flow growth supportive: Operating cash-flow growth supports the quality assessment. (polarity=positive; metric=operating_cash_flow_yoy; value=0.195991; threshold=>=15% strong; <-10% weak)
- `interest_coverage_strong` — Interest coverage supportive: Interest coverage supports the quality assessment. (polarity=positive; metric=interest_coverage; value=61.396104; threshold=>=4 supportive; <1 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.135504; threshold=<=3% supportive; >12% weak)
- `fcf_yield_strong` — FCF yield supportive: FCF yield supports the quality assessment. (polarity=positive; metric=fcf_yield; value=0.078798; threshold=>=2% supportive; <-2% weak)
- `ps_hist_percentile_strong` — Historical P/S percentile supportive: Historical P/S percentile supports the quality assessment. (polarity=positive; metric=ps_hist_percentile; value=0.5; threshold=<=60% supportive; >80% expensive)
- `pe_hist_percentile_strong` — Historical P/E percentile supportive: Historical P/E percentile supports the quality assessment. (polarity=positive; metric=pe_hist_percentile; value=0.25; threshold=<=60% supportive; >80% expensive)
- `receivables_growth_gap_strong` — Receivables growth gap supportive: Receivables growth gap supports the quality assessment. (polarity=positive; metric=receivables_growth_gap; value=0.01708; threshold=<=5pp supportive; >25pp weak)
- `inventory_growth_gap_strong` — Inventory growth gap supportive: Inventory growth gap supports the quality assessment. (polarity=positive; metric=inventory_growth_gap; value=0.0; threshold=<=10pp supportive; >30pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=46; threshold=<=400)

## Quality Applicability

- Company Quality v1 is one common financial-quality core. Specialist accounting semantics (banks, brokers, insurers, REITs, foreign or unsupported reporting models) are pending independent review; until then, cross-model comparability is UNVERIFIED for every decision, and this grade must not be read as sector-relative quality.
- Applicability for THIS decision: not disproven, but still unverified across business models — compare with caution.

## Entry Quality

- State: WATCH_BREAKOUT
- Structure: A mixed remainder, not a single chart story: not damaged and not overextended, but missing at least one readiness condition — read the unmet conditions below instead of assuming a basing pattern.
- Score: 0.9
- Confidence: 1.0
- Market as-of: 2026-10-12

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.170932; threshold=>=1.00 healthy; <0.95 damaged)
- `price_near_sma50_ready_band` — Price near SMA50: Price is in the pre-registered SMA50 readiness band. (polarity=positive; metric=price_to_sma50; value=1.033785; threshold=0.98–1.08)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.36796; threshold=>=0%)
- `relative_strength_60d_qqq_ready` — 60d relative strength acceptable: The stock is keeping pace with QQQ over 60 trading days. (polarity=positive; metric=relative_strength_60d_qqq; value=0.295057; threshold=>=-3%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

## Counter-Evidence

- `accrual_ratio_weak` — Accrual quality weak: Accrual quality is a material counter-signal for Company Quality. (polarity=negative; metric=accrual_ratio; value=-0.243083; threshold=|accrual|<=0.10 supportive; >0.35 weak)

## Missing Evidence

- none

## Next Review Conditions

- Trigger: Re-review when market structure confirms ENTRY_READY or deteriorates into TREND_DAMAGED.
- Structure: Watch for confirmation into ENTRY_READY or deterioration into TREND_DAMAGED.

## Decision History

- Previous action: n/a
- State change: New prospective decision snapshot.

## Evidence & Provenance

- Schema version: 1
- Generated at UTC: 2026-10-13T09:32:59.988550+00:00
- Source lists: n/a
- cik: 0001108524
- code_sha: 220a4716c411bd7e9e80f9f7f89502f6ab1ff0ac
- config_fingerprint: e778b6553cf52859581a8bfa5101af564a8be83fda011aace9b5639b8162a50e
- entry_policy_version: entry_quality_v1_2026-10-10
- filing_entity_name: Salesforce, Inc.
- fundamental_companyfacts_raw_sha256: c095055e906b649cdd3095bccf1cd652d19df2b633002d758e65c303aaf0f4ad
- fundamental_companyfacts_sha256: c095055e906b649cdd3095bccf1cd652d19df2b633002d758e65c303aaf0f4ad
- fundamental_currency_supported: True
- fundamental_edgartools_fallback_fact_count: 0
- fundamental_edgartools_fallback_status: not_needed
- fundamental_edgartools_fallback_used: False
- fundamental_effective_sha256: 33d0a0d7e8f992ca84bf4c7c7571c1a8bc744fb0bc308f8dc519dfd74f4acdb2
- fundamental_facts_cover_latest_periodic: True
- fundamental_latest_periodic_accession: 0001108524-26-000190
- fundamental_latest_periodic_filing_date: 2026-08-27
- fundamental_latest_periodic_form: 10-Q
- fundamental_operating_entity_detail: ticker_listed_with_core_facts
- fundamental_operating_entity_verified: True
- fundamental_reporting_currency: USD
- fundamental_source: companyfacts
- fundamental_submissions_sha256: b0d4e34b5ad3f6b59e756b449b60627729b44eb6d748eb511dc5ebaac1b3aa1f
- identity_scoring_sha: 05dd51cc5bf519c1ea968c1c7ecf80e87839ca32e3632915f70e5945ecdaadc3
- quality_policy_version: company_quality_v1_2026-10-10
- scan_config_path: outputs/config.mvp_beta.json
- strategy_style: risk_off
- watchlist_csv_path: data/ai_watchlist.csv
- watchlist_etf_count: 0
