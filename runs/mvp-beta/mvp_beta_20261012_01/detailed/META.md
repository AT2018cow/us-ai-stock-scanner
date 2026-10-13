# Detailed Report — META — Meta Platforms, Inc.

## META — Meta Platforms, Inc.

- Decision date: 2026-10-12
- Company Quality: A
- Entry Quality: WATCH_PULLBACK
- Action State: WATCH_PULLBACK
- Priority: 9
- Fundamental data as-of: 2026-07-30
- Market data as-of: 2026-10-12
- Review trigger: Re-review when price normalizes toward the SMA50 readiness band without long-term trend damage.
- Previous action: n/a
- State change reason: New prospective decision snapshot.

## Company Quality

- Grade: A
- Score: 0.81
- Confidence: 1.0
- Data as-of: 2026-07-30

### Component Scores

- balance_sheet: 0.933333
- dilution: 0.8
- growth_stability: 0.783333
- operating_red_flags: 1.0
- profitability_cash: 0.75
- valuation_context: 0.616667

### Positives

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.298351; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=40976000000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=1.913434; threshold=>=0.8 supportive; <0.5 weak)
- `revenue_yoy_strong` — Revenue growth supportive: Revenue growth supports the quality assessment. (polarity=positive; metric=revenue_yoy; value=0.276519; threshold=>=8% supportive; <-10% weak)
- `operating_cash_flow_yoy_strong` — Operating cash-flow growth supportive: Operating cash-flow growth supports the quality assessment. (polarity=positive; metric=operating_cash_flow_yoy; value=0.273727; threshold=>=15% strong; <-10% weak)
- `net_debt_to_ebitda_strong` — Net debt / EBITDA supportive: Net debt / EBITDA supports the quality assessment. (polarity=positive; metric=net_debt_to_ebitda; value=0.623635; threshold=<=1.5 supportive; >4 weak)
- `interest_coverage_strong` — Interest coverage supportive: Interest coverage supports the quality assessment. (polarity=positive; metric=interest_coverage; value=194.903587; threshold=>=4 supportive; <1 weak)
- `current_ratio_strong` — Current ratio supportive: Current ratio supports the quality assessment. (polarity=positive; metric=current_ratio; value=2.225563; threshold=>=1 supportive; <0.75 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=0.006344; threshold=<=3% supportive; >12% weak)
- `fcf_yield_strong` — FCF yield supportive: FCF yield supports the quality assessment. (polarity=positive; metric=fcf_yield; value=0.021729; threshold=>=2% supportive; <-2% weak)
- `ps_hist_percentile_strong` — Historical P/S percentile supportive: Historical P/S percentile supports the quality assessment. (polarity=positive; metric=ps_hist_percentile; value=0.5; threshold=<=60% supportive; >80% expensive)
- `receivables_growth_gap_strong` — Receivables growth gap supportive: Receivables growth gap supports the quality assessment. (polarity=positive; metric=receivables_growth_gap; value=0.036928; threshold=<=5pp supportive; >25pp weak)
- `inventory_growth_gap_strong` — Inventory growth gap supportive: Inventory growth gap supports the quality assessment. (polarity=positive; metric=inventory_growth_gap; value=0.0; threshold=<=10pp supportive; >30pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=74; threshold=<=400)

## Quality Applicability

- Company Quality v1 is one common financial-quality core. Specialist accounting semantics (banks, brokers, insurers, REITs, foreign or unsupported reporting models) are pending independent review; until then, cross-model comparability is UNVERIFIED for every decision, and this grade must not be read as sector-relative quality.
- Applicability for THIS decision: not disproven, but still unverified across business models — compare with caution.

## Entry Quality

- State: WATCH_PULLBACK
- Structure: Price is extended above trend after a strong run — healthy, but chasing it here means paying up; wait for normalization toward the band.
- Score: 0.883333
- Confidence: 1.0
- Market as-of: 2026-10-12

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.178434; threshold=>=1.00 healthy; <0.95 damaged)
- `return_20d_ready_band` — 20d return in readiness band: Recent momentum is positive/controlled rather than chased. (polarity=positive; metric=return_20d; value=0.116249; threshold=-3% to +12%)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.150132; threshold=>=0%)
- `relative_strength_60d_qqq_ready` — 60d relative strength acceptable: The stock is keeping pace with QQQ over 60 trading days. (polarity=positive; metric=relative_strength_60d_qqq; value=0.077229; threshold=>=-3%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

## Counter-Evidence

- `accrual_ratio_weak` — Accrual quality weak: Accrual quality is a material counter-signal for Company Quality. (polarity=negative; metric=accrual_ratio; value=-0.49574; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `price_extended_above_sma50` — Price extended above SMA50: Price is extended enough to prefer a pullback. (polarity=negative; metric=price_to_sma50; value=1.154772; threshold=<=1.10)

## Missing Evidence

- none

## Next Review Conditions

- Trigger: Re-review when price normalizes toward the SMA50 readiness band without long-term trend damage.
- Structure: Watch for normalization toward the band without trend damage.

## Decision History

- Previous action: n/a
- State change: New prospective decision snapshot.

## Evidence & Provenance

- Schema version: 1
- Generated at UTC: 2026-10-13T09:32:59.988550+00:00
- Source lists: n/a
- cik: 0001326801
- code_sha: 220a4716c411bd7e9e80f9f7f89502f6ab1ff0ac
- config_fingerprint: e778b6553cf52859581a8bfa5101af564a8be83fda011aace9b5639b8162a50e
- entry_policy_version: entry_quality_v1_2026-10-10
- filing_entity_name: Meta Platforms, Inc.
- fundamental_companyfacts_raw_sha256: 0317fc3e86d06ba1660234ad40ec4c1408d9828fd2c4c45e25e2394bfd676699
- fundamental_companyfacts_sha256: 0317fc3e86d06ba1660234ad40ec4c1408d9828fd2c4c45e25e2394bfd676699
- fundamental_currency_supported: True
- fundamental_edgartools_fallback_fact_count: 0
- fundamental_edgartools_fallback_status: not_needed
- fundamental_edgartools_fallback_used: False
- fundamental_effective_sha256: 5136918ebf57509b497b28de4d0a862b02a5f2e08e9c28ed426f121d3c173c57
- fundamental_facts_cover_latest_periodic: True
- fundamental_latest_periodic_accession: 0001628280-26-050705
- fundamental_latest_periodic_filing_date: 2026-07-30
- fundamental_latest_periodic_form: 10-Q
- fundamental_operating_entity_detail: ticker_listed_with_core_facts
- fundamental_operating_entity_verified: True
- fundamental_reporting_currency: USD
- fundamental_source: companyfacts
- fundamental_submissions_sha256: df8b7fc3348c65fcf373ab914ec75e068fe08e00a6281e664183204d283e88d1
- identity_scoring_sha: bd960928676fa1ae2d92acd559ee44766703984256ed5fa67a00ce81530b16c9
- quality_policy_version: company_quality_v1_2026-10-10
- scan_config_path: outputs/config.mvp_beta.json
- strategy_style: risk_off
- watchlist_csv_path: data/ai_watchlist.csv
- watchlist_etf_count: 0
