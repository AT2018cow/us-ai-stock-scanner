# Stage 1 portfolio viability / list-triage decision

Date: 2026-10-10  
Base main: `5ea55046c35324af11daa1cc6407a860ba984116`

This bundle is a **retrospective screening layer over existing canonical evidence**. It is not account NAV, not a new replay, and not fresh OOS evidence. No production parameter, scanner rule, position gate, or tuner setting is changed.

## Method

The screen compares `momentum`, `industry_trend`, and one deliberately simple combination. The combination return is a 50/50 average of the two same-date list-level returns after the canonical replay's existing transaction-cost treatment. This is only a sleeve proxy; it does not model account cash, duplicate-symbol weights, overlapping holding periods, or realized turnover.

Selected-set turnover is reported as `1 - Jaccard` between consecutive monthly selected-symbol sets. Concentration is checked at the date/year, selected-symbol-frequency, channel-slot, and (where canonical attribution exists) return-contribution levels.

## 120d viability

| style | candidate | avg excess vs QQQ | down-regime excess | worst-date excess | turnover proxy | avg names | 2025 share of total excess | avg excess excluding 2025 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| risk_off | momentum | +6.92% | +3.67% | -5.38% | 70.99% | 18.5 | 73.74% | +2.51% |
| risk_off | industry_trend | +6.14% | +5.44% | -3.45% | 60.57% | 19.1 | 64.15% | +3.05% |
| risk_off | 50/50 proxy | +6.53% | +4.55% | -3.14% | 62.78% | 22.8 | 69.23% | +2.78% |
| risk_on | momentum | +6.75% | +4.15% | -5.06% | 75.13% | 18.6 | 71.06% | +2.70% |
| risk_on | industry_trend | +6.42% | +5.30% | -2.84% | 61.70% | 19.0 | 60.51% | +3.51% |
| risk_on | 50/50 proxy | +6.59% | +4.73% | -2.84% | 64.92% | 23.0 | 65.91% | +3.11% |

The 120d signal is the stable part of the screen: all 2023/2024/2025 full-year 120d excess cells are positive for both source lists and the proxy, and both regimes are positive. The magnitude is 2025-heavy, but it is not solely a 2025 artifact: removing the top year leaves roughly +2.5% to +3.5% average excess. A single date is also not carrying the result: the best date contributes about 10.8%–13.3% of total 120d excess, while every leave-one-date-out 120d average remains positive.

The 20d/60d files are intentionally retained rather than hidden. They contain materially weaker cells, including negative years/regimes, so this PR does **not** claim horizon-universal alpha.

## Diversification, overlap, concentration

Momentum and industry_trend overlap substantially but not completely. Mean selected-set Jaccard is 67.7% risk_off and 66.5% risk_on. Adding industry_trend expands the average union to about 23 names and contributes about 4.3–4.4 names per date that momentum did not select.

That diversification is modest rather than transformational: 120d component excess correlation is 0.927 risk_off and 0.878 risk_on. Even so, the 50/50 proxy cuts 120d date-level excess dispersion to about 86.5% of momentum's while improving the worst observed date and lowering the selected-set turnover proxy.

Pre-dedup channel slots are exactly balanced across `core_ai`, `ai_enabler`, and `ai_peripheral` (420 each, max channel share 33.3%) for both lists/styles. This is a selection-slot diagnostic, not an account-capital statement.

For momentum, existing canonical return-contribution attribution shows the 120d top symbol contributes 9.35% risk_off / 9.39% risk_on and top three contribute 24.3% / 26.5%; aggregate return remains positive after removing the top symbol. The compact canonical attribution does not contain equivalent `industry_trend` symbol-return rows. This PR therefore reports exact selected-symbol frequency concentration for industry/combo and **does not invent** missing return-contribution figures. Exact per-symbol/list contribution becomes a required Stage 2 NAV output.

## Style split

A separate risk_on/risk_off portfolio candidate is rejected. At 120d, risk_on vs risk_off selection Jaccard is 82.6% for momentum and 91.2% for industry_trend; excess-return correlations are 0.944 and 0.972. Average risk_on-minus-risk_off excess is only -0.17pp for momentum and +0.28pp for industry_trend. That is not enough incremental diversification to justify another allocation degree of freedom.

## Decision

Advance exactly **two frozen candidates** to the account-NAV simulator:

1. **Momentum-only** — primary minimal candidate. It has the strongest raw 120d excess in the risk_off reference and already has explicit return-contribution concentration evidence. Its main liability is high turnover proxy, which Stage 2 must price correctly.
2. **Momentum + industry_trend, equal sleeves with account-level symbol deduplication** — secondary candidate. The screening proxy preserves most of momentum's 120d excess while improving dispersion, worst-date behavior, breadth, and turnover proxy. Do not optimize the sleeve weight in Stage 1.

Do not advance `industry_trend` as a third standalone candidate. It is viable and is the useful diversifier in candidate 2, but a third candidate adds decision complexity without enough new information. Do not start style-allocation tuning.

## Next gate

Stage 2 should now implement the canonical account-NAV simulator only: monthly rebalance, next-open execution, equal weights, explicit cash, production caps, symbol deduplication, fixed source-compatible costs, no leverage/shorting, QQQ benchmark, and audit outputs for NAV, trades, holdings, realized turnover, costs, drawdown, and per-symbol/list contribution. Compare only the two frozen candidates before any sizing optimization.

After that: fixed-candidate robustness, then prospective paper/shadow, then a staged live pilot with explicit kill switches. `low_value` ranking / research-gate interaction remains parallel alpha R&D and must not block this path.
