# Quality failure cases (first versions, 2026-10-09 post-hoc decisions)

No re-weighting proposed. Each case: what v1 says, what the accounting
reality is, and what evidence would settle applicability.

## JPM — bank C driven by leverage semantics (not asset quality)

- v1: grade C, conf 0.53; risks include `net_debt_to_ebitda_weak` and
  `interest_coverage_weak` (values in decisions.jsonl).
- Reality: deposits (~$2.4T class) are counted as debt; net interest
  income is the earnings engine, not a cost to cover. The two risk codes
  invert meaning for a deposit franchise.
- Settling evidence: NII ex-provisions trend, CET1 trajectory, net
  charge-off rate — none are v1 inputs today.

## BAC / MS / WFC — same C cluster, same mechanism

- All C with leverage/coverage-driven risks; franchise quality (deposit
  share, capital ratios) invisible to v1. Corroborates JPM, not
  independent variation.

## GS — correct entity, wrong vocabulary (UNRATED, conf 0.45)

- Identity verified (0000886982, 642 XBRL tags). Missing 9: revenue tags
  absent because broker-dealers report `RevenuesNetOfInterestExpense`,
  `InvestmentBankingRevenue`, `BrokerageCommissionsRevenue` — none in
  v1's revenue tag map. NI/OCF facts present.
- Settling evidence: broker revenue-tag alias research (input expansion,
  NOT a weight change; graded effect must be re-validated if added).

## XOM — subsidiary entity, unmeasurable (UNRATED, conf 0.17)

- Mapped 0002115436 (Holdings, 34 filings); operating company 0000034088
  (1001 filings) sits elsewhere. 14 core metrics missing; identity gate
  fires `operating_entity_unverified`.
- Open research question (entity SELECTION, not scoring): when the mapped
  entity yields no measurable operating economics, should the pipeline
  prefer the operating CIK? No change proposed here.

## AMT — REIT B on NI-based metrics (readable, unverified)

- Grade B, conf 1.0, zero missing. But NI/depreciation-driven components
  (profitability_cash, valuation percentiles) measure GAAP constructs
  that REIT economics explicitly replace with FFO/AFFO.
- B must not be compared with ordinary B's. Settling evidence: FFO/share
  path, AFFO margin, Debt/EBITDAre, fixed-charge coverage.
