# H4 — Liquidity: INCONCLUSIVE (no additional fetch per protocol §8)

**Verdict: H4 = INCONCLUSIVE.** No v1 liquidity-gate change is proposed or supported.

## Why no gate-disagreement analysis was possible

1. The production gate is a **one-day snapshot `dollar_volume >= $2m`** value
   computed inside a live scan. No historical series of that snapshot field
   exists for the 2023-01→2026-03 window.
2. Local `data/watchlist_history/` (38 files) and the frozen inputs contain
   only candidate **membership** snapshots from 2026-09-22 onward — no
   historical per-symbol snapshot dollar-volume observations.
3. Same-feed (Alpaca IEX) historical daily bars *could* be fetched, but a
   bar-derived `close × volume` or 20-session mean is a **different metric**
   from the scanner's snapshot field (protocol §8: never equate the three).
   Without same-date snapshot-vs-bar **pairs**, a gate-disagreement count
   would compare incomparable quantities.
4. Per protocol §8, launching an expensive historical SIP/IEX re-fetch merely
   to force a GO is prohibited. None was launched.

## What IS available (diagnostic only, not a gate test)

- The datasets carry `avg_dollar_volume_20d` and `dollar_volume` (as-of signal
  date reconstruction inputs, IEX-scale proxies, not consolidated tape).
- IEX-scale proxies must not be interpreted as executable capacity or
  compared 1:1 with SIP-derived figures (AGENTS.md liquidity invariant).

## To make H4 answerable in the future

- Archive the live scanner's per-symbol snapshot `dollar_volume` (and feed)
  at each future `--formal` or experiment snapshot, so same-date
  snapshot-vs-bar pairs accumulate prospectively.
- Only then can snapshot-vs-20-session disagreement be measured honestly.

**No `liquidity_coverage.csv` / `liquidity_cases.csv` is submitted; this file
is the contracted substitute. The $2m pre-decision gate is unchanged.**
