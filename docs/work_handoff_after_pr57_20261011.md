# Work handoff after PR #57 — generalized US stock selection research

> Date: 2026-10-11
>
> Current `main`: `2d8919444828643f7b888f90907e0b0e6632bfc4`
> (merged PR #57: **Research: end-to-end generalized US stock Quality, Entry and liquidity validation**).
>
> This is the primary handoff for the next conversation. It supersedes older short-term
> handoff notes for the generalized-selection work. Historical evidence and previous
> handoff documents remain useful as audit history, but should not be treated as the
> current execution plan when they conflict with this document.

## 1. Product direction that must remain stable

The long-term product is no longer an AI-only stock scanner.

The durable decision core is:

```text
US Core Universe -------+
Thematic Universe ------+--> versioned candidate union
Manual Research Universe+          |
                                   v
                         Company Quality
                                ×
                           Entry Quality
                                |
                                v
                    StockDecision / Action List
                                |
                                v
                         Detailed Report
```

Key principles:

- **AI is an optional research theme**, not the definition of the investable universe.
- `core_ai`, `ai_enabler`, `ai_peripheral`, and `ai_smallcap` remain legacy
  AI discovery provenance only; they are not universal sectors, business-model
  classifications, market-cap cohorts, or Quality score inputs.
- Candidate discovery, actual company/business-model classification, and research
  themes are separate concepts and must stay separate in data/provenance.
- Company Quality × Entry Quality remains the canonical decision model.
- The user-facing product remains a small human-reviewed Action List, not automated
  trading, portfolio construction, position sizing, or broker execution.

## 2. PR granularity — change from earlier workflow

Do **not** split the next phase into many tiny PRs.

Use **outcome-sized PRs**: one PR should deliver a coherent research or policy outcome
with its code, tests, documentation and pre-registered evidence contract together.

Good reasons to split a PR:

- a production/correctness blocker must be fixed before the rest can be evaluated;
- two changes would make evidence attribution impossible;
- a migration is independently risky or backward-incompatible;
- a large external experiment must finish before a later policy decision is knowable.

Bad reasons to split:

- one script per PR;
- one documentation update per PR;
- separate PRs for Quality, Entry, liquidity and Action when they are part of one
  already-registered end-to-end research objective;
- evidence-only PRs for routine experiments.

Routine experiment evidence should be submitted as browsable Markdown/JSON/CSV/JSONL
files in the append-only `evidence-observations` branch, pinned by exact commit SHA,
with SHA256 checks. No ZIP and no routine evidence PR.

## 3. Current repository state

### 3.1 General discovery implementation

PR #56 is merged.

It added an opt-in three-source discovery path:

- US Core
- Thematic
- Manual

Default production behavior remains backward compatible: if
`discovery_source_files` is absent, the old AI watchlist path remains active.

New opt-in snapshots can preserve:

- source memberships;
- source-row rejections;
- original frozen source CSV bytes;
- source hashes and as-of dates;
- unique-symbol decision/exclusion conservation.

### 3.2 PR #56 smoke evidence

The current `evidence-observations` branch head is:

`5e625e6db1215b6380dde6d3bdfad69574eebbe2`

It currently contains only:

`runs/general-discovery/2026-10-09_9c48794_20261011T061651Z/`

This is the small PR #56 engineering smoke test, not the generalized-v0 PR #57 study.

Smoke-test facts already reviewed:

- 7 raw source rows;
- 6 accepted memberships;
- 5 unique symbols;
- 5 StockDecisions;
- 1 source-row rejection (`SOURCE_DISABLED`);
- 0 pre-decision universe exclusions;
- validator PASS;
- submitted SHA256 files reconcile;
- multi-source overlap works;
- legacy Quality/Entry/Action behavior for overlapping baseline names stayed consistent.

Interpretation:

**Engineering smoke GO only.**

It is too small to validate cross-industry Quality, Entry, liquidity or Action behavior.

## 4. PR #57 is already merged — do not recreate it

PR #57 merged at:

`2d8919444828643f7b888f90907e0b0e6632bfc4`

Its purpose is exactly the larger PR structure agreed in the previous conversation:
perform one end-to-end generalized-selection research cycle instead of fragmenting
Universe, liquidity, Quality, Entry and Action diagnostics across many PRs.

Primary protocol:

`docs/generalized_end_to_end_research_v0.md`

Related design documents:

- `docs/general_purpose_discovery_and_quality_v2_design.md`
- `docs/general_discovery_implementation.md`
- `docs/research_evidence_workflow.md`
- `docs/liquidity_gate_research_protocol_20261011.md`

PR #57 freezes a diagnostic research cohort under:

`data/research/generalized_v0/`

Registered cohort:

- 60 US Core rows;
- 12 provisional coverage groups × 5 names;
- 10 AI thematic memberships;
- 5 manual research memberships;
- 75 memberships;
- 62 unique symbols.

Important:

- The roster was frozen on **2026-10-11**.
- It is **not** valid historical membership for 2026-10-09.
- The earliest eligible future US market session is **2026-10-12**.
- The cohort is purposive and diagnostic, not random, not representative of the
  entire US equity market, and not an official final US Core production universe.
- Provisional coverage groups are research strata, not verified GICS sectors or
  fully homogeneous accounting models.

## 5. The next task is the PR #57 post-merge experiment

The next conversation should first verify:

1. `main == 2d8919444828643f7b888f90907e0b0e6632bfc4` or a later commit that has
   not invalidated the protocol.
2. `evidence-observations` does **not** yet contain a
   `runs/generalized-v0/` evidence directory.
3. The user has a local credentialed environment for Alpaca/SEC.
4. A valid US market session on or after 2026-10-12 is available.

Do **not** run a generalized-v0 snapshot against 2026-10-09 and do not rewrite
`source_asof` to make it appear PIT-valid.

### 5.1 Prepare the experiment config

Use the merged PR #57 helper exactly as documented:

```bash
python scripts/research_generalized_selection.py prepare \
  --base-config configs/config.risk_off.json \
  --output-config outputs/config.generalized_v0.experiment.json
```

The helper refuses overwrite. Use a new path for a rerun rather than modifying an
old experiment config.

### 5.2 Offline source preflight

For the actual intended market session:

```bash
python scripts/preview_discovery_sources.py \
  --config outputs/config.generalized_v0.experiment.json \
  --decision-date <YYYY-MM-DD>
```

The date must be on/after 2026-10-12 and must correspond to the market session the
later snapshot will actually use.

### 5.3 Credentialed experiment — never formal at this stage

```bash
python scripts/run_mvp_full_scan.py \
  --config outputs/config.generalized_v0.experiment.json
```

Use the new experiment snapshot path printed by this command.

Then:

```bash
python scripts/validate_mvp_snapshot.py "$SNAPSHOT" --json > validation.json
```

Then export the bounded same-feed PIT bar study:

```bash
python scripts/export_generalized_pit_bars.py \
  --snapshot "$SNAPSHOT" \
  --config outputs/config.generalized_v0.experiment.json \
  --out-dir outputs/generalized_bars_v0
```

Then run the integrated research audit:

```bash
python scripts/research_generalized_selection.py audit \
  --snapshot "$SNAPSHOT" \
  --config outputs/config.generalized_v0.experiment.json \
  --bars-csv outputs/generalized_bars_v0/pit_iex_daily_bars.csv \
  --out-dir outputs/generalized_research_v0
```

Do **not** add `--formal`.

Do not change:

- Quality v1;
- Entry v1;
- Action mapping;
- QQQ regime logic;
- IEX feed;
- the current $2m snapshot liquidity gate;
- the 62-name research cohort after seeing results.

## 6. Evidence submission for the next review

Submit to `evidence-observations` as plain browsable files, not ZIP and not a PR.

Recommended path:

```text
runs/generalized-v0/<session>_<scanner_sha7>_<run_id>/
```

Required review files:

```text
README.md
validation.json
run_manifest.json
discovery_memberships.jsonl
discovery_source_rejections.jsonl
discovery_source_inputs/*.csv
coverage_strata.csv
universe_exclusions.jsonl
decisions.jsonl
action_list.md
weekly_review.md
sanitized_config.json
pit_bars_manifest.json
pit_iex_daily_bars.csv              # only if provider terms allow redistribution
research_audit.json
research_review.md
quality_entry_action_by_symbol.csv
liquidity_diagnostics.csv
entry_benchmark_diagnostics.csv
reviewer_notes.md
SHA256SUMS
```

If raw Alpaca bars cannot legally be committed, do not push them. Preserve:

- their byte SHA256;
- schema;
- per-symbol/session coverage;
- exact reproducible fetch protocol;
- manifest and derived diagnostics;

and mark the inability to inspect raw bars as an explicit review limitation.

Never submit:

- `.env`;
- Alpaca/SEC secrets;
- SEC user-agent identity;
- raw API caches;
- EdgarTools caches;
- unredacted sensitive manual notes;
- unrelated large logs;
- virtualenv.

## 7. What the generalized-v0 evidence must answer

The central review should evaluate all of the following together, without forcing a
premature production change.

### 7.1 Universe / provenance

Check:

- 75 memberships and 62 unique symbols from the frozen source files;
- all source hashes and source dates;
- every unique candidate becomes exactly one Decision or one universe exclusion;
- source-row rejections remain distinct from unique-symbol universe exclusions;
- no future-dated membership;
- no silent ticker/share-class substitution;
- no unexplained inactive/unmapped/security-type loss;
- network and SEC workload remain bounded.

### 7.2 Liquidity

Current production behavior remains a one-day Alpaca/IEX snapshot
`dollar_volume >= $2m` pre-decision gate.

The research comparison uses same-feed historical daily bars and a pre-registered
20-session turnover diagnostic.

Do **not** equate:

- snapshot dollar volume;
- last daily-bar close × volume;
- 20-session mean daily turnover;
- SIP/consolidated liquidity;
- actual executable capacity.

Research GO for the diagnostic requires at least 80% of the 62 names to have
20 valid IEX sessions through the decision session, with split/freshness handling
documented.

A disagreement with the current $2m gate is a research finding, not automatic
authorization to lower/remove the gate.

### 7.3 Company Quality

Quality v1 remains frozen during the experiment.

Audit:

- grade distribution;
- confidence;
- positives/risks/missing facts;
- latest filing and USD/non-USD coverage;
- financial-integrity failure modes;
- provisional accounting-group differences;
- company-level outliers.

Do **not** treat cross-group average score differences as direct evidence for new weights.

Required conceptual direction for Quality v2:

**one common financial-quality core + a small number of business-model-aware
interpretation rules.**

Do not build one independent scoring system per sector.

Banks, brokers, insurers, REITs, unsupported/foreign reporting and unknown financial
models need explicit specialist semantics before claiming cross-industry-comparable
Quality.

### 7.4 Entry Quality

Entry must **not** be left out of generalized optimization.

Entry v1 remains frozen in the experiment, but PR #57 evaluates whether it generalizes
beyond an AI-heavy universe.

Study:

- Entry state distributions across provisional groups;
- SMA/trend/momentum/relative-strength failure modes;
- aligned trailing stock-vs-QQQ and stock-vs-SPY behavior;
- optional illustrative industry-proxy comparisons;
- state persistence / deterioration where available.

QQQ and SPY comparisons must share aligned stock/QQQ/SPY sessions for the main
comparison so the result is not caused by different calendars.

Sector proxies are exploratory and must not be mistaken for verified classifications.

Entry research GO requires >=80% of the 62 symbols to have >=61 aligned stock/QQQ/SPY
sessions through the decision date.

Important:

- These are trailing diagnostics, not forward returns.
- Do not automatically replace QQQ with SPY.
- Do not automatically add sector-relative signals.
- A future Entry v2 change must be justified by stable, interpretable evidence.

### 7.5 Action / attention

Keep current Action mapping and attention cap during the experiment.

Audit:

- which Quality × Entry combinations reach each Action state;
- which highest-priority names are omitted by the cap;
- provisional-group representation in Daily/Weekly lists;
- whether the priority ordering is useful;
- whether `Quality B + ENTRY_READY`, broad `WATCH_BREAKOUT`, or other known v1
  routing choices need later research.

Do not introduce industry quotas merely to make the list look diversified.

## 8. Multi-dimensional GO / NO-GO

The next evidence review must separate:

- **Engineering GO**
- **Universe/provenance GO**
- **Liquidity diagnostic GO / INCONCLUSIVE**
- **Quality diagnostic GO / INCONCLUSIVE**
- **Entry diagnostic GO / INCONCLUSIVE**
- **Action diagnostic GO / INCONCLUSIVE**

Engineering GO is not strategy GO.

Any component may be INCONCLUSIVE while the others pass. Do not force a policy
change merely to produce a v2.

## 9. What should happen after the generalized-v0 evidence review

After the evidence is reviewed, create **one consolidated policy-candidate PR**, not a
series of tiny PRs.

Working name:

**Generalized Selection v2 — evidence-backed Quality / Entry / Liquidity / Attention**

Only include changes supported by the evidence. A component with insufficient evidence
remains unchanged.

Examples of possible changes if justified:

- Quality:
  - business-model-aware interpretation;
  - explicit applicability/non-comparability states;
  - better missingness/risk handling;
  - a small number of evidence-backed semantic adjustments.
- Entry:
  - market benchmark change or dual benchmark;
  - sector-relative diagnostic;
  - revised readiness/overextension semantics;
  - no change if QQQ-based v1 is already robust.
- Liquidity:
  - move from one-day snapshot proxy to a more stable same-feed metric;
  - move liquidity from pre-decision exclusion to attention/execution eligibility;
  - keep the current gate if alternatives do not improve research usefulness.
- Attention / Action:
  - better within-state ranking;
  - explicitly surface useful `B + ENTRY_READY` names;
  - better breakup of broad `WATCH_BREAKOUT`;
  - retain v1 mapping if evidence is weak.

One PR may contain multiple evidence-backed components, but its evaluation must preserve
**component attribution**. Compare Quality, Entry, liquidity and Action changes
separately before interpreting the combined v2 result.

Do not tune dozens of weights or thresholds against the same small diagnostic cohort.

## 10. Evidence needed before production promotion

The 62-name generalized-v0 cohort is a **diagnostic cohort**, not final OOS proof.

Before production v2 promotion:

1. freeze candidate policy before viewing the final validation sample;
2. use at least one temporally distinct or genuinely prospective cohort;
3. preserve the current v1 formal/prospective history as the comparator;
4. do not overwrite old snapshots;
5. report sample size, missingness, date/industry concentration and market regime;
6. keep overlapping 20/60/120-day observations from being treated as independent;
7. distinguish decision-quality improvements from simply changing the universe.

Only then consider switching the default production candidate source or Quality/Entry
policy version.

## 11. Formal prospective snapshots during research

The existing v1 may continue as a frozen baseline if desired, but do not reinterpret
it as the generalized strategy.

Do not create a generalized-v0 `--formal` snapshot before the generalized-v0
experiment evidence receives review GO.

When a future v2 candidate is promoted, start a new clearly versioned prospective
series. Never rewrite the old v1 series.

## 12. Next-conversation operating instructions

The next conversation should:

1. read this handoff first;
2. read `AGENTS.md`;
3. read `docs/generalized_end_to_end_research_v0.md`;
4. verify current `main` and `evidence-observations` branch heads;
5. if generalized-v0 evidence has already been uploaded, **review it before writing
   any new production policy code**;
6. otherwise guide/prepare the bounded post-merge generalized-v0 experiment exactly
   as registered;
7. after evidence review, decide the single next outcome-sized policy PR;
8. keep Quality and Entry equally within scope; do not optimize one while assuming the
   other is correct merely because it already exists;
9. preserve v1 as the frozen comparator;
10. do not create many small PRs unless correctness or evidence attribution requires it.

## 13. First prompt for the next conversation

Use:

> 请以 GitHub 项目 `AT2018cow/us-ai-stock-scanner` 中的
> `docs/work_handoff_after_pr57_20261011.md` 为唯一最新交接入口。
> 先核对当前 `main`、PR #57 合并状态和 `evidence-observations` 分支；
> 如果已经有 `runs/generalized-v0/` 证据，就优先完成端到端 evidence 审核，
> 分别给出 Universe、Liquidity、Quality、Entry、Action 的
> GO / INCONCLUSIVE / NO-GO，并据此设计一个合并后的、粒度较大的 v2 政策 PR；
> 如果还没有 generalized-v0 evidence，则按文档中已预注册的 62 只跨行业 cohort
> 和命令推进一次非 `--formal` 实验。不要重新开发 PR #57，不要把工作拆成很多
> 小 PR，不要改变旧 v1 prospective 历史，也不要在证据不足时强行修改 Quality、
> Entry 或流动性规则。

