# Low-value selection attribution

This is descriptive offline attribution using frozen survivor datasets and replay selections.
It does not rerun PIT data and does not establish causal P&L by itself.

- audited years: 2023, 2025
- primary outcome horizon: 120d
- risk_on-only channel-selection cases: 412

## Exclusion reasons

- hard:max_range_position_52w: n=189, mature=189, winner_vs_QQQ=117, avg_excess=+0.1166
- hard:min_drawdown_from_52w_high: n=98, mature=98, winner_vs_QQQ=61, avg_excess=+0.1442
- hard:max_price_to_sma200: n=96, mature=96, winner_vs_QQQ=58, avg_excess=+0.1464
- below_top_n: n=18, mature=18, winner_vs_QQQ=6, avg_excess=-0.0271
- group_cap: n=11, mature=11, winner_vs_QQQ=4, avg_excess=+0.0815

## Repeated soft-condition failures

- max_ps_hist_percentile: cases=314, winners_vs_QQQ=177, avg_excess=+0.1165
- max_pe_hist_percentile: cases=226, winners_vs_QQQ=144, avg_excess=+0.1648
- min_value_discount_any: cases=143, winners_vs_QQQ=77, avg_excess=+0.0855
- max_20d_return: cases=106, winners_vs_QQQ=76, avg_excess=+0.2265
- min_avg_dollar_volume_20d: cases=92, winners_vs_QQQ=51, avg_excess=+0.0674
- max_ev_to_ebit: cases=88, winners_vs_QQQ=49, avg_excess=+0.0643
- min_net_income_yoy: cases=57, winners_vs_QQQ=35, avg_excess=+0.0425
- min_expectation_proxy: cases=47, winners_vs_QQQ=29, avg_excess=+0.0886
- min_interest_coverage: cases=43, winners_vs_QQQ=29, avg_excess=+0.1929
- min_current_ratio: cases=42, winners_vs_QQQ=23, avg_excess=+0.0069
- max_ps_percentile_in_sic: cases=60, winners_vs_QQQ=22, avg_excess=-0.0367
- max_net_debt_to_ebitda: cases=31, winners_vs_QQQ=20, avg_excess=+0.2034

## Largest missed positive-excess cases

- 2025-12-31 core_ai MU: excess=+2.9621, reason=hard:min_drawdown_from_52w_high, soft_fail=max_20d_return,max_ps_hist_percentile,max_pe_hist_percentile
- 2025-12-31 ai_enabler MU: excess=+2.9621, reason=hard:max_range_position_52w, soft_fail=max_20d_return,max_ps_hist_percentile,max_pe_hist_percentile
- 2025-11-28 ai_enabler MU: excess=+2.0644, reason=hard:max_price_to_sma200, soft_fail=max_ps_hist_percentile,max_pe_hist_percentile
- 2025-11-28 core_ai MU: excess=+2.0644, reason=hard:max_range_position_52w, soft_fail=max_ps_hist_percentile,max_pe_hist_percentile
- 2025-08-29 core_ai LRCX: excess=+1.4610, reason=hard:max_price_to_sma200, soft_fail=max_shares_yoy,min_value_discount_any
- 2025-08-29 ai_enabler LRCX: excess=+1.4610, reason=hard:max_price_to_sma200, soft_fail=max_shares_yoy,min_value_discount_any
- 2023-12-29 core_ai NVDA: excess=+1.2321, reason=hard:min_drawdown_from_52w_high, soft_fail=
- 2023-12-29 ai_enabler NVDA: excess=+1.2321, reason=hard:max_range_position_52w, soft_fail=
- 2025-10-31 ai_enabler MU: excess=+1.1979, reason=hard:max_range_position_52w, soft_fail=max_20d_return,max_ps_hist_percentile,max_pe_hist_percentile
- 2025-10-31 core_ai MU: excess=+1.1979, reason=hard:min_drawdown_from_52w_high, soft_fail=max_20d_return,max_ps_hist_percentile,max_pe_hist_percentile
- 2023-11-30 ai_enabler VRT: excess=+1.1607, reason=hard:max_range_position_52w, soft_fail=min_avg_dollar_volume_20d,max_net_debt_to_ebitda,min_interest_coverage,max_ps_hist_percentile,max_pe_hist_percentile
- 2023-11-30 ai_peripheral VRT: excess=+1.1607, reason=hard:max_range_position_52w, soft_fail=min_avg_dollar_volume_20d,max_net_debt_to_ebitda,min_interest_coverage,max_ps_hist_percentile,max_pe_hist_percentile
- 2025-12-31 ai_enabler LRCX: excess=+1.1066, reason=hard:max_range_position_52w, soft_fail=max_ps_hist_percentile,max_pe_hist_percentile,min_value_discount_any
- 2025-12-31 core_ai LRCX: excess=+1.1066, reason=hard:min_drawdown_from_52w_high, soft_fail=max_ev_to_ebit,max_ps_hist_percentile,max_pe_hist_percentile,min_value_discount_any
- 2023-10-31 ai_peripheral VRT: excess=+0.9187, reason=hard:max_price_to_sma200, soft_fail=min_avg_dollar_volume_20d,max_net_debt_to_ebitda,min_interest_coverage,max_ps_hist_percentile,max_pe_hist_percentile
- 2023-10-31 ai_enabler VRT: excess=+0.9187, reason=hard:max_price_to_sma200, soft_fail=min_avg_dollar_volume_20d,max_net_debt_to_ebitda,min_interest_coverage,max_ps_hist_percentile,max_pe_hist_percentile
- 2025-12-31 ai_enabler KLAC: excess=+0.8913, reason=hard:max_price_to_sma200, soft_fail=min_interest_coverage
- 2025-09-30 ai_enabler VRT: excess=+0.8539, reason=hard:max_range_position_52w, soft_fail=max_20d_return,max_ps_hist_percentile,max_pe_hist_percentile
- 2025-09-30 ai_peripheral VRT: excess=+0.8539, reason=hard:max_range_position_52w, soft_fail=max_20d_return,max_ps_hist_percentile,max_pe_hist_percentile
- 2025-09-30 core_ai AMAT: excess=+0.8528, reason=hard:min_drawdown_from_52w_high, soft_fail=max_20d_return,max_ps_hist_percentile,max_pe_hist_percentile

## Paired selection-only diagnostic

- mean of per-date (risk_on-only mean return - risk_off-only mean return): +0.1151
- This is a selection-substitution diagnostic, not an account-return estimate.
