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
import hashlib
import json
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

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
    starts = {"2025-09-30": "2025-07-01", "2025-12-31": "2025-10-01",
              "2026-03-31": "2026-01-01", "2026-06-30": "2026-04-01"}
    return {"val": value, "end": end, "start": starts.get(end, end[:8] + "01"),
            "filed": filed, "accn": accn, "form": "10-Q"}


def _facts_doc(*, rev=100.0, ni=10.0, ocf=12.0, accn="0000001111-26-000001",
               filed="2026-08-03", ends=("2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"),
               cik="0000111111", entity="AAA Inc"):
    def series(vals):
        return [_10q_obs(v, e, filed, accn) for v, e in zip(vals, ends)]
    return {"cik": cik, "entityName": entity,
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


def _plant_raw_facts(cache_dir, cik, facts):
    (Path(cache_dir) / f"facts_{cik}.json").write_text(
        json.dumps(facts))


def _plant_raw(cache_dir, cik, submissions, facts):
    _plant_raw_submissions(cache_dir, cik, submissions)
    _plant_raw_facts(cache_dir, cik, facts)


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
    def _rec(self, **over):
        base = {"symbol": "X", "financial_asof": "2026-08-03",
                "mapped_cik": "0001", "code_version": "v",
                "config_fingerprint": "c", "effective_facts_sha": "f",
                "scoring_inputs_sha": "s", "raw_bytes_sha": "r"}
        base.update(over)
        return base

    def test_precedence(self) -> None:
        base = self._rec()
        self.assertEqual(compare_identity_records(None, base), PROVENANCE_MISSING)
        self.assertEqual(compare_identity_records({}, {}), PROVENANCE_MISSING)
        self.assertEqual(compare_identity_records(base, dict(base)), SAME)
        # Reviewer counterexample: same scoring sha, different CIK/facts/raw.
        other_entity = self._rec(mapped_cik="0002", effective_facts_sha="facts-B",
                                 scoring_inputs_sha="s", raw_bytes_sha="raw-B")
        self.assertEqual(compare_identity_records(base, other_entity), UNCOMPARABLE)
        # Symbol/asof mismatch is not a valid pair.
        self.assertEqual(compare_identity_records(base, self._rec(symbol="Y")),
                         PROVENANCE_MISSING)
        self.assertEqual(compare_identity_records(base, self._rec(financial_asof="2026-09-30")),
                         PROVENANCE_MISSING)
        # Code/config drift without proof.
        self.assertEqual(compare_identity_records(base, self._rec(code_version="v2")),
                         UNCOMPARABLE)
        # Scoring differs with everything else equal.
        self.assertEqual(compare_identity_records(base, self._rec(scoring_inputs_sha="s2")),
                         UNCOMPARABLE)
        # Same scoring, different raw bytes: feed re-serialization.
        self.assertEqual(compare_identity_records(base, self._rec(raw_bytes_sha="r2")),
                         RECONCILED)
        # Facts-only layer (canonical 10-digit CIKs throughout).
        facts_only = {"symbol": "X", "financial_asof": "d", "mapped_cik": "0001",
                      "code_version": "v", "config_fingerprint": "c",
                      "effective_facts_sha": "f"}
        self.assertEqual(compare_identity_records(facts_only, dict(facts_only)),
                         PROVENANCE_MISSING)
        self.assertEqual(compare_identity_records(
            facts_only, dict(facts_only, effective_facts_sha="g")),
                         UNCOMPARABLE)
        # Missing scoring layer on one side only.
        self.assertEqual(compare_identity_records(
            facts_only, self._rec()), PROVENANCE_MISSING)

    def test_same_scoring_different_facts_never_reconciled(self) -> None:
        # Reviewer counterexample, verbatim shape: identical scoring inputs
        # but different effective facts must be UNCOMPARABLE, never
        # RECONCILED — equal scores from different measurements prove
        # nothing about economic identity.
        a = dict(symbol="X", financial_asof="2026-08-03", mapped_cik="0001",
                 code_version="v", config_fingerprint="c", effective_facts_sha="f1",
                 scoring_inputs_sha="same", raw_bytes_sha="raw1")
        b = dict(a, effective_facts_sha="f2", raw_bytes_sha="raw2")
        self.assertEqual(compare_identity_records(a, b), UNCOMPARABLE)
        self.assertEqual(compare_identity_records(b, a), UNCOMPARABLE)

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
            _plant_raw(tmp, "0000111111", sub, fac)
            out = self._run(tmp, stub)
            self.assertTrue(out["fundamental_operating_entity_verified"])
            meta = json.loads((Path(tmp) / "parsed_fund_0000111111.json").read_text())["_cache_meta"]
            self.assertEqual(meta["v"], 9)
            self.assertEqual(meta["ticker_map_sha"], "mapsha1")

    def test_hit_serves_without_refetch(self) -> None:
        with TemporaryDirectory() as tmp:
            sub, fac = _submissions_doc(), _facts_doc()
            stub = _StubSec(sub, fac)
            _plant_meta(tmp, "0000111111", "0000001111-26-000001")
            _plant_raw(tmp, "0000111111", sub, fac)
            first = self._run(tmp, stub)
            calls_after_first = dict(stub.calls)
            second = self._run(tmp, stub)
            self.assertEqual(second["revenue"], first["revenue"])
            self.assertEqual(stub.calls["submissions"], calls_after_first["submissions"])
            self.assertEqual(stub.calls["facts"], calls_after_first["facts"])

    def test_old_version_and_corrupt_cache_miss(self) -> None:
        with TemporaryDirectory() as tmp:
            sub, fac = _submissions_doc(), _facts_doc()
            stub = _StubSec(sub, fac)
            _plant_meta(tmp, "0000111111", "0000001111-26-000001")
            _plant_raw(tmp, "0000111111", sub, fac)
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
            sub, fac = _submissions_doc(), _facts_doc()
            stub = _StubSec(sub, fac, map_sha="mapsha1")
            _plant_meta(tmp, "0000111111", "0000001111-26-000001")
            _plant_raw(tmp, "0000111111", sub, fac)
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

            stub = Slow(sub := _submissions_doc(), _facts_doc())
            _plant_meta(tmp, "0000111111", "0000001111-26-000001")
            _plant_raw(tmp, "0000111111", sub, _facts_doc())
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
    def _rec(self, symbol, cik, asof, scoring, facts, raw):
        return {"symbol": symbol, "financial_asof": asof, "mapped_cik": cik,
                "code_version": "v9test", "config_fingerprint": "cfg",
                "effective_facts_sha": facts, "scoring_inputs_sha": scoring,
                "raw_bytes_sha": raw}

    def test_xom_thin_vs_opco_never_silently_mixed(self) -> None:
        # Thin holdings run: no scoring/effective fingerprints at all.
        thin = {"symbol": "XOM", "financial_asof": "2026-08-03",
                "mapped_cik": "0002115436", "code_version": "v9test",
                "config_fingerprint": "cfg", "effective_facts_sha": None,
                "scoring_inputs_sha": None, "raw_bytes_sha": "shell84k"}
        opco = self._rec("XOM", "0002115436", "2026-08-03",
                         "opco-labels", "opco-facts", "opco6m")
        # No silent pick: without fingerprints there is nothing valid to
        # compare, even against a fully fingerprinted run.
        self.assertEqual(compare_identity_records(thin, opco), PROVENANCE_MISSING)
        # And a scored thin run against opco content differs by issuer
        # content, not just bytes.
        thin_scored = self._rec("XOM", "0002115436", "2026-08-03",
                                "s-thin", "f-thin", "shell84k")
        self.assertEqual(compare_identity_records(thin_scored, opco), UNCOMPARABLE)
        # Cross-entity with identical scoring inputs still UNCOMPARABLE.
        other_entity = self._rec("XOM", "0000034088", "2026-08-03",
                                 "s-thin", "f-thin", "shell84k")
        self.assertEqual(compare_identity_records(thin_scored, other_entity),
                         UNCOMPARABLE)

    def test_hon_skew_keeps_capped_path(self) -> None:
        ok, detail = verify_operating_entity("HON", ["HON"], 1006, True)
        self.assertTrue(ok)
        self.assertEqual(detail, "ticker_listed_with_core_facts")
        # The HON cap itself comes from latest_periodic_filing_not_covered
        # (existing gate, unchanged); identity must not override it.


class DowngradeHelperTests(unittest.TestCase):
    def test_hard_finding_forces_false_with_dedup(self) -> None:
        from ai_value_scanner.fundamentals.identity import downgrade_on_hard_findings
        ok, detail = downgrade_on_hard_findings(True, "ticker_listed_with_core_facts",
                                               ["RESPONSE_CIK_MISMATCH"])
        self.assertFalse(ok)
        self.assertIn("RESPONSE_CIK_MISMATCH", detail)
        # TICKER_NOT_LISTED already reported by verify(): no doubling.
        ok, detail = downgrade_on_hard_findings(False, "ticker_not_listed",
                                               ["TICKER_NOT_LISTED"])
        self.assertFalse(ok)
        self.assertEqual(detail.upper().count("TICKER_NOT_LISTED"), 1)

    def test_non_hard_findings_leave_verdict(self) -> None:
        from ai_value_scanner.fundamentals.identity import downgrade_on_hard_findings
        self.assertEqual(downgrade_on_hard_findings(True, "ok", ["ACCESSION_FILER_UNRESOLVED"]),
                         (True, "ok"))
        self.assertEqual(downgrade_on_hard_findings(None, "x", ["RESPONSE_CIK_MISMATCH"]),
                         (False, "x+RESPONSE_CIK_MISMATCH"))


class LoaderCoherenceTests(unittest.TestCase):
    def _run_loader(self, tmp, facts_cik, tickers):
        sub = _submissions_doc()
        sub["tickers"] = list(tickers)
        fac = _facts_doc(cik=facts_cik)
        stub = _StubSec(sub, fac)
        _plant_meta(tmp, "0000111111", "0000001111-26-000001")
        _plant_raw(tmp, "0000111111", sub, fac)
        cfg = _test_config(tmp)
        from ai_value_scanner.scanner import load_one_fundamental
        return load_one_fundamental(stub, "AAA", "0000111111", cfg)

    def test_response_cik_mismatch_fails_closed_end_to_end(self) -> None:
        # Required regression: mapped/requested A, submissions tickers OK,
        # facts response CIK=B WITH core facts -> unverified, UNRATED+code.
        from ai_value_scanner.decision.quality import build_company_quality_v1
        with TemporaryDirectory() as tmp:
            out = self._run_loader(tmp, "0000999999", ["AAA"])
            self.assertFalse(out["fundamental_operating_entity_verified"])
            self.assertIn("RESPONSE_CIK_MISMATCH",
                          out["fundamental_operating_entity_detail"])
            decision = build_company_quality_v1(out, decision_date="2026-10-09")
            self.assertEqual(decision.grade.value, "UNRATED")
            self.assertIn("operating_entity_unverified",
                          [e.code for e in decision.missing])

    def test_matching_response_cik_passes_through(self) -> None:
        with TemporaryDirectory() as tmp:
            out = self._run_loader(tmp, "0000111111", ["AAA"])
            self.assertTrue(out["fundamental_operating_entity_verified"])


class ReplayCoherenceTests(unittest.TestCase):
    def _frame(self, n=250, start="2025-10-01", base=100.0):
        idx = pd.date_range(start=start, periods=n, freq="D", tz="UTC")
        return pd.DataFrame({"open": base, "high": base * 1.01, "low": base * 0.99,
                             "close": base, "volume": 1_000_000.0}, index=idx)

    def _run_cross_section(self, facts_cik):
        from ai_value_scanner.backtest import (
            build_cross_section_asof,
            build_fundamental_pti_db,
            build_theme_scores_rules_proxy,
        )
        with TemporaryDirectory() as tmp:
            sub = _submissions_doc()
            fac = _facts_doc(cik=facts_cik)
            stub = _StubSec(sub, fac)
            cfg = _test_config(tmp)
            universe = pd.DataFrame([{"symbol": "AAA", "cik": "0000111111",
                                      "name": "AAA Inc"}])
            fundamentals = build_fundamental_pti_db(universe, stub, 1)
            themes = build_theme_scores_rules_proxy(universe, fundamentals, cfg)
            bar_db = {"AAA": self._frame(), "QQQ": self._frame(base=500.0)}
            asof = pd.Timestamp("2026-10-09", tz="UTC")
            df = build_cross_section_asof(
                asof=asof, universe=universe, bar_db=bar_db,
                fundamentals=fundamentals, theme_scores=themes,
                watchlist_by_symbol={"AAA": ("bucket", 1, "-")},
                benchmark_return_20d=0.01, benchmark_return_60d=0.04,
                disclosure_lookback_days=720, scan_config=cfg,
                qqq_return_60d=0.04, benchmark_trend_ok=True, split_events={})
            self.assertEqual(len(df), 1)
            return df.iloc[0].to_dict()

    def test_replay_mismatch_row_flagged(self) -> None:
        row = self._run_cross_section("0000999999")
        self.assertFalse(row["fundamental_operating_entity_verified"])
        self.assertIn("RESPONSE_CIK_MISMATCH",
                      row["fundamental_operating_entity_detail"])

    def test_replay_match_row_verified(self) -> None:
        row = self._run_cross_section("0000111111")
        self.assertTrue(row["fundamental_operating_entity_verified"])


class ProductionPathAcceptanceTests(unittest.TestCase):
    def test_fcx_threshold_edge_pinned(self) -> None:
        # Real v0 FCX value through the real builder: the -10.07% OCF edge
        # must keep emitting its weak code (not silently absorbed).
        from ai_value_scanner.decision.quality import build_company_quality_v1
        from tests.test_identity_verification import _metrics as _base_metrics
        metrics = _base_metrics(operating_cash_flow_yoy=-0.100747)
        decision = build_company_quality_v1(metrics, decision_date="2026-10-09")
        codes = [e.code for e in (*decision.risks, *decision.positives)]
        self.assertIn("operating_cash_flow_yoy_weak", codes)

    def test_nee_normal_update_path_untouched(self) -> None:
        # Verified entity + full metrics grades on economics (A/B), with no
        # identity codes — the NEE-class normal path must not route through
        # any new gate.
        from ai_value_scanner.decision.quality import build_company_quality_v1
        from tests.test_identity_verification import _metrics as _base_metrics
        metrics = _base_metrics(fundamental_operating_entity_verified=True,
                                fundamental_operating_entity_detail="ticker_listed_with_core_facts")
        decision = build_company_quality_v1(metrics, decision_date="2026-10-09")
        self.assertIn(decision.grade.value, ("A", "B"))
        codes = [e.code for e in (*decision.missing, *decision.risks)]
        self.assertNotIn("operating_entity_unverified", codes)

    def test_pld_lag_keeps_not_covered_path(self) -> None:
        # Filed-but-uncovered stays UNRATED via the pre-existing
        # latest_periodic_filing_not_covered gate (PLD class).
        from ai_value_scanner.decision.quality import build_company_quality_v1
        from tests.test_identity_verification import _metrics as _base_metrics
        metrics = _base_metrics(fundamental_facts_cover_latest_periodic=False)
        decision = build_company_quality_v1(metrics, decision_date="2026-10-09")
        self.assertEqual(decision.grade.value, "UNRATED")
        self.assertIn("latest_periodic_filing_not_covered",
                      [e.code for e in decision.missing])


class ManifestRowsFileTests(unittest.TestCase):
    def _decision(self):
        from ai_value_scanner.decision.model import (
            ActionState, EntryDecision, EntryState, EvidenceItem,
            QualityDecision, QualityGrade, StockDecision)
        quality = QualityDecision(grade=QualityGrade.A, score=0.8, confidence=1.0,
                                  component_scores={}, positives=(), risks=(),
                                  missing=(), data_asof="2026-08-03")
        entry = EntryDecision(state=EntryState.ENTRY_READY, score=0.6, confidence=0.9,
                              positives=(), risks=(), market_asof="2026-10-12")
        return StockDecision(schema_version="v1", symbol="AAA", company_name="AAA Inc",
                             decision_date="2026-10-12",
                             generated_at_utc="2026-10-13T00:00:00+00:00",
                             quality=quality, entry=entry,
                             action_state=ActionState.PRIORITY_REVIEW, priority=1,
                             rationale=(), review_trigger="Review now.",
                             source_lists=(), provenance={})

    def test_rows_file_written_and_referenced(self) -> None:
        from ai_value_scanner.reporting.snapshot import write_decision_snapshot
        with TemporaryDirectory() as tmp:
            decision = self._decision()
            paths = write_decision_snapshot(
                output_root=tmp, strategy_style="risk_off", decisions=[decision],
                daily_attention=[decision], weekly_attention=[decision],
                generated_at_utc="2026-10-13T00:00:00+00:00", decision_date="2026-10-12",
                config_fingerprint="cfg", code_sha="sha",
                ticker_map_rows=[{"symbol": "AAA", "cik": "0000111111",
                                   "company_name": "AAA Inc"}])
            rows_file = Path(paths.root) / "ticker_map_rows.json"
            self.assertTrue(rows_file.is_file())
            manifest = json.loads((Path(paths.root) / "run_manifest.json").read_text())
            ref = manifest["input_provenance"]["ticker_map_rows_file"]
            self.assertEqual(ref, "ticker_map_rows.json")
            self.assertEqual(
                manifest["input_provenance"]["ticker_map_rows_sha256"],
                hashlib.sha256(rows_file.read_bytes()).hexdigest())

    def test_rows_checksum_mismatch_reported(self) -> None:
        from scripts.validate_mvp_snapshot import check_ticker_map_rows
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {"input_provenance": {
                "ticker_map_rows_file": "ticker_map_rows.json",
                "ticker_map_rows_sha256": "0" * 64}}
            (root / "ticker_map_rows.json").write_text("[]")
            errors = check_ticker_map_rows(root, manifest)
            self.assertTrue(any("sha256" in e.lower() or "mismatch" in e.lower()
                                for e in errors))
            manifest["input_provenance"] = {}
            self.assertEqual(check_ticker_map_rows(root, manifest), [])


class RefreshHeuristicTests(unittest.TestCase):
    def _sec(self, tmp, subs_payload):
        from ai_value_scanner.scanner import SecClient, RequestRateLimiter, NetworkMonitor
        cik = "0000111111"
        (Path(tmp) / f"submissions_{cik}.json").write_text(json.dumps(subs_payload))

        class Resp:
            status_code = 200

            def __init__(self, payload):
                self._payload = payload
                self.text = json.dumps(payload)

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        fetched = []

        def fake_get(url):
            fetched.append(url)
            return Resp({"cik": cik, "entityName": "AAA",
                         "facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": []}}}}})

        session = _StubSession(fake_get)
        monitor = NetworkMonitor()
        limiter = RequestRateLimiter(1000.0, monitor=monitor, service_name="sec-test")
        sec = SecClient(session=session, user_agent="t", timeout_sec=5,
                        cache_dir=Path(tmp), request_limiter=limiter,
                        submissions_ttl_sec=10 ** 9, monitor=monitor)
        return sec, cik, fetched

    def test_eighth_k_ignored_for_coverage(self) -> None:
        # Newest filing is an 8-K: refresh heuristic must use the older 10-Q,
        # so an already-covered 10-Q does not force refetch.
        with TemporaryDirectory() as tmp:
            subs = {"cik": "0000111111", "name": "AAA", "tickers": ["AAA"],
                    "filings": {"recent": {
                        "form": ["8-K", "10-Q"], "accessionNumber": ["k-accn", "q-accn"],
                        "filingDate": ["2026-10-02", "2026-07-29"]}}}
            sec, cik, fetched = self._sec(tmp, subs)
            (Path(tmp) / f"facts_{cik}.json").write_text(json.dumps({"facts": {}}))
            (Path(tmp) / f"facts_meta_{cik}.json").write_text(json.dumps(
                {"covered_accession": "q-accn", "pending_accession": None}))
            sec.get_companyfacts(cik)
            self.assertEqual(fetched, [])

    def test_unknown_form_stays_conservative(self) -> None:
        with TemporaryDirectory() as tmp:
            subs = {"cik": "0000111111", "name": "AAA", "tickers": ["AAA"],
                    "filings": {"recent": {
                        "accessionNumber": ["new-accn"], "filingDate": ["2026-10-02"]}}}
            sec, cik, fetched = self._sec(tmp, subs)
            (Path(tmp) / f"facts_{cik}.json").write_text(json.dumps({"facts": {}}))
            (Path(tmp) / f"facts_meta_{cik}.json").write_text(json.dumps(
                {"covered_accession": "old-accn", "pending_accession": None}))
            sec.get_companyfacts(cik)
            self.assertEqual(len(fetched), 1)

class FinalMergeGateTests(unittest.TestCase):
    """P0 remaining blocker regressions; all fixtures are offline."""

    def test_both_fingerprint_layers_required(self):
        base = dict(symbol="AAA", financial_asof="2026-08-03",
                    mapped_cik="0000111111", code_version="sha|quality|entry",
                    config_fingerprint="cfg", effective_facts_sha="eff",
                    scoring_inputs_sha="score", raw_bytes_sha="raw")
        self.assertEqual(compare_identity_records(base, dict(base)), SAME)
        for key in ("scoring_inputs_sha", "effective_facts_sha"):
            self.assertEqual(compare_identity_records(
                base, dict(base, **{key: None})), PROVENANCE_MISSING)
            both = dict(base, **{key: None})
            self.assertEqual(compare_identity_records(both, both),
                             PROVENANCE_MISSING)
        self.assertEqual(compare_identity_records(
            base, dict(base, effective_facts_sha="other")), UNCOMPARABLE)

    def test_decision_adapter_requires_real_code_sha(self):
        from ai_value_scanner.fundamentals.provenance import (
            decision_provenance_to_identity_record,
        )
        provenance = {
            "cik": "0000111111", "code_sha": "code-one",
            "quality_policy_version": "q1", "entry_policy_version": "e1",
            "config_fingerprint": "cfg", "fundamental_effective_sha256": "effective",
            "identity_scoring_sha": "score",
            "fundamental_companyfacts_raw_sha256": "raw-facts",
            "fundamental_submissions_sha256": "raw-submissions",
        }
        dec = {"symbol": "AAA", "decision_date": "2026-10-13",
               "quality": {"data_asof": "2026-08-03"},
               "provenance": provenance}
        a = decision_provenance_to_identity_record(dec)
        self.assertEqual(a["financial_asof"], "2026-08-03")
        self.assertIn("code-one", a["code_version"])
        self.assertIsNotNone(a["raw_bytes_sha"])
        self.assertEqual(compare_identity_records(a, dict(a)), SAME)
        b = decision_provenance_to_identity_record(dict(
            dec, provenance=dict(provenance, code_sha="code-two")))
        self.assertEqual(compare_identity_records(a, b), UNCOMPARABLE)
        old = decision_provenance_to_identity_record(dict(
            dec, provenance=dict(provenance, code_sha=None)))
        self.assertEqual(compare_identity_records(a, old), PROVENANCE_MISSING)

    def test_missing_facts_response_cik_never_verifies_identity(self):
        from ai_value_scanner.fundamentals.identity import downgrade_on_hard_findings
        findings = check_entity_coherence(
            symbol="AAA", mapped_cik="0000111111",
            submissions=_submissions_doc(), facts_queried_cik="0000111111",
            facts_response_cik=None)["findings"]
        self.assertIn("RESPONSE_CIK_MISSING", findings)
        verified, _ = downgrade_on_hard_findings(
            True, "ticker_listed_with_core_facts", findings)
        self.assertFalse(verified)

    def test_live_audit_exception_fails_closed(self):
        from unittest.mock import patch
        from ai_value_scanner.decision.quality import build_company_quality_v1
        with TemporaryDirectory() as tmp:
            sub, facts = _submissions_doc(), _facts_doc()
            _plant_meta(tmp, "0000111111", "0000001111-26-000001")
            _plant_raw(tmp, "0000111111", sub, facts)
            def _audit_failure(**kwargs):
                raise RuntimeError("injected audit error")
            # Patch the loader's globals directly: confirm the actual
            # callable used by the integrated path is the one failing.
            with patch.dict(load_one_fundamental.__globals__,
                            {"check_entity_coherence": _audit_failure}):
                row = load_one_fundamental(
                    _StubSec(sub, facts), "AAA", "0000111111", _test_config(tmp))
            self.assertFalse(row["fundamental_operating_entity_verified"])
            self.assertIn("coherence_check_failed", row["fundamental_operating_entity_detail"])
            quality = build_company_quality_v1(row, decision_date="2026-10-09")
            self.assertEqual(quality.grade.value, "UNRATED")
            self.assertIn("operating_entity_unverified",
                          [x.code for x in quality.missing])

    def test_replay_audit_exception_fails_closed(self):
        from unittest.mock import patch
        with patch("ai_value_scanner.backtest.check_entity_coherence",
                   side_effect=RuntimeError("injected replay error")):
            row = ReplayCoherenceTests()._run_cross_section("0000111111")
        self.assertFalse(row["fundamental_operating_entity_verified"])
        self.assertIn("COHERENCE_CHECK_FAILED",
                      row["fundamental_operating_entity_detail"])

    def test_companyfacts_raw_layer_separate_from_effective_document(self):
        with TemporaryDirectory() as tmp:
            sub, facts = _submissions_doc(), _facts_doc()
            _plant_meta(tmp, "0000111111", "0000001111-26-000001")
            _plant_raw(tmp, "0000111111", sub, facts)
            row = load_one_fundamental(
                _StubSec(sub, facts), "AAA", "0000111111", _test_config(tmp))
            self.assertEqual(row["fundamental_companyfacts_raw_sha256"],
                             sha256_hex(canonical_json_bytes(facts)))
            # No fallback patch in this case; the full document is unchanged.
            self.assertEqual(row["fundamental_companyfacts_raw_sha256"],
                             row["fundamental_companyfacts_sha256"])


if __name__ == "__main__":
    unittest.main()
