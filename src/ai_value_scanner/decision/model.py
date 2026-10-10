from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Any, Iterable, Literal, Mapping


DECISION_SCHEMA_VERSION = "1"
EvidencePolarity = Literal["positive", "negative", "neutral", "missing"]


class QualityGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    UNRATED = "UNRATED"


class EntryState(str, Enum):
    ENTRY_READY = "ENTRY_READY"
    WATCH_PULLBACK = "WATCH_PULLBACK"
    WATCH_BREAKOUT = "WATCH_BREAKOUT"
    TREND_DAMAGED = "TREND_DAMAGED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ActionState(str, Enum):
    PRIORITY_REVIEW = "PRIORITY_REVIEW"
    WATCH_PULLBACK = "WATCH_PULLBACK"
    WATCH_BREAKOUT = "WATCH_BREAKOUT"
    HOLD_MONITOR = "HOLD_MONITOR"
    AVOID = "AVOID"


@dataclass(frozen=True)
class EvidenceItem:
    code: str
    label: str
    polarity: EvidencePolarity
    metric: str | None
    value: float | str | None
    threshold: float | str | None
    message: str

    def __post_init__(self) -> None:
        if self.polarity not in {"positive", "negative", "neutral", "missing"}:
            raise ValueError(f"unsupported evidence polarity: {self.polarity!r}")


@dataclass(frozen=True)
class QualityDecision:
    grade: QualityGrade
    score: float | None
    confidence: float
    component_scores: dict[str, float | None]
    positives: tuple[EvidenceItem, ...]
    risks: tuple[EvidenceItem, ...]
    missing: tuple[EvidenceItem, ...]
    data_asof: str | None


@dataclass(frozen=True)
class EntryDecision:
    state: EntryState
    score: float | None
    confidence: float
    positives: tuple[EvidenceItem, ...]
    risks: tuple[EvidenceItem, ...]
    market_asof: str | None


@dataclass(frozen=True)
class StockDecision:
    schema_version: str
    symbol: str
    company_name: str | None
    decision_date: str
    generated_at_utc: str
    quality: QualityDecision
    entry: EntryDecision
    action_state: ActionState
    priority: int
    rationale: tuple[EvidenceItem, ...]
    review_trigger: str | None
    source_lists: tuple[str, ...]
    provenance: dict[str, str | int | float | bool | None]
    previous_action_state: ActionState | None = None
    state_change_reason: str | None = None


def _evidence_to_dict(item: EvidenceItem) -> dict[str, Any]:
    return {
        "code": item.code,
        "label": item.label,
        "polarity": item.polarity,
        "metric": item.metric,
        "value": item.value,
        "threshold": item.threshold,
        "message": item.message,
    }


def _evidence_from_dict(payload: Mapping[str, Any]) -> EvidenceItem:
    return EvidenceItem(
        code=str(payload["code"]),
        label=str(payload["label"]),
        polarity=payload["polarity"],
        metric=None if payload.get("metric") is None else str(payload["metric"]),
        value=payload.get("value"),
        threshold=payload.get("threshold"),
        message=str(payload["message"]),
    )


def stock_decision_to_dict(decision: StockDecision) -> dict[str, Any]:
    return {
        "schema_version": decision.schema_version,
        "symbol": decision.symbol,
        "company_name": decision.company_name,
        "decision_date": decision.decision_date,
        "generated_at_utc": decision.generated_at_utc,
        "quality": {
            "grade": decision.quality.grade.value,
            "score": decision.quality.score,
            "confidence": decision.quality.confidence,
            "component_scores": dict(decision.quality.component_scores),
            "positives": [_evidence_to_dict(item) for item in decision.quality.positives],
            "risks": [_evidence_to_dict(item) for item in decision.quality.risks],
            "missing": [_evidence_to_dict(item) for item in decision.quality.missing],
            "data_asof": decision.quality.data_asof,
        },
        "entry": {
            "state": decision.entry.state.value,
            "score": decision.entry.score,
            "confidence": decision.entry.confidence,
            "positives": [_evidence_to_dict(item) for item in decision.entry.positives],
            "risks": [_evidence_to_dict(item) for item in decision.entry.risks],
            "market_asof": decision.entry.market_asof,
        },
        "action_state": decision.action_state.value,
        "priority": decision.priority,
        "rationale": [_evidence_to_dict(item) for item in decision.rationale],
        "review_trigger": decision.review_trigger,
        "source_lists": list(decision.source_lists),
        "provenance": dict(decision.provenance),
        "previous_action_state": (
            None
            if decision.previous_action_state is None
            else decision.previous_action_state.value
        ),
        "state_change_reason": decision.state_change_reason,
    }


def stock_decision_from_dict(payload: Mapping[str, Any]) -> StockDecision:
    schema_version = str(payload["schema_version"])
    if schema_version != DECISION_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported StockDecision schema_version={schema_version!r}; "
            f"expected {DECISION_SCHEMA_VERSION!r}"
        )

    quality_payload = payload["quality"]
    entry_payload = payload["entry"]
    if not isinstance(quality_payload, Mapping):
        raise TypeError("quality must be an object")
    if not isinstance(entry_payload, Mapping):
        raise TypeError("entry must be an object")

    previous_action = payload.get("previous_action_state")
    return StockDecision(
        schema_version=schema_version,
        symbol=str(payload["symbol"]),
        company_name=(
            None if payload.get("company_name") is None else str(payload["company_name"])
        ),
        decision_date=str(payload["decision_date"]),
        generated_at_utc=str(payload["generated_at_utc"]),
        quality=QualityDecision(
            grade=QualityGrade(quality_payload["grade"]),
            score=quality_payload.get("score"),
            confidence=float(quality_payload["confidence"]),
            component_scores=dict(quality_payload.get("component_scores", {})),
            positives=tuple(
                _evidence_from_dict(item)
                for item in quality_payload.get("positives", [])
            ),
            risks=tuple(
                _evidence_from_dict(item) for item in quality_payload.get("risks", [])
            ),
            missing=tuple(
                _evidence_from_dict(item) for item in quality_payload.get("missing", [])
            ),
            data_asof=(
                None
                if quality_payload.get("data_asof") is None
                else str(quality_payload["data_asof"])
            ),
        ),
        entry=EntryDecision(
            state=EntryState(entry_payload["state"]),
            score=entry_payload.get("score"),
            confidence=float(entry_payload["confidence"]),
            positives=tuple(
                _evidence_from_dict(item) for item in entry_payload.get("positives", [])
            ),
            risks=tuple(
                _evidence_from_dict(item) for item in entry_payload.get("risks", [])
            ),
            market_asof=(
                None
                if entry_payload.get("market_asof") is None
                else str(entry_payload["market_asof"])
            ),
        ),
        action_state=ActionState(payload["action_state"]),
        priority=int(payload["priority"]),
        rationale=tuple(
            _evidence_from_dict(item) for item in payload.get("rationale", [])
        ),
        review_trigger=(
            None
            if payload.get("review_trigger") is None
            else str(payload["review_trigger"])
        ),
        source_lists=tuple(str(item) for item in payload.get("source_lists", [])),
        provenance=dict(payload.get("provenance", {})),
        previous_action_state=(
            None if previous_action is None else ActionState(previous_action)
        ),
        state_change_reason=(
            None
            if payload.get("state_change_reason") is None
            else str(payload["state_change_reason"])
        ),
    )


def stock_decision_to_json(decision: StockDecision, *, indent: int | None = None) -> str:
    return json.dumps(
        stock_decision_to_dict(decision),
        ensure_ascii=False,
        indent=indent,
        sort_keys=True,
        separators=None if indent is not None else (",", ":"),
    )


def stock_decision_from_json(payload: str) -> StockDecision:
    decoded = json.loads(payload)
    if not isinstance(decoded, Mapping):
        raise TypeError("StockDecision JSON must decode to an object")
    return stock_decision_from_dict(decoded)


def stock_decisions_to_jsonl(decisions: Iterable[StockDecision]) -> str:
    lines = [stock_decision_to_json(decision) for decision in decisions]
    return "\n".join(lines) + ("\n" if lines else "")


def stock_decisions_from_jsonl(payload: str) -> tuple[StockDecision, ...]:
    decisions: list[StockDecision] = []
    for line_number, raw_line in enumerate(payload.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            decisions.append(stock_decision_from_json(line))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid StockDecision JSONL line {line_number}: {exc}") from exc
    return tuple(decisions)
