# Detailed Report — GS — GOLDMAN SACHS GROUP INC

## GS — GOLDMAN SACHS GROUP INC

- Decision date: 2026-10-09
- Company Quality: UNRATED
- Entry Quality: TREND_DAMAGED
- Action State: AVOID
- Priority: 61
- Fundamental data as-of: 2026-08-03
- Market data as-of: 2026-10-09
- Review trigger: Re-review after stale/missing evidence clears or Quality/Entry materially improves.
- Previous action: AVOID
- State change reason: n/a

## Decision Rationale

- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=0.34912; threshold=>=15% strong; <-10% weak)
- `operating_cash_flow_yoy_strong` — Operating cash-flow growth supportive: Operating cash-flow growth supports the quality assessment. (polarity=positive; metric=operating_cash_flow_yoy; value=0.722344; threshold=>=15% strong; <-10% weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.038153; threshold=<=3% supportive; >12% weak)
- `pe_hist_percentile_strong` — Historical P/E percentile supportive: Historical P/E percentile supports the quality assessment. (polarity=positive; metric=pe_hist_percentile; value=0.0; threshold=<=60% supportive; >80% expensive)
- `free_cash_flow_weak` — Free cash flow weak: Free cash flow is a material counter-signal for Company Quality. (polarity=negative; metric=free_cash_flow; value=-41515000000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_weak` — Operating cash-flow conversion weak: Operating cash-flow conversion is a material counter-signal for Company Quality. (polarity=negative; metric=ocf_to_net_income; value=-1.874684; threshold=>=0.8 supportive; <0.5 weak)
- `fcf_yield_weak` — FCF yield weak: FCF yield is a material counter-signal for Company Quality. (polarity=negative; metric=fcf_yield; value=-0.15925; threshold=>=2% supportive; <-2% weak)

## Company Quality

- Grade: UNRATED
- Score: 0.266667
- Confidence: 0.45
- Data as-of: 2026-08-03

### Component Scores

- balance_sheet: n/a
- dilution: 1.0
- growth_stability: 1.0
- operating_red_flags: n/a
- profitability_cash: 0.0
- valuation_context: 0.5

### Positives

- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=0.34912; threshold=>=15% strong; <-10% weak)
- `operating_cash_flow_yoy_strong` — Operating cash-flow growth supportive: Operating cash-flow growth supports the quality assessment. (polarity=positive; metric=operating_cash_flow_yoy; value=0.722344; threshold=>=15% strong; <-10% weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.038153; threshold=<=3% supportive; >12% weak)
- `pe_hist_percentile_strong` — Historical P/E percentile supportive: Historical P/E percentile supports the quality assessment. (polarity=positive; metric=pe_hist_percentile; value=0.0; threshold=<=60% supportive; >80% expensive)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=67; threshold=<=400)

### Risks

- `free_cash_flow_weak` — Free cash flow weak: Free cash flow is a material counter-signal for Company Quality. (polarity=negative; metric=free_cash_flow; value=-41515000000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_weak` — Operating cash-flow conversion weak: Operating cash-flow conversion is a material counter-signal for Company Quality. (polarity=negative; metric=ocf_to_net_income; value=-1.874684; threshold=>=0.8 supportive; <0.5 weak)
- `fcf_yield_weak` — FCF yield weak: FCF yield is a material counter-signal for Company Quality. (polarity=negative; metric=fcf_yield; value=-0.15925; threshold=>=2% supportive; <-2% weak)

### Missing Evidence

- `net_margin_missing` — Net margin missing: Net margin is unavailable, so it cannot support Company Quality. (polarity=missing; metric=net_margin; threshold=>=10% supportive; <0% weak)
- `accrual_ratio_missing` — Accrual quality missing: Accrual quality is unavailable, so it cannot support Company Quality. (polarity=missing; metric=accrual_ratio; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `revenue_yoy_missing` — Revenue growth missing: Revenue growth is unavailable, so it cannot support Company Quality. (polarity=missing; metric=revenue_yoy; threshold=>=8% supportive; <-10% weak)
- `net_debt_to_ebitda_missing` — Net debt / EBITDA missing: Net debt / EBITDA is unavailable, so it cannot support Company Quality. (polarity=missing; metric=net_debt_to_ebitda; threshold=<=1.5 supportive; >4 weak)
- `interest_coverage_missing` — Interest coverage missing: Interest coverage is unavailable, so it cannot support Company Quality. (polarity=missing; metric=interest_coverage; threshold=>=4 supportive; <1 weak)
- `current_ratio_missing` — Current ratio missing: Current ratio is unavailable, so it cannot support Company Quality. (polarity=missing; metric=current_ratio; threshold=>=1 supportive; <0.75 weak)
- `ps_hist_percentile_missing` — Historical P/S percentile missing: Historical P/S percentile is unavailable, so it cannot support Company Quality. (polarity=missing; metric=ps_hist_percentile; threshold=<=60% supportive; >80% expensive)
- `receivables_growth_gap_missing` — Receivables growth gap missing: Receivables growth gap is unavailable, so it cannot support Company Quality. (polarity=missing; metric=receivables_growth_gap; threshold=<=5pp supportive; >25pp weak)
- `inventory_growth_gap_missing` — Inventory growth gap missing: Inventory growth gap is unavailable, so it cannot support Company Quality. (polarity=missing; metric=inventory_growth_gap; threshold=<=10pp supportive; >30pp weak)

## Entry Quality

- State: TREND_DAMAGED
- Score: 0.189167
- Confidence: 1.0
- Market as-of: 2026-10-09

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

### Risks

- `price_materially_below_sma200` — Price materially below SMA200: Long-term price structure is materially damaged. (polarity=negative; metric=price_to_sma200; value=0.932764; threshold=>=1.00 healthy; <0.95 damaged)
- `price_below_sma50` — Price below SMA50: Shorter-term trend confirmation is weak. (polarity=negative; metric=price_to_sma50; value=0.904523; threshold=>=0.97)
- `return_60d_weak` — 60d trend weak: Medium-term momentum is weak. (polarity=negative; metric=return_60d; value=-0.18292; threshold=>-8% preferred)
- `relative_strength_60d_qqq_weak` — 60d relative strength weak: The stock is materially lagging QQQ. (polarity=negative; metric=relative_strength_60d_qqq; value=-0.247133; threshold=>-10% preferred)

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
