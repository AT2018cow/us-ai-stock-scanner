# Liquidity-gate selection-bias research (v1 baseline)

Status: **research only — no production policy changes**. Date: 2026-10-11.
Source: the merged PR #53 frozen experiment:
`evidence/mvp_candidate_universe/2026-10-09_aa59e9d/`.
Scanner source SHA: `aa59e9d8c4593a815f6c17e906b703bf686d988e`.
Market session 2026-10-09; risk_off compatibility config; Alpaca IEX feed.

## How to reproduce without credentials

```bash
python scripts/audit_liquidity_gate_bias.py evidence/mvp_candidate_universe/2026-10-09_aa59e9d/
python scripts/audit_liquidity_gate_bias.py evidence/mvp_candidate_universe/2026-10-09_aa59e9d/ --format json
```

The script reads the frozen original watchlist CSV, the canonical 510 decisions,
177 exclusion rows, and the manifest. It checks conservation and computes rates
with the **full discovery-bucket denominator**. It does not change anything in
the input directory or call market-data/SEC endpoints.

## First-pass findings: 2026-10-09

**687 discovered = 510 decisions + 177 exclusions**.
9 were excluded at asset/SEC mapping stages; 168 at price/liquidity.
Price/liquidity = 167 under the configured $2,000,000 IEX snapshot dollar-volume gate
plus 1 under the $1 share-price floor.

| Discovery bucket (multi-label) | Discovered | Excluded | Dollar-volume excluded | Dollar-volume exclusion rate |
| --- | ---: | ---: | ---: | ---: |
| core_ai | 154 | 12 | 11 | 7.1% |
| ai_enabler | 193 | 15 | 12 | 6.2% |
| ai_peripheral | 211 | 13 | 8 | 3.8% |
| ai_smallcap | 259 | 137 | 136 | 52.5% |

**The buckets overlap**: 817 source rows are not 817 unique stocks.
These are *discovery channels*, NOT industry/sector/market-cap classifications.
137 of the 177 exclusion records are from ai_smallcap, but that does not by
itself prove a false rejection or that a smaller gate would improve returns.

### The observed dollar-volume distribution among 167 gate rejects

| Dollar-volume bracket (IEX snapshot) | Stocks |
| --- | ---: |
| under $250k | 27 |
| $250k–$500k | 35 |
| $500k–$1m | 38 |
| $1m–$1.5m | 35 |
| $1.5m–$1.8m | 21 |
| $1.8m–$2m | 11 |

Illustrations: ARQQ $261k, QUBT $1.407m; MATX/LSTR are just below $2m.
**These dollar amounts are IEX observations and cannot be compared 1:1 to SIP
or assumed as actual trade capacity.**

## Research hypotheses and tests — pre-register before comparison

1. **H1: discovery-source imbalance.** With fixed input watchlist and
   the existing IEX feed, quantify rejection by source bucket and date;
   test whether the discrepancy persists, and explicitly account for
   smallcap size, venue, sector, and missingness once reliable fields exist.
2. **H2: single-day noise.** Compare the $2m one-day IEX snapshot proxy
   with a pre-specified 20-trading-day mean of per-bar close×volume from
   the **same feed**, using only dates available at the historical decision
   session. Report coverage, market-as-of, corporate-action handling and
   missing/partial bars; do not substitute zero for unavailable volume.
3. **H3: eligibility-layer placement.** On a bounded, pre-registered
   rejected-company sample, estimate incremental bars/SEC work if liquidity
   moved from pre-decision to attention eligibility. Maintain hard costs/risk
   checks. No new decisions can be imputed for historical rejected symbols.
4. **H4: value of recovered candidates.** Only after safe PIT Quality/Entry
   reconstruction, study what additional companies would enter research,
   and compare review usefulness plus QQQ-relative 20/60/120d results
   with explicit selection bias and overlapping-horizon cautions.

## Missing evidence / stop conditions

- PR #53 does **not** contain historical 20d bars for the 177 excluded names
  or canonical PIT Company/Entry for those names. Do not claim a new gate
  would outperform or recover particular high-quality picks.
- No consolidated-tape liquidity comparator is present. A SIP comparison
  requires an authorized feed and separately bounded experiment.
- The current data cover just **one** market session; date-wise dispersion,
  adverse fills/spreads and any economic impact are unknown.
- Fewer observed exclusions is *not* the objective: both false negatives
  and false positives plus executionability must be assessed.
- Preserve current production `min_dollar_volume=2000000` and feed during
  research; do not change Quality/Entry/Action or amend existing snapshots.

## Next evidence gate

Next deliverable is one compact, **uncompressed, browsable** research evidence
directory containing `README.md`, `manifest.json`, `audit.json`,
`liquidity_comparison.csv`, `coverage_report.md`, and `review_notes.md`.
Only include `liquidity_comparison.csv` after a documented PIT-valid 20d
comparison exists; otherwise call out the missing data, do not fabricate rows.
Include exact command, scanner and audit script SHAs, decision date,
source watchlist hash, feeds/as-of, denominators, missingness, sample-size
constraints and validator output. Do not commit API keys or raw caches.

Follow `docs/research_evidence_workflow.md` to submit these as direct files
without ZIP and without mandatory evidence-only PR. A review GO for this
descriptive audit does not authorize a new production liquidity policy.

## Subsequent project sequence

Only after the liquidity gate evidence has been examined, start the separate
**cross-industry Company Quality v2** audit (existing Quality diagnostics
by actual accounting business model, no automatic per-industry strategies).
