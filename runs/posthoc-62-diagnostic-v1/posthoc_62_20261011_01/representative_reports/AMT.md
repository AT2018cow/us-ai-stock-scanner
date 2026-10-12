# Detailed Report — AMT — AMERICAN TOWER CORP /MA/

## AMT — AMERICAN TOWER CORP /MA/

- Decision date: 2026-10-09
- Company Quality: B
- Entry Quality: ENTRY_READY
- Action State: HOLD_MONITOR
- Priority: 33
- Fundamental data as-of: 2026-07-28
- Market data as-of: 2026-10-09
- Review trigger: Re-review on a Quality or Entry state change; prioritize only if Quality A reaches ENTRY_READY.
- Previous action: HOLD_MONITOR
- State change reason: Entry Quality TREND_DAMAGED→ENTRY_READY.

## Decision Rationale

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.329406; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=3959800000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=1.60227; threshold=>=0.8 supportive; <0.5 weak)
- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=1.418926; threshold=>=15% strong; <-10% weak)
- `accrual_ratio_weak` — Accrual quality weak: Accrual quality is a material counter-signal for Company Quality. (polarity=negative; metric=accrual_ratio; value=-0.695202; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `current_ratio_weak` — Current ratio weak: Current ratio is a material counter-signal for Company Quality. (polarity=negative; metric=current_ratio; value=0.351998; threshold=>=1 supportive; <0.75 weak)

## Company Quality

- Grade: B
- Score: 0.726667
- Confidence: 1.0
- Data as-of: 2026-07-28

### Component Scores

- balance_sheet: 0.383333
- dilution: 1.0
- growth_stability: 0.716667
- operating_red_flags: 1.0
- profitability_cash: 0.75
- valuation_context: 0.816667

### Positives

- `net_margin_strong` — Net margin supportive: Net margin supports the quality assessment. (polarity=positive; metric=net_margin; value=0.329406; threshold=>=10% supportive; <0% weak)
- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=3959800000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=1.60227; threshold=>=0.8 supportive; <0.5 weak)
- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=1.418926; threshold=>=15% strong; <-10% weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=-0.004893; threshold=<=3% supportive; >12% weak)
- `fcf_yield_strong` — FCF yield supportive: FCF yield supports the quality assessment. (polarity=positive; metric=fcf_yield; value=0.046574; threshold=>=2% supportive; <-2% weak)
- `ps_hist_percentile_strong` — Historical P/S percentile supportive: Historical P/S percentile supports the quality assessment. (polarity=positive; metric=ps_hist_percentile; value=0.5; threshold=<=60% supportive; >80% expensive)
- `pe_hist_percentile_strong` — Historical P/E percentile supportive: Historical P/E percentile supports the quality assessment. (polarity=positive; metric=pe_hist_percentile; value=0.25; threshold=<=60% supportive; >80% expensive)
- `receivables_growth_gap_strong` — Receivables growth gap supportive: Receivables growth gap supports the quality assessment. (polarity=positive; metric=receivables_growth_gap; value=-0.223439; threshold=<=5pp supportive; >25pp weak)
- `inventory_growth_gap_strong` — Inventory growth gap supportive: Inventory growth gap supports the quality assessment. (polarity=positive; metric=inventory_growth_gap; value=0.0; threshold=<=10pp supportive; >30pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=73; threshold=<=400)

### Risks

- `accrual_ratio_weak` — Accrual quality weak: Accrual quality is a material counter-signal for Company Quality. (polarity=negative; metric=accrual_ratio; value=-0.695202; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `current_ratio_weak` — Current ratio weak: Current ratio is a material counter-signal for Company Quality. (polarity=negative; metric=current_ratio; value=0.351998; threshold=>=1 supportive; <0.75 weak)

### Missing Evidence

- none

## Entry Quality

- State: ENTRY_READY
- Score: 0.873333
- Confidence: 1.0
- Market as-of: 2026-10-09

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.032559; threshold=>=1.00 healthy; <0.95 damaged)
- `price_near_sma50_ready_band` — Price near SMA50: Price is in the pre-registered SMA50 readiness band. (polarity=positive; metric=price_to_sma50; value=1.057261; threshold=0.98–1.08)
- `return_20d_ready_band` — 20d return in readiness band: Recent momentum is positive/controlled rather than chased. (polarity=positive; metric=return_20d; value=0.025199; threshold=-3% to +12%)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.080154; threshold=>=0%)
- `relative_strength_60d_qqq_ready` — 60d relative strength acceptable: The stock is keeping pace with QQQ over 60 trading days. (polarity=positive; metric=relative_strength_60d_qqq; value=0.015941; threshold=>=-3%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

### Risks

- none

## Decision History

- Previous action: HOLD_MONITOR
- State change: Entry Quality TREND_DAMAGED→ENTRY_READY.

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
