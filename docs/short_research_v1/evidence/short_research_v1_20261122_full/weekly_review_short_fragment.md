<a id="short-research"></a>
## Short Research (1)

- **Status**: `ready` · **Rule**: `short_research_rules_v1` · **Signal date**: 2016-05-31 · **Feed**: sip
- **Independence**: This is a fourth, separate research list. It does not change the long Top-15, Action states, Low-Value, Industry-Trend, Momentum, or Research Pool. It is not a trade instruction.
- **Funnel**: input 477 → U0 335 → industry RS 151 → P/E 98 → U 91 → S0 21 → S1 3 → S2 1 → selected 1
- **Status counts**: CONFIRMED 1 · INSUFFICIENT_DATA 244 · NO_SIGNAL 86 · SCOPE_EXCLUDED 142 · WATCH 4
- **CSV**: [short_candidates.csv](./short_candidates.csv)

| # | Symbol | SIC | RS60 vs peers | SMA50 | 20d | Rev YoY | OCF YoY | P/E pct | P/E prem | Borrow |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | HIMX | 3674 | -3.8% | 0.963 | -6.0% | -17.7% | -76.0% | 1.000 | +671.2% | UNKNOWN |

- **Invalidation**: Recheck if price closes at/above SMA50, `rs60_sic` turns >= 0, revenue growth turns > 0, OCF growth turns > -10%, or the P/E percentile/premium falls below 0.80 / 25%.
- **Borrow**: `UNKNOWN` means no verified, time-stamped broker observation was available. Quantity and fee are intentionally blank; verify with the broker before any action.

