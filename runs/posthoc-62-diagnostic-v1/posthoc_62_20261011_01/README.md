# Post-hoc 62-symbol diagnostic v1 — RUN posthoc_62_20261011_01

**Mode: `retrospective_posthoc_cohort`.** The 62-symbol roster was frozen
2026-10-11 and evaluated as of three EARLIER sessions with strictly
point-in-time evidence. This cohort was NOT discovered by any historical
process, is NOT a PIT candidate pool, and proves nothing about strategy
returns. Purpose: functional validation of Quality/Entry/Action judgements
and report usability on real cross-industry names.

## Sessions and method

- Decision dates: 2026-09-30, 2026-10-05, 2026-10-09 (all verified QQQ
  trading sessions; chained previous 09-30 → 10-05 → 10-09).
- Per date, per symbol: PIT bars ≤ date (IEX), SEC filings with filed-date
  ≤ date (TTM rebuilt), split events (fail-closed fetch), QQQ regime —
  through the frozen v1 pipeline (`build_cross_section_asof` →
  `build_stock_decisions` → same renderers). No forward data anywhere.
- 62/62 decisions on all 3 dates; 0 universe exclusions.
- Policy: Quality v1 + Entry v1 + Action mapping + $2m gate, all frozen
  (experiment config byte-identical to the PR #57 prepare output).

## Headline findings (details in files below)

- Quality grades describe real businesses (see phase1a tables): A ≈ 14%
  margin/15x coverage/net-cash; C ≈ loss-making/cash-burning/indebted.
- Entry states read as distinct price structures (READY healthy-trend,
  PULLBACK extended, BREAKOUT basing, DAMAGED broken).
- 9-day stability: 0 grade changes / 21 state changes / 6 action changes;
  PRIORITY_REVIEW 4 → 6 → 8. Slow-Quality/fast-Entry separation holds.
- Banks cluster in C/AVOID (BAC/JPM/MS/WFC), GS UNRATED — v1 accounting
  semantics visibly unfit for banks (no re-weighting done; research only).
- REITs all grade B (AMT/EQIX/O/PLD).
- XOM + GS UNRATED on 9–14 missing core metrics; XOM mapped name reads
  "ExxonMobil Holdings Corp" — identity mapping under P0 review
  (see anomalies.md; no reliability claimed for these two ratings).

## Layout

- `README.md`, `run_manifest.json`, `SHA256SUMS`
- `dates/<YYYY-MM-DD>/`: decisions.jsonl, action_list.md (15),
  universe_exclusions.jsonl, manifest.json
- `representative_reports/`: ABBV (PRIORITY), JPM (bank C), XOM/GS
  (UNRATED), AAPL (READY→BREAKOUT), AMT (REIT B+READY), ADBE (A DAMAGED)
- `posthoc_stability.csv`: per-symbol grade/state/action trails
- `phase1a_*.csv`: operating-reality/applicability/structure stats
  (25,025-row _03 base; valid-n reported per metric)
- `anomalies.md`: bank/REIT/XOM/GS records + decision criteria
- `posthoc_62_diagnostic.py` + `test_posthoc_62_guards.py` (exact sources)
