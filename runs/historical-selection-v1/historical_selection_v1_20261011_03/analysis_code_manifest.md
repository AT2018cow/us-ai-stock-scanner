# Analysis code manifest — RUN_ID historical_selection_v1_20261011_03

Production modules untouched (`src/ai_value_scanner/scanner.py`,
`decision/`, `strategy/` clean). Research/repair changes live in PR #58
branch at `af70b5e` (CI unittest success run 38151804814; local 545 OK):

- `split_query_end_iso` (`evaluation/backtest.py`) + 2 call sites
  (extract script, backtest replay); `{stem}.splits.json` frozen artifact.
- `evaluation/equity_continuity.py` + `scripts/repair_equity_discontinuity.py`.
- `tests/test_corporate_action_label_integrity.py` (15 tests).

| script | SHA256 | invocation |
|---|---|---|
| research/hist_h1_quality.py | 2578eb466bc439eb4ed8d4bb681a04e1c95fecf2e118966efc1fc90bb87615b2 | `.venv/bin/python research/hist_h1_quality.py historical_selection_v1_20261011_03` |
| research/hist_h2_entry.py | 04744ea766a678ffe859e4eff351de60fe468cfb06a51525d22524e65551d08b | `.venv/bin/python research/hist_h2_entry.py historical_selection_v1_20261011_03` |
| research/hist_h3_action.py | 7984f12890c1ebf1aebfe7173f569dfaffcbe4fc7b43986002168d0df298a42b | `.venv/bin/python research/hist_h3_action.py historical_selection_v1_20261011_03` |
| research/diff_v1_v3_labels.py | 31be64c76092ef265050198f0d94a683c6e442a7b0b20a6ec4fb75fadabddb85 | `.venv/bin/python research/diff_v1_v3_labels.py` (reads _02 + _03 analysis dirs) |
| scripts/repair_equity_discontinuity.py | (tracked at af70b5e) | see validation_and_tests.md invocations |

Copies of the four `research/` scripts are included in this evidence
directory. Frozen case rules in script headers; repair rules in the
module docstring. All local, deterministic, read-only (repair writes new
files, never in place).
