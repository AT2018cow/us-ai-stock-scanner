# Same-data-state gate evidence

This directory contains compact, machine-readable records for old/new replay
gates that intentionally compare behavior across a correctness-changing
refactor.

A gate manifest records the compared commits, frozen repository inputs,
comparison scope, unchanged layers, intentional differences, attribution
results, and any audit limitations.

## Evidence standard

For future gates, prefer recording all of the following when the environment
allows it:

- base/head commit SHAs and exact command/config identity;
- frozen watchlist/history hashes;
- a read-only or copied cache snapshot hash;
- output artifact hashes for both sides;
- exact diff counts plus intentional-change attribution;
- unit/integration test result.

A manifest must not invent unavailable hashes. If raw outputs or cache
snapshots were only retained locally, the record must say so explicitly.

## PR #10

`pr10_same_data_state_20261007.json` records the PR #10 reconstruction gate.
Its raw `outputs/gate10_*` files and shared cache snapshot were not committed
or hashed, so the manifest preserves the pushed comparison evidence while
explicitly marking that repository-only independent replay is not possible.


## Fast feature-snapshot gate

For strategy/scoring/filter/ranking refactors, do not rerun the expensive SEC/PIT
reconstruction for every checkout. Capture a small, representative set of
pre-strategy cross sections once from a frozen cache, then reuse that exact
bundle for old/new code.

### 1. Capture snapshots once

Example:

```bash
python run_backtest.py \
  --mode historical_replay \
  --scan-config configs/config.risk_off.json \
  --start-date 2026-01-01 \
  --end-date 2026-06-30 \
  --watchlist-csv-path <frozen-watchlist.csv> \
  --watchlist-history-dir <frozen-watchlist-history> \
  --feature-snapshot-only \
  --feature-snapshot-dir outputs/fast_gate_risk_off \
  --feature-snapshot-dates 2026-01-30,2026-02-27,2026-03-31,2026-04-30,2026-05-29,2026-06-30
```

Snapshot-only mode evaluates only the requested dates, forces the base scenario,
writes deterministic cross-section CSV files plus `manifest.json`, and exits
before ranking and forward-return event evaluation. It still uses the normal
frozen-cache data/PIT pipeline, so snapshot capture is the one expensive step.

Capture risk-off and risk-on bundles separately when both styles are relevant.
Choose dates that cover the behavior under review; 6–12 representative dates is
the normal Fast/Targeted gate, not a mandatory fixed calendar.

### 2. Run old/new strategy code offline

Run the same command in each checkout:

```bash
python scripts/fast_strategy_gate.py run \
  --snapshot-dir outputs/fast_gate_risk_off \
  --scan-config configs/config.risk_off.json \
  --output outputs/fast_gate_old.json

python scripts/fast_strategy_gate.py run \
  --snapshot-dir outputs/fast_gate_risk_off \
  --scan-config configs/config.risk_off.json \
  --output outputs/fast_gate_new.json
```

This stage performs no SEC/Alpaca access, no fact reconstruction and no price
history reconstruction. It only loads the frozen cross sections and executes
filter/scoring/ranking/selection logic.

### 3. Compare

```bash
python scripts/fast_strategy_gate.py compare \
  --baseline outputs/fast_gate_old.json \
  --current outputs/fast_gate_new.json
```

For mechanical strategy refactors, require `FAST_GATE_MATCH`. For intentional
strategy changes, compare the JSON results directly and document the expected
selection/diagnostic differences.

Use Medium or Full historical replay only when the change modifies data/PIT/
feature construction, when the targeted snapshots reveal unexpectedly broad
drift, or at a phase checkpoint.
