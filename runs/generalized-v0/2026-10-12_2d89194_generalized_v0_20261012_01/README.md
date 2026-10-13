# Generalized-v0 experiment evidence — 2026-10-12 session

**Mode: experiment (NOT formal, NOT prospective). Diagnostic only.**

## Run facts

- Decision session: **2026-10-12** (Monday; resolved from observed IEX bars,
  never wall-clock; verified ≠ 2026-10-13).
- Code: `2d8919444828643f7b888f90907e0b0e6632bfc4` (PR #57 baseline, frozen;
  post-#57 policy/report/identity changes NOT included by design).
- Config: `config.generalized_v0.experiment.json` (byte-identical to the
  PR #57 prepared file; sanitized copy archived, no secrets).
- Cohort: 75 source memberships → 62 unique symbols → 62 decisions,
  0 source-row rejections, 0 universe exclusions. Source files frozen
  2026-10-11 (NOT PIT membership for any earlier date).
- Policy frozen: Quality v1, Entry v1, Action mapping, QQQ regime, IEX
  feed, $2m snapshot gate. Validator PASS (validation.json).
- Bars: 76/76 symbols (62 + QQQ/SPY/benchmark ETFs), 9,728 rows,
  split-adjusted IEX; dataset SHA256 in pit_bars_manifest.json.
- Raw `pit_iex_daily_bars.csv` NOT committed (provider redistribution
  terms): SHA, schema, coverage and derived diagnostics archived;
  missing raw bars is an explicit review limitation (re-fetch protocol in
  the manifest + research protocol §6).

## Exact commands (frozen worktree @2d89194, foreground, no --formal)

```bash
python scripts/preview_discovery_sources.py --config config.generalized_v0.experiment.json --decision-date 2026-10-12
python scripts/run_mvp_full_scan.py --config config.generalized_v0.experiment.json
python scripts/validate_mvp_snapshot.py "$SNAPSHOT" --json > validation.json
python scripts/export_generalized_pit_bars.py --snapshot "$SNAPSHOT" --config config.generalized_v0.experiment.json --out-dir outputs/generalized_bars_v0
python scripts/research_generalized_selection.py audit --snapshot "$SNAPSHOT" --config config.generalized_v0.experiment.json --bars-csv outputs/generalized_bars_v0/pit_iex_daily_bars.csv --out-dir outputs/generalized_research_v0
```

## Results headline (details: research_review.md, reviewer_notes.md)

- Universe/provenance: 75/62/0/0, source hashes verified, no future
  membership, no silent substitution.
- Liquidity: 62/62 names with 20 valid IEX sessions (100% ≥ 80% GO);
  0 snapshot-vs-20-session threshold disagreements.
- Entry benchmarks: all groups with aligned 61-session QQQ+SPY coverage
  (GO); sign disagreements: communications 1, industrials 2, semis 1.
- Quality: A/B/C/UNRATED distributions + bank/REIT non-comparability
  flags per group; no v2 weights proposed.
- Action: 6/3/7/39/7 with cap-15 lists; no quota changes.
- One validator warning: latest periodic filing not covered for
  1 decision (named in reviewer_notes.md).
