MVP candidate-universe provenance experiment (PR #52 validation)

Code SHA: aa59e9d8c4593a815f6c17e906b703bf686d988e
Decision date: 2026-10-09
Config: configs/config.risk_off.json
Strategy style: risk_off
Mode: experiment
Command: python scripts/run_mvp_full_scan.py
Validator: PASS
Warnings:
- latest periodic filing is not covered by recognized Company Facts for 9 decision(s)
- non-USD core monetary facts are unsupported for 17 decision(s)
Candidate-universe contract: candidate_universe_v1_2026-10-11
Funnel: discovery=687, tradable_mapped=678, post_sample=678, decisions=510, excluded=177
Exclusion reasons: ALPACA_ACTIVE_ASSET_MISSING=6, SEC_MAPPING_MISSING=3, DOLLAR_VOLUME_BELOW_MIN=167, PRICE_BELOW_MIN=1
Market-data feed: iex
min_price: 1.0
min_dollar_volume: 2000000.0
Watchlist refreshed before run: no
Input/output manually modified after run: no
Credential variable names: ALPACA_API_KEY, ALPACA_API_SECRET, SEC_USER_AGENT
