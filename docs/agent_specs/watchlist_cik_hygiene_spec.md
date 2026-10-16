# Agent Specification: Automatic CIK-Based Ticker Rename Migration & Delisting Hygiene

- **Date**: 2026-10-16
- **Baseline**: `main` @ `20e5a77` (PR #94)
- **Target Execution Agent**: DeepSeek (implementation + unit tests only; no Git state mutations or live network calls)
- **Reviewer / Integrator**: Architect Agent

---

## 1. Problem & Motivation

When companies in `data/ai_watchlist.csv` (or `data/ai_smallcap_manual.csv`) undergo corporate actions:
1. **Ticker Renames / Rebrands** (e.g., `EQR -> VMRK`, `SATS -> ECHO`, `BITF -> KEEL`, `GREE -> VIP`, `GRYP -> ABTC`, `ANY -> DRK`, `BTOG -> SGRX`, `MOGO -> ORIO`):
   - A company's 10-digit SEC `CIK` never changes across name or ticker changes.
   - Local `cache/parsed_fund_{cik}.json` and `cache/submissions_{cik}.json` already store the historical `(symbol, cik)` binding for every stock we have scanned, while SEC's `company_tickers.json` maps that same `CIK` to the company's current ticker(s).
2. **M&A / Privatization Delistings** (e.g., `CYBR`, `CFLT`, `QRVO`, `WBD`, `AVB`, `DBRG`, `SKYT`, `SMLR`):
   - Once a company delists (Form `15-12G` / `15-15D` / `25`), it is marked `inactive` (`tradable=false`) in Alpaca `/v2/assets` and/or removed from SEC `company_tickers.json`, with no active replacement common-stock ticker under its `CIK`.
3. **Goal**:
   - Add a pure, deterministic corporate-action reconciliation pass `reconcile_watchlist_corporate_actions(...)` in `src/ai_value_scanner/scanner.py` and integrate it into `scripts/refresh_ai_watchlist.py` (enabled by default, with `--no-reconcile-corporate-actions` opt-out and full `--dry-run` reporting) so that every watchlist refresh automatically:
     - **migrates renamed tickers** (`OLD -> NEW`) via `CIK` continuity while preserving `bucket`, `etfs` (`SRC:MANUAL`, etc.), and `enabled` flags;
     - **prunes confirmed delisted/inactive tickers** that have no active replacement under their `CIK`;
     - optionally reconciles `data/ai_smallcap_manual.csv` at the same time so manual seed files never re-inject retired tickers on future smallcap rebuilds.

---

## 2. Detailed Design

### 2.1 `src/ai_value_scanner/scanner.py` — Cache & SEC/Alpaca Helpers + `reconcile_watchlist_corporate_actions`

1. **Helper: `load_cached_symbol_to_cik(cache_dir: str | Path = "cache") -> dict[str, str]`**:
   - Scans `Path(cache_dir).glob("parsed_fund_*.json")` and `Path(cache_dir).glob("submissions_*.json")` (read-only, ignoring corrupt files).
   - From `parsed_fund_{cik}.json`: extracts `symbol = normalize_equity_symbol(payload.get("symbol"))` and 10-digit `cik = str(payload.get("cik") or path.stem.split("_")[-1]).strip().zfill(10)`.
   - From `submissions_{cik}.json`: extracts `cik = path.stem.split("_")[-1].strip().zfill(10)` and each ticker in `payload.get("tickers") or []` via `normalize_equity_symbol(t)`.
   - Returns `dict[str, str]` mapping `normalized_symbol -> 10-digit cik` (`parsed_fund` takes precedence over `submissions`).

2. **Helper: `build_sec_ticker_cik_maps(sec_rows: Iterable[dict[str, Any]]) -> tuple[dict[str, str], dict[str, list[str]]]`**:
   - Given rows with `{"symbol": ..., "cik": ...}` (such as `SecClient.ticker_mapping_snapshot()["frame"].to_dict("records")` or raw `company_tickers.json` entries):
   - Normalizes each symbol via `normalize_equity_symbol(r.get("symbol") or r.get("ticker"))` and `cik = str(r.get("cik") or r.get("cik_str") or "").strip().zfill(10)`.
   - Returns `(sec_ticker_to_cik, sec_cik_to_tickers)` where:
     - `sec_ticker_to_cik[norm_sym] = cik`
     - `sec_cik_to_tickers[cik]` is a deduplicated `list[str]` of normalized symbols in the order they appear in SEC's table (SEC orders primary common stock before preferred/warrants).

3. **Pure Function: `reconcile_watchlist_corporate_actions`**:
   ```python
   def reconcile_watchlist_corporate_actions(
       watchlist: pd.DataFrame,
       *,
       sec_ticker_to_cik: Mapping[str, str],
       sec_cik_to_tickers: Mapping[str, Sequence[str]],
       historical_symbol_to_cik: Mapping[str, str] | None = None,
       active_alpaca_symbols: Set[str] | None = None,
   ) -> tuple[pd.DataFrame, dict[str, Any]]:
       """Reconcile ticker renames (via CIK continuity) and prune delisted symbols.

       Safety contract:
       - If `sec_ticker_to_cik` is empty, returns `(watchlist, empty_report)`
         unchanged (never prunes when SEC reference mapping is unavailable).
       - Returns `(reconciled_df, report)` where `report` contains:
         - `"renamed"`: list of `{"old_symbol": str, "new_symbol": str, "cik": str, "bucket": str}`
         - `"removed_delisted"`: list of `{"symbol": str, "cik": str | None, "bucket": str, "reason": str}`
         - `"renamed_count"`: int (number of rows renamed)
         - `"removed_count"`: int (number of rows removed)
       """
   ```

4. **Exact Decision Logic Inside `reconcile_watchlist_corporate_actions`**:
   - If `watchlist is None` or `watchlist.empty` or not `sec_ticker_to_cik`:
     return `(watchlist if watchlist is not None else pd.DataFrame(columns=WATCHLIST_CSV_COLUMNS), {"renamed": [], "removed_delisted": [], "renamed_count": 0, "removed_count": 0})`.
   - Normalize `active_alpaca_norm: set[str] | None`:
     - If `active_alpaca_symbols is not None` and len(active_alpaca_symbols) > 0:
       `{normalize_equity_symbol(s) for s in active_alpaca_symbols if normalize_equity_symbol(s)}`
     - Else: `None` (if an empty set is passed or Alpaca assets weren't fetched, treat as `None` so a transient Alpaca outage never mass-prunes the watchlist!).
   - Define helper `_in_sec(sym: str) -> bool`:
     `sym in sec_ticker_to_cik or sym.replace(".", "-") in sec_ticker_to_cik`
   - Define helper `_in_alpaca(sym: str) -> bool`:
     `active_alpaca_norm is None or sym in active_alpaca_norm or sym.replace(".", "-") in active_alpaca_norm`
   - Define helper `_is_likely_common_ticker(sym: str) -> bool`:
     - Returns `False` if `"-P"` in `sym` or `".P"` in `sym` (preferred series like `DBRG-PH`), or if `len(sym) == 5 and sym.endswith(("W", "R", "U"))` when the 4-letter base is not in SEC, wait — keep it simple: exclude symbols containing `"-"` or `"."` unless no other candidate exists, and when `active_alpaca_norm is not None`, require `_in_alpaca(cand)`!
     - Even simpler and more exact: for a given `cik`, candidate replacement tickers are `[c for c in sec_cik_to_tickers.get(cik, ()) if c and c != norm_sym and "-" not in c and "." not in c and _in_alpaca(c)]`.
       - Also guard against 5-letter OTC/preferred debt tickers (like `GREEL` or `HXSCL` when `VIP` or `SKHY` is first): since SEC `company_tickers.json` lists the primary exchange ticker first (e.g. `['VIP', 'GREEL']`, `['SKHY', 'HXSCL']`), picking `candidates[0]` when `active_alpaca_norm` confirms `_in_alpaca(candidates[0])` (or when `active_alpaca_norm is None` and `not (len(candidates[0]) == 5 and candidates[0].endswith(("L", "P", "W", "F")))`) selects the exact primary common ticker!
   - For each row in `watchlist`:
     - Let `norm_sym = normalize_equity_symbol(row["symbol"])`, `bucket = str(row["bucket"]).strip().lower()`.
     - **If `_in_sec(norm_sym)` and `_in_alpaca(norm_sym)`**:
       - Keep row unchanged!
     - **Else (symbol is missing in SEC `company_tickers.json` OR inactive in Alpaca)**:
       - Resolve `cik = (historical_symbol_to_cik or {}).get(norm_sym) or sec_ticker_to_cik.get(norm_sym) or sec_ticker_to_cik.get(norm_sym.replace(".", "-"))`.
       - Look for a replacement ticker `new_sym` in `sec_cik_to_tickers.get(cik, ())` where:
         - `new_sym != norm_sym`
         - `"-" not in new_sym and "." not in new_sym`
         - `_in_alpaca(new_sym)` is `True`
         - Not a 5-letter senior-note/OTC suffix (`not (len(new_sym) == 5 and new_sym.endswith(("L", "P", "W", "Z", "F")))`)
       - **If `new_sym` is found**:
         - Rewrite `row["symbol"] = new_sym` and append `{"old_symbol": norm_sym, "new_symbol": new_sym, "cik": cik, "bucket": bucket}` to `report["renamed"]`.
       - **Else (no active replacement ticker for this CIK)**:
         - Drop the row and append `{"symbol": norm_sym, "cik": cik, "bucket": bucket, "reason": "missing_in_sec" if not _in_sec(norm_sym) else "inactive_in_alpaca"}` to `report["removed_delisted"]`.
   - After processing all rows, collapse any duplicate `(symbol, bucket)` pairs created when `old_sym -> new_sym` merged into an existing `(new_sym, bucket)` row (reusing `_collapse_watchlist_rows` so `etfs` and `SRC:*` tokens are unioned and `etf_count` is recomputed!).

5. **Helper: `reconcile_manual_seed_csv(manual_csv_path: Path, report: Mapping[str, Any], *, dry_run: bool = False) -> dict[str, int]`**:
   - Given `report` from `reconcile_watchlist_corporate_actions` (which has `renamed` and `removed_delisted`):
   - If `manual_csv_path.exists()`:
     - Build `rename_map = {item["old_symbol"]: item["new_symbol"] for item in report.get("renamed", [])}` and `remove_set = {item["symbol"] for item in report.get("removed_delisted", [])}`.
     - Read `manual_csv_path` (`symbol,note`), apply `rename_map` and drop `remove_set`, deduplicate by `symbol` preserving order, and if changed and `not dry_run`, write back with Unix `LF` (`lineterminator="\n"`).
     - Return `{"renamed": n_renamed, "removed": n_removed}`.

---

### 2.2 `scripts/refresh_ai_watchlist.py` — Integrate Corporate-Action Reconciliation

Update `scripts/refresh_ai_watchlist.py`:
1. Add CLI arguments:
   - `--no-reconcile-corporate-actions` (`action="store_true"`, default `False`): skip CIK-based rename migration and delisting hygiene.
   - `--manual-seed-csv` (`default="data/ai_smallcap_manual.csv"`): path to the smallcap manual seed CSV to keep in sync when corporate actions are reconciled.
2. When `not args.no_reconcile_corporate_actions`:
   - Load `historical_symbol_to_cik = load_cached_symbol_to_cik(cfg.cache_dir)`.
   - Fetch SEC ticker mapping via `SecClient` (if `SEC_USER_AGENT` is available in env/dotenv; if not or if network fails, print a warning and skip reconciliation gracefully without failing `refresh_ai_watchlist.py`).
   - Optionally fetch active tradable US equities from Alpaca `/v2/assets?status=active&asset_class=us_equity` (if `ALPACA_API_KEY` and `ALPACA_API_SECRET` are available in env/dotenv; if not or if network fails, pass `active_alpaca_symbols=None` and reconcile using SEC `company_tickers.json` + `historical_symbol_to_cik`).
   - Run `merged, ca_report = reconcile_watchlist_corporate_actions(merged, sec_ticker_to_cik=..., sec_cik_to_tickers=..., historical_symbol_to_cik=..., active_alpaca_symbols=...)`.
   - Print a summary line:
     ```
     [watchlist] corporate_actions renamed={renamed_count} removed_delisted={removed_count}
     ```
     And for each rename/removal, print:
     - `[watchlist] ~ {old_symbol} -> {new_symbol} ({bucket}, cik={cik})`
     - `[watchlist] - {symbol} ({bucket}, cik={cik}, reason={reason})`
   - Also call `reconcile_manual_seed_csv(Path(args.manual_seed_csv), ca_report, dry_run=args.dry_run)`.

---

### 2.3 Documentation Updates (`README.md` & `scripts/README.md`)

- Update `README.md` §4.1 and §13.2 and `scripts/README.md` to document that `scripts/refresh_ai_watchlist.py` automatically reconciles corporate actions (CIK-based ticker rename migration `OLD -> NEW` and delisted/inactive ticker removal across both `data/ai_watchlist.csv` and `data/ai_smallcap_manual.csv`, with `--no-reconcile-corporate-actions` to opt out).

---

## 3. Unit Test Requirements

Extend `tests/test_watchlist_refresh_safe_merge.py` with a `TestCorporateActionReconciliation` test class (100% offline mocked, zero network calls) covering:
1. **CIK-based rename migration (`BITF -> KEEL`, `EQR -> VMRK`, `SATS -> ECHO`)**:
   - `BITF` (`ai_smallcap`, `SRC:MANUAL`) is missing from `sec_ticker_to_cik`, `historical_symbol_to_cik` maps `"BITF": "0001812477"`, and `sec_cik_to_tickers["0001812477"]` is `["KEEL"]`:
     - Row is automatically migrated to `KEEL` (`ai_smallcap`, `SRC:MANUAL`, `etf_count=0`).
2. **Rename into an already-present target ticker merges cleanly (`EQR -> VMRK`)**:
   - If `EQR` (`ai_peripheral`, `VNQ,SRC:MANUAL`) renames to `VMRK` and `VMRK` (`ai_peripheral`, `VNQ,XLRE`) is already in the watchlist, the reconciled watchlist has a single `(VMRK, ai_peripheral)` row with `etfs="VNQ,XLRE,SRC:MANUAL"` and `etf_count=2`.
3. **Delisting removal (`CYBR`, `CFLT`, `WBD`, `QRVO`, `DBRG-PH` preferred-only guard)**:
   - `CYBR` (missing from `sec_ticker_to_cik`, CIK `0001598110` has `[]` in `sec_cik_to_tickers`) is removed with `reason="missing_in_sec"`.
   - `WBD` (still in `sec_ticker_to_cik`, but absent from `active_alpaca_symbols` and no other active common ticker under its CIK) is removed with `reason="inactive_in_alpaca"`.
   - `DBRG` (common stock delisted; `sec_cik_to_tickers` only has preferred/debt tickers `["DBRG-PH", "DBRHP"]`) does **not** migrate to preferred/debt ticker and is removed as delisted.
   - `GREE` (CIK has `["VIP", "GREEL"]` where `GREEL` is a 5-letter baby bond) migrates to `VIP`, not `GREEL`.
4. **Safety guards**:
   - When `sec_ticker_to_cik` is empty (e.g. SEC offline), `reconcile_watchlist_corporate_actions` leaves the watchlist 100% untouched.
   - `reconcile_manual_seed_csv` renames `BITF -> KEEL` and removes `CYBR` in `ai_smallcap_manual.csv` (and respects `dry_run=True`).
   - `load_cached_symbol_to_cik` reads synthetic `parsed_fund_*.json` and `submissions_*.json` fixtures.
