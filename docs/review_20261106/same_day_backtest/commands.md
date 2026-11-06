# Reproduction commands

The commands below record this study's original sequence. Reproduce the numerical results from the frozen CSVs with the offline evaluator; do not rerun extraction under an existing immutable study identity after source changes. For a new extraction use a new `--study-version` (for example `v3`), run smoke first, and download its success record to `outputs/review_20261106/infi_smoke_v3_pass.json` before `--stage full --study-version v3`. A new evaluation can use `--evaluation-version v3`; existing v2 evidence remains intact. `--evaluation-scope sip_monthly` selects one completed scope when recovering.

All Modal launches are foreground, explicit `infi`, and long tasks follow a passing smoke.

```sh
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_selection_backtest.py --stage smoke
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_selection_backtest.py --stage full
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_selection_backtest.py --stage evaluate
.venv/bin/python -m unittest discover -s tests
```

The launcher requires the downloaded `outputs/review_20261106/infi_smoke_pass.json` before full extraction. Study specs and completed artifacts are under `ai-scanner-research:/selection_review_20261106/`. Specs are immutable by run id: a code/input mismatch stops instead of resuming. Evaluation likewise checks dataset and source identities before reusing a result directory. A changed implementation requires a new study/result identity, not deletion of existing evidence.

Offline evaluator, after downloading datasets and their companion `.meta.json` files:

```sh
.venv/bin/python scripts/evaluate_current_top15.py \
  --dataset outputs/review_20261106/infi_results/sip_2016_2020_v1/dataset.csv \
  --dataset outputs/review_20261106/infi_results/sip_2021_2026_v1/dataset.csv \
  --output outputs/review_20261106/reproduced_sip_monthly
```

Output must be a new directory. Large raw CSVs/caches remain untracked. SIP study liquidity thresholds retain the same numeric setting for a fixed experiment, but have different economic semantics from IEX; do not silently transfer the result into production.
