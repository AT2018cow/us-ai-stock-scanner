"""Offline acceptance probes. Run from the repository with its Python environment."""
import argparse
from collections import Counter
from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from test_forward_observations import at, build_archive
from test_swing_experiment import ORIGIN, _cohort, frame, row
from ai_value_scanner.decision.review import build_ready_ages
from ai_value_scanner.forward.ledger import Ledger, evidence_id
from ai_value_scanner.forward.study import (
    freeze_protocol, record_exit, record_fill, record_outcome, record_paper, record_review, study_summary,
)
from ai_value_scanner.market_calendar import session_close_utc
from ai_value_scanner.reporting.publication import latest_list_status
from ai_value_scanner.reporting.snapshot import REPORT_RENDERER_REVISION, load_snapshot_decisions
from ai_value_scanner.research.swing_cohorts import day_shift, sessions, sha
from ai_value_scanner.research.swing_experiment import _medium_paths, evaluate
from ai_value_scanner.research.swing_paths import PriceBook
from ai_value_scanner.scanner import write_latest_decision_pointer


def publication_and_exit(tmp):
    root = tmp / "decisions"
    day = "2025-11-03"
    _, receipt = build_archive(root, day)
    pointer = write_latest_decision_pointer(root, decision_date=day, strategy_style="production")
    data = json.loads(pointer.read_bytes())
    read_at = at(day, "22:20")
    statuses = {}
    for first in ("22:01", "23:00"):
        data["first_readable_at_utc"] = at(day, first).isoformat()
        pointer.write_text(json.dumps(data))
        statuses[first] = latest_list_status(root, "production", read_at)["status"]

    ledger = Ledger(tmp / "paper.db", snapshot_root=root)
    protocol = freeze_protocol(ledger, {
        "version": "acceptance", "style": "production", "decision_policy": "v1",
        "report_renderer": REPORT_RENDERER_REVISION, "config_fingerprint": "config-fixture",
        "description": "isolated simulation", "horizons": [2], "fee_bps_per_side": 15,
        "paper_rules": ["manual-next-open"],
    }, now=at("2025-10-31", "22:00"))
    ledger.import_attempt(receipt, now=read_at)
    snapshot = ledger.records("snapshot")[0]["id"]
    obs = evidence_id("observation", snapshot, "AAA")
    review = record_review(ledger, {
        "protocol_id": protocol, "observation_id": obs, "workflow": "new", "surface": "daily",
        "choice": "deep_dive", "reason": "fixture", "budget_minutes": 5, "review_minutes": 2,
        "displayed_at": at(day, "22:03"), "read_at": at(day, "22:05"), "decided_at": at(day, "22:08"),
    }, now=read_at)
    paper = record_paper(ledger, {
        "protocol_id": protocol, "observation_id": obs, "path": "manual", "review_id": review,
        "rule_version": "manual-next-open", "status": "planned", "decision_at": read_at,
    }, now=read_at)
    enter = at("2025-11-04", "14:30")
    record_fill(ledger, dict(paper_id=paper, status="entered", entry_at=enter, entry_price=100,
                             entry_source="fixture SIP open", price_basis="same shares"), now=enter)
    decided = at("2025-11-04", "21:10")
    commitment = record_exit(ledger, dict(paper_id=paper, decided_at=decided, reason="structure broke"), now=decided)
    terminal = at("2025-11-05", "21:00")
    settlement = dict(paper_id=paper, horizon=2, asof=terminal.isoformat(), exit_at=terminal.isoformat(),
                      exit_source="fixture SIP close", exit_price=110, price_basis="same shares",
                      equity_continuity="verified")
    original = record_outcome(ledger, settlement, now=terminal)
    result = ledger.records("outcome")[0]["payload"]
    maturity = study_summary(ledger, protocol, now=terminal)["paper_maturity"]
    opening = ledger.records("paper_exit")[0]["payload"]["execute_at"]
    record_outcome(ledger, dict(settlement, exit_id=commitment, exit_at=opening, exit_price=92,
                               exit_source="fixture SIP open", exit_reason="structure broke",
                               supersedes=original, revision="corrected", revision_reason="honor committed exit"),
                   now=terminal + timedelta(minutes=1))
    corrected = ledger.records("outcome")[-1]["payload"]
    return {"read_at": read_at.isoformat(), "publication_status_by_first_readable_utc": statuses,
            "committed_execution": opening, "net_on_committed_exit_revision": round(corrected["net_return"], 6),
            "committed_open_price_in_scenario": 92, "expected_net_if_honored": round(92 / 100 - 1 - .003, 6),
            "accepted_exit_at": result["exit_at"], "accepted_net": round(result["net_return"], 6),
            "maturity_before_correction": maturity}


def quote_labels(security, days, prices, *, events=None):
    return {"security_id": security, "verified_from": str(days[0]), "verified_through": str(days[-1]),
            "identity_source": "fixture identity", "corporate_actions_source": "fixture inventory",
            "splits": [], "distributions": [], "events": events or {},
            "bars": [dict(session=str(day), o=opening, c=close, h=max(opening, close), l=min(opening, close))
                     for day, (opening, close) in prices.items()]}


def labels(through, securities):
    return {"feed": "sip", "price_basis": "raw", "source": "engineered acceptance fixture",
            "asof_utc": (session_close_utc(through) + timedelta(hours=1)).isoformat(), "securities": securities}


def benchmark_comparison():
    rows = [row(ORIGIN, f"A{i}", i, priority=i) for i in range(1, 16)]
    cohort = _cohort({str(ORIGIN): frame(ORIGIN, rows)})
    days = sessions(day_shift(ORIGIN, 1), day_shift(ORIGIN, 60))
    securities = {r["security_id"]: quote_labels(
        r["security_id"], days, {d: (100, 100) for d in days[1:]}, events={str(days[0]): "suspended"}
    ) for r in rows}
    qqq = "QQQ:0001067839"
    securities[qqq] = quote_labels(qqq, days, {d: (100 if d == days[0] else 110, 110) for d in days})
    output = evaluate(cohort, labels(days[-1], securities), cohort_sha256=sha(cohort))
    result = next(r for r in output["ranking_paths"] if r["horizon"] == 10)
    portfolios = result["portfolios"]
    return {"planned": str(days[0]), "all_stock_entries": sorted({r["path"]["entry_session"] for r in result["stock_paths"]}),
            "filled_seats": len(result["stock_paths"]), "top15_net": round(portfolios["top15"]["net_15"], 6),
            "full_qqq_net": round(portfolios["qqq_full"]["net_15"], 6),
            "reported_equal_deployment_net": round(portfolios["qqq_equal_deployed"]["net_15"], 6),
            "expected_equal_deployment_net": round(110 / 110 - 1 - .003, 6)}


def weekly_continuity():
    signal = date(2025, 11, 7)  # Friday, following a weak October 31 weekly close.
    end = day_shift(signal, 60)
    days = sessions(date(2025, 8, 1), end)
    security = "AAA:0000000001"
    prices = {day: (80, 80) if day == date(2025, 10, 31) else (100, 100) for day in days}
    prices[days[days.index(signal) + 1]] = (100, 95)
    book = PriceBook(labels(end, {security: quote_labels(security, days, prices)}))
    target = {"security_id": security, "cik": "0000000001", "industry": "35"}
    one = {"target": target, "peer": None, "session": str(signal), "short_confirmed": True, "below_sma10": False,
           "short_stop": 98, "available": (session_close_utc(signal) + timedelta(minutes=30)).isoformat()}
    paths, _ = _medium_paths(book, [one], [])
    result = next(r for r in paths if r["horizon"] == 60)
    # Independent grouping by ISO week, excluding an unfinished terminal week.
    weekly = {}
    for day in days:
        weekly[day.isocalendar()[:2]] = (day, prices[day][1])
    closes = list(weekly.values())
    margins = []
    for i, (day, close) in enumerate(closes):
        if day >= signal and day_shift(day, 1).isocalendar()[:2] != day.isocalendar()[:2]:
            margins.append(close - sum(v for _, v in closes[i-9:i+1]) / 10)
    return {"signal": str(signal), "terminal": str(end), "observed_short_break": result["short_break"],
            "completed_weeks_from_signal": len(margins), "smallest_close_minus_sma10": min(margins),
            "expected_held": min(margins) >= 0, "reported_held": result["medium_trend_held"]}


def archive_check(root, tmp):
    dates = ("2026-11-23", "2026-11-20", "2026-11-19", "2026-11-18", "2026-11-17", "2026-11-16")
    archives = [root / day / "production" for day in dates]
    groups = [load_snapshot_decisions(directory) for directory in archives]
    prior = [{d.symbol: d for d in group} for group in groups[1:]]
    computed = build_ready_ages(groups[0], zip(dates[1:], prior))
    independent = Counter()
    for d in groups[0]:
        if d.entry.state.value == "ENTRY_READY":
            streak = 1
            for session, rows in zip(dates[1:], prior):
                old = rows.get(d.symbol)
                if (not old or old.provenance["cik"] != d.provenance["cik"]
                    or old.entry.market_asof != session or old.entry.state.value != "ENTRY_READY"):
                    break
                streak += 1
            independent[min(streak, 3)] += 1
    ledger = Ledger(tmp / "archive.db", snapshot_root=root)
    first = ledger.import_archive(archives[0])
    second = ledger.import_archive(archives[0])
    observations = [r["payload"] for r in ledger.records("observation", parent=first)]
    return {"days_latest_first": dates, "ready_duration_capped_at_3_reference": dict(independent),
            "ready_duration_capped_at_3_implementation": dict(Counter(min(3, v.sessions) for v in computed.values() if v.sessions)),
            "ready_start_evidence_in_six_sessions": dict(Counter(v.reason for v in computed.values() if v.sessions)),
            "manifest_sha256": [sha256((d / "run_manifest.json").read_bytes()).hexdigest() for d in archives],
            "decisions_sha256": [sha256((d / "decisions.jsonl").read_bytes()).hexdigest() for d in archives],
            "ledger_retry_same_id": first == second, "observations": len(observations),
            "daily_ranked": sum(d["daily_rank"] is not None for d in observations),
            "weekly_ranked": sum(d["weekly_rank"] is not None for d in observations),
            "DIS_s2_reason": next(d["s2_reason"] for d in observations if d["symbol"] == "DIS"),
            "formal_receipts_imported": len(ledger.records("receipt"))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="local root with production snapshots for Nov 16–23, 2026")
    args = parser.parse_args()
    with TemporaryDirectory() as temporary:
        tmp = Path(temporary)
        report = {"publication_and_exit": publication_and_exit(tmp), "qqq": benchmark_comparison(),
                  "weekly_continuity": weekly_continuity()}
        if args.archive:
            report["archive"] = archive_check(args.archive, tmp)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
