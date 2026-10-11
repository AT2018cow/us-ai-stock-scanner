# Coverage and integrity — RUN_ID historical_selection_v1_20261011_02

## Universe verdict (HARD LIMITATION — survives into final review)

**`retrospective with approximate historical universe`.** All 38 watchlist
snapshots are dated 2026-09-22 or later; the full 2023-01→2026-03 window uses
`union_superset_approx` membership (documented upward bias: weak/delisted
names under-represented). These 39 signal dates support **mechanism
diagnostics** (scoring, Entry states, Action ranking) but CANNOT prove true
historical excess returns for a generalized US strategy. This limitation is
not lifted by row counts.

## Dataset integrity

| item | company_quality | entry_quality |
|---|---|---|
| rows | 25,025 | 25,025 |
| signal dates | 39 (2023-01-31→2026-03-31, monthly) | same 39 |
| symbols | 670 | 670 |
| dataset_kind | company_quality | entry_quality |
| pre_strategy_cross_section | true | true |
| CSV SHA256 | e1249bca…59d818ff | d5f86035…9af10794 |
| meta SHA256 | f915df97…0bae9c39 | e03f2d24…9403fb |
| `_SUCCESS.json` | status success, spec match | status success, spec match |
| watchlist_source | mixed PIT-snapshots≥2026-09-22 + union approx before | same |
| label maturity | 100% valid at 20/60/120d (no immature) | 100% valid |
| units | signal_date × symbol, next_open/close, 15bps single-side, QQQ bench | same |

Grade mix (action master): A 6,847 / B 9,163 / C 7,154 / UNRATED 1,861.
Entry mix (A/B only, n=16,010): READY 2,041 / PULLBACK 2,392 / BREAKOUT 4,969 /
DAMAGED 5,785 / INSUFFICIENT 823.

## PIT claims and their limits

- Per-date SEC filing cutoffs + TTM reconstruction enforced by the extractor;
  `fundamental_data_asof`, accession provenance preserved per row.
- Date-column checks alone do not prove perfect SEC PIT (restatements,
  late filings); filed-as-of semantics are the extractor's, documented.
- Corporate actions: split events fetched (41 symbols in window), fail-closed
  on fetch failure; bars are split-adjusted, NOT dividend-total-return.
- Overlapping 20/60/120d labels are NOT independent observations; all tables
  report date-equal-weight means alongside pooled means, plus n_dates and
  concentration diagnostics.
- 2023–2024 = exploratory development; 2025/2026Q1 = temporal diagnostics
  only (these years were touched by prior research — never pristine OOS).

## What was NOT used

- Legacy `weight_dataset_*` survivor files (explicitly excluded as universe).
- `hist_cq_4dates.csv` hand-merged pilot file (exploratory only, not evidence).
- Generalized-v0 62-name cohort (frozen 2026-10-11; post-hoc use forbidden).
