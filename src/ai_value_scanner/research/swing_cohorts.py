"""Preregister and freeze swing experiment cohorts without reading outcome prices."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
from itertools import groupby
import math
from pathlib import Path
from typing import Any

from ai_value_scanner.decision.medium_term import sic_group
from ai_value_scanner.forward.ledger import Ledger, append, canonical, entries, evidence_id, require, text, utc
from ai_value_scanner.fundamentals.coverage import SHARES_BASIS
from ai_value_scanner.market_calendar import is_session_day, session_close_utc, session_open_utc
from ai_value_scanner.market_data import SIP_PUBLICATION_DELAY
from ai_value_scanner.swing.setups import (
    BREAKOUT_VERSION, PULLBACK_VERSION, factor_between, next_session, previous_session, split_factors,
)

VERSION = "swing_experiment_v3"
KINDS = {BREAKOUT_VERSION: ("breakout", "WATCH_BREAKOUT"), PULLBACK_VERSION: ("pullback", "WATCH_PULLBACK")}
IDENTITY = ("style", "config_fingerprint", "decision_policy", "report_renderer")
PRIMARY = 10
HORIZONS = (5, PRIMARY, 20, 60)
WAIT = 5
DELAYS = (1, 3, 5)
SEED = 70925
CAP = 15
INTEGRITY = {"freshness", "benchmark_freshness", "data_completeness"}
ENTRY_GATES = INTEGRITY | {"trend_damage"}
PROTOCOL = {
    "version": VERSION, "primary_horizon": PRIMARY, "horizons": list(HORIZONS), "wait_sessions": WAIT,
    "delays": list(DELAYS), "fee_bps_per_side": [15, 30], "seed": SEED, "attention_cap": CAP,
    "minimum_lift": .003, "maximum_tail_deterioration": .01, "minimum_dates": 40,
    "minimum_issuers": 10, "minimum_calendar_blocks": 4, "minimum_pair_coverage": .90,
    "minimum_publication_coverage": .90,
    "maximum_issuer_share": .25, "volatility_caliper": .10, "bootstrap_draws": 2000,
    "missing_delta_stress": .20, "maximum_tail_interval_width": .08,
    "primary_comparisons": ["confirmation_vs_matched", "wait_vs_immediate", "structure_exit_vs_fixed",
                            "financial_candidate_vs_top15"],
}


def sha(value: Any) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def implementation_sha256() -> str:
    """Bind executable research source, including imported timing/basis rules."""
    package = Path(__file__).resolve().parents[1]
    sources = (
        "research/swing_cohorts.py", "research/swing_experiment.py", "research/swing_paths.py",
        "research/swing_statistics.py", "market_calendar.py", "market_data.py", "swing/setups.py",
        "decision/medium_term.py", "fundamentals/coverage.py", "forward/ledger.py",
    )
    return sha({name: sha256((package / name).read_bytes()).hexdigest() for name in sources})


def require_implementation(spec: dict) -> None:
    if spec.get("implementation_sha256") != implementation_sha256():
        raise ValueError("evaluator implementation differs from registration; register a new protocol")


def numeric(value) -> float | None:
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def sessions(start: date, end: date) -> list[date]:
    result = []
    while start <= end:
        result.append(start)
        start = next_session(start)
    return result


def day_shift(day: date, count: int) -> date:
    for _ in range(count):
        day = next_session(day)
    return day


def execution_day(known: str) -> date:
    """Daily-only convention. Never substitute an open that already elapsed."""
    instant = utc(known)
    day = instant.date()  # UTC morning and NY session open are on the same date.
    if is_session_day(day) and instant < session_open_utc(day):
        return day
    return next_session(day)


def register(ledger: Ledger, spec: dict, *, now: datetime | None = None) -> str:
    at = utc(now or datetime.now(timezone.utc))
    start, end = (date.fromisoformat(spec[name]) for name in ("start", "through"))
    if start > end or not is_session_day(start) or not is_session_day(end):
        raise ValueError("protocol endpoints must be ordered NYSE sessions")
    mode, pattern = spec["mode"], spec["pattern"]
    if mode not in ("retrospective", "forward") or pattern not in KINDS:
        raise ValueError("unknown evidence mode or swing protocol")
    if mode == "forward" and at >= session_open_utc(start):
        raise ValueError("a forward protocol must be registered before the first session opens")
    identity = {key: text(spec.get(key), key) for key in IDENTITY}
    windows = {}
    for item in spec.get("pressure_windows", []):
        label = text(item.get("name"), "pressure window name")
        first, last = (date.fromisoformat(item[key]) for key in ("start", "through"))
        if (label in windows or not start <= first <= last <= end
            or not is_session_day(first) or not is_session_day(last)):
            raise ValueError("pressure windows must have distinct names and lie within the registered NYSE interval")
        windows[label] = {"start": first.isoformat(), "through": last.isoformat()}
    key = evidence_id("swing_protocol", text(spec.get("name"), "name"), identity["style"], pattern)
    payload = {**identity, "name": spec["name"], "start": start.isoformat(), "through": end.isoformat(),
               "mode": mode, "pattern": pattern, "rules": PROTOCOL, "pressure_windows": windows,
               "implementation_sha256": implementation_sha256()}
    with ledger.transaction() as db:
        append(db, key, "swing_protocol", None, payload, at)
    return key


def _integrity(row, day):
    gates = [gate for gate in row.get("entry_gates", []) if gate["gate_key"] in INTEGRITY]
    gate_names = {gate["gate_key"] for gate in gates if gate["status"] == "PASS"}
    return bool(row.get("security_id") and row["quality"] != "UNRATED" and row.get("quality_asof")
                and row["quality_asof"][:10] <= day and row["market_asof"] == day
                and gate_names == INTEGRITY and all(gate["status"] == "PASS" for gate in gates)
                and row["entry"] != "INSUFFICIENT_DATA")


def _eligible(row, day):
    return _integrity(row, day) and row["quality"] in ("A", "B") and row["entry"] != "TREND_DAMAGED"


def _pattern(row, variant, version):
    context = row.get("swing_review") or {}
    item = (context.get("patterns") or {}).get(variant) or {}
    state = item.get("state") or {}
    if state.get("version") != version or numeric(context.get("close")) is None:
        return {}, False
    return state, item.get("new_confirmation") is True


def _vol(row):
    for item in row.get("entry_gates", []):
        if item.get("metric") == "volatility_60d":
            return numeric(item.get("observed"))
    return None


def _industry(row):
    return sic_group(row.get("industry"))


def _cik(row):
    return (row.get("security_id") or ":").split(":")[-1] or None


def _regime(row):
    for gate in row.get("entry_gates", []):
        if gate["gate_key"] == "market_regime":
            reason = gate.get("reason", "")
            if reason.startswith("Defensive regime"):
                return "defensive"
            if reason.startswith("Benchmark regime does not impose"):
                return "supportive"
    return "unknown"


def _member(row):
    return {"security_id": row["security_id"], "symbol": row["symbol"], "cik": _cik(row),
            "quality": row["quality"], "industry": _industry(row), "volatility": _vol(row), "regime": _regime(row),
            "daily_rank": row.get("daily_rank"), "s2_reason": row.get("s2_reason")}


def _seeded(rows, day, purpose):
    return sorted(rows, key=lambda row: sha([SEED, day, purpose, row["security_id"]]))


def _peers(target, rows):
    vol = _vol(target)
    return [
        row for row in rows
        if _cik(row) != _cik(target) and row["quality"] == target["quality"]
        and _industry(row) is not None and _industry(row) == _industry(target) and vol is not None
        and _vol(row) is not None and abs(_vol(row) - vol) <= PROTOCOL["volatility_caliper"]
    ]


def _entry_pass(row):
    names = {gate["gate_key"] for gate in row.get("entry_gates", []) if gate["status"] == "PASS"}
    return row["entry"] == "ENTRY_READY" and ENTRY_GATES <= names


def _risk(row):
    vol = _vol(row)
    return (row["quality"], row["entry"], _industry(row), None if vol is None else math.floor(vol * 10),
            tuple(sorted((gate["gate_key"], gate["status"]) for gate in row.get("entry_gates", []))))


def _fcf_yield(row, *, day, available):
    review = row.get("financial_review") or {}
    fcf = numeric(review.get("metrics", {}).get("fcf_per_current_share"))
    close = numeric(row.get("official_close"))
    shares = (review.get("derived_operands") or {}).get("current_shares") or {}
    if (review.get("status") != "recovered_candidate" or review.get("currency") != "USD"
        or review.get("asof") != day or row.get("market_asof") != day or fcf is None or not close or close <= 0
        or shares.get("basis") != SHARES_BASIS or not shares.get("sources")):
        return None
    try:
        prior, current = date.fromisoformat(shares["end"]), date.fromisoformat(day)
        if prior > current:
            return None
        if prior == current:
            return numeric(fcf / close)
        basis_ids = shares.get("basis_ids")
        if not isinstance(basis_ids, list) or len(basis_ids) != 1 or not basis_ids[0]:
            return None
        proofs = [proof for proof in review.get("market_share_bases", []) if (
            proof.get("security_id") == row["security_id"] and proof.get("share_basis_id") == basis_ids[0]
            and proof.get("share_period_end") == shares["end"] and proof.get("price_session") == day
            and proof.get("source") and isinstance(proof.get("splits"), list)
            and session_close_utc(current) <= utc(proof["known_at_utc"]) <= utc(available)
        )]
        if len(proofs) != 1:
            return None
        splits = split_factors(proofs[0]["splits"], through=current)
        if len(splits) != len(proofs[0]["splits"]) or any(
            not prior < effective <= current or not is_session_day(effective) for effective in splits
        ):
            return None
        return numeric(fcf * factor_between(splits, prior, current) / close)
    except (AttributeError, KeyError, TypeError, ValueError, ArithmeticError):
        return None


def _rank_cohort(day, available, meta, rows):
    ordered = sorted(rows, key=lambda row: (row["priority"], row["symbol"]))
    quality = [row for row in ordered if _integrity(row, day) and row["quality"] in ("A", "B")]
    entry = [row for row in quality if _entry_pass(row)]
    priority = [row for row in entry if row["action"] == "PRIORITY_REVIEW"]
    evidence_cutoff = min(utc(available), utc(meta["generated_at_utc"])) if meta.get("generated_at_utc") else available
    scores = {row["security_id"]: _fcf_yield(row, day=day, available=evidence_cutoff) for row in priority}
    # The actual production ranking comes from the archived priority. The
    # candidate reorders only contiguous, comparable risk blocks when every
    # member has verified FCF yield; otherwise all original slots are preserved.
    candidate = []
    for risk, group in groupby(priority, _risk):
        block = list(group)
        if risk[2] is not None and risk[3] is not None and all(scores[row["security_id"]] is not None for row in block):
            block.sort(key=lambda row: (-scores[row["security_id"]], row["priority"], row["symbol"]))
        candidate.extend(block)
    by_symbol = {row["symbol"]: row for row in ordered}
    daily = [by_symbol[sym] for sym in meta["daily"]]
    pools = {"quality": quality, "entry": entry, "priority": priority, "top15": priority[:CAP],
             "rank16_30": priority[CAP:2*CAP], "daily_s2": daily,
             "daily_grace": [row for row in daily if row.get("s2_reason") == "soft_exit_grace"],
             "financial_candidate": candidate[:CAP], "random_k": _seeded(priority, day, "rank")[:CAP]}
    swaps = set(row["security_id"] for row in pools["financial_candidate"]) - set(row["security_id"] for row in pools["top15"])
    regimes = {_regime(row) for row in quality} - {"unknown"}
    return {
        "session": day, "available": available,
        "regime": regimes.pop() if len(regimes) == 1 else "unknown",
        "daily_stability_policy": meta.get("stability_policy"),
        "groups": {name: [_member(row) for row in pool] for name, pool in pools.items()},
        "financial_additions": sorted(swaps),
        "financial_removals": sorted(set(row["security_id"] for row in pools["top15"])
                                     - set(row["security_id"] for row in pools["financial_candidate"])),
        "candidate_scores": scores,
        "cash_rule": "one_slot_per_member; groups_of_fewer_than_15_keep_unused_slots_in_cash",
    }


def freeze(ledger: Ledger, protocol_id: str, *, asof: datetime | None = None) -> dict:
    instant = utc(asof or datetime.now(timezone.utc))
    with ledger.transaction() as db:
        protocol = require(db, protocol_id, "swing_protocol")
        spec = protocol["payload"]
        require_implementation(spec)
        if spec["rules"] != PROTOCOL or utc(protocol["recorded_at"]) > instant:
            raise ValueError("protocol revision or freeze cutoff does not match the registration")
        snapshots = {item["payload"]["session"]: item for item in entries(db, "snapshot")
                     if item["payload"]["style"] == spec["style"] and utc(item["recorded_at"]) <= instant}
        attempts = defaultdict(list)
        for receipt in entries(db, "receipt"):
            payload = receipt["payload"]
            if payload["style"] == spec["style"] and utc(receipt["recorded_at"]) <= instant:
                attempts[payload["session"]].append(receipt)
        start, end = (date.fromisoformat(spec[key]) for key in ("start", "through"))
        frames, coverage = {}, {}
        # Include one predecessor for first-observation evidence and five
        # follow-up sessions for origins near the registration endpoint.
        for day in sessions(previous_session(start), day_shift(end, WAIT)):
            token = day.isoformat()
            if session_close_utc(day) + SIP_PUBLICATION_DELAY > instant:
                coverage[token] = {"status": "not_yet_observable"}
                continue
            snapshot = snapshots.get(token)
            if snapshot is None:
                coverage[token] = {"status": "no_matching_snapshot", "attempts": [a["payload"]["status"] for a in attempts[token]]}
                continue
            raw = snapshot["payload"]
            if any(raw.get(key) != spec[key] for key in IDENTITY):
                coverage[token] = {"status": "other_protocol_version"}
                continue
            proofs = [a for a in attempts[token] if a["parent"] == snapshot["id"] and a["payload"]["first_readable_at_utc"]]
            proof = proofs[0] if proofs else None
            forward = bool(proof and raw.get("decision_bytes_pinned")
                           and utc(protocol["recorded_at"]) <= utc(proof["payload"]["first_readable_at_utc"]))
            # The pre-registration predecessor can establish baseline continuity,
            # but only the study sessions may contribute forward observations.
            forward_prior = day < start and proof and raw.get("decision_bytes_pinned")
            if spec["mode"] == "forward" and not (forward or forward_prior):
                coverage[token] = {"status": "publication_proof_unavailable"}
                continue
            if spec["mode"] == "forward" and any(
                not a["payload"].get("receipt_sha256") for a in proofs
            ):
                raise ValueError("forward evidence must have imported formal receipts")
            available = (utc(proof["payload"]["first_readable_at_utc"]) if proof else
                         max(utc(raw["generated_at_utc"]), session_close_utc(day) + SIP_PUBLICATION_DELAY))
            if available > instant:
                coverage[token] = {"status": "not_readable_at_cutoff"}
                continue
            rows = [item["payload"] for item in entries(db, "observation", parent=snapshot["id"])]
            frames[token] = {"rows": rows, "meta": raw, "available": available.isoformat()}
            coverage[token] = {"status": "observed", "available": available.isoformat(),
                               "snapshot": snapshot["id"], "manifest_sha256": raw["manifest_sha256"],
                               "receipt": proof["id"] if proof else None,
                               "receipt_sha256": proof["payload"]["receipt_sha256"] if proof else None,
                               "timing": "first_readable" if proof else "retrospective_assumption"}
    return freeze_cohorts(spec, frames, coverage=coverage, protocol_id=protocol_id, asof=instant)


def freeze_cohorts(spec, frames, *, coverage, protocol_id, asof):
    coverage = {day: dict(row) for day, row in coverage.items()}
    version = spec["pattern"]
    variant, watch_state = KINDS[version]
    start, end = (date.fromisoformat(spec[key]) for key in ("start", "through"))
    days = sessions(previous_session(start), day_shift(end, WAIT))
    episodes, matched, rank, medium = [], [], [], []
    active, last, used_pairs, used_random = {}, {}, defaultdict(set), defaultdict(set)
    missing = Counter()
    for day in days:
        token = day.isoformat()
        frame = frames.get(token)
        available = frame["available"] if frame else None
        rows = frame["rows"] if frame else []
        if coverage.get(token, {}).get("status") == "not_yet_observable":
            break
        known = {row["security_id"]: row for row in rows if row["security_id"]}
        order_ok = frame is not None and (not last or utc(available) > utc(last["available"]))
        new_watches, waiting_today = {}, []
        adjacent = order_ok and last.get("session") == previous_session(day).isoformat()
        if adjacent:
            for security, row in sorted(known.items()):
                state, _ = _pattern(row, variant, version)
                if (not _eligible(row, token) or row["entry"] != watch_state or state.get("status") != "watching"
                    or (variant == "pullback" and not state.get("origin"))):
                    continue
                if security in active:
                    if day < day_shift(date.fromisoformat(active[security]["session"]), WAIT):
                        waiting_today.append(row)
                    continue
                prev = last["rows"].get(security)
                prev_state, _ = _pattern(prev, variant, version) if prev else ({}, False)
                if not prev or not _integrity(prev, last["session"]) or not prev_state or prev_state.get("status") == "insufficient":
                    if start <= day <= end:
                        missing["left_censored"] += 1
                    continue
                if (_eligible(prev, last["session"]) and prev["entry"] == watch_state and prev_state.get("status") == "watching"
                    and (variant == "breakout" or prev_state.get("origin"))):
                    continue
                waiting_today.append(row)
                new_watches[security] = row
        elif order_ok and start <= day <= end:
            missing["left_censored"] += sum(
                _eligible(row, token) and row["entry"] == watch_state for row in rows
            )
        for security, episode in list(active.items()):
            row = known.get(security)
            state, fresh = _pattern(row, variant, version) if row else ({}, False)
            continuity = adjacent
            if not continuity or not row or not state or state.get("status") == "insufficient" or row["market_asof"] != token:
                episode.update(status="unknown_continuity", resolution_session=token)
            elif not _eligible(row, token):
                # A canonical observed loss of eligibility can close the
                # opportunity. Missing evidence is never treated as cash.
                episode.update(status="failed" if _integrity(row, token) else "unknown_continuity",
                               resolution_session=token)
            elif fresh and state.get("confirmed") == token and numeric(state.get("stop")) and state["stop"] > 0:
                controls = [item for item in waiting_today if _cik(item) != _cik(row)]
                peers = sorted(_peers(row, controls), key=lambda item: (abs(_vol(row) - _vol(item)), item["security_id"]))
                peer = next((item for item in peers if _cik(item) not in used_pairs[token]), None)
                random = next((item for item in _seeded(controls, token, "shape") if _cik(item) not in used_random[token]), None)
                if peer:
                    used_pairs[token].add(_cik(peer))
                if random:
                    used_random[token].add(_cik(random))
                episode.update(status="confirmed", resolution_session=token, confirmation_available=available,
                               level=state["stop"], confirmation_origin=state.get("origin"),
                               resistance=(state.get("resistance") or {}).get("price"))
                matched.append({"session": token, "available": available, "event_id": episode["id"],
                                "target": _member(row), "peer": _member(peer) if peer else None,
                                "random": _member(random) if random else None, "unconfirmed_pool_size": len(controls)})
            elif state.get("status") == "invalidated" and state.get("ended") == token:
                episode.update(status="failed", resolution_session=token)
            elif state.get("status") == "confirmed":
                # A regenerated shape with an earlier confirmation date
                # cannot stand in for the missing first observation.
                episode.update(status="unknown_continuity", resolution_session=token)
            elif day == day_shift(date.fromisoformat(episode["session"]), WAIT):
                episode.update(status="expired", resolution_session=token)
            if episode["status"] != "waiting":
                del active[security]
        if start <= day <= end and order_ok:
            rank.append(_rank_cohort(token, available, frame["meta"], rows))
            eligible = [row for row in sorted(rows, key=lambda item: item["symbol"]) if _eligible(row, token)]
            medium_peers = defaultdict(list)
            for row in eligible:
                media = row.get("medium_review") or {}
                if media.get("short_confirmed") is False and media.get("medium_trend_damaged") is False:
                    medium_peers[(row["quality"], _industry(row))].append(row)
            for row in eligible:
                m = row.get("medium_review") or {}
                if m.get("medium_trend_damaged") in (True, False) and m.get("short_confirmed") in (True, False):
                    stock = _member(row)
                    current_group = (m["short_confirmed"], m["medium_trend_damaged"])
                    peers = [
                        peer for peer in medium_peers[(stock["quality"], stock["industry"])]
                        if stock["industry"] is not None and _cik(peer) != stock["cik"]
                    ]
                    comparator = _seeded(peers, token, "medium")[0] if peers else None
                    live = [_pattern(row, key, value)[0] for value, (key, _) in KINDS.items()]
                    stops = [p["stop"] for p in live if p.get("status") == "confirmed" and numeric(p.get("stop"))]
                    medium.append({"session": token, "available": available, "target": stock,
                                   "short_confirmed": current_group[0], "below_sma10": current_group[1],
                                   "peer": _member(comparator) if comparator else None,
                                   "short_stop": max(stops) if stops else None,
                                   "weekly_sma10": (m.get("completed_week") or {}).get("sma10")})
            for security, row in new_watches.items():
                episode = {**_member(row), "session": token, "available": available,
                           "id": evidence_id("swing_episode", protocol_id, security, token), "status": "waiting"}
                episodes.append(episode)
                active[security] = episode
        if frame is not None and order_ok:
            last = {"session": token, "rows": known, "available": available}
        elif not order_ok and frame:
            missing["out_of_order_publication"] += 1
            coverage.setdefault(token, {})["status"] = "out_of_order_publication"
    return {
        "version": VERSION, "protocol_id": protocol_id, "spec": spec, "frozen_at": asof.isoformat(),
        "session_coverage": coverage, "episodes": episodes, "confirmation_pairs": matched,
        "ranking": rank, "medium": medium, "excluded": dict(missing),
        "weights": {"episodes": "equal_by_origin_session_then_equal_per_session",
                    "confirmation": "equal_by_confirmation_session_then_equal_per_session",
                    "ranking": "equal_slots"},
    }
