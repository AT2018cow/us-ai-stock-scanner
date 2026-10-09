# score_weights sweep (risk_on)

- dataset: outputs/post_pr23_baseline_202610/alpha_attribution/corrected_risk_on_dataset/weight_dataset_risk_on.csv
- candidates: 1 (+baseline) | seed=42
- split: train <= 2026-01-01 < validate
- channels: ['core_ai', 'ai_enabler', 'ai_peripheral'] | top_n per channel: 10
- baseline score: full=0.1641 train=0.1916 valid=-0.1349

## Top 20 by TRAIN score

| rank | cid | train | valid | full | soft_w (lv/mo) |
|---|---|---|---|---|---|
| 1 | 0 | 0.1916 | -0.1349 | 0.1641 | 0.33/0.22 |

## Best candidate details

### Multipliers per list type (applied to each channel's current weights)
- low_value: {"ai_link_score": 1.0, "current_debt_ratio_low": 1.0, "days_below_sma200": 1.0, "ev_to_ebit_low": 1.0, "fcf_yield": 1.0, "inventory_growth_gap_low": 1.0, "liquidity": 1.0, "net_income_yoy": 1.0, "net_margin": 1.0, "pe_discount": 1.0, "pe_percentile_low": 1.0, "ps_discount": 1.0, "ps_percentile_low": 1.0, "range_position_52w_low": 1.0, "revenue_yoy": 1.0, "watchlist_etf_count": 1.0}
- momentum: {"ai_link_score": 1.0, "current_debt_ratio_low": 1.0, "drawdown_from_52w_high": 1.0, "inventory_growth_gap_low": 1.0, "liquidity": 1.0, "return_20d": 1.0, "watchlist_etf_count": 1.0}
- soft_pass_rate weights: {"low_value": 0.3302, "momentum": 0.2176}

### Resulting effective weights per channel
- low_value/core_ai: {"soft_pass_rate": 0.3302, "fcf_yield": 0.1667, "ai_link_score": 0.1436, "pe_discount": 0.1309, "ps_discount": 0.1225, "pe_percentile_low": 0.0825, "watchlist_etf_count": 0.08, "current_debt_ratio_low": 0.0753, "inventory_growth_gap_low": 0.0493, "net_income_yoy": 0.0485, "ev_to_ebit_low": 0.0313, "revenue_yoy": 0.0288, "liquidity": 0.0238, "ps_percentile_low": 0.0226, "range_position_52w_low": 0.0168, "net_margin": 0.0164, "days_below_sma200": 0.0}
- low_value/ai_enabler: {"soft_pass_rate": 0.3302, "fcf_yield": 0.1667, "ai_link_score": 0.1231, "pe_discount": 0.109, "ps_discount": 0.1078, "pe_percentile_low": 0.1031, "current_debt_ratio_low": 0.0753, "net_income_yoy": 0.0647, "watchlist_etf_count": 0.064, "inventory_growth_gap_low": 0.0493, "revenue_yoy": 0.036, "ev_to_ebit_low": 0.0313, "ps_percentile_low": 0.0271, "liquidity": 0.0238, "net_margin": 0.0205, "range_position_52w_low": 0.0112, "days_below_sma200": 0.0}
- low_value/ai_peripheral: {"soft_pass_rate": 0.3302, "fcf_yield": 0.1667, "ai_link_score": 0.1436, "ps_discount": 0.1078, "pe_discount": 0.1018, "pe_percentile_low": 0.0825, "current_debt_ratio_low": 0.0753, "net_income_yoy": 0.0647, "inventory_growth_gap_low": 0.0493, "watchlist_etf_count": 0.048, "revenue_yoy": 0.036, "ev_to_ebit_low": 0.0313, "liquidity": 0.0286, "ps_percentile_low": 0.0226, "range_position_52w_low": 0.0168, "days_below_sma200": 0.0}
- momentum/core_ai: {"return_20d": 0.479, "watchlist_etf_count": 0.2937, "soft_pass_rate": 0.2176, "ai_link_score": 0.1363, "liquidity": 0.115, "inventory_growth_gap_low": 0.0533, "current_debt_ratio_low": 0.0227, "drawdown_from_52w_high": -0.0157}
- momentum/ai_enabler: {"return_20d": 0.479, "watchlist_etf_count": 0.3084, "soft_pass_rate": 0.2176, "ai_link_score": 0.1363, "liquidity": 0.1074, "inventory_growth_gap_low": 0.0533, "current_debt_ratio_low": 0.0227, "drawdown_from_52w_high": -0.0157}
- momentum/ai_peripheral: {"return_20d": 0.491, "watchlist_etf_count": 0.2937, "soft_pass_rate": 0.2176, "ai_link_score": 0.1363, "liquidity": 0.1074, "inventory_growth_gap_low": 0.0533, "current_debt_ratio_low": 0.0227, "drawdown_from_52w_high": -0.0157}

### Per-year breakdown (best candidate)
| list_type   |   horizon_days |   year |   n_dates |   avg_return |   win_rate |   avg_excess_vs_qqq |
|:------------|---------------:|-------:|----------:|-------------:|-----------:|--------------------:|
| low_value   |             20 |   2023 |        12 |   0.0121286  |   0.583333 |         -0.00907947 |
| low_value   |             20 |   2024 |        12 |   0.0206994  |   0.666667 |          0.00257161 |
| low_value   |             20 |   2025 |        10 |   0.029249   |   0.7      |          0.0193195  |
| low_value   |             20 |   2026 |         7 |  -0.0162715  |   0.571429 |         -0.0130692  |
| low_value   |             60 |   2023 |        12 |   0.0740307  |   0.666667 |         -0.013375   |
| low_value   |             60 |   2024 |        12 |   0.0228661  |   0.666667 |         -0.0147941  |
| low_value   |             60 |   2025 |        10 |   0.0903641  |   0.9      |          0.0686222  |
| low_value   |             60 |   2026 |         7 |  -0.138598   |   0.428571 |         -0.0241398  |
| low_value   |            120 |   2023 |        12 |   0.186445   |   1        |          0.0202721  |
| low_value   |            120 |   2024 |        12 |   0.070578   |   0.75     |         -0.00353975 |
| low_value   |            120 |   2025 |        10 |   0.253997   |   1        |          0.156714   |
| low_value   |            120 |   2026 |         5 |  -0.2861     |   0.4      |         -0.0293281  |
| momentum    |             20 |   2023 |        12 |   0.0134467  |   0.583333 |         -0.0077613  |
| momentum    |             20 |   2024 |        12 |   0.0384323  |   0.916667 |          0.0203045  |
| momentum    |             20 |   2025 |        10 |   0.0319787  |   0.7      |          0.0220492  |
| momentum    |             20 |   2026 |         7 |  -0.00585847 |   0.571429 |         -0.00265614 |
| momentum    |             60 |   2023 |        12 |   0.0692815  |   0.666667 |         -0.0181242  |
| momentum    |             60 |   2024 |        12 |   0.068575   |   0.833333 |          0.0309148  |
| momentum    |             60 |   2025 |        10 |   0.105052   |   0.8      |          0.0833103  |
| momentum    |             60 |   2026 |         5 |   0.025876   |   0.4      |         -0.0254261  |
| momentum    |            120 |   2023 |        12 |   0.172414   |   1        |          0.00624072 |
| momentum    |            120 |   2024 |        12 |   0.118077   |   0.833333 |          0.0439589  |
| momentum    |            120 |   2025 |        10 |   0.26994    |   1        |          0.172658   |
| momentum    |            120 |   2026 |         2 |   0.194016   |   1        |          0.0504383  |

### Per-regime breakdown (best candidate)
| list_type   |   horizon_days | regime   |   n_dates |   avg_return |   win_rate |   avg_excess_vs_qqq |
|:------------|---------------:|:---------|----------:|-------------:|-----------:|--------------------:|
| low_value   |             20 | down     |         8 |  -0.0203495  |   0.5      |        -0.0235242   |
| low_value   |             20 | up       |        33 |   0.0222825  |   0.666667 |         0.0064185   |
| low_value   |             60 | down     |         8 |   0.00893504 |   0.875    |        -0.0287106   |
| low_value   |             60 | up       |        33 |   0.0310526  |   0.636364 |         0.0133896   |
| low_value   |            120 | down     |         8 |   0.0570933  |   0.75     |        -0.000709752 |
| low_value   |            120 | up       |        31 |   0.120548   |   0.870968 |         0.0591118   |
| momentum    |             20 | down     |         8 |   0.00584928 |   0.5      |         0.00267458  |
| momentum    |             20 | up       |        33 |   0.0258949  |   0.757576 |         0.0100309   |
| momentum    |             60 | down     |         7 |   0.113122   |   1        |        -0.00479964  |
| momentum    |             60 | up       |        32 |   0.0638226  |   0.65625  |         0.027908    |
| momentum    |            120 | down     |         7 |   0.186484   |   0.857143 |         0.0415251   |
| momentum    |            120 | up       |        29 |   0.181653   |   0.965517 |         0.0737646   |

### Baseline per-year breakdown (current config)
| list_type   |   horizon_days |   year |   n_dates |   avg_return |   win_rate |   avg_excess_vs_qqq |
|:------------|---------------:|-------:|----------:|-------------:|-----------:|--------------------:|
| low_value   |             20 |   2023 |        12 |   0.0121286  |   0.583333 |         -0.00907947 |
| low_value   |             20 |   2024 |        12 |   0.0206994  |   0.666667 |          0.00257161 |
| low_value   |             20 |   2025 |        10 |   0.029249   |   0.7      |          0.0193195  |
| low_value   |             20 |   2026 |         7 |  -0.0162715  |   0.571429 |         -0.0130692  |
| low_value   |             60 |   2023 |        12 |   0.0740307  |   0.666667 |         -0.013375   |
| low_value   |             60 |   2024 |        12 |   0.0228661  |   0.666667 |         -0.0147941  |
| low_value   |             60 |   2025 |        10 |   0.0903641  |   0.9      |          0.0686222  |
| low_value   |             60 |   2026 |         7 |  -0.138598   |   0.428571 |         -0.0241398  |
| low_value   |            120 |   2023 |        12 |   0.186445   |   1        |          0.0202721  |
| low_value   |            120 |   2024 |        12 |   0.070578   |   0.75     |         -0.00353975 |
| low_value   |            120 |   2025 |        10 |   0.253997   |   1        |          0.156714   |
| low_value   |            120 |   2026 |         5 |  -0.2861     |   0.4      |         -0.0293281  |
| momentum    |             20 |   2023 |        12 |   0.0134467  |   0.583333 |         -0.0077613  |
| momentum    |             20 |   2024 |        12 |   0.0384323  |   0.916667 |          0.0203045  |
| momentum    |             20 |   2025 |        10 |   0.0319787  |   0.7      |          0.0220492  |
| momentum    |             20 |   2026 |         7 |  -0.00585847 |   0.571429 |         -0.00265614 |
| momentum    |             60 |   2023 |        12 |   0.0692815  |   0.666667 |         -0.0181242  |
| momentum    |             60 |   2024 |        12 |   0.068575   |   0.833333 |          0.0309148  |
| momentum    |             60 |   2025 |        10 |   0.105052   |   0.8      |          0.0833103  |
| momentum    |             60 |   2026 |         5 |   0.025876   |   0.4      |         -0.0254261  |
| momentum    |            120 |   2023 |        12 |   0.172414   |   1        |          0.00624072 |
| momentum    |            120 |   2024 |        12 |   0.118077   |   0.833333 |          0.0439589  |
| momentum    |            120 |   2025 |        10 |   0.26994    |   1        |          0.172658   |
| momentum    |            120 |   2026 |         2 |   0.194016   |   1        |          0.0504383  |

### Baseline per-regime breakdown (current config)
| list_type   |   horizon_days | regime   |   n_dates |   avg_return |   win_rate |   avg_excess_vs_qqq |
|:------------|---------------:|:---------|----------:|-------------:|-----------:|--------------------:|
| low_value   |             20 | down     |         8 |  -0.0203495  |   0.5      |        -0.0235242   |
| low_value   |             20 | up       |        33 |   0.0222825  |   0.666667 |         0.0064185   |
| low_value   |             60 | down     |         8 |   0.00893504 |   0.875    |        -0.0287106   |
| low_value   |             60 | up       |        33 |   0.0310526  |   0.636364 |         0.0133896   |
| low_value   |            120 | down     |         8 |   0.0570933  |   0.75     |        -0.000709752 |
| low_value   |            120 | up       |        31 |   0.120548   |   0.870968 |         0.0591118   |
| momentum    |             20 | down     |         8 |   0.00584928 |   0.5      |         0.00267458  |
| momentum    |             20 | up       |        33 |   0.0258949  |   0.757576 |         0.0100309   |
| momentum    |             60 | down     |         7 |   0.113122   |   1        |        -0.00479964  |
| momentum    |             60 | up       |        32 |   0.0638226  |   0.65625  |         0.027908    |
| momentum    |            120 | down     |         7 |   0.186484   |   0.857143 |         0.0415251   |
| momentum    |            120 | up       |        29 |   0.181653   |   0.965517 |         0.0737646   |