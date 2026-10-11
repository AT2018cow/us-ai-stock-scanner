# Analysis code manifest — RUN_ID historical_selection_v1_20261011_02

Research scripts are untracked workdir files (protocol §7 allows
`research/`); reproduced here by SHA256 with exact invocations. All are
read-only pandas diagnostics — no production module was modified
(`git status` on `src/` clean). Copies of the three scripts are included in
this evidence directory for independent re-computation.

| script | SHA256 | invocation |
|---|---|---|
| research/hist_h1_quality.py | 2578eb466bc439eb4ed8d4bb681a04e1c95fecf2e118966efc1fc90bb87615b2 | `.venv/bin/python research/hist_h1_quality.py historical_selection_v1_20261011_02` |
| research/hist_h2_entry.py | 04744ea766a678ffe859e4eff351de60fe468cfb06a51525d22524e65551d08b | `.venv/bin/python research/hist_h2_entry.py historical_selection_v1_20261011_02` |
| research/hist_h3_action.py | 7984f12890c1ebf1aebfe7173f569dfaffcbe4fc7b43986002168d0df298a42b | `.venv/bin/python research/hist_h3_action.py historical_selection_v1_20261011_02` |

Pre-registered evaluators (tracked, code SHA `73a6fe6`):
`scripts/evaluate_company_quality.py`, `scripts/evaluate_entry_quality.py`,
`scripts/evaluate_action_states.py --attention-cap 15` — outputs
`quality_v1_*` / `entry_v1_*` / `action_v1_*` in this directory.

Frozen case-selection rules live in each script's header (R1–R4, F1–F3,
reason-code order, E-first key) and were fixed before viewing forward
returns. Environment: repo `.venv`, pandas-based, local only.
