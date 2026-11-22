# Short Research v1 reproduction

```bash
.venv/bin/python -m unittest discover -s tests -p test_short_research_v1.py
.venv/bin/python -m unittest discover -s tests
```

Frozen evaluation (importable entry; no new scan/cron CLI):

```bash
.venv/bin/python - <<'PY'
from ai_value_scanner.research.short_research_v1 import evaluate_frozen_short_research
evaluate_frozen_short_research('outputs/review_followup_20261106/datasets', 'outputs/short_research_v1/smoke', scope='smoke')
PY
```
