"""Point-in-time, issuer-weighted peer and completed-week evidence."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import math
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

from ai_value_scanner.market_calendar import is_session_day
from ai_value_scanner.swing.events import timestamp
from ai_value_scanner.swing.setups import completed_sip_bars, next_session
from .model import StockDecision
from .review import issuer_cik

MEDIUM_REVIEW_VERSION = "medium_term_sic2_v1"
MIN_PEER_ISSUERS = 5
HORIZONS = (5, 20)
RETURNS = (*HORIZONS, 60)


def sic_group(value: Any) -> str | None:
    token = str(value or "").strip().removesuffix(".0")
    if not token.isascii() or not token.isdigit() or len(token) not in (3, 4):
        return None
    if int(token) == 0 or int(token) >= 9900:
        return None
    return token.zfill(4)[:2]


def classifications_asof(records: Iterable[Mapping], cutoff: datetime) -> dict[str, str]:
    """Use only the latest observed revision per issuer. Resolve ties conservatively."""
    latest: dict[str, tuple[datetime, set]] = {}
    for record in records:
        issuer = issuer_cik(record.get("cik"))
        if issuer is None:
            continue
        known = timestamp(record["known_at_utc"])
        if known > cutoff:
            continue
        industry = sic_group(record.get("sic"))
        old = latest.get(issuer)
        if old is None or old[0] < known:
            latest[issuer] = (known, {industry})
        elif old[0] == known:
            old[1].add(industry)
    return {issuer: next(iter(groups)) for issuer, (_, groups) in latest.items()
            if len(groups) == 1 and None not in groups}


def market_profile(rows: Iterable[Mapping], session: date, *, splits=()) -> dict:
    bars = completed_sip_bars(rows, session, splits=splits)
    windows = {}
    for horizon in RETURNS:
        if len(bars) <= horizon:
            continue
        value = bars[-1].close / bars[-horizon - 1].close - 1
        if math.isfinite(value):
            windows[horizon] = {"start": bars[-horizon - 1].session.isoformat(), "end": session.isoformat(), "return": value}
    weeks = []
    for bar in bars:
        if next_session(bar.session).isocalendar()[:2] == bar.session.isocalendar()[:2]:
            continue
        preceding_sunday = bar.session - timedelta(days=bar.session.weekday() + 1)
        if next_session(preceding_sunday) >= bars[0].session:
            weeks.append(bar)
    weekly = None
    if len(weeks) >= 10:
        last_ten = weeks[-10:]
        average = mean(bar.close for bar in last_ten)
        weekly = {
            "first_week_end": last_ten[0].session.isoformat(),
            "last_week_end": last_ten[-1].session.isoformat(),
            "close": last_ten[-1].close,
            "sma10": average,
            "relative_to_sma10": last_ten[-1].close / average - 1,
        }
    return {"windows": windows, "completed_week": weekly}


def _matching_values(target: Mapping | None, benchmark: Mapping | None) -> bool:
    return bool(target and benchmark and (target["start"], target["end"]) == (benchmark["start"], benchmark["end"]))


def _short_confirmation(decision: StockDecision) -> bool | None:
    if decision.swing_review is None:
        return None
    statuses = {item["state"]["status"] for item in decision.swing_review["patterns"].values()}
    if "confirmed" in statuses:
        return True
    return None if "insufficient" in statuses else False


def build_medium_reviews(
    decisions: Sequence[StockDecision], profiles: Mapping[str, Mapping], benchmark: Mapping,
    groups_by_cik: Mapping[str, str], *, session: str, classification_asof: str, classification_source: str,
) -> dict[str, dict]:
    """Freeze actual metric values with portfolio-independent peer counts.

    A peer is one company, selected by the first symbol with a valid matched
    return within its share classes. All classes of the target are excluded.
    """
    issuers = {decision.symbol: issuer_cik(decision.provenance.get("cik")) for decision in decisions}
    groups: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for symbol, cik in sorted(issuers.items()):
        group = groups_by_cik.get(cik)
        if group:
            groups[group][cik].append(symbol)

    benchmark_returns = benchmark.get("windows", {})
    summaries = {}
    for decision in decisions:
        symbol = decision.symbol
        issuer = issuers[symbol]
        group = groups_by_cik.get(issuer)
        own = profiles.get(symbol) or {}
        metrics = {}
        for horizon in HORIZONS:
            target = own.get("windows", {}).get(horizon)
            qqq = benchmark_returns.get(horizon)
            candidates = {cik: names for cik, names in groups.get(group, {}).items() if cik != issuer}
            effective: list[tuple[str, str, float]] = []
            for cik, classes in sorted(candidates.items()):
                for name in classes:
                    peer = profiles.get(name, {}).get("windows", {}).get(horizon)
                    if _matching_values(peer, qqq):
                        effective.append((cik, name, peer["return"]))
                        break
            peer_mean = mean(value for _, _, value in effective) if len(effective) >= MIN_PEER_ISSUERS else None
            # Qualifying coverage is observable even when a target lacks price
            # or realized return. All published comparisons use one QQQ window.
            reason = None
            if not group:
                reason = "classification_unknown"
            elif qqq is None:
                reason = "benchmark_window_missing"
            elif peer_mean is None:
                reason = "insufficient_peer_issuers"
            elif not _matching_values(target, qqq):
                reason = "target_window_missing"
            metrics[str(horizon)] = {
                "start": qqq["start"] if qqq else None, "end": session,
                "eligible_peers": len(candidates), "effective_peers": len(effective),
                "coverage": len(effective) / len(candidates) if candidates else None,
                "members_sha256": sha256(json.dumps(effective, separators=(",", ":")).encode()).hexdigest(),
                "target_return": target["return"] if _matching_values(target, qqq) else None,
                "peer_return": peer_mean, "benchmark_return": qqq["return"] if qqq else None,
                "stock_minus_peer": target["return"] - peer_mean if peer_mean is not None and _matching_values(target, qqq) else None,
                "peer_minus_qqq": peer_mean - qqq["return"] if peer_mean is not None else None,
                "peer_positive_share": sum(ret > 0 for _, _, ret in effective) / len(effective) if peer_mean is not None else None,
                "reason": reason,
            }
        target_60 = own.get("windows", {}).get(60)
        qqq_60 = benchmark_returns.get(60)
        relative_60 = target_60["return"] - qqq_60["return"] if _matching_values(target_60, qqq_60) else None
        weekly = own.get("completed_week")
        short = _short_confirmation(decision)
        damaged = weekly["relative_to_sma10"] < 0 if weekly else None
        summaries[symbol] = {
            "version": MEDIUM_REVIEW_VERSION, "session": session, "feed": "sip",
            "sic2": group, "classification_asof": classification_asof, "classification_source": classification_source,
            "minimum_peers": MIN_PEER_ISSUERS, "horizons": metrics,
            "completed_week": weekly, "relative_to_qqq_60d": relative_60,
            "short_confirmed": short, "medium_trend_damaged": damaged,
            "divergence": "short_confirmed_medium_trend_damaged" if short and damaged else None,
        }
    return summaries


def validate_medium_review(review: Mapping, session: str) -> None:
    if review["version"] != MEDIUM_REVIEW_VERSION or review["session"] != session or review["feed"] != "sip":
        raise ValueError("invalid medium-term evidence identity")
    if not is_session_day(date.fromisoformat(session)):
        raise ValueError("invalid medium-term trading session")
    for key in ("5", "20"):
        row = review["horizons"][key]
        if not 0 <= row["effective_peers"] <= row["eligible_peers"] or row["end"] != session:
            raise ValueError("invalid peer cohort counts or session")
        if row["effective_peers"] < MIN_PEER_ISSUERS and any(
            row[field] is not None for field in ("peer_return","stock_minus_peer","peer_minus_qqq","peer_positive_share")
        ):
            raise ValueError("peer sample must meet the coverage floor")
