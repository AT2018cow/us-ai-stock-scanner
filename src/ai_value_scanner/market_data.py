"""Explicit completed-session contract for official SIP end-of-day decisions."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import math

from .market_calendar import is_session_day, latest_completed_session, session_close_utc


def official_eod_window(now: datetime):
    if now.tzinfo is None: raise ValueError('timezone-aware clock required')
    local_day=now.astimezone(ZoneInfo('America/New_York')).date()
    session=latest_completed_session(now)
    # No official publication during a session or inside SIP's delayed window.
    if is_session_day(local_day) and now < session_close_utc(local_day)+timedelta(minutes=20):
        raise ValueError('Official SIP scan is available only 20 minutes after market close; use intraday_watch for monitoring')
    return session, (now.astimezone(timezone.utc)-timedelta(minutes=20)).isoformat()


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
