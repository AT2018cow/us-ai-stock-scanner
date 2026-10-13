"""Identity provenance contract: snapshots, fingerprints, cache binding.

Covers the P0 review checklist with offline fixtures + bounded cache
replay (tmp dirs, stub SEC clients): ticker-map freeze/conflicts,
canonical hashing, layered fingerprints, compare precedence, entity
coherence, parsed-cache version/map binding/corruption/concurrency,
three-path equivalent validation, SEC failure fallback, XOM/HON
acceptance rows, manifest + validator registry. No network.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from ai_value_scanner.config import load_config
from ai_value_scanner.decision.model import QualityGrade
from ai_value_scanner.decision.universe import (
    SEC_MAPPING_STAGE,
    SEC_TICKER_CIK_CONFLICT,
    classify_asset_mapping_universe,
    find_mapping_conflicts,
)
from ai_value_scanner.fundamentals.identity import verify_operating_entity
from ai_value_scanner.fundamentals.provenance import (
    AUDIT_COMPARISON_STATES,
    PROVENANCE_MISSING,
    RECONCILED,
    SAME,
    UNCOMPARABLE,
    canonical_json_bytes,
    check_entity_coherence,
    compare_identity_records,
    fingerprint_facts,
    fingerprint_scoring_inputs,
    sha256_hex,
)
from ai_value_scanner.reporting.snapshot import build_run_manifest
from ai_value_scanner.scanner import SecClient, identity_payload_ready, load_one_fundamental

MAP_URL_ROWS = {"AAA": {"ticker": "AAA", "cik_str": 111, "title": "AAA Inc"},
                "BBB": {"ticker": "BBB", "cik_str": 222, "title": "BBB Corp"}}


class _FakeResp:
    def __init__(self, payload=None, content=b"{}", fail=None):
        self._payload = payload if payload is not None else {}
        self.content = content
        self.status_code = 200
        self._fail = fail

    def raise_for_status(self):
        if self._fail is not None:
            raise self._fail

    def json(self):
        if self._fail is not None:
            raise self._fail
        return self._payload


class _StubSession:
    def __init__(self, handler):
        self._handler = handler
        self.calls = []

    def get(self, url, headers=None, timeout=None, params=None):
        self.calls.append(url)
        return self._handler(url)


def _sec_client(handler, cache_dir, monitor=None):
    from ai_value_scanner.scanner import RequestRateLimiter, NetworkMonitor
    session = _StubSession(handler)
    limiter = RequestRateLimiter(1000.0, monitor=monitor or NetworkMonitor(),
                                 service_name="sec-test")
    return SecClient(session=session, user_agent="test-agent", timeout_sec=5,
                     cache_dir=Path(cache_dir), request_limiter=limiter,
                     submissions_ttl_sec=10 ** 9, monitor=monitor)


def _10q_obs(value, end, filed, accn):
    return {"val": value, "end": end, "start": end[:8] + "01",
            "filed": filed, "accn": accn, "form": "10-Q"}


def _facts_doc(*, rev=100.0, ni=10.0, ocf=12.0, accn="0000001111-26-000001",
               filed="2026-08-03", ends=("2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30")):
    def series(vals):
        return [_10q_obs(v, e, filed, accn) for v, e in zip(vals, ends)]
    return {"cik": "0000111111", "entityName": "AAA Inc",
            "facts": {"us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax":
                    {"units": {"USD": series([rev] * 4)}},
                "NetIncomeLoss": {"units": {"USD": series([ni] * 4)}},
                "NetCashProvidedByUsedInOperatingActivities":
                    {"units": {"USD": series([ocf] * 4)}},
                "EntityCommonStockSharesOutstanding":
                    {"units": {"shares": series([1000] * 4)}},
            }}}


def _submissions_doc(*, tickers=("AAA",), accn="0000001111-26-000001",
                     filed="2026-08-03", name="AAA Inc"):
    return {"cik": "0000111111", "name": name, "sic": "7370", "tickers": list(tickers),
            "filings": {"recent": {
                "form": ["10-Q", "8-K"], "accessionNumber": [accn, "0000001111-26-000002"],
                "filingDate": [filed, filed]}}}


class _StubSec:
    """Stub for load_one_fundamental: only the three used methods."""

    def __init__(self, submissions, facts, map_sha="mapsha1"):
        self._sub = submissions
        self._facts = facts
        self._map_sha = map_sha
        self.calls = {"submissions": 0, "facts": 0, "snapshot": 0}

    def get_submissions(self, cik):
        self.calls["submissions"] += 1
        return dict(self._sub)

    def get_companyfacts(self, cik):
        self.calls["facts"] += 1
        return json.loads(json.dumps(self._facts))

    def ticker_map_snapshot(self):
        self.calls["snapshot"] += 1
        return {"source": "test", "sha256": self._map_sha, "fetched_utc": None,
                "read_utc": "2026-10-13T00:00:00+00:00", "n_rows": 1, "conflicts": {}}


def _test_config(cache_dir):
    cfg = load_config("configs/config.risk_off.json")
    return dataclasses.replace(cfg, cache_dir=str(cache_dir),
                               sec_cache_ttl_submissions_sec=10 ** 9)


def _plant_meta(cache_dir, cik, covered):
    (Path(cache_dir) / f"facts_meta_{cik}.json").write_text(json.dumps(
        {"covered_accession": covered, "pending_accession": None}))


def _plant_raw_submissions(cache_dir, cik, submissions):
    (Path(cache_dir) / f"submissions_{cik}.json").write_text(
        json.dumps(submissions))


class TickerMapSnapshotTests(unittest.TestCase):
    def test_memo_freezes_bytes_across_calls(self) -> None:
        with TemporaryDirectory() as tmp:
            sec = _sec_client(lambda url: _FakeResp(MAP_URL_ROWS, content=b'{"a":1}'), tmp)
            first = sec.ticker_map_snapshot()
            second = sec.ticker_map_snapshot()
            self.assertEqual(first["sha256"], second["sha256"])
            self.assertEqual(first["sha256"], sha256_hex(b'{"a":1}'))
            self.assertEqual(first["source"], "network")
            self.assertIsNotNone(first["fetched_utc"])
            self.assertEqual(len(sec.session.calls), 1)

    def test_fallback_snapshot_uses_canonical_bytes(self) -> None:
        with TemporaryDirectory() as tmp:
            def fail(url):
                raise ConnectionError("down")
            sec = _sec_client(fail, tmp)
            Path(tmp, "submissions_0000111111.json").write_text(json.dumps({
                "cik": "0000111111", "name": "AAA Inc", "tickers": ["AAA"]}))
            snap = sec.ticker_map_snapshot()
            self.assertEqual(snap["source"], "fallback_submissions_cache")
            self.assertIsNone(snap["fetched_utc"])
            self.assertEqual(snap["n_rows"], 1)
            again = sec.ticker_map_snapshot()
            self.assertEqual(again["sha256"], snap["sha256"])

    def test_both_dead_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            def fail(url):
                raise ConnectionError("down")
            sec = _sec_client(fail, tmp)
            with self.assertRaises(RuntimeError):
                sec.ticker_mapping()

    def test_conflicts_detected_not_resolved(self) -> None:
        rows = {"A": {"ticker": "AAA", "cik_str": 111, "title": "One"},
                "B": {"ticker": "AAA", "cik_str": 999, "title": "Two"}}
        with TemporaryDirectory() as tmp:
            sec = _sec_client(lambda url: _FakeResp(rows, content=b"x"), tmp)
            snap = sec.ticker_map_snapshot()
            self.assertEqual(snap["conflicts"], {"AAA": ["0000000111", "0000000999"]})


class MappingConflictExclusionTests(unittest.TestCase):
    def test_find_mapping_conflicts(self) -> None:
        frame = pd.DataFrame({"symbol": ["A", "A", "B"],
                              "cik": ["0001", "0002", "0003"]})
        self.assertEqual(find_mapping_conflicts(frame), {"A": ["0001", "0002"]})
        self.assertEqual(find_mapping_conflicts(
            pd.DataFrame({"symbol": ["A"], "cik": ["0001"]})), {})

    def test_conflict_excluded_never_silently_picked(self) -> None:
        assets = [{"symbol": "DUP", "status": "active", "tradable": True,
                   "exchange": "NYSE"}]
        mapping = pd.DataFrame({"symbol": ["DUP", "DUP"], "cik": ["1", "2"]})
        eligible, exclusions = classify_asset_mapping_universe(
            discovery_symbols={"DUP"}, assets=assets, sec_mapping=mapping,
            enabled_exchanges=["NYSE"])
        self.assertEqual(eligible, set())
        self.assertEqual(len(exclusions), 1)
        self.assertEqual(exclusions[0]["reason_code"], SEC_TICKER_CIK_CONFLICT)
        self.assertEqual(exclusions[0]["exclusion_stage"], SEC_MAPPING_STAGE)


class CanonicalHashTests(unittest.TestCase):
    def test_key_order_independent(self) -> None:
        self.assertEqual(canonical_json_bytes({"b": 1, "a": [1, 2]}),
                         canonical_json_bytes({"a": [1, 2], "b": 1}))

    def test_fingerprints_change_with_content(self) -> None:
        self.assertNotEqual(fingerprint_facts({"r": [1]}), fingerprint_facts({"r": [2]}))
        self.assertEqual(fingerprint_scoring_inputs({"a": 1.5}),
                         fingerprint_scoring_inputs({"a": 1.5}))
        self.assertIsNone(fingerprint_facts(None))


class CompareStatesTests(unittest.TestCase):
    def test_precedence(self) -> None:
        self.assertEqual(compare_identity_records(None, {"a": 1}), PROVENANCE_MISSING)
        self.assertEqual(compare_identity_records({}, {}), PROVENANCE_MISSING)
        base = {"scoring_inputs_sha": "s", "effective_facts_sha": "f", "raw_bytes_sha": "r"}
        same = dict(base)
        self.assertEqual(compare_identity_records(base, same), SAME)
        other_raw = dict(base, raw_bytes_sha="r2")
        self.assertEqual(compare_identity_records(base, other_raw), RECONCILED)
        other_facts = dict(base, effective_facts_sha="f2", scoring_inputs_sha="s2")
        self.assertEqual(compare_identity_records(base, other_facts), UNCOMPARABLE)
        facts_only = {"effective_facts_sha": "f"}
        self.assertEqual(compare_identity_records(facts_only, dict(facts_only)), SAME)
        self.assertEqual(compare_identity_records(facts_only, {"effective_facts_sha": "g"}),
                         UNCOMPARABLE)

    def test_states_disjoint_from_quality_grades(self) -> None:
        grades = {g.value for g in QualityGrade}
        self.assertTrue(AUDIT_COMPARISON_STATES.isdisjoint(grades))


class EntityCoherenceTests(unittest.TestCase):
    def test_response_cik_mismatch_is_hard_finding(self) -> None:
        from ai_value_scanner.fundamentals.provenance import check_entity_coherence
        out = check_entity_coherence(symbol="X", mapped_cik="0001",
                                     submissions={"tickers": ["X"]},
                                     facts_queried_cik="0001",
                                     facts_response_cik="0002")
        self.assertIn("RESPONSE_CIK_MISMATCH", out["findings"])

    def test_prefix_alone_never_fails(self) -> None:
        from ai_value_scanner.fundamentals.provenance import check_entity_coherence
        out = check_entity_coherence(
            symbol="PLD", mapped_cik="0001045609",
            submissions={"tickers": ["PLD"]},
            facts_queried_cik="0001045609", facts_response_cik="0001045609",
            relevant_accessions=["0001193125-26-323746"])
        self.assertNotIn("RESPONSE_CIK_MISMATCH", out["findings"])
        self.assertIn("ACCESSION_FILER_UNRESOLVED", out["findings"])
        self.assertEqual(out["unresolved_prefixes"], ["0001193125"])

    def test_relevant_periodic_preferred_over_general_latest(self) -> None:
        from ai_value_scanner.scanner import latest_periodic_filing
        subs = {"filings": {"recent": {
            "form": ["8-K", "10-Q", "4"], "accessionNumber": ["k", "q", "w"],
            "filingDate": ["2026-10-01", "2026-07-29", "2026-10-02"]}}}
        latest = latest_periodic_filing(subs)
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["accession"], "q")


class ParsedCacheBindingTests(unittest.TestCase):
    def _run(self, cache_dir, stub, cik="0000111111"):
        cfg = _test_config(cache_dir)
        return load_one_fundamental(stub, "AAA", cik, cfg)

    def test_fresh_compute_writes_v9_with_map_sha(self) -> None:
        with TemporaryDirectory() as tmp:
            sub, fac = _submissions_doc(), _facts_doc()
            stub = _StubSec(sub, fac, map_sha="mapsha1")
            _plant_meta(tmp, "0000111111", "0000001111-26-000001")
            _plant_raw_submissions(tmp, "0000111111", sub)
            out = self._run(tmp, stub)
            self.assertTrue(out["fundamental_operating_entity_verified"])
            meta = json.loads((Path(tmp) / "parsed_fund_0000111111.json").read_text())["_cache_meta"]
            self.assertEqual(meta["v"], 9)
            self.assertEqual(meta["ticker_map_sha"], "mapsha1")

    def test_hit_serves_without_refetch(self) -> None:
        with TemporaryDirectory() as tmp:
            sub = _submissions_doc()
            stub = _StubSec(sub, _facts_doc())
            _plant_meta(tmp, "0000111111", "0000001111-26-000001")
            _plant_raw_submissions(tmp, "0000111111", sub)
            first = self._run(tmp, stub)
            calls_after_first = dict(stub.calls)
            second = self._run(tmp, stub)
            self.assertEqual(second["revenue"], first["revenue"])
            self.assertEqual(stub.calls["submissions"], calls_after_first["submissions"])
            self.assertEqual(stub.calls["facts"], calls_after_first["facts"])

    def test_old_version_and_corrupt_cache_miss(self) -> None:
        with TemporaryDirectory() as tmp:
            sub = _submissions_doc()
            stub = _StubSec(sub, _facts_doc())
            _plant_meta(tmp, "0000111111", "0000001111-26-000001")
            _plant_raw_submissions(tmp, "0000111111", sub)
            self._run(tmp, stub)
            path = Path(tmp) / "parsed_fund_0000111111.json"
            payload = json.loads(path.read_text())
            payload["_cache_meta"]["v"] = 8
            path.write_text(json.dumps(payload))
            before = dict(stub.calls)
            out = self._run(tmp, stub)
            self.assertGreater(stub.calls["submissions"], before["submissions"])
            self.assertTrue(out["fundamental_operating_entity_verified"])
            path.write_text("{corrupt!!")
            out2 = self._run(tmp, stub)
            self.assertTrue(out2["fundamental_operating_entity_verified"])

    def test_map_change_invalidates_hit(self) -> None:
        with TemporaryDirectory() as tmp:
            sub = _submissions_doc()
            stub = _StubSec(sub, _facts_doc(), map_sha="mapsha1")
            _plant_meta(tmp, "0000111111", "0000001111-26-000001")
            _plant_raw_submissions(tmp, "0000111111", sub)
            self._run(tmp, stub)
            stub._map_sha = "mapsha2-different-content"
            before = dict(stub.calls)
            out = self._run(tmp, stub)
            self.assertGreater(stub.calls["submissions"], before["submissions"])
            self.assertTrue(out["fundamental_operating_entity_verified"])

    def test_concurrent_writes_stay_parseable(self) -> None:
        with TemporaryDirectory() as tmp:
            import time as _time

            class Slow(_StubSec):
                def get_companyfacts(self, cik):
                    _time.sleep(0.05)
                    return super().get_companyfacts(cik)

            stub = Slow(_submissions_doc(), _facts_doc())
            _plant_meta(tmp, "0000111111", "0000001111-26-000001")
            _plant_raw_submissions(tmp, "0000111111", _submissions_doc())
            errors: list = []

            def work():
                try:
                    self._run(tmp, stub)
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=work) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            payload = json.loads((Path(tmp) / "parsed_fund_0000111111.json").read_text())
            self.assertEqual(payload["_cache_meta"]["v"], 9)

    def test_identity_payload_ready_same_verdict_all_paths(self) -> None:
        from ai_value_scanner.scanner import identity_payload_ready
        fresh = {"fundamental_operating_entity_verified": True,
                 "fundamental_operating_entity_detail": "x"}
        self.assertTrue(identity_payload_ready(fresh, current_map_sha="m", recorded_map_sha="m"))
        self.assertFalse(identity_payload_ready(
            {"fundamental_operating_entity_verified": True},
            current_map_sha="m", recorded_map_sha="m"))
        self.assertFalse(identity_payload_ready(
            fresh, current_map_sha="m", recorded_map_sha="other"))
        self.assertFalse(identity_payload_ready(None, current_map_sha="m", recorded_map_sha="m"))


class ManifestAndValidatorTests(unittest.TestCase):
    def test_manifest_carries_ticker_map(self) -> None:
        snap = {"source": "network", "sha256": "abc", "fetched_utc": "t",
                "read_utc": "t2", "n_rows": 2, "conflicts": {}}
        manifest = build_run_manifest(
            decisions=[], daily_attention=[], weekly_attention=[],
            generated_at_utc="2026-10-13T00:00:00+00:00", decision_date="2026-10-12",
            strategy_style="risk_off", config_fingerprint="cfg", code_sha="sha",
            input_provenance={"ticker_map": snap})
        self.assertEqual(manifest["input_provenance"]["ticker_map"]["sha256"], "abc")

    def test_validator_registry_contains_conflict_reason(self) -> None:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import validate_mvp_snapshot as validator
        self.assertEqual(
            validator.EXCLUSION_REASON_TO_STAGE["SEC_TICKER_CIK_CONFLICT"],
            "sec_mapping")


class AcceptanceRowsTests(unittest.TestCase):
    def test_xom_thin_vs_opco_never_silently_mixed(self) -> None:
        thin = {"scoring_inputs_sha": None, "effective_facts_sha": None,
                "raw_bytes_sha": "shell84k"}
        opco = {"scoring_inputs_sha": "opco-labels", "effective_facts_sha": "opco-facts",
                "raw_bytes_sha": "opco6m"}
        # Missing scoring fingerprints on the thin side: no silent pick.
        self.assertEqual(compare_identity_records(thin, opco), PROVENANCE_MISSING)
        opco_thin_scored = {"scoring_inputs_sha": "s-thin", "effective_facts_sha": "f-thin",
                            "raw_bytes_sha": "shell84k"}
        self.assertEqual(compare_identity_records(opco_thin_scored, opco), UNCOMPARABLE)

    def test_hon_skew_keeps_capped_path(self) -> None:
        ok, detail = verify_operating_entity("HON", ["HON"], 1006, True)
        self.assertTrue(ok)
        self.assertEqual(detail, "ticker_listed_with_core_facts")
        # The HON cap itself comes from latest_periodic_filing_not_covered
        # (existing gate, unchanged); identity must not override it.


if __name__ == "__main__":
    unittest.main()
