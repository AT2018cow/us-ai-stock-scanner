# Action List usage acceptance — frozen Generalized-v0 2026-10-12 (read-only)

**Verdict: GO (conditional — see blockers).** Scope: usability of the
frozen artifact as a human-research shortlist. NOT a returns claim, NOT
a production promotion, NOT a re-rating of any name. Alpha/profitability
is explicitly out of scope for this round.

## Method (no recompute)

Read-only review of `runs/generalized-v0/2026-10-12_2d89194_generalized_v0_20261012_01/`
(decisions.jsonl 62, action_list.md + weekly_review.md 15 each, manifest,
research diagnostics). Checked: list↔decision token agreement, evidence
richness per listed name, asof completeness, UNRATED/C handling,
WATCH_BREAKOUT wording, trigger specificity. Human verification time:
N/A in agent review — must be measured by a human researcher.

## Acceptance table (top 15 + notable off-list)

| symbol | action | worth_opening | reject_or_caveat | missing_key_evidence | next_action_answerable |
|---|---|---|---|---|---|
| ETN | PRIORITY_REVIEW | Y | — | none (20 pos) | yes — Review now; downgrade on A-loss/READY-loss |
| KO | PRIORITY_REVIEW | Y | valuation percentiles at 1.0 (stated) | none (21 pos) | yes — same trigger shape |
| EOG | PRIORITY_REVIEW | Y | — | none (20 pos) | yes |
| JNJ | PRIORITY_REVIEW | Y | — | none (21 pos) | yes |
| MSFT | PRIORITY_REVIEW | Y | 2 risks incl. valuation (stated) | none (20 pos) | yes |
| TMO | PRIORITY_REVIEW | Y | — | none (19 pos) | yes |
| AMD | WATCH_PULLBACK | Y | extended; wait instruction clear | none | yes — normalize-to-band trigger |
| AMAT | WATCH_PULLBACK | Y | extended; wait instruction clear | none | yes |
| META | WATCH_PULLBACK | Y | extended; wait instruction clear | none | yes |
| CRM | WATCH_BREAKOUT | unknown | RS evidenced-met; blocker is drawdown/vol/sma50-slice, none evidenced (values not in artifact) | exact gate unrecoverable read-only | PARTIAL — needs silent-band answer first |
| TXN | WATCH_BREAKOUT | unknown | NO ret60 AND NO RS evidence at all (ret60-silent class) | the READY blocker itself | PARTIAL — needs silent-band answer first |
| CAT | WATCH_BREAKOUT | Y | explicit ret60/RS weakness + 1 missing (stated) | interest coverage (disclosed) | yes |
| LIN | WATCH_BREAKOUT | Y | explicit RS weakness (-12.3%) | — | yes |
| PG | WATCH_BREAKOUT | unknown | RS-silent: RS = +2.16% ret60 minus 6.42% QQQ = **-4.26%** (gate ≥ -3%, no item) | the READY blocker itself | PARTIAL — needs silent-band answer first |
| GOOGL | WATCH_BREAKOUT | unknown | RS-silent: RS = +1.73% minus 6.42% = **-4.69%** (no item); 1 immaterial missing | the READY blocker itself | PARTIAL — same as TXN |
| XOM | HOLD_MONITOR (off-list) | N | B grade is entity-UNVERIFIED (holdings-CIK/opco-facts question open) — do not use | verified issuer identity | no — pending P0 entity selection |
| HON | AVOID (off-list) | N | correctly excluded (UNRATED via filing-facts skew gate) | Q3 facts recognition | n/a (correctly out) |
| GS | AVOID (off-list) | N | correctly excluded (UNRATED, tag vocabulary) | broker revenue tags | n/a (correctly out) |
| BAC/JPM/MS/WFC | AVOID (off-list) | N | correctly excluded (C = missing-balance + narrow risks, NOT leverage verdicts) | specialist bank semantics | n/a (correctly out) |

## Top 3 blockers (by decision impact)

1. **Silent READY-blockers on the shortlist (TXN, GOOGL, PG, CRM).** A reviewer
   asking "what flips this to READY" finds no answer in the artifact:
   GOOGL/PG sit in the RS silent band (-4.69%/-4.26%, reconstructed from
   frozen row + manifest QQQ); TXN lacks ret60 AND RS evidence entirely;
   CRM passes RS but blocks on an unevidenced drawdown/vol/sma50 gate.
   Recommend the scoped evidence-completeness micro-PR (additive
   neutral/info items for near-miss gates; no state/score/threshold
   change; parity-tested). Not a rerun trigger.
2. **Frozen artifact has no CIK traceability (0/62).** Fixed in main
   post-freeze (P0); do NOT rewrite history. Any name reused from this
   artifact must be re-verified under current main first.
3. **XOM-B in this artifact is entity-unverified.** HOLD placement is
   luck, not validation; excluded from all conclusions pending the P0
   entity-selection outcome.

## GO rationale (what passed)

- Actionable shortlist within attention capacity: 6 fully-evidenced
  PRIORITY names + 5 readable WATCH names with specific triggers + 4
  WATCH names flagged unknown with exact silent-band reasons (reviewable
  with caveats, not blocked).
- List↔decision consistency: token agreement on all 15; no recompute.
- asof complete (62/62); decision_date from QQQ session (no future data).
- No false READY: all 14 READY fully gate-evidenced; no "buy now" language.
- UNRATED/C correctly OFF the lists with stated reasons.
