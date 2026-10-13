# Detailed Report — PG — PROCTER & GAMBLE Co

## PG — PROCTER & GAMBLE Co

- Decision date: 2026-10-12
- Company Quality: A
- Entry Quality: WATCH_BREAKOUT
- Action State: WATCH_BREAKOUT
- Priority: 14
- Fundamental data as-of: 2026-08-04
- Market data as-of: 2026-10-12
- Review trigger: Re-review when market structure confirms ENTRY_READY or deteriorates into TREND_DAMAGED.
- Previous action: n/a
- State change reason: New prospective decision snapshot.

## Company Quality

- Grade: A
- Score: 0.789167
- Confidence: 1.0
- Data as-of: 2026-08-04

### Component Scores

- balance_sheet: 0.633333
- dilution: 1.0
- growth_stability: 0.716667
- operating_red_flags: 1.0
- profitability_cash: 0.825
- valuation_context: 0.716667

### Positives

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.276255; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=15147000000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=0.813376; threshold=>=0.8 supportive; <0.5 weak)
- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=0.407011; threshold=>=15% strong; <-10% weak)
- `net_debt_to_ebitda_strong` — Net debt / EBITDA supportive: Net debt / EBITDA supports the quality assessment. (polarity=positive; metric=net_debt_to_ebitda; value=0.782915; threshold=<=1.5 supportive; >4 weak)
- `interest_coverage_strong` — Interest coverage supportive: Interest coverage supports the quality assessment. (polarity=positive; metric=interest_coverage; value=29.328753; threshold=>=4 supportive; <1 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.007658; threshold=<=3% supportive; >12% weak)
- `fcf_yield_strong` — FCF yield supportive: FCF yield supports the quality assessment. (polarity=positive; metric=fcf_yield; value=0.04253; threshold=>=2% supportive; <-2% weak)
- `pe_hist_percentile_strong` — Historical P/E percentile supportive: Historical P/E percentile supports the quality assessment. (polarity=positive; metric=pe_hist_percentile; value=0.0; threshold=<=60% supportive; >80% expensive)
- `receivables_growth_gap_strong` — Receivables growth gap supportive: Receivables growth gap supports the quality assessment. (polarity=positive; metric=receivables_growth_gap; value=-0.053461; threshold=<=5pp supportive; >25pp weak)
- `inventory_growth_gap_strong` — Inventory growth gap supportive: Inventory growth gap supports the quality assessment. (polarity=positive; metric=inventory_growth_gap; value=0.049372; threshold=<=10pp supportive; >30pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=69; threshold=<=400)

## Quality Applicability

- Company Quality v1 is one common financial-quality core. Specialist accounting semantics (banks, brokers, insurers, REITs, foreign or unsupported reporting models) are pending independent review; until then, cross-model comparability is UNVERIFIED for every decision, and this grade must not be read as sector-relative quality.
- Applicability for THIS decision: not disproven, but still unverified across business models — compare with caution.

## Entry Quality

- State: WATCH_BREAKOUT
- Structure: A mixed remainder, not a single chart story: not damaged and not overextended, but missing at least one readiness condition — read the unmet conditions below instead of assuming a basing pattern.
- Score: 0.843333
- Confidence: 1.0
- Market as-of: 2026-10-12

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.0368; threshold=>=1.00 healthy; <0.95 damaged)
- `price_near_sma50_ready_band` — Price near SMA50: Price is in the pre-registered SMA50 readiness band. (polarity=positive; metric=price_to_sma50; value=1.048836; threshold=0.98–1.08)
- `return_20d_ready_band` — 20d return in readiness band: Recent momentum is positive/controlled rather than chased. (polarity=positive; metric=return_20d; value=0.048375; threshold=-3% to +12%)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.021603; threshold=>=0%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

## Counter-Evidence

- `current_ratio_weak` — Current ratio weak: Current ratio is a material counter-signal for Company Quality. (polarity=negative; metric=current_ratio; value=0.677314; threshold=>=1 supportive; <0.75 weak)

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
- cik: 0000080424
- code_sha: 220a4716c411bd7e9e80f9f7f89502f6ab1ff0ac
- config_fingerprint: e778b6553cf52859581a8bfa5101af564a8be83fda011aace9b5639b8162a50e
- entry_policy_version: entry_quality_v1_2026-10-10
- filing_entity_name: PROCTER & GAMBLE Co
- fundamental_companyfacts_raw_sha256: f50b37c78d4e995661144538f74688127f9c055e36fd75b65de00e37e84ce678
- fundamental_companyfacts_sha256: f50b37c78d4e995661144538f74688127f9c055e36fd75b65de00e37e84ce678
- fundamental_currency_supported: True
- fundamental_edgartools_fallback_fact_count: 0
- fundamental_edgartools_fallback_status: not_needed
- fundamental_edgartools_fallback_used: False
- fundamental_effective_sha256: a9909d0356a010c92b222e12eb44c7e0a34244832db1bd870012196ae204d4dc
- fundamental_facts_cover_latest_periodic: True
- fundamental_latest_periodic_accession: 0000080424-26-000103
- fundamental_latest_periodic_filing_date: 2026-08-04
- fundamental_latest_periodic_form: 10-K
- fundamental_operating_entity_detail: ticker_listed_with_core_facts
- fundamental_operating_entity_verified: True
- fundamental_reporting_currency: USD
- fundamental_source: companyfacts
- fundamental_submissions_sha256: 8b530f7a43ffa65bdb7fa04dc2f6d08021dea7196b63aaf7f5acca6d111333ef
- identity_scoring_sha: e3d3042a0c8c53021ef85aef277713825df89c3ab6f500009dfe724e1fe78701
- quality_policy_version: company_quality_v1_2026-10-10
- scan_config_path: outputs/config.mvp_beta.json
- strategy_style: risk_off
- watchlist_csv_path: data/ai_watchlist.csv
- watchlist_etf_count: 0
