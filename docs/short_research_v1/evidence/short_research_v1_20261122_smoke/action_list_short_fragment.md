<a id="short-research"></a>
## Short Research (2)

- **Status**: `ready` · **Rule**: `short_research_rules_v1` · **Signal date**: 2020-03-31 · **Feed**: sip
- **Independence**: This is a fourth, separate research list. It does not change the long Top-15, Action states, Low-Value, Industry-Trend, Momentum, or Research Pool. It is not a trade instruction.
- **Funnel**: input 564 → U0 436 → industry RS 231 → P/E 154 → U 146 → S0 44 → S1 8 → S2 2 → selected 2
- **Status counts**: CONFIRMED 2 · INSUFFICIENT_DATA 290 · NO_SIGNAL 142 · SCOPE_EXCLUDED 128 · WATCH 2
- **Reason counts**: AVG_DOLLAR_VOLUME_BELOW_MIN 92 · DOLLAR_VOLUME_BELOW_MIN 49 · DUPLICATE_CIK_LOWER_ADV 1 · FUNDAMENTAL_ASOF_INVALID 22 · FUNDAMENTAL_ASOF_MISSING 23 · FUNDAMENTAL_ASOF_STALE 18 · INDUSTRY_PEERS_INSUFFICIENT 205 · INDUSTRY_RS_MISSING 205 · OCF_DIRECTION_INVALID 34 · OCF_GROWTH_MISSING 34 · PE_PEERS_INSUFFICIENT 179 · PE_VALUATION_MISSING 282 · PRICE_BELOW_MIN 39 · PRICE_TO_SMA50_MISSING 2 · RETURN_60D_MISSING 3 · REVENUE_MISSING 38 · REVENUE_NONPOSITIVE 1 · REVENUE_YOY_MISSING 42 · SIC_FINANCIAL_EXCLUDED 41
- **CSV**: [short_candidates.csv](./short_candidates.csv)

| # | Symbol | SIC | RS60 vs peers | SMA50 | 20d | Rev YoY | OCF YoY | P/E pct | P/E prem | Borrow |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | EIX | 4911 | -11.9% | 0.808 | -19.8% | -2.4% | -109.7% | 1.000 | +86352397.8% | UNKNOWN |
| 2 | SMTC | 3674 | -6.0% | 0.867 | -5.5% | -12.7% | -35.4% | 0.871 | +200.5% | UNKNOWN |

- **Invalidation**: Recheck if price closes at/above SMA50, `rs60_sic` turns >= 0, revenue growth turns > 0, OCF growth turns > -10%, or the P/E percentile/premium falls below 0.80 / 25%.
- **Borrow**: `UNKNOWN` means no verified, time-stamped broker observation was available. Quantity and fee are intentionally blank; verify with the broker before any action.

