# Non-Operating Gain Defense — Follow-up Issues (Post-PR #90)

Date: 2026-10-16. Companion to `docs/review_nonoperating_investment_gain_blind_spot_20261016.md`
(§7 attribution, §8 tickets T1–T3) and `docs/agent_specs/nonoperating_gain_defense_spec.md`.

Scope: PR #90 (`517e757`, three-layer tag-agnostic defense) is **approved as-is**.
The 45 new tests pass, the full suite (955 tests) is green, and the implementation is
strictly better than the ticket in two places (margin-gap instead of ratio trigger;
explicit guard against double-subtracting below-the-line gains from EBIT, locked by
`test_below_the_line_gain_tags_not_stripped_from_ebit`).
What follows is the complete residual-issue list — nothing is blocking, items P1-1–P1-3
are recommended for the next round, P2-1–P2-4 are backlog.

Verified against: `--recompute-v2` preview of the frozen 2026-10-15 `risk_off` snapshot,
live-path unit-test archetypes, and a quarterly-ratio re-screen of the local SEC facts
cache (read-only, no network).

---

## P1-1. Quarterly-spike hole (SHOP class) — genuine residual gap, needs Case C

**Problem.** The Layer-1 TTM margin gap is diluted by TTM averaging: a huge
single-quarter gain can hide behind a sub-threshold TTM gap. SHOP is the live proof —
quarterly unrealized gain is ~83% of quarterly net income, yet the TTM
`net_margin − operating_margin` gap is only **0.6pp** (threshold 5pp), so SHOP gets
no risk item and no badge; only its growth rate is silently substituted
(−15.4% → +51.3%).

**Evidence (quarterly re-screen, `NonoperatingIncomeExpense / quarterly Revenue`,
threshold ≥25%, absolute floor $200M):**

| Symbol | Quarterly nonop / revenue | TTM gap (Layer 1) | Caught by Layer 1? |
|---|---|---|---|
| GOOG | 82% ($98.0B / $119.8B) | +21.7pp | yes |
| WDC | 65% | +38.5pp | yes |
| SHOP | 36% ($1.3B / $3.58B) | +0.6pp | **no** |
| AMZN | 27% ($53.4B / $200.6B) | +5.4pp | yes (borderline) |

A quarterly trigger at 25% catches all four, including SHOP. The $200M absolute floor
is required: the screen also surfaced two stale-cache CIKs with 2022/2018 dates,
so a ratio-only trigger would generate noise from dead cache entries.

**Suggested fix.** Add Layer-1 **Case C (quarterly trigger)**: single-quarter
`NonoperatingIncomeExpense / quarterly Revenue ≥ 25%` with an absolute floor
(~$200M, tune once and freeze). Reuse the existing `nonoperating_gain_inflation`
risk code and `⚠️NonOp-Gain` badge — no new concepts. SHOP should then carry the
badge like ZM does.

**Acceptance.** (1) SHOP archetype gains `nonoperating_gain_inflation` in the
trigger-matrix test; (2) MSFT/BILL controls still clean; (3) stale-date cache entries
below the absolute floor stay silent (regression test with an old-dated fixture);
(4) 2026-10-15 recompute shows SHOP badged, Top-15 still clean names only.

---

## P1-2. Post-cron verification checklist (action, not code — most important item)

**Problem.** The `--recompute-v2` preview path is frozen by design: it appends risk
items and penalties but **does not re-score** (scores, grades, positives,
Highlights stay at pre-fix values). Therefore PR #90's production effect is
currently **unobserved** — the badge logic is proven, tomorrow's report is not.

**Suggested fix.** After the next daily cron, verify these four lines before
declaring PR #90 done in production (paste the result into the PR review-evidence
area):

1. GOOG / AMZN / ZM / NTNX carry the `⚠️NonOp-Gain` badge in a rendered report;
2. their growth figures show clean operating values (GOOG `+24.9%`, not `+114.7%`;
   ZM `+22.0%`, not `+174.0%`; AMZN `+24.6%`; NTNX `+58.8%`), and Highlights margins
   use the operating basis (GOOG `34.0%`, not `55.7%`);
3. SNPS `adjusted_net_income_yoy` no longer contains the $0.43B disposal gain
   (parsed-fund cache TTL is 24h — `sec_cache_ttl_submissions_sec: 86400` — so the
   Layer-3 tag takes effect at most one day after PR #90's first cron);
4. their attention ranks dropped vs the 2026-10-15 pre-fix snapshot
   (penalty −0.06 each, −0.12 when stacked with pre-earnings).

If any line fails, the live path has a break the preview cannot show — treat as P0.

---

## P1-3. Promote the one-off universe screen into the repo

**Problem.** The `/tmp` screen script did the decisive work (231-company first pass →
5 confirmed polluters + ZM/NTNX), but `/tmp` is ephemeral. Q3 10-Qs are arriving now,
and two known forward risks (Anthropic-series revaluation events; the AMZN $92B
unrealized balance still parked in AOCI, recyclable into P&L on IPO/liquidity events)
can create new polluters next quarter.

**Suggested fix.** Check in a read-only, cache-only `scripts/audit_nonop_gain_screen.py`
(no network, unit-testable on fixtures) implementing both lenses from this review
(TTM margin gap + P1-1 quarterly trigger), plus a one-line runbook entry:
"re-run after each earnings season; new hits go to the review queue, never
directly to production thresholds." Retrospective hits must stay retrospective —
no auto-promotion (per AGENTS.md §8).

**Acceptance.** Script runs offline against the facts cache, reproduces the
GOOG/AMZN/SHOP/WDC/ZM/NTNX/SNPS findings on demand, and exits non-zero-safe
(no scan/report side effects).

---

## P2-1. Flagged names vanish entirely (backlog, product call)

**Problem.** In the preview, GOOG/AMZN/NTNX appear in **no** rendered section:
outside the Top-15, below the 15-name cap-omitted A-bucket cutoff (double penalty
−0.12 pushes them past #30), and excluded from the B-bucket by grade. Compression
is working as designed, but the warning badge is then never seen by the user —
the evidence of the fix is invisible.

**Suggested direction.** A count line ("N names deprioritized on quality-integrity
grounds") or a small demoted-with-cause bucket. No scoring change; visibility only.
Needs an explicit product decision on whether demoted names deserve any surface.

## P2-2. Preview/live contradictions (backlog, cosmetic but confusing)

**Problem.** Preview staleness produces self-contradictory rows: ZM's radar row shows
the NonOp badge next to Highlights `"EPS YoY +174.0%"` (live value is `+22.0%`);
SHOP still shows `adjusted_net_income_yoy_weak −15.4%` (live: substituted to
`+51.3%`). Circulated screenshots will confuse readers.

**Suggested direction.** Either refresh Highlights/Why-Own strings inside the
`--recompute-v2` overlay, or stamp preview outputs with a uniform
"scores frozen at snapshot date; badges only" marker. Preview-only; production
rendering is unaffected.

## P2-3. Silent growth substitution leaves no trace (backlog)

**Problem.** When the YoY-gap rule fires without margin inflation (SHOP:
−15.4% → +51.3%), the report shows `+51.3%` with no badge while the 10-Q shows
`−15%` — an attentive user cannot reconcile the two numbers.

**Suggested direction.** One trace line in the detailed report when substitution
fires without `nonoperating_gain_inflation` (e.g. under Watchouts:
"Growth shown on operating-income basis; GAAP NI YoY distorted by base effect").
No scoring or ranking change.

## P2-4. Record T3 as deferred + sync §8 with as-built (backlog, ~15 min docs)

**Problem.** (a) The edgartools spike (T3) was never run — correctly so, since the
tag-agnostic layer removed its urgency, but "never run" and "deferred" must be
distinguished in writing or someone will re-raise it. (b) Review §8 T1/T2 specify a
ratio trigger; as-built is margin-gap — a future reader will look for ratio
thresholds that do not exist in code.

**Suggested direction.** Append a dated note to the review doc: "T3 deferred
(date), rationale: tag-agnostic Layer 1 supersedes mapping outsourcing; revisit only
if a tag-variant class escapes both TTM-gap and quarterly triggers." Correct §8 to
point at the as-built constants (`QUALITY_V2_NONOP_*` in
`src/ai_value_scanner/decision/quality.py`, `H3_NONOPERATING_GAIN_PRIORITY_PENALTY`
in `src/ai_value_scanner/decision/action.py`).

---

## Standing expectation (read before judging the next report)

Live-path archetype scores after de-pollution: GOOG **0.849/A**, ZM **0.858/A**,
NTNX **0.807/A**, AMZN **0.864/A**, WDC **0.843/A**, SHOP **0.855/A** (clean).
**The fix does not demote grades — and that is correct behavior.** GOOG's operating
margin (34.0%) and operating-income growth (+24.9%) are genuinely A-grade; the fix
removes the $99B of water, not the operating merit. Judge the next report by
**badge presence, clean growth/margin values, and rank drops** — never by grade
changes. Anyone asking "why still A" should be pointed at this section.

## Watch item (no action unless noisy)

`net_margin − operating_margin ≥ 5pp` can also come from structural sources
(persistently low cash tax rate, large recurring interest income on cash piles).
Such names would carry a permanent badge. After the next full-universe run, list
names where the flag persists across consecutive quarters; if the list is noisy,
add a persistence filter then — not now.
