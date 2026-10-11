# Candidate policy — what may change, what must not, what needs new evidence

Status after retrospective H1–H3 (`historical_selection_v1_20261011_02`).
**No production change is proposed in this document.**

## MUST NOT change (evidence insufficient or negative)

- Quality v1 weights, grades, thresholds, confidence/missingness handling.
  Rank IC ~0 and A/B<C composition do not authorize re-weighting; C's edge
  is distressed-rebound composition in an approximate universe.
- Entry v1 gates, QQQ benchmark, state machine. READY weakness and 28%
  persistence are diagnostics, not remap instructions. No SPY/sector switch.
- Action mapping, `_priority_sort_key`, 15 cap. E-first tested → no
  improvement → rejected. B+READY tested → negative → not promoted.
- IEX $2m pre-decision liquidity gate (H4 INCONCLUSIVE; no pairs measured).
- Candidate universe / discovery sources (frozen; union approx labelled).

## Under investigation (candidates WITHOUT promotion — need new evidence)

1. **Attention-design alternatives** (not order swaps): the 15-cap suppresses
   260–440 names/month; whether a secondary queue or different compression
   helps is untested. Requires: pre-registered candidate + prospective or
   independent temporal sample + component attribution.
2. **Quality applicability states** (banks/REITs/unknown/reporting-model
   non-comparability): H1 confirms heterogeneous accounting inside grades,
   but no verified business-model labels exist here. Requires: independent
   classifier + reviewed fundamentals before any comparability claim.
3. **Entry readiness semantics**: READY rarity/weakness + BREAKOUT weak-side
   mix suggest the *question* of what "ready" should mean, not an answer.
   Requires: stable interpretable evidence on a distinct sample.
4. **Liquidity metric**: snapshot-vs-20-session disagreement unmeasured.
   Requires: prospectively archived snapshot dollar-volume pairs (see
   liquidity_limitations.md).

## Validation plan before ANY production v2

1. Freeze candidate policy BEFORE viewing the final validation sample.
2. Test on a temporally distinct or genuinely prospective cohort
   (generalized-v0 prospective track is the designated next sample).
3. Keep v1 formal/prospective history as frozen comparator; never overwrite.
4. Report sample size, missingness, date/industry concentration, regime.
5. Never treat overlapping 20/60/120d rows as independent samples.
6. Separate decision-quality improvement from universe changes.

**Research GO ≠ strategy GO ≠ production GO.**
