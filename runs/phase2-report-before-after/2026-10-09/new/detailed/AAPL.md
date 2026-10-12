# Detailed Report — AAPL — Apple Inc.

## AAPL — Apple Inc.

- Decision date: 2026-10-09
- Company Quality: B
- Entry Quality: WATCH_BREAKOUT
- Action State: HOLD_MONITOR
- Priority: 27
- Fundamental data as-of: 2026-07-31
- Market data as-of: 2026-10-09
- Review trigger: Re-review on a Quality or Entry state change; prioritize only if Quality A reaches ENTRY_READY.
- Previous action: HOLD_MONITOR
- State change reason: Entry Quality ENTRY_READY→WATCH_BREAKOUT.

## Company Quality

- Grade: B
- Score: 0.800833
- Confidence: 1.0
- Data as-of: 2026-07-31

### Component Scores

- balance_sheet: 0.85
- dilution: 1.0
- growth_stability: 0.933333
- operating_red_flags: 0.5
- profitability_cash: 0.875
- valuation_context: 0.316667

### Positives

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.276186; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=136683000000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=1.138013; threshold=>=0.8 supportive; <0.5 weak)
- `revenue_yoy_strong` — Revenue growth supportive: Revenue growth supports the quality assessment. (polarity=positive; metric=revenue_yoy; value=0.142424; threshold=>=8% supportive; <-10% weak)
- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=0.29865; threshold=>=15% strong; <-10% weak)
- `operating_cash_flow_yoy_strong` — Operating cash-flow growth supportive: Operating cash-flow growth supports the quality assessment. (polarity=positive; metric=operating_cash_flow_yoy; value=0.351485; threshold=>=15% strong; <-10% weak)
- `net_debt_to_ebitda_strong` — Net debt / EBITDA supportive: Net debt / EBITDA supports the quality assessment. (polarity=positive; metric=net_debt_to_ebitda; value=0.189308; threshold=<=1.5 supportive; >4 weak)
- `interest_coverage_strong` — Interest coverage supportive: Interest coverage supports the quality assessment. (polarity=positive; metric=interest_coverage; value=39.374269; threshold=>=4 supportive; <1 weak)
- `current_ratio_strong` — Current ratio supportive: Current ratio supports the quality assessment. (polarity=positive; metric=current_ratio; value=1.003295; threshold=>=1 supportive; <0.75 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.016591; threshold=<=3% supportive; >12% weak)
- `fcf_yield_strong` — FCF yield supportive: FCF yield supports the quality assessment. (polarity=positive; metric=fcf_yield; value=0.027835; threshold=>=2% supportive; <-2% weak)
- `receivables_growth_gap_strong` — Receivables growth gap supportive: Receivables growth gap supports the quality assessment. (polarity=positive; metric=receivables_growth_gap; value=-0.00304; threshold=<=5pp supportive; >25pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=70; threshold=<=400)

## Quality Applicability

- Company Quality v1 is one common financial-quality core. Specialist accounting semantics (banks, brokers, insurers, REITs, foreign or unsupported reporting models) are pending independent review; until then, cross-model comparability is UNVERIFIED for every decision, and this grade must not be read as sector-relative quality.
- Applicability for THIS decision: not disproven, but still unverified across business models — compare with caution.

## Entry Quality

- State: WATCH_BREAKOUT
- Structure: Price is basing around trend without confirmation — neither damaged nor ready; it needs a structural trigger before entry.
- Score: 0.8
- Confidence: 1.0
- Market as-of: 2026-10-09

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.157372; threshold=>=1.00 healthy; <0.95 damaged)
- `price_near_sma50_ready_band` — Price near SMA50: Price is in the pre-registered SMA50 readiness band. (polarity=positive; metric=price_to_sma50; value=1.043649; threshold=0.98–1.08)
- `return_20d_ready_band` — 20d return in readiness band: Recent momentum is positive/controlled rather than chased. (polarity=positive; metric=return_20d; value=0.012717; threshold=-3% to +12%)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.009723; threshold=>=0%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

## Counter-Evidence

- `ps_hist_percentile_weak` — Historical P/S percentile weak: Historical P/S percentile is a material counter-signal for Company Quality. (polarity=negative; metric=ps_hist_percentile; value=1.0; threshold=<=60% supportive; >80% expensive)
- `pe_hist_percentile_weak` — Historical P/E percentile weak: Historical P/E percentile is a material counter-signal for Company Quality. (polarity=negative; metric=pe_hist_percentile; value=1.0; threshold=<=60% supportive; >80% expensive)
- `inventory_growth_gap_weak` — Inventory growth gap weak: Inventory growth gap is a material counter-signal for Company Quality. (polarity=negative; metric=inventory_growth_gap; value=0.729644; threshold=<=10pp supportive; >30pp weak)

## Missing Evidence

- none

## Next Review Conditions

- Trigger: Re-review on a Quality or Entry state change; prioritize only if Quality A reaches ENTRY_READY.
- Structure: Watch for confirmation into ENTRY_READY or deterioration into TREND_DAMAGED.

## Decision History

- Previous action: HOLD_MONITOR
- State change: Entry Quality ENTRY_READY→WATCH_BREAKOUT.

## Evidence & Provenance

- Schema version: 1
- Generated at UTC: 2026-10-12T02:22:26.219967+00:00
- Source lists: n/a
- code_sha: 6711919c8ea91dbe27345829c957cd72611533e0
- cohort: generalized_v0_62frozen
- entry_policy_version: entry_quality_v1_2026-10-10
- membership_asof: 2026-10-11 (NOT PIT for these dates)
- mode: retrospective_posthoc_cohort
- quality_policy_version: company_quality_v1_2026-10-10
- watchlist_bucket: posthoc:us_core
- watchlist_etf_count: 1
- watchlist_etfs: -
