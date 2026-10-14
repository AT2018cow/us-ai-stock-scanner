# M0 Baseline Inventory & Provenance Audit (2026-10-14)

- **Audit Mode**: Read-only (`RETROSPECTIVE_EXPLORATORY` & `POINT_IN_TIME_RECONSTRUCTED` cross-sections; zero network calls, zero forward-return computation, zero v1 policy changes).
- **Verified `main` HEAD**: `1a2612e4736c82cb9407bf3ca536e82b6f389578`
- **Verified `evidence-observations` HEAD**: `68143bff19f60f014e237d1f95eda28adf074b9b`

## 1. Frozen Snapshot & Evidence Inventory

| Artifact ID | Scope & Decision Date | Code SHA | File / Archive Location | `decisions.jsonl` / Primary SHA256 | Decisions | CIK Traceable |
| --- | --- | --- | --- | --- | ---: | --- |
| `mvp_v1_full_2026-10-09_313c5ff` | 510-stock AI Watchlist (`risk_off`), `2026-10-09` | `313c5ffedc9c1cf837b70d5e95d01d545d5c592f` | `evidence/archive/mvp_edgartools_fallback_fix/2026-10-09_313c5ff/` | `1e04333aad598e5cb94501a1cf73075039221b0a064297736043041fff8bbf60` | 510 | `0/510` (pre-PR #59/#66) |
| `mvp_beta_2026-10-12_220a471` | 62-stock 3-Source Discovery Union (`us_core`+`thematic`+`manual`), `2026-10-12` | `220a4716c411bd7e9e80f9f7f89502f6ab1ff0ac` | `evidence-observations:runs/mvp-beta/mvp_beta_20261012_01/` | `533ff08f80b187bc57f16c0d969ab7b87c82457fbd36d017b0ae53984c065ac6` | 62 | `62/62` (post-PR #66) |
| `historical_v3_repaired` | 39 monthly signal dates (`2023-01` to `2026-03`), 670 symbols | `2d8919444828643f7b888f90907e0b0e6632bfc4` | `evidence-observations:runs/historical-selection-v1/historical_selection_v1_20261011_03/` | `2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e` | 25,025 | N/A (`union_superset_approx`) |
| `mvp_v11_pr_a_archive` | PR #70 Historical Optimizer (`NO-GO / KEEP V1`) + 13 SEC/PIT cases | `9514166907e7f279fd6efd6f77f672badb9bd6f7` | `evidence-observations:runs/mvp-v11-pr-a-20261014/` | Commit `68143bff19f60f014e237d1f95eda28adf074b9b` | 1,440 paired | 13 audited cases (`UNVERIFIED` binding) |
| `p0_identity_acceptance_02` | PR #64 L0/L1/L2 provenance & `UNCOMPARABLE` fixture matrix | `11cc71d` (merged) | `evidence-observations:runs/p0-identity-v1/p0_identity_20261013_02/` | Commit `fd8328b389a0efe0c300ce8654dd30448ef8f265` | 6 cases | Synthetic + cached fixtures |
| `business_model_quality_v0` | PR #62 11-company specialist accounting & entry silent-gate matrix | `f1090f1` (merged) | `data/research/business_model_quality_v0/` | Tracked in `main` | 11 symbols × 3 dates | 11/11 CIK inventoried |

## 2. Cross-Sectional State Distributions

### 2.1 510-Symbol AI Watchlist Snapshot (`2026-10-09`, code `313c5ff`)
- **Company Quality**: `A=183`, `B=205`, `C=92`, `UNRATED=30`
- **Entry Quality**: `ENTRY_READY=47`, `WATCH_PULLBACK=85`, `WATCH_BREAKOUT=141`, `TREND_DAMAGED=230`, `INSUFFICIENT_DATA=7`
- **Action State**: `PRIORITY_REVIEW=19` (15 in Daily/Weekly shortlist; **4 omitted by Top-15 cap**: `EXPD`, `ZM`, `JCI`, `SAIC`), `WATCH_PULLBACK=33`, `WATCH_BREAKOUT=55`, `HOLD_MONITOR=281` (includes **23 `B + ENTRY_READY`** and **76 `A + TREND_DAMAGED`**), `AVOID=122`
- **Silent Entry Gates Detected**:
  - `WATCH_BREAKOUT` with **0 Entry risk items**: `74` symbols (RAMP, DUOL, TDY, TDC, PYPL, VLTO, WDAY, CRM, CGNX, TXN, FIX, STLD...)
  - `TREND_DAMAGED` **without a trend-damage risk item** (triggered by `days_below_sma200 >= 15` or `sma200 in [0.95, 1.00)`): `14` symbols (ADSK, ISRG, UI, TYL, UBER, CTSH, G, CHKP, HUBB, BAH, TSLA, SBAC...)

### 2.2 62-Symbol Generalized MVP Beta Snapshot (`2026-10-12`, code `220a471`)
- **Company Quality**: `A=24`, `B=31`, `C=5`, `UNRATED=2`
- **Entry Quality**: `ENTRY_READY=14`, `WATCH_PULLBACK=3`, `WATCH_BREAKOUT=16`, `TREND_DAMAGED=29`, `INSUFFICIENT_DATA=0`
- **Action State**: `PRIORITY_REVIEW=6` (`ETN`, `KO`, `EOG`, `JNJ`, `MSFT`, `TMO`), `WATCH_PULLBACK=3` (`AMD`, `AMAT`, `META`), `WATCH_BREAKOUT=7` (`CRM`, `TXN`, `CAT`, `LIN`, `PG`, `GOOGL`, plus rank #16 `LLY`), `HOLD_MONITOR=39` (includes **8 `B + ENTRY_READY`** and **8 `A + TREND_DAMAGED`**), `AVOID=7`
- **Silent Entry Gates Detected**:
  - `WATCH_BREAKOUT` with **0 Entry risk items**: `9` symbols (`CRM, TXN, PG, GOOGL, ABBV, AAPL, NEM, EQIX, INTC`)
  - `TREND_DAMAGED` **without a trend-damage risk item**: `3` symbols (`ISRG, COST, WMT`)
