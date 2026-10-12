# Detailed Report — XOM — ExxonMobil Holdings Corp

## XOM — ExxonMobil Holdings Corp

- Decision date: 2026-10-09
- Company Quality: UNRATED
- Entry Quality: ENTRY_READY
- Action State: AVOID
- Priority: 62
- Fundamental data as-of: 2026-08-03
- Market data as-of: 2026-10-09
- Review trigger: Re-review after stale/missing evidence clears or Quality/Entry materially improves.
- Previous action: AVOID
- State change reason: n/a

## Attention — read before acting

- Filing-entity identity UNVERIFIED: the ticker->CIK binding does not verifiably represent the operating issuer. Do not treat this grade as a reliable company judgement.
- Company Quality UNRATED: no reliable company judgement exists; see Missing Evidence for what to supplement.

## Company Quality

- Grade: UNRATED
- Score: 0.15
- Confidence: 0.166667
- Data as-of: 2026-08-03

### Component Scores

- balance_sheet: 0.75
- dilution: 1.0
- growth_stability: n/a
- operating_red_flags: n/a
- profitability_cash: n/a
- valuation_context: n/a

### Positives

- `current_ratio_strong` — Current ratio supportive: Current ratio supports the quality assessment. (polarity=positive; metric=current_ratio; value=1.134673; threshold=>=1 supportive; <0.75 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.035442; threshold=<=3% supportive; >12% weak)

## Quality Applicability

- Company Quality v1 is one common financial-quality core. Specialist accounting semantics (banks, brokers, insurers, REITs, foreign or unsupported reporting models) are pending independent review; until then, cross-model comparability is UNVERIFIED for every decision, and this grade must not be read as sector-relative quality.
- Applicability for THIS decision: UNVERIFIED — do not compare this grade across business models or against sector peers.

## Entry Quality

- State: ENTRY_READY
- Structure: Price holds above its long-term trend inside the readiness band with non-negative momentum — a healthy structure that is not overextended.
- Score: 1.0
- Confidence: 1.0
- Market as-of: 2026-10-09

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.124312; threshold=>=1.00 healthy; <0.95 damaged)
- `price_near_sma50_ready_band` — Price near SMA50: Price is in the pre-registered SMA50 readiness band. (polarity=positive; metric=price_to_sma50; value=1.046061; threshold=0.98–1.08)
- `return_20d_ready_band` — 20d return in readiness band: Recent momentum is positive/controlled rather than chased. (polarity=positive; metric=return_20d; value=0.018255; threshold=-3% to +12%)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.158034; threshold=>=0%)
- `relative_strength_60d_qqq_ready` — 60d relative strength acceptable: The stock is keeping pace with QQQ over 60 trading days. (polarity=positive; metric=relative_strength_60d_qqq; value=0.093821; threshold=>=-3%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

## Counter-Evidence

- none

## Missing Evidence

- `net_margin_missing` — Net margin missing: Net margin is unavailable, so it cannot support Company Quality. (polarity=missing; metric=net_margin; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_missing` — Free cash flow missing: Free cash flow is unavailable, so it cannot support Company Quality. (polarity=missing; metric=free_cash_flow; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_missing` — Operating cash-flow conversion missing: Operating cash-flow conversion is unavailable, so it cannot support Company Quality. (polarity=missing; metric=ocf_to_net_income; threshold=>=0.8 supportive; <0.5 weak)
- `accrual_ratio_missing` — Accrual quality missing: Accrual quality is unavailable, so it cannot support Company Quality. (polarity=missing; metric=accrual_ratio; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `revenue_yoy_missing` — Revenue growth missing: Revenue growth is unavailable, so it cannot support Company Quality. (polarity=missing; metric=revenue_yoy; threshold=>=8% supportive; <-10% weak)
- `net_income_yoy_missing` — Earnings growth missing: Earnings growth is unavailable, so it cannot support Company Quality. (polarity=missing; metric=net_income_yoy; threshold=>=15% strong; <-10% weak)
- `operating_cash_flow_yoy_missing` — Operating cash-flow growth missing: Operating cash-flow growth is unavailable, so it cannot support Company Quality. (polarity=missing; metric=operating_cash_flow_yoy; threshold=>=15% strong; <-10% weak)
- `net_debt_to_ebitda_missing` — Net debt / EBITDA missing: Net debt / EBITDA is unavailable, so it cannot support Company Quality. (polarity=missing; metric=net_debt_to_ebitda; threshold=<=1.5 supportive; >4 weak)
- `interest_coverage_missing` — Interest coverage missing: Interest coverage is unavailable, so it cannot support Company Quality. (polarity=missing; metric=interest_coverage; threshold=>=4 supportive; <1 weak)
- `fcf_yield_missing` — FCF yield missing: FCF yield is unavailable, so it cannot support Company Quality. (polarity=missing; metric=fcf_yield; threshold=>=2% supportive; <-2% weak)
- `ps_hist_percentile_missing` — Historical P/S percentile missing: Historical P/S percentile is unavailable, so it cannot support Company Quality. (polarity=missing; metric=ps_hist_percentile; threshold=<=60% supportive; >80% expensive)
- `pe_hist_percentile_missing` — Historical P/E percentile missing: Historical P/E percentile is unavailable, so it cannot support Company Quality. (polarity=missing; metric=pe_hist_percentile; threshold=<=60% supportive; >80% expensive)
- `receivables_growth_gap_missing` — Receivables growth gap missing: Receivables growth gap is unavailable, so it cannot support Company Quality. (polarity=missing; metric=receivables_growth_gap; threshold=<=5pp supportive; >25pp weak)
- `inventory_growth_gap_missing` — Inventory growth gap missing: Inventory growth gap is unavailable, so it cannot support Company Quality. (polarity=missing; metric=inventory_growth_gap; threshold=<=10pp supportive; >30pp weak)
- `operating_entity_unverified` — Operating filing entity unverified: The ticker->CIK binding does not verifiably represent the operating issuer (ticker absent from the entity filing record, an entity with filings but no revenue, net income or operating-cash-flow facts, or an unchecked binding). No reliable grade can be claimed; verify the filing entity before use. (polarity=missing; metric=fundamental_operating_entity_detail; value=core_facts_absent; threshold=ticker must map to the operating issuer with core facts)

## Next Review Conditions

- Trigger: Re-review after stale/missing evidence clears or Quality/Entry materially improves.
- Supplement: Net margin missing (net_margin_missing).
- Supplement: Free cash flow missing (free_cash_flow_missing).
- Supplement: Operating cash-flow conversion missing (ocf_to_net_income_missing).
- Structure: Watch for loss of the readiness band or momentum breakdown.

## Decision History

- Previous action: AVOID
- State change: n/a

## Evidence & Provenance

- Schema version: 1
- Generated at UTC: 2026-10-12T17:11:58.867338+00:00
- Source lists: n/a
- cik: 0002115436
- code_sha: 1cba0ba06b13a83ce7834c6c9df309c27ff94c14
- cohort: generalized_v0_62frozen
- entry_policy_version: entry_quality_v1_2026-10-10
- filing_entity_name: ExxonMobil Holdings Corp
- membership_asof: 2026-10-11 (NOT PIT for these dates)
- mode: retrospective_posthoc_cohort
- quality_policy_version: company_quality_v1_2026-10-10
- watchlist_bucket: posthoc:manual+us_core
- watchlist_etf_count: 2
- watchlist_etfs: -
