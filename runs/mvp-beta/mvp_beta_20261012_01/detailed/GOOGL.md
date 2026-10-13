# Detailed Report — GOOGL — Alphabet Inc.

## GOOGL — Alphabet Inc.

- Decision date: 2026-10-12
- Company Quality: A
- Entry Quality: WATCH_BREAKOUT
- Action State: WATCH_BREAKOUT
- Priority: 15
- Fundamental data as-of: 2026-07-23
- Market data as-of: 2026-10-12
- Review trigger: Re-review when market structure confirms ENTRY_READY or deteriorates into TREND_DAMAGED.
- Previous action: n/a
- State change reason: New prospective decision snapshot.

## Company Quality

- Grade: A
- Score: 0.785
- Confidence: 0.95
- Data as-of: 2026-07-23

### Component Scores

- balance_sheet: 0.933333
- dilution: 0.8
- growth_stability: 1.0
- operating_red_flags: 0.6
- profitability_cash: 0.75
- valuation_context: 0.633333

### Positives

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.55653; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=53273000000.0; threshold=>0 supportive; <0 weak)
- `revenue_yoy_strong` — Revenue growth supportive: Revenue growth supports the quality assessment. (polarity=positive; metric=revenue_yoy; value=0.200504; threshold=>=8% supportive; <-10% weak)
- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=1.147024; threshold=>=15% strong; <-10% weak)
- `operating_cash_flow_yoy_strong` — Operating cash-flow growth supportive: Operating cash-flow growth supports the quality assessment. (polarity=positive; metric=operating_cash_flow_yoy; value=0.38866; threshold=>=15% strong; <-10% weak)
- `net_debt_to_ebitda_strong` — Net debt / EBITDA supportive: Net debt / EBITDA supports the quality assessment. (polarity=positive; metric=net_debt_to_ebitda; value=0.246513; threshold=<=1.5 supportive; >4 weak)
- `interest_coverage_strong` — Interest coverage supportive: Interest coverage supports the quality assessment. (polarity=positive; metric=interest_coverage; value=470.686335; threshold=>=4 supportive; <1 weak)
- `current_ratio_strong` — Current ratio supportive: Current ratio supports the quality assessment. (polarity=positive; metric=current_ratio; value=2.723981; threshold=>=1 supportive; <0.75 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=0.006336; threshold=<=3% supportive; >12% weak)
- `pe_hist_percentile_strong` — Historical P/E percentile supportive: Historical P/E percentile supports the quality assessment. (polarity=positive; metric=pe_hist_percentile; value=0.0; threshold=<=60% supportive; >80% expensive)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=81; threshold=<=400)

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
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.036917; threshold=>=1.00 healthy; <0.95 damaged)
- `price_near_sma50_ready_band` — Price near SMA50: Price is in the pre-registered SMA50 readiness band. (polarity=positive; metric=price_to_sma50; value=1.019049; threshold=0.98–1.08)
- `return_20d_ready_band` — 20d return in readiness band: Recent momentum is positive/controlled rather than chased. (polarity=positive; metric=return_20d; value=0.009515; threshold=-3% to +12%)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.017317; threshold=>=0%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

## Counter-Evidence

- none

## Missing Evidence

- `inventory_growth_gap_missing` — Inventory growth gap missing: Inventory growth gap is unavailable, so it cannot support Company Quality. (polarity=missing; metric=inventory_growth_gap; threshold=<=10pp supportive; >30pp weak)

## Next Review Conditions

- Trigger: Re-review when market structure confirms ENTRY_READY or deteriorates into TREND_DAMAGED.
- Supplement: Inventory growth gap missing (inventory_growth_gap_missing).
- Structure: Watch for confirmation into ENTRY_READY or deterioration into TREND_DAMAGED.

## Decision History

- Previous action: n/a
- State change: New prospective decision snapshot.

## Evidence & Provenance

- Schema version: 1
- Generated at UTC: 2026-10-13T09:32:59.988550+00:00
- Source lists: n/a
- cik: 0001652044
- code_sha: 220a4716c411bd7e9e80f9f7f89502f6ab1ff0ac
- config_fingerprint: e778b6553cf52859581a8bfa5101af564a8be83fda011aace9b5639b8162a50e
- entry_policy_version: entry_quality_v1_2026-10-10
- filing_entity_name: Alphabet Inc.
- fundamental_companyfacts_raw_sha256: 67e9eb51a09725a55b786cc0a569efcfb9906ad170e445e4775bc2126e22ae7d
- fundamental_companyfacts_sha256: 67e9eb51a09725a55b786cc0a569efcfb9906ad170e445e4775bc2126e22ae7d
- fundamental_currency_supported: True
- fundamental_edgartools_fallback_fact_count: 0
- fundamental_edgartools_fallback_status: not_needed
- fundamental_edgartools_fallback_used: False
- fundamental_effective_sha256: 3cd6585502f1a1b3b4875a832d9ef261278c1c58d606d5f027ea7a94553ea6fb
- fundamental_facts_cover_latest_periodic: True
- fundamental_latest_periodic_accession: 0001652044-26-000071
- fundamental_latest_periodic_filing_date: 2026-07-23
- fundamental_latest_periodic_form: 10-Q
- fundamental_operating_entity_detail: ticker_listed_with_core_facts
- fundamental_operating_entity_verified: True
- fundamental_reporting_currency: USD
- fundamental_source: companyfacts
- fundamental_submissions_sha256: 5e01d433873a51f4aae07737595e1a52f20afc17d8bc7b08e5dba07593e1fc8f
- identity_scoring_sha: 4f041716b4ccd10ba37ea6039251e55828469b2240c5c2318375b7186148352f
- quality_policy_version: company_quality_v1_2026-10-10
- scan_config_path: outputs/config.mvp_beta.json
- strategy_style: risk_off
- watchlist_csv_path: data/ai_watchlist.csv
- watchlist_etf_count: 0
