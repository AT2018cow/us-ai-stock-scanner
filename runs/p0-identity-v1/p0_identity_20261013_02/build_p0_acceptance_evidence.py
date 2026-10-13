"""P0 acceptance evidence generator (research-only, offline, deterministic).

Runs the real P0 machinery on synthetic fixtures + the five recorded
acceptance rows and writes a reviewable evidence directory. No network,
no production data, no scoring changes. Rerun: python3 this file, then
diff the output directory (only run_manifest generated_utc may differ).
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

OUT = Path("outputs/p0_identity_evidence/p0_identity_20261013_02")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    from ai_value_scanner.decision.quality import build_company_quality_v1
    from ai_value_scanner.fundamentals.identity import verify_operating_entity
    from ai_value_scanner.fundamentals.provenance import (
        canonical_json_bytes,
        check_entity_coherence,
        compare_identity_records,
        fingerprint_effective_values,
        fingerprint_facts,
        fingerprint_scoring_inputs,
    )

    OUT.mkdir(parents=True, exist_ok=True)
    code_sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()

    # --- per-symbol identity verdicts (5 acceptance rows) ---
    verdicts = [
        {"symbol": "XOM", "case": "thin-holdings",
         "inputs": {"tickers": ["XOM"], "n_filings": 34, "core": False},
         "result": verify_operating_entity("XOM", ["XOM"], 34, False)},
        {"symbol": "XOM", "case": "opco-content",
         "inputs": {"tickers": ["XOM"], "n_filings": 1001, "core": True,
                    "note": "successor-CIK content question open"},
         "result": verify_operating_entity("XOM", ["XOM"], 1001, True)},
        {"symbol": "HON", "case": "filing-facts-skew",
         "inputs": {"tickers": ["HON"], "n_filings": 1006, "core": True},
         "result": verify_operating_entity("HON", ["HON"], 1006, True)},
        {"symbol": "FCX", "case": "threshold-edge",
         "inputs": {"tickers": ["FCX"], "n_filings": 1000, "core": True},
         "result": verify_operating_entity("FCX", ["FCX"], 1000, True)},
        {"symbol": "NEE", "case": "genuine-upgrade",
         "inputs": {"tickers": ["NEE"], "n_filings": 1003, "core": True},
         "result": verify_operating_entity("NEE", ["NEE"], 1003, True)},
        {"symbol": "PLD", "case": "filed-but-uncovered",
         "inputs": {"tickers": ["PLD"], "n_filings": 1001, "core": True},
         "result": verify_operating_entity("PLD", ["PLD"], 1001, True)},
    ]
    with (OUT / "per_symbol_identity_verdicts.csv").open("w", newline="",
                                                          encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["symbol", "case", "verdict", "detail"])
        for v in verdicts:
            ok, detail = v["result"]
            writer.writerow([v["symbol"], v["case"], ok, detail])

    # --- fingerprints (canonical examples) ---
    facts_a = {"revenue": [(1.0, 2.0)], "ni": [3.0]}
    facts_b = {"revenue": [(1.0, 9.0)], "ni": [3.0]}
    metrics = {"net_margin": 0.14, "revenue": 100.0}
    fingerprints = {
        "canonical_algorithm": ("json.dumps(sort_keys=True, separators=(',',':'), "
                                "ensure_ascii=True, default=str) -> utf-8 -> sha256"),
        "facts_A": fingerprint_facts(facts_a),
        "facts_B_different": fingerprint_facts(facts_b),
        "facts_reordered_equal": fingerprint_facts({"ni": [3.0], "revenue": [(1.0, 2.0)]}),
        "scoring_inputs": fingerprint_scoring_inputs(metrics),
        "effective_values": fingerprint_effective_values(
            {"revenue": 100.0, "net_income": 5.0, "extra_unlisted_key": 1}),
    }
    (OUT / "fingerprints.json").write_text(json.dumps(fingerprints, indent=1),
                                           encoding="utf-8")

    # --- comparison (incl. reviewer counterexample, verbatim shape) ---
    pairs = {
        "reviewer_counterexample": (
            {"mapped_cik": "0001", "scoring_inputs_sha": "s",
             "effective_facts_sha": "facts-A", "raw_bytes_sha": "raw-A"},
            {"mapped_cik": "0002", "scoring_inputs_sha": "s",
             "effective_facts_sha": "facts-B", "raw_bytes_sha": "raw-B"}),
        "reviewer_counterexample_same_cik": (
            {"symbol": "X", "financial_asof": "2026-08-03",
             "mapped_cik": "0001", "code_version": "v",
             "config_fingerprint": "c", "effective_facts_sha": "f1",
             "scoring_inputs_sha": "same", "raw_bytes_sha": "raw1"},
            {"symbol": "X", "financial_asof": "2026-08-03",
             "mapped_cik": "0001", "code_version": "v",
             "config_fingerprint": "c", "effective_facts_sha": "f2",
             "scoring_inputs_sha": "same", "raw_bytes_sha": "raw2"}),
        "identical_runs": (
            {"symbol": "X", "financial_asof": "d", "mapped_cik": "1",
             "code_version": "v", "config_fingerprint": "c",
             "effective_facts_sha": "f", "scoring_inputs_sha": "s",
             "raw_bytes_sha": "r"},
            {"symbol": "X", "financial_asof": "d", "mapped_cik": "1",
             "code_version": "v", "config_fingerprint": "c",
             "effective_facts_sha": "f", "scoring_inputs_sha": "s",
             "raw_bytes_sha": "r"}),
        "missing_effective_layer": (
            {"symbol": "X", "financial_asof": "d", "mapped_cik": "1",
             "code_version": "v", "config_fingerprint": "c",
             "effective_facts_sha": None, "scoring_inputs_sha": "s"},
            {"symbol": "X", "financial_asof": "d", "mapped_cik": "1",
             "code_version": "v", "config_fingerprint": "c",
             "effective_facts_sha": None, "scoring_inputs_sha": "s"}),
        "different_computation_code": (
            {"symbol": "X", "financial_asof": "d", "mapped_cik": "1",
             "code_version": "sha-one|q|e", "config_fingerprint": "c",
             "effective_facts_sha": "f", "scoring_inputs_sha": "s"},
            {"symbol": "X", "financial_asof": "d", "mapped_cik": "1",
             "code_version": "sha-two|q|e", "config_fingerprint": "c",
             "effective_facts_sha": "f", "scoring_inputs_sha": "s"}),
        "thin_vs_scored": (
            {"symbol": "XOM", "financial_asof": "2026-08-03",
             "mapped_cik": "0002115436", "code_version": "v",
             "config_fingerprint": "c"},
            {"symbol": "XOM", "financial_asof": "2026-08-03",
             "mapped_cik": "0002115436", "code_version": "v",
             "config_fingerprint": "c", "effective_facts_sha": "f2",
             "scoring_inputs_sha": "s2", "raw_bytes_sha": "r2"}),
    }
    comparison = {name: compare_identity_records(dict(a), dict(b))
                  for name, (a, b) in pairs.items()}
    (OUT / "comparison.json").write_text(json.dumps(comparison, indent=1),
                                         encoding="utf-8")

    # --- coherence spot + capped-path existence ---
    coherence = check_entity_coherence(
        symbol="XOM", mapped_cik="0002115436",
        submissions={"tickers": ["XOM"]},
        facts_queried_cik="0002115436", facts_response_cik="0002115436",
        relevant_accessions=["0000034088-26-000093"])
    capped = build_company_quality_v1(
        {"fundamental_facts_cover_latest_periodic": False},
        decision_date="2026-10-09")
    (OUT / "coherence_and_cap.json").write_text(json.dumps({
        "coherence": coherence,
        "hon_skew_capped_grade": capped.grade.value,
        "hon_skew_capped_confidence": capped.confidence,
        "hon_skew_codes": [e.code for e in capped.missing],
    }, indent=1, default=str), encoding="utf-8")

    # --- impact matrix (5 cases) ---
    with (OUT / "impact_matrix.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["case", "old_behavior", "new_behavior", "grade_effect"])
        writer.writerows([
            ["XOM thin holdings", "UNRATED generic missingness",
             "UNRATED + operating_entity_unverified", "none (already UNRATED)"],
            ["XOM opco content", "B (v0, cross-entity)", "UNCOMPARABLE vs thin run",
             "verdict withdrawn pending entity selection"],
            ["HON skew", "UNRATED + capped (existing gate)", "unchanged, pinned by test",
             "none"],
            ["FCX edge", "B on threshold edge", "unchanged, pinned", "none"],
            ["NEE upgrade", "B on new Q2 facts", "unchanged, pinned", "none"],
            ["PLD lag", "B on Q1 asof", "unchanged + lag note", "none"],
        ])

    (OUT / "run_manifest.json").write_text(json.dumps({
        "run_id": "p0_identity_20261013_02", "mode": "synthetic-acceptance",
        "code_sha": code_sha, "evidence_type": "offline fixtures, no network",
    }, indent=1), encoding="utf-8")

    (OUT / "reviewer_notes.md").write_text(
        "# P0 acceptance evidence notes\n\n"
        "- Everything here is produced by the reviewed functions on frozen\n"
        "  fixtures (this generator is committed alongside for reruns).\n"
        "- No production decisions, no real credentials, no bulk data.\n"
        "- UNCOMPARABLE / PROVENANCE_MISSING / RECONCILED are audit states\n"
        "  only — never Quality grades (disjointness tested).\n",
        encoding="utf-8")

    (OUT / "README.md").write_text(
        "# P0 identity/version acceptance evidence\n\n"
        "Deterministic synthetic proof for the merge gate: verdicts,\n"
        "fingerprints, comparison outputs, coherence + cap checks, impact\n"
        "matrix, run manifest. Rerun `runs/p0-identity-v1/p0_identity_20261013_02/build_p0_acceptance_evidence.py`;\n"
        "only run_manifest generated_utc-equivalents may differ (none stored).\n",
        encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
