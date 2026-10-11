# Generalized US Stock Selection — integrated research and acceptance (#57)

> **Research only.** This PR does not change production `risk_off`/`risk_on`,
> v1 Company Quality, Entry, Action routing, QQQ regime, IEX `$2m` gate,
> live watchlist, formal prospective archive or strategy weights.

## Goals in one PR, not multiple mini-PRs

1. **Freeze a bounded, general-US study cohort** and three-source provenance.
2. **Audit Company Quality v1** by provisional accounting/business-model cohorts:
   grades, confidence, risk reasons, missing facts, USD/filing coverage.
3. **Audit Entry v1** across sectors: Entry states, risk reasons, trailing
   20/60-session performance relative to QQQ, SPY and illustrative industry
   proxies, aligned on common trading-session bars (no lookahead).
4. **Audit one-day liquidity vs 20-session turnover** using the same IEX feed,
   with explicit bar coverage, stale/missing cases, and threshold disagreement.
5. **Audit Action List** compression/cross-industry representation without
   changing priority logic or interpreting selected names as trade instructions.

## Registered cohort (2026-10-11 freeze; not PIT for 2026-10-09)

Stored as plain Git-tracked CSVs under `data/research/generalized_v0/`:

| File | Scope |
| --- | --- |
| `us_core.csv` | 60 research-selected US-listed common-stock ticker assertions |
| `coverage_strata.csv` | 12 intentionally different research/business-model hypotheses × 5 |
| `thematic.csv` | 10 AI-related thematic research rows, overlapping the core |
| `manual.csv` | 5 **research-curated diagnostic** rows, 3 overlapping + 2 distinct |

Frozen union: **75 memberships, 62 unique symbols**.
Source date is **2026-10-11**, the date the research roster was made,
which is a weekend. The earliest eligible **future** US market session
is 2026-10-12. Do not scan or label this universe as of 2026-10-09.
These are manually preselected **coverage probes**, not a random or
representative sample of the US market. No attempt is made to recover
historical index membership, verified GICS classifications, or all liquid
stocks. Any invalid security / missing Alpaca asset / SEC mapping must be
reported by existing exclusion contracts, never quietly replaced after
seeing Quality/Entry outcomes.

Coverage labels (e.g. `software_platforms_devices`,
`semiconductors_and_equipment`) intentionally encompass businesses with
different accounting structures; they are *review strata*, not validated
common business models or GICS sectors. Group-level Quality statistics
must not be read as issuer-comparable scores.

Coverage labels are deliberately `research_provisional` in the metadata,
not an official sector feed; their purpose is to identify accounting
differences in a bounded controlled experiment. In particular:

- `banks_brokers`, `reit_property`: **not Quality v2-comparable**
  pending specialist accounting evaluation.
- `healthcare_pharma_medtech`: contains dissimilar payors, pharma and
  instrument makers; company-level semantics need review.
- Broad platforms/industrial conglomerates can cross stratum boundaries.
- The two manual-only names are classified **unknown** until an independent
  classifier or reviewed fundamental evidence establishes a business model.
- A few widely followed companies and a quota of five per topic bias the
  universe toward recognizable companies; exclusion rates here cannot
  estimate the true US equity universe or a liquidity threshold's alpha.

## Tools and saved outputs

- `scripts/research_generalized_selection.py prepare` creates the one
  temporary opt-in config without modifying the official compatibility file.
- `scripts/export_generalized_pit_bars.py` calls the already-installed
  Alpaca client for at most **76** stock/ETF securities, from 185 calendar
  days before the **snapshot market-as-of**, with `feed=iex`; it requests
  stock-split events and preserves dollar volume through split adjustment.
  The current Alpaca client requests bars with a **start date only**: the
  provider may return bars after the decision session, but exporter discards
  every future-dated bar before writing the dataset. Split actions are bounded
  through the snapshot as-of date; stale market-data fallback aborts the export.
  No SEC fundamentals are fetched by this export step.
- `scripts/research_generalized_selection.py audit` loads the real immutable
  generalized snapshot and optionally the IEX bar CSV; checks all 62
  symbols, source hashes, manifest counts, source dates, prefilter/feed,
  and creates the same research reports for all three dimensions.
  It reconstructs **every source membership/rejection row** from the
  snapshotted CSVs (not just SHA256 and aggregate counts) and refuses changes
  in symbol, source, manual note or AI theme assignment. The aggregate
  review includes group-level bar-gate disagreement counts and QQQ/SPY
  trailing-excess sign disagreements, alongside raw per-symbol CSVs.

Outputs from the read-only audit:

```text
research_audit.json                    # aggregate cohort and review coverage
research_review.md                    # human-readable group cross-tab
quality_entry_action_by_symbol.csv    # financial/entry risks, coverage, actions
liquidity_diagnostics.csv             # IEX bar last-session versus 20-session mean
entry_benchmark_diagnostics.csv       # aligned QQQ / SPY / illustrative proxy
```

Optional market-data export outputs:

```text
pit_iex_daily_bars.csv                # authorized same-feed adjusted OHLCV
pit_bars_manifest.json                # requested sessions, symbols, split handling, provenance
```

**Important quantitative semantics:** `close × volume` on one last daily bar
is a *new proxy* and is **not** the scanner's snapshot dollar-volume field.
No recommendation to lower/raise `$2m` may follow from a discrepancy.
QQQ/SPY/industry results are backward-looking **trailing** relative
observations, not predictions, forward returns, point-in-time v2 Entry
state replays or statistically independent experiments. **QQQ and SPY
relative returns for each stock share a triple-intersection of stock/QQQ/SPY
market sessions**, so absent SPY/QQQ observations cannot shift the comparison
window silently; illustrative sector proxies use a separate stock/proxy
intersection and must not be interpreted as the same calendar window. Industry ETF
assignments are illustrative and not verified sector classifications.
Open-source bars are raw from Alpaca then split-adjusted, but they are
**not dividend-total-return adjusted**; note that limitation explicitly.
Missing bars never become zero turnover or zero return. A failed
corporate-action fetch fails closed rather than silently exporting
misleading unadjusted trend comparisons.

## Local steps before merge (no credentials)

```bash
python -m unittest discover -s tests
python scripts/research_generalized_selection.py prepare \
  --base-config configs/config.risk_off.json \
  --output-config outputs/config.generalized_v0.experiment.json
python scripts/preview_discovery_sources.py \
  --config outputs/config.generalized_v0.experiment.json \
  --decision-date 2026-10-12
```

Note: `prepare` refuses to overwrite an existing experiment config.
Rename or choose another new output path when repeating. If the calendar
date at the time of the run has not reached 2026-10-12, wait for the
actual market session rather than bypassing as-of checks.

## One external, bounded experimental workflow after merge

**Requires user-held Alpaca/SEC credentials. Never run `--formal`.**
Use the *same* `outputs/config.generalized_v0.experiment.json` prepared
from the compatibility baseline and the exact frozen source files.
Check `ALPACA_FEED=iex` and hold policy/thresholds constant.

```bash
python scripts/run_mvp_full_scan.py \
  --config outputs/config.generalized_v0.experiment.json

# Set SNAPSHOT to the new path printed by the scan, not an old formal output.
python scripts/validate_mvp_snapshot.py "$SNAPSHOT" --json > validation.json

python scripts/export_generalized_pit_bars.py \
  --snapshot "$SNAPSHOT" \
  --config outputs/config.generalized_v0.experiment.json \
  --out-dir outputs/generalized_bars_v0

python scripts/research_generalized_selection.py audit \
  --snapshot "$SNAPSHOT" \
  --config outputs/config.generalized_v0.experiment.json \
  --bars-csv outputs/generalized_bars_v0/pit_iex_daily_bars.csv \
  --out-dir outputs/generalized_research_v0
```

When optional bars are supplied, the audit **requires the original
`pit_bars_manifest.json` beside the bar CSV** and checks byte SHA256,
feed, market session, code SHA, config fingerprint, source cohort hashes,
declared symbol count and row count before generating comparisons.
A standalone unprovenanced market-data CSV is a **NO-GO** for the
benchmark/liquidity results.

The audit independently reloads the experiment config, compares the **raw JSON**
byte-equivalent policy object to the frozen `configs/config.risk_off.json`
baseline after removing only `discovery_source_files`, then recomputes the
scanner-compatible normalized `config_fingerprint` and requires it to match
the snapshot manifest. This catches both explicit policy edits and effective
runtime drift before the generalized-universe evidence is interpreted.

Use **new unique output directories** for reruns; never overwrite prior
runs or snapshot bytes. Full scanner workload: 62 unique candidates,
and QQQ/other preexisting scanner benchmarks. Extra bar-export workload:
at most 76 instruments in bounded batches over ~185 calendar days plus
corporate-action data. Network fallback/cached provenance must be recorded;
if source or cache age cannot be established, classify comparison as
inconclusive rather than implying fresh PIT bars.

### Review evidence to submit — original browsable files, NO ZIP, NO evidence PR

Submit in `evidence-observations` with pinned commit SHA:

```text
runs/generalized-v0/<session>_<scanner_sha7>_<run_id>/
  README.md                     # exact commands, run UTC, SHA, config delta, mode
  validation.json               # validator PASS/FAIL/warnings
  run_manifest.json             # source/market/feed/coverage/provenance
  discovery_memberships.jsonl
  discovery_source_rejections.jsonl
  discovery_source_inputs/*.csv # frozen, byte-identical snapshot source files
  coverage_strata.csv           # frozen provisional accounting-group labels from code SHA
  universe_exclusions.jsonl
  decisions.jsonl
  action_list.md
  weekly_review.md
  sanitized_config.json         # full non-secret opt-in config
  pit_bars_manifest.json
  pit_iex_daily_bars.csv         # bounded licensed research input, if permitted
  research_audit.json
  research_review.md
  quality_entry_action_by_symbol.csv
  liquidity_diagnostics.csv
  entry_benchmark_diagnostics.csv
  reviewer_notes.md
  SHA256SUMS
```

If the market-data provider's terms prohibit republishing the raw
bar CSV, **do not push it**. Submit its SHA, schema, per-symbol/session
coverage, derived non-sensitive diagnostics, and an independently
reproducible fetch protocol; explicitly label the missing raw input
as a review limitation. The full config must be sanitized for credentials
before submission, then its archived content hash and actual local config
hash must be distinguished (not misrepresented as byte-identical).
Never submit `.env`, keys, tokens, SEC user-agent identity, personal manual
notes, raw SEC/Alpaca/EdgarTools caches, or verbose unredacted logs.

### Acceptance and scoped GO/NO-GO

**Engineering GO:** exact-head CI PASS; same frozen inputs and SHA256;
archived source membership content byte-equivalent after normalized origin
paths, unmodified source identifiers and notes;
source membership raw-row accounting; 62 unique discovery symbols each
exactly one Decision OR universe exclusion; no future source membership;
validator PASS; report generator completes; no v1 policy change or
unaccounted exclusion; source/market-data network budget documented.

**Liquidity evidence GO:** at least 80% of 62 symbols have 20 valid IEX
trading-session observations anchored at the decision session,
bar freshness and corporate actions recorded; number of gate
disagreements by provisional group reported, with non-participating
rejected names visible. Otherwise liquidity comparison is INCONCLUSIVE.

**Entry evidence GO:** at least 80% of 62 have aligned
61 common QQQ **and** SPY daily sessions through the decision session;
sector proxies are exploratory, not required for GO. Report 20/60
trailing relative returns by group and Entry state (sample sizes too),
no automatic Entry state remapping. If insufficient, Entry benchmark
comparison remains INCONCLUSIVE.

**Quality diagnostic GO:** every decision retains v1 grade/confidence/
missingness; each provisional group reports counts and failure modes;
bank/REIT/unknown cohort flagged non-comparable; do not impute
unavailable non-USD/latest-filing data. Neither group score differences
nor unrepresentative sample outcomes authorize Quality v2 weights.

**Action GO:** existing single StockDecision priority/Action semantics
and daily/weekly cap validated; group representation and omissions
reported without arbitrary sector quotas.

Decision: research evidence GO is **NOT production promotion**. A
subsequent consolidated policy change can revise Quality, Entry,
liquidity or Attention only after independent, temporally distinct
evidence. Keep old prospective v1 as frozen comparator.
