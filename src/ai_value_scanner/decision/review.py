"""Frozen review evidence and watchlist outcomes derived from StockDecision."""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .action import H3_B_MIN_QUALITY_CONFIDENCE, H3_B_MIN_QUALITY_SCORE, H3_READY_MIN_ENTRY_SCORE
from .attention import is_hard_damage_for_retention, is_soft_exit_grace_eligible
from .model import ActionState, EntryState, QualityGrade, ReadyAge, ReviewCondition, StockDecision

REVIEW_EVIDENCE_VERSION = "decision_review_v1"

_QUANTITY = r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))([%xd]?)"
_SINGLE_LIMIT = re.compile(rf"(>=|<=|>|<)\s*{_QUANTITY}(?: annualized)?")
_BAND = re.compile(rf"{_QUANTITY}\s*(?:to|-)\s*{_QUANTITY}")
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.-]*")
_ENTRY_PROVENANCE_FIELDS = ("market_data_feed", "market_data_mode", "entry_policy_version")


def _amount(raw: str, unit: str) -> float:
    return float(raw) / (100 if unit == "%" else 1)


def _margin(target: str, observed: float | str | None) -> tuple[str | None, float | None]:
    value = observed if isinstance(observed, (float, int)) and math.isfinite(observed) else None
    if match := _SINGLE_LIMIT.fullmatch(target):
        comparison, raw, unit = match.groups()
        limit = _amount(raw, unit)
        if value is None:
            return comparison, None
        distance = value - limit if comparison.startswith(">") else limit - value
        return comparison, round(distance, 6)
    if match := _BAND.fullmatch(target):
        low, low_unit, high, high_unit = match.groups()
        distance = None if value is None else min(value - _amount(low, low_unit), _amount(high, high_unit) - value)
        return "between", round(distance, 6) if distance is not None else None
    return None, None


def build_review_conditions(decision: StockDecision) -> tuple[ReviewCondition, ...]:
    action_v2 = str(decision.provenance.get("decision_policy_version")).endswith(",a=v2")
    direction = "maintain" if decision.action_state is ActionState.PRIORITY_REVIEW else "qualify"
    grade = decision.quality.grade
    grade_eligible = grade is QualityGrade.A or (action_v2 and grade is QualityGrade.B)
    conditions = [
        ReviewCondition(
            route="priority_review", direction=direction, metric="quality_grade",
            label="Company Quality", observed=grade.value, comparison="in",
            target="A or qualifying B" if action_v2 else "A",
            margin=None,
            status="PASS" if grade_eligible else "BLOCK",
            data_asof=decision.quality.data_asof,
            reason="The additional B thresholds apply when the grade is B." if action_v2
            else "Priority Review requires Quality A.",
            blocking=not grade_eligible,
        ),
        ReviewCondition(
            route="priority_review", direction=direction, metric="entry_state",
            label="Entry state", observed=decision.entry.state.value, comparison="=",
            target=EntryState.ENTRY_READY.value, margin=None,
            status="PASS" if decision.entry.state is EntryState.ENTRY_READY else "BLOCK",
            data_asof=decision.entry.market_asof,
            reason="Priority Review requires a confirmed Ready state.",
            blocking=decision.entry.state is not EntryState.ENTRY_READY,
        ),
    ]
    if action_v2 and grade in {QualityGrade.A, QualityGrade.B}:
        for metric, label, observed, threshold, asof in (
            ("quality_score", "B Quality score", decision.quality.score,
             H3_B_MIN_QUALITY_SCORE, decision.quality.data_asof),
            ("quality_confidence", "B Quality confidence", decision.quality.confidence,
             H3_B_MIN_QUALITY_CONFIDENCE, decision.quality.data_asof),
            ("entry_score", "B Entry score", decision.entry.score,
             H3_READY_MIN_ENTRY_SCORE, decision.entry.market_asof),
        ):
            target = f">= {threshold:.2f}"
            comparison, margin = _margin(target, observed)
            if grade is QualityGrade.A:
                status = "NOT_APPLICABLE"
            elif observed is None or not math.isfinite(observed):
                status = "UNKNOWN"
            else:
                status = "PASS" if observed >= threshold else "BLOCK"
            conditions.append(ReviewCondition(
                "quality_b_route", direction, metric, label, observed, comparison,
                target, margin, status, asof,
                "This threshold is required for Priority Review when the company is rated B.",
                blocking=status in {"BLOCK", "UNKNOWN"},
            ))
    for gate in decision.entry.gate_results:
        comparison, margin = _margin(gate.target, gate.observed)
        conditions.append(ReviewCondition(
            "entry_ready",
            "invalidate" if gate.gate_key in {"trend_damage", "overextension"} else (
                "maintain" if decision.entry.state is EntryState.ENTRY_READY else "qualify"
            ),
            gate.metric or gate.gate_key, gate.gate_label, gate.observed, comparison,
            gate.target, margin, gate.status, decision.entry.market_asof, gate.reason,
            blocking=gate.blocking,
        ))
    return tuple(conditions)


def issuer_cik(value: Any) -> str | None:
    token = str(value or "").strip().lstrip("0")
    return token.zfill(10) if len(token) <= 10 and token.isascii() and token.isdigit() else None


def _continuity(current: StockDecision, previous: StockDecision | None) -> str | None:
    if previous is None:
        return "security_missing_in_prior_snapshot"
    cik = issuer_cik(current.provenance.get("cik"))
    if cik is None or cik != issuer_cik(previous.provenance.get("cik")):
        return "security_identity_unverified_or_changed"
    required = (*_ENTRY_PROVENANCE_FIELDS, "quality_policy_version")
    if any(not current.provenance.get(field) for field in required):
        return "feed_or_policy_unverified"
    for field in (*required, "decision_policy_version"):
        if current.provenance.get(field) != previous.provenance.get(field):
            return "feed_or_policy_changed"
    if previous.entry.market_asof != previous.decision_date or previous.entry.state is EntryState.INSUFFICIENT_DATA:
        return "prior_entry_data_unavailable"
    return None


def build_ready_ages(
    current: Sequence[StockDecision],
    history: Iterable[tuple[str, Mapping[str, StockDecision] | None]],
) -> dict[str, ReadyAge]:
    """Track consecutive validated Ready days, with an explicit lower bound at gaps."""
    active: dict[str, StockDecision] = {}
    ages: dict[str, ReadyAge] = {}
    for decision in current:
        symbol = decision.symbol
        if decision.entry.market_asof != decision.decision_date or decision.entry.state is EntryState.INSUFFICIENT_DATA:
            ages[symbol] = ReadyAge(0, None, None, "current_entry_data_unavailable")
        elif decision.entry.state is EntryState.ENTRY_READY:
            active[symbol] = decision
            ages[symbol] = ReadyAge(1, decision.decision_date, None, "archive_boundary")
        else:
            ages[symbol] = ReadyAge(0, None, None, "not_ready")

    for index, (session, prior) in enumerate(history):
        if index == 0 and prior is not None:
            for decision in current:
                previous = prior.get(decision.symbol)
                if (
                    ages[decision.symbol].reason == "not_ready" and previous is not None
                    and previous.entry.state is EntryState.ENTRY_READY
                    and _continuity(decision, previous) is None
                ):
                    ages[decision.symbol] = ReadyAge(
                        0, None, None, f"ready_reset_to_{decision.entry.state.value.lower()}"
                    )
        if not active:
            break
        for symbol, decision in tuple(active.items()):
            age = ages[symbol]
            previous = prior.get(symbol) if prior is not None else None
            issue = "missing_prior_session" if prior is None else _continuity(decision, previous)
            if issue:
                ages[symbol] = replace(age, reason=issue)
            elif previous.entry.state is EntryState.ENTRY_READY:
                ages[symbol] = ReadyAge(age.sessions + 1, session, None, "archive_boundary")
                continue
            else:
                ages[symbol] = replace(age, first_ready_session=age.observed_since, reason="observed_transition")
            del active[symbol]
        if not active:
            break
    return ages


def with_review_evidence(
    decision: StockDecision, age: ReadyAge | None, *, previous_daily: Iterable[str] = ()
) -> StockDecision:
    trigger = decision.review_trigger
    conditions = build_review_conditions(decision)
    action_v2 = any(condition.route == "quality_b_route" for condition in conditions)
    if action_v2 and decision.action_state is ActionState.PRIORITY_REVIEW:
        trigger = "Review while Entry stays Ready and Quality stays A or meets all B thresholds."
    elif action_v2 and decision.action_state is ActionState.HOLD_MONITOR:
        trigger = "Re-review when Entry is Ready and Quality is A or meets all B thresholds."
    if decision.symbol in previous_daily:
        hard_damage = is_hard_damage_for_retention(decision)
        conditions += (ReviewCondition(
            "daily_retention", "invalidate", "hard_damage", "Daily list hard damage",
            "triggered" if hard_damage else "clear", "=", "clear", None,
            "BLOCK" if hard_damage else "PASS", decision.entry.market_asof,
            "The S2 hard-damage gate blocks grace when trend, data coverage, quality or overextension breaches it.",
            blocking=hard_damage,
        ),)
    return replace(
        decision, review_trigger=trigger, ready_age=age,
        review_conditions=conditions,
    )


@dataclass(frozen=True)
class FollowedSecurity:
    symbol: str
    cik: str
    added_at_utc: str
    reason: str

    def __post_init__(self) -> None:
        if not _SYMBOL.fullmatch(self.symbol) or issuer_cik(self.cik) != self.cik or not self.reason.strip():
            raise ValueError("invalid followed security")
        if datetime.fromisoformat(self.added_at_utc).utcoffset() is None:
            raise ValueError("followed security added_at_utc requires a timezone")


def load_followed_securities(path: Path, *, asof: datetime) -> tuple[list[FollowedSecurity], str]:
    contents = path.read_bytes()
    reader = csv.DictReader(io.StringIO(contents.decode("utf-8-sig")), strict=True)
    needed = {"symbol", "cik", "added_at_utc", "reason"}
    if not needed.issubset(reader.fieldnames or []):
        raise ValueError("review watchlist requires symbol,cik,added_at_utc,reason")
    seen: set[str] = set()
    entries = []
    for row in reader:
        symbol = (row["symbol"] or "").strip().upper()
        cik = issuer_cik(row["cik"])
        reason = (row["reason"] or "").strip()
        try:
            added = datetime.fromisoformat((row["added_at_utc"] or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"review watchlist row {reader.line_num} has an invalid added_at_utc") from exc
        if not _SYMBOL.fullmatch(symbol) or cik is None or not reason or added.utcoffset() is None or symbol in seen:
            raise ValueError(f"review watchlist row {reader.line_num} has invalid or repeated security information")
        seen.add(symbol)
        if added <= asof:
            entries.append(FollowedSecurity(symbol, cik, added.astimezone(timezone.utc).isoformat(), reason))
    return entries, hashlib.sha256(contents).hexdigest()


@dataclass(frozen=True)
class FollowedPrior:
    cik: str | None
    in_daily: bool
    action: str
    entry: str
    quality: str
    provenance: dict[str, str | None]

    def __post_init__(self) -> None:
        if type(self.in_daily) is not bool or (self.cik is not None and issuer_cik(self.cik) != self.cik):
            raise ValueError("invalid prior security identity or membership")
        ActionState(self.action)
        EntryState(self.entry)
        QualityGrade(self.quality)
        if set(self.provenance) != {*_ENTRY_PROVENANCE_FIELDS, "quality_policy_version"} or any(
            value is not None and not isinstance(value, str) for value in self.provenance.values()
        ):
            raise ValueError("invalid prior decision provenance")


def freeze_followed_prior(
    entries: Iterable[FollowedSecurity], previous: Mapping[str, StockDecision], daily: Iterable[str],
) -> dict[str, FollowedPrior]:
    daily = set(daily)
    return {
        entry.symbol: FollowedPrior(
            issuer_cik(prior.provenance.get("cik")), entry.symbol in daily,
            prior.action_state.value, prior.entry.state.value, prior.quality.grade.value,
            {field: prior.provenance.get(field) for field in (*_ENTRY_PROVENANCE_FIELDS, "quality_policy_version")},
        )
        for entry in entries if (prior := previous.get(entry.symbol)) is not None
    }


def build_followed_rows(
    entries: Iterable[FollowedSecurity],
    current: Sequence[StockDecision],
    previous: Mapping[str, FollowedPrior],
    daily_symbols: Iterable[str],
    exclusions: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_symbol = {decision.symbol: decision for decision in current}
    excluded = {row["symbol"]: row for row in exclusions}
    daily = set(daily_symbols)
    quality_rank = {QualityGrade.A: 0, QualityGrade.B: 1, QualityGrade.C: 2, QualityGrade.UNRATED: 3}
    rows = []
    for entry in entries:
        symbol = entry.symbol
        decision = by_symbol.get(symbol)
        row = dict(symbol=symbol, cik=entry.cik, added_at_utc=entry.added_at_utc, reason=entry.reason,
                   status="tracked", changes=[], detail=False, exclusion_reason=None)
        changes = row["changes"]
        if decision is None or issuer_cik(decision.provenance.get("cik")) != entry.cik:
            if decision is not None:
                row["status"] = "security_identity_unverified_or_changed"
            elif symbol in excluded:
                row["status"] = "excluded"
                row["exclusion_reason"] = excluded[symbol]["reason_code"]
            else:
                row["status"] = "missing_from_scan"
            row["same_issuer_symbols"] = sorted(
                item.symbol for item in current
                if item.symbol != symbol and issuer_cik(item.provenance.get("cik")) == entry.cik
            )
            rows.append(row)
            continue
        row.update(detail=True, action=decision.action_state.value, entry=decision.entry.state.value,
                   quality=decision.quality.grade.value, in_daily=symbol in daily,
                   priority=decision.priority)
        prior = previous.get(symbol)
        if prior is not None and prior.cik == entry.cik:
            quality_version = decision.provenance.get("quality_policy_version")
            if quality_version and quality_version == prior.provenance.get("quality_policy_version"):
                if quality_rank[decision.quality.grade] > quality_rank[QualityGrade(prior.quality)]:
                    changes.append("quality_data_unavailable" if decision.quality.grade is QualityGrade.UNRATED else "quality_weakened")
            if all(
                decision.provenance.get(field) and decision.provenance[field] == prior.provenance.get(field)
                for field in _ENTRY_PROVENANCE_FIELDS
            ):
                if decision.entry.state is EntryState.TREND_DAMAGED and prior.entry != EntryState.TREND_DAMAGED.value:
                    changes.append("trend_damaged")
                if decision.entry.state is EntryState.INSUFFICIENT_DATA and prior.entry != EntryState.INSUFFICIENT_DATA.value:
                    changes.append("entry_data_unavailable")
        same_issuer = prior is not None and prior.cik == entry.cik
        was_listed = same_issuer and prior.in_daily
        grace = was_listed and is_soft_exit_grace_eligible(
            replace(decision, previous_action_state=ActionState(prior.action)), (symbol,),
        )
        if was_listed and symbol not in daily:
            if decision.action_state is ActionState.PRIORITY_REVIEW or grace:
                changes.append("left_daily_ranking_cutoff")
            elif is_hard_damage_for_retention(decision):
                changes.append("left_daily_hard_damage")
            else:
                changes.append("left_daily_ineligible")
        elif symbol in daily:
            if grace and is_soft_exit_grace_eligible(decision, (symbol,)):
                changes.append("grace_retained")
            elif same_issuer and not was_listed:
                changes.append("entered_daily")
        elif decision.action_state is ActionState.PRIORITY_REVIEW:
            changes.append("off_daily_capacity")
        rows.append(row)
    return rows
