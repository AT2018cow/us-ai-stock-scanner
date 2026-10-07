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
