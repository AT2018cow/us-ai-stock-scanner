# M3 Candidate Preflight Report (frozen 2026-10-15, non-return gates)

Five pre-registered variants evaluated offline: v1_baseline, h1_quality_only,
h2_entry_only, h3_action_only, v2_combined. Snapshot v1_baseline counts come from
frozen decisions.jsonl; variants rebuild from emitted evidence maps (partial
vectors). Rebuild fidelity (v1-rebuild Top-15 Jaccard vs frozen): snap510=0.7647058823529411, snap62=0.7647058823529411.
Snapshot policy verdicts compare v1-rebuild vs variant-rebuild (same information),
and snapshot Axis7 cases use surgical H3 on frozen decisions (exact mapping+ranking,
no rebuild degradation). Snapshot variant rows are dominated by partial-vector
INSUFFICIENT states, so snapshot policy deltas are only interpretable rebuild-vs-rebuild;
hist_dev carries the policy signal. Hist_dev uses full rows via wired builders.
Return figures are 2023-2024 dev date-equal exploratory only.

## 1. Variant-by-variant non-return gates

### snap62
- v1_baseline: A/B/C/U=24/31/5/2; READY/PB/WB/TD=14/3/16/29; PR/HM/AV=6/39/7; Jaccard-vs-v1=1.0
- h1_quality_only: A/B/C/U=31/25/5/1; READY/PB/WB/TD=15/4/20/23; PR/HM/AV=7/33/6; Jaccard-vs-v1=0.6666666666666666
- h2_entry_only: A/B/C/U=25/31/5/1; READY/PB/WB/TD=14/4/21/23; PR/HM/AV=6/37/6; Jaccard-vs-v1=0.7647058823529411
- h3_action_only: A/B/C/U=25/31/5/1; READY/PB/WB/TD=15/4/20/23; PR/HM/AV=10/33/6; Jaccard-vs-v1=0.5
- v2_combined: A/B/C/U=31/25/5/1; READY/PB/WB/TD=14/4/21/23; PR/HM/AV=10/30/6; Jaccard-vs-v1=0.5
### snap510
- v1_baseline: A/B/C/U=183/205/92/30; READY/PB/WB/TD=47/85/141/230; PR/HM/AV=19/281/122; Jaccard-vs-v1=1.0
- h1_quality_only: A/B/C/U=234/170/86/20; READY/PB/WB/TD=58/86/159/200; PR/HM/AV=33/242/107; Jaccard-vs-v1=0.5
- h2_entry_only: A/B/C/U=187/204/99/20; READY/PB/WB/TD=57/86/160/200; PR/HM/AV=23/267/119; Jaccard-vs-v1=0.7647058823529411
- h3_action_only: A/B/C/U=187/204/99/20; READY/PB/WB/TD=58/86/159/200; PR/HM/AV=41/249/119; Jaccard-vs-v1=0.5789473684210527
- v2_combined: A/B/C/U=234/170/86/20; READY/PB/WB/TD=57/86/160/200; PR/HM/AV=43/232/107; Jaccard-vs-v1=0.5789473684210527
### hist_dev_24_dates
- v1_baseline: A/B/C/U=3852/5650/4489/1123; READY/PB/WB/TD=1781/2604/4475/5035; PR/HM/AV=601/6190/6389; Jaccard-vs-v1=1.0
- h1_quality_only: A/B/C/U=4234/5323/4434/1123; READY/PB/WB/TD=1781/2604/4475/5035; PR/HM/AV=669/5989/6335; Jaccard-vs-v1=0.711447
- h2_entry_only: A/B/C/U=3852/5650/4489/1123; READY/PB/WB/TD=1723/2983/4154/5035; PR/HM/AV=579/6190/6389; Jaccard-vs-v1=0.895935
- h3_action_only: A/B/C/U=3852/5650/4489/1123; READY/PB/WB/TD=1781/2604/4475/5035; PR/HM/AV=795/5996/6389; Jaccard-vs-v1=0.780279
- v2_combined: A/B/C/U=4234/5323/4434/1123; READY/PB/WB/TD=1723/2983/4154/5035; PR/HM/AV=868/5767/6335; Jaccard-vs-v1=0.606843

## 2. Defect reduction (v1_baseline -> v2_combined)

- Axis 1 cash-cow accrual_weak: hist_dev 2253->0 (Δ-2253); snap62 17->0 (Δ-17); snap510 110->0 (Δ-110).
- Axis 2 penalized high-growth B: hist_dev 146->0 (Δ-146).
- Axis 5 dead-zone in BREAKOUT: hist_dev 411->32 (Δ-379).
  (Residual 32 = dead-zone-extension rows failing the extra core-uptrend
  conditions: days_below>3, MA alignment <0.98, or defensive gate.)
- Axis 8 inverted MA in READY: hist_dev 58->0 (Δ-58).

## 3. Frozen casebook verification (38 M2 cases)

- TRUE=26, CONTROL_PRESERVED=6, FALSE=6 (detail in m3_casebook_verification.csv).
  - M2-A5-CRM01 CRM: v1=A/WATCH_BREAKOUT/WATCH_BREAKOUT/p10 v2=A/WATCH_BREAKOUT/WATCH_BREAKOUT/p15 (v2 state=WATCH_BREAKOUT [same-info v1-rebuild comparator: A/WATCH_BREAKOUT/WATCH_BREAKOUT/p12])
  - M2-A7-TRUNC02 EXPD: v1=A/ENTRY_READY/PRIORITY_REVIEW/p16 v2=A/ENTRY_READY/PRIORITY_REVIEW/p22 (v2 priority=22 [surgical H3 on frozen decisions (exact); full v2_combined rebuild differs on partial features] [same-info v1-rebuild comparator: A/ENTRY_READY/PRIORITY_REVIEW/p17])
  - M2-A7-BREADY02 ATO: v1=B/ENTRY_READY/HOLD_MONITOR/p165 v2=B/ENTRY_READY/PRIORITY_REVIEW/p27 (v2 priority=27)
  - M2-R-SEL01 BRKR: v1=A/ENTRY_READY/PRIORITY_REVIEW/p15 v2=A/ENTRY_READY/PRIORITY_REVIEW/p19 (marginal member still ahead (p19 vs p22))
  - M2-R-REJ01 AVT: v1=B/ENTRY_READY/HOLD_MONITOR/p135 v2=B/ENTRY_READY/PRIORITY_REVIEW/p22 (v2 priority=22)
  - M2-R-REJ02 AVY: v1=B/ENTRY_READY/HOLD_MONITOR/p127 v2=B/ENTRY_READY/PRIORITY_REVIEW/p26 (v2 priority=26)

## 4. Top-15 movement

- 30 membership changes recorded in m3_top15_diff_snap62_and_snap510.csv (snap62, snap510, 2023-01-31, 2024-06-28, 2024-12-31).

## 5. M4 readiness recommendation

- If gates pass (defects fall, controls preserved, movement explainable): proceed to M4 formal
  2025/2026Q1 held-out comparative validation with pre-registered utility + return metrics.
- If any control breaks or defects do not fall: revise the candidate, do not relax the gate.

_End of M3 preflight. No forward-return optimization was performed._
