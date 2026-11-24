"""Explicit completed-session contract for official SIP end-of-day decisions."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import math

from .market_calendar import (
    is_session_day,
    latest_completed_session,
    session_close_utc,
    session_open_utc,
)

SIP_PUBLICATION_DELAY = timedelta(minutes=20)


def sip_publication_window(now: datetime) -> tuple[date, str]:
    """Expected decision session and the current publication window."""
    session = latest_completed_session(now)
    local_day = now.astimezone(ZoneInfo("America/New_York")).date()
    if is_session_day(local_day) and session_open_utc(local_day) <= now:
        close = session_close_utc(local_day)
        if now < close:
            return session, "market_open"
        if now < close + SIP_PUBLICATION_DELAY:
            return session, "awaiting_sip"
    return session, "available"


def official_eod_window(now: datetime):
    """Return (latest completed session, delayed-access request end).

    Official scans are blocked while a session is open and during SIP's
    delayed-access window (20 minutes after the close). Before the open they
    are allowed to target the latest completed session, which keeps the
    post-close run retryable after midnight without changing the decision date.
    """
    if now.tzinfo is None:
        raise ValueError('timezone-aware clock required')
    session, window = sip_publication_window(now)
    if window != "available":
        raise ValueError(
            'Official SIP scan is available before the open or at least 20 '
            'minutes after the close; use intraday_watch for monitoring'
        )
    return session, (now.astimezone(timezone.utc) - SIP_PUBLICATION_DELAY).isoformat()


def completed_bar(rows, session):
    expected=session.isoformat()
    eligible=[r for r in rows if str(r.get('t',''))[:10]<=expected]
    if not eligible:return None
    row=max(eligible,key=lambda r:str(r.get('t','')))
    if str(row.get('t',''))[:10]!=expected:return None
    try:
        price,volume=float(row['c']),float(row['v'])
        if not math.isfinite(price) or not math.isfinite(volume) or price<=0 or volume<0:return None
    except (KeyError,ValueError,TypeError):return None
    return dict(row)
