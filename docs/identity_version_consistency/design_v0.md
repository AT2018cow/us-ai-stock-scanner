# P0: financial-data identity & version consistency — design v0

> Status: DESIGN ONLY. No production code changed in this commit.
> Goal: same symbol + same financial as-of must never silently yield
> incomparable facts and grades across runs (observed: XOM posthoc-1009
> UNRATED vs frozen-1012 B at identical asof 2026-08-03).

## 1. Problem restated (frozen)

- Ticker->CIK map is fetched live and never archived: post-hoc and frozen
  runs cannot prove they used the same binding.
- Submissions/companyfacts cache files carry no fetch timestamps usable
  post-hoc; content for one CIK was observed at 6.6MB and 84KB within the
  hour (self-overwrite cannot be excluded — mechanism open).
- Same-asof grade flips across pipelines have four distinct honest
  mechanisms (XOM content/entity, HON integrity-gate skew, FCX threshold
  edge, NEE genuine upgrade). Only XOM-class is unexplained.

## 2. Data contract (to implement; research + production paths)

Per run, freeze an identity manifest (JSON, committed with evidence):

```text
ticker_map: {fetched_utc, source_url, sha256, n_rows}
per symbol:
  symbol, mapped_cik, map_match ("listed" | "unlisted" | "unmapped")
  submissions: {entity_name, tickers[], n_recent_filings,
                latest_periodic {form, accession, filing_date}, sha256, fetched_utc}
  companyfacts: {queried_cik, content_sha256, fetched_utc,
                 n_tags, core_tags_present {revenue, ni, ocf}}
  identity_verdict, identity_detail  (existing helper + tightened rule)
```

Rules:
- UNCOMPARABLE is a research/audit comparison state first: when two runs
  share (symbol, asof) but content SHAs differ, labels are incomparable
  until explained. It is NOT a new production Quality grade; any
  production-behavior change gets its own section + impact proof.
- Missing/unverifiable identity input fails closed (existing gate
  behavior); absent-flag legacy frames keep old behavior.
- No scoring-formula rewrite. No full-history replay for this P0.

## 3. Test plan (synthetic + cached, no credentialed bulk fetch)

- Map freeze round-trip: write manifest, re-read, byte-compare.
- Ticker-list mismatch -> UNVERIFIED; empty-list + facts without evidence
  -> UNVERIFIED; evidence restores verified (extends existing 14 tests).
- Content-flap detector: two facts payloads, same asof window, disjoint
  core tags -> comparison reports UNCOMPARABLE (not a silent pick).
- Cache reliability: stale-tail batch must enrich-or-mark-stale (the
  registered P1 bulk-batch case, in scope here as it shares fixtures).
- XOM/HON/FCX/NEE/PLD acceptance rows: each case replays its inputs to
  its recorded verdict (matrix in §5).

## 4. Heavy-compute gate

Prefer existing cache + synthetic fixtures. If a credentialed mass
refetch is ever needed: file fields/window/resource budget for approval
first, then run on Modal at2018cow (foreground, checkpoints). Not
authorized by this design commit.

## 5. Acceptance matrix (fill during implementation)

| case | inputs (frozen) | old verdict | new verdict | conservative on failure |
|---|---|---|---|---|
| XOM holdings-thin | submissions 34/no-10Q + shell facts | UNRATED-generic | UNRATED + identity code | UNVERIFIED, no grade claim |
| XOM opco-content | 6.6MB opco facts under successor CIK | B (v0) | under review: entity-selection question open | UNCOMPARABLE vs thin run |
| HON skew | newer filing than facts | UNRATED+capped | unchanged (correct) | capped |
| FCX edge | OCF YoY -10.07% | B | unchanged | n/a |
| NEE upgrade | Q2 facts newly recognized | B | unchanged | n/a |
| PLD lag | Q2 filed, facts absent | B on Q1 | unchanged + lag note | asof stays, disclosed |
