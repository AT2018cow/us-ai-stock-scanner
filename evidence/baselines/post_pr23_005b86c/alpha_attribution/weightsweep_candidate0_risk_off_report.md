# score_weights sweep (risk_off)

- dataset: outputs/post_pr23_baseline_202610/weight_dataset_risk_off.csv
- candidates: 1 (+baseline) | seed=42
- split: train <= 2026-01-01 < validate
- channels: ['core_ai', 'ai_enabler', 'ai_peripheral'] | top_n per channel: 10
- baseline score: full=0.1484 train=0.1668 valid=0.0109

## Top 20 by TRAIN score

| rank | cid | train | valid | full | soft_w (lv/mo) |
|---|---|---|---|---|---|
| 1 | 0 | 0.1668 | 0.0109 | 0.1484 | 0.12/0.32 |

## Best candidate details

### Multipliers per list type (applied to each channel's current weights)
- low_value: {"ai_link_score": 1.0, "current_debt_ratio_low": 1.0, "days_below_sma200": 1.0, "ev_to_ebit_low": 1.0, "fcf_yield": 1.0, "inventory_growth_gap_low": 1.0, "liquidity": 1.0, "net_income_yoy": 1.0, "net_margin": 1.0, "pe_discount": 1.0, "pe_percentile_low": 1.0, "ps_discount": 1.0, "ps_percentile_low": 1.0, "range_position_52w_low": 1.0, "revenue_yoy": 1.0, "watchlist_etf_count": 1.0}
- momentum: {"ai_link_score": 1.0, "current_debt_ratio_low": 1.0, "drawdown_from_52w_high": 1.0, "inventory_growth_gap_low": 1.0, "liquidity": 1.0, "return_20d": 1.0, "watchlist_etf_count": 1.0}
- soft_pass_rate weights: {"low_value": 0.1238, "momentum": 0.3243}

### Resulting effective weights per channel
- low_value/core_ai: {"pe_discount": 0.2482, "ev_to_ebit_low": 0.1814, "soft_pass_rate": 0.1238, "ai_link_score": 0.1205, "watchlist_etf_count": 0.1158, "ps_discount": 0.0901, "ps_percentile_low": 0.0664, "fcf_yield": 0.0476, "pe_percentile_low": 0.0404, "inventory_growth_gap_low": 0.0394, "net_margin": 0.0343, "range_position_52w_low": 0.0263, "days_below_sma200": 0.0242, "revenue_yoy": 0.0211, "net_income_yoy": 0.0206, "current_debt_ratio_low": 0.0147, "liquidity": 0.0095}
- low_value/ai_enabler: {"pe_discount": 0.2069, "ev_to_ebit_low": 0.1814, "soft_pass_rate": 0.1238, "ai_link_score": 0.1033, "watchlist_etf_count": 0.0926, "ps_percentile_low": 0.0797, "ps_discount": 0.0793, "pe_percentile_low": 0.0504, "fcf_yield": 0.0476, "net_margin": 0.0429, "inventory_growth_gap_low": 0.0394, "net_income_yoy": 0.0275, "revenue_yoy": 0.0264, "days_below_sma200": 0.0242, "range_position_52w_low": 0.0175, "current_debt_ratio_low": 0.0147, "liquidity": 0.0095}
- low_value/ai_peripheral: {"pe_discount": 0.1931, "ev_to_ebit_low": 0.1814, "soft_pass_rate": 0.1238, "ai_link_score": 0.1205, "ps_discount": 0.0793, "watchlist_etf_count": 0.0695, "ps_percentile_low": 0.0664, "fcf_yield": 0.0476, "pe_percentile_low": 0.0404, "inventory_growth_gap_low": 0.0394, "net_income_yoy": 0.0275, "revenue_yoy": 0.0264, "range_position_52w_low": 0.0263, "days_below_sma200": 0.0242, "current_debt_ratio_low": 0.0147, "liquidity": 0.0114}
- momentum/core_ai: {"return_20d": 0.4798, "watchlist_etf_count": 0.3489, "soft_pass_rate": 0.3243, "ai_link_score": 0.2288, "liquidity": 0.0647, "inventory_growth_gap_low": 0.0436, "current_debt_ratio_low": 0.0155, "drawdown_from_52w_high": -0.034}
- momentum/ai_enabler: {"return_20d": 0.4798, "watchlist_etf_count": 0.3663, "soft_pass_rate": 0.3243, "ai_link_score": 0.2288, "liquidity": 0.0604, "inventory_growth_gap_low": 0.0436, "current_debt_ratio_low": 0.0155, "drawdown_from_52w_high": -0.034}
- momentum/ai_peripheral: {"return_20d": 0.4918, "watchlist_etf_count": 0.3489, "soft_pass_rate": 0.3243, "ai_link_score": 0.2288, "liquidity": 0.0604, "inventory_growth_gap_low": 0.0436, "current_debt_ratio_low": 0.0155, "drawdown_from_52w_high": -0.034}

### Per-year breakdown (best candidate)
| list_type   |   horizon_days |   year |   n_dates |   avg_return |   win_rate |   avg_excess_vs_qqq |
|:------------|---------------:|-------:|----------:|-------------:|-----------:|--------------------:|
| low_value   |             20 |   2023 |        12 |   0.00978126 |   0.416667 |        -0.0114268   |
| low_value   |             20 |   2024 |        12 |   0.0135597  |   0.666667 |        -0.00456812  |
| low_value   |             20 |   2025 |        10 |   0.00928423 |   0.7      |        -0.000645247 |
| low_value   |             20 |   2026 |         7 |  -0.0158506  |   0.285714 |        -0.0126483   |
| low_value   |             60 |   2023 |        12 |   0.0465558  |   0.666667 |        -0.04085     |
| low_value   |             60 |   2024 |        12 |   0.0286813  |   0.583333 |        -0.00897894  |
| low_value   |             60 |   2025 |        10 |   0.0322081  |   0.6      |         0.0104662   |
| low_value   |             60 |   2026 |         5 |   0.0533342  |   0.6      |         0.00203206  |
| low_value   |            120 |   2023 |        12 |   0.116705   |   0.916667 |        -0.0494684   |
| low_value   |            120 |   2024 |        12 |   0.0644104  |   0.75     |        -0.00970742  |
| low_value   |            120 |   2025 |        10 |   0.127635   |   0.8      |         0.0303526   |
| low_value   |            120 |   2026 |         3 |  -0.110443   |   0.666667 |        -0.0327417   |
| momentum    |             20 |   2023 |        12 |   0.0150084  |   0.583333 |        -0.00619963  |
| momentum    |             20 |   2024 |        12 |   0.0371312  |   0.916667 |         0.0190034   |
| momentum    |             20 |   2025 |        10 |   0.0321323  |   0.7      |         0.0222028   |
| momentum    |             20 |   2026 |         7 |  -0.00754144 |   0.571429 |        -0.00433911  |
| momentum    |             60 |   2023 |        12 |   0.0754299  |   0.666667 |        -0.0119758   |
| momentum    |             60 |   2024 |        12 |   0.0669107  |   0.833333 |         0.0292504   |
| momentum    |             60 |   2025 |        10 |   0.10397    |   0.8      |         0.0822285   |
| momentum    |             60 |   2026 |         5 |   0.0279766  |   0.4      |        -0.0233256   |
| momentum    |            120 |   2023 |        12 |   0.179119   |   1        |         0.0129456   |
| momentum    |            120 |   2024 |        12 |   0.108643   |   0.916667 |         0.0345249   |
| momentum    |            120 |   2025 |        10 |   0.280886   |   1        |         0.183604    |
| momentum    |            120 |   2026 |         2 |   0.185704   |   1        |         0.0421269   |

### Per-regime breakdown (best candidate)
| list_type   |   horizon_days | regime   |   n_dates |   avg_return |   win_rate |   avg_excess_vs_qqq |
|:------------|---------------:|:---------|----------:|-------------:|-----------:|--------------------:|
| low_value   |             20 | down     |         8 |  -0.0216799  |   0.25     |        -0.0248546   |
| low_value   |             20 | up       |        33 |   0.0131945  |   0.606061 |        -0.00266946  |
| low_value   |             60 | down     |         7 |   0.0760632  |   0.714286 |        -0.0418589   |
| low_value   |             60 | up       |        32 |   0.0299736  |   0.59375  |        -0.005941    |
| low_value   |            120 | down     |         7 |   0.133555   |   0.857143 |        -0.0114039   |
| low_value   |            120 | up       |        30 |   0.0727838  |   0.8      |        -0.0135255   |
| momentum    |             20 | down     |         8 |   0.00384737 |   0.5      |         0.000672665 |
| momentum    |             20 | up       |        33 |   0.0261645  |   0.757576 |         0.0103005   |
| momentum    |             60 | down     |         7 |   0.113282   |   1        |        -0.00463986  |
| momentum    |             60 | up       |        32 |   0.0654593  |   0.65625  |         0.0295448   |
| momentum    |            120 | down     |         7 |   0.181674   |   1        |         0.036715    |
| momentum    |            120 | up       |        29 |   0.184886   |   0.965517 |         0.0769977   |

### Baseline per-year breakdown (current config)
| list_type   |   horizon_days |   year |   n_dates |   avg_return |   win_rate |   avg_excess_vs_qqq |
|:------------|---------------:|-------:|----------:|-------------:|-----------:|--------------------:|
| low_value   |             20 |   2023 |        12 |   0.00978126 |   0.416667 |        -0.0114268   |
| low_value   |             20 |   2024 |        12 |   0.0135597  |   0.666667 |        -0.00456812  |
| low_value   |             20 |   2025 |        10 |   0.00928423 |   0.7      |        -0.000645247 |
| low_value   |             20 |   2026 |         7 |  -0.0158506  |   0.285714 |        -0.0126483   |
| low_value   |             60 |   2023 |        12 |   0.0465558  |   0.666667 |        -0.04085     |
| low_value   |             60 |   2024 |        12 |   0.0286813  |   0.583333 |        -0.00897894  |
| low_value   |             60 |   2025 |        10 |   0.0322081  |   0.6      |         0.0104662   |
| low_value   |             60 |   2026 |         5 |   0.0533342  |   0.6      |         0.00203206  |
| low_value   |            120 |   2023 |        12 |   0.116705   |   0.916667 |        -0.0494684   |
| low_value   |            120 |   2024 |        12 |   0.0644104  |   0.75     |        -0.00970742  |
| low_value   |            120 |   2025 |        10 |   0.127635   |   0.8      |         0.0303526   |
| low_value   |            120 |   2026 |         3 |  -0.110443   |   0.666667 |        -0.0327417   |
| momentum    |             20 |   2023 |        12 |   0.0150084  |   0.583333 |        -0.00619963  |
| momentum    |             20 |   2024 |        12 |   0.0371312  |   0.916667 |         0.0190034   |
| momentum    |             20 |   2025 |        10 |   0.0321323  |   0.7      |         0.0222028   |
| momentum    |             20 |   2026 |         7 |  -0.00754144 |   0.571429 |        -0.00433911  |
| momentum    |             60 |   2023 |        12 |   0.0754299  |   0.666667 |        -0.0119758   |
| momentum    |             60 |   2024 |        12 |   0.0669107  |   0.833333 |         0.0292504   |
| momentum    |             60 |   2025 |        10 |   0.10397    |   0.8      |         0.0822285   |
| momentum    |             60 |   2026 |         5 |   0.0279766  |   0.4      |        -0.0233256   |
| momentum    |            120 |   2023 |        12 |   0.179119   |   1        |         0.0129456   |
| momentum    |            120 |   2024 |        12 |   0.108643   |   0.916667 |         0.0345249   |
| momentum    |            120 |   2025 |        10 |   0.280886   |   1        |         0.183604    |
| momentum    |            120 |   2026 |         2 |   0.185704   |   1        |         0.0421269   |

### Baseline per-regime breakdown (current config)
| list_type   |   horizon_days | regime   |   n_dates |   avg_return |   win_rate |   avg_excess_vs_qqq |
|:------------|---------------:|:---------|----------:|-------------:|-----------:|--------------------:|
| low_value   |             20 | down     |         8 |  -0.0216799  |   0.25     |        -0.0248546   |
| low_value   |             20 | up       |        33 |   0.0131945  |   0.606061 |        -0.00266946  |
| low_value   |             60 | down     |         7 |   0.0760632  |   0.714286 |        -0.0418589   |
| low_value   |             60 | up       |        32 |   0.0299736  |   0.59375  |        -0.005941    |
| low_value   |            120 | down     |         7 |   0.133555   |   0.857143 |        -0.0114039   |
| low_value   |            120 | up       |        30 |   0.0727838  |   0.8      |        -0.0135255   |
| momentum    |             20 | down     |         8 |   0.00384737 |   0.5      |         0.000672665 |
| momentum    |             20 | up       |        33 |   0.0261645  |   0.757576 |         0.0103005   |
| momentum    |             60 | down     |         7 |   0.113282   |   1        |        -0.00463986  |
| momentum    |             60 | up       |        32 |   0.0654593  |   0.65625  |         0.0295448   |
| momentum    |            120 | down     |         7 |   0.181674   |   1        |         0.036715    |
| momentum    |            120 | up       |        29 |   0.184886   |   0.965517 |         0.0769977   |