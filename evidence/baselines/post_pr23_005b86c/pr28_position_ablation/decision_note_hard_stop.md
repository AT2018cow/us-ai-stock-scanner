# PR28 position-gate ablation: HARD STOP record

Date: 2026-10-10
Run: `post_pr28_position_ablation_202610`, dataset stage only, risk_off
low_value, style-aware extractor with exactly three skipped structural hard
gates (`max_range_position_52w`, `min_drawdown_from_52w_high`,
`max_price_to_sma200`). Expanded dataset: SHA
`bb6edd7a30d8347aeb2020f77255eb1d043d2417aa8892b1a62da8ff0cad0ad6`,
23774 rows / 42 dates. Raw CSV stays off-repo.

## Verdict: STOP — do not interpret B-arm returns

- Baseline ordered parity: **114/126** channel-dates exact; 12 single-symbol
  Top-10 boundary swaps (all Jaccard 0.818).
- A second gate also fails: median A/B Jaccard 0.46 < 0.50.
- Per protocol, any non-empty actual_only/expected_only is a stop condition.
  **No B-arm return conclusion is recorded here.**

## Parity debug summary

Ruled out: file mix-up (signals SHA verified across evidence/download/working
copies), scoring/filter code drift (zero `src/` diff between replay code
`26f93e4` and ablation code `cd613c3`), Top-N/dedupe/cap ordering (same
canonical functions and parameters).

Confirmed: 8/12 swaps are sub-0.1sigma near-ties at the Top-10 boundary;
small live-data drift exists between the replay run (Oct 8 20:39 UTC) and the
extraction runs (soft_pass_count +/-1 flips); swapped symbols' own stored
features are identical across Oct-8/Oct-9 datasets.

Unresolved: exact input-side cause of 4 larger-margin swaps
(2023-05-31 NXPI/ACN, 2024-02-29 AAPL/TER, 2026-04-30 PH/AAPL, 2026-09-30
CEG/BWXT). Replay-side per-date inputs are not retained, so the residual
cannot be attributed to a single column from committed evidence. There is no
wholesale list divergence, but the mismatch pattern is not demonstrably
random: 10/12 swaps are in ai_enabler and ADBE is the extraction-only boundary
name in 7/12 mismatches. A systematic input/soft-score drift therefore cannot
be excluded.

## What this means for the mechanism question

The stop is procedural, not a refutation: the B-arm comparison was computed
but remains quarantined. The chosen follow-up is not to weaken the historical
parity rule. Instead, code-path equivalence will be tested on one immutable
cross-section state using the canonical production selector, and any new
mechanism test will use a separately pre-registered single-gate intervention.
The Oct-8 replay vs Oct-9 extraction remains 114/126 and is not relabeled as
passing. No production change is justified by PR28.
