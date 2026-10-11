# Browsable experiment evidence workflow (no ZIP, no routine evidence PR)

Status: **proposed process update**; does not retroactively change any existing evidence PR
or mutate a formal prospective snapshot. Use for research and credentialed experiment
work after this process change is accepted.

## Principle

Reviewers need per-file browser links, machine-readable inputs and reproducible
hashes. ZIPs obscure ordinary inspection, and mandatory evidence-only PRs
add repeated merge work. Keep the code review and evidence review separate.

## Storage decision

**Short term:** keep normal source/code/policy/CI PRs against `main`.
Put new experiment artifacts as **ordinary text files in append-only
`evidence-observations` branch** in this repository, committed directly
without a PR and **never merged into `main`**. Create this branch only
once the user approves this storage choice; this document alone does not
create it. Link to a specific directory at a pinned Git commit SHA.

**Longer term, if there are many large runs:** move the same plain-file
directory structure to a dedicated private evidence repository to keep the
scanner repository lightweight. Do not automatically create a second repo.

Prefer Markdown/JSON/CSV for browser viewing. Retain JSONL for full
machine audit; a multi-megabyte JSONL may not preview completely on
GitHub, so provide a small summary Markdown and index next to it.

## Directory and stable identity

```text
runs/<study>/<decision_date>_<scanner_sha7>_<run_id>/
  README.md
  manifest.json
  validation.json
  audit.md
  audit.json
  input_hashes.txt
  SHA256SUMS
  [the minimum canonical CSV/JSONL needed for the pre-registered review]
  [sanitized log only if needed]
```

- Experiment run ID distinguishes reruns with the same market date and scanner SHA.
- Archive by **copying** actual output bytes, not editing original formal snapshots.
- Record source code SHA, config fingerprint, exact command, dataset scope, feed,
  cache/network provenance, UTC run time and market decision date.
- Do not force-push, delete or overwrite past evidence directories.
- Link both the browsable directory and the evidence **commit SHA** in the
  originating code PR or a tracking GitHub Issue. A branch name alone can move.
- Keep file-level SHA256 hashes. Commit identity provides repository object
  integrity, but true long-term write protection needs repository permissions
  or branch ruleset; the append-only promise alone is a process convention.

## How to submit for review

1. Before the experiment, the **code/research PR** states the exact command,
   expected artifacts, exclusions, acceptance criteria and GO/NO-GO.
2. Run one approved **experiment**; never silently promote a configuration or
   rewrite the earlier formal prospective record.
3. Write readable review summaries and validation output next to the raw
   text artifacts. Generate `SHA256SUMS` for exactly the submitted files.
4. Commit files directly to the approved evidence branch, no ZIP, no PR.
   Provide the pinned directory link and full evidence commit SHA for review.
5. Reviewer reads individual files, independently reconciles raw records
   with manifest/validator and records GO/NO-GO as a comment on the
   originating code PR or a tracking Issue. A GO is scoped to its experiment.

Never include `.env`, credentials, emails/SEC identity string, raw SEC/Alpaca
caches, EdgarTools caches, virtualenv, or irrelevant bulk outputs. A raw log
must be sanitized before upload. If storage limits make full JSONL unwieldy,
agree on a focused raw extract plus counts first; do not substitute an
unverifiable summary for evidence required by the review gate.

## Formal snapshots

Canonical `--formal` outputs remain in the existing immutable
`outputs/decisions/<market_date>/<style>/` archive, separate from evidence
distribution. Do not make pushing each formal run a PR prerequisite.
If a selected prospective milestone needs external review, copy its
unchanged bytes into a separately versioned evidence directory and pin the
commit/hash. Never modify a historical snapshot in place.

## Exceptions

Retain conventional PRs for software/policy/config changes, and for a
rare milestone evidence package that is expressly intended to become part
of the `main` repository's public history. Existing merged evidence PRs
remain preserved, without rewriting their documented original contracts.
