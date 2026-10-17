# Drawdown Protection & Bear-Market Replay Evaluation

Route A: forward-drawdown attribution on the frozen 39-date dataset (production `build_stock_decisions` v1/v2 rebuild per date, FULL vs ETF_SLICE scope). Route B: 2022 bear-market replay when provided.

## Provenance

- Base dataset: `company_quality_dataset_risk_off.v3.csv` (25025 rows, 39 signal dates).
- 2022 bear market dataset: `company_quality_dataset_risk_off.repaired.csv` (8251 rows, 12 signal dates).
- Securities addressed by CIK/ticker rename hygiene at refresh time; universe snapshots are the documented `union_superset_approx` approximation (AGENTS.md §4): the current watchlist applied to all historical dates, not true PIT ETF-constituent history; the ETF-slice (etf_count>=1) cut is the bias-reduced read.
- Retrospective replay only; no threshold/weight/policy promotion implied (AGENTS.md §8).

## 1. E0 baseline reproduction check

Status: **PASS** (15 cohort rows checked vs `e0_current_cohorts.csv` v1_current, tolerance 1e-05).

## 2. Trailing regime vs forward-drawdown protection

`regime == "down"` is a trailing indicator (benchmark trailing 60d return on the signal date). In the 2023-2026 bull market most trailing dips were followed by V-shaped rebounds; the forward lens `qqq_return_60 < 0` isolates dates whose NEXT 60 trading days were actual market drawdowns.

- FWD_DRAWDOWN_60D: 8 dates, next-60d QQQ range -10.3%..-0.9%.
- TRAILING_DOWN: 10 dates, next-60d QQQ range +1.6%..+21.6% (post-dip rebound measure).

## 3. Rank tiers: FWD_BULL_60D vs FWD_DRAWDOWN_60D (v2_current)

| scope | segment | tier | n | mean_ex60 | diff_vs_univ | win_rate | raw_ret60 | severe_loss60 |
|---|---|---|---|---|---|---|---|---|
| FULL | FWD_BULL_60D | 1-5 | 31 | -0.027565 | -0.033417 | 0.225806 | 0.067720 | 0.025806 |
| FULL | FWD_BULL_60D | 6-15 | 31 | -0.034400 | -0.040252 | 0.258065 | 0.060885 | 0.035484 |
| FULL | FWD_BULL_60D | 16-30 | 31 | -0.052759 | -0.058611 | 0.193548 | 0.042526 | 0.049462 |
| FULL | FWD_BULL_60D | 31-50 | 31 | -0.007625 | -0.013478 | 0.483871 | 0.087659 | 0.027419 |
| FULL | FWD_BULL_60D | 51-100 | 31 | -0.005939 | -0.011791 | 0.548387 | 0.089346 | 0.046452 |
| FULL | FWD_BULL_60D | 101+ | 31 | 0.010098 | 0.004246 | 0.580645 | 0.105383 | 0.088360 |
| FULL | FWD_BULL_60D | universe | 31 | 0.005852 | 0.000000 | 0.612903 | 0.101137 | 0.080912 |
| FULL | FWD_DRAWDOWN_60D | 1-5 | 8 | 0.002005 | 0.003455 | 0.500000 | -0.049393 | 0.200000 |
| FULL | FWD_DRAWDOWN_60D | 6-15 | 8 | -0.019687 | -0.018238 | 0.250000 | -0.071085 | 0.175000 |
| FULL | FWD_DRAWDOWN_60D | 16-30 | 8 | 0.015707 | 0.017157 | 0.625000 | -0.035691 | 0.141667 |
| FULL | FWD_DRAWDOWN_60D | 31-50 | 8 | 0.030838 | 0.032288 | 0.375000 | -0.020560 | 0.162500 |
| FULL | FWD_DRAWDOWN_60D | 51-100 | 8 | 0.041676 | 0.043125 | 0.500000 | -0.009722 | 0.162500 |
| FULL | FWD_DRAWDOWN_60D | 101+ | 8 | -0.006692 | -0.005243 | 0.375000 | -0.058090 | 0.257463 |
| FULL | FWD_DRAWDOWN_60D | universe | 8 | -0.001449 | 0.000000 | 0.375000 | -0.052848 | 0.242702 |
| ETF_SLICE | FWD_BULL_60D | 1-5 | 31 | -0.028208 | -0.023617 | 0.290323 | 0.067077 | 0.025806 |
| ETF_SLICE | FWD_BULL_60D | 6-15 | 31 | -0.034678 | -0.030087 | 0.354839 | 0.060607 | 0.022581 |
| ETF_SLICE | FWD_BULL_60D | 16-30 | 31 | -0.032409 | -0.027818 | 0.354839 | 0.062876 | 0.034409 |
| ETF_SLICE | FWD_BULL_60D | 31-50 | 31 | -0.006377 | -0.001786 | 0.387097 | 0.088908 | 0.029032 |
| ETF_SLICE | FWD_BULL_60D | 51-100 | 31 | -0.007020 | -0.002429 | 0.419355 | 0.088265 | 0.031613 |
| ETF_SLICE | FWD_BULL_60D | 101+ | 31 | -0.001364 | 0.003227 | 0.483871 | 0.093921 | 0.061259 |
| ETF_SLICE | FWD_BULL_60D | universe | 31 | -0.004591 | 0.000000 | 0.516129 | 0.090694 | 0.053616 |
| ETF_SLICE | FWD_DRAWDOWN_60D | 1-5 | 8 | 0.012758 | -0.007276 | 0.500000 | -0.038640 | 0.175000 |
| ETF_SLICE | FWD_DRAWDOWN_60D | 6-15 | 8 | 0.015918 | -0.004116 | 0.625000 | -0.035480 | 0.150000 |
| ETF_SLICE | FWD_DRAWDOWN_60D | 16-30 | 8 | 0.027649 | 0.007615 | 0.625000 | -0.023749 | 0.075000 |
| ETF_SLICE | FWD_DRAWDOWN_60D | 31-50 | 8 | 0.070900 | 0.050865 | 0.625000 | 0.019502 | 0.125000 |
| ETF_SLICE | FWD_DRAWDOWN_60D | 51-100 | 8 | 0.024967 | 0.004933 | 0.625000 | -0.026431 | 0.142500 |
| ETF_SLICE | FWD_DRAWDOWN_60D | 101+ | 8 | 0.015861 | -0.004174 | 0.500000 | -0.035538 | 0.193534 |
| ETF_SLICE | FWD_DRAWDOWN_60D | universe | 8 | 0.020035 | 0.000000 | 0.500000 | -0.031364 | 0.178234 |

## 4. Cohorts & severe-loss rates (v2_current)

| scope | segment | cohort | n | mean_ex60 | median_ex60 | severe_loss60 | severe_under60 |
|---|---|---|---|---|---|---|---|
| FULL | FWD_BULL_60D | TOP15 | 31 | -0.032122 | -0.031605 | 0.032258 | 0.133333 |
| FULL | FWD_BULL_60D | PRIORITY_REVIEW | 31 | -0.041534 | -0.034248 | 0.033962 | 0.143790 |
| FULL | FWD_DRAWDOWN_60D | TOP15 | 8 | -0.012456 | -0.010033 | 0.183333 | 0.083333 |
| FULL | FWD_DRAWDOWN_60D | PRIORITY_REVIEW | 8 | 0.022322 | 0.013245 | 0.132712 | 0.064565 |
| FULL | TRAILING_DOWN | TOP15 | 10 | -0.063720 | -0.041623 | 0.060000 | 0.226667 |
| FULL | TRAILING_DOWN | PRIORITY_REVIEW | 10 | -0.076047 | -0.073482 | 0.044640 | 0.231014 |
| FULL | BASE_ALL_39 | TOP15 | 39 | -0.028088 | -0.031562 | 0.063248 | 0.123077 |
| FULL | BASE_ALL_39 | PRIORITY_REVIEW | 39 | -0.028435 | -0.023587 | 0.054219 | 0.127538 |
| ETF_SLICE | FWD_BULL_60D | TOP15 | 31 | -0.032521 | -0.031961 | 0.023656 | 0.122581 |
| ETF_SLICE | FWD_BULL_60D | PRIORITY_REVIEW | 31 | -0.041655 | -0.036728 | 0.026445 | 0.133204 |
| ETF_SLICE | FWD_DRAWDOWN_60D | TOP15 | 8 | 0.014865 | 0.008326 | 0.158333 | 0.058333 |
| ETF_SLICE | FWD_DRAWDOWN_60D | PRIORITY_REVIEW | 8 | 0.032298 | 0.022348 | 0.118842 | 0.053462 |
| ETF_SLICE | TRAILING_DOWN | TOP15 | 10 | -0.069524 | -0.057214 | 0.046667 | 0.220000 |
| ETF_SLICE | TRAILING_DOWN | PRIORITY_REVIEW | 10 | -0.080895 | -0.081695 | 0.034012 | 0.223706 |
| ETF_SLICE | BASE_ALL_39 | TOP15 | 39 | -0.022801 | -0.027022 | 0.051282 | 0.109402 |
| ETF_SLICE | BASE_ALL_39 | PRIORITY_REVIEW | 39 | -0.026485 | -0.020585 | 0.045398 | 0.116846 |

## 5. Entry state / SMA200 extension / grade crosscuts (v2_current, FWD_DRAWDOWN_60D)

| scope | cut | bucket | n | mean_ex60 | severe_loss60 |
|---|---|---|---|---|---|
| FULL | entry_state | ENTRY_READY|all_grades | 8 | 0.019559 | 0.176820 |
| FULL | entry_state | WATCH_PULLBACK|all_grades | 8 | 0.012163 | 0.303167 |
| FULL | entry_state | WATCH_BREAKOUT|all_grades | 8 | 0.022096 | 0.178569 |
| FULL | entry_state | TREND_DAMAGED|all_grades | 8 | -0.028213 | 0.276874 |
| FULL | entry_state | INSUFFICIENT_DATA|all_grades | 8 | -0.035249 | 0.339115 |
| FULL | entry_state | ENTRY_READY|grade_A_only | 8 | 0.022058 | 0.135434 |
| FULL | entry_state | WATCH_PULLBACK|grade_A_only | 8 | 0.026900 | 0.228987 |
| FULL | entry_state | WATCH_BREAKOUT|grade_A_only | 8 | 0.018270 | 0.133976 |
| FULL | entry_state | TREND_DAMAGED|grade_A_only | 8 | -0.011992 | 0.202153 |
| FULL | entry_state | INSUFFICIENT_DATA|grade_A_only | 5 | -0.009077 | 0.155263 |
| FULL | sma200_extension | <1.00x|all_grades | 8 | -0.029507 | 0.273309 |
| FULL | sma200_extension | 1.00-1.25x|all_grades | 8 | 0.019990 | 0.172781 |
| FULL | sma200_extension | 1.25-1.35x|all_grades | 8 | 0.004665 | 0.261006 |
| FULL | sma200_extension | 1.35-1.45x|all_grades | 8 | -0.023120 | 0.333514 |
| FULL | sma200_extension | >1.45x|all_grades | 8 | 0.046743 | 0.348830 |
| FULL | sma200_extension | <1.00x|grade_A_only | 8 | -0.015012 | 0.208753 |
| FULL | sma200_extension | 1.00-1.25x|grade_A_only | 8 | 0.014332 | 0.138113 |
| FULL | sma200_extension | 1.25-1.35x|grade_A_only | 8 | 0.013661 | 0.189635 |
| FULL | sma200_extension | 1.35-1.45x|grade_A_only | 8 | 0.029573 | 0.216444 |
| FULL | sma200_extension | >1.45x|grade_A_only | 8 | 0.093036 | 0.147569 |
| FULL | quality_grade | A | 8 | 0.003658 | 0.183325 |
| FULL | quality_grade | B | 8 | 0.006305 | 0.195950 |
| FULL | quality_grade | C | 8 | -0.022730 | 0.371209 |
| FULL | quality_grade | UNRATED | 8 | 0.025575 | 0.216190 |
| ETF_SLICE | entry_state | ENTRY_READY|all_grades | 8 | 0.026963 | 0.158126 |
| ETF_SLICE | entry_state | WATCH_PULLBACK|all_grades | 8 | 0.022405 | 0.270177 |
| ETF_SLICE | entry_state | WATCH_BREAKOUT|all_grades | 8 | 0.033393 | 0.139372 |
| ETF_SLICE | entry_state | TREND_DAMAGED|all_grades | 8 | -0.000548 | 0.181740 |
| ETF_SLICE | entry_state | INSUFFICIENT_DATA|all_grades | 8 | -0.016249 | 0.300787 |
| ETF_SLICE | entry_state | ENTRY_READY|grade_A_only | 8 | 0.033340 | 0.117948 |
| ETF_SLICE | entry_state | WATCH_PULLBACK|grade_A_only | 8 | 0.039603 | 0.199814 |
| ETF_SLICE | entry_state | WATCH_BREAKOUT|grade_A_only | 8 | 0.020611 | 0.125755 |
| ETF_SLICE | entry_state | TREND_DAMAGED|grade_A_only | 8 | 0.020904 | 0.124674 |
| ETF_SLICE | entry_state | INSUFFICIENT_DATA|grade_A_only | 5 | 0.031399 | 0.044123 |
| ETF_SLICE | sma200_extension | <1.00x|all_grades | 8 | 0.000283 | 0.181662 |
| ETF_SLICE | sma200_extension | 1.00-1.25x|all_grades | 8 | 0.028704 | 0.137315 |
| ETF_SLICE | sma200_extension | 1.25-1.35x|all_grades | 8 | 0.030915 | 0.226484 |
| ETF_SLICE | sma200_extension | 1.35-1.45x|all_grades | 8 | -0.015216 | 0.319563 |
| ETF_SLICE | sma200_extension | >1.45x|all_grades | 8 | 0.058914 | 0.313389 |
| ETF_SLICE | sma200_extension | <1.00x|grade_A_only | 8 | 0.014619 | 0.141056 |
| ETF_SLICE | sma200_extension | 1.00-1.25x|grade_A_only | 8 | 0.021348 | 0.119662 |
| ETF_SLICE | sma200_extension | 1.25-1.35x|grade_A_only | 8 | 0.042433 | 0.134761 |
| ETF_SLICE | sma200_extension | 1.35-1.45x|grade_A_only | 7 | 0.038972 | 0.130556 |
| ETF_SLICE | sma200_extension | >1.45x|grade_A_only | 8 | 0.062984 | 0.250521 |
| ETF_SLICE | quality_grade | A | 8 | 0.021158 | 0.137460 |
| ETF_SLICE | quality_grade | B | 8 | 0.024836 | 0.141995 |
| ETF_SLICE | quality_grade | C | 8 | -0.011292 | 0.318657 |
| ETF_SLICE | quality_grade | UNRATED | 8 | 0.077930 | 0.141774 |

## 6. 2022 tech bear market (BEAR_2022)

| scope | tier | n | mean_ex60 | diff_vs_univ | severe_loss60 |
|---|---|---|---|---|---|
| FULL | 1-5 | 12 | 0.022800 | 0.011659 | 0.116667 |
| FULL | 6-15 | 12 | 0.012970 | 0.001829 | 0.066667 |
| FULL | 16-30 | 12 | 0.023558 | 0.012417 | 0.122222 |
| FULL | 31-50 | 12 | 0.015096 | 0.003955 | 0.112500 |
| FULL | 51-100 | 12 | 0.031953 | 0.020811 | 0.095000 |
| FULL | 101+ | 12 | 0.008773 | -0.002369 | 0.209175 |
| FULL | universe | 12 | 0.011141 | 0.000000 | 0.193395 |
| ETF_SLICE | 1-5 | 12 | 0.003173 | -0.013556 | 0.116667 |
| ETF_SLICE | 6-15 | 12 | 0.029740 | 0.013011 | 0.041667 |
| ETF_SLICE | 16-30 | 12 | 0.028485 | 0.011755 | 0.077778 |
| ETF_SLICE | 31-50 | 12 | 0.027881 | 0.011151 | 0.075000 |
| ETF_SLICE | 51-100 | 12 | 0.028992 | 0.012262 | 0.086667 |
| ETF_SLICE | 101+ | 12 | 0.013298 | -0.003431 | 0.169468 |
| ETF_SLICE | universe | 12 | 0.016730 | 0.000000 | 0.147880 |

## 7. Interpretive guardrails

- Overlapping 60d/120d windows are not independent samples; aggregation is date-equal and the sample is small (39 base dates, 8 forward-drawdown dates).
- `severe_loss_rate_60` = share of cohort members with `fwd_ret_60 <= -20%` (date-equal mean); tail metrics need many more drawdown dates before any promotion-grade conclusion.
- Forward labels beyond the dataset's frozen horizon are matured retrospectively; never call them OOS.
