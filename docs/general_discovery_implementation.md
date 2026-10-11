# Opt-in multi-source discovery implementation (v1-compatible)

> Implementation PR; baseline `configs/config.risk_off.json` and existing `data/ai_watchlist.csv` remain unchanged.
> No new Quality / Entry / Action weights or thresholds. No default expansion to full US equities.

## Purpose and mode selection

The scanner supports two **mutually exclusive** discovery modes:

- **Legacy default:** if `discovery_source_files` is omitted or `null`, load the
  existing `watchlist_csv_path` unchanged through `watchlist_rows_to_scores`.
  Retain existing AI buckets, source/ETF counts, decision contract, IEX `$2m`
  prefilter, legacy watchlist PIT archival, output names and pre-existing
  configuration fingerprint computation (omit new null config key from hash).
- **Opt-in generalized mode:** explicitly list one or more frozen CSV sources
  in `discovery_source_files`. Do NOT auto-append the legacy AI watchlist:
  adding the AI theme must be an **explicit** thematic input. Source files
  are unioned on canonical listed security symbol, while retaining all
  distinct source memberships as a separate snapshot audit.

Allowed source file keys: `us_core`, `thematic`, `manual`. Any subset is
allowed for bounded tests and future incremental rollout. No new field
appears in official `config.risk_off.json` in this PR.

## Source CSV schema

Each enabled source CSV uses at minimum:

```csv
symbol,source_id,source_asof,security_type,enabled,theme_id,legacy_bucket,etfs,research_note
MSFT,us_core_us_common_20261009,2026-10-09,common_stock,1,,,,
```

The row above is an **illustrative example, not a proposed production US Core selection**.
Use source-file keys to specify its kind; do not rely on column order.

- `symbol` must be an explicit uppercase listed-security ticker, with optional
  period, not an alias requiring guesswork; `BRK-B` is rejected rather than
  silently treated as `BRK.B`. Distinct listed share classes are distinct
  securities even when their CIK is shared.
- `source_id` is a stable **within-kind** discovery-list ID. One CSV can
  contain many thematic `source_id` and `theme_id` values.
- `source_asof` is the `YYYY-MM-DD` date on which membership was known;
  the scanner rejects a membership dated **after the market decision session**.
- `security_type=common_stock` is the seed-provider's asserted classification,
  **not** an independent Alpaca/SEC verification and not a Quality guarantee.
  ETFs/warrants/preferred/unknown values are explicit source-row rejections.
- `enabled` accepts 1/0, true/false, yes/no. Disabled source rows
  are preserved in the input archive and source rejection audit.
- `theme_id` is **required for thematic** rows; optional/ignored for other
  source types. AI has ID `ai`; themes are not Quality score bonuses.
- `legacy_bucket` and `etfs` only flow into the existing legacy score
  adapter for `theme_id=ai`. They are empty for US Core and Manual.
  ETF consensus from different sources must not be manufactured.
- `research_note` is required for Manual rows. Do not place secrets or
  personally identifying material in this field; it is archived verbatim.

Rows rejected before symbol-level discovery appear in
`discovery_source_rejections.jsonl` with source filename, CSV row number
and a deterministic reason (disabled, invalid symbol, missing source ID/as-of,
not common-stock, missing theme ID/manual note or duplicate membership).
Raw input row conservation is kept separate from **unique enabled symbol**
conservation; a disabled raw row is not itself a missing StockDecision.

## Example opt-in config creation — without changing production config

Prepare frozen CSVs for the desired source types first (paths are examples,
and the CSVs are user-supplied, NOT created by this PR):

```text
data/discovery/us_core_20261009.csv
data/discovery/thematic_20261009.csv
data/discovery/manual_20261009.csv
```

Create a **temporary experiment config** based on the existing risk_off
compatibility baseline:

```bash
python - <<'PY'
import json
from pathlib import Path
src = Path('configs/config.risk_off.json')
config = json.loads(src.read_text(encoding='utf-8'))
config['discovery_source_files'] = {
    'us_core': 'data/discovery/us_core_20261009.csv',
    'thematic': 'data/discovery/thematic_20261009.csv',
    'manual': 'data/discovery/manual_20261009.csv',
}
dst = Path('outputs/config.discovery.experiment.json')
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
print(dst)
PY
```

Do **not** commit this local config as the new official default.

Run offline preflight (no credentials):

```bash
python scripts/preview_discovery_sources.py \
  --config outputs/config.discovery.experiment.json \
  --decision-date 2026-10-09
python -m unittest discover -s tests
```

The preview lists input source hashes, distinct candidates, multi-source
overlap, all rejected source rows, and full input row counts. It makes no
investment decisions. Replace the example date with the **actual target
market session**, not today's wall-clock date.

## Opt-in full-scan experiment (requires credentials; do not run --formal)

**Only after the implementation PR is merged and the input cohort is reviewed**:

```bash
python scripts/run_mvp_full_scan.py \
  --config outputs/config.discovery.experiment.json
```

All enabled membership source dates must be on/before the resulting QQQ market
session date. This run must use a **bounded, pre-registered cohort** and
`max_symbols=null` (full scan of that cohort, not a hidden sample). The
existing SEC/Alpaca environment variables and cache discipline apply.
No source expansion, fundamental score promotion or formal snapshot is allowed
without reviewing the experiment evidence.

New opt-in snapshot artifacts in addition to current v1 files:

```text
discovery_memberships.jsonl
discovery_source_rejections.jsonl
discovery_source_inputs/us_core.csv       # only when configured
discovery_source_inputs/thematic.csv      # only when configured
discovery_source_inputs/manual.csv        # only when configured
```

`run_manifest.json.discovery_sources` stores schema version, source file SHA256,
raw/accepted/rejected counts, symbol counts and overlapping memberships.
The snapshot writer copies the exact input bytes to the **immutable** snapshot
and fails if the source changed since initial read. Validator checks
input SHA256, manifest/source-row counts, membership dedupe, all source
as-of dates and `discovery symbols = decisions + exclusions`.

## Review evidence to submit (non-ZIP and no routine evidence PR)

Follow `docs/research_evidence_workflow.md` after its process adoption.
Submit browsable original text files in a pinned commit on the approved
evidence branch/repository, with a readable index and SHA256SUMS:

```text
runs/general-discovery/<market_date>_<scanner_sha7>_<run_id>/
  README.md
  run_manifest.json
  validation.json
  discovery_memberships.jsonl
  discovery_source_rejections.jsonl
  discovery_source_inputs/*.csv
  universe_exclusions.jsonl
  decisions.jsonl
  action_list.md
  weekly_review.md
  source_coverage_review.md
  input_hashes.txt
  SHA256SUMS
  sanitized_scan.log                 # only if needed for diagnosis
```

**Experiment README and source_coverage_review must document:** exact
run and code/config/input SHAs; decision market-as-of date; actual feed;
all accepted and disabled/malformed raw rows; per-source and intersection
counts; 1-to-1 decision/exclusion conservation; unknown symbols/share-class
aliases, unsupported filings/currencies and confidence/missingness;
legacy comparison with the same frozen v1 data where feasible;
runtime, network/SEC request bounds and any manual edits; review examples
for overlapping membership, manual-only, thematic-only, core-only, source
rejects, nontradable/unmapped and liquidity exclusions.

**Do not upload:** `.env`, credentials, token values, personal notes/secrets,
unredacted identity-bearing headers/logs, raw Alpaca/SEC/EdgarTools caches,
virtualenv or unrelated large artifacts. Source CSVs and manual research
notes must be reviewed for sensitive data before publication.

**GO / NO-GO:** exact-head CI and validator PASS; no silently vanished
symbols or source rows; the three source types can each be represented;
legacy mode without new config remains identical; preserved old v1 Quality/
Entry/Action and IEX liquidity rules; bounded network/cost and understood
coverage/unsupported reporting. GO only approves discovery-source correctness,
**not** general-market strategy performance or Quality v2.

## Research and rollout boundaries

- Do not infer actual accounting business model, industry or financial-reporting
  comparability from discovery source or `ai_smallcap` label.
- Financials, insurers, REITs, non-USD and unsupported reporting types remain
  subject to existing fail-closed behavior; Quality v2 is a **separate** PR.
- QQQ remains Entry v1's current benchmark, pending separate evaluation.
- No historical ETF constituent reconstruction, hypothetical backwards PIT
  memberships, order execution or portfolio layer.
- Old AI-specific snapshot history and legacy watchlist archive are untouched.
- This implementation supports **inputting** real US Core/thematic/manual
  candidates but does **not** manufacture or certify an official US Core roster.
