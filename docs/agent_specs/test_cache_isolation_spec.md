# Agent Specification: Test Cache Isolation (No Real `cache/` Writes From Unit Tests)

- **Date**: 2026-10-17
- **Baseline**: `main` @ `a273da2` (PR #95)
- **Target Execution Agent**: DeepSeek (test-file edits + unit tests only; no Git state mutations or live network calls; **tests-only PR — do not modify production code or `data/` / `cache/`**)
- **Reviewer / Integrator**: Architect Agent

---

## 1. Problem & Empirical Findings

A full-suite run (`python -m unittest discover -s tests`) currently **mutates exactly two files inside the real repo `cache/` directory** (verified by a before/after `find cache -type f -printf "%p %T@\n" | sort` sweep of all 4,326 cache files: exactly 2 changed, 0 added, 0 removed):

1. **`cache/parsed_fund_0001329099.json`** — written by `tests/test_gap12_metrics.py`, class `Gap12MetricTests`:
   - The BIDU test calls `load_one_fundamental(sec, "BIDU", "0001329099", cfg)` with `cfg = ScanConfig(use_ttm_metrics=True)` (default `cache_dir="cache"`).
   - Because the real `cache/submissions_0001329099.json` exists, `load_one_fundamental`'s persist guard passes and it writes the parsed-fund cache into the real repo cache.
2. **`cache/sec_pending_streaks.json`** — written by `tests/test_daily_cron_scan_and_ttl.py`, class `RefreshPurityTests`:
   - `test_main_never_scans_even_with_credentials` calls `_run_main([], ...)` → `rsc.main()` → real `run_sec_prewarm(..., limit=0)`.
   - With no `--limit`, `run_sec_prewarm` calls the real `record_pending_streaks(cfg.cache_dir, ...)` (production diagnostics path), writing `cache/sec_pending_streaks.json` with the mocked summary's `processed_ciks=["1"]`.

CI is unaffected (fresh checkout has no `cache/`), but local runs repeatedly rewrite shared production cache files. Tests must be hermetic.

---

## 2. Detailed Design (test-file changes only)

### 2.1 `tests/test_gap12_metrics.py` — Isolated Cache Dir in `Gap12MetricTests`

1. Add `import tempfile` and `from pathlib import Path` to the imports (if not present).
2. Add to class `Gap12MetricTests`:
   ```python
   def setUp(self) -> None:
       self._tmp = tempfile.TemporaryDirectory()
       self.addCleanup(self._tmp.cleanup)
       self._cache_dir = str(Path(self._tmp.name) / "cache")
   ```
3. Change **all six** `ScanConfig(...)` constructions whose config flows into `load_one_fundamental` to pass `cache_dir=self._cache_dir`:
   - `ScanConfig(use_ttm_metrics=True, nonrecurring_addback_revenue_cap=0.25)` → `("TEST", "0000000001")`;
   - same config → `("CAP", "0000000002")`;
   - `ScanConfig(use_ttm_metrics=True)` → `("ANNUAL", "0000000003")`;
   - `ScanConfig(use_ttm_metrics=True)` → `("INF", "0000000004")`;
   - `ScanConfig(use_ttm_metrics=True)` → `("BIDU", "0001329099")` (**the real-CIK writer**);
   - `ScanConfig(use_ttm_metrics=True)` → `("FRESH", "0000000001")`.
   - Do **not** change the `ScanConfig(metric_hard_filter_coverage_mode=...)` construction that does not reach `load_one_fundamental`.
4. Optional but recommended (preserves write-path coverage): in the BIDU test, seed the temp cache dir with a minimal `submissions_0001329099.json` (e.g. `{"cik": "1329099", "filings": {"recent": {"form": [], "accessionNumber": [], "filingDate": []}}}` or the same shape the guarded path can parse; if seeding turns out brittle, skip it — sticking with a bare temp dir is acceptable, since the write-guard's behavior is already covered elsewhere).
5. Add a regression test:
   ```python
   def test_real_cache_untouched_by_bidu_fixture(self) -> None:
       # (same BIDU _FakeSecClient fixture as the existing BIDU test)
       repo_file = Path("cache") / "parsed_fund_0001329099.json"
       existed_before = repo_file.exists()
       mtime_before = repo_file.stat().st_mtime_ns if existed_before else None
       cfg = ScanConfig(use_ttm_metrics=True, cache_dir=self._cache_dir)
       load_one_fundamental(sec, "BIDU", "0001329099", cfg)
       self.assertEqual(repo_file.exists(), existed_before)
       if existed_before:
           self.assertEqual(repo_file.stat().st_mtime_ns, mtime_before)
   ```

### 2.2 `tests/test_daily_cron_scan_and_ttl.py` — Isolated Cache Dir in `RefreshPurityTests`

1. Add `import tempfile` (and use `Path` if not already imported).
2. Add to class `RefreshPurityTests`:
   ```python
   def setUp(self) -> None:
       self._tmp = tempfile.TemporaryDirectory()
       self.addCleanup(self._tmp.cleanup)
       self._cache_dir = str(Path(self._tmp.name) / "cache")
   ```
3. In `RefreshPurityTests._run_main`, wrap the existing body with a `patch.object(rsc, "load_config", return_value=ScanConfig(cache_dir=self._cache_dir))` context (import `ScanConfig` locally inside `_run_main` as the other tests do, e.g. `from ai_value_scanner.scanner import ScanConfig`):
   - `rsc.main()`'s parser check `cfg.sec_cache_ttl_submissions_sec > 0` is satisfied by the `ScanConfig()` default `86400`.
   - Keep `patch.object(sys, "argv", ...)` and the `patch.dict(os.environ, ...)` behavior unchanged, so all existing argv/env assertions keep passing.
4. In the two direct `run_sec_prewarm` tests, pass an isolated config:
   - `test_run_sec_prewarm_defaults_and_limit`: `cfg = ScanConfig(cache_dir=self._cache_dir)` (keep the `limit=1` and `submissions_ttl_sec` assertion unchanged — `submissions_ttl_sec` is derived from `max_age_hours`, not the config file).
   - `test_run_sec_prewarm_exits_1_without_symbols`: `ScanConfig(cache_dir=self._cache_dir)`.
5. Add a regression test extending the previous writer scenario:
   ```python
   def test_main_pending_streaks_isolated_from_repo_cache(self) -> None:
       stack, _, _ = self._patch_prewarm_stack(_clean_summary())
       repo_file = Path("cache") / "sec_pending_streaks.json"
       existed_before = repo_file.exists()
       mtime_before = repo_file.stat().st_mtime_ns if existed_before else None
       with stack:
           self._run_main([], {"ALPACA_API_KEY": "test-key"})
       # The diagnostics path executed inside the isolated temp cache dir.
       self.assertTrue((Path(self._cache_dir) / "sec_pending_streaks.json").exists())
       # ...and the real repo cache file was untouched.
       self.assertEqual(repo_file.exists(), existed_before)
       if existed_before:
           self.assertEqual(repo_file.stat().st_mtime_ns, mtime_before)
   ```

---

## 3. Acceptance Criteria

1. **Sweep is clean** — after the changes, the following sweep must show an empty diff:
   ```bash
   find cache -type f -printf "%p %T@\n" | sort > /tmp/cache_before.txt
   .venv/bin/python -m unittest discover -s tests
   find cache -type f -printf "%p %T@\n" | sort > /tmp/cache_after.txt
   diff /tmp/cache_before.txt /tmp/cache_after.txt
   ```
2. `git status -s data/ cache/ 2>/dev/null` shows no modifications attributable to the test run; `data/ai_watchlist.csv` and `data/ai_smallcap_manual.csv` remain byte-identical to `HEAD`.
3. Only the two test files change (`tests/test_gap12_metrics.py`, `tests/test_daily_cron_scan_and_ttl.py`); production code and docs untouched.
4. Full suite passes: `.venv/bin/python -m unittest discover -s tests` → `OK` with the same or greater test count.
5. All pre-existing assertions in both files remain unchanged in meaning (in particular: `test_default_max_age_hours_is_4h`'s `submissions_ttl_sec == int(4.0 * 3600)` check, `_clean_summary`-based flows, and the `test_main_never_scans_even_with_credentials` intent).
