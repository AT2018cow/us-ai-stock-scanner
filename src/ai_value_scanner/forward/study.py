"""Record human decisions and price-evidenced paper paths without changing scans."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import re
from typing import Any

from ai_value_scanner.market_calendar import is_session_day, session_close_utc, session_open_utc
from ai_value_scanner.market_data import SIP_PUBLICATION_DELAY, sip_publication_window
from .ledger import (
    Ledger, append, entries, evidence_id, local_day, lookup, number,
    readable_at, require, text, utc,
)

_PROTOCOL_IDENTITY = ("style", "decision_policy", "config_fingerprint", "report_renderer")


def _matches_protocol(spec: dict, snapshot: dict) -> bool:
    return all(spec.get(field) == snapshot.get(field) for field in _PROTOCOL_IDENTITY)


def freeze_protocol(ledger: Ledger, spec: dict, *, now: datetime | None = None) -> str:
    recorded = utc(now or datetime.now(timezone.utc))
    version = text(spec.get("version"), "protocol version")
    style = text(spec.get("style"), "strategy style")
    fees = number(spec.get("fee_bps_per_side"), "fee_bps_per_side", maximum=100)
    horizons = spec.get("horizons")
    if not isinstance(horizons, list) or not horizons or any(
        type(days) is not int or not 1 <= days <= 252 for days in horizons
    ):
        raise ValueError("horizons must be a nonempty list of session counts between 1 and 252")
    versions = spec.get("setup_versions", [])
    if not isinstance(versions, list) or any(not isinstance(item, str) or not item.strip() for item in versions):
        raise ValueError("setup_versions must list frozen shape versions")
    rules = spec.get("paper_rules", [])
    if not isinstance(rules, list) or any(not isinstance(item, str) or not item.strip() for item in rules):
        raise ValueError("paper_rules must list frozen path versions")
    protocol = {
        "version": version, "style": style, "fee_bps_per_side": fees,
        "horizons": sorted(set(horizons)), "setup_versions": sorted(set(versions)),
        "paper_rules": sorted(set(rules)),
        "decision_policy": text(spec.get("decision_policy"), "decision_policy"),
        "report_renderer": text(spec.get("report_renderer"), "report_renderer"),
        "config_fingerprint": text(spec.get("config_fingerprint"), "config_fingerprint"),
        "description": text(spec.get("description"), "description"),
    }
    key = evidence_id("protocol", style, version)
    with ledger.transaction() as db:
        append(db, key, "protocol", None, protocol, recorded)
    return key


def _context(db, protocol_id: str, observation_id: str):
    protocol = require(db, protocol_id, "protocol")
    observation = require(db, observation_id, "observation")
    snapshot = require(db, observation["parent"], "snapshot")
    study, published = protocol["payload"], snapshot["payload"]
    if not _matches_protocol(study, published):
        raise ValueError("snapshot does not match the registered protocol")
    ready_at = readable_at(db, snapshot["id"])
    return protocol, observation, snapshot, ready_at


def _evidence_class(protocol: dict, snapshot: dict, ready_at: datetime | None, happened: datetime, recorded: datetime) -> str:
    if ready_at is None:
        return "publication_time_unknown"
    deadline = session_close_utc(local_day(_next_open(ready_at)))
    if (snapshot["payload"].get("decision_bytes_pinned") and utc(protocol["recorded_at"]) <= ready_at
        and happened <= recorded <= deadline
        and local_day(happened) == local_day(recorded)):
        return "forward"
    return "backfill"


def record_review(ledger: Ledger, data: dict, *, now: datetime | None = None) -> str:
    recorded = utc(now or datetime.now(timezone.utc))
    protocol_id, observation_id = data["protocol_id"], data["observation_id"]
    workflow, surface = data["workflow"], data["surface"]
    choice = data["choice"]
    if workflow not in ("baseline", "new") or surface not in ("daily", "weekly"):
        raise ValueError("invalid review workflow or displayed list")
    if choice not in ("deep_dive", "wait", "reject"):
        raise ValueError("invalid review choice")
    displayed, read, decided = (utc(data[key]) for key in ("displayed_at", "read_at", "decided_at"))
    if not displayed <= read <= decided <= recorded:
        raise ValueError("display, reading, decision, and actual recording are out of order")
    budget = number(data["budget_minutes"], "budget_minutes", minimum=0.01)
    minutes = number(data["review_minutes"], "review_minutes", maximum=budget)
    if minutes > (decided - read).total_seconds() / 60 + 1e-9:
        raise ValueError("reported review minutes exceed elapsed reading time")
    risks = data.get("risk_codes", [])
    if not isinstance(risks, list):
        raise ValueError("risk_codes must be a list")
    risk_codes = sorted({text(risk, "risk code") for risk in risks})
    pair = data.get("pair_id")
    pair = text(pair, "pair_id") if pair is not None else None
    key = evidence_id("review", protocol_id, observation_id, workflow, surface)
    with ledger.transaction() as db:
        protocol, observation, snapshot, ready_at = _context(db, protocol_id, observation_id)
        if observation["payload"][surface + "_rank"] is None:
            raise ValueError("reviewed stock is absent from the declared list")
        existing = lookup(db, key)
        if existing is None and displayed < (ready_at or utc(snapshot["payload"]["generated_at_utc"])):
            raise ValueError("report was displayed before the source was available")
        archive_hash = snapshot["payload"]["sha256"]["action_list.md" if surface == "daily" else "weekly_review.md"]
        shown_hash = data.get("displayed_report_sha256", archive_hash if workflow == "new" else None)
        if not isinstance(shown_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", shown_hash):
            raise ValueError("the displayed report requires its SHA256")
        if workflow == "new" and shown_hash != archive_hash:
            raise ValueError("displayed report hash differs from the registered archive")
        shown_version = (
            text(data.get("displayed_version"), "baseline report version")
            if workflow == "baseline" else snapshot["payload"]["report_renderer"]
        )
        payload = {
            "protocol_id": protocol_id, "snapshot_id": snapshot["id"],
            "manifest_sha256": snapshot["payload"]["manifest_sha256"],
            "displayed_report_sha256": shown_hash, "displayed_version": shown_version,
            "workflow": workflow, "surface": surface, "choice": choice,
            "reason": text(data["reason"], "review reason"), "budget_minutes": budget,
            "review_minutes": minutes, "risk_codes": risk_codes, "pair_id": pair,
            "displayed_at": displayed.isoformat(), "read_at": read.isoformat(), "decided_at": decided.isoformat(),
        }
        payload["evidence_class"] = (
            existing["payload"]["evidence_class"] if existing
            else _evidence_class(protocol, snapshot, ready_at, decided, recorded)
        )
        if pair is not None:
            for review in entries(db, "review"):
                other = review["payload"]
                if review["id"] == key or (other["protocol_id"], other["pair_id"]) != (protocol_id, pair):
                    continue
                peer = require(db, review["parent"], "observation")["payload"]
                current = observation["payload"]
                if (
                    workflow == other["workflow"] or surface != other["surface"] or budget != other["budget_minutes"]
                    or not current["industry"] or current["industry"] != peer["industry"]
                    or date.fromisoformat(current["session"]).isocalendar()[:2]
                    != date.fromisoformat(peer["session"]).isocalendar()[:2]
                    or not current["security_id"] or not peer["security_id"] or current["security_id"] == peer["security_id"]
                ):
                    raise ValueError("review pair needs distinct securities, matching week, industry, list and budget")
        append(db, key, "review", observation_id, payload, recorded)
    return key


def record_setup(ledger: Ledger, data: dict, *, now: datetime | None = None) -> str:
    """Attach observations from an explicit setup version to a continuing event."""
    recorded = utc(now or datetime.now(timezone.utc))
    pid, oid = data["protocol_id"], data["observation_id"]
    version = text(data["setup_version"], "setup_version")
    state = data["state"]
    if state not in ("watching", "confirmed", "active", "ended"):
        raise ValueError("invalid setup observation state")
    observed = utc(data["observed_at"])
    source = text(data["source"], "setup evidence source")
    if not isinstance(data.get("evidence"), dict) or not data["evidence"]:
        raise ValueError("setup observations require nonempty evidence")
    key = evidence_id("setup", pid, oid, version)
    with ledger.transaction() as db:
        protocol, observation, snapshot, ready_at = _context(db, pid, oid)
        if version not in protocol["payload"]["setup_versions"]:
            raise ValueError("setup version is not frozen in the protocol")
        security = observation["payload"]["security_id"]
        if not security:
            raise ValueError("setup identity requires an issuer CIK")
        if not (ready_at or utc(snapshot["payload"]["generated_at_utc"])) <= observed <= recorded:
            raise ValueError("setup observation falls outside the available evidence window")
        day = snapshot["payload"]["session"]
        group = evidence_id("setup_series", pid, security, version)
        existing = lookup(db, key)
        if existing is None:
            past = [row["payload"] for row in entries(db, "setup") if row["payload"]["series_id"] == group]
            previous = max(past, key=lambda row: row["session"]) if past else None
            if previous is not None and previous["session"] >= day:
                raise ValueError("setup observations must advance to a later session")
            previous_day = date.fromisoformat(previous["session"]) if previous else None
            adjacent = previous_day is not None and local_day(_next_open(session_open_utc(previous_day))) == date.fromisoformat(day)
            interrupted = previous["event_id"] if (
                previous and not adjacent and previous["state"] in ("confirmed", "active")
            ) else None
            open_episode = bool(adjacent and previous["event_id"] and previous["state"] in ("confirmed", "active"))
            continuation = state in ("active", "ended")
            gap = bool(continuation and previous and not open_episode and (
                interrupted or previous.get("continuity") == "unknown"
            ))
            if not gap and open_episode != continuation:
                raise ValueError("continuations require an open confirmation and new confirmations require a closed series")
            watch_id = None
            if state == "watching":
                watch_id = previous["watch_id"] if adjacent and previous["state"] == "watching" else key
            if state == "confirmed":
                episode = evidence_id("episode", snapshot["id"], security, pid, version, day)
                first_session = day
                if adjacent and previous["state"] == "watching":
                    watch_id = previous["watch_id"]
            elif open_episode:
                episode, first_session, watch_id = previous["event_id"], previous["first_confirmed_session"], previous["watch_id"]
            else:
                episode, first_session = None, None
            evidence_class = _evidence_class(protocol, snapshot, ready_at, observed, recorded)
            if open_episode and previous["evidence_class"] != "forward":
                evidence_class = previous["evidence_class"]
        else:
            before = existing["payload"]
            episode, first_session, watch_id = before["event_id"], before["first_confirmed_session"], before["watch_id"]
            evidence_class = before["evidence_class"]
            gap = before.get("continuity") == "unknown"
            interrupted = before.get("interrupted_event_id")
        append(db, key, "setup", oid, {
            "protocol_id": pid, "snapshot_id": snapshot["id"], "series_id": group, "session": day,
            "setup_version": version, "state": state, "source": source, "evidence": data["evidence"],
            "observed_at": observed.isoformat(), "evidence_class": evidence_class,
            "event_id": episode, "first_confirmed_session": first_session, "watch_id": watch_id,
            **({"continuity": "unknown"} if gap else {}),
            **({"interrupted_event_id": interrupted} if interrupted else {}),
        }, recorded)
    return key


def _next_open(after: datetime) -> datetime:
    day = local_day(after)
    while not is_session_day(day) or session_open_utc(day) <= after:
        day += timedelta(days=1)
    return session_open_utc(day)


def _session_at(value: datetime):
    day = local_day(value)
    if not is_session_day(day) or not session_open_utc(day) <= value <= session_close_utc(day):
        raise ValueError("execution timestamp is outside a regular NYSE session")
    return day


def _maturity(start: date, sessions: int) -> datetime:
    while sessions > 1:
        start += timedelta(days=1)
        if is_session_day(start):
            sessions -= 1
    return session_close_utc(start)


def record_paper(ledger: Ledger, data: dict, *, now: datetime | None = None) -> str:
    recorded = utc(now or datetime.now(timezone.utc))
    pid, oid = data["protocol_id"], data["observation_id"]
    basis, status = data["path"], data["status"]
    if basis not in ("manual", "fixed") or status not in ("planned", "cash", "unexecutable"):
        raise ValueError("invalid paper path or status")
    rule = text(data["rule_version"], "paper rule version")
    decision_at = utc(data["decision_at"])
    execution_basis = data.get("execution_basis", "next_open")
    if execution_basis not in ("next_open", "time_stamped"):
        raise ValueError("invalid execution basis")
    reviewed, setup = data.get("review_id"), data.get("setup_id")
    with ledger.transaction() as db:
        protocol, observation, snapshot, ready_at = _context(db, pid, oid)
        if rule not in protocol["payload"]["paper_rules"]:
            raise ValueError("paper rule version is not frozen in the protocol")
        if ready_at is None:
            raise ValueError("a paper path requires a known publication time")
        if not observation["payload"]["security_id"]:
            raise ValueError("paper identity requires an issuer CIK")
        after = ready_at
        historical_input = False
        if reviewed is not None:
            review = require(db, reviewed, "review")
            if review["parent"] != oid or review["payload"]["protocol_id"] != pid:
                raise ValueError("human review belongs to another observation or protocol")
            after = max(after, utc(review["payload"]["decided_at"]))
            historical_input = review["payload"]["evidence_class"] != "forward"
        if basis == "manual" and reviewed is None:
            raise ValueError("manual path requires a human review ID")
        event_id = None
        if setup is not None:
            setup_row = require(db, setup, "setup")
            signal = setup_row["payload"]
            if setup_row["parent"] != oid or signal["protocol_id"] != pid or not signal["event_id"] or signal["state"] not in ("confirmed", "active"):
                raise ValueError("paper setup must be a confirmed event from this observation")
            event_id = signal["event_id"]
            after = max(after, utc(signal["observed_at"]))
            historical_input |= signal["evidence_class"] != "forward"
        if not after <= decision_at <= recorded:
            raise ValueError("paper decision predates its evidence or lies in the future")
        earliest = _next_open(decision_at)
        if execution_basis == "time_stamped":
            day = local_day(decision_at)
            if is_session_day(day) and session_open_utc(day) <= decision_at < session_close_utc(day):
                earliest = decision_at
        reason = text(data.get("reason"), "cash or execution reason") if status != "planned" else None
        ref = event_id or oid
        key = evidence_id("paper", pid, ref, basis, rule)
        existing = lookup(db, key)
        first_recorded = utc(existing["recorded_at"]) if existing else recorded
        evidence_class = existing["payload"]["evidence_class"] if existing else _evidence_class(
            protocol, snapshot, ready_at, decision_at, first_recorded,
        )
        late_open_plan = execution_basis == "next_open" and first_recorded >= earliest
        if (historical_input or late_open_plan) and evidence_class == "forward":
            evidence_class = "backfill"
        append(db, key, "paper", oid, {
            "protocol_id": pid, "snapshot_id": snapshot["id"], "review_id": reviewed, "setup_id": setup,
            "event_id": event_id, "path": basis, "rule_version": rule,
            "status": status, "reason": reason, "evidence_class": evidence_class,
            "decision_at": decision_at.isoformat(), "execution_basis": execution_basis,
            "earliest_execution_at": earliest.isoformat(), "start_session": local_day(earliest).isoformat(),
            "fee_bps_per_side": protocol["payload"]["fee_bps_per_side"],
        }, recorded)
    return key


def record_fill(ledger: Ledger, data: dict, *, now: datetime | None = None) -> str:
    recorded = utc(now or datetime.now(timezone.utc))
    pid, status = data["paper_id"], data["status"]
    key = evidence_id("paper_fill", pid)
    with ledger.transaction() as db:
        plan = require(db, pid, "paper")
        path = plan["payload"]
        if path["status"] != "planned" or status not in ("entered", "unexecutable"):
            raise ValueError("only a planned path may record an entry or failed execution")
        earliest = utc(path["earliest_execution_at"])
        if status == "entered":
            entry = utc(data["entry_at"])
            if not earliest <= entry <= recorded or (
                path["execution_basis"] == "next_open" and entry != earliest
            ) or (path["execution_basis"] == "time_stamped" and entry <= utc(path["decision_at"])):
                raise ValueError("entry precedes the executable window or is not the declared open")
            payload = {
                "status": status, "start_session": _session_at(entry).isoformat(), "entry_at": entry.isoformat(),
                "entry_price": number(data["entry_price"], "entry_price", minimum=1e-12),
                "entry_source": text(data["entry_source"], "entry price source"),
                "price_basis": text(data["price_basis"], "price_basis"),
                "evidence_class": (
                    path["evidence_class"] if path["execution_basis"] == "next_open" and utc(plan["recorded_at"]) < entry
                    else "backfill"
                ),
            }
        else:
            observed = utc(data["observed_at"])
            if not earliest <= observed <= recorded:
                raise ValueError("execution failure falls outside the observation window")
            payload = {"status": status, "reason": text(data["reason"], "execution reason"),
                       "observed_at": observed.isoformat(), "start_session": path["start_session"]}
        append(db, key, "paper_fill", pid, payload, recorded)
    return key


def record_outcome(ledger: Ledger, data: dict, *, now: datetime | None = None) -> str:
    recorded = utc(now or datetime.now(timezone.utc))
    pid, horizon = data["paper_id"], data["horizon"]
    asof = utc(data["asof"])
    revision = text(data.get("revision", "original"), "outcome revision")
    supersedes = data.get("supersedes")
    key = evidence_id("outcome", pid, horizon, revision)
    request = evidence_id("settlement_input", {**data, "asof": asof.isoformat()})
    with ledger.transaction() as db:
        existing = lookup(db, key)
        if existing and "request_id" in existing["payload"]:
            if request != existing["payload"]["request_id"]:
                raise ValueError("conflicting immutable outcome revision")
            return key
        path = require(db, pid, "paper")["payload"].copy()
        fill = lookup(db, evidence_id("paper_fill", pid))
        evidence_at = utc(existing["recorded_at"]) if existing else recorded
        if fill is not None and utc(fill["recorded_at"]) <= evidence_at:
            path.update(fill["payload"])
        protocol = require(db, path["protocol_id"], "protocol")["payload"]
        if type(horizon) is not int or horizon not in protocol["horizons"]:
            raise ValueError("horizon is outside the frozen protocol")
        terminal = _maturity(date.fromisoformat(path["start_session"]), horizon)
        if not terminal <= asof <= recorded:
            raise ValueError("outcome is not mature or uses a future cutoff")
        previous = [item for item in entries(db, "outcome", parent=pid) if item["payload"]["horizon"] == horizon]
        if existing is None and supersedes != (previous[-1]["id"] if previous else None):
            raise ValueError("a correction must supersede the latest outcome for this horizon")
        gross = net = exit_at = exit_price = source = reason = None
        continuity = "not_applicable"
        evidence_class = path["evidence_class"]
        if path["status"] == "cash":
            status, gross, net = "mature", 0.0, 0.0
        elif path["status"] == "unexecutable":
            status, reason = "mature_missing", path["reason"]
        elif path["status"] == "planned":
            status, reason = "mature_missing", text(data.get("missing_reason"), "missing entry evidence reason")
        else:
            continuity = data.get("equity_continuity", "unknown")
            if continuity not in ("verified", "unknown", "broken"):
                raise ValueError("invalid equity continuity")
            status = "mature_missing"
            if data.get("exit_price") is not None:
                exit_price = number(data["exit_price"], "exit_price", minimum=1e-12)
                exit_at = utc(data["exit_at"])
                _session_at(exit_at)
                if not utc(path["entry_at"]) <= exit_at <= terminal:
                    raise ValueError("exit falls outside the observed holding path")
                source = text(data["exit_source"], "exit price source")
                if exit_at < terminal:
                    reason = text(data["exit_reason"], "early exit reason")
                    commitment = lookup(db, evidence_id("paper_exit", pid))
                    if (
                        commitment is None or utc(commitment["recorded_at"]) > evidence_at
                        or commitment["payload"]["execute_at"] != exit_at.isoformat()
                        or data.get("exit_id") != commitment["id"]
                    ):
                        evidence_class = "backfill"
                if continuity == "verified" and data.get("price_basis") == path["price_basis"]:
                    status = "mature"
                    gross = exit_price / path["entry_price"] - 1
                    net = gross - 2 * path["fee_bps_per_side"] / 10_000
            if status == "mature_missing":
                reason = text(data["missing_reason"], "mature missing evidence reason")
        if supersedes is not None:
            text(data.get("revision_reason"), "revision reason")
        payload = {
            "horizon": horizon, "maturity_at": terminal.isoformat(), "asof": asof.isoformat(),
            "status": status, "equity_continuity": continuity, "price_basis": data.get("price_basis"),
            "exit_price": exit_price, "exit_source": source, "exit_at": exit_at.isoformat() if exit_at else None,
            "gross_return": gross, "net_return": net, "reason": reason,
            "revision": revision, "revision_reason": data.get("revision_reason"), "supersedes": supersedes,
        }
        if not existing:
            payload.update(request_id=request, evidence_class=evidence_class)
        append(db, key, "outcome", pid, payload, recorded)
    return key


def record_exit(ledger: Ledger, data: dict, *, now: datetime | None = None) -> str:
    """Freeze a discretionary next-open exit before its price can be observed."""
    recorded = utc(now or datetime.now(timezone.utc))
    pid = data["paper_id"]
    decided = utc(data["decided_at"])
    execution = _next_open(decided)
    key = evidence_id("paper_exit", pid)
    payload = {"decided_at": decided.isoformat(), "execute_at": execution.isoformat(),
               "reason": text(data["reason"], "exit decision reason")}
    with ledger.transaction() as db:
        existing = lookup(db, key)
        if existing is None:
            fill = require(db, evidence_id("paper_fill", pid), "paper_fill")
            if fill["payload"]["status"] != "entered" or not (
                max(utc(fill["recorded_at"]), utc(fill["payload"]["entry_at"])) <= decided <= recorded < execution
                and local_day(recorded) == local_day(decided)
            ):
                raise ValueError("exit must be recorded after entry and before the predetermined next open")
        append(db, key, "paper_exit", pid, payload, recorded)
    return key


def study_summary(ledger: Ledger, protocol_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Report coverage and maturity without treating absent evidence as zero."""
    from pandas import DataFrame
    from ai_value_scanner.research.review_utility import AttentionObservation, attention_utility

    now = utc(now or datetime.now(timezone.utc))
    with ledger.transaction() as db:
        protocol = require(db, protocol_id, "protocol")
        enrolled = utc(protocol["recorded_at"])
        if enrolled > now:
            raise ValueError("summary cutoff predates the frozen protocol")
        spec = protocol["payload"]
        def known(kind):
            return [row for row in entries(db, kind) if utc(row["recorded_at"]) <= now]

        snapshots = {
            row["id"]: row for row in known("snapshot")
            if _matches_protocol(spec, row["payload"])
        }
        observations = {
            row["id"]: row for row in known("observation") if row["parent"] in snapshots
        }
        reviews = [row for row in known("review") if row["payload"]["protocol_id"] == protocol_id]
        receipts = [row for row in known("receipt") if row["payload"]["style"] == spec["style"]]
        setups = [row for row in known("setup") if row["payload"]["protocol_id"] == protocol_id]
        paper = [row for row in known("paper") if row["payload"]["protocol_id"] == protocol_id]
        fills = {row["parent"]: row["payload"] for row in known("paper_fill")}
        outcomes = {(row["parent"], row["payload"]["horizon"]): row["payload"] for row in known("outcome")}
        by_snapshot = defaultdict(dict)
        for row in observations.values():
            by_snapshot[row["parent"]][row["payload"]["symbol"]] = row["payload"]["action"]
        forward = {
            sid for sid, row in snapshots.items()
            if row["payload"].get("decision_bytes_pinned")
            and (publication := readable_at(db, sid, asof=now)) is not None and enrolled <= publication
        }

    utility = defaultdict(dict)
    for surface in ("daily", "weekly"):
        attention = [
            AttentionObservation(row["payload"]["session"], tuple(row["payload"][surface]), by_snapshot[sid])
            for sid, row in snapshots.items() if sid in forward
        ]
        for workflow in ("baseline", "new"):
            log = []
            for row in reviews:
                fields = row["payload"]
                if (fields["surface"], fields["workflow"], fields["evidence_class"]) != (surface, workflow, "forward") or fields["snapshot_id"] not in forward:
                    continue
                obs = observations[row["parent"]]["payload"]
                log.append({
                    "decision_date": obs["session"], "symbol": obs["symbol"],
                    "review_status": {"deep_dive": "follow_up", "wait": "reviewed", "reject": "rejected"}[fields["choice"]],
                    "review_minutes": fields["review_minutes"], "rejection_reason": fields["reason"],
                })
            events, weeks, _ = attention_utility(attention, DataFrame(log))
            slots = len(events)
            utility[surface][workflow] = {
                "slots": slots, "reviewed": len(log), "unreviewed": slots - len(log),
                "coverage": len(log) / slots if slots else None,
                "utility_status": "observed" if log else "undetermined",
                "weekly": weeks.astype(object).where(weeks.notna(), None).to_dict("records"),
            }
    groups = defaultdict(dict)
    for row in reviews:
        item = row["payload"]
        if item["pair_id"] and item["evidence_class"] == "forward" and item["snapshot_id"] in forward:
            groups[item["pair_id"]][item["workflow"]] = item
    pairs = []
    for pair_id, pair in groups.items():
        if set(pair) == {"baseline", "new"}:
            old, new = pair["baseline"], pair["new"]
            pairs.append({
                "pair_id": pair_id, "review_minutes_delta": new["review_minutes"] - old["review_minutes"],
                "deep_dive_delta": int(new["choice"] == "deep_dive") - int(old["choice"] == "deep_dive"),
                "risk_identification_delta": len(new["risk_codes"]) - len(old["risk_codes"]),
            })
    maturity = Counter()
    for row in paper:
        path = {**row["payload"], **fills.get(row["id"], {})}
        for horizon in spec["horizons"]:
            outcome = outcomes.get((row["id"], horizon))
            terminal = _maturity(date.fromisoformat(path["start_session"]), horizon)
            if terminal > now:
                status = "unmatured"
            else:
                status = outcome["status"] if outcome and utc(outcome["asof"]) <= now else "mature_missing"
            evidence = path["evidence_class"]
            if evidence == "forward" and (path["snapshot_id"] not in forward or path["execution_basis"] == "time_stamped" and path["status"] == "entered"):
                evidence = "backfill"
            if status == "mature" and outcome and (
                outcome.get("evidence_class") == "backfill" or (
                    "evidence_class" not in outcome and outcome["exit_at"] and utc(outcome["exit_at"]) < terminal
                )
            ):
                evidence = "backfill"
            maturity[(evidence, path["path"], horizon, status)] += 1
    by_session = defaultdict(list)
    for row in receipts:
        by_session[row["payload"]["session"]].append(row)
    publications = []
    day = local_day(enrolled)
    last, _ = sip_publication_window(now)
    while day <= last:
        if is_session_day(day) and enrolled <= (available := session_close_utc(day) + SIP_PUBLICATION_DELAY) <= now:
            attempts = by_session[day.isoformat()]
            scoped = [row for row in attempts if row["parent"] in snapshots]
            successes = [row for row in scoped if row["payload"]["status"] in ("published", "reused")]
            status = "missing_receipt"
            if successes:
                if any(row["parent"] in forward for row in successes):
                    status = "published"
                else:
                    status = "publication_time_unknown" if not any(row["payload"]["first_readable_at_utc"] for row in successes) else "outside_forward_cohort"
            other_versions = sum(row["parent"] is not None and row["parent"] not in snapshots for row in attempts)
            publications.append({"session": day.isoformat(), "status": status, "attempts": len(scoped),
                                 "other_versions": other_versions,
                                 "unlinked_attempts": sum(row["parent"] is None for row in attempts)})
        day += timedelta(days=1)
    setup_episodes = {}
    seen = {row["id"]: row["payload"]["observed_at"] for row in setups}
    for row in setups:
        item = row["payload"]
        if (interrupted := item.get("interrupted_event_id")) in setup_episodes:
            setup_episodes[interrupted]["latest_state"] = "continuity_unknown"
        if (event := item["event_id"]) is None:
            continue
        episode = setup_episodes.setdefault(event, {
            "event_id": event, "setup_version": item["setup_version"],
            "first_confirmed_session": item["first_confirmed_session"],
            "first_seen_at": seen.get(item["watch_id"], item["observed_at"]),
        })
        episode.update(latest_seen_at=item["observed_at"], latest_state=item["state"])
    return {
        "protocol_id": protocol_id, "snapshots": len(snapshots), "eligible_forward_snapshots": len(forward),
        "formal_attempts": dict(Counter(row["payload"]["status"] for row in receipts if row["parent"] in snapshots)),
        "other_version_attempts": dict(Counter(row["payload"]["status"] for row in receipts if row["parent"] is not None and row["parent"] not in snapshots)),
        "unlinked_attempts": dict(Counter(row["payload"]["status"] for row in receipts if row["parent"] is None)),
        "sessions": publications,
        "reviews_by_evidence": dict(Counter(row["payload"]["evidence_class"] for row in reviews)),
        "review_utility": utility["daily"],
        "weekly_review_utility": utility["weekly"],
        "matched_pairs": pairs, "matched_utility_status": "observed" if pairs else "undetermined",
        "confirmed_events": len(setup_episodes), "setup_episodes": list(setup_episodes.values()),
        "paper_maturity": [
            {"evidence_class": evidence, "path": path, "horizon": horizon, "status": status, "count": count}
            for (evidence, path, horizon, status), count in sorted(maturity.items())
        ],
    }
