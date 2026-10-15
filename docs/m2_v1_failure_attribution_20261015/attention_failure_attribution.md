# M2 v1 Failure Attribution Report (frozen 2026-10-15)

Offline read-only audit of frozen v1 decisions across snap62 (62 symbols,
2026-10-12), snap510 (510 symbols, 2026-10-09), and 25,025 historical v3 rows
(39 dates, 2023-01-31..2026-03-31). Return diagnostics use ONLY the 24
development dates 2023-01-31..2024-12-31 (RETROSPECTIVE_EXPLORATORY);
2025/2026Q1 forward labels remain unpeeked for M4.
Case registry: 34/34 strata matched.

## 1. Executive Summary and Causal Breakdown

- Axis 1 accrual sign bug: 3997 dev-row cash-cow false positives at accrual<-0.10 (2253 at <-0.20); accrual-only fix upgrades 642 B->A and 259 C->B on dev dates.
- Axis 2 working-capital penalty: 363 of 1194 high-growth healthy dev rows penalized; 129 penalized B rows reach grade A under the combined fix.
- Axis 3 binary FCF: 958 of 10266 FCF-positive dev rows run sub-3% margins yet score 1.0; 364 of 601 PRIORITY_REVIEW rows carry ps/pe percentile weak flags.
- Axis 5 dead zone: 411 dev dead-zone pullbacks hide in WATCH_BREAKOUT (snap62 CRM archetype).
- Axis 6 breakout split (dev): MILD=411, NEAR=1808, WEAK=2256, UNOBS=0.
- Axis 7 attention: 18 of 24 dev dates truncate A+READY (279 obs); 272 high-score B+READY obs suppressed to HOLD_MONITOR.
- Axis 8 MA alignment: on dev dates, 140/1781 (7.9%) ENTRY_READY rows and 723/4475 (16.2%) WATCH_BREAKOUT rows have inverted moving averages (SMA50 < SMA200).

## 2. Fundamental Metric Audit

### 2.1 accrual_ratio sign inversion (Axis 1)
v1 scores abs(accrual): OCF>NI cash generation reads as weak when accrual<-0.10.
Dev false-positive rate: 28.6% at -0.10, 16.1% at -0.20.
### 2.2 High-growth working-capital penalty (Axis 2)
Penalized share of high-growth healthy rows: 30.4%.
### 2.3 Binary FCF and valuation drag (Axis 3)
FCF margin median among FCF-positive rows: 0.132438; thin-margin count: 958; strong-margin count: 4522.
### 2.4 Missing margin pillars (Axis 4)
operating_margin computable on 85.9% of dev rows and 86.2% of all rows from existing facts with zero new fetches. Snapshot decisions.jsonl serializes only emitted evidence (no revenue/ebit values), so coverage is proven on historical rows, whose facts are the same SEC source.

## 3. Entry and Price-Volume Metric Audit

Dead-zone (1.08,1.10]/(12%,15%] rows are WATCH_BREAKOUT, not WATCH_PULLBACK;
the 3-way split separates MILD pullbacks from NEAR consolidations and WEAK laggards.
MILD rows occur across all 24 dev dates (411 obs, 9.2% of BREAKOUT),
so the seam is structural, not a single-date artifact.
Snapshot caveat: pre-M1 snapshots serialize only emitted evidence, so 10/16 snap62
and 90/141 snap510 BREAKOUT rows are UNOBSERVABLE for bucketing (silent-band gates);
CAT/LIN fall in this unobservable set, not the confirmed-weak set.
sma50_to_sma200 is exactly price_to_sma200/price_to_sma50 on every row (Axis 8).

## 4. Action Routing and Top-15 Compression Audit

18 dev dates truncate eligible A+READY names while 272 high-score B+READY rows sit in HOLD_MONITOR behind A+WATCH_BREAKOUT names. Date-equal 60d net-QQQ comparisons are exploratory only.

_End of M2 attribution. All counts reproducible from metric_and_routing_diagnostics.csv._
