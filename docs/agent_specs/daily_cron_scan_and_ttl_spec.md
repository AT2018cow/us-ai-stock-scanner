# Daily Cron Pipeline Spec — Single-Responsibility Separation (`refresh_sec_cache.py` vs `run_daily_cron.py`) & Two-Tier Freshness TTL

> **Target Agent**: Muse Spark 1.3 (Execution Agent)
> **Reviewer**: Chief Technical Lead / Architect
> **Base `main` Reference**: Post-PR #84 (`1e0a861`)

---

## 1. Objective & Single-Responsibility Architecture

In PR #84, Stage 2 (`run_scan`) was embedded directly inside `scripts/refresh_sec_cache.py`. However, a script named `refresh_sec_cache.py` must adhere strictly to the **Single Responsibility Principle (SRP)**:
- **`scripts/refresh_sec_cache.py`**: Must **ONLY** refresh and validate the SEC parsed cache. Running `python scripts/refresh_sec_cache.py` must NEVER trigger a stock scan or generate daily reports.
- **`run_scan.py`**: Runs the stock scan and generates the daily/weekly reports and immutable decision snapshot.
- **`scripts/run_daily_cron.py` (NEW — Dedicated Daily Cron Orchestrator)**: Explicitly named orchestrator for the daily `11:00` local (`23:00 EDT` / `22:00 EST`) cron job that executes:
  - **Stage 1**: Calls `refresh_sec_cache.run_sec_prewarm(...)` with `--max-age-hours 4.0` (`14400s`);
  - **Stage 2**: Immediately runs `run_daily_scan_after_prewarm(...)` (with 1-hour `3600s` Alpaca TTL override and `allow_existing_decision_snapshot=True`) to generate the daily MVP v2 reports and update `outputs/decisions/latest_<style>.json`.

---

## 2. Shared-Worktree Safety & Allowed Files

### Shared-Worktree Rules:
- **DO NOT** run `git checkout`, `git switch`, `git branch`, `git add`, `git commit`, `git push`, `git stash`, `git reset`, or `git clean`.
- **DO NOT** make any live network calls in unit tests.
- Never output absolute filesystem paths (`/home/...` or `/tmp/...`) in any generated file or pointer JSON.

### Allowed to Modify / Create:
1. `scripts/refresh_sec_cache.py` **(MODIFY — restore pure SEC-cache-only responsibility; remove `run_scan` import, remove `run_daily_scan_after_prewarm`, remove `--skip-scan`; expose reusable `run_sec_prewarm(cfg, *, repo, user_agent, max_age_hours=4.0, limit=0) -> dict[str, Any]`)**
2. `scripts/run_daily_cron.py` **(NEW — dedicated daily cron orchestrator containing `run_daily_scan_after_prewarm(...)` and `main()` that runs Stage 1 `run_sec_prewarm` + Stage 2 `run_daily_scan_after_prewarm`)**
3. `tests/test_daily_cron_scan_and_ttl.py` **(MODIFY — update tests to verify `refresh_sec_cache.py` is 100% pure SEC prewarm without `run_scan`, and `scripts/run_daily_cron.py` orchestrates Stage 1 + Stage 2)**
4. `README.md` **(MODIFY — briefly document `scripts/run_daily_cron.py` vs `scripts/refresh_sec_cache.py` in the CLI / cron section)**

---

## 3. Exact Implementation Requirements

### 3.1 Pure SEC Cache Refresh in `scripts/refresh_sec_cache.py`
1. Remove `run_scan` from the `from ai_value_scanner.scanner import (...)` block in `scripts/refresh_sec_cache.py`.
2. Remove `run_daily_scan_after_prewarm` and `--skip-scan` from `scripts/refresh_sec_cache.py`.
3. Extract the body of `main()`'s SEC prewarm execution into a clean function in `scripts/refresh_sec_cache.py`:
   ```python
   def run_sec_prewarm(
       cfg: ScanConfig,
       *,
       repo: Path,
       user_agent: str,
       max_age_hours: float = 4.0,
       limit: int = 0,
   ) -> dict[str, Any]:
   ```
   - `run_sec_prewarm` creates `monitor = NetworkMonitor()` and `sec = SecClient(...)` (using `rsc.SecClient` so existing mocks on `refresh_sec_cache.SecClient`, `refresh_sec_cache.collect_symbols`, and `refresh_sec_cache.refresh_symbols` in `tests/test_refresh_sec_cache_retry.py` continue to work 100% identically!).
   - Calls `collect_symbols(repo, cfg)`, applies `limit`, logs summary, logs `no_cik` and `conflicted`, and when `not (limit and limit > 0)` calls `record_pending_streaks(...)`.
   - Always closes `sec.session.close()` in `finally:` and returns `summary` (or exits `1` if `not symbols`).
4. In `scripts/refresh_sec_cache.py`'s `main()`:
   - Parse `--config` (default `"configs/config.risk_off.json"`), `--max-age-hours` (default `4.0`), `--limit` (default `0`).
   - Validate `SEC_USER_AGENT`, `0 < args.max_age_hours <= 24`, `cfg.sec_cache_ttl_submissions_sec > 0`.
   - Call `summary = run_sec_prewarm(cfg, repo=repo, user_agent=user_agent, max_age_hours=args.max_age_hours, limit=args.limit)`.
   - Never call `run_scan`!
   - If `summary["failed"] or summary["aborted"] or summary["conflicted"]`: `sys.exit(1)`.

### 3.2 Dedicated Daily Cron Orchestrator in `scripts/run_daily_cron.py`
Create `scripts/run_daily_cron.py`:
1. Imports `run_sec_prewarm`, `log`, `ScanConfig`, `load_config` from `refresh_sec_cache` (or `ai_value_scanner.scanner`) and `run_scan` from `ai_value_scanner.scanner`.
2. Defines `run_daily_scan_after_prewarm(cfg: ScanConfig, *, config_path: str, summary: Mapping[str, Any], limit: int = 0, skip_scan: bool = False, alpaca_ttl_sec: int = 3600, scan_fn: Callable[..., Any] | None = None) -> dict[str, Any]`:
   - If `skip_scan or (limit and limit > 0)`:
     return `{"scan_executed": False, "scan_failed": False, "reason": "skipped_by_flag_or_limit"}`.
   - If `summary.get("aborted") is True or bool(summary.get("conflicted"))`:
     return `{"scan_executed": False, "scan_failed": False, "reason": "aborted_or_conflicted_prewarm"}`.
   - Clones `cfg` via `dataclasses.replace` setting:
     - `alpaca_cache_ttl_assets_sec=min(cfg.alpaca_cache_ttl_assets_sec, alpaca_ttl_sec)`
     - `alpaca_cache_ttl_snapshots_sec=min(cfg.alpaca_cache_ttl_snapshots_sec, alpaca_ttl_sec)`
     - `alpaca_cache_ttl_bars_sec=min(cfg.alpaca_cache_ttl_bars_sec, alpaca_ttl_sec)`
   - Calls `(scan_fn or run_scan)(scan_cfg, scan_config_path=config_path, allow_existing_decision_snapshot=True)`.
   - Returns `{"scan_executed": True, "scan_failed": False, "output_path": str(out_path)}` (or catches `Exception` and returns `{"scan_executed": False, "scan_failed": True, "error": str(exc)}`).
3. Defines `main() -> None` in `scripts/run_daily_cron.py`:
   - CLI arguments:
     - `--config` (default `"configs/config.risk_off.json"`)
     - `--max-age-hours` (type `float`, default `4.0`)
     - `--alpaca-ttl-sec` (type `int`, default `3600`)
     - `--limit` (type `int`, default `0`)
     - `--skip-scan` (`action="store_true"`, default `False`)
   - Loads `.env`, validates `SEC_USER_AGENT`, `0 < args.max_age_hours <= 24`, `args.alpaca_ttl_sec > 0`, `cfg.sec_cache_ttl_submissions_sec > 0`.
   - Stage 1: `summary = run_sec_prewarm(cfg, repo=repo, user_agent=user_agent, max_age_hours=args.max_age_hours, limit=args.limit)`
   - Stage 2: If `not args.skip_scan and not (args.limit and args.limit > 0)`:
     - If `os.getenv("ALPACA_API_KEY", "").strip()` is non-empty:
       call `scan_res = run_daily_scan_after_prewarm(cfg, config_path=args.config, summary=summary, limit=args.limit, skip_scan=args.skip_scan, alpaca_ttl_sec=args.alpaca_ttl_sec)`
       if `scan_res.get("scan_failed")`: `sys.exit(1)`
     - Else:
       log `WARNING: ALPACA_API_KEY not set; skipping Stage 2 daily scan`
   - If `summary["failed"] or summary["aborted"] or summary["conflicted"]`: `sys.exit(1)`.

---

## 4. Verification Commands

Run locally:
```bash
.venv/bin/python -m unittest discover -s tests -p "test_daily_cron_scan_and_ttl.py"
.venv/bin/python -m unittest discover -s tests -p "test_refresh_sec_cache_retry.py"
.venv/bin/python -m unittest discover -s tests -p "test_m5_opt_in_cli_and_shadow_snapshot.py"
.venv/bin/python -m unittest discover -s tests
```
When all tests pass, stop and report for Chief Architect review.
