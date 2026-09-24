# AGENTS.md

US AI stock scanner: Alpaca market data + SEC EDGAR fundamentals, filters a local watchlist for undervalued AI stocks. The `ai_value_scanner` package lives in `src/`; root `run_scan.py` / `run_backtest.py` are thin CLI wrappers.

## Commands
- Install: `.venv/bin/pip install -e .` (py>=3.10; venv is 3.12). `requirements.txt` mirrors pyproject deps.
- Scan: `python run_scan.py --config configs/config.risk_off.json [--max-symbols N]` (`--config` defaults to risk_off). Observation period: `python scripts/observation_scan.py` runs both styles (risk_off then risk_on); see docs/OBSERVATION_PROTOCOL.md.
- Refresh watchlist: `python scripts/refresh_ai_watchlist.py --config configs/config.risk_off.json --output data/ai_watchlist.csv`
- Build smallcap layer: `python scripts/build_smallcap_universe.py --config configs/config.risk_off.json` (merges Nasdaq screen + Yahoo hot + `data/ai_smallcap_manual.csv` into `ai_smallcap` bucket; idempotent rebuild). Run order: refresh ETF watchlist → smallcap builder → scan.
- Backtest: `python run_backtest.py --mode historical_replay --scan-config configs/config.risk_off.json`
- Tune params: `python scripts/tune_parameters.py --base-config configs/config.risk_off.json --param-space configs/tuner.param_space.json`
- Tests: `python -m unittest discover -s tests` — stdlib `unittest`, NOT pytest. 56 tests, fully offline/fast, no env needed.
- No lint/format/typecheck tooling or CI exists. Tests are the only verification.

## Environment
- `.env` (gitignored) must set `ALPACA_API_ENDPOINT`, `ALPACA_API_KEY`, `ALPACA_API_SECRET`, `SEC_USER_AGENT`. Missing values fail at runtime (API client construction), not at import.

## Gotchas
- Scan aborts if `data/ai_watchlist.csv` is missing/empty; it is the only scan input (regenerate via the refresh script).
- `cache/` and `outputs/` are gitignored. Alpaca cache has TTLs (snapshots 120s, bars 6h). SEC cache is **incremental**: submissions (~176 KB each, ~2.3 min total) refresh on every scan (`sec_cache_ttl_submissions_sec`, default 0 = always fresh) and serve as the change detector; companyfacts (~4 MB each) only refetch when submissions show a new filing after the facts cache's mtime. No need to manually `rm cache/` for fresh fundamentals. SEC is rate-limited (~5 req/s).
- Channels: `core_ai`/`ai_enabler`/`ai_peripheral` (ETF buckets) + `ai_smallcap` (smallcap bucket). Code iterates `channel_profiles.keys()` dynamically, but `ScanConfig.from_dict` **replaces** the whole dict — a new channel must be added to code defaults AND all 4 production JSONs (tuner promotion deep-copies base config, so it survives). `SRC:`-prefixed `etfs` tokens are provenance tags, excluded from `etf_count`.
- Watchlist sources: stockanalysis.com holdings pages embed only ~top-25 holdings per ETF (server-side truncation, not code). Finviz export and stockanalysis.com `/list/` pages return 403 to plain scripts; Yahoo screener accepts one `scrIds` per request (combined → 400).
- Config files: `config.risk_off.json` (default, defensive leg), `config.risk_on.json` (offensive leg), `config.strict_candidate.json` (candidate). Two-style architecture since 2026-09-24: balanced is archived (redundant with risk_off, corr 0.999). `configs/archive/` — never edit or run archived configs.
- Config semantics: `null` disables a filter; `channel_profiles.<channel>` overrides global params per channel; unknown config keys are silently ignored; CLI `--max-symbols` overrides config `max_symbols`.
- `scripts/tune_parameters.py` auto-promotes to risk_on/risk_off unless `--no-promote` (balanced path is an archived reference). Default windows = past 3 full years + current YTD. `low_value` is the primary pass/fail list; `industry_trend`, `momentum`, `research_pool` are diagnostic only.
- Backtest `historical_replay` needs PIT watchlist snapshots in `data/watchlist_history`; `--allow-latest-watchlist-fallback` is OFF by default (avoid lookahead). `--theme-source rules_proxy|historical_news|latest_scan|zero` defaults to `rules_proxy`.

## Conventions
- Log format: scan `[HH:MM:SS][LEVEL][+elapsed]`, backtest `[scope HH:MM:SS +elapsed]`.
- Outputs: scan → `outputs/ai_value_scan_<UTC>_<scope>_ranked.*`, backtest → `outputs/backtest_<mode>_<UTC>_*`, tuner → `outputs/tuning_<UTC>_*`.
- To add a config parameter: add the field to `ScanConfig`, wire channel override in `resolve_channel_profile`, use it in the filter/scoring step, then update the README tables. README.md (Chinese) is the authoritative reference for all filter/threshold semantics.