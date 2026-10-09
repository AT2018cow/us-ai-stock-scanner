# Backtest Report

- generated UTC: 2026-10-08T21:15:49.948210+00:00
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

- base | industry_trend | H=20 | n=41/45 | avg=0.0193 | win=68.29% | excess_vs_QQQ=0.0059 | no_signal=3 | unpriced=1
- base | industry_trend | H=60 | n=39/45 | avg=0.0711 | win=74.36% | excess_vs_QQQ=0.0204 | no_signal=3 | unpriced=3
- base | industry_trend | H=120 | n=36/45 | avg=0.1765 | win=97.22% | excess_vs_QQQ=0.0614 | no_signal=3 | unpriced=6
- base | low_value | H=20 | n=41/45 | avg=0.0070 | win=53.66% | excess_vs_QQQ=-0.0064 | no_signal=3 | unpriced=1
- base | low_value | H=60 | n=39/45 | avg=0.0387 | win=61.54% | excess_vs_QQQ=-0.0119 | no_signal=3 | unpriced=3
- base | low_value | H=120 | n=36/45 | avg=0.1023 | win=83.33% | excess_vs_QQQ=-0.0128 | no_signal=3 | unpriced=6
- base | momentum | H=20 | n=41/45 | avg=0.0218 | win=70.73% | excess_vs_QQQ=0.0084 | no_signal=3 | unpriced=1
- base | momentum | H=60 | n=39/45 | avg=0.0740 | win=71.79% | excess_vs_QQQ=0.0234 | no_signal=3 | unpriced=3
- base | momentum | H=120 | n=36/45 | avg=0.1843 | win=97.22% | excess_vs_QQQ=0.0692 | no_signal=3 | unpriced=6
- base | research_pool | H=20 | n=44/45 | avg=0.0162 | win=63.64% | excess_vs_QQQ=-0.0014 | no_signal=0 | unpriced=1
- base | research_pool | H=60 | n=42/45 | avg=0.0726 | win=78.57% | excess_vs_QQQ=0.0125 | no_signal=0 | unpriced=3
- base | research_pool | H=120 | n=39/45 | avg=0.1546 | win=97.44% | excess_vs_QQQ=0.0271 | no_signal=0 | unpriced=6

## Segments

- base | 2023 | industry_trend | H=20 | n=12/12 | avg=0.0169 | win=66.67% | excess_vs_QQQ=-0.0043 | no_signal=0 | unpriced=0
- base | 2023 | industry_trend | H=60 | n=12/12 | avg=0.0742 | win=75.00% | excess_vs_QQQ=-0.0132 | no_signal=0 | unpriced=0
- base | 2023 | industry_trend | H=120 | n=12/12 | avg=0.1790 | win=100.00% | excess_vs_QQQ=0.0128 | no_signal=0 | unpriced=0
- base | 2023 | low_value | H=20 | n=12/12 | avg=0.0098 | win=41.67% | excess_vs_QQQ=-0.0114 | no_signal=0 | unpriced=0
- base | 2023 | low_value | H=60 | n=12/12 | avg=0.0466 | win=66.67% | excess_vs_QQQ=-0.0408 | no_signal=0 | unpriced=0
- base | 2023 | low_value | H=120 | n=12/12 | avg=0.1166 | win=91.67% | excess_vs_QQQ=-0.0496 | no_signal=0 | unpriced=0
- base | 2023 | momentum | H=20 | n=12/12 | avg=0.0150 | win=58.33% | excess_vs_QQQ=-0.0062 | no_signal=0 | unpriced=0
- base | 2023 | momentum | H=60 | n=12/12 | avg=0.0754 | win=66.67% | excess_vs_QQQ=-0.0120 | no_signal=0 | unpriced=0
- base | 2023 | momentum | H=120 | n=12/12 | avg=0.1791 | win=100.00% | excess_vs_QQQ=0.0129 | no_signal=0 | unpriced=0
- base | 2023 | research_pool | H=20 | n=12/12 | avg=0.0111 | win=50.00% | excess_vs_QQQ=-0.0101 | no_signal=0 | unpriced=0
- base | 2023 | research_pool | H=60 | n=12/12 | avg=0.0733 | win=58.33% | excess_vs_QQQ=-0.0142 | no_signal=0 | unpriced=0
- base | 2023 | research_pool | H=120 | n=12/12 | avg=0.1701 | win=100.00% | excess_vs_QQQ=0.0040 | no_signal=0 | unpriced=0
- base | 2024 | industry_trend | H=20 | n=12/12 | avg=0.0284 | win=75.00% | excess_vs_QQQ=0.0103 | no_signal=0 | unpriced=0
- base | 2024 | industry_trend | H=60 | n=12/12 | avg=0.0603 | win=83.33% | excess_vs_QQQ=0.0226 | no_signal=0 | unpriced=0
- base | 2024 | industry_trend | H=120 | n=12/12 | avg=0.1129 | win=91.67% | excess_vs_QQQ=0.0387 | no_signal=0 | unpriced=0
- base | 2024 | low_value | H=20 | n=12/12 | avg=0.0140 | win=66.67% | excess_vs_QQQ=-0.0042 | no_signal=0 | unpriced=0
- base | 2024 | low_value | H=60 | n=12/12 | avg=0.0288 | win=58.33% | excess_vs_QQQ=-0.0088 | no_signal=0 | unpriced=0
- base | 2024 | low_value | H=120 | n=12/12 | avg=0.0633 | win=75.00% | excess_vs_QQQ=-0.0109 | no_signal=0 | unpriced=0
- base | 2024 | momentum | H=20 | n=12/12 | avg=0.0371 | win=91.67% | excess_vs_QQQ=0.0190 | no_signal=0 | unpriced=0
- base | 2024 | momentum | H=60 | n=12/12 | avg=0.0669 | win=83.33% | excess_vs_QQQ=0.0293 | no_signal=0 | unpriced=0
- base | 2024 | momentum | H=120 | n=12/12 | avg=0.1086 | win=91.67% | excess_vs_QQQ=0.0345 | no_signal=0 | unpriced=0
- base | 2024 | research_pool | H=20 | n=12/12 | avg=0.0264 | win=75.00% | excess_vs_QQQ=0.0083 | no_signal=0 | unpriced=0
- base | 2024 | research_pool | H=60 | n=12/12 | avg=0.0640 | win=83.33% | excess_vs_QQQ=0.0263 | no_signal=0 | unpriced=0
- base | 2024 | research_pool | H=120 | n=12/12 | avg=0.1189 | win=91.67% | excess_vs_QQQ=0.0448 | no_signal=0 | unpriced=0
- base | 2025 | industry_trend | H=20 | n=10/12 | avg=0.0261 | win=70.00% | excess_vs_QQQ=0.0162 | no_signal=2 | unpriced=0
- base | 2025 | industry_trend | H=60 | n=10/12 | avg=0.0903 | win=80.00% | excess_vs_QQQ=0.0686 | no_signal=2 | unpriced=0
- base | 2025 | industry_trend | H=120 | n=10/12 | avg=0.2391 | win=100.00% | excess_vs_QQQ=0.1418 | no_signal=2 | unpriced=0
- base | 2025 | low_value | H=20 | n=10/12 | avg=0.0093 | win=70.00% | excess_vs_QQQ=-0.0006 | no_signal=2 | unpriced=0
- base | 2025 | low_value | H=60 | n=10/12 | avg=0.0329 | win=60.00% | excess_vs_QQQ=0.0111 | no_signal=2 | unpriced=0
- base | 2025 | low_value | H=120 | n=10/12 | avg=0.1305 | win=80.00% | excess_vs_QQQ=0.0332 | no_signal=2 | unpriced=0
- base | 2025 | momentum | H=20 | n=10/12 | avg=0.0321 | win=70.00% | excess_vs_QQQ=0.0222 | no_signal=2 | unpriced=0
- base | 2025 | momentum | H=60 | n=10/12 | avg=0.1040 | win=80.00% | excess_vs_QQQ=0.0822 | no_signal=2 | unpriced=0
- base | 2025 | momentum | H=120 | n=10/12 | avg=0.2809 | win=100.00% | excess_vs_QQQ=0.1836 | no_signal=2 | unpriced=0
- base | 2025 | research_pool | H=20 | n=12/12 | avg=0.0191 | win=75.00% | excess_vs_QQQ=0.0036 | no_signal=0 | unpriced=0
- base | 2025 | research_pool | H=60 | n=12/12 | avg=0.0763 | win=83.33% | excess_vs_QQQ=0.0300 | no_signal=0 | unpriced=0
- base | 2025 | research_pool | H=120 | n=12/12 | avg=0.1722 | win=100.00% | excess_vs_QQQ=0.0456 | no_signal=0 | unpriced=0
- base | 2026YTD | industry_trend | H=20 | n=7/9 | avg=-0.0017 | win=57.14% | excess_vs_QQQ=0.0015 | no_signal=1 | unpriced=1
- base | 2026YTD | industry_trend | H=60 | n=5/9 | avg=0.0507 | win=40.00% | excess_vs_QQQ=-0.0006 | no_signal=1 | unpriced=3
- base | 2026YTD | industry_trend | H=120 | n=2/9 | avg=0.2306 | win=100.00% | excess_vs_QQQ=0.0870 | no_signal=1 | unpriced=6
- base | 2026YTD | low_value | H=20 | n=7/9 | avg=-0.0133 | win=28.57% | excess_vs_QQQ=-0.0101 | no_signal=1 | unpriced=1
- base | 2026YTD | low_value | H=60 | n=5/9 | avg=0.0550 | win=60.00% | excess_vs_QQQ=0.0037 | no_signal=1 | unpriced=3
- base | 2026YTD | low_value | H=120 | n=2/9 | avg=0.1108 | win=100.00% | excess_vs_QQQ=-0.0327 | no_signal=1 | unpriced=6
- base | 2026YTD | momentum | H=20 | n=7/9 | avg=-0.0075 | win=57.14% | excess_vs_QQQ=-0.0043 | no_signal=1 | unpriced=1
- base | 2026YTD | momentum | H=60 | n=5/9 | avg=0.0280 | win=40.00% | excess_vs_QQQ=-0.0233 | no_signal=1 | unpriced=3
- base | 2026YTD | momentum | H=120 | n=2/9 | avg=0.1857 | win=100.00% | excess_vs_QQQ=0.0421 | no_signal=1 | unpriced=6
- base | 2026YTD | research_pool | H=20 | n=8/9 | avg=0.0039 | win=50.00% | excess_vs_QQQ=-0.0102 | no_signal=0 | unpriced=1
- base | 2026YTD | research_pool | H=60 | n=6/9 | avg=0.0810 | win=100.00% | excess_vs_QQQ=0.0032 | no_signal=0 | unpriced=3
- base | 2026YTD | research_pool | H=120 | n=3/9 | avg=0.1652 | win=100.00% | excess_vs_QQQ=-0.0246 | no_signal=0 | unpriced=6

## Signal Diagnostics

- base | industry_trend | ai_enabler | avg_selected=9.33 | avg_ranked=78.80 | common_first_fail=min_dollar_volume
- base | industry_trend | ai_peripheral | avg_selected=9.33 | avg_ranked=64.62 | common_first_fail=min_dollar_volume
- base | industry_trend | core_ai | avg_selected=9.33 | avg_ranked=24.53 | common_first_fail=min_dollar_volume
- base | low_value | ai_enabler | avg_selected=9.33 | avg_ranked=15.27 | common_first_fail=min_dollar_volume
- base | low_value | ai_peripheral | avg_selected=8.53 | avg_ranked=9.91 | common_first_fail=min_dollar_volume
- base | low_value | core_ai | avg_selected=7.11 | avg_ranked=7.49 | common_first_fail=min_dollar_volume
- base | momentum | ai_enabler | avg_selected=9.33 | avg_ranked=78.80 | common_first_fail=min_dollar_volume
- base | momentum | ai_peripheral | avg_selected=9.33 | avg_ranked=64.62 | common_first_fail=min_dollar_volume
- base | momentum | core_ai | avg_selected=9.33 | avg_ranked=24.53 | common_first_fail=min_dollar_volume
- base | research_pool | ai_enabler | avg_selected=10.00 | avg_ranked=62.47 | common_first_fail=
- base | research_pool | ai_peripheral | avg_selected=10.00 | avg_ranked=40.56 | common_first_fail=
- base | research_pool | core_ai | avg_selected=10.00 | avg_ranked=40.22 | common_first_fail=

## Artifacts

- events: /root/research/post_pr23_baseline_202610/replay/risk_off/post_pr23_baseline_202610_risk_off_events.csv
- summary: /root/research/post_pr23_baseline_202610/replay/risk_off/post_pr23_baseline_202610_risk_off_summary.csv
- benchmarks: /root/research/post_pr23_baseline_202610/replay/risk_off/post_pr23_baseline_202610_risk_off_benchmarks.csv
- segment summary: /root/research/post_pr23_baseline_202610/replay/risk_off/post_pr23_baseline_202610_risk_off_segments.csv
- signal diagnostics: /root/research/post_pr23_baseline_202610/replay/risk_off/post_pr23_baseline_202610_risk_off_events_signal_diagnostics.csv
- signal channel summary: /root/research/post_pr23_baseline_202610/replay/risk_off/post_pr23_baseline_202610_risk_off_events_signal_channel_summary.csv

## Notes

- `historical_replay` remains an approximation; survivorship bias is reduced but not fully eliminated.
- Default theme source is `rules_proxy` (metadata keyword scoring), stable and reproducible.
- `theme_source=latest_scan` and `theme_source=historical_news` are optional comparison modes.
- This is useful for relative validation before long live accumulation, not a perfect PIT backtest.

