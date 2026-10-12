# Detailed Report — JPM — JPMORGAN CHASE & CO

## JPM — JPMORGAN CHASE & CO

- Decision date: 2026-10-09
- Company Quality: C
- Entry Quality: WATCH_BREAKOUT
- Action State: AVOID
- Priority: 58
- Fundamental data as-of: 2026-08-06
- Market data as-of: 2026-10-09
- Review trigger: Re-review after stale/missing evidence clears or Quality/Entry materially improves.
- Previous action: AVOID
- State change reason: n/a

## Decision Rationale

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.363569; threshold=>=10% supportive; <0% weak)
- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=0.151737; threshold=>=15% strong; <-10% weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.052002; threshold=<=3% supportive; >12% weak)
- `pe_hist_percentile_strong` — Historical P/E percentile supportive: Historical P/E percentile supports the quality assessment. (polarity=positive; metric=pe_hist_percentile; value=0.0; threshold=<=60% supportive; >80% expensive)
- `ocf_to_net_income_weak` — Operating cash-flow conversion weak: Operating cash-flow conversion is a material counter-signal for Company Quality. (polarity=negative; metric=ocf_to_net_income; value=-2.450311; threshold=>=0.8 supportive; <0.5 weak)
- `price_below_sma50` — Price below SMA50: Shorter-term trend confirmation is weak. (polarity=negative; metric=price_to_sma50; value=0.95085; threshold=>=0.97)
- `free_cash_flow_missing` — Free cash flow missing: Free cash flow is unavailable, so it cannot support Company Quality. (polarity=missing; metric=free_cash_flow; threshold=>0 supportive; <0 weak)

## Company Quality

- Grade: C
- Score: 0.401667
- Confidence: 0.533333
- Data as-of: 2026-08-06

### Component Scores

- balance_sheet: n/a
- dilution: 1.0
- growth_stability: 0.716667
- operating_red_flags: 1.0
- profitability_cash: 0.5
- valuation_context: 1.0

### Positives

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.363569; threshold=>=10% supportive; <0% weak)
- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=0.151737; threshold=>=15% strong; <-10% weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.052002; threshold=<=3% supportive; >12% weak)
- `pe_hist_percentile_strong` — Historical P/E percentile supportive: Historical P/E percentile supports the quality assessment. (polarity=positive; metric=pe_hist_percentile; value=0.0; threshold=<=60% supportive; >80% expensive)
- `inventory_growth_gap_strong` — Inventory growth gap supportive: Inventory growth gap supports the quality assessment. (polarity=positive; metric=inventory_growth_gap; value=0.0; threshold=<=10pp supportive; >30pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=64; threshold=<=400)

### Risks

- `ocf_to_net_income_weak` — Operating cash-flow conversion weak: Operating cash-flow conversion is a material counter-signal for Company Quality. (polarity=negative; metric=ocf_to_net_income; value=-2.450311; threshold=>=0.8 supportive; <0.5 weak)

### Missing Evidence

- `free_cash_flow_missing` — Free cash flow missing: Free cash flow is unavailable, so it cannot support Company Quality. (polarity=missing; metric=free_cash_flow; threshold=>0 supportive; <0 weak)
- `accrual_ratio_missing` — Accrual quality missing: Accrual quality is unavailable, so it cannot support Company Quality. (polarity=missing; metric=accrual_ratio; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `net_debt_to_ebitda_missing` — Net debt / EBITDA missing: Net debt / EBITDA is unavailable, so it cannot support Company Quality. (polarity=missing; metric=net_debt_to_ebitda; threshold=<=1.5 supportive; >4 weak)
- `interest_coverage_missing` — Interest coverage missing: Interest coverage is unavailable, so it cannot support Company Quality. (polarity=missing; metric=interest_coverage; threshold=>=4 supportive; <1 weak)
- `current_ratio_missing` — Current ratio missing: Current ratio is unavailable, so it cannot support Company Quality. (polarity=missing; metric=current_ratio; threshold=>=1 supportive; <0.75 weak)
- `fcf_yield_missing` — FCF yield missing: FCF yield is unavailable, so it cannot support Company Quality. (polarity=missing; metric=fcf_yield; threshold=>=2% supportive; <-2% weak)
- `ps_hist_percentile_missing` — Historical P/S percentile missing: Historical P/S percentile is unavailable, so it cannot support Company Quality. (polarity=missing; metric=ps_hist_percentile; threshold=<=60% supportive; >80% expensive)
- `receivables_growth_gap_missing` — Receivables growth gap missing: Receivables growth gap is unavailable, so it cannot support Company Quality. (polarity=missing; metric=receivables_growth_gap; threshold=<=5pp supportive; >25pp weak)

## Entry Quality

- State: WATCH_BREAKOUT
- Score: 0.696667
- Confidence: 1.0
- Market as-of: 2026-10-09

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.033603; threshold=>=1.00 healthy; <0.95 damaged)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

### Risks

- `price_below_sma50` — Price below SMA50: Shorter-term trend confirmation is weak. (polarity=negative; metric=price_to_sma50; value=0.95085; threshold=>=0.97)

## Decision History

- Previous action: AVOID
- State change: n/a

## Provenance

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
