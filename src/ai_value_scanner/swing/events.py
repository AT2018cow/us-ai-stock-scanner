"""Read a versioned, issuer-bound event calendar with point-in-time revisions."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from io import StringIO
from pathlib import Path
from typing import Any

from ai_value_scanner.decision.review import issuer_cik
from ai_value_scanner.market_calendar import NYSE_TZ, session_open_utc


@dataclass(frozen=True)
class Event:
    event_id: str
    symbol: str
    cik: str
    event_type: str
    event_date: str | None
    session: str
    known_at_utc: str
    certainty: str
    source: str


def timestamp(value: str | datetime) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    if value.utcoffset() is None:
        raise ValueError("timestamp requires a timezone")
    return value.astimezone(timezone.utc)


def load_calendar(path: Path) -> tuple[dict[tuple[str, str], tuple[Event, ...]], str]:
    raw = path.read_bytes()
    reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")), strict=True)
    if not set(Event.__dataclass_fields__).issubset(reader.fieldnames or ()):
        raise ValueError("missing event calendar columns")
    grouped: dict[tuple[str, str], list[Event]] = {}
    for row in reader:
        fields = {field: (row[field] or "").strip() for field in Event.__dataclass_fields__}
        cik = issuer_cik(fields["cik"])
        if cik is None or not fields["symbol"] or not fields["event_id"] or not fields["event_type"]:
            raise ValueError(f"invalid calendar record at row {reader.line_num}")
        if fields["source"]:
            if fields["session"] not in ("premarket", "postmarket", "unknown") or fields["certainty"] not in (
                "confirmed", "estimated", "conflict", "cancelled",
            ):
                raise ValueError(f"invalid calendar record at row {reader.line_num}")
            fields["event_date"] = date.fromisoformat(fields["event_date"]).isoformat()
        else:
            # Retain the revision time, but suppress the unverified date and
            # disposition so the previous sourced row cannot remain current.
            fields.update(event_date=None, session="unknown", certainty="unknown")
        fields["known_at_utc"] = timestamp(fields["known_at_utc"]).isoformat()
        fields["symbol"] = fields["symbol"].upper()
        fields["cik"] = cik
        grouped.setdefault((fields["symbol"], cik), []).append(Event(**fields))
    return {key: tuple(items) for key, items in grouped.items()}, sha256(raw).hexdigest()


def known_events(
    calendar: dict[tuple[str, str], tuple[Event, ...]], symbol: str, cik: Any,
    *, decision_day: date, asof: datetime, unavailable: str | None = None,
) -> dict:
    rows = calendar.get((symbol, issuer_cik(cik)), ())
    revisions: dict[str, list[Event]] = {}
    for row in rows:
        if timestamp(row.known_at_utc) <= asof:
            revisions.setdefault(row.event_id, []).append(row)
    current, elapsed = [], []
    cutoff = asof.astimezone(NYSE_TZ).date()
    for event_id, batch in revisions.items():
        batch = sorted(set(batch), key=lambda event: (event.known_at_utc, event.event_date or "", event.source, event.session, event.certainty, event.event_type))
        latest = [event for event in batch if event.known_at_utc == batch[-1].known_at_utc]
        unverified = any(not event.source for event in latest)
        conflict = not unverified and len({(event.event_date, event.session, event.certainty, event.event_type) for event in latest}) > 1
        event = batch[-1]
        unknown = unverified or conflict or event.certainty == "conflict"
        if not unknown and event.certainty == "cancelled":
            continue
        item = {
            "event_id": event_id, "event_type": event.event_type,
            "event_date": None if unknown else event.event_date,
            "session": "unknown" if unknown else event.session,
            "certainty": "unknown" if unverified else "conflict" if unknown else event.certainty,
            "first_known_at_utc": batch[0].known_at_utc,
            "source": None if unknown else event.source,
            "revisions": [asdict(event) for event in batch],
        }
        event_day = date.fromisoformat(event.event_date) if not unknown else None
        if event_day and (event_day < max(cutoff, decision_day) or (
            event.session == "premarket" and asof >= session_open_utc(event_day)
        )):
            if event_day >= decision_day:
                elapsed.append(item)
        else:
            current.append(item)
    known_current = any(item["event_date"] is not None for item in current)
    return {
        "status": "available" if known_current else "unknown",
        "reason": None if known_current else ("current_revision_uncertain" if current else unavailable),
        "asof": asof.isoformat(),
        "events": sorted(current, key=lambda item: (item["event_date"] is None, item["event_date"] or "", item["event_id"])),
        **({"elapsed_events": sorted(elapsed, key=lambda item: (item["event_date"], item["event_id"]))} if elapsed else {}),
    }
