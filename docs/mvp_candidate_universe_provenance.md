# MVP candidate-universe provenance / exclusion contract

> Status: operational correctness contract for the low-frequency manual-selection MVP.
> This change does not change Company Quality, Entry Quality, Action mapping,
> the $2M liquidity threshold, Alpaca market-data feed, or ETF discovery inputs.

## 1. Three universe layers

1. **Discovery universe** — symbols from the versioned ETF-derived watchlist.
2. **Decision universe** — discovery symbols that survive existing pre-decision operational gates and receive a canonical StockDecision.
3. **Attention universe** — the small Daily / Weekly human-review list selected from decisions.

Before this contract, pre-decision rejects disappeared without a canonical reason.
The price/liquidity gate uses Alpaca snapshot dollar volume; with the default setup
this is an IEX-feed observation, not consolidated-tape liquidity. The exclusion
therefore preserves the feed, observed value and threshold. This PR makes existing
behavior auditable; it does not claim that the gate is economically optimal.

## 2. Snapshot artifacts

Scanner-produced snapshots now include:

```text
decisions.jsonl
universe_exclusions.jsonl
action_list.md
weekly_review.md
detailed/
run_manifest.json
```

`decisions.jsonl` remains the canonical investment-decision artifact.
`universe_exclusions.jsonl` is the canonical pre-decision exclusion audit.

The manifest `candidate_universe` section records contract version, discovery count,
tradable/mapped count, post-sample count, decision count, exclusion count, reason/stage
counts, actual market-data feed, `min_price`, and `min_dollar_volume`.

## 3. Conservation rules

For a full run:

```text
discovery_unique_symbols = decision_universe_symbols + excluded_symbols
tradable_mapped_symbols = decision_universe_symbols + price_liquidity_prefilter exclusions
```

For a sample run:

```text
tradable_mapped_symbols = post_sample_symbols + sample_limit exclusions
post_sample_symbols = decision_universe_symbols + price_liquidity_prefilter exclusions
```

The validator treats violations as hard failures.

## 4. Exclusion reason codes

| Stage | Reason | Meaning |
| --- | --- | --- |
| asset_eligibility | `ALPACA_ACTIVE_ASSET_MISSING` | Watchlist symbol absent from Alpaca active US equities; no stronger inactive/delisted claim is inferred. |
| asset_eligibility | `NOT_TRADABLE` | Active asset exists but `tradable != true`. |
| asset_eligibility | `EXCHANGE_NOT_ENABLED` | Asset exchange is outside configured enabled exchanges. |
| sec_mapping | `SEC_MAPPING_MISSING` | Tradable/enabled asset has no SEC ticker/CIK mapping. |
| sample_limit | `SAMPLE_MAX_SYMBOLS_LIMIT` | Non-formal `max_symbols` sampling omitted it. |
| price_liquidity_prefilter | `PRICE_MISSING` | Snapshot price unavailable. |
| price_liquidity_prefilter | `PRICE_BELOW_MIN` | Price below configured minimum. |
| price_liquidity_prefilter | `DOLLAR_VOLUME_MISSING` | Price exists but snapshot dollar-volume unavailable. |
| price_liquidity_prefilter | `DOLLAR_VOLUME_BELOW_MIN` | Snapshot dollar volume below configured minimum. |

Price/liquidity rows also preserve feed, observed value, threshold, asset metadata
and watchlist discovery provenance.

## 5. Deliberate non-changes

- no change to `min_dollar_volume=2_000_000`;
- no IEX-to-SIP switch;
- no replacement with 20d average dollar volume;
- no Quality / Entry / Action or attention-cap changes;
- no ETF-list expansion or refresh;
- no industry-specific scoring;
- no retroactive edit/deletion of an earlier formal snapshot.

## 6. External experiment after merge

After this code PR is merged, run one experiment-mode full scan. Do **not** use
`--formal` until the evidence PR is reviewed.

Do not refresh `data/ai_watchlist.csv` just to change the funnel. Use the existing
input watchlist and archive its exact bytes/hash. If a refresh is operationally
unavoidable, record that explicitly.

```bash
python scripts/run_mvp_full_scan.py
```

The command prints the snapshot path. Let it be `<SNAPSHOT>`, then run:

```bash
python scripts/validate_mvp_snapshot.py <SNAPSHOT> --json > validation.json
```

## 7. Review evidence to submit

Create a separate evidence PR:

```text
evidence/mvp_candidate_universe/<decision_date>_<actual_code_sha7>/
  README.md
  run_manifest.json
  validation.json
  decisions.jsonl
  universe_exclusions.jsonl
  action_list.md
  weekly_review.md
  detailed/
  full_scan.log
  ai_watchlist.csv
  ai_watchlist.sha256
  universe_review.md
```

The evidence README must record exact merged code SHA/command, decision date, config/style,
experiment mode, validator result/warnings, candidate-universe contract version and funnel,
actual market-data feed, thresholds, whether the watchlist was refreshed, whether anything
was manually modified, and credential variable **names only** (never values).

`universe_review.md` must include:

1. discovery/tradable-mapped/post-sample/decision/excluded counts;
2. exclusion counts by stage and reason;
3. exact ARQQ and QUBT exclusion rows if present in the archived watchlist, otherwise state they were absent;
4. at least five `DOLLAR_VOLUME_BELOW_MIN` examples spanning low and near-threshold observations, with feed/value/threshold;
5. all non-price/liquidity exclusions;
6. confirmation every discovery symbol has either one decision or exactly one exclusion;
7. confirmation this PR did not change Quality / Entry / Action or config thresholds.

Do not submit `.env`, credential/identity values, raw Alpaca caches, raw SEC/EdgarTools
caches/XBRL, virtualenv, or unrelated bulk outputs.

## 8. GO / NO-GO review

The evidence review will verify validator PASS, exact conservation, no duplicate/overlap,
correct feed/value/threshold provenance, explicit ARQQ/QUBT handling when applicable,
explicit non-price/liquidity losses, unchanged decision policy, and bounded network/cache behavior.

If those pass: GO for candidate-universe provenance correctness. That GO does **not**
decide whether the $2M IEX gate should remain; that requires a separate strategy study.

Until this evidence is reviewed, do not create another formal prospective snapshot.
