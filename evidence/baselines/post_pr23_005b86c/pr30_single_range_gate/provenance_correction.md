# PR30 evidence provenance correction

Date: 2026-10-10

The committed PR30 result bundle was produced after the research
channel-column fix had been edited into the working tree, while Git HEAD still
pointed to the PR30 merge commit `20a610b9...`. The bundle's
`single_range_gate_input_manifest.json` therefore records
`code_sha=20a610b9...` even though the executed working tree also contained
the subsequently committed channel-parity fix in `9c478546...`.

Consequences:

- the observed 168/168 same-state parity is strong evidence that the executed
  code matched production semantics;
- the negative single-gate result is retained as historical evidence;
- however, the existing manifest does not uniquely identify the executed code
  state, so this bundle is **not canonical provenance** until reproduced from
  a clean committed checkout.

PR31 closes recurrence by making
`scripts/low_value_single_gate_ablation.py` reject dirty worktrees and record
both Git commit SHA and tree SHA.

Required revalidation:

1. merge PR31;
2. use a clean committed checkout;
3. reuse the exact frozen dataset SHA
   `bb6edd7a30d8347aeb2020f77255eb1d043d2417aa8892b1a62da8ff0cad0ad6`;
4. rerun the local evaluator only (no Modal compute);
5. require 168/168 same-state parity and materially identical negative
   retrospective gate results;
6. commit the refreshed compact evidence under a separate clean-rerun label.

Until then, do not use the existing bundle as a provenance-complete promotion
artifact. It already disallows production promotion, and no production change
was made.
