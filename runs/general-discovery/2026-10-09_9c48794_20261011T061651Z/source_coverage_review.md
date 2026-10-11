# Source coverage review — opt-in discovery smoke experiment

Code SHA: 9c4879438265a94f9301b2197340a350a518cad6
Config SHA256: 3713181214bd139a20ca0c86df81ea97212fdbfea7886a4814cd1d34b9d6bfdc (outputs/config.discovery.experiment.json)
Market session: 2026-10-09 (QQQ market-asof; run wall-clock 2026-10-11)
Feed: iex. Mode: experiment (no --formal).
Validator: PASS, warnings: none.

## Source inputs (frozen, archived byte-identical)

- data/discovery/us_core_20261009.csv (sha256 fd6ab937…): 3 raw rows, 3 memberships, 0 rejected
- data/discovery/thematic_20261009.csv (sha256 fcbbd5…): 2 raw rows, 2 memberships, 0 rejected
- data/discovery/manual_20261009.csv (sha256 d3f50a…): 2 raw rows, 1 membership, 1 rejected (SBUX SOURCE_DISABLED)
- Total: 7 raw rows, 6 memberships, 5 unique symbols, 1 multi-source symbol (MSFT: us_core + thematic/ai)

All source_asof=2026-10-09, on/before the decision session. No future membership.

## Per-source examples

- US Core only: JNJ (A/PRIORITY_REVIEW), XOM (B/HOLD_MONITOR)
- Thematic only: NVDA (B/HOLD_MONITOR, theme ai)
- Manual only: COST (A/HOLD_MONITOR with TREND_DAMAGED — honest non-promotion)
- Overlapping membership: MSFT (us_core + thematic/ai → exactly one StockDecision, A/PRIORITY_REVIEW; legacy_bucket core_ai + AIQ etf preserved on the thematic row only, no consensus inflation)
- Source reject: SBUX manual row 3, SOURCE_DISABLED, absent from decisions

## Conservation

5 discovery symbols = 5 decisions + 0 exclusions. No overlap, no missing symbols.
universe_exclusions.jsonl is present and empty. Rejected raw row (SBUX) is a
source-row rejection, correctly not counted as a missing decision.

## Unknowns / non-comparables

None in this cohort: all 5 mapped to Alpaca active assets + SEC CIK, USD
Company Facts coverage, no fallback used (not_needed=5), no currency blockers.

## Legacy parity

Default legacy path untouched: this run used a separate untracked experiment
config; configs/config.risk_off.json and data/ai_watchlist.csv unchanged;
discovery_source_files=null default preserved with legacy config fingerprint.

## Budget

Runtime ~10s scan (+3s unittest preflight). SEC: 3 hits / 6 misses (all 5
symbols fresh in cache or single-fetch). Alpaca: snapshots + bars for 5
symbols + QQQ. No new external data source.

## Uncertainties

- 5-symbol smoke cohort exercises union/dedupe/rejection plumbing only; it says
  nothing about cross-industry Quality comparability or threshold choice.
- GO (if granted) approves discovery-source correctness only.
