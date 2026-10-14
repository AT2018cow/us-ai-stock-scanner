# MVP v1.1 PR-A — A0 structural data gate review report

Date: 2026-10-14
Executor: coding agent (local, read-only; no Modal, no SEC/Alpaca network calls)
Code under test: PR #70 head `4d56c08b6951deb528bff5c87fb52621ab13e427`
(`feature/mvp-v11-historical-optimizer-pr-a-20261014`, based on main `b4946e6`)
Plan reference: `docs/mvp_v11_historical_selection_optimization_plan_20261013.md` (docs branch `docs/mvp-v11-historical-optimization-plan-20261013`)

## 1. Verdict

**A0 structural gate: PASS (structural only).** Both corrected v3 datasets were
recovered locally, their SHA256 and archived metadata match the registered study
manifest, and row/date/sample-level integrity checks pass. Per the plan and the
PR runbook, this is **inventory only**: PIT filing availability, universe
provenance, price/label correctness, and canonical v1 (B0) parity remain
**unverified**. No candidate returns were computed.

## 2. Recovered inputs (local paths, unmodified)

Root: `outputs/historical_selection_v1_20261011_03/`

| File | SHA256 (prefix) | Role |
| --- | --- | --- |
| `repaired/company_quality_dataset_risk_off.v3.csv` | `2a4600ee…` | corrected v3 Company Quality (36 MB, 25,026 lines incl. header) |
| `repaired/entry_quality_dataset_risk_off.v3.csv` | `2a4600ee…` | corrected v3 Entry Quality (byte-identical to CQ pre-strategy rows, as registered in the manifest) |
| `evidence/company_quality_dataset_risk_off.meta.json` | `5644f2af…` | original CQ metadata (explicit `--quality-meta`) |
| `evidence/entry_quality_dataset_risk_off.meta.json` | `1574a855…` | original EQ metadata (explicit `--entry-meta`) |
| `evidence/company_quality_dataset_risk_off.splits.json` | `f5c7e421…` | corporate-action splits (48 symbols with events) |
| `evidence/study_manifest.json` | `aa120515…` | registered study manifest |
| `repaired/company_quality_discontinuities.csv` | `20dc8670…` | 52 audit rows (51 audit-only + 1 WOLF nulling) |
| `repaired/entry_quality_discontinuities.csv` | `20dc8670…` | identical audit content |
| `repaired/*.v3.meta.json` | `b425be82…` / `fbb734f8…` | repair-script companion metadata (not used as gate metadata) |

Full hashes: `SHA256SUMS_inputs.txt` in this directory.

**Manifest cross-check (all match):**

- CSV SHA256 = manifest `datasets_v3.*.csv_sha256` (`2a4600ee…`) ✔
- meta SHAs = manifest `meta_cq` / `meta_eq` ✔
- splits JSON SHA = manifest `splits_json` (`f5c7e421…`) ✔
- Study-level provenance (metadata lacks per-file keys, values live in
  `study_manifest.json`): code_sha `af70b5ea06209271bf8e815a9bf3a8bc911334c6`
  (PR #58 head, CI run 38151804814), config_sha256 `7a967e42…`,
  `entry_price_mode=next_open`, `exit_price_mode=close`,
  `trading_cost_bps_single_side=15`.

## 3. Metadata verification

Both metas declare: `dataset_kind` = `company_quality` / `entry_quality`,
`pre_strategy_cross_section = true`, `n_rows = 25025`, `n_dates = 39`,
window 2023-01-01→2026-03-31 monthly, horizons 20/60/120,
`allow_latest_watchlist_fallback = false`,
universe `union_superset_approx` (mixed PIT snapshots from 2026-09-22 +
approximation before), risk_off style, IEX feed per registered policies.
`entry_price_mode=next_open`, `exit_price_mode=close`; **cost convention verified
in the dataset builder** (`scripts/extract_weight_dataset.py`, whose meta
f-strings match this dataset byte-for-byte): both `fwd_ret_{h}` (stock legs) and
`qqq_return_{h}` (benchmark leg) are computed via `forward_return_with_exit`
with `roundtrip_cost = 2 × 15 bps` already subtracted on **both** sides — so
`fwd_ret − qqq_return` is a net-of-cost excess comparison and the planned
comparator must **not** subtract 15 bps again (no double-counting).

## 4. Sample integrity (script checks + independent spot checks)

- Rows: **25,025** per dataset = metadata `n_rows` ✔ (25,026 lines incl. header)
- Symbols: **670**; signal dates: **39** (`2023-01-31` → `2026-03-31`) ✔
- Date split matches the plan exactly: **24** dates 2023–2024 (7,459+7,655 rows),
  **12** dates 2025 (7,908 rows), **3** dates 2026Q1 (2,003 rows) ✔
- `signal_date × symbol` uniqueness: no duplicates ✔
- No future as-of: `fundamental_data_asof ≤ signal_date`, `market_asof ≤ signal_date` ✔
- Paired forward-label coverage (both ret & QQQ present):
  20d **25,025/25,025**, 60d **25,023** (2 missing), 120d **25,020** (5 missing) ✔
- Missing-label identity = exactly the registered WOLF nulling:
  `WOLF` rows 2025-04-30…2025-08-29, reason `REORG_JUMP_BACKDATED 2025-09-30`,
  audit CSV row `WOLF,…,True,0,2,5` (0×20d, 2×60d, 5×120d labels nulled) ✔
- `equity_discontinuity_flag = 1` on exactly those 5 WOLF rows; the separate
  audit CSV holds **52 rows = 51 audit-only + 1 nulling**, matching
  `study_manifest.json` (`audit_only: 51`) ✔
- 346 rows (40 symbols, spread 2023–2026) have no `fundamental_data_asof`:
  expected PIT coverage gaps for candidates without as-of fundamentals; they are
  retained rows (quality will be missing/penalized downstream), not label gaps.

## 5. Runs performed

```bash
# clean checkout of PR #70 head 4d56c08
python -m unittest discover -s tests
# → Ran 666 tests … OK   (CI on the same head: unittest PASS, run 38441243481)

python scripts/mvp_v11_a0.py \
  --quality-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv \
  --quality-meta    outputs/historical_selection_v1_20261011_03/evidence/company_quality_dataset_risk_off.meta.json \
  --entry-dataset   outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv \
  --entry-meta      outputs/historical_selection_v1_20261011_03/evidence/entry_quality_dataset_risk_off.meta.json \
  --output outputs/mvp_v11_a0/structural_gate.json
# → STRUCTURAL_PASS (PIT and forward labels UNVERIFIED)
```

`structural_gate.json` (copy in this directory) reports for both datasets:
`status = STRUCTURAL_PASS_PIT_AND_LABELS_UNVERIFIED`, 25,025 rows / 670 symbols /
39 dates, label coverage above, and dataset+metadata SHA256. The gate ran
offline; `outputs/` remains untracked, hence this evidence copy.

## 6. Limitations carried forward (not resolved by this gate)

1. Date-level as-of checks do not prove intraday filing availability.
2. SEC entity/identity, restatement, and the 51 audit-only discontinuities are
   unresolved; labels must stay audit-flagged, never backfilled.
3. Universe is `union_superset_approx` (retrospective), not true PIT ETF
   holdings; all results must be labeled retrospective / approximation.
4. 2025 and 2026Q1 are temporal diagnostics only (previously viewed data).
5. Canonical v1 B0 parity (Quality/Entry/Action/priority/Top-15 per date) is the
   **next gate** and has not been attempted; no alpha claim is possible yet.

## 7. Next steps (unchanged, inside PR-A)

1. B0 canonical parity against the registered research decision reconstruction.
2. Locked B0/R1–R5/E1–E4 registry execution, 2023–2024 development window only.
3. Paired comparator (next_open → horizon close; labels already net of 30 bps
   roundtrip on both legs — do not re-apply 15 bps), migrations,
   concentration/risk diagnostics, temporal diagnostics for 2025/2026Q1.
4. Immutable manifests + append-only evidence, then GO / INCONCLUSIVE / NO-GO.
