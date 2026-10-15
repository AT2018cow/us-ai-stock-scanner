# M2 Hypothesis Backlog for M3 Pre-registration (frozen 2026-10-15)

Exactly 3 falsifiable, orthogonal candidates. Each states mechanism, scope,
falsifier, data limits, and validation feasibility. No thresholds change v1.

## H1-Quality (`quality_v2_accounting_core`)

- Mechanism: score negative accruals as supportive when OCF/NI>=1.0 (do not
  penalize OCF>NI); replace binary FCF>0 with fcf_margin + operating_margin
  pillars; exempt revenue_yoy>=25% and OCF/NI>=0.8 rows from point-in-time
  working-capital gap penalties.
- M2 evidence: 642 B->A / 259 C->B accrual-only upgrades; 129 penalized B rows reach A combined.
- Falsifier: pre-registered variant changes <1% of B/C grades on dev dates, or
  human reviewers reject the new pillar explanations at parity acceptance.
- Limits: banks/REITs need specialist accounting; exemption is dev-only evidence.
- Feasibility: pure function of existing SEC facts; preflight without returns.

## H2-Entry (`entry_v2_structure_and_pullback_seam`)

- Mechanism: close the (1.08,1.10] SMA50 and (12%,15%] ret20 dead-zone into
  WATCH_PULLBACK; require sma50_to_sma200>=0.98 for ENTRY_READY; partition
  WATCH_BREAKOUT into NEAR_BREAKOUT vs LAGGING sub-reasons.
- M2 evidence: dev dead-zone pullbacks hide in BREAKOUT; bucket split MILD=411/NEAR=1808/WEAK=2256.
- Falsifier: seam rows show no date-equal excess gap vs NEAR on dev dates, or
  reviewers find the sub-reasons unactionable.
- Limits: pre-M1 snapshots leave some gates UNOBSERVABLE; dev returns exploratory.
- Feasibility: exact ratio from existing columns; state-partition preflight first.

## H3-Action (`action_v2_ready_priority_and_joint_rank`)

- Mechanism: promote high-conviction B (score>=0.68, conf>=0.80) + ENTRY_READY
  above unconfirmed WATCH_BREAKOUT (or a SECONDARY_READY_REVIEW slot); rank
  PRIORITY_REVIEW by 0.60*quality + 0.40*entry instead of Quality-only order.
- M2 evidence: 18/24 dev dates truncate A+READY; 272 high-score B+READY obs suppressed.
- Falsifier: re-ranking swaps <2 Top-15 members on dev dates, or reviewers rate
  the joint rank less trustworthy than Quality-first order.
- Limits: member swaps do not imply return improvement; utility-first metric.
- Feasibility: ranking-only preflight on frozen decisions; no rescoring needed.

_End of backlog. M3 may select 0-3 of these; selection needs a separate protocol._
