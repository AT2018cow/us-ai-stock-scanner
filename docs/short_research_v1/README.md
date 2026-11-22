# Short Research v1 — implementation and evidence index

- Date: 2026-11-22
- Status: implemented; frozen smoke and full evaluation complete; production configs remain disabled.
- Implementation commit: `7f411eadd3c8d23d92f9c3303a7dbc36908eee1f` (`7f411ea`)
- Evidence `manifest.json` code_sha: `7f411eadd3c8d23d92f9c3303a7dbc36908eee1f`
- Contract: `short_research_v1` · Rule: `short_research_rules_v1`
- Independent reviewer: Codex (V1-01 … V1-10)

## 1. Code locations

| Area | Location |
| --- | --- |
| Config switch and compatibility validation | `src/ai_value_scanner/config.py` (`enable_short_research`) |
| Pure rules, input contract, funnel, statuses, borrow contract, JSON/CSV/report section | `src/ai_value_scanner/research/short_research_v1.py` |
| Frozen settlement, costs, statistics, bootstrap, evidence publication | `src/ai_value_scanner/research/short_research_v1_eval.py` |
| Same-scan adapter (before legacy list / Research Pool routing) | `src/ai_value_scanner/scanner.py` |
| Snapshot files, manifest binding, renderer revision | `src/ai_value_scanner/reporting/snapshot.py` |
| Daily/weekly Short Research block | `src/ai_value_scanner/reporting/decision.py` |
| Compatibility scan report status/count/file entry | `src/ai_value_scanner/reporting/scan.py` |
| Snapshot validator | `scripts/validate_mvp_snapshot.py` |
| Tests | `tests/test_short_research_v1.py` |
| User guide | `README.md` §3.4.2 (6) |

No new scan/cron command or flag was added. `run_scan.py` and the existing cron entry remain the only production entries.

## 2. Reproduction commands

```bash
.venv/bin/python -m unittest discover -s tests -p test_short_research_v1.py
.venv/bin/python -m unittest discover -s tests
```

Frozen smoke (four agreed dates):

```bash
.venv/bin/python - <<'PY'
from ai_value_scanner.research.short_research_v1 import evaluate_frozen_short_research
evaluate_frozen_short_research(
    "outputs/review_followup_20261106/datasets",
    "outputs/short_research_v1/smoke",
    scope="smoke",
)
PY
```

Frozen full (four datasets: 2016–2020 monthly, 2021–2026 monthly, COVID weekly, 2022 bear weekly):

```bash
.venv/bin/python - <<'PY'
from ai_value_scanner.research.short_research_v1 import evaluate_frozen_short_research
evaluate_frozen_short_research(
    "outputs/review_followup_20261106/datasets",
    "outputs/short_research_v1/full",
    scope="full",
)
PY
```

A credentialed live SIP/SEC scan was **not** run in this environment. The frozen adapter/snapshot/report contract is covered by tests; the production command remains:

```bash
.venv/bin/python run_scan.py --config configs/config.production.json
```

Enablement is intentionally left to the user; production configs do not set `enable_short_research`.

## 3. Test result

- `tests/test_short_research_v1.py`: **47 tests, OK**.
- Full unittest suite: **1,430 tests, OK** (the repository's intentional theme-status message still prints, but the process exits 0).

## 4. Evidence

Compact, browsable evidence:

- `docs/short_research_v1/evidence/short_research_v1_20261122_smoke/`
- `docs/short_research_v1/evidence/short_research_v1_20261122_full/`

Raw working outputs (gitignored):

- `outputs/short_research_v1/smoke/`
- `outputs/short_research_v1/full/`

Both evidence directories contain:

`protocol.json`, `manifest.json`, `commands.md`, `report.md`, `validation.json`, `SHA256SUMS`, `coverage.csv`, `paired_by_date.csv`, `summary.csv`, `members.csv`, `casebook.csv`, `scan_integration.json`, `short_research.json`, `short_candidates.csv`, `action_list_short_fragment.md`, `weekly_review_short_fragment.md`, `checkpoint.json`.

`sha256sum -c SHA256SUMS` passes in both directories; no local absolute paths are present.

## 5. Frozen input identities

| Dataset | Rows | Dates | SHA256 (prefix) |
| --- | ---: | ---: | --- |
| `sip_2016_2020_v1` | 31,516 | 60 | `0944488aa43c0cd9…` |
| `sip_2021_2026_v1` | 49,015 | 70 | `aaaca3090da010e2…` |
| `sip_covid_weekly_v1` | 11,861 | 21 | `9518f538d0db3e67…` |
| `sip_bear_weekly_v1` | 35,747 | 52 | `d2fd0dc9b7a21d17…` |

All four match `success.json`, metadata SHA256, and the `parity.inputs` hashes in `docs/value_pullback_optimization_20261106/worker_manifests/prepared/`.

## 6. Results summary

### Smoke (4 dates)

- Funnel: input 2,445 → U0 unique 1,503 → U 493 → S0 171 → S1 18 → S2 4; S2 dates 3.
- Verdict: **insufficient_evidence** (fewer than 24 mature complete dates).

### Full (203 signal dates: 130 monthly + 73 weekly)

- Funnel: input 128,139 → U0 unique 95,743 → U 31,134 → S0 8,692 → S1 734 → S2 165; S2 dates 103; selected 163.
- Primary 20d same-slot monthly: 64 mature complete dates; S2 short gross **−0.9%**, S2−S0 **−0.0%**; S2−S0 95% CI [−3.6%, +2.8%].
- Weekly 20d same-slot: S2 **+3.1%**, S2−S0 **+4.0%**; 2022 bear weekly S2 **+3.7%**, S2−S0 **−0.8%**.
- Verdict: **signal_or_increment_failed** — S2 absolute 20d short gross and S2−S0 are not positive in the primary monthly comparison.
- This is retrospective frozen evidence, not OOS, and does not promote production behavior.

## 7. V1-01 … V1-10 coverage

| Item | Implementation/evidence |
| --- | --- |
| V1-01 input/no lookahead | Strict required columns, one valid signal date, SIP-only feed, CIK/SIC normalization, duplicate date×symbol rejection, future/as-of row reasons, non-finite reasons, `shares_stale` unknown not false; tests in `TestInputContract`; hashes in `validation.json`/`manifest.json`. |
| V1-02 peer calculations | SIC leave-one-out median, P/E average percentile/median/premium, 4-other/5-including-target minima, same-CIK dedupe, tie and shuffle tests in `TestPeerCalculations`; hand-checked 10/12/14/16/20 case. |
| V1-03 selection/list | S0/S1/S2 boundaries, subset chain, WATCH/NO_SIGNAL/INSUFFICIENT/SCOPE_EXCLUDED, top-5 cap and stable `(rs60_sic, symbol)` order in `TestSelectionRules`. |
| V1-04 settlement/splits | 20/60 planned endpoints, exact exit-label check, missing labels kept missing, `x = 1 + fwd_ret + 0.003`, short gross, cost scenarios, 100→80 and 100→120 examples, split-adjusted label case in `TestSettlementAndCosts`. |
| V1-05 comparison/statistics | k=min(5,n_S0,n_S1,n_S2), 1/k weights, fixed-5 cash slots, paired masks, block bootstrap 2,000/seed 61,122/block 6, segments, concentration/contribution helpers; smoke/full `coverage.csv`, `paired_by_date.csv`, `summary.csv`. |
| V1-06 borrow | Trusted same-day metadata, bare cache, stale/future, source/environment mismatch, conflicting flags, no-selection-change test in `TestBorrowEvidence`; all historical rows `UNKNOWN`. |
| V1-07 reproducibility | Two smoke runs byte-identical for coverage/paired/summary/members/JSON/CSV/report/validation; `SHA256SUMS` verified; checkpoint identity mismatch rejected and matching checkpoint reused in `TestFrozenSmokeEvaluation`. |
| V1-08 same-scan/isolation | Read-only whitelist adapter, short on/off snapshots with identical `decisions.jsonl` and long daily/weekly symbols, QQQ-paused report with non-empty short section, in `TestSnapshotIntegration`; live credentialed scan not run (documented limitation). |
| V1-09 files/empty/fault isolation | ready/no_candidates/unavailable/disabled snapshots, CSV header-only empty cases, five-cap CSV, short failure converted to unavailable while long snapshot publishes, in `TestSnapshotIntegration`. |
| V1-10 compatibility/immutability | Switch/rule-version reuse mismatch, same-identity reuse, missing/tampered JSON/CSV/report rejection, historical snapshot without field, immutable rerun `FileExistsError`, renderer revision bump, in `TestReuseAndValidation`. |

## 8. Known limitations

- No credentialed live SIP/SEC scan was run here. The frozen adapter simulation and unit tests cover the contract; Codex should run the documented live command if credentials are available.
- All historical borrow statuses are `UNKNOWN`; no historical borrow database or extra broker requests were used.
- Intraperiod maximum adverse excursion is not verified without raw frozen daily paths; period-end adverse-up is reported instead.
- Monthly inputs are largely `union_superset_approx`; overlapping forward labels are aggregated by date, not treated as independent samples.
- Costs are scenario assumptions, not observed borrow fees, locates, recalls, or dividends.
- The full verdict is negative; this evidence is for implementation and research validation only, not production promotion.
