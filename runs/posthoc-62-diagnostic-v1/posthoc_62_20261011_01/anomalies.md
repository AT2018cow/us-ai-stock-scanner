# Anomaly records — posthoc_62_20261011_01 (2026-10-09 decisions)

Judgement basis: the rating shown is always the frozen v1 output. "Anomaly"
means the v1 output is surprising for a human reviewer and needs either a
business-model semantic (banks/REITs) or a data-identity check (XOM/GS).
No weight, mapping, or threshold was changed in response.

## Banks: v1 accounting semantics unfit (research only, no re-score)

| symbol | grade | entry | action | human reading |
|---|---|---|---|---|
| BAC | C | TREND_DAMAGED | AVOID | levered balance sheet reads as weak |
| JPM | C | WATCH_BREAKOUT | AVOID | highest-quality US bank lands in C |
| MS | C | TREND_DAMAGED | AVOID | broker leverage penalised |
| WFC | C | WATCH_BREAKOUT | AVOID | same pattern |
| AXP | B | TREND_DAMAGED | HOLD_MONITOR | charge-card model scores less badly |
| GS | UNRATED | TREND_DAMAGED | AVOID | 9 core metrics missing (see below) |

Criterion for flagging: SIC-major 6 (finance) with grade C/UNRATED while
the franchise is investment-grade by any human standard. Required future
work: specialist bank/broker semantics (leverage, NII, credit costs) before
any cross-model comparability claim. C must NOT be read as "bad balance
sheet" for banks.

## REITs: graded B across the board, semantics unverified

AMT (B/ENTRY_READY), EQIX (B/WATCH_BREAKOUT), O (B/TREND_DAMAGED), PLD
(B/TREND_DAMAGED). FFO-based economics are not what the v1 metrics
measure (net income, leverage). B must NOT be read as cross-comparable
quality for REITs.

## XOM / GS UNRATED: identity + coverage under P0 review

- XOM: 14 core metrics missing (net margin, FCF, OCF conversion, growth,
  leverage, coverage, yields, percentiles, gaps); confidence 0.167.
- GS: 9 core metrics missing (margin, accruals, growth, leverage,
  coverage, current ratio, percentiles, gaps); confidence 0.45.
- XOM mapped company name reads "ExxonMobil Holdings Corp" (expected
  "Exxon Mobil Corporation") — possible subsidiary-CIK mis-mapping.
- Verdict: **no reliability claimed** for these two ratings pending the
  identity audit (asset record vs SEC CIK vs filing entity). Fail-closed
  UNRATED was the correct output given the inputs; the inputs themselves
  are suspect.
