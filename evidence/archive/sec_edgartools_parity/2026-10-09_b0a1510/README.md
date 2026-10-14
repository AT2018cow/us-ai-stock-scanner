# EdgarTools SEC parity spike — experiment evidence

Code SHA: b0a151050fab2af14f13c9b7996b1f1cad708e74
Decision date: 2026-10-09
Source snapshot: outputs/decision_experiments/risk_off_20261010T143355Z/2026-10-09/risk_off
EdgarTools version: 5.61.1
Identity source: EDGAR_IDENTITY
Mode: diagnostic experiment (no --formal concept; read-only diagnostic)

Command:

```bash
CODE_SHA7="$(git rev-parse --short=7 HEAD)"

python scripts/diagnose_sec_with_edgartools.py \
  --snapshot-root outputs/decision_experiments/risk_off_20261010T143355Z/2026-10-09/risk_off \
  --all-flagged \
  --output-dir "outputs/sec_edgartools_diagnostic/2026-10-09_${CODE_SHA7}"
```

Classification counts (verbatim from summary.json):

```json
{
  "cases": 65,
  "classifications": {
    "CONTROL_EDGARTOOLS_CORE_FOUND": 1,
    "CURRENT_PATH_GAP_EDGARTOOLS_CORE_FOUND": 49,
    "CURRENT_PATH_GAP_EDGARTOOLS_CORE_FOUND_CUSTOM": 2,
    "CURRENT_PATH_GAP_EDGARTOOLS_CORE_NOT_FOUND": 2,
    "CURRENT_PATH_NON_USD_EDGARTOOLS_NON_USD_ONLY": 3,
    "CURRENT_PATH_NON_USD_EDGARTOOLS_USD_SEEN": 8
  },
  "current_path_gap_cases": 53,
  "current_path_gap_edgartools_core_found": 51,
  "current_path_gap_core_found_rate": 0.962264,
  "custom_core_taxonomy_cases": 6,
  "edgartools_fetch_failures": 0,
  "edgartools_xbrl_unavailable": 0
}
```

Ordinary 10-Q filing-gap recovery: 46/47 (core_found_rate 0.978723).
20-F: 3/4. 40-F: 2/2.

Input/output manually edited after run: no
