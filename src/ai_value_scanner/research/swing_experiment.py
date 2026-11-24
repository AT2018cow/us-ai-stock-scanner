"""Join frozen cohorts to labels and report waiting, exits and selection as paper evidence."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any

from ai_value_scanner.forward.ledger import utc
from ai_value_scanner.market_calendar import session_close_utc
from ai_value_scanner.swing.setups import BREAKOUT_VERSION, next_session
from .swing_cohorts import (
    CAP, DELAYS, HORIZONS, PRIMARY, PROTOCOL, VERSION, WAIT, day_shift, execution_day,
    require_implementation, sessions, sha,
)
from .swing_paths import PriceBook, barrier_order, cash, false_breakout, settle
from .swing_statistics import distribution, summarize

QQQ = "QQQ:0001067839"


def _miss(status):
    return {"status": status, "net_15": None, "net_30": None}


def _exposure(path):
    if path.get("entry_session") and path.get("exit_session"):
        return [path["entry_session"], path["exit_session"]]
    return path.get("exposure_window")


def _joint_exposure(paths):
    windows = [value for path in paths if (value := _exposure(path)) is not None]
    return [min(window[0] for window in windows), max(window[1] for window in windows)] if windows else None


def _signed_contribution(candidate, baseline):
    issuers = candidate.keys() | baseline.keys()
    return {key: candidate.get(key, 0.) - baseline.get(key, 0.) for key in sorted(issuers)}


def _single_contribution(issuer, path):
    value = path.get("net_15")
    return {issuer: value} if issuer and value is not None else {}


def _pair(family, horizon, row, candidate, baseline, *, counterpart=None, **more):
    target = row.get("target", row)
    candidate_cik = target.get("cik")
    baseline_cik = counterpart.get("cik") if counterpart is not None else candidate_cik
    return {
        "family": family, "horizon": horizon, "session": row["session"], "available": row["available"],
        "event_id": row.get("event_id") or row.get("id") or target["security_id"],
        "security_id": target["security_id"], "issuer_keys": sorted({
            key for key in (target.get("cik"), (counterpart or {}).get("cik")) if key
        }),
        "industry": target.get("industry"), "regime": target.get("regime"),
        "issuer_attribution_net_15": _signed_contribution(
            _single_contribution(candidate_cik, candidate), _single_contribution(baseline_cik, baseline)),
        "exposure_window": _joint_exposure((candidate, baseline)),
        "candidate": candidate, "baseline": baseline, **more,
    }


def _false_breakout_window(book, security, signal, anchor):
    through = day_shift(signal, 5)
    observation = false_breakout(book, security, signal, through, anchor)
    mature = session_close_utc(through) <= book.at
    if not mature:
        observation = ({"status": "early_breach", "session": observation["session"]} if observation["status"] == "breached"
                       else {"status": "future_unmatured", "observed_status": observation["status"]})
    return {**observation, "through": through.isoformat(), "window_mature": mature}


def _episode_paths(book, row, out):
    security = row["security_id"]
    planned = execution_day(row["available"])
    confirmed = row["status"] == "confirmed"
    signal = date.fromisoformat(row["resolution_session"]) if confirmed else None
    available = execution_day(row["confirmation_available"]) if confirmed else None
    locked = row.get("level")
    diagnostics = {}
    for horizon in HORIZONS:
        terminal = day_shift(planned, horizon - 1)
        immediate = settle(book, security, planned, terminal)
        if confirmed:
            waited = settle(book, security, available, terminal, signal=signal, locked=locked, avoid_invalidated=True)
        elif row["status"] == "waiting":
            waited = _miss("future_unmatured")
        elif row["status"] in ("expired", "failed"):
            waited = cash(book, terminal, row["status"])
        else:
            waited = _miss("signal_continuity_unknown")
        out.append(_pair("wait_vs_immediate", horizon, row, waited, immediate, observation_outcome=row["status"],
                         immediate_opportunity_cost=immediate["net_15"] if waited["status"] == "cash" else None))
        if not confirmed:
            continue
        stop_terminal = day_shift(available, horizon + WAIT - 1)
        options = {"signal": signal, "locked": locked, "avoid_invalidated": True,
                   "fixed_horizon": horizon, "open_deadline": day_shift(available, WAIT)}
        fixed = settle(book, security, available, stop_terminal, **options)
        early = settle(book, security, available, stop_terminal, exit_on_break=True, **options)
        trigger_row = {**row, "session": row["resolution_session"], "available": row["confirmation_available"]}
        diag = None
        if row.get("resistance") and fixed.get("entry_session") and fixed["status"] == "settled":
            diag = barrier_order(book, security, signal, date.fromisoformat(fixed["entry_session"]),
                                 date.fromisoformat(fixed["exit_session"]), locked, row["resistance"])
        same_fill = (fixed.get("entry_session") is not None and
                     all(fixed.get(key) == early.get(key) for key in ("entry_session", "price_denominator", "shares_at_entry")))
        out.append(_pair("structure_exit_vs_fixed", horizon, trigger_row, early, fixed,
                         barrier_diagnostic=diag, comparison_eligible=same_fill))
        # Hold the same number of sessions from each actual entry, and also
        # report the delay's economic cost on the primary confirmation clock.
        fixed_end = date.fromisoformat(fixed["terminal_session"])
        for delay in DELAYS:
            start = day_shift(available, delay)
            delayed = settle(book, security, start, fixed_end, signal=signal, locked=locked, avoid_invalidated=True)
            out.append(_pair(f"delay_{delay}_common_end", horizon, trigger_row, delayed, fixed))
            own = settle(book, security, start, day_shift(start, horizon + WAIT - 1),
                         **{**options, "open_deadline": day_shift(start, WAIT)})
            out.append(_pair(f"delay_{delay}_equal_hold", horizon, trigger_row, own, fixed))
        if horizon == PRIMARY:
            immediate_hold = settle(book, security, planned, day_shift(planned, horizon + WAIT - 1),
                                    fixed_horizon=horizon, open_deadline=day_shift(planned, WAIT))
            out.append(_pair("wait_vs_immediate_equal_hold", horizon, row, fixed, immediate_hold))
            diagnostics["confirmation_close_break_5"] = _false_breakout_window(book, security, signal, locked)
    return diagnostics


def _confirmation_paths(book, row, out):
    planned = execution_day(row["available"])
    for horizon in HORIZONS:
        terminal = day_shift(planned, horizon - 1)
        result = settle(book, row["target"]["security_id"], planned, terminal)
        for key in ("peer", "random"):
            match = row[key]
            control = settle(book, match["security_id"], planned, terminal) if match else _miss("no_eligible_match")
            out.append(_pair("confirmation_vs_matched" if key == "peer" else "confirmation_vs_seeded_random",
                             horizon, row, result, control, counterpart=match))


def _portfolio(members, legs, denom, *, mature):
    ret = {name: 0. for name in ("net_15", "net_30")}
    missing, contributions, issuers = Counter(), defaultdict(float), defaultdict(float)
    deployed = 0
    for member in members:
        result = legs[member["security_id"]]
        if result["status"] == "settled":
            deployed += 1
        if result["net_15"] is None:
            missing[result["status"]] += 1
            continue
        for name in ret:
            ret[name] += result[name] / denom
        contributions[member.get("industry") or "unknown"] += result["net_15"] / denom
        if member["cik"]:
            issuers[member["cik"]] += result["net_15"] / denom
    shared = {"nominated": len(members), "deployment_weight": None if missing else deployed / denom,
              "cash_weight": None if missing else 1 - deployed / denom, "missing_statuses": dict(missing),
              "industry_contributions_net_15": dict(contributions),
              "issuer_contributions_net_15": dict(issuers),
              "exposure_window": None if missing else _joint_exposure(legs[member["security_id"]] for member in members)}
    if missing or not mature:
        return _miss("future_unmatured" if not mature or "future_unmatured" in missing else "incomplete_portfolio") | shared
    return {"status": "settled" if deployed else "cash", **shared, **ret}


def _ranking_paths(book, rows, out):
    raw = []
    compare = {"entry": "quality", "priority": "entry", "top15": "priority", "daily_s2": "top15",
               "financial_candidate": "top15", "random_k": "top15", "top_equal_k": "rank16_30",
               "qqq_equal_deployed": "top15", "qqq_full": "top15"}
    for frame in rows:
        day = frame["session"]
        group = frame["groups"]
        group = {**group, "top_equal_k": group["top15"][:len(group["rank16_30"])]}
        members = {item["security_id"]: item for pool in group.values() for item in pool}
        planned = execution_day(frame["available"])
        for horizon in HORIZONS:
            terminal = day_shift(planned, horizon - 1)
            legs = {key: settle(book, key, planned, terminal) if key else _miss("identity_unverified") for key in members}
            portfolios = {name: _portfolio(pool, legs, max(CAP, len(pool)), mature=session_close_utc(terminal) <= book.at)
                          for name, pool in group.items()}
            market = settle(book, QQQ, planned, terminal)
            portfolios["qqq_full"] = {**market, "issuer_contributions_net_15": _single_contribution(QQQ.split(":")[1], market)}
            share = portfolios["top15"]["deployment_weight"]
            if share is None:
                portfolios["qqq_equal_deployed"] = _miss("future_unmatured" if portfolios["top15"]["status"] ==
                                                         "future_unmatured" else "unknown_deployment")
            elif share == 0:
                portfolios["qqq_equal_deployed"] = cash(book, terminal, "no_stock_deployment")
            elif market["net_15"] is None:
                portfolios["qqq_equal_deployed"] = market
            else:
                portfolios["qqq_equal_deployed"] = {
                    **market, "deployment_weight": share, "cash_weight": 1 - share,
                    "net_15": market["net_15"] * share, "net_30": market["net_30"] * share,
                    "issuer_contributions_net_15": {QQQ.split(":")[1]: market["net_15"] * share},
                }
            raw.append({"session": day, "horizon": horizon, "available": frame["available"], "stock_paths": [
                {"member": members[key], "path": result} for key, result in legs.items()],
                "portfolios": portfolios, "financial_additions": frame["financial_additions"],
                "financial_removals": frame["financial_removals"], "daily_stability_policy": frame["daily_stability_policy"],
                "s2_grace_members": group["daily_grace"]})
            for candidate, baseline in compare.items():
                a, b = portfolios[candidate], portfolios[baseline]
                base = group.get(baseline, [])
                portfolio = group.get(candidate, [])
                if candidate == "top_equal_k" and not base:
                    continue
                swaps = sorted(set(frame["financial_additions"] + frame["financial_removals"]))
                issuers = (set(key.split(":")[-1] for key in swaps if key) if candidate == "financial_candidate"
                           else {item["cik"] for item in portfolio + base if item["cik"]})
                unchanged = (candidate == "financial_candidate" and
                             Counter(item["security_id"] for item in portfolio) == Counter(item["security_id"] for item in base))
                if candidate in ("qqq_full", "qqq_equal_deployed") and a.get("status") == "settled":
                    issuers.add(QQQ.split(":")[1])
                attribution = ({} if unchanged else _signed_contribution(
                    a.get("issuer_contributions_net_15", {}), b.get("issuer_contributions_net_15", {})))
                out.append({"family": f"{candidate}_vs_{baseline}", "session": day, "available": frame["available"],
                            "horizon": horizon, "event_id": day, "issuer_keys": sorted(issuers),
                            "issuer_attribution_net_15": attribution,
                            "exposure_window": _joint_exposure((a, b)),
                            "known_zero_delta": unchanged and session_close_utc(terminal) <= book.at,
                            "regime": frame.get("regime"), "candidate": a, "baseline": b,
                            "membership_changed": bool(swaps) if candidate == "financial_candidate" else None})
    return raw


def _holds_medium(book, security, signal, terminal):
    """Diagnostic only. Reconstruct ten finished trading weeks at each weekly close."""
    starting = signal - timedelta(days=84)
    # Start on a known NYSE session, even across holidays.
    days = sessions(next_session(starting), terminal)
    week_ends = []
    for i, day in enumerate(days):
        if next_session(day).isocalendar()[:2] != day.isocalendar()[:2]:
            week_ends.append((i, day))
    valid = [(i, day) for i, day in week_ends if day >= signal and i > 0]
    prior = [(i, day) for i, day in week_ends if day < signal]
    if prior:
        valid.insert(0, prior[-1])
    if not valid:
        return None
    lookup = [day for _, day in week_ends]
    for index, day in valid:
        n = lookup.index(day)
        if n < 9:
            return None
        start = lookup[n - 9]
        factor = book.factor(security, start, day)
        if factor is None or any(book.observation(security, k)[0] != "observed" for k in sessions(start, day)):
            return None
        closes = [book.observation(security, k)[1][3] * book.factor(security, k, day) for k in lookup[n-9:n+1]]
        if closes[-1] < mean(closes):
            return False
    return True


def _medium_paths(book, rows, out):
    raw = []
    groups = defaultdict(list)
    for row in rows:
        target = row["target"]["security_id"]
        signal = date.fromisoformat(row["session"])
        planned = execution_day(row["available"])
        name = ("short_confirmed" if row["short_confirmed"] else "short_not_confirmed") + (
            "_below_10w" if row["below_sma10"] else "_at_or_above_10w")
        for horizon in (20, 60):
            end = day_shift(planned, horizon - 1)
            result = settle(book, target, planned, end)
            peer = row["peer"]
            control = settle(book, peer["security_id"], planned, end) if peer else _miss("no_eligible_match")
            out.append(_pair(f"medium_{name}_vs_peer", horizon, row, result, control, counterpart=peer))
            stop = row["short_stop"]
            condition = {}
            if horizon == 60 and result["status"] == "settled" and stop is not None and not row["below_sma10"]:
                breach = false_breakout(book, target, signal, end, stop)
                # Only make the stronger continuity claim after checking every
                # completed week from the frozen signal through the endpoint.
                if breach["status"] == "breached":
                    condition = {"short_break": breach["session"], "medium_trend_held": _holds_medium(book, target, signal, end)}
            entry = {"group": name, "horizon": horizon, "target": row["target"], "session": row["session"],
                     "candidate": result, "comparator": peer, "baseline": control, **condition}
            raw.append(entry)
            groups[(name, horizon)].append(entry)
    response = {}
    for name in ("short_confirmed_below_10w", "short_confirmed_at_or_above_10w",
                 "short_not_confirmed_below_10w", "short_not_confirmed_at_or_above_10w"):
        for horizon in (20, 60):
            data = groups[(name, horizon)]
            rtn, mae = defaultdict(list), defaultdict(list)
            for row in data:
                result = row["candidate"]
                if result.get("net_15") is not None:
                    rtn[row["session"]].append(result["net_15"])
                if result.get("mae") is not None:
                    mae[row["session"]].append(result["mae"])
            response[f"{name}/{horizon}"] = {"rows": len(data), "net_15": distribution(mean(xs) for xs in rtn.values()),
                "mae": distribution(mean(xs) for xs in mae.values()), "statuses": dict(Counter(r["candidate"]["status"] for r in data)),
                "industry_counts": dict(Counter(r["target"]["industry"] or "unknown" for r in data))}
    return raw, response


def evaluate(frozen: dict[str, Any], evidence: dict, *, cohort_sha256: str, now: datetime | None = None) -> dict:
    if frozen.get("version") != VERSION or frozen["spec"].get("rules") != PROTOCOL:
        raise ValueError("unknown cohort/rules revision")
    if sha(frozen) != cohort_sha256:
        raise ValueError("cohort hash differs from the frozen membership")
    require_implementation(frozen["spec"])
    if utc(evidence["asof_utc"]) > utc(now or datetime.now(timezone.utc)):
        raise ValueError("price evidence cutoff cannot be in the future")
    book = PriceBook(evidence, forward=frozen["spec"]["mode"] == "forward")
    pairs, diagnostics = [], []
    for row in frozen["episodes"]:
        detail = _episode_paths(book, row, pairs)
        if detail:
            diagnostics.append({"event_id": row["id"], **detail})
    for row in frozen["confirmation_pairs"]:
        _confirmation_paths(book, row, pairs)
    variants = _ranking_paths(book, frozen["ranking"], pairs)
    medium, medium_summary = _medium_paths(book, frozen["medium"], pairs)
    groups = defaultdict(list)
    for row in pairs:
        groups[(row["family"], row["horizon"])].append(row)
    for family in PROTOCOL["primary_comparisons"]:
        groups.setdefault((family, PRIMARY), [])
    summaries = {}
    for (family, horizon), rows in sorted(groups.items()):
        spec = frozen["spec"]
        # Confirmation can occur in the preregistered five-session follow-up.
        end = max(spec["through"], *(r["session"] for r in rows)) if rows else spec["through"]
        main = horizon == PRIMARY and family in PROTOCOL["primary_comparisons"]
        block = max(horizon, horizon + WAIT) if family in ("structure_exit_vs_fixed", "wait_vs_immediate_equal_hold") else horizon
        summaries[f"{family}/{horizon}"] = summarize(rows, horizon=block, calendar_start=spec["start"],
                                                      calendar_end=end, main=main)
        if main:
            summaries[f"{family}/{horizon}"]["prespecified_pressure_windows"] = {
                name: summarize(rows, horizon=block, calendar_start=window["start"],
                                calendar_end=window["through"], main=False)
                for name, window in spec.get("pressure_windows", {}).items()
            }
    primary_rank = summaries[f"financial_candidate_vs_top15/{PRIMARY}"]
    swap_dates = sum(bool(row["financial_additions"]) for row in frozen["ranking"])
    if not swap_dates and frozen["ranking"]:
        primary_rank.update(selection_delta=0, verdict="no_membership_change")
    primary_rank["swap_dates"] = swap_dates
    spec = frozen["spec"]
    dates = sessions(date.fromisoformat(spec["start"]), date.fromisoformat(spec["through"]))
    coverage_size = len(dates)
    covered = sum(frozen["session_coverage"].get(str(day), {}).get("status") == "observed" for day in dates)
    calendar_coverage = covered / coverage_size
    for family in PROTOCOL["primary_comparisons"]:
        main = summaries[f"{family}/{PRIMARY}"]
        enough = calendar_coverage >= PROTOCOL["minimum_publication_coverage"]
        main["checks"]["publication_coverage"] = enough
        if not enough and main["verdict"] == "meets_registered_research_thresholds":
            main["verdict"] = "insufficient_evidence"
    failure_counts = Counter(item["status"] for item in frozen["episodes"])
    contacts = frozen["confirmation_pairs"]
    modes = {"retrospective": "retrospective_diagnostic_only", "forward": "preregistered_forward_paper_comparison"}
    risk = Counter(item["confirmation_close_break_5"]["status"] for item in diagnostics)
    mature_windows = sum(item["confirmation_close_break_5"]["window_mature"] for item in diagnostics)
    eligible = risk["breached"] + risk["not_breached"]
    opportunity_cost = {}
    for horizon in HORIZONS:
        by_day = defaultdict(list)
        for row in groups[("wait_vs_immediate", horizon)]:
            if row["immediate_opportunity_cost"] is not None:
                by_day[row["session"]].append(row["immediate_opportunity_cost"])
        opportunity_cost[str(horizon)] = distribution(mean(values) for values in by_day.values())
    return {
        "version": VERSION, "cohort_sha256": cohort_sha256, "price_evidence_sha256": sha(evidence),
        "implementation_sha256": frozen["spec"]["implementation_sha256"],
        "source": book.source, "price_cutoff_utc": book.at.isoformat(), "evidence_class": modes[frozen["spec"]["mode"]],
        "production_promotion": False, "session_coverage": frozen["session_coverage"], "excluded": frozen["excluded"],
        "publication_coverage": {"observed": covered, "expected": coverage_size, "rate": calendar_coverage},
        "observation_statuses": dict(failure_counts), "confirmed_episodes": len(contacts),
        "opportunity_cost_when_waiting_stays_cash": opportunity_cost,
        "match_failures": {key: sum(row[key] is None for row in contacts) for key in ("peer", "random")},
        "match_failure_rate": {key: (sum(row[key] is None for row in contacts) / len(contacts)) if contacts else None
                               for key in ("peer", "random")},
        "false_breakout_5d": {"rate": risk["breached"] / eligible if eligible else None, "statuses": dict(risk),
                             "mature_windows": mature_windows, "scorable_mature_windows": eligible,
                             "early_breaches": risk["early_breach"]}
        if frozen["spec"]["pattern"] == BREAKOUT_VERSION else None,
        "confirmation_diagnostics": diagnostics, "comparisons": summaries, "paired_paths": pairs,
        "ranking_paths": variants, "medium_summary": medium_summary, "medium_paths": medium,
        "medium_held_despite_short_break_60d": [row for row in medium if row.get("medium_trend_held") is True],
    }
