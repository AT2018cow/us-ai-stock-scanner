# Backtest Report

- generated UTC: 2026-10-08T21:44:58.262332+00:00
- mode: historical_replay
- signal rows: 180
- list types: low_value, industry_trend, momentum, research_pool
- horizons: 20, 60, 120
- top_n: 10
- per_channel_top_n: True
- trading_cost_bps(one-way): 15.0
- entry_price_mode: next_open
- exit_price_mode: close
- rebalance_frequency: monthly
- replay_max_symbols: 800
- replay_asset_status: all
- use_historical_watchlist: True
- watchlist_history_dir: /root/data/watchlist_history
- watchlist_csv_path_override: /root/data/ai_watchlist.csv
- allow_latest_watchlist_fallback: False
- disclosure_lookback_days: 720
- theme_source: rules_proxy
- allow_lookahead_theme_source: False
- delist_return_assumption: -0.55
- delist_detection_buffer_days: 7
- perturbation_enabled: False

## Summary

- base | industry_trend | H=20 | n=41/45 | avg=0.0195 | win=70.73% | excess_vs_QQQ=0.0061 | no_signal=3 | unpriced=1
- base | industry_trend | H=60 | n=39/45 | avg=0.0727 | win=76.92% | excess_vs_QQQ=0.0221 | no_signal=3 | unpriced=3
- base | industry_trend | H=120 | n=36/45 | avg=0.1793 | win=97.22% | excess_vs_QQQ=0.0642 | no_signal=3 | unpriced=6
- base | low_value | H=20 | n=40/45 | avg=0.0199 | win=65.00% | excess_vs_QQQ=0.0052 | no_signal=4 | unpriced=1
- base | low_value | H=60 | n=38/45 | avg=0.0582 | win=71.05% | excess_vs_QQQ=0.0100 | no_signal=4 | unpriced=3
- base | low_value | H=120 | n=35/45 | avg=0.1603 | win=91.43% | excess_vs_QQQ=0.0488 | no_signal=4 | unpriced=6
- base | momentum | H=20 | n=41/45 | avg=0.0220 | win=70.73% | excess_vs_QQQ=0.0086 | no_signal=3 | unpriced=1
- base | momentum | H=60 | n=39/45 | avg=0.0727 | win=71.79% | excess_vs_QQQ=0.0220 | no_signal=3 | unpriced=3
- base | momentum | H=120 | n=36/45 | avg=0.1826 | win=94.44% | excess_vs_QQQ=0.0675 | no_signal=3 | unpriced=6
- base | research_pool | H=20 | n=44/45 | avg=0.0156 | win=61.36% | excess_vs_QQQ=-0.0019 | no_signal=0 | unpriced=1
- base | research_pool | H=60 | n=42/45 | avg=0.0714 | win=78.57% | excess_vs_QQQ=0.0113 | no_signal=0 | unpriced=3
- base | research_pool | H=120 | n=39/45 | avg=0.1525 | win=94.87% | excess_vs_QQQ=0.0250 | no_signal=0 | unpriced=6

## Segments

- base | 2023 | industry_trend | H=20 | n=12/12 | avg=0.0174 | win=75.00% | excess_vs_QQQ=-0.0038 | no_signal=0 | unpriced=0
- base | 2023 | industry_trend | H=60 | n=12/12 | avg=0.0771 | win=75.00% | excess_vs_QQQ=-0.0103 | no_signal=0 | unpriced=0
- base | 2023 | industry_trend | H=120 | n=12/12 | avg=0.1853 | win=100.00% | excess_vs_QQQ=0.0192 | no_signal=0 | unpriced=0
- base | 2023 | low_value | H=20 | n=11/12 | avg=0.0283 | win=63.64% | excess_vs_QQQ=0.0016 | no_signal=1 | unpriced=0
- base | 2023 | low_value | H=60 | n=11/12 | avg=0.0793 | win=63.64% | excess_vs_QQQ=-0.0030 | no_signal=1 | unpriced=0
- base | 2023 | low_value | H=120 | n=11/12 | avg=0.1838 | win=100.00% | excess_vs_QQQ=0.0245 | no_signal=1 | unpriced=0
- base | 2023 | momentum | H=20 | n=12/12 | avg=0.0134 | win=58.33% | excess_vs_QQQ=-0.0078 | no_signal=0 | unpriced=0
- base | 2023 | momentum | H=60 | n=12/12 | avg=0.0693 | win=66.67% | excess_vs_QQQ=-0.0181 | no_signal=0 | unpriced=0
- base | 2023 | momentum | H=120 | n=12/12 | avg=0.1724 | win=100.00% | excess_vs_QQQ=0.0062 | no_signal=0 | unpriced=0
- base | 2023 | research_pool | H=20 | n=12/12 | avg=0.0115 | win=50.00% | excess_vs_QQQ=-0.0097 | no_signal=0 | unpriced=0
- base | 2023 | research_pool | H=60 | n=12/12 | avg=0.0746 | win=58.33% | excess_vs_QQQ=-0.0128 | no_signal=0 | unpriced=0
- base | 2023 | research_pool | H=120 | n=12/12 | avg=0.1731 | win=100.00% | excess_vs_QQQ=0.0070 | no_signal=0 | unpriced=0
- base | 2024 | industry_trend | H=20 | n=12/12 | avg=0.0294 | win=75.00% | excess_vs_QQQ=0.0113 | no_signal=0 | unpriced=0
- base | 2024 | industry_trend | H=60 | n=12/12 | avg=0.0619 | win=83.33% | excess_vs_QQQ=0.0243 | no_signal=0 | unpriced=0
- base | 2024 | industry_trend | H=120 | n=12/12 | avg=0.1196 | win=91.67% | excess_vs_QQQ=0.0455 | no_signal=0 | unpriced=0
- base | 2024 | low_value | H=20 | n=12/12 | avg=0.0201 | win=66.67% | excess_vs_QQQ=0.0020 | no_signal=0 | unpriced=0
- base | 2024 | low_value | H=60 | n=12/12 | avg=0.0240 | win=66.67% | excess_vs_QQQ=-0.0136 | no_signal=0 | unpriced=0
- base | 2024 | low_value | H=120 | n=12/12 | avg=0.0715 | win=75.00% | excess_vs_QQQ=-0.0026 | no_signal=0 | unpriced=0
- base | 2024 | momentum | H=20 | n=12/12 | avg=0.0384 | win=91.67% | excess_vs_QQQ=0.0203 | no_signal=0 | unpriced=0
- base | 2024 | momentum | H=60 | n=12/12 | avg=0.0686 | win=83.33% | excess_vs_QQQ=0.0309 | no_signal=0 | unpriced=0
- base | 2024 | momentum | H=120 | n=12/12 | avg=0.1181 | win=83.33% | excess_vs_QQQ=0.0440 | no_signal=0 | unpriced=0
- base | 2024 | research_pool | H=20 | n=12/12 | avg=0.0249 | win=75.00% | excess_vs_QQQ=0.0068 | no_signal=0 | unpriced=0
- base | 2024 | research_pool | H=60 | n=12/12 | avg=0.0618 | win=83.33% | excess_vs_QQQ=0.0242 | no_signal=0 | unpriced=0
- base | 2024 | research_pool | H=120 | n=12/12 | avg=0.1200 | win=83.33% | excess_vs_QQQ=0.0459 | no_signal=0 | unpriced=0
- base | 2025 | industry_trend | H=20 | n=10/12 | avg=0.0249 | win=70.00% | excess_vs_QQQ=0.0150 | no_signal=2 | unpriced=0
- base | 2025 | industry_trend | H=60 | n=10/12 | avg=0.0909 | win=80.00% | excess_vs_QQQ=0.0692 | no_signal=2 | unpriced=0
- base | 2025 | industry_trend | H=120 | n=10/12 | avg=0.2371 | win=100.00% | excess_vs_QQQ=0.1399 | no_signal=2 | unpriced=0
- base | 2025 | low_value | H=20 | n=10/12 | avg=0.0297 | win=70.00% | excess_vs_QQQ=0.0198 | no_signal=2 | unpriced=0
- base | 2025 | low_value | H=60 | n=10/12 | avg=0.0907 | win=90.00% | excess_vs_QQQ=0.0689 | no_signal=2 | unpriced=0
- base | 2025 | low_value | H=120 | n=10/12 | avg=0.2503 | win=100.00% | excess_vs_QQQ=0.1530 | no_signal=2 | unpriced=0
- base | 2025 | momentum | H=20 | n=10/12 | avg=0.0320 | win=70.00% | excess_vs_QQQ=0.0220 | no_signal=2 | unpriced=0
- base | 2025 | momentum | H=60 | n=10/12 | avg=0.1051 | win=80.00% | excess_vs_QQQ=0.0833 | no_signal=2 | unpriced=0
- base | 2025 | momentum | H=120 | n=10/12 | avg=0.2699 | win=100.00% | excess_vs_QQQ=0.1727 | no_signal=2 | unpriced=0
- base | 2025 | research_pool | H=20 | n=12/12 | avg=0.0184 | win=66.67% | excess_vs_QQQ=0.0029 | no_signal=0 | unpriced=0
- base | 2025 | research_pool | H=60 | n=12/12 | avg=0.0723 | win=83.33% | excess_vs_QQQ=0.0260 | no_signal=0 | unpriced=0
- base | 2025 | research_pool | H=120 | n=12/12 | avg=0.1626 | win=100.00% | excess_vs_QQQ=0.0359 | no_signal=0 | unpriced=0
- base | 2026YTD | industry_trend | H=20 | n=7/9 | avg=-0.0018 | win=57.14% | excess_vs_QQQ=0.0014 | no_signal=1 | unpriced=1
- base | 2026YTD | industry_trend | H=60 | n=5/9 | avg=0.0518 | win=60.00% | excess_vs_QQQ=0.0005 | no_signal=1 | unpriced=3
- base | 2026YTD | industry_trend | H=120 | n=2/9 | avg=0.2120 | win=100.00% | excess_vs_QQQ=0.0684 | no_signal=1 | unpriced=6
- base | 2026YTD | low_value | H=20 | n=7/9 | avg=-0.0077 | win=57.14% | excess_vs_QQQ=-0.0045 | no_signal=1 | unpriced=1
- base | 2026YTD | low_value | H=60 | n=5/9 | avg=0.0290 | win=60.00% | excess_vs_QQQ=-0.0223 | no_signal=1 | unpriced=3
- base | 2026YTD | low_value | H=120 | n=2/9 | avg=0.1142 | win=100.00% | excess_vs_QQQ=-0.0293 | no_signal=1 | unpriced=6
- base | 2026YTD | momentum | H=20 | n=7/9 | avg=-0.0059 | win=57.14% | excess_vs_QQQ=-0.0027 | no_signal=1 | unpriced=1
- base | 2026YTD | momentum | H=60 | n=5/9 | avg=0.0259 | win=40.00% | excess_vs_QQQ=-0.0254 | no_signal=1 | unpriced=3
- base | 2026YTD | momentum | H=120 | n=2/9 | avg=0.1940 | win=100.00% | excess_vs_QQQ=0.0504 | no_signal=1 | unpriced=6
- base | 2026YTD | research_pool | H=20 | n=8/9 | avg=0.0035 | win=50.00% | excess_vs_QQQ=-0.0105 | no_signal=0 | unpriced=1
- base | 2026YTD | research_pool | H=60 | n=6/9 | avg=0.0823 | win=100.00% | excess_vs_QQQ=0.0044 | no_signal=0 | unpriced=3
- base | 2026YTD | research_pool | H=120 | n=3/9 | avg=0.1601 | win=100.00% | excess_vs_QQQ=-0.0297 | no_signal=0 | unpriced=6

## Signal Diagnostics

- base | industry_trend | ai_enabler | avg_selected=9.33 | avg_ranked=78.80 | common_first_fail=min_dollar_volume
- base | industry_trend | ai_peripheral | avg_selected=9.33 | avg_ranked=64.62 | common_first_fail=min_dollar_volume
- base | industry_trend | core_ai | avg_selected=9.33 | avg_ranked=24.53 | common_first_fail=min_dollar_volume
- base | low_value | ai_enabler | avg_selected=8.51 | avg_ranked=13.93 | common_first_fail=min_dollar_volume
- base | low_value | ai_peripheral | avg_selected=6.58 | avg_ranked=8.18 | common_first_fail=min_dollar_volume
- base | low_value | core_ai | avg_selected=6.82 | avg_ranked=7.27 | common_first_fail=min_dollar_volume
- base | momentum | ai_enabler | avg_selected=9.33 | avg_ranked=78.80 | common_first_fail=min_dollar_volume
- base | momentum | ai_peripheral | avg_selected=9.33 | avg_ranked=64.62 | common_first_fail=min_dollar_volume
- base | momentum | core_ai | avg_selected=9.33 | avg_ranked=24.53 | common_first_fail=min_dollar_volume
- base | research_pool | ai_enabler | avg_selected=10.00 | avg_ranked=82.38 | common_first_fail=
- base | research_pool | ai_peripheral | avg_selected=10.00 | avg_ranked=59.89 | common_first_fail=
- base | research_pool | core_ai | avg_selected=10.00 | avg_ranked=50.29 | common_first_fail=

## Artifacts

- events: /root/research/post_pr23_baseline_202610/replay/risk_on/post_pr23_baseline_202610_risk_on_events.csv
- summary: /root/research/post_pr23_baseline_202610/replay/risk_on/post_pr23_baseline_202610_risk_on_summary.csv
- benchmarks: /root/research/post_pr23_baseline_202610/replay/risk_on/post_pr23_baseline_202610_risk_on_benchmarks.csv
- segment summary: /root/research/post_pr23_baseline_202610/replay/risk_on/post_pr23_baseline_202610_risk_on_segments.csv
- signal diagnostics: /root/research/post_pr23_baseline_202610/replay/risk_on/post_pr23_baseline_202610_risk_on_events_signal_diagnostics.csv
- signal channel summary: /root/research/post_pr23_baseline_202610/replay/risk_on/post_pr23_baseline_202610_risk_on_events_signal_channel_summary.csv

## Notes

- `historical_replay` remains an approximation; survivorship bias is reduced but not fully eliminated.
- Default theme source is `rules_proxy` (metadata keyword scoring), stable and reproducible.
- `theme_source=latest_scan` and `theme_source=historical_news` are optional comparison modes.
- This is useful for relative validation before long live accumulation, not a perfect PIT backtest.

