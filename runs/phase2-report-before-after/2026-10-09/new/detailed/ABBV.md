# Detailed Report — ABBV — AbbVie Inc.

## ABBV — AbbVie Inc.

- Decision date: 2026-10-09
- Company Quality: A
- Entry Quality: ENTRY_READY
- Action State: PRIORITY_REVIEW
- Priority: 7
- Fundamental data as-of: 2026-08-03
- Market data as-of: 2026-10-09
- Review trigger: Review now; downgrade if Company Quality falls below A or Entry Quality leaves ENTRY_READY.
- Previous action: PRIORITY_REVIEW
- State change reason: n/a

## Company Quality

- Grade: A
- Score: 0.746667
- Confidence: 1.0
- Data as-of: 2026-08-03

### Component Scores

- balance_sheet: 0.733333
- dilution: 0.8
- growth_stability: 0.816667
- operating_red_flags: 1.0
- profitability_cash: 0.65
- valuation_context: 0.616667

### Positives

- `free_cash_flow_strong` — Free cash flow supportive: Free cash flow supports the quality assessment. (polarity=positive; metric=free_cash_flow; value=18210000000.0; threshold=>0 supportive; <0 weak)
- `ocf_to_net_income_strong` — Operating cash-flow conversion supportive: Operating cash-flow conversion supports the quality assessment. (polarity=positive; metric=ocf_to_net_income; value=3.058003; threshold=>=0.8 supportive; <0.5 weak)
- `revenue_yoy_strong` — Revenue growth supportive: Revenue growth supports the quality assessment. (polarity=positive; metric=revenue_yoy; value=0.103861; threshold=>=8% supportive; <-10% weak)
- `adjusted_net_income_yoy_strong` — Earnings growth supportive: Earnings growth supports the quality assessment. (polarity=positive; metric=adjusted_net_income_yoy; value=0.608016; threshold=>=15% strong; <-10% weak)
- `net_debt_to_ebitda_strong` — Net debt / EBITDA supportive: Net debt / EBITDA supports the quality assessment. (polarity=positive; metric=net_debt_to_ebitda; value=-0.370795; threshold=<=1.5 supportive; >4 weak)
- `interest_coverage_strong` — Interest coverage supportive: Interest coverage supports the quality assessment. (polarity=positive; metric=interest_coverage; value=5.808985; threshold=>=4 supportive; <1 weak)
- `shares_yoy_strong` — Share-count change supportive: Share-count change supports the quality assessment. (polarity=positive; metric=shares_yoy; value=0.000316; threshold=<=3% supportive; >12% weak)
- `fcf_yield_strong` — FCF yield supportive: FCF yield supports the quality assessment. (polarity=positive; metric=fcf_yield; value=0.037283; threshold=>=2% supportive; <-2% weak)
- `pe_hist_percentile_strong` — Historical P/E percentile supportive: Historical P/E percentile supports the quality assessment. (polarity=positive; metric=pe_hist_percentile; value=0.25; threshold=<=60% supportive; >80% expensive)
- `receivables_growth_gap_strong` — Receivables growth gap supportive: Receivables growth gap supports the quality assessment. (polarity=positive; metric=receivables_growth_gap; value=-0.00993; threshold=<=5pp supportive; >25pp weak)
- `inventory_growth_gap_strong` — Inventory growth gap supportive: Inventory growth gap supports the quality assessment. (polarity=positive; metric=inventory_growth_gap; value=-0.070192; threshold=<=10pp supportive; >30pp weak)
- `fundamental_data_fresh` — Fundamental data freshness: Fundamental evidence is within the pre-registered freshness window. (polarity=positive; metric=fundamental_data_age_days; value=67; threshold=<=400)

## Quality Applicability

- Company Quality v1 is one common financial-quality core. Specialist accounting semantics (banks, brokers, insurers, REITs, foreign or unsupported reporting models) are pending independent review; until then, cross-model comparability is UNVERIFIED for every decision, and this grade must not be read as sector-relative quality.
- Applicability for THIS decision: not disproven, but still unverified across business models — compare with caution.

## Entry Quality

- State: ENTRY_READY
- Structure: Price holds above its long-term trend inside the readiness band with non-negative momentum — a healthy structure that is not overextended.
- Score: 0.835
- Confidence: 1.0
- Market as-of: 2026-10-09

### Positives

- `market_data_fresh` — Market data fresh: Market data is within the preferred freshness window. (polarity=positive; metric=market_data_age_days; value=0; threshold=<=3)
- `price_above_sma200` — Price above SMA200: Long-term price structure is above its 200-day average. (polarity=positive; metric=price_to_sma200; value=1.188088; threshold=>=1.00 healthy; <0.95 damaged)
- `price_near_sma50_ready_band` — Price near SMA50: Price is in the pre-registered SMA50 readiness band. (polarity=positive; metric=price_to_sma50; value=1.067605; threshold=0.98–1.08)
- `return_20d_ready_band` — 20d return in readiness band: Recent momentum is positive/controlled rather than chased. (polarity=positive; metric=return_20d; value=0.074922; threshold=-3% to +12%)
- `return_60d_nonnegative` — 60d trend non-negative: Medium-term momentum is non-negative. (polarity=positive; metric=return_60d; value=0.086563; threshold=>=0%)
- `relative_strength_60d_qqq_ready` — 60d relative strength acceptable: The stock is keeping pace with QQQ over 60 trading days. (polarity=positive; metric=relative_strength_60d_qqq; value=0.02235; threshold=>=-3%)
- `supportive_market_regime` — Supportive market regime: Benchmark regime does not impose the defensive entry gate. (polarity=positive; metric=regime; value=up; threshold=supportive)

## Counter-Evidence

- `accrual_ratio_weak` — Accrual quality weak: Accrual quality is a material counter-signal for Company Quality. (polarity=negative; metric=accrual_ratio; value=-0.389914; threshold=|accrual|<=0.10 supportive; >0.35 weak)
- `ps_hist_percentile_weak` — Historical P/S percentile weak: Historical P/S percentile is a material counter-signal for Company Quality. (polarity=negative; metric=ps_hist_percentile; value=1.0; threshold=<=60% supportive; >80% expensive)

## Missing Evidence

- none

## Next Review Conditions

- Trigger: Review now; downgrade if Company Quality falls below A or Entry Quality leaves ENTRY_READY.
- Structure: Watch for loss of the readiness band or momentum breakdown.

## Decision History

- Previous action: PRIORITY_REVIEW
- State change: n/a

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
