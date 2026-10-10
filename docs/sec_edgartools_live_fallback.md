# Live SEC fallback — EdgarTools ordinary USD 10-Q

Status: MVP correctness follow-up after PR #44 evidence.

## Purpose

The production scanner still treats SEC Company Facts as its primary fundamentals
source. PR #44 showed that many ordinary U.S. 10-Q filings contain usable filing-level
XBRL even when the Company Facts aggregation does not expose the latest accession
through the scanner's recognized core concepts.

This change adds one deliberately narrow fallback:

1. the latest periodic filing is an ordinary 10-Q;
2. Company Facts does not cover that accession;
3. EdgarTools can read the exact accession;
4. consolidated standard `us-gaap` Revenue, Net Income, and Operating Cash Flow
   are all available in USD;
5. after the filing facts are merged **in memory**, the repository's existing
   reconstruction layer must prove that the latest rolling TTM for all three core
   flows is driven by that accession.

Only then may the latest-filing integrity blocker clear.

## Architecture

```text
SEC Company Facts (primary)
        |
        | latest 10-Q accession missing from recognized core facts
        v
EdgarTools exact-filing XBRL
        |
        | standard us-gaap + consolidated + USD only
        v
small in-memory Company Facts-compatible patch
        |
        v
existing FactRecord extraction
        |
        v
existing quarter/YTD/TTM reconstruction
        |
        v
existing accounting metrics
        |
        v
existing Company Quality -> StockDecision
```

EdgarTools does not calculate Company Quality, Entry Quality, Action State, TTM,
valuation, or accounting ratios.

The raw SEC Company Facts cache is never modified by the fallback.

## Strict eligibility

The live fallback does **not** support by default:

- 20-F;
- 40-F;
- IFRS normalization;
- non-USD core financial statements;
- FX conversion;
- custom-taxonomy-only core concepts;
- a filing that cannot produce a current rolling TTM using the existing accounting
  reconstruction rules.

These cases stay fail-closed and may remain `UNRATED`.

## Live-only revenue aliases

PR #44 evidence showed two recurring standard `us-gaap` revenue concepts that are
useful in the live path:

- `RevenueFromContractWithCustomerIncludingAssessedTax`;
- `RegulatedAndUnregulatedOperatingRevenue`.

They are added as **live-only aliases**. The historical/replay `REVENUE_TAGS`
contract is unchanged in this PR.

## Currency semantics

`fundamental_reporting_currency` / `fundamental_currency_supported` now inspect
the latest periodic accession when one is known.

Historical or supplemental USD facts elsewhere in the filing history no longer make a
foreign issuer appear USD-supported. Mixed core currencies also fail closed.

No FX normalization is introduced.

## Provenance

Canonical decisions expose:

- `fundamental_source`;
- `fundamental_edgartools_fallback_used`;
- `fundamental_edgartools_fallback_status`;
- `fundamental_edgartools_fallback_version`;
- `fundamental_edgartools_fallback_fact_count`;
- latest periodic filing date/form/accession;
- reporting currency and currency-supported flag.

The validator reports fallback usage and status counts.

## Stop rule

This is intended to be the final common-case SEC expansion before prospective
observation unless the real-data acceptance run reveals a concrete correctness defect.

Do not use the acceptance run to justify:

- broad taxonomy expansion;
- IFRS support;
- FX infrastructure;
- Quality threshold changes;
- broad historical tuning.

If ordinary USD 10-Q cases work and unsupported cases fail closed, proceed to formal
prospective observation.

## Review evidence to submit

After this PR is merged, run one **experiment** full scan. Do not use `--formal`.

### Environment

Normal production installation now includes EdgarTools:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

SEC identity can use the existing repository variable:

```bash
export SEC_USER_AGENT="scanner-name your_email@example.com"
```

or EdgarTools' preferred explicit identity:

```bash
export EDGAR_IDENTITY="Your Name your_email@example.com"
```

If both are present, `EDGAR_IDENTITY` is used by EdgarTools.

Never commit either value.

### Run

```bash
python scripts/run_mvp_full_scan.py
```

Do **not** run `--formal` yet.

### Evidence directory

Create a separate evidence PR containing:

```text
evidence/mvp_edgartools_fallback/<decision_date>_<code_sha7>/
  README.md
  run_manifest.json
  validation.json
  decisions.jsonl
  action_list.md
  weekly_review.md
  detailed/
  full_scan.log
  ai_watchlist.csv
  ai_watchlist.sha256
  fallback_cases.md
```

The evidence README must record:

- exact code SHA and command;
- decision date and strategy style;
- experiment mode;
- validator PASS/FAIL and warnings;
- the `fundamental_fallback` counts from validation;
- whether inputs or outputs were manually modified;
- which identity variable was used: `EDGAR_IDENTITY` or `SEC_USER_AGENT`,
  **name only, never its value**.

### fallback_cases.md

Include one compact section for:

- EXLS;
- JCI;
- PYPL;
- CDNS;
- NXPI;
- NEE;
- TTAN;
- TSM;
- ASML;
- SAP;
- every additional decision where
  `fundamental_edgartools_fallback_used == true`;
- every additional decision whose fallback status is neither `not_needed` nor
  `ineligible_form`.

For each case include only:

- symbol;
- Quality grade / confidence;
- Action / Entry;
- `fundamental_data_asof`;
- latest periodic filing date/form/accession;
- `fundamental_source`;
- fallback used/status/version/fact count;
- reporting currency / currency-supported;
- latest-filing coverage flag;
- relevant Quality missing/risk codes.

Do not copy raw filing XBRL into the evidence package.

### Do not submit

- `.env`;
- SEC/EdgarTools identity values or email;
- Alpaca keys/secrets;
- raw SEC Company Facts or submissions caches;
- raw EdgarTools filing/XBRL/cache files;
- Alpaca raw caches;
- virtualenv;
- unrelated bulk outputs.

### Review questions

The evidence review will check:

1. EXLS / JCI / PYPL / CDNS / NXPI recover through the exact-filing path when
   their latest 10-Q can drive current rolling TTM;
2. recovered decisions use the latest filing date rather than silently retaining old
   annual/quarter values;
3. ordinary Company Facts controls remain unchanged;
4. TTAN and other unsupported/incomplete cases remain safely `UNRATED`;
5. TSM / ASML / SAP remain non-USD or otherwise unsupported rather than being
   incorrectly promoted by incidental USD facts;
6. fallback usage is bounded and Action List compression remains usable;
7. no historical/replay regression is introduced;
8. if these checks pass, SEC expansion stops and the next step is `--formal`
   prospective observation.
