# M2 v1 Failure Attribution Report (frozen 2026-10-15, M2.1 complete)

Offline read-only audit of frozen v1 decisions across snap62 (62 symbols,
2026-10-12), snap510 (510 symbols, 2026-10-09), and 25,025 historical v3 rows
(39 dates, 2023-01-31..2026-03-31). Cross-sectional counts cover all 39 dates;
return diagnostics use ONLY the 24 development dates 2023-01-31..2024-12-31
(RETROSPECTIVE_EXPLORATORY); 2025/2026Q1 forward labels remain unpeeked for M4.
Case registry: 38/38 strata matched (28 STRATIFIED_PRE + 6 controls + 4 paired exploratory).

## 1. Executive Summary and Causal Breakdown

- Axis 1 accrual sign bug: 3997 dev-row / 6930 all-39 cash-cow false positives at accrual<-0.10; accrual-only fix upgrades 642 B->A and 259 C->B on dev dates.
- Axis 2 working-capital penalty: 363 of 1194 high-growth healthy dev rows penalized; 129 penalized B rows reach grade A under the combined fix.
- Axis 5 dead zone: 626 all-39 dead-zone pullbacks hide in WATCH_BREAKOUT (snap62 CRM archetype).
- Axis 7 attention: 18 of 24 dev dates truncate A+READY (279 obs, 399 across all 39); 272 high-score B+READY obs suppressed to HOLD_MONITOR.
- Axis 6 breakout split (dev): MILD=411, NEAR=1808, WEAK=2256, UNOBS=0.
- Parity: snapshot Top-15/manifest match snap510=True, snap62=True; post-M1 zero-silent verdict=PASS.

## 2. Fundamental Metric Audit (6-pillar decomposition)

Pillar means/coverages/weak-rates per grade live in component_and_routing_diagnostics.csv (section=pillar_decomposition, scopes snap62/snap510/hist_dev_24_dates/hist_all_39_dates). Growth-split dev excess (A/B-C x high/low revenue growth) is reported under growth_split_returns; high-growth leaders concentrate penalties on valuation_context and red_flags while low-growth mature names dominate Grade A on cheap self-history multiples.
Weight note: production code weights profitability 0.30 / red_flags 0.10 vs the spec-canonical 0.25 / 0.15; means and coverages are weight-free facts and both schedules are carried per pillar row for adjudication.

## 3. Entry and Price-Volume Metric Audit

Dead-zone (1.08,1.10]/(12%,15%] rows are WATCH_BREAKOUT, not WATCH_PULLBACK; per-gate failure counts across dev and all-39 dates live under section=entry_subgates. Snapshot caveat: pre-M1 snapshots serialize only emitted evidence, so 10/16 snap62 and 90/141 snap510 BREAKOUT rows are UNOBSERVABLE for bucketing (silent-band gates). sma50_to_sma200 is exactly price_to_sma200/price_to_sma50 on every row (Axis 8).

## 4. Action Routing, Replacement Cost and Top-15 Compression Audit

Same-date replacement comparison (section=replacement_comparison): marginal #11-15 members vs excluded A+READY-16+ / high-score B+READY on identical dates; 34 all-39 dates pair a marginal selected row with a live excluded opportunity. Dev date-equal excess diagnostics compare the two pools.

## 5. Cross-Industry Business-Model Bias Audit

Six archetypes + explicit UNCLASSIFIED_RESIDUAL (section=industry_bias, scopes snap62/snap510/hist_all_39_dates): grade shares, mean confidence, top missing metrics and top weak flags per archetype. Snapshot archetypes reuse the hist-derived symbol map (most-common SIC); symbols absent from history stay UNCLASSIFIED.

## 6. Growth-Split Return Diagnostics (dev only, exploratory)

- A_HIGH_GROWTH: date-equal mean excess -0.0187 (n_dates=24, n_obs=519)
- A_LOW_GROWTH: date-equal mean excess -0.0226 (n_dates=24, n_obs=3330)
- BC_HIGH_GROWTH: date-equal mean excess +0.0879 (n_dates=24, n_obs=2173)
- BC_LOW_GROWTH: date-equal mean excess -0.0162 (n_dates=24, n_obs=7554)
- OTHER: date-equal mean excess +0.0221 (n_dates=24, n_obs=1538)
- replacement EXCLUDED_OPPORTUNITY: date-equal mean excess -0.0212 (n_dates=24, n_obs=561)
- replacement MARGINAL_11_15: date-equal mean excess -0.0138 (n_dates=20, n_obs=98)
- replacement OTHER: date-equal mean excess -0.0019 (n_dates=24, n_obs=14455)

_End of M2 attribution. Counts reproducible from the diagnostics CSVs; parity verdicts in report_evidence_parity_checks.json._
