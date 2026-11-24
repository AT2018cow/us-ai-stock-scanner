"""Date-weighted distributions and paired calendar-block inference."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from random import Random
from statistics import mean

from .swing_cohorts import PROTOCOL, SEED, sessions


def quantile(values, p):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    lo = int(pos)
    return ordered[lo] + (ordered[min(lo + 1, len(ordered) - 1)] - ordered[lo]) * (pos - lo)


def distribution(values):
    values = list(values)
    if not values:
        return {"n": 0, "mean": None, "p05": None, "win_rate": None, "severe_loss_rate": None,
                "mean_gain": None, "mean_loss": None}
    gains = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    return {"n": len(values), "mean": mean(values), "p05": quantile(values, .05),
            "win_rate": len(gains) / len(values),
            "severe_loss_rate": sum(v <= -.10 for v in values) / len(values),
            "mean_gain": mean(gains) if gains else None, "mean_loss": mean(losses) if losses else None}


def _bootstrap(dates, deltas, absolutes, block):
    rng = Random(SEED)
    chunks = [dates[i:i+block] for i in range(len(dates) - block + 1)]
    if len(dates) < 2 * block or not chunks:
        return None, None
    shifts, tails = [], []
    for _ in range(PROTOCOL["bootstrap_draws"]):
        draw = []
        for _ in range((len(dates) + block - 1) // block):
            draw.extend(rng.choice(chunks))
        relative = [deltas[day] for day in draw if day in deltas]
        paired = [absolutes[day] for day in draw if day in absolutes]
        if relative:
            shifts.append(mean(relative))
        if paired:
            tails.append(quantile([a for a, _ in paired], .05) - quantile([b for _, b in paired], .05))
    def ci(sample):
        return [quantile(sample, .025), quantile(sample, .975)] if sample else None
    return ci(shifts), ci(tails)


def _absolute_returns(row, fee):
    return row["candidate"].get(f"net_{fee}"), row["baseline"].get(f"net_{fee}")


def _delta(row, fee):
    if row.get("known_zero_delta") is True:
        return 0.
    a, b = _absolute_returns(row, fee)
    return a - b if a is not None and b is not None else None


def _daily_deltas(pairs, fee, *, missing=None):
    groups = defaultdict(list)
    for row in pairs:
        value = _delta(row, fee)
        if value is None:
            value = missing
        if value is not None:
            groups[row["session"]].append(value)
    return {day: mean(values) for day, values in groups.items()}


def _daily_absolutes(pairs, fee):
    groups = defaultdict(list)
    for row in pairs:
        a, b = _absolute_returns(row, fee)
        if a is not None and b is not None:
            groups[row["session"]].append((a, b))
    return {day: (mean(x[0] for x in values), mean(x[1] for x in values)) for day, values in groups.items()}


def _nonoverlapping_slices(rows):
    # Union the actual entry-to-exit windows for each signal date, so one
    # date contributes at most one observation to any slice.
    by_date = defaultdict(list)
    for row in rows:
        if row.get("exposure_window") is not None:
            by_date[row["session"]].append(row)
    windows = sorted(
        (min(row["exposure_window"][0] for row in values),
         max(row["exposure_window"][1] for row in values), day)
        for day, values in by_date.items()
    )
    partitions = []
    for start, end, day in windows:
        partition = next((part for part in partitions if part[-1]["exposure_end"] < start), None)
        if partition is None:
            partition = []
            partitions.append(partition)
        partition.append({"session": day, "exposure_start": start, "exposure_end": end})
    deltas = _daily_deltas((row for values in by_date.values() for row in values), 15)
    return [{"windows": part, "paired_delta_net_15": distribution(deltas[item["session"]] for item in part)}
            for part in partitions]


def summarize(pairs, *, horizon, calendar_start, calendar_end, main):
    dates = [day.isoformat() for day in sessions(date.fromisoformat(calendar_start), date.fromisoformat(calendar_end))]
    date_set = set(dates)
    all_rows = [row for row in pairs if row["session"] in date_set]
    pairs = [row for row in all_rows if row.get("comparison_eligible") is not False]
    excluded = Counter((r["candidate"]["status"], r["baseline"]["status"]) for r in all_rows
                       if r.get("comparison_eligible") is False)
    d15, d30 = _daily_deltas(pairs, 15), _daily_deltas(pairs, 30)
    abs15 = _daily_absolutes(pairs, 15)
    candidate = distribution(a for a, _ in abs15.values())
    baseline = distribution(b for _, b in abs15.values())
    mature = [r for r in pairs if "future_unmatured" not in (r["candidate"]["status"], r["baseline"]["status"])]
    valid = [r for r in mature if _delta(r, 15) is not None]
    states = Counter((r["candidate"]["status"], r["baseline"]["status"]) for r in pairs)
    issuers = Counter(key for r in valid for key in r.get("issuer_keys", []))
    by_date = Counter(r["session"] for r in valid)
    events = {r["event_id"] for r in valid}
    biggest = min(issuers.items(), key=lambda item: (-item[1], item[0]), default=None)
    contributions = defaultdict(list)
    for row in valid:
        for issuer, amount in row.get("issuer_attribution_net_15", {}).items():
            contributions[issuer].append(amount / by_date[row["session"]] / len(by_date))
    contribution = {issuer: sum(amounts) for issuer, amounts in sorted(contributions.items())}
    largest_contributor = min((key for key, amount in contribution.items() if amount != 0.),
                              key=lambda key: (-abs(contribution[key]), key), default=None)
    strata = {}
    for kind in ("year", "regime", "industry"):
        grouped = defaultdict(list)
        for row in valid:
            group = row["session"][:4] if kind == "year" else row.get(kind) or "unknown"
            grouped[group].append(row)
        strata[kind] = {str(group): distribution(_daily_deltas(rows, 15).values())
                        for group, rows in sorted(grouped.items())}
    occupied = sum(any(day in d15 for day in dates[i:i+horizon]) for i in range(0, len(dates), horizon))
    ci, tci = _bootstrap(dates, d15, abs15, horizon) if main else (None, None)
    stress = {}
    for label, bound in (("missing_adverse", -PROTOCOL["missing_delta_stress"]),
                         ("missing_favorable", PROTOCOL["missing_delta_stress"])):
        sample = _daily_deltas(mature, 15, missing=bound)
        stress[label] = mean(sample.values()) if sample else None
    extra = {
        "dates": len(d15), "rows": len(pairs), "mature_or_explicitly_unavailable": len(mature),
        "dates_with_paired_absolute_returns": len(abs15),
        "known_zero_rows_missing_absolute": sum(
            r.get("known_zero_delta") is True and None in _absolute_returns(r, 15) for r in valid),
        "excluded_before_comparison": {f"{a}|{b}": n for (a, b), n in sorted(excluded.items())},
        "matched_settled": sum(None not in _absolute_returns(r, 15) for r in valid),
        "scorable_delta_rows": len(valid), "event_count": len(events), "distinct_issuers": len(issuers),
        "repeated_issuers": sum(n > 1 for n in issuers.values()), "date_member_counts": dict(sorted(by_date.items())),
        "largest_issuer_exposure": list(biggest) if biggest else None,
        "largest_absolute_contributor": largest_contributor,
        "issuer_attribution_date_weighted_net_15": contribution,
        "without_largest_contributor": distribution(_daily_deltas(
            [row for row in valid if largest_contributor not in row.get("issuer_keys", [])], 15).values()),
        "paired_coverage": len(valid) / len(mature) if mature else None,
        "statuses": {f"{a}|{b}": n for (a,b),n in sorted(states.items())},
        "cost_stress_30": distribution(d30.values()), "mean_delta_ci95": ci, "tail_delta_ci95": tci,
        "candidate_net_15": candidate, "baseline_net_15": baseline, "paired_delta_net_15": distribution(d15.values()),
        "nonoverlapping_partitions": _nonoverlapping_slices(valid), "calendar_block_sessions": horizon,
        "occupied_calendar_blocks": occupied, "slices": strata, **stress,
    }
    if main:
        lift = extra["paired_delta_net_15"]["mean"]
        cost = extra["cost_stress_30"]["mean"]
        tail = candidate["p05"] - baseline["p05"] if candidate["p05"] is not None else None
        checks = {
            "enough_dates": len(d15) >= PROTOCOL["minimum_dates"],
            "enough_calendar_blocks": occupied >= PROTOCOL["minimum_calendar_blocks"],
            "enough_issuers": len(issuers) >= PROTOCOL["minimum_issuers"],
            "issuer_concentration": bool(biggest and biggest[1] / sum(issuers.values()) <= PROTOCOL["maximum_issuer_share"]),
            "pair_coverage": (extra["paired_coverage"] or 0.) >= PROTOCOL["minimum_pair_coverage"],
            "tail_precision": bool(tci and len(abs15) >= PROTOCOL["minimum_dates"]
                                   and tci[1] - tci[0] <= PROTOCOL["maximum_tail_interval_width"]),
            "enough_lift": lift is not None and lift >= PROTOCOL["minimum_lift"],
            "positive_ci": bool(ci and ci[0] > 0),
            "stress_cost_positive": cost is not None and cost > 0,
            "tail_limit": tail is not None and tail >= -PROTOCOL["maximum_tail_deterioration"],
            "no_missing_sign_flip": stress["missing_adverse"] is not None and stress["missing_adverse"] > 0,
            "positive_without_largest": (extra["without_largest_contributor"]["mean"] or 0.) > 0,
        }
        precise = all(checks[key] for key in ("enough_dates", "enough_calendar_blocks", "enough_issuers",
                                             "issuer_concentration", "pair_coverage", "tail_precision"))
        if not precise:
            status = "insufficient_evidence"
        elif not all(checks[key] for key in ("enough_lift", "tail_limit")):
            status = "did_not_meet_economic_threshold"
        elif not all(checks.values()):
            status = "insufficient_evidence"
        else:
            status = "meets_registered_research_thresholds"
        extra.update(verdict=status, checks=checks, p05_deterioration=tail)
    return extra
