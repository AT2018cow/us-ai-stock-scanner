# Daily Cron Pipeline Spec — Unified SEC Prewarm + MVP v2 Scan & Two-Tier Freshness TTL

> **Target Agent**: Muse Spark 1.3 (Execution Agent)
> **Reviewer**: Chief Technical Lead / Architect
> **Base `main` Reference**: Post-PR #83 (`6e59510`)

---

## 1. Objective & Crontab Context

On the production machine (timezone `UTC+8`), the system crontab runs daily at **`10:30` local time** (`22:30 EDT`, after the `16:00 EDT` US market close and after the `22:00 EDT` SEC EDGAR filing cutoff):
```cron
30 10 * * * cd /home/ss/opencode_ws/us-ai-stock-scanner && .venv/bin/python scripts/refresh_sec_cache.py >> .debug_logs/sec_refresh_cron.log 2>&1
```

Why a flat 20-hour TTL is **too long**:
If the user runs a manual test scan late at night (e.g., `00:30–02:30` local time, which is only `8–10` hours before the `10:30` cron job), a `20h` or `12h` TTL would still be considered "fresh" at `10:30`, causing the `10:30` cron job to skip fetching the new day's post-close Alpaca bars and post-22:00-ET SEC filings!

To guarantee that **the `10:30` cron job ALWAYS fetches the latest SEC and Alpaca data**, while **Stage 2 of cron (`run_scan`) 100% reuses Stage 1's just-refreshed SEC caches** and **back-to-back manual runs within a 6-hour window don't re-fetch every 2 minutes**, we implement a **Two-Tier TTL & Unified Cron Pipeline**:

---

## 2. Two-Tier TTL Architecture

| Layer | Setting / Location | Value | Exact Behavior |
| :--- | :--- | :---: | :--- |
| **Cron Stage 1 (SEC Refresh)** | `refresh_sec_cache.py` default `--max-age-hours` | **`4.0` hours (`14400s`)** | Any SEC cache from yesterday's cron (`24h` ago) OR from a late-night manual test (`00:00–02:30`, `8–10h` ago) is expired (`> 4h`), so **Cron at `10:30` ALWAYS fetches the latest SEC filings**. |
| **Cron Stage 2 (Daily Scan)** | `run_daily_scan_after_prewarm` in `refresh_sec_cache.py` | Alpaca TTL overridden to **`3600s` (`1h`)**; SEC uses Stage 1 cache | Runs immediately (~`10:45`, 15 min after Stage 1): **100% hits the SEC `parsed_fund` caches just written by Stage 1**, while `1h` Alpaca TTL guarantees **Cron ALWAYS fetches fresh post-close Alpaca daily bars & snapshots**! |
| **Manual / Interactive Runs** | `configs/config.risk_off.json`, `config.risk_on.json`, `config.strict_candidate.json`, `ScanConfig` | **`21600s` (`6h`)** for `assets`, `snapshots`, `bars` | Replaces the old `120s` (2-minute) snapshot TTL with `6 hours` (`21600s`): back-to-back manual runs in the same research session hit local cache, without ever spanning across market sessions. |
| **SEC Pending Cooldown** | `PENDING_CHECKED_SCAN_COOLDOWN_SEC` in `scanner.py` | **`21600.0s` (`6h`)** | Unpatchable pending filings (`20-F`, etc.) checked by Cron Stage 1 at `10:30` are cached for Cron Stage 2 (`10:45`) and daytime manual runs (`10:30–16:30`), while expiring before the next day's cron. |

---

## 3. Shared-Worktree Safety & Allowed Files

### Shared-Worktree Rules:
- **DO NOT** run `git checkout`, `git switch`, `git branch`, `git add`, `git commit`, `git push`, `git stash`, `git reset`, or `git clean`.
- **DO NOT** make any live network calls in unit tests.
- Never output absolute filesystem paths (`/home/...` or `/tmp/...`) in any generated file or pointer JSON.

### Allowed to Modify / Create:
1. `src/ai_value_scanner/config.py` **(MODIFY — set default `alpaca_cache_ttl_assets_sec`, `alpaca_cache_ttl_snapshots_sec`, and `alpaca_cache_ttl_bars_sec` to `21600`)**
2. `configs/config.risk_off.json`, `configs/config.risk_on.json`, `configs/config.strict_candidate.json` **(MODIFY — set `alpaca_cache_ttl_assets_sec`, `alpaca_cache_ttl_snapshots_sec`, and `alpaca_cache_ttl_bars_sec` to `21600`)**
3. `src/ai_value_scanner/scanner.py` **(MODIFY — set `PENDING_CHECKED_SCAN_COOLDOWN_SEC = 21600.0`; add `allow_existing_decision_snapshot: bool = False` to `run_scan`; and write `outputs/decisions/latest_<style>.json` pointer when `max_symbols is None`)**
4. `scripts/refresh_sec_cache.py` **(MODIFY — change default `--max-age-hours` from `20.0` to `4.0`; add `--skip-scan` CLI flag and `run_daily_scan_after_prewarm(...)` which sets `cfg.alpaca_cache_ttl_assets_sec = 3600`, `cfg.alpaca_cache_ttl_snapshots_sec = 3600`, `cfg.alpaca_cache_ttl_bars_sec = 3600` before calling `run_scan(..., allow_existing_decision_snapshot=True)`)**
5. `tests/test_m5_opt_in_cli_and_shadow_snapshot.py` **(MODIFY — update the Alpaca TTL assertion from `43200` to `21600`)**
6. `tests/test_daily_cron_scan_and_ttl.py` **(NEW — unit tests covering the `21600s` [6h] interactive TTLs, `4.0h` cron SEC `--max-age-hours`, `3600s` [1h] cron Stage 2 Alpaca TTL override, `run_daily_scan_after_prewarm` execution & skip rules, idempotent weekend/same-session snapshot preservation, and `latest_<style>.json` pointer generation)**

---

## 4. Exact Implementation Requirements

### 4.1 Idempotent Snapshot Handling & `latest_<style>.json` Pointer in `src/ai_value_scanner/scanner.py`
In `run_scan` (`src/ai_value_scanner/scanner.py`):
1. Add keyword argument `allow_existing_decision_snapshot: bool = False` to `run_scan(...)`.
2. Before calling `write_decision_snapshot(output_root=snapshot_root, strategy_style=config.strategy_style, ...)`:
   - Check `existing_paths = decision_snapshot_paths(snapshot_root, decision_date, strategy_style=config.strategy_style)`.
   - If `allow_existing_decision_snapshot and existing_paths.root.exists()`:
     - Do NOT call `write_decision_snapshot` (which would raise `FileExistsError`).
     - Instead, set `decision_snapshot_root = existing_paths.root` and log:
       `log_status(started_at, "INFO", f"MVP decision snapshot already exists for {decision_date}/{config.strategy_style}: {existing_paths.root} (preserved immutable snapshot)")`
   - Otherwise, call `write_decision_snapshot(...)` as normal.
3. Whenever `decision_snapshot_root is not None` and `config.max_symbols is None`:
   - Write a compact JSON pointer file at `Path(snapshot_root) / f"latest_{config.strategy_style or 'default'}.json"` containing relative paths (or repo-relative strings, never `/home/...` or `/tmp/...` when inside the repo; if `snapshot_root` is a temp dir in a unit test, store relative paths relative to `snapshot_root`, e.g. `"2026-10-15/risk_off/action_list.md"`, so `contains_absolute_path` is always `False`!):
     ```json
     {
       "decision_date": "2026-10-15",
       "strategy_style": "risk_off",
       "decision_policy_version": "v2",
       "report_layout_version": "v2",
       "snapshot_dir": "2026-10-15/risk_off",
       "action_list_md": "2026-10-15/risk_off/action_list.md",
       "weekly_review_md": "2026-10-15/risk_off/weekly_review.md",
       "run_manifest_json": "2026-10-15/risk_off/run_manifest.json"
     }
     ```

### 4.2 Two-Stage Daily Cron in `scripts/refresh_sec_cache.py`
In `scripts/refresh_sec_cache.py`:
1. Change `--max-age-hours` default from `20.0` to **`4.0`** (`14400s`).
2. Add `--skip-scan` (`action="store_true", default=False`) to `parser`.
3. Implement `run_daily_scan_after_prewarm(cfg: ScanConfig, *, config_path: str, summary: Mapping[str, Any], limit: int = 0, skip_scan: bool = False, scan_fn: Callable[..., Any] | None = None) -> dict[str, Any]`:
   - If `skip_scan` is `True` or `(limit and limit > 0)`:
     return `{"scan_executed": False, "scan_failed": False, "reason": "skipped_by_flag_or_limit"}`.
   - If `summary.get("aborted")` is `True` or `bool(summary.get("conflicted"))`:
     return `{"scan_executed": False, "scan_failed": False, "reason": "aborted_or_conflicted_prewarm"}`.
   - Clone/copy `cfg` (e.g. ` dataclasses.replace(cfg, alpaca_cache_ttl_assets_sec=min(cfg.alpaca_cache_ttl_assets_sec, 3600), alpaca_cache_ttl_snapshots_sec=min(cfg.alpaca_cache_ttl_snapshots_sec, 3600), alpaca_cache_ttl_bars_sec=min(cfg.alpaca_cache_ttl_bars_sec, 3600))` or mutate a copy) so Stage 2 forces a 1-hour (`3600s`) Alpaca freshness window to guarantee fresh post-close market data at `10:30` even if a manual scan ran the night before!
   - Call `(scan_fn or run_scan)(scan_cfg, scan_config_path=config_path, allow_existing_decision_snapshot=True)`.
   - Return `{"scan_executed": True, "scan_failed": False, "output_path": str(out_path)}`.
   - If `scan_fn` raises an exception, log `ERROR: daily MVP scan failed: {type(exc).__name__}: {exc}` and return `{"scan_executed": False, "scan_failed": True, "error": str(exc)}`.
4. In `main()` of `scripts/refresh_sec_cache.py`:
   - After `refresh_symbols` and `record_pending_streaks`, if `not args.skip_scan and not (args.limit and args.limit > 0)`:
     - Check if `os.getenv("ALPACA_API_KEY", "").strip()` is non-empty:
       - If non-empty: call `scan_res = run_daily_scan_after_prewarm(cfg, config_path=args.config, summary=summary, limit=args.limit, skip_scan=args.skip_scan)`. If `scan_res.get("scan_failed")`, exit `1`.
       - If empty (e.g. in unit tests that only set `SEC_USER_AGENT` without Alpaca credentials): log `WARNING: ALPACA_API_KEY not set; skipping Stage 2 daily scan`.

---

## 5. Verification Commands

Run locally:
```bash
.venv/bin/python -m unittest discover -s tests -p "test_daily_cron_scan_and_ttl.py"
.venv/bin/python -m unittest discover -s tests -p "test_refresh_sec_cache_retry.py"
.venv/bin/python -m unittest discover -s tests -p "test_m5_opt_in_cli_and_shadow_snapshot.py"
.venv/bin/python -m unittest discover -s tests
```
When all tests pass, stop and report for Chief Architect review.
