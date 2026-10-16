# Agent Specification: Watchlist Refresh Safe Merge & Manual/Smallcap Protection

- **Date**: 2026-10-16
- **Baseline**: `main` @ `fb64b45` (PR #92)
- **Target Execution Agent**: DeepSeek (implementation + unit tests only; no Git state mutations or live network calls)
- **Reviewer / Integrator**: Architect Agent

---

## 1. Problem & Motivation

1. **Destructive Overwrite in `scripts/refresh_ai_watchlist.py`**:
   - Currently, `scripts/refresh_ai_watchlist.py` calls `df = refresh_watchlist_from_etfs(cfg)` and writes `df` directly to `data/ai_watchlist.csv`.
   - Running it directly overwrites `data/ai_watchlist.csv` with only the top ~25 holdings fetched from the 3 ETF buckets (`core_ai`, `ai_enabler`, `ai_peripheral`), **wiping out**:
     - all `SRC:MANUAL` rows across `core_ai`, `ai_enabler`, `ai_peripheral`, and `ai_smallcap`;
     - the entire `ai_smallcap` layer (`SRC:NASDAQ_SCREEN`, `SRC:YAHOO_HOT`, `SRC:MANUAL`);
     - any existing ETF-seeded candidates if an upstream ETF page partially fails or rotates its top-25 holdings;
     - any user `enabled=0` overrides.
2. **Manual `ai_smallcap` Loss in `scripts/build_smallcap_universe.py`**:
   - When `scripts/build_smallcap_universe.py` rebuilds `ai_smallcap`, line 360 drops all rows where `bucket == "ai_smallcap"`, which would drop `ai_smallcap` rows carrying `SRC:MANUAL` in `data/ai_watchlist.csv` unless they are also preserved during merge.
3. **Watchlist Versioning Mandate (`AGENTS.md` §4)**:
   - *"Going forward, archive/version the watchlist produced by ETF refreshes so prospective validation uses real observed candidate-universe snapshots."*

---

## 2. Detailed Design

### 2.1 `src/ai_value_scanner/scanner.py` — Pure `merge_refreshed_watchlist` Function

Add a pure helper function in `src/ai_value_scanner/scanner.py` (and export it in `__all__` if applicable):

```python
WATCHLIST_CSV_COLUMNS = [
    "symbol",
    "bucket",
    "etf_count",
    "etfs",
    "enabled",
    "updated_utc",
]


def merge_refreshed_watchlist(
    existing: pd.DataFrame,
    refreshed_etfs: pd.DataFrame,
    *,
    prune_dropped_etf_rows: bool = False,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Safely merge freshly fetched ETF rows into an existing watchlist DataFrame.

    Returns (merged_df, stats_dict) where stats_dict contains:
      - existing_rows: int
      - fetched_etf_rows: int
      - added_rows: int
      - updated_rows: int
      - preserved_manual_or_smallcap_rows: int
      - preserved_prior_etf_rows: int
      - pruned_etf_rows: int
      - total_rows: int
      - unique_symbols: int
    """
```

#### Exact Merge Semantics:
1. **Normalize inputs**:
   - Ensure both `existing` and `refreshed_etfs` normalize `symbol` via `normalize_equity_symbol(s)` and `bucket` via `str(b).strip().lower()`. Drop rows with empty `symbol` or empty `bucket`.
   - Helper to split token strings:
     - `src_tokens(etfs_str)`: sorted set of tokens in `etfs_str.split(",")` that start with `"SRC:"` (case-insensitive, normalized to uppercase).
     - `etf_tokens(etfs_str)`: sorted set of non-empty tokens in `etfs_str.split(",")` that do **not** start with `"SRC:"` (normalized to uppercase).
2. **Index `existing` and `refreshed_etfs` by `(symbol, bucket)`**:
   - If `existing` has duplicate `(symbol, bucket)` rows, collapse them first by unioning their tokens and keeping `enabled` (`0` if explicitly `0`, else `1`).
   - If `refreshed_etfs` has duplicate `(symbol, bucket)` rows, collapse them by unioning their ETF tokens.
3. **For each `(symbol, bucket)` in `existing`**:
   - **Case 1: `(symbol, bucket)` is also in `refreshed_etfs`** (`updated_rows += 1`):
     - Keep `SRC:*` tokens from `existing` + all new ETF tokens from `refreshed_etfs` (sorted: ETF tokens first alphabetically, then `SRC:*` tokens alphabetically, joined by `","`).
     - `etf_count = len(new_etf_tokens)` (never counting `SRC:*` tokens).
     - `enabled = existing_enabled` (preserve user `0`/`1` setting).
     - `updated_utc = refreshed_row["updated_utc"]`.
   - **Case 2: `(symbol, bucket)` is NOT in `refreshed_etfs`**:
     - Check if the row is **protected**:
       - `is_protected = (bucket == "ai_smallcap") or bool(existing_src_tokens) or (existing_enabled == 0)`
     - If `is_protected`:
       - Always keep the row untouched (`preserved_manual_or_smallcap_rows += 1`), ensuring `etf_count = len(existing_etf_tokens)`.
     - Else (it was a pure ETF row in `core_ai`/`ai_enabler`/`ai_peripheral` with no `SRC:*` tokens):
       - If `not prune_dropped_etf_rows` (the default safe additive mode):
         - Keep the row untouched (`preserved_prior_etf_rows += 1`).
       - If `prune_dropped_etf_rows` is `True`:
         - Omit the row (`pruned_etf_rows += 1`).
4. **For each `(symbol, bucket)` in `refreshed_etfs` that was NOT in `existing`** (`added_rows += 1`):
   - Add the new row with `etf_count = len(new_etf_tokens)`, `etfs = ",".join(new_etf_tokens)`, `enabled = 1`, `updated_utc = refreshed_row["updated_utc"]`.
5. **Sort & Output**:
   - Sort deterministically by `["bucket", "symbol"]`, reset index, and return `(merged_df[WATCHLIST_CSV_COLUMNS], stats)`.
   - Ensure `write_csv_atomic` always writes Unix `LF` (`lineterminator="\n"`).

---

### 2.2 `scripts/refresh_ai_watchlist.py` — Safe Merge CLI, Dry-Run, and Snapshot Archiving

Update `scripts/refresh_ai_watchlist.py`:
1. Add CLI flags to `build_parser()`:
   - `--dry-run` (`action="store_true"`): fetch ETF holdings and compute the merge against existing `--output` / `cfg.watchlist_csv_path`, print merge statistics and any newly added `(symbol, bucket, etfs)` rows, and exit **without** writing or modifying any files.
   - `--prune-dropped-etf-rows` (`action="store_true"`, default `False`): opt-in to pruning prior pure-ETF rows no longer in the freshly fetched top-25 ETF holdings (while still preserving all `SRC:*` and `ai_smallcap` rows).
   - `--no-archive` (`action="store_true"`, default `False`): skip archiving to `data/watchlist_history/`.
2. In `main()`:
   - Resolve `out = Path(args.output) if args.output else Path(cfg.watchlist_csv_path)`.
   - Load `existing = pd.read_csv(out)` if `out.exists()` else empty `pd.DataFrame(columns=WATCHLIST_CSV_COLUMNS)`.
   - Fetch `refreshed = refresh_watchlist_from_etfs(cfg)`.
   - Guard against total network failure: if `refreshed.empty` and `not existing.empty`:
     - Print `[watchlist] WARNING: ETF refresh returned 0 rows; preserving existing watchlist untouched.` and return without overwriting!
   - Call `merged, stats = merge_refreshed_watchlist(existing, refreshed, prune_dropped_etf_rows=args.prune_dropped_etf_rows)`.
   - Print a clear summary line:
     ```
     [watchlist] existing={existing_rows} fetched_etf={fetched_etf_rows} added={added_rows} updated={updated_rows} preserved_protected={preserved_manual_or_smallcap_rows} preserved_etf={preserved_prior_etf_rows} pruned={pruned_etf_rows} total={total_rows} unique_symbols={unique_symbols}
     ```
   - If `args.dry_run`:
     - Print `[watchlist] dry-run complete; output not modified: {out}` and return.
   - Write `write_csv_atomic(merged, out)`.
   - If `not args.no_archive` and `out == Path(cfg.watchlist_csv_path)`:
     - Call `archive_watchlist_snapshot(cfg, datetime.now(timezone.utc))` and print the archived snapshot path.

---

### 2.3 `scripts/build_smallcap_universe.py` — Preserve `SRC:MANUAL` Rows in `ai_smallcap`

In `scripts/build_smallcap_universe.py`:
- When pruning existing `ai_smallcap` rows before concatenating `new_rows` (around lines 358–364):
  - Any existing `ai_smallcap` row in `existing` whose `etfs` column contains `"SRC:MANUAL"` (case-insensitive) and is not already in `new_rows["symbol"]` must be **preserved** (or automatically included in the manual candidate seed before `merge_universe` so it is never lost when rebuilding `ai_smallcap`)!
  - Best implementation: in `main()`, in addition to `load_manual_symbols(Path(args.manual_csv))`, also extract any existing `ai_smallcap` symbols from `existing` where `etfs` contains `"SRC:MANUAL"` and include them in the manual seed (with no cap truncation on `SRC:MANUAL` rows, or preserving any unmerged `SRC:MANUAL` `ai_smallcap` rows when pruning `existing`). Specifically: when pruning `existing` at line 360, keep `ai_smallcap` rows that carry `SRC:MANUAL` if they are not already present in `new_rows`, so zero `SRC:MANUAL` rows can ever be lost!

---

### 2.4 Documentation Updates (`README.md` & `scripts/README.md`)

- Update `README.md` §4.1 and §13.2 (`scripts/refresh_ai_watchlist.py`) to document:
  - `refresh_ai_watchlist.py` uses **safe additive merge** (`merge_refreshed_watchlist`): it updates ETF holdings and adds newly discovered ETF constituents while strictly preserving `SRC:MANUAL` rows, `ai_smallcap` rows, and user `enabled=0` flags, and automatically archives a snapshot to `data/watchlist_history/`.
  - Document `--dry-run` and `--prune-dropped-etf-rows`.

---

## 3. Unit Test Requirements

Create `tests/test_watchlist_refresh_safe_merge.py` covering:
1. **`SRC:MANUAL` & `ai_smallcap` preservation**:
   - Existing `core_ai`, `ai_enabler`, and `ai_smallcap` rows with `SRC:MANUAL` are 100% preserved when `refreshed_etfs` does not contain them.
2. **Overlap between `SRC:MANUAL` and refreshed ETFs**:
   - If `HOOD` is in `existing` as `(core_ai, 0, "SRC:MANUAL", 1)` and `refreshed_etfs` returns `HOOD` in `core_ai` with `etfs="ARKQ,IGV"`, the merged row has `etfs="ARKQ,IGV,SRC:MANUAL"` and `etf_count=2` (not `3`).
3. **Preservation of `enabled=0` overrides**:
   - If a symbol has `enabled=0` in `existing` and appears in `refreshed_etfs`, `enabled` remains `0`.
4. **Default additive mode vs `--prune-dropped-etf-rows`**:
   - Default (`prune_dropped_etf_rows=False`) keeps prior pure-ETF rows not in `refreshed_etfs`;
   - `prune_dropped_etf_rows=True` removes prior pure-ETF rows not in `refreshed_etfs`, while still keeping all `SRC:*` and `ai_smallcap` rows.
5. **Total network failure guard & `--dry-run` CLI**:
   - Mocking `refresh_watchlist_from_etfs` to return an empty DataFrame leaves the existing CSV file byte-for-byte untouched;
   - Running `refresh_ai_watchlist.py --dry-run` with mocked ETF rows prints stats and leaves the existing CSV file byte-for-byte untouched.
6. **`build_smallcap_universe.py` `SRC:MANUAL` preservation**:
   - Rebuilding `ai_smallcap` preserves existing `ai_smallcap` rows tagged with `SRC:MANUAL`.
