# MVP v1.1 PR-A — data-risk triage review report (short)

Date: 2026-10-14
Code under test: PR #70 head `d6e8d78cd29f4873f1778123993ec7313e390fab`
(CI pass on this head, run 38451082287; local 675 tests OK)
Tool: `scripts/mvp_v11_data_risk_audit.py` (read-only triage; no labels, masks,
or decisions changed; no returns computed; no SEC/Alpaca access)

## 1. Deliverables

- `data_risk_review_summary.json` — SHA256 `11bcf6a2ad14762831fa1868d490eeaae9bd3fd081246d8cd67202900e7feaea`
- `event_review_queue.csv` — SHA256 `3bf0844fce0e2df40e81eea69eb2445c24a6abeaff7922473ca315b88143204e`
- All 52 dispositions remain `UNREVIEWED` for your adjudication.

Input pins verified by the tool: v3 CSV `2a4600ee…`, metadata `1574a855…`,
events `20dc8670…`, frozen ranking `4b0d25e0…`.

## 2. Headline numbers

- 52 events = 51 audit-only + 1 WOLF label-nulling (`REORG_JUMP_BACKDATED
  2025-09-30`, 2×60d + 5×120d labels nulled; not in any Top-k).
- **Top-k exposure (triage priority, not proof of influence):**
  - `HEI` 2025-12-31 — in **Top-5 and Top-15 on the event date**; decision was
    grade A / PRIORITY_REVIEW.
  - `HEI` 2023-12-29, 2024-12-31, 2025-08-29 — in Top-15 on the **previous**
    date (C AVOID / A HOLD_MONITOR / A WATCH_BREAKOUT respectively).
- 21 events with severe share-ratio changes (>10× or <0.1×), 5 with sharp
  price moves (>3× or <⅓×, excluding WOLF's 23.3× which is already nulled).
- 346 missing-`fundamental_data_asof` rows unchanged (all UNRATED/AVOID per B0).
- All 52 events are `in_v3_on_event_date = true`; none of the Top-k-exposed
  events had missing fundamentals on the event date.

## 3. Patterns observed in the frozen data (context for your adjudication)

1. **HEI recurring share-count flip (4 events, incl. the only Top-5 exposure).**
   `shares_outstanding` alternates ~55M ↔ ~138–139M when the fiscal-year
   (Oct 31) filing replaces the July one, every year (2023, 2024, 2025);
   `shares_asof_end` alternates 07-31 ↔ 10-31. Market cap jumps proportionally
   (e.g. 2025-11-28 $17.4B → 2025-12-31 $45.0B) while price stays continuous
   (price_ratio 0.87–1.05). Suspected systematic shares-source/scale or
   share-class artifact, not a real corporate action — needs your evidence
   ruling; it distorts valuation/score inputs on affected dates.
2. **Extreme share-ratio spikes with ~1.0 price ratio (HXL 983,561×; SW
   5,193,583×; LAES 154,468×; UNIT 2,390,363×; SBET 256×; and PKG/SKY/TBLA
   1000× ↔ 0.001× flip-flop pairs).** Pattern consistent with share-count
   unit/scaling artifacts; price/return labels look continuous, so the risk is
   to score inputs (market cap, shares_yoy), not to forward labels.
3. **Sharp price moves with flat shares (CORZ 38.7× Jan-2024; LAES 14.9×
   Dec-2024; UMAC 9.9× and QUBT 6.3× Nov-2024).** These are real-looking price
   dislocations embedded in forward labels; flag for label-uncertainty masks if
   you deem the move data-quality rather than market reality.
4. **WOLF nulling already applied** (labels nulled, not zero-filled) — matches
   the registered audit; the follow-on 2025-11-28 SHARE_CLIFF event (0.165×)
   remains audit-only.

No event disposition, mask, or exclusion was applied anywhere — per protocol
these await your ruling on handling principles and any additional PIT checks.

## 4. Available PIT provenance columns (for your verification plan)

`fundamental_data_asof`, `market_asof`, `shares_asof_end`,
`current_debt_ratio_source`, `inventory_growth_gap_source`,
`pe_hist_percentile_source`, `ps_hist_percentile_source`, `watchlist_source`.
No filing-accession/CIK/currency columns exist in the frozen CSV — filing
public-time and entity identity cannot be certified from this file alone.

## 5. Verdict

`DATA_RISK_REVIEW_REQUIRED` — `ready_for_candidate_returns: false`. The
automated triage alone passes nothing; the 52 dispositions, filing
public-time evidence, entity/identity checks, and a frozen event-handling /
valid-mask protocol need your decision before the candidate matrix can be
approved and run on 2023–2024.
